# Structured extraction regression investigation

## Confirmed root cause

The original uploaded `CareGuide_Test_Invoice_CG-2026-001.pdf` was located through its persisted document record, not replaced with generated financial answers. Its stored original checksum matches the supplied Downloads copy. It explicitly identifies itself as synthetic software-test data; a byte-for-byte copy is retained as `sample-data/layout-invoice.pdf` for regression testing. Document text is treated as untrusted data, not application instructions.

PyMuPDF extracted all invoice text successfully. The database showed two completed processing attempts (initial and first retry), both `REQUIRES_REVIEW`, with no job error. The extractor produced eight null header fields and no items. The ten issues were one invalid currency, eight missing required fields and missing line items. No application log files were found in the project/data log locations; the persisted jobs, source text and issues provide the failure evidence.

The active mode was `deterministic_demo`, with no LLM key. The original deterministic parser required colon-separated labels and exact `Item: description | quantity | price | amount` fixture rows. The reported PDF instead draws invoice-number/issue-date/due-date headings above their values, puts Bill From/Bill To in different columns, and draws item cells individually. PyMuPDF's plain text contains separate lines for each cell, in content drawing order. The old aliases also omitted Bill From/Bill To, Issue Date and VAT. `Currency: BDT (Bangladeshi Taka)` was recognized as evidence but passed verbatim into a schema requiring three uppercase letters, so it became null. Repeating the job could not fix those deterministic parsing assumptions.

## Implementation

- Digital PDF source units now retain word bounding boxes alongside the original text and blocks.
- The reusable `invoice_parser.py` reconstructs visual rows/cells, associates labels with adjacent/aligned values, maps tables by their printed headers and retains per-cell evidence.
- Text-only/OCR fallback supports inline and vertical labels, label/value groups, pipe/tab/whitespace tables, and vertically extracted table cells. Existing fixture and canonical spreadsheet workflows remain supported. Spreadsheet line tables retain sheet/row/column evidence.
- Label aliases cover Invoice No/Number, Issue/Invoice Date, Bill From/Supplier/Vendor, Bill To/Customer, VAT/Tax and Grand Total/Total, among others.
- Numeric normalization accepts printed currency codes, grouped numbers and common decimal separators using Decimal. Currency annotations yield only an explicitly observed code. Ambiguous `$` alone does not imply USD. Ambiguous dates, conflicting header values and invalid amounts require review.
- Missing quantity, amount or per-line tax stays null; no missing financial amount is calculated during extraction. Validation independently checks observed arithmetic. Model/API mode labeling remains honest: deterministic parsing is not AI.

## Actual reprocessing result

The existing API was running without auto-reload. After confirming there were no active jobs, it was restarted to load the fix. The original document was reprocessed through the authenticated REST endpoint, using the real separate-process worker. Its third attempt (retry count 2) completed successfully, progress 100, no processing error. Existing human corrections were empty and remain unchanged. The original file was not overwritten.

| Field | Saved raw extraction |
| --- | --- |
| Invoice number | CG-2026-001 |
| Invoice date | 2026-11-26 |
| Supplier | Northstar Office Supplies Ltd. |
| Customer | CareGuide Demo Operations |
| Subtotal | BDT 8500.00 |
| Tax | BDT 850.00 |
| Total | BDT 9350.00 |
| Currency | BDT |
| Item count | 4 |
| Document status | COMPLETED |
| Validation endpoint outcome | PASSED, zero issues |

| Description | Quantity | Unit price | Line amount |
| --- | --- | --- | --- |
| Document Scanner Accessories | 2 | 1250.00 | 2500.00 |
| A4 Printer Paper Box | 3 | 850.00 | 2550.00 |
| USB Flash Drive 64GB | 4 | 625.00 | 2500.00 |
| Desktop Cable Organizer | 5 | 190.00 | 950.00 |

All four quantity × unit-price checks pass; the observed line amounts sum to 8500.00; observed subtotal + tax equals 9350.00. Per-line tax is not printed and remains null. Later browser regression uploads are genuine duplicate copies and can correctly receive duplicate warnings; that does not imply an arithmetic/extraction failure.

## Verification

- Full pytest suite: **84 passed, 4 explicitly skipped**, zero failures, 16.25 seconds. Four real OCR tests remain skipped because the Tesseract executable is unavailable. Starlette emits the existing TestClient/httpx deprecation warning.
- **39 new parser/API regression cases** cover the reported file, unrelated identifiers/names/amounts, label variations, shuffled PDF drawing order, multiple table formats/reordered columns, canonical spreadsheet evidence, currency and locale normalization, missing cells, negative lines, conflicting observations, repeated equivalent totals and ambiguous dates.
- Existing keyword-search escaping test was corrected to allow genuine literal `%` content in the new VAT fixture while still proving `%` does not become a wildcard.
- Real browser workflows: **3 passed in 27.9 seconds**, including the positioned invoice, existing corrections/search/comparison workflow, valid/duplicate documents and corrupt-file retries.
- No runtime LLM or embedding calls were made. No deployment or GitHub push is part of this fix; the requested commit is local.

## AI adapter and remaining limits

The real provider adapter is already independent of deterministic label templates: it supplies document text to a configurable Responses structured-output model, parses the Invoice Pydantic schema and applies deterministic validation afterwards. A capable configured model may handle more varied layouts, but that is an expectation rather than measured evidence. This environment has no LLM_API_KEY and uses deterministic mode; live provider behavior, account/model access and costs have not been verified. It currently sends text rather than page images, and different line-item arrays across chunks are withheld for review rather than merged. Exact model field citations/confidence are not verified.

The deterministic parser remains heuristic, not universal layout understanding. Borderless tables with severely overlapping columns, wrapped/multiline descriptions, unfamiliar labels, ambiguous locale conventions, multiple invoices per file and poor OCR may still require review or an evaluated AI adapter. No 1000-page benchmark or new Docker/pgvector/Celery evaluation was performed.
