"""Synthetic fixtures; ground truth is declared before rendering, not extracted from outputs."""
import csv
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import pymupdf
import openpyxl
import xlwt

ROOT = Path(__file__).resolve().parents[1] / 'sample-data'
BASE = {'invoice_number': 'CG-2026-001', 'invoice_date': '2026-11-20', 'supplier_name': 'Synthetic Northstar Supplies', 'customer_name': 'Synthetic Harbor Studio', 'subtotal': '200.00', 'tax': '20.00', 'total': '220.00', 'currency': 'USD', 'line_items': [{'description': 'Consulting', 'quantity': '2', 'unit_price': '100.00', 'line_amount': '200.00', 'tax_amount': '20.00', 'currency': None}], 'discount': None, 'shipping': None, 'credit': None, 'tax_inclusive': None}


def lines(data):
    return ['SYNTHETIC TEST INVOICE - NOT A REAL BILL'] + [f'{k}: {v}' for k, v in data.items() if k != 'line_items' and v is not None] + [f"Item: {i['description']} | {i['quantity']} | {i['unit_price']} | {i['line_amount']} | {i['tax_amount']}" for i in data['line_items']]


def pdf(path, data, pages=1):
    with pymupdf.open() as document:
        for index in range(pages):
            page = document.new_page()
            # Continuation pages retain evidence but do not repeat financial line items.
            page.insert_text((45, 50), '\n'.join(lines(data)) if index == 0 else f'SYNTHETIC continuation page {index + 1}\nNo additional financial entries.', fontsize=11)
        document.save(path)


def generate():
    ROOT.mkdir(exist_ok=True)
    truth = {}
    for filename, data in [('invoice.pdf', BASE), ('duplicate.pdf', BASE), ('incorrect-total.pdf', BASE | {'invoice_number': 'CG-2026-002', 'total': '250.00'}), ('missing-fields.pdf', BASE | {'invoice_number': 'CG-2026-003', 'customer_name': None}), ('multipage.pdf', BASE | {'invoice_number': 'CG-2026-004'})]:
        pdf(ROOT / filename, data, 3 if filename == 'multipage.pdf' else 1)
        truth[filename] = {'invoice': data, 'expected_processing': 'success', 'invalid_total': filename == 'incorrect-total.pdf'}
    # Exact checksum duplicate, separately from business duplicate rendering.
    (ROOT / 'duplicate.pdf').write_bytes((ROOT / 'invoice.pdf').read_bytes())
    image = Image.new('RGB', (1600, 2000), 'white')
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 28)
    except OSError:
        font = ImageFont.load_default(size=28)
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines(BASE)):
        draw.text((70, 80 + index * 60), line, font=font, fill='black')
    image.save(ROOT / 'invoice.png')
    image.save(ROOT / 'invoice.jpg')
    image.save(ROOT / 'multiframe.tiff', save_all=True, append_images=[image.copy()])
    low = image.resize((1000, 1250)).filter(ImageFilter.GaussianBlur(0.7))
    low.save(ROOT / 'low-quality.png')
    with pymupdf.open() as document:
        page = document.new_page(width=800, height=1000)
        page.insert_image(page.rect, filename=str(ROOT / 'invoice.png'))
        document.save(ROOT / 'scanned.pdf')
    for filename in ['invoice.png', 'invoice.jpg', 'multiframe.tiff', 'low-quality.png', 'scanned.pdf']:
        truth[filename] = {'invoice': BASE, 'expected_processing': 'success', 'ocr': True}
    headers = [k for k in BASE if k != 'line_items']
    record = BASE | {'total': '225.00'}
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = 'Accounting'
    sheet.append(headers)
    sheet.append([record[k] for k in headers])
    book.create_sheet('Notes').append(['SYNTHETIC TEST DATA ONLY'])
    book.save(ROOT / 'accounting.xlsx')
    legacy = xlwt.Workbook()
    legacy_sheet = legacy.add_sheet('Accounting')
    for col, header in enumerate(headers):
        legacy_sheet.write(0, col, header)
        if record[header] is not None:
            legacy_sheet.write(1, col, record[header])
    legacy.save(str(ROOT / 'accounting.xls'))
    for filename in ['accounting.xlsx', 'accounting.xls']:
        truth[filename] = {'invoice': record | {'line_items': []}, 'expected_processing': 'success', 'invalid_total': True}
    with (ROOT / 'invoice.csv').open('w', newline='', encoding='utf-8') as target:
        writer = csv.writer(target)
        writer.writerow(headers)
        writer.writerow([BASE[k] for k in headers])
    truth['invoice.csv'] = {'invoice': BASE | {'line_items': []}, 'expected_processing': 'success'}
    (ROOT / 'corrupted.pdf').write_bytes(b'%PDF-1.7\nThis file is deliberately corrupt')
    truth['corrupted.pdf'] = {'expected_processing': 'failure'}
    (ROOT / 'ground-truth.json').write_text(json.dumps({'label': 'SYNTHETIC FIXTURES', 'documents': truth}, indent=2), encoding='utf-8')
    print(f'Generated {len(truth)} synthetic labeled documents in {ROOT}')


if __name__ == '__main__':
    generate()
