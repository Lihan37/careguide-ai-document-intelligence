"""Bounded, provenance-preserving readers. No document code or macros are executed."""
import csv
import io
import os
import re
import shutil
import subprocess
import time
from functools import lru_cache
import zipfile
from pathlib import Path
from datetime import date, datetime
from charset_normalizer import from_bytes
from PIL import Image, ImageOps, ImageEnhance, ImageFilter, UnidentifiedImageError
from .config import settings

EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.xlsx', '.xls', '.csv'}


class ProcessingError(ValueError):
    pass


def signature(path: Path, extension: str):
    head = path.open('rb').read(1024)
    good = {
        '.pdf': head.startswith(b'%PDF-'), '.png': head.startswith(b'\x89PNG\r\n\x1a\n'),
        '.jpg': head.startswith(b'\xff\xd8\xff'), '.jpeg': head.startswith(b'\xff\xd8\xff'),
        '.tif': head.startswith((b'II*\x00', b'MM\x00*')), '.tiff': head.startswith((b'II*\x00', b'MM\x00*')),
        '.xls': head.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'), '.xlsx': head.startswith(b'PK\x03\x04'),
        '.csv': b'\x00' not in head and not head.startswith((b'%PDF', b'PK\x03\x04', b'MZ')),
    }
    if not good.get(extension, False):
        raise ProcessingError('File signature does not match an allowed file type')
    if extension == '.xlsx':
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) > 2000 or sum(m.file_size for m in members) > 100_000_000:
                    raise ProcessingError('Workbook expanded size exceeds limit')
                if '[Content_Types].xml' not in archive.namelist() or 'xl/workbook.xml' not in archive.namelist():
                    raise ProcessingError('Not an XLSX workbook')
                if any('vbaproject' in m.filename.lower() or m.filename.startswith(('/', '\\')) or '..' in Path(m.filename).parts for m in members):
                    raise ProcessingError('Macros or unsafe workbook members rejected')
        except zipfile.BadZipFile as exc:
            raise ProcessingError('Corrupt workbook archive') from exc


@lru_cache(maxsize=16)
def installed_ocr_languages(command, data_dir):
    args = [command, '--list-langs']
    if data_dir:
        args += ['--tessdata-dir', data_dir]
    try:
        result = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace', timeout=5,
                                check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return frozenset(line.strip() for line in result.stdout.splitlines()[1:])
    except (OSError, subprocess.SubprocessError):
        return frozenset()


def ocr_configuration():
    cfg = settings()
    command = shutil.which(cfg.tesseract_cmd or 'tesseract')
    if command is None and cfg.tesseract_cmd and Path(cfg.tesseract_cmd).is_file():
        command = str(Path(cfg.tesseract_cmd).resolve())
    data_dir = str(Path(cfg.tesseract_data_dir).resolve()) if cfg.tesseract_data_dir else ''
    return command, data_dir, installed_ocr_languages(command, data_dir) if command else frozenset()


def ocr_available():
    command, _, languages = ocr_configuration()
    return bool(command and set(settings().ocr_language.split('+')) <= languages)


def normalize_dark_bands(pixels):
    """Make light lettering on broad, solid bands readable as dark text."""
    import cv2
    import numpy as np

    width = pixels.shape[1]
    close_size = max(3, min(31, round(width * .015))) | 1
    closing = cv2.getStructuringElement(cv2.MORPH_RECT, (close_size, close_size))
    minimum_height = max(3, round(width * .013)) | 1
    opening = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, round(width * .025)) | 1, minimum_height))
    dark_pixels = cv2.inRange(pixels, 0, 100)
    mask = cv2.morphologyEx(dark_pixels, cv2.MORPH_CLOSE, closing)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, opening)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask.fill(0)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < width / 4 or w < h * 3:
            continue
        # A nearby heading can touch the closed contour. Find the solid rows
        # of the band in the original pixels before changing their polarity.
        solid_rows = np.count_nonzero(dark_pixels[y:y + h, x:x + w], axis=1) >= w * .72
        boundaries = np.flatnonzero(np.diff(solid_rows, prepend=False, append=False))
        for top, bottom in zip(boundaries[::2], boundaries[1::2]):
            if bottom - top >= minimum_height:
                mask[y + top:y + bottom, x:x + w] = 255
    return np.bitwise_xor(pixels, mask, out=pixels)


def preprocess(image):
    image = ImageOps.exif_transpose(image).convert('L')
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(1.4).filter(ImageFilter.MedianFilter(3))
    import cv2
    import numpy as np
    array = np.array(image)
    foreground = cv2.findNonZero(cv2.threshold(array, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1])
    if foreground is not None:
        angle = cv2.minAreaRect(foreground)[-1]
        if angle > 45:
            angle -= 90
        if 0.2 < abs(angle) < 12:
            matrix = cv2.getRotationMatrix2D((array.shape[1] / 2, array.shape[0] / 2), angle, 1)
            array = cv2.warpAffine(array, matrix, (array.shape[1], array.shape[0]), borderValue=255)
    return Image.fromarray(normalize_dark_bands(array))


