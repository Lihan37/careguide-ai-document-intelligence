"""Measure local reader, deterministic extraction and validation on bounded synthetic PDFs."""
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import pymupdf

from benchmark_ocr import peak_python_working_set
from runtime_env import ROOT, create_run


def measure(path):
    if os.getenv('APP_ENV') != 'evaluation' or os.getenv('AUTOMATION_KIND') != 'evaluation':
        raise SystemExit('Scaling measurements require an isolated evaluation run.')
    sys.path.insert(0, str(ROOT / 'services/api'))
    from app.extraction import demo_extract
    from app.processing import ProcessingError, units
    from app.validation import validate

    result = {'file': path.name, 'bytes': path.stat().st_size}
    started = perf_counter()
    try:
        source = list(units(path, '.pdf'))
        invoice, _, issues = demo_extract(source)
        result.update(status='processed', pages=len(source),
                      ocr_pages=sum(unit['method'] == 'tesseract_ocr' for unit in source),
                      source_text_chars=sum(len(unit['text']) for unit in source),
                      review_issues=len(issues + validate(invoice)))
    except ProcessingError as exc:
        result.update(status='failed', error=str(exc))
    except pymupdf.FileDataError:
        result.update(status='failed', error='Invalid or corrupt PDF')
    result.update(seconds=perf_counter() - started, python_peak_working_set_bytes=peak_python_working_set())
    return result


def fixtures(directory):
    sample = ROOT / 'sample-data'
    files = [sample / 'layout-invoice.pdf', sample / 'ocr/multipage.pdf']
    with pymupdf.open(files[0]) as invoice, pymupdf.open() as annex:
        annex.new_page().insert_text((48, 70), '\n'.join([
            'SYNTHETIC DELIVERY RECORD',
            'Inventory reconciliation confirmed the quantities received during the reporting period.',
            'These attachments contain supporting descriptions for a fictional supplier.',
            'The duplicate annex text is used only to measure page throughput.',
        ]))
        for count in (24, 96, 1000):
            path = directory / f'digital-{count}.pdf'
            with pymupdf.open() as target:
                target.insert_pdf(invoice)
                for _ in range(count - 1):
                    target.insert_pdf(annex, final=False)
                target.save(path, garbage=3, deflate=True)
            files.append(path)
    with pymupdf.open(files[1]) as scan:
        for count in (8, 16):
            path = directory / f'image-only-{count}.pdf'
            with pymupdf.open() as target:
                for _ in range(count // len(scan)):
                    target.insert_pdf(scan, final=False)
                assert len(target) == count and all(not page.get_text().strip() for page in target)
                target.save(path, garbage=3, deflate=True)
            files.append(path)
    return [*files, sample / 'corrupted.pdf']


def main():
    # Child execution is only for parent-selected synthetic PDF fixtures.
    if len(sys.argv) == 3 and sys.argv[1] == '--measure':
        print(json.dumps(measure(Path(sys.argv[2]))))
        return
    if len(sys.argv) != 1:
        raise SystemExit('Run this benchmark without arguments.')
    run = create_run('evaluation', 'evaluation')
    root = Path(run['root'])
    env = os.environ | run['env']
    results = []
    for path in fixtures(root):
        child = subprocess.run([sys.executable, __file__, '--measure', str(path)], cwd=ROOT,
                               env=env, capture_output=True, text=True, timeout=90, check=True)
        results.append(json.loads(child.stdout))
    report = {'files_processed': sum(result['status'] == 'processed' for result in results),
              'files_failed': sum(result['status'] == 'failed' for result in results), 'files': results}
    output = root / 'scaling-benchmark.json'
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(output)
    print(json.dumps(report, indent=2))
    if any(result['status'] != 'processed' for result in results[:-1]) or results[-1]['status'] != 'failed':
        raise SystemExit('Unexpected fixture outcome')


if __name__ == '__main__':
    main()
