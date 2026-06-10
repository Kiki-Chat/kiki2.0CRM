"""Hermetic unit tests for Kiki-Zentrale Round 2.

Covers the previously-untested round-2 logic:
  - render_autonomy_block (pure, per level)
  - appointments._get_kiki_level + book_appointment L1/L2/L3 gating
  - cost_estimates.draft_cost_estimate (kva-off no-op, L2 draft, L3 send)
  - agent_config._fetch_appointment_categories employee-name join (employees, not users)
  - post_call._fire_level3_confirmations (level gating + confirm + notify)
  - kiki_zentrale._repush_bg (delegates + swallows errors)

No network, no DB — a table-routing fake Supabase client + monkeypatches.
"""

from __future__ import annotations

from datetime import datetime, timezone

import app.services.appointment_notify as notify_mod
from app.api.routes import kiki_zentrale as kz
from app.schemas.tools import BookAppointmentRequest, DraftCostEstimateRequest
from app.services import agent_config as ac
from app.services import appointments as appt
from app.services import cost_estimates as ce
from app.services import post_call as pc
from app.services import provisioning as prov


# ─── table-routing fake Supabase client ──────────────────────────────────────
class _Result:
    def __init__(self, data):
        self.data = data
        self.count = len(data) if data else 0


class _Query:
    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._insert_rows = None

    # read-chain no-ops (return self so the chain continues)
    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def delete(self, *a, **k):
        return self

    def update(self, vals):
        self._store["updates"].append((self._table, vals))
        return self

    def insert(self, vals):
        rows = vals if isinstance(vals, list) else [vals]
        out = []
        for i, r in enumerate(rows):
            row = dict(r)
            row.setdefault("id", f"{self._table}-{i}")
            out.append(row)
        self._store["inserts"].append((self._table, rows))
        self._insert_rows = out
        return self

    def execute(self):
        if self._insert_rows is not None:
            return _Result(self._insert_rows)
        return _Result(list(self._store["reads"].get(self._table, [])))


class FakeClient:
    def __init__(self, reads=None):
        self.store = {"reads": reads or {}, "inserts": [], "updates": []}

    def table(self, name):
        return _Query(self.store, name)


# ─── render_autonomy_block (pure) ─────────────────────────────────────────────
def test_render_autonomy_block_per_level():
    l1 = ac.render_autonomy_block(1)
    l2 = ac.render_autonomy_block(2)
    l3 = ac.render_autonomy_block(3)
    assert "KEINE Termine" in l1 and "hk_createInquiry" in l1
    assert "Reservierung" in l2 and "bestätigt" in l2
    assert "verbindlich" in l3 and "direkt" in l3
    # all three are distinct guidance
    assert len({l1, l2, l3}) == 3


def test_render_autonomy_block_unknown_level_defaults_to_l2():
    assert ac.render_autonomy_block(99) == ac.render_autonomy_block(2)


# ─── _get_kiki_level ──────────────────────────────────────────────────────────
def test_get_kiki_level_reads_value():
    c = FakeClient({"agent_configs": [{"kiki_level": 3}]})
    assert appt._get_kiki_level(c, "org1") == 3


def test_get_kiki_level_defaults_to_2_when_missing():
    assert appt._get_kiki_level(FakeClient({"agent_configs": []}), "org1") == 2


# ─── book_appointment L1/L2/L3 gating ─────────────────────────────────────────
def _book_payload():
    return BookAppointmentRequest(
        date="morgen", time="10:00", name="Test Kunde", phone="+4915112345678",
        conversation_id="conv_test_1",
    )


