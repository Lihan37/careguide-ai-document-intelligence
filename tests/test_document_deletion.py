from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import Audit, Comparison, Document, Embedding, Job, Session, SourceUnit, User
from app.jobs import run_job
from app.main import app
from app.security import token


FIXTURES = Path('sample-data')


@pytest.fixture(autouse=True)
def isolated_owner(client):
    # Shared suite database, independent owner for fixtures and comparisons.
    with Session() as db:
        owner = User(username='deletion-test-' + uuid4().hex, password_hash='unused', role='reviewer')
        db.add(owner)
        db.commit()
        session = token(owner.id)
    client.cookies.clear()
    client.cookies.set('careguide_session', session)


def upload(client, name='layout-invoice.pdf', *, filename=None):
    response = client.post('/api/documents/upload', files={'files': (filename or name, (FIXTURES / name).read_bytes())})
    assert response.status_code == 202
    return response.json()['results'][0]


def endpoint(document):
    return f'/api/documents/{document["document_id"]}'


def remove(client, document, comparisons=()):
    return client.request('DELETE', endpoint(document), json={'comparison_ids': list(comparisons)})


def original(document):
    with Session() as db:
        return Path(db.get(Document, document['document_id']).storage_path)


def add_embedding(document):
    with Session() as db:
        db.add(Embedding(document_id=document['document_id'], model='synthetic-vector', text='Synthetic quote',
                         source={'page': 1}, vector=[0.0] * 1536))
        db.commit()


def test_delete_removes_only_target_records_and_supports_reupload(client):
    target = upload(client, 'invoice.csv', filename='temporary-walkthrough.csv')
    retained = upload(client, 'accounting.xlsx')
    path = original(target)
    content = path.read_bytes()
    assert path.exists() and path.parent == Path(settings().storage_dir)
    assert client.patch(endpoint(target) + '/corrections', json={
        'fields': {'supplier_name': 'Temporary Review Name'}, 'reason': 'Synthetic correction',
    }).status_code == 200
    add_embedding(target)
    add_embedding(retained)
    before = client.get(endpoint(retained)).json()
    preview = client.get(endpoint(target) + '/deletion')
    assert preview.json() == {'filename': 'temporary-walkthrough.csv', 'comparison_ids': [],
                              'active_processing': False, 'blocked': False}
    dashboard = client.get('/api/dashboard').json()['total']
    deleted = remove(client, target)
    assert deleted.json() == {'deleted': True, 'comparisons_deleted': 0, 'original': 'removed', 'warning': None}
    assert client.get(endpoint(target)).status_code == 404
    assert remove(client, target).status_code == 404
    assert client.get(endpoint(target) + '/source').status_code == 404
    assert client.get('/api/jobs/' + target['job_id']).status_code == 404
    assert client.get('/api/search', params={'q': 'temporary-walkthrough.csv'}).json()['total'] == 0
    assert all(row['id'] != target['document_id'] for row in client.get('/api/review-queue').json()['items'])
    assert client.get('/api/dashboard').json()['total'] == dashboard - 1
    assert not path.exists()
    assert client.get(endpoint(retained)).json() == before and original(retained).exists()
    with Session() as db:
        assert db.get(Document, target['document_id']) is None
        for model in (SourceUnit, Embedding, Job, Audit):
            assert db.scalar(select(func.count()).select_from(model).where(model.document_id == target['document_id'])) == 0
        assert db.scalar(select(Embedding.id).where(Embedding.document_id == retained['document_id']))
    replacement = upload(client, 'invoice.csv', filename='temporary-walkthrough.csv')
    assert replacement['document_id'] != target['document_id'] and original(replacement).read_bytes() == content


