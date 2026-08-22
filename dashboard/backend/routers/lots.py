"""Buying lots, keyed by the SKU already stamped on every listing and order.

The only stored fact is what was paid (table `lots`, migration 0008). Units sold,
net proceeds, items still listed and current listed value are all aggregated live
from sold_orders + active_listings, so a lot appears here the moment its SKU shows
up in the data - entering a cost is what turns it into a profit figure.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import UndefinedColumn, UndefinedTable
from pydantic import BaseModel, Field

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db
from dashboard.backend.utils.pokemon_sprites import get_sprite_url

router = APIRouter(prefix="/api/v1/lots", tags=["lots"])

NO_SKU = "(no SKU)"

# Not purchased lots, so there is no cost basis to track and nothing here would
# ever show a profit: PULL is cards pulled from packs personally (nothing was
# paid per card), NONTCG is non-TCG stock, and NO_SKU is rows with no SKU stamped
# at all. Excluded from this page entirely - their sales still show on the Sold
# Orders page, which is where the full picture lives.
EXCLUDED_SKUS = ("PULL", "NONTCG", NO_SKU)

# eBay reports order-level money (order_total, total_fees, order_earnings) on only
# ONE row of a multi-item order - see append_sold_orders.py. Summing order_earnings
# per SKU therefore credits an entire mixed order to whichever lot happens to own
# that one row, and gives the other lots in it nothing. So the order's net is split
# across its lines in proportion to each line's share of the order's item value.
# This conserves exactly: the allocated nets sum back to the reported order nets.
_SOLD_LINES_CTE = f"""
order_totals AS (
    SELECT order_id,
           MAX(order_earnings) AS order_net,
           SUM(item_price * COALESCE(quantity, 1)) AS order_gross
    FROM sold_orders
    WHERE user_id = %(uid)s
    GROUP BY order_id
),
sold_lines AS (
    SELECT COALESCE(NULLIF(TRIM(s.sku), ''), '{NO_SKU}') AS sku,
           s.order_id,
           s.item_id,
           s.item_title,
           s.card,
           COALESCE(s.quantity, 1) AS qty,
           s.item_price,
           s.item_price * COALESCE(s.quantity, 1) AS line_gross,
           CASE
               WHEN t.order_net IS NULL THEN NULL
               WHEN COALESCE(t.order_gross, 0) = 0 THEN NULL
               ELSE t.order_net * (s.item_price * COALESCE(s.quantity, 1)) / t.order_gross
           END AS line_net,
           s.sale_date
    FROM sold_orders s
    JOIN order_totals t ON t.order_id = s.order_id
    WHERE s.user_id = %(uid)s
)
"""

_LOT_AGGREGATE_SQL = f"""
WITH {_SOLD_LINES_CTE},
sold_agg AS (
    SELECT sku,
           SUM(qty) AS sold_items,
           SUM(line_gross) AS sold_gross,
           SUM(line_net) AS sold_net,
           -- Fee data arrives from the Finances API after the sale, so a very
           -- recent order can have no net yet. Counted, not silently treated as 0.
           COUNT(*) FILTER (WHERE line_net IS NULL) AS sold_missing_net,
           MIN(sale_date) AS first_sale,
           MAX(sale_date) AS last_sale
    FROM sold_lines
    -- Non-lot SKUs drop out HERE, after the allocation above - never before it.
    -- The allocation's denominator is the whole order's item value, so an order
    -- mixing PULL with a real lot must still be split across all its lines; strip
    -- the PULL lines first and that order's entire net lands on the lot instead.
    WHERE NOT (sku = ANY(%(excluded)s))
    GROUP BY sku
),
active_agg AS (
    SELECT COALESCE(NULLIF(TRIM(sku), ''), '{NO_SKU}') AS sku,
           SUM(COALESCE(quantity, 1)) AS active_items,
           SUM(COALESCE(price, 0) * COALESCE(quantity, 1)) AS listed_value
    FROM active_listings
    WHERE user_id = %(uid)s
      AND NOT (COALESCE(NULLIF(TRIM(sku), ''), '{NO_SKU}') = ANY(%(excluded)s))
    GROUP BY 1
)
SELECT COALESCE(a.sku, s.sku) AS sku,
       COALESCE(a.active_items, 0) AS active_items,
       COALESCE(a.listed_value, 0) AS listed_value,
       COALESCE(s.sold_items, 0) AS sold_items,
       COALESCE(s.sold_gross, 0) AS sold_gross,
       COALESCE(s.sold_net, 0) AS sold_net,
       COALESCE(s.sold_missing_net, 0) AS sold_missing_net,
       s.first_sale,
       s.last_sale
