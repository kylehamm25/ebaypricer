@echo off
cd /d "%~dp0"

echo Starting EbayPrice Dashboard...
echo.

start "EbayPrice Backend" cmd /c "python -m uvicorn dashboard.backend.main:app --host 127.0.0.1 --port 8000"
timeout /t 2 /nobreak >nul
start "EbayPrice Frontend" cmd /c "cd dashboard\frontend && npm run dev"

echo.
echo Backend:  http://127.0.0.1:8000
echo Frontend: http://localhost:5173
echo.
echo Close the cmd windows to stop the servers.
echo.
pause
