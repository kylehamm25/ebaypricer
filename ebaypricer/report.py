import json
import sqlite3
from .db import get_today_snapshots, get_today_snapshots_full


def print_report(conn: sqlite3.Connection):
    rows = get_today_snapshots(conn)
    if not rows:
        print("No snapshots for today yet.")
        return

    print(f"{'Card':<35} {'Wtd Avg':>8} {'Median':>8} {'Avg':>8} {'Min':>8} {'Max':>8} {'n':>4}")
    print(f"{'-'*87}")
    for card, w_avg, median, avg, mn, mx, n in rows:
        name = card[:34]
        print(f"{name:<35} {w_avg:>8.2f} {median:>8.2f} {avg:>8.2f} {mn:>8.2f} {mx:>8.2f} {n:>4}")
    print(f"{'-'*87}\n")


def export_json(conn: sqlite3.Connection, path: str = "price_report.json"):
    rows = get_today_snapshots_full(conn)
    cols = ["card_query", "snapshot_date", "sample_size", "avg_price", "median_price",
            "min_price", "max_price", "std_dev", "weighted_avg"]
    data = [dict(zip(cols, row)) for row in rows]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