def test_deletion_requires_reviewer_role_and_ownership(client):
    target = upload(client)
    with Session() as db:
        visitor = User(username='deletion-foreign-admin', password_hash='unused', role='admin')
        viewer = User(username='deletion-read-only-owner', password_hash='unused', role='viewer')
        db.add_all([visitor, viewer])
        db.commit()
        foreign_token, viewer_token = token(visitor.id), token(viewer.id)
        own_read_only_document = db.get(Document, target['document_id'])
        with TestClient(app) as guest:
            assert guest.get(endpoint(target) + '/deletion').status_code == 401
            assert remove(guest, target).status_code == 401
            guest.cookies.set('careguide_session', foreign_token)
            assert guest.get(endpoint(target) + '/deletion').status_code == 404
            assert remove(guest, target).status_code == 404
            own_read_only_document.owner_id = viewer.id
            db.commit()
            guest.cookies.set('careguide_session', viewer_token)
            assert guest.get(endpoint(target)).status_code == 200
            assert guest.get(endpoint(target) + '/deletion').status_code == 403
            assert remove(guest, target).status_code == 403
    assert original(target).exists()


def test_comparison_dependencies_require_exact_confirmation(client):
    target = upload(client)
    baseline = upload(client, 'accounting.xlsx')
    retained = upload(client, 'tax-layout-invoice.pdf')

    def compare(first, second):
        response = client.post('/api/comparisons', json={'document_ids': [first['document_id'], second['document_id']]})
        assert response.status_code == 201
        return response.json()['id']

    unrelated_id = compare(retained, baseline)
    target_comparison = compare(baseline, target)
    preview = client.get(endpoint(target) + '/deletion').json()
    assert preview['comparison_ids'] == [target_comparison]
    assert remove(client, target).status_code == 409
    assert remove(client, target, [target_comparison, unrelated_id]).status_code == 409
    new_dependency = compare(target, retained)
    assert remove(client, target, preview['comparison_ids']).status_code == 409
    baseline_before = client.get(endpoint(baseline)).json()
    unrelated_before = client.get('/api/comparisons/' + unrelated_id).json()
    result = remove(client, target, [target_comparison, new_dependency])
    assert result.status_code == 200 and result.json()['comparisons_deleted'] == 2
    assert client.get('/api/comparisons/' + target_comparison).status_code == 404
    assert client.get('/api/comparisons/' + new_dependency).status_code == 404
    assert client.get(endpoint(baseline)).json() == baseline_before
    assert client.get('/api/comparisons/' + unrelated_id).json() == unrelated_before


def test_foreign_comparison_record_blocks_deletion(client):
    target = upload(client)
    with Session() as db:
        other = User(username='deletion-legacy-comparison-owner', password_hash='unused', role='reviewer')
        db.add(other)
        db.flush()
        comparison = Comparison(owner_id=other.id, document_ids=[target['document_id']], results=[])
        db.add(comparison)
        db.commit()
        identifier = comparison.id
    preview = client.get(endpoint(target) + '/deletion').json()
    assert preview['blocked'] and not preview['comparison_ids']
    assert remove(client, target, [identifier]).status_code == 409
    with Session() as db:
        assert db.get(Comparison, identifier)
    assert original(target).exists()


def test_processing_and_cancelling_both_block_deletion_until_reader_closes(client, monkeypatch):
    monkeypatch.setattr('app.main.dispatch', lambda _: None)
    target = upload(client)
    path = original(target)
    assert client.get(endpoint(target) + '/deletion').json()['active_processing']
    assert remove(client, target).status_code == 409
    reading, resume, closed = Event(), Event(), Event()

    def reader(path, _):
        try:
            with path.open('rb'):
                reading.set()
                assert resume.wait(10)
                yield {'page': 1, 'total': 1, 'text': 'Synthetic document', 'method': 'digital_pdf'}
        finally:
            closed.set()

    monkeypatch.setattr('app.jobs.units', reader)
    with ThreadPoolExecutor() as executor:
        processed = executor.submit(run_job, target['job_id'])
        try:
            assert reading.wait(10)
            assert remove(client, target).status_code == 409
            response = client.post('/api/jobs/' + target['job_id'] + '/cancel')
            assert response.json()['status'] == 'CANCELLING'
            assert client.get(endpoint(target) + '/deletion').json()['active_processing']
            assert remove(client, target).status_code == 409
            assert client.post(endpoint(target) + '/reprocess').status_code == 409
            assert path.exists() and not closed.is_set()
        finally:
            resume.set()
        processed.result(timeout=10)
    assert closed.is_set()
    assert client.get('/api/jobs/' + target['job_id']).json()['status'] == 'CANCELLED'
    assert not client.get(endpoint(target) + '/deletion').json()['active_processing']
    assert remove(client, target).json()['original'] == 'removed'


