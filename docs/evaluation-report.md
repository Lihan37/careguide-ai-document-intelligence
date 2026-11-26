# Evaluation report

## Real OCR verification

Windows x64 and Tesseract 5.5.4 with `OCR_LANGUAGE=eng` were used for this run. The dedicated benchmark timed actual pixel recognition, invoice extraction and Decimal validation on the eight files in `sample-data/ocr`. It excludes HTTP upload and database persistence.

| Fixture | OCR page times (seconds) | Result |
| --- | --- | --- |
| Clear PNG | 0.840 | Header, both lines and arithmetic passed |
| Clear JPG | 0.760 | Header, both lines and arithmetic passed |
| Two-frame TIFF | 0.658, 0.377 | Both frames read and arithmetic passed |
| Image-only PDF | 0.533 | Header, both lines and arithmetic passed |
| Two-page image-only PDF | 0.465, 0.379 | Both pages read and arithmetic passed |
| Mixed PDF | 0.487 on page 2 | Page 1 used digital text and page 2 used OCR. Arithmetic passed. |
| Degraded JPG | 0.341 | All eight header fields matched. Both line items were missing and review was required. |
| Corrupt PNG | No OCR page completed | Rejected as expected |

Seven files processed, one failed, and nine OCR pages completed. Wall time was **4.982 seconds** and median OCR time was **0.487 seconds per page**. The range was **0.341 to 0.840 seconds**. Peak Python working set was **121,053,184 bytes (115.4 MiB)**. This memory figure covers the benchmark process and excludes child Tesseract processes. All 56 scored headers on the seven readable files matched the synthetic ground truth. Only six files had both line items extracted. This sample does not establish performance for other layouts, languages or a 1,000-page document.

The separate end-to-end evaluation of the original 14-fixture dataset used an isolated SQLite database and processed 13 files in **12.897 seconds** of aggregate per-file pipeline time. The deliberately corrupt PDF failed. The successful files matched all 104 scored header fields and all 13 expected total-validation decisions. These measurements apply to the synthetic fixtures. Live LLM extraction, semantic search and PostgreSQL were outside this run.

Reproduce using the [Windows OCR settings](setup-windows.md#ocr) and `scripts/benchmark_ocr.py` or `scripts/evaluate.py` with the project virtual environment. Each writes a private JSON report under `data/evaluation/`.

## Historical baseline before installing OCR

Generated: 2026-11-25T22:36:20.077057+00:00

This is a deterministic fixture evaluation, **not a live LLM evaluation**. Synthetic data follows explicit key/value or canonical column layouts. Ground truth is declared in `scripts/generate_samples.py` before file generation. It is not inferred from extraction outputs. No private financial data is used.

| Measurement | Actual result |
| --- | --- |
| Dataset size | 14 documents |
| Reader + extraction successes | 8/14 (57.14%) |
| Failure rate, including deliberate corruption and unavailable OCR | 42.86% |
| Expected processing outcome accuracy | 64.29% |
| Eight header fields, successful documents only | 64/64 (100.00%) |
| Total calculation validation, successful documents only | 8/8 |
| Total elapsed processing time | 0.509865 seconds |

The field metric excludes failed documents; do not generalize it to arbitrary invoice formats. Null/null counts as correct; line items are tested separately and excluded from this metric. Expected outcomes assume OCR is installed, so missing OCR correctly lowers outcome accuracy. Time is wall-clock reader + deterministic extraction + validation in one local process, excludes API/upload/queue/provider latency. Per-document times and failure reasons are in `evaluation-results.json`.

One positive exact-duplicate pair was flagged. Automated tests also verify unrelated suppliers are not duplicates. PDF-to-PDF and PDF-to-Excel total differences are measured in the JSON report. No statistical generalization is supported by this small dataset.

Live LLM extraction, real embeddings/pgvector retrieval, Celery/Redis integration, and 1000-page performance were not evaluated in this environment. OCR availability: False. Re-run after installing OCR or configuring external services. `pytest` and Playwright results are recorded in `docs/testing.md`.

Reproduce: `.\.venv\Scripts\python scripts/generate_samples.py`, then `.\.venv\Scripts\python scripts/evaluate.py`.
