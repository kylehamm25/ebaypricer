from fastapi import APIRouter, Query
from dashboard.backend.database import get_db
from dashboard.backend.utils.pokemon_sprites import get_sprite_url

router = APIRouter(prefix="/api/v1/sold", tags=["sold"])

_SD = '"Sale Date"'
_IP = '"Item Price"'
_IT = '"Item Title"'
_C = '"Card"'


def _exists(db) -> bool:
    return bool(
        db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='staging_sold_orders'"
        ).fetchone()
    )


@router.get("/list")
def get_sold_listings(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    card: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    sort_by: str = Query("Sale Date"),
    sort_dir: str = Query("desc"),
):
    where_clauses = []
    params = []
    if card:
        where_clauses.append(f"{_C} LIKE ?")
        params.append(f"%{card}%")
    if date_from:
        where_clauses.append(f"{_SD} >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append(f"{_SD} <= ?")
        params.append(date_to)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    sort_col = sort_by if sort_by in (_SD, _IP, _IT, _C) else _SD
    if '"' not in sort_col:
        sort_col = f'"{sort_col}"'
    dir_sql = "ASC" if sort_dir == "asc" else "DESC"

    with get_db() as db:
        if not _exists(db):
            return {"items": [], "total": 0, "page": page, "per_page": per_page}
        total = db.execute(
            f"SELECT COUNT(*) AS c FROM staging_sold_orders WHERE {where_sql}",
            params,
        ).fetchone()["c"]
        offset = (page - 1) * per_page
        rows = db.execute(
            f"SELECT * FROM staging_sold_orders WHERE {where_sql} ORDER BY {sort_col} {dir_sql} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
    items = [dict(r) for r in rows]
    # Add sprite URL based on Title field
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
def get_sold_summary():
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
            f"""SELECT COUNT(*) AS total_items,
                       COALESCE(ROUND(SUM(CAST({_IP} AS REAL)), 2), 0) AS total_revenue,
                       COALESCE(ROUND(SUM(CAST("Shipping" AS REAL)), 2), 0) AS total_shipping,
                       COALESCE(ROUND(SUM(CAST("Total eBay Fees" AS REAL)), 2), 0) AS total_fees,
                       COALESCE(ROUND(SUM(CAST("Order Earnings" AS REAL)), 2), 0) AS total_earnings,
                       COALESCE(ROUND(AVG(CAST({_IP} AS REAL)), 2), 0) AS avg_price
                FROM staging_sold_orders"""
        ).fetchone()
    return dict(row)


@router.get("/trends")
def get_sold_trends(days: int = 90):
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            f"""SELECT {_SD} AS date, COUNT(*) AS count,
                       COALESCE(SUM(CAST({_IP} AS REAL)), 0) AS revenue
                FROM staging_sold_orders
                GROUP BY {_SD} ORDER BY {_SD} DESC LIMIT ?""",
            (days,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/by-card")
def get_sold_by_card(min_sales: int = 1):
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            f"""SELECT {_C} AS card_query, COUNT(*) AS count,
                       ROUND(AVG(CAST({_IP} AS REAL)), 2) AS avg_price,
                       ROUND(SUM(CAST({_IP} AS REAL)), 2) AS total_revenue
                FROM staging_sold_orders
                WHERE {_C} IS NOT NULL AND {_C} != ''
                GROUP BY {_C}
                HAVING count >= ?
                ORDER BY count DESC LIMIT 50""",
            (min_sales,),
        ).fetchall()
    return [dict(r) for r in rows]
