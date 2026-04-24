@echo off
title J.A.R.V.I.S. // Cognitive Architecture v3.0
cd /d C:\jarvis
echo.
echo  ========================================
echo   J.A.R.V.I.S. v3.0 - Starting...
echo  ========================================
echo.
echo  [1/2] Starting API server on port 8000...
start "JARVIS-API" cmd /c "cd /d C:\jarvis && python -m uvicorn api.server:app --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak >nul
echo  [2/2] Starting HUD on port 5173...
start "JARVIS-HUD" cmd /c "cd /d C:\jarvis\jarvis-hud && npm run dev"
echo.
echo  API:  http://localhost:8000
echo  HUD:  http://localhost:5173
echo  Health: http://localhost:8000/health
echo.
echo  Press any key to stop all services...
pause >nul
taskkill /fi "WINDOWTITLE eq JARVIS-API" >nul 2>&1
taskkill /fi "WINDOWTITLE eq JARVIS-HUD" >nul 2>&1
