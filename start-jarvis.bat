@echo off
title JARVIS-TRILHUM 4.0
rem Roda a partir da pasta deste script, onde quer que o projeto esteja.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Ambiente .venv ausente. Rode: python -m venv .venv ^&^& .venv\Scripts\pip install -e .[dev]
  pause
  exit /b 1
)

rem O HUD buildado e servido pela propria API (sem servidor de desenvolvimento do Vite).
rem O build precisa existir antes de a API subir. Depois de mudar o HUD, rode "npm run build" em jarvis-hud.
if not exist "jarvis-hud\dist\index.html" (
  if not exist "jarvis-hud\node_modules" (
    echo HUD sem build e sem dependencias. Rode uma vez: cd jarvis-hud ^&^& npm ci
    pause
    exit /b 1
  )
  echo [1/2] Gerando o build do HUD...
  call npm --prefix jarvis-hud run build || (pause & exit /b 1)
) else (
  echo [1/2] Build do HUD encontrado.
)

rem JARVIS-TRILHUM: porta propria e sem a voz local (o microfone e do JARVIS principal, na 8000).
set JARVIS_PORT=8003
set JARVIS_VOZ_LOCAL=0
set PYTHONPATH=%~dp0
echo [2/2] JARVIS-TRILHUM em http://127.0.0.1:8003 ...
start "JARVIS-TRILHUM-API" cmd /c ".venv\Scripts\python -m jarvis"

echo.
echo Abra http://127.0.0.1:8003 no navegador.
echo Pressione uma tecla para encerrar...
pause >nul
taskkill /fi "WINDOWTITLE eq JARVIS-TRILHUM-API" >nul 2>&1
