"""Date/time NL parsing for appointment booking (services/common). Pure logic —
`_parse_date` takes an explicit `now`, so these are deterministic. NOW = Thursday
2026-06-04, Europe/Berlin."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.common import _parse_date, _parse_time

NOW = datetime(2026, 6, 4, 10, 0, tzinfo=ZoneInfo("Europe/Berlin"))  # Thursday


def _d(s):
    r = _parse_date(s, NOW)
    return r.strftime("%Y-%m-%d") if r else None


def test_relative_weeks_now_parse():
    # Previously returned None → "INVALID_DATE".
    assert _d("in 3 wochen") == "2026-06-25"
    assert _d("in einer woche") == "2026-06-11"
    assert _d("nächste woche") == "2026-06-11"


def test_weekday_distinctions():
    # "diesen" (this week) vs "nächsten" (strictly next) vs "nächste Woche X"
    # used to collapse to the same day; now they differ.
    assert _d("diesen donnerstag") == "2026-06-04"
    assert _d("nächsten donnerstag") == "2026-06-11"
    assert _d("nächste woche donnerstag") == "2026-06-11"


def test_weekday_upcoming():
    assert _d("freitag") == "2026-06-05"
    assert _d("montag") == "2026-06-08"


def test_relative_words():
    assert _d("heute") == "2026-06-04"
    assert _d("morgen") == "2026-06-05"
    assert _d("übermorgen") == "2026-06-06"


def test_iso_and_day_month():
    assert _d("2026-12-24") == "2026-12-24"
    # A bare day.month already elapsed this year rolls to next year.
    assert _d("2.6.") == "2027-06-02"


def test_time_words_parse():
    assert _parse_time("14:30") == (14, 30)
    assert _parse_time("halb drei") == (2, 30)
    assert _parse_time("viertel nach drei") == (3, 15)
    assert _parse_time("viertel vor drei") == (2, 45)
    assert _parse_time("nachmittags") == (14, 0)  # not 12:00 (the "mittags" trap)
    assert _parse_time("vormittags") == (10, 0)
    assert _parse_time("15 uhr") == (15, 0)
    assert _parse_time("3 pm") == (15, 0)


def test_time_unparseable_is_none():
    # No silent 09:00 fallback inside the parser — caller decides.
    assert _parse_time("irgendwann mal") is None
