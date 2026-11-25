from decimal import Decimal
from .schemas import Invoice
from .validation import normalize, tolerance

FIELDS = ['invoice_number', 'invoice_date', 'supplier_name', 'customer_name', 'subtotal', 'tax', 'total', 'currency', 'line_items']


def mapped_invoice(source, mapping, row=2):
    rows = source.get('rows', [])
    if not rows or row < 2 or row > len(rows):
        raise ValueError('Choose a valid spreadsheet data row (first data row is 2)')
    data, evidence = {}, {}
    for field, header in mapping.items():
        if field not in Invoice.model_fields or field == 'line_items' or header not in [str(v) for v in rows[0]]:
            raise ValueError('Unknown invoice field or spreadsheet column')
        column = [str(v) for v in rows[0]].index(header)
        value = rows[row - 1][column] if column < len(rows[row - 1]) else None
        data[field] = value if value != '' else None
        evidence[field] = {'document_id': source['document_id'], 'sheet': source['sheet'], 'row': row, 'column': column + 1, 'excerpt': str(value)}
    return Invoice.model_validate(data).model_dump(mode='json'), evidence


def compare(left, right, left_evidence=None, right_evidence=None):
    results = []
    for field in FIELDS:
        a, b, difference = left.get(field), right.get(field), None
        if a is None or b is None or (field == 'line_items' and (not a or not b)):
            status = 'MISSING'
        elif field in {'subtotal', 'tax', 'total'}:
            difference = Decimal(str(b)) - Decimal(str(a))
            status = 'MATCHED' if left.get('currency') == right.get('currency') and abs(difference) <= tolerance(left.get('currency')) else 'MISMATCHED'
        elif field == 'line_items':
            status = 'MATCHED' if a == b else 'REQUIRES_REVIEW'
        else:
            status = 'MATCHED' if normalize(a) == normalize(b) else 'MISMATCHED'
        results.append({'field': field, 'left': a, 'right': b, 'status': status, 'difference': str(difference) if difference is not None else None, 'left_source': (left_evidence or {}).get(field), 'right_source': (right_evidence or {}).get(field)})
    return results
