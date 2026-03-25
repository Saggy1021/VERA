# VERA — Start Server
# Run this script to launch the VERA backend cleanly.
# Usage:  .\start_vera.ps1
# Then open http://localhost:8000 in Chrome or Edge.

Write-Host "`n=== VERA Server Startup ===" -ForegroundColor Cyan

# 1. Kill any existing process using port 8000
Write-Host "Stopping existing processes on port 8000..." -ForegroundColor Yellow
$pids = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
foreach ($p in $pids) {
    if ($p -gt 0) {
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
        Write-Host "  Killed PID $p" -ForegroundColor Gray
    }
}
Get-Process -Name "uvicorn","python" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# 2. Set environment variables
$env:TF_ENABLE_ONEDNN_OPTS = "0"
$env:TF_CPP_MIN_LOG_LEVEL  = "2"

# 3. Start uvicorn in the foreground so errors are visible
Write-Host "Starting VERA on http://localhost:8000 ..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop.`n" -ForegroundColor Gray

# Launch using python -m uvicorn to avoid hardcoded absolute path errors in pip executables on Windows
& ".\venv310\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info