def _wire_book(monkeypatch, level: int) -> FakeClient:
    client = FakeClient({"appointments": [], "customers": [], "agent_configs": []})
    monkeypatch.setattr(appt, "get_service_client", lambda: client)
    monkeypatch.setattr(appt, "_get_kiki_level", lambda c, o: level)
    monkeypatch.setattr(appt, "parse_when",
                        lambda d, t: datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(appt, "get_or_create_customer",
                        lambda *a, **k: {"id": "cust1", "display_name": "Test Kunde"})
    monkeypatch.setattr(appt, "_first_employee", lambda c, o: {"id": "emp1", "display_name": "Max"})
    monkeypatch.setattr(appt, "gen_inquiry_number", lambda c, o: "ANF-TEST-1")
    monkeypatch.setattr(appt, "_scheduling_rules", lambda c, o: {
        "business_hours": None, "lead_hours": 24, "lead_only_weekdays": False,
        "earliest_clock": None, "buffer_minutes": 0, "max_per_day": 0, "parallel": 1,
    })
    return client


def _appt_inserts(client: FakeClient):
    return [r for (t, r) in client.store["inserts"] if t == "appointments"]


def test_book_appointment_l1_inquiry_only_no_appointment(monkeypatch):
    client = _wire_book(monkeypatch, level=1)
    res = appt.book_appointment("org1", _book_payload())
    assert res["success"] is True
    assert res["appointmentId"] is None          # no appointment created
    assert res["inquiryId"]                       # inquiry WAS created
    assert _appt_inserts(client) == []            # zero appointment inserts


def test_book_appointment_l2_creates_pending(monkeypatch):
    client = _wire_book(monkeypatch, level=2)
    res = appt.book_appointment("org1", _book_payload())
    assert res["success"] is True
    assert res["appointmentId"] is not None
    inserts = _appt_inserts(client)
    assert len(inserts) == 1
    assert inserts[0][0]["status"] == "pending"


def test_book_appointment_l3_creates_pending_for_postcall_confirm(monkeypatch):
    client = _wire_book(monkeypatch, level=3)
    res = appt.book_appointment("org1", _book_payload())
    assert res["appointmentId"] is not None
    inserts = _appt_inserts(client)
    assert len(inserts) == 1
    # L3 still lands as 'pending'; post_call._fire_level3_confirmations confirms it.
    assert inserts[0][0]["status"] == "pending"
    assert inserts[0][0]["source_conversation_id"] == "conv_test_1"


# ─── draft_cost_estimate ──────────────────────────────────────────────────────
def _draft_payload():
    return DraftCostEstimateRequest(
        customerId="cust1", inquiryId="inq1", subject="Heizungswartung",
        positions=[{"description": "Wartung", "quantity": 1, "unit": "Pauschal",
                    "price": 120, "vat": 19}],
        notes="aus Anruf",
    )


def test_draft_cost_estimate_noop_when_kva_disabled(monkeypatch):
    client = FakeClient({"agent_configs": [{"kva_automation_enabled": False, "kiki_level": 2}]})
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    res = ce.draft_cost_estimate("org1", _draft_payload())
    assert res["success"] is False
    assert "nicht aktiviert" in res["message"]
    assert client.store["inserts"] == []          # nothing created


def test_draft_cost_estimate_l2_creates_draft_no_send(monkeypatch):
    client = FakeClient({
        "agent_configs": [{"kva_automation_enabled": True, "kiki_level": 2}],
        "cost_estimates": [],
    })
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    sent = {"called": False}
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: sent.__setitem__("called", True) or True)
    res = ce.draft_cost_estimate("org1", _draft_payload())
    assert res["success"] is True
    assert res["status"] == "draft"
    assert sent["called"] is False                # L2 must NOT send
    ce_inserts = [r for (t, r) in client.store["inserts"] if t == "cost_estimates"]
    assert len(ce_inserts) == 1
    assert ce_inserts[0][0]["status"] == "draft"


def test_draft_cost_estimate_l3_sends(monkeypatch):
    client = FakeClient({
        "agent_configs": [{"kva_automation_enabled": True, "kiki_level": 3}],
        "cost_estimates": [],
    })
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: True)   # send succeeds
    res = ce.draft_cost_estimate("org1", _draft_payload())
    assert res["success"] is True
    assert res["status"] == "sent"
    assert "versendet" in res["message"]


def test_draft_cost_estimate_l3_send_failure_stays_draft(monkeypatch):
    client = FakeClient({
        "agent_configs": [{"kva_automation_enabled": True, "kiki_level": 3}],
        "cost_estimates": [],
    })
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: False)  # send fails
    res = ce.draft_cost_estimate("org1", _draft_payload())
    assert res["success"] is True
    assert res["status"] == "draft"               # never lost; stays a draft


# ─── _fetch_appointment_categories employee-name join (employees, not users) ──
def test_fetch_categories_resolves_employee_display_name(monkeypatch):
    client = FakeClient({
        "appointment_categories": [
            {"id": "c1", "name": "Wartung", "description": "Jährlich",
             "duration_minutes": 90, "default_employee_id": "emp1", "sort_order": 0},
        ],
        "employees": [{"id": "emp1", "display_name": "Max Mustermann"}],
    })
    monkeypatch.setattr(ac, "get_service_client", lambda: client)
    cats = ac._fetch_appointment_categories("org1")
    assert cats[0]["employee_name"] == "Max Mustermann"


