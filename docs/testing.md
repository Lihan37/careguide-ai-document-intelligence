# Tests and verification

Latest extraction regression verification: **84 pytest cases passed, 4 OCR cases explicitly skipped; 3 real browser workflows passed**. See [extraction investigation](extraction-fix.md) for the actual reprocessed document, broader layout cases and remaining provider limits. The checkpoint table below records the original implementation run; browser-results.json remains that historical run rather than fabricated replacement metrics.

Verified on Windows with Python 3.13 and Node 22.17. Results are actual command outputs, not projections.

| Check | Result |
| --- | --- |
| pytest | 45 passed, 4 explicitly skipped; see pytest-results.xml |
| Real OCR integration | Four tests explicitly skipped: Tesseract executable unavailable |
| Playwright Chromium | 2 passed in 25.3 s; real local API/background processor; browser-results.json |
| Next.js production build | Passed compilation, TypeScript and page generation |
| TypeScript standalone | Passed after separating reusable frontend components |
| Python compileall | Passed |
| pip dependency check | No broken requirements |
| SQLite Alembic migration | Local upgrade passed; migration round-trip test added for reproducibility |
| Docker/Redis/PostgreSQL/Celery/pgvector | Not runtime tested: Docker engine unavailable |
| Live LLM/embeddings | Not executed: no credentials |
| 1000-page load benchmark | Not executed |

## Reproduce

```powershell
.\.venv\Scripts\python -m pytest -q --junitxml=docs/pytest-results.xml
.\.venv\Scripts\python scripts/evaluate.py
npm.cmd run build --prefix apps/web
npm.cmd run typecheck --prefix apps/web
```

For Playwright, start API on port 8000 and frontend on port 3000 with the same `.env` local credentials; the test reads DEMO_PASSWORD privately and never prints it. Tests upload real synthetic documents into that local database and perform corrections/comparison; use an assessment demo database, not private production data.

```powershell
Set-Location apps/web
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

The two browser workflows test valid invoices, exact duplicate warnings, a corrupt-file retry and connected navigation. The primary workflow logs in, uploads an incorrect-total PDF, waits for actual asynchronous extraction, sees failed arithmetic, corrects and audits the total, approves the review, finds the record through search, uploads a multi-sheet XLSX, detects a real comparison mismatch, and captures desktop/mobile screenshots. Failure artifacts are under ignored test-results/. The browser-results.json report is checked in as measured evidence.

Backend tests use an isolated temporary SQLite database and synchronous task dispatch to make API assertions deterministic. The actual browser test uses the production local background process, not mocked API data. Provider tests use mocked SDK responses and explicitly are not live LLM evaluation. Unit tests cover signature validation, all parser categories, resource limits, CSV encoding/quoting/malformed input, OCR unavailability, formula cache preservation, schema/NaN rejection, line and total arithmetic, credits/discounts/tax-inclusive values, supplier-scoped duplicates, PDF/PDF and PDF/Excel comparison, sheet mappings, ownership/role/origin protection, search wildcard escaping, correction history, review gating, retry limits, cancellation, terminal job idempotency and stale recovery.

The installed Starlette emits a TestClient httpx deprecation warning. It does not fail tests; the requested httpx/TestClient stack remains in use. No failing test was silently skipped. OCR tests skip only when the executable is absent and automatically run when available.

Tests keep temporary databases/files under ignored `data/test-runs/`. Pytest cache is disabled so managed Windows temp/cache permissions do not block reproducibility. Provider-call budget checks prevent calling an LLM when the configured chunk budget would be exceeded.
