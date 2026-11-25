"""Tax labels must identify printed amounts without deriving amounts from rates."""
from decimal import Decimal
from pathlib import Path

import pytest
import pymupdf

from app.extraction import demo_extract
from app.invoice_parser import label_pair
from app.processing import units
from app.validation import validate


LABELS = ['Tax', 'VAT', 'VAT (10%)', 'Tax (VAT 10%)', 'Sales Tax', 'GST', 'Tax Amount']


@pytest.mark.parametrize('label', LABELS)
@pytest.mark.parametrize('separator', [': ', '    ', '\n'])
def test_printed_tax_amount_across_labels_and_text_layouts(label, separator):
    text = 'TAX INVOICE\n' + label + separator + 'BDT 7.89'
    invoice, evidence, issues = demo_extract([{'page': 2, 'text': text, 'method': 'text'}])
    assert invoice.tax == Decimal('7.89')
    assert invoice.currency == 'BDT'
    assert not issues
    assert label in evidence['tax']['excerpt']
    assert '7.89' in evidence['tax']['excerpt']
    assert evidence['tax']['page'] == 2


@pytest.mark.parametrize('label', ['Tax (VAT 7.5%)', 'GST (5%)', 'Sales Tax (8,25%)', 'Tax Amount (VAT @ 12%)', 'tax(vat 10%)', 'VAT (at 10%)'])
def test_compound_rates_are_labels_not_financial_values(label):
    # Amount deliberately does not equal a rate-derived result.
    invoice, _, issues = demo_extract([{'text': f'{label}: EUR 3.75\nSubtotal: EUR 40.00'}])
    assert invoice.tax == Decimal('3.75')
    assert not issues


@pytest.mark.parametrize('label', LABELS)
def test_label_without_printed_amount_does_not_fabricate_tax(label):
    invoice, _, _ = demo_extract([{'text': f'{label}\nSubtotal: BDT 100.00\nGrand Total: BDT 110.00'}])
    assert invoice.tax is None


@pytest.mark.parametrize('title', ['TAX INVOICE', 'VAT INVOICE', 'GST INVOICE', 'Sales Tax Invoice'])
def test_invoice_titles_do_not_become_invalid_tax_candidates(title):
    assert label_pair(title) == (None, '')
    invoice, evidence, issues = demo_extract([{'text': title + '\nSubtotal: BDT 100.00'}])
    assert invoice.tax is None and 'tax' not in evidence
    assert not issues
    assert any(issue['rule_id'] == 'required_tax' for issue in validate(invoice))


def test_parenthesized_value_is_not_removed_or_calculated():
    invoice, evidence, issues = demo_extract([{'text': 'Tax: (BDT 12.50)'}])
    assert invoice.tax == Decimal('-12.50')
    assert evidence['tax']['excerpt'] == 'Tax: (BDT 12.50)'
    assert not issues
    rate_only, _, _ = demo_extract([{'text': 'Tax: (10%)\nSubtotal: BDT 100'}])
    assert rate_only.tax is None


def test_invalid_tax_value_still_requires_review():
    invoice, evidence, issues = demo_extract([{'text': 'Tax (VAT 10%): pending'}])
    assert invoice.tax is None
    assert evidence['tax']['excerpt'].endswith('pending')
    assert any(issue['rule_id'] == 'invalid_tax' for issue in issues)


def test_conflicting_tax_amounts_still_require_review():
    invoice, evidence, issues = demo_extract([{'text': 'VAT (10%): BDT 5.00\nSales Tax: BDT 6.00'}])
    assert invoice.tax is None and evidence['tax']['candidates']
    assert any(issue['rule_id'] == 'ambiguous_tax' for issue in issues)


@pytest.mark.parametrize('label', LABELS)
def test_spreadsheet_header_uses_same_tax_label_normalization(label):
    invoice, evidence, issues = demo_extract([{'sheet': 'Invoices', 'text': '', 'rows': [['Invoice No', label, 'Total'], ['REG-93', '7.89', '47.89']]}])
    assert invoice.tax == Decimal('7.89')
    assert evidence['tax']['column'] == 2 and evidence['tax']['row'] == 2
    assert not issues


