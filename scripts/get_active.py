"""
Usage:
    python update_active_listings.py
    python update_active_listings.py --output "path\to\file.xlsx"

Fetches all currently-active eBay listings and fully refreshes the
"Active Listings" sheet in the workbook (does NOT touch "Sold Orders"
or "Summary"). Unlike the sold-orders script, this is a full replace
each run, not an append — active listings change price/quantity or
disappear when they sell or end, so a stale append-log doesn't make
sense here.
"""

import argparse
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from sold_api import get_access_token, fetch_active_listings

_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(dotenv_path=_env_path)

SHEET_NAME = "Active Listings"

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Arial", size=10)
DATA_FONT = Font(name="Arial", size=10)
SHADE_FILL = PatternFill("solid", fgColor="EBF3FB")
CURRENCY_COLS = {"Price"}
INT_COLS = {"Quantity", "Days Listed", "Watchers"}

DEFAULT_OUTPUT = r"H:\My Drive\ebay\ebay_sold_orders.xlsx"


def parse_args():
    parser = argparse.ArgumentParser(description="Refresh Active Listings sheet with current eBay listings")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="Output xlsx path")
    return parser.parse_args()


def _write_headers(ws: Worksheet, headers: list[str]) -> None:
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _clear_sheet(ws: Worksheet) -> None:
    if ws.max_row > 0:
        ws.delete_rows(1, ws.max_row)


def write_data_rows(ws: Worksheet, rows: list[dict], headers: list[str], start_row: int = 2) -> None:
    for row_idx, row in enumerate(rows, start_row):
        for col_idx, h in enumerate(headers, 1):
            val = row.get(h)
            if h == "Link" and val:
                val = f'=HYPERLINK("{val}", "link")'
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = DATA_FONT
            cell.alignment = Alignment(vertical="center")
            if h in CURRENCY_COLS and row.get(h) is not None:
                cell.number_format = '#,##0.00'
            elif h in INT_COLS:
                cell.number_format = '0'
        if row_idx % 2 == 0:
            for col_idx in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col_idx).fill = SHADE_FILL


def auto_column_widths(ws: Worksheet, headers: list[str], rows: list[dict]) -> None:
    for col_idx, h in enumerate(headers, 1):
        col_letter = get_column_letter(col_idx)
        max_len = max(
            len(str(h)),
            max((len(str(row.get(h, ""))) for row in rows), default=0),
        )
        ws.column_dimensions[col_letter].width = min(max_len + 4, 45)


def write_last_updated(ws: Worksheet, headers: list[str], now: datetime) -> None:
    note_col = len(headers) + 2
    cell = ws.cell(row=1, column=note_col, value=f"Last updated: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    cell.font = Font(italic=True, name="Arial", size=9, color="808080")


def main():
    args = parse_args()
    now = datetime.now(timezone.utc)

    token = get_access_token()

    rows = fetch_active_listings(token)

    if not rows:
        print("No active listings returned — leaving existing sheet untouched.")
        return

    rows.sort(key=lambda r: r.get("Days Listed", 0), reverse=True)
    headers = list(rows[0].keys())

    xlsx_path = args.output

    if os.path.exists(xlsx_path):
        wb = load_workbook(xlsx_path)
    else:
        wb = Workbook()
        default_ws = wb.active
        if default_ws is not None:
            wb.remove(default_ws)

    existing_widths: dict[str, float] = {}
    if SHEET_NAME in wb.sheetnames:
        ws = wb[SHEET_NAME]
        for col_letter, dim in ws.column_dimensions.items():
            if dim.width is not None:
                existing_widths[col_letter] = dim.width
        _clear_sheet(ws)
    else:
        ws = wb.create_sheet(SHEET_NAME)

    _write_headers(ws, headers)
    ws.freeze_panes = "A2"
    write_data_rows(ws, rows, headers)

    if existing_widths:
        for col_idx, h in enumerate(headers, 1):
            col_letter = get_column_letter(col_idx)
            if col_letter in existing_widths:
                ws.column_dimensions[col_letter].width = existing_widths[col_letter]
            else:
                max_len = max(
                    len(str(h)),
                    max((len(str(row.get(h, ""))) for row in rows), default=0),
                )
                ws.column_dimensions[col_letter].width = min(max_len + 4, 45)
    else:
        auto_column_widths(ws, headers, rows)

    write_last_updated(ws, headers, now)

    wb.save(xlsx_path)
    print(f"Active Listings refreshed — {len(rows)} listings")


if __name__ == "__main__":
    main()