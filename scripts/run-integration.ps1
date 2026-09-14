$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $root ".env"

if (-not (Test-Path $environmentFile)) {
    throw "Create .env from .env.example before running live integrations."
}

$values = @{}
Get-Content $environmentFile | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        $values[$Matches[1]] = $Matches[2]
    }
}

foreach (
    $required in
    "POSTGRES_PASSWORD", "TEMPORAL_POSTGRES_PASSWORD", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"
) {
    if (-not $values[$required]) {
        throw "$required must be set in .env."
    }
}

$env:TEST_DATABASE_URL = "postgresql+asyncpg://agora:$($values.POSTGRES_PASSWORD)@127.0.0.1:5432/agora"
$env:TEST_REDIS_URL = "redis://127.0.0.1:6379/0"
$env:TEST_MINIO_ENDPOINT = "127.0.0.1:9000"
$env:TEST_MINIO_ACCESS_KEY = $values.MINIO_ROOT_USER
$env:TEST_MINIO_SECRET_KEY = $values.MINIO_ROOT_PASSWORD
$env:TEST_NATS_URL = "nats://127.0.0.1:4222"
$env:TEST_NATS_STREAM = "AGORA"
$env:TEST_TEMPORAL_ADDRESS = "127.0.0.1:7233"
$env:TEST_TEMPORAL_NAMESPACE = "default"

Push-Location (Join-Path $root "backend")
try {
    uv run pytest -m integration -q
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}