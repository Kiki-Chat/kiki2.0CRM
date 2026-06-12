"""projects_auto — the item-6 headline behaviour: every NEW inquiry is auto-filed
into a Projekt (attach to a matching open one, else create its own). The contract
under test: already-filed → no-op; no open projects → create; clear similarity →
attach; ANY doubt (embed failure, below threshold) → create; safe wrapper never
raises into call ingest."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.services import projects_auto as pa


def _chain(rows):
    chain = MagicMock()
    for m in ("select", "eq", "neq", "in_", "is_", "limit", "order", "insert", "update", "like"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = MagicMock(data=rows, count=len(rows))
    return chain


class _Client:
    def __init__(self, tables: dict):
        self.tables = tables
        self.calls: list[str] = []

    def table(self, name):
        self.calls.append(name)
        return self.tables.get(name) or _chain([])


def _inquiry(**over):
    row = {"id": "inq-1", "customer_id": "cust-1", "title": "Heizung defekt",
           "subject": None, "notes": "Heizung macht Geräusche", "project_id": None}
    row.update(over)
    return row


def test_already_filed_is_noop():
    client = _Client({})
    out = pa.auto_assign_inquiry_to_project(client, "org1", _inquiry(project_id="p-9"))
    assert out is None
    assert client.calls == []  # not a single table touched


def test_no_open_projects_creates_one(monkeypatch):
    created = {"id": "p-new", "number": "PRJ-2026-00001", "title": "Heizung defekt"}
    projects_tbl = _chain([])  # the open-projects select returns nothing
    projects_tbl.insert.return_value = _chain([created])
    inquiries_tbl = _chain([])
    client = _Client({"projects": projects_tbl, "inquiries": inquiries_tbl})
    monkeypatch.setattr(pa, "gen_project_number", lambda c, o: "PRJ-2026-00001")

    out = pa.auto_assign_inquiry_to_project(client, "org1", _inquiry())
    assert out["id"] == "p-new"
    insert_arg = projects_tbl.insert.call_args[0][0]
    assert insert_arg["title"] == "Heizung defekt"
    assert insert_arg["status"] == "active"
    update_arg = inquiries_tbl.update.call_args[0][0]
    assert update_arg["project_id"] == "p-new"
    assert update_arg["case_source"] == "ai"


def test_similar_open_project_attaches(monkeypatch):
    open_p = {"id": "p-match", "title": "Heizungsreparatur", "description": None, "status": "active"}
    projects_tbl = _chain([open_p])
    inquiries_tbl = _chain([])
    client = _Client({"projects": projects_tbl, "inquiries": inquiries_tbl})
    monkeypatch.setattr(pa.ai_usage, "within_cap", lambda org: True)
    # Identical vectors → cosine 1.0 ≥ threshold → attach.
    monkeypatch.setattr(pa.ai_client, "embed", lambda texts, model: ([[1.0, 0.0]] * len(texts), 1))

    out = pa.auto_assign_inquiry_to_project(client, "org1", _inquiry())
    assert out["id"] == "p-match"
    update_arg = inquiries_tbl.update.call_args[0][0]
    assert update_arg["project_id"] == "p-match"
    assert update_arg["case_confidence"] == 1.0
    projects_tbl.insert.assert_not_called()


def test_low_similarity_creates_new(monkeypatch):
    open_p = {"id": "p-other", "title": "Dach undicht", "description": None, "status": "active"}
    created = {"id": "p-new"}
    projects_tbl = _chain([open_p])
    projects_tbl.insert.return_value = _chain([created])
    inquiries_tbl = _chain([])
    client = _Client({"projects": projects_tbl, "inquiries": inquiries_tbl})
    monkeypatch.setattr(pa.ai_usage, "within_cap", lambda org: True)
    monkeypatch.setattr(pa, "gen_project_number", lambda c, o: "PRJ-2026-00002")
    # Orthogonal vectors → cosine 0.0 < threshold → create new.
    monkeypatch.setattr(
        pa.ai_client, "embed",
        lambda texts, model: ([[1.0, 0.0]] + [[0.0, 1.0]] * (len(texts) - 1), 1),
    )

    out = pa.auto_assign_inquiry_to_project(client, "org1", _inquiry())
    assert out["id"] == "p-new"


def test_embed_failure_falls_back_to_create(monkeypatch):
    open_p = {"id": "p-x", "title": "Irgendwas", "description": None, "status": "active"}
    created = {"id": "p-new"}
    projects_tbl = _chain([open_p])
    projects_tbl.insert.return_value = _chain([created])
    client = _Client({"projects": projects_tbl, "inquiries": _chain([])})
    monkeypatch.setattr(pa.ai_usage, "within_cap", lambda org: True)
    monkeypatch.setattr(pa, "gen_project_number", lambda c, o: "PRJ-2026-00003")

    def _boom(texts, model):
        raise RuntimeError("no openai")

    monkeypatch.setattr(pa.ai_client, "embed", _boom)
    out = pa.auto_assign_inquiry_to_project(client, "org1", _inquiry())
    assert out["id"] == "p-new"


def test_safe_wrapper_never_raises(monkeypatch):
    class _Exploding:
        def table(self, name):
            raise RuntimeError("db down")

    out = pa.safe_auto_assign(_Exploding(), "org1", _inquiry())
    assert out is None  # swallowed — call ingest must never break