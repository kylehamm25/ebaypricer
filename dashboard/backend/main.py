from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dashboard.backend.routers import dashboard, sold, active, pricing, pipeline, promotion
from dashboard.backend.services.excel_sync import sync_excel

app = FastAPI(title="EbayPrice Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(sold.router)
app.include_router(active.router)
app.include_router(pricing.router)
app.include_router(pipeline.router)
app.include_router(promotion.router)


@app.on_event("startup")
def on_startup():
    try:
        result = sync_excel()
        print(f"Excel sync on startup: {result}")
    except Exception as e:
        print(f"Excel sync skipped on startup: {e}")


@app.get("/api/v1/pipeline/sync-excel")
def trigger_excel_sync():
    return sync_excel()


@app.get("/")
def root():
    return {"app": "EbayPrice Dashboard", "status": "running"}
