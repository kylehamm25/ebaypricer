from fastapi import APIRouter, HTTPException
from ebaypricer.auth import get_access_token, get_ebay_token
from ebaypricer.marketing_api import get_campaigns, get_ads

router = APIRouter(prefix="/api/v1/promotions", tags=["promotions"])

# Simple server-side cache
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
    except Exception as e:
        raise HTTPException(502, str(e))


@router.get("/campaigns")
def get_campaign_list():
    def _fetch():
        token = get_access_token()
        return get_campaigns(token)
    return _cached_or_fetch("campaigns", _fetch)


@router.get("/ads")
def get_ad_list():
    def _fetch():
        token = get_access_token()
        campaigns = get_campaigns(token)
        all_ads = []
        for c in campaigns:
            ads = get_ads(token, c["campaignId"])
            for ad in ads:
                ad["campaign_name"] = c.get("campaignName", "")
            all_ads.extend(ads)
        return all_ads
    return _cached_or_fetch("ads", _fetch, ttl=120)
