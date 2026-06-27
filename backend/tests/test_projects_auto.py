"""projects_auto — the auto-grouping behaviour: every NEW inquiry is auto-filed
into a Fall/case (attach to a matching open one, else create its own). The contract
under test: already-filed → no-op; no open cases → create; clear similarity →
attach; ANY doubt (embed failure, below threshold) → create; safe wrapper never
raises into call ingest. (Post Case↔Project split: grouping table is `cases`,
inquiries carry `case_id`, numbers via gen_case_number.)"""
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
           "subject": None, "notes": "Heizung macht Geräusche", "case_id": None}
    row.update(over)
    return row


def test_already_filed_is_noop():
    client = _Client({})
    out = pa.auto_assign_inquiry_to_case(client, "org1", _inquiry(case_id="c-9"))
    assert out is None
    assert client.calls == []  # not a single table touched


def test_no_open_cases_creates_one(monkeypatch):
    created = {"id": "c-new", "number": "FL-KC007-0001", "title": "Heizung defekt"}
    cases_tbl = _chain([])  # the open-cases select returns nothing
    cases_tbl.insert.return_value = _chain([created])
    inquiries_tbl = _chain([])
    client = _Client({"cases": cases_tbl, "inquiries": inquiries_tbl})
    monkeypatch.setattr(pa, "gen_case_number", lambda c, o: "FL-KC007-0001")

    out = pa.auto_assign_inquiry_to_case(client, "org1", _inquiry())
    assert out["id"] == "c-new"
    insert_arg = cases_tbl.insert.call_args[0][0]
    assert insert_arg["title"] == "Heizung defekt"
    assert insert_arg["status"] == "active"
    update_arg = inquiries_tbl.update.call_args[0][0]
    assert update_arg["case_id"] == "c-new"
    assert update_arg["case_source"] == "ai"


def test_confident_judge_attaches(monkeypatch):
    # Embedding shortlists the candidate; the LLM judge confidently matches → attach.
    open_c = {"id": "c-match", "title": "Heizungsreparatur", "description": None,
              "status": "active", "customer_id": "cust-1", "number": "FL-1"}
    cases_tbl = _chain([open_c])
    inquiries_tbl = _chain([])
    client = _Client({"cases": cases_tbl, "inquiries": inquiries_tbl})
    monkeypatch.setattr(pa.ai_usage, "within_cap", lambda org: True)
    monkeypatch.setattr(pa.ai_client, "embed", lambda texts, model: ([[1.0, 0.0]] * len(texts), 1))
    monkeypatch.setattr(pa, "_judge_attach", lambda *a: (open_c, 0.95, "gleiche Heizung"))
    monkeypatch.setattr(pa, "safe_retitle", lambda *a, **k: None)

    out = pa.auto_assign_inquiry_to_case(client, "org1", _inquiry())
    assert out["id"] == "c-match"
    update_arg = inquiries_tbl.update.call_args[0][0]
    assert update_arg["case_id"] == "c-match"
    assert update_arg["case_confidence"] == 0.95
    cases_tbl.insert.assert_not_called()


def test_moderate_judge_creates_and_suggests_merge(monkeypatch):
    # Plausible but not confident → keep the call as its OWN Vorgang, but persist a
    # merge suggestion for a human to confirm (never a silent merge).
    open_c = {"id": "c-maybe", "title": "Heizung", "description": None, "status": "active",
              "customer_id": "cust-1", "number": "FL-2"}
    cases_tbl = _chain([open_c])
    cases_tbl.insert.return_value = _chain([{"id": "c-new"}])
    inquiries_tbl = _chain([])
    sugg_tbl = _chain([])
    client = _Client({"cases": cases_tbl, "inquiries": inquiries_tbl, "case_merge_suggestions": sugg_tbl})
    monkeypatch.setattr(pa.ai_usage, "within_cap", lambda org: True)
    monkeypatch.setattr(pa, "gen_case_number", lambda c, o: "FL-KC007-9")
    monkeypatch.setattr(pa.ai_client, "embed", lambda texts, model: ([[1.0, 0.0]] * len(texts), 1))
    monkeypatch.setattr(pa, "_judge_attach", lambda *a: (open_c, 0.6, "evtl. dasselbe"))

    out = pa.auto_assign_inquiry_to_case(client, "org1", _inquiry())
    assert out["id"] == "c-new"                 # kept separate
    sugg_tbl.insert.assert_called_once()
    sugg_arg = sugg_tbl.insert.call_args[0][0]
    assert sugg_arg["source_case_id"] == "c-new"
    assert sugg_arg["target_case_id"] == "c-maybe"
    assert sugg_arg["status"] == "pending"


def test_low_similarity_creates_new(monkeypatch):
    open_c = {"id": "c-other", "title": "Dach undicht", "description": None, "status": "active"}
    created = {"id": "c-new"}
    cases_tbl = _chain([open_c])
    cases_tbl.insert.return_value = _chain([created])
    inquiries_tbl = _chain([])
    client = _Client({"cases": cases_tbl, "inquiries": inquiries_tbl})
    monkeypatch.setattr(pa.ai_usage, "within_cap", lambda org: True)
    monkeypatch.setattr(pa, "gen_case_number", lambda c, o: "FL-KC007-0002")
    # Orthogonal vectors → cosine 0.0 < threshold → create new.
    monkeypatch.setattr(
        pa.ai_client, "embed",
        lambda texts, model: ([[1.0, 0.0]] + [[0.0, 1.0]] * (len(texts) - 1), 1),
    )

    out = pa.auto_assign_inquiry_to_case(client, "org1", _inquiry())
    assert out["id"] == "c-new"


def test_embed_failure_falls_back_to_create(monkeypatch):
    open_c = {"id": "c-x", "title": "Irgendwas", "description": None, "status": "active"}
    created = {"id": "c-new"}
    cases_tbl = _chain([open_c])
    cases_tbl.insert.return_value = _chain([created])
    client = _Client({"cases": cases_tbl, "inquiries": _chain([])})
    monkeypatch.setattr(pa.ai_usage, "within_cap", lambda org: True)
    monkeypatch.setattr(pa, "gen_case_number", lambda c, o: "FL-KC007-0003")

    def _boom(texts, model):
        raise RuntimeError("no openai")

    monkeypatch.setattr(pa.ai_client, "embed", _boom)
    out = pa.auto_assign_inquiry_to_case(client, "org1", _inquiry())
    assert out["id"] == "c-new"


def test_safe_wrapper_never_raises(monkeypatch):
    class _Exploding:
        def table(self, name):
            raise RuntimeError("db down")

    out = pa.safe_auto_assign(_Exploding(), "org1", _inquiry())
    assert out is None  # swallowed — call ingest must never break
