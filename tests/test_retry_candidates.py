from datetime import timedelta

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Embedding, Job, Session, SourceUnit, User, now
from app.jobs import run_job
from app.main import app
from app.processing import ProcessingError
from app.schemas import Invoice
from app.security import password_hash
from scripts.generate_samples import BASE


@pytest.fixture
def financial_document(client, monkeypatch, request):
    name = 'RETRY-' + request.node.name
    raw = BASE | {'invoice_number': name}

    def extracted(source):
        return Invoice.model_validate(raw), {'invoice_number': {'page': 1, 'excerpt': name}}, [], 'llm:gemini:test', {}

    monkeypatch.setattr('app.jobs.extract', extracted)
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 70), 'Synthetic financial validation fixture ' + name + ' for processing')
        upload = client.post('/api/documents/upload', files={'files': (name + '.pdf', pdf.tobytes(), 'application/pdf')})
    assert upload.status_code == 202
    id = upload.json()['results'][0]['document_id']
    url = '/api/documents/' + id
    assert client.get(url + '/validation').json() == {'outcome': 'PASSED', 'issues': []}
    assert client.post('/api/reviews/' + id + '/resolve', json={'decision': 'approved', 'note': 'Checked verified result'}).status_code == 200
    return url, id, raw


def current(client, url):
    body = client.get(url).json()
    return {key: body[key] for key in ('raw', 'effective', 'corrected', 'evidence', 'issues', 'sources',
                                      'status', 'review_status', 'error', 'extraction_method')}


def retry(client, url):
    response = client.post(url + '/reprocess')
    assert response.status_code == 202
    return response.json()['id']


def test_incomplete_retry_stages_without_losing_approval_or_search(client, monkeypatch, financial_document):
    url, id, raw = financial_document
    with Session() as db:
        source_ids = list(db.scalars(select(SourceUnit.id).where(SourceUnit.document_id == id)))
        marker = Embedding(document_id=id, source={'page': 1}, text='Prior indexed source', model='test')
        db.add(marker)
        db.commit()
        marker_id = marker.id
    before = current(client, url)
    monkeypatch.setattr('app.jobs.extract', lambda _: (
        Invoice.model_validate({'invoice_number': raw['invoice_number']}), {}, [], 'deterministic_demo', {},
    ))
    job_id = retry(client, url)
    job = client.get('/api/jobs/' + job_id).json()
    assert (job['status'], job['candidate_status']) == ('REQUIRES_REVIEW', 'pending')
    assert current(client, url) == before
    review = client.get(f'{url}/candidates/{job_id}').json()
    assert review['current']['effective']['total'] == '220.00'
    assert review['candidate']['effective']['total'] is None
    assert review['current']['evidence'] == before['evidence']
    assert any(issue['rule_id'] == 'required_total' for issue in review['candidate']['issues'])
    with Session() as db:
        assert list(db.scalars(select(SourceUnit.id).where(SourceUnit.document_id == id))) == source_ids
        assert db.get(Embedding, marker_id) is not None


def test_failed_retry_retains_current_and_reports_error(client, monkeypatch, financial_document):
    url, _, _ = financial_document
    before = current(client, url)

    def fail(_):
        raise ProcessingError('Synthetic reader failure')

    monkeypatch.setattr('app.jobs.extract', fail)
    job_id = retry(client, url)
    job = client.get('/api/jobs/' + job_id).json()
    assert (job['status'], job['error'], job['candidate_status']) == ('FAILED', 'Synthetic reader failure', None)
    assert current(client, url) == before
    assert len(client.get(url).json()['history']) == 2


def test_equivalent_retry_keeps_original_result_and_no_snapshot(client, monkeypatch, financial_document):
    url, _, raw = financial_document
    before = current(client, url)
    monkeypatch.setattr('app.jobs.extract', lambda _: (
        Invoice.model_validate(raw | {'total': '220.0'}), {}, [], 'deterministic_demo', {},
    ))
    job_id = retry(client, url)
    assert client.get('/api/jobs/' + job_id).json()['candidate_status'] == 'equivalent'
    assert current(client, url) == before
    with Session() as db:
        assert db.get(Job, job_id).candidate is None


