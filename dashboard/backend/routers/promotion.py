import uuid

from fastapi import APIRouter, Depends, HTTPException

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.services.ebay_oauth import NotConnectedError, get_access_token
from ebaypricer.marketing_api import MarketingApiError, get_campaigns, get_ads

router = APIRouter(prefix="/api/v1/promotions", tags=["promotions"])

# Simple server-side cache, keyed per-user
_cache = {}
_cache_ttl = {}


def _cached_or_fetch(key, fetch_fn, ttl=60):
    import time
    now = time.time()
    if key in _cache and (now - _cache_ttl.get(key, 0)) < ttl:
        return _cache[key]
    try:
        result = fetch_fn()
        _cache[key] = result
        _cache_ttl[key] = now
        return result
    except NotConnectedError as e:
        raise HTTPException(400, str(e))
    except MarketingApiError as e:
        raise HTTPException(502, str(e))


@router.get("/campaigns")
def get_campaign_list(user_id: uuid.UUID = Depends(get_current_user_id)):
    def _fetch():
        token = get_access_token(user_id)
        return get_campaigns(token)
    return _cached_or_fetch(f"campaigns:{user_id}", _fetch)


@router.get("/ads")
def get_ad_list(user_id: uuid.UUID = Depends(get_current_user_id)):
    def _fetch():
        token = get_access_token(user_id)
        campaigns = get_campaigns(token)
        all_ads = []
        for c in campaigns:
            ads = get_ads(token, c["campaignId"])
            for ad in ads:
                ad["campaign_name"] = c.get("campaignName", "")
            all_ads.extend(ads)
        return all_ads
    return _cached_or_fetch(f"ads:{user_id}", _fetch, ttl=120)
