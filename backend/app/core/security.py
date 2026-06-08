import time

import httpx
from jose import JWTError, jwt

from app.core.config import settings

# Supabase issues ES256 (asymmetric) tokens by default with the new signing
# keys. We verify against the project's published JWKS. Legacy projects that
# still use a shared HS256 secret are handled via SUPABASE_JWT_SECRET.

_jwks_cache: dict = {"keys": None, "ts": 0.0}


def _jwks_url() -> str:
    return f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"


def _get_jwks(force: bool = False) -> list[dict]:
    now = time.time()
    # TTL is read live from settings (default 300s) so a rotated/revoked Supabase
    # signing key stops being trusted within one short window, not up to an hour.
    if not force and _jwks_cache["keys"] and now - _jwks_cache["ts"] < settings.jwks_ttl_seconds:
        return _jwks_cache["keys"]
    resp = httpx.get(_jwks_url(), timeout=5)
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    _jwks_cache["keys"] = keys
    _jwks_cache["ts"] = now
    return keys


def decode_supabase_jwt(token: str) -> dict:
    """Verify a Supabase access token and return its claims.

    Raises JWTError if the token is invalid or expired.
    """
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")

    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise JWTError("HS256 token received but SUPABASE_JWT_SECRET is not set")
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    kid = header.get("kid")
    keys = _get_jwks()
    key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:
        # Key may have rotated — refresh once.
        keys = _get_jwks(force=True)
        key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:
        raise JWTError("Signing key not found in JWKS")

    return jwt.decode(token, key, algorithms=[alg], audience="authenticated")


__all__ = ["decode_supabase_jwt", "JWTError"]
