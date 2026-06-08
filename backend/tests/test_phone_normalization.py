"""Phone normalization tests (Sprint P0.8).

Covers _to_e164 directly, plus the end-to-end get_or_create_customer dedup
behavior: same number in different formats → same customer row.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.customers import get_or_create_customer
from app.services.identify import _to_e164


# ─── _to_e164 unit tests ─────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        # already E.164
        ("+4915734432281", "+4915734432281"),
        ("+49 157 344 322 81", "+4915734432281"),
        # local German
        ("0157 344 322 81", "+49157344322 81".replace(" ", "")),
        ("01701112222", "+491701112222"),
        # international 00-prefix
        ("00 49 170 111 222", "+49170111222"),
        ("004915734432281", "+4915734432281"),
        # international without "+"
        ("918920100973", "+918920100973"),
        ("49170111222", "+49170111222"),
        # null / empty / non-digit-only
        (None, None),
        ("", None),
        ("   ", None),
        ("---", None),
    ],
)
def test_to_e164(raw, expected):
    assert _to_e164(raw) == expected


def test_to_e164_custom_default_country():
    """Caller can override the default country code (e.g., '44' for UK)."""
    assert _to_e164("0207 123 4567", default_country="44") == "+442071234567"


# ─── get_or_create_customer dedup-on-format ──────────────────────────────────
def _query_chain(returns: list) -> MagicMock:
    chain = MagicMock()
    for op in ("select", "eq", "neq", "limit", "order", "upsert", "insert"):
        getattr(chain, op).return_value = chain
    chain.execute.return_value = MagicMock(data=returns)
    return chain


def _build_client(initial_customers: list[dict] | None = None) -> tuple[MagicMock, dict]:
    """Mock supabase client where customers .eq().eq().execute() returns rows
    matching the second .eq() value (the phone). Captures INSERT payloads."""
    state: dict = {
        "customers": list(initial_customers or []),
        "filters": {},
        "last_insert": None,
    }

    def _customers_chain() -> MagicMock:
        chain = MagicMock()
        # capture select cols (ignored)
        chain.select.return_value = chain

        # .neq("status", "deleted") — the dedup lookup excludes soft-deleted rows.
        def _neq(col, val):
            state.setdefault("neq_calls", []).append((col, val))
            return chain

        chain.neq.side_effect = _neq

        # .eq("org_id", X) → returns self, stores filter
        # .eq("phone"|"phone2"|"email"|"full_name", Y) → returns self, stores filter
        def _eq(col, val):
            state.setdefault("eq_calls", []).append((col, val))
            return chain

        def _limit(n):
            return chain

        def _execute():
            # Match rows against the latest single-column filter (phone, then
            # phone2, then email, then full_name), then drop any .neq() matches.
            eq_calls = state.get("eq_calls", [])
            neq_calls = state.get("neq_calls", [])
            rows = state["customers"]
            for col in ("phone", "phone2", "email", "full_name"):
                val = next((v for c, v in eq_calls if c == col), None)
                if val is not None:
                    rows = [r for r in rows if r.get(col) == val]
                    break
            else:
                rows = []
            for col, val in neq_calls:
                rows = [r for r in rows if r.get(col) != val]
            # Reset filters for the next chain
            state["eq_calls"] = []
            state["neq_calls"] = []
            return MagicMock(data=rows)

        chain.eq.side_effect = _eq
        chain.limit.side_effect = _limit
        chain.execute.side_effect = _execute

        def _insert(payload):
            state["last_insert"] = payload
            # Simulate the DB returning the inserted row with an id.
            new_row = {**payload, "id": f"cust_{len(state['customers'])}"}
            state["customers"].append(new_row)
            insert_chain = MagicMock()
            insert_chain.execute.return_value = MagicMock(data=[new_row])
            return insert_chain

        chain.insert.side_effect = _insert
        return chain

    client = MagicMock()

    def _table(name):
        return _customers_chain()

    client.table.side_effect = _table
    return client, state


def _stub_customer_number(monkeypatch):
    monkeypatch.setattr(
        "app.services.customers.gen_customer_number",
        lambda *a, **k: "K-0001",
    )


def test_get_or_create_inserts_normalized_phone(monkeypatch):
    """A new customer with a locally-formatted phone is stored in E.164."""
    _stub_customer_number(monkeypatch)
    client, state = _build_client(initial_customers=[])
    monkeypatch.setattr("app.services.customers.get_service_client", lambda: client)

    cust = get_or_create_customer("org_x", phone="0157 344 322 81", name="Luca Feder")
    assert cust["phone"] == "+49157344322 81".replace(" ", "")
    assert state["last_insert"]["phone"] == "+4915734432281"
    assert state["last_insert"]["identified_by"] == "phone"


def test_get_or_create_matches_same_number_in_different_format(monkeypatch):
    """The whole point of P0.8 — second call with same physical number
    in a different format finds the existing row, doesn't insert again."""
    _stub_customer_number(monkeypatch)
    # Seed: one customer already stored in E.164.
    seeded = [{"id": "cust_existing", "full_name": "Luca Feder", "phone": "+4915734432281"}]
    client, state = _build_client(initial_customers=seeded)
    monkeypatch.setattr("app.services.customers.get_service_client", lambda: client)

    # Caller passes the local German format.
    cust = get_or_create_customer("org_x", phone="0157 344 322 81", name="Luca Feder")
    assert cust["id"] == "cust_existing"
    assert state["last_insert"] is None, "Must NOT insert a duplicate"


