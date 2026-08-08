"""
Per-user eBay OAuth (Phase 5).

Three-legged OAuth (authorization_code, no PKCE - server-side app with client secret):
  1. GET /ebay/connect-url  -> state {user_id} + code_verifier stored in memory, returns authorize URL
  2. eBay redirects browser to /ebay/callback?code=...&state=...
  3. Callback exchanges code -> refresh_token (Fernet-encrypted), stores in ebay_connections,
     redirects the browser back to the frontend.

Refresh tokens are encrypted at rest with `cryptography.fernet.Fernet` using the
EBAY_TOKEN_ENCRYPTION_KEY env var. Access tokens are refreshed per-user on demand and
cached in memory for the token lifetime.
"""

import base64
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests
from cryptography.fernet import Fernet, InvalidToken

from dashboard.backend.config import (
    EBAY_APP_ID,
    EBAY_RUNAME,
    EBAY_SCOPES,
    EBAY_SECRET,
    EBAY_TOKEN_ENCRYPTION_KEY,
)
from dashboard.backend.database import get_db

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
AUTHORIZE_URL = "https://auth.ebay.com/oauth2/authorize"
USERINFO_URL = "https://api.ebay.com/identity/v1/oauth2/userinfo"

_STATE_TTL_SECONDS = 600  # 10 minutes
_lock = threading.Lock()
# state -> {"user_id": uuid, "verifier": str, "expires_at": float}
_auth_states: dict[str, dict] = {}
# user_id -> {"token": str, "expires_at": float}
_access_cache: dict[str, dict] = {}


class EbayOAuthError(Exception):
    pass


class NotConnectedError(EbayOAuthError):
    pass


class EncryptionNotConfiguredError(EbayOAuthError):
    pass


