"""eBay Developer Analytics: how much of today's API quota this app has spent.

The rest of this repo deliberately does not hardcode eBay's limits - they vary by API
and by account standing, and a guessed number is worse than none. eBay reports the real
figures, so they are read rather than assumed.

Only a curated handful of the ~250 reported resources are surfaced. The full response
lists every Trading call by name, all sharing one pool, which would drown the four that
actually matter here:

    Browse    - comp research and the valuation page. THE constraint: one call per card
                per day, and the valuation page lets a person spend these by typing.
    Trading   - active listings, sold orders, price revisions. One shared bucket for
                every Trading call.
    Finances  - fee data for sold orders.
    Marketing - promoted-listing ad rates.

Fetching this is itself a metered call (developer.analytics.app_rate_limit), so callers
must cache - see the router, which does.
"""

from __future__ import annotations

import requests

from .auth import get_ebay_token

RATE_LIMIT_URL = "https://api.ebay.com/developer/analytics/v1_beta/rate_limit/"

# Display name -> how to find it in the response. Matched on the resource name except
# for Trading, which reports one shared pool under a per-call name, so it is matched on
# the block's apiName instead and collapsed to a single figure.
_BROWSE = "buy.browse"
_FINANCES = "payoutapi.sell.finances"
_MARKETING = "sell.marketing.ads.campaign"


def fetch_rate_limits(timeout: int = 20) -> list[dict]:
    """Today's quota for the APIs this app uses, most-consumed first.

    Each entry: {name, used, limit, remaining, pct, reset}. Returns [] rather than
    raising if eBay is unreachable or the app lacks access - a usage widget must never
    be the thing that breaks a page.
    """
    try:
        resp = requests.get(
            RATE_LIMIT_URL,
            headers={"Authorization": f"Bearer {get_ebay_token()}"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return []

    out: dict[str, dict] = {}
    for block in payload.get("rateLimits") or []:
        api_name = (block.get("apiName") or "").strip()
        for resource in block.get("resources") or []:
            res_name = (resource.get("name") or "").strip()
            label = None
            if res_name == _BROWSE:
                label = "Browse"
            elif res_name == _FINANCES:
                label = "Finances"
            elif res_name == _MARKETING:
                label = "Marketing"
            # eBay reports this block as "TradingAPI", not "Trading" - and as 84
            # separate call names all drawing on one shared pool.
            elif api_name.lower().replace(" ", "") == "tradingapi":
                label = "Trading"
            if not label:
                continue

            for rate in resource.get("rates") or []:
                limit = rate.get("limit") or 0
                remaining = rate.get("remaining")
                if not limit or remaining is None:
                    continue
                used = limit - remaining
                # Trading reports the same shared pool once per call name; keep the
                # worst reading rather than whichever happened to come last.
                prev = out.get(label)
                if prev and prev["used"] >= used:
                    continue
                out[label] = {
                    "name": label,
                    "used": used,
                    "limit": limit,
                    "remaining": remaining,
                    "pct": round(used / limit * 100, 1),
                    "reset": rate.get("reset"),
                }

    return sorted(out.values(), key=lambda r: -r["pct"])