FROM active_agg a
FULL OUTER JOIN sold_agg s ON s.sku = a.sku
"""

# One lot's sold lines. line_net is the line's allocated share of its order's net
# (see _SOLD_LINES_CTE), never the raw order-level figure - so these rows sum to
# the same sold_net the lots list shows, and a multi-item order reads sensibly
# line by line instead of putting the whole order's money on one row.
_LOT_SOLD_SQL = f"""
WITH {_SOLD_LINES_CTE}
SELECT order_id, item_id, item_title, card, sale_date,
       qty AS quantity, item_price, line_gross, line_net
FROM sold_lines
WHERE sku = %(sku)s
ORDER BY sale_date DESC NULLS LAST, order_id, item_id
"""

# One lot's live listings. Same SKU normalisation as the aggregate above, so the
# rows here are exactly the ones counted in active_items / listed_value.
_LOT_ACTIVE_SQL = f"""
SELECT item_id, title, card, condition, price, shipping_charge, quantity,
       days_listed, watchers, start_date, estimated_net, suggested_price
FROM active_listings
WHERE user_id = %(uid)s
  AND COALESCE(NULLIF(TRIM(sku), ''), '{NO_SKU}') = %(sku)s
ORDER BY price DESC NULLS LAST, item_id
"""


def _f(value) -> float:
    """Numerics come back as Decimal; JSON wants float."""
    return float(value) if value is not None else 0.0


def _fopt(value) -> float | None:
    """Like _f, but keeps null null - a missing net is not a net of zero.

    Rounded: the allocated line net is a division, so it arrives with far more
    decimal places than money has.
    """
    return round(float(value), 2) if value is not None else None


# `title` arrived in migration 0009, after 0008 was already applied, so it may not
# exist yet. Widest column list first; the fallback drops title only.
_LOT_COLUMNS = ("sku, title, cost, purchased_at, source, notes",
                "sku, cost, purchased_at, source, notes")


def _fetch_costs(user_id: UUID) -> tuple[dict[str, dict], bool]:
    """Stored lot fields keyed by SKU, plus whether migration 0008 has been run.

    Takes its own connection per attempt: a failed statement aborts the whole
    transaction, so the fallback query cannot reuse the one that just errored.
    """
    for columns in _LOT_COLUMNS:
        try:
            with get_db() as db:
                rows = db.execute(
                    f"SELECT {columns} FROM lots WHERE user_id = %s", [user_id]
                ).fetchall()
            return {r["sku"]: dict(r) for r in rows}, True
        except UndefinedTable:
            return {}, False
        except UndefinedColumn:
            continue  # migration 0009 not run yet; retry without title
    return {}, True


@router.get("")
def list_lots(user_id: UUID = Depends(get_current_user_id)):
    # Read stored fields first, on their own connection - a missing table or column
    # aborts the transaction, so the aggregate below needs a clean one.
    costs, cost_tracking_enabled = _fetch_costs(user_id)
    with get_db() as db:
        try:
            rows = db.execute(
                _LOT_AGGREGATE_SQL,
                {"uid": user_id, "excluded": list(EXCLUDED_SKUS)},
            ).fetchall()
        except UndefinedTable:
            # Pre-migration-0001 install; nothing to aggregate yet.
            rows = []
        # A cost saved against a SKU that no longer has any listing or order would
        # otherwise vanish along with the money it records, so keep it visible.
        known = {r["sku"] for r in rows}
        orphans = [
            sku for sku in costs
            if sku not in known and sku not in EXCLUDED_SKUS
        ]

    lots = [_build_lot(dict(r), costs.get(r["sku"])) for r in rows]
    lots += [_build_lot(_empty_agg(sku), costs[sku]) for sku in orphans]
    lots.sort(key=lambda x: x["sku"])
    return {
        "lots": lots,
        "totals": _totals(lots),
        "cost_tracking_enabled": cost_tracking_enabled,
    }


def _empty_agg(sku: str) -> dict:
    """A lot with a cost recorded but nothing (any longer) listed or sold under it."""
    return {"sku": sku, "active_items": 0, "listed_value": 0, "sold_items": 0,
            "sold_gross": 0, "sold_net": 0, "sold_missing_net": 0,
            "first_sale": None, "last_sale": None}


@router.get("/{sku}")
def get_lot(sku: str, user_id: UUID = Depends(get_current_user_id)):
    """One lot's summary plus the sold and active listings behind it."""
    sku = sku.strip()
    if not sku or sku in EXCLUDED_SKUS:
        raise HTTPException(404, f"{sku or 'That SKU'} is not a purchased lot")

    costs, cost_tracking_enabled = _fetch_costs(user_id)
    with get_db() as db:
        try:
            # The whole-catalog aggregate, then the one row - rather than a
            # SKU-filtered copy of it. There are a dozen lots, and this guarantees
            # the header here shows exactly what the list row showed, including the
            # cross-lot net allocation, which a filtered query would get wrong.
            rows = db.execute(
                _LOT_AGGREGATE_SQL,
                {"uid": user_id, "excluded": list(EXCLUDED_SKUS)},
            ).fetchall()
            agg = next((dict(r) for r in rows if r["sku"] == sku), None)
            sold = db.execute(_LOT_SOLD_SQL, {"uid": user_id, "sku": sku}).fetchall()
            active = db.execute(_LOT_ACTIVE_SQL, {"uid": user_id, "sku": sku}).fetchall()
        except UndefinedTable:
            # Pre-migration-0001 install; nothing to aggregate yet.
            agg, sold, active = None, [], []

    if agg is None:
        # No listing or order carries this SKU. That is still a real lot if a cost
        # was saved against it - otherwise the SKU simply doesn't exist.
        if sku not in costs:
            raise HTTPException(404, f"No lot {sku}")
        agg = _empty_agg(sku)

    return {
        "lot": _build_lot(agg, costs.get(sku)),
        "sold": [_sold_row(dict(r)) for r in sold],
        "active": [_active_row(dict(r)) for r in active],
        "cost_tracking_enabled": cost_tracking_enabled,
    }


