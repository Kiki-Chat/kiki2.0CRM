"""Integration tests for the employee-aware mode of get_available_slots — the
real-time on-call routing. Verifies that, given a routing signal (topic), Kiki
offers slots tagged with the right AVAILABLE, least-loaded competent person, skips
times when everyone competent is busy, and gates the spoken name on the toggle.

DB is faked (per-table chainable stub that ignores filters; the engine's own
Python logic does the time/employee selection)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from app.services import appointments as appt
from app.schemas.tools import GetAvailableAppointmentsRequest

BERLIN = ZoneInfo("Europe/Berlin")


def _berlin(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=BERLIN)


def emp(eid: str, area: str) -> dict:
    return {"id": eid, "display_name": eid.capitalize(), "activity_area": area,
            "auto_assign": True, "is_active": True}


def _appt(eid: str, h: int, *, day: int = 15, dur: int = 60) -> dict:
    return {"id": f"a-{eid}-{h}", "assigned_employee_id": eid,
            "scheduled_at": _berlin(2026, 7, day, h, 0).isoformat(),
            "duration_minutes": dur, "status": "confirmed"}


def _rules() -> dict:
    return {"business_hours": None, "lead_hours": 0, "lead_only_weekdays": False,
            "earliest_clock": None, "buffer_minutes": 0, "max_per_day": 0, "parallel": 1}


def _fake_client(**table_rows: list[dict]) -> MagicMock:
    def make_chain(rows: list[dict]) -> MagicMock:
        chain = MagicMock()
        for m in ("select", "eq", "neq", "in_", "gte", "lte", "lt", "order", "limit"):
            getattr(chain, m).return_value = chain
        res = MagicMock()
        res.data = rows
        chain.execute.return_value = res
        return chain

    chains = {name: make_chain(rows) for name, rows in table_rows.items()}
    client = MagicMock()
    client.table.side_effect = lambda name: chains.get(name, make_chain([]))
    return client


def _wire(monkeypatch, client, *, name_enabled: bool, now=None):
    monkeypatch.setattr(appt, "get_service_client", lambda: client)
    monkeypatch.setattr(appt, "_scheduling_rules", lambda c, o: _rules())
    monkeypatch.setattr(appt, "now_berlin", lambda: now or _berlin(2026, 7, 15, 7, 0))
    monkeypatch.setattr(appt, "_suggest_employee_enabled", lambda c, o: name_enabled)


# 2026-07-15 is a Wednesday → business day. Topic "Heizung" matches both techs.
def test_routes_slot_to_free_competent_employee(monkeypatch):
    """James booked 14:00; Steve free → the 14:00 slot is offered with Steve."""
    client = _fake_client(
        employees=[emp("steve", "Heizung"), emp("james", "Heizung")],
        appointments=[_appt("james", 14)],
    )
    _wire(monkeypatch, client, name_enabled=True)
    res = appt.get_available_slots(
        "org", GetAvailableAppointmentsRequest(days=1, durationMinutes=60, preferredTime="14:00", topic="Heizung defekt")
    )
    by_time = {s["displayTime"]: s for s in res["slots"]}
    assert by_time["14:00"]["employeeId"] == "steve"
    assert by_time["14:00"]["employeeName"] == "Steve"


def test_name_gated_off_returns_team(monkeypatch):
    """Same routing, but with the naming toggle OFF the spoken name is 'Team'
    while the employeeId still carries the real assignee for booking continuity."""
    client = _fake_client(
        employees=[emp("steve", "Heizung"), emp("james", "Heizung")],
        appointments=[_appt("james", 14)],
    )
    _wire(monkeypatch, client, name_enabled=False)
    res = appt.get_available_slots(
        "org", GetAvailableAppointmentsRequest(days=1, durationMinutes=60, preferredTime="14:00", topic="Heizung defekt")
    )
    slot = next(s for s in res["slots"] if s["displayTime"] == "14:00")
    assert slot["employeeId"] == "steve"
    assert slot["employeeName"] == "Team"


def test_slot_skipped_when_all_competent_busy(monkeypatch):
    """Both techs booked 14:00 → 14:00 is NOT offered, but 15:00 is (the 'offer a
    later time' behaviour)."""
    client = _fake_client(
        employees=[emp("steve", "Heizung"), emp("james", "Heizung")],
        appointments=[_appt("steve", 14), _appt("james", 14)],
    )
    _wire(monkeypatch, client, name_enabled=True)
    res = appt.get_available_slots(
        "org", GetAvailableAppointmentsRequest(days=1, durationMinutes=60, preferredTime="14:00", topic="Heizung defekt")
    )
    times = {s["displayTime"] for s in res["slots"]}
    assert "14:00" not in times
    assert "15:00" in times


def test_no_topic_falls_back_to_legacy_orgwide(monkeypatch):
    """Without a routing signal, behaviour is the historical org-wide one: a single
    booking at 14:00 with parallel=1 blocks 14:00 for everyone."""
    client = _fake_client(appointments=[_appt("anyone", 14)], employees=[])
    monkeypatch.setattr(appt, "get_service_client", lambda: client)
    monkeypatch.setattr(appt, "_scheduling_rules", lambda c, o: _rules())
    monkeypatch.setattr(appt, "now_berlin", lambda: _berlin(2026, 7, 15, 7, 0))
    monkeypatch.setattr(appt, "_suggest_employee_enabled", lambda c, o: False)
    monkeypatch.setattr(appt, "_first_employee", lambda c, o: None)
    res = appt.get_available_slots(
        "org", GetAvailableAppointmentsRequest(days=1, durationMinutes=60, preferredTime="14:00")
    )
    times = {s["displayTime"] for s in res["slots"]}
    assert "14:00" not in times  # org-wide parallel=1 fully booked at 14:00
    assert res["slots"][0]["employeeName"] == "Team"
