# Windows setup

Use PowerShell from the root of your clone. The reviewer setup targets Python 3.13 and Node.js 22. For Docker, use Docker Desktop in Linux container mode or Docker Engine with the Compose v2 plugin and `docker compose up --wait` support. Native OCR requires Tesseract 5 and traineddata for each configured language. Install VS Code Python tooling if desired and select `.venv\Scripts\python.exe` as the interpreter.

## Local mode without Docker or paid services

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup-local.ps1 -SkipInstall
npm.cmd ci --prefix apps/web
```

The script creates an ignored `.env` with unique local credentials, applies migrations, and generates synthetic fixtures if they are missing. Read `DEMO_PASSWORD` privately in your editor and use it with username `reviewer`. The command scopes execution policy to one PowerShell process. On a managed machine where PowerShell scripts are disabled, initialize with `.\.venv\Scripts\python scripts/init_reviewer_env.py`, create the data directory with `New-Item -ItemType Directory -Force data`, and run `.\.venv\Scripts\python -m alembic upgrade head`.

Terminal 1:

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
npm.cmd run dev --prefix apps/web
```

Open **http://localhost:3000**. Use `localhost` consistently; browsing frontend at `127.0.0.1` while API is configured for `localhost` can break host-scoped cookies/CORS. The local API creates the configured user on first startup, after migrations. Changing DEMO_PASSWORD later does not reset an existing user; use `scripts/reset-password.py` explicitly. Local processing starts its own separate process; no worker terminal or Redis is needed. SQLite is persistent under `data/`, and semantic search remains disabled.

## Semantic search for an existing local workspace

