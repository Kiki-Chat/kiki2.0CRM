"""Phase 1.5 — technician dispatch availability. Dispatching a technician who is
already on another job at that time is blocked (409); the available-technicians
endpoint ranks free technicians first so the picker can show 'verplant'."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import appointments as appt_routes
from app.services import availability

BERLIN = ZoneInfo("Europe/Berlin")
_START = datetime(2026, 7, 15, 10, 0, tzinfo=BERLIN)
_END = _START + timedelta(minutes=60)


def _admin(org: str = "org-1") -> deps.CurrentUser:
    return deps.CurrentUser(id="u1", email="a@x.de", org_id=org, role="org_admin", full_name=None)


def _routing(**tables: list[dict]) -> MagicMock:
    def chain(rows: list[dict]) -> MagicMock:
        c = MagicMock()
        for m in ("select", "eq", "in_", "gte", "lte", "order", "limit"):
            getattr(c, m).return_value = c
        c.execute.return_value = MagicMock(data=rows)
        return c

    chains = {n: chain(r) for n, r in tables.items()}
    cl = MagicMock()
    cl.table.side_effect = lambda n: chains.get(n, chain([]))
    return cl


_TECH = {"id": "t1", "display_name": "Tom", "email": "t@x.de", "is_technician": True}
_APPT = {"id": "a1", "scheduled_at": _START.isoformat(), "duration_minutes": 60, "assigned_employee_id": None}


def test_dispatch_blocked_when_technician_busy(monkeypatch):
    fake = _routing(employees=[_TECH], appointments=[_APPT])
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: fake)
    monkeypatch.setattr(availability, "is_free", lambda *a, **k: False)
    # The guard must block BEFORE assignment — _patch must never run.
    monkeypatch.setattr(
        appt_routes, "_patch",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not patch")),
    )
    with pytest.raises(HTTPException) as exc:
        appt_routes._dispatch_technician(_admin(), "a1", "t1")
    assert exc.value.status_code == 409
    assert "verplant" in exc.value.detail


def test_available_technicians_ranks_available_first(monkeypatch):
    techs = [
        {"id": "t1", "display_name": "Tom", "activity_area": None, "calendar_color": None},
        {"id": "t2", "display_name": "Sara", "activity_area": None, "calendar_color": None},
    ]
    fake = _routing(appointments=[_APPT], employees=techs, case_employees=[], cases=[])
    monkeypatch.setattr(appt_routes, "get_service_client", lambda: fake)
    # t1 busy at the slot, t2 free.
    monkeypatch.setattr(availability, "load_busy_map", lambda *a, **k: {"t1": [(_START, _END)], "t2": []})
    res = appt_routes._available_technicians("org-1", "a1")
    assert [t["id"] for t in res] == ["t2", "t1"]  # available first
    assert res[0]["available"] is True and res[1]["available"] is False
