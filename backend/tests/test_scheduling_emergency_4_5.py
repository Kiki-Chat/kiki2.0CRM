"""Batch 4.5 regression tests — scheduling + emergency + prompt blocks.

Hermetic unit tests (monkeypatch DB / scheduling rules). No network, no DB.

Coverage:
  - appointments.get_available_slots: lead_time_hours, earliest_clock,
    buffer_minutes, parallel_slots=2, max_appointments_per_day,
    _add_lead_hours weekdays_only.
  - scheduling.is_emergency_by_hours: enabled/disabled, inside/outside hours.
  - agent_config.render_emergency_block: windows, surcharge variations.
  - agent_config.render_staff_transfer_block: with / without forwarding number.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services import appointments as appt
from app.services import scheduling as sched
from app.services import agent_config as ac
from app.schemas.tools import GetAvailableAppointmentsRequest

BERLIN = ZoneInfo("Europe/Berlin")


# ─── minimal fake Supabase client (re-usable across tests) ───────────────────

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, table):
        self._store = store
        self._table = table

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def lt(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def delete(self, *a, **k): return self
    def update(self, *a, **k): return self
    def insert(self, *a, **k): return self

    def execute(self):
        return _Result(list(self._store.get(self._table, [])))


class FakeClient:
    def __init__(self, reads=None):
        self._reads = reads or {}

    def table(self, name):
        return _Query(self._reads, name)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _berlin(y, mo, d, h, mi=0) -> datetime:
    """A Berlin-local datetime (CEST/CET aware)."""
    return datetime(y, mo, d, h, mi, tzinfo=BERLIN)


def _utc(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def _slots_payload(**kwargs) -> GetAvailableAppointmentsRequest:
    defaults = {"days": 7, "duration_minutes": 60}
    defaults.update(kwargs)
    return GetAvailableAppointmentsRequest(**defaults)


def _base_rules(**overrides) -> dict:
    """Return a valid scheduling rules dict with sensible defaults."""
    rules = {
        "business_hours": None,   # None → normalize_business_hours fills defaults
        "lead_hours": 0,
        "lead_only_weekdays": False,
        "earliest_clock": None,
        "buffer_minutes": 0,
        "max_per_day": 0,
        "parallel": 1,
    }
    rules.update(overrides)
    return rules


def _wire_slots(monkeypatch, rules: dict, now: datetime, existing_appts=None):
    """Monkeypatch get_available_slots so it never touches the DB."""
    client = FakeClient({"appointments": existing_appts or [], "employees": []})
    monkeypatch.setattr(appt, "get_service_client", lambda: client)
    monkeypatch.setattr(appt, "_scheduling_rules", lambda c, o: rules)
    monkeypatch.setattr(appt, "now_berlin", lambda: now)
    monkeypatch.setattr(appt, "_first_employee", lambda c, o: None)
    return client


# ═══════════════════════════════════════════════════════════════════════════════
# 1. get_available_slots
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetAvailableSlots:

    def test_lead_time_hours_blocks_early_slots(self, monkeypatch):
        """lead_time_hours=4 means slots within 4 h of 'now' must be absent."""
        # "now" is Monday 2026-06-08 08:00 Berlin; lead 4 h → earliest 12:00
        now = _berlin(2026, 6, 8, 8, 0)
        rules = _base_rules(lead_hours=4)
        _wire_slots(monkeypatch, rules, now)

        result = appt.get_available_slots("org1", _slots_payload(days=1))
        slots = result["slots"]
        # Every returned slot must be at or after 12:00 (now + 4 h)
        for s in slots:
            dt = datetime.fromisoformat(s["datetime"])
            assert dt >= now + timedelta(hours=4), (
                f"Slot {s['datetime']} is before lead-time fence"
            )

    def test_earliest_clock_filters_morning_slots_on_first_bookable_day(self, monkeypatch):
        """earliest_clock='10:00' must suppress 08:00 and 09:00 on the first
        bookable business day when 'now' is ALREADY within business hours so that
        earliest_date equals today (a business day).

        BUG NOTE: When 'now' falls on a weekend or outside-hours evening, earliest_date
        is set to that non-business day. The `day == earliest_date` guard in
        get_available_slots then never matches any business day, so earliest_clock is
        silently skipped for ALL days. This test uses a weekday morning for 'now'
        so earliest_date == the same business day to keep the test valid.
        """
        # "now" = Monday 2026-06-08 07:00 Berlin (before business hours, same calendar day)
        now = _berlin(2026, 6, 8, 7, 0)
        # lead_hours=0 → earliest_dt = 07:00 Mon; earliest_date = 2026-06-08 (Monday)
        rules = _base_rules(lead_hours=0, earliest_clock="10:00")
        _wire_slots(monkeypatch, rules, now)

        result = appt.get_available_slots("org1", _slots_payload(days=2))
        slots = result["slots"]
        assert slots, "Expected at least one slot"
        # The first bookable day is Monday 2026-06-08; slots before 10:00 must not appear.
        monday_slots = [s for s in slots if s["datetime"][:10] == "2026-06-08"]
        for s in monday_slots:
            hour = int(s["displayTime"][:2])
            assert hour >= 10, (
                f"earliest_clock=10 should block hour {hour} on first bookable day"
            )
        # Later days (Tuesday+) must still start at open_hour (08:00)
        tuesday_slots = [s for s in slots if s["datetime"][:10] == "2026-06-09"]
        if tuesday_slots:
            hours = {int(s["displayTime"][:2]) for s in tuesday_slots}
            assert min(hours) < 10, (
                "Later days should offer slots before 10:00 (no earliest_clock restriction)"
            )

    def test_earliest_clock_applies_on_first_bookable_day_even_when_now_is_weekend(self, monkeypatch):
        """Regression (FIXED): earliest_clock must apply on the first BOOKABLE day
        even when 'now' is a weekend/holiday. earliest_clock is now keyed to the
        first open day, not earliest_dt.date() (which could be a skipped weekend)."""
        now = _berlin(2026, 6, 7, 20, 0)   # Sunday evening
        rules = _base_rules(lead_hours=0, earliest_clock="10:00")
        _wire_slots(monkeypatch, rules, now)

        result = appt.get_available_slots("org1", _slots_payload(days=2))
        slots = result["slots"]
        assert slots, "Expected at least one slot"
        monday_slots = [s for s in slots if s["datetime"][:10] == "2026-06-08"]
        for s in monday_slots:
            hour = int(s["displayTime"][:2])
            assert hour >= 10, (
                f"earliest_clock=10 should block hour {hour} on Monday even when now=Sunday"
            )

    def test_buffer_minutes_collapses_adjacent_slot(self, monkeypatch):
        """buffer_minutes=30 with a 60-min booking at 09:00 should block 09:30
        and 10:00 (which would overlap with the padded interval)."""
        now = _berlin(2026, 6, 9, 7, 0)   # Monday 07:00
        # Existing booking at 09:00 for 60 min
        existing = [{
            "scheduled_at": _berlin(2026, 6, 9, 9, 0).isoformat(),
            "duration_minutes": 60,
            "status": "confirmed",
        }]
        rules = _base_rules(lead_hours=0, buffer_minutes=30, parallel=1)
        _wire_slots(monkeypatch, rules, now, existing_appts=existing)

        result = appt.get_available_slots("org1", _slots_payload(days=1))
        slot_hours = {int(s["displayTime"][:2]) for s in result["slots"]}
        # 09:00 is taken; 10:00 starts at 10:00, existing ends at 10:00 + 30 min
        # pad = 10:30; slot end = 11:00 > 10:00 - 30 = 09:30 → conflict → blocked
        assert 9 not in slot_hours, "09:00 slot should be blocked (occupied)"
        assert 10 not in slot_hours, "10:00 slot should be blocked (buffer overlap)"
        # 11:00 should be free (start=11:00, existing padded end = 10:30 < 11:00)
        assert 11 in slot_hours, "11:00 slot should be free after buffer clears"

    def test_parallel_slots_allows_two_concurrent_but_blocks_third(self, monkeypatch):
        """parallel_slots=2 — two bookings at 10:00 are OK, a third is blocked."""
        now = _berlin(2026, 6, 9, 7, 0)   # Monday 07:00
        existing = [
            {"scheduled_at": _berlin(2026, 6, 9, 10, 0).isoformat(),
             "duration_minutes": 60, "status": "confirmed"},
            {"scheduled_at": _berlin(2026, 6, 9, 10, 0).isoformat(),
             "duration_minutes": 60, "status": "pending"},
        ]
        rules = _base_rules(lead_hours=0, parallel=2, buffer_minutes=0)
        _wire_slots(monkeypatch, rules, now, existing_appts=existing)

        result = appt.get_available_slots("org1", _slots_payload(days=1))
        slot_hours = {int(s["displayTime"][:2]) for s in result["slots"]}
        # Two slots exist at 10:00 = parallel capacity reached → 10:00 blocked
        assert 10 not in slot_hours, (
            "10:00 slot should be blocked when parallel=2 is already filled"
        )
        # Other hours on the same day should still appear
        assert 8 in slot_hours or 11 in slot_hours, (
            "Non-conflicting slots should still be available"
        )

    def test_parallel_slots_two_allows_second_concurrent(self, monkeypatch):
        """parallel_slots=2 — with only ONE booking at 10:00, the slot stays open."""
        now = _berlin(2026, 6, 9, 7, 0)
        existing = [
            {"scheduled_at": _berlin(2026, 6, 9, 10, 0).isoformat(),
             "duration_minutes": 60, "status": "confirmed"},
        ]
        rules = _base_rules(lead_hours=0, parallel=2, buffer_minutes=0)
        _wire_slots(monkeypatch, rules, now, existing_appts=existing)

        result = appt.get_available_slots("org1", _slots_payload(days=1))
        slot_hours = {int(s["displayTime"][:2]) for s in result["slots"]}
        assert 10 in slot_hours, (
            "10:00 slot must still be available when only 1 of 2 parallel slots used"
        )

    def test_max_appointments_per_day_blocks_second_same_day(self, monkeypatch):
        """max_per_day=1: once one appointment exists on Monday, no more slots."""
        now = _berlin(2026, 6, 9, 7, 0)   # Monday 07:00
        existing = [
            {"scheduled_at": _berlin(2026, 6, 9, 9, 0).isoformat(),
             "duration_minutes": 60, "status": "confirmed"},
        ]
        rules = _base_rules(lead_hours=0, max_per_day=1, parallel=2)
        _wire_slots(monkeypatch, rules, now, existing_appts=existing)

        result = appt.get_available_slots("org1", _slots_payload(days=1))
        monday_slots = [
            s for s in result["slots"]
            if s["datetime"][:10] == "2026-06-09"
        ]
        assert monday_slots == [], (
            "max_per_day=1 with 1 existing appt must block all remaining Monday slots"
        )

    def test_max_appointments_per_day_zero_means_unlimited(self, monkeypatch):
        """max_per_day=0 (disabled) should not suppress any slots."""
        now = _berlin(2026, 6, 9, 7, 0)
        existing = [
            {"scheduled_at": _berlin(2026, 6, 9, 9, 0).isoformat(),
             "duration_minutes": 60, "status": "confirmed"},
            {"scheduled_at": _berlin(2026, 6, 9, 10, 0).isoformat(),
             "duration_minutes": 60, "status": "confirmed"},
        ]
        rules = _base_rules(lead_hours=0, max_per_day=0, parallel=3)
        _wire_slots(monkeypatch, rules, now, existing_appts=existing)

        result = appt.get_available_slots("org1", _slots_payload(days=1))
        assert result["slots"], "max_per_day=0 should leave Monday open"


class TestAddLeadHours:
    """Unit tests for appointments._add_lead_hours (weekdays_only logic)."""

    def test_no_weekday_filter_simple_addition(self):
        """Without weekdays_only, lead hours are calendar hours."""
        base = _berlin(2026, 6, 5, 12, 0)   # Friday noon
        result = appt._add_lead_hours(base, 24, weekdays_only=False)
        assert result == base + timedelta(hours=24)

    def test_weekday_only_skips_weekend(self):
        """24 weekday-hours from Friday noon must skip over Sat+Sun."""
        # Friday 12:00 Berlin + 24 weekday hours
        # Sat 12:00-Sun 23:59 = 0 weekday hours; Mon 00:00-Mon 11:59 = 12 h
        # → final = Monday + 12 h from start? No: Friday 13:00→14:00→…→17:00 = 5h;
        # sat/sun = skip; Mon 00:00→12:00 = 12h; total = 5+12=17h → still only Mon 12:00
        # Actually: 24 weekday hours from Fri 12:00:
        #   Fri 12:00→13:00 (1h), …, Fri 17:00 is still Fri so Fri 12:00–... each
        #   hour Mon<5 → count. Fri 12:00+1h=Fri 13:00 (weekday, count), …
        #   Fri 12:00 + 12 h = Fri 24:00 (midnight) → Sat 00:00 (weekend, skip)
        #   Sat → Sun skipped; Mon 00:00 → 01:00 (weekday, count)
        #   12 h on Fri + 12 h on Mon (00:00–12:00) = 24 weekday hours
        base = _berlin(2026, 6, 5, 12, 0)   # Friday noon
        result = appt._add_lead_hours(base, 24, weekdays_only=True)
        # Result should be Monday not Saturday
        assert result.weekday() == 0, (
            f"24 weekday-hours from Friday noon should land on Monday, got weekday={result.weekday()}"
        )
        # Must be strictly later than base
        assert result > base

    def test_weekday_only_zero_hours(self):
        """Zero lead hours with weekdays_only returns unchanged datetime."""
        base = _berlin(2026, 6, 3, 10, 0)   # Wednesday
        assert appt._add_lead_hours(base, 0, weekdays_only=True) == base

    def test_weekday_only_hard_cap_90_days(self):
        """Values > 90*24 hours are clamped to 90*24 weekday-hours before the loop.

        The hard cap is applied to the INPUT hours count (min(h, 90*24) = 2160).
        With weekdays_only=True 2160 weekday-hours span ~18 calendar weeks (≈126
        days), which is *more* than 90 calendar days, so we only assert that the
        result is finite (the cap prevented an infinite loop) and within a sane
        upper bound.
        """
        base = _berlin(2026, 6, 3, 10, 0)
        # This must terminate in reasonable time (the cap prevents runaway).
        result = appt._add_lead_hours(base, 99999, weekdays_only=True)
        # Result must be strictly later than base
        assert result > base
        # Should not exceed 200 calendar days (hard cap of 90*24 weekday-hours
        # at 5 weekday-days/week ≈ 126 calendar days; 200 gives generous margin).
        generous_cap = base + timedelta(days=200)
        assert result <= generous_cap, (
            "Even with weekdays_only=True the capped 2160 weekday-hours should "
            "not exceed ~200 calendar days"
        )

    def test_no_weekday_filter_caps_at_90_days(self):
        base = _berlin(2026, 6, 3, 10, 0)
        result = appt._add_lead_hours(base, 99999, weekdays_only=False)
        assert result == base + timedelta(hours=90 * 24)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. is_emergency_by_hours
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsEmergencyByHours:
    """Tests for scheduling.is_emergency_by_hours (monkeypatches the DB)."""

    def _wire_emergency(self, monkeypatch, emergency_enabled: bool, scheduling: dict | None = None):
        row = {"emergency_enabled": emergency_enabled}
        if scheduling is not None:
            row["scheduling"] = scheduling
        client = FakeClient({"agent_configs": [row]})
        monkeypatch.setattr(sched, "get_service_client", lambda: client)

    def test_disabled_returns_false_regardless_of_time(self, monkeypatch):
        """emergency_enabled=False → never an emergency."""
        self._wire_emergency(monkeypatch, emergency_enabled=False)
        # Late night / outside hours
        assert sched.is_emergency_by_hours("org1", _utc(2026, 6, 3, 21, 0)) is False

    def test_enabled_inside_business_hours_returns_false(self, monkeypatch):
        """emergency_enabled=True but call inside 08–17 Mon–Fri → not an emergency."""
        self._wire_emergency(monkeypatch, emergency_enabled=True)
        # Wed 09:00 UTC = 11:00 CEST → inside default business hours
        assert sched.is_emergency_by_hours("org1", _utc(2026, 6, 3, 9, 0)) is False

    def test_enabled_outside_business_hours_returns_true(self, monkeypatch):
        """emergency_enabled=True and call outside hours → emergency."""
        self._wire_emergency(monkeypatch, emergency_enabled=True)
        # Wed 21:00 UTC = 23:00 CEST → after 17:00
        assert sched.is_emergency_by_hours("org1", _utc(2026, 6, 3, 21, 0)) is True

    def test_enabled_weekend_returns_true(self, monkeypatch):
        """emergency_enabled=True on a Saturday → emergency (weekend is closed)."""
        self._wire_emergency(monkeypatch, emergency_enabled=True)
        # Sat 10:00 UTC = 12:00 CEST → weekend
        assert sched.is_emergency_by_hours("org1", _utc(2026, 6, 6, 10, 0)) is True

    def test_enabled_with_custom_hours_respects_them(self, monkeypatch):
        """Custom business hours are respected when evaluating emergency status."""
        custom_bh = {
            "monday": {"open": True, "start": "09:00", "end": "12:00",
                       "break_start": None, "break_end": None},
        }
        self._wire_emergency(monkeypatch, emergency_enabled=True,
                             scheduling={"business_hours": custom_bh})
        # Monday 08:00 UTC = 10:00 CEST — inside Mon 09:00–12:00
        assert sched.is_emergency_by_hours("org1", _utc(2026, 6, 1, 8, 0)) is False
        # Monday 11:00 UTC = 13:00 CEST — after Mon closes at 12:00
        assert sched.is_emergency_by_hours("org1", _utc(2026, 6, 1, 11, 0)) is True

    def test_no_config_row_returns_false(self, monkeypatch):
        """No agent_configs row → emergency_enabled defaults to absent (falsy) → False."""
        client = FakeClient({"agent_configs": []})
        monkeypatch.setattr(sched, "get_service_client", lambda: client)
        assert sched.is_emergency_by_hours("org1", _utc(2026, 6, 3, 21, 0)) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 3. render_emergency_block
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderEmergencyBlock:

    def test_disabled_returns_no_service_notice(self):
        out = ac.render_emergency_block({"emergency_enabled": False})
        assert "Kein Notdienst" in out
        assert "außerhalb" in out

    def test_enabled_contains_default_keywords_when_none_configured(self):
        out = ac.render_emergency_block({"emergency_enabled": True})
        assert "Rohrbruch" in out or "Gasgeruch" in out

    def test_enabled_custom_keywords_override_defaults(self):
        cfg = {
            "emergency_enabled": True,
            "emergency_keywords": ["Überschwemmung", "Stromausfall"],
        }
        out = ac.render_emergency_block(cfg)
        assert "Überschwemmung" in out
        assert "Stromausfall" in out
        # Default keyword "Kompletter Heizungsausfall" must NOT appear in the list.
        # Note: "Rohrbruch" also appears in the hardcoded active-hours explanation
        # text ("z. B. Gasgeruch, Rohrbruch"), so we check a different default keyword.
        assert "Kompletter Heizungsausfall" not in out
        assert "Kompletter Warmwasserausfall" not in out

    def test_extra_windows_single_window_appears(self):
        cfg = {
            "emergency_enabled": True,
            "emergency_extra_windows": [
                {"from": "18:00", "to": "22:00"},
            ],
        }
        out = ac.render_emergency_block(cfg)
        assert "18:00" in out and "22:00" in out

    def test_extra_windows_with_weekday_filter(self):
        cfg = {
            "emergency_enabled": True,
            "emergency_extra_windows": [
                {"from": "18:00", "to": "22:00", "weekdays": ["mon", "wed"]},
            ],
        }
        out = ac.render_emergency_block(cfg)
        # German abbreviations for Mon and Wed
        assert "Mo" in out and "Mi" in out
        assert "18:00" in out

    def test_extra_windows_multiple_windows_all_appear(self):
        cfg = {
            "emergency_enabled": True,
            "emergency_extra_windows": [
                {"from": "18:00", "to": "22:00"},
                {"from": "06:00", "to": "08:00", "label": "Frühdienst"},
            ],
        }
        out = ac.render_emergency_block(cfg)
        assert "18:00" in out and "22:00" in out
        assert "06:00" in out and "08:00" in out
        assert "Frühdienst" in out

    def test_extra_windows_malformed_entry_skipped(self):
        """A window missing 'from' or 'to' must not crash — it is silently skipped."""
        cfg = {
            "emergency_enabled": True,
            "emergency_extra_windows": [
                {"from": "18:00"},           # missing 'to'
                {"to": "22:00"},             # missing 'from'
                {"from": "19:00", "to": "21:00"},  # valid
            ],
        }
        out = ac.render_emergency_block(cfg)
        assert "19:00" in out and "21:00" in out

    def test_surcharge_notice_with_custom_text(self):
        cfg = {
            "emergency_enabled": True,
            "emergency_surcharge_notice_enabled": True,
            "emergency_surcharge_text": "50 Euro Anfahrtspauschale",
        }
        out = ac.render_emergency_block(cfg)
        assert "50 Euro Anfahrtspauschale" in out

    def test_surcharge_notice_enabled_without_text_uses_generic_fallback(self):
        cfg = {
            "emergency_enabled": True,
            "emergency_surcharge_notice_enabled": True,
            "emergency_surcharge_text": "",
        }
        out = ac.render_emergency_block(cfg)
        # Generic fallback notice must mention a surcharge
        assert "Zuschlag" in out

    def test_surcharge_notice_disabled_does_not_appear(self):
        cfg = {
            "emergency_enabled": True,
            "emergency_surcharge_notice_enabled": False,
            "emergency_surcharge_text": "50 Euro",
        }
        out = ac.render_emergency_block(cfg)
        # The custom text must NOT appear when the notice is disabled
        assert "50 Euro" not in out

    def test_no_emergency_number_gives_callback_instruction(self):
        cfg = {
            "emergency_enabled": True,
            "emergency_number": "",
            "forwarding_number": "",
        }
        out = ac.render_emergency_block(cfg)
        assert "KEINE Notdienst-Nummer" in out
        assert "hk_createInquiry" in out

    def test_emergency_number_set_gives_transfer_instruction(self):
        cfg = {
            "emergency_enabled": True,
            "emergency_number": "+49301234567",
        }
        out = ac.render_emergency_block(cfg)
        assert "transfer_to_number" in out or "verbindest" in out

    def test_only_outside_hours_flag_mentioned(self):
        """emergency_only_outside_business_hours=True → text says 'NUR außerhalb'."""
        cfg = {
            "emergency_enabled": True,
            "emergency_only_outside_business_hours": True,
        }
        out = ac.render_emergency_block(cfg)
        assert "NUR außerhalb" in out

    def test_always_active_variant_mentions_jederzeit(self):
        """emergency_only_outside_business_hours=False → active at any time."""
        cfg = {
            "emergency_enabled": True,
            "emergency_only_outside_business_hours": False,
        }
        out = ac.render_emergency_block(cfg)
        assert "JEDERZEIT" in out


# ═══════════════════════════════════════════════════════════════════════════════
# 4. render_staff_transfer_block
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderStaffTransferBlock:

    def test_no_forwarding_number_returns_callback_only_instruction(self):
        out = ac.render_staff_transfer_block({"incoming_forwarding_number": ""})
        assert "KEINE Mitarbeiter-Weiterleitung" in out
        assert "Rückrufnotiz" in out

    def test_none_forwarding_number_same_as_empty(self):
        out = ac.render_staff_transfer_block({"incoming_forwarding_number": None})
        assert "KEINE Mitarbeiter-Weiterleitung" in out

    def test_missing_key_same_as_no_number(self):
        out = ac.render_staff_transfer_block({})
        assert "KEINE Mitarbeiter-Weiterleitung" in out

    def test_with_forwarding_number_offers_live_transfer(self):
        cfg = {"incoming_forwarding_number": "+49301234567"}
        out = ac.render_staff_transfer_block(cfg)
        # Must mention the system tool for transfer
        assert "transfer_to_number" in out

    def test_with_forwarding_number_also_covers_failure_path(self):
        """The block must also instruct on transfer failure (callback note)."""
        cfg = {"incoming_forwarding_number": "+49301234567"}
        out = ac.render_staff_transfer_block(cfg)
        assert "hk_createInquiry" in out

    def test_with_forwarding_number_mentions_business_hours_condition(self):
        """Transfer is only offered inside business hours."""
        cfg = {"incoming_forwarding_number": "+49301234567"}
        out = ac.render_staff_transfer_block(cfg)
        assert "Geschäftszeiten" in out

    def test_whitespace_only_forwarding_number_treated_as_empty(self):
        """A number that is only whitespace should count as 'not set'."""
        out = ac.render_staff_transfer_block({"incoming_forwarding_number": "   "})
        assert "KEINE Mitarbeiter-Weiterleitung" in out


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _slot_conflicts (pure helper)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSlotConflicts:

    def _make_interval(self, start_berlin_h, duration_m=60):
        start = _berlin(2026, 6, 9, start_berlin_h, 0)
        return (start, start + timedelta(minutes=duration_m))

    def test_no_intervals_no_conflict(self):
        start = _berlin(2026, 6, 9, 10, 0)
        assert appt._slot_conflicts([], start, 60, 0) == 0

    def test_non_overlapping_no_conflict(self):
        intervals = [self._make_interval(8)]   # 08:00–09:00
        start = _berlin(2026, 6, 9, 10, 0)     # 10:00–11:00
        assert appt._slot_conflicts(intervals, start, 60, 0) == 0

    def test_overlapping_counts_one(self):
        intervals = [self._make_interval(10)]   # 10:00–11:00
        start = _berlin(2026, 6, 9, 10, 0)
        assert appt._slot_conflicts(intervals, start, 60, 0) == 1

    def test_buffer_extends_conflict_window(self):
        """A slot at 10:00 with 30-min buffer should conflict with an existing
        appointment that ends at 10:00 (i.e. 09:00–10:00 for 60 min)."""
        # Existing: 09:30–10:30 (start=09:30, duration=60 min)
        ex_start = _berlin(2026, 6, 9, 9, 30)
        intervals = [(ex_start, ex_start + timedelta(minutes=60))]  # 09:30–10:30
        slot_start = _berlin(2026, 6, 9, 10, 0)   # 10:00–11:00

        # Without buffer: 10:00 < 10:30+0 AND 11:00 > 09:30-0 → CONFLICT
        assert appt._slot_conflicts(intervals, slot_start, 60, 0) == 1

        # Now test a case where without buffer there's NO conflict, but buffer adds one.
        # Existing: 08:00–09:00 (60 min); slot: 09:00–10:00 (60 min).
        ex2_start = _berlin(2026, 6, 9, 8, 0)
        intervals2 = [(ex2_start, ex2_start + timedelta(minutes=60))]  # 08:00–09:00
        slot_start2 = _berlin(2026, 6, 9, 9, 0)   # 09:00–10:00

        # Without buffer: slot start (09:00) < ex end (09:00)? No → 0 conflicts.
        assert appt._slot_conflicts(intervals2, slot_start2, 60, 0) == 0

        # With 30-min buffer: ex padded end = 09:00+30 = 09:30 > slot start 09:00 → 1.
        assert appt._slot_conflicts(intervals2, slot_start2, 60, 30) == 1

    def test_multiple_intervals_counted(self):
        intervals = [self._make_interval(10), self._make_interval(10)]
        start = _berlin(2026, 6, 9, 10, 0)
        assert appt._slot_conflicts(intervals, start, 60, 0) == 2