def _sold_row(row: dict) -> dict:
    return {
        "order_id": row["order_id"],
        "item_id": row["item_id"],
        "item_title": row["item_title"],
        "card": row["card"],
        "sale_date": _iso(row["sale_date"]),
        "quantity": int(row["quantity"] or 1),
        "item_price": _fopt(row["item_price"]),
        "line_gross": _fopt(row["line_gross"]),
        # Null, not 0: the Finances API hasn't reported this order's fees yet.
        "line_net": _fopt(row["line_net"]),
        "sprite_url": get_sprite_url(row["item_title"] or ""),
    }


def _active_row(row: dict) -> dict:
    return {
        "item_id": row["item_id"],
        "title": row["title"],
        "card": row["card"],
        "condition": row["condition"],
        "price": _fopt(row["price"]),
        "shipping_charge": _fopt(row["shipping_charge"]),
        "quantity": int(row["quantity"] or 1),
        "days_listed": int(row["days_listed"]) if row["days_listed"] is not None else None,
        "watchers": int(row["watchers"]) if row["watchers"] is not None else None,
        "start_date": _iso(row["start_date"]),
        "estimated_net": _fopt(row["estimated_net"]),
        "suggested_price": _fopt(row["suggested_price"]),
        "sprite_url": get_sprite_url(row["title"] or ""),
    }


