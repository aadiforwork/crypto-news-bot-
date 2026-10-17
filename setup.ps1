# Crypto AI News Bot - Quick Setup (PowerShell)
# Run: .\setup.ps1

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Crypto AI News Bot - Quick Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

Set-Location "C:\users\hp\Documents\Ai_Agents"

Write-Host "[1/3] Creating .env from template..." -ForegroundColor Yellow
if (Test-Path .env) {
    Write-Host "  .env exists. Backing up to .env.backup" -ForegroundColor Gray
    Copy-Item .env .env.backup -Force
}
Copy-Item .env.example .env -Force
Write-Host "  Done." -ForegroundColor Green

Write-Host ""
Write-Host "[2/3] Opening .env in Notepad..." -ForegroundColor Yellow
Write-Host "  Fill in your 3 keys:" -ForegroundColor White
Write-Host "    - TELEGRAM_BOT_TOKEN (from @BotFather)" -ForegroundColor White
Write-Host "    - TELEGRAM_CHAT_ID (from @userinfobot)" -ForegroundColor White
Write-Host "    - OPENROUTER_API_KEY (from openrouter.ai/keys - free tier)" -ForegroundColor White
Write-Host ""
notepad .env

Write-Host ""
Write-Host "[3/3] Testing bot with free LLM (one cycle)..." -ForegroundColor Yellow
Write-Host ""
py main.py --once

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To run continuously on Windows:" -ForegroundColor White
Write-Host "  py main.py" -ForegroundColor Gray
Write-Host ""
Write-Host "To deploy 24/7 on Linux VPS:" -ForegroundColor White
Write-Host "  Follow PM2_SETUP_GUIDE.md" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter to exit"