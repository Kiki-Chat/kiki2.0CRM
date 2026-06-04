"""Unit tests for the business-hours window check that drives out-of-hours
emergency tagging (services/scheduling._within_hours). Pure logic — no DB."""

from datetime import datetime, timezone

from app.services.scheduling import _within_hours, default_business_hours

# Default tradesperson week: Mon–Fri 08:00–17:00, weekend closed. Evaluated in
# Europe/Berlin; June = CEST (UTC+2). Dates below: 2026-06-03 = Wed, 06 = Sat.
HOURS = default_business_hours()


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_weekday_daytime_is_open():
    # Wed 09:00 UTC = 11:00 CEST → inside 08:00–17:00.
    assert _within_hours(HOURS, _utc(2026, 6, 3, 9)) is True


def test_weekday_evening_is_closed():
    # Wed 19:00 UTC = 21:00 CEST → after 17:00.
    assert _within_hours(HOURS, _utc(2026, 6, 3, 19)) is False


def test_weekday_early_morning_is_closed():
    # Wed 05:00 UTC = 07:00 CEST → before 08:00.
    assert _within_hours(HOURS, _utc(2026, 6, 3, 5)) is False


def test_weekend_is_closed():
    # Sat 10:00 UTC = 12:00 CEST → weekend, day not open.
    assert _within_hours(HOURS, _utc(2026, 6, 6, 10)) is False


def test_naive_datetime_treated_as_utc():
    # Naive 09:00 → treated as UTC → 11:00 CEST → open (no crash on tzinfo).
    assert _within_hours(HOURS, datetime(2026, 6, 3, 9)) is True


def test_lunch_break_is_closed():
    hours = default_business_hours()
    hours["wednesday"]["break_start"] = "12:00"
    hours["wednesday"]["break_end"] = "13:00"
    # Wed 10:30 UTC = 12:30 CEST → inside the break.
    assert _within_hours(hours, _utc(2026, 6, 3, 10, 30)) is False
    # Wed 12:00 UTC = 14:00 CEST → after the break → open.
    assert _within_hours(hours, _utc(2026, 6, 3, 12)) is True
