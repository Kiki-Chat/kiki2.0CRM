"""Customer detail Vorgang-card enrichment — ai_summary, case rollups, orphan primary_call."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.api.routes import customers as cust_mod


class _Chain:
    def __init__(self, db: "_DB", table: str):
        self._db = db
        self._table = table
        self._filters: list[tuple] = []
        self._order_desc = False

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self._filters.append(("neq", col, val))
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, val))
        return self

    def order(self, _col, desc=False):
        self._order_desc = desc
        return self

    def limit(self, *_a, **_k):
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def execute(self):
        rows = self._db.rows.get(self._table, [])
        out = []
        for r in rows:
            ok = True
            for op, col, val in self._filters:
                rv = r.get(col)
                if op == "eq" and rv != val:
                    ok = False
                    break
                if op == "neq" and rv == val:
                    ok = False
                    break
                if op == "is" and val == "null" and rv is not None:
                    ok = False
                    break
                if op == "in" and rv not in val:
                    ok = False
                    break
            if ok:
                out.append(dict(r))
        if self._order_desc:
            out.sort(key=lambda x: x.get("created_at") or x.get("started_at") or "", reverse=True)
        r = MagicMock()
        r.data = out
        return r


class _DB:
    def __init__(self, rows: dict[str, list[dict]]):
        self.rows = {k: [dict(v) for v in vs] for k, vs in rows.items()}

    def table(self, name: str):
        return _Chain(self, name)


ORG = "org-1"
CUST = "cust-1"
CASE_A = "case-a"
CASE_B = "case-b"
INQ_GROUPED = "inq-g"
INQ_ORPHAN = "inq-o"


@pytest.fixture
def sample_db():
    return _DB({
        "customers": [{
            "id": CUST, "org_id": ORG, "full_name": "Familie Wagner",
            "email": "w@.de", "phone": "+491", "phone2": "+492",
            "customer_type": "regular", "created_at": "2026-06-01T10:00:00Z",
            "updated_at": "2026-06-27T10:00:00Z",
        }],
        "inquiries": [
            {"id": INQ_GROUPED, "org_id": ORG, "customer_id": CUST, "case_id": CASE_A,
             "subject": "Bad", "title": "Badsanierung", "status": "open",
             "created_at": "2026-06-10T10:00:00Z", "updated_at": "2026-06-20T10:00:00Z"},
            {"id": INQ_ORPHAN, "org_id": ORG, "customer_id": CUST, "case_id": None,
             "subject": "Hahn", "title": "Tropfender Hahn", "status": "open",
             "case_confidence": 0.4, "case_reason": "low confidence",
             "created_at": "2026-06-26T10:00:00Z", "updated_at": "2026-06-26T16:00:00Z"},
        ],
        "calls": [
            {"id": "call-1", "org_id": ORG, "customer_id": CUST, "inquiry_id": INQ_GROUPED,
             "summary_title": "Erstanfrage", "direction": "inbound", "duration_seconds": 120,
             "started_at": "2026-06-16T09:00:00Z", "deleted_at": None},
            {"id": "call-2", "org_id": ORG, "customer_id": CUST, "inquiry_id": INQ_GROUPED,
             "summary_title": "Rückfrage", "direction": "inbound", "duration_seconds": 90,
             "started_at": "2026-06-20T11:00:00Z", "deleted_at": None},
            {"id": "call-3", "org_id": ORG, "customer_id": CUST, "inquiry_id": INQ_ORPHAN,
             "summary_title": "Meldung Hahn", "direction": "inbound", "duration_seconds": 88,
             "started_at": "2026-06-26T16:40:00Z", "deleted_at": None},
        ],
        "appointments": [
            {"id": "appt-1", "org_id": ORG, "customer_id": CUST, "inquiry_id": INQ_GROUPED,
             "title": "Aufmaß", "scheduled_at": "2026-06-18T14:00:00Z", "status": "pending"},
        ],
        "cost_estimates": [
            {"id": "kva-1", "org_id": ORG, "customer_id": CUST, "inquiry_id": INQ_GROUPED,
             "number": "KVA-1", "status": "sent", "total": 1000, "created_at": "2026-06-19T10:00:00Z"},
        ],
        "cases": [
            {"id": CASE_A, "org_id": ORG, "customer_id": CUST, "number": "VG-1",
             "title": "Badsanierung Gäste-Bad", "status": "active", "created_at": "2026-06-10T10:00:00Z",
             "project_id": None, "ai_summary": "Komplettsanierung läuft."},
            {"id": CASE_B, "org_id": ORG, "customer_id": CUST, "number": "VG-2",
             "title": "Leerer Vorgang", "status": "planning", "created_at": "2026-06-01T10:00:00Z",
             "project_id": None, "ai_summary": None},
        ],
        "projects": [],
    })


def test_customer_detail_cases_include_ai_summary(monkeypatch, sample_db):
    monkeypatch.setattr(cust_mod, "get_service_client", lambda: sample_db)
    out = cust_mod._detail(ORG, CUST)
    assert out is not None
    case_a = next(c for c in out["cases"] if c["id"] == CASE_A)
    assert case_a["ai_summary"] == "Komplettsanierung läuft."


def test_customer_detail_case_call_count_rollup(monkeypatch, sample_db):
    monkeypatch.setattr(cust_mod, "get_service_client", lambda: sample_db)
    out = cust_mod._detail(ORG, CUST)
    case_a = next(c for c in out["cases"] if c["id"] == CASE_A)
    assert case_a["call_count"] == 2


def test_customer_detail_case_entry_count_rollup(monkeypatch, sample_db):
    monkeypatch.setattr(cust_mod, "get_service_client", lambda: sample_db)
    out = cust_mod._detail(ORG, CUST)
    case_a = next(c for c in out["cases"] if c["id"] == CASE_A)
    # 2 calls + 1 appointment + 1 kva
    assert case_a["entry_count"] == 4


def test_customer_detail_case_last_activity_at(monkeypatch, sample_db):
    monkeypatch.setattr(cust_mod, "get_service_client", lambda: sample_db)
    out = cust_mod._detail(ORG, CUST)
    case_a = next(c for c in out["cases"] if c["id"] == CASE_A)
    assert case_a["last_activity_at"] == "2026-06-20T11:00:00Z"


def test_customer_detail_empty_case_zero_stats(monkeypatch, sample_db):
    monkeypatch.setattr(cust_mod, "get_service_client", lambda: sample_db)
    out = cust_mod._detail(ORG, CUST)
    case_b = next(c for c in out["cases"] if c["id"] == CASE_B)
    assert case_b["call_count"] == 0
    assert case_b["entry_count"] == 0
    assert case_b["last_activity_at"] == "2026-06-01T10:00:00Z"


def test_customer_detail_orphan_primary_call(monkeypatch, sample_db):
    monkeypatch.setattr(cust_mod, "get_service_client", lambda: sample_db)
    out = cust_mod._detail(ORG, CUST)
    orphan = next(i for i in out["inquiries"] if i["id"] == INQ_ORPHAN)
    assert orphan.get("primary_call") is not None
    assert orphan["primary_call"]["id"] == "call-3"
    assert orphan["primary_call"]["summary_title"] == "Meldung Hahn"


def test_customer_detail_grouped_inquiry_no_primary_call(monkeypatch, sample_db):
    monkeypatch.setattr(cust_mod, "get_service_client", lambda: sample_db)
    out = cust_mod._detail(ORG, CUST)
    grouped = next(i for i in out["inquiries"] if i["id"] == INQ_GROUPED)
    assert "primary_call" not in grouped
