# Register/Unregister the portal as a Windows Task Scheduler task
# Usage:
#   .\portal\register-task.ps1              # Register (starts on logon + now)
#   .\portal\register-task.ps1 -Unregister  # Remove the task

param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "LEO_Portal_Service"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceScript = Join-Path $root "service.ps1"

if ($Unregister) {
    Write-Host "Removing scheduled task '$taskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Done." -ForegroundColor Green
    exit 0
}

# -- Build task ----------------------------------------------------
Write-Host ""
Write-Host "  Registering Portal Service" -ForegroundColor Cyan
Write-Host "  ==========================" -ForegroundColor Cyan
Write-Host ""

$argString = '-WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $serviceScript + '"'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argString -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3 -ExecutionTimeLimit (New-TimeSpan -Days 365) -StartWhenAvailable

# Register (current user, no elevated privileges needed)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Live Event Operations Portal - auto-start FastAPI on localhost:8000' -Force | Out-Null

Write-Host '  Task registered.' -ForegroundColor Green
Write-Host '  Trigger: At logon (current user)' -ForegroundColor Green
Write-Host '  Restart: On failure, up to 3 retries at 1-min intervals' -ForegroundColor Green
Write-Host ''

# Start it now
Write-Host '  Starting portal now...' -ForegroundColor Yellow
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3

$task = Get-ScheduledTask -TaskName $taskName
Write-Host ('  Status: ' + $task.State) -ForegroundColor Green
Write-Host '  URL: http://localhost:8000' -ForegroundColor Green
Write-Host ''
Write-Host '  To remove: .\portal\register-task.ps1 -Unregister' -ForegroundColor DarkGray
