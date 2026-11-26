"""Inspect untrusted PDF objects and expose only bounded page content."""
from base64 import a85decode
from binascii import unhexlify
from collections import defaultdict
from contextlib import contextmanager
from math import isfinite
import re
from struct import unpack_from
import time
import zlib

import pymupdf
from pymupdf import mupdf

from .processing import ProcessingError


MAX_OBJECTS = 200_000
MAX_DIRECT_NODES = 1_000_000
MAX_STREAM_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
CHUNK_BYTES = 64 * 1024
ATTACHMENT_ERROR = 'Embedded PDF files rejected. Only supported document-level C2PA provenance is allowed.'
ACTIVE_KEYS = {'JavaScript', 'JS', 'OpenAction', 'AA', 'XFA', 'RichMediaContent', 'RichMediaSettings'}
ACTIVE_NAMES = {'JavaScript', 'Launch', 'RichMedia', 'FileAttachment', 'Sound', 'Movie', 'Screen', '3D',
                'Rendition', 'GoToE', 'GoToR', 'ImportData', 'SubmitForm', 'GoTo3DView'}
ATTACHMENT_KEYS = {'AF', 'EF', 'RF', 'FS', 'EmbeddedFiles'}
ATTACHMENT_NAMES = {'Filespec', 'EmbeddedFile'}
IMAGE_FILTERS = {'/DCTDecode', '/JPXDecode', '/CCITTFaxDecode', '/JBIG2Decode'}
ASCII_FILTERS = {'/ASCII85Decode', '/ASCIIHexDecode'}
JUMBF_UUID_SUFFIX = bytes.fromhex('00110010800000aa00389b71')
MANIFEST_TYPES = {b'c2ma', b'c2cm', b'c2um'}


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise ProcessingError('PDF processing time limit exceeded')


def boxes(data):
    """Read box framing without decoding any manifest content boxes."""
    start = 0
    while start < len(data):
        if len(data) - start < 8:
            raise ValueError('Truncated box')
        size, kind = unpack_from('>I4s', data, start)
        if size < 8 or size > len(data) - start:
            raise ValueError('Invalid box size')
        end = start + size
        yield kind, data[start + 8:end]
        start = end


def superbox(data):
    children = iter(boxes(data))
    kind, description = next(children, (b'', b''))
    if kind != b'jumd' or len(description) < 19:
        raise ValueError('Missing description')
    # This profile accepts requestable, labelled boxes without optional extensions.
    label = bytes(description[17:])
    if description[16] != 3 or not label.endswith(b'\0') or b'\0' in label[:-1]:
        raise ValueError('Unsupported description')
    return bytes(description[:16]), label[:-1], children


def manifest_shape(raw):
    """Recognize the C2PA JUMBF envelope, never trust or interpret its payload."""
    def inspect(node, depth):
        nonlocal count
        count += 1
        if depth > 8 or count > 4096:
            raise ValueError('Manifest structure limit')
        uuid, label, children = superbox(node)
        types, kinds = [], []
        for kind, child in children:
            count += 1
            if count > 4096:
                raise ValueError('Manifest box limit')
            kinds.append(kind)
            if kind == b'jumb':
                types.append(inspect(child, depth + 1))
            elif kind not in {b'cbor', b'json', b'bfdb', b'bidb', b'free'}:
                raise ValueError('Unsupported content box')
        if not kinds:
            raise ValueError('Empty manifest box')
        kind = uuid[:4] if uuid[4:] == JUMBF_UUID_SUFFIX else b''
        if kind == b'c2pa' and (label != b'c2pa' or not types or any(t not in MANIFEST_TYPES for t in types)
                                or any(k != b'jumb' for k in kinds)):
            raise ValueError('Invalid manifest store')
        if kind in MANIFEST_TYPES and any(types.count(t) != 1 for t in (b'c2as', b'c2cl', b'c2cs')):
            raise ValueError('Missing claim, assertion store, or signature box')
        if kind in {b'c2cl', b'c2cs'} and kinds != [b'cbor']:
            raise ValueError('Invalid claim or signature envelope')
        return kind

    try:
        count = 0
        root, = boxes(memoryview(raw))
        return root[0] == b'jumb' and inspect(root[1], 0) == b'c2pa'
    except ValueError:
        return False


def expanded_flate(raw, allowance, deadline):
    decoder = zlib.decompressobj()
    length = 0
    try:
        for start in range(0, len(raw), CHUNK_BYTES):
            chunk = raw[start:start + CHUNK_BYTES]
            while chunk:
                check_deadline(deadline)
                length += len(decoder.decompress(chunk, min(CHUNK_BYTES, allowance - length + 1)))
                if length > allowance:
                    raise ProcessingError('PDF stream decompression limit exceeded')
                chunk = decoder.unconsumed_tail
        if decoder.eof and not decoder.unused_data:
            return length
    except zlib.error:
        pass
    raise ProcessingError('Malformed or corrupt PDF stream')


