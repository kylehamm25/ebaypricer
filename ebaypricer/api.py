import time
import logging
import requests
from datetime import datetime, timedelta, timezone
from .config import EBAY_APP_ID, EBAY_SECRET, LISTING_LIMIT

log = logging.getLogger(__name__)

_token_cache: dict = {}


def get_ebay_token() -> str:
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
    return _token_cache["token"]


def search_sold_listings(query: str, LOOKBACK_DAYS: int) -> list[dict]:
    token = get_ebay_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }

    date_from = (
        datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    params = {
        "q": f"{query} pokemon card -PSA -BGS -CGC -SGC -graded -slab",
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
        return search_sold_listings(query, LOOKBACK_DAYS)

    resp.raise_for_status()
    data = resp.json()
    items = data.get("itemSummaries", [])
    log.info(f" {len(items)} sold listings found")
    return items
