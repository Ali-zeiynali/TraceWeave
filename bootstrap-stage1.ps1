# TraceWeave historical Stage-1 bootstrap compatibility shim.
# v0.3 no longer embeds the old v0.1 repository payload here because running it after an upgrade could downgrade files.
[CmdletBinding()]
param()
Write-Host "TraceWeave is already at the Stage 2+3 generation (v0.3)." -ForegroundColor Yellow
Write-Host "Fresh install:  python -m venv .venv ; pip install -e ." -ForegroundColor Cyan
Write-Host "Upgrade v0.1:   .\\TraceWeave-patch-v0.1-to-v0.3.ps1" -ForegroundColor Cyan
Write-Host "See README.md and USAGE.md for complete setup instructions."
