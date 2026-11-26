"""Measure reader/extractor/validator behavior against independently declared fixture truth."""
import json
import platform
import sys
import time
import os
import shutil
import subprocess
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

FIELDS = ['invoice_number', 'invoice_date', 'supplier_name', 'customer_name', 'subtotal', 'tax', 'total', 'currency']
ROOT = Path(__file__).resolve().parents[1]


def evaluate():
    # Configure isolation before importing any application module or cached settings.
    if 'app.config' in sys.modules or 'app.db' in sys.modules:
        raise RuntimeError('Run evaluation as a separate process before importing application settings; no environment mutation or cached database reuse is allowed')
    sys.path.insert(0, str(ROOT))
    from scripts.runtime_env import create_run
    context = create_run('evaluation', 'evaluation')
    os.environ.update(context['env'])
    sys.path.insert(0, str(ROOT / 'services/api'))
    from app.config import settings
    if settings().app_env != 'evaluation' or settings().automation_run_id != context['run_id']:
        raise RuntimeError('Evaluation refuses reused/cached application settings; run as a separate process')
    from app.processing import ocr_available
    from app.validation import duplicates
    from app.comparison import compare
    from app.db import Session, Document, Job, User, Audit
    from app.jobs import run_job
    from app.security import password_hash
    from types import SimpleNamespace
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, check=True, capture_output=True)
    output_dir = Path(context['root'])
    fixtures = output_dir / 'fixtures'
    fixtures.mkdir()
    truth = json.loads((ROOT / 'sample-data/ground-truth.json').read_text())['documents']
    shutil.copy2(ROOT / 'sample-data/ground-truth.json', fixtures / 'ground-truth.json')
    with Session() as db:
        owner = User(username='evaluation', password_hash=password_hash(context['env']['DEMO_PASSWORD']))
        db.add(owner)
        db.commit()
        owner_id = owner.id
    results = []
    matched = measured = succeeded = expected_outcomes = arithmetic_correct = arithmetic_count = 0
    extracted = {}
    for name, expected in truth.items():
        start = time.perf_counter()
        result = {'file': name, 'expected_processing': expected['expected_processing']}
        try:
            # Inputs are copied into the evaluation namespace, never uploaded to
            # the normal API or written into its database/storage.
            source_path = (ROOT / 'sample-data' / name).resolve()
            if not source_path.is_relative_to((ROOT / 'sample-data').resolve()):
                raise ValueError('Unsafe fixture path')
            target = fixtures / name
            shutil.copy2(source_path, target)
            with Session() as db:
                document = Document(owner_id=owner_id, filename=name, file_type=target.suffix, size=target.stat().st_size, checksum=hashlib.sha256(target.read_bytes()).hexdigest(), storage_path=str(target))
                db.add(document)
                db.flush()
                job = Job(document_id=document.id)
                db.add(job)
                db.add(Audit(document_id=document.id, user_id=owner_id, action='uploaded', detail=settings().provenance | {'filename': name}))
                db.commit()
                document_id, job_id = document.id, job.id
            run_job(job_id)
            with Session() as db:
                document = db.get(Document, document_id)
                if document.status not in {'COMPLETED', 'REQUIRES_REVIEW'}:
                    raise ValueError('Document processing failed')
                output, issues = document.raw, document.issues
            extracted[name] = output
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
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'mode': 'deterministic_demo — not live AI', 'dataset': '14 synthetic fixtures; eight invoice header fields scored (null/null counts as correct). Lines are covered by unit tests, not this accuracy metric.', 'sample_size': len(truth), 'processing_success_count': succeeded, 'processing_success_rate': succeeded / len(truth), 'processing_failure_rate': (len(truth) - succeeded) / len(truth), 'expected_outcome_accuracy': expected_outcomes / len(truth), 'field_accuracy_on_successful_documents': matched / measured if measured else None, 'correct_fields': matched, 'scored_fields': measured, 'calculation_validation_accuracy': arithmetic_correct / arithmetic_count if arithmetic_count else None, 'validation_sample_size': arithmetic_count, 'total_processing_seconds': round(sum(r['seconds'] for r in results), 6), 'duplicate_detection': {'exact_fixture_flagged': bool(duplicate_issues), 'scope': 'One positive checksum pair; supplier-negative tests are in pytest suite'}, 'comparisons': comparison_results, 'ocr_available': ocr_available(), 'live_ai_evaluation': 'Not executed: deterministic evaluation does not call an AI provider', 'semantic_search_evaluation': 'Not executed: isolated SQLite evaluation', 'large_pdf_benchmark': 'Not executed; no claim of 1000-page performance', 'environment': {'name': 'evaluation', 'run_id': context['run_id'], 'python': platform.python_version(), 'os': platform.system()}, 'documents': results}
    (output_dir / 'evaluation-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    # The dashboard may read metrics here, but no development DB row is touched.
    (ROOT / 'data/evaluation/latest-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
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

The field metric excludes failed documents; do not generalize it to arbitrary invoice formats. Null/null counts as correct; line items are tested separately and excluded from this metric. Expected outcomes assume OCR is installed, so missing OCR correctly lowers outcome accuracy. Time includes the synchronous local job pipeline and persistence in the isolated evaluation database; API/upload/queue/provider latency is excluded. Per-document times and failure reasons are in `evaluation-results.json`.

One positive exact-duplicate pair was flagged. Automated tests also verify unrelated suppliers are not duplicates. PDF-to-PDF and PDF-to-Excel total differences are measured in the JSON report. No statistical generalization is supported by this small dataset.

Live LLM extraction, real embeddings/pgvector retrieval, Celery/Redis integration, and 1000-page performance were not evaluated in this environment. OCR availability: {report['ocr_available']}. Re-run after installing OCR or configuring external services. `pytest` and Playwright results are recorded in `docs/testing.md`.

Reproduce: `.\\.venv\\Scripts\\python scripts/generate_samples.py`, then `.\\.venv\\Scripts\\python scripts/evaluate.py`.
'''
    (output_dir / 'evaluation-report.md').write_text(markdown, encoding='utf-8')
    print('Evaluation runtime and reports: ' + str(output_dir))
    print(json.dumps({k: report[k] for k in ('sample_size', 'processing_success_count', 'processing_failure_rate', 'field_accuracy_on_successful_documents', 'total_processing_seconds')}, indent=2))


if __name__ == '__main__':
    evaluate()
