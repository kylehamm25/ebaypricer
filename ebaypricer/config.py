import os
import argparse
from dotenv import load_dotenv

load_dotenv(override=True)

EBAY_APP_ID = os.getenv("EBAY_APP_ID")
EBAY_SECRET = os.getenv("EBAY_SECRET")
DB_PATH     = os.getenv("DB_PATH", "data/pokemon_prices.db")
LOOKBACK_DAYS = 150
OUTLIER_SIGMA = 2.0
LISTING_LIMIT = 50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull eBay sold prices for Pokémon cards.")
    parser.add_argument("txt", nargs="?", default="data/cards_to_track.txt",
                        help="Path to a .txt file with one card name per line")
    return parser.parse_args()


def load_cards(path: str) -> list[str]:
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]
