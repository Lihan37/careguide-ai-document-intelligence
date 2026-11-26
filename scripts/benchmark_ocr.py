"""Measure the synthetic OCR dataset without connecting to any database."""
import ctypes
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

from runtime_env import ROOT, create_run


def peak_python_working_set():
    if sys.platform != 'win32':
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak if sys.platform == 'darwin' else peak * 1024

    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                'peak_rss', 'rss', 'peak_paged', 'paged', 'peak_nonpaged',
                'nonpaged', 'pagefile', 'peak_pagefile',
            )
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    current_process = ctypes.windll.kernel32.GetCurrentProcess
    current_process.restype = wintypes.HANDLE
    get_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
    if get_memory_info(current_process(), ctypes.byref(counters), counters.cb):
        return counters.peak_rss
    return None


def main():
    run = create_run('evaluation', 'evaluation')
    os.environ.update(run['env'])
    sys.path.insert(0, str(ROOT / 'services/api'))
    from app.extraction import demo_extract
    from app.processing import ocr_available, ocr_configuration, units
    from app.validation import validate

    if not ocr_available():
        raise SystemExit('Configure Tesseract and the requested language via environment variables before benchmarking.')
    command, _, _ = ocr_configuration()
    version = subprocess.run([command, '--version'], capture_output=True, check=True, text=True, timeout=5).stdout.splitlines()[0]
    directory = ROOT / 'sample-data/ocr'
    truth = json.loads((directory / 'ground-truth.json').read_text(encoding='utf-8'))
    results = []
    started = time.perf_counter()
    for filename in truth['files']:
        start_file = time.perf_counter()
        path = directory / filename
        try:
            pages = list(units(path, path.suffix))
            invoice, _, issues = demo_extract(pages)
            results.append({
                'file': filename, 'status': 'processed',
                'pages': [{key: page[key] for key in ('page', 'method', 'ocr_seconds', 'ocr_confidence') if key in page} for page in pages],
                'correct_header_fields': sum(str(getattr(invoice, k)) == v for k, v in truth['header'].items()),
                'scored_header_fields': len(truth['header']),
                'line_amounts': [str(item.line_amount) for item in invoice.line_items],
                'validation_rules': [i['rule_id'] for i in issues + validate(invoice)],
            })
        except Exception as exc:
            results.append({'file': filename, 'status': 'failed', 'error_type': type(exc).__name__})
        results[-1]['seconds'] = round(time.perf_counter() - start_file, 4)

    times = [page['ocr_seconds'] for result in results for page in result.get('pages', []) if 'ocr_seconds' in page]
    report = {
        'engine': version, 'configured_language': os.getenv('OCR_LANGUAGE', 'eng'),
        'files_processed': sum(result['status'] == 'processed' for result in results),
        'files_failed': sum(result['status'] == 'failed' for result in results),
        'seconds_total': round(time.perf_counter() - started, 4),
        'ocr_pages': len(times), 'seconds_per_ocr_page_median': round(statistics.median(times), 4) if times else None,
        'seconds_per_ocr_page_range': [min(times), max(times)] if times else None,
        'peak_python_working_set_bytes': peak_python_working_set(), 'files': results,
    }
    output = Path(run['root']) / 'ocr-benchmark.json'
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(output)
    print(json.dumps({key: value for key, value in report.items() if key != 'files'}, indent=2))


if __name__ == '__main__':
    main()
