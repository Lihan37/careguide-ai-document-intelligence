param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.venv')) { python -m venv .venv }
if (-not $SkipInstall) {
    & .\.venv\Scripts\python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
if (-not (Test-Path '.env')) {
    $sessionBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($sessionBytes)
    $passwordBytes = New-Object byte[] 18
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($passwordBytes)
    $localSecret = [Convert]::ToBase64String($sessionBytes)
    $localPassword = [Convert]::ToBase64String($passwordBytes)
    @"
DATABASE_URL=sqlite:///./data/careguide.db
EXECUTION_MODE=local
EXTRACTION_MODE=deterministic_demo
SESSION_SECRET=$localSecret
DEMO_USERNAME=reviewer
DEMO_PASSWORD=$localPassword
"@ | Set-Content -LiteralPath '.env' -Encoding utf8
    Write-Host 'Created .env with random local credentials. Read DEMO_PASSWORD privately in your editor.'
}
New-Item -ItemType Directory -Force 'data' | Out-Null
& .\.venv\Scripts\python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' }
& .\.venv\Scripts\python scripts/generate_samples.py
Write-Host 'Start API: .\.venv\Scripts\python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000'
