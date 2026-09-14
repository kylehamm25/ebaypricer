"""What an unlisted inventory row is worth.

Extracted out of routers/inventory.py because routers/lots.py needs the same number
- a lot's unlisted stock is valued exactly the way the Inventory page values it, or
the two pages quietly disagree about the same cards. This is the only copy.

Nothing here researches. Values come from whatever `active_price_snapshots` already
holds, which is why callers pass a connection in and get one query for a whole page
rather than one per row; see the ebay-api-rate-limits skill for why pricing must
never happen inside a request handler.
"""

from dashboard.backend.services.suggested_price import condition_multiplier
from dashboard.backend.services.upsert_rules import existing_columns


def latest_snapshots(db, card_queries: list[str]) -> dict[str, dict]:
    """Newest cached comp snapshot per distinct card. No eBay call."""
    queries = [q for q in set(card_queries) if q]
    if not queries:
        return {}
    rows = db.execute(
        # DISTINCT ON keeps the newest per card; the table holds one row per
        # (card_query, snapshot_date), so without it a well-researched card would
        # arrive once for every day it was ever researched.
        """SELECT DISTINCT ON (card_query)
                  card_query, snapshot_date, avg_price, sample_size, pool_quality
           FROM active_price_snapshots
           WHERE card_query = ANY(%s)
           ORDER BY card_query, snapshot_date DESC""",
        [queries],
    ).fetchall()
    return {r["card_query"]: dict(r) for r in rows}


def row_value(row: dict, snap: dict | None) -> dict:
    """One row's value, condition-adjusted, or an explicit absence.

    Deliberately thin: a cached comp average times the shared condition ladder, and
    that is all. It is NOT a suggested price - no staleness blend, no guardrails, no
    rounding to a price ending - because none of that applies to a card that isn't
    listed. See the ebay-pricing-rules skill.
    """
    mult, known = condition_multiplier(row.get("condition"))
    qty = int(row.get("quantity") or 1)

    # A stated price wins over comps, and the condition multiplier deliberately does
    # NOT touch it - the same rule /valuation/manual follows. A comp average is a
    # mixed-condition figure that has to be scaled to the card in hand; a price the
    # seller typed is already the value of the card in hand, so scaling it again
    # would quietly reduce a number they stated outright.
    manual = row.get("manual_value")
    if manual is not None:
        unit = round(float(manual), 2)
        return {
            "unit_value": unit,
            "total_value": round(unit * qty, 2),
            "value_status": "manual",
            # No snapshot behind it, so there is no date, no comp count and no pool
            # to judge. Null rather than a figure borrowed from somewhere else.
            "value_date": None,
            "comps": None,
            "condition_known": known,
            "pool_filtered": None,
        }

    if not snap or snap.get("avg_price") is None:
        return {
            "unit_value": None,
            "total_value": None,
            # Two different absences: nothing has researched this card yet, versus
            # there is no catalog card or search to research (sealed, bulk).
            "value_status": "unresearched" if row.get("card_query") else "no_card",
            "value_date": None,
            "comps": None,
            "condition_known": known,
            "pool_filtered": None,
        }

    unit = round(float(snap["avg_price"]) * mult, 2)
    return {
        "unit_value": unit,
        "total_value": round(unit * qty, 2),
        "value_status": "ok",
        "value_date": snap["snapshot_date"].isoformat() if snap.get("snapshot_date") else None,
        "comps": snap.get("sample_size"),
        "condition_known": known,
        # A snapshot with no pool_quality predates comp filtering, so it may be
        # averaging graded slabs and multi-card lots. Flagged rather than hidden -
        # the same distinction routers/valuation.py draws.
        "pool_filtered": snap.get("pool_quality") is not None,
    }


def raise_below_minimum(db, user_id, min_price: float) -> int:
    """Bump every one of this user's active rows currently worth less than
    `min_price` up to it, in place. Returns how many rows were touched.

    Called from routers/settings.py right after a minimum listing price (migration
    0018) is saved - the point of a floor is that nothing already in the pile sits
    under it either, not just that nothing new gets listed under it.

    Writes `manual_value`, the only field that can make a row's shown value differ
    from its comp average, so a raised row stops following the comp price and holds
    at the minimum until manual_value is cleared by hand - a real, visible write, not
    a guardrail folded into `row_value`, which stays the thin comp-times-multiplier
    calculation the ebay-pricing-rules skill requires. Only ever raises: a row already
    at or above the minimum, or with no known value yet (row_value returned None), is
    left untouched, and this never researches - it works from whatever
    `active_price_snapshots` already holds, the same as everything else here.
    """
    present = existing_columns(db, "inventory")
    if "manual_value" not in present:
        # Nowhere to store the raised number. Not an error: saving the four required
        # listing-defaults fields doesn't depend on 0012 having been run either, so a
        # minimum can be set before there is anywhere to apply it.
        return 0

    where = ["user_id = %s"]
    params: list = [user_id]
    if "archived_at" in present:
        # A row that has left the pile is no longer a listing candidate; raising its
        # value would only distort a total nobody is looking at any more.
        where.append("archived_at IS NULL")

    rows = [dict(r) for r in db.execute(
        f"SELECT id, card_query, condition, quantity, manual_value FROM inventory "
        f"WHERE {' AND '.join(where)}",
        params,
    ).fetchall()]
    if not rows:
        return 0

    snaps = latest_snapshots(db, [r["card_query"] for r in rows if r["card_query"]])
    below = []
    for row in rows:
        value = row_value(row, snaps.get(row["card_query"]))
        if value["unit_value"] is not None and value["unit_value"] < min_price:
            below.append(row["id"])
    if not below:
        return 0

    db.execute(
        "UPDATE inventory SET manual_value = %s, updated_at = now() "
        "WHERE user_id = %s AND id = ANY(%s)",
        [min_price, user_id, below],
    )
    return len(below)