def test_reviewer_accepts_improvement_with_corrections_and_archive(client, monkeypatch, financial_document):
    url, id, raw = financial_document
    assert client.patch(url + '/corrections', json={
        'fields': {'supplier_name': 'Verified Synthetic Supplier'}, 'reason': 'Verified spelling',
    }).status_code == 200
    before = current(client, url)
    evidence = {'customer_name': {'page': 1, 'excerpt': 'Synthetic customer'}}
    monkeypatch.setattr('app.jobs.extract', lambda _: (
        Invoice.model_validate(raw | {'customer_name': 'Updated Synthetic Customer'}), evidence, [], 'llm:gemini:retry-test', {},
    ))
    job_id = retry(client, url)
    assert current(client, url) == before
    review = client.get(f'{url}/candidates/{job_id}').json()
    assert review['can_accept'] and review['candidate']['effective']['supplier_name'] == 'Verified Synthetic Supplier'
    assert client.post(f'{url}/candidates/{job_id}/accept', json={'reason': 'Verified new customer'}).status_code == 200
    after = current(client, url)
    assert after['effective']['customer_name'] == 'Updated Synthetic Customer'
    assert after['corrected'] == before['corrected'] and after['evidence'] == evidence
    assert after['status'] == 'COMPLETED' and after['review_status'] == 'pending'
    pdf = client.get(url + '/source')
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
    with Session() as db:
        job = db.get(Job, job_id)
        assert job.candidate_status == 'accepted'
        assert job.candidate['replaced']['raw'] == before['raw']
        assert job.candidate['replaced']['sources'] == before['sources']
    audit = client.get(url).json()['audit']
    assert any(event['action'] == 'extraction_candidate_accepted' and event['detail']['job_id'] == job_id for event in audit)
    assert client.post(f'{url}/candidates/{job_id}/accept', json={'reason': 'Duplicate acceptance'}).status_code == 409


def test_candidate_cannot_overwrite_newer_correction(client, monkeypatch, financial_document):
    url, _, raw = financial_document
    monkeypatch.setattr('app.jobs.extract', lambda _: (
        Invoice.model_validate(raw | {'customer_name': 'Retry Customer'}), {}, [], 'deterministic_demo', {},
    ))
    job_id = retry(client, url)
    assert client.patch(url + '/corrections', json={
        'fields': {'customer_name': 'Newer Review'}, 'reason': 'Verified with original',
    }).status_code == 200
    review = client.get(f'{url}/candidates/{job_id}').json()
    assert review['stale'] and review['candidate']['effective']['customer_name'] == 'Retry Customer'
    assert client.post(f'{url}/candidates/{job_id}/accept', json={'reason': 'Stale acceptance'}).status_code == 409
    assert current(client, url)['effective']['customer_name'] == 'Newer Review'


def test_progress_cancel_and_recovery_preserve_result(client, monkeypatch, financial_document):
    url, _, _ = financial_document
    before = current(client, url)
    monkeypatch.setattr('app.main.dispatch', lambda _: None)
    queued = retry(client, url)
    assert current(client, url) == before
    assert client.post(url + '/reprocess').status_code == 409
    assert client.post('/api/jobs/' + queued + '/cancel').status_code == 200
    run_job(queued)
    assert current(client, url) == before
    stale = retry(client, url)
    with Session() as db:
        db.get(Job, stale).status = 'PROCESSING'
        db.get(Job, stale).updated_at = now() - timedelta(days=1)
        db.commit()
    assert client.post('/api/jobs/recover-stale').json()['recovered'] == 1
    assert client.get('/api/jobs/' + stale).json()['status'] == 'FAILED'
    assert current(client, url) == before


def test_candidate_endpoints_require_reviewer_and_document_ownership(client, monkeypatch, financial_document):
    url, _, raw = financial_document
    monkeypatch.setattr('app.jobs.extract', lambda _: (
        Invoice.model_validate(raw | {'customer_name': 'Retry Customer'}), {}, [], 'deterministic_demo', {},
    ))
    candidate_url = url + '/candidates/' + retry(client, url)
    with Session() as db:
        for role in ('reviewer', 'viewer'):
            db.add(User(username='candidate-' + role, role=role, password_hash=password_hash('synthetic-password-042')))
        db.commit()
    for role, code in [('reviewer', 404), ('viewer', 403)]:
        with TestClient(app) as stranger:
            assert stranger.post('/api/auth/login', json={
                'username': 'candidate-' + role, 'password': 'synthetic-password-042',
            }).status_code == 200
            assert stranger.get(candidate_url).status_code == code
            assert stranger.post(candidate_url + '/accept', json={'reason': 'Try foreign result'}).status_code == code
