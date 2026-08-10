import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.services.ebay_client import EbayApiError, fetch_orders, fetch_transactions
from dashboard.backend.services.ebay_data import sync_user_ebay_data
from dashboard.backend.services.ebay_oauth import (
    EbayOAuthError,
    EncryptionNotConfiguredError,
    NotConnectedError,
    complete_connection,
    create_authorize_url,
    disconnect,
    get_connection_status,
)
from dashboard.backend.services.promotion_boost import run_user_promotion_boost

router = APIRouter(prefix="/api/v1/ebay", tags=["ebay"])


@router.get("/connect-url")
def connect_url(user_id: uuid.UUID = Depends(get_current_user_id)):
    try:
        return {"url": create_authorize_url(user_id)}
    except EbayOAuthError as e:
        raise HTTPException(500, str(e))


@router.get("/callback")
def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    """eBay redirects the browser here after the user consents. No auth header needed -
    the state token maps back to the signed-in user."""
    if not code or not state:
        raise HTTPException(400, "Missing code or state")
    try:
        redirect_path = complete_connection(code, state, error)
    except EncryptionNotConfiguredError as e:
        raise HTTPException(500, str(e))
    except EbayOAuthError as e:
        raise HTTPException(502, str(e))
    return RedirectResponse(url=redirect_path)


@router.get("/status")
def status(user_id: uuid.UUID = Depends(get_current_user_id)):
    return get_connection_status(user_id)


@router.post("/disconnect")
def disconnect_endpoint(user_id: uuid.UUID = Depends(get_current_user_id)):
    try:
        disconnect(user_id)
    except NotConnectedError as e:
        raise HTTPException(404, str(e))
    return {"disconnected": True}


@router.post("/sync")
def sync_now(user_id: uuid.UUID = Depends(get_current_user_id)):
    """Kick off a per-user eBay sync in the background. Returns immediately."""
    try:
        result = sync_user_ebay_data(user_id)
    except NotConnectedError as e:
        raise HTTPException(400, str(e))
    except EbayOAuthError as e:
        raise HTTPException(502, str(e))
    if result.get("status") == "error":
        raise HTTPException(502, result.get("error", "sync failed"))
    if result.get("status") == "running":
        raise HTTPException(409, result.get("error", "sync already running"))
    return result


@router.post("/sync/background")
def sync_now_background(user_id: uuid.UUID = Depends(get_current_user_id)):
    """Start a per-user sync in a background thread and return immediately."""
    threading.Thread(target=sync_user_ebay_data, args=(user_id,), daemon=True).start()
    return {"started": True}


@router.post("/promotion-boost")
def promotion_boost_now(user_id: uuid.UUID = Depends(get_current_user_id)):
    """Run promoted-listing ad-rate boosting for this user now. Never raises for
    ineligible/unconnected accounts - check the returned status field."""
    return run_user_promotion_boost(user_id)


@router.get("/orders")
def orders(limit: int = 10, offset: int = 0, user_id: uuid.UUID = Depends(get_current_user_id)):
    try:
        return fetch_orders(user_id, limit=limit, offset=offset)
    except NotConnectedError as e:
        raise HTTPException(400, str(e))
    except EbayApiError as e:
        raise HTTPException(e.status_code or 502, str(e))


@router.get("/transactions")
def transactions(
    limit: int = 10, offset: int = 0, user_id: uuid.UUID = Depends(get_current_user_id)
):
    try:
        return fetch_transactions(user_id, limit=limit, offset=offset)
    except NotConnectedError as e:
        raise HTTPException(400, str(e))
    except EbayApiError as e:
        raise HTTPException(e.status_code or 502, str(e))
