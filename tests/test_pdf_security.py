from pathlib import Path
from struct import pack
import zlib

import pymupdf
import pytest

from app.config import settings
from app import pdf_ingestion
from app.processing import ProcessingError, ocr_available, units


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


def box(name, body):
    return pack('>I4s', len(body) + 8, name) + body


def superbox(kind, label, *content):
    description = kind + bytes.fromhex('00110010800000aa00389b71') + b'\x03' + label + b'\0'
    return box(b'jumb', box(b'jumd', description) + b''.join(content))


def manifest_store():
    # Structurally valid test envelope. Its inert CBOR is not a signed claim.
    data = box(b'cbor', b'\xa0')
    assertions = superbox(b'c2as', b'c2pa.assertions', superbox(b'cbor', b'c2pa.hash.data', data))
    claim = superbox(b'c2cl', b'c2pa.claim.v2', data)
    signature = superbox(b'c2cs', b'c2pa.signature', data)
    return superbox(b'c2pa', b'c2pa', superbox(b'c2ma', b'urn:c2pa:synthetic', assertions, claim, signature))


def associate_manifest(pdf, payload):
    stream = pdf.get_new_xref()
    pdf.update_object(stream, '<</Type /EmbeddedFile /Subtype /application#2Fc2pa>>')
    pdf.update_stream(stream, payload, compress=False)
    spec = pdf.get_new_xref()
    pdf.update_object(spec, f'<</Type /Filespec /Subtype (application/c2pa) /F (Synthetic provenance) '
                            f'/AFRelationship /C2PA_Manifest /EF <</F {stream} 0 R>>>>')
    pdf.xref_set_key(pdf.pdf_catalog(), 'AF', f'[{spec} 0 R]')
    pdf.xref_set_key(pdf.pdf_catalog(), 'Names', f'<</EmbeddedFiles <</Names [(Synthetic provenance) {spec} 0 R]>>>>')
    return stream


@pytest.mark.parametrize(('filename', 'methods'), [
    ('invoice.pdf', ['digital_pdf']),
    ('ocr/scanned.pdf', ['tesseract_ocr']),
    ('ocr/multipage.pdf', ['tesseract_ocr', 'tesseract_ocr']),
    ('ocr/mixed.pdf', ['digital_pdf', 'tesseract_ocr']),
])
def test_c2pa_pdf_uses_visible_pages_and_preserves_original(client, filename, methods):
    if 'tesseract_ocr' in methods and not ocr_available():
        pytest.skip('Real Tesseract unavailable')
    with pymupdf.open(SAMPLES / filename) as document:
        associate_manifest(document, manifest_store())
        original = document.tobytes()
    upload = client.post('/api/documents/upload', files={'files': ('normal-upload.pdf', original, 'application/pdf')})
    upload.raise_for_status()
    item = upload.json()['results'][0]
    url = '/api/documents/' + item['document_id']
    detail = client.get(url).json()
    assert detail['status'] in {'COMPLETED', 'REQUIRES_REVIEW'}, detail['error']
    assert [source['method'] for source in detail['sources']] == methods
    assert [source['page'] for source in detail['sources']] == list(range(1, len(methods) + 1))
    assert all(source['pdf_normalization'] == 'visible_pages_only_c2pa' for source in detail['sources'])
    assert all('Synthetic provenance' not in source['text'] for source in detail['sources'])
    assert detail['evidence']['total']['page'] == len(methods)
    normalization, = [entry['detail'] for entry in detail['audit'] if entry['action'] == 'pdf_normalized']
    assert normalization == {'job_id': item['job_id'], 'mode': 'visible_pages_only_c2pa', 'page_count': len(methods),
                             'original_sha256': detail['checksum'], 'authenticity_verified': False}
    download = client.get(url + '/source')
    assert download.content == original
    assert download.headers['content-disposition'].startswith('attachment;')
    assert client.get(url + f'/source?page={len(methods)}').headers['content-type'] == 'image/png'


@pytest.mark.parametrize('variant', ['bad structure', 'extra attachment', 'alternate reference', 'oversized manifest'])
def test_c2pa_metadata_labels_cannot_approve_unknown_content(tmp_path, variant, monkeypatch):
    path = tmp_path / 'associated.pdf'
    with pymupdf.open(SAMPLES / 'invoice.pdf') as pdf:
        payload = manifest_store()[:-1] if variant == 'bad structure' else manifest_store()
        stream = associate_manifest(pdf, payload)
        if variant == 'extra attachment':
            pdf.embfile_add('fixture.bin', b'Inert second file')
        elif variant == 'alternate reference':
            pdf.xref_set_key(pdf.page_xref(0), 'ExtraObject', f'{stream} 0 R')
        elif variant == 'oversized manifest':
            monkeypatch.setattr(pdf_ingestion, 'MAX_MANIFEST_BYTES', 64)
        pdf.save(path)
    with pytest.raises(ProcessingError, match='Embedded PDF files rejected'):
        next(units(path, '.pdf'))


def test_rejects_file_annotation_even_with_valid_provenance(tmp_path):
    path = tmp_path / 'annotation.pdf'
    with pymupdf.open(SAMPLES / 'invoice.pdf') as pdf:
        associate_manifest(pdf, manifest_store())
        pdf[0].add_file_annot((40, 40), b'Inert test attachment', 'note.txt')
        pdf.save(path)
    with pytest.raises(ProcessingError, match='Active content rejected'):
        next(units(path, '.pdf'))


def test_flate_stream_expansion_is_bounded(tmp_path, monkeypatch):
    path = tmp_path / 'bounded.pdf'
    with pymupdf.open(SAMPLES / 'invoice.pdf') as pdf:
        stream = pdf.get_new_xref()
        pdf.update_object(stream, '<<>>')
        pdf.update_stream(stream, zlib.compress(b' ' * 20_000), compress=False)
        pdf.xref_set_key(stream, 'Filter', '/FlateDecode')
        pdf.xref_set_key(pdf.page_xref(0), 'Contents', f'{stream} 0 R')
        pdf.save(path)
    monkeypatch.setattr(pdf_ingestion, 'MAX_STREAM_BYTES', 8_192)
    with pytest.raises(ProcessingError, match='decompression limit exceeded'):
        next(units(path, '.pdf'))


def test_pdf_input_size_is_checked_before_opening(monkeypatch):
    monkeypatch.setattr(settings(), 'max_file_mb', 0)
    with pytest.raises(ProcessingError, match='configured size limit'):
        next(units(SAMPLES / 'invoice.pdf', '.pdf'))


def test_supported_provenance_pdf_ignores_hidden_text(tmp_path):
    if not ocr_available():
        pytest.skip('Real Tesseract unavailable')
    path = tmp_path / 'invisible-text.pdf'
    with pymupdf.open(SAMPLES / 'ocr/scanned.pdf') as pdf:
        associate_manifest(pdf, manifest_store())
        pdf[0].insert_text((40, 38), 'This invisible label has no visual evidence.', render_mode=3)
        pdf.save(path)
    source, = list(units(path, '.pdf'))
    assert source['method'] == 'tesseract_ocr'
    assert source['blocks'] == [] and 'invisible label' not in source['text']
