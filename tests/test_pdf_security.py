from pathlib import Path

import pymupdf
import pytest

from app.config import settings
from app.processing import ProcessingError, units


SAMPLES = Path('sample-data')


def test_safe_digital_pdf_enters_extraction():
    page, = list(units(SAMPLES / 'invoice.pdf', '.pdf'))
    assert page['method'] == 'digital_pdf' and page['words']


@pytest.mark.parametrize(('feature', 'error'), [
    ('embedded attachment', 'Embedded PDF files rejected'),
    ('JavaScript', 'Active content rejected'),
    ('OpenAction', 'Active content rejected'),
    ('Launch', 'Active content rejected'),
])
def test_pdf_rejected_before_any_page_is_read(tmp_path, feature, error):
    path = tmp_path / 'restricted.pdf'
    with pymupdf.open(SAMPLES / 'scanned.pdf') as pdf:
        if feature == 'embedded attachment':
            pdf.embfile_add('fixture.txt', b'Inert test attachment')
        elif feature == 'JavaScript':
            pdf.xref_set_key(pdf.pdf_catalog(), 'Names', '<</JavaScript << /Names [] >> >>')
        elif feature == 'OpenAction':
            pdf.xref_set_key(pdf.pdf_catalog(), 'OpenAction', f'[{pdf.page_xref(0)} 0 R /Fit]')
        elif feature == 'Launch':
            pdf.xref_set_key(pdf.page_xref(0), 'AA', '<</O <</S /Launch>>>>')
        pdf.save(path)
    with pytest.raises(ProcessingError, match=error):
        next(units(path, '.pdf'))


def test_pdf_cross_reference_repair_is_rejected(tmp_path):
    path = tmp_path / 'repairable.pdf'
    content = (SAMPLES / 'invoice.pdf').read_bytes()
    path.write_bytes(content[:content.rindex(b'startxref')])
    with pymupdf.open(path) as pdf:
        assert pdf.is_repaired
    with pytest.raises(ProcessingError, match='Malformed or corrupt PDF'):
        next(units(path, '.pdf'))


def test_corrupt_pdf_returns_safe_error():
    with pytest.raises(ProcessingError, match='Malformed or corrupt PDF'):
        next(units(SAMPLES / 'corrupted.pdf', '.pdf'))


def test_pdf_page_limit_precedes_page_reads(monkeypatch):
    monkeypatch.setattr(settings(), 'max_pages', 1)
    with pytest.raises(ProcessingError, match='over-limit PDF'):
        next(units(SAMPLES / 'multipage.pdf', '.pdf'))