def ocr(image):
    cfg = settings()
    if not ocr_available():
        raise ProcessingError('Tesseract OCR or the configured language is unavailable. Check TESSERACT_CMD, TESSERACT_DATA_DIR and OCR_LANGUAGE.')
    command, data_dir, languages = ocr_configuration()
    if command is None:
        raise ProcessingError('Tesseract OCR is unavailable.')
    tessdata = ['--tessdata-dir', data_dir] if data_dir else []
    # Use the CLI argument vector directly: pytesseract's config-string parser
    # can pass literal quotes around a Windows tessdata path.
    environment = os.environ.copy()
    environment.setdefault('OMP_THREAD_LIMIT', '1')

    def recognize(pixels, args, timeout):
        with io.BytesIO() as encoded:
            pixels.save(encoded, format='PNG', dpi=(300, 300))
            return subprocess.run(
                [command, 'stdin', 'stdout', *tessdata, *args], input=encoded.getvalue(),
                capture_output=True, check=True, timeout=timeout, env=environment,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            ).stdout.decode('utf-8', errors='replace')

    started = time.perf_counter()
    with preprocess(image) as processed:
        rotation = 0
        if 'osd' in languages:
            try:
                orientation = recognize(processed, ['--psm', '0', '-l', 'osd'], min(5, cfg.ocr_timeout / 3))
                match = re.search(r'^Rotate: (90|180|270)\r?$', orientation, re.MULTILINE)
                rotation = int(match[1]) if match else 0
            except (OSError, subprocess.SubprocessError):
                pass  # A sparse text page may not have enough points for orientation detection.
        oriented = processed.rotate(-rotation, expand=True, fillcolor=255) if rotation else processed
        try:
            remaining = cfg.ocr_timeout - (time.perf_counter() - started)
            if remaining <= 0:
                raise ProcessingError('OCR exceeded the page time limit.')
            data = recognize(oriented, ['--psm', '6', '-l', cfg.ocr_language, '-c', 'tessedit_create_tsv=1'], remaining)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ProcessingError('Tesseract could not recognize this page.') from exc
        except subprocess.TimeoutExpired as exc:
            raise ProcessingError('OCR exceeded the page time limit.') from exc
        finally:
            if oriented is not processed:
                oriented.close()
    lines, confidences, words = {}, [], []
    rows = csv.DictReader(io.StringIO(data), delimiter='\t', quoting=csv.QUOTE_NONE)
    if not {'text', 'block_num', 'par_num', 'line_num', 'conf', 'left', 'top', 'width', 'height'} <= set(rows.fieldnames or []):
        raise ProcessingError('Tesseract did not return word evidence for this page.')
    for row in rows:
        word = row['text'] or ''
        if not word.strip():
            continue
        key = (row['block_num'], row['par_num'], row['line_num'])
        lines.setdefault(key, []).append(word)
        confidence = float(row['conf'])
        if confidence >= 0:
            confidences.append(confidence)
        x, y, width, height = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
        words.append({'text': word, 'bbox': [x, y, x + width, y + height]})
    return {'text': '\n'.join(' '.join(line) for line in lines.values()), 'words': words,
            'method': 'tesseract_ocr', 'ocr_confidence': sum(confidences) / len(confidences) / 100 if confidences else None,
            'ocr_language': cfg.ocr_language, 'ocr_seconds': round(time.perf_counter() - started, 6),
            'coordinate_space': 'preprocessed_image_pixels'}


def scalar(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, float):
        return str(value)
    return value


