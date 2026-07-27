import os
import sys
import subprocess
import threading
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from dashboard.backend.config import LOG_PATH
from ebaypricer.paths import PROJECT_ROOT

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])

_pipeline_state = {
    "state": "idle",
    "pid": None,
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
}


@router.get("/status")
def get_pipeline_status():
    return _pipeline_state


@router.get("/logs")
def get_pipeline_logs(lines: int = 200):
    if not os.path.exists(LOG_PATH):
        return ""
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])


@router.post("/run")
def run_pipeline():
    if _pipeline_state["state"] == "running":
        raise HTTPException(409, "Pipeline is already running")

    def _target():
        _pipeline_state["state"] = "running"
        _pipeline_state["pid"] = None
        _pipeline_state["started_at"] = datetime.now(timezone.utc)
        _pipeline_state["finished_at"] = None
        _pipeline_state["exit_code"] = None
        try:
            result = subprocess.run(
                [sys.executable, "scripts/main.py"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            _pipeline_state["exit_code"] = result.returncode
        except Exception:
            _pipeline_state["exit_code"] = -1
        finally:
            _pipeline_state["state"] = "idle"
            _pipeline_state["finished_at"] = datetime.now(timezone.utc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return {"message": "Pipeline started"}
