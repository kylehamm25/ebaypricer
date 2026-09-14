@echo off
cd /d "%~dp0"

echo Starting EbayPrice Dashboard...
echo.

start "EbayPrice Backend" cmd /k ".venv\Scripts\python.exe -m uvicorn dashboard.backend.main:app --host 127.0.0.1 --port 8000"
timeout /t 2 /nobreak >nul
start "EbayPrice Frontend" cmd /k "cd dashboard\frontend && npm run dev"

echo.
echo Backend:  http://127.0.0.1:8000
echo Frontend: http://localhost:5173
echo.
echo Close the cmd windows to stop the servers.
