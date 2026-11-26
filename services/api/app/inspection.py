"""Read-only inventory and conservative automation provenance classification."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from .config import PROJECT_ROOT


@contextmanager
def readonly_database(database_url):
    url = make_url(database_url)
    if url.get_backend_name() == 'sqlite':
        path = Path(url.database).resolve()
        if not path.is_file():
            raise ValueError('Database does not exist; inspection never creates one')
        engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(path.as_uri() + '?mode=ro', uri=True))
    else:
        engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA query_only=ON' if url.get_backend_name() == 'sqlite' else 'SET TRANSACTION READ ONLY')
            yield connection
    finally:
        engine.dispose()


def json_value(value):
    return json.loads(value) if isinstance(value, str) else value


def automation_proof(document, audits, cfg):
    if cfg.app_env not in {'test', 'evaluation'}:
        return False
    for audit in audits:
        detail = json_value(audit['detail']) or {}
        if audit['action'] != 'uploaded' or detail.get('environment') != cfg.app_env or detail.get('run_id') != cfg.automation_run_id or detail.get('automation_kind') != cfg.automation_kind:
            continue
        try:
            uuid.UUID(detail['run_id'])
            from scripts.runtime_env import verify_owned_directory
            root = verify_owned_directory(cfg.runtime_root, cfg.automation_run_id, cfg.app_env, cfg.automation_kind)
            path = Path(document['storage_path']).resolve()
            if path.is_relative_to(root) and path != root:
                return True
        except (OSError, ValueError):
            pass
    return False


def inventory(connection, cfg):
    documents = connection.execute(text('SELECT * FROM documents ORDER BY uploaded_at, id')).mappings().all()
    audits = connection.execute(text('SELECT document_id, action, detail FROM audit_logs')).mappings().all()
    fixture_hashes = {}
    for fixture in (PROJECT_ROOT / 'sample-data').iterdir():
        if fixture.is_file() and fixture.suffix in {'.pdf', '.xlsx', '.xls', '.csv', '.png', '.jpg', '.tiff'}:
            fixture_hashes.setdefault(hashlib.sha256(fixture.read_bytes()).hexdigest(), []).append(fixture.name)
    result = []
    for document in documents:
        events = [event for event in audits if event['document_id'] == document['id']]
        proof = automation_proof(document, events, cfg)
        notes = json.dumps([json_value(event['detail']) for event in events], ensure_ascii=False).casefold()
        matches = fixture_hashes.get(document['checksum'], [])
        if proof:
            likely = cfg.automation_kind + ' (explicit environment/run provenance)'
            belongs = 'confirmed automation-owned'
        elif 'browser test:' in notes:
            likely = 'Likely historical Playwright run: browser-test correction/review note'
            belongs = 'likely; no original run provenance, not cleanup eligible'
        elif matches:
            likely = 'Fixture checksum match; historical Playwright or manual upload are indistinguishable'
            belongs = 'unknown; filename/checksum alone are not proof'
        else:
            likely = 'Manual upload or unknown source; preserve'
            belongs = 'not proven; preserve'
        result.append({'filename': document['filename'], 'document_id': document['id'], 'uploaded_at': str(document['uploaded_at']), 'status': document['status'], 'likely_source': likely, 'test_or_evaluation_run': belongs, 'cleanup_eligible': proof, 'matching_fixture_names': matches, 'original_exists': Path(document['storage_path']).is_file()})
    return result


def logical_snapshot(connection):
    tables = ['users', 'documents', 'source_units', 'processing_jobs', 'audit_logs', 'document_comparisons', 'document_embeddings', 'alembic_version']
    hashes = {}
    for table in tables:
        rows = [dict(row) for row in connection.execute(text('SELECT * FROM ' + table)).mappings()]
        hashes[table] = hashlib.sha256(json.dumps(sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, default=str)), sort_keys=True, default=str).encode()).hexdigest()
    documents = connection.execute(text('SELECT id, filename, uploaded_at, status, storage_path, checksum FROM documents ORDER BY uploaded_at')).mappings().all()
    files = {row['id']: {'path': row['storage_path'], 'exists': Path(row['storage_path']).is_file(), 'sha256': hashlib.sha256(Path(row['storage_path']).read_bytes()).hexdigest() if Path(row['storage_path']).is_file() else None} for row in documents}
    return {'table_hashes': hashes, 'documents': [dict(row) for row in documents], 'files': files}
