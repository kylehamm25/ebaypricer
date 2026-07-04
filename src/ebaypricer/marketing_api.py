import json
import logging
import re
import sys

import requests

from .auth import get_access_token

log = logging.getLogger(__name__)

MARKETING_URL = "https://api.ebay.com/sell/marketing/v1"

# Trading API returns Item ID as plain "123456789".
# The Marketing API may return listingId as "v1|123456789|0".
_LISTING_ID_PREFIX = re.compile(r"^v1\|")
_LISTING_ID_SUFFIX = re.compile(r"\|0$")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _normalize_listing_id(raw: str) -> str:
    """Strip the v1|...|0 wrapper so IDs from Trading API and Marketing API
    can be compared directly."""
    return _LISTING_ID_SUFFIX.sub("", _LISTING_ID_PREFIX.sub("", raw))


def get_campaigns(token: str, status: str = "RUNNING") -> list[dict]:
    """Return all campaigns matching *status*."""
    resp = requests.get(
        f"{MARKETING_URL}/ad_campaign",
        headers=_headers(token),
        params={"limit": 200, "offset": 0},
        timeout=15,
    )
    if resp.status_code == 404:
        return []
    if resp.status_code == 403:
        print("ERROR: eBay returned 403 Forbidden for the Marketing API.")
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:1000]
        print(f"  Response body: {json.dumps(detail, indent=2) if isinstance(detail, dict) else detail}")
        print()
        print("  This usually means your account is not eligible for Promoted Listings.")
        print("  eBay silently drops the sell.marketing scope during authorization")
        print("  if the seller account doesn't meet the requirements.")
        print()
        print("  Required in your eBay account:")
        print("    1. Active eBay Store subscription")
        print("       -> Account -> Subscriptions -> eBay Store")
        print("    2. Top Rated or Above Standard seller level")
        print("       -> Seller Dashboard -> Performance")
        print("    3. Accept Promoted Listings terms")
        print("       -> Go to a listing you own and click 'Promote' to accept terms")
        print()
        print("  If you believe you meet all requirements, re-authorize:")
        print("    1. Go to https://www.ebay.com/mye/myebay/account/application-access")
        print("    2. Revoke 'tcg pricefinder'")
        print("    3. Run: python scripts/gen_access_token.py")
        print("    4. Check the RESPONSE line for 'sell.marketing' in the scope list")
        sys.exit(1)
    resp.raise_for_status()
    campaigns = resp.json().get("campaigns", [])
    return [c for c in campaigns if c.get("campaignStatus") == status]


def get_ads(token: str, campaign_id: str) -> list[dict]:
    """Return all ads for a campaign, with normalized listingId."""
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
        for ad in data.get("ads", []):
            ad["listingId"] = _normalize_listing_id(ad.get("listingId", ""))
            ads.append(ad)
        if offset + limit >= data.get("total", 0):
            break
        offset += limit
    return ads


def bulk_update_bids(token: str, campaign_id: str, requests_list: list[dict]) -> dict:
    """Update bid percentages for up to 500 listings at once.
    Each request: { "listingId": "...", "bidPercentage": "..." }
    Returns {"sent": N, "errors": [...]}.
    """
    result: dict = {"sent": 0, "errors": []}
    if not requests_list:
        return result
    resp = requests.post(
        f"{MARKETING_URL}/ad_campaign/{campaign_id}/bulk_update_ads_bid_by_listing_id",
        headers=_headers(token),
        json={"requests": requests_list},
        timeout=30,
    )
    if resp.status_code != 200:
        log.error("Bulk bid update failed (%s): %s", resp.status_code, resp.text[:1000])
        result["errors"].append({"status": resp.status_code, "body": resp.text[:1000]})
        return result
    result["sent"] = len(requests_list)
    body = resp.json()
    if body.get("errors") or body.get("warnings"):
        result["errors"] = body.get("errors", []) + body.get("warnings", [])
    return result


def create_ad(token: str, campaign_id: str, listing_id: str, bid_pct: float) -> dict:
    """Add a listing to a campaign. Returns {"ok": bool, "response": ...}."""
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
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:500]
        log.error("Create ad failed for listing %s (%s): %s", listing_id, resp.status_code, json.dumps(body)[:500])
        return {"ok": False, "status": resp.status_code, "response": body}
    return {"ok": True, "status": resp.status_code, "response": resp.json() if resp.text else None}


def compute_target_bid(days_listed: int, current_bid: float | None = None) -> float | None:
    """Return the target bid % for a listing. Returns None if no boost due."""
    if days_listed < 10:
        return None
    bucket = days_listed // 10
    target = min(2.0 + bucket * 1.0, 10.0)
    if current_bid is not None and target <= current_bid:
        return None
    return target
