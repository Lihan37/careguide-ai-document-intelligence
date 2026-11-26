"""Prepare and verify an independent PostgreSQL copy of the SQLite workspace."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import file_digest
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import mkdtemp

import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'data/semantic-dev'
BACKUP = PROFILE / 'backup'
SQLITE_COPY = BACKUP / 'careguide.db'
STORAGE = PROFILE / 'uploads'
REPORT = PROFILE / 'migration-report.json'
READY_STATUSES = ('COMPLETED', 'REQUIRES_REVIEW')
ACTIVE_STATUSES = ('QUEUED', 'PROCESSING')

sys.path.insert(0, str(ROOT / 'services/api'))
from app.config import settings
from app.db import Base, Document, Embedding, Job, SourceUnit
from app.search import index_document, model_info, source_chunks


class ProfileError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ProfileError(message)


def sqlite_readonly(path):
    return sqlite3.connect(path.resolve(strict=True).as_uri() + '?mode=ro', uri=True)


def sqlite_engine(path):
    return create_engine('sqlite://', creator=lambda: sqlite_readonly(path), poolclass=NullPool)


def checksum(path):
    with path.open('rb') as handle:
        return file_digest(handle, 'sha256').hexdigest()


def inventory(root):
    files = {}
    for path in root.rglob('*'):
        require(not path.is_symlink() and not path.is_junction(), 'Upload directory contains a link or junction')
        if path.is_file():
            files[path.relative_to(root).as_posix()] = checksum(path)
    return files


def sqlite_profile():
    values = dotenv_values(ROOT / '.env', encoding='utf-8-sig', interpolate=False)
    url = make_url(values.get('DATABASE_URL') or 'sqlite:///' + (ROOT / 'data/careguide.db').as_posix())
    require(url.get_backend_name() == 'sqlite' and url.database and url.database != ':memory:',
            'The saved development .env must identify a file-backed SQLite workspace')
    sqlite = (ROOT / url.database).resolve(strict=True)
    files = (ROOT / (values.get('STORAGE_DIR') or 'data/uploads')).resolve(strict=True)
    require(not sqlite.is_relative_to(PROFILE) and not files.is_relative_to(PROFILE) and not PROFILE.is_relative_to(files),
            'The original and semantic profile must use separate paths')
    return sqlite, files


def verified_sqlite(path):
    with closing(sqlite_readonly(path)) as source:
        require(source.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'SQLite integrity check failed')
        require(not source.execute('PRAGMA foreign_key_check').fetchall(), 'SQLite has invalid foreign keys')
        placeholders = ','.join('?' for _ in ACTIVE_STATUSES)
        require(not source.execute(f'SELECT 1 FROM processing_jobs WHERE status IN ({placeholders}) LIMIT 1', ACTIVE_STATUSES).fetchone(),
                'Wait for the existing document jobs to finish before copying or switching')


def normalized(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.tolist() if hasattr(value, 'tolist') else value


def read_rows(connection, table):
    return [{key: normalized(value) for key, value in row.items()}
            for row in connection.execute(select(table).order_by(*table.primary_key.columns)).mappings()]


def read_data(engine):
    with engine.connect() as connection:
        return {table.name: read_rows(connection, table) for table in Base.metadata.sorted_tables}


def mapped_data(dataset, original_root, target_root, known_uploads):
    for document in dataset['documents']:
        path = Path(document['storage_path']).resolve(strict=True)
        require(path.is_relative_to(original_root), 'A registered original lies outside the SQLite upload directory')
        key = path.relative_to(original_root).as_posix()
        require(known_uploads.get(key) == document['checksum'], 'A registered upload is missing or failed its checksum')
        document['storage_path'] = str(target_root / key)
    return dataset


def write_json(path, contents):
    path.write_text(json.dumps(contents, indent=2) + '\n', encoding='utf-8')


def verify_source():
    original, uploads = sqlite_profile()
    verified_sqlite(original)
    verified_sqlite(SQLITE_COPY)
    require(read_data(sqlite_engine(original)) == read_data(sqlite_engine(SQLITE_COPY)),
            'SQLite rows changed after the snapshot. Keep SQLite active and retain both profiles.')
    current_files = inventory(uploads)
    require(current_files == inventory(BACKUP / 'uploads'), 'Original uploads changed after the snapshot')
    return uploads, current_files


def backup():
    if BACKUP.exists():
        return verify_source()
    source, uploads = sqlite_profile()
    verified_sqlite(source)
    staging = Path(mkdtemp(prefix='backup-', dir=PROFILE))
    copy = staging / 'careguide.db'
    with closing(sqlite_readonly(source)) as origin, closing(sqlite3.connect(copy)) as destination:
        origin.backup(destination)
    uploads_at_start = inventory(uploads)
    shutil.copytree(uploads, staging / 'uploads')
    verified_sqlite(copy)
    require(uploads_at_start == inventory(staging / 'uploads'), 'Upload backup failed checksum verification')
    mapped_data(read_data(sqlite_engine(copy)), uploads, STORAGE, uploads_at_start)
    staging.rename(BACKUP)
    return verify_source()


def copy_database(target, dataset):
    with target.begin() as destination:
        # Avoid overwriting either an existing import or a database with new edits.
        for table in Base.metadata.sorted_tables:
            existing = read_rows(destination, table)
            expected = dataset[table.name]
            require(not existing or existing == expected, 'PostgreSQL already contains different data')
            if not existing and expected:
                destination.execute(table.insert(), expected)
        for table in Base.metadata.sorted_tables:
            require(read_rows(destination, table) == dataset[table.name], f'Row verification failed for {table.name}')
        require(not destination.scalar(text("SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated")),
                'PostgreSQL contains unvalidated foreign keys')
        # The deferred comparison document IDs are stored in JSON, outside FK constraints.
        owners = {doc['id']: doc['owner_id'] for doc in dataset['documents']}
        for row in dataset['document_comparisons']:
            require(all(owners.get(doc_id) == row['owner_id'] for doc_id in row['document_ids']),
                    'Comparison references a missing document or a different owner')


def index_saved_documents(target):
    cfg = settings()
    model, dimensions = model_info(cfg)
    indexed = 0
    with Session(target) as db, db.begin():
        documents = db.scalars(select(Document).where(Document.status.in_(READY_STATUSES)).order_by(Document.id))
        for document in documents:
            source = [row | {'document_id': document.id} for row in db.scalars(
                select(SourceUnit.data).where(SourceUnit.document_id == document.id).order_by(SourceUnit.position)
            )]
            chunks = list(source_chunks(source))
            if not chunks:
                continue
            index_document(db, document, source)
            rows = db.execute(select(Embedding.text, Embedding.source, func.vector_dims(Embedding.vector)).where(
                Embedding.document_id == document.id, Embedding.model == model)).all()
            actual = sorted((value, json.dumps(location, sort_keys=True), dims) for value, location, dims in rows)
            expected = sorted((value, json.dumps(location, sort_keys=True), dimensions) for value, location in chunks)
            require(actual == expected, 'Stored vectors did not match their source chunks and configured dimensions')
            indexed += 1
        count = db.scalar(select(func.count()).select_from(Embedding).where(Embedding.model == model))
    return {'model': model, 'dimensions': dimensions, 'indexed_documents': indexed, 'chunks': count}


def target_engine():
    cfg = settings()
    url = make_url(cfg.database_url)
    require(cfg.app_env == 'development' and url.get_backend_name() == 'postgresql'
            and url.host == '127.0.0.1' and url.port == 55432 and url.database == 'careguide_semantic'
            and Path(cfg.storage_dir).resolve() == STORAGE and cfg.embedding_provider == 'local' and cfg.embeddings_enabled,
            'Initialize requires the dedicated loopback semantic profile')
    return create_engine(cfg.database_url, hide_parameters=True)


def verify_target():
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    target = target_engine()
    try:
        with target.connect() as connection:
            actual = connection.scalar(text('SELECT system_identifier::text FROM pg_control_system()'))
            require(actual == report['cluster_id'], 'PostgreSQL volume differs from the initialized semantic profile')
            require(connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")),
                    'pgvector is unavailable in this database')
    finally:
        target.dispose()


def verify_api_idle(port):
    cfg = settings()
    with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=6, trust_env=False) as client:
        client.post('/api/auth/login', json={'username': cfg.demo_username, 'password': cfg.demo_password}).raise_for_status()
        response = client.get('/api/settings')
        response.raise_for_status()
        database = response.json()['database']
    if database == 'sqlite':
        original, _ = sqlite_profile()
        verified_sqlite(original)
        return
    require(database == 'postgresql', 'Could not identify the active API database')
    target = target_engine()
    try:
        with target.connect() as connection:
            active = connection.scalar(select(Job.id).where(Job.status.in_(ACTIVE_STATUSES)).limit(1))
            require(active is None, 'Wait for active PostgreSQL jobs before stopping the API')
    finally:
        target.dispose()


def initialize():
    if REPORT.exists():
        verify_target()
        print('Semantic profile is already initialized. Use Start to run it.')
        return
    original_uploads, verified_uploads = backup()
    if not STORAGE.exists() or not any(STORAGE.iterdir()):
        shutil.copytree(BACKUP / 'uploads', STORAGE, dirs_exist_ok=True)
    require(inventory(STORAGE) == verified_uploads, 'PostgreSQL upload copy differs from the verified backup')
    dataset = mapped_data(read_data(sqlite_engine(SQLITE_COPY)), original_uploads, STORAGE, verified_uploads)
    target = target_engine()
    try:
        copy_database(target, dataset)
        vectors = index_saved_documents(target)
        require(vectors['chunks'] > 0 or not any(row['text'].strip() and row['status'] in READY_STATUSES
                                              for row in dataset['documents']), 'Readable documents have no indexed chunks')
        with target.connect() as connection:
            version = connection.scalar(text('SHOW server_version'))
            extension = connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
            cluster_id = connection.scalar(text('SELECT system_identifier::text FROM pg_control_system()'))
            indexes = list(connection.scalars(text("SELECT indexname FROM pg_indexes WHERE schemaname='public' "
                                                   "AND tablename IN ('documents','document_embeddings') ORDER BY indexname")))
            require({'ix_documents_owner_id', 'ix_document_embeddings_model_document'} <= set(indexes),
                    'Semantic lookup indexes are missing')
        copied = read_data(target)
        require(all(rows == copied[table] for table, rows in dataset.items() if table != 'document_embeddings'),
                'Indexing changed imported records')
        verify_source()
        report = {'copied_rows': {name: len(rows) for name, rows in dataset.items()}, 'verified_uploads': len(verified_uploads),
                  'postgres': version, 'pgvector': extension, 'cluster_id': cluster_id, 'indexes': indexes, 'embeddings': vectors,
                  'verified_foreign_keys': True, 'original_sqlite_and_uploads_verified': True}
        write_json(REPORT, report)
        print(json.dumps(report, indent=2))
    finally:
        target.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('backup', 'initialize', 'verify-source', 'verify-target', 'verify-idle'))
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    try:
        if args.action == 'backup':
            _, files = backup()
            print(f'Verified SQLite backup and {len(files)} original uploads.')
        elif args.action == 'initialize':
            initialize()
        elif args.action == 'verify-source':
            verify_source()
            print('SQLite records and upload checksums match the verified backup.')
        elif args.action == 'verify-target':
            verify_target()
            print('Initialized PostgreSQL profile and pgvector verified.')
        else:
            verify_api_idle(args.port)
            print('No active processing jobs.')
    except Exception as exc:
        if isinstance(exc, ProfileError):
            print(f'Semantic workspace setup stopped: {exc}', file=sys.stderr)
        else:
            print(f'Semantic workspace setup stopped ({type(exc).__name__}). Check local service configuration.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