# ─── _fire_level3_confirmations ───────────────────────────────────────────────
class _InlineThread:
    """Run the thread target synchronously so the test can assert its effects."""
    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


def test_fire_level3_noop_when_not_level3(monkeypatch):
    client = FakeClient({
        "agent_configs": [{"kiki_level": 2}],
        "appointments": [{"id": "a1", "status": "pending"}],
    })
    monkeypatch.setattr(pc, "get_service_client", lambda: client)
    monkeypatch.setattr(pc.threading, "Thread", _InlineThread)
    calls = []
    monkeypatch.setattr(notify_mod, "notify_appointment_outcome",
                        lambda *a, **k: calls.append(a))
    pc._fire_level3_confirmations("org1", "conv1")
    assert calls == []                             # L2 → no auto-confirm
    assert client.store["updates"] == []


def test_fire_level3_confirms_and_notifies(monkeypatch):
    client = FakeClient({
        "agent_configs": [{"kiki_level": 3}],
        "appointments": [{"id": "a1", "status": "pending"}],
    })
    monkeypatch.setattr(pc, "get_service_client", lambda: client)
    monkeypatch.setattr(pc.threading, "Thread", _InlineThread)
    calls = []
    monkeypatch.setattr(notify_mod, "notify_appointment_outcome",
                        lambda *a, **k: calls.append(a))
    pc._fire_level3_confirmations("org1", "conv1")
    # flipped to confirmed + fired the confirmation
    statuses = [vals.get("status") for (t, vals) in client.store["updates"] if t == "appointments"]
    assert "confirmed" in statuses
    assert calls and calls[0][1] == "a1" and calls[0][2] == "confirm"


# ─── _repush_bg ───────────────────────────────────────────────────────────────
def test_repush_bg_delegates(monkeypatch):
    seen = {}
    monkeypatch.setattr(kz.ac, "rerender_and_push_for_org",
                        lambda **k: seen.update(k) or {"updated": True})
    kz._repush_bg("org1", "user1", "kz_categories")
    assert seen["org_id"] == "org1"
    assert seen["actor_id"] == "user1"
    assert seen["endpoint_label"] == "kz_categories"


def test_repush_bg_swallows_errors(monkeypatch):
    def _boom(**k):
        raise RuntimeError("EL down")
    monkeypatch.setattr(kz.ac, "rerender_and_push_for_org", _boom)
    kz._repush_bg("org1", "user1", "kz_emergency")   # must NOT raise


# ─── provisioning._seed_required_fields (new-org defaults) ────────────────────
def test_seed_required_fields_inserts_name_phone_address():
    client = FakeClient({"agent_required_fields": []})
    prov._seed_required_fields(client, "org1")
    inserts = [r for (t, r) in client.store["inserts"] if t == "agent_required_fields"]
    assert len(inserts) == 1
    rows = inserts[0]
    # Leitfaden rework: core fields + optional email + the three linked offer rows.
    assert {r["field_key"] for r in rows} == {
        "name", "phone", "address", "problem_description",
        "email", "offer_appointment", "offer_kva", "offer_price_info",
    }
    addr = next(r for r in rows if r["field_key"] == "address")
    assert addr["identification_role"] == "address" and addr["sort_order"] == 2
    # The customer concern is now a default required field too (locked).
    pd = next(r for r in rows if r["field_key"] == "problem_description")
    assert pd["sort_order"] == 3 and pd["is_locked"] and pd["label"].startswith("Anliegen")
    core = [r for r in rows if r["field_key"] in ("name", "phone", "address", "problem_description")]
    assert all(r["is_duty"] and r["is_locked"] for r in core)
    # Email is opt-in (inactive); linked rows carry their setting + are locked.
    email = next(r for r in rows if r["field_key"] == "email")
    assert email["is_active"] is False and not email["is_locked"]
    offer = next(r for r in rows if r["field_key"] == "offer_appointment")
    assert offer["linked_setting"] == "appointments_enabled" and offer["is_locked"]


def test_seed_required_fields_idempotent_when_rows_exist():
    client = FakeClient({"agent_required_fields": [{"id": "existing"}]})
    prov._seed_required_fields(client, "org1")
    assert [r for (t, r) in client.store["inserts"] if t == "agent_required_fields"] == []
