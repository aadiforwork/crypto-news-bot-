@echo off
REM Crypto AI News Bot - Autopilot Runner (LOCAL mode, no LLM API needed)
REM Auto-restarts the bot if it crashes. Logs to logs\bot.log

cd /d "C:\users\hp\Documents\Ai_Agents"
if not exist logs mkdir logs

:restart
echo [%date% %time%] Starting bot... >> logs\bot.log
py main.py --local >> logs\bot.log 2>&1
echo [%date% %time%] Bot exited with code %errorlevel%. Restarting in 30 seconds... >> logs\bot.log
timeout /t 30 /nobreak >nul
goto restart
