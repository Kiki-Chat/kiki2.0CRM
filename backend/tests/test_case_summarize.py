"""retitle_case gating — refresh the summary always, move the title only on a
material change, and never over a human lock (app/services/cases/summarize.py)."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.services.cases import summarize as sz


def _chain(rows):
    chain = MagicMock()
    for m in ("select", "eq", "neq", "in_", "is_", "limit", "order", "insert", "update"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    return chain


class _Client:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return self.tables.get(name) or _chain([])


def _cases(title="Alt", locked=False):
    return _chain([{"title": title, "title_locked": locked, "customer_id": "cust-1"}])


def test_retitle_updates_title_on_material_change(monkeypatch):
    cases_tbl = _cases()
    client = _Client({"cases": cases_tbl})
    monkeypatch.setattr(sz, "summarize_case",
                        lambda *a, **k: {"title": "Heizung Fehler F28", "summary": "Kurz.", "material": True})
    monkeypatch.setattr(sz, "existing_case_titles", lambda *a, **k: set())
    sz.retitle_case(client, "org", "case-1")
    upd = cases_tbl.update.call_args[0][0]
    assert upd["title"] == "Heizung Fehler F28"
    assert upd["ai_summary"] == "Kurz."


def test_retitle_keeps_title_when_not_material(monkeypatch):
    cases_tbl = _cases()
    client = _Client({"cases": cases_tbl})
    monkeypatch.setattr(sz, "summarize_case",
                        lambda *a, **k: {"title": "Andere", "summary": "S", "material": False})
    sz.retitle_case(client, "org", "case-1")
    upd = cases_tbl.update.call_args[0][0]
    assert "title" not in upd          # stable headline — only the summary refreshes
    assert upd["ai_summary"] == "S"


def test_retitle_respects_human_lock(monkeypatch):
    cases_tbl = _cases(locked=True)
    client = _Client({"cases": cases_tbl})
    monkeypatch.setattr(sz, "summarize_case",
                        lambda *a, **k: {"title": "KI-Titel", "summary": "S", "material": True})
    sz.retitle_case(client, "org", "case-1", force=False)
    upd = cases_tbl.update.call_args[0][0]
    assert "title" not in upd          # locked → AI never overwrites a human title


def test_retitle_force_overrides_material_but_not_lock(monkeypatch):
    cases_tbl = _cases(locked=False)
    client = _Client({"cases": cases_tbl})
    monkeypatch.setattr(sz, "summarize_case",
                        lambda *a, **k: {"title": "Erzwungen", "summary": "S", "material": False})
    monkeypatch.setattr(sz, "existing_case_titles", lambda *a, **k: set())
    sz.retitle_case(client, "org", "case-1", force=True)
    upd = cases_tbl.update.call_args[0][0]
    assert upd["title"] == "Erzwungen"  # force re-titles even when not material