def _build_lot(agg: dict, cost_row: dict | None) -> dict:
    cost = _f(cost_row["cost"]) if cost_row and cost_row["cost"] is not None else None
    sold_net = _f(agg["sold_net"])
    listed_value = _f(agg["listed_value"])

    lot = {
        "sku": agg["sku"],
        # Absent (rather than None) when migration 0009 hasn't been run.
        "title": (cost_row or {}).get("title"),
        "cost": cost,
        "purchased_at": _iso(cost_row.get("purchased_at")) if cost_row else None,
        "source": (cost_row or {}).get("source"),
        "notes": (cost_row or {}).get("notes"),
        "active_items": int(agg["active_items"] or 0),
        "listed_value": listed_value,
        "sold_items": int(agg["sold_items"] or 0),
        "sold_gross": _f(agg["sold_gross"]),
        "sold_net": sold_net,
        "sold_missing_net": int(agg["sold_missing_net"] or 0),
        "first_sale": _iso(agg.get("first_sale")),
        "last_sale": _iso(agg.get("last_sale")),
    }
    lot["total_items"] = lot["active_items"] + lot["sold_items"]

    # Everything below needs a cost to mean anything, and a lot with no cost
    # entered yet is the normal starting state - so these stay null rather than
    # defaulting to zero, which would read as "broke even".
    if cost is None or cost <= 0:
        lot.update(realized_profit=None, projected_profit=None,
                   roi_pct=None, recouped_pct=None)
        return lot

    # Realized = money actually banked against money spent. Projected additionally
    # assumes every unsold item sells at its current asking price, which is
    # optimistic (it ignores the fees those future sales will incur) - the UI
    # labels it as such.
    lot["realized_profit"] = round(sold_net - cost, 2)
    lot["projected_profit"] = round(sold_net + listed_value - cost, 2)
    lot["roi_pct"] = round((sold_net - cost) / cost * 100, 1)
    lot["recouped_pct"] = round(sold_net / cost * 100, 1)
    return lot


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, date) else None


def _totals(lots: list[dict]) -> dict:
    # Only lots with a cost roll into the money totals - a lot whose cost hasn't
    # been entered yet would otherwise show profit against zero investment and
    # make the ROI meaningless.
    tracked = [x for x in lots if x["cost"] is not None]
    cost = sum(x["cost"] for x in tracked)
    sold_net = sum(x["sold_net"] for x in tracked)
    listed_value = sum(x["listed_value"] for x in tracked)
    return {
        "cost": round(cost, 2),
        "sold_net": round(sold_net, 2),
        "listed_value": round(listed_value, 2),
        "realized_profit": round(sold_net - cost, 2),
        "projected_profit": round(sold_net + listed_value - cost, 2),
        "tracked_lots": len(tracked),
        "untracked_lots": len(lots) - len(tracked),
    }


class LotUpdate(BaseModel):
    title: str | None = Field(None, max_length=200)
    cost: float | None = Field(None, ge=0)
    purchased_at: date | None = None
    source: str | None = None
    notes: str | None = None


_UPSERT_WITH_TITLE = """
INSERT INTO lots (user_id, sku, title, cost, purchased_at, source, notes, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, now())
ON CONFLICT (user_id, sku) DO UPDATE SET
    title = EXCLUDED.title,
    cost = EXCLUDED.cost,
    purchased_at = EXCLUDED.purchased_at,
    source = EXCLUDED.source,
    notes = EXCLUDED.notes,
    updated_at = now()
"""

_UPSERT_NO_TITLE = """
INSERT INTO lots (user_id, sku, cost, purchased_at, source, notes, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, now())
ON CONFLICT (user_id, sku) DO UPDATE SET
    cost = EXCLUDED.cost,
    purchased_at = EXCLUDED.purchased_at,
    source = EXCLUDED.source,
    notes = EXCLUDED.notes,
    updated_at = now()
"""


@router.put("/{sku}")
def upsert_lot(sku: str, body: LotUpdate, user_id: UUID = Depends(get_current_user_id)):
    sku = sku.strip()
    if not sku:
        raise HTTPException(422, "SKU is required")
    # Refused rather than silently stored: these never appear on this page, so a
    # cost saved here would be money recorded nowhere the user can see it again.
    if sku in EXCLUDED_SKUS:
        raise HTTPException(422, f"{sku} is not a purchased lot and isn't tracked here")

    title = (body.title or "").strip() or None
    common = [body.cost, body.purchased_at, body.source or None, body.notes or None]
    try:
        with get_db(read_only=False) as db:
            db.execute(_UPSERT_WITH_TITLE, [user_id, sku, title] + common)
    except UndefinedColumn:
        # Migration 0009 not run. Everything else still saves; a title would be
        # silently dropped, so that is refused loudly instead.
        if title:
            raise HTTPException(
                503, "Lot titles need migration db/migrations/0009_lots_title.sql to be run first"
            )
        with get_db(read_only=False) as db:
            db.execute(_UPSERT_NO_TITLE, [user_id, sku] + common)
    except UndefinedTable:
        raise HTTPException(
            503, "Lot cost tracking needs migration db/migrations/0008_lots.sql to be run first"
        )
    return {"status": "ok", "sku": sku}
