import logging
import time
import requests
from ebaypricer.config import parse_args, load_cards, DB_PATH, LOOKBACK_DAYS
from ebaypricer.api import search_sold_listings
from ebaypricer.db import init_db, insert_listing, compute_snapshot
from ebaypricer.models import parse_item
from ebaypricer.report import print_report, export_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main():
    args = parse_args()
    cards = load_cards(args.txt)
    conn = init_db(DB_PATH)
    try:
        for card in cards:
            log.info(f" Pulling sold listings for: {card}")
            try:
                items = search_sold_listings(card, LOOKBACK_DAYS)
            except requests.HTTPError as e:
                log.error(f"eBay API error for '{card}': {e}")
                continue

            inserted = 0
            for raw in items:
                parsed = parse_item(raw, card)
                if not parsed:
                    continue
                if insert_listing(conn, parsed):
                    inserted += 1

            conn.commit()
            log.info(f" Inserted {inserted} new listings\n")
            compute_snapshot(conn, card, LOOKBACK_DAYS)
            time.sleep(1)

        print_report(conn)
        export_json(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
