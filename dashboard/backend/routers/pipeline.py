import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db
from dashboard.backend.services.price_research import JOB_NAME, run_shared_price_research

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


def _latest_run():
    with get_db() as conn:
        return conn.execute(
            "SELECT status, started_at, finished_at, detail FROM job_runs "
            "WHERE job_name = %s ORDER BY started_at DESC LIMIT 1",
            (JOB_NAME,),
        ).fetchone()


@router.get("/status")
def get_pipeline_status(user_id: uuid.UUID = Depends(get_current_user_id)):
    row = _latest_run()
    if row is None:
        return {"state": "idle", "finished_at": None, "last_run_at": None, "last_status": None}
    running = row["finished_at"] is None
    return {
        "state": "running" if running else "idle",
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "last_run_at": (row["finished_at"] or row["started_at"]).isoformat(),
        "last_status": row["status"],
    }


@router.get("/logs")
def get_pipeline_logs(lines: int = 200, user_id: uuid.UUID = Depends(get_current_user_id)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT job_name, status, started_at, finished_at, detail FROM job_runs "
            "ORDER BY started_at DESC LIMIT %s",
            (min(lines, 500),),
        ).fetchall()
    return [
        {
            "job_name": r["job_name"],
            "status": r["status"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            "detail": r["detail"],
        }
        for r in rows
    ]


@router.post("/run")
def run_pipeline(user_id: uuid.UUID = Depends(get_current_user_id)):
    row = _latest_run()
    if row is not None and row["finished_at"] is None:
        raise HTTPException(409, "Price research is already running")

    thread = threading.Thread(target=run_shared_price_research, daemon=True)
    thread.start()
    return {"message": "Price research started"}
