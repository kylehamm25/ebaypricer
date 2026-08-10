import uuid

from fastapi import APIRouter, Depends, Query

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])

_GENERIC_WORDS = {
    "pokemon", "promo", "promos", "english", "card", "cards", "tcg",
    "near", "mint", "black", "star", "white", "holo", "common", "uncommon",
}


def _fuzzy_card_query(db, card_name: str) -> str | None:
    words = [
        w.lower()
        for w in card_name.split()
        if len(w) > 3 and w.isalnum() and not w.isdigit() and w.lower() not in _GENERIC_WORDS
    ]
    if not words:
        return None
    rows = db.execute("SELECT DISTINCT card_query FROM price_snapshots").fetchall()
    best, best_score = None, 0
    for r in rows:
        q = (r["card_query"] or "").lower()
        score = sum(1 for w in words if w in q)
        if score > best_score:
            best, best_score = r["card_query"], score
    return best if best_score else None


def _card_has_data(db, q: str) -> bool:
    return bool(
        db.execute("SELECT 1 FROM price_snapshots WHERE card_query = %s LIMIT 1", (q,)).fetchone()
        or db.execute("SELECT 1 FROM active_price_snapshots WHERE card_query = %s LIMIT 1", (q,)).fetchone()
        or db.execute("SELECT 1 FROM sold_listings WHERE card_query = %s LIMIT 1", (q,)).fetchone()
    )


@router.get("/comparisons")
def get_price_comparisons(user_id: uuid.UUID = Depends(get_current_user_id)):
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
               WHERE ps.snapshot_date = %s AND aps.snapshot_date = %s
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
def get_price_snapshots(
    card: str = Query(...), days: int = 90, user_id: uuid.UUID = Depends(get_current_user_id)
):
    with get_db() as db:
        sold_rows = db.execute(
            """SELECT * FROM price_snapshots
               WHERE card_query = %s AND snapshot_date >= CURRENT_DATE - make_interval(days => %s)
               ORDER BY snapshot_date DESC LIMIT 30""",
            (card, days),
        ).fetchall()
        active_rows = db.execute(
            """SELECT * FROM active_price_snapshots
               WHERE card_query = %s AND snapshot_date >= CURRENT_DATE - make_interval(days => %s)
               ORDER BY snapshot_date DESC LIMIT 30""",
            (card, days),
        ).fetchall()
    return {
        "card_query": card,
        "price_snapshots": [dict(r) for r in sold_rows],
        "active_snapshots": [dict(r) for r in active_rows],
    }


@router.get("/cards/{card_name}")
def get_card_price_detail(card_name: str, user_id: uuid.UUID = Depends(get_current_user_id)):
    with get_db() as db:
        card_name = card_name.strip()
        used = card_name
        matched_query = None
        if not _card_has_data(db, used):
            alt = _fuzzy_card_query(db, used)
            if alt:
                used = alt
                matched_query = alt
        sold_snaps = db.execute(
            "SELECT * FROM price_snapshots WHERE card_query = %s ORDER BY snapshot_date DESC LIMIT 30",
            (used,),
        ).fetchall()
        active_snaps = db.execute(
            "SELECT * FROM active_price_snapshots WHERE card_query = %s ORDER BY snapshot_date DESC LIMIT 30",
            (used,),
        ).fetchall()
        recent_sold = db.execute(
            "SELECT * FROM sold_listings WHERE card_query = %s ORDER BY sold_date DESC LIMIT 10",
            (used,),
        ).fetchall()
    return {
        "card_query": used,
        "matched_query": matched_query,
        "price_snapshots": [dict(r) for r in sold_snaps],
        "active_snapshots": [dict(r) for r in active_snaps],
        "recent_sold": [dict(r) for r in recent_sold],
    }
