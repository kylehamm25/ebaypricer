"""
eBay API client for per-user calls (Phase 5).

All calls use a per-user access token obtained via ebay_oauth.get_access_token().
Scope: sell/fulfillment orders and sell/finances transactions.
"""

import uuid

import requests

from dashboard.backend.services.ebay_oauth import get_access_token

FULFILLMENT_BASE = "https://api.ebay.com/sell/fulfillment/v1"
FINANCES_BASE = "https://apiz.ebay.com/sell/finances/v1"


class EbayApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


def _get(user_id: uuid.UUID, url: str, params: dict | None = None) -> dict:
    token = get_access_token(user_id)
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params=params,
        timeout=20,
    )
    if resp.status_code != 200:
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        raise EbayApiError(
            f"eBay API error ({resp.status_code}) on {url}", resp.status_code, payload
        )
    return resp.json()


def fetch_orders(user_id: uuid.UUID, limit: int = 10, offset: int = 0) -> dict:
    """Recent fulfillment orders for the user's account."""
    return _get(
        user_id,
        f"{FULFILLMENT_BASE}/order",
        {"limit": limit, "offset": offset},
    )


def fetch_transactions(user_id: uuid.UUID, limit: int = 10, offset: int = 0) -> dict:
    """Recent finances transactions for the user's account."""
    return _get(
        user_id,
        f"{FINANCES_BASE}/transaction",
        {"limit": limit, "offset": offset},
    )
