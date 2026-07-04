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
import json
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
    parser.add_argument("--debug", action="store_true",
                        help="Print raw API responses for debugging")
    return parser.parse_args()


def main():
    args = parse_args()

    token = get_access_token()

    # ── Find target campaign ────────────────────────────────────────────
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
        if args.debug:
            print(f"  Full campaign data: {json.dumps(campaign, indent=2)}")

    # ── Get active listings ─────────────────────────────────────────────
    print("\nFetching active listings ...")
    listings = fetch_active_listings(token)
    if not listings:
        print("No active listings found.")
        return

    print(f"  {len(listings)} total active listings")

    # ── Get existing ads in the campaign ────────────────────────────────
    print("\nFetching current ads in campaign ...")
    ads = get_ads(token, campaign_id)
    ads_by_listing: dict[str, dict] = {}
    for ad in ads:
        lid = ad.get("listingId", "")
        if lid:
            ads_by_listing[lid] = ad
    print(f"  {len(ads)} existing promoted listings")

    if args.debug and ads:
        print(f"  Sample ad: {json.dumps(ads[0], indent=2)}")
        print(f"  Sample listing (Trading API ID): {json.dumps(listings[0].get('Item ID', ''))}")

    # ── Build update list ───────────────────────────────────────────────
    to_update: list[dict] = []
    to_create: list[tuple[str, float]] = []
    boosts = 0
    at_cap = 0
    skipped_days = 0
    no_ad_found = 0

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

    # ── Create new ads ──────────────────────────────────────────────────
    if to_create:
        print(f"\nCreating {len(to_create)} new promoted listing(s) ...")
        ok = 0
        for listing_id, bid_pct in to_create:
            result = create_ad(token, campaign_id, listing_id, bid_pct)
            if result["ok"]:
                ok += 1
            elif args.debug:
                print(f"  FAILED listing {listing_id}: {json.dumps(result['response'], indent=2)[:300]}")
        print(f"  {ok}/{len(to_create)} created")

    # ── Execute bulk updates ────────────────────────────────────────────
    if to_update:
        print(f"\nUpdating {len(to_update)} bid(s) in batches of {BATCH_SIZE} ...")
        total_sent = 0
        for i in range(0, len(to_update), BATCH_SIZE):
            batch = to_update[i:i + BATCH_SIZE]
            result = bulk_update_bids(token, campaign_id, batch)
            total_sent += result["sent"]
            if result["errors"] and args.debug:
                print(f"  batch {i // BATCH_SIZE + 1} errors: {json.dumps(result['errors'], indent=2)[:500]}")
            print(f"  batch {i // BATCH_SIZE + 1}: {result['sent']} updates")
        print(f"  Total: {total_sent} bid update(s) sent")


if __name__ == "__main__":
    main()
