"""Render synthetic invoices as pixels and embed the scans in PDFs."""
import io
import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

DESTINATION = Path(__file__).resolve().parents[1] / 'sample-data/ocr'
EXPECTED = {
    'invoice_number': 'SCAN-2048', 'invoice_date': '2026-11-20',
    'supplier_name': 'Synthetic Atlas Supplies', 'customer_name': 'Synthetic Harbor Lab',
    'subtotal': '160.00', 'tax': '16.00', 'total': '176.00', 'currency': 'USD',
}
HEADER = ['Invoice No: SCAN-2048', 'Invoice Date: 2026-11-20',
          'Supplier: Synthetic Atlas Supplies', 'Customer: Synthetic Harbor Lab', 'Currency: USD']
ROWS = ['Item: Scanner stand | 2 | 40.00 | 80.00 | 8.00',
        'Item: Printer tray | 4 | 20.00 | 80.00 | 8.00']
TOTALS = ['Subtotal: 160.00', 'VAT (10%): 16.00', 'Grand Total: 176.00']


def render(lines, color=0, paper=255):
    image = Image.new('L', (1200, 1500), paper)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype('arial.ttf', 34)
    except OSError:
        font = ImageFont.load_default(size=34)
    for index, text in enumerate(['SYNTHETIC TEST INVOICE', *lines]):
        draw.text((72, 75 + 64 * index), text, font=font, fill=color)
    return image


def raster_pdf(path, images, *, digital_first=False, footer=False):
    with pymupdf.open() as document:
        if digital_first:
            page = document.new_page(width=600, height=750)
            page.insert_text((36, 55), '\n'.join(['SYNTHETIC DIGITAL INVOICE COVER', *HEADER]), fontsize=15)
        for image in images:
            page = document.new_page(width=600, height=750)
            with io.BytesIO() as buffer:
                image.save(buffer, format='PNG')
                page.insert_image(page.rect, stream=buffer.getvalue())
            if footer:
                page.insert_text((36, 725), 'Synthetic scan with a digital footer for testing only.', fontsize=10)
        document.save(path, deflate=True)


def generate(destination=DESTINATION):
    destination.mkdir(parents=True, exist_ok=True)
    with render(HEADER + ROWS + TOTALS) as full, render(HEADER + ROWS[:1]) as first, render(ROWS[1:] + TOTALS) as second:
        full.save(destination / 'clear.png')
        full.save(destination / 'clear.jpg', quality=92)
        first.save(destination / 'scanned.tiff', compression='tiff_deflate', save_all=True, append_images=[second])
        raster_pdf(destination / 'scanned.pdf', [full])
        raster_pdf(destination / 'multipage.pdf', [first, second])
        with render(ROWS + TOTALS) as continuation:
            raster_pdf(destination / 'mixed.pdf', [continuation], digital_first=True, footer=True)
    with render(HEADER + ROWS + TOTALS, color=110, paper=171) as faint:
        with faint.resize((770, 960)) as reduced, reduced.filter(ImageFilter.GaussianBlur(0.85)) as blurred:
            blurred.save(destination / 'low-quality.jpg', quality=30)
    (destination / 'corrupt.png').write_bytes(b'\x89PNG\r\n\x1a\ntruncated synthetic test image')
    (destination / 'ground-truth.json').write_text(json.dumps({
        'header': EXPECTED, 'line_amounts': ['80.00', '80.00'],
        'files': {
            'clear.png': ['tesseract_ocr'], 'clear.jpg': ['tesseract_ocr'],
            'scanned.tiff': ['tesseract_ocr', 'tesseract_ocr'], 'scanned.pdf': ['tesseract_ocr'],
            'multipage.pdf': ['tesseract_ocr', 'tesseract_ocr'],
            'mixed.pdf': ['digital_pdf', 'tesseract_ocr'], 'low-quality.jpg': ['tesseract_ocr'],
            'corrupt.png': None,
        },
    }, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    generate()
