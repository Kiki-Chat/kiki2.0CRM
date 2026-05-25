"""Symmetric encryption for stored third-party credentials (SMTP password, PDS API key).

Uses Fernet (AES-128-CBC + HMAC-SHA256). The key MUST be supplied via the
``SETTINGS_ENC_KEY`` environment variable. We validate it at *import time* so the
backend refuses to start without a valid key — rather than silently storing
plaintext and failing a random PATCH days later.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_GENERATE_HINT = (
    'python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)

_key = (settings.settings_enc_key or "").strip()
if not _key:
    raise RuntimeError(
        "SETTINGS_ENC_KEY is not set — the backend will not start. "
        f"Generate one with:\n  {_GENERATE_HINT}\n"
        "then set it in backend/.env (local) and the Railway env vars (prod)."
    )
try:
    _fernet = Fernet(_key.encode())
except Exception as exc:  # noqa: BLE001 — surface any malformed-key error loudly
    raise RuntimeError(
        f"SETTINGS_ENC_KEY is not a valid Fernet key ({exc}). "
        f"Generate a fresh one with:\n  {_GENERATE_HINT}"
    ) from exc


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a secret for storage. Returns None for empty input."""
    if not plaintext:
        return None
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(token: str | None) -> str | None:
    """Decrypt a stored secret. Returns None if absent or tampered."""
    if not token:
        return None
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        return None
