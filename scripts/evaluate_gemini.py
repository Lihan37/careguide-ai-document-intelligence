"""Run live Gemini extraction on the committed synthetic invoice fixtures."""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from dotenv import dotenv_values

from .runtime_env import ROOT, create_run

sys.path.insert(0, str(ROOT / 'services/api'))
from app.config import read_local_gemini_key, settings
from app.gemini import GeminiExtractionError, extract_gemini
from app.processing import ProcessingError, units
from app.validation import validate

FIXTURES = ROOT / 'sample-data'
DECIMAL_FIELDS = {'subtotal', 'tax', 'total', 'quantity', 'unit_price', 'line_amount', 'tax_amount'}


def score_invoice(invoice, expected):
    def score_fields(model, fields):
        scores = {}
        for field, value in fields.items():
            actual = getattr(model, field, None)
            if field == 'invoice_date':
                actual = str(actual)
            if field in DECIMAL_FIELDS:
                value = Decimal(value.replace(',', ''))
            scores[field] = actual == value
        return scores

    scores = score_fields(invoice, {k: v for k, v in expected.items() if k != 'line_items'})
    scores['line_count'] = len(invoice.line_items) == len(expected['line_items'])
    for index, fields in enumerate(expected['line_items']):
        item = invoice.line_items[index] if index < len(invoice.line_items) else None
        scores.update({f'line_{index + 1}.{field}': correct for field, correct in score_fields(item, fields).items()})
    return scores


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true', help='Send only bundled synthetic fixture text to Gemini.')
    args = parser.parse_args()
    if not args.run_live:
        parser.error('Pass --run-live to send the three synthetic invoices to Gemini.')
    key = read_local_gemini_key()
    if not key:
        print('BLOCKED: set GEMINI_API_KEY in the local .env.')
        return 2

    local = dotenv_values(ROOT / '.env', encoding='utf-8-sig', interpolate=False)
    run = create_run('evaluation', 'evaluation')
    os.environ.update(run['env'])
    for name in ('GEMINI_MODEL', 'GEMINI_MAX_REQUESTS', 'GEMINI_TIMEOUT_SECONDS', 'GEMINI_MAX_OUTPUT_TOKENS',
                 'TESSERACT_CMD', 'TESSERACT_DATA_DIR', 'OCR_LANGUAGE'):
        if local.get(name):
            os.environ[name] = local[name]
    cfg = settings()
    fixtures = json.loads((FIXTURES / 'gemini-ground-truth.json').read_text(encoding='utf-8'))
    results = []
    for filename, expected in fixtures.items():
        path = FIXTURES / filename
        result = {'fixture': filename}
        results.append(result)
        started = perf_counter()
        try:
            source = list(units(path, path.suffix))
            invoice, evidence, issues, method, usage = extract_gemini(source, cfg, api_key=key)
            result.update(method=method, source_methods=[unit['method'] for unit in source],
                          values=invoice.model_dump(mode='json'), evidence=evidence,
                          checks=score_invoice(invoice, expected), issues=issues + validate(invoice), usage=usage)
        except ProcessingError as exc:
            result['error'] = str(exc)
        except GeminiExtractionError as exc:
            result.update(error=str(exc), usage=exc.usage)
            break  # Preserve quota after a provider failure.
        finally:
            result['pipeline_seconds'] = round(perf_counter() - started, 6)

    checks = [check for result in results for check in result.get('checks', {}).values()]
    successful = sum('checks' in result and all(result['checks'].values()) and not result['issues'] for result in results)
    report = {
        'model': cfg.gemini_model, 'files_attempted': len(results), 'files_expected': len(fixtures),
        'files_matching_and_validated': successful, 'scored_checks': len(checks), 'matching_checks': sum(checks),
        'request_attempts': sum((result.get('usage') or {}).get('requests', 0) for result in results),
        'results': results,
    }
    output = Path(run['root']) / 'gemini-results.json'
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'{successful}/{len(fixtures)} invoices matched and passed validation. Results: {output}')
    return 0 if successful == len(fixtures) else 1


if __name__ == '__main__':
    raise SystemExit(main())
