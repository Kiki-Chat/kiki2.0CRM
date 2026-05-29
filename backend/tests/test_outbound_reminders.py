"""P1 — outbound appointment-reminder calling.

Covers three layers, all hermetic (no real ElevenLabs / Twilio traffic):

  * ``outbound_call.place_outbound_call`` — request body shape + error handling
    (httpx is faked).
  * ``outbound_reminders.run_due_reminders`` — the sweep: gating (occasion /
    window / weekday / identity), selection-query contract (status + unreminded
    + date range), per-appointment dispatch + idempotent stamp, dry-run.
  * ``outbound_reminders.send_reminder_for_appointment`` — manual trigger,
    UAT to_number override, not-found + no-phone errors.
  * endpoints — cron route is secret-gated; manual route maps service errors
    to 404 / 400.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import outbound as outbound_routes
from app.core.config import settings as cfg
from app.main import app
from app.services import outbound_call, outbound_reminders
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
        # {table: [resp1, resp2, ...]} popped FIFO; exhausted -> [].
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
        self._body = body or {
            "success": True,
            "conversation_id": "conv-1",
            "callSid": "CA1",
        }

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
    "name": "Fliesen Test GmbH",
    "elevenlabs_agent_id": "agent_safe",
    "elevenlabs_phone_number_id": "phnum_abc",
}


def _cfg_row(now: datetime, **over) -> dict:
    """A config row whose window/weekday accept ``now`` by default."""
    wd = outbound_reminders._WEEKDAY_KEYS[now.astimezone(outbound_reminders._BERLIN).weekday()]
    base = {
        "org_id": "org-1",
        "outbound_enabled": True,
        "outbound_occasions": {"appointment_reminder": True},
        "outbound_time_from": "00:00",
        "outbound_time_to": "23:59",
        "outbound_weekdays": [wd],
        "appointment_reminder_days": 1,
    }
    base.update(over)
    return base


# ─── place_outbound_call ─────────────────────────────────────────────────────
def test_place_outbound_call_builds_request_and_returns_json(monkeypatch):
    captured: dict = {}
    _patch_http(monkeypatch, captured)

    out = outbound_call.place_outbound_call(
        agent_id="agent_safe",
        agent_phone_number_id="phnum_abc",
        to_number="+49170000000",
        dynamic_variables={"customer_name": "Max"},
    )
    assert out["conversation_id"] == "conv-1"
    assert out["callSid"] == "CA1"
    assert captured["path"] == "/v1/convai/twilio/outbound-call"
    assert captured["headers"]["xi-api-key"] == cfg.elevenlabs_api_key
    body = captured["json"]
    assert body["agent_id"] == "agent_safe"
    assert body["agent_phone_number_id"] == "phnum_abc"
    assert body["to_number"] == "+49170000000"
    assert body["call_recording_enabled"] is True
    assert body["conversation_initiation_client_data"]["dynamic_variables"] == {
        "customer_name": "Max"
    }


def test_place_outbound_call_raises_on_non_200(monkeypatch):
    captured: dict = {}
    _patch_http(monkeypatch, captured, status_code=422, body={"detail": "bad"})
    with pytest.raises(OutboundCallError) as e:
        outbound_call.place_outbound_call(
            agent_id="a", agent_phone_number_id="p", to_number="+49170000000"
        )
    assert "422" in str(e.value)


def test_place_outbound_call_requires_phone_number_id():
    """No HTTP attempted when the agent_phone_number_id is missing."""
    with pytest.raises(OutboundCallError) as e:
        outbound_call.place_outbound_call(
            agent_id="a", agent_phone_number_id="", to_number="+49170000000"
        )
    assert "agent_phone_number_id" in str(e.value)


# ─── run_due_reminders: happy path + selection contract ──────────────────────
def test_run_due_reminders_dispatches_and_stamps(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)  # Wed
    appt = {
        "id": "appt-1",
        "customer_id": "cust-1",
        "scheduled_at": "2026-06-01T08:30:00+00:00",
        "title": "Wartung",
        "status": "confirmed",
        "reminder_sent_at": None,
    }
    cust = {"id": "cust-1", "full_name": "Max Mustermann", "phone": "+49170111222"}
    db = _FakeDB(
        {
            "agent_configs": [[_cfg_row(now)]],
            "organizations": [[_ORG_ROW]],
            "appointments": [[appt]],  # SELECT; the later UPDATE pops [] (fine)
            "customers": [[cust]],
        }
    )
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "conv-9", "callSid": "CA9"})
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", placed)

    summary = outbound_reminders.run_due_reminders(now=now)

    assert summary["dispatched"] == 1
    assert summary["orgs_processed"] == 1
    assert summary["calls"][0]["appointment_id"] == "appt-1"
    assert summary["calls"][0]["to_number"] == "+49170111222"

    # The call carried the org identity + customer dynamic vars.
    kwargs = placed.call_args.kwargs
    assert kwargs["agent_id"] == "agent_safe"
    assert kwargs["agent_phone_number_id"] == "phnum_abc"
    assert kwargs["to_number"] == "+49170111222"
    dv = kwargs["dynamic_variables"]
    assert dv["customer_name"] == "Max Mustermann"
    assert dv["appointment_date"] == "01.06.2026"
    expected_time = (
        outbound_reminders._parse_iso(appt["scheduled_at"])
        .astimezone(outbound_reminders._BERLIN)
        .strftime("%H:%M")
    )
    assert dv["appointment_time"] == expected_time

    # Idempotent stamp written back to the appointment.
    appt_updates = [p for (t, p) in db.updates if t == "appointments"]
    assert appt_updates and appt_updates[0]["reminder_conversation_id"] == "conv-9"
    assert appt_updates[0]["reminder_call_sid"] == "CA9"
    assert appt_updates[0]["reminder_sent_at"] is not None


def test_run_due_reminders_selection_filters_status_and_unreminded(monkeypatch):
    """The appointments SELECT must constrain status IN (pending, confirmed),
    reminder_sent_at IS NULL (dedup), and a scheduled_at date range."""
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB(
        {
            "agent_configs": [[_cfg_row(now)]],
            "organizations": [[_ORG_ROW]],
            "appointments": [[]],  # none due
        }
    )
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", MagicMock())

    outbound_reminders.run_due_reminders(now=now)

    appt_filters = db.filter_log["appointments"][0]
    names = [f[0] for f in appt_filters]
    assert names.count("gte") == 1 and names.count("lt") == 1  # date range
    assert ("in_", ("status", ["pending", "confirmed"])) in appt_filters
    assert ("is_", ("reminder_sent_at", "null")) in appt_filters


def test_run_due_reminders_dry_run_places_no_call(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    appt = {
        "id": "appt-1",
        "customer_id": "cust-1",
        "scheduled_at": "2026-06-01T08:30:00+00:00",
        "title": "Wartung",
        "status": "confirmed",
        "reminder_sent_at": None,
    }
    db = _FakeDB(
        {
            "agent_configs": [[_cfg_row(now)]],
            "organizations": [[_ORG_ROW]],
            "appointments": [[appt]],
            "customers": [[{"id": "cust-1", "full_name": "Max", "phone": "+4917000"}]],
        }
    )
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", placed)

    summary = outbound_reminders.run_due_reminders(now=now, dry_run=True)
    placed.assert_not_called()
    assert summary["dispatched"] == 0
    assert summary["calls"][0]["dry_run"] is True
    assert not db.updates  # nothing stamped


# ─── run_due_reminders: gating ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "over,reason",
    [
        ({"outbound_occasions": {"appointment_reminder": False}}, "occasion_disabled"),
        ({"outbound_time_from": "00:00", "outbound_time_to": "00:01"}, "outside_window"),
    ],
)
def test_run_due_reminders_gating_skips(monkeypatch, over, reason):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    db = _FakeDB({"agent_configs": [[_cfg_row(now, **over)]]})
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", placed)

    summary = outbound_reminders.run_due_reminders(now=now)
    placed.assert_not_called()
    assert summary["skipped"][0]["reason"] == reason
    assert summary["orgs_processed"] == 0


def test_run_due_reminders_weekday_excluded(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)  # Wed
    db = _FakeDB({"agent_configs": [[_cfg_row(now, outbound_weekdays=["sun"])]]})
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", placed)

    summary = outbound_reminders.run_due_reminders(now=now)
    placed.assert_not_called()
    assert summary["skipped"][0]["reason"] == "weekday_excluded"


def test_run_due_reminders_skips_when_phone_number_id_missing(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    org_no_phone = {**_ORG_ROW, "elevenlabs_phone_number_id": None}
    db = _FakeDB(
        {"agent_configs": [[_cfg_row(now)]], "organizations": [[org_no_phone]]}
    )
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", placed)

    summary = outbound_reminders.run_due_reminders(now=now)
    placed.assert_not_called()
    assert summary["skipped"][0]["reason"] == "missing_agent_identity"


def test_run_due_reminders_appointment_without_phone_skipped(monkeypatch):
    now = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
    appt = {
        "id": "appt-1",
        "customer_id": "cust-1",
        "scheduled_at": "2026-06-01T08:30:00+00:00",
        "title": "Wartung",
        "status": "confirmed",
        "reminder_sent_at": None,
    }
    db = _FakeDB(
        {
            "agent_configs": [[_cfg_row(now)]],
            "organizations": [[_ORG_ROW]],
            "appointments": [[appt]],
            "customers": [[{"id": "cust-1", "full_name": "No Phone", "phone": None}]],
        }
    )
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    placed = MagicMock()
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", placed)

    summary = outbound_reminders.run_due_reminders(now=now)
    placed.assert_not_called()
    skipped = [s for s in summary["skipped"] if s.get("appointment_id") == "appt-1"]
    assert skipped and skipped[0]["reason"] == "no_phone"


# ─── send_reminder_for_appointment (manual / UAT) ────────────────────────────
def test_send_reminder_override_dials_test_number_not_customer(monkeypatch):
    """UAT safety: with a to_number override, the override is dialled and the
    customer's real stored phone is NOT used."""
    appt = {
        "id": "appt-1",
        "customer_id": "cust-1",
        "scheduled_at": "2026-06-01T08:30:00+00:00",
        "title": "Wartung",
        "status": "confirmed",
        "reminder_sent_at": None,
    }
    cust = {"id": "cust-1", "full_name": "Real Customer", "phone": "+49REALCUSTOMER"}
    db = _FakeDB(
        {
            "appointments": [[appt]],
            "organizations": [[_ORG_ROW]],
            "customers": [[cust]],
        }
    )
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    placed = MagicMock(return_value={"success": True, "conversation_id": "c", "callSid": "CA"})
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", placed)

    res = outbound_reminders.send_reminder_for_appointment(
        org_id="org-1", appointment_id="appt-1", to_number_override="+49TESTNUMBER"
    )
    assert res["to_number"] == "+49TESTNUMBER"
    assert placed.call_args.kwargs["to_number"] == "+49TESTNUMBER"
    assert placed.call_args.kwargs["to_number"] != cust["phone"]


