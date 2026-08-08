import base64
import uuid

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from dashboard.backend.config import AUTH_REQUIRED, DEFAULT_USER_ID, SUPABASE_JWT_SECRET, SUPABASE_URL

_bearer = HTTPBearer(auto_error=False)
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        )
    return _jwks_client


def _decode_token(token: str) -> dict:
    try:
        # Current Supabase: ES256 tokens verified against the project JWKS.
        client = _get_jwks_client()
        key = client.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["ES256"], audience="authenticated")
    except Exception:
        pass
    # Legacy: HS256 with the shared secret (Supabase exposes it base64-encoded).
    try:
        key: str | bytes = base64.b64decode(SUPABASE_JWT_SECRET, validate=True)
    except Exception:
        key = SUPABASE_JWT_SECRET
    return jwt.decode(token, key, algorithms=["HS256"], audience="authenticated")


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> uuid.UUID:
    if credentials is not None:
        try:
            payload = _decode_token(credentials.credentials)
            sub = payload.get("sub")
            if sub:
                return uuid.UUID(sub)
        except (jwt.PyJWTError, ValueError):
            pass
    if AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if DEFAULT_USER_ID:
        return uuid.UUID(DEFAULT_USER_ID)
    raise RuntimeError("No user context: set DEFAULT_USER_ID until auth is wired up (Phase 3)")
