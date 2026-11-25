# Evaluation report

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
