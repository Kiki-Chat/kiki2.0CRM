"""Track A, Phase 2 — two-stage scheduling (employee↔technician split).

Covers the new services/jobs.py: the flag gate, the technician pool with its
department→activity_area→any-active fallback chain, the selection ladder
(continuity → workload → preference → name), and dispatch-on-confirm.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from app.services import jobs

BERLIN = ZoneInfo("Europe/Berlin")
_START = datetime(2026, 7, 15, 10, 0, tzinfo=BERLIN)
_END = _START + timedelta(minutes=60)


def _routing(**tables: list[dict]) -> MagicMock:
    def chain(rows: list[dict]) -> MagicMock:
        c = MagicMock()
        for m in ("select", "eq", "in_", "gte", "lte", "order", "limit", "insert", "update"):
            getattr(c, m).return_value = c
        c.execute.return_value = MagicMock(data=rows)
        return c

    chains = {n: chain(r) for n, r in tables.items()}
    cl = MagicMock()
    cl.table.side_effect = lambda n: chains.get(n, chain([]))
    return cl


# ── flag gate ───────────────────────────────────────────────────────────────

def test_two_stage_enabled_reads_flag():
    on = _routing(agent_configs=[{"scheduling_two_stage_enabled": True}])
    off = _routing(agent_configs=[{"scheduling_two_stage_enabled": False}])
    missing = _routing(agent_configs=[])
    assert jobs.two_stage_enabled(on, "org-1") is True
    assert jobs.two_stage_enabled(off, "org-1") is False
    assert jobs.two_stage_enabled(missing, "org-1") is False


def test_two_stage_enabled_missing_column_is_off():
    cl = MagicMock()
    cl.table.side_effect = RuntimeError("column does not exist")
    assert jobs.two_stage_enabled(cl, "org-1") is False


# ── the ladder (pure) ─────────────────────────────────────────────────────────

_T1 = {"id": "t1", "display_name": "Anton"}
_T2 = {"id": "t2", "display_name": "Berta"}
_T3 = {"id": "t3", "display_name": "Cesar"}
_ALL_FREE = {"t1": [], "t2": [], "t3": []}


def test_ladder_busy_filtered_out():
    # t1 busy at the slot → only t2 is eligible.
    busy = {"t1": [(_START, _END)], "t2": []}
    pick = jobs.pick_technician_ladder([_T1, _T2], busy, {}, start=_START, end=_END)
    assert pick["id"] == "t2"


def test_ladder_continuity_wins_over_workload():
    # t1 has MORE open jobs but is the continuity tech → still wins.
    pick = jobs.pick_technician_ladder(
        [_T1, _T2], _ALL_FREE, {"t1": 5, "t2": 0}, start=_START, end=_END, continuity_id="t1"
    )
    assert pick["id"] == "t1"


def test_ladder_workload_breaks_tie_when_no_continuity():
    pick = jobs.pick_technician_ladder(
        [_T1, _T2, _T3], _ALL_FREE, {"t1": 2, "t2": 0, "t3": 1}, start=_START, end=_END
    )
    assert pick["id"] == "t2"  # fewest open jobs


def test_ladder_preference_after_workload():
    # equal workload → customer preference (t3) wins over name order.
    pick = jobs.pick_technician_ladder(
        [_T1, _T2, _T3], _ALL_FREE, {}, start=_START, end=_END, preferred_id="t3"
    )
    assert pick["id"] == "t3"


def test_ladder_name_is_final_tiebreak():
    pick = jobs.pick_technician_ladder([_T2, _T1], _ALL_FREE, {}, start=_START, end=_END)
    assert pick["id"] == "t1"  # Anton < Berta


def test_ladder_none_when_all_busy():
    busy = {"t1": [(_START, _END)], "t2": [(_START, _END)]}
    assert jobs.pick_technician_ladder([_T1, _T2], busy, {}, start=_START, end=_END) is None


# ── technician pool fallback chain ────────────────────────────────────────────

def _emp(id, name, *, tech=True, wk=None, area=None):
    return {
        "id": id, "display_name": name,
        "is_technician": tech, "worker_kind": wk,
        "activity_area": area, "is_active": True, "auto_assign": True,
    }


def test_pool_prefers_department_members():
    techs = [_emp("t1", "Anton", area="heizung"), _emp("t2", "Berta", area="rohre")]
    cl = _routing(
        employees=techs,
        employee_departments=[{"employee_id": "t2"}],  # only t2 is in the dept
    )
    pool = jobs.technician_pool(cl, "org-1", department_id="d-rohre", category_name="Rohrbruch", summary=None)
    assert [t["id"] for t in pool] == ["t2"]
    assert pool[0]["skill_score"] == 2


def test_pool_falls_back_to_activity_area():
    techs = [_emp("t1", "Anton", area="heizung gas"), _emp("t2", "Berta", area="rohre wasser")]
    # no department members → activity_area token overlap with the signal.
    cl = _routing(employees=techs, employee_departments=[])
    pool = jobs.technician_pool(cl, "org-1", department_id=None, category_name=None, summary="Rohre verstopft")
    assert [t["id"] for t in pool] == ["t2"]
    assert pool[0]["skill_score"] >= 1


def test_pool_falls_back_to_any_active_technician():
    techs = [_emp("t1", "Anton", area=None), _emp("t2", "Berta", area=None)]
    cl = _routing(employees=techs, employee_departments=[])
    pool = jobs.technician_pool(cl, "org-1", department_id=None, category_name=None, summary="kein treffer")
    assert {t["id"] for t in pool} == {"t1", "t2"}
    assert all(t["skill_score"] == 0 for t in pool)


def test_pool_excludes_non_technicians():
    rows = [_emp("t1", "Anton"), _emp("o1", "Office", tech=False, wk="office")]
    cl = _routing(employees=rows, employee_departments=[])
    pool = jobs.technician_pool(cl, "org-1", department_id=None, category_name=None, summary="x")
    assert [t["id"] for t in pool] == ["t1"]


def test_pool_includes_worker_kind_both():
    rows = [_emp("m1", "Meister", tech=False, wk="both")]
    cl = _routing(employees=rows, employee_departments=[])
    pool = jobs.technician_pool(cl, "org-1", department_id=None, category_name=None, summary="x")
    assert [t["id"] for t in pool] == ["m1"]


# ── dispatch on confirm ───────────────────────────────────────────────────────

def test_dispatch_on_confirm_assigns_and_flips(monkeypatch):
    job = {"id": "j1", "technician_employee_id": "t1", "status": "suggested"}
    fake = _routing(appointment_jobs=[job], appointments=[{"assigned_employee_id": None}])
    monkeypatch.setattr(jobs, "get_service_client", lambda: fake)
    out = jobs.dispatch_job_on_confirm("org-1", "a1")
    assert out == {"job_id": "j1", "technician_id": "t1"}


def test_dispatch_on_confirm_noop_without_technician(monkeypatch):
    fake = _routing(appointment_jobs=[], appointments=[{"assigned_employee_id": None}])
    monkeypatch.setattr(jobs, "get_service_client", lambda: fake)
    assert jobs.dispatch_job_on_confirm("org-1", "a1") is None
