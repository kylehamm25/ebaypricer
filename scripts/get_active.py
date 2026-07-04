import argparse
import os
from datetime import datetime, timezone

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ebaypricer.auth import get_access_token
from ebaypricer.trading_api import fetch_active_listings
from ebaypricer.cards import enrich_rows
from ebaypricer.excel import (
    HEADER_FILL, HEADER_FONT, DATA_FONT, SHADE_FILL,
    ACTIVE_CURRENCY_COLS, ACTIVE_INT_COLS, write_headers,
)

SHEET_NAME = "Active Listings"

DEFAULT_OUTPUT = r"H:\My Drive\ebay\ebay_sold_orders.xlsx"


def parse_args():
    parser = argparse.ArgumentParser(description="Refresh Active Listings sheet with current eBay listings")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="Output xlsx path")
    return parser.parse_args()


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
            if h in ACTIVE_CURRENCY_COLS and row.get(h) is not None:
                cell.number_format = '#,##0.00'
            elif h in ACTIVE_INT_COLS:
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

    xlsx_path = args.output

    ws = None
    existing_widths: dict[str, float] = {}
    existing_cards: dict[str, str] = {}
    if os.path.exists(xlsx_path):
        wb = load_workbook(xlsx_path)
        if SHEET_NAME in wb.sheetnames:
            ws = wb[SHEET_NAME]
            col_to_idx = {str(cell.value): i for i, cell in enumerate(ws[1]) if cell.value}
            card_col = col_to_idx.get("Card", -1)
            itemid_col = col_to_idx.get("Item ID", -1)
            if card_col >= 0 and itemid_col >= 0:
                for row in ws.iter_rows(min_row=2, values_only=True):
                    item_id = str(row[itemid_col]).strip() if len(row) > itemid_col and row[itemid_col] else ""
                    card_val = str(row[card_col]).strip() if len(row) > card_col and row[card_col] else ""
                    if item_id and card_val:
                        existing_cards[item_id] = card_val
            for col_letter, dim in ws.column_dimensions.items():
                if dim.width is not None:
                    existing_widths[col_letter] = dim.width
    else:
        wb = Workbook()
        default_ws = wb.active
        if default_ws is not None:
            wb.remove(default_ws)

    token = get_access_token()

    rows = fetch_active_listings(token)

    if not rows:
        print("No active listings returned — leaving existing sheet untouched.")
        return

    print("  Enriching with Pokémon card data ...")
    enrich_rows(rows, title_key="Title")

    if existing_cards:
        preserved = 0
        for row in rows:
            item_id = row.get("Item ID", "")
            card = existing_cards.get(item_id)
            if card:
                row["Card"] = card
                preserved += 1
        if preserved:
            print(f"  Preserved {preserved} existing Card value(s)")

    rows.sort(key=lambda r: r.get("Days Listed", 0), reverse=True)
    headers = list(rows[0].keys())

    if ws is None:
        ws = wb.create_sheet(SHEET_NAME)
    _clear_sheet(ws)

    write_headers(ws, headers)
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