def test_send_reminder_not_found_raises_lookuperror(monkeypatch):
    db = _FakeDB({"appointments": [[]]})
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    with pytest.raises(LookupError):
        outbound_reminders.send_reminder_for_appointment(
            org_id="org-1", appointment_id="missing"
        )


def test_send_reminder_no_phone_no_override_raises(monkeypatch):
    appt = {
        "id": "appt-1",
        "customer_id": "cust-1",
        "scheduled_at": "2026-06-01T08:30:00+00:00",
        "title": "X",
        "status": "confirmed",
        "reminder_sent_at": None,
    }
    db = _FakeDB(
        {
            "appointments": [[appt]],
            "organizations": [[_ORG_ROW]],
            "customers": [[{"id": "cust-1", "full_name": "X", "phone": None}]],
        }
    )
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", MagicMock())
    with pytest.raises(OutboundCallError):
        outbound_reminders.send_reminder_for_appointment(
            org_id="org-1", appointment_id="appt-1"
        )


def test_send_reminder_missing_phone_number_id_raises(monkeypatch):
    appt = {
        "id": "appt-1",
        "customer_id": "cust-1",
        "scheduled_at": "2026-06-01T08:30:00+00:00",
        "title": "X",
        "status": "confirmed",
        "reminder_sent_at": None,
    }
    db = _FakeDB(
        {
            "appointments": [[appt]],
            "organizations": [[{**_ORG_ROW, "elevenlabs_phone_number_id": None}]],
        }
    )
    monkeypatch.setattr(outbound_reminders, "get_service_client", lambda: db)
    monkeypatch.setattr(outbound_reminders, "place_outbound_call", MagicMock())
    with pytest.raises(OutboundCallError) as e:
        outbound_reminders.send_reminder_for_appointment(
            org_id="org-1", appointment_id="appt-1"
        )
    assert "phone_number_id" in str(e.value)


