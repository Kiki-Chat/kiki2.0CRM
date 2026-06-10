"""P1 outbound calling (Path A — per-call conversation override).

Rewritten from the reminder-only suite to the occasion-driven engine:

  * ``outbound_call.place_outbound_call`` — request body now carries BOTH
    dynamic_variables AND conversation_config_override in one
    conversation_initiation_client_data object (httpx faked).
  * ``outbound_occasions`` — server-side German rendering + WerkPilot variable
    schema; fallbacks; company-agnostic base; sendKVA stripped.
  * ``outbound_dispatch.run_due_outbound`` — uniform gate, selection contract,
    outbound_calls idempotency (claim + placed), dry-run, both occasions.
  * ``outbound_dispatch.send_single_outbound`` — manual/UAT trigger, to_number
    override (skips the ledger claim), not-found + no-phone + unknown-occasion.
  * endpoints — cron route secret-gated; /send maps service errors to 404 / 400.

All hermetic: no real ElevenLabs / Twilio / Supabase traffic.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import outbound as outbound_routes
from app.core.config import settings as cfg
from app.main import app
from app.services import outbound_call, outbound_dispatch, outbound_occasions
from app.services.outbound_call import OutboundCallError


# ─── fakes ───────────────────────────────────────────────────────────────────
class _FakeChain:
    """Chainable query builder; records filter calls + update/insert payloads,
    pops the next staged response (FIFO per table) on execute()."""

    def __init__(self, table: str, db: "_FakeDB"):
        self._table = table
        self._db = db
        self.filters: list[tuple] = []

    def select(self, *a, **k):
        return self

    def _flt(self, name, a):
        self.filters.append((name, a))
        return self

    def eq(self, *a, **k):
        return self._flt("eq", a)

    def neq(self, *a, **k):
        return self._flt("neq", a)

    def in_(self, *a, **k):
        return self._flt("in_", a)

    def gte(self, *a, **k):
        return self._flt("gte", a)

    def lt(self, *a, **k):
        return self._flt("lt", a)

    def lte(self, *a, **k):
        return self._flt("lte", a)

    def is_(self, *a, **k):
        return self._flt("is_", a)

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, payload):
        self._db.updates.append((self._table, payload))
        return self

    def insert(self, payload):
        self._db.inserts.append((self._table, payload))
        return self

    def execute(self):
        self._db.filter_log.setdefault(self._table, []).append(self.filters)
        rows = self._db._next(self._table)
        res = MagicMock()
        res.data = rows
        res.count = len(rows)
        return res


class _FakeDB:
    def __init__(self, responses: dict[str, list[list[dict]]]):
        self._responses = {k: list(v) for k, v in responses.items()}
        self.updates: list[tuple[str, dict]] = []
        self.inserts: list[tuple[str, dict]] = []
        self.filter_log: dict[str, list] = {}

    def _next(self, table: str) -> list[dict]:
        q = self._responses.get(table)
        return q.pop(0) if q else []

    def table(self, name: str) -> _FakeChain:
        return _FakeChain(name, self)


class _FakeResp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self._body


class _FakeHttpClient:
    def __init__(self, captured: dict, *, status_code: int = 200, body: dict | None = None):
        self._captured = captured
        self._status = status_code
        self._body = body or {"success": True, "conversation_id": "conv-1", "callSid": "CA1"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, path, headers=None, json=None):
        self._captured["path"] = path
        self._captured["headers"] = headers
        self._captured["json"] = json
        return _FakeResp(self._status, self._body)


def _patch_http(monkeypatch, captured, *, status_code=200, body=None):
    monkeypatch.setattr(
        outbound_call.httpx,
        "Client",
        lambda **kw: _FakeHttpClient(captured, status_code=status_code, body=body),
    )


def _org_user(org_id="org-1") -> deps.CurrentUser:
    return deps.CurrentUser(
        id="u1", email="a@b.de", org_id=org_id, role="org_admin", full_name=None
    )


_ORG_ROW = {
    "id": "org-1",
    "name": "Fliesen Test GmbH",
    "phone_number": "+4940000000",
    "elevenlabs_agent_id": "agent_safe",
    "elevenlabs_phone_number_id": "phnum_abc",
}
_APPT = {
    "id": "appt-1",
    "customer_id": "cust-1",
    "scheduled_at": "2026-06-01T08:30:00+00:00",  # → 10:30 Berlin (CEST)
    "title": "Wartung",
    "status": "confirmed",
}
_KVA = {
    "id": "kva-1",
    "customer_id": "cust-1",
    "number": "KVA-2026-00007",
    "subject": "Heizung",
    "total": 1234.5,
    "sent_at": "2026-05-20T09:00:00+00:00",
    "status": "sent",
    "type": "kva",
}
_CUST = {"id": "cust-1", "full_name": "Max Mustermann", "phone": "+49170111222"}


def _cfg_row(now: datetime, **over) -> dict:
    wd = outbound_dispatch._WEEKDAY_KEYS[now.astimezone(outbound_dispatch._BERLIN).weekday()]
    base = {
        "org_id": "org-1",
        "outbound_enabled": True,
        "outbound_occasions": {"appointment_reminder": True, "kva_followup": True},
        "outbound_time_from": "00:00",
        "outbound_time_to": "23:59",
        "outbound_weekdays": [wd],
        "appointment_reminder_days": 1,
        "kva_followup_days": 7,
    }
    base.update(over)
    return base


# ─── place_outbound_call: override + dynamic_variables together ──────────────
def test_place_outbound_call_carries_override_and_dynamic_vars(monkeypatch):
    captured: dict = {}
    _patch_http(monkeypatch, captured)

    override = {"agent": {"first_message": "Guten Tag", "language": "de", "prompt": {"prompt": "SYS"}}}
    out = outbound_call.place_outbound_call(
        agent_id="agent_safe",
        agent_phone_number_id="phnum_abc",
        to_number="+49170000000",
        dynamic_variables={"anlassTyp": "TERMIN_ERINNERUNG"},
        conversation_config_override=override,
    )
    assert out["conversation_id"] == "conv-1"
    body = captured["json"]
    cicd = body["conversation_initiation_client_data"]
    assert cicd["dynamic_variables"] == {"anlassTyp": "TERMIN_ERINNERUNG"}
    assert cicd["conversation_config_override"] == override
    assert captured["headers"]["xi-api-key"] == cfg.elevenlabs_api_key


def test_place_outbound_call_raises_on_non_200(monkeypatch):
    captured: dict = {}
    _patch_http(monkeypatch, captured, status_code=422, body={"detail": "bad"})
    with pytest.raises(OutboundCallError) as e:
        outbound_call.place_outbound_call(
            agent_id="a", agent_phone_number_id="p", to_number="+49170000000"
        )
    assert "422" in str(e.value)


def test_place_outbound_call_requires_phone_number_id():
    with pytest.raises(OutboundCallError) as e:
        outbound_call.place_outbound_call(
            agent_id="a", agent_phone_number_id="", to_number="+49170000000"
        )
    assert "agent_phone_number_id" in str(e.value)


# ─── occasion rendering (WerkPilot schema + German + guarantees) ─────────────
def _content(occasion_key, record, customer=_CUST, org=None):
    org = org or {"id": "org-1", "name": "Fliesen Test GmbH"}
    return outbound_occasions.build_call_content(
        outbound_occasions.OCCASIONS[occasion_key],
        record=record,
        customer=customer,
        org=org,
        outbound_call_id="ocid-1",
    )


def test_render_appointment_reminder_vars_and_text():
    c = _content("appointment_reminder", _APPT)
    dv = c["dynamic_variables"]
    # WerkPilot variable schema — IDs/occasion layer, not display strings.
    assert set(dv) == {
        "outboundCallId", "organisationId", "anlassTyp", "kundeId",
        "kundenName", "voicemailMessage", "referenzTyp", "referenzId",
    }
    assert dv["anlassTyp"] == "TERMIN_ERINNERUNG"
    assert dv["referenzTyp"] == "Termin"
    assert dv["referenzId"] == "appt-1"
    assert dv["kundeId"] == "cust-1"
    assert dv["kundenName"] == "Max Mustermann"
    assert dv["organisationId"] == "org-1"
    assert dv["outboundCallId"] == "ocid-1"
    # Dates/amounts rendered server-side, inline (the architecture shift).
    fm = c["conversation_config_override"]["agent"]["first_message"]
    assert "10:30" in fm and "Juni" in fm and "Wartung" in fm
    assert dv["voicemailMessage"].startswith("Guten Tag")
    assert c["conversation_config_override"]["agent"]["language"] == "de"


def test_render_kva_followup_vars_and_text():
    c = _content("kva_followup", _KVA)
    dv = c["dynamic_variables"]
    assert dv["anlassTyp"] == "KVA_NACHFASSEN"
    assert dv["referenzTyp"] == "KVA"
    assert dv["referenzId"] == "kva-1"
    fm = c["conversation_config_override"]["agent"]["first_message"]
    assert "KVA-2026-00007" in fm
    assert "1.234,50" in fm  # German EUR grouping
    assert "20.05.2026" in fm  # sent date
    assert "Heizung" in fm


def test_render_fallbacks_drop_optional_clauses():
    appt_no_title = {**_APPT, "title": ""}
    c = _content("appointment_reminder", appt_no_title, customer={"id": "c", "full_name": "", "phone": "x"})
    fm = c["conversation_config_override"]["agent"]["first_message"]
    assert "zum Thema" not in fm        # no title → clause dropped
    assert "Erinnerung:" in fm          # no name → colon directly after "Erinnerung"
    assert "Erinnerung für" not in fm   # salutation "für {name}" dropped

    kva_bare = {"id": "k2", "customer_id": None, "number": "", "subject": "", "total": None, "sent_at": None, "status": "sent", "type": "kva"}
    ck = _content("kva_followup", kva_bare, customer=None)
    fmk = ck["conversation_config_override"]["agent"]["first_message"]
    assert "Euro" not in fmk and "vom " not in fmk and "zum Thema" not in fmk
    assert "Kostenvoranschlag" in fmk
    assert ck["dynamic_variables"]["kundeId"] == ""


def test_override_prompt_is_company_agnostic_and_tool_filtered():
    prompt = _content("kva_followup", _KVA)["conversation_config_override"]["agent"]["prompt"]["prompt"]
    # Company fact interpolated from the org record; no reference company baked in.
    assert "Fliesen Test GmbH" in prompt
    assert "Husmann" not in prompt and "Murdock" not in prompt
    # Tool filtering: sendKVA has no hk_ equivalent → stripped; transfer via system tool.
    assert "sendKVA" not in prompt and "hk_sendKVA" not in prompt
    assert "hk_transferCall" not in prompt
    assert "transfer_to_agent" in prompt
    # hk_ tools that ARE attached are referenced.
    assert "hk_createInquiry" in prompt and "hk_getAvailableAppointments" in prompt


# ─── the uniform gate (single function, every occasion) ──────────────────────
def test_uniform_gate_branches():
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)  # Wed
    now_local = now.astimezone(outbound_dispatch._BERLIN)
    wd = outbound_dispatch._WEEKDAY_KEYS[now_local.weekday()]
    g = outbound_dispatch._passes_gate

    assert g(_cfg_row(now), "appointment_reminder", now_local, wd) is None
    assert g(_cfg_row(now), "kva_followup", now_local, wd) is None
    assert g(_cfg_row(now, outbound_enabled=False), "kva_followup", now_local, wd) == "outbound_disabled"
    # absent key ⇒ disabled ⇒ never fires
    assert g(_cfg_row(now, outbound_occasions={"appointment_reminder": True}), "kva_followup", now_local, wd) == "occasion_disabled"
    assert g(_cfg_row(now, outbound_occasions={"kva_followup": False}), "kva_followup", now_local, wd) == "occasion_disabled"
    assert g(_cfg_row(now, outbound_weekdays=["sun"]), "appointment_reminder", now_local, wd) == "weekday_excluded"
    assert g(_cfg_row(now, outbound_time_from="00:00", outbound_time_to="00:01"), "appointment_reminder", now_local, wd) == "outside_window"


# ─── run_due_outbound: happy paths + ledger idempotency ──────────────────────
def test_run_due_outbound_appointment_dispatch_and_ledger(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[_ORG_ROW]],
        "appointments": [[_APPT]],
        "outbound_calls": [[]],   # dedup pre-check: none dispatched yet
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "conv-9", "callSid": "CA9"})
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["appointment_reminder"])

    assert summary["dispatched"] == 1
    assert summary["orgs_processed"] == 1
    assert summary["calls"][0]["occasion"] == "appointment_reminder"
    assert summary["calls"][0]["referenz_id"] == "appt-1"

    kwargs = placed.call_args.kwargs
    assert kwargs["agent_id"] == "agent_safe"
    assert kwargs["to_number"] == "+49170111222"
    dv = kwargs["dynamic_variables"]
    assert dv["anlassTyp"] == "TERMIN_ERINNERUNG" and dv["referenzId"] == "appt-1"
    assert kwargs["conversation_config_override"]["agent"]["language"] == "de"

    # Ledger: claim inserted (pending) then stamped placed; outboundCallId == row id.
    ins = [p for (t, p) in db.inserts if t == "outbound_calls"]
    assert ins and ins[0]["status"] == "pending" and ins[0]["referenz_id"] == "appt-1"
    assert ins[0]["id"] == dv["outboundCallId"]
    upd = [p for (t, p) in db.updates if t == "outbound_calls"]
    assert any(u.get("status") == "placed" and u.get("conversation_id") == "conv-9" for u in upd)


def test_run_due_outbound_kva_dispatch(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[_ORG_ROW]],
        "cost_estimates": [[_KVA]],
        "outbound_calls": [[]],
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "c", "callSid": "CA"})
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["kva_followup"])
    assert summary["dispatched"] == 1
    dv = placed.call_args.kwargs["dynamic_variables"]
    assert dv["anlassTyp"] == "KVA_NACHFASSEN" and dv["referenzTyp"] == "KVA"
    assert "1.234,50" in dv["voicemailMessage"]


def test_selection_contract_appointment(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[_ORG_ROW]],
        "appointments": [[]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", MagicMock())

    outbound_dispatch.run_due_outbound(now=now, occasions=["appointment_reminder"])
    flt = db.filter_log["appointments"][0]
    names = [f[0] for f in flt]
    assert names.count("gte") == 1 and names.count("lt") == 1            # date range
    assert ("in_", ("status", ["pending", "confirmed"])) in flt


def test_selection_contract_kva(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[_ORG_ROW]],
        "cost_estimates": [[]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", MagicMock())

    outbound_dispatch.run_due_outbound(now=now, occasions=["kva_followup"])
    flt = db.filter_log["cost_estimates"][0]
    assert ("eq", ("type", "kva")) in flt
    assert ("eq", ("status", "sent")) in flt
    assert [f for f in flt if f[0] == "lte" and f[1][0] == "sent_at"]   # N-days cutoff


def test_run_due_outbound_dedup_excludes_already_dispatched(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[_ORG_ROW]],
        "appointments": [[_APPT]],
        "outbound_calls": [[{"referenz_id": "appt-1"}]],  # already has a non-failed call
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["appointment_reminder"])
    placed.assert_not_called()
    assert summary["dispatched"] == 0
    assert not [p for (t, p) in db.inserts if t == "outbound_calls"]  # no new claim


def test_run_due_outbound_dry_run_no_call_no_claim(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[_ORG_ROW]],
        "appointments": [[_APPT]],
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["appointment_reminder"], dry_run=True)
    placed.assert_not_called()
    assert summary["dispatched"] == 0
    assert summary["calls"][0]["dry_run"] is True
    assert summary["calls"][0]["dynamic_variables"]["anlassTyp"] == "TERMIN_ERINNERUNG"
    assert not db.inserts  # nothing claimed


@pytest.mark.parametrize(
    "over,reason",
    [
        ({"outbound_occasions": {"appointment_reminder": False}}, "occasion_disabled"),
        ({"outbound_time_from": "00:00", "outbound_time_to": "00:01"}, "outside_window"),
        ({"outbound_weekdays": ["sun"]}, "weekday_excluded"),
    ],
)
def test_run_due_outbound_gating_skips(monkeypatch, over, reason):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)  # Wed
    db = _FakeDB({"agent_configs": [[_cfg_row(now, **over)]]})
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["appointment_reminder"])
    placed.assert_not_called()
    assert summary["skipped"][0]["reason"] == reason
    assert summary["orgs_processed"] == 0


def test_run_due_outbound_missing_agent_identity_skips(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[{**_ORG_ROW, "elevenlabs_phone_number_id": None}]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["appointment_reminder"])
    placed.assert_not_called()
    assert summary["skipped"][0]["reason"] == "missing_agent_identity"


def test_run_due_outbound_no_phone_skipped(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[_ORG_ROW]],
        "appointments": [[_APPT]],
        "outbound_calls": [[]],
        "customers": [[{"id": "cust-1", "full_name": "No Phone", "phone": None}]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["appointment_reminder"])
    placed.assert_not_called()
    skipped = [s for s in summary["skipped"] if s.get("referenz_id") == "appt-1"]
    assert skipped and skipped[0]["reason"] == "no_phone"


# ─── send_single_outbound (manual / UAT) ─────────────────────────────────────
def test_send_single_override_dials_test_number_and_skips_ledger(monkeypatch):
    db = _FakeDB({
        "organizations": [[_ORG_ROW]],
        "appointments": [[_APPT]],
        "customers": [[{**_CUST, "phone": "+49REALCUSTOMER"}]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "c", "callSid": "CA"})
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    res = outbound_dispatch.send_single_outbound(
        org_id="org-1", occasion="appointment_reminder",
        record_id="appt-1", to_number_override="+49TESTNUMBER",
    )
    assert res["to_number"] == "+49TESTNUMBER"
    assert placed.call_args.kwargs["to_number"] == "+49TESTNUMBER"
    assert placed.call_args.kwargs["to_number"] != "+49REALCUSTOMER"
    # UAT override is repeatable → NO ledger claim written.
    assert not [p for (t, p) in db.inserts if t == "outbound_calls"]


def test_send_single_unknown_occasion_raises(monkeypatch):
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: _FakeDB({}))
    with pytest.raises(OutboundCallError) as e:
        outbound_dispatch.send_single_outbound(org_id="org-1", occasion="nope", record_id="x")
    assert "unknown occasion" in str(e.value)


def test_send_single_not_found_raises_lookuperror(monkeypatch):
    db = _FakeDB({"organizations": [[_ORG_ROW]], "appointments": [[]]})
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    with pytest.raises(LookupError):
        outbound_dispatch.send_single_outbound(
            org_id="org-1", occasion="appointment_reminder", record_id="missing"
        )


def test_send_single_no_phone_no_override_raises(monkeypatch):
    db = _FakeDB({
        "organizations": [[_ORG_ROW]],
        "appointments": [[_APPT]],
        "customers": [[{"id": "cust-1", "full_name": "X", "phone": None}]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", MagicMock())
    with pytest.raises(OutboundCallError):
        outbound_dispatch.send_single_outbound(
            org_id="org-1", occasion="appointment_reminder", record_id="appt-1"
        )


def test_send_single_missing_phone_number_id_raises(monkeypatch):
    db = _FakeDB({"organizations": [[{**_ORG_ROW, "elevenlabs_phone_number_id": None}]]})
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", MagicMock())
    with pytest.raises(OutboundCallError) as e:
        outbound_dispatch.send_single_outbound(
            org_id="org-1", occasion="appointment_reminder", record_id="appt-1"
        )
    assert "phone_number_id" in str(e.value)


# ─── endpoints ───────────────────────────────────────────────────────────────
def test_cron_endpoint_requires_secret(monkeypatch):
    monkeypatch.setattr(cfg, "master_webhook_secret", "test-secret")
    monkeypatch.setattr(cfg, "post_call_webhook_secret", "")
    monkeypatch.setattr(outbound_dispatch, "run_due_outbound", lambda **kw: {"dispatched": 0})
    client = TestClient(app)

    assert client.post("/api/outbound/run-due-reminders").status_code == 401
    ok = client.post(
        "/api/outbound/run-due-reminders", headers={"X-HeyKiki-Secret": "test-secret"}
    )
    assert ok.status_code == 200
    assert ok.json() == {"dispatched": 0}


def test_send_route_maps_lookup_to_404(monkeypatch):
    def _raise(**kw):
        raise LookupError("nope")

    monkeypatch.setattr(outbound_dispatch, "send_single_outbound", _raise)
    body = outbound_routes.SendOutboundBody(occasion="appointment_reminder", record_id="x", to_number="+4917000")
    with pytest.raises(HTTPException) as e:
        asyncio.run(outbound_routes.send_outbound(body, user=_org_user()))
    assert e.value.status_code == 404


def test_send_route_maps_outbound_error_to_400(monkeypatch):
    def _raise(**kw):
        raise OutboundCallError("config bad")

    monkeypatch.setattr(outbound_dispatch, "send_single_outbound", _raise)
    body = outbound_routes.SendOutboundBody(occasion="kva_followup", record_id="x")
    with pytest.raises(HTTPException) as e:
        asyncio.run(outbound_routes.send_outbound(body, user=_org_user()))
    assert e.value.status_code == 400


# ─── new occasion rendering (payment / satisfaction / review) ────────────────
_INV = {"id": "inv-1", "customer_id": "cust-1", "number": "RE-2026-00002", "subject": "Heizung",
        "total": 339.15, "due_date": "2026-05-15", "status": "sent", "paid_at": None, "cost_estimate_id": None}
_INQ_DONE = {"id": "inq-1", "customer_id": "cust-1", "title": "Heizung Reparatur",
             "status": "completed", "number": "ANF-1", "updated_at": "2026-05-28T10:00:00+00:00"}


def test_render_payment_reminder_soft_tone():
    c = _content("payment_reminder", _INV)
    dv = c["dynamic_variables"]
    assert dv["anlassTyp"] == "ZAHLUNGSERINNERUNG" and dv["referenzTyp"] == "Rechnung" and dv["referenzId"] == "inv-1"
    fm = c["conversation_config_override"]["agent"]["first_message"]
    assert "RE-2026-00002" in fm and "339,15" in fm and "15.05.2026" in fm and "freundlich" in fm.lower()
    sp = c["conversation_config_override"]["agent"]["prompt"]["prompt"]
    assert "KEINE Mahnung" in sp and "Mahngebühren" in sp        # soft-tone guardrails baked in
    assert "sendKVA" not in sp and "hk_transferCall" not in sp


def test_render_satisfaction_and_review():
    cs = _content("satisfaction_survey", _INQ_DONE)
    assert cs["dynamic_variables"]["anlassTyp"] == "ZUFRIEDENHEIT"
    assert cs["dynamic_variables"]["referenzTyp"] == "Vorgang" and cs["dynamic_variables"]["referenzId"] == "inq-1"
    assert "Zufriedenheit" in cs["conversation_config_override"]["agent"]["first_message"]
    cr = _content("review_request", _INQ_DONE)
    assert cr["dynamic_variables"]["anlassTyp"] == "BEWERTUNG"
    assert "Bewertung" in cr["conversation_config_override"]["agent"]["first_message"]


# ─── close-case gate ─────────────────────────────────────────────────────────
def test_close_case_gate_skips_completed_inquiry(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    appt = {**_APPT, "inquiry_id": "inq-x"}
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[_ORG_ROW]],
        "appointments": [[appt]],
        "inquiries": [[{"id": "inq-x", "status": "completed"}]],
        "outbound_calls": [[]],
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["appointment_reminder"])
    placed.assert_not_called()
    assert any(s.get("reason") == "case_closed" for s in summary["skipped"])
    assert summary["dispatched"] == 0


def test_open_case_with_inquiry_records_inquiry_id_in_claim(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    appt = {**_APPT, "inquiry_id": "inq-open"}
    db = _FakeDB({
        "agent_configs": [[_cfg_row(now)]],
        "organizations": [[_ORG_ROW]],
        "appointments": [[appt]],
        "inquiries": [[{"id": "inq-open", "status": "open"}]],
        "outbound_calls": [[]],
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "c", "callSid": "CA"})
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["appointment_reminder"])
    assert summary["dispatched"] == 1
    ins = [p for (t, p) in db.inserts if t == "outbound_calls"]
    assert ins[0]["inquiry_id"] == "inq-open" and ins[0]["cycle_no"] == 1
    assert summary["calls"][0]["inquiry_id"] == "inq-open"


# ─── payment: inquiry derived from the linked KVA ────────────────────────────
def test_payment_inquiry_derived_from_kva(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    inv = {**_INV, "cost_estimate_id": "ce-1"}
    cfg = _cfg_row(now, outbound_occasions={"payment_reminder": True}, payment_reminder_days=14)
    db = _FakeDB({
        "agent_configs": [[cfg]],
        "organizations": [[_ORG_ROW]],
        "invoices": [[inv]],
        "cost_estimates": [[{"inquiry_id": "inq-pay"}]],
        "inquiries": [[{"id": "inq-pay", "status": "open"}]],
        "outbound_calls": [[]],
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "c", "callSid": "CA"})
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["payment_reminder"])
    assert summary["dispatched"] == 1
    ins = [p for (t, p) in db.inserts if t == "outbound_calls"]
    assert ins[0]["inquiry_id"] == "inq-pay" and ins[0]["occasion"] == "payment_reminder"


# ─── cycle-based dedup (recurring) ───────────────────────────────────────────
def _pay_db(now, attempt_rows):
    cfg = _cfg_row(now, outbound_occasions={"payment_reminder": True}, payment_reminder_days=14)
    return _FakeDB({
        "agent_configs": [[cfg]],
        "organizations": [[_ORG_ROW]],
        "invoices": [[_INV]],
        "inquiries": [[]],
        # run_due_retries (topic 18) queries outbound_calls FIRST in the sweep —
        # the FakeDB ignores filters, so it must get an empty result set or it
        # would consume the attempt rows meant for _existing_attempts (and
        # re-dial them as "due retries").
        "outbound_calls": [[], attempt_rows],
        "customers": [[_CUST]],
    })


def test_payment_cooldown_skips_within_window(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(days=2)).isoformat()
    db = _pay_db(now, [{"referenz_id": "inv-1", "created_at": recent, "cycle_no": 1, "status": "placed"}])
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["payment_reminder"])
    placed.assert_not_called()
    assert any(s.get("reason") == "cooldown" for s in summary["skipped"])


def test_payment_fires_next_cycle_after_cooldown(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=20)).isoformat()
    db = _pay_db(now, [{"referenz_id": "inv-1", "created_at": old, "cycle_no": 1, "status": "placed"}])
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "c", "callSid": "CA"})
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["payment_reminder"])
    assert summary["dispatched"] == 1
    ins = [p for (t, p) in db.inserts if t == "outbound_calls"]
    assert ins[0]["cycle_no"] == 2  # advances


def test_payment_max_cycles_caps(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=60)).isoformat()
    three = [{"referenz_id": "inv-1", "created_at": old, "cycle_no": i, "status": "placed"} for i in (1, 2, 3)]
    db = _pay_db(now, three)
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["payment_reminder"])
    placed.assert_not_called()
    assert any(s.get("reason") == "max_cycles_reached" for s in summary["skipped"])


# ─── post-completion occasions + org flag ────────────────────────────────────
def test_satisfaction_fires_on_completed_inquiry(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    cfg = _cfg_row(now, outbound_occasions={"satisfaction_survey": True})
    db = _FakeDB({
        "agent_configs": [[cfg]],
        "organizations": [[_ORG_ROW]],
        "inquiries": [[_INQ_DONE]],
        "outbound_calls": [[]],
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "c", "callSid": "CA"})
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["satisfaction_survey"])
    assert summary["dispatched"] == 1
    dv = placed.call_args.kwargs["dynamic_variables"]
    assert dv["anlassTyp"] == "ZUFRIEDENHEIT" and dv["referenzId"] == "inq-1"


def test_review_skipped_when_reviews_disabled(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    cfg = _cfg_row(now, outbound_occasions={"review_request": True})
    db = _FakeDB({"agent_configs": [[cfg]], "organizations": [[{**_ORG_ROW, "google_reviews_enabled": False}]]})
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["review_request"])
    placed.assert_not_called()
    assert summary["skipped"][0]["reason"] == "org_flag_off"
    assert summary["orgs_processed"] == 0


def test_review_fires_when_enabled(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    cfg = _cfg_row(now, outbound_occasions={"review_request": True})
    db = _FakeDB({
        "agent_configs": [[cfg]],
        "organizations": [[{**_ORG_ROW, "google_reviews_enabled": True}]],
        "inquiries": [[_INQ_DONE]],
        "outbound_calls": [[]],
        "customers": [[_CUST]],
    })
    monkeypatch.setattr(outbound_dispatch, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "c", "callSid": "CA"})
    monkeypatch.setattr(outbound_dispatch, "place_outbound_call", placed)

    summary = outbound_dispatch.run_due_outbound(now=now, occasions=["review_request"])
    assert summary["dispatched"] == 1
    ins = [p for (t, p) in db.inserts if t == "outbound_calls"]
    assert ins[0]["inquiry_id"] == "inq-1"  # the inquiry IS the case