Start Docker Desktop and prepare the FastEmbed model cache using the [model setup in the README](../README.md#local-semantic-search). From the project root, initialize the dedicated PostgreSQL 17 profile. It uses a named Docker volume on `127.0.0.1:55432` and generates its own password under ignored `data/semantic-dev/`. The original `.env`, SQLite database and upload directory remain in place.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\semantic-local.ps1 Initialize
```

Initialization verifies SQLite integrity and upload checksums before applying migrations to the new database. It then checks copied rows, IDs, ownership and foreign keys, and indexes the saved page and worksheet text locally. It keeps the verified backup and reports in `data/semantic-dev/backup` and `data/semantic-dev/migration-report.json`. Finish any outstanding processing first. If the original workspace changes during the initial copy, keep SQLite active until the snapshot and copy can be reconciled.

You can preview the PostgreSQL API on port 8001 while the SQLite API remains on 8000. Close the preview with Ctrl+C when finished.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\semantic-local.ps1 Start -Port 8001
```

To switch the normal localhost frontend to the verified copy, stop the idle API and check that the SQLite records and uploads still match the verified backup. Start the PostgreSQL-backed API on port 8000. The same command starts PostgreSQL if needed. The existing local document processing mode handles new jobs, so Redis is optional for this profile.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\semantic-local.ps1 StopApi
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\semantic-local.ps1 VerifySource
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\semantic-local.ps1 Start
```

In another terminal, run `npm.cmd run dev --prefix apps/web` if the frontend is stopped. Open **http://localhost:3000/search**. Keyword search runs independently. Semantic search uses FastEmbed’s English BGE model and exact cosine ranking over owner-filtered 384-dimensional pgvector rows. The database has lookup indexes for owner and embedding model/document. Results link to the stored PDF page or worksheet. [FastEmbed supported models](https://qdrant.github.io/fastembed/examples/Supported_Models/) · [pgvector filtering](https://github.com/pgvector/pgvector#filtering)

### Return to SQLite

Stop the current API and start the original profile. In a separate terminal, you can stop the PostgreSQL container while retaining its volume and private upload directory.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\semantic-local.ps1 StopApi
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\semantic-local.ps1 StartSQLite
# Optional, in another PowerShell terminal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\semantic-local.ps1 StopPostgres
```

Each profile keeps its own edits after the copy. Edits made while PostgreSQL is active remain in that profile when you return to SQLite. Use `Start` again to return to PostgreSQL and its later edits.

## OCR

The following PowerShell commands install the verified 64-bit Windows build, Tesseract 5.5.4 from conda-forge, inside ignored project data. Run from the project root in a normal PowerShell terminal. The setup uses the upstream micromamba download, a project-local package cache, and about 217 MB of package downloads. It requires no administrator access. [Micromamba Windows instructions](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html#windows) · [conda-forge Tesseract](https://anaconda.org/channels/conda-forge/packages/tesseract)

```powershell
$ocrTools = Join-Path (Get-Location) 'data/ocr-tools'
New-Item -ItemType Directory -Force $ocrTools | Out-Null
Invoke-WebRequest https://micro.mamba.pm/api/micromamba/win-64/latest -OutFile "$ocrTools/micromamba.tar.bz2"
tar.exe -xf "$ocrTools/micromamba.tar.bz2" -C $ocrTools Library/bin/micromamba.exe
$env:MAMBA_ROOT_PREFIX = "$ocrTools/cache"
& "$ocrTools/Library/bin/micromamba.exe" --no-rc create --yes --override-channels -c conda-forge -p "$ocrTools/tesseract" tesseract=5.5.4
$env:TESSERACT_CMD = "$ocrTools/tesseract/Library/bin/tesseract.exe"
$env:TESSERACT_DATA_DIR = "$ocrTools/tesseract/share/tessdata"
$env:OCR_LANGUAGE = 'eng'
& $env:TESSERACT_CMD --version
& $env:TESSERACT_CMD --list-langs --tessdata-dir $env:TESSERACT_DATA_DIR
```

For normal development, put the three settings in the ignored `.env` using the paths above. You can also use paths relative to the repo when starting the API from the root. The verified local values are:

```dotenv
TESSERACT_CMD=data/ocr-tools/tesseract/Library/bin/tesseract.exe
TESSERACT_DATA_DIR=data/ocr-tools/tesseract/share/tessdata
OCR_LANGUAGE=eng
```

If you already have the [UB Mannheim Windows distribution](https://github.com/UB-Mannheim/tesseract/wiki), use its `tesseract.exe` and `tessdata` directory instead. Ask your administrator to install that distribution if your organization requires a managed system-level installation. Required models must appear in `--list-langs`. Set `OCR_LANGUAGE=eng+ben` to enable English and Bengali together when both are available. The Docker image includes English; add other traineddata to the worker image and configure both services consistently. [Tesseract installation guide](https://tesseract-ocr.github.io/tessdoc/Installation.html)

Restart the API and any separate worker, then check OCR availability in Settings. Keep the PowerShell environment variables exported for isolated tests and evaluation because those runners do not load development configuration. See [testing commands](testing.md#safe-commands). OCR uses the native executable with an explicit argument vector so Windows language-data paths with spaces work.

## PostgreSQL, Redis and Celery with Docker

Start Docker Desktop in Linux container mode. With a fresh clone, run the following from the repository root. The initializer generates a separate URL-safe `POSTGRES_PASSWORD` for this checkout. When reusing a checkout with an existing `.env`, keep its current credentials and fill in `POSTGRES_PASSWORD` if empty. If a PostgreSQL volume already exists, use the password it was initialized with.

```powershell
docker compose version
python scripts/init_reviewer_env.py
npm.cmd ci --prefix apps/web
```

For the container-only backend, edit the ignored `.env` in your editor and set `EMBEDDINGS_ENABLED=true`, `EMBEDDING_PROVIDER=local`, `EXTRACTION_MODE=deterministic_demo`, and `OCR_LANGUAGE=eng`. Compose supplies its internal PostgreSQL, Redis, and file paths. Its PostgreSQL data and uploads are separate from the native SQLite workspace.

```powershell
docker compose build api worker
docker compose run --rm --no-deps api python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/app/data/embedding-models', threads=2)"
docker compose up -d --wait
docker compose ps
npm.cmd run dev --prefix apps/web
```

The initial build and model download need internet access. The local model runs offline after download. The API applies Alembic migrations, becomes ready, and creates the `reviewer` account. The worker starts after API readiness. Open **http://localhost:3000** and sign in with the `DEMO_PASSWORD` in the checkout's `.env`. In **Settings**, check PostgreSQL, Celery, OCR, and semantic availability. Upload `sample-data/layout-invoice.pdf` and `sample-data/ocr/multipage.pdf`, then use the search and source checks in the [reviewer walkthrough](../README.md#demonstration-and-submission).

Use `docker compose logs --tail 100 api worker` for recent service logs, `docker compose exec worker tesseract --list-langs` for OCR language availability, and `docker compose exec redis redis-cli ping` for broker readiness. Stop the frontend with `Ctrl+C` and run `docker compose stop` to stop containers and retain their named volumes. The app remains local to loopback. Stop any other backend on port 8000 before starting. For a different API port, set `CAREGUIDE_API_PORT` in `.env` and `NEXT_PUBLIC_API_URL` to the corresponding `http://localhost:<port>` in the frontend terminal. Set `CAREGUIDE_POSTGRES_PORT` or `CAREGUIDE_REDIS_PORT` in `.env` if the corresponding host ports are occupied.

### Native API and worker with Docker infrastructure

Use this path to combine the full local stack with a native Gemini key. Complete the [Windows Quick Start](../README.md#quick-start--windows-no-paid-services) installation, stop the native API, and set up [native OCR](#ocr) if you will evaluate scans. Use a fresh clone or a separate Compose project if you already uploaded records with the container API, because PostgreSQL records store paths specific to the API runtime that wrote them. Start just the database and broker using `docker compose up -d --wait postgres redis`. In the private `.env`, set the following values. Replace the password placeholder with that checkout's generated `POSTGRES_PASSWORD`. Keep the database and broker host ports in sync with any `CAREGUIDE_*_PORT` overrides. Preserve your SQLite database and originals in their existing locations.

```dotenv
DATABASE_URL=postgresql+psycopg://careguide:<your-generated-postgres-password>@localhost:5432/careguide
REDIS_URL=redis://localhost:6379/0
EXECUTION_MODE=celery
STORAGE_DIR=./data/uploads-postgres
EMBEDDINGS_ENABLED=true
EMBEDDING_PROVIDER=local
```

Initialize the database and cache from the repository root, then leave the API running in that terminal.

```powershell
.\.venv\Scripts\python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='data/embedding-models', threads=2)"
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000
```

After the API becomes ready, start the worker in a second PowerShell terminal from the repository root.

```powershell
$env:PYTHONPATH = "$PWD\services\api;$PWD"
.\.venv\Scripts\python -m celery -A worker.tasks:celery_app worker --pool=solo --concurrency=1 --loglevel=INFO
```

In a third terminal, run `npm.cmd run dev --prefix apps/web`. Log in with the local reviewer credentials. Stop the frontend, worker and API with `Ctrl+C`, then run `docker compose stop postgres redis`. To return to SQLite, restore `DATABASE_URL=sqlite:///./data/careguide.db`, `STORAGE_DIR=./data/uploads`, `EXECUTION_MODE=local`, and `EMBEDDINGS_ENABLED=false` in `.env`, then restart the API and frontend. Each setup keeps its own database and uploads. Run one API/worker arrangement per workspace at a time because the container and native upload paths differ.

Without Docker, use the Ubuntu WSL package and startup commands in [stack verification](testing.md#ubuntu-wsl-alternative). SQLite remains available for local keyword search and process-based OCR.

## Linux or WSL

With Git, Python 3.13 and Node.js 22 installed, run the following from a fresh clone for SQLite. Install Tesseract 5 and its English language data with your distro's package manager if testing scans. On Debian or Ubuntu, the package names are `tesseract-ocr` and `tesseract-ocr-eng`. Verify the runtime with `tesseract --version` and `tesseract --list-langs`. Set `TESSERACT_CMD=tesseract` and `OCR_LANGUAGE=eng` in the private `.env`.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python scripts/init_reviewer_env.py
mkdir -p data
.venv/bin/python -m alembic upgrade head
npm ci --prefix apps/web
.venv/bin/python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000
```

In a second shell, run `npm run dev --prefix apps/web`. For the [Docker Full Stack](#postgresql-redis-and-celery-with-docker), run the same Compose commands and use `python3.13` and `npm` instead of `python` and `npm.cmd`. See [handoff verification](testing.md#reviewer-handoff-clean-clone) for the host and paths exercised.

For a local production frontend build, set `NEXT_PUBLIC_API_URL` before building if you changed the API port. On Windows run `npm.cmd run build --prefix apps/web` followed by `npm.cmd run start --prefix apps/web`. On Linux use `npm` for both commands.

## Optional provider setup

Use the [Gemini reviewer instructions](../README.md#optional-gemini-extraction) for Gemini specifically. Keep the following optional OpenAI-compatible configuration separate.

No paid account is needed for deterministic demonstration. A provider API may charge per input/output token and embedding input. Set an API key only when ready to incur the provider's published usage charges. There is no built-in pricing calculator or spending cap. For a compatible local provider, costs can be zero beyond local compute, but its Responses structured-output API and embedding-dimensions support must be verified; compatibility is not claimed.

```dotenv
EXTRACTION_MODE=llm
LLM_API_KEY=your-private-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
EMBEDDINGS_ENABLED=true
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

Embeddings require PostgreSQL. Restart API and worker; reprocess documents to index chunks. Model names are configurable defaults, not a guarantee of account access. Provider text is sent off-machine only when this mode is explicitly configured. Never place the key in `NEXT_PUBLIC_*` variables. The API stores token usage where returned, not a claimed dollar cost.

## Troubleshooting

- API startup fails: ensure migrations ran and SESSION_SECRET has 32+ characters, DEMO_PASSWORD 12+. `.env` must use ordinary UTF-8; the setup script works with this tested settings version.
- Browser cannot log in. Use `localhost` for both services, check the API readiness URL, and verify `DEMO_USERNAME` and `DEMO_PASSWORD` privately. On an existing native database, use `.\.venv\Scripts\python scripts/reset-password.py` to apply a deliberate password reset for the configured username.
- Blank scans/failed OCR: verify the Tesseract executable path and language data. Inspect job errors; do not assume the Python package includes the binary.
- Docker pipe/engine error: start Docker Desktop; otherwise use verified SQLite/local mode.
- Jobs queued indefinitely: check configured worker and Redis. Failed dispatch is retryable. Recover expired jobs through Processing Jobs after the configured time limit.
- Semantic search disabled. Check PostgreSQL, the pgvector migration, `EMBEDDINGS_ENABLED=true`, `EMBEDDING_PROVIDER=local`, and the shared cache. Upload a synthetic source to create embeddings. SQLite supports keyword search.
- Gemini unavailable. Confirm the private root `.env` on the native API and worker, restart both, and run the model access check. Check current quota in Google AI Studio if generation is rate-limited.
- Port in use: stop the existing service or update the frontend API URL/CORS origin together. Bind only loopback for this local assessment.
- Package updates differ: use backend requirements-lock.txt and frontend npm ci. Linux Compose currently resolves compatible requirements.txt versions; freeze a platform-specific lock before production.
