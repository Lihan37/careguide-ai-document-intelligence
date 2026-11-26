# Evaluation report

## Final pre-submission checks

The clean Windows checkout reran the deterministic evaluation on 14 independently labeled synthetic fixtures. Thirteen processed successfully and the deliberate corrupt PDF failed. This is **92.86% processing success**, **7.14% failure**, and all 14 expected processing outcomes. The 13 readable files matched **104/104 header checks** and all **13/13 expected total-validation decisions** in **8.509 seconds** of aggregate pipeline time. That field metric excludes failed documents and includes expected nulls. The positive duplicate pair was flagged. PDF/PDF totals differed by 30 and PDF/Excel totals differed by 5 as expected.

A separate smoke test uploaded the three Gemini fixtures through the running scratch clone's API and waited for the actual background jobs. Results persisted as `llm:gemini:gemini-3.5-flash-lite`, matched **69/69** header and line-item checks, and passed Decimal validation on **3/3** invoices. The scanned invoice used actual Tesseract on both pages and retained total evidence on page 2. Audit records captured **five attempts with four usage responses**, **1,785 reported input tokens**, **1,189 reported output tokens**, and **15.602 seconds** of aggregate adapter time. That measurement is separate from the earlier direct live evaluation below. Mocked Gemini tests exercise malformed, ungrounded and failed provider responses.

All three tested paraphrases ranked the expected document first in the final service run. The walkthrough query `equipment for digitizing paperwork` returned the positioned invoice's page 1 with no literal keyword match. The worker reported page counts 0–8, and all 24 sampled API health requests during OCR succeeded. The maximum sample was **1.84 ms** over loopback. [Final test scope](testing.md)

## PostgreSQL, pgvector and queue verification

Docker provided PostgreSQL **17.12** with pgvector **0.8.7** and Redis **7.4.9** on separately assigned loopback ports. The API and a real Celery `solo` worker ran as separate Windows Python processes. A fresh PostgreSQL database migrated through revisions `0001` and `0002`, preserved a 1,536-dimensional migration sentinel, and stored genuine 384-dimensional BGE embeddings. PostgreSQL persisted uploaded records, manual corrections and comparison results across an API restart. The test inspected all three new indexes and verified the owner/time index with an `EXPLAIN` diagnostic.

| Semantic query | Top result | Rank | Cosine distance | API time |
| --- | --- | ---: | ---: | ---: |
| electricity bill | Power statement, page 1 | 1 | 0.3091 | 0.556 s |
| internet service subscription | Network statement, page 1 | 1 | 0.3540 | 0.012 s |

Neither query had a literal keyword match. Both semantic excerpts matched the stored source text at the returned offsets and page. The first query included API-process model initialization. The corpus and query set were synthetic and small. An ownership check verified that a document transferred to another test user disappeared from the original user's semantic and direct results.

Redis held the upload before the worker started. A duplicated delivery produced one processing history and one source page. A corrupt PDF failed again after an explicit retry. A simulated expired job was marked failed through the recovery endpoint and successfully reprocessed. During an eight-page image-only PDF, polling observed page counts from 0 through 8. All 25 health requests sampled during processing returned HTTP 200. The slowest sampled request took **1.67 ms**. The test recorded client-side time over loopback. See the [reproduction commands](testing.md#postgresql-redis-and-celery-verification).

## PDF scale measurements

The benchmark used Windows, Tesseract 5.5.4 with English traineddata, and a fresh Python process per file. Timing covers the reader, deterministic extraction and Decimal validation. Peak working set covers the Python process and its loaded libraries. Tesseract child memory, API and queue overhead, database persistence, embeddings and Gemini are outside these measurements.

| Fixture | Pages | File bytes | Processing time | Peak Python working set |
| --- | ---: | ---: | ---: | ---: |
| Digital invoice | 1 | 3,246 | 0.036 s | 102.5 MiB |
| Digital invoice with annexes | 24 | 6,478 | 0.070 s | 102.6 MiB |
| Digital invoice with annexes | 96 | 16,213 | 0.157 s | 103.8 MiB |
| Digital invoice with annexes | 1,000 | 140,086 | 1.429 s | 119.8 MiB |
| Image-only invoice | 2 | 38,537 | 0.913 s | 128.6 MiB |
| Image-only invoice with repeated pages | 8 | 39,350 | 3.470 s | 130.0 MiB |
| Image-only invoice with repeated pages | 16 | 40,435 | 6.521 s | 130.6 MiB |
| Corrupt PDF | — | 42 | 0.005 s | 98.9 MiB |

Seven files processed and one was rejected as expected. The two larger scanned fixtures intentionally repeat invoice rows and raised validation issues. The digital benchmark contains one invoice and repeated short annexes. It demonstrates reader and parser behavior for that lightweight document shape. Large image-heavy PDFs, distinct content on every page and high-concurrency workloads can use more time and memory. No 1,000-page scanned benchmark was run.

## Gemini invoice extraction

The original `0/3` report recorded one Gemini generation attempt for `layout-invoice.pdf`. Its adapter time was 1.718 seconds, with no token usage returned and no data to validate. The other two invoices were unattempted because the runner stops on provider failure. The local key and model metadata were verified separately. Replaying the original request reproduced HTTP 400 `INVALID_ARGUMENT` for schema complexity before extraction. The provider-facing schema now omits Pydantic defaults, titles and the large line-item array bound. The strict local schema still enforces the original constraints. [Gemini structured output limits](https://ai.google.dev/gemini-api/docs/structured-output)

The first live run after the schema fix completed all four requests. All three invoices passed Decimal checks and matched 67/69 expected checks. Gemini copied letterhead names for the suppliers on two PDFs. The extraction instruction now prefers the full printed party name from the labeled billing block. The final run used the user-confirmed free tier and the model `gemini-3.5-flash-lite`.

| Synthetic fixture | Exact checks | Requests | Input tokens | Output tokens | Gemini adapter | Full pipeline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Positioned invoice PDF | 25/25 | 1 | 628 | 442 | 6.618 s | 6.679 s |
| Compound VAT invoice PDF | 25/25 | 1 | 597 | 442 | 2.408 s | 2.411 s |
| Two-page image-only invoice | 19/19 | 2 | 560 | 305 | 12.163 s | 13.289 s |
| Total | 69/69 | 4 | 1,785 | 1,189 | 21.189 s | 22.379 s |

All three invoices passed Decimal validation. The scanned invoice used actual Tesseract OCR on both pages and preserved page 2 evidence for the total. Gemini did not return separate thinking-token counts. The score counts exact header checks, line counts and expected printed line-item values. It covers these three fixtures. The isolated Windows checks passed with 228 backend tests and five Chromium tests, no failures or skips, plus TypeScript and the production build.

After configuring a local key, run the live evaluation from the repository root. The script sends only bundled invoices, scores them against independently recorded values, and identifies fixtures that were unattempted after a provider failure. Failed requests record a sanitized error category, HTTP code and recognized provider status. See the [setup and evaluation commands](../README.md#optional-gemini-extraction) and [fixture ground truth](../sample-data/gemini-ground-truth.json).

Google lists Gemini 3.5 Flash-Lite as free for standard input and output where the free tier is available. Google lists paid standard text rates of USD 0.30 per million input tokens and USD 2.50 per million output tokens, including thinking. These are published prices rather than application billing measurements. Use an eligible unbilled project to verify free-tier access. [Gemini API pricing and data usage](https://ai.google.dev/gemini-api/docs/pricing)

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
