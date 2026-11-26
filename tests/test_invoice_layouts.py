"""Layout regressions: expectations live in tests, never in extraction code."""
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest

from app.extraction import demo_extract
from app.processing import units
from app.validation import validate
from app.invoice_parser import number


def parse(text):
    return demo_extract([{'document_id': 'regression', 'page': 1, 'method': 'text', 'text': text}])


def test_reported_synthetic_invoice():
    source = list(units(Path('sample-data/layout-invoice.pdf'), '.pdf'))
    source[0]['document_id'] = 'layout-regression'
    invoice, evidence, issues = demo_extract(source)
    assert invoice.invoice_number == 'CG-2026-001'
    assert invoice.invoice_date.isoformat() == '2026-11-26'
    assert invoice.supplier_name == 'Northstar Office Supplies Ltd.'
    assert invoice.customer_name == 'CareGuide Demo Operations'
    assert (invoice.subtotal, invoice.tax, invoice.total) == (Decimal('8500.00'), Decimal('850.00'), Decimal('9350.00'))
    assert invoice.currency == 'BDT'
    assert len(invoice.line_items) == 4
    assert [line.quantity for line in invoice.line_items] == [Decimal('2'), Decimal('3'), Decimal('4'), Decimal('5')]
    assert [line.line_amount for line in invoice.line_items] == [Decimal('2500'), Decimal('2550'), Decimal('2500'), Decimal('950')]
    assert all(line.tax_amount is None for line in invoice.line_items)
    assert issues == validate(invoice) == []
    assert evidence['total']['bbox'] and '9,350.00' in evidence['total']['excerpt']
    assert evidence['invoice_number']['document_id'] == 'layout-regression'
    assert len(evidence['line_items']['items']) == 4
    assert evidence['line_items']['items'][0]['unit_price']['bbox']


def test_layout_invoice_api_workflow(client):
    with Path('sample-data/layout-invoice.pdf').open('rb') as source:
        response = client.post('/api/documents/upload', files=[('files', ('layout-invoice.pdf', source, 'application/pdf'))])
    assert response.status_code == 202
    document_id = response.json()['results'][0]['document_id']
    record = client.get(f'/api/documents/{document_id}').json()
    assert record['status'] == 'COMPLETED'
    assert record['raw']['total'] == '9350.00'
    assert record['raw']['currency'] == 'BDT'
    assert len(record['raw']['line_items']) == 4
    assert record['evidence']['line_items']['items'][0]['quantity']['document_id'] == document_id
    assert client.get(f'/api/documents/{document_id}/validation').json() == {'outcome': 'PASSED', 'issues': []}


@pytest.mark.parametrize('headings', [
    ('Invoice No.', 'Issue Date', 'Bill From', 'Bill To', 'VAT (10%)', 'Grand Total'),
    ('Invoice Number', 'Invoice Date', 'Supplier', 'Customer', 'Tax', 'Total'),
    ('Invoice ID', 'Date Issued', 'Vendor', 'Sold To', 'Tax Amount', 'Total Amount'),
])
@pytest.mark.parametrize('separator', [': ', ' '])
def test_label_aliases_with_different_values(headings, separator):
    keys = list(headings[:4]) + ['Sub Total', headings[4], headings[5], 'Currency']
    values = ['RM-49', '2026-09-18', 'Rivermark Industrial', 'Demo Bluehaven', 'USD 25.00', 'USD 2.50', 'USD 27.50', 'USD (US Dollar)']
    text = '\n'.join(k + separator + v for k, v in zip(keys, values))
    text += '\nDescription | Quantity | Rate | Line Total\nSafety gloves | 2 | 12.50 | 25.00'
    invoice, evidence, issues = parse(text)
    assert invoice.invoice_number == 'RM-49'
    assert invoice.supplier_name == 'Rivermark Industrial'
    assert invoice.customer_name == 'Demo Bluehaven'
    assert invoice.currency == 'USD'
    assert invoice.total == Decimal('27.50')
    assert len(invoice.line_items) == 1 and invoice.line_items[0].quantity == 2
    assert not issues and not validate(invoice)
    assert 'RM-49' in evidence['invoice_number']['excerpt']


