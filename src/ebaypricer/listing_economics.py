"""Shared estimation helpers for active-listing economics, used by both the
legacy Excel pipeline (scripts/get_active.py) and the per-user OAuth sync
(dashboard/backend/services/ebay_data.py) so the two paths agree on numbers."""

SHIPPING_PRICE_MAP = {
    "free ebay standard": 0,
    "ebay standard envelope": 0.78,
    "ground advantage": 5,
    "free ground advantage": 0,
}


def shipping_charge_for_profile(profile: str | None) -> float:
    return SHIPPING_PRICE_MAP.get((profile or "").strip().lower(), 0)


def estimate_fees_and_net(price: float) -> tuple[float, float]:
    """Tiered net-percentage estimate of eBay/payment fees for an active (not yet
    sold) listing - real fees aren't known until Finances API data exists post-sale."""
    if price <= 2:
        multiplier = 0.65
    elif price <= 5:
        multiplier = 0.70
    else:
        multiplier = 0.73

    estimated_net = round(price * multiplier, 2)
    estimated_fees = round(price - estimated_net, 2)
    return estimated_fees, estimated_net
