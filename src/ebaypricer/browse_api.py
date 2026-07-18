from __future__ import annotations

import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev

import requests

from .auth import get_ebay_token

log = logging.getLogger(__name__)

OUTLIER_SIGMA = 2.0
LISTING_LIMIT = 50


def search_sold_listings(query: str, days_back: int = 30) -> list[dict]:
    token = get_ebay_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }

    date_from = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    params = {
        "q": f"{query} -PSA -BGS -CGC -SGC -graded -slab",
        "filter": f"buyingOptions:{{FIXED_PRICE|AUCTION}},soldDate:[{date_from}]",
        "sort": "newlyListed",
        "limit": str(LISTING_LIMIT),
    }

    resp = requests.get(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        headers=headers,
        params=params,
        timeout=15,
    )

    if resp.status_code == 429:
        log.warning("Rate limited — sleeping 60s before retry")
        time.sleep(60)
        return search_sold_listings(query, days_back)

    resp.raise_for_status()
    data = resp.json()
    return data.get("itemSummaries", [])


def parse_item(item: dict, card_query: str) -> dict | None:
    try:
        price_info = item.get("price", {})
        price = float(price_info.get("value", 0))
        if price <= 0:
            return None

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
            "condition":    item.get("condition", "UNKNOWN"),
            "listing_type": listing_type,
            "sold_date":    sold_date,
            "url":          item.get("itemWebUrl", ""),
            "pulled_at":    datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


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

        CREATE TABLE IF NOT EXISTS active_price_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            card_query      TEXT,
            snapshot_date   TEXT,
            sample_size     INTEGER,
            avg_price       REAL,
            min_price       REAL,
            max_price       REAL,
            UNIQUE(card_query, snapshot_date)
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


def compute_snapshot(conn: sqlite3.Connection, card_query: str, days_back: int = 30) -> dict | None:
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
        return None

    recent_cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

    pairs: list[tuple[float, str]] = [(price, sold_date) for price, _, sold_date in rows]

    if len(pairs) >= 4:
        raw_prices = [p for p, _ in pairs]
        m, s = mean(raw_prices), stdev(raw_prices)
        pairs = [(p, d) for p, d in pairs if abs(p - m) <= OUTLIER_SIGMA * s]

    if not pairs:
        return None

    prices = [p for p, _ in pairs]
    weighted_sum = 0.0
    weight_total = 0
    for p, sold_date in pairs:
        w = 2 if sold_date >= recent_cutoff else 1
        weighted_sum += p * w
        weight_total += w

    sorted_p = sorted(prices)
    n = len(sorted_p)
    median = sorted_p[n // 2] if n % 2 else (sorted_p[n // 2 - 1] + sorted_p[n // 2]) / 2

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
    return snapshot


def search_active_listings(query: str, limit: int = 5) -> list[dict]:
    token = get_ebay_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }

    params = {
        "q": f"{query} -PSA -BGS -CGC -SGC -graded -slab",
        "filter": "buyingOptions:{FIXED_PRICE|AUCTION}",
        "sort": "bestMatch",
        "limit": str(limit),
    }

    resp = requests.get(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        headers=headers,
        params=params,
        timeout=15,
    )

    if resp.status_code == 429:
        log.warning("Rate limited — sleeping 60s before retry")
        time.sleep(60)
        return search_active_listings(query, limit)

    resp.raise_for_status()
    data = resp.json()
    return data.get("itemSummaries", [])


def parse_active_item(item: dict, card_query: str) -> dict | None:
    try:
        price_info = item.get("price", {})
        price = float(price_info.get("value", 0))
        if price <= 0:
            return None

        buying_options = item.get("buyingOptions", [])
        if "FIXED_PRICE" in buying_options:
            listing_type = "BIN"
        elif "AUCTION" in buying_options:
            listing_type = "Auction"
        else:
            listing_type = "Unknown"

        return {
            "item_id":      item.get("itemId", ""),
            "card_query":   card_query,
            "title":        item.get("title", ""),
            "price":        price,
            "currency":     price_info.get("currency", "USD"),
            "condition":    item.get("condition", "UNKNOWN"),
            "listing_type": listing_type,
            "url":          item.get("itemWebUrl", ""),
            "pulled_at":    datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def get_today_active_snapshot(conn: sqlite3.Connection, card_query: str) -> dict | None:
    today = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        """
        SELECT sample_size, avg_price, min_price, max_price
        FROM active_price_snapshots
        WHERE card_query = ? AND snapshot_date = ?
        """,
        (card_query, today),
    ).fetchone()
    if not row:
        return None
    return {
        "card_query":    card_query,
        "snapshot_date": today,
        "sample_size":   row[0],
        "avg_price":     row[1],
        "min_price":     row[2],
        "max_price":     row[3],
    }


def save_active_snapshot(conn: sqlite3.Connection, snapshot: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO active_price_snapshots
            (card_query, snapshot_date, sample_size, avg_price, min_price, max_price)
        VALUES
            (:card_query, :snapshot_date, :sample_size, :avg_price, :min_price, :max_price)
        """,
        snapshot,
    )
    conn.commit()


def get_today_snapshot(conn: sqlite3.Connection, card_query: str) -> dict | None:
    today = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        """
        SELECT sample_size, avg_price, median_price, min_price, max_price, std_dev, weighted_avg
        FROM price_snapshots
        WHERE card_query = ? AND snapshot_date = ?
        """,
        (card_query, today),
    ).fetchone()
    if not row:
        return None
    return {
        "card_query":    card_query,
        "snapshot_date": today,
        "sample_size":   row[0],
        "avg_price":     row[1],
        "median_price":  row[2],
        "min_price":     row[3],
        "max_price":     row[4],
        "std_dev":       row[5],
        "weighted_avg":  row[6],
    }