def decode_ascii(raw, name):
    if len(raw) > 8 * 1024 * 1024:
        raise ProcessingError('PDF encoded stream limit exceeded')
    raw = re.sub(rb'[\x00\t\n\f\r ]+', b'', raw)
    try:
        if name == '/ASCII85Decode' and raw.endswith(b'~>'):
            return a85decode(raw[:-2], ignorechars=b'')
        if name == '/ASCIIHexDecode' and raw.endswith(b'>'):
            body = raw[:-1]
            return unhexlify(body + b'0' * (len(body) % 2))
    except ValueError:
        pass
    raise ProcessingError('Malformed or corrupt PDF stream encoding')


def inspect_objects(pdf, cfg, deadline):
    document = mupdf.pdf_document_from_fz_document(pdf.this)
    catalog = pdf.pdf_catalog()
    markers, references = set(), defaultdict(set)
    direct_nodes = 0

    def walk(owner, obj, path):
        nonlocal direct_nodes
        direct_nodes += 1
        if direct_nodes > MAX_DIRECT_NODES or len(path) > 32:
            raise ProcessingError('PDF object structure limit exceeded')
        if mupdf.pdf_is_indirect(obj):
            references[mupdf.pdf_to_num(obj)].add((owner, path))
        elif mupdf.pdf_is_dict(obj):
            for index in range(mupdf.pdf_dict_len(obj)):
                key = mupdf.pdf_to_name(mupdf.pdf_dict_get_key(obj, index))
                value = mupdf.pdf_dict_get_val(obj, index)
                if key in ACTIVE_KEYS:
                    raise ProcessingError('Active content rejected')
                if key in ATTACHMENT_KEYS:
                    markers.add((owner, path + (key,)))
                walk(owner, value, path + (key,))
        elif mupdf.pdf_is_array(obj):
            for index in range(mupdf.pdf_array_len(obj)):
                walk(owner, mupdf.pdf_array_get(obj, index), path + (index,))
        elif mupdf.pdf_is_name(obj):
            name = mupdf.pdf_to_name(obj)
            if name in ACTIVE_NAMES:
                raise ProcessingError('Active content rejected')
            if name in ATTACHMENT_NAMES:
                markers.add((owner, path))

    walk(-1, mupdf.pdf_trailer(document), ())
    streams = []
    for xref in range(1, pdf.xref_length()):
        check_deadline(deadline)
        walk(xref, mupdf.pdf_load_object(document, xref), ())
        if pdf.xref_is_stream(xref):
            streams.append(xref)
    normalized = bool(markers)
    manifest = allowed_manifest(pdf, catalog, markers, references) if normalized else None
    expanded = 0
    for xref in streams:
        check_deadline(deadline)
        if xref == manifest:
            continue
        expanded += inspect_stream(pdf, xref, cfg, deadline, MAX_EXPANDED_BYTES - expanded)
        if expanded > MAX_EXPANDED_BYTES:
            raise ProcessingError('PDF expanded stream budget exceeded')
    return normalized


def allowed_manifest(pdf, catalog, markers, references):
    """Accept just a shared catalog association and a single unfiltered store."""
    def matches(xref, key, kind, pattern):
        actual_kind, value = pdf.xref_get_key(xref, key)
        return re.fullmatch(pattern, value) if actual_kind == kind else None

    association = matches(catalog, 'AF', 'array', r'\[\s*(\d+)\s+0\s+R\s*\]')
    if not association:
        raise ProcessingError(ATTACHMENT_ERROR)
    spec = int(association[1])
    pointer = matches(spec, 'EF/F', 'xref', r'(\d+)\s+0\s+R')
    if not pointer:
        raise ProcessingError(ATTACHMENT_ERROR)
    stream = int(pointer[1])
    if (markers != {(catalog, ('AF',)), (catalog, ('Names', 'EmbeddedFiles')),
                    (spec, ('Type',)), (spec, ('EF',)), (stream, ('Type',))}
            or references[spec] != {(catalog, ('AF', 0)), (catalog, ('Names', 'EmbeddedFiles', 'Names', 1))}
            or references[stream] != {(spec, ('EF', 'F'))}
            or not set(pdf.xref_get_keys(spec)) <= {'Type', 'Subtype', 'AFRelationship', 'F', 'UF', 'Desc', 'EF'}
            or pdf.xref_get_key(spec, 'Type') != ('name', '/Filespec')
            or pdf.xref_get_key(spec, 'Subtype') != ('string', 'application/c2pa')
            or pdf.xref_get_key(spec, 'AFRelationship') != ('name', '/C2PA_Manifest')
            or set(pdf.xref_get_keys(stream)) != {'Type', 'Subtype', 'Length'}
            or pdf.xref_get_key(stream, 'Type') != ('name', '/EmbeddedFile')
            or pdf.xref_get_key(stream, 'Subtype') != ('name', '/application/c2pa')
            or not pdf.xref_is_stream(stream) or pdf.embfile_count() != 1):
        raise ProcessingError(ATTACHMENT_ERROR)
    kind, size = pdf.xref_get_key(stream, 'Length')
    if kind != 'int' or not 0 < int(size) <= MAX_MANIFEST_BYTES:
        raise ProcessingError(ATTACHMENT_ERROR)
    raw = pdf.xref_stream_raw(stream)
    if not raw or len(raw) != int(size) or not manifest_shape(raw):
        raise ProcessingError(ATTACHMENT_ERROR)
    return stream


