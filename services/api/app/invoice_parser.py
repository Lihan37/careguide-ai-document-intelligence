"""Conservative invoice parsing from labels, cell coordinates and table headers.

No invoice-specific names, identifiers, amounts, or fallback financial values.
This is deterministic parsing, not AI; unknown/ambiguous facts stay unknown.
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .schemas import Invoice, LineItem


def key(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


LABELS = {
    'invoice number': 'invoice_number', 'invoice no': 'invoice_number',
    'invoice #': 'invoice_number', 'invoice id': 'invoice_number',
    'invoice': 'invoice_number', 'invoice date': 'invoice_date',
    'issue date': 'invoice_date', 'date issued': 'invoice_date', 'date': 'invoice_date',
    'supplier name': 'supplier_name', 'supplier': 'supplier_name',
    'bill from': 'supplier_name', 'billed from': 'supplier_name',
    'vendor': 'supplier_name', 'sold by': 'supplier_name',
    'customer name': 'customer_name', 'customer': 'customer_name',
    'bill to': 'customer_name', 'billed to': 'customer_name', 'sold to': 'customer_name',
    'sub total': 'subtotal', 'subtotal': 'subtotal',
    'vat': 'tax', 'tax': 'tax', 'tax amount': 'tax', 'vat amount': 'tax',
    'sales tax': 'tax', 'sales tax amount': 'tax',
    'gst': 'tax', 'gst amount': 'tax',
    'grand total': 'total', 'total amount': 'total', 'total': 'total',
    'currency': 'currency', 'discount': 'discount', 'shipping': 'shipping',
    'credit': 'credit', 'due date': '_due_date',
}
ALIASES = {key(label): field for label, field in LABELS.items()}
MONETARY = {'subtotal', 'tax', 'total', 'discount', 'shipping', 'credit'}
# Currency codes are recognized only when printed explicitly. Ambiguous '$' is not USD.
CODES = set('AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL'.split())
TABLE_LABELS = {
    'description': 'description', 'itemdescription': 'description', 'item': 'description',
    'product': 'description', 'details': 'description',
    'qty': 'quantity', 'quantity': 'quantity',
    'unitprice': 'unit_price', 'price': 'unit_price', 'rate': 'unit_price',
    'amount': 'line_amount', 'lineamount': 'line_amount',
    'linetotal': 'line_amount', 'total': 'line_amount',
    'tax': 'tax_amount', 'vat': 'tax_amount', 'taxamount': 'tax_amount',
    'salestax': 'tax_amount', 'gst': 'tax_amount', 'gstamount': 'tax_amount',
    'vatamount': 'tax_amount', 'salestaxamount': 'tax_amount',
}

TAX_LABEL_ANNOTATION = re.compile(
    r'^(?P<label>(?:sales[\s_]+tax|tax|vat|gst)(?:[\s_]+amount)?)'
    r'\s*\(\s*(?:(?:sales\s+tax|tax|vat|gst)\s*)?(?:(?:@|at)\s*)?'
    r'\d+(?:[.,]\d+)?\s*%\s*\)(?=\s|:|$)',
    re.IGNORECASE,
)


def currencies(value):
    return {code.upper() for code in re.findall(r'(?<![A-Za-z])[A-Za-z]{3}(?![A-Za-z])', str(value)) if code.upper() in CODES}


def number(value):
    """Read a printed number; never compute absent amounts or convert percentages."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace('\u2212', '-').replace('\u00a0', ' ').replace('\u202f', ' ')
    if '%' in text:
        return None
    for code in currencies(text):
        text = re.sub(r'(?i)\b' + code + r'\b', '', text)
    text = text.strip().lstrip('$€£৳₹').strip()
    negative = text.startswith('(') and text.endswith(')')
    if negative:
        text = text[1:-1].strip()
    if re.search(r'\d\s+\d', text):
        if not re.fullmatch(r'-?\d{1,3}(?: \d{3})+(?:[.,]\d{1,6})?', text):
            return None
        text = text.replace(' ', '')
    if not re.fullmatch(r'[+-]?\d+(?:[.,]\d+)*', text):
        return None
    if ',' in text and '.' in text:
        decimal_sep = ',' if text.rfind(',') > text.rfind('.') else '.'
        thousands = '.' if decimal_sep == ',' else ','
        if not re.fullmatch(r'[+-]?\d{1,3}(?:' + re.escape(thousands) + r'\d{3})+' + re.escape(decimal_sep) + r'\d{1,6}', text):
            return None
        text = text.replace(thousands, '').replace(decimal_sep, '.')
    elif ',' in text:
        if re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+', text):
            text = text.replace(',', '')
        elif text.count(',') == 1 and len(text.rsplit(',', 1)[1]) in (1, 2):
            text = text.replace(',', '.')
        else:
            return None
    try:
        parsed = Decimal(text)
        return str(-parsed if negative else parsed) if parsed.is_finite() else None
    except InvalidOperation:
        return None


