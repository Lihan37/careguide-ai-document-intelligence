# Tests, environment isolation and safe inspection

The verified environment is Windows, Python 3.13 and Node 22.17. Current verification after the isolation change: **185 backend tests passed, 4 real OCR cases explicitly skipped; 4 isolated browser workflows passed**. TypeScript standalone and Next.js production build passed. OCR skips are caused by the missing Tesseract executable; the existing Starlette/TestClient httpx deprecation warning remains visible.

## Safe commands

Run from the repository root:

```powershell
.\.venv\Scripts\python -m pytest -q --junitxml=data/verification/pytest-results.xml
npm.cmd run test:e2e --prefix apps/web
npm.cmd run typecheck --prefix apps/web
npm.cmd run build --prefix apps/web
.\.venv\Scripts\python scripts/evaluate.py
```

Install Chromium once with `npx.cmd --prefix apps/web playwright install chromium`. The browser runner starts its own servers; do **not** point tests at the normal app or supply development credentials. Direct `npx playwright test` without an isolated runner context fails intentionally. No external AI account is required.

| Purpose | Environment and locations |
| --- | --- |
| Development | APP_ENV=development; existing `.env` retained. Defaults: `data/careguide.db`, `data/uploads/`. |
| Backend tests | APP_ENV=test, AUTOMATION_KIND=pytest; fresh `data/test-runs/<UUID>/careguide.db`, `uploads/`, and pytest temporary files. |
| Browser tests | APP_ENV=test, AUTOMATION_KIND=playwright; fresh database/uploads under `data/test-runs/<UUID>`, source-only frontend copy under `apps/web/.test-runs/<UUID>`, independent loopback ports and generated credentials. |
| Evaluation | APP_ENV=evaluation, AUTOMATION_KIND=evaluation; fresh `data/evaluation/<UUID>/careguide.db`, copied `fixtures/`, `uploads/`, metrics/report files. |

`scripts/runtime_env.py` creates unique roots and ownership markers. Automated settings require explicit paths, environment, automation kind and run UUID; there is no development fallback. Test/evaluation do not load `.env`. Paths are resolved, checked against their environment namespace and protected development locations, and must have a matching ownership marker. Tests also reject hardlinks to a configured development database. Development cannot reuse test/evaluation paths. PostgreSQL support is retained; automated PostgreSQL DB names must include the environment and unique run ID, but PostgreSQL runtime was not tested here.

Pytest configures isolation before importing the app, migrates an isolated database through Alembic for API assertions and synchronous task dispatch for determinism, and closes/removes its run-owned database/uploads at teardown. It no longer regenerates committed fixtures. Each Playwright run migrates its own database and exercises the real local background process. It verifies `/api/environment` before each test and sends environment/run headers; the API rejects mismatched tagged requests before document insertion. New upload audit details identify the originating environment/run. Normal startup creates no fixture records.

Playwright servers shut down cooperatively before temporary directories are removed. The runner retains JSON reports/screenshots privately under `data/verification/playwright/<UUID>`. Databases and uploaded originals are not retained after a completed browser run. A hard process interruption may leave a marked temporary directory for inspection; it never authorizes deleting development data or legacy directories. No automatic broad cleanup of `data/` occurs.

## Coverage and actual evidence

The full backend run passed 185 cases with zero failures and four OCR skips. **41 environment-isolation cases** are included: unsafe/missing configuration, explicit development mode, traversal/storage overlap, ownership markers, hardlinks, PostgreSQL naming, direct Playwright invocation, normal-app URL rejection, upload provenance, cross-environment requests, no startup document seeding, read-only inventory, conservative cleanup, migration reset protection and broker namespaces.

Existing coverage remains for PDF/OCR/spreadsheets/CSV, malformed files, schema and Decimal arithmetic, duplicates, comparison, corrections/audits, review gates, search, authorization, retry/cancellation/recovery and both reported invoice layouts. The four browser workflows use real upload/processing results: compound VAT and first-layout invoices, correction/search/comparison, valid/duplicate documents, corrupt-file retry and connected navigation. Their recorded isolated run passed four cases in 43.2 seconds; no development records were inserted.

