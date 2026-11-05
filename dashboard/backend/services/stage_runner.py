"""
Page-triggered refresh runner.

Lets a single dashboard page (Sold Orders, Active Listings) refresh just the
slice it depends on, instead of a full sync round. Reuses the same
advisory-lock + job_runs pattern as price_research.py so status/history stay
visible through the same job_runs table, just under different job names.
"""

import logging
import threading
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Json

from dashboard.backend.config import DATABASE_URL
from dashboard.backend.database import get_db
from dashboard.backend.services.ebay_data import sync_all_users
from dashboard.backend.services.price_research import run_shared_price_research

log = logging.getLogger(__name__)

# Distinct from price_research.py's 727002.
_SOLD_LOCK_KEY = 727003
_ACTIVE_LOCK_KEY = 727004

SOLD_JOB_NAME = "sold_refresh"
ACTIVE_JOB_NAME = "active_refresh"

_SOLD_GUARD = threading.Lock()
_ACTIVE_GUARD = threading.Lock()


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


def _run_stage(job_name: str, guard: threading.Lock, lock_key: int, work) -> dict:
    """work() does the actual sync, called with the lock held."""
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
    """Per-user OAuth sync of sold orders + Finances fee data, straight into Postgres."""

    def work() -> dict:
        try:
            synced = sync_all_users()
        except Exception as e:
            return {"status": "error", "error": str(e)[:300]}
        return {"status": "ok", "sync": synced}

    return _run_stage(SOLD_JOB_NAME, _SOLD_GUARD, _SOLD_LOCK_KEY, work)


def run_active_refresh() -> dict:
    """Per-user OAuth sync of active listings, then shared price research so pricing
    columns (comp averages, search rank, suggestions) reflect the refreshed set too.

    The research is forced: pressing Refresh means "go and look now", and unforced it
    short-circuits on _all_cards_researched_today, so the second refresh of any day
    left every comp figure and suggested price exactly as it was.

    That is a deliberate exception to the ebay-api-rate-limits skill's "never pass
    force=True from a request-triggered path". The cost scales with the catalog: one
    Browse search per card for comps plus up to three memoized search-position
    queries, so ~200 cards is a few hundred Browse calls against a 5,000/day limit,
    plus ~200 x 0.5s of inter-call sleep. MAX_RUN_SECONDS (45 min) and the advisory
    lock still bound one run, and the lock stops repeated clicks stacking - but
    someone refreshing all day can still exhaust the daily quota. Keep the
    scheduler's own round in services/ebay_data.py unforced so the automatic path
    stays cheap."""

    def work() -> dict:
        try:
            synced = sync_all_users()
        except Exception as e:
            return {"status": "error", "error": str(e)[:300]}
        research = run_shared_price_research(force=True)
        return {"status": "ok", "sync": synced, "price_research": research}

    return _run_stage(ACTIVE_JOB_NAME, _ACTIVE_GUARD, _ACTIVE_LOCK_KEY, work)
