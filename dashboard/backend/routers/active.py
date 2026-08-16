import threading
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.errors import UndefinedTable
from psycopg.types.json import Json
from pydantic import BaseModel

from ebaypricer.trading_api import EbayReviseError, revise_price_with_best_offer

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db
from dashboard.backend.services.ebay_oauth import NotConnectedError, get_access_token
from dashboard.backend.services.suggested_price import REPRICE_COOLDOWN_DAYS
from dashboard.backend.services.stage_runner import ACTIVE_JOB_NAME, get_latest_run, run_active_refresh
from dashboard.backend.utils.pokemon_sprites import get_sprite_url

router = APIRouter(prefix="/api/v1/active", tags=["active"])

_SELECT = (
    'item_id AS "Item ID", title AS "Title", card AS "Card", condition AS "Condition", '
    'sku AS "SKU", price AS "Price", shipping_charge AS "Shipping Charge", '
    'COALESCE(ad_rate::text || \'%%\', \'\') AS "Ad Rate", watchers AS "Watchers", '
    'days_listed AS "Days Listed", start_date AS "Start Date", quantity AS "Quantity", '
    'estimated_fees AS "Estimated Fees", estimated_net AS "Estimated Net", '
    'recent_sold_avg AS "Recent Sold Avg", price_vs_sold_avg AS "Price vs Sold Avg", '
    'recent_sold_count AS "Recent Sold Count", last_checked AS "Last Checked", '
    'active_avg_top5 AS "Active Avg (Top 5)", price_accuracy AS "Price Accuracy", '
    'search_position AS "Search Position", '
    # Computed server-side by services/suggested_price.py. Both /list and /item use
    # this same _SELECT, which is what keeps the list page and the detail page showing
    # one identical number - they previously each derived their own and disagreed.
    'suggested_price AS "Suggested Price", suggested_price_at AS "Suggested Price At", '
    'suggested_price_basis AS "Suggested Price Basis"'
)

_SORT_COLS = {
    "Days Listed": "days_listed",
    "Watchers": "watchers",
    "Price": "price",
    "Search Position": "search_position",
    "Card": "card",
    "Condition": "condition",
    "Suggested Price": "suggested_price",
}


def _exists(db, table: str = "active_listings") -> bool:
    return bool(
        db.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS exists", [f"public.{table}"]
        ).fetchone()["exists"]
    )


@router.get("/list")
def get_active_listings(
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    card: str = Query(None),
    days_min: int = Query(None),
    days_max: int = Query(None),
    sort_by: str = Query("Days Listed"),
    sort_dir: str = Query("desc"),
):
    where_clauses = ["user_id = %s"]
    params = [user_id]
    if card:
        where_clauses.append("card LIKE %s")
        params.append(f"%{card}%")
    if days_min is not None:
        where_clauses.append("days_listed >= %s")
        params.append(days_min)
    if days_max is not None:
        where_clauses.append("days_listed <= %s")
        params.append(days_max)

    where_sql = " AND ".join(where_clauses)
    sort_col = _SORT_COLS.get(sort_by, "days_listed")
    dir_sql = "ASC" if sort_dir == "asc" else "DESC"

    offset = (page - 1) * per_page
    # One round trip, not three. Re-sorting is the hottest path on this page and the
    # DB is remote (~30ms each way), so the separate to_regclass probe and COUNT(*)
    # were most of the click-to-repaint latency. The window count is evaluated before
    # LIMIT, so it still yields the full filtered total.
    with get_db() as db:
        try:
            rows = db.execute(
                f"SELECT {_SELECT}, COUNT(*) OVER () AS _total FROM active_listings "
                f"WHERE {where_sql} ORDER BY {sort_col} {dir_sql} LIMIT %s OFFSET %s",
                params + [per_page, offset],
            ).fetchall()
        except UndefinedTable:
            # Migration not applied yet - degrade rather than 500.
            return {"items": [], "total": 0, "page": page, "per_page": per_page}
        # A window count needs at least one row; an empty page (out-of-range offset or
        # a filter matching nothing) falls back to a plain COUNT so paging stays right.
        if rows:
            total = rows[0]["_total"]
        else:
            total = db.execute(
                f"SELECT COUNT(*) AS c FROM active_listings WHERE {where_sql}", params
            ).fetchone()["c"]

    items = []
    for row in rows:
        item = dict(row)
        item.pop("_total", None)
        title = item.get("Title", "")
        if title:
            item["sprite_url"] = get_sprite_url(title)
        items.append(item)
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/refresh/status")
def get_active_refresh_status(user_id: UUID = Depends(get_current_user_id)):
    row = get_latest_run(ACTIVE_JOB_NAME)
    if row is None:
        return {"state": "idle", "last_run_at": None, "last_status": None}
    running = row["finished_at"] is None
    return {
        "state": "running" if running else "idle",
        "last_run_at": (row["finished_at"] or row["started_at"]).isoformat(),
        "last_status": row["status"],
    }


