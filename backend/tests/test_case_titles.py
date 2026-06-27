"""Vorgang (case) title helpers — German long-date formatting + per-customer
uniqueness guard (app/services/cases/titles.py)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.cases import titles as t

# Independent weekday→German mapping so the test doesn't reuse the module's arrays.
_EN_TO_DE = {0: "Montag", 1: "Dienstag", 2: "Mittwoch", 3: "Donnerstag",
             4: "Freitag", 5: "Samstag", 6: "Sonntag"}


def test_format_de_long_date_basic():
    dt = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)  # midday → no tz date-flip
    assert t.format_de_long_date(dt) == f"{_EN_TO_DE[dt.weekday()]}, 27. Juni"


def test_format_de_long_date_accepts_iso_string():
    assert t.format_de_long_date("2026-01-05T09:00:00Z") == "Montag, 5. Januar"  # 2026-01-05 is a Monday


def test_format_de_long_date_uses_berlin_timezone():
    # 23:30 UTC on 27 Jun (CEST = +2) is already 01:30 on the 28th in Berlin.
    dt = datetime(2026, 6, 27, 23, 30, tzinfo=timezone.utc)
    berlin = dt.astimezone(ZoneInfo("Europe/Berlin"))
    assert berlin.day == 28
    assert t.format_de_long_date(dt) == f"{_EN_TO_DE[berlin.weekday()]}, 28. Juni"


def test_format_de_long_date_none_is_a_string():
    out = t.format_de_long_date(None)
    assert isinstance(out, str) and ", " in out and "." in out


def test_unique_title_returns_base_when_free():
    assert t.make_unique_case_title("Heizung defekt", set()) == "Heizung defekt"


def test_unique_title_appends_date_on_collision():
    when = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
    out = t.make_unique_case_title("Heizung defekt", {"Heizung defekt"}, when)
    assert out == f"Heizung defekt · {t.format_de_long_date(when)}"


def test_unique_title_appends_counter_when_date_also_collides():
    when = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
    dated = f"Heizung defekt · {t.format_de_long_date(when)}"
    out = t.make_unique_case_title("Heizung defekt", {"Heizung defekt", dated}, when)
    assert out == f"{dated} (2)"


def test_unique_title_blank_base_falls_back_to_vorgang():
    assert t.make_unique_case_title("  ", set()) == "Vorgang"
    assert t.make_unique_case_title(None, set()) == "Vorgang"


def test_unique_title_truncates_to_120():
    base = "X" * 200
    assert len(t.make_unique_case_title(base, set())) == 120


# ─── existing_case_titles (thin DB read) ────────────────────────────────────
class _FakeCases:
    """Minimal stand-in: every chained method returns self; execute() yields rows."""

    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


def test_existing_case_titles_collects_and_excludes():
    client = _FakeCases([
        {"id": "c1", "title": "Heizung defekt"},
        {"id": "c2", "title": "  Dach undicht  "},
        {"id": "c3", "title": ""},          # blank → dropped
        {"id": "c4", "title": "Heizung defekt"},
    ])
    titles = t.existing_case_titles(client, "org", "cust", exclude_id="c4")
    assert titles == {"Heizung defekt", "Dach undicht"}


def test_existing_case_titles_empty_without_customer():
    assert t.existing_case_titles(_FakeCases([{"id": "c1", "title": "x"}]), "org", None) == set()
