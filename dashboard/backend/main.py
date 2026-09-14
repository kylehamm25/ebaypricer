import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dashboard.backend.config import ALLOWED_ORIGINS, DEFAULT_USER_ID, FRONTEND_DIST
from dashboard.backend.database import close_pool
from dashboard.backend.routers import dashboard, sold, active, lots, pricing, pipeline, promotion, ebay, valuation, inventory, settings
from dashboard.backend.services.excel_sync import sync_excel
from dashboard.backend.services.ebay_data import has_connections, start_scheduler
from dashboard.backend.services.price_research import reconcile_stale_job_runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        orphaned = reconcile_stale_job_runs()
        if orphaned:
            print(f"Reconciled {orphaned} job_runs row(s) orphaned by a previous crash/restart")
        if has_connections():
            start_scheduler()
        result = sync_excel()
        print(f"Excel sync on startup: {result}")
    except Exception as e:
        print(f"Startup sync skipped: {e}")
    yield
    close_pool()


app = FastAPI(title="EbayPrice Dashboard", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(sold.router)
app.include_router(active.router)
app.include_router(lots.router)
app.include_router(pricing.router)
app.include_router(pipeline.router)
app.include_router(promotion.router)
app.include_router(ebay.router)
app.include_router(valuation.router)
app.include_router(inventory.router)
app.include_router(settings.router)


@app.get("/api/v1/pipeline/sync-excel")
def trigger_excel_sync():
    return sync_excel()


@app.get("/")
def root():
    if _index and os.path.isfile(_index):
        return FileResponse(_index)
    return {"app": "EbayPrice Dashboard", "status": "running"}


# Serve the built frontend (single host deployment)
_index = None
_assets = os.path.join(FRONTEND_DIST, "assets")

if os.path.isdir(FRONTEND_DIST):
    _index = os.path.join(FRONTEND_DIST, "index.html")
    app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        file_path = os.path.join(FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(_index)
