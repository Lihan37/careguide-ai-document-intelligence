param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
if (-not $SkipInstall) {
    & .\.venv\Scripts\python -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
& .\.venv\Scripts\python scripts/init_reviewer_env.py
if ($LASTEXITCODE -ne 0) { throw 'Local environment initialization failed' }
New-Item -ItemType Directory -Force 'data' | Out-Null
& .\.venv\Scripts\python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' }
if (-not (Test-Path 'sample-data/ground-truth.json')) {
    & .\.venv\Scripts\python scripts/generate_samples.py
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic sample generation failed' }
}
Write-Host 'Start API: .\.venv\Scripts\python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000'
