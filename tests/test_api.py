from pathlib import Path
import pymupdf
from fastapi.testclient import TestClient
from app.main import app
from app.db import Session, Document, Job, User
from app.jobs import run_job
from app.security import password_hash


def upload(client, name='invoice.pdf'):
    response = client.post('/api/documents/upload', files=[('files', (name, (Path('sample-data') / name).read_bytes()))])
    assert response.status_code == 202
    return response.json()['results'][0]['document_id']


def test_auth_and_owner_authorization(client):
    id = upload(client)
    with TestClient(app) as stranger:
        assert stranger.get('/api/documents').status_code == 401
        assert stranger.get(f'/api/documents/{id}/source').status_code == 401
        with Session() as db:
            db.add(User(username='other', password_hash=password_hash('other-password-123'), role='viewer'))
            db.commit()
        assert stranger.post('/api/auth/login', json={'username': 'other', 'password': 'other-password-123'}).status_code == 200
        assert stranger.get(f'/api/documents/{id}').status_code == 404
        assert stranger.patch(f'/api/documents/{id}/corrections', json={'fields': {}, 'reason': 'test'}).status_code == 403


def test_upload_validation(client):
    response = client.post('/api/documents/upload', files=[('files', ('attack.exe', b'MZ')), ('files', ('fake.pdf', b'hello'))])
    assert all('error' in result for result in response.json()['results'])


def test_correction_review_search_and_audit(client):
    id = upload(client, 'incorrect-total.pdf')
    before = client.get(f'/api/documents/{id}').json()
    assert before['status'] == 'REQUIRES_REVIEW'
    assert client.post(f'/api/reviews/{id}/resolve', json={'decision': 'approved', 'note': 'checked'}).status_code == 409
    response = client.patch(f'/api/documents/{id}/corrections', json={'fields': {'total': '220.00'}, 'reason': 'Corrected arithmetic using source'} )
    assert response.status_code == 200
    after = client.get(f'/api/documents/{id}').json()
    assert after['raw']['total'] == '250.00'
    assert after['corrected']['total'] == '220.00'
    assert any(a['action'] == 'correction' for a in after['audit'])
    assert client.post(f'/api/reviews/{id}/resolve', json={'decision': 'approved', 'note': 'Reviewed original source'}).status_code == 200
    assert client.get('/api/search', params={'q': 'CG-2026-002'}).json()['total'] >= 1
    assert client.get(f'/api/documents/{id}/source?page=1').headers['content-type'] == 'image/png'


def test_signed_discount_correction_and_comparison(client):
    def upload_discount_fixture(invoice_number):
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40, 50), '\n'.join([
                'Invoice Number: ' + invoice_number, 'Invoice Date: 2026-11-26',
                'Supplier: Synthetic Discount Supplier', 'Customer: Synthetic Buyer', 'Currency: USD',
                'Description | Qty | Unit Price | Amount', 'Inspection | 2 | 100.00 | 200.00',
                'Subtotal: USD 200.00', 'Discount: USD 10.00', 'Tax: USD 20.00', 'Total: USD 210.00',
            ]))
            response = client.post('/api/documents/upload', files={'files': (invoice_number + '.pdf', pdf.tobytes(), 'application/pdf')})
        assert response.status_code == 202
        return response.json()['results'][0]['document_id']

    first = upload_discount_fixture('DISCOUNT-REG-A')
    second = upload_discount_fixture('DISCOUNT-REG-B')
    before = client.get(f'/api/documents/{first}/extraction').json()
    changed = client.patch(f'/api/documents/{first}/corrections', json={
        'fields': {'discount': '-10.00'}, 'reason': 'Verify signed discount handling',
    })
    assert changed.status_code == 200
    refreshed = client.get(f'/api/documents/{first}/validation').json()
    assert refreshed == {'outcome': 'PASSED', 'issues': []}
    after = client.get(f'/api/documents/{first}/extraction').json()
    assert after['effective']['discount'] == '-10.00'
    assert after['original'] == before['original'] and after['evidence'] == before['evidence']
    comparison = client.post('/api/comparisons', json={'document_ids': [first, second]})
    assert comparison.status_code == 201
    discount = next(f for f in comparison.json()['results'][0]['fields'] if f['field'] == 'discount')
    assert (discount['left'], discount['right'], discount['status']) == ('-10.00', '10.00', 'MATCHED')


def test_failure_retry_idempotency(client):
    id = upload(client, 'corrupted.pdf')
    assert client.get(f'/api/documents/{id}').json()['status'] == 'FAILED'
    response = client.post(f'/api/documents/{id}/reprocess')
    assert response.status_code == 202
    job = client.get('/api/jobs/' + response.json()['id']).json()
    assert job['status'] == 'FAILED' and job['retries'] == 1
    run_job(job['id'])
    assert client.get('/api/jobs/' + job['id']).json()['status'] == 'FAILED'


def test_actual_document_comparisons(client):
    pdf = upload(client)
    other = upload(client, 'incorrect-total.pdf')
    excel = upload(client, 'accounting.xlsx')
    for right in [other, excel]:
        response = client.post('/api/comparisons', json={'document_ids': [pdf, right]})
        assert response.status_code == 201
        fields = response.json()['results'][0]['fields']
        assert next(f for f in fields if f['field'] == 'total')['status'] == 'MISMATCHED'
        assert client.get('/api/comparisons/' + response.json()['id']).status_code == 200


def test_semantic_disabled(client):
    response = client.post('/api/search/semantic', json={'query': 'office supplies'})
    assert response.status_code == 503


def test_csrf_origin(client):
    assert client.post('/api/auth/logout', headers={'Origin': 'https://evil.example'}).status_code == 403
