"""Run live Gemini extraction on the committed synthetic invoice fixtures."""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from dotenv import dotenv_values
from google.genai import errors

from .runtime_env import ROOT, create_run

sys.path.insert(0, str(ROOT / 'services/api'))
from app.config import read_local_gemini_key, settings
from app.gemini import GeminiExtractionError, build_client, extract_gemini, provider_error
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
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run-live', action='store_true', help='Send only bundled synthetic fixture text to Gemini.')
    mode.add_argument('--check-access', action='store_true', help='Look up model metadata without requesting generation.')
    args = parser.parse_args()
    if 'app.db' in sys.modules or settings.cache_info().currsize:
        raise RuntimeError('Run Gemini evaluation in a separate process from the application.')
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
    if args.check_access:
        return check_access(cfg, key)

    fixtures = json.loads((FIXTURES / 'gemini-ground-truth.json').read_text(encoding='utf-8'))
    report = evaluate_fixtures(cfg, key, fixtures)
    output = Path(run['root']) / 'gemini-results.json'
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    successful = report['files_matching_and_validated']
    print(f"{successful}/{len(fixtures)} invoices matched and passed validation. "
          f"{report['files_attempted']} attempted, {report['files_unattempted']} unattempted. Results: {output}")
    return 0 if successful == len(fixtures) else 1


def check_access(cfg, key):
    started = perf_counter()
    try:
        with build_client(cfg, key) as client:
            supported = 'generateContent' in (client.models.get(model=cfg.gemini_model).supported_actions or [])
    except errors.APIError as exc:
        failure = provider_error(exc)
        print(f"Model lookup failed with HTTP {failure['http_status']}. {failure['message']}")
        return 1
    except Exception:
        print('Model lookup failed. Check network connectivity and local SDK configuration.')
        return 1
    print(f'Model lookup succeeded for {cfg.gemini_model} in {perf_counter() - started:.3f} seconds. '
          f'Generation capability advertised: {supported}. Check project tier and quota in Google AI Studio.')
    return 0 if supported else 1


def evaluate_fixtures(cfg, key, fixtures):
    results = []
    provider_failed = False
    for filename, expected in fixtures.items():
        path = FIXTURES / filename
        result = {'fixture': filename, 'expected': expected}
        results.append(result)
        if provider_failed:
            result.update(status='unattempted', reason='Evaluation stopped after a provider failure.')
            continue
        started = perf_counter()
        try:
            source = list(units(path, path.suffix))
            invoice, evidence, issues, method, usage = extract_gemini(source, cfg, api_key=key)
            result.update(status='extracted', method=method, source_methods=[unit['method'] for unit in source],
                          values=invoice.model_dump(mode='json'), evidence=evidence,
                          checks=score_invoice(invoice, expected), issues=issues + validate(invoice), usage=usage)
        except ProcessingError as exc:
            result.update(status='processing_error', error=str(exc))
        except GeminiExtractionError as exc:
            result.update(status='provider_error', error=str(exc), usage=exc.usage)
            provider_failed = True
        finally:
            result['pipeline_seconds'] = round(perf_counter() - started, 6)

    checks = [check for result in results for check in result.get('checks', {}).values()]
    successful = sum('checks' in result and all(result['checks'].values()) and not result['issues'] for result in results)
    unattempted = sum(result['status'] == 'unattempted' for result in results)
    return {
        'model': cfg.gemini_model, 'files_attempted': len(results) - unattempted, 'files_expected': len(fixtures),
        'files_unattempted': unattempted,
        'files_matching_and_validated': successful, 'scored_checks': len(checks), 'matching_checks': sum(checks),
        'request_attempts': sum((result.get('usage') or {}).get('requests', 0) for result in results),
        'results': results,
    }


if __name__ == '__main__':
    raise SystemExit(main())
