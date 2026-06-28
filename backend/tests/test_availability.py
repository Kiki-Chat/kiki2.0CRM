"""Unit tests for services.availability — the unified "is this employee free?"
engine. Pure interval logic needs no DB; the batched loader is exercised with a
table-routing MagicMock client (appointments vs employee_absences)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from app.services.availability import (
    _intervals_conflict,
    _parse_iso,
    busy_intervals,
    free_employees,
    is_free,
    load_busy_map,
    slot_free,
)
from app.services.common import BERLIN


# ─── datetime helpers (Berlin-aware) ─────────────────────────────────────────
def dt(hour: int, minute: int = 0, day: int = 15) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=BERLIN)


def iso(hour: int, minute: int = 0, day: int = 15) -> str:
    return dt(hour, minute, day).isoformat()


# ─── table-routing fake client ───────────────────────────────────────────────
def _routing_client(appts: list[dict] | None = None, absences: list[dict] | None = None) -> MagicMock:
    """`.table('appointments')` and `.table('employee_absences')` each yield a
    chainable stub returning their staged rows. The stub ignores filters (the
    engine's Python grouping does the per-employee selection), so stage rows that
    already belong to the queried employees."""
    def make_chain(rows: list[dict]) -> MagicMock:
        chain = MagicMock()
        for m in ("select", "eq", "in_", "gte", "lte", "order", "limit"):
            getattr(chain, m).return_value = chain
        res = MagicMock()
        res.data = rows
        chain.execute.return_value = res
        return chain

    appt_chain = make_chain(appts or [])
    abs_chain = make_chain(absences or [])
    client = MagicMock()
    client.table.side_effect = lambda name: (
        appt_chain if name == "appointments"
        else abs_chain if name == "employee_absences"
        else make_chain([])
    )
    return client


# ─── pure interval logic ─────────────────────────────────────────────────────
def test_slot_free_detects_overlap():
    busy = [(dt(10), dt(11))]
    assert slot_free(busy, dt(10, 30), dt(11, 30)) is False
    assert _intervals_conflict(busy, dt(10, 30), dt(11, 30)) is True


def test_slot_free_adjacent_is_free():
    """Half-open intervals: a slot starting exactly when a busy block ends, or
    ending exactly when one begins, does NOT conflict."""
    busy = [(dt(10), dt(11))]
    assert slot_free(busy, dt(11), dt(12)) is True   # starts at busy end
    assert slot_free(busy, dt(9), dt(10)) is True    # ends at busy start


def test_slot_free_buffer_padding():
    """A buffer pads each busy block on both sides, so an otherwise-adjacent slot
    becomes a conflict (travel/prep time)."""
    busy = [(dt(10), dt(11))]
    assert slot_free(busy, dt(11), dt(12), buffer_minutes=15) is False
    assert slot_free(busy, dt(11, 15), dt(12), buffer_minutes=15) is True


def test_slot_free_empty_busy():
    assert slot_free([], dt(10), dt(11)) is True


# ─── _parse_iso ──────────────────────────────────────────────────────────────
def test_parse_iso_variants():
    assert _parse_iso(None) is None
    assert _parse_iso("nonsense") is None
    z = _parse_iso("2026-07-15T10:00:00Z")
    assert z is not None and z.utcoffset().total_seconds() == 0
    naive = _parse_iso("2026-07-15T10:00:00")
    assert naive is not None and naive.tzinfo == BERLIN


# ─── load_busy_map (batched, two tables) ─────────────────────────────────────
def test_load_busy_map_unions_appts_and_absences():
    client = _routing_client(
        appts=[{"id": "a1", "assigned_employee_id": "E1", "scheduled_at": iso(10), "duration_minutes": 60}],
        absences=[{"employee_id": "E2", "starts_at": iso(9), "ends_at": iso(17)}],
    )
    busy = load_busy_map(client, "org", ["E1", "E2"], dt(8), dt(18))
    assert busy["E1"] == [(dt(10), dt(11))]
    assert busy["E2"] == [(dt(9), dt(17))]


def test_load_busy_map_ignores_unassigned_appointments():
    """A google_import/unassigned appointment (assigned_employee_id=None) is the
    company calendar, not any one person — it must not block an employee."""
    client = _routing_client(
        appts=[
            {"id": "a1", "assigned_employee_id": None, "scheduled_at": iso(10), "duration_minutes": 60},
            {"id": "a2", "assigned_employee_id": "E1", "scheduled_at": iso(14), "duration_minutes": 30},
        ],
    )
    busy = load_busy_map(client, "org", ["E1"], dt(8), dt(18))
    assert busy["E1"] == [(dt(14), dt(14, 30))]


def test_load_busy_map_excludes_named_appointment():
    """exclude_appointment_ids drops the appointment being rescheduled so it
    doesn't conflict with itself."""
    client = _routing_client(
        appts=[{"id": "a1", "assigned_employee_id": "E1", "scheduled_at": iso(10), "duration_minutes": 60}],
    )
    busy = load_busy_map(client, "org", ["E1"], dt(8), dt(18), exclude_appointment_ids={"a1"})
    assert busy["E1"] == []


def test_is_free_and_busy_intervals():
    client = _routing_client(
        appts=[{"id": "a1", "assigned_employee_id": "E1", "scheduled_at": iso(10), "duration_minutes": 60}],
    )
    assert is_free(client, "org", "E1", dt(12), dt(13)) is True
    assert is_free(client, "org", "E1", dt(10, 30), dt(11)) is False
    assert busy_intervals(client, "org", "E1", dt(8), dt(18)) == [(dt(10), dt(11))]


def test_free_employees_filters_and_preserves_order():
    client = _routing_client(
        appts=[{"id": "a1", "assigned_employee_id": "E1", "scheduled_at": iso(10), "duration_minutes": 60}],
        absences=[{"employee_id": "E2", "starts_at": iso(9), "ends_at": iso(17)}],
    )
    # 12:00–13:00: E1 free, E2 on absence all day, E3 unknown→free. Order kept.
    assert free_employees(client, "org", ["E1", "E2", "E3"], dt(12), dt(13)) == ["E1", "E3"]
    # 10:30–11:00: E1 busy, E2 absent, E3 free.
    assert free_employees(client, "org", ["E1", "E2", "E3"], dt(10, 30), dt(11)) == ["E3"]
