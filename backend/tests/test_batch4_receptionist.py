"""Batch 4 — receptionist correctness (mock DB).

Covers:
  4.1  identify.py phone lookup also matches phone2 (CUST-014).
  4.2  identify response carries bounded OPEN-case context for a known customer.
  4.3  knowledge.py answers price questions from the catalog when Preisauskunft is
       ON, and returns an honest no-answer (not a dead stub) otherwise.
  4.4  record_missed_call writer inserts a missed_calls row (idempotent), and the
       missed-inbound detector flags only genuinely-abandoned inbound calls — that
       single row is what the existing `callback_owed` Open Action consumes.

All DB access is mocked; no network, no real Supabase.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.tools import IdentifyCustomerRequest, QueryKnowledgeBaseRequest
from app.services import identify as identify_mod
from app.services import knowledge as knowledge_mod
from app.services import post_call as post_call_mod


# ─────────────────────────────────────────────────────────────────────────────
# Generic table-aware mock client
# ─────────────────────────────────────────────────────────────────────────────
class _Query:
    """A chainable PostgREST-style query over an in-memory table.

    Supports the subset used by the code under test: select / eq / neq / ilike /
    gt / not_.in_ / order / limit / execute / insert. Filters AND together.
    """

    def __init__(self, store: "_Store", table: str):
        self._store = store
        self._table = table
        self._eq: list[tuple[str, object]] = []
        self._neq: list[tuple[str, object]] = []
        self._gt: list[tuple[str, float]] = []
        self._not_in: list[tuple[str, list]] = []
        self._ilike: list[tuple[str, str]] = []
        self._limit_n: int | None = None
        self._pending_not = False

    # filter builders -------------------------------------------------------
    def select(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit_n = n
        return self

    def eq(self, col, val):
        self._eq.append((col, val))
        return self

    def neq(self, col, val):
        self._neq.append((col, val))
        return self

    def gt(self, col, val):
        self._gt.append((col, val))
        return self

    def ilike(self, col, pattern):
        self._ilike.append((col, pattern.strip("%").lower()))
        return self

    @property
    def not_(self):
        self._pending_not = True
        return self

    def in_(self, col, values):
        if self._pending_not:
            self._not_in.append((col, list(values)))
            self._pending_not = False
        else:  # plain .in_ — not exercised here, but keep it sane
            self._eq.append((col, ("__in__", list(values))))
        return self

    def is_(self, col, val):  # pragma: no cover - not used by these tests
        self._pending_not = False
        return self

    # terminal --------------------------------------------------------------
    def _match(self, row: dict) -> bool:
        for col, val in self._eq:
            if isinstance(val, tuple) and val and val[0] == "__in__":
                if row.get(col) not in val[1]:
                    return False
            elif row.get(col) != val:
                return False
        for col, val in self._neq:
            if row.get(col) == val:
                return False
        for col, val in self._gt:
            try:
                if not (float(row.get(col)) > float(val)):
                    return False
            except (TypeError, ValueError):
                return False
        for col, values in self._not_in:
            if row.get(col) in values:
                return False
        for col, frag in self._ilike:
            if frag not in (str(row.get(col) or "").lower()):
                return False
        return True

    def execute(self):
        rows = [r for r in self._store.tables.get(self._table, []) if self._match(r)]
        if self._limit_n is not None:
            rows = rows[: self._limit_n]
        return SimpleNamespace(data=[dict(r) for r in rows])

    def insert(self, payload):
        self._store.inserts.setdefault(self._table, []).append(payload)
        new = {"id": f"{self._table}_{len(self._store.tables.get(self._table, []))}", **payload}
        self._store.tables.setdefault(self._table, []).append(new)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[new]))


class _Store:
    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables = {k: list(v) for k, v in (tables or {}).items()}
        self.inserts: dict[str, list[dict]] = {}

    def client(self) -> MagicMock:
        c = MagicMock()
        c.table.side_effect = lambda name: _Query(self, name)
        return c


# ─────────────────────────────────────────────────────────────────────────────
# 4.1 — phone2 match
# ─────────────────────────────────────────────────────────────────────────────
def test_identify_matches_phone2(monkeypatch):
    """A known customer calling from their SECONDARY number (stored in phone2)
    is identified, not treated as a new caller."""
    store = _Store(
        {
            "customers": [
                {
                    "id": "cust_1",
                    "org_id": "org_x",
                    "full_name": "Luca Feder",
                    "phone": "+4915111111111",
                    "phone2": "+4915722222222",
                    "email": None,
                    "customer_number": "K-0001",
                    "address": None,
                }
            ],
            "inquiries": [],
            "cases": [],
        }
    )
    client = store.client()
    monkeypatch.setattr(identify_mod, "get_service_client", lambda: client)

    # Caller-ID is the secondary number, in a different (local) format.
    payload = IdentifyCustomerRequest(phoneNumber="0157 222 22222")
    out = identify_mod.identify_customer("org_x", payload)
    assert out["status"] == "EXISTING_CUSTOMER"
    assert out["customerId"] == "cust_1"


def test_identify_still_matches_primary_phone(monkeypatch):
    """Primary-phone match path is unchanged by the phone2 addition."""
    store = _Store(
        {
            "customers": [
                {
                    "id": "cust_1",
                    "org_id": "org_x",
                    "full_name": "Luca Feder",
                    "phone": "+4915111111111",
                    "phone2": None,
                    "customer_number": "K-0001",
                    "address": None,
                    "email": None,
                }
            ],
            "inquiries": [],
            "cases": [],
        }
    )
    client = store.client()
    monkeypatch.setattr(identify_mod, "get_service_client", lambda: client)

    payload = IdentifyCustomerRequest(phoneNumber="+4915111111111")
    out = identify_mod.identify_customer("org_x", payload)
    assert out["status"] == "EXISTING_CUSTOMER"
    assert out["customerId"] == "cust_1"


def test_identify_unknown_number_is_new(monkeypatch):
    """An unknown number (neither phone nor phone2) → NEW_CUSTOMER."""
    store = _Store(
        {
            "customers": [
                {"id": "cust_1", "org_id": "org_x", "phone": "+4915111111111",
                 "phone2": "+4915722222222"}
            ],
            "inquiries": [],
            "cases": [],
        }
    )
    client = store.client()
    monkeypatch.setattr(identify_mod, "get_service_client", lambda: client)

    payload = IdentifyCustomerRequest(phoneNumber="+4915799999999")
    out = identify_mod.identify_customer("org_x", payload)
    assert out["status"] == "NEW_CUSTOMER"
    assert out["customerId"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 4.2 — open-case context on identify
# ─────────────────────────────────────────────────────────────────────────────
def test_identify_includes_open_inquiries(monkeypatch):
    """A known customer's OPEN inquiries are attached (bounded, newest first) so the
    agent can disambiguate 'which case?'."""
    store = _Store(
        {
            "customers": [
                {
                    "id": "cust_1",
                    "org_id": "org_x",
                    "full_name": "Luca Feder",
                    "phone": "+4915111111111",
                    "phone2": None,
                    "customer_number": "K-0001",
                    "address": None,
                    "email": None,
                }
            ],
            "inquiries": [
                {
                    "number": "ANF-1",
                    "title": "Heizung tropft",
                    "status": "open",
                    "customer_id": "cust_1",
                    "org_id": "org_x",
                    "created_at": "2026-06-01T10:00:00Z",
                },
                {
                    "number": "ANF-2",
                    "title": "Alter Auftrag",
                    "status": "completed",  # closed → must be EXCLUDED
                    "customer_id": "cust_1",
                    "org_id": "org_x",
                    "created_at": "2026-05-01T10:00:00Z",
                },
            ],
            "cases": [],
        }
    )
    client = store.client()
    monkeypatch.setattr(identify_mod, "get_service_client", lambda: client)

    payload = IdentifyCustomerRequest(phoneNumber="+4915111111111")
    out = identify_mod.identify_customer("org_x", payload)
    assert out["status"] == "EXISTING_CUSTOMER"
    assert "openCases" in out
    nums = {i["number"] for i in out["openCases"]}
    assert nums == {"ANF-1"}  # completed inquiry excluded
    item = out["openCases"][0]
    assert set(item.keys()) == {"number", "title", "status"}
    assert item["title"] == "Heizung tropft"
    # Compact summary is read back to the caller.
    assert "Heizung tropft" in out["message"]


def test_identify_open_context_bounded_to_five(monkeypatch):
    """Never floods the response — capped at 5 open items."""
    store = _Store(
        {
            "customers": [
                {"id": "cust_1", "org_id": "org_x", "full_name": "X",
                 "phone": "+4915111111111", "phone2": None,
                 "customer_number": "K", "address": None, "email": None}
            ],
            "inquiries": [
                {
                    "number": f"ANF-{i}",
                    "title": f"Sache {i}",
                    "status": "open",
                    "customer_id": "cust_1",
                    "org_id": "org_x",
                    "created_at": f"2026-06-{i:02d}T10:00:00Z",
                }
                for i in range(1, 9)  # 8 open inquiries
            ],
            "cases": [],
        }
    )
    client = store.client()
    monkeypatch.setattr(identify_mod, "get_service_client", lambda: client)

    out = identify_mod.identify_customer(
        "org_x", IdentifyCustomerRequest(phoneNumber="+4915111111111")
    )
    assert len(out["openCases"]) == identify_mod._OPEN_CONTEXT_LIMIT == 5


def test_identify_falls_back_to_open_cases(monkeypatch):
    """No open inquiries but an open CASE → the case is surfaced."""
    store = _Store(
        {
            "customers": [
                {"id": "cust_1", "org_id": "org_x", "full_name": "X",
                 "phone": "+4915111111111", "phone2": None,
                 "customer_number": "K", "address": None, "email": None}
            ],
            "inquiries": [],
            "cases": [
                {
                    "number": "FL-9",
                    "title": "Badsanierung",
                    "status": "active",
                    "customer_id": "cust_1",
                    "org_id": "org_x",
                    "created_at": "2026-06-01T10:00:00Z",
                },
                {
                    "number": "FL-OLD",
                    "title": "Altfall",
                    "status": "completed",  # excluded
                    "customer_id": "cust_1",
                    "org_id": "org_x",
                    "created_at": "2026-01-01T10:00:00Z",
                },
            ],
        }
    )
    client = store.client()
    monkeypatch.setattr(identify_mod, "get_service_client", lambda: client)

    out = identify_mod.identify_customer(
        "org_x", IdentifyCustomerRequest(phoneNumber="+4915111111111")
    )
    assert [i["number"] for i in out["openCases"]] == ["FL-9"]


# ─────────────────────────────────────────────────────────────────────────────
# 4.3 — queryKnowledgeBase
# ─────────────────────────────────────────────────────────────────────────────
def test_knowledge_price_question_returns_catalog_price(monkeypatch):
    """Preisauskunft ON + a price question matching a catalog item → a Richtpreis."""
    store = _Store(
        {
            "agent_configs": [{"org_id": "org_x", "price_info_enabled": True}],
            "catalog_items": [
                {"org_id": "org_x", "name": "Heizungswartung", "unit_price": 120,
                 "unit": "pauschal", "is_active": True, "description": None},
                {"org_id": "org_x", "name": "Rohrreinigung", "unit_price": 90,
                 "unit": "Stunde", "is_active": True, "description": None},
            ],
        }
    )
    client = store.client()
    monkeypatch.setattr(knowledge_mod, "get_service_client", lambda: client)

    out = knowledge_mod.query_knowledge_base(
        "org_x", QueryKnowledgeBaseRequest(question="Was kostet eine Heizungswartung?")
    )
    assert out["success"] is True
    assert out["source"] == "price_catalog"
    assert out["answer"] is not None
    assert "Heizungswartung" in out["answer"]
    assert "120,00" in out["message"]
    assert out["followUp"] is False


def test_knowledge_price_question_toggle_off_no_price(monkeypatch):
    """Preisauskunft OFF → never quote a price; honest no-answer instead."""
    store = _Store(
        {
            "agent_configs": [{"org_id": "org_x", "price_info_enabled": False}],
            "catalog_items": [
                {"org_id": "org_x", "name": "Heizungswartung", "unit_price": 120,
                 "unit": "pauschal", "is_active": True}
            ],
        }
    )
    client = store.client()
    monkeypatch.setattr(knowledge_mod, "get_service_client", lambda: client)

    out = knowledge_mod.query_knowledge_base(
        "org_x", QueryKnowledgeBaseRequest(question="Was kostet eine Heizungswartung?")
    )
    assert out["answer"] is None
    assert out["source"] == "none"
    assert out["followUp"] is True


def test_knowledge_non_price_question_is_honest_no_answer(monkeypatch):
    """A non-price question is served by the native EL KB (primary); this backend
    fallback returns an HONEST structured no-answer, NOT a dead stub."""
    # No DB access expected — but provide a client so a stray call wouldn't crash.
    store = _Store({"agent_configs": [{"org_id": "org_x", "price_info_enabled": True}]})
    client = store.client()
    monkeypatch.setattr(knowledge_mod, "get_service_client", lambda: client)

    out = knowledge_mod.query_knowledge_base(
        "org_x", QueryKnowledgeBaseRequest(question="Habt ihr am Samstag geöffnet?")
    )
    assert out["answer"] is None
    assert out["source"] == "none"
    assert out["followUp"] is True
    # Honest: acknowledges the question and promises a colleague follow-up.
    assert "Kollege" in out["message"]


def test_knowledge_empty_question_is_no_answer(monkeypatch):
    store = _Store({})
    monkeypatch.setattr(knowledge_mod, "get_service_client", lambda: store.client())
    out = knowledge_mod.query_knowledge_base("org_x", QueryKnowledgeBaseRequest(question="  "))
    assert out["answer"] is None
    assert out["followUp"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 4.4 — missed-calls writer + detection
# ─────────────────────────────────────────────────────────────────────────────
def test_record_missed_call_inserts_row():
    store = _Store({"missed_calls": []})
    client = store.client()
    rid = post_call_mod.record_missed_call(
        client, "org_x", caller_number="+4915700000000", customer_id="cust_1",
        missed_at="2026-06-17T08:00:00Z",
    )
    assert rid is not None
    inserted = store.inserts["missed_calls"][0]
    assert inserted["org_id"] == "org_x"
    assert inserted["caller_number"] == "+4915700000000"
    assert inserted["status"] == "pending"
    assert inserted["customer_id"] == "cust_1"
    assert inserted["missed_at"] == "2026-06-17T08:00:00Z"


def test_record_missed_call_is_idempotent_for_pending_caller():
    """A still-pending callback for the same caller is reused, not duplicated."""
    store = _Store(
        {
            "missed_calls": [
                {"id": "mc_existing", "org_id": "org_x",
                 "caller_number": "+4915700000000", "status": "pending"}
            ]
        }
    )
    client = store.client()
    rid = post_call_mod.record_missed_call(
        client, "org_x", caller_number="+4915700000000",
    )
    assert rid == "mc_existing"
    assert "missed_calls" not in store.inserts  # no new insert


def test_is_missed_inbound_flags_short_abandoned_call():
    assert post_call_mod._is_missed_inbound(
        "inbound",
        caller_number="+4915700000000",
        duration_seconds=4,
        trimmed=[{"role": "agent", "message": "Guten Tag, hier ist Kiki."}],
        summary=None,
        customer_concern=False,
        call_successful="unknown",
    ) is True


def test_is_missed_inbound_flags_failed_call():
    assert post_call_mod._is_missed_inbound(
        "inbound",
        caller_number="+4915700000000",
        duration_seconds=40,  # not short
        trimmed=[],
        summary=None,
        customer_concern=False,
        call_successful="failure",
    ) is True


def test_is_missed_inbound_ignores_handled_call():
    """A call that captured a concern (or any caller turn) is NOT missed."""
    # captured concern
    assert post_call_mod._is_missed_inbound(
        "inbound", caller_number="+4915700000000", duration_seconds=4,
        trimmed=[], summary=None, customer_concern=True, call_successful="failure",
    ) is False
    # caller actually spoke
    assert post_call_mod._is_missed_inbound(
        "inbound", caller_number="+4915700000000", duration_seconds=4,
        trimmed=[{"role": "user", "message": "Meine Heizung ist kaputt"}],
        summary=None, customer_concern=False, call_successful="failure",
    ) is False
    # has a summary
    assert post_call_mod._is_missed_inbound(
        "inbound", caller_number="+4915700000000", duration_seconds=4,
        trimmed=[], summary="Kunde meldet Wasserschaden", customer_concern=False,
        call_successful="failure",
    ) is False


def test_is_missed_inbound_ignores_outbound_and_no_number():
    assert post_call_mod._is_missed_inbound(
        "outbound", caller_number="+4915700000000", duration_seconds=2,
        trimmed=[], summary=None, customer_concern=False, call_successful="failure",
    ) is False
    assert post_call_mod._is_missed_inbound(
        "inbound", caller_number=None, duration_seconds=2,
        trimmed=[], summary=None, customer_concern=False, call_successful="failure",
    ) is False


def test_is_missed_inbound_long_engaged_call_not_missed():
    """A normal-length inbound call with no failure signal is NOT flagged."""
    assert post_call_mod._is_missed_inbound(
        "inbound", caller_number="+4915700000000", duration_seconds=90,
        trimmed=[], summary=None, customer_concern=False, call_successful="success",
    ) is False
