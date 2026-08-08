from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _table_exists(db, name: str) -> bool:
    return bool(
        db.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS exists", (f"public.{name}",)
        ).fetchone()["exists"]
    )


@router.get("/kpis")
def get_dashboard_kpis(user_id: UUID = Depends(get_current_user_id)):
    with get_db() as db:
        sold_exists = _table_exists(db, "sold_orders")
        active_exists = _table_exists(db, "active_listings")

        sold_items = 0
        revenue = 0
        shipping = 0
        fees = 0
        trends = []
        top_items = []

        if sold_exists:
            rows = db.execute(
                """SELECT sale_date AS date, COUNT(*) AS count,
                          COALESCE(SUM(item_price), 0) AS revenue
                   FROM sold_orders
                   WHERE user_id = %s
                     AND sale_date >= CURRENT_DATE - INTERVAL '29 days'
                   GROUP BY sale_date ORDER BY sale_date ASC""",
                [user_id],
            ).fetchall()
            by_date = {r["date"].isoformat(): r for r in rows}
            today = datetime.now(timezone.utc).date()
            trends = []
            for i in range(29, -1, -1):
                d = (today - timedelta(days=i)).isoformat()
                r = by_date.get(d)
                trends.append(
                    {
                        "date": d,
                        "count": r["count"] if r else 0,
                        "revenue": r["revenue"] if r else 0,
                    }
                )

            month_filter = "to_char(sale_date, 'YYYY-MM') = to_char(CURRENT_DATE, 'YYYY-MM')"

            row = db.execute(
                f"""SELECT (SELECT COUNT(*) FROM sold_orders WHERE user_id = %s AND {month_filter}) AS items,
                           (SELECT COALESCE(ROUND(SUM(item_price), 2), 0)
                            FROM sold_orders WHERE user_id = %s AND {month_filter}) AS rev,
                           COALESCE(ROUND(SUM(order_ship), 2), 0) AS ship,
                           COALESCE(ROUND(SUM(order_fees), 2), 0) AS fees
                    FROM (
                      SELECT order_id,
                             MAX(shipping) AS order_ship,
                             MAX(total_fees) AS order_fees
                      FROM sold_orders
                      WHERE user_id = %s AND {month_filter}
                      GROUP BY order_id
                    )""",
                [user_id, user_id, user_id],
            ).fetchone()
            sold_items = row["items"]
            revenue = row["rev"]
            shipping = row["ship"]
            fees = row["fees"]

            top_items = [
                dict(r) for r in db.execute(
                    f"""SELECT item_title AS title, COUNT(*) AS count,
                               ROUND(AVG(item_price), 2) AS avg_price,
                               ROUND(SUM(item_price), 2) AS revenue
                        FROM sold_orders
                        WHERE user_id = %s AND {month_filter}
                          AND item_title IS NOT NULL AND item_title != ''
                        GROUP BY item_title
                        ORDER BY count DESC LIMIT 10""",
                    [user_id],
                ).fetchall()
            ]

        active_count = 0
        if active_exists:
            active_count = db.execute(
                "SELECT COUNT(*) AS c FROM active_listings WHERE user_id = %s",
                [user_id],
            ).fetchone()["c"]

    return {
        "sold_items": sold_items,
        "revenue": revenue,
        "shipping": shipping,
        "fees": fees,
        "active_listings": active_count,
        "trends": trends,
        "top_items": top_items,
    }