def test_queued_cancel_and_late_delivery_are_safe(client, monkeypatch):
    monkeypatch.setattr('app.main.dispatch', lambda _: None)
    target = upload(client)
    assert client.post('/api/jobs/' + target['job_id'] + '/cancel').json()['status'] == 'CANCELLED'
    assert remove(client, target).json()['original'] == 'removed'
    run_job(target['job_id'])
    assert client.get(endpoint(target)).status_code == 404


def test_terminal_stale_job_does_not_override_worker_activity_marker(client):
    target = upload(client)
    with Session() as db:
        job = db.get(Job, target['job_id'])
        job.status, job.worker_active = 'FAILED', True
        db.commit()
    assert client.get(endpoint(target) + '/deletion').json()['active_processing']
    assert remove(client, target).status_code == 409
    assert original(target).exists()
    with Session() as db:
        db.get(Job, target['job_id']).worker_active = False
        db.commit()


def test_original_still_referenced_by_other_owner_is_retained(client):
    first = upload(client)
    second = upload(client)
    path = original(first)
    with Session() as db:
        other = User(username='deletion-shared-original-owner', password_hash='unused', role='reviewer')
        db.add(other)
        db.flush()
        shared = db.get(Document, second['document_id'])
        shared.storage_path, shared.owner_id = str(path), other.id
        db.commit()
    result = remove(client, first).json()
    assert result['original'] == 'shared' and result['warning']
    assert path.exists() and client.get(endpoint(second)).status_code == 404
    with Session() as db:
        assert db.get(Document, second['document_id']).storage_path == str(path)


def test_delete_rolls_back_all_related_records_if_database_commit_fails(client, monkeypatch):
    target = upload(client)
    retained = upload(client, 'accounting.xlsx')
    add_embedding(target)
    comparison = client.post('/api/comparisons', json={'document_ids': [target['document_id'], retained['document_id']]}).json()['id']
    before = client.get(endpoint(target)).json()
    path = original(target)

    def fail_commit(session):
        session.flush()
        raise SQLAlchemyError('Synthetic transaction failure')

    with monkeypatch.context() as fault:
        fault.setattr(Session.class_, 'commit', fail_commit)
        assert remove(client, target, [comparison]).status_code == 500
    assert path.exists()
    assert client.get(endpoint(target)).json() == before
    assert client.get('/api/comparisons/' + comparison).status_code == 200
    with Session() as db:
        assert db.scalar(select(Embedding.id).where(Embedding.document_id == target['document_id']))


def test_original_cleanup_error_is_reported_after_successful_database_removal(client, monkeypatch):
    target = upload(client)
    path = original(target)
    unlink = Path.unlink

    def fail_unlink(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError('Synthetic locked original')
        return unlink(candidate, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, 'unlink', fail_unlink)
        result = remove(client, target)
    assert result.status_code == 200 and result.json()['original'] == 'retained'
    assert result.json()['warning'] == 'The database deletion succeeded, but the original file could not be cleaned up.'
    assert client.get(endpoint(target)).status_code == 404 and path.exists()


def test_cleanup_cannot_unlink_an_original_outside_private_storage(client):
    target = upload(client)
    fixture = (FIXTURES / 'layout-invoice.pdf').resolve()
    content = fixture.read_bytes()
    with Session() as db:
        db.get(Document, target['document_id']).storage_path = str(fixture)
        db.commit()
    result = remove(client, target).json()
    assert result['original'] == 'retained' and result['warning']
    assert fixture.read_bytes() == content
