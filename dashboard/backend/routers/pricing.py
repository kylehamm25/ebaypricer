from fastapi import APIRouter, Query
from dashboard.backend.database import get_db

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


@router.get("/comparisons")
def get_price_comparisons():
    with get_db() as db:
        latest_sold = db.execute(
            "SELECT MAX(snapshot_date) AS d FROM price_snapshots"
        ).fetchone()["d"]
        latest_active = db.execute(
            "SELECT MAX(snapshot_date) AS d FROM active_price_snapshots"
        ).fetchone()["d"]

        if not latest_sold or not latest_active:
            return []

        rows = db.execute(
            """SELECT ps.card_query,
                      ps.weighted_avg AS sold_weighted_avg,
                      ps.sample_size AS sold_sample,
                      aps.avg_price AS active_avg,
                      aps.sample_size AS active_sample
               FROM price_snapshots ps
               JOIN active_price_snapshots aps ON ps.card_query = aps.card_query
               WHERE ps.snapshot_date = ? AND aps.snapshot_date = ?
               ORDER BY ps.card_query""",
            (latest_sold, latest_active),
        ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        sold = d.get("sold_weighted_avg")
        active = d.get("active_avg")
        if sold is not None and active is not None:
            d["spread"] = round(sold - active, 2)
        else:
            d["spread"] = None
        result.append(d)
    return result


@router.get("/snapshots")
def get_price_snapshots(card: str = Query(...), days: int = 90):
    with get_db() as db:
        sold_rows = db.execute(
            """SELECT * FROM price_snapshots
               WHERE card_query = ? AND snapshot_date >= DATE('now', ? || ' days')
               ORDER BY snapshot_date DESC LIMIT 30""",
            (card, f"-{days}"),
        ).fetchall()
        active_rows = db.execute(
            """SELECT * FROM active_price_snapshots
               WHERE card_query = ? AND snapshot_date >= DATE('now', ? || ' days')
               ORDER BY snapshot_date DESC LIMIT 30""",
            (card, f"-{days}"),
        ).fetchall()
    return {
        "card_query": card,
        "price_snapshots": [dict(r) for r in sold_rows],
        "active_snapshots": [dict(r) for r in active_rows],
    }


@router.get("/cards/{card_name}")
def get_card_price_detail(card_name: str):
    with get_db() as db:
        sold_snaps = db.execute(
            "SELECT * FROM price_snapshots WHERE card_query = ? ORDER BY snapshot_date DESC LIMIT 30",
            (card_name,),
        ).fetchall()
        active_snaps = db.execute(
            "SELECT * FROM active_price_snapshots WHERE card_query = ? ORDER BY snapshot_date DESC LIMIT 30",
            (card_name,),
        ).fetchall()
        recent_sold = db.execute(
            "SELECT * FROM sold_listings WHERE card_query = ? ORDER BY sold_date DESC LIMIT 50",
            (card_name,),
        ).fetchall()
    return {
        "card_query": card_name,
        "price_snapshots": [dict(r) for r in sold_snaps],
        "active_snapshots": [dict(r) for r in active_snaps],
        "recent_sold": [dict(r) for r in recent_sold],
    }
