from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base, Document, User
from app.main import app
from scripts import semantic_local


def test_local_semantic_backup_verifies_sqlite_and_all_originals(tmp_path, monkeypatch):
    original = tmp_path / 'original' / 'database.sqlite'
    uploads = original.parent / 'uploads'
    uploads.mkdir(parents=True)
    stored = uploads / 'synthetic.csv'
    stored.write_bytes(b'invoice_number,total,currency\nEXAMPLE-401,50,USD\n')
    profile = tmp_path / 'semantic'
    profile.mkdir()
    monkeypatch.setattr(semantic_local, 'PROFILE', profile)
    monkeypatch.setattr(semantic_local, 'BACKUP', profile / 'backup')
    monkeypatch.setattr(semantic_local, 'SQLITE_COPY', profile / 'backup/careguide.db')
    monkeypatch.setattr(semantic_local, 'STORAGE', profile / 'uploads')
    monkeypatch.setattr(semantic_local, 'sqlite_profile', lambda: (original, uploads))
    engine = create_engine('sqlite:///' + original.as_posix())
    Base.metadata.create_all(engine)
    with Session(engine) as db, db.begin():
        owner = User(username='synthetic', password_hash='fixture', role='reviewer')
        db.add(owner)
        db.flush()
        db.add(Document(owner_id=owner.id, status='COMPLETED', filename='invoice.csv', file_type='.csv',
                        size=stored.stat().st_size, checksum=semantic_local.checksum(stored), storage_path=str(stored),
                        raw={'total': '50'}, corrected={'total': '51'}, evidence={'total': {'sheet': 'CSV', 'row': 2}}))
    engine.dispose()

    _, checksums = semantic_local.backup()
    assert checksums == {'synthetic.csv': semantic_local.checksum(stored)}
    archived = semantic_local.read_data(semantic_local.sqlite_engine(semantic_local.SQLITE_COPY))
    mapped = semantic_local.mapped_data(archived, uploads, profile / 'uploads', checksums)
    doc, = mapped['documents']
    assert Path(doc['storage_path']).parent == profile / 'uploads'
    assert doc['corrected'] == {'total': '51'} and doc['evidence']['total']['row'] == 2
    stored.write_bytes(b'changed fixture')
    with pytest.raises(semantic_local.ProfileError, match='uploads changed'):
        semantic_local.verify_source()
    assert (profile / 'backup/uploads/synthetic.csv').read_bytes().startswith(b'invoice_number,')


def test_semantic_api_authenticates_before_disabled_backend_check(client):
    payload = {'query': 'document retrieval', 'limit': 3}
    assert client.post('/api/search/semantic', json=payload).status_code == 503
    with TestClient(app) as guest:
        assert guest.post('/api/search/semantic', json=payload).status_code == 401
