import re
from decimal import Decimal
from .schemas import Invoice


def tolerance(currency):
    # Currency precision, expressed as exact decimals; unknown currencies use cents.
    from .config import settings
    return Decimal(settings().currency_tolerances.get(currency, '0.01'))


def discount_magnitude(discount: Decimal | None) -> Decimal:
    """Both a positive discount and a signed negative discount reduce the total."""
    return discount.copy_abs() if discount is not None else Decimal(0)


def validate(invoice: Invoice):
    issues = []
    tol = tolerance(invoice.currency)

    def issue(rule, severity, explanation, expected=None, actual=None):
        issues.append({'rule_id': rule, 'severity': severity, 'explanation': explanation, 'expected': str(expected) if expected is not None else None, 'actual': str(actual) if actual is not None else None, 'difference': str(actual - expected) if isinstance(actual, Decimal) and isinstance(expected, Decimal) else None})

    def reconcile(rule, expected, actual):
        if abs(expected - actual) > tol:
            issue(rule, 'FAILED', 'Arithmetic differs beyond currency tolerance', expected, actual)

    for name in ('invoice_number', 'invoice_date', 'supplier_name', 'customer_name', 'subtotal', 'tax', 'total', 'currency'):
        if getattr(invoice, name) is None:
            issue('required_' + name, 'REQUIRES_REVIEW', 'Required field is missing or invalid')
    if invoice.invoice_number and not re.search(r'\w', invoice.invoice_number):
        issue('invoice_number', 'REQUIRES_REVIEW', 'Invoice number has no letters or digits')
    for name in ('subtotal', 'tax', 'total', 'shipping', 'credit'):
        value = getattr(invoice, name)
        if value is not None and value < 0:
            issue('negative_' + name, 'WARNING', 'Negative amount may be a legitimate credit; reviewer must confirm', actual=value)
    amounts, taxes = [], []
    for i, item in enumerate(invoice.line_items):
        if any(value is not None and value < 0 for value in (item.quantity, item.unit_price, item.line_amount, item.tax_amount)):
            issue(f'line_{i + 1}_negative', 'WARNING', 'Negative line may be a credit or return; confirm with source')
        if item.quantity is not None and item.unit_price is not None and item.line_amount is not None:
            reconcile(f'line_{i + 1}_amount', item.quantity * item.unit_price, item.line_amount)
        if item.line_amount is not None:
            amounts.append(item.line_amount)
        if item.tax_amount is not None:
            taxes.append(item.tax_amount)
        if item.currency and item.currency != invoice.currency:
            issue(f'line_{i + 1}_currency', 'FAILED', 'Line currency differs from invoice currency')
    if amounts and len(amounts) == len(invoice.line_items) and invoice.subtotal is not None:
        reconcile('subtotal', sum(amounts, Decimal(0)), invoice.subtotal)
    if taxes and len(taxes) == len(invoice.line_items) and invoice.tax is not None:
        reconcile('tax', sum(taxes, Decimal(0)), invoice.tax)
    if invoice.subtotal is not None and invoice.tax is not None and invoice.total is not None:
        tax_to_add = Decimal(0) if invoice.tax_inclusive else invoice.tax
        shipping = invoice.shipping or Decimal(0)
        credit = invoice.credit or Decimal(0)
        expected = invoice.subtotal + tax_to_add + shipping - discount_magnitude(invoice.discount) - credit
        reconcile('total', expected, invoice.total)
    if not invoice.line_items:
        issue('line_items_missing', 'WARNING', 'No line items extracted; subtotal-to-lines check unavailable')
    return issues


def normalize(value):
    return re.sub(r'[^\w]', '', str(value or '').casefold())


def duplicates(document, others, effective):
    found = []
    for other in others:
        if other.id == document.id:
            continue
        b = other.raw | other.corrected
        exact = document.checksum == other.checksum
        same_business = bool(effective.get('supplier_name') and effective.get('invoice_number') and normalize(effective.get('supplier_name')) == normalize(b.get('supplier_name')) and normalize(effective.get('invoice_number')) == normalize(b.get('invoice_number')))
        if exact or same_business:
            found.append({'rule_id': 'exact_file_duplicate' if exact else 'potential_invoice_duplicate', 'severity': 'WARNING', 'explanation': 'Exact file checksum match' if exact else 'Supplier and invoice number match; confirm date, total and currency', 'related_document_id': other.id, 'matching_fields': [k for k in ('invoice_date', 'total', 'currency') if effective.get(k) is not None and effective.get(k) == b.get(k)]})
    return found
