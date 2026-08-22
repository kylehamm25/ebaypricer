from __future__ import annotations

import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev

from urllib.parse import urlencode

import requests

from .auth import get_ebay_token

log = logging.getLogger(__name__)

OUTLIER_SIGMA = 2.0
LISTING_LIMIT = 50
MAX_QUERY_WORDS = 5
MAX_RATE_LIMIT_RETRIES = 3

# Search configuration — toggle listing formats and graded exclusions here.
# BUYING_OPTIONS: "FIXED_PRICE" (Buy It Now), "AUCTION", or both "FIXED_PRICE|AUCTION"
BUYING_OPTIONS = "FIXED_PRICE"
# EXCLUDED_TERMS: space-separated negative keywords appended to every query.
# The lot/bundle terms free up result slots that were being spent on multi-card
# listings, which are never a comp for a single card. Verified against this seller's
# own titles first: none contain any of these words, so they cannot hide our own
# listing from the search-position lookup, which shares this function.
EXCLUDED_TERMS = "-PSA -BGS -CGC -SGC -graded -slab -lot -bundle -playset -proxy -reprint"

# eBay US leaf category for single trading cards ("CCG Individual Cards", under
# Toys & Hobbies > Collectible Card Games). Verified empirically rather than assumed:
# 49 of 50 results across two real card queries carry it, the one exception being a
# non-sport card that was itself a mismatch. Constraining the search here is cheaper
# and more reliable than filtering sealed product, supplies and other games out of the
# results afterwards. Server-side filtering costs no extra API calls.
CARD_CATEGORY_ID = "183454"


def _build_query(query: str) -> str:
    words = query.split()
    if len(words) > MAX_QUERY_WORDS:
        query = " ".join(words[:MAX_QUERY_WORDS])
    return f"{query} {EXCLUDED_TERMS}".strip()


def web_search_url(query: str) -> str:
    """The same search, as a link a person can open.

    Mirrors what search_active_listings() asks the API for - identical truncated query,
    identical negative keywords, same category, same Buy It Now restriction - so clicking
    through shows the pool the comps were actually drawn from. Built here, beside those
    constants, because a copy in the frontend would quietly stop matching the moment any
    of them changed.
    """
    params = {"_nkw": _build_query(query), "_sacat": CARD_CATEGORY_ID}
    # LH_BIN is the web equivalent of buyingOptions:{FIXED_PRICE}; only correct while
    # that is what we actually filter on.
    if BUYING_OPTIONS == "FIXED_PRICE":
        params["LH_BIN"] = "1"
    return "https://www.ebay.com/sch/i.html?" + urlencode(params)


def _buying_options_filter() -> str:
    return f"buyingOptions:{{{BUYING_OPTIONS}}}"


# NOTE: there used to be a search_sold_listings()/parse_item() pair here that called
# eBay's Browse API (buy/browse/v1/item_summary/search) with a "soldDate:[...]" filter
# to try to search sold/completed items. That filter isn't a real Browse API filter -
# eBay silently ignores it and returns ordinary ACTIVE listings (verified: identical
# item IDs to a plain active search, live buyingOptions present, no soldDate/
# itemEndDate field in the response). The Browse API only ever searches currently
# active listings; there is no "sold" search on it. Real sold comps require eBay's
# Marketplace Insights API (restricted-access, requires separate approval) - until
# that's available, sold/market pricing comes from ebaypricer.cards.lookup_market_price
# (TCGdex/TCGPlayer) instead. Don't recreate a "sold" search against this endpoint.


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

        CREATE TABLE IF NOT EXISTS listing_positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id         TEXT,
            card_query      TEXT,
            snapshot_date   TEXT,
            position        INTEGER,
            search_size     INTEGER,
            UNIQUE(item_id, snapshot_date)
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


def search_active_listings(query: str, limit: int = 5, offset: int = 0, _retries: int = 0) -> list[dict]:
    token = get_ebay_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }

    params = {
        "q": _build_query(query),
        "filter": _buying_options_filter(),
        "category_ids": CARD_CATEGORY_ID,
        "limit": str(limit),
        "offset": str(offset),
    }

    resp = requests.get(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        headers=headers,
        params=params,
        timeout=15,
    )

    if resp.status_code == 429:
        if _retries >= MAX_RATE_LIMIT_RETRIES:
            resp.raise_for_status()
        log.warning("Rate limited — sleeping 60s before retry (%d/%d)", _retries + 1, MAX_RATE_LIMIT_RETRIES)
        time.sleep(60)
        return search_active_listings(query, limit, offset, _retries=_retries + 1)

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

        # shippingOptions is part of the default item_summary/search response (no
        # fieldgroups needed), but eBay estimates it against a default ship-to
        # location rather than a specific buyer, and can omit it entirely - so this
        # is a directional cost, not a guaranteed exact one. Only the first/cheapest
        # option is kept, matching how the item is actually surfaced in search.
        shipping_options = item.get("shippingOptions") or []
        first_shipping = shipping_options[0] if shipping_options else {}
        shipping_cost_info = first_shipping.get("shippingCost") or {}
        shipping_cost = shipping_cost_info.get("value")

        return {
            "item_id":            item.get("itemId", ""),
            "card_query":         card_query,
            "title":              item.get("title", ""),
            "price":              price,
            "currency":           price_info.get("currency", "USD"),
            "condition":          item.get("condition", "UNKNOWN"),
            "listing_type":       listing_type,
            "url":                item.get("itemWebUrl", ""),
            "shipping_cost":      float(shipping_cost) if shipping_cost is not None else None,
            "shipping_cost_type": first_shipping.get("shippingCostType", ""),
            "pulled_at":          datetime.now(timezone.utc).isoformat(),
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


def get_today_listing_positions(
    conn: sqlite3.Connection, card_query: str
) -> dict[str, tuple[int, int]] | None:
    today = datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        """
        SELECT item_id, position, search_size
        FROM listing_positions
        WHERE card_query = ? AND snapshot_date = ?
        """,
        (card_query, today),
    ).fetchall()
    if not rows:
        return None
    return {item_id: (position, search_size) for item_id, position, search_size in rows}


def save_listing_positions(
    conn: sqlite3.Connection,
    card_query: str,
    positions: dict[str, int],
    search_size: int,
) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    for item_id, position in positions.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO listing_positions
                (item_id, card_query, snapshot_date, position, search_size)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item_id, card_query, today, position, search_size),
        )
    conn.commit()
