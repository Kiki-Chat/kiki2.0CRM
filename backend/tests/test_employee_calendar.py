"""Tests for the per-employee calendar token layer (services/employee_calendar)
and the shared refresh helper (oauth_tokens.access_token_from_conn). Encryption
uses the real Fernet key from .env; the DB is faked."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.core.crypto import encrypt
from app.services import employee_calendar as ec
from app.services import oauth_tokens


def _future_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _fake_client(**table_rows: list[dict]) -> MagicMock:
    def make_chain(rows: list[dict]) -> MagicMock:
        chain = MagicMock()
        for m in ("select", "eq", "in_", "order", "limit", "upsert", "delete"):
            getattr(chain, m).return_value = chain
        res = MagicMock()
        res.data = rows
        chain.execute.return_value = res
        return chain

    chains = {name: make_chain(rows) for name, rows in table_rows.items()}
    client = MagicMock()
    client.table.side_effect = lambda name: chains.get(name, make_chain([]))
    return client


# ─── shared helper: access_token_from_conn ───────────────────────────────────
def test_access_token_from_conn_returns_cached_when_fresh():
    conn = {
        "access_token_encrypted": encrypt("tok-123"),
        "refresh_token_encrypted": encrypt("ref"),
        "token_expires_at": _future_iso(),
    }
    persisted: list = []
    tok = oauth_tokens.access_token_from_conn(
        conn, "google", lambda a, r, e: persisted.append((a, r, e))
    )
    assert tok == "tok-123"
    assert persisted == []  # still valid → no refresh, no persist


def test_access_token_from_conn_raises_without_refresh():
    conn = {"access_token_encrypted": None, "refresh_token_encrypted": None, "token_expires_at": None}
    with pytest.raises(oauth_tokens.OAuthTokenError):
        oauth_tokens.access_token_from_conn(conn, "google", lambda *a: None)


# ─── resolve_employee_id ─────────────────────────────────────────────────────
def test_resolve_employee_id(monkeypatch):
    monkeypatch.setattr(ec, "get_service_client", lambda: _fake_client(employees=[{"id": "emp-1"}]))
    assert ec.resolve_employee_id("org", "user-1") == "emp-1"


def test_resolve_employee_id_none_when_no_row(monkeypatch):
    monkeypatch.setattr(ec, "get_service_client", lambda: _fake_client(employees=[]))
    assert ec.resolve_employee_id("org", "user-1") is None
    assert ec.resolve_employee_id("org", None) is None


# ─── get_valid_access_token ──────────────────────────────────────────────────
def test_get_valid_access_token_returns_cached_when_fresh(monkeypatch):
    conn = {
        "access_token_encrypted": encrypt("tok-xyz"),
        "refresh_token_encrypted": encrypt("ref"),
        "token_expires_at": _future_iso(),
        "account_email": "e@x.de",
    }
    monkeypatch.setattr(
        ec, "get_service_client", lambda: _fake_client(employee_calendar_connections=[conn])
    )
    assert ec.get_valid_access_token("org", "emp") == "tok-xyz"


def test_get_valid_access_token_raises_when_not_connected(monkeypatch):
    monkeypatch.setattr(
        ec, "get_service_client", lambda: _fake_client(employee_calendar_connections=[])
    )
    with pytest.raises(oauth_tokens.OAuthTokenError):
        ec.get_valid_access_token("org", "emp")


# ─── list_connections ────────────────────────────────────────────────────────
def test_list_connections_reports_decryptable_as_connected(monkeypatch):
    rows = [
        {"employee_id": "e1", "provider": "google", "account_email": "a@x.de",
         "token_expires_at": None,
         "access_token_encrypted": encrypt("t"), "refresh_token_encrypted": None},
        {"employee_id": "e2", "provider": "google", "account_email": None,
         "token_expires_at": None,
         "access_token_encrypted": None, "refresh_token_encrypted": None},
    ]
    monkeypatch.setattr(
        ec, "get_service_client", lambda: _fake_client(employee_calendar_connections=rows)
    )
    out = ec.list_connections("org")
    assert out["e1"]["connected"] is True and out["e1"]["account_email"] == "a@x.de"
    assert out["e2"]["connected"] is False  # no ciphertext → not connected
