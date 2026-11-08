# LedgerMind — Run Visible Browser Walkthrough in Windows Terminal
# ================================================================
# Usage:
#   .\qa\run_visible_inspection.ps1

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  LedgerMind — Visible Desktop Browser Walkthrough Suite" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

# Check Python
$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) {
    Write-Host "Error: Python is not on PATH." -ForegroundColor Red
    exit 1
}

# Run the visible walkthrough script
Write-Host "Launching Google Chrome on your physical desktop..." -ForegroundColor Yellow
python qa\visible_walkthrough.py