def pdf_units(path):
    cfg = settings()
    from .pdf_ingestion import check_deadline, inspected_pdf, page_pixels
    import pymupdf

    deadline = time.monotonic() + cfg.job_timeout
    with inspected_pdf(path, cfg, deadline) as (pdf, normalized):
        for index, page in enumerate(pdf):
            check_deadline(deadline)
            # EXCLUDE_IMAGES avoids copying image data while inspecting the text layer.
            flags = pymupdf.TEXTFLAGS_TEXT
            text_page = page.get_textpage(clip=page.rect, flags=flags)
            text = text_page.extractText()
            blocks = [{'bbox': list(b[:4]), 'text': b[4]} for b in text_page.extractBLOCKS() if b[6] == 0]
            hidden_text = normalized and bool(text.strip()) and any(
                span['type'] == 3 or span['opacity'] <= 0 for span in page.get_texttrace()
            )
            # A scan with a digital watermark or footer can have a text layer.
            sparse_scan = 30 <= len(text.strip()) < 150 and any(
                (pymupdf.Rect(image['bbox']) & page.rect).get_area() >= page.rect.get_area() * .55
                for image in page.get_image_info()
            )
            if hidden_text:
                blocks = []
            if hidden_text or len(text.strip()) < 30 or sparse_scan:
                pix = page_pixels(page, cfg.max_image_pixels, 2.2)
                with Image.frombytes('L', [pix.width, pix.height], pix.samples) as image:
                    del pix
                    recognized = ocr(image)
            else:
                recognized = {'text': text, 'method': 'digital_pdf', 'ocr_confidence': None,
                              'words': [{'bbox': list(word[:4]), 'text': word[4]} for word in text_page.extractWORDS()]}
            check_deadline(deadline)
            metadata = {'pdf_normalization': 'visible_pages_only_c2pa'} if normalized else {}
            yield {'page': index + 1, 'total': pdf.page_count, 'blocks': blocks} | metadata | recognized


def units(path: Path, extension: str):
    """Yield one page/sheet at a time; caller persists each unit before requesting next."""
    cfg = settings()
    if extension == '.pdf':
        yield from pdf_units(path)
    elif extension in {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}:
        formats = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.tif': 'TIFF', '.tiff': 'TIFF'}
        try:
            with Image.open(path, formats=[formats[extension]]) as image:
                frames = getattr(image, 'n_frames', 1)
                if frames > cfg.max_pages:
                    raise ProcessingError('Too many image frames')
                for index in range(frames):
                    image.seek(index)
                    if image.width * image.height > cfg.max_image_pixels:
                        raise ProcessingError('Image pixel limit exceeded')
                    yield {'page': index + 1, 'total': frames} | ocr(image)
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, EOFError) as exc:
            raise ProcessingError('Corrupt, oversized, or unsupported image.') from exc
    elif extension == '.xlsx':
        import openpyxl
        book = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
        formulas = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
        try:
            total_cells = 0
            for sheet in book:
                dimension = (sheet.max_row or 0) * (sheet.max_column or 0)
                total_cells += dimension
                if total_cells > cfg.max_cells:
                    raise ProcessingError('Workbook cell limit exceeded')
                rows = [[scalar(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
                formula_cells = [{'row': c.row, 'column': c.column, 'formula': c.value, 'cached_value': rows[c.row - 1][c.column - 1]} for row in formulas[sheet.title] for c in row if c.data_type == 'f']
                yield sheet_unit(sheet.title, rows, len(book.sheetnames), formula_cells)
        finally:
            book.close()
            formulas.close()
    elif extension == '.xls':
        import xlrd
        book = xlrd.open_workbook(path, on_demand=True)
        try:
            total_cells = 0
            for sheet in book.sheets():
                total_cells += sheet.nrows * sheet.ncols
                if total_cells > cfg.max_cells:
                    raise ProcessingError('Workbook cell limit exceeded')
                rows = [[xlrd.xldate.xldate_as_datetime(c.value, book.datemode).date().isoformat() if c.ctype == xlrd.XL_CELL_DATE else scalar(c.value) for c in sheet.row(i)] for i in range(sheet.nrows)]
                yield sheet_unit(sheet.name, rows, book.nsheets)
        finally:
            book.release_resources()
    elif extension == '.csv':
        raw = path.read_bytes()
        encoding = from_bytes(raw).best()
        if encoding is None:
            raise ProcessingError('CSV encoding could not be detected')
        decoded = str(encoding).lstrip('\ufeff')
        try:
            dialect = csv.Sniffer().sniff(decoded[:8192], delimiters=',;\t|')
        except csv.Error:
            dialect = csv.excel
        csv.field_size_limit(100000)
        try:
            rows, count, width = [], 0, None
            for row in csv.reader(io.StringIO(decoded), dialect, strict=True):
                count += len(row)
                if count > cfg.max_cells:
                    raise ProcessingError('CSV cell limit exceeded')
                if width is None:
                    width = len(row)
                if len(row) != width:
                    raise ProcessingError('CSV has inconsistent row widths')
                rows.append(row)
            yield sheet_unit('CSV', rows, 1) | {'encoding': encoding.encoding}
        except csv.Error as exc:
            raise ProcessingError('Malformed CSV') from exc
    else:
        raise ProcessingError('Unsupported document format.')


def sheet_unit(name, rows, total, formulas=None):
    text = '\n'.join(' | '.join('' if v is None else str(v) for v in row) for row in rows)
    return {'sheet': name, 'total': total, 'rows': rows, 'text': text, 'formulas': formulas or [], 'method': 'spreadsheet'}
