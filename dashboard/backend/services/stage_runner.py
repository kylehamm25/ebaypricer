"""
Page-triggered pipeline stage runner.

Lets a single dashboard page (Sold Orders, Active Listings) refresh just the
slice of the pipeline it depends on, instead of the full scripts/main.py run
that pipeline_runner.py does. Reuses the same advisory-lock + job_runs
pattern as pipeline_runner.py and price_research.py so status/history stay
visible through the same job_runs table, just under different job names.
"""

import logging
import subprocess
import sys
import threading
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Json

from dashboard.backend.config import DATABASE_URL
from dashboard.backend.database import get_db
from dashboard.backend.services.excel_sync import sync_excel
from dashboard.backend.services.price_research import run_shared_price_research
from ebaypricer.paths import PROJECT_ROOT

log = logging.getLogger(__name__)

# Distinct from pipeline_runner.py's 727001 and price_research.py's 727002.
_SOLD_LOCK_KEY = 727003
_ACTIVE_LOCK_KEY = 727004

SOLD_JOB_NAME = "sold_refresh"
ACTIVE_JOB_NAME = "active_refresh"

_SOLD_GUARD = threading.Lock()
_ACTIVE_GUARD = threading.Lock()

_STAGE_TIMEOUT_S = 20 * 60


def _try_advisory_lock(key: int) -> psycopg.Connection | None:
    try:
        conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
        row = conn.execute(f"SELECT pg_try_advisory_lock({key})").fetchone()
        if row and row[0]:
            return conn
        conn.close()
        return None
    except Exception:
        return None


def _start_job_run(job_name: str, started: datetime) -> int | None:
    try:
        with get_db(read_only=False) as conn:
            row = conn.execute(
                "INSERT INTO job_runs (job_name, user_id, status, started_at) "
                "VALUES (%s, NULL, 'running', %s) RETURNING id",
                (job_name, started),
            ).fetchone()
            return row["id"] if row else None
    except Exception as e:
        log.error("Failed to start job_runs row for %s: %s", job_name, e)
        return None


def _finish_job_run(job_id: int | None, job_name: str, status: str, detail: dict | None = None) -> None:
    try:
        with get_db(read_only=False) as conn:
            if job_id is not None:
                conn.execute(
                    "UPDATE job_runs SET status = %s, finished_at = %s, detail = %s WHERE id = %s",
                    (status, datetime.now(timezone.utc), Json(detail) if detail is not None else None, job_id),
                )
            else:
                conn.execute(
                    "INSERT INTO job_runs (job_name, user_id, status, started_at, finished_at, detail) "
                    "VALUES (%s, NULL, %s, %s, %s, %s)",
                    (job_name, status, datetime.now(timezone.utc), datetime.now(timezone.utc),
                     Json(detail) if detail is not None else None),
                )
    except Exception as e:
        log.error("Failed to finish job_runs row for %s: %s", job_name, e)


def get_latest_run(job_name: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, started_at, finished_at, detail FROM job_runs "
            "WHERE job_name = %s ORDER BY started_at DESC LIMIT 1",
            (job_name,),
        ).fetchone()
    return dict(row) if row else None


def _run_script(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=_STAGE_TIMEOUT_S,
    )


def _run_stage(job_name: str, guard: threading.Lock, lock_key: int, work) -> dict:
    """work() does the actual script run + sync, called with the lock held."""
    if not guard.acquire(blocking=False):
        return {"status": "skipped", "reason": "already running locally"}

    lock_conn = _try_advisory_lock(lock_key)
    if lock_conn is None:
        guard.release()
        return {"status": "skipped", "reason": "another runner is active"}

    started = datetime.now(timezone.utc)
    job_id = _start_job_run(job_name, started)
    try:
        summary = work()
        summary["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds())
        _finish_job_run(job_id, job_name, summary.get("status", "ok"), summary)
        return summary
    except subprocess.TimeoutExpired:
        detail = {"status": "error", "error": f"timed out after {_STAGE_TIMEOUT_S}s"}
        _finish_job_run(job_id, job_name, "error", detail)
        return detail
    except Exception as e:
        detail = {"status": "error", "error": str(e)[:300]}
        _finish_job_run(job_id, job_name, "error", detail)
        return detail
    finally:
        try:
            lock_conn.close()
        except Exception:
            pass
        guard.release()


def run_sold_refresh() -> dict:
    """Runs append_sold_orders.py (pulls new sold orders + Finances fee data from eBay),
    then syncs the updated workbook into Postgres."""

    def work() -> dict:
        result = _run_script("scripts/append_sold_orders.py")
        if result.returncode != 0:
            tail = "\n".join(result.stdout.splitlines()[-10:]) + "\n" + "\n".join(result.stderr.splitlines()[-10:])
            return {"status": "error", "exit_code": result.returncode, "log_tail": tail[-1500:]}
        excel = sync_excel()
        return {"status": "ok", "exit_code": 0, "excel": excel}

    return _run_stage(SOLD_JOB_NAME, _SOLD_GUARD, _SOLD_LOCK_KEY, work)


def run_active_refresh() -> dict:
    """Runs get_active.py (refreshes the Active Listings sheet from eBay), syncs it into
    Postgres, then kicks off shared price research so pricing columns (Sold Avg, Spread,
    Search Rank) reflect the refreshed listing set too."""

    def work() -> dict:
        result = _run_script("scripts/get_active.py")
        if result.returncode != 0:
            tail = "\n".join(result.stdout.splitlines()[-10:]) + "\n" + "\n".join(result.stderr.splitlines()[-10:])
            return {"status": "error", "exit_code": result.returncode, "log_tail": tail[-1500:]}
        excel = sync_excel()
        research = run_shared_price_research()
        return {"status": "ok", "exit_code": 0, "excel": excel, "price_research": research}

    return _run_stage(ACTIVE_JOB_NAME, _ACTIVE_GUARD, _ACTIVE_LOCK_KEY, work)
