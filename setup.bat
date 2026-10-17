@echo off
echo ============================================
echo Crypto AI News Bot - Quick Setup
echo ============================================
echo.

cd /d "C:\users\hp\Documents\Ai_Agents"

echo [1/3] Creating .env from template...
if exist .env (
    echo .env already exists. Backing up to .env.backup
    copy .env .env.backup >nul
)
copy .env.example .env >nul
echo Done.

echo.
echo [2/3] Opening .env in Notepad...
echo Please fill in your 3 keys:
echo   - TELEGRAM_BOT_TOKEN (from @BotFather)
echo   - TELEGRAM_CHAT_ID (from @userinfobot)
echo   - OPENROUTER_API_KEY (from openrouter.ai/keys - free tier)
echo.
notepad .env

echo.
echo [3/3] Testing bot with free LLM (one cycle)...
echo.
py main.py --once

echo.
echo ============================================
echo Setup complete!
echo ============================================
echo.
echo To run continuously on Windows:
echo   py main.py
echo.
echo To deploy 24/7 on Linux VPS:
echo   Follow PM2_SETUP_GUIDE.md
echo.
pause