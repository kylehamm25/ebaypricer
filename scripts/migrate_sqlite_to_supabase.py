"""
Phase 2: migrate SQLite (db/pokemon_prices.db) -> Supabase.

Copies shared tables (price_snapshots, active_price_snapshots, sold_listings)
and user-owned tables (listing_positions, inventory_value_history) with
typed conversion and idempotent ON CONFLICT upserts (safe to re-run).

Staging tables (staging_sold_orders / staging_active_listings) are skipped:
they are rebuilt by the workbook sync (excel_sync).

Usage:
    python scripts/migrate_sqlite_to_supabase.py
"""

import sqlite3
from datetime import datetime

import psycopg

from dashboard.backend.config import DATABASE_URL, DEFAULT_USER_ID
from ebaypricer.paths import DB_PATH


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


TABLES = [
    {
        "sqlite": "price_snapshots",
        "pg": "price_snapshots",
        "cols": ["card_query", "snapshot_date", "sample_size", "avg_price",
                 "median_price", "min_price", "max_price", "std_dev", "weighted_avg"],
        "key": ["card_query", "snapshot_date"],
        "conv": {"snapshot_date": _d},
    },
    {
        "sqlite": "active_price_snapshots",
        "pg": "active_price_snapshots",
        "cols": ["card_query", "snapshot_date", "sample_size", "avg_price",
                 "min_price", "max_price"],
        "key": ["card_query", "snapshot_date"],
        "conv": {"snapshot_date": _d},
    },
    {
        "sqlite": "sold_listings",
        "pg": "sold_listings",
        "cols": ["item_id", "card_query", "title", "price", "currency",
                 "condition", "listing_type", "sold_date", "url", "pulled_at"],
        "key": ["item_id"],
        "conv": {"sold_date": _dt, "pulled_at": _dt},
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


def migrate():
    user_id = DEFAULT_USER_ID
    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    with psycopg.connect(DATABASE_URL, prepare_threshold=None) as dst:
        for spec in TABLES:
            table = spec["pg"]
            src_table = spec["sqlite"]
            if not src.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (src_table,),
            ).fetchone():
                print(f"{table}: source table not found, skipping")
                continue

            rows = src.execute(f"SELECT * FROM {src_table}").fetchall()
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
                values = tuple(
                    conv[c](r[c]) if c in conv else r[c]
                    for c in spec["cols"]
                )
                if spec.get("user_owned"):
                    values = (user_id,) + values
                data.append(values)

            with dst.cursor() as cur:
                cur.executemany(insert_sql, data)
            print(f"{table}: {len(data)} rows upserted")
        dst.commit()

    src.close()
    print("Migration complete.")


if __name__ == "__main__":
    migrate()
