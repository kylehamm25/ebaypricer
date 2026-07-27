import os
import sqlite3
from openpyxl import load_workbook
from dashboard.backend.config import EXCEL_PATH, DB_PATH_STR


def sync_excel(force: bool = False) -> dict:
    if not os.path.exists(EXCEL_PATH):
        return {"error": f"Excel file not found: {EXCEL_PATH}"}

    wb = load_workbook(EXCEL_PATH, read_only=True, data_only=True)
    conn = sqlite3.connect(DB_PATH_STR)
    result = {}

    sheet_table_map = {
        "Sold Orders": "staging_sold_orders",
        "Active Listings": "staging_active_listings",
    }

    for sheet_name, table_name in sheet_table_map.items():
        if sheet_name not in wb.sheetnames:
            result[sheet_name] = "sheet not found"
            continue

        ws = wb[sheet_name]
        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        headers = [h.strip() if h else f"col_{i}" for i, h in enumerate(headers)]
        col_defs = ", ".join(f'"{h}" TEXT' for h in headers)
        placeholders = ", ".join(f'"{h}"' for h in headers)

        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(f"CREATE TABLE {table_name} ({col_defs})")

        count = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if all(v is None for v in row):
                continue
            values = tuple(str(v) if v is not None else None for v in row)
            conn.execute(
                f"INSERT INTO {table_name} ({placeholders}) VALUES ({', '.join('?' for _ in headers)})",
                values,
            )
            count += 1

        conn.commit()
        result[sheet_name] = f"{count} rows synced"

    conn.close()
    wb.close()
    return result
