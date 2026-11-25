from decimal import Decimal
from types import SimpleNamespace
import pytest
from app.schemas import Invoice
from app.validation import validate, duplicates
from app.comparison import compare, mapped_invoice
from scripts.generate_samples import BASE


def test_exact_arithmetic():
    assert validate(Invoice.model_validate(BASE)) == []
    issues = validate(Invoice.model_validate(BASE | {'total': '230'}))
    assert any(i['rule_id'] == 'total' and i['difference'] == '10.00' for i in issues)


def test_adjustments():
    assert validate(Invoice.model_validate(BASE | {'discount': '10', 'shipping': '5', 'credit': '2', 'total': '213'})) == []


def test_tax_inclusive():
    assert validate(Invoice.model_validate(BASE | {'tax_inclusive': True, 'total': '200'})) == []


@pytest.mark.parametrize('value', ['NaN', 'Infinity', 'not money'])
def test_bad_numbers(value):
    with pytest.raises(ValueError):
        Invoice(total=value)


def test_missing_and_line_mismatch():
    assert any(i['rule_id'] == 'required_total' for i in validate(Invoice()))
    data = BASE | {'line_items': [BASE['line_items'][0] | {'quantity': '3'}]}
    assert any(i['rule_id'] == 'line_1_amount' for i in validate(Invoice.model_validate(data)))


def test_duplicate_supplier_scope():
    a = SimpleNamespace(id='a', checksum='a')
    b = SimpleNamespace(id='b', checksum='b', raw=BASE, corrected={})
    assert duplicates(a, [b], BASE)
    assert not duplicates(a, [b], BASE | {'supplier_name': 'Unrelated supplier'})
    b.checksum = 'a'
    assert duplicates(a, [b], {})[0]['rule_id'] == 'exact_file_duplicate'


def test_pdf_pdf_and_excel_compare():
    assert next(f for f in compare(BASE, BASE | {'total': '225'}) if f['field'] == 'total')['difference'] == '5.00'
    source = {'document_id': 'x', 'sheet': 'ledger', 'rows': [['Invoice', 'Amount'], ['CG-2026-001', '225']]}
    data, evidence = mapped_invoice(source, {'invoice_number': 'Invoice', 'total': 'Amount'})
    assert evidence['total']['row'] == 2
    assert next(f for f in compare(BASE, data) if f['field'] == 'total')['status'] == 'MISMATCHED'
