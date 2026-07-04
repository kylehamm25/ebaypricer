# Auto-Boost Promoted Listings

## Overview

Increase the promoted listing ad rate by 1% every 10 days an item is listed without selling, up to 10% max.

## Files to Create

### 1. `src/ebaypricer/marketing_api.py`

Marketing API wrapper module with these functions:

- `get_campaigns(token, status="RUNNING")` — list campaigns
- `get_ads(token, campaign_id)` — list ads in a campaign with current bid %
- `bulk_update_bids(token, campaign_id, requests)` — bulk update via `bulkUpdateAdsBidByListingId` (batches of 500)
- `create_ad(token, campaign_id, listing_id, bid_pct)` — add a listing to a campaign
- `compute_target_bid(days_listed, current_bid)` — calculates target bid: `min(2.0 + (days//10) * 1.0, 10.0)`, returns `None` if no boost due

<details>
<summary>Full source</summary>

```python
import logging
import sys
from datetime import datetime, timezone

import requests

from .auth import get_access_token

log = logging.getLogger(__name__)

MARKETING_URL = "https://api.ebay.com/sell/marketing/v1"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_campaigns(token: str, status: str = "RUNNING") -> list[dict]:
    resp = requests.get(
        f"{MARKETING_URL}/ad_campaign",
        headers=_headers(token),
        params={"limit": 200, "offset": 0},
        timeout=15,
    )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    campaigns = resp.json().get("campaigns", [])
    return [c for c in campaigns if c.get("campaignStatus") == status]


def get_ads(token: str, campaign_id: str) -> list[dict]:
    ads: list[dict] = []
    offset = 0
    limit = 200
    while True:
        resp = requests.get(
            f"{MARKETING_URL}/ad_campaign/{campaign_id}/ad",
            headers=_headers(token),
            params={"limit": limit, "offset": offset},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        ads.extend(data.get("ads", []))
        if offset + limit >= data.get("total", 0):
            break
        offset += limit
    return ads


def bulk_update_bids(token: str, campaign_id: str, requests_list: list[dict]) -> int:
    if not requests_list:
        return 0
    resp = requests.post(
        f"{MARKETING_URL}/ad_campaign/{campaign_id}/bulk_update_ads_bid_by_listing_id",
        headers=_headers(token),
        json={"requests": requests_list},
        timeout=30,
    )
    if resp.status_code != 200:
        log.error("Bulk bid update failed (%s): %s", resp.status_code, resp.text[:500])
        return 0
    return len(requests_list)


def create_ad(token: str, campaign_id: str, listing_id: str, bid_pct: float) -> bool:
    resp = requests.post(
        f"{MARKETING_URL}/ad_campaign/{campaign_id}/ad",
        headers=_headers(token),
        json={
            "bidPercentage": f"{bid_pct:.1f}",
            "listingId": listing_id,
        },
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        log.error("Create ad failed for listing %s (%s): %s", listing_id, resp.status_code, resp.text[:300])
        return False
    return True


def compute_target_bid(days_listed: int, current_bid: float | None = None) -> float | None:
    if days_listed < 10:
        return None
    bucket = days_listed // 10
    target = min(2.0 + bucket * 1.0, 10.0)
    if current_bid is not None and target <= current_bid:
        return None
    return target
```
</details>

### 2. `scripts/auto_boost_promotion.py`

Entry point script:

<details>
<summary>Full source</summary>

