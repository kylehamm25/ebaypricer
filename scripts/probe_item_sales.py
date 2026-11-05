"""
One-shot probe of eBay's Marketplace Insights Item Sales API (genuine sold comps).

Read-only: exactly one Browse-style call, no writes anywhere. Validates whether
the `sell.marketplace.insights.readonly` scope this app requests actually yields
usable sold records for a card - the prerequisite for reopening sold-side
research (see ADR-002, which removed it for lack of a real source).

Usage:
    python scripts/probe_item_sales.py --q "sylveon ex 41 prismatic" [--limit 10]

Requires a connection whose granted scopes include
`sell.marketplace.insights.readonly`. Tokens never gain scopes retroactively:
if the guard below reports the scope missing, disconnect/reconnect on the
Settings page (which consents to the current EBAY_SCOPES) and run again.
"""

import argparse
import json
import sys
import uuid

import requests

from dashboard.backend.config import DEFAULT_USER_ID
from dashboard.backend.services.ebay_oauth import (
    EbayOAuthError,
    NotConnectedError,
    get_access_token,
    get_connection_status,
)

INSIGHTS_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.marketplace.insights.readonly"
ITEM_SALES_URL = "https://api.ebay.com/sell/marketplace_insights/v1/item_sales/search"


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe the Item Sales (sold comps) API once.")
    ap.add_argument("--q", required=True, help="keywords, e.g. a card name + number + set")
    ap.add_argument("--limit", type=int, default=10, help="records to ask for (default 10)")
    ap.add_argument("--marketplace", default="EBAY_US")
    ap.add_argument("--user", default=DEFAULT_USER_ID, help="user_id (default DEFAULT_USER_ID)")
    args = ap.parse_args()

    user_id = uuid.UUID(args.user)
    try:
        status = get_connection_status(user_id)
    except Exception as e:
        print(f"Could not read eBay connection: {e}")
        return 2
    if not status["connected"]:
        print("No eBay connection for this user - connect on the Settings page first.")
        return 2
    granted = status["scopes"] or ""
    if INSIGHTS_SCOPE not in granted.split():
        print("Connected, but the granted scopes lack sell.marketplace.insights.readonly.")
        print("Disconnect/reconnect on the Settings page to consent to the current "
              "EBAY_SCOPES, then run this probe again. No API call was made.")
        return 2

    try:
        token = get_access_token(user_id)
    except (NotConnectedError, EbayOAuthError) as e:
        print(f"Token refresh failed: {e}")
        return 2

    resp = requests.get(
        ITEM_SALES_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": args.marketplace,
            "Content-Type": "application/json",
        },
        params={"q": args.q, "limit": args.limit},
        timeout=20,
    )
    if resp.status_code != 200:
        print(f"Item Sales call failed ({resp.status_code}): {resp.text[:500]}")
        return 1

    body = resp.json()
    # Field names below are best-effort: print what the API actually returns, and
    # the raw payload (truncated) so the shape can be pinned down from evidence.
    records = body.get("itemSales") or body.get("item_sales") or []
    print(f"total: {body.get('total', '?')}  returned: {len(records)}")
    for r in records:
        price = r.get("price") or {}
        print(
            f"  sold_qty={r.get('totalSoldQuantity', r.get('soldQuantity', '?'))} "
            f"price={price.get('value', '?')} {price.get('currency', '')} "
            f"| {str(r.get('title', r.get('itemId', '?')))[:90]}"
        )
    raw = json.dumps(body)[:2000]
    print(f"--- raw (first 2000 chars) ---\n{raw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
