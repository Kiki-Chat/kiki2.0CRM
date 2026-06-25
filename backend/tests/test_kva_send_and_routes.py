"""Production-readiness assurance for the KVA email-send + the round-2 routes.

The question this file answers for each mail/call trigger is the same one we'd
ask in a prod incident: *why did (or didn't) a mail go out?* Every send path
must resolve to exactly one of three outcomes:

  1. FIRES        — the send actually happens and the row is stamped 'sent'.
  2. DELIBERATELY  — a clear, asserted reason gates it (no recipient, a
     GATED          @temp.local placeholder, automation toggle off, autonomy
                    level too low). No send, no 'sent' stamp.
  3. FAILS SAFELY  — an exception in the send path (e.g. Brevo key missing) is
                    caught; the request never crashes and the KVA stays a draft.

Sections:
  A. `_send_draft_kva` internals — the gating + the catch (A is the NEW value;
     the L2/L3 wiring in test_round2_features.py already covers the caller).
  B. `draft_cost_estimate` end-to-end gating (toggle + level → send-or-not).
  C. Route-level coverage of the round-2 endpoints with a real TestClient +
     dependency_overrides. The core assertion: a failing ElevenLabs re-push
     (a BackgroundTask) must NEVER break the synchronous config save.

Hermetic: no network, no DB. `_send_draft_kva` does its imports lazily
(`from app.services.email_send import Attachment, send_email` and
`from app.services import email_templates` *inside* the function), so those are
patched on their SOURCE modules; the data helpers (fetch_customer / fetch_org /
build_pdf) are patched on the cost_estimates module where the function looks
them up.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import kiki_zentrale as kz
from app.main import app
from app.schemas.tools import DraftCostEstimateRequest
from app.services import cost_estimates as ce
from app.services import email_send, email_templates


# ─── shared fakes ─────────────────────────────────────────────────────────────
class _UpdateChain:
    """Chainable .update(payload).eq().eq().execute() recorder for the
    cost_estimates status stamp inside _send_draft_kva."""

    def __init__(self, sink: list[dict]):
        self._sink = sink

    def update(self, payload):
        self._sink.append(dict(payload))
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        return MagicMock(data=[])


class _FakeClient:
    """Minimal client: only `.table('cost_estimates').update(...)` is exercised
    by _send_draft_kva (fetch_customer / fetch_org / build_pdf are monkeypatched
    so no other table is touched). Records every status-update payload."""

    def __init__(self):
        self.status_updates: list[dict] = []

    def table(self, name: str):
        assert name == "cost_estimates", f"unexpected table {name!r}"
        return _UpdateChain(self.status_updates)


def _wire_send_helpers(monkeypatch, *, customer: dict | None, org: dict | None = None):
    """Patch the data helpers + PDF builder so _send_draft_kva runs without a DB
    or fpdf. Leaves send_email to the individual test."""
    monkeypatch.setattr(ce, "fetch_customer", lambda *a, **k: customer)
    monkeypatch.setattr(ce, "fetch_org", lambda *a, **k: org or {"name": "Muster GmbH"})
    monkeypatch.setattr(ce, "build_pdf", lambda *a, **k: b"%PDF-FAKE")
    # render_message_email is imported from email_templates inside the function.
    monkeypatch.setattr(email_templates, "render_message_email", lambda **k: "<html>kva</html>")


_ROW = {
    "id": "ce-1",
    "customer_id": "cust-1",
    "number": "KVA-2026-00001",
    "subtotal": 100.0,
    "vat_amount": 19.0,
    "total": 119.0,
    "line_items": [],
}


# ─── A. _send_draft_kva gating + safe-failure ─────────────────────────────────
def test_send_draft_kva_no_email_skips_deliberately(monkeypatch):
    """DELIBERATELY GATED: customer has no email → returns False, send_email is
    NEVER called, and the row is NOT stamped 'sent' (stays a draft)."""
    _wire_send_helpers(monkeypatch, customer={"full_name": "Max", "email": None})
    sent = MagicMock()
    monkeypatch.setattr(email_send, "send_email", sent)

    client = _FakeClient()
    out = ce._send_draft_kva(client, "org-1", _ROW)

    assert out is False
    sent.assert_not_called()
    assert client.status_updates == []  # no 'sent' stamp


def test_send_draft_kva_temp_local_email_skips_deliberately(monkeypatch):
    """DELIBERATELY GATED: a synthesized @temp.local address is never a real
    inbox → returns False, no send, no stamp."""
    _wire_send_helpers(
        monkeypatch, customer={"full_name": "Max", "email": "cust-1@temp.local"}
    )
    sent = MagicMock()
    monkeypatch.setattr(email_send, "send_email", sent)

    client = _FakeClient()
    out = ce._send_draft_kva(client, "org-1", _ROW)

    assert out is False
    sent.assert_not_called()
    assert client.status_updates == []


def test_send_draft_kva_send_raises_is_caught_stays_draft(monkeypatch):
    """FAILS SAFELY: send_email raises (e.g. Brevo API key not configured) →
    _send_draft_kva CATCHES it, returns False, and the KVA is left as a draft.
    The exception must NOT propagate (it would otherwise 500 the tool webhook)."""
    _wire_send_helpers(
        monkeypatch, customer={"full_name": "Max", "email": "max@example.de"}
    )

    def _boom(**kwargs):
        raise RuntimeError("Brevo API key not configured")

    monkeypatch.setattr(email_send, "send_email", _boom)

    client = _FakeClient()
    out = ce._send_draft_kva(client, "org-1", _ROW)  # must NOT raise

    assert out is False
    assert client.status_updates == []  # never stamped 'sent'


def test_send_draft_kva_success_stamps_sent(monkeypatch):
    """FIRES: a valid recipient + a working send_email → returns True and stamps
    status='sent' + a sent_at timestamp on the cost_estimates row."""
    _wire_send_helpers(
        monkeypatch, customer={"full_name": "Max", "email": "max@example.de"}
    )
    captured: dict = {}
    monkeypatch.setattr(email_send, "send_email", lambda **kw: captured.update(kw))

    client = _FakeClient()
    out = ce._send_draft_kva(client, "org-1", _ROW)

    assert out is True
    # The send actually targeted the customer's real inbox.
    assert captured["to_email"] == "max@example.de"
    assert captured["org_id"] == "org-1"
    assert captured["attachments"] and captured["attachments"][0].content == b"%PDF-FAKE"
    # Status stamped exactly once: 'sent' + a sent_at.
    assert len(client.status_updates) == 1
    stamp = client.status_updates[0]
    assert stamp["status"] == "sent"
    assert stamp.get("sent_at")


# ─── B. draft_cost_estimate end-to-end gating (toggle + level) ────────────────
def _draft_payload() -> DraftCostEstimateRequest:
    return DraftCostEstimateRequest(
        customerId="cust-1",
        inquiryId="inq-1",
        subject="Heizungswartung",
        positions=[{"description": "Wartung", "quantity": 1, "unit": "Pauschal",
                    "price": 120, "vat": 19}],
        notes="aus Anruf",
    )


class _DraftClient:
    """Table-routing fake: agent_configs read returns `cfg`, cost_estimates
    insert echoes the row back with an id. gen_number's count read also hits
    cost_estimates (select count) → returns count 0."""

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self.inserts: list[dict] = []

    def table(self, name: str):
        outer = self

        class _T:
            def __init__(self):
                self._insert = None

            def select(self, *a, **k):
                return self

            def eq(self, *a, **k):
                return self

            def gte(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def insert(self, row):
                self._insert = row
                return self

            def execute(self):
                if self._insert is not None:
                    outer.inserts.append(self._insert)
                    return MagicMock(data=[{**self._insert, "id": "ce-1"}])
                if name == "agent_configs":
                    return MagicMock(data=[outer._cfg], count=1)
                # cost_estimates count read inside gen_number
                return MagicMock(data=[], count=0)

        return _T()


def test_draft_cost_estimate_gated_off_no_insert(monkeypatch):
    """DELIBERATELY GATED: KVA-Automatisierung off → success=False with the
    German 'nicht aktiviert' note and NOTHING is inserted."""
    client = _DraftClient({"kva_automation_enabled": False, "kiki_level": 3})
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    # Guard: even if reached, the send helper must not run.
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: pytest.fail("must not send"))

    res = ce.draft_cost_estimate("org-1", _draft_payload())

    assert res["success"] is False
    assert "nicht aktiviert" in res["message"]
    assert client.inserts == []


def test_draft_cost_estimate_l1_hard_blocked_server_side(monkeypatch):
    """Amber's ruling 2026-06-12 (audit AUT-05): L1 = OFF for every capability.
    KVA enabled but level 1 → no draft, same 'nicht aktiviert' contract — the
    prompt is no longer the only thing preventing an L1 tool call."""
    client = _DraftClient({"kva_enabled": True, "kva_level": 1, "kiki_level": 3})
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: pytest.fail("must not send"))

    res = ce.draft_cost_estimate("org-1", _draft_payload())

    assert res["success"] is False
    assert "nicht aktiviert" in res["message"]
    assert client.inserts == []


def test_draft_cost_estimate_l2_drafts_without_send(monkeypatch):
    """L2: enabled but autonomy level 2 → a draft is created and _send_draft_kva
    is NOT called (the team reviews before anything leaves the building)."""
    client = _DraftClient({"kva_automation_enabled": True, "kiki_level": 2})
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    send_called = {"n": 0}
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: send_called.__setitem__("n", send_called["n"] + 1) or True)

    res = ce.draft_cost_estimate("org-1", _draft_payload())

    assert res["success"] is True
    assert res["status"] == "draft"
    assert send_called["n"] == 0  # gated by level
    assert len(client.inserts) == 1
    assert client.inserts[0]["status"] == "draft"


def test_draft_cost_estimate_l3_invokes_send(monkeypatch):
    """L3: enabled + autonomy level 3 → _send_draft_kva IS invoked (mocked True)
    and the returned status flips to 'sent'."""
    client = _DraftClient({"kva_automation_enabled": True, "kiki_level": 3})
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    send_args: list = []
    monkeypatch.setattr(
        ce, "_send_draft_kva",
        lambda c, org_id, row: (send_args.append((org_id, row.get("id"))), True)[1],
    )

    res = ce.draft_cost_estimate("org-1", _draft_payload())

    assert res["success"] is True
    assert res["status"] == "sent"
    assert "versendet" in res["message"]
    assert send_args == [("org-1", "ce-1")]  # called once, with the inserted row


# ─── C. Route-level tests (TestClient + dependency_overrides) ─────────────────
client = TestClient(app)


def _org_admin(org_id: str = "org-1") -> deps.CurrentUser:
    return deps.CurrentUser(
        id="user-1", email="admin@example.com", org_id=org_id,
        role="org_admin", full_name="Admin",
    )


def test_route_draft_cost_estimate_returns_service_dict(monkeypatch):
    """POST /api/elevenlabs/tools/draft-cost-estimate: resolve_tool_org is
    overridden to a fake org and the SERVICE function is monkeypatched to a
    canned dict — so no DB/network is hit and we assert the route returns 200
    with exactly the service's payload."""
    canned = {
        "success": True, "id": "ce-1", "number": "KVA-2026-00001",
        "status": "draft", "message": "Angebot wurde erstellt.",
    }
    seen: dict = {}

    def _fake_draft(org_id, payload):
        seen["org_id"] = org_id
        seen["subject"] = payload.subject
        return canned

    # The route imported draft_cost_estimate into its own module namespace.
    from app.api.routes.tools import draft_cost_estimate as route_mod
    monkeypatch.setattr(route_mod, "draft_cost_estimate", _fake_draft)
    app.dependency_overrides[deps.resolve_tool_org] = lambda: deps.ToolOrg(org_id="org-xyz")
    try:
        r = client.post(
            "/api/elevenlabs/tools/draft-cost-estimate",
            json={"customerId": "c1", "subject": "Heizung", "positions": []},
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    assert r.json() == canned
    assert seen == {"org_id": "org-xyz", "subject": "Heizung"}


def test_route_problem_description_upserts_and_does_not_block_on_push(monkeypatch):
    """PATCH /api/kiki-zentrale/problem-description: require_org overridden to an
    admin; _upsert_config + the EL re-push are monkeypatched. Asserts 200, the
    upsert received {problem_description: ...}, and the response body is the
    saved row (the deferred push neither blocks nor mangles the response)."""
    upsert_calls: list[tuple[str, dict]] = []

    def _fake_upsert(org_id, fields):
        upsert_calls.append((org_id, fields))
        return {**fields, "org_id": org_id}

    push_calls: list = []
    monkeypatch.setattr(kz, "_upsert_config", _fake_upsert)
    monkeypatch.setattr(kz.ac, "rerender_and_push_for_org", lambda **k: push_calls.append(k))
    app.dependency_overrides[deps.require_org] = lambda: _org_admin()
    try:
        r = client.patch(
            "/api/kiki-zentrale/problem-description",
            json={"problem_description": "Heizung tropft? Frage nach Modell + Baujahr."},
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    assert len(upsert_calls) == 1
    assert upsert_calls[0][1] == {
        "problem_description": "Heizung tropft? Frage nach Modell + Baujahr."
    }
    # Response carries the saved value (push is best-effort + deferred).
    assert r.json()["problem_description"] == "Heizung tropft? Frage nach Modell + Baujahr."
    # The TestClient runs BackgroundTasks after the response → push ran once,
    # but its outcome did not affect the 200 above.
    assert len(push_calls) == 1


def test_route_emergency_save_survives_push_failure(monkeypatch):
    """CORE PRODUCTION-READINESS ASSERTION — PATCH /api/kiki-zentrale/emergency:
    the synchronous DB write succeeds and the route returns 200 EVEN WHEN the
    ElevenLabs re-push raises. The push runs as a BackgroundTask AFTER the
    response is sent and is wrapped by `_repush_bg`, so an EL outage / un-
    provisioned org can never break the admin's save.

    TestClient executes BackgroundTasks synchronously after the handler returns;
    if `_repush_bg` did not swallow the error the test request would surface a
    500, so a clean 200 proves both the save AND the swallow at the route level.
    """
    saved = {"emergency_enabled": True, "emergency_number": "+4925100000000", "org_id": "org-1"}
    monkeypatch.setattr(kz, "_upsert_config", lambda org_id, fields: {**fields, "org_id": org_id})

    def _boom(**kwargs):
        raise RuntimeError("ElevenLabs push failed: agent not provisioned")

    monkeypatch.setattr(kz.ac, "rerender_and_push_for_org", _boom)
    app.dependency_overrides[deps.require_org] = lambda: _org_admin()
    try:
        r = client.patch(
            "/api/kiki-zentrale/emergency",
            json={"emergency_enabled": True, "emergency_number": "+4925100000000"},
        )
    finally:
        app.dependency_overrides.clear()

    # 200 despite the push raising → save path is decoupled from the EL push.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["emergency_enabled"] is True
    assert body["emergency_number"] == "+4925100000000"


# ─── D. send_cost_estimate (hk_sendKVA) — L3-gated re-send ────────────────────
class _SendClient:
    """Routes agent_configs read → cfg, cost_estimates select → kva_row (or none)."""

    def __init__(self, cfg: dict, kva_row: dict | None):
        self._cfg = cfg
        self._kva = kva_row

    def table(self, name: str):
        cfg, kva = self._cfg, self._kva

        class _T:
            def select(self, *a, **k):
                return self

            def eq(self, *a, **k):
                return self

            def order(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def execute(self):
                if name == "agent_configs":
                    return MagicMock(data=[cfg] if cfg else [])
                return MagicMock(data=[kva] if kva else [])

        return _T()


def _send_payload(**kw):
    from app.schemas.tools import SendCostEstimateRequest

    return SendCostEstimateRequest(**kw)


def test_send_kva_gated_below_l3(monkeypatch):
    """DELIBERATELY GATED (Amber: send only at the fully-automatic level): KVA
    level 2 → no send, success=False with the German 'Team versendet' note."""
    client = _SendClient({"kva_enabled": True, "kva_level": 2}, dict(_ROW))
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: pytest.fail("must not send below L3"))

    res = ce.send_cost_estimate("org-1", _send_payload(costEstimateId="ce-1"))

    assert res["success"] is False and "Team" in res["message"]


def test_send_kva_l3_not_found(monkeypatch):
    """L3 but no matching KVA → success=False, never reaches the send path."""
    client = _SendClient({"kva_enabled": True, "kva_level": 3}, None)
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: pytest.fail("nothing to send"))

    res = ce.send_cost_estimate("org-1", _send_payload(number="KVA-NOPE"))

    assert res["success"] is False and "nicht finden" in res["message"]


def test_send_kva_l3_no_email_asks_for_it(monkeypatch):
    """L3, KVA found, but the customer has only a @temp.local placeholder →
    success=False with needsEmail=True so the agent asks for an address."""
    client = _SendClient({"kva_enabled": True, "kva_level": 3}, dict(_ROW))
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    monkeypatch.setattr(ce, "fetch_customer", lambda *a, **k: {"email": "x@temp.local"})
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: pytest.fail("no real email"))

    res = ce.send_cost_estimate("org-1", _send_payload(customerId="cust-1"))

    assert res["success"] is False and res.get("needsEmail") is True


