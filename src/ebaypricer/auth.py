import base64
import os
import sys
import time

import requests
from dotenv import set_key

from .paths import ENV_PATH


def _write_env_key(key: str, value: str) -> None:
    set_key(ENV_PATH, key, value)


def _parse_usd(val: str) -> float:
    val = val.strip().lstrip("$").replace(",", "")
    try:
        return float(val) if val else 0.0
    except ValueError:
        return 0.0


def _parse_csv_date(date_str: str) -> str:
    months = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    }
    try:
        parts = date_str.strip().replace(".", "").split("-")
        if len(parts) == 3:
            mon = months.get(parts[0].title(), "01")
            day = parts[1].zfill(2)
            yr = ("20" + parts[2]) if len(parts[2]) == 2 else parts[2]
            return f"{yr}-{mon}-{day}"
    except (IndexError, KeyError):
        pass
    return date_str


MARKETING_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.marketing"


def get_access_token() -> str:
    """Trading API OAuth — uses refresh_token grant."""
    app_id = os.getenv("EBAY_APP_ID")
    secret = os.getenv("EBAY_SECRET")
    refresh = os.getenv("REFRESH_TOKEN")
    dev_id = os.getenv("EBAY_DEV_ID")
    if not app_id or not secret or not dev_id or not refresh:
        print("ERROR: EBAY_APP_ID, EBAY_DEV_ID, EBAY_SECRET, and REFRESH_TOKEN must all be set in .env")
        sys.exit(1)

    credentials = base64.b64encode(f"{app_id}:{secret}".encode()).decode()

    data: dict = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "scope": MARKETING_SCOPE,
    }
    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=data,
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"Token refresh failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    body = resp.json()
    access_token = body["access_token"]
    granted_scopes = body.get("scope", "(not returned)")
    _write_env_key("ACCESS_TOKEN", access_token)
    print(f"Access token refreshed (scopes: {granted_scopes})")
    if MARKETING_SCOPE not in str(granted_scopes):
        print("WARNING: sell.marketing scope was NOT granted.")
        print("  The refresh token may not have this scope.")
        print("  Run: python scripts/gen_access_token.py")
        print("  and complete the browser authorization to re-authorize.")
    return access_token


_token_cache: dict = {}


def get_ebay_token() -> str:
    """Browse API OAuth — uses client_credentials grant (cached)."""
    if _token_cache.get("expires_at", 0) > time.time() + 60:
        return _token_cache["token"]

    app_id = os.getenv("EBAY_APP_ID")
    secret = os.getenv("EBAY_SECRET")
    if not app_id or not secret:
        raise ValueError(
            "Missing EBAY_APP_ID or EBAY_SECRET. "
            "Copy .env.example to .env and fill in your credentials."
        )

    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        auth=(app_id, secret),
        data={"grant_type": "client_credentials",
              "scope": "https://api.ebay.com/oauth/api_scope"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + int(data["expires_in"])
    return _token_cache["token"]