The isolated evaluation run migrated its own database and persisted 14 document/job records. It processed 8/14 fixtures successfully; five OCR-dependent fixtures and the deliberately corrupt PDF failed visibly. Header accuracy on successful fixtures was 64/64. These are deterministic synthetic-fixture measurements, not live AI accuracy. The run's report includes pipeline/persistence time, so it should not be compared directly with the earlier reader-only timing.

Read-only snapshots taken before/after backend, browser and evaluation checks showed identical hashes for all **eight development tables and all 23 uploaded original files**. Both manually uploaded test invoices and the uploaded CV remained present. Full inventory and preservation evidence are private under `data/inspection/`; they are not committed because they describe the user's local records.

`docs/pytest-results.xml`, `docs/browser-results.json`, `docs/evaluation-results.json` and the earlier extraction/tax reports are historical checkpoints. New automated outputs go under ignored `data/verification/` or `data/evaluation/`; tests do not overwrite these committed artifacts. Live LLM/embeddings, PostgreSQL/Redis/Celery runtime and a 1000-page benchmark remain unverified.

## Inspect existing records

```powershell
.\.venv\Scripts\python scripts/inspect_records.py
```

This opens the database read-only and writes private CSV/JSON reports to `data/inspection/`. Each row contains filename, document ID, upload timestamp/status, likely source, whether test ownership is proven and cleanup eligibility. Checksums/filenames identify fixture resemblance only. Historical browser-test correction notes are evidence of likely origin, not sufficient deletion authorization. Manually uploaded documents and unknown-origin records are preserved.

For a preservation check, pass `--compare-snapshot <private-snapshot.json>` to compare logical table hashes and original-file hashes. Do not publish inventories, snapshots, `.env` or databases.

## Optional cleanup

The default command performs **no deletion**:

```powershell
.\.venv\Scripts\python scripts/cleanup_automated_records.py
```

For the inspected development database it lists zero eligible records and retains all 23. Development deletion is refused unconditionally. Legacy records have no trustworthy run provenance, so they cannot be auto-selected even when their names/checksums match fixtures. No cleanup `--apply` command was executed during this work, including tests.

To inspect a specific retained automation/evaluation run:

```powershell
.\.venv\Scripts\python scripts/cleanup_automated_records.py --environment evaluation --run-id <run-uuid>
```

The dry run lists exact document IDs, originals, related row counts and comparison references. Applying requires `--apply`, explicit `--ids <document-uuid> ...`, and `--confirm "DELETE AUTOMATED RECORDS <run-uuid>"`, in addition to the environment/run flags. Only rows carrying matching upload provenance with files in that owned run directory qualify. Active processing or references from retained records block cleanup. Filenames alone never qualify.

The optional SQLite-only apply path quarantines originals under the same run root and deletes selected metadata/dependencies in a database transaction. Errors before commit restore moved files; originals are never permanently purged. A durable `quarantine/<operation-uuid>/operation.json` records file moves. After a crash, `--recover <journal-path> --confirm "RECOVER AUTOMATED FILES <run-uuid>"` with the same run-selection flags reconciles file placement with committed document-row existence. Mixed/unexpected states require manual inspection. This optional destructive apply path was deliberately not exercised against application records; inspect the dry run and back up any retained automation data before choosing to apply.

## Prevent accidental loss

Never reset/delete `data/careguide.db`, `data/uploads/` or the whole `data/` tree to clear test records. Alembic upgrades remain available; development downgrades/resets are blocked. Safe fixture generation only creates repository inputs and never uploads/seeds documents. Celery queue names and Redis key prefixes include environment/run identity; restart API/workers together after this change. These controls protect the supplied automation entry points; arbitrary manual SQL/admin file operations remain outside their authority.

Workflow references: [Playwright web servers](https://playwright.dev/docs/test-webserver), [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
