import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_DIR = os.path.join(PROJECT_ROOT, "db")
DB_PATH = os.path.join(DB_DIR, "pokemon_prices.db")
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

CACHE_FILE = os.path.join(DATA_DIR, "cards_cache.json")
PRICING_CACHE = os.path.join(DATA_DIR, "pricing_cache.json")
TCGDEX_SET_MAP = os.path.join(DATA_DIR, "tcgdex_set_map.json")
