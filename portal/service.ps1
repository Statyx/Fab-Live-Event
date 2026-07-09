# CCE Validation Portal - Auto-Restart Service
# Keeps the portal alive: restarts on crash, logs output.
# Register with Task Scheduler via:  .\portal\register-task.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root "backend"
$logDir = Join-Path $root "logs"
$restartDelay = 5          # seconds between crash restart
$maxConsecutiveFails = 10   # stop if it crashes this many times in a row

# -- Setup ---------------------------------------------------------
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$logFile = Join-Path $logDir "portal_$(Get-Date -Format 'yyyy-MM-dd').log"

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

# -- Dependency check ----------------------------------------------
$pythonOk = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonOk) {
    Write-Log "FATAL: python not found in PATH"
    exit 1
}

# Install/update deps silently
Write-Log "Installing dependencies..."
Push-Location $backendDir
pip install -r requirements.txt -q 2>$null
Pop-Location

# -- Main loop -----------------------------------------------------
$consecutiveFails = 0

Write-Log "Portal service starting (PID: $PID)"
Write-Log "Backend: $backendDir"
Write-Log "URL: http://localhost:8000"

while ($consecutiveFails -lt $maxConsecutiveFails) {
    Write-Log "Starting uvicorn..."

    $startTime = Get-Date
    try {
        Set-Location $backendDir
        python -m uvicorn main:app --host 127.0.0.1 --port 8000 2>&1 |
            ForEach-Object {
                $ts = Get-Date -Format "HH:mm:ss"
                $line = "[$ts] $_"
                Add-Content -Path $logFile -Value $line
                Write-Host $line
            }
    } catch {
        Write-Log "ERROR: $_"
    }

    $runtime = (Get-Date) - $startTime

    # If it ran for more than 60 seconds, reset the fail counter
    if ($runtime.TotalSeconds -gt 60) {
        $consecutiveFails = 0
    } else {
        $consecutiveFails++
    }

    $exitCode = $LASTEXITCODE
    Write-Log "Uvicorn exited (code=$exitCode, runtime=$([math]::Round($runtime.TotalSeconds))s, consecutive_fails=$consecutiveFails)"

    if ($consecutiveFails -ge $maxConsecutiveFails) {
        Write-Log "FATAL: $maxConsecutiveFails consecutive fast crashes - stopping service"
        break
    }

    Write-Log "Restarting in ${restartDelay}s..."
    Start-Sleep -Seconds $restartDelay
}

Write-Log "Portal service stopped"
