# Annotated tax-label regression

## Evidence and root cause

The second synthetic invoice was located through the application database and inspected directly with PyMuPDF. It prints `Tax (VAT 10%)` and `BDT 965.00` in adjacent positioned cells. The regression fixture `sample-data/tax-layout-invoice.pdf` contains the same synthetic PDF.

Both stored review issues were extraction-related: `invalid_tax` and `required_tax`. There were no duplicate or arithmetic issues to suppress. The old annotation regex removed only bare percentages such as `(10%)`, leaving `(VAT 10%)` in the label. The label therefore failed to identify the adjacent amount. Separately, the generic `Tax ...` label matcher misread the heading `TAX INVOICE` as a tax field with observed value `INVOICE`, producing the invalid-tax evidence.

## Fix

Tax-label normalization now recognizes optional tax names and rates inside parentheses, including `VAT (10%)`, `Tax (VAT 10%)`, decimal rates and optional `@`/`at` wording. It is anchored to tax labels; it does not strip parenthesized financial values such as a negative tax credit. Sales Tax/GST aliases are supported alongside Tax, VAT and Tax Amount. Invoice titles are excluded from monetary candidates. Shared normalization handles text fields, positioned PDF fields, canonical spreadsheet tax headers and per-line tax headers while keeping line tax separate from invoice tax.

Amounts always come from printed values. Rates alone do not produce an amount, no difference between subtotal and total is substituted as tax, missing values remain null, and invalid/conflicting printed amounts still require review. No validator rule was removed or relaxed.

## Actual saved results

After checking there were no active jobs, the local API was restarted to load the fix. The second invoice was reprocessed through the authenticated API and real background worker. Comparing its saved raw JSON before/after showed **only `tax` changed**. Existing line items and human corrections were preserved.

| Field | Saved extraction |
| --- | --- |
| Invoice number | EDS-INV-2026-042 |
| Invoice date | 2026-11-25 |
| Supplier | Eastern Digital Solutions Ltd. |
| Customer | CareGuide Demo Operations |
| Subtotal | BDT 9650.00 |
| Tax | BDT 965.00 |
| Grand total | BDT 10615.00 |
| Currency | BDT |
| Line items | 4 |
| Document/job status | COMPLETED |
| Validation | PASSED; zero issues |

Observed line amounts are 2900.00, 2250.00, 2800.00 and 1700.00. Decimal checks verify each quantity × unit price, their sum of 9650.00, and 9650.00 + 965.00 = 10615.00. Per-line tax is not printed and stays null. The first uploaded invoice was also checked through the live API: tax remains 850.00, four line items remain intact, and validation has zero issues.

Browser regression uploads create additional legitimate duplicate copies. Duplicate warnings on those copies remain enabled; they are not hidden to make tests appear successful.

## Checks performed

- **144 backend tests passed, 4 OCR tests explicitly skipped**, zero failures (15.03 seconds). This includes 60 new tax regression cases covering all seven requested label forms in inline, vertical and positioned layouts, spreadsheet headers, rate-only/zero/negative/invalid/conflicting values, invoice-title rejection, the exact second PDF and API validation. Existing first-invoice regression tests still pass.
- **4 real browser workflows passed** (32.4 seconds), including the second invoice's visible tax, API extraction and absence of tax-related review issues, plus the first invoice, corrections, search, comparisons, duplicate warnings and failed-job retries.
- Next.js production build and TypeScript standalone checks passed. Python compileall passed. `pip check` reports no broken requirements.
- Some minimal generated PDF test cases initially triggered the reader's sparse-page OCR fallback; they were corrected to include enough synthetic digital text to test the intended digital-PDF path. No failing test was skipped to conceal it.

The existing Tesseract executable is unavailable, so the same four real OCR tests remain explicitly skipped. No live LLM/embedding or large-file benchmark was performed, and no deployment is part of this change. Financial correctness is deterministic and does not depend on an enabled AI provider.
