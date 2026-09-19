# Verificacion de desarrollo de Thinkuy: lint + pruebas + coherencia de assets PWA.
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\dev_check.ps1
# Sale con codigo 1 si algo falla, para poder encadenarlo (pre-commit / CI).

$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "[ERROR] No existe el interprete del entorno virtual: $py"
    exit 1
}

$failed = $false

Write-Host "== 1/3 ruff (backend) =="
& $py -m ruff check (Join-Path $root "backend")
if ($LASTEXITCODE -ne 0) { $failed = $true }

Write-Host "== 2/3 pytest (suite completa) =="
Push-Location $root
& $py -m pytest
if ($LASTEXITCODE -ne 0) { $failed = $true }
Pop-Location

Write-Host "== 3/3 version de assets PWA =="
& $py (Join-Path $root "tools\bump_pwa_version.py") --check
if ($LASTEXITCODE -ne 0) { $failed = $true }

if ($failed) {
    Write-Host ""
    Write-Host "DEV CHECK: FALLO"
    exit 1
}
Write-Host ""
Write-Host "DEV CHECK: OK"
exit 0
