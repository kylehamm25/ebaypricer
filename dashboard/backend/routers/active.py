from uuid import UUID

from fastapi import APIRouter, Depends, Query

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db
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
    'search_position AS "Search Position"'
)

_SORT_COLS = {
    "Days Listed": "days_listed",
    "Watchers": "watchers",
    "Price": "price",
    "Search Position": "search_position",
    "Card": "card",
    "Condition": "condition",
}


def _exists(db) -> bool:
    return bool(
        db.execute(
            "SELECT to_regclass('public.active_listings') IS NOT NULL AS exists"
        ).fetchone()["exists"]
    )


@router.get("/list")
def get_active_listings(
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    card: str = Query(None),
    condition: str = Query(None),
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
    if condition:
        where_clauses.append("condition = %s")
        params.append(condition)
    if days_min is not None:
        where_clauses.append("days_listed >= %s")
        params.append(days_min)
    if days_max is not None:
        where_clauses.append("days_listed <= %s")
        params.append(days_max)

    where_sql = " AND ".join(where_clauses)
    sort_col = _SORT_COLS.get(sort_by, "days_listed")
    dir_sql = "ASC" if sort_dir == "asc" else "DESC"

    with get_db() as db:
        if not _exists(db):
            return {"items": [], "total": 0, "page": page, "per_page": per_page}
        total = db.execute(
            f"SELECT COUNT(*) AS c FROM active_listings WHERE {where_sql}",
            params,
        ).fetchone()["c"]
        offset = (page - 1) * per_page
        rows = db.execute(
            f"SELECT {_SELECT} FROM active_listings WHERE {where_sql} "
            f"ORDER BY {sort_col} {dir_sql} LIMIT %s OFFSET %s",
            params + [per_page, offset],
        ).fetchall()
    items = [dict(r) for r in rows]
    for item in items:
        title = item.get("Title", "")
        if title:
            item["sprite_url"] = get_sprite_url(title)
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
    }


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
                       COALESCE(SUM(price), 0) AS total_value,
                       COALESCE(AVG(days_listed), 0) AS avg_days_listed,
                       COALESCE(AVG(watchers), 0) AS avg_watchers,
                       COALESCE(AVG(price), 0) AS avg_price
                FROM active_listings
                WHERE user_id = %s
                  AND price IS NOT NULL""",
            [user_id],
        ).fetchone()
    return dict(row)


@router.get("/by-condition")
def get_active_by_condition(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            """SELECT condition AS condition, COUNT(*) AS count
               FROM active_listings
               WHERE user_id = %s
                 AND condition IS NOT NULL AND condition != ''
               GROUP BY condition ORDER BY count DESC""",
            [user_id],
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/by-card-value")
def get_active_by_card_value(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            """SELECT card AS card, COUNT(*) AS count,
                       COALESCE(SUM(price), 0) AS total_value
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
                   ROUND(SUM(price), 2) AS value
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
        rows = db.execute(
            """SELECT snapshot_date AS date, total_value, total_listings
               FROM inventory_value_history
               WHERE user_id = %s
               ORDER BY snapshot_date ASC""",
            [user_id],
        ).fetchall()
    return [dict(r) for r in rows]


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
