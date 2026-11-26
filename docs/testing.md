# Tests, environment isolation and safe inspection

See the [reviewer handoff run](#reviewer-handoff-clean-clone) for the current setup and regression evidence. The checked-in JSON and XML reports document earlier verification runs, including the separate live Gemini evaluation with synthetic inputs.

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

`scripts/runtime_env.py` creates unique roots and ownership markers. Automated settings require explicit paths, environment, automation kind and run UUID. Paths are resolved, checked against protected development locations and their environment namespace, and must have a matching ownership marker. Pytest and Playwright do not load development settings or credentials. The opt-in live Gemini CLI uses its key and selected Gemini/OCR settings from the local file and refuses to run inside a process with cached application settings. The live PostgreSQL test creates its own run database and removes that database after closing its API and worker processes.

Pytest configures isolation before importing the app, migrates an isolated database through Alembic for API assertions and synchronous task dispatch for determinism, and closes/removes its run-owned database/uploads at teardown. It no longer regenerates committed fixtures. Each Playwright run migrates its own database and exercises the real local background process. It verifies `/api/environment` before each test and sends environment/run headers; the API rejects mismatched tagged requests before document insertion. New upload audit details identify the originating environment/run. Normal startup creates no fixture records.

Playwright servers shut down cooperatively before temporary directories are removed. The runner retains JSON reports/screenshots privately under `data/verification/playwright/<UUID>`. Databases and uploaded originals are not retained after a completed browser run. A hard process interruption may leave a marked temporary directory for inspection; it never authorizes deleting development data or legacy directories. No automatic broad cleanup of `data/` occurs.

## Coverage and actual evidence

The backend suite covers unsafe configuration, database and storage paths, hardlinks, PostgreSQL naming, wrong-server requests, audit provenance, read-only inspection, cleanup, migration reset protection and broker namespaces. The final isolation regression simulates a redirected run directory and verifies that both startup and cleanup reject it. The Gemini evaluation rejects a process with cached application settings.

The backend OCR suite covers JPG, PNG, multi-frame TIFF, image-only PDFs, multipage scans, and a mixed PDF with a text layer on its first page and a digital footer on its scanned second page. It checks original OCR text, source page evidence, Decimal arithmetic, blank scans, corrupt images, unsupported formats, a retry after restoring language configuration and manual correction with the original OCR warning retained. The fifth browser workflow uploads a multipage scan and checks the structured total, second-page evidence and passing validation through the isolated API and background worker. Existing browser workflows cover digital invoices, correction, review, search, comparison, duplicate warnings and failed-job retries.

Run `python -m pytest tests/test_pdf_security.py tests/test_ocr.py` with Tesseract configured to check PDF ingestion. Tests exercise normal authenticated uploads for digital, image-only, multipage and mixed PDFs containing a synthetic, structurally valid C2PA store. The tests compare downloaded originals byte for byte and assert page evidence and the normalization audit. Rejection cases cover malformed PDF structure, unrelated or mislabeled attachments, additional references, file annotations, JavaScript, OpenAction, Launch and stream expansion or size limits. The synthetic manifest tests cover framing and object associations. They use inert payloads and make no authenticity assertions.

The latest isolated evaluation processed 13 of 14 fixtures, with the deliberately corrupt PDF as the only failure. It matched 104 of 104 scored header values across successfully processed fixtures. The separate OCR benchmark processed seven of eight scan fixtures and measured nine OCR pages. See the [OCR evaluation results](evaluation-report.md#real-ocr-verification).

Read-only snapshots taken after the final cleanup and after the automated checks matched across all eight development tables and all 15 retained originals. The authenticated development API and Chromium displayed the same 15 IDs. Both manual invoices retained four line items and passed Decimal validation. All manual originals were checksum-verified through their download route, and the preview route returned images.

`docs/pytest-results.xml`, `docs/browser-results.json`, `docs/evaluation-results.json` and the earlier extraction/tax reports are historical checkpoints. New automated outputs go under ignored `data/verification/` or `data/evaluation/`. Local vector search, queue processing and PDF scale measurements are recorded in the [evaluation report](evaluation-report.md).

## PostgreSQL, Redis and Celery verification

Install the current lockfile and prime the model cache using the [README instructions](../README.md#local-semantic-search). Start Docker Desktop with Linux containers and export the Tesseract settings from [Windows OCR setup](setup-windows.md#ocr). Use two disposable containers with automatically assigned loopback ports:

```powershell
$tag = [guid]::NewGuid().ToString('N').Substring(0, 8)
$pg = "careguide-check-pg-$tag"
$redis = "careguide-check-redis-$tag"
$env:POSTGRES_PASSWORD = [guid]::NewGuid().ToString('N')
docker run --rm -d --name $pg --memory 512m --cpus 2 -e POSTGRES_PASSWORD -p 127.0.0.1::5432 pgvector/pgvector:pg17
docker run --rm -d --name $redis --memory 128m --cpus 1 -p 127.0.0.1::6379 redis:7-alpine
```

Wait for `docker exec $pg pg_isready -U postgres` to report ready, then run:

```powershell
$pgPort = (docker port $pg 5432/tcp).Split(':')[-1]
$redisPort = (docker port $redis 6379/tcp).Split(':')[-1]
$env:CAREGUIDE_TEST_POSTGRES_URL = "postgresql+psycopg://postgres:$($env:POSTGRES_PASSWORD)@127.0.0.1:$pgPort/postgres"
$env:CAREGUIDE_TEST_REDIS_URL = "redis://127.0.0.1:$redisPort/0"
.\.venv\Scripts\python -m pytest -q tests/test_service_stack.py
docker stop $pg $redis
Remove-Item Env:CAREGUIDE_TEST_POSTGRES_URL,Env:CAREGUIDE_TEST_REDIS_URL,Env:POSTGRES_PASSWORD
```

To run all backend tests with the live infrastructure check, run `.\.venv\Scripts\python -m pytest -q` in the same configured environment before stopping those containers. Run this separately from frontend builds or other CPU-heavy checks. The live integration test skips when either service URL is missing. It verifies migrations, persistence across an API restart, keyword and owner-filtered vector search, Redis queue delivery, page progress, duplicate deliveries, corrupt-file retry and simulated stale-lease recovery. Detailed metrics are saved privately under `data/verification/services-<UUID>/results.json`. The native test worker uses `solo` on Windows and prefork on Linux.

### Ubuntu WSL alternative

On Ubuntu 24.04 under WSL 2, install `postgresql-16`, `postgresql-16-pgvector` and `redis-server` using `sudo apt update` and `sudo apt install postgresql-16 postgresql-16-pgvector redis-server`. Start each service with `sudo service postgresql start` and `sudo service redis-server start`. Provision a dedicated database before using it from CareGuide:

```sh
sudo -u postgres createuser --pwprompt careguide_app
sudo -u postgres createdb -O careguide_app careguide_sandbox
sudo -u postgres psql -d careguide_sandbox -c 'CREATE EXTENSION IF NOT EXISTS vector'
pg_isready
redis-cli ping
```

Use this database, its own upload directory and matching Redis URL when launching the API and worker. Set `EXECUTION_MODE=celery` before starting both processes. Keep both processes on the same OS for compatible stored file paths. An independent WSL service install was not needed for the verified Docker infrastructure path. [pgvector installation](https://github.com/pgvector/pgvector)

Run `.\.venv\Scripts\python scripts/benchmark_scaling.py` with OCR configured to reproduce the isolated PDF benchmark. Each fixture runs in a fresh Python process, and output stays under `data/evaluation/<UUID>/scaling-benchmark.json`.

## Clean Windows reproduction

### Reviewer handoff clean clone

A fresh clone from `710b62d` received the reviewer setup changes and used its own `.env`, account, database, upload directory and public model cache. The handoff ran on Windows with Python 3.13.5, Node.js 22.17.0, Docker Engine 28.3.0, and Compose v2.38.1. The Python lockfile and the npm dependency tree were installed into the clone. The checkout provisioned its own SQLite database with Alembic, and rerunning the initializer left `.env` intact.

| Workflow | Evidence |
| --- | --- |
| SQLite Quick Start | Reviewer login, authenticated uploads, keyword search, two-page OCR using Windows Tesseract 5.5.4, and PDF/Excel comparison showing 220.00 versus 225.00. SQLite correctly reported semantic search unavailable. |
| Docker Full Stack | Fresh Linux API and worker images, PostgreSQL 17.12, pgvector 0.8.7, Redis 7.4.9, English Tesseract 5.5.0, and a fresh FastEmbed model download. Celery processed the digital invoice and two-page scan. The scan passed Decimal validation at USD 176.00, with OCR evidence from both pages. |
| Local semantic search | The paraphrase `equipment for digitizing paperwork` ranked the digital invoice first, with page 1 and exact source offsets. PostgreSQL stored six 384-dimensional chunks across the four sample uploads. Both searches were checked in Chromium, including opening the linked semantic result. The literal `Document Scanner Accessories` worked in keyword search on both databases. |
| Backend automation | 288 passed, zero failed and zero skipped on the full sequential rerun (77.05 s), including PostgreSQL migrations, Redis/Celery and OCR. An initial run during concurrent frontend work hit HTTP 429 while polling an OCR retry and ended with 287 passed and one failed. |
| Frontend automation | Six Chromium workflows passed with zero failures and zero skips. TypeScript and the production build passed. |
| Gemini | The clean clone had no reviewer API key. The access command reported the missing configuration. The [recorded live Gemini evaluation](evaluation-report.md#gemini-invoice-extraction) is earlier evidence. |

The host already had Git, Python, Node.js, Docker Desktop, native Tesseract and a Playwright Chromium cache. The initial fresh clone did not contain project dependencies, credentials, uploaded documents, databases or a model cache. Linux containers were run on Docker Desktop. A fresh Docker Desktop installation, native Linux and WSL service installation were outside this run.

### Earlier release evidence

A separate checkout of GitHub main was created from `e8fc3e3`. A fresh virtual environment installed the repository lockfile, `npm.cmd ci --prefix apps/web` installed the frontend lock, and `scripts/setup-local.ps1 -SkipInstall` generated a new private configuration and migrated fresh SQLite to `0002`. The audit changes were then applied to that checkout and the updated Pillow lock was installed. A previously absent verification directory exposed a stack-test setup issue. The fixed test creates its own reports directory.

The fresh clone started its API and frontend on separate loopback ports and signed in using its generated account. It fetched its own public BGE model files and produced a 384-dimensional vector. Its runtime used the existing native Tesseract executable and English language data. The scratch live Gemini check temporarily read the configured free-tier key through the local environment file and removed it from the scratch file after the run. Docker provided disposable PostgreSQL and Redis. The audit did not reinstall Docker Desktop or Tesseract, execute the WSL install, or run the Linux prefork Compose worker.

See the [quick start](../README.md#quick-start--windows-no-paid-services), [OCR setup](setup-windows.md#ocr), and [isolated services](#postgresql-redis-and-celery-verification) to reproduce these steps. Keep the API and frontend ports consistent with `NEXT_PUBLIC_API_URL` and `CORS_ORIGIN` when the normal development app is already running.

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

The earlier cleanup removed one confirmed historical test upload. The final audit recovered additional archived launch/completion evidence, backed up the then-current 22 originals, and removed seven more historical test records. The final audit kept every active comparison and followed its retained document references before selecting removals. See the [development cleanup report](development-document-cleanup-report.md) for classifications, verification and the private artifact layout.

Workflow references: [Playwright web servers](https://playwright.dev/docs/test-webserver), [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