def test_line_tax_header_keeps_line_and_invoice_tax_separate():
    invoice, evidence, issues = demo_extract([{'sheet': 'Items', 'text': '', 'rows': [['Description', 'Qty', 'Rate', 'Amount', 'GST (5%)'], ['Gloves', '2', '10', '20', '1']]}])
    assert invoice.tax is None
    assert invoice.line_items[0].tax_amount == Decimal('1')
    assert evidence['line_items']['items'][0]['tax_amount']['column'] == 5
    assert not issues


@pytest.mark.parametrize('label', LABELS)
def test_positioned_tax_labels_use_adjacent_amount_and_retain_evidence(label, tmp_path):
    path = tmp_path / 'tax-label.pdf'
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), 'TAX INVOICE', fontsize=20)
        page.insert_text((40, 100), label, fontsize=10)
        page.insert_text((260, 100), 'BDT 7.89', fontsize=10)
        # Exercise digital-PDF parsing, not the sparse-page OCR fallback.
        page.insert_text((40, 180), 'SYNTHETIC DIGITAL PDF REGRESSION FIXTURE', fontsize=10)
        pdf.save(path)
    invoice, evidence, issues = demo_extract(list(units(path, '.pdf')))
    assert invoice.tax == Decimal('7.89')
    assert label in evidence['tax']['excerpt']
    assert evidence['tax']['bbox'][0] == 260
    assert evidence['tax']['label_bbox'][0] == 40
    assert not issues


def test_existing_invoice_spreadsheet_alias_is_preserved():
    invoice, _, issues = demo_extract([{'sheet': 'Invoices', 'text': '', 'rows': [['Invoice', 'Supplier', 'Total'], ['REG-93', 'Lotus Demo', '47.89']]}])
    assert invoice.invoice_number == 'REG-93' and invoice.total == Decimal('47.89')
    assert not issues


def test_explicit_zero_tax_is_not_treated_as_missing():
    invoice, _, issues = demo_extract([{'text': 'GST (0%): BDT 0.00'}])
    assert invoice.tax == Decimal('0.00')
    assert not issues


def test_second_invoice_api_validation(client):
    with Path('sample-data/tax-layout-invoice.pdf').open('rb') as source:
        response = client.post('/api/documents/upload', files=[('files', ('tax-layout-invoice.pdf', source, 'application/pdf'))])
    assert response.status_code == 202
    document_id = response.json()['results'][0]['document_id']
    record = client.get(f'/api/documents/{document_id}').json()
    assert record['raw']['tax'] == '965.00'
    assert len(record['raw']['line_items']) == 4
    assert client.get(f'/api/documents/{document_id}/validation').json() == {'outcome': 'PASSED', 'issues': []}


def test_second_uploaded_synthetic_pdf_retains_all_fields_and_four_items():
    invoice, evidence, issues = demo_extract(list(units(Path('sample-data/tax-layout-invoice.pdf'), '.pdf')))
    assert invoice.invoice_number == 'EDS-INV-2026-042'
    assert invoice.invoice_date.isoformat() == '2026-11-25'
    assert invoice.supplier_name == 'Eastern Digital Solutions Ltd.'
    assert invoice.customer_name == 'CareGuide Demo Operations'
    assert (invoice.subtotal, invoice.tax, invoice.total) == (Decimal('9650.00'), Decimal('965.00'), Decimal('10615.00'))
    assert invoice.currency == 'BDT'
    assert len(invoice.line_items) == 4
    assert [item.quantity for item in invoice.line_items] == [Decimal('2'), Decimal('3'), Decimal('1'), Decimal('4')]
    assert [item.line_amount for item in invoice.line_items] == [Decimal('2900'), Decimal('2250'), Decimal('2800'), Decimal('1700')]
    assert all(item.quantity * item.unit_price == item.line_amount for item in invoice.line_items)
    assert sum((item.line_amount for item in invoice.line_items), Decimal(0)) == invoice.subtotal
    assert invoice.subtotal + invoice.tax == invoice.total
    assert 'Tax (VAT 10%)' in evidence['tax']['excerpt']
    assert evidence['tax']['bbox'] and '965.00' in evidence['tax']['excerpt']
    assert issues == validate(invoice) == []
