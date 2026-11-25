"""Bounded, provenance-preserving readers. No document code or macros are executed."""
import csv
import io
import re
import shutil
import zipfile
from pathlib import Path
from datetime import date, datetime
from charset_normalizer import from_bytes
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
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


def ocr_available():
    command = settings().tesseract_cmd or 'tesseract'
    return bool(shutil.which(command) or Path(command).is_file())


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
    return Image.fromarray(array)


def ocr(image):
    if not ocr_available():
        raise ProcessingError('Tesseract OCR is unavailable. Install it and configure TESSERACT_CMD.')
    import pytesseract
    if settings().tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings().tesseract_cmd
    image = preprocess(image)
    try:
        try:
            rotation = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT, timeout=min(10, settings().ocr_timeout))['rotate']
            if rotation:
                image = image.rotate(-rotation, expand=True, fillcolor=255)
        except (pytesseract.TesseractError, RuntimeError):
            pass
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, timeout=settings().ocr_timeout, config='--psm 6')
        lines, confidences = {}, []
        for i, word in enumerate(data['text']):
            if not word.strip():
                continue
            key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
            lines.setdefault(key, []).append(word)
            if float(data['conf'][i]) >= 0:
                confidences.append(float(data['conf'][i]))
        return '\n'.join(' '.join(line) for line in lines.values()), (sum(confidences) / len(confidences) / 100 if confidences else None)
    finally:
        image.close()


def scalar(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, float):
        return str(value)
    return value


def units(path: Path, extension: str):
    """Yield one page/sheet at a time; caller persists each unit before requesting next."""
    cfg = settings()
    if extension == '.pdf':
        import pymupdf
        with pymupdf.open(path) as pdf:
            if pdf.needs_pass or pdf.page_count > cfg.max_pages or pdf.page_count == 0:
                raise ProcessingError('Encrypted, empty, or over-limit PDF')
            if pdf.xref_length() > 200000:
                raise ProcessingError('PDF object limit exceeded')
            if pdf.embfile_count() or any(re.search(r'/JavaScript\b|/JS\b|/Launch\b|/OpenAction\b', pdf.xref_object(i)) for i in range(1, pdf.xref_length())):
                raise ProcessingError('Active content or embedded files rejected')
            for index in range(pdf.page_count):
                page = pdf[index]
                text = page.get_text()
                blocks = [{'bbox': list(b[:4]), 'text': b[4]} for b in page.get_text('blocks') if isinstance(b[4], str)]
                method, confidence = 'digital_pdf', None
                if len(text.strip()) < 30:
                    scale = min(2.0, (cfg.max_image_pixels / max(1, page.rect.width * page.rect.height)) ** 0.5)
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    with Image.frombytes('RGB', [pix.width, pix.height], pix.samples) as image:
                        text, confidence = ocr(image)
                    del pix
                    method = 'tesseract_ocr'
                words = [{'bbox': list(word[:4]), 'text': word[4]} for word in page.get_text('words')] if method == 'digital_pdf' else []
                yield {'page': index + 1, 'total': pdf.page_count, 'text': text, 'blocks': blocks, 'words': words, 'method': method, 'ocr_confidence': confidence}
    elif extension in {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}:
        Image.MAX_IMAGE_PIXELS = cfg.max_image_pixels
        with Image.open(path) as image:
            frames = getattr(image, 'n_frames', 1)
            if frames > cfg.max_pages:
                raise ProcessingError('Too many image frames')
            for index in range(frames):
                image.seek(index)
                if image.width * image.height > cfg.max_image_pixels:
                    raise ProcessingError('Image pixel limit exceeded')
                text, confidence = ocr(image)
                yield {'page': index + 1, 'total': frames, 'text': text, 'method': 'tesseract_ocr', 'ocr_confidence': confidence}
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
    else:
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


def sheet_unit(name, rows, total, formulas=None):
    text = '\n'.join(' | '.join('' if v is None else str(v) for v in row) for row in rows)
    return {'sheet': name, 'total': total, 'rows': rows, 'text': text, 'formulas': formulas or [], 'method': 'spreadsheet'}
