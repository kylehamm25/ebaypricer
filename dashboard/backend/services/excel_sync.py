import logging
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from dashboard.backend.config import DEFAULT_USER_ID, EXCEL_PATH
from dashboard.backend.database import get_db

log = logging.getLogger(__name__)

_SOLD_COLUMNS = {
    "Order ID": "order_id",
    "Item ID": "item_id",
    "Sale Date": "sale_date",
    "Buyer": "buyer",
    "Item Title": "item_title",
    "Quantity": "quantity",
    "Item Price": "item_price",
    "Shipping": "shipping",
    "Order Total": "order_total",
    "Total eBay Fees": "total_fees",
    "Order Earnings": "order_earnings",
    "SKU": "sku",
    "Card": "card",
}

_ACTIVE_COLUMNS = {
    "Item ID": "item_id",
    "Title": "title",
    "Card": "card",
    "Condition": "condition",
    "SKU": "sku",
    "Price": "price",
    "Shipping Charge": "shipping_charge",
    "Ad Rate": "ad_rate",
    "Watchers": "watchers",
    "Days Listed": "days_listed",
    "Start Date": "start_date",
    "Quantity": "quantity",
    "Estimated Fees": "estimated_fees",
    "Estimated Net": "estimated_net",
    "Recent Sold Avg": "recent_sold_avg",
    "Price vs Sold Avg": "price_vs_sold_avg",
    "Recent Sold Count": "recent_sold_count",
    "Last Checked": "last_checked",
    "Active Avg (Top 5)": "active_avg_top5",
    "Price Accuracy": "price_accuracy",
    "Search Position": "search_position",
}

_DATE_COLUMNS = {"sale_date", "start_date", "last_checked"}
_INT_COLUMNS = {"quantity", "watchers", "days_listed", "recent_sold_count", "search_position"}
_NUM_COLUMNS = {
    "item_price", "shipping", "order_total", "total_fees", "order_earnings",
    "price", "shipping_charge", "estimated_fees", "estimated_net",
    "recent_sold_avg", "price_vs_sold_avg", "active_avg_top5", "price_accuracy",
    "total_value", "ad_rate",
}


def _to_text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _to_date(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_int(v):
    s = _to_text(v)
    if s is None:
        return None
    try:
        return int(Decimal(s))
    except (InvalidOperation, ValueError):
        return None


def _to_num(v):
    s = _to_text(v)
    if s is None:
        return None
    if isinstance(v, str) and v.strip().endswith("%"):
        s = v.strip().rstrip("%")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _coerce(col: str, v):
    if col in _DATE_COLUMNS:
        return _to_date(v)
    if col in _INT_COLUMNS:
        return _to_int(v)
    if col in _NUM_COLUMNS:
        return _to_num(v)
    return _to_text(v)


def _upsert_rows(conn, table: str, columns: dict[str, str], key_cols: list[str],
                 rows: list[dict], skip_cols: set[str] | None = None) -> int:
    """skip_cols: columns mapped here but absent from the sheet this run. They are left
    out of the statement entirely rather than written as NULL - writing NULL would let a
    column that merely went missing from the workbook ERASE good values already in
    Postgres (this is what happened to ad_rate). Omitted columns keep whatever the row
    already has; genuinely new rows just get the database default."""
    if not rows:
        return 0
    skip = skip_cols or set()
    all_cols = key_cols + [c for c in columns.values() if c not in key_cols and c not in skip]
    col_sql = ", ".join(all_cols)
    placeholders = ", ".join("%s" for _ in all_cols)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in all_cols if c not in key_cols)
    insert_sql = (
        f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(key_cols)}) DO UPDATE SET {updates}"
    )
    # item.get(c), NOT item[c]. A row only carries keys for headers that were actually
    # present in the sheet, and the sheet's schema is not guaranteed: get_active.py only
    # writes "Ad Rate" for promoted listings, so the column disappears entirely whenever
    # no listing is promoted or the Marketing API call fails. Indexing raised
    # KeyError: 'ad_rate' from inside the shared transaction, which rolled back BOTH
    # sheets - so one optional column going missing silently froze every sold order and
    # active listing in Postgres while the workbook itself kept updating fine.
    # Same "degrade rather than crash" rule the migrations follow.
    with conn.cursor() as cur:
        cur.executemany(insert_sql, [tuple(item.get(c) for c in all_cols) for item in rows])
    return len(rows)


