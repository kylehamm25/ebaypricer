import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db
from dashboard.backend.services.stage_runner import SOLD_JOB_NAME, get_latest_run, run_sold_refresh
from dashboard.backend.utils.pokemon_sprites import get_sprite_url

router = APIRouter(prefix="/api/v1/sold", tags=["sold"])

_SELECT = (
    'order_id AS "Order ID", item_id AS "Item ID", sale_date AS "Sale Date", '
    'buyer AS "Buyer", item_title AS "Item Title", quantity AS "Quantity", '
    'item_price AS "Item Price", shipping AS "Shipping", order_total AS "Order Total", '
    'total_fees AS "Total eBay Fees", order_earnings AS "Order Earnings", '
    'sku AS "SKU", card AS "Card"'
)

_SORT_COLS = {
    "Sale Date": "sale_date",
    "Item Price": "item_price",
    "Item Title": "item_title",
    "Card": "card",
}


def _exists(db) -> bool:
    return bool(
        db.execute(
            "SELECT to_regclass('public.sold_orders') IS NOT NULL AS exists"
        ).fetchone()["exists"]
    )


@router.get("/list")
def get_sold_listings(
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    card: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    sort_by: str = Query("Sale Date"),
    sort_dir: str = Query("desc"),
):
    where_clauses = ["user_id = %s"]
    params = [user_id]
    if card:
        where_clauses.append("card LIKE %s")
        params.append(f"%{card}%")
    if date_from:
        where_clauses.append("sale_date >= %s")
        params.append(date_from)
    if date_to:
        where_clauses.append("sale_date <= %s")
        params.append(date_to)

    where_sql = " AND ".join(where_clauses)
    sort_col = _SORT_COLS.get(sort_by, "sale_date")
    dir_sql = "ASC" if sort_dir == "asc" else "DESC"

    with get_db() as db:
        if not _exists(db):
            return {"items": [], "total": 0, "page": page, "per_page": per_page}
        total = db.execute(
            f"SELECT COUNT(*) AS c FROM sold_orders WHERE {where_sql}",
            params,
        ).fetchone()["c"]
        offset = (page - 1) * per_page
        rows = db.execute(
            f"SELECT {_SELECT} FROM sold_orders WHERE {where_sql} "
            f"ORDER BY {sort_col} {dir_sql} LIMIT %s OFFSET %s",
            params + [per_page, offset],
        ).fetchall()
    items = [dict(r) for r in rows]
    for item in items:
        title = item.get("Item Title", "")
        if title:
            item["sprite_url"] = get_sprite_url(title)
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/summary")
def get_sold_summary(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        if not _exists(db):
            return {
                "total_items": 0,
                "total_revenue": 0,
                "total_shipping": 0,
                "total_fees": 0,
                "total_earnings": 0,
                "avg_price": 0,
            }
        row = db.execute(
            """SELECT (SELECT COUNT(*) FROM sold_orders WHERE user_id = %s) AS total_items,
                       COALESCE(ROUND(SUM(item_price), 2), 0) AS total_revenue,
                       COALESCE((SELECT ROUND(SUM(s), 2) FROM (
                                  SELECT order_id, MAX(shipping) AS s
                                  FROM sold_orders WHERE user_id = %s GROUP BY order_id
                                )), 0) AS total_shipping,
                       COALESCE((SELECT ROUND(SUM(f), 2) FROM (
                                  SELECT order_id, MAX(total_fees) AS f
                                  FROM sold_orders WHERE user_id = %s GROUP BY order_id
                                )), 0) AS total_fees,
                       COALESCE(ROUND(AVG(item_price), 2), 0) AS avg_price
                FROM sold_orders WHERE user_id = %s""",
            [user_id, user_id, user_id, user_id],
        ).fetchone()
    result = dict(row)
    result["total_earnings"] = round(result["total_revenue"] - result["total_fees"], 2)
    return result


@router.get("/trends")
def get_sold_trends(user_id: UUID = Depends(get_current_user_id), days: int = 90):
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            """SELECT sale_date AS date, COUNT(*) AS count,
                       COALESCE(SUM(item_price), 0) AS revenue
                FROM sold_orders
                WHERE user_id = %s
                  AND sale_date >= CURRENT_DATE - make_interval(days => %s)
                GROUP BY sale_date ORDER BY sale_date ASC""",
            [user_id, days - 1],
        ).fetchall()
        by_date = {r["date"].isoformat(): r for r in rows}
        today = datetime.now(timezone.utc).date()
        trends = []
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            r = by_date.get(d)
            trends.append(
                {
                    "date": d,
                    "count": r["count"] if r else 0,
                    "revenue": r["revenue"] if r else 0,
                }
            )
    return trends


@router.get("/refresh/status")
def get_sold_refresh_status(user_id: UUID = Depends(get_current_user_id)):
    row = get_latest_run(SOLD_JOB_NAME)
    if row is None:
        return {"state": "idle", "last_run_at": None, "last_status": None}
    running = row["finished_at"] is None
    return {
        "state": "running" if running else "idle",
        "last_run_at": (row["finished_at"] or row["started_at"]).isoformat(),
        "last_status": row["status"],
    }


@router.post("/refresh")
def trigger_sold_refresh(user_id: UUID = Depends(get_current_user_id)):
    row = get_latest_run(SOLD_JOB_NAME)
    if row is not None and row["finished_at"] is None:
        raise HTTPException(409, "Sold orders refresh is already running")
    threading.Thread(target=run_sold_refresh, daemon=True).start()
    return {"message": "Sold orders refresh started"}


@router.get("/by-card")
def get_sold_by_card(user_id: UUID = Depends(get_current_user_id), min_sales: int = 1):
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            """SELECT card AS card_query, COUNT(*) AS count,
                       ROUND(AVG(item_price), 2) AS avg_price,
                       ROUND(SUM(item_price), 2) AS total_revenue
                FROM sold_orders
                WHERE user_id = %s
                  AND card IS NOT NULL AND card != ''
                GROUP BY card
                HAVING COUNT(*) >= %s
                ORDER BY COUNT(*) DESC LIMIT 50""",
            [user_id, min_sales],
        ).fetchall()
    return [dict(r) for r in rows]