# ─── endpoints ───────────────────────────────────────────────────────────────
def test_cron_endpoint_requires_secret(monkeypatch):
    monkeypatch.setattr(cfg, "master_webhook_secret", "test-secret")
    monkeypatch.setattr(cfg, "post_call_webhook_secret", "")
    monkeypatch.setattr(
        outbound_reminders, "run_due_reminders", lambda **kw: {"dispatched": 0}
    )
    client = TestClient(app)

    assert client.post("/api/outbound/run-due-reminders").status_code == 401
    ok = client.post(
        "/api/outbound/run-due-reminders",
        headers={"X-HeyKiki-Secret": "test-secret"},
    )
    assert ok.status_code == 200
    assert ok.json() == {"dispatched": 0}


def test_send_reminder_route_maps_lookup_to_404(monkeypatch):
    def _raise(**kw):
        raise LookupError("nope")

    monkeypatch.setattr(outbound_reminders, "send_reminder_for_appointment", _raise)
    body = outbound_routes.SendReminderBody(to_number="+4917000")
    with pytest.raises(HTTPException) as e:
        asyncio.run(outbound_routes.send_reminder("appt-x", body, user=_org_user()))
    assert e.value.status_code == 404


def test_send_reminder_route_maps_outbound_error_to_400(monkeypatch):
    def _raise(**kw):
        raise OutboundCallError("config bad")

    monkeypatch.setattr(outbound_reminders, "send_reminder_for_appointment", _raise)
    body = outbound_routes.SendReminderBody()
    with pytest.raises(HTTPException) as e:
        asyncio.run(outbound_routes.send_reminder("appt-x", body, user=_org_user()))
    assert e.value.status_code == 400