def sync_excel(force: bool = False) -> dict:
    if not os.path.exists(EXCEL_PATH):
        return {"error": f"Excel file not found: {EXCEL_PATH}"}
    user_id = uuid.UUID(DEFAULT_USER_ID)

    wb = load_workbook(EXCEL_PATH, read_only=True, data_only=True)
    result = {}

    sheet_map = [
        ("Sold Orders", "sold_orders", _SOLD_COLUMNS, ["user_id", "order_id", "item_id"]),
        ("Active Listings", "active_listings", _ACTIVE_COLUMNS, ["user_id", "item_id"]),
    ]

    with get_db(read_only=False) as conn:
        for sheet_name, table, col_map, key_cols in sheet_map:
            if sheet_name not in wb.sheetnames:
                result[sheet_name] = "sheet not found"
                continue
            ws = wb[sheet_name]
            headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
            headers = [h.strip() if isinstance(h, str) else h for h in headers]

            # Columns we map but the sheet doesn't have. These now sync as NULL rather
            # than aborting (see _upsert_rows), so say so out loud - otherwise a column
            # quietly vanishing from the workbook looks like data that simply stopped
            # updating, with nothing anywhere explaining why.
            missing = [h for h in col_map if h not in headers]
            skip_cols = {col_map[h] for h in missing}
            if missing:
                log.warning(
                    "%s: sheet is missing mapped column(s) %s - leaving existing values "
                    "in place for them", sheet_name, ", ".join(missing),
                )

            rows = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                if all(v is None for v in row):
                    continue
                item = {"user_id": user_id}
                for header, v in zip(headers, row):
                    col = col_map.get(header)
                    if col is None:
                        continue
                    item[col] = _coerce(col, v)
                if all(item.get(k) is not None for k in key_cols[1:]):
                    rows.append(item)

            if not rows:
                result[sheet_name] = "0 rows synced"
                continue
            count = _upsert_rows(conn, table, col_map, key_cols, rows, skip_cols)
            result[sheet_name] = f"{count} rows synced"

            if table == "active_listings":
                # The Excel sheet is the source of truth for what's currently active;
                # anything not in this run's rows has sold/ended and must be dropped,
                # or it lingers in Postgres forever and inflates inventory value.
                current_ids = [r["item_id"] for r in rows]
                deleted = conn.execute(
                    "DELETE FROM active_listings WHERE user_id = %s AND item_id != ALL(%s)",
                    [user_id, current_ids],
                ).rowcount
                if deleted:
                    result[sheet_name] += f" ({deleted} stale rows removed)"

        total_row = conn.execute(
            "SELECT COALESCE(SUM(price * COALESCE(quantity, 1)), 0) AS v, COUNT(*) AS n "
            "FROM active_listings WHERE user_id = %s AND price IS NOT NULL",
            [user_id],
        ).fetchone()
        conn.execute(
            """INSERT INTO inventory_value_history (user_id, snapshot_date, total_value, total_listings)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (user_id, snapshot_date) DO UPDATE SET
                   total_value = EXCLUDED.total_value,
                   total_listings = EXCLUDED.total_listings""",
            (user_id, datetime.now(timezone.utc).date(), total_row["v"], total_row["n"]),
        )
        result["Inventory Value"] = (
            f"{total_row['n']} listings, ${total_row['v']:.2f} (history recorded)"
        )

    wb.close()
    return result