def _encryptor() -> Fernet:
    if not EBAY_TOKEN_ENCRYPTION_KEY:
        raise EncryptionNotConfiguredError(
            "EBAY_TOKEN_ENCRYPTION_KEY is not set - generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(EBAY_TOKEN_ENCRYPTION_KEY.encode())


def _prune_states() -> None:
    now = time.time()
    for key in [k for k, v in _auth_states.items() if v["expires_at"] < now]:
        del _auth_states[key]


def create_authorize_url(user_id: uuid.UUID) -> str:
    """Build the eBay authorization URL for a user; state is stored in memory."""
    if not EBAY_APP_ID or not EBAY_SECRET or not EBAY_RUNAME:
        raise EbayOAuthError("EBAY_APP_ID, EBAY_SECRET, and RUNAME must be set in .env")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    with _lock:
        _prune_states()
        _auth_states[state] = {
            "user_id": str(user_id),
            "verifier": verifier,
            "expires_at": time.time() + _STATE_TTL_SECONDS,
        }

    params = {
        "client_id": EBAY_APP_ID,
        "response_type": "code",
        "redirect_uri": EBAY_RUNAME,
        "scope": EBAY_SCOPES,
        "state": state,
    }
    return AUTHORIZE_URL + "?" + "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())


def complete_connection(code: str, state: str, error: str | None = None) -> str:
    """Exchange the callback params for a refresh token and persist it (encrypted).

    Returns the frontend redirect path (e.g. "/settings?ebay=connected").
    """
    with _lock:
        entry = _auth_states.pop(state, None)
    if entry is None:
        raise EbayOAuthError("OAuth state expired or invalid - please try connecting again")
    user_id = uuid.UUID(entry["user_id"])

    if error:
        raise EbayOAuthError(f"eBay authorization failed: {error}")

    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": "Basic "
            + base64.b64encode(f"{EBAY_APP_ID}:{EBAY_SECRET}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": EBAY_RUNAME,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise EbayOAuthError(f"Token exchange failed ({resp.status_code}): {resp.text[:300]}")
    body = resp.json()

    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise EbayOAuthError(f"eBay did not return a refresh_token: {resp.text[:300]}")

    access_token = body.get("access_token", "")
    expires_in = int(body.get("expires_in", 7200))
    scopes = body.get("scope") or EBAY_SCOPES

    ebay_user_id = None
    if access_token:
        try:
            userinfo = requests.get(
                USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if userinfo.status_code == 200:
                ebay_user_id = userinfo.json().get("sub")
            else:
                print(f"  [ebay] userinfo failed ({userinfo.status_code}): {userinfo.text[:200]}")
        except requests.RequestException as e:
            print(f"  [ebay] userinfo request failed: {e}")

    now = datetime.now(timezone.utc)
    token = _encryptor().encrypt(refresh_token.encode())
    with get_db(read_only=False) as conn:
        conn.execute(
            """INSERT INTO ebay_connections
                   (user_id, ebay_user_id, refresh_token, scopes, token_issued_at, token_expires_at, sync_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (user_id) DO UPDATE SET
                   ebay_user_id = EXCLUDED.ebay_user_id,
                   refresh_token = EXCLUDED.refresh_token,
                   scopes = EXCLUDED.scopes,
                   token_issued_at = EXCLUDED.token_issued_at,
                   token_expires_at = EXCLUDED.token_expires_at,
                   sync_status = 'connected'""",
            (
                str(user_id),
                ebay_user_id,
                token.decode(),
                scopes,
                now,
                now + timedelta(seconds=expires_in),
                "connected",
            ),
        )
    with _lock:
        _access_cache.pop(str(user_id), None)
    return "/settings?ebay=connected"


def _get_connection_row(user_id: uuid.UUID) -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT user_id, ebay_user_id, refresh_token, scopes, token_issued_at, token_expires_at, last_synced_at, sync_status "
            "FROM ebay_connections WHERE user_id = %s",
            [str(user_id)],
        ).fetchall()
    return rows[0] if rows else None


def get_access_token(user_id: uuid.UUID) -> str:
    """Per-user access token: refresh grant with the stored (encrypted) refresh token, cached."""
    key = str(user_id)
    with _lock:
        cached = _access_cache.get(key)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["token"]

    row = _get_connection_row(user_id)
    if row is None:
        raise NotConnectedError("No eBay connection for this user - connect your eBay account first")
    try:
        refresh_token = _encryptor().decrypt(row["refresh_token"].encode()).decode()
    except InvalidToken:
        raise EbayOAuthError("Stored eBay refresh token could not be decrypted - reconnect your account")

    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": "Basic "
            + base64.b64encode(f"{EBAY_APP_ID}:{EBAY_SECRET}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=15,
    )
    if resp.status_code != 200:
        raise EbayOAuthError(
            f"eBay token refresh failed ({resp.status_code}): {resp.text[:300]}"
        )
    body = resp.json()
    token = body["access_token"]
    expires_at = time.time() + int(body.get("expires_in", 7200))
    with _lock:
        _access_cache[key] = {"token": token, "expires_at": expires_at}
    return token


def get_connection_status(user_id: uuid.UUID) -> dict:
    row = _get_connection_row(user_id)
    if row is None:
        return {
            "connected": False,
            "ebay_user_id": None,
            "scopes": None,
            "token_expires_at": None,
            "last_synced_at": None,
            "sync_status": None,
        }
    return {
        "connected": True,
        "ebay_user_id": row["ebay_user_id"],
        "scopes": row["scopes"],
        "token_expires_at": row["token_expires_at"].isoformat() if row["token_expires_at"] else None,
        "last_synced_at": row["last_synced_at"].isoformat() if row["last_synced_at"] else None,
        "sync_status": row["sync_status"],
    }


def disconnect(user_id: uuid.UUID) -> None:
    with get_db(read_only=False) as conn:
        cur = conn.execute("DELETE FROM ebay_connections WHERE user_id = %s", [str(user_id)])
        if cur.rowcount == 0:
            raise NotConnectedError("No eBay connection for this user")
    with _lock:
        _access_cache.pop(str(user_id), None)
