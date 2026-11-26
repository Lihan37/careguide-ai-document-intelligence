# CareGuide AI Document Intelligence

CareGuide reduces the manual work of reading and reconciling financial documents. Upload files, inspect invoice fields and their sources, verify arithmetic, compare PDF and Excel records, and correct or search results. Originals stay private and corrections retain audit history.

Digital, scanned and mixed PDFs use the same upload flow. Supported document-level C2PA provenance is checked automatically, and only page text or raster pixels reach extraction. The private original remains available as a download. Unsupported attachments and active PDF content are rejected. [PDF ingestion and security](docs/security.md#pdf-ingestion-and-content-credentials)

Built against the supplied **Ai Engineer Task 1.3.pdf** (seven tasks, nine deliverables). The application is intended for local demonstration; no deployment was performed. All bundled financial records are clearly synthetic.

**Verified:** SQLite and PostgreSQL with pgvector, CPU semantic search, Redis/Celery with a real worker, authenticated API, PDF/image/spreadsheet parsing, Tesseract OCR, live Gemini on bundled synthetic invoices, Decimal validation, manual correction, comparisons and Chromium workflows. See the [measured results](docs/evaluation-report.md) and [assessment compliance matrix](docs/assessment-compliance.md).

![Dashboard with real synthetic records](docs/dashboard-preview.png)

## Quick start — Windows, no paid services

From the cloned repository root, with Python 3.13 and Node 22:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup-local.ps1 -SkipInstall
npm.cmd ci --prefix apps/web
```

The script creates a private ignored development `.env` with random credentials and migrates SQLite. Committed synthetic fixtures are reused; they are generated only if missing. It does not seed uploaded documents. Read DEMO_PASSWORD in your editor; username is `reviewer`. It does not print secrets. No venv activation or permanent execution-policy change is required.

Run in separate terminals:

```powershell
# Terminal 1 — API and local background processor
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2 — frontend
npm.cmd run dev --prefix apps/web
```

Open **http://localhost:3000**. API docs: **http://localhost:8000/docs**. Use localhost consistently for browser/API cookies. A production frontend build can be served with `npm.cmd run build --prefix apps/web`, then `npm.cmd run start --prefix apps/web`.

## Architecture and structure

Next.js App Router/TypeScript/Tailwind frontend → FastAPI/Pydantic API → SQLAlchemy database/private file storage → local process or Redis/Celery → bounded readers → structured extraction → deterministic validation → review/search/comparison. PostgreSQL with pgvector is the target service stack; durable SQLite is the verified single-machine fallback. [Architecture diagram and decisions](docs/architecture.md), [database schema](docs/database-schema.md).

```text
apps/web/                  Next.js routes, reusable page components, Playwright
services/api/app/          API/auth, ORM, readers, extraction, finance, search, jobs
services/api/migrations/   Alembic schema
worker/                   Celery task entry point
scripts/                  local setup, synthetic fixtures, evaluation, password reset
tests/                    processing, finance, API, failure and security tests
sample-data/              synthetic PDFs, images, multi-sheet/legacy workbooks, CSV, truth
docs/                     architecture, API, setup, evidence, disclosure and demo script
docker-compose.yml        PostgreSQL/pgvector, Redis, API and Linux OCR worker
```

## Features and routes

| Frontend | Function |
| --- | --- |
| / | Real database counts, recent documents, processing activity and file distribution |
| /upload | Multi-file selection/drop, size/type checks, upload progress, per-file results |
| /documents | Search, status/format filters, pagination and source links |
| /documents/{id} | Private source preview, extracted/effective fields, evidence, validation, corrections, history |
| /jobs | Live processing stage, progress, retries, cancellation and stale recovery |
| /review | Unapproved exceptions with source-linked document review |
| /comparison | Multi-document baseline comparison, sheet/row/column mapping, differences and saved snapshots |
| /search | Independent keyword retrieval and optional pgvector semantic matches with page or sheet references |
| /evaluation | Saved measured evaluation, methodology and capability limitations |
| /settings | Safe provider/OCR/database configuration status and readiness check |

The API implements uploads, lists/details/status/extraction/validation/source, retries, corrections, jobs, search, comparisons, review and evaluation. See [full route reference](docs/api-reference.md) and generated OpenAPI. Originals remain private; all financial routes require authentication, ownership and appropriate reviewer authorization.

## Environment and services

Copy values deliberately from `.env.example`; do not overwrite the generated local credentials accidentally.

| Variable | Purpose |
| --- | --- |
| DATABASE_URL | SQLite local URL or PostgreSQL psycopg URL |
| APP_ENV | `development` by default; automated runners explicitly use `test` or `evaluation` |
| EXECUTION_MODE | `local` separate-process fallback or `celery` |
| REDIS_URL | Broker address in Celery mode |
| STORAGE_DIR | Private originals, default ./data/uploads |
| SESSION_SECRET | At least 32 random characters; rotate to invalidate sessions |
| DEMO_USERNAME / DEMO_PASSWORD | Local initial account; password at least 12 characters |
| POSTGRES_PASSWORD | Required by Compose; use a strong URL-safe password |
| EXTRACTION_MODE | `deterministic_demo`, `gemini_auto`, `gemini`, or `llm` |
| LLM_API_KEY / LLM_BASE_URL / LLM_MODEL | Private structured-output provider configuration |
| MAX_LLM_CHUNKS | Maximum provider chunks per document, default 100; not a dollar spending cap |
| GEMINI_API_KEY | Gemini credential read by the native Python backend from the ignored project-root `.env` |
| GEMINI_MODEL | Defaults to `gemini-3.5-flash-lite` |
| GEMINI_TIMEOUT_SECONDS / GEMINI_MAX_REQUESTS / GEMINI_MAX_OUTPUT_TOKENS | Defaults of 20 seconds per request, 6 attempts per document including retries, and 4096 output tokens per request |
| EMBEDDINGS_ENABLED / EMBEDDING_PROVIDER | Enable PostgreSQL vector indexing and choose `local` or `openai` |
| EMBEDDING_CACHE_DIR | Local FastEmbed model files, default `data/embedding-models` |
| EMBEDDING_MODEL / EMBEDDING_DIMENSIONS | Configurable OpenAI-compatible embedding model and dimensions |
| TESSERACT_CMD | Native Tesseract executable path. Falls back to `tesseract` on PATH when empty. |
| TESSERACT_DATA_DIR | Optional language-data directory containing `.traineddata` files |
| OCR_LANGUAGE / OCR_REVIEW_THRESHOLD | Language code or combination such as `eng+ben`, and mean word confidence threshold for review (default 0.80) |
| MAX_FILE_MB / MAX_UPLOAD_FILES / MAX_PAGES | Resource limits (defaults 30 / 10 / 1200) |
| OCR_TIMEOUT / JOB_TIMEOUT | Per-OCR and processing budgets (30 / 3600 seconds) |
| CURRENCY_TOLERANCES | Optional JSON currency→decimal-string tolerance overrides |
| NEXT_PUBLIC_API_URL / CORS_ORIGIN | Browser API URL and permitted frontend origin |

The default quick start uses SQLite and a separate local worker process. For the verified PostgreSQL/Redis route, start Docker Desktop, launch infrastructure with `docker compose up -d postgres redis`, and follow [isolated stack verification](docs/testing.md#postgresql-redis-and-celery-verification). That procedure uses a fresh PostgreSQL database and private upload directory for each run. An Ubuntu WSL alternative is documented there. The normal SQLite database and its uploads can remain in place.

### Local semantic search

Install the current Python lockfile and fetch the free English BGE model once from the repository root:

```powershell
.\.venv\Scripts\python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='data/embedding-models', threads=2)"
```

For a separately configured PostgreSQL application, apply Alembic migrations to that database, set `EMBEDDINGS_ENABLED=true` and `EMBEDDING_PROVIDER=local`, then start the API and worker with the same cache path and settings. Processing new originals stores 384-dimensional vectors. Reprocessing an existing document indexes it with the selected model. Keyword results remain available independently. The local model runs offline after download. [FastEmbed model reference](https://qdrant.tech/documentation/embeddings/fastembed/)

## Optional Gemini extraction on Windows

1. Install the updated Python lockfile with `.\.venv\Scripts\python -m pip install -r requirements-lock.txt`.
2. In Google AI Studio, create a Gemini API key in an eligible unbilled project. Confirm that the model is available on the project’s free tier and leave billing disabled. Google lists Gemini 3.5 Flash-Lite on the free tier where available. [Create an API key](https://aistudio.google.com/apikey) · [Gemini API pricing and data usage](https://ai.google.dev/gemini-api/docs/pricing)
3. Open the existing project-root `.env` in your editor and add the key there. Use a literal value with no shell substitution. Keep the rest of the local settings.

   ```dotenv
   GEMINI_API_KEY=<paste your Google AI Studio key here>
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```

4. Run `.\.venv\Scripts\python -m scripts.evaluate_gemini --check-access` to verify model lookup without generation. After confirming free-tier quota in AI Studio, run `.\.venv\Scripts\python -m scripts.evaluate_gemini --run-live` from the repository root. The evaluation sends three bundled synthetic invoices, including one two-page scan, and reports expected and actual fields, validation, latency, request attempts and available token counts in `data/evaluation/<UUID>/gemini-results.json`.
5. Set `EXTRACTION_MODE=gemini_auto` in the same `.env` and restart the API and any separate worker. Upload a synthetic invoice and inspect the extraction method and evidence on its detail page. Use `EXTRACTION_MODE=gemini` to send each processed invoice to Gemini, including simple documents. Use `deterministic_demo` for an offline workflow. Existing `llm` mode continues to use the configured OpenAI-compatible provider.

`gemini_auto` keeps the local result when the parser has all required invoice and core line-item fields, reports no issues, passes Decimal validation and has sufficient OCR confidence. Documents routed to Gemini display `llm:gemini:<model>` after successful extraction. Provider errors are visible and can be retried through the existing job flow.

Gemini receives extracted text from files routed to it. Use synthetic fixtures for free-tier verification. Check your organization's data-sharing rules and Google's data terms before sending private invoices. The request limits bound attempts and output per document. The API does not enforce project-wide spending. [Gemini API pricing and data usage](https://ai.google.dev/gemini-api/docs/pricing) · [Measured live results](docs/evaluation-report.md#gemini-invoice-extraction)

## Migrations, tests and evaluation

```powershell
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m pytest -q --junitxml=data/verification/pytest-results.xml
.\.venv\Scripts\python scripts/evaluate.py
npm.cmd run build --prefix apps/web
```

Run `npm.cmd run test:e2e --prefix apps/web` after `npx.cmd --prefix apps/web playwright install chromium`. It starts its own API/frontend on separate loopback ports, generates temporary credentials, migrates an isolated database, verifies the server environment, and removes its temporary database/uploads/frontend copy after stopping servers. The normal app may remain running. Direct `npx playwright test` is intentionally rejected without runner context. [Testing and isolation](docs/testing.md); checked-in evaluation reports are historical snapshots.

| Environment | Database and private files |
| --- | --- |
| Development | Existing `.env` is preserved. Default SQLite is `data/careguide.db`; originals are in `data/uploads/`. |
| Pytest / Playwright | Fresh `data/test-runs/<UUID>/careguide.db` and `uploads/` per run; no development `.env` loading or default-path fallback. Temporary data is removed after tests. Reports remain under `data/verification/`. |
| Evaluation | Fresh `data/evaluation/<UUID>/careguide.db`, copied `fixtures/`, and `uploads/`; reports remain in the same run folder. No development document rows are written. The Evaluation page can read `data/evaluation/latest-results.json`. |

Automation requires explicit environment, kind, run UUID, ownership marker, database and storage paths. Paths must belong to the matching run namespace. The runtime rejects redirected run directories and ownership markers. Browser identity checks and tagged requests protect the normal API. Celery queue names and Redis prefixes are scoped by run. Development database downgrade/reset commands are blocked.

Inspect existing records without modifying them:

```powershell
.\.venv\Scripts\python scripts/inspect_records.py
.\.venv\Scripts\python scripts/cleanup_automated_records.py
```

The inventory is saved privately to `data/inspection/records-report.csv` and JSON, including filename, ID, upload time, status, likely source, original path and cleanup eligibility. The generic cleanup script is **dry-run by default** and applies only to isolated runs. The separate [development cleanup audit](docs/development-document-cleanup-report.md) describes the historical record reconciliation.

The Windows OCR run used the project-local Tesseract 5.5.4 build. It processed 13/14 files in the original evaluation and 7/8 in a dedicated scan benchmark. The deliberate corrupt files failed. The scan benchmark includes image-only, multipage and mixed PDFs. See the [measured results and limitations](docs/evaluation-report.md) and [Windows setup](docs/setup-windows.md#ocr).

## Demonstration and submission

Upload `sample-data/invoice.pdf` and `accounting.xlsx`, open **Processing Jobs**, then compare the results in **Document Comparison**. The totals differ by 5. Use `incorrect-total.pdf` to demonstrate a 250-to-220 audited correction and `ocr/multipage.pdf` for real OCR on both pages. Use the separate scratch-workspace instructions for the live AI and semantic-search segments. [7:40 recording plan](docs/demo-script.md)

The technical handoff includes the [assessment matrix](docs/assessment-compliance.md), [clean Windows verification](docs/testing.md#clean-windows-reproduction), [evaluation report](docs/evaluation-report.md), and [AI prompts and disclosure](docs/ai-assistance-disclosure.md). Record the actual walkthrough and include it with those links when preparing the recruitment submission.

## Security and limits

The API enforces authentication and per-owner document access. Upload size, format, page and pixel limits constrain untrusted inputs. Provider calls use structured output and retained source evidence. Private originals, credentials and run artifacts belong in ignored local paths. The audit verified these controls with synthetic data. Production hardening and sustained throughput remain separate work. [Security scope](docs/security.md) · [Known limitations](docs/limitations.md)
