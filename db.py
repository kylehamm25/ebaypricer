import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev
from config import DB_PATH, LOOKBACK_DAYS, OUTLIER_SIGMA

log = logging.getLogger(__name__)


def init_db(path: str = DB_PATH) -> sqlite3.Connection:
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


def insert_listing(conn: sqlite3.Connection, parsed: dict) -> bool:
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
        return True
    except sqlite3.Error as e:
        log.debug(f"DB insert error: {e}")
        return False


def compute_snapshot(conn: sqlite3.Connection, card_query: str, days_back: int = LOOKBACK_DAYS):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
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
        log.warning(f"  No data for '{card_query}' — skipping snapshot.")
        return

    recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

    pairs: list[tuple[float, str]] = []
    for price, listing_type, sold_date in rows:
        pairs.append((price, sold_date))

    if len(pairs) >= 4:
        raw_prices = [p for p, _ in pairs]
        m, s = mean(raw_prices), stdev(raw_prices)
        pairs = [(p, d) for p, d in pairs if abs(p - m) <= OUTLIER_SIGMA * s]

    if not pairs:
        log.warning(f"  All prices for '{card_query}' were outliers — skipping.")
        return

    prices = [p for p, _ in pairs]
    weighted_sum = 0.0
    weight_total = 0
    for p, sold_date in pairs:
        w = 2 if sold_date >= recent_cutoff else 1
        weighted_sum += p * w
        weight_total += w

    sorted_p = sorted(prices)
    n = len(sorted_p)
    median = sorted_p[n // 2] if n % 2 else (sorted_p[n//2 - 1] + sorted_p[n//2]) / 2

    snapshot = {
        "card_query":    card_query,
        "snapshot_date": datetime.now(timezone.utc).date().isoformat(),
        "sample_size":   n,
        "avg_price":     round(mean(prices), 2),
        "median_price":  round(median, 2),
        "min_price":     round(min(prices), 2),
        "max_price":     round(max(prices), 2),
        "std_dev":       round(stdev(prices), 2) if n > 1 else 0.0,
        "weighted_avg":  round(weighted_sum / weight_total, 2),
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


def get_today_snapshots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    today = datetime.now(timezone.utc).date().isoformat()
    return conn.execute(
        """
        SELECT card_query, weighted_avg, median_price, avg_price,
               min_price, max_price, sample_size
        FROM price_snapshots
        WHERE snapshot_date = ?
        ORDER BY weighted_avg DESC
        """,
        (today,),
    ).fetchall()


def get_today_snapshots_full(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    today = datetime.now(timezone.utc).date().isoformat()
    return conn.execute(
        "SELECT card_query, snapshot_date, sample_size, avg_price, median_price, "
        "min_price, max_price, std_dev, weighted_avg FROM price_snapshots WHERE snapshot_date = ?",
        (today,)
    ).fetchall()
