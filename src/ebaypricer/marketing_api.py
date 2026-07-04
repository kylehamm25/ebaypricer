import logging

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
    """Return all campaigns matching *status* (RUNNING, PAUSED, ENDED, etc.)."""
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
    """Return all ads for a campaign, each with adId, bidPercentage, listingId."""
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
    """Update bid percentages for up to 500 listings at once.
    Each request: { "listingId": "...", "bidPercentage": "..." }
    Returns number of updates sent.
    """
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
    """Add a listing to a campaign with the given bid percentage."""
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
    """Return the target bid % for a listing that has been listed *days_listed*
    days. Returns None if no boost is due yet."""
    if days_listed < 10:
        return None
    bucket = days_listed // 10
    target = min(2.0 + bucket * 1.0, 10.0)
    if current_bid is not None and target <= current_bid:
        return None
    return target