@router.post("/refresh")
def trigger_active_refresh(user_id: UUID = Depends(get_current_user_id)):
    row = get_latest_run(ACTIVE_JOB_NAME)
    if row is not None and row["finished_at"] is None:
        raise HTTPException(409, "Active listings refresh is already running")
    threading.Thread(target=run_active_refresh, daemon=True).start()
    return {"message": "Active listings refresh started"}


@router.get("/item/{item_id}")
def get_active_item(item_id: str, user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        if not _exists(db):
            return None
        row = db.execute(
            f"SELECT {_SELECT} FROM active_listings WHERE user_id = %s AND item_id = %s",
            [user_id, item_id],
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
    title = item.get("Title", "")
    if title:
        item["sprite_url"] = get_sprite_url(title)
    return item


@router.post("/item/{item_id}/refresh")
def refresh_active_item(item_id: str, user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        row = db.execute(
            "SELECT card FROM active_listings WHERE user_id = %s AND item_id = %s",
            [user_id, item_id],
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Listing not found")
    card = row["card"]
    if not card:
        raise HTTPException(400, "Listing has no matched card to research")

    from dashboard.backend.services.price_research import refresh_card

    refresh_card(card)
    return get_active_item(item_id, user_id)


@router.get("/item/{item_id}/positions")
def get_active_item_positions(
    item_id: str,
    user_id: UUID = Depends(get_current_user_id),
    days: int = Query(90, ge=1, le=365),
):
    with get_db() as db:
        if not _exists(db, "listing_positions"):
            return []
        rows = db.execute(
            """SELECT snapshot_date, position, search_size
               FROM listing_positions
               WHERE user_id = %s AND item_id = %s
                 AND snapshot_date >= CURRENT_DATE - make_interval(days => %s)
               ORDER BY snapshot_date ASC""",
            [user_id, item_id, days],
        ).fetchall()
    return [dict(r) for r in rows]


class ReviseItemPrice(BaseModel):
    price: float


# Best Offer auto-accept and auto-decline are both pinned to this share of the new
# price: offers at or above it are auto-accepted, offers below it are auto-declined.
OFFER_THRESHOLD_PCT = 0.9


def _live_price(db, user_id: UUID, item_id: str) -> float | None:
    """The price we last recorded for one of this user's listings, or None if the
    listing isn't theirs. Feeds revise_price_with_best_offer, which needs to know
    which direction the price is moving to order its two eBay calls correctly."""
    row = db.execute(
        "SELECT price FROM active_listings WHERE user_id = %s AND item_id = %s",
        [user_id, item_id],
    ).fetchone()
    return None if row is None else (float(row["price"]) if row["price"] is not None else None)


def _log_price_changes(rows: list[tuple]) -> None:
    """Append applied price changes to price_change_log.
    rows: [(user_id, item_id, old_price, new_price, source), ...]

    Deliberately its own connection and transaction, not the caller's: the price is
    already live on eBay by the time we get here, so a failure to write history (most
    likely migration 0005 not applied yet) must not roll back the local UPDATE that
    records it. Same reasoning as the job_runs write below.

    This is also what feeds the reprice cooldown, so call it before any suggestion
    recompute - otherwise the recompute runs against a log that doesn't yet know about
    the change and re-suggests the listing we just repriced."""
    if not rows:
        return
    try:
        with get_db(read_only=False) as db, db.cursor() as cur:
            cur.executemany(
                "INSERT INTO price_change_log (user_id, item_id, old_price, new_price, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                rows,
            )
    except Exception as e:  # history must never fail the actual revision
        print(f"[price-log] failed to record {len(rows)} price change(s): {e}")


def _owns_item(db, user_id: UUID, item_id: str) -> bool:
    return db.execute(
        "SELECT 1 FROM active_listings WHERE user_id = %s AND item_id = %s",
        [user_id, item_id],
    ).fetchone() is not None


@router.post("/item/{item_id}/price")
def revise_active_item_price(
    item_id: str, body: ReviseItemPrice, user_id: UUID = Depends(get_current_user_id)
):
    if body.price <= 0:
        raise HTTPException(400, "Price must be greater than 0")
    # Confirm the listing is ours before calling eBay. The user's own token would make
    # eBay reject a foreign item anyway, but there's no reason to send the call.
    with get_db() as db:
        if not _owns_item(db, user_id, item_id):
            raise HTTPException(404, "Listing not found")
        current_price = _live_price(db, user_id, item_id)
    try:
        token = get_access_token(user_id)
    except NotConnectedError:
        raise HTTPException(409, "eBay account not connected")
    try:
        revise_price_with_best_offer(
            item_id, body.price, round(body.price * OFFER_THRESHOLD_PCT, 2), token,
            current_price=current_price,
        )
    except EbayReviseError as e:
        raise HTTPException(422, str(e))

    with get_db(read_only=False) as db:
        db.execute(
            "UPDATE active_listings SET price = %s WHERE user_id = %s AND item_id = %s",
            [body.price, user_id, item_id],
        )
    _log_price_changes([(user_id, item_id, current_price, body.price, "single")])
    return {"status": "ok", "price": body.price}


class BulkPriceItem(BaseModel):
    item_id: str
    price: float


class BulkPriceRequest(BaseModel):
    items: list[BulkPriceItem]


BULK_PRICE_JOB = "bulk_price_revision"
MAX_BULK_ITEMS = 100


@router.post("/bulk-price")
def bulk_revise_prices(body: BulkPriceRequest, user_id: UUID = Depends(get_current_user_id)):
    """Apply several price revisions in one call (the review-then-confirm bulk flow).

    Each item is attempted independently and reported on individually - one listing
    that eBay rejects must not silently discard the rest. Records a job_runs row for the
    batch and a price_change_log row per applied change."""
    if not body.items:
        raise HTTPException(400, "No items supplied")
    if len(body.items) > MAX_BULK_ITEMS:
        raise HTTPException(400, f"Too many items in one request (max {MAX_BULK_ITEMS})")

    try:
        token = get_access_token(user_id)
    except NotConnectedError:
        raise HTTPException(409, "eBay account not connected")

    started = datetime.now(timezone.utc)
    results: list[dict] = []
    changes: list[tuple] = []
    applied = 0

    with get_db() as db:
        owned = {
            r["item_id"]: (float(r["price"]) if r["price"] is not None else None)
            for r in db.execute(
                "SELECT item_id, price FROM active_listings WHERE user_id = %s", [user_id]
            ).fetchall()
        }

    for item in body.items:
        if item.price <= 0:
            results.append({"item_id": item.item_id, "status": "error", "error": "Price must be greater than 0"})
            continue
        if item.item_id not in owned:
            results.append({"item_id": item.item_id, "status": "error", "error": "Listing not found"})
            continue
        offer_threshold = round(item.price * OFFER_THRESHOLD_PCT, 2)
        try:
            offer_error = revise_price_with_best_offer(
                item.item_id, item.price, offer_threshold, token,
                current_price=owned[item.item_id],
            )
        except Exception as e:
            results.append({"item_id": item.item_id, "status": "error", "error": str(e)[:200]})
            continue
        offer_applied = offer_error is None
        offer_error = offer_error[:200] if offer_error else None
        with get_db(read_only=False) as db:
            db.execute(
                "UPDATE active_listings SET price = %s WHERE user_id = %s AND item_id = %s",
                [item.price, user_id, item.item_id],
            )
        applied += 1
        changes.append((user_id, item.item_id, owned[item.item_id], item.price, "bulk"))
        results.append({
            "item_id": item.item_id,
            "status": "ok" if offer_applied else "partial",
            "price": item.price,
            "offer_threshold": offer_threshold if offer_applied else None,
            **({"error": f"Price applied; offer thresholds not set: {offer_error}"} if not offer_applied else {}),
        })

    failed = len(results) - applied
    # Before the recompute below, so the suggestions it writes already see the cooldown.
    _log_price_changes(changes)

    try:
        with get_db(read_only=False) as db:
            db.execute(
                "INSERT INTO job_runs (job_name, user_id, status, started_at, finished_at, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    BULK_PRICE_JOB, user_id, "ok" if failed == 0 else "partial",
                    started, datetime.now(timezone.utc),
                    Json({"requested": len(body.items), "applied": applied, "failed": failed}),
                ),
            )
    except Exception as e:  # auditing must never fail the actual revision
        print(f"[bulk-price] failed to record job_run: {e}")

    # Prices changed, so the stored suggestions are now relative to stale prices.
    try:
        from dashboard.backend.services.price_research import recompute_suggestions

        recompute_suggestions(user_id=str(user_id))
    except Exception as e:
        print(f"[bulk-price] suggestion recompute failed: {e}")

    return {"applied": applied, "failed": failed, "results": results}


@router.get("/price-changes")
def list_price_changes(
    days: int = Query(30, ge=1, le=365),
    item_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user_id: UUID = Depends(get_current_user_id),
):
    """Applied price changes for this user, newest first - the history behind the
    reprice cooldown. Title/card are joined from active_listings and come back null for
    listings that have since ended, since the log outlives the listing row."""
    where = ["pcl.user_id = %s", "pcl.changed_at >= now() - make_interval(days => %s)"]
    params: list = [user_id, days]
    if item_id:
        where.append("pcl.item_id = %s")
        params.append(item_id)
    params.append(limit)

    with get_db() as db:
        if not _exists(db, "price_change_log"):
            return {"days": days, "cooldown_days": REPRICE_COOLDOWN_DAYS, "changes": []}
        rows = db.execute(
            f"""SELECT pcl.item_id, pcl.old_price, pcl.new_price, pcl.source, pcl.changed_at,
                       al.title, al.card, al.price AS current_price
                FROM price_change_log pcl
                LEFT JOIN active_listings al
                       ON al.user_id = pcl.user_id AND al.item_id = pcl.item_id
                WHERE {' AND '.join(where)}
                ORDER BY pcl.changed_at DESC
                LIMIT %s""",
            params,
        ).fetchall()
    return {"days": days, "cooldown_days": REPRICE_COOLDOWN_DAYS, "changes": [dict(r) for r in rows]}


@router.get("/summary")
def get_active_summary(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        if not _exists(db):
            return {
                "total_listings": 0,
                "total_value": 0,
                "avg_days_listed": 0,
                "avg_watchers": 0,
                "avg_price": 0,
            }
        row = db.execute(
            """SELECT COUNT(*) AS total_listings,
                       COALESCE(SUM(price * COALESCE(quantity, 1)), 0) AS total_value,
                       COALESCE(AVG(days_listed), 0) AS avg_days_listed,
                       COALESCE(AVG(watchers), 0) AS avg_watchers,
                       COALESCE(AVG(price), 0) AS avg_price
                FROM active_listings
                WHERE user_id = %s
                  AND price IS NOT NULL""",
            [user_id],
        ).fetchone()
    return dict(row)


@router.get("/by-card-value")
def get_active_by_card_value(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            """SELECT card AS card, COUNT(*) AS count,
                       COALESCE(SUM(price * COALESCE(quantity, 1)), 0) AS total_value
                FROM active_listings
                WHERE user_id = %s
                  AND card IS NOT NULL AND card != ''
                GROUP BY card ORDER BY total_value DESC""",
            [user_id],
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/value-buckets")
def get_active_value_buckets(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        if not _exists(db):
            return {"buckets": [], "total_count": 0, "total_value": 0}
        rows = db.execute(
            """SELECT
                   CASE
                     WHEN price <= 2 THEN '0-2'
                     WHEN price <= 5 THEN '2-5'
                     WHEN price <= 10 THEN '5-10'
                     WHEN price <= 25 THEN '10-25'
                     WHEN price <= 50 THEN '25-50'
                     ELSE '50+'
                   END AS bucket,
                   COUNT(*) AS count,
                   ROUND(SUM(price * COALESCE(quantity, 1)), 2) AS value
                 FROM active_listings
                 WHERE user_id = %s
                   AND price IS NOT NULL
                 GROUP BY bucket
                 ORDER BY MIN(price)""",
            [user_id],
        ).fetchall()
    buckets = [dict(r) for r in rows]
    total_count = sum(b["count"] for b in buckets)
    total_value = sum(b["value"] for b in buckets)
    for b in buckets:
        b["count_pct"] = round(b["count"] / total_count * 100, 1) if total_count else 0
        b["value_pct"] = round(b["value"] / total_value * 100, 1) if total_value else 0
    return {
        "buckets": buckets,
        "total_count": total_count,
        "total_value": round(total_value, 2),
    }


@router.get("/value-trend")
def get_active_value_trend(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        today = datetime.now(timezone.utc).date()
        rows = db.execute(
            """SELECT snapshot_date AS date, total_value, total_listings
               FROM inventory_value_history
               WHERE user_id = %s AND snapshot_date < %s
               ORDER BY snapshot_date ASC""",
            [user_id, today],
        ).fetchall()
        points = [dict(r) for r in rows]

        # Today's snapshot row (if any) only reflects the value as of the last sync,
        # which can lag behind mid-day listing/price changes. Compute it live instead
        # so the trend's current-day point always matches the "Total Value" KPI.
        if _exists(db):
            today_totals = db.execute(
                """SELECT COALESCE(SUM(price * COALESCE(quantity, 1)), 0) AS total_value,
                          COUNT(*) AS total_listings
                   FROM active_listings
                   WHERE user_id = %s AND price IS NOT NULL""",
                [user_id],
            ).fetchone()
            if today_totals["total_listings"] > 0:
                points.append({
                    "date": today,
                    "total_value": today_totals["total_value"],
                    "total_listings": today_totals["total_listings"],
                })
    return points


@router.get("/days-distribution")
def get_active_days_distribution(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            """SELECT
                   CASE
                     WHEN days_listed <= 10 THEN '0-10 days'
                     WHEN days_listed <= 20 THEN '11-20 days'
                     WHEN days_listed <= 30 THEN '21-30 days'
                     WHEN days_listed <= 60 THEN '31-60 days'
                     ELSE '60+ days'
                   END AS bucket,
                   COUNT(*) AS count
                 FROM active_listings
                 WHERE user_id = %s
                   AND days_listed IS NOT NULL
                 GROUP BY bucket ORDER BY bucket""",
            [user_id],
        ).fetchall()
    return [dict(r) for r in rows]
