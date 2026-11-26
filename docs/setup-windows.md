# Windows setup

Use PowerShell from `D:\Projects\CareGuide-AI-Assessment`. Python 3.13 and Node 22 were used in this run. Node must satisfy the installed Next.js requirement (at least 20.9). Install VS Code Python tooling if desired; select `.venv\Scripts\python.exe` as interpreter.

## Local mode without Docker or paid services

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup-local.ps1 -SkipInstall
npm.cmd ci --prefix apps/web
```

The script generates ignored `.env` with random local credentials only if it does not exist, applies migrations and generates synthetic fixtures. It does not print credentials. Read `DEMO_PASSWORD` privately in your editor; username defaults to `reviewer`. The command scopes execution policy to that one PowerShell process. It does not change the machine policy or require venv activation. If a managed machine forbids scripts entirely, follow the script's Python commands individually after creating `.env` privately from the example (set SQLite/local values).

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

Start Docker Desktop (Linux containers). In `.env`, retain the generated SESSION_SECRET and DEMO_PASSWORD, add a strong URL-safe POSTGRES_PASSWORD and set database/Redis/Celery variables as in `.env.example`. Compose overrides service hostnames inside containers.

```powershell
docker compose up --build -d
docker compose ps
npm.cmd run dev --prefix apps/web
```

Compose starts database, broker, API and worker; the API runs Alembic migrations. For native API/worker with Docker infrastructure only:

```powershell
docker compose up -d postgres redis
# Set DATABASE_URL and EXECUTION_MODE=celery in .env first.
.\.venv\Scripts\python -m alembic upgrade head
$env:PYTHONPATH = "$PWD\services\api;$PWD"
.\.venv\Scripts\python -m celery -A worker.tasks:celery_app worker --pool=solo --concurrency=1 --loglevel=WARNING
```

The verified Windows setup used Docker for PostgreSQL and Redis with a native Celery `solo` worker. Use a Linux worker for production. See the [isolated verification commands](testing.md#postgresql-redis-and-celery-verification).

Without Docker, use the Ubuntu WSL package and startup commands in [stack verification](testing.md#ubuntu-wsl-alternative). SQLite remains available for local keyword search and process-based OCR.

## Optional provider setup

No paid account is needed for deterministic demonstration. A provider API may charge per input/output token and embedding input. Set an API key only when ready to incur the provider's published usage charges. There is no built-in pricing calculator or spending cap. For a compatible local provider, costs can be zero beyond local compute, but its Responses structured-output API and embedding-dimensions support must be verified; compatibility is not claimed.

```dotenv
EXTRACTION_MODE=llm
LLM_API_KEY=your-private-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
EMBEDDINGS_ENABLED=true
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

Embeddings require PostgreSQL. Restart API and worker; reprocess documents to index chunks. Model names are configurable defaults, not a guarantee of account access. Provider text is sent off-machine only when this mode is explicitly configured. Never place the key in `NEXT_PUBLIC_*` variables. The API stores token usage where returned, not a claimed dollar cost.

## Troubleshooting

- API startup fails: ensure migrations ran and SESSION_SECRET has 32+ characters, DEMO_PASSWORD 12+. `.env` must use ordinary UTF-8; the setup script works with this tested settings version.
- Browser cannot log in: check ports, use localhost for frontend/API, and verify the password against the configured user (not the DB password).
- Blank scans/failed OCR: verify the Tesseract executable path and language data. Inspect job errors; do not assume the Python package includes the binary.
- Docker pipe/engine error: start Docker Desktop; otherwise use verified SQLite/local mode.
- Jobs queued indefinitely: check configured worker and Redis. Failed dispatch is retryable. Recover expired jobs through Processing Jobs after the configured time limit.
- Port in use: stop the existing service or update the frontend API URL/CORS origin together. Bind only loopback for this local assessment.
- Package updates differ: use backend requirements-lock.txt and frontend npm ci. Linux Compose currently resolves compatible requirements.txt versions; freeze a platform-specific lock before production.
