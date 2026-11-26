import io
import json
from decimal import Decimal
from pathlib import Path

from PIL import Image
import pymupdf
import pytest

from app.config import settings
from app.extraction import demo_extract
from app.processing import ProcessingError, ocr_available, units
from app.validation import validate

FIXTURES = Path('sample-data/ocr')
TRUTH = json.loads((FIXTURES / 'ground-truth.json').read_text(encoding='utf-8'))


@pytest.fixture
def require_ocr():
    if not ocr_available():
        pytest.skip('Configured Tesseract executable or language is unavailable')


@pytest.mark.parametrize('filename', [name for name, methods in TRUTH['files'].items() if methods])
def test_invoice_from_real_scan(require_ocr, filename):
    path = FIXTURES / filename
    expected_methods = TRUTH['files'][filename]
    if path.suffix == '.pdf':
        with pymupdf.open(path) as source:
            for page, method in zip(source, expected_methods, strict=True):
                if method == 'tesseract_ocr':
                    assert page.get_images()
                    assert '176.00' not in page.get_text()
                    assert not page.get_text().strip() or filename == 'mixed.pdf'

    pages = list(units(path, path.suffix))
    assert [page['page'] for page in pages] == list(range(1, len(expected_methods) + 1))
    assert [page['method'] for page in pages] == expected_methods
    for page in pages:
        if page['method'] == 'tesseract_ocr':
            assert 0 < page['ocr_confidence'] <= 1
            assert page['ocr_seconds'] > 0
            assert page['words']
    invoice, evidence, issues = demo_extract(pages)
    for field, expected in TRUTH['header'].items():
        assert str(getattr(invoice, field)) == expected
    assert invoice.subtotal + invoice.tax == invoice.total == Decimal('176.00')
    assert evidence['total']['page'] == len(pages)
    assert evidence['total']['method'] == 'tesseract_ocr'
    assert evidence['total']['ocr_confidence'] > 0
    if filename == 'low-quality.jpg':
        # Poor scans may lose one or both lines. Assert only facts supported by
        # the recognized output and let financial checks report any discrepancy.
        assert any('176.00' in page['text'] for page in pages)
        assert invoice.shipping is None
    else:
        assert [str(item.line_amount) for item in invoice.line_items] == TRUTH['line_amounts']
        assert not (issues + validate(invoice))
        assert evidence['line_items']['items'][-1]['description']['page'] == len(pages)


def upload(client, filename, data):
    response = client.post('/api/documents/upload', files=[('files', (filename, data))])
    return response.json()['results'][0]


def test_corrupt_image_job_failure_and_unrelated_upload(client, require_ocr):
    result = upload(client, 'bad.png', (FIXTURES / 'corrupt.png').read_bytes())
    status = client.get(f'/api/documents/{result["document_id"]}/status').json()
    assert status['status'] == 'FAILED'
    assert status['error'] == 'Corrupt, oversized, or unsupported image.'
    good = upload(client, 'good.png', (FIXTURES / 'clear.png').read_bytes())
    status = client.get(f'/api/documents/{good["document_id"]}/status').json()
    assert status['status'] in {'COMPLETED', 'REQUIRES_REVIEW'}
    assert status['job']['progress'] == 100


def test_unsupported_and_renamed_image_rejected(client, tmp_path):
    image = tmp_path / 'renamed.png'
    Image.new('L', (10, 10)).save(image, format='BMP')
    with pytest.raises(ProcessingError, match='unsupported image'):
        list(units(image, '.png'))
    with pytest.raises(ProcessingError, match='Unsupported document format'):
        list(units(image, '.bmp'))
    result = upload(client, 'upload.bmp', image.read_bytes())
    assert 'extension' in result['error']


def test_missing_language_fails_job_and_retry_uses_real_ocr(client, require_ocr, monkeypatch):
    cfg = settings()
    language = cfg.ocr_language
    monkeypatch.setattr(cfg, 'ocr_language', 'nonexistentmodel')
    result = upload(client, 'retry.jpg', (FIXTURES / 'clear.jpg').read_bytes())
    document_id = result['document_id']
    status = client.get(f'/api/documents/{document_id}/status').json()
    assert status['status'] == 'FAILED' and 'configured language is unavailable' in status['error']
    monkeypatch.setattr(cfg, 'ocr_language', language)
    retry = client.post(f'/api/documents/{document_id}/reprocess')
    assert retry.status_code == 202
    status = client.get(f'/api/documents/{document_id}/status').json()
    assert status['status'] in {'COMPLETED', 'REQUIRES_REVIEW'} and status['error'] is None
    assert status['job']['retries'] == 1 and status['job']['pages_processed'] == 1
    record = client.get(f'/api/documents/{document_id}/extraction').json()
    assert record['original']['total'] == '176.00'


def test_blank_scan_retains_null_fields_for_review(client, require_ocr):
    with io.BytesIO() as data:
        Image.new('L', (700, 950), 255).save(data, format='PNG')
        result = upload(client, 'blank.png', data.getvalue())
    record = client.get(f'/api/documents/{result["document_id"]}').json()
    assert record['status'] == 'REQUIRES_REVIEW'
    assert record['raw']['total'] is None
    assert record['sources'][0]['text'] == ''
    assert record['sources'][0]['ocr_confidence'] is None
    assert any(issue['rule_id'] == 'ocr_review' and issue['page'] == 1 for issue in record['issues'])


def test_ocr_warning_and_manual_correction(client, require_ocr, monkeypatch):
    monkeypatch.setattr(settings(), 'ocr_review_threshold', 1)
    result = upload(client, 'review.png', (FIXTURES / 'clear.png').read_bytes())
    url = f'/api/documents/{result["document_id"]}'
    record = client.get(url).json()
    assert record['status'] == 'REQUIRES_REVIEW'
    assert any(issue['rule_id'] == 'ocr_review' for issue in record['issues'])
    assert record['sources'][0]['ocr_language'] == settings().ocr_language
    assert '176.00' in record['sources'][0]['text']
    correction = client.patch(url + '/corrections', json={'fields': {'invoice_number': 'SCAN-2048-CHECKED'}, 'reason': 'Reviewed scan against original'})
    assert correction.status_code == 200
    revised = client.get(url).json()
    assert revised['effective']['invoice_number'] == 'SCAN-2048-CHECKED'
    assert revised['raw']['invoice_number'] == 'SCAN-2048'
    assert revised['sources'] == record['sources']
    assert any(issue['rule_id'] == 'ocr_review' for issue in revised['issues'])
