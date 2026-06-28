"""Unit tests for services.assignment — the availability + workload + skill
ranker that the voice tool and the CRM picker share. Includes the canonical
"Steve vs James" routing scenario."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from app.services.assignment import (
    build_pool,
    open_ticket_counts,
    pick_for_slot,
    rank_for_slot,
    recommend,
)
from app.services.common import BERLIN


# ─── helpers ─────────────────────────────────────────────────────────────────
def dt(hour: int, minute: int = 0, day: int = 15) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=BERLIN)


def iso(hour: int, minute: int = 0, day: int = 15) -> str:
    return dt(hour, minute, day).isoformat()


def emp(eid: str, area: str | None, *, auto_assign: bool = True, is_active: bool = True) -> dict:
    return {
        "id": eid,
        "display_name": eid.capitalize(),
        "activity_area": area,
        "auto_assign": auto_assign,
        "is_active": is_active,
    }


def _fake_client(**table_rows: list[dict]) -> MagicMock:
    """Per-table chainable client; each `.table(name)` yields its staged rows and
    ignores filters (the engine's Python logic does the selection)."""
    def make_chain(rows: list[dict]) -> MagicMock:
        chain = MagicMock()
        for m in ("select", "eq", "in_", "gte", "lte", "order", "limit", "not_", "is_"):
            getattr(chain, m).return_value = chain
        res = MagicMock()
        res.data = rows
        chain.execute.return_value = res
        return chain

    chains = {name: make_chain(rows) for name, rows in table_rows.items()}
    client = MagicMock()
    client.table.side_effect = lambda name: chains.get(name, make_chain([]))
    return client


# ─── pick_for_slot — the Steve vs James scenario (pure) ──────────────────────
def test_pick_for_slot_busy_one_free_other():
    """Steve and James both do heating; James is booked 14:00–15:00, Steve is
    free → the 14:30 job goes to Steve."""
    pool = [
        {"id": "steve", "display_name": "Steve", "skill_score": 1},
        {"id": "james", "display_name": "James", "skill_score": 1},
    ]
    busy = {"james": [(dt(14), dt(15))]}
    workload = {"steve": 3, "james": 0}
    assert pick_for_slot(pool, busy, workload, dt(14, 30), dt(15, 30))["id"] == "steve"


def test_pick_for_slot_both_free_fewest_tickets_wins():
    """Both free + equally skilled → the one with fewer open tickets handles it."""
    pool = [
        {"id": "steve", "display_name": "Steve", "skill_score": 1},
        {"id": "james", "display_name": "James", "skill_score": 1},
    ]
    workload = {"steve": 3, "james": 0}
    assert pick_for_slot(pool, {}, workload, dt(16), dt(17))["id"] == "james"


def test_pick_for_slot_nobody_free():
    pool = [{"id": "steve", "display_name": "Steve", "skill_score": 1}]
    busy = {"steve": [(dt(16), dt(17))]}
    assert pick_for_slot(pool, busy, {}, dt(16), dt(17)) is None


def test_pick_for_slot_skill_beats_load():
    """A genuine skill match outranks a merely-less-loaded generalist."""
    pool = [
        {"id": "specialist", "display_name": "Spec", "skill_score": 2},
        {"id": "generalist", "display_name": "Gen", "skill_score": 0},
    ]
    workload = {"specialist": 5, "generalist": 0}
    assert pick_for_slot(pool, {}, workload, dt(10), dt(11))["id"] == "specialist"


# ─── rank_for_slot — available first ─────────────────────────────────────────
def test_rank_for_slot_available_beats_lower_load():
    """A busy person with 0 tickets ranks BELOW a free person with many — being
    free at the asked time is the hard filter for a recommendation."""
    client = _fake_client(
        appointments=[{"id": "a1", "assigned_employee_id": "steve", "scheduled_at": iso(14), "duration_minutes": 60}],
        employee_absences=[],
    )
    pool = [
        {"id": "steve", "display_name": "Steve", "skill_score": 1},
        {"id": "james", "display_name": "James", "skill_score": 1},
    ]
    ranked = rank_for_slot(client, "org", pool, dt(14), dt(15), workload={"steve": 0, "james": 5})
    assert [e["id"] for e in ranked] == ["james", "steve"]
    assert ranked[0]["available"] is True and ranked[1]["available"] is False


# ─── open_ticket_counts ──────────────────────────────────────────────────────
def test_open_ticket_counts_only_open_cases():
    client = _fake_client(
        case_employees=[
            {"case_id": "c1", "employee_id": "steve"},
            {"case_id": "c2", "employee_id": "steve"},
            {"case_id": "c3", "employee_id": "james"},
        ],
        cases=[
            {"id": "c1", "status": "active"},      # open
            {"id": "c2", "status": "completed"},   # closed → not counted
            {"id": "c3", "status": "planning"},    # open
        ],
    )
    assert open_ticket_counts(client, "org", ["steve", "james"]) == {"steve": 1, "james": 1}


def test_open_ticket_counts_empty():
    assert open_ticket_counts(_fake_client(), "org", []) == {}


# ─── build_pool — skill path + fallbacks ─────────────────────────────────────
def test_build_pool_skill_path():
    client = _fake_client(employees=[emp("steve", "Heizung"), emp("james", "Heizung Solar")])
    pool = build_pool(client, "org", category_name="Heizung", summary="Heizung kaputt")
    assert {e["id"] for e in pool} == {"steve", "james"}
    assert all(e["skill_score"] >= 1 for e in pool)


def test_build_pool_fallback_to_category_default():
    """No trade-skill match (a finance category) → fall back to the category's
    default employee, flagged skill_score 0."""
    client = _fake_client(employees=[emp("olivia", "Buchhaltung")])
    pool = build_pool(
        client, "org", category_name="Finanzierung", summary="Ratenzahlung besprechen",
        category_default_employee_id="olivia",
    )
    assert [e["id"] for e in pool] == ["olivia"]
    assert pool[0]["skill_score"] == 0


def test_build_pool_fallback_to_any_active():
    """No skill match and no category default → any active employee, so a slot is
    still offerable."""
    client = _fake_client(employees=[emp("a", "Buchhaltung"), emp("b", "Empfang")])
    pool = build_pool(client, "org", category_name="Finanzierung", summary="Ratenzahlung")
    assert {e["id"] for e in pool} == {"a", "b"}
    assert all(e["skill_score"] == 0 for e in pool)


# ─── recommend — end-to-end ──────────────────────────────────────────────────
def test_recommend_surfaces_least_loaded_available():
    client = _fake_client(
        employees=[emp("steve", "Heizung"), emp("james", "Heizung")],
        appointments=[],
        employee_absences=[],
        case_employees=[{"case_id": "c1", "employee_id": "steve"}],
        cases=[{"id": "c1", "status": "active"}],  # steve 1 open, james 0
    )
    out = recommend(client, "org", category_name="Heizung", summary="Heizung kaputt", start=dt(10), end=dt(11))
    assert out["recommended"]["id"] == "james"
    assert out["any_available"] is True
    assert {c["id"] for c in out["candidates"]} == {"steve", "james"}


def test_recommend_none_when_all_busy():
    client = _fake_client(
        employees=[emp("steve", "Heizung")],
        appointments=[{"id": "a1", "assigned_employee_id": "steve", "scheduled_at": iso(10), "duration_minutes": 60}],
        employee_absences=[],
        case_employees=[],
        cases=[],
    )
    out = recommend(client, "org", category_name="Heizung", summary="Heizung kaputt", start=dt(10), end=dt(11))
    assert out["recommended"] is None
    assert out["any_available"] is False
