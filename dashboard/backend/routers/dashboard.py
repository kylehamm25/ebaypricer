from fastapi import APIRouter
from dashboard.backend.database import get_db

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/kpis")
def get_dashboard_kpis():
    with get_db() as db:
        sold_exists = bool(
            db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='staging_sold_orders'"
            ).fetchone()
        )
        active_exists = bool(
            db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='staging_active_listings'"
            ).fetchone()
        )

        sold_items = 0
        revenue = 0
        shipping = 0
        fees = 0
        trends = []
        top_items = []

        if sold_exists:
            # Get last 90 days of daily data for trends (matching sold orders page)
            trends = [
                dict(r) for r in db.execute(
                    """SELECT "Sale Date" AS date, COUNT(*) AS count,
                              COALESCE(SUM(CAST("Item Price" AS REAL)), 0) AS revenue
                       FROM staging_sold_orders
                       WHERE "Sale Date" >= date('now', '-90 days')
                       GROUP BY "Sale Date" ORDER BY "Sale Date" ASC"""
                ).fetchall()
            ]

            # Current month KPIs
            month_filter = """strftime('%Y-%m', "Sale Date") = strftime('%Y-%m', 'now')"""

            row = db.execute(
                f"""SELECT (SELECT COUNT(*) FROM staging_sold_orders WHERE {month_filter}) AS items,
                           (SELECT COALESCE(ROUND(SUM(CAST("Item Price" AS REAL)), 2), 0)
                            FROM staging_sold_orders WHERE {month_filter}) AS rev,
                           COALESCE(ROUND(SUM(order_ship), 2), 0) AS ship,
                           COALESCE(ROUND(SUM(order_fees), 2), 0) AS fees
                    FROM (
                      SELECT "Order ID",
                             MAX(CAST("Shipping" AS REAL)) AS order_ship,
                             MAX(CAST("Total eBay Fees" AS REAL)) AS order_fees
                      FROM staging_sold_orders
                      WHERE {month_filter}
                      GROUP BY "Order ID"
                    )"""
            ).fetchone()
            sold_items = row["items"]
            revenue = row["rev"]
            shipping = row["ship"]
            fees = row["fees"]

            top_items = [
                dict(r) for r in db.execute(
                    f"""SELECT "Item Title" AS title, COUNT(*) AS count,
                               ROUND(AVG(CAST("Item Price" AS REAL)), 2) AS avg_price,
                               ROUND(SUM(CAST("Item Price" AS REAL)), 2) AS revenue
                        FROM staging_sold_orders
                        WHERE {month_filter}
                          AND "Item Title" IS NOT NULL AND "Item Title" != ''
                        GROUP BY "Item Title"
                        ORDER BY count DESC LIMIT 10"""
                ).fetchall()
            ]

        active_count = 0
        if active_exists:
            active_count = db.execute(
                "SELECT COUNT(*) AS c FROM staging_active_listings"
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
