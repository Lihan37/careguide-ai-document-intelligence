# Tests, environment isolation and safe inspection

The verification environment used Windows, Python 3.13, Node 22.17 and Tesseract 5.5.4 with English traineddata. **228 backend tests and five isolated browser workflows passed**, with zero failures and zero skips. TypeScript and the production build also passed.

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

To include real OCR, export `TESSERACT_CMD`, `TESSERACT_DATA_DIR` and `OCR_LANGUAGE=eng` in the same PowerShell session. The [Windows installation instructions](setup-windows.md#ocr) include the exact commands for the verified project-local installation. Pytest, Playwright and evaluation inherit these variables without reading development credentials. Run `python scripts/benchmark_ocr.py` using the project virtual environment for timings and a private JSON report under `data/evaluation/`. The benchmark reads the committed synthetic fixtures without connecting to a database.

| Purpose | Environment and locations |
| --- | --- |
| Development | APP_ENV=development; existing `.env` retained. Defaults: `data/careguide.db`, `data/uploads/`. |
| Backend tests | APP_ENV=test, AUTOMATION_KIND=pytest; fresh `data/test-runs/<UUID>/careguide.db`, `uploads/`, and pytest temporary files. |
| Browser tests | APP_ENV=test, AUTOMATION_KIND=playwright; fresh database/uploads under `data/test-runs/<UUID>`, source-only frontend copy under `apps/web/.test-runs/<UUID>`, independent loopback ports and generated credentials. |
| Evaluation | APP_ENV=evaluation, AUTOMATION_KIND=evaluation; fresh `data/evaluation/<UUID>/careguide.db`, copied `fixtures/`, `uploads/`, metrics/report files. |

`scripts/runtime_env.py` creates unique roots and ownership markers. Automated settings require explicit paths, environment, automation kind and run UUID. Paths are resolved, checked against protected development locations and their environment namespace, and must have a matching ownership marker. Pytest and Playwright do not load development settings or credentials. The opt-in live Gemini CLI reads only its key and selected Gemini/OCR settings from the local file, writes to a dedicated evaluation directory, and refuses to run inside a process with cached application settings. Development cannot reuse test/evaluation paths. Automated PostgreSQL DB names must include the environment and run ID. PostgreSQL configuration is covered by tests and its runtime remains unverified.

Pytest configures isolation before importing the app, migrates an isolated database through Alembic for API assertions and synchronous task dispatch for determinism, and closes/removes its run-owned database/uploads at teardown. It no longer regenerates committed fixtures. Each Playwright run migrates its own database and exercises the real local background process. It verifies `/api/environment` before each test and sends environment/run headers; the API rejects mismatched tagged requests before document insertion. New upload audit details identify the originating environment/run. Normal startup creates no fixture records.

Playwright servers shut down cooperatively before temporary directories are removed. The runner retains JSON reports/screenshots privately under `data/verification/playwright/<UUID>`. Databases and uploaded originals are not retained after a completed browser run. A hard process interruption may leave a marked temporary directory for inspection; it never authorizes deleting development data or legacy directories. No automatic broad cleanup of `data/` occurs.

## Coverage and actual evidence

The backend suite covers unsafe or missing configuration, database and storage paths, ownership markers, hardlinks, PostgreSQL naming, wrong-server requests, audit provenance, read-only inspection, cleanup, migration reset protection and broker namespaces. Gemini evaluation has a regression test that rejects a process with cached app settings before reading a credential or changing the environment.

The backend OCR suite covers JPG, PNG, multi-frame TIFF, image-only PDFs, multipage scans, and a mixed PDF with a text layer on its first page and a digital footer on its scanned second page. It checks original OCR text, source page evidence, Decimal arithmetic, blank scans, corrupt images, unsupported formats, a retry after restoring language configuration and manual correction with the original OCR warning retained. The fifth browser workflow uploads a multipage scan and checks the structured total, second-page evidence and passing validation through the isolated API and background worker. Existing browser workflows cover digital invoices, correction, review, search, comparison, duplicate warnings and failed-job retries.

The latest isolated evaluation processed 13 of 14 fixtures, with the deliberately corrupt PDF as the only failure. It matched 104 of 104 scored header values across successfully processed fixtures. The separate OCR benchmark processed seven of eight scan fixtures and measured nine OCR pages. See the [OCR evaluation results](evaluation-report.md#real-ocr-verification).

Read-only snapshots taken after the reviewed cleanup and after the automated checks showed identical hashes for all eight development tables and all 22 retained originals. Both manual invoices were re-extracted locally without changing their records. Each produced four line items and passed Decimal validation.

`docs/pytest-results.xml`, `docs/browser-results.json`, `docs/evaluation-results.json` and the earlier extraction/tax reports are historical checkpoints. New automated outputs go under ignored `data/verification/` or `data/evaluation/`. Live Gemini results are reported separately. Live embeddings, PostgreSQL/Redis/Celery runtime and a 1,000-page benchmark remain unverified. [Evaluation report](evaluation-report.md)

## Inspect existing records

```powershell
.\.venv\Scripts\python scripts/inspect_records.py
```

This opens the database read-only and writes private CSV/JSON reports to `data/inspection/`. Each row contains filename, document ID, upload timestamp, status, original path, likely source and cleanup eligibility. Filenames, hashes and historical correction notes alone cannot establish that automation created a record.

For a preservation check, pass `--compare-snapshot <private-snapshot.json>` to compare logical table hashes and original-file hashes. Do not publish inventories, snapshots, `.env` or databases.

## Optional cleanup

The default command performs **no deletion**:

```powershell
.\.venv\Scripts\python scripts/cleanup_automated_records.py
```

The generic script lists zero auto-eligible development records and refuses development `--apply`. It applies to uploads carrying explicit isolated-run provenance. For the reviewed historical upload, see the one-time local cleanup below.

To inspect a specific retained automation/evaluation run:

```powershell
.\.venv\Scripts\python scripts/cleanup_automated_records.py --environment evaluation --run-id <run-uuid>
```

The dry run lists exact document IDs, originals, related row counts and comparison references. Applying requires `--apply`, explicit `--ids <document-uuid> ...`, and `--confirm "DELETE AUTOMATED RECORDS <run-uuid>"`, in addition to the environment/run flags. Only rows carrying matching upload provenance with files in that owned run directory qualify. Active processing or references from retained records block cleanup. Filenames alone never qualify.

The optional SQLite-only apply path quarantines originals under the same run root and deletes selected metadata/dependencies in a database transaction. Errors before commit restore moved files; originals are never permanently purged. A durable `quarantine/<operation-uuid>/operation.json` records file moves. After a crash, `--recover <journal-path> --confirm "RECOVER AUTOMATED FILES <run-uuid>"` with the same run-selection flags reconciles file placement with committed document-row existence. Mixed/unexpected states require manual inspection. This optional destructive apply path was deliberately not exercised against application records; inspect the dry run and back up any retained automation data before choosing to apply.

## Prevent accidental loss

Never reset/delete `data/careguide.db`, `data/uploads/` or the whole `data/` tree to clear test records. Alembic upgrades remain available; development downgrades/resets are blocked. Safe fixture generation only creates repository inputs and never uploads/seeds documents. Celery queue names and Redis key prefixes include environment/run identity; restart API/workers together after this change. These controls protect the supplied automation entry points; arbitrary manual SQL/admin file operations remain outside their authority.

## Development backup and historical cleanup

Before any authorized local cleanup, take a SQLite online backup with Python's `sqlite3.Connection.backup()` from the development database opened read-only. Copy the full upload tree to a private directory inside ignored `data/`. Verify the copy with `PRAGMA integrity_check` and `PRAGMA foreign_key_check`, compare the copied database with the source logically, and compare SHA-256 for each copied original. Stop active jobs and confirm the live paths, plan and verified backup still match before applying changes. Remove selected database rows and dependents in a single transaction, validate integrity, then quarantine the affected originals. Retain the backup and operation journal for recovery.

The historical Playwright config used the normal development frontend. Its archived passing report matched five uploads in its two recorded test windows, supported by the exact upload order and scripted audit notes. One confirmed corrupt-PDF upload had no references from retained records and was removed. Four confirmed uploads remain because other records reference them. Other similar uploads remain for review because no equally strong run evidence was available. The generic isolated-run cleanup rules remain unchanged.

The private dry run, verified database and 23-original backup, and quarantine journal are under `data/inspection/archived-browser-cleanup/`. Follow-up comparison confirmed all 22 retained records, their dependents, comparisons, users and original checksums match the backup. Both manual invoices and the résumé were preserved.

Workflow references: [Playwright web servers](https://playwright.dev/docs/test-webserver), [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
