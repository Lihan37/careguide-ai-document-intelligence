"""Verify invoice header facts against the source layout before trusting a model's mapping."""
import re

from openpyxl.utils.cell import get_column_letter

from .invoice_parser import (CODES, CURRENCY_SYMBOL, MONETARY, PARTY_FIELDS, QUALIFIED_CURRENCY,
                             header_currency, label_pair, normalized, number, table_header, visual_rows)


SOURCE_KEYS = ('document_id', 'page', 'sheet', 'method', 'ocr_confidence')
VERIFIED_FIELDS = PARTY_FIELDS | {'invoice_date', 'currency'}
ISO_AMOUNT = re.compile(r'(?<![A-Z])(?:[A-Z]{3})(?![A-Z])')
AMBIGUOUS_SYMBOL = re.compile(r'[$£¥]')
CURRENCY_NAMES = {
    'us dollars': 'USD', 'united states dollars': 'USD', 'canadian dollars': 'CAD',
    'australian dollars': 'AUD', 'new zealand dollars': 'NZD', 'euros': 'EUR',
    'pounds sterling': 'GBP', 'british pounds': 'GBP', 'japanese yen': 'JPY',
    'chinese yuan': 'CNY', 'indian rupees': 'INR', 'bangladeshi taka': 'BDT',
}


def source_label(text):
    # Treat the short heading as a role only when it is visibly a label.
    match = re.fullmatch(r'from(?:\s*:\s*(.*))?', text.strip(), re.IGNORECASE)
    return ('supplier_name', match[1] or '') if match else label_pair(text)


def field_value(field, text):
    if field in PARTY_FIELDS:
        if (len(text) > 255 or source_label(text)[0] or not any(char.isalpha() for char in text)
                or re.search(r'@|https?://|^\d+\s|^(?:address|phone|account|email|contact)\b', text, re.IGNORECASE)):
            return None
    return normalized(field, text)


def rows_with_locations(unit):
    if 'rows' in unit:
        return [[{'text': str(value).strip(), 'row': row, 'column': col,
                  'cell': f'{get_column_letter(col)}{row}'}
                 for col, value in enumerate(values, 1) if value is not None and str(value).strip()]
                for row, values in enumerate(unit['rows'], 1)]
    return [row['cells'] for row in visual_rows(unit)]


def neighboring_value(rows, row, column, label, field):
    right = rows[row][column + 1:column + 2]
    if 'bbox' in label:
        x0, y0, x1, y1 = label['bbox']
        height = y1 - y0
        right = [cell for cell in right if cell['bbox'][0] - x1 <= max(36, 3 * height)]
        next_rows = ([cell for cell in cells if abs(cell['bbox'][0] - x0) <= max(12, 1.3 * height)
                      and 0 < cell['bbox'][1] - y0 <= max(45, 3 * height)]
                     for cells in rows[row + 1:row + 4])
    else:
        next_rows = ([cell for cell in cells if cell['column'] == label['column']]
                     for cells in rows[row + 1:row + 2])
    if right and not source_label(right[0]['text'])[0] and field_value(field, right[0]['text']) is not None:
        return right[0]
    below = next((cells for cells in next_rows if cells), [])
    if len(below) == 1 and not source_label(below[0]['text'])[0]:
        return below[0]
    return None


def labeled_values(unit, rows):
    for row, cells in enumerate(rows):
        for column, label in enumerate(cells):
            field, inline = source_label(label['text'])
            if field not in VERIFIED_FIELDS | MONETARY:
                continue
            if inline:
                yield field, inline, label, label
            elif field in MONETARY and (right := cells[column + 1:column + 3]) and len(right) == 2 and (
                    currency_markers(right[0]['text'], labeled=True) and number(right[1]['text']) is not None):
                yield field, right[0]['text'] + ' ' + right[1]['text'], label, right[0] | {
                    'text': right[0]['text'] + ' ' + right[1]['text'],
                }
            elif value := neighboring_value(rows, row, column, label, field):
                yield field, value['text'], label, value
    if rows:
        return
    # A plain-text run of several headings has no reliable column alignment.
    lines = [line.strip() for line in unit['text'].splitlines() if line.strip()]
    for index, line in enumerate(lines):
        field, inline = source_label(line)
        if field not in VERIFIED_FIELDS | MONETARY:
            continue
        label = {'text': line}
        if inline:
            yield field, inline, label, label
        elif (index + 1 < len(lines) and not source_label(lines[index + 1])[0]
              and (index == 0 or source_label(lines[index - 1])[0] is None or source_label(lines[index - 1])[1])):
            yield field, lines[index + 1], label, {'text': lines[index + 1]}


def evidence(unit, label, cell, basis):
    source = {key: unit[key] for key in SOURCE_KEYS if key in unit}
    source.update({key: cell[key] for key in ('bbox', 'row', 'column', 'cell') if key in cell})
    source.update({f'label_{key}': label[key] for key in ('bbox', 'cell') if key in label})
    excerpt = cell['text'] if label is cell else label['text'] + '\n' + cell['text']
    return source | {'excerpt': excerpt, 'confidence': None, 'confidence_basis': basis}


def currency_markers(value, *, labeled=False):
    if labeled:
        marker = value.strip().upper()
        if marker in CODES:
            return {marker}
        if marker in QUALIFIED_CURRENCY:
            return {QUALIFIED_CURRENCY[marker]}
        if named := CURRENCY_NAMES.get(' '.join(value.casefold().split())):
            return {named}
    if number(value) is None:
        return set()
    symbols = {QUALIFIED_CURRENCY[symbol] for symbol in CURRENCY_SYMBOL.findall(value)}
    return symbols | (set(ISO_AMOUNT.findall(value)) & CODES)


def header_observations(unit):
    rows = rows_with_locations(unit)
    observations = []
    unresolved = None
    for field, value, label, cell in labeled_values(unit, rows):
        if field in MONETARY or field == 'currency':
            context = evidence(unit, label, cell, 'Currency marker in a labeled financial field.')
            observations.extend(('currency', code, context) for code in currency_markers(value, labeled=field == 'currency'))
            if AMBIGUOUS_SYMBOL.search(value):
                unresolved = unresolved or context
        elif actual := field_value(field, value):
            observations.append((field, actual, evidence(unit, label, cell, 'Verified against the labeled source field.')))

    in_table = False
    for row in rows:
        columns = table_header([cell['text'] for cell in row], minimum_numeric_columns=1)
        if columns:
            in_table = True
            for column, field in columns:
                cell = row[column]
                if field in {'unit_price', 'line_amount', 'tax_amount'} and (code := header_currency(cell['text'])[1]):
                    observations.append(('currency', code, evidence(unit, cell, cell, 'Currency in a price column heading.')))
        elif any(source_label(cell['text'])[0] in VERIFIED_FIELDS | MONETARY for cell in row):
            in_table = False
        elif in_table:
            for cell in row:
                printed = cell['text']
                if number(printed) is None:
                    continue
                codes = currency_markers(printed)
                context = evidence(unit, cell, cell, 'Currency marker attached to a price or amount.')
                observations.extend(('currency', code, context) for code in codes)
                if not codes and AMBIGUOUS_SYMBOL.search(printed):
                    unresolved = unresolved or context
    return observations, unresolved
