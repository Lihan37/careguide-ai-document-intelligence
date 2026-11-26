from pathlib import Path
from uuid import uuid4

import pytest

from app.db import Document, Session, User
from app.security import token


@pytest.fixture
def reviewer_client(client):
    # Duplicate checks are owner-scoped. Give each case its own fixtures.
    with Session() as db:
        owner = User(username='review-status-test-' + uuid4().hex, password_hash='unused', role='reviewer')
        db.add(owner)
        db.commit()
        session = token(owner.id)
    client.cookies.clear()
    client.cookies.set('careguide_session', session)
    return client


@pytest.mark.parametrize('kind,processing,review,validation', [
    ('warning', 'REQUIRES_REVIEW', 'approved', 'WARNING'),
    ('clean', 'COMPLETED', 'approved', 'PASSED'),
    ('failed', 'REQUIRES_REVIEW', 'pending', 'FAILED'),
    ('missing', 'REQUIRES_REVIEW', 'pending', 'REQUIRES_REVIEW'),
])
def test_review_decision_keeps_processing_and_validation_independent(reviewer_client, kind, processing, review, validation):
    client = reviewer_client
    file = {'failed': 'incorrect-total.pdf', 'missing': 'missing-fields.pdf'}.get(kind, 'layout-invoice.pdf')
    blocked = review == 'pending'
    content = (Path('sample-data') / file).read_bytes()

    def upload(name):
        response = client.post('/api/documents/upload', files={'files': (name, content, 'application/pdf')})
        assert response.status_code == 202
        return response.json()['results'][0]['document_id']

    other_id = upload('original-for-duplicate-check.pdf') if kind == 'warning' else None
    filename = 'review-status-invoice.pdf'
    document_id = upload(filename)
    url = '/api/documents/' + document_id
    before = client.get(url).json()
    original_validation = client.get(url + '/validation').json()
    assert (before['status'], before['review_status'], original_validation['outcome']) == (processing, 'pending', validation)
    if kind == 'warning':
        assert [(issue['rule_id'], issue['severity'], issue['related_document_id']) for issue in before['issues']] == [
            ('exact_file_duplicate', 'WARNING', other_id),
        ]

    response = client.post(f'/api/reviews/{document_id}/resolve', json={'decision': 'approved', 'note': 'Checked the original.'})
    assert response.status_code == (409 if blocked else 200)
    if not blocked:
        assert response.json() == {'review_status': 'approved', 'issues_retained': True}

    refreshed = client.get(url).json()
    listed, = client.get('/api/documents', params={'q': filename}).json()['items']
    status = client.get(url + '/status').json()
    for summary in (refreshed, listed, status):
        assert (summary['status'], summary['review_status'], summary['issue_count']) == (processing, review, len(before['issues']))
    assert all(refreshed[key] == before[key] for key in ('raw', 'corrected', 'sources', 'evidence', 'issues', 'history'))
    assert client.get(url + '/validation').json() == original_validation
    assert client.get(url + '/source').content == content
    queue = client.get('/api/review-queue', params={'q': filename}).json()['items']
    assert [row['id'] for row in queue] == ([document_id] if blocked else [])
    decisions = [entry['detail']['decision'] for entry in refreshed['audit'] if entry['action'] == 'review_decision']
    assert decisions == ([] if blocked else ['approved'])
    with Session() as db:
        persisted = db.get(Document, document_id)
        assert (persisted.status, persisted.review_status, persisted.issues) == (processing, review, before['issues'])
        if other_id:
            assert db.get(Document, other_id).review_status == 'pending'