def inspect_stream(pdf, xref, cfg, deadline, remaining):
    if pdf.xref_get_key(xref, 'F')[0] != 'null':
        raise ProcessingError(ATTACHMENT_ERROR)
    is_image = pdf.xref_get_key(xref, 'Subtype') == ('name', '/Image')
    if is_image:
        dimensions = [pdf.xref_get_key(xref, key) for key in ('Width', 'Height')]
        if any(kind != 'int' or int(value) < 1 for kind, value in dimensions):
            raise ProcessingError('Malformed PDF image dimensions')
        width, height = (int(value) for _, value in dimensions)
        if width * height > cfg.max_image_pixels:
            raise ProcessingError('PDF image pixel limit exceeded')
    filter_kind, filter_value = pdf.xref_get_key(xref, 'Filter')
    if filter_kind == 'null':
        size_kind, length = pdf.xref_get_key(xref, 'Length')
        if size_kind == 'xref':
            length = pdf.xref_object(int(length.split()[0]), compressed=True).strip()
        if not length.isdecimal():
            raise ProcessingError('Invalid PDF stream length')
        return int(length)
    if filter_kind == 'name':
        filters = [filter_value]
    elif filter_kind == 'array' and re.fullmatch(r'\[\s*(?:/[A-Za-z0-9]+\s*)+\]', filter_value):
        filters = re.findall(r'/[A-Za-z0-9]+', filter_value)
    else:
        filters = []
    raw = None
    if filters and filters[0] in ASCII_FILTERS:
        raw = decode_ascii(pdf.xref_stream_raw(xref) or b'', filters.pop(0))
        if not filters:
            return len(raw)
    if filters == ['/FlateDecode']:
        return expanded_flate(raw if raw is not None else pdf.xref_stream_raw(xref) or b'', min(MAX_STREAM_BYTES, remaining), deadline)
    if len(filters) == 1 and is_image and filters[0] in IMAGE_FILTERS:
        return width * height * 4
    raise ProcessingError('Unsupported PDF stream encoding. Export a PDF with standard compression.')


@contextmanager
def inspected_pdf(path, cfg, deadline):
    if path.stat().st_size > cfg.max_file_mb * 1024 * 1024:
        raise ProcessingError('File exceeds configured size limit')
    check_deadline(deadline)
    try:
        with pymupdf.open(path, filetype='pdf') as pdf:
            if not pdf.is_pdf or pdf.is_repaired:
                raise ProcessingError('Malformed or corrupt PDF')
            if pdf.needs_pass or 'Encrypt' in pdf.xref_get_keys(-1) or not 0 < pdf.page_count <= cfg.max_pages:
                raise ProcessingError('Encrypted, empty, or over-limit PDF')
            if pdf.xref_length() > MAX_OBJECTS:
                raise ProcessingError('PDF object limit exceeded')
            normalized = inspect_objects(pdf, cfg, deadline)
            yield pdf, normalized
    except (RuntimeError, IndexError, OverflowError) as exc:
        raise ProcessingError('Malformed or corrupt PDF') from exc


def page_pixels(page, max_pixels, scale, *, colorspace=pymupdf.csGRAY):
    rect = page.rect
    if not all(isfinite(dimension) and dimension > 0 for dimension in (rect.width, rect.height)):
        raise ProcessingError('Invalid PDF page geometry')
    scale = min(scale, (max_pixels / (rect.width * rect.height)) ** .5)
    bounds = (rect * pymupdf.Matrix(scale, scale)).irect
    if bounds.width * bounds.height > max_pixels:
        scale *= .995 * (max_pixels / (bounds.width * bounds.height)) ** .5
    bounds = (rect * pymupdf.Matrix(scale, scale)).irect
    if not 0 < bounds.width * bounds.height <= max_pixels:
        raise ProcessingError('PDF page exceeds the image pixel limit')
    return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=colorspace, alpha=False, annots=False)
