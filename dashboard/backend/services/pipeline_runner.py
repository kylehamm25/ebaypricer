"""
Pipeline runner (runs the legacy scripts and ingests their output into Supabase).

run_pipeline_once() executes scripts/main.py (append_sold_orders, get_active,
price_active_listings, avg_active_price), then ingests the results into
Supabase. Nothing in that chain writes to eBay - the ad-rate boost step was
removed so an unattended run cannot move ad spend:
  - Excel workbook -> sold_orders / active_listings / inventory_value_history
  - SQLite (db/pokemon_prices.db) -> active_price_snapshots / listing_positions

A Postgres advisory lock guarantees a single active runner across processes
(prod + dev servers, cron invocations, ...).
"""

import os
import sqlite3
import subprocess
import sys
import threading
from datetime import date, datetime, timezone

import psycopg

from dashboard.backend.config import DATABASE_URL, DEFAULT_USER_ID
from dashboard.backend.database import get_db
from dashboard.backend.services.excel_sync import sync_excel
from ebaypricer.paths import DB_PATH, PROJECT_ROOT

_PIPELINE_LOCK_KEY = 727001
_LOCAL_GUARD = threading.Lock()


def _dt(v):
    """ISO timestamp text -> datetime; returns None for empty/junk."""
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _d(v):
    """YYYY-MM-DD text -> date."""
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return None


_TABLES = [
    # price_snapshots and sold_listings are deliberately absent: the sold side was
    # removed (see services/price_research.py), and re-ingesting the legacy SQLite
    # copies would put it straight back.
    {
        "sqlite": "active_price_snapshots",
        "pg": "active_price_snapshots",
        "cols": ["card_query", "snapshot_date", "sample_size", "avg_price",
                 "min_price", "max_price"],
        "key": ["card_query", "snapshot_date"],
        "conv": {"snapshot_date": _d},
    },
    {
        "sqlite": "listing_positions",
        "pg": "listing_positions",
        "cols": ["item_id", "card_query", "snapshot_date", "position", "search_size"],
        "key": ["user_id", "item_id", "snapshot_date"],
        "conv": {"snapshot_date": _d},
        "user_owned": True,
    },
    {
        "sqlite": "inventory_value_history",
        "pg": "inventory_value_history",
        "cols": ["snapshot_date", "total_value", "total_listings"],
        "key": ["user_id", "snapshot_date"],
        "conv": {"snapshot_date": _d},
        "user_owned": True,
    },
]


def sync_sqlite_to_supabase() -> dict:
    """Upsert the pipeline's SQLite tables (price snapshots etc.) into Supabase."""
    if not os.path.exists(DB_PATH):
        return {"error": f"SQLite db not found: {DB_PATH}"}

    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    results = {}
    try:
        with get_db(read_only=False) as dst:
            for spec in _TABLES:
                table = spec["pg"]
                if not src.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (spec["sqlite"],),
                ).fetchone():
                    results[table] = "source table not found"
                    continue

                rows = src.execute(f"SELECT * FROM {spec['sqlite']}").fetchall()
                conv = spec["conv"]
                target_cols = (["user_id"] + spec["cols"]) if spec.get("user_owned") else spec["cols"]
                updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in target_cols if c not in spec["key"])
                insert_sql = (
                    f"INSERT INTO {table} ({', '.join(target_cols)}) VALUES "
                    f"({', '.join('%s' for _ in target_cols)}) "
                    f"ON CONFLICT ({', '.join(spec['key'])}) DO UPDATE SET {updates}"
                )

                data = []
                for r in rows:
                    values = tuple(conv[c](r[c]) if c in conv else r[c] for c in spec["cols"])
                    if spec.get("user_owned"):
                        values = (DEFAULT_USER_ID,) + values
                    data.append(values)

                with dst.cursor() as cur:
                    cur.executemany(insert_sql, data)
                results[table] = f"{len(data)} rows upserted"
    finally:
        src.close()
    return results


def _try_advisory_lock() -> psycopg.Connection | None:
    """Acquire the cross-process pipeline lock; returns the held connection or None."""
    try:
        conn = psycopg.connect(DATABASE_URL, prepare_threshold=None)
        row = conn.execute(f"SELECT pg_try_advisory_lock({_PIPELINE_LOCK_KEY})").fetchone()
        if row and row[0]:
            return conn
        conn.close()
        return None
    except Exception:
        return None


def run_pipeline_once() -> dict:
    """Run scripts/main.py, then ingest workbook + SQLite results into Supabase.

    Skips without error when another runner (local thread or another process)
    is already running the pipeline.
    """
    if not _LOCAL_GUARD.acquire(blocking=False):
        return {"status": "skipped", "reason": "pipeline already running locally"}

    lock_conn = None
    try:
        lock_conn = _try_advisory_lock()
        if lock_conn is None:
            return {"status": "skipped", "reason": "another runner is active"}

        started = datetime.now(timezone.utc)
        print(f"[pipeline] running scripts/main.py at {started.isoformat()}")
        result = subprocess.run(
            [sys.executable, "scripts/main.py"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=7200,
        )
        summary: dict = {
            "status": "ok" if result.returncode == 0 else "error",
            "exit_code": result.returncode,
            "started_at": started.isoformat(),
        }

        if result.returncode == 0:
            try:
                summary["excel"] = sync_excel()
            except Exception as e:
                summary["excel_error"] = str(e)[:200]
            try:
                summary["sqlite"] = sync_sqlite_to_supabase()
            except Exception as e:
                summary["sqlite_error"] = str(e)[:200]
        else:
            tail = "\n".join(result.stdout.splitlines()[-10:]) + "\n" + "\n".join(
                result.stderr.splitlines()[-10:]
            )
            summary["log_tail"] = tail[-1500:]

        summary["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds())
        print(
            f"[pipeline] finished: status={summary['status']} exit={result.returncode} "
            f"duration={summary['duration_s']}s"
        )
        return summary
    except subprocess.TimeoutExpired:
        print("[pipeline] timed out after 2h")
        return {"status": "error", "error": "pipeline timed out after 2h"}
    except Exception as e:
        print(f"[pipeline] failed: {e}")
        return {"status": "error", "error": str(e)[:300]}
    finally:
        if lock_conn is not None:
            try:
                lock_conn.close()
            except Exception:
                pass
        _LOCAL_GUARD.release()
