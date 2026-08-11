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
        or db.execute("SELECT 1 FROM active_market_listings WHERE card_query = %s LIMIT 1", (q,)).fetchone()
    )


@router.get("/comparisons")
def get_price_comparisons(user_id: uuid.UUID = Depends(get_current_user_id)):
    with get_db() as db:
        # Research runs incrementally across cards (each run is wall-clock budgeted and
        # picks up where it left off), so on any given day only a handful of cards have
        # a snapshot dated *today* - most still carry yesterday's (or older) date. Using
        # a single shared "latest date" filter here previously meant every card not
        # touched by the most recent run vanished from this endpoint entirely, leaving
        # the Active Avg/Sold Avg columns blank for most listings. Pull each card's own
        # newest row instead, independent of what date that happens to be.
        #
        # active_price_snapshots is the primary table (Active Avg/Suggested no longer
        # depend on sold data at all) - LEFT JOIN sold data in optionally rather than
        # requiring it, or any card whose TCGdex lookup didn't find a price (~30% of
        # cards) would be excluded from this list entirely despite having perfectly
        # good active data.
        rows = db.execute(
            """SELECT DISTINCT ON (aps.card_query)
                      aps.card_query,
                      ps.weighted_avg AS sold_weighted_avg,
                      ps.sample_size AS sold_sample,
                      aps.avg_price AS active_avg,
                      aps.min_price AS active_min,
                      aps.sample_size AS active_sample
               FROM active_price_snapshots aps
               LEFT JOIN LATERAL (
                   SELECT weighted_avg, sample_size
                   FROM price_snapshots p
                   WHERE p.card_query = aps.card_query
                   ORDER BY p.snapshot_date DESC
                   LIMIT 1
               ) ps ON true
               ORDER BY aps.card_query, aps.snapshot_date DESC"""
        ).fetchall()

        if not rows:
            return []

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
        # Only recently-seen competitors. active_market_listings is append/upsert-only
        # (nothing ever deletes from it), so without this filter the comps table and the
        # Active Min/Max tiles surface listings that ended weeks ago.
        recent_active = db.execute(
            """SELECT * FROM active_market_listings
               WHERE card_query = %s AND pulled_at >= now() - interval '14 days'
               ORDER BY price ASC LIMIT 15""",
            (used,),
        ).fetchall()
    return {
        "card_query": used,
        "matched_query": matched_query,
        "price_snapshots": [dict(r) for r in sold_snaps],
        "active_snapshots": [dict(r) for r in active_snaps],
        "recent_active": [dict(r) for r in recent_active],
    }
