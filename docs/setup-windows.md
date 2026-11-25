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

## OCR

Tesseract is free. Follow the Windows distribution links from [Tesseract documentation](https://tesseract-ocr.github.io/tessdoc/Installation.html). Install a trusted build and set, in `.env`:

```dotenv
TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe
```

Restart the API. Verify Settings reports OCR available; run OCR tests/evaluation. Python `pytesseract` is an interface, not the OCR executable. The Docker image includes the Linux executable and English language data. Other languages require installed traineddata and explicit extension of the OCR configuration. No OCR installation was performed on this host; tests clearly report that limit.

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

Celery does not officially support Windows worker production operation. Prefer the Linux worker container or WSL; `solo` is a local convenience. The Docker engine was unavailable during this session, so Compose and pgvector were not runtime verified.

Without Docker, install PostgreSQL 17 with pgvector and Redis through WSL or a local Linux VM, create a careguide database/user, and set their connection URLs. SQLite local mode is the exact verified free alternative; it needs neither service. Do not claim pgvector functionality from SQLite tests.

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