```python
"""
Automatically boost promoted listing ad rates for stale inventory.

Every 10 days an item has been listed without selling, increase its
promoted ad rate by 1%, up to a maximum of 10%.

Usage:
    python scripts/auto_boost_promotion.py
    python scripts/auto_boost_promotion.py --campaign-name "My Campaign"
    python scripts/auto_boost_promotion.py --dry-run

Requires a refresh token with the sell.marketing scope. Re-run
gen_access_token.py to authorize it if you haven't already.
"""

import argparse
import logging
import sys

from ebaypricer.auth import get_access_token
from ebaypricer.trading_api import fetch_active_listings
from ebaypricer.marketing_api import (
    compute_target_bid,
    create_ad,
    get_ads,
    get_campaigns,
    bulk_update_bids,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BATCH_SIZE = 500


def parse_args():
    parser = argparse.ArgumentParser(
        description="Boost promoted listing ad rates for stale inventory"
    )
    parser.add_argument("--campaign-name", type=str, default=None,
                        help="Name of the ad campaign to update (default: first RUNNING campaign)")
    parser.add_argument("--campaign-id", type=str, default=None,
                        help="Campaign ID (overrides --campaign-name)")
    parser.add_argument("--min-days", type=int, default=10,
                        help="Days listed before first boost (default: 10)")
    parser.add_argument("--max-bid", type=float, default=10.0,
                        help="Maximum bid percentage (default: 10.0)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be done without making changes")
    return parser.parse_args()


def main():
    args = parse_args()

    token = get_access_token()

    campaign_id = args.campaign_id
    if not campaign_id:
        campaigns = get_campaigns(token)
        if not campaigns:
            print("No RUNNING campaigns found.")
            sys.exit(0)
        if args.campaign_name:
            matches = [c for c in campaigns if c.get("campaignName") == args.campaign_name]
            if not matches:
                print(f"No campaign named '{args.campaign_name}' found.")
                sys.exit(1)
            campaign = matches[0]
        else:
            campaign = campaigns[0]
        campaign_id = campaign["campaignId"]
        print(f"Using campaign: {campaign.get('campaignName', campaign_id)} ({campaign_id})")

    print("\nFetching active listings ...")
    listings = fetch_active_listings(token)
    if not listings:
        print("No active listings found.")
        return
    print(f"  {len(listings)} total active listings")

    print("\nFetching current ads in campaign ...")
    ads = get_ads(token, campaign_id)
    ads_by_listing: dict[str, dict] = {}
    for ad in ads:
        lid = ad.get("listingId", "")
        if lid:
            ads_by_listing[lid] = ad
    print(f"  {len(ads)} existing promoted listings")

    to_update: list[dict] = []
    to_create: list[tuple[str, float]] = []
    boosts = 0
    at_cap = 0
    skipped_days = 0

    for item in listings:
        days = item.get("Days Listed", 0)
        item_id = item.get("Item ID", "")
        title = item.get("Title", "")

        if days < args.min_days:
            skipped_days += 1
            continue

        current_bid = None
        ad = ads_by_listing.get(item_id)
        if ad:
            current_bid = float(ad.get("bidPercentage", 0))

        target = compute_target_bid(days, current_bid)
        if target is None:
            at_cap += 1
            continue

        if target >= args.max_bid:
            target = args.max_bid

        if ad:
            to_update.append({
                "listingId": item_id,
                "bidPercentage": f"{target:.1f}",
            })
            status = f"{current_bid:.0f}% -> {target:.0f}% (update)"
        else:
            to_create.append((item_id, target))
            status = f"{target:.0f}% (create)"

        boosts += 1
        print(f"  {status:30s}  {title[:60]}")

    print(f"\nSummary:")
    print(f"  Skipped (under {args.min_days} days):  {skipped_days}")
    print(f"  Already at cap / no boost needed:      {at_cap}")
    print(f"  To update (bid increase):              {len(to_update)}")
    print(f"  To create (add to campaign):           {len(to_create)}")
    print(f"  Total boosts:                          {boosts}")

    if args.dry_run:
        print("\nDry-run mode — no changes made.")
        return

    if not to_update and not to_create:
        print("\nNothing to do.")
        return

    if to_create:
        print(f"\nCreating {len(to_create)} new promoted listing(s) ...")
        ok = 0
        for listing_id, bid_pct in to_create:
            if create_ad(token, campaign_id, listing_id, bid_pct):
                ok += 1
        print(f"  {ok}/{len(to_create)} created")

    if to_update:
        print(f"\nUpdating {len(to_update)} bid(s) in batches of {BATCH_SIZE} ...")
        total_sent = 0
        for i in range(0, len(to_update), BATCH_SIZE):
            batch = to_update[i:i + BATCH_SIZE]
            n = bulk_update_bids(token, campaign_id, batch)
            total_sent += n
            print(f"  batch {i // BATCH_SIZE + 1}: {n} updates")
        print(f"  Total: {total_sent} bid update(s) sent")


if __name__ == "__main__":
    main()
```
</details>

## File to Modify

### `scripts/gen_access_token.py` — line 11

Add the sell.marketing scope:

```diff
-SCOPE = "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"
+SCOPE = "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly https://api.ebay.com/oauth/api_scope/sell.marketing"
```

## Usage

```bash
# 1. Re-authorize with marketing scope (one-time)
python scripts/gen_access_token.py

# 2. Dry-run to preview
python scripts/auto_boost_promotion.py --dry-run

# 3. Run for real
python scripts/auto_boost_promotion.py

# 4. Add to daily automation
# In run_daily.sh:
echo "python scripts/auto_boost_promotion.py" >> scripts/run_daily.sh
```

## How the algorithm works

| Days Listed | Target Bid | Notes |
|---|---|---|
| 0–9 | 2% (campaign default) | No boost yet |
| 10 | 3% | +1% |
| 20 | 4% | +1% |
| ... | ... | ... |
| 80 | 10% | Max cap |
| 90+ | 10% | Stays at cap |

The script is idempotent — running it daily only boosts items whose `Days Listed` has crossed a new 10-day boundary since the last run.

## Edge cases handled

- **No campaigns found** → exits cleanly with message
- **Listing not in campaign yet** → `createAd` is called automatically
- **Already at 10% cap** → skipped
- **Current bid higher than calculated target** → skipped (won't lower bid)
- **API errors during bulk update** → logged, other batches continue
- More than 500 boosts needed → split into batches of 500