@pytest.mark.parametrize('table', [
    'Description | Qty | Unit Price | Amount\nGloves | 2 | 12.50 | 25.00',
    'Description\tQuantity\tRate\tLine Total\nGloves\t2\t12.50\t25.00',
    'Description   Quantity   Unit Price   Amount\nGloves   2   12.50   25.00',
    'Description Qty Unit Price Amount\nGloves 2 12.50 25.00',
    'DESCRIPTION\nQTY\nUNIT PRICE\nAMOUNT\nGloves\n2\n12.50\n25.00',
    'Amount | Description | Unit Price | Quantity\n25.00 | Gloves | 12.50 | 2',
])
def test_table_formats_and_reordered_columns(table):
    invoice, evidence, issues = parse(table + '\nSubtotal: 25.00\nTax: 2.50\nTotal: 27.50')
    assert not issues
    assert len(invoice.line_items) == 1
    line = invoice.line_items[0]
    assert (line.description, line.quantity, line.unit_price, line.line_amount) == ('Gloves', Decimal('2'), Decimal('12.50'), Decimal('25.00'))
    assert evidence['line_items']['items'][0]['description']['page'] == 1


def test_vertical_labels_and_distinct_due_date():
    text = 'INVOICE NUMBER\nISSUE DATE\nDUE DATE\nBL-734\n2026-08-19\n2026-09-19\nBILL FROM\nSilver Birch Ltd.\nBILL TO\nDemo Operations\nSubtotal\nEUR 1.234,50\nVAT (10%)\nEUR 123,45\nGrand Total\nEUR 1.357,95\nCurrency: EUR (Euro)'
    invoice, _, issues = parse(text)
    assert invoice.invoice_number == 'BL-734'
    assert invoice.invoice_date.isoformat() == '2026-08-19'
    assert invoice.supplier_name == 'Silver Birch Ltd.'
    assert invoice.customer_name == 'Demo Operations'
    assert invoice.subtotal == Decimal('1234.50')
    assert invoice.total == Decimal('1357.95')
    assert not issues


def test_compound_party_headings_and_annotated_summary_labels():
    invoice, evidence, issues = parse('''INVOICE DETAILS
Invoice Number: INV-941
Invoice Date: 2026-05-21
Bill From / Supplier: Juniper Paper
Bill To / Customer: Demo Finance
Description | Qty | Unit Price | Amount
Paper stock | 2 | 20.00 | 40.00
Subtotal (all items): USD 40.00
Discount (deduction): -USD 5.00
Delivery & handling: USD 3.00
VAT (10% on net amount): USD 3.50
Total Amount Due: USD 41.50''')
    assert (invoice.supplier_name, invoice.customer_name) == ('Juniper Paper', 'Demo Finance')
    assert (invoice.subtotal, invoice.discount, invoice.shipping, invoice.tax, invoice.total) == (
        Decimal('40.00'), Decimal('-5.00'), Decimal('3.00'), Decimal('3.50'), Decimal('41.50'),
    )
    assert '10% on net amount' in evidence['tax']['excerpt']
    assert not issues and not validate(invoice)


@pytest.mark.parametrize(('printed', 'expected'), [
    ('BDT 8,500.00', '8500.00'), ('1.234,56 EUR', '1234.56'),
    ('GBP 1 234.50', '1234.50'), ('(USD 20.00)', '-20.00'),
    ('12,34', '12.34'), ('10%', None), ('not provided', None),
    ('NaN', None), ('8,50,0.00', None), ('2 50', None),
])
def test_number_normalization_is_conservative(printed, expected):
    assert number(printed) == expected


def test_no_guessed_financial_values_or_default_currency():
    invoice, evidence, _ = parse('Invoice No: VOID-82\nDescription | Price | Amount\nGloves | 12.50 | 25.00\nVAT: 10%\nGrand Total: $27.50')
    assert invoice.subtotal is None
    assert invoice.tax is None
    assert invoice.currency is None
    assert invoice.invoice_date is None
    assert invoice.line_items[0].quantity is None
    assert invoice.line_items[0].tax_amount is None
    assert evidence['tax']['excerpt'] == 'VAT: 10%'


@pytest.mark.parametrize('text', [
    'Total: USD 100\nGrand Total: USD 200',
    'Subtotal: USD 100\nTax: EUR 10\nTotal: USD 110',
])
def test_conflicting_observations_require_review(text):
    invoice, evidence, issues = parse(text)
    field = 'total' if '200' in text else 'currency'
    assert getattr(invoice, field) is None
    assert evidence[field]['candidates']
    assert any(i['rule_id'] == 'ambiguous_' + field for i in issues)


