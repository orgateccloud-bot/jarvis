@echo off
title J.A.R.V.I.S. 4.0
rem Roda a partir da pasta deste script, onde quer que o projeto esteja.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Ambiente .venv ausente. Rode: python -m venv .venv ^&^& .venv\Scripts\pip install -e .[dev]
  pause
  exit /b 1
)

echo [1/2] API em http://127.0.0.1:8000 ...
start "JARVIS-API" cmd /c ".venv\Scripts\python -m jarvis"
timeout /t 3 /nobreak >nul

echo [2/2] HUD em http://localhost:5173 ...
start "JARVIS-HUD" cmd /c "cd /d jarvis-hud && npm run dev"

echo.
echo Token do HUD: dados\.token
echo Pressione uma tecla para encerrar tudo...
pause >nul
taskkill /fi "WINDOWTITLE eq JARVIS-API" >nul 2>&1
taskkill /fi "WINDOWTITLE eq JARVIS-HUD" >nul 2>&1
