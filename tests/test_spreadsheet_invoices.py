from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

import openpyxl
import pymupdf

from app.extraction import demo_extract
from app.processing import units
from app.validation import validate


def parse(path):
    return demo_extract(list(units(path, '.xlsx')))


def layout_workbook(path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Sales Invoice'
    sheet.merge_cells('B2:H2')
    sheet['B2'] = 'Operations Invoice'
    sheet.merge_cells('B4:C4')
    for cell, value in {
        'B4': 'Invoice No', 'D4': 'TS-481', 'E4': 'Seller', 'F4': 'Juniper Paper', 'G4': 'Buyer', 'H4': 'Atlas Demo',
        'B5': 'Date', 'D5': date(2026, 5, 12),
        'B8': 'Qty', 'D8': 'Description', 'F8': 'Line Total (USD)', 'H8': 'Unit Price (USD)',
        'B9': 2, 'D9': 'Paper stock', 'F9': 25, 'H9': 12.50,
        'B10': 3, 'D10': 'Shipping envelopes', 'F10': 15, 'H10': 5,
        'F12': 'Subtotal', 'H12': 40,
        'F13': 'Discount', 'H13': -5,
        'F14': 'Shipping', 'H14': 3,
        'F15': 'VAT (10% after discount)', 'G15': 'USD', 'H15': 3.50,
        'F16': 'Amount Due', 'H16': 41.50,
    }.items():
        sheet[cell] = value
    sheet['H13'].number_format = '#,##0.00;[Red](#,##0.00)'
    workbook.save(path)


def test_statement_layout_uses_cells_and_preserves_merged_positions(tmp_path):
    path = tmp_path / 'layout.xlsx'
    layout_workbook(path)
    invoice, evidence, issues = parse(path)
    assert invoice.invoice_number == 'TS-481' and invoice.invoice_date == date(2026, 5, 12)
    assert (invoice.supplier_name, invoice.customer_name, invoice.currency) == ('Juniper Paper', 'Atlas Demo', 'USD')
    assert (invoice.subtotal, invoice.discount, invoice.shipping, invoice.tax, invoice.total) == (
        Decimal('40'), Decimal('-5'), Decimal('3'), Decimal('3.50'), Decimal('41.50'),
    )
    assert evidence['invoice_number']['cell'] == 'D4' and evidence['invoice_number']['label_cell'] == 'B4'
    assert evidence['supplier_name']['excerpt'] == 'Juniper Paper'
    assert evidence['discount']['number_format'] == '#,##0.00;[Red](#,##0.00)'
    assert (evidence['tax']['sheet'], evidence['tax']['row'], evidence['tax']['column']) == ('Sales Invoice', 15, 8)
    assert [item.line_amount for item in invoice.line_items] == [Decimal('25'), Decimal('15')]
    item = evidence['line_items']['items'][0]
    assert {field: source['cell'] for field, source in item.items()} == {
        'quantity': 'B9', 'description': 'D9', 'line_amount': 'F9', 'unit_price': 'H9',
    }
    assert not issues and not validate(invoice)


def cache_values(path, entry, values):
    # Openpyxl creates formulas without a cache. Simulate stored Excel results in OOXML.
    with ZipFile(path) as source:
        files = {name: source.read(name) for name in source.namelist()}
    tree = ElementTree.fromstring(files[entry])
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    for cell in tree.iter(ns + 'c'):
        if cell.attrib['r'] in values:
            cell.find(ns + 'v').text = values[cell.attrib['r']]
    files[entry] = ElementTree.tostring(tree, encoding='utf-8')
    with ZipFile(path, 'w') as target:
        for name, content in files.items():
            target.writestr(name, content)


def test_separate_worksheets_and_cached_formula_evidence(tmp_path):
    path = tmp_path / 'separate.xlsx'
    workbook = openpyxl.Workbook()
    cover = workbook.active
    cover.title = 'Cover'
    cover.append(['Invoice Number', 'Date', 'Seller', 'Buyer', 'Currency'])
    cover.append(['F-908', date(2026, 6, 15), 'Delta Demo', 'Mercury Demo', 'EUR'])
    items = workbook.create_sheet('Items')
    items.append(['Shipment contents'])
    items.append([None, 'Item Name', 'Unit Price (EUR)', 'Quantity', 'Extended Amount (EUR)'])
    items.append([None, 'Valve', 5.50, 2, '=C3*D3'])
    items.append([None, 'Hose', 4, 1, '=C4*D4'])
    summary = workbook.create_sheet('Totals')
    summary.append(['Subtotal', 15])
    summary.append(['Tax', '=0'])
    summary.append(['Shipping', '=B1-B1'])  # no cached value
    summary.append(['Grand Total', '=B1+B2'])
    workbook.save(path)
    cache_values(path, 'xl/worksheets/sheet2.xml', {'E3': '11'})
    cache_values(path, 'xl/worksheets/sheet3.xml', {'B2': '0', 'B4': '15'})

    invoice, evidence, issues = parse(path)
    assert invoice.invoice_number == 'F-908' and invoice.invoice_date == date(2026, 6, 15)
    assert invoice.tax == Decimal('0') and invoice.total == Decimal('15')
    assert invoice.shipping is None and invoice.line_items[1].line_amount is None
    assert (evidence['total']['sheet'], evidence['total']['cell'], evidence['total']['formula'], evidence['total']['cached_value']) == (
        'Totals', 'B4', '=B1+B2', 15,
    )
    assert (evidence['shipping']['cell'], evidence['shipping']['cached_value']) == ('B3', None)
    second_line = evidence['line_items']['items'][1]['line_amount']
    assert second_line['sheet'] == 'Items' and second_line['cell'] == 'E4' and second_line['cached_value'] is None
    assert {issue['rule_id'] for issue in issues} == {'uncached_line_formula', 'uncached_formula_shipping'}


def test_conflicting_cells_stay_null_and_percent_is_not_an_amount(tmp_path):
    path = tmp_path / 'conflict.xlsx'
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet['A1'] = 'Subtotal'
    sheet['B1'] = 100
    sheet['A2'] = 'VAT'
    sheet['B2'] = .10
    sheet['B2'].number_format = '0%'
    sheet['A3'] = 'Total'
    sheet['B3'] = 110
    other = workbook.create_sheet('Reconciliation')
    other.append(['Grand Total', 120])
    workbook.save(path)
    invoice, evidence, issues = parse(path)
    assert invoice.tax is None and invoice.total is None
    assert evidence['tax']['cell'] == 'B2' and evidence['tax']['percentage'] is True
    assert [(ref['sheet'], ref['cell']) for ref in evidence['total']['candidates']] == [('Sheet', 'B3'), ('Reconciliation', 'B1')]
    assert {issue['rule_id'] for issue in issues} == {'invalid_tax', 'ambiguous_total'}


def test_pdf_and_xlsx_compare_amounts_and_cell_evidence(client, tmp_path):
    path = tmp_path / 'layout.xlsx'
    layout_workbook(path)
    spreadsheet = client.post('/api/documents/upload', files={'files': (path.name, path.read_bytes())})
    spreadsheet_id = spreadsheet.json()['results'][0]['document_id']
    assert client.get(f'/api/documents/{spreadsheet_id}/validation').json() == {'outcome': 'PASSED', 'issues': []}
    content = ('Invoice Number: TS-481\nInvoice Date: 2026-05-12\nSupplier: Juniper Paper\nCustomer: Atlas Demo\n'
               'Currency: USD\nSubtotal: 40.00\nDiscount: 5.00\nShipping: 3.00\nVAT: 3.50\nAmount Due: 41.50\n'
               'Item: 01 Paper stock | 2 | 12.500 | 25.00\nItem: 02 Shipping envelopes | 3 | 5.00 | 15.00')
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 50), content)
        digital = client.post('/api/documents/upload', files={'files': ('layout.pdf', BytesIO(pdf.tobytes()))})
    digital_id = digital.json()['results'][0]['document_id']
    comparison = client.post('/api/comparisons', json={'document_ids': [digital_id, spreadsheet_id]})
    comparison.raise_for_status()
    fields = {field['field']: field for field in comparison.json()['results'][0]['fields']}
    assert all(field['status'] == 'MATCHED' for field in fields.values()), fields
    assert fields['total']['left_source']['page'] == 1 and fields['total']['right_source']['cell'] == 'H16'
    assert fields['line_items']['right_source']['items'][1]['unit_price']['cell'] == 'H10'
