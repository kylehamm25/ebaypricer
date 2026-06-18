import os
import sqlite3
import requests
import json
import time
import logging
from datetime import datetime, timedelta
from statistics import mean, stdev
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Config
EBAY_APP_ID   = os.getenv("EBAY_APP_ID")       # Client ID from eBay Developer portal
EBAY_SECRET   = os.getenv("EBAY_SECRET")       # Client Secret from eBay Developer portal
DB_PATH       = os.getenv("DB_PATH", "pokemon_prices.db")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 30))   # How far back to pull sold data
OUTLIER_SIGMA = float(os.getenv("OUTLIER_SIGMA", 2.0)) # Std-dev threshold for outlier removal

# Cards to track
CARDS_TO_TRACK = [
    "Charizard Base Set Holo",
    "Pikachu Illustrator",
    "Lugia Neo Genesis Holo",
    "Blastoise Base Set Holo",
    "Mewtwo Base Set Holo",
]

# ── OAuth token ───────────────────────────────────────────────────────────────
_token_cache: dict = {}

def get_ebay_token() -> str:
    """Fetches (and caches) an eBay OAuth application token."""
    if _token_cache.get("expires_at", 0) > time.time() + 60:
        return _token_cache["token"]

    if not EBAY_APP_ID or not EBAY_SECRET:
        raise ValueError(
            "Missing EBAY_APP_ID or EBAY_SECRET. "
            "Copy .env.example to .env and fill in your credentials."
        )

    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        auth=(EBAY_APP_ID, EBAY_SECRET),
        data={"grant_type": "client_credentials",
              "scope": "https://api.ebay.com/oauth/api_scope"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + int(data["expires_in"])
    log.info("eBay OAuth token refreshed.")
    return _token_cache["token"]


# ── Database ──────────────────────────────────────────────────────────────────
def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sold_listings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id       TEXT UNIQUE,
            card_query    TEXT,
            title         TEXT,
            price         REAL,
            currency      TEXT,
            condition     TEXT,
            listing_type  TEXT,
            sold_date     TEXT,
            url           TEXT,
            pulled_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS price_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            card_query      TEXT,
            snapshot_date   TEXT,
            sample_size     INTEGER,
            avg_price       REAL,
            median_price    REAL,
            min_price       REAL,
            max_price       REAL,
            std_dev         REAL,
            weighted_avg    REAL,
            UNIQUE(card_query, snapshot_date)
        );
    """)
    conn.commit()
    return conn


# ── eBay Search ───────────────────────────────────────────────────────────────
def search_sold_listings(query: str, days_back: int = 30) -> list[dict]:
    """
    Uses eBay Browse API (search endpoint) with filter for sold items.
    Returns a list of raw item dicts.
    """
    token = get_ebay_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }

    date_from = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    params = {
        "q": f"{query} pokemon card",
        "category_ids": "2536",  # Pokémon Individual Cards category
        "filter": f"buyingOptions:{{FIXED_PRICE|AUCTION}},soldDate:[{date_from}]",
        "sort": "newlyListed",
        "limit": "200",
    }

    all_items = []
    offset = 0

    while True:
        params["offset"] = str(offset)
        resp = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers=headers,
            params=params,
            timeout=15,
        )

        if resp.status_code == 429:
            log.warning("Rate limited — sleeping 60s")
            time.sleep(60)
            continue

        resp.raise_for_status()
        data = resp.json()
        items = data.get("itemSummaries", [])
        all_items.extend(items)

        total = int(data.get("total", 0))
        offset += len(items)
        if offset >= total or not items:
            break

        time.sleep(0.5)  # polite delay between pages

    log.info(f"  '{query}' → {len(all_items)} sold listings found")
    return all_items


# ── Parsing & Cleaning ────────────────────────────────────────────────────────
CONDITION_MAP = {
    "NEW": "New",
    "LIKE_NEW": "NM",
    "EXCELLENT": "LP",
    "VERY_GOOD": "MP",
    "GOOD": "HP",
    "ACCEPTABLE": "DMG",
    "FOR_PARTS_OR_NOT_WORKING": "DMG",
}

def parse_item(item: dict, card_query: str) -> dict | None:
    """Extract and normalise fields from a raw eBay item dict."""
    try:
        price_info = item.get("price", {})
        price = float(price_info.get("value", 0))
        if price <= 0:
            return None

        raw_condition = item.get("condition", "UNKNOWN")
        condition = CONDITION_MAP.get(raw_condition.upper(), raw_condition)

        buying_options = item.get("buyingOptions", [])
        if "FIXED_PRICE" in buying_options:
            listing_type = "BIN"
        elif "AUCTION" in buying_options:
            listing_type = "Auction"
        else:
            listing_type = "Unknown"

        sold_date = item.get("itemEndDate") or item.get("itemCreationDate", "")

        return {
            "item_id":      item.get("itemId", ""),
            "card_query":   card_query,
            "title":        item.get("title", ""),
            "price":        price,
            "currency":     price_info.get("currency", "USD"),
            "condition":    condition,
            "listing_type": listing_type,
            "sold_date":    sold_date,
            "url":          item.get("itemWebUrl", ""),
            "pulled_at":    datetime.utcnow().isoformat(),
        }
    except Exception as e:
        log.debug(f"Skipping item due to parse error: {e}")
        return None


def remove_outliers(prices: list[float], sigma: float = 2.0) -> list[float]:
    """Remove prices more than `sigma` standard deviations from the mean."""
    if len(prices) < 4:
        return prices
    m, s = mean(prices), stdev(prices)
    return [p for p in prices if abs(p - m) <= sigma * s]


# ── Pricing Model ─────────────────────────────────────────────────────────────
def compute_snapshot(conn: sqlite3.Connection, card_query: str, days_back: int = 30):
    """
    Reads stored sold listings for a card and writes a price snapshot.
    Applies recency weighting: sales in last 14 days count 2×.
    """
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
    rows = conn.execute(
        """
        SELECT price, listing_type, sold_date
        FROM sold_listings
        WHERE card_query = ?
          AND sold_date >= ?
          AND currency = 'USD'
        ORDER BY sold_date DESC
        """,
        (card_query, cutoff),
    ).fetchall()

    if not rows:
        log.warning(f"No data for '{card_query}' — skipping snapshot.")
        return

    # BIN prices are typically closer to "fair value" than auctions
    # Apply a small uplift to auction prices when mixing
    prices = []
    weighted = []
    recent_cutoff = (datetime.utcnow() - timedelta(days=14)).isoformat()

    for price, listing_type, sold_date in rows:
        adj_price = price * 1.12 if listing_type == "Auction" else price
        prices.append(adj_price)
        weight = 2 if sold_date >= recent_cutoff else 1
        weighted.extend([adj_price] * weight)

    prices  = remove_outliers(prices, OUTLIER_SIGMA)
    weighted = remove_outliers(weighted, OUTLIER_SIGMA)

    if not prices:
        log.warning(f"All prices for '{card_query}' were outliers — skipping.")
        return

    sorted_p = sorted(prices)
    n = len(sorted_p)
    median = sorted_p[n // 2] if n % 2 else (sorted_p[n//2 - 1] + sorted_p[n//2]) / 2

    snapshot = {
        "card_query":    card_query,
        "snapshot_date": datetime.utcnow().date().isoformat(),
        "sample_size":   n,
        "avg_price":     round(mean(prices), 2),
        "median_price":  round(median, 2),
        "min_price":     round(min(prices), 2),
        "max_price":     round(max(prices), 2),
        "std_dev":       round(stdev(prices), 2) if n > 1 else 0.0,
        "weighted_avg":  round(mean(weighted), 2),
    }

    conn.execute(
        """
        INSERT OR REPLACE INTO price_snapshots
            (card_query, snapshot_date, sample_size, avg_price, median_price,
             min_price, max_price, std_dev, weighted_avg)
        VALUES
            (:card_query, :snapshot_date, :sample_size, :avg_price, :median_price,
             :min_price, :max_price, :std_dev, :weighted_avg)
        """,
        snapshot,
    )
    conn.commit()
    log.info(
        f"  Snapshot → {card_query}: "
        f"weighted_avg=${snapshot['weighted_avg']:.2f}  "
        f"median=${snapshot['median_price']:.2f}  "
        f"n={n}"
    )


# ── Report ────────────────────────────────────────────────────────────────────
def print_report(conn: sqlite3.Connection):
    """Print a simple pricing summary table to stdout."""
    today = datetime.utcnow().date().isoformat()
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

    print(f"\n{'='*80}")
    print(f"  Pokémon Card Price Report  —  {today}")
    print(f"{'='*80}")
    print(f"{'Card':<35} {'Wtd Avg':>9} {'Median':>9} {'Avg':>9} {'Min':>7} {'Max':>7} {'n':>4}")
    print(f"{'-'*80}")
    for card, w_avg, median, avg, mn, mx, n in rows:
        name = card[:34]
        print(f"{name:<35} ${w_avg:>8.2f} ${median:>8.2f} ${avg:>8.2f} ${mn:>6.2f} ${mx:>6.2f} {n:>4}")
    print(f"{'='*80}\n")


def export_json(conn: sqlite3.Connection, path: str = "price_report.json"):
    """Export today's snapshots to JSON for use in other tools."""
    today = datetime.utcnow().date().isoformat()
    rows = conn.execute(
        "SELECT * FROM price_snapshots WHERE snapshot_date = ?", (today,)
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM price_snapshots LIMIT 0").description]
    data = [dict(zip(cols, row)) for row in rows]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"Exported {len(data)} snapshots → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    conn = init_db(DB_PATH)
    log.info(f"Database: {DB_PATH}")

    for card in CARDS_TO_TRACK:
        log.info(f"Pulling sold listings for: {card}")
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
            except sqlite3.Error as e:
                log.debug(f"DB insert error: {e}")

        conn.commit()
        log.info(f"  Inserted {inserted} new listings.")
        compute_snapshot(conn, card, LOOKBACK_DAYS)
        time.sleep(1)  # be kind to the API

    print_report(conn)
    export_json(conn)
    conn.close()


if __name__ == "__main__":
    main()