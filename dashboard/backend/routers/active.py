from fastapi import APIRouter, Query
from dashboard.backend.database import get_db
from dashboard.backend.utils.pokemon_sprites import get_sprite_url

router = APIRouter(prefix="/api/v1/active", tags=["active"])

# Excel column names have spaces - quoted for SQL
_P = '"Price"'
_DL = '"Days Listed"'
_W = '"Watchers"'
_C = '"Card"'


def _exists(db) -> bool:
    return bool(
        db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='staging_active_listings'"
        ).fetchone()
    )


@router.get("/list")
def get_active_listings(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    card: str = Query(None),
    days_min: int = Query(None),
    days_max: int = Query(None),
    sort_by: str = Query("Days Listed"),
    sort_dir: str = Query("desc"),
):
    where_clauses = []
    params = []
    if card:
        where_clauses.append(f"{_C} LIKE ?")
        params.append(f"%{card}%")
    if days_min is not None:
        where_clauses.append(f"CAST({_DL} AS INTEGER) >= ?")
        params.append(days_min)
    if days_max is not None:
        where_clauses.append(f"CAST({_DL} AS INTEGER) <= ?")
        params.append(days_max)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    allowed_sort = {_DL, _P, _W, _C}
    sort_col = sort_by if f'"{sort_by}"' in allowed_sort or sort_by in allowed_sort else _DL
    if '"' not in sort_col:
        sort_col = f'"{sort_col}"'
    dir_sql = "ASC" if sort_dir == "asc" else "DESC"

    with get_db() as db:
        if not _exists(db):
            return {"items": [], "total": 0, "page": page, "per_page": per_page}
        total = db.execute(
            f"SELECT COUNT(*) AS c FROM staging_active_listings WHERE {where_sql}",
            params,
        ).fetchone()["c"]
        offset = (page - 1) * per_page
        rows = db.execute(
            f"SELECT * FROM staging_active_listings WHERE {where_sql} ORDER BY {sort_col} {dir_sql} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
    items = [dict(r) for r in rows]
    # Add sprite URL based on Title field
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


@router.get("/summary")
def get_active_summary():
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
            f"""SELECT COUNT(*) AS total_listings,
                       COALESCE(SUM(CAST({_P} AS REAL)), 0) AS total_value,
                       COALESCE(AVG(CAST({_DL} AS INTEGER)), 0) AS avg_days_listed,
                       COALESCE(AVG(CAST({_W} AS INTEGER)), 0) AS avg_watchers,
                       COALESCE(AVG(CAST({_P} AS REAL)), 0) AS avg_price
                FROM staging_active_listings
                WHERE {_P} IS NOT NULL AND {_P} != ''"""
        ).fetchone()
    return dict(row)


@router.get("/by-condition")
def get_active_by_condition():
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            """SELECT "Condition" AS condition, COUNT(*) AS count
               FROM staging_active_listings
               WHERE "Condition" IS NOT NULL AND "Condition" != ''
               GROUP BY "Condition" ORDER BY count DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/days-distribution")
def get_active_days_distribution():
    with get_db() as db:
        if not _exists(db):
            return []
        rows = db.execute(
            f"""SELECT
                   CASE
                     WHEN CAST({_DL} AS INTEGER) <= 10 THEN '0-10 days'
                     WHEN CAST({_DL} AS INTEGER) <= 20 THEN '11-20 days'
                     WHEN CAST({_DL} AS INTEGER) <= 30 THEN '21-30 days'
                     WHEN CAST({_DL} AS INTEGER) <= 60 THEN '31-60 days'
                     ELSE '60+ days'
                   END AS bucket,
                   COUNT(*) AS count
                 FROM staging_active_listings
                 WHERE {_DL} IS NOT NULL AND {_DL} != ''
                 GROUP BY bucket ORDER BY bucket"""
        ).fetchall()
    return [dict(r) for r in rows]
