param(
    [Parameter(Mandatory, Position=0)]
    [ValidateSet('Initialize', 'Start', 'StopApi', 'StartSQLite', 'VerifySource', 'StopPostgres')]
    [string]$Action,
    [ValidateRange(1,65535)][int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $project '.venv/Scripts/python.exe'
$profilePath = Join-Path $project 'data/semantic-dev'
$secretPath = Join-Path $profilePath 'postgres.env'
$reportPath = Join-Path $profilePath 'migration-report.json'
$composePath = Join-Path $project 'docker-compose.semantic-local.yml'
$variables = @('POSTGRES_PASSWORD', 'APP_ENV', 'DATABASE_URL', 'STORAGE_DIR', 'EMBEDDINGS_ENABLED', 'EMBEDDING_PROVIDER', 'EXECUTION_MODE')
$previous = @{}
foreach ($variable in $variables) { $previous[$variable] = [Environment]::GetEnvironmentVariable($variable, 'Process') }

function Invoke-Checked([string]$program, [string[]]$arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw "${program} failed with exit code $LASTEXITCODE" }
}

function Set-SemanticProfile {
    $line = (Get-Content -LiteralPath $secretPath -Raw).Trim()
    if ($line -notmatch '^POSTGRES_PASSWORD=([a-f0-9]{64})$') { throw 'Invalid dedicated PostgreSQL credentials file' }
    $env:POSTGRES_PASSWORD = $Matches[1]
    $env:APP_ENV = 'development'
    $env:DATABASE_URL = "postgresql+psycopg://careguide_semantic:$env:POSTGRES_PASSWORD@127.0.0.1:55432/careguide_semantic"
    $env:STORAGE_DIR = Join-Path $profilePath 'uploads'
    $env:EMBEDDINGS_ENABLED = 'true'
    $env:EMBEDDING_PROVIDER = 'local'
    $env:EXECUTION_MODE = 'local'
}

function Start-Postgres {
    Invoke-Checked 'docker' @('compose', '-f', $composePath, '--env-file', $secretPath, 'up', '-d', '--wait', 'postgres')
}

function Start-Api {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port is occupied. Stop the existing API before switching profiles."
    }
    Invoke-Checked $python @('-m', 'uvicorn', 'app.main:app', '--app-dir', 'services/api', '--host', '127.0.0.1', '--port', "$Port")
}

Push-Location -LiteralPath $project
try {
    switch ($Action) {
        'Initialize' {
            if (-not (Test-Path -LiteralPath $secretPath)) {
                New-Item -ItemType Directory -Force -Path $profilePath | Out-Null
                $bytes = [byte[]]::new(32)
                $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
                try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
                $password = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
                New-Item -ItemType File -Path $secretPath -Value "POSTGRES_PASSWORD=$password" | Out-Null
            }
            Set-SemanticProfile
            if (Test-Path -LiteralPath $reportPath) {
                Start-Postgres
                Invoke-Checked $python @('scripts/semantic_local.py', 'verify-target')
            } else {
                Invoke-Checked $python @('scripts/semantic_local.py', 'backup')
                Start-Postgres
                Invoke-Checked $python @('-m', 'alembic', 'upgrade', 'head')
                Invoke-Checked $python @('scripts/semantic_local.py', 'initialize')
            }
        }
        'Start' {
            if (-not (Test-Path -LiteralPath $reportPath)) { throw 'Initialize the semantic profile first.' }
            Set-SemanticProfile
            Start-Postgres
            Invoke-Checked $python @('scripts/semantic_local.py', 'verify-target')
            Start-Api
        }
        'StopApi' {
            $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
            if ($listeners.Count -eq 0) { break }
            if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') { throw "Unexpected listener on port $Port" }
            $apiPid = $listeners[0].OwningProcess
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $apiPid"
            if ($process.CommandLine -notmatch '\buvicorn\s+app\.main:app\b' -or $process.CommandLine -notmatch 'services[/\\]api') {
                throw "Port $Port does not belong to a CareGuide API process."
            }
            if (Test-Path -LiteralPath $reportPath) { Set-SemanticProfile }
            Invoke-Checked $python @('scripts/semantic_local.py', 'verify-idle', '--port', "$Port")
            Stop-Process -Id $apiPid
            Wait-Process -Id $apiPid -Timeout 10 -ErrorAction SilentlyContinue
        }
        'StartSQLite' {
            foreach ($variable in $variables) { [Environment]::SetEnvironmentVariable($variable, $null, 'Process') }
            Start-Api
        }
        'VerifySource' { Invoke-Checked $python @('scripts/semantic_local.py', 'verify-source') }
        'StopPostgres' {
            Set-SemanticProfile
            Invoke-Checked 'docker' @('compose', '-f', $composePath, '--env-file', $secretPath, 'stop', 'postgres')
        }
    }
} finally {
    foreach ($variable in $variables) { [Environment]::SetEnvironmentVariable($variable, $previous[$variable], 'Process') }
    Pop-Location
}
