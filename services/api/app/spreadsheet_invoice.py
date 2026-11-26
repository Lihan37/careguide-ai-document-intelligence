"""Extract invoice facts from worksheet cells without parsing the display text."""
import re
from collections import Counter

from openpyxl.utils.cell import get_column_letter

from .invoice_parser import ALIASES, CODES, MONETARY, header_currency, key, label_pair, table_header


def blank(value):
    return value is None or isinstance(value, str) and not value.strip()


def bare_field(value, *, canonical=False):
    if blank(value):
        return None
    text = str(value)
    if canonical and (name := ALIASES.get(key(text))):
        return name
    field, inline = label_pair(text)
    return field if not inline else None


def parse_sheet(unit, source, offer, item, issues):
    rows = unit['rows']
    formulas = {(entry['row'] - 1, entry['column'] - 1): entry for entry in unit.get('formulas', [])}
    formats = unit.get('cell_formats', {})

    def value(row, column):
        return rows[row][column] if row < len(rows) and column < len(rows[row]) else None

    def present(row, column):
        return not blank(value(row, column)) or (row, column) in formulas

    def address(row, column):
        return f'{get_column_letter(column + 1)}{row + 1}'

    def reference(row, column, *, label=None):
        cell = address(row, column)
        raw = value(row, column)
        result = source(unit, str(raw) if raw is not None else '', row=row + 1, column=column + 1, cell=cell)
        if label is not None:
            result['label_cell'] = address(*label)
        if fmt := formats.get(cell):
            result['number_format'] = fmt
            # Quoted and escaped percent signs are literals in Excel formats.
            if '%' in re.sub(r'"[^"]*"|\\.', '', fmt):
                result['percentage'] = True
        if entry := formulas.get((row, column)):
            result.update(formula=entry['formula'], cached_value=entry['cached_value'])
        return result

    table = {}
    table_row = None
    skip_row = None
    for row, cells in enumerate(rows):
        if row == skip_row:
            continue
        populated = [column for column in range(len(cells)) if present(row, column)]
        if not populated:
            continue

        columns = table_header(cells, minimum_numeric_columns=1)
        if columns:
            names = Counter(field for _, field in columns)
            table = {field: column for column, field in columns if names[field] == 1}
            table_row = row
            if any(count > 1 for count in names.values()):
                issues.append({'rule_id': 'ambiguous_spreadsheet_item_columns', 'severity': 'REQUIRES_REVIEW',
                               'explanation': 'Multiple columns have the same item heading.', 'sheet': unit['sheet'], 'row': row + 1})
            for column, field in columns:
                if field in ('unit_price', 'line_amount', 'tax_amount') and (code := header_currency(str(cells[column]))[1]):
                    offer('currency', code, reference(row, column))
            continue

        description_column = table.get('description')
        if description_column is not None:
            description = value(row, description_column)
            numeric = {field: column for field, column in table.items() if field != 'description' and present(row, column)}
            summary = any(bare_field(cells[column]) in MONETARY for column in populated)
            if (isinstance(description, str) and description.strip() and numeric
                    and (not summary or 'quantity' in numeric and 'unit_price' in numeric)):
                references = {field: reference(row, column, label=(table_row, column))
                              for field, column in table.items() if present(row, column)}
                for field, entry in references.items():
                    if 'formula' in entry and entry['cached_value'] is None:
                        issues.append({'rule_id': 'uncached_line_formula', 'severity': 'REQUIRES_REVIEW',
                                       'explanation': 'Line item formula has no cached result.', 'field': field,
                                       'sheet': unit['sheet'], 'row': row + 1, 'column': entry['column']})
                item({field: value(row, column) for field, column in table.items()}, references)
                continue
        table = {}

        headers = {col: field for col in populated if (field := bare_field(cells[col], canonical=True))}
        # Keep support for a row-oriented record with additional non-invoice columns.
        if (len(set(headers.values())) >= 3 and row + 1 < len(rows)
                and list(headers) == populated[:len(headers)]):
            for column, field in headers.items():
                offer(field, value(row + 1, column), reference(row + 1, column, label=(row, column)))
            skip_row = row + 1
            continue

        for index, column in enumerate(populated):
            field, inline = label_pair(str(cells[column]))
            if not field:
                continue
            if inline:
                offer(field, inline, reference(row, column))
                continue

            label = (row, column)
            right = populated[index + 1:index + 3]
            if right and not bare_field(cells[right[0]]):
                next_column = right[0]
                if (field in MONETARY and len(right) == 2 and (code := str(cells[next_column]).strip().upper()) in CODES
                        and not bare_field(cells[right[1]])):
                    offer('currency', code, reference(row, next_column))
                    next_column = right[1]
                offer(field, cells[next_column], reference(row, next_column, label=label))
            elif present(row + 1, column) and not bare_field(value(row + 1, column)):
                offer(field, value(row + 1, column), reference(row + 1, column, label=label))
