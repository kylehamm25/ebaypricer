@echo off
rem Start EbayPrice in production mode (single host: FastAPI serves the built frontend on :8000)
rem Requires: dashboard/frontend/dist built (npm run build) and .env configured
setlocal

if not exist "dashboard\frontend\dist\index.html" (
    echo Building frontend for single-host serving...
    pushd dashboard\frontend
    set VITE_API_BASE=/api/v1
    call npm run build
    popd
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)

.venv\Scripts\python.exe -m pip install -q -r requirements.txt -r requirements-dashboard.txt
if errorlevel 1 exit /b 1

echo Starting EbayPrice on http://localhost:8000 (AUTH_REQUIRED=%AUTH_REQUIRED%)
.venv\Scripts\python.exe -m uvicorn dashboard.backend.main:app --host 0.0.0.0 --port 8000
