"""One-time / on-demand import of an eBay Orders Report CSV into the sold orders workbook.

Reuses the full append pipeline from append_sold_orders.py (fee merge, card
enrichment, dedup against existing rows, Excel formatting), so the dashboard's
sold orders page picks up the imported history unchanged.

Usage:
    python scripts/import_orders_report.py [--csv path] [--output path]
"""

import argparse
import csv
import glob
import os
import sys
from datetime import datetime, timezone

from ebaypricer.auth import get_access_token

from append_sold_orders import DEFAULT_OUTPUT, append_rows_to_workbook

REPORT_GLOB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eBay-OrdersReport-*.csv")

MONEY_COLS = ("Sold For", "Shipping And Handling", "Total Price")
INT_COLS = ("Quantity",)


def parse_money(value: str) -> float:
    if value is None:
        return 0.0
    cleaned = value.strip().replace("$", "").replace(",", "")
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%b-%d-%y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def latest_report() -> str:
    matches = glob.glob(REPORT_GLOB)
    if not matches:
        print(f"No eBay Orders Report CSV found matching: {REPORT_GLOB}")
        sys.exit(1)
    return max(matches, key=os.path.getmtime)


def parse_orders_report(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) < 2:
        print(f"No data in {path}")
        sys.exit(1)

    header_row = next(
        (r for r in rows[:5] if any(str(c).strip() == "Sales Record Number" for c in r)),
        None,
    )
    if header_row is None:
        print(f"Could not find header row in {path}")
        sys.exit(1)
    headers = [str(h).strip() if h else "" for h in header_row]
    col = {h: i for i, h in enumerate(headers)}
    for required in ("Order Number", "Item Title", "Sale Date"):
        if required not in col:
            print(f"CSV missing required column: {required}")
            sys.exit(1)

    def get(r: list, name: str) -> str:
        i = col.get(name)
        if i is None or i >= len(r):
            return ""
        return r[i].strip()

    data_rows = [r for r in rows[rows.index(header_row) + 1:] if r and get(r, "Sales Record Number").isdigit()]

    by_order: dict = {}
    for r in data_rows:
        oid = get(r, "Order Number") or get(r, "Transaction ID") or f"CSV-{get(r, 'Sales Record Number')}"
        by_order.setdefault(oid, []).append(r)

    out: list[dict] = []
    for oid, group in by_order.items():
        if not oid:
            continue

        item_rows = [r for r in group if get(r, "Item Number")]

        if not item_rows:
            continue

        first_has_item = get(group[0], "Item Number") != ""

        if first_has_item:
            line_items = group
            order_rows = group
        else:
            line_items = item_rows
            order_rows = group[0:1]

        order_shipping = parse_money(get(order_rows[0], "Shipping And Handling")) if order_rows else 0.0
        order_total = parse_money(get(order_rows[0], "Total Price")) if order_rows else 0.0

        priced = sorted(line_items, key=lambda r: parse_money(get(r, "Sold For")), reverse=True)

        for i, r in enumerate(line_items):
            item_price = parse_money(get(r, "Sold For"))
            sale_date = parse_date(get(r, "Sale Date"))
            if not get(r, "Item Number") or not sale_date:
                continue
            is_top = r is priced[0]
            out.append({
                "Order ID":    oid,
                "Item ID":     get(r, "Item Number"),
                "Sale Date":   sale_date,
                "Buyer":       get(r, "Buyer Username"),
                "Item Title":  get(r, "Item Title"),
                "Quantity":    int(get(r, "Quantity") or 1),
                "Item Price":  item_price,
                "Shipping":    order_shipping if is_top else 0.0,
                "Order Total": order_total if is_top else 0.0,
                "SKU":         get(r, "Custom Label"),
            })

    return out


def main():
    parser = argparse.ArgumentParser(description="Import eBay Orders Report CSV into the sold orders workbook")
    parser.add_argument("--csv", type=str, default=None, help="Path to the eBay Orders Report CSV (default: newest in scripts/)")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="Output xlsx path")
    args = parser.parse_args()

    csv_path = args.csv or latest_report()
    print(f"Using report: {csv_path}")

    rows = parse_orders_report(csv_path)
    if not rows:
        print("No line items found in report")
        sys.exit(0)
    print(f"Parsed {len(rows)} line items from {csv_path}")

    token = get_access_token()
    min_date = min(r["Sale Date"] for r in rows)
    start_dt = datetime.strptime(min_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    new_count = append_rows_to_workbook(rows, args.output, start_dt, token)
    print(f"Imported {new_count} new orders ({len(rows) - new_count} skipped as duplicates)")


if __name__ == "__main__":
    main()
