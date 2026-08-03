# Live Event Operations Portal — Start Script
# Launches the portal on http://localhost:8000

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  Live Event Operations Portal" -ForegroundColor Cyan
Write-Host "  ========================" -ForegroundColor Cyan
Write-Host ""

# Check python
$pythonOk = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonOk) { Write-Host "ERROR: python not found in PATH" -ForegroundColor Red; exit 1 }

# Install deps
Write-Host "[1/2] Installing dependencies..." -ForegroundColor Yellow
Push-Location "$root\backend"
pip install -r requirements.txt -q 2>$null
Pop-Location

# Launch
Write-Host "[2/2] Starting server..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Portal: http://localhost:8000" -ForegroundColor Green
Write-Host "  API:    http://localhost:8000/docs" -ForegroundColor Green
Write-Host ""
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

Set-Location "$root\backend"
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