def invoice_date(value):
    text = str(value).strip()
    if re.fullmatch(r'\d{1,2}[/-]\d{1,2}[/-]\d{4}', text):
        a, b, year = map(int, re.split(r'[/-]', text))
        if a <= 12 and b <= 12 and a != b:
            return None  # No silent locale assumption for ambiguous dates.
        text = f'{year}-{b if a > 12 else a:02d}-{a if a > 12 else b:02d}'
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d %b %Y', '%d %B %Y', '%d-%b-%Y', '%B %d, %Y', '%b %d, %Y'):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def label_pair(text):
    text = text.strip()
    # Titles are not field/value pairs. In particular, 'INVOICE' is not tax.
    if re.fullmatch(r'(?:tax|vat|gst|sales\s+tax)\s+invoice', text, re.IGNORECASE):
        return None, ''
    # Normalize only a tax label's rate annotation, never an observed value.
    # 'Tax (VAT 10%)' and 'VAT (10%)' both refer to the printed tax amount.
    text = TAX_LABEL_ANNOTATION.sub(r'\g<label>', text)
    if ':' in text:
        label, value = text.split(':', 1)
        if key(label) in ALIASES:
            return ALIASES[key(label)], value.strip()
    if key(text) in ALIASES:
        # A bare INVOICE title is not an invoice-number field.
        return (None, '') if key(text) == 'invoice' else (ALIASES[key(text)], '')
    for label in sorted(LABELS, key=len, reverse=True):
        pattern = r'^[ \t]*' + r'[\s_]+'.join(re.escape(part) for part in label.split()) + r'\.?\s*(?:[:#]\s*|\s+)(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            return LABELS[label], match[1].strip()
    return None, ''


def normalized(field, value):
    if field in MONETARY:
        return number(value)
    if field == 'currency':
        codes = currencies(value)
        return next(iter(codes)) if len(codes) == 1 else None
    if field in {'invoice_date', '_due_date'}:
        return invoice_date(value)
    text = str(value).strip() if value is not None else ''
    if not text:
        return None
    if field == 'invoice_number' and not re.fullmatch(r'[\w][\w./-]*', text):
        return None
    return text


def visual_rows(unit):
    """Reconstruct visual rows/cells from PDF words independent of drawing order."""
    words = unit.get('words', [])
    rows = []
    for word in sorted(words, key=lambda word: ((word['bbox'][1] + word['bbox'][3]) / 2, word['bbox'][0])):
        bbox = word['bbox']
        center = (bbox[1] + bbox[3]) / 2
        if not rows or abs(center - rows[-1]['center']) > max(2, min(bbox[3] - bbox[1], rows[-1]['height']) * .35):
            rows.append({'center': center, 'height': bbox[3] - bbox[1], 'words': []})
        rows[-1]['words'].append(word)
    result = []
    for row in rows:
        cells = []
        for word in sorted(row['words'], key=lambda word: word['bbox'][0]):
            x0, y0, x1, y1 = word['bbox']
            if not cells or x0 - cells[-1]['bbox'][2] > max(10, row['height'] * .8):
                cells.append({'text': word['text'], 'bbox': [x0, y0, x1, y1]})
            else:
                cell = cells[-1]
                cell['text'] += ' ' + word['text']
                cell['bbox'] = [min(cell['bbox'][0], x0), min(cell['bbox'][1], y0), max(cell['bbox'][2], x1), max(cell['bbox'][3], y1)]
        result.append({'cells': cells, 'center': row['center']})
    return result


def table_header(cells):
    columns = []
    for i, cell in enumerate(cells):
        name = TABLE_LABELS.get(key(cell))
        field, value = label_pair(str(cell))
        if name is None and field == 'tax' and not value:
            name = 'tax_amount'
        if name is not None:
            columns.append((i, name))
    fields = {field for _, field in columns}
    return columns if 'description' in fields and len(fields - {'description'}) >= 2 else []


def is_summary(text):
    field, value = label_pair(text)
    return field in MONETARY and (not value or number(value) is not None)


