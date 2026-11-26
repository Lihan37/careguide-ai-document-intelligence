from decimal import Decimal, InvalidOperation
import re
from .schemas import Invoice
from .validation import discount_magnitude, normalize, tolerance

FIELDS = ['invoice_number', 'invoice_date', 'supplier_name', 'customer_name', 'subtotal', 'tax', 'total', 'currency', 'line_items']
LINE_NUMBERS = ('quantity', 'unit_price', 'line_amount', 'tax_amount')
OPTIONAL_AMOUNTS = ('discount', 'shipping')


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


def line_descriptions(items):
    descriptions = [str(item.get('description') or '').strip() for item in items]
    prefixes = [re.match(r'^0*' + str(index) + r'\s+(\S.*)$', label)
                for index, label in enumerate(descriptions, 1)]
    stripped = [match[1] for match in prefixes] if len(items) > 1 and all(prefixes) else descriptions
    return list(map(normalize, descriptions)), list(map(normalize, stripped))


def line_items_match(left, right):
    if len(left) != len(right):
        return False
    left_names, left_without_numbers = line_descriptions(left)
    right_names, right_without_numbers = line_descriptions(right)
    if left_names != right_names and left_without_numbers != right_without_numbers:
        return False
    try:
        for a, b in zip(left, right):
            if a.get('currency') != b.get('currency'):
                return False
            for name in LINE_NUMBERS:
                a_value, b_value = a.get(name), b.get(name)
                if a_value is None or b_value is None:
                    if a_value != b_value:
                        return False
                elif Decimal(str(a_value)) != Decimal(str(b_value)):
                    return False
    except InvalidOperation:
        return False
    return True


def compare(left, right, left_evidence=None, right_evidence=None):
    results = []
    fields = [*FIELDS, *(field for field in OPTIONAL_AMOUNTS if left.get(field) is not None or right.get(field) is not None)]
    for field in fields:
        a, b, difference = left.get(field), right.get(field), None
        if a is None or b is None or (field == 'line_items' and (not a or not b)):
            status = 'MISSING'
        elif field in {'subtotal', 'tax', 'total', 'discount', 'shipping'}:
            left_amount, right_amount = Decimal(str(a)), Decimal(str(b))
            if field == 'discount':
                left_amount, right_amount = discount_magnitude(left_amount), discount_magnitude(right_amount)
            difference = right_amount - left_amount
            status = 'MATCHED' if left.get('currency') == right.get('currency') and abs(difference) <= tolerance(left.get('currency')) else 'MISMATCHED'
        elif field == 'line_items':
            status = 'MATCHED' if line_items_match(a, b) else 'REQUIRES_REVIEW'
        else:
            status = 'MATCHED' if normalize(a) == normalize(b) else 'MISMATCHED'
        results.append({'field': field, 'left': a, 'right': b, 'status': status, 'difference': str(difference) if difference is not None else None, 'left_source': (left_evidence or {}).get(field), 'right_source': (right_evidence or {}).get(field)})
    return results
