from pathlib import Path
import pytest
from PIL import Image
from app.processing import units, signature, preprocess, ocr_available, ProcessingError
from app.extraction import demo_extract

DATA = Path('sample-data')


def test_digital_pdf_provenance():
    result = list(units(DATA / 'invoice.pdf', '.pdf'))
    assert result[0]['page'] == 1 and result[0]['blocks']
    invoice, evidence, _ = demo_extract(result)
    assert invoice.invoice_number == 'CG-2026-001'
    assert str(invoice.total) == '220.00'
    assert evidence['invoice_number']['page'] == 1


@pytest.mark.parametrize('filename', ['accounting.xlsx', 'accounting.xls', 'invoice.csv'])
def test_spreadsheets(filename):
    result = list(units(DATA / filename, Path(filename).suffix))
    invoice, evidence, _ = demo_extract(result)
    assert invoice.supplier_name == 'Synthetic Northstar Supplies'
    assert evidence['total']['row'] == 2
    assert evidence['total']['column'] > 0
    if filename.endswith('xlsx'):
        assert len(result) == 2


def test_multi_page():
    assert [u['page'] for u in units(DATA / 'multipage.pdf', '.pdf')] == [1, 2, 3]


def test_corrupt():
    with pytest.raises(Exception):
        list(units(DATA / 'corrupted.pdf', '.pdf'))


def test_signature_mismatch():
    with pytest.raises(ProcessingError):
        signature(DATA / 'invoice.csv', '.pdf')


def test_preprocess():
    with Image.open(DATA / 'low-quality.png') as image:
        processed = preprocess(image)
        assert processed.mode == 'L' and processed.size == image.size


@pytest.mark.parametrize('filename', ['invoice.png', 'invoice.jpg', 'multiframe.tiff', 'scanned.pdf'])
def test_real_ocr(filename):
    if not ocr_available():
        pytest.skip('Tesseract binary is not installed; real OCR integration unverified')
    result = list(units(DATA / filename, Path(filename).suffix))
    assert 'CG-2026-001' in result[0]['text']
    assert result[0]['ocr_confidence'] > 0


def test_missing_ocr_is_explicit(monkeypatch):
    monkeypatch.setattr('app.processing.ocr_available', lambda: False)
    with pytest.raises(ProcessingError, match='unavailable'):
        list(units(DATA / 'invoice.png', '.png'))


def test_malformed_csv(tmp_path):
    path = tmp_path / 'bad.csv'
    path.write_text('a,b\n1,2,3\n')
    with pytest.raises(ProcessingError):
        list(units(path, '.csv'))