def test_get_or_create_matches_international_without_plus(monkeypatch):
    """+918920100973 vs 918920100973 → same row."""
    _stub_customer_number(monkeypatch)
    seeded = [{"id": "cust_existing", "full_name": "Ambar", "phone": "+918920100973"}]
    client, state = _build_client(initial_customers=seeded)
    monkeypatch.setattr("app.services.customers.get_service_client", lambda: client)

    cust = get_or_create_customer("org_x", phone="918920100973", name="Ambar")
    assert cust["id"] == "cust_existing"
    assert state["last_insert"] is None


def test_get_or_create_no_phone_falls_back_to_name(monkeypatch):
    """When phone is missing, the existing name-based dedup still works."""
    _stub_customer_number(monkeypatch)
    seeded = [{"id": "cust_existing", "full_name": "Peter Müller", "phone": None}]
    client, state = _build_client(initial_customers=seeded)
    monkeypatch.setattr("app.services.customers.get_service_client", lambda: client)

    cust = get_or_create_customer("org_x", phone=None, name="Peter Müller")
    assert cust["id"] == "cust_existing"
    assert state["last_insert"] is None


def test_get_or_create_empty_phone_string_treated_as_no_phone(monkeypatch):
    """A blank-string phone normalizes to None; falls through to name dedup."""
    _stub_customer_number(monkeypatch)
    seeded = [{"id": "cust_existing", "full_name": "Hans", "phone": None}]
    client, state = _build_client(initial_customers=seeded)
    monkeypatch.setattr("app.services.customers.get_service_client", lambda: client)

    cust = get_or_create_customer("org_x", phone="  ", name="Hans")
    assert cust["id"] == "cust_existing"
    assert state["last_insert"] is None


def test_get_or_create_landline_no_name_matches_by_phone(monkeypatch):
    """Regression: a LANDLINE caller with NO captured name must still match the
    existing row by phone — otherwise a repeat caller gets a new row every call
    (the landline+name rule must not regress the call path)."""
    _stub_customer_number(monkeypatch)
    seeded = [{"id": "cust_existing", "full_name": "Werkstatt Müller", "phone": "+4930123456"}]
    client, state = _build_client(initial_customers=seeded)
    monkeypatch.setattr("app.services.customers.get_service_client", lambda: client)

    cust = get_or_create_customer("org_x", phone="030123456", name=None)
    assert cust["id"] == "cust_existing"
    assert state["last_insert"] is None, "Landline repeat caller must not duplicate"


def test_get_or_create_skips_soft_deleted_match(monkeypatch):
    """A soft-deleted row must NOT count as a dedup match — a returning customer
    whose record was deleted gets a fresh row instead of resurrecting the old."""
    _stub_customer_number(monkeypatch)
    seeded = [{"id": "cust_deleted", "full_name": "Alt", "phone": "+4915711122233", "status": "deleted"}]
    client, state = _build_client(initial_customers=seeded)
    monkeypatch.setattr("app.services.customers.get_service_client", lambda: client)

    cust = get_or_create_customer("org_x", phone="015711122233", name="Alt")
    assert cust["id"] != "cust_deleted"
    assert state["last_insert"] is not None, "Must insert a fresh row, not reuse the deleted one"
