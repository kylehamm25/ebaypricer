import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

from ebaypricer.browse_api import (
    compute_snapshot,
    init_db,
    parse_item,
    search_sold_listings,
)
from ebaypricer.paths import DB_PATH as DEFAULT_DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

LOOKBACK_DAYS = 150


def parse_args():
    parser = argparse.ArgumentParser(description="Pull eBay sold prices for Pokémon cards.")
    parser.add_argument("txt", nargs="?", default="cards_to_track.txt",
                        help="Path to a .txt file with one card name per line")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH,
                        help="Path to SQLite database")
    return parser.parse_args()


def print_report(conn):
    today = datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        """
        SELECT card_query, weighted_avg, median_price, avg_price,
               min_price, max_price, sample_size
        FROM price_snapshots
        WHERE snapshot_date = ?
        ORDER BY weighted_avg DESC
        """,
        (today,),
    ).fetchall()

    if not rows:
        print("No snapshots for today yet.")
        return

    print(f"{'Card':<35} {'Wtd Avg':>8} {'Median':>8} {'Avg':>8} {'Min':>8} {'Max':>8} {'n':>4}")
    print(f"{'-'*87}")
    for card, w_avg, median, avg, mn, mx, n in rows:
        print(f"{card[:34]:<35} {w_avg:>8.2f} {median:>8.2f} {avg:>8.2f} {mn:>8.2f} {mx:>8.2f} {n:>4}")
    print(f"{'-'*87}\n")


def export_json(conn, path="price_report.json"):
    today = datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        "SELECT card_query, snapshot_date, sample_size, avg_price, median_price, "
        "min_price, max_price, std_dev, weighted_avg FROM price_snapshots WHERE snapshot_date = ?",
        (today,)
    ).fetchall()
    cols = ["card_query", "snapshot_date", "sample_size", "avg_price", "median_price",
            "min_price", "max_price", "std_dev", "weighted_avg"]
    data = [dict(zip(cols, row)) for row in rows]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    args = parse_args()
    db_path = args.db

    with open(args.txt) as f:
        cards_to_track = [line.strip() for line in f if line.strip()]

    if not cards_to_track:
        log.warning("No card names found in %s", args.txt)
        return

    conn = init_db(db_path)
    try:
        for card in cards_to_track:
            log.info(" Pulling sold listings for: %s", card)
            try:
                items = search_sold_listings(card, LOOKBACK_DAYS)
            except requests.HTTPError as e:
                log.error("eBay API error for '%s': %s", card, e)
                continue

            inserted = 0
            for raw in items:
                parsed = parse_item(raw, card)
                if not parsed:
                    continue
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO sold_listings
                            (item_id, card_query, title, price, currency, condition,
                             listing_type, sold_date, url, pulled_at)
                        VALUES
                            (:item_id, :card_query, :title, :price, :currency, :condition,
                             :listing_type, :sold_date, :url, :pulled_at)
                        """,
                        parsed,
                    )
                    inserted += 1
                except Exception:
                    pass

            conn.commit()
            log.info(" Inserted %d new listings\n", inserted)
            compute_snapshot(conn, card, LOOKBACK_DAYS)
            time.sleep(1)

        print_report(conn)
        export_json(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
