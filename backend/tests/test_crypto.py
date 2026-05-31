"""Item 2 — crypto.decrypt must not fail silently.

A wrong/rotated SETTINGS_ENC_KEY makes every stored credential fail to decrypt.
decrypt() still returns None (callers rely on that contract) but now LOGS the
failure so the key problem is visible instead of looking like "no token stored".
"""
import logging

from app.core.crypto import decrypt, encrypt


def test_encrypt_decrypt_roundtrip():
    assert decrypt(encrypt("hunter2")) == "hunter2"


def test_decrypt_none_is_silent_none(caplog):
    """The legitimate 'nothing stored' case: None in, None out, NO warning."""
    with caplog.at_level(logging.WARNING, logger="app.core.crypto"):
        assert decrypt(None) is None
        assert decrypt("") is None
    assert caplog.records == []


def test_decrypt_invalid_token_logs_and_returns_none(caplog):
    """Garbage ciphertext (wrong key / tamper) → None, but a WARNING is logged."""
    with caplog.at_level(logging.WARNING, logger="app.core.crypto"):
        assert decrypt("not-a-real-fernet-token") is None
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.levelno == logging.WARNING
    assert "InvalidToken" in rec.getMessage()
    assert "SETTINGS_ENC_KEY" in rec.getMessage()
    # The ciphertext itself must never be logged.
    assert "not-a-real-fernet-token" not in rec.getMessage()