def extract_invoice(source_units):
    candidates, item_rows, issues = {}, [], []

    def source(unit, excerpt, **extra):
        return {k: unit[k] for k in ('document_id', 'page', 'sheet', 'method', 'coordinate_space', 'ocr_confidence') if k in unit} | {'excerpt': excerpt, 'confidence': None, 'confidence_basis': 'deterministic label/table match; uncalibrated'} | extra

    def offer(field, raw, reference):
        if field is None or field.startswith('_') or raw is None or str(raw).strip() == '':
            return
        candidates.setdefault(field, []).append((raw, reference))
        if field in MONETARY:
            for code in currencies(raw):
                candidates.setdefault('currency', []).append((code, reference))

    def item(values, references):
        parsed = {}
        for field, raw in values.items():
            if field == 'description':
                parsed[field] = str(raw).strip() or None
            else:
                parsed[field] = number(raw)
                if parsed[field] is None and raw is not None and str(raw).strip():
                    issues.append({'rule_id': f'invalid_line_{len(item_rows) + 1}_{field}', 'severity': 'REQUIRES_REVIEW', 'explanation': 'Invalid observed line value; inspect original table evidence', 'actual': str(raw)})
        if not parsed.get('description'):
            return
        try:
            line = LineItem.model_validate(parsed)
        except ValueError:
            issues.append({'rule_id': 'invalid_line_item', 'severity': 'REQUIRES_REVIEW', 'explanation': 'Line exceeds schema limits; inspect original table evidence'})
            return
        item_rows.append((line, references))

    for unit in source_units:
        lines = [line.strip() for line in unit['text'].splitlines() if line.strip()]
        rows = visual_rows(unit)
        # Prefer coordinates for PDF labels: adjacent values or aligned values below.
        for index, row in enumerate(rows):
            for column, cell in enumerate(row['cells']):
                field, value = label_pair(cell['text'])
                if not field:
                    continue
                if value:
                    offer(field, value, source(unit, cell['text'], bbox=cell['bbox']))
                    continue
                right = row['cells'][column + 1:column + 2]
                if right and not label_pair(right[0]['text'])[0] and normalized(field, right[0]['text']) is not None:
                    offer(field, right[0]['text'], source(unit, cell['text'] + ' | ' + right[0]['text'], bbox=right[0]['bbox'], label_bbox=cell['bbox']))
                    continue
                for below in rows[index + 1:index + 4]:
                    if below['center'] - row['center'] > 45:
                        break
                    aligned = [c for c in below['cells'] if abs(c['bbox'][0] - cell['bbox'][0]) < 22]
                    if aligned:
                        candidate = aligned[0]
                        if not label_pair(candidate['text'])[0] and normalized(field, candidate['text']) is not None:
                            offer(field, candidate['text'], source(unit, cell['text'] + '\n' + candidate['text'], bbox=candidate['bbox'], label_bbox=cell['bbox']))
                        break

        # Text/OCR fallback. Resolve consecutive label groups before their value group.
        # When geometry exists, do not add speculative cross-column text matches.
        for index, line in enumerate(lines):
            field, value = label_pair(line)
            if field and value:
                offer(field, value, source(unit, line))
            elif field and not rows and (index == 0 or not label_pair(lines[index - 1])[0] or label_pair(lines[index - 1])[1]):
                labels = []
                cursor = index
                while cursor < len(lines):
                    name, inline = label_pair(lines[cursor])
                    if not name or inline:
                        break
                    labels.append((name, lines[cursor]))
                    cursor += 1
                for offset, (name, heading) in enumerate(labels):
                    if cursor + offset < len(lines) and not label_pair(lines[cursor + offset])[0]:
                        offer(name, lines[cursor + offset], source(unit, heading + '\n' + lines[cursor + offset]))

        # Positioned tables are bounded by their header and first summary row.
        header, header_cells, geometry_items = [], [], False
        for row_index, row in enumerate(rows):
            cells = row['cells']
            found = table_header([c['text'] for c in cells])
            if found:
                header, header_cells = found, cells
                continue
            if not header:
                continue
            if cells and is_summary(cells[0]['text']):
                header = []
                continue
            values, refs = {}, {}
            for cell in cells:
                center = (cell['bbox'][0] + cell['bbox'][2]) / 2
                description_col = next(col for col, name in header if name == 'description')
                if abs(cell['bbox'][0] - header_cells[description_col]['bbox'][0]) < 20:
                    col, name = description_col, 'description'
                else:
                    col, name = min(header, key=lambda pair: abs(center - (header_cells[pair[0]]['bbox'][0] + header_cells[pair[0]]['bbox'][2]) / 2))
                if name in values:
                    values[name] += ' ' + cell['text']
                else:
                    values[name] = cell['text']
                refs[name] = source(unit, cell['text'], bbox=cell['bbox'], row=row_index + 1, column=col + 1)
            if values.get('description') and any(number(values.get(field)) is not None for field in ('quantity', 'unit_price', 'line_amount')):
                item(values, refs)
                geometry_items = True

        # Canonical spreadsheet header/data record (existing supported workflow).
        sheet_rows = unit.get('rows', [])
        if sheet_rows:
            headers = {}
            for i, value in enumerate(sheet_rows[0]):
                if key(value) in ALIASES:
                    headers[i] = ALIASES[key(value)]
                    continue
                field, inline = label_pair(str(value))
                if field and not inline:
                    headers[i] = field
            if len(headers) >= 3 and len(sheet_rows) > 1:
                for column, field in headers.items():
                    raw = sheet_rows[1][column] if column < len(sheet_rows[1]) else None
                    offer(field, raw, source(unit, str(raw), row=2, column=column + 1))
            table_columns = table_header([str(value) for value in sheet_rows[0]])
            if table_columns:
                for row_index, values in enumerate(sheet_rows[1:], 2):
                    if values and is_summary(str(values[0])):
                        break
                    item({name: values[col] if col < len(values) else None for col, name in table_columns}, {name: source(unit, str(values[col]), row=row_index, column=col + 1) for col, name in table_columns if col < len(values)})

        if geometry_items or sheet_rows:
            continue
        # Delimited and whitespace tables, including PDF text with one cell per line.
        active, index = [], 0
        while index < len(lines):
            line = lines[index]
            # Preserve the original explicit Item fixture format without requiring it.
            if re.match(r'^item\s*:', line, re.IGNORECASE) and '|' in line:
                cells = [c.strip() for c in line.split(':', 1)[1].split('|')]
                names = ['description', 'quantity', 'unit_price', 'line_amount', 'tax_amount']
                if 4 <= len(cells) <= 5:
                    item(dict(zip(names, cells)), {name: source(unit, line, column=i + 1) for i, name in enumerate(names[:len(cells)])})
                index += 1
                continue
            cells = [c.strip() for c in re.split(r'\s*\|\s*|\t+| {2,}', line)]
            found = table_header(cells)
            if not found:
                # A single-space header can still be recognized by its column names.
                tokens = re.findall(r'item description|unit price|line amount|line total|tax amount|description|quantity|product|details|amount|price|qty|rate|total|tax|vat', line, re.IGNORECASE)
                if key(''.join(tokens)) == key(line):
                    found = table_header(tokens)
            if found:
                active = found
                index += 1
                continue
            # Vertical header: DESCRIPTION\nQTY\nUNIT PRICE\nAMOUNT.
            vertical = []
            cursor = index
            while cursor < len(lines) and key(lines[cursor]) in TABLE_LABELS:
                vertical.append(lines[cursor])
                cursor += 1
            if table_header(vertical):
                active = table_header(vertical)
                index = cursor
                continue
            if active:
                if is_summary(line) or label_pair(line)[0]:
                    active = []
                    index += 1
                    continue
                count = max(col for col, _ in active) + 1
                if len(cells) == 1:
                    tokens = line.split()
                    numeric_count = len(active) - 1
                    if active[0][1] == 'description' and len(tokens) > numeric_count and all(number(token) is not None for token in tokens[-numeric_count:]):
                        cells = [' '.join(tokens[:-numeric_count])] + tokens[-numeric_count:]
                    elif index + count <= len(lines) and all(number(lines[index + col]) is not None for col, name in active if name != 'description'):
                        cells = lines[index:index + count]
                        index += count - 1
                if len(cells) == count:
                    item({name: cells[col] for col, name in active}, {name: source(unit, ' | '.join(cells), column=col + 1) for col, name in active})
            index += 1

    data, evidence = {}, {}
    for field, observed in candidates.items():
        values = {}
        invalid = []
        for raw, reference in observed:
            value = normalized(field, raw)
            try:
                if value is not None:
                    value = Invoice.model_validate({field: value}).model_dump(mode='json')[field]
            except ValueError:
                value = None
            if value is None:
                invalid.append((raw, reference))
            else:
                # Repeated totals with different printed precision are the same fact.
                identity = Decimal(value) if field in MONETARY else value
                values.setdefault(identity, (value, reference))
        if len(values) == 1:
            data[field], evidence[field] = next(iter(values.values()))
        elif len(values) > 1:
            data[field] = None
            evidence[field] = observed[0][1] | {'candidates': [reference | {'original_value': str(raw)} for raw, reference in observed]}
            issues.append({'rule_id': 'ambiguous_' + field, 'severity': 'REQUIRES_REVIEW', 'explanation': 'Conflicting observed values; no value selected'})
        else:
            data[field] = None
            evidence[field] = invalid[0][1]
            issues.append({'rule_id': 'invalid_' + field, 'severity': 'REQUIRES_REVIEW', 'explanation': 'Observed value is invalid or ambiguous; inspect original evidence', 'actual': str(invalid[0][0])})
    data['line_items'] = [line.model_dump(mode='json') for line, _ in item_rows]
    if item_rows:
        evidence['line_items'] = {'confidence': None, 'confidence_basis': 'observed table cells; uncalibrated', 'items': [references for _, references in item_rows]}
    return Invoice.model_validate(data), evidence, issues