def test_repeated_equivalent_totals_are_not_ambiguous():
    invoice, _, issues = parse('Total: USD 1,000.00\nGrand Total: USD 1000')
    assert invoice.total == Decimal('1000')
    assert not issues


def test_negative_line_values_remain_observed_values():
    invoice, _, issues = parse('Description | Quantity | Unit Price | Amount\nReturned gloves | -2 | 12.50 | -25.00')
    assert invoice.line_items[0].line_amount == Decimal('-25')
    assert not issues
    assert any(i['rule_id'] == 'line_1_negative' for i in validate(invoice))


def test_table_does_not_absorb_totals_as_items():
    invoice, _, _ = parse('Description | Qty | Price | Amount\nGloves | 2 | 12.50 | 25.00\nSubtotal | | | 25.00\nVAT | | | 2.50\nTotal | | | 27.50')
    assert len(invoice.line_items) == 1


def test_spreadsheet_line_table_retains_cell_evidence():
    invoice, evidence, issues = demo_extract([{'sheet': 'Items', 'text': 'Description | Qty | Rate | Amount\nGloves | 2 | 12.50 | 25.00', 'rows': [['Description', 'Qty', 'Rate', 'Amount'], ['Gloves', 2, '12.50', '25.00']]}])
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].quantity == 2
    assert evidence['line_items']['items'][0]['unit_price']['sheet'] == 'Items'
    assert evidence['line_items']['items'][0]['unit_price']['row'] == 2
    assert evidence['line_items']['items'][0]['unit_price']['column'] == 3
    assert not issues


def test_missing_table_cell_is_not_calculated():
    invoice, _, _ = parse('Description | Qty | Rate | Amount\nGloves | 2 | 12.50 | ')
    assert invoice.line_items[0].line_amount is None


def test_malformed_table_number_preserves_evidence_and_review():
    invoice, evidence, issues = parse('Description | Qty | Rate | Amount\nGloves | 2 | oops | 25.00')
    assert invoice.line_items[0].unit_price is None
    assert evidence['line_items']['items'][0]['unit_price']['excerpt'].endswith('25.00')
    assert any(i['rule_id'] == 'invalid_line_1_unit_price' for i in issues)


@pytest.mark.parametrize(('printed', 'expected'), [('26/11/2026', '2026-11-26'), ('11/26/2026', '2026-11-26'), ('18 Sep 2026', '2026-09-18'), ('02/03/2026', None)])
def test_dates_do_not_guess_ambiguous_locale(printed, expected):
    invoice, _, _ = parse('Issue Date: ' + printed)
    assert (invoice.invoice_date.isoformat() if invoice.invoice_date else None) == expected


def test_shuffled_pdf_drawing_order_uses_coordinates(tmp_path):
    path = tmp_path / 'different-layout.pdf'
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        # Deliberately draw values before headings and right column before left.
        for x, y, text in [
            (320, 92, '2026-07-29'), (40, 92, 'AX-982'),
            (320, 70, 'Issue Date'), (40, 70, 'Invoice No'),
            (320, 150, 'Bill To'), (40, 150, 'Supplier'),
            (320, 172, 'Demo Horizon Group'), (40, 172, 'Aspen Equipment'),
            (40, 230, 'Description'), (260, 230, 'Qty'), (340, 230, 'Rate'), (440, 230, 'Amount'),
            (40, 252, 'Safety gloves'), (260, 252, '2'), (340, 252, '12.50'), (440, 252, '25.00'),
            (320, 300, 'Subtotal'), (440, 300, 'CAD 25.00'),
            (320, 322, 'Tax'), (440, 322, 'CAD 2.50'),
            (320, 344, 'Grand Total'), (440, 344, 'CAD 27.50'),
        ]:
            page.insert_text((x, y), text, fontsize=10)
        pdf.save(path)
    invoice, evidence, issues = demo_extract(list(units(path, '.pdf')))
    assert invoice.invoice_number == 'AX-982'
    assert invoice.supplier_name == 'Aspen Equipment'
    assert invoice.customer_name == 'Demo Horizon Group'
    assert invoice.currency == 'CAD'
    assert invoice.total == Decimal('27.50')
    assert len(invoice.line_items) == 1
    assert evidence['customer_name']['bbox'][0] == 320
    assert not issues and not validate(invoice)