def test_send_kva_l3_sends(monkeypatch):
    """FIRES: L3 + found + real email → _send_draft_kva is invoked with the row,
    status flips to 'sent'."""
    client = _SendClient({"kva_enabled": True, "kva_level": 3}, dict(_ROW))
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    monkeypatch.setattr(ce, "fetch_customer", lambda *a, **k: {"email": "max@example.de"})
    sent_args: list = []
    monkeypatch.setattr(
        ce, "_send_draft_kva",
        lambda c, o, row: (sent_args.append((o, row.get("id"))), True)[1],
    )

    res = ce.send_cost_estimate("org-1", _send_payload(costEstimateId="ce-1"))

    assert res["success"] is True and res["status"] == "sent" and "versendet" in res["message"]
    assert sent_args == [("org-1", "ce-1")]


def test_send_kva_l3_send_fails_safely(monkeypatch):
    """FAILS SAFELY: L3 + found + email, but the send path returns False →
    success=False with the 'Team' fallback (never raises)."""
    client = _SendClient({"kva_enabled": True, "kva_level": 3}, dict(_ROW))
    monkeypatch.setattr(ce, "get_service_client", lambda: client)
    monkeypatch.setattr(ce, "fetch_customer", lambda *a, **k: {"email": "max@example.de"})
    monkeypatch.setattr(ce, "_send_draft_kva", lambda *a, **k: False)

    res = ce.send_cost_estimate("org-1", _send_payload(costEstimateId="ce-1"))

    assert res["success"] is False and "Team" in res["message"]


def test_route_send_cost_estimate_returns_service_dict(monkeypatch):
    """POST /api/elevenlabs/tools/send-cost-estimate returns the service dict 1:1."""
    canned = {
        "success": True, "id": "ce-1", "number": "KVA-2026-00001",
        "status": "sent", "message": "Das Angebot wurde per E-Mail versendet.",
    }
    seen: dict = {}

    def _fake_send(org_id, payload):
        seen["org_id"] = org_id
        seen["cid"] = payload.cost_estimate_id
        return canned

    from app.api.routes.tools import send_cost_estimate as route_mod
    monkeypatch.setattr(route_mod, "send_cost_estimate", _fake_send)
    app.dependency_overrides[deps.resolve_tool_org] = lambda: deps.ToolOrg(org_id="org-xyz")
    try:
        r = client.post(
            "/api/elevenlabs/tools/send-cost-estimate",
            json={"costEstimateId": "ce-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    assert r.json() == canned
    assert seen == {"org_id": "org-xyz", "cid": "ce-1"}
