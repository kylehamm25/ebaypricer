"""
Usage:
    python append_sold_orders.py
    python append_sold_orders.py --output "path\to\file.xlsx"
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from sold_api import get_access_token, fetch_sold_orders
from get_sold_from_CSV import (
    fetch_finance_fees, merge_fees_into_rows, combine_orders,
)

_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(dotenv_path=_env_path)

CUTOFF = datetime(2026, 6, 29, tzinfo=timezone.utc)

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Arial", size=10)
DATA_FONT = Font(name="Arial", size=10)
SHADE_FILL = PatternFill("solid", fgColor="EBF3FB")
CURRENCY_COLS = {"Item Price", "Subtotal", "Shipping", "Order Total", "Total eBay Fees", "Order Earnings"}
INT_COLS = {"Quantity"}

DEFAULT_OUTPUT = r"H:\My Drive\ebay\ebay_sold_orders.xlsx"


def parse_args():
    parser = argparse.ArgumentParser(description="Append new eBay sold orders to existing Excel workbook")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="Output xlsx path")
    parser.add_argument("--days", type=int, default=0,
                        help="Fetch last N days (default 0 = use hardcoded cutoff 2026-06-29)")
    return parser.parse_args()


def read_header_cols(ws: Worksheet) -> dict[str, int]:
    """Return mapping of header name → 0-based column index from row 1."""
    col: dict[str, int] = {}
    for cell in ws[1]:
        if cell.value is not None:
            col[str(cell.value).strip()] = cell.column - 1
    return col


def get_existing_keys(ws: Worksheet) -> set[tuple[tuple[str, ...], str]]:
    """Build dedup key set of (sorted Item IDs, Sale Date) from existing rows."""
    col = read_header_cols(ws)
    date_idx = col.get("Sale Date", 2)
    iid_idx = col.get("Item ID", 1)
    last_data_row = find_last_data_row(ws)
    keys: set[tuple[tuple[str, ...], str]] = set()
    row_count = 0
    for row in ws.iter_rows(min_row=2, max_row=last_data_row, values_only=True):
        row_count += 1
        date = str(row[date_idx]).strip() if len(row) > date_idx and row[date_idx] is not None else ""
        iid_raw = str(row[iid_idx]).strip() if len(row) > iid_idx and row[iid_idx] is not None else ""
        item_ids = tuple(sorted(i.strip() for i in iid_raw.split("; ") if i.strip()))
        if item_ids:
            keys.add((item_ids, date))
    print(f"  Scanned {row_count} data rows ({len(keys)} unique keys, ws.max_row={ws.max_row})")
    return keys


def order_key(order: dict) -> tuple[tuple[str, ...], str]:
    iid_raw = order.get("Item ID", "")
    item_ids = tuple(sorted(i.strip() for i in iid_raw.split("; ") if i.strip()))
    date = order.get("Sale Date", "")
    return (item_ids, date)


def find_last_data_row(ws: Worksheet) -> int:
    for row in range(ws.max_row, 0, -1):
        cell = ws.cell(row=row, column=1)
        if cell.value is not None and str(cell.value).strip():
            return row
    return 1


def create_new_workbook(headers: list[str]) -> tuple[Workbook, Worksheet]:
    wb = Workbook()
    ws = wb.active
    if ws is None:
        ws = wb.create_sheet("Sold Orders", 0)
    ws.title = "Sold Orders"
    _write_headers(ws, headers)
    ws.freeze_panes = "A2"
    wb.create_sheet("Summary")
    return wb, ws


def _write_headers(ws: Worksheet, headers: list[str]) -> None:
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")


def write_data_rows(ws: Worksheet, rows: list[dict], start_row: int) -> None:
    headers = list(rows[0].keys()) if rows else []
    for row_idx, row in enumerate(rows, start_row):
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=row[h])
            cell.font = DATA_FONT
            cell.alignment = Alignment(vertical="center")
            if h in CURRENCY_COLS and row[h] is not None:
                cell.number_format = '#,##0.00'
            elif h in INT_COLS:
                cell.number_format = '0'
        if row_idx % 2 == 0:
            for col_idx in range(1, len(headers) + 1):
                shade = ws.cell(row=row_idx, column=col_idx)
                shade.fill = SHADE_FILL


def auto_column_widths(ws: Worksheet, headers: list[str], rows: list[dict]) -> None:
    for col_idx, h in enumerate(headers, 1):
        col_letter = get_column_letter(col_idx)
        max_len = max(
            len(str(h)),
            max((len(str(row.get(h, ""))) for row in rows), default=0),
        )
        ws.column_dimensions[col_letter].width = min(max_len + 4, 40)


def update_summary_sheet(wb: Workbook, headers: list[str], total_rows: int) -> None:
    if "Summary" in wb.sheetnames:
        ws_sum = wb["Summary"]
        for row in ws_sum.iter_rows():
            for cell in row:
                cell.value = None
    else:
        ws_sum = wb.create_sheet("Summary")

    if ws_sum is None:
        return

    ws_sum["A1"] = "Summary"
    ws_sum["A1"].font = Font(bold=True, name="Arial", size=12)

    col_letter = {h: get_column_letter(i) for i, h in enumerate(headers, 1)}

    if "Order ID" not in col_letter:
        return

    ws_sum["A3"] = "Total Transactions"
    ws_sum["B3"] = f"=COUNTA('Sold Orders'!{col_letter['Order ID']}2:{col_letter['Order ID']}{total_rows})"
    ws_sum["A4"] = "Total Revenue"
    ws_sum["B4"] = f"=SUM('Sold Orders'!{col_letter['Order Total']}2:{col_letter['Order Total']}{total_rows})"
    ws_sum["B4"].number_format = '#,##0.00'
    ws_sum["A5"] = "Total Shipping Collected"
    ws_sum["B5"] = f"=SUM('Sold Orders'!{col_letter['Shipping']}2:{col_letter['Shipping']}{total_rows})"
    ws_sum["B5"].number_format = '#,##0.00'

    next_row = 6
    if "Total eBay Fees" in col_letter:
        ws_sum[f"A{next_row}"] = "Total eBay Fees"
        ws_sum[f"B{next_row}"] = (
            f"=SUM('Sold Orders'!{col_letter['Total eBay Fees']}2:"
            f"{col_letter['Total eBay Fees']}{total_rows})"
        )
        ws_sum[f"B{next_row}"].number_format = '#,##0.00'
        next_row += 1
    if "Order Earnings" in col_letter:
        ws_sum[f"A{next_row}"] = "Total Order Earnings"
        ws_sum[f"B{next_row}"] = (
            f"=SUM('Sold Orders'!{col_letter['Order Earnings']}2:"
            f"{col_letter['Order Earnings']}{total_rows})"
        )
        ws_sum[f"B{next_row}"].number_format = '#,##0.00'
        next_row += 1

    ws_sum[f"A{next_row}"] = "Avg Order Value"
    ws_sum[f"B{next_row}"] = "=IF(B3=0,0,B4/B3)"
    ws_sum[f"B{next_row}"].number_format = '#,##0.00'

    for r in range(3, next_row + 1):
        ws_sum.cell(r, 1).font = Font(name="Arial", size=10, bold=True)
        ws_sum.cell(r, 2).font = Font(name="Arial", size=10)


def main():
    args = parse_args()
    now = datetime.now(timezone.utc)

    if args.days > 0:
        start_dt = now - timedelta(days=args.days)
        label = start_dt.strftime("%Y-%m-%d")
    else:
        start_dt = CUTOFF
        label = f"{CUTOFF.date()} (hardcoded)"

    print(f"Fetching orders after {label} -> {now.date()}")


    token = get_access_token()

    raw_rows = fetch_sold_orders(token, start_dt, now)
    print(f"  API returned {len(raw_rows)} line items")

    # Deduplicate by (Item ID, Sale Date) — same item can appear via Order
    # element and standalone Transaction with different Order IDs.
    # Prefer the entry with the real-looking Order ID (doesn't start with Item ID).
    seen: dict = {}
    deduped = []
    for r in raw_rows:
        key = (r["Item ID"], r.get("Sale Date", ""))
        if key not in seen:
            seen[key] = len(deduped)
            deduped.append(r)
        else:
            existing = deduped[seen[key]]
            existing_oid = existing.get("Order ID", "")
            candidate_oid = r.get("Order ID", "")
            # Prefer the one whose Order ID doesn't start with the Item ID
            # (real Order IDs have a different format than ItemID-TransactionID)
            if existing_oid.startswith(existing.get("Item ID", "")) and not candidate_oid.startswith(r.get("Item ID", "")):
                deduped[seen[key]] = r
    if len(deduped) < len(raw_rows):
        print(f"  Removed {len(raw_rows) - len(deduped)} duplicate line items")
    raw_rows = deduped

    if not raw_rows:
        print(f"No orders found after {label}.")
        sys.exit(0)


    fee_start = start_dt - timedelta(days=15)
    fees_by_order, item_id_index = fetch_finance_fees(token, fee_start, now)
    print(f"  Found fee data for {len(fees_by_order)} orders")
    merge_fees_into_rows(raw_rows, fees_by_order, item_id_index)

    combined = combine_orders(raw_rows)
    combined.sort(key=lambda r: r["Sale Date"], reverse=True)
    headers = list(combined[0].keys())

    xlsx_path = args.output
    existing_keys: set = set()
    
    fetched_keys = {order_key(r) for r in combined}

    if os.path.exists(xlsx_path):
        print(f"Loading existing workbook: {xlsx_path}")
        wb = load_workbook(xlsx_path)
        ws = wb["Sold Orders"]
        existing_keys = get_existing_keys(ws)
        total = len(existing_keys)
        overlapping = len(existing_keys & fetched_keys)
        print(f"  Orders in file before this fetch: {total} ({overlapping} overlap with current fetch)")
    else:
        existing_keys = set()
        print("No existing workbook found, creating new one")
        wb, ws = create_new_workbook(headers)

    new_orders = [r for r in combined if order_key(r) not in existing_keys]
    skipped = len(combined) - len(new_orders)

    if not new_orders:
        print(f"No new orders to append (skipped {skipped} duplicates).")
        sys.exit(0)

    if os.path.exists(xlsx_path):
        start_row = find_last_data_row(ws) + 1
    else:
        start_row = 2

    write_data_rows(ws, new_orders, start_row)
    total_rows = find_last_data_row(ws)
    auto_column_widths(ws, headers, combined)

    update_summary_sheet(wb, headers, total_rows)

    wb.save(xlsx_path)
    print(f"Appended {len(new_orders)} new order(s) (skipped {skipped} existing).")
    print(f"Saved -> {xlsx_path}")


if __name__ == "__main__":
    main()