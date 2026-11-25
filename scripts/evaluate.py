"""Measure reader/extractor/validator behavior against independently declared fixture truth."""
import json
import platform
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/api'))
from app.processing import units, ocr_available
from app.extraction import demo_extract
from app.validation import validate, duplicates
from app.comparison import compare
from types import SimpleNamespace

FIELDS = ['invoice_number', 'invoice_date', 'supplier_name', 'customer_name', 'subtotal', 'tax', 'total', 'currency']
ROOT = Path(__file__).resolve().parents[1]


def evaluate():
    truth = json.loads((ROOT / 'sample-data/ground-truth.json').read_text())['documents']
    results = []
    matched = measured = succeeded = expected_outcomes = arithmetic_correct = arithmetic_count = 0
    extracted = {}
    for name, expected in truth.items():
        start = time.perf_counter()
        result = {'file': name, 'expected_processing': expected['expected_processing']}
        try:
            source = list(units(ROOT / 'sample-data' / name, Path(name).suffix))
            invoice, evidence, extraction_issues = demo_extract(source)
            output = invoice.model_dump(mode='json')
            extracted[name] = output
            issues = validate(invoice)
            correct = 0
            for field in FIELDS:
                actual, wanted = output[field], expected['invoice'][field]
                equal = Decimal(actual) == Decimal(wanted) if field in {'subtotal', 'tax', 'total'} and actual is not None and wanted is not None else actual == wanted
                correct += int(equal)
            matched += correct
            measured += len(FIELDS)
            succeeded += 1
            expected_outcomes += expected['expected_processing'] == 'success'
            flagged_total = any(i['rule_id'] == 'total' and i['severity'] == 'FAILED' for i in issues)
            arithmetic_correct += flagged_total == expected.get('invalid_total', False)
            arithmetic_count += 1
            result.update(status='success', correct_fields=correct, fields_scored=len(FIELDS), total_validation_correct=flagged_total == expected.get('invalid_total', False), issue_count=len(issues))
        except Exception as exc:
            expected_outcomes += expected['expected_processing'] == 'failure'
            result.update(status='failure', error_type=type(exc).__name__, reason='OCR unavailable' if expected.get('ocr') and not ocr_available() else 'Reader rejected document')
        result['seconds'] = round(time.perf_counter() - start, 6)
        results.append(result)
    duplicate_a = SimpleNamespace(id='a', checksum='identical')
    duplicate_b = SimpleNamespace(id='b', checksum='identical', raw=extracted.get('invoice.pdf', {}), corrected={})
    duplicate_issues = duplicates(duplicate_a, [duplicate_b], extracted.get('invoice.pdf', {}))
    comparison_results = {}
    for filename in ['incorrect-total.pdf', 'accounting.xlsx']:
        if filename in extracted:
            comparison_results[filename] = next(r for r in compare(extracted['invoice.pdf'], extracted[filename]) if r['field'] == 'total')
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'mode': 'deterministic_demo — not live AI', 'dataset': '14 synthetic fixtures; fixed fixture grammar; eight invoice header fields scored (null/null counts as correct). Lines are covered by unit tests, not this accuracy metric.', 'sample_size': len(truth), 'processing_success_count': succeeded, 'processing_success_rate': succeeded / len(truth), 'processing_failure_rate': (len(truth) - succeeded) / len(truth), 'expected_outcome_accuracy': expected_outcomes / len(truth), 'field_accuracy_on_successful_documents': matched / measured if measured else None, 'correct_fields': matched, 'scored_fields': measured, 'calculation_validation_accuracy': arithmetic_correct / arithmetic_count if arithmetic_count else None, 'validation_sample_size': arithmetic_count, 'total_processing_seconds': round(sum(r['seconds'] for r in results), 6), 'duplicate_detection': {'exact_fixture_flagged': bool(duplicate_issues), 'scope': 'One positive checksum pair; supplier-negative tests are in pytest suite'}, 'comparisons': comparison_results, 'ocr_available': ocr_available(), 'live_ai_evaluation': 'Not executed: credentials not configured; deterministic accuracy is not AI accuracy', 'semantic_search_evaluation': 'Not executed: PostgreSQL/credentials unavailable', 'large_pdf_benchmark': 'Not executed; no claim of 1000-page performance', 'environment': {'python': platform.python_version(), 'os': platform.system()}, 'documents': results}
    (ROOT / 'docs/evaluation-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    successes = report['processing_success_count']
    markdown = f'''# Evaluation report

Generated: {report['generated_at']}

This is a deterministic fixture evaluation, **not a live LLM evaluation**. Synthetic data follows explicit key/value or canonical column layouts. Ground truth is declared in `scripts/generate_samples.py` before file generation. It is not inferred from extraction outputs. No private financial data is used.

| Measurement | Actual result |
| --- | --- |
| Dataset size | {len(truth)} documents |
| Reader + extraction successes | {successes}/{len(truth)} ({report['processing_success_rate']:.2%}) |
| Failure rate, including deliberate corruption and unavailable OCR | {report['processing_failure_rate']:.2%} |
| Expected processing outcome accuracy | {report['expected_outcome_accuracy']:.2%} |
| Eight header fields, successful documents only | {matched}/{measured} ({report['field_accuracy_on_successful_documents']:.2%}) |
| Total calculation validation, successful documents only | {arithmetic_correct}/{arithmetic_count} |
| Total elapsed processing time | {report['total_processing_seconds']} seconds |

The field metric excludes failed documents; do not generalize it to arbitrary invoice formats. Null/null counts as correct; line items are tested separately and excluded from this metric. Expected outcomes assume OCR is installed, so missing OCR correctly lowers outcome accuracy. Time is wall-clock reader + deterministic extraction + validation in one local process, excludes API/upload/queue/provider latency. Per-document times and failure reasons are in `evaluation-results.json`.

One positive exact-duplicate pair was flagged. Automated tests also verify unrelated suppliers are not duplicates. PDF-to-PDF and PDF-to-Excel total differences are measured in the JSON report. No statistical generalization is supported by this small dataset.

Live LLM extraction, real embeddings/pgvector retrieval, Celery/Redis integration, and 1000-page performance were not evaluated in this environment. OCR availability: {report['ocr_available']}. Re-run after installing OCR or configuring external services. `pytest` and Playwright results are recorded in `docs/testing.md`.

Reproduce: `.\\.venv\\Scripts\\python scripts/generate_samples.py`, then `.\\.venv\\Scripts\\python scripts/evaluate.py`.
'''
    (ROOT / 'docs/evaluation-report.md').write_text(markdown, encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('sample_size', 'processing_success_count', 'processing_failure_rate', 'field_accuracy_on_successful_documents', 'total_processing_seconds')}, indent=2))


if __name__ == '__main__':
    evaluate()
