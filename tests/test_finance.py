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


@pytest.mark.parametrize(('discount', 'shipping', 'tax', 'credit', 'total'), [
    (None, None, '20.00', None, '220.00'),
    ('10.00', None, '20.00', None, '210.00'),
    ('-10.00', None, '20.00', None, '210.00'),
    ('-10.00', '5.00', '0.00', None, '195.00'),
    ('-10.00', '5.00', '19.00', None, '214.00'),
    ('-10.00', '5.00', '19.00', '2.00', '212.00'),
    (None, None, '20.00', '2.00', '218.00'),
    ('-0.00', '0.00', '20.00', '0.00', '220.00'),
])
def test_discounts_reconcile_with_vat_shipping_and_credit(discount, shipping, tax, credit, total):
    line = BASE['line_items'][0] | {'tax_amount': tax}
    invoice = Invoice.model_validate(BASE | {
        'discount': discount, 'shipping': shipping, 'tax': tax, 'credit': credit,
        'total': total, 'line_items': [line],
    })
    assert validate(invoice) == []


@pytest.mark.parametrize('wrong_total', ['200.00', '230.00'])
def test_signed_discount_rejects_double_reduction_and_wrong_sign(wrong_total):
    invoice = Invoice.model_validate(BASE | {'discount': '-10.00', 'total': wrong_total})
    issue, = validate(invoice)
    assert issue['rule_id'] == 'total' and issue['severity'] == 'FAILED'
    assert issue['expected'] == '210.00'


def test_signs_of_negative_line_shipping_and_credit_are_preserved():
    return_line = {'description': 'Returned item', 'quantity': '-1', 'unit_price': '10.00',
                   'line_amount': '-10.00', 'tax_amount': '-1.00'}
    invoice = Invoice.model_validate(BASE | {
        'subtotal': '190.00', 'tax': '19.00', 'shipping': '-5.00', 'credit': '-2.00',
        'discount': '-10.00', 'total': '196.00', 'line_items': [*BASE['line_items'], return_line],
    })
    assert [(issue['rule_id'], issue['severity']) for issue in validate(invoice)] == [
        ('negative_shipping', 'WARNING'), ('negative_credit', 'WARNING'), ('line_2_negative', 'WARNING'),
    ]


def test_zero_invoice_with_signed_zero_discount():
    invoice = Invoice.model_validate(BASE | {
        'subtotal': '0.00', 'tax': '0.00', 'discount': '-0.00', 'total': '0.00',
        'line_items': [BASE['line_items'][0] | {'unit_price': '0.00', 'line_amount': '0.00', 'tax_amount': '0.00'}],
    })
    assert validate(invoice) == []


def test_tax_inclusive():
    assert validate(Invoice.model_validate(BASE | {'tax_inclusive': True, 'total': '200'})) == []
    assert validate(Invoice.model_validate(BASE | {'tax_inclusive': True, 'discount': '-10.00', 'total': '190'})) == []


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


@pytest.mark.parametrize(('right_discount', 'right_currency', 'status', 'difference'), [
    ('-10.00', 'USD', 'MATCHED', '0.00'),
    ('-12.00', 'USD', 'MISMATCHED', '2.00'),
    ('-10.00', 'BDT', 'MISMATCHED', '0.00'),
    (None, 'USD', 'MISSING', None),
])
def test_comparison_uses_discount_magnitude_and_keeps_original_sign(right_discount, right_currency, status, difference):
    source = {'document_id': 'x', 'sheet': 'ledger', 'rows': [['Discount', 'Currency'], [right_discount, right_currency]]}
    mapped, evidence = mapped_invoice(source, {'discount': 'Discount', 'currency': 'Currency'})
    field = next(f for f in compare(BASE | {'discount': '10.00'}, mapped, right_evidence=evidence) if f['field'] == 'discount')
    assert (field['status'], field['difference']) == (status, difference)
    assert (field['left'], field['right']) == ('10.00', right_discount)
    assert field['right_source']['sheet'] == 'ledger'
