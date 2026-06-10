"""Item 1 — cross-org foreign-key (FK) hardening.

The Wave-2 isolation audit found no read leaks, but several write paths let a
caller attach ANOTHER org's FK id (customer / project / employee / inquiry /
vehicle / tool) to a row in their own org — a dangling cross-tenant pointer.

These tests assert the write path rejects a cross-org FK with 422 while still
accepting same-org ids (no regression), plus that the elevenlabs_agent service
helpers scope their by-id lookups by org_id (defense-in-depth).

Uses a filter-applying fake Supabase client (mirrors test_wave2_employee_tiers)
so `.eq("org_id", …)` actually excludes other-org rows.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import appointments as appt
from app.api.routes import documents as docs
from app.api.routes import employees as emp
from app.api.routes import inquiries as inq
from app.main import app
from app.services import elevenlabs_agent as ea

client = TestClient(app)


def _user(org_id: str = "org-A", role: str = "org_admin") -> deps.CurrentUser:
    return deps.CurrentUser(id="u1", email="a@a.de", org_id=org_id, role=role, full_name=None)


# ─── Filter-applying fake (eq filters actually exclude rows) ──────────────────
class _Res:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count if count is not None else len(data)


class _Q:
    def __init__(self, rows):
        self._rows = list(rows)
        self._filters: list[tuple] = []
        self._insert = None

    def eq(self, col, val):
        self._filters.append((col, val)); return self

    # filters we don't model still need to chain
    def neq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def select(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def lt(self, *a, **k): return self
    def gt(self, *a, **k): return self
    def is_(self, *a, **k): return self
    # get_org_code's self-heal uses `.not_.is_(...)`; `.not_` is an attribute.
    @property
    def not_(self): return self

    def insert(self, row):
        self._insert = row; return self

    def update(self, fields):
        self._update = fields; return self

    def delete(self):
        self._delete = True; return self

    def _apply(self):
        return [r for r in self._rows if all(r.get(c) == v for c, v in self._filters)]

    def execute(self):
        if self._insert is not None:
            row = dict(self._insert)
            row.setdefault("id", "new-row")
            return _Res([row])
        return _Res(self._apply())


class _Storage:
    def from_(self, *_a, **_k): return self
    def upload(self, *_a, **_k): return {}
    def create_signed_url(self, *_a, **_k): return {"signedURL": "https://x/y"}
    def remove(self, *_a, **_k): return {}


class FakeDB:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables
        self.storage = _Storage()

    def table(self, name: str):
        return _Q(self.tables.get(name, []))


# Two customers / projects / employees / inquiries — one per org.
def _tables() -> dict[str, list[dict]]:
    return {
        "customers": [
            {"id": "cust-A", "org_id": "org-A"},
            {"id": "cust-B", "org_id": "org-B"},
        ],
        "projects": [
            {"id": "proj-A", "org_id": "org-A"},
            {"id": "proj-B", "org_id": "org-B"},
        ],
        "employees": [
            {"id": "emp-A", "org_id": "org-A", "deleted": False},
            {"id": "emp-B", "org_id": "org-B", "deleted": False},
        ],
        "inquiries": [],  # empty → gen_inquiry_number counts 0
        # gen_inquiry_number → get_org_code reads the org's K-code (migration 0058);
        # a stored code short-circuits the self-heal path.
        "organizations": [{"id": "org-A", "code": "K01"}],
    }


def _override(monkeypatch, module, tables=None):
    monkeypatch.setattr(module, "get_service_client", lambda: FakeDB(tables or _tables()))
    app.dependency_overrides[deps.require_org] = lambda: _user("org-A")
    app.dependency_overrides[deps.require_org_admin] = lambda: _user("org-A")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ─── Inquiries ────────────────────────────────────────────────────────────────
def test_inquiry_create_rejects_cross_org_customer(monkeypatch):
    _override(monkeypatch, inq)
    r = client.post("/api/inquiries", json={"customer_id": "cust-B", "title": "X"})
    assert r.status_code == 422, r.text
    assert "Organisation" in r.json()["detail"]


def test_inquiry_create_rejects_cross_org_project(monkeypatch):
    _override(monkeypatch, inq)
    r = client.post("/api/inquiries", json={"project_id": "proj-B", "title": "X"})
    assert r.status_code == 422, r.text


def test_inquiry_create_accepts_same_org_customer(monkeypatch):
    _override(monkeypatch, inq)
    r = client.post("/api/inquiries", json={"customer_id": "cust-A", "title": "X"})
    assert r.status_code == 200, r.text  # no regression on valid same-org FK


def test_inquiry_update_rejects_cross_org_project(monkeypatch):
    _override(monkeypatch, inq)
    r = client.patch("/api/inquiries/inq-A", json={"project_id": "proj-B"})
    assert r.status_code == 422, r.text


def test_inquiry_update_rejects_cross_org_employee(monkeypatch):
    _override(monkeypatch, inq)
    r = client.patch("/api/inquiries/inq-A", json={"assigned_employee_id": "emp-B"})
    assert r.status_code == 422, r.text


# ─── Appointments ─────────────────────────────────────────────────────────────
def test_appointment_create_rejects_cross_org_customer(monkeypatch):
    _override(monkeypatch, appt)
    r = client.post("/api/appointments", json={"customer_id": "cust-B", "scheduled_at": "2026-06-02T10:00:00Z"})
    assert r.status_code == 422, r.text


def test_appointment_create_rejects_cross_org_employee(monkeypatch):
    _override(monkeypatch, appt)
    r = client.post("/api/appointments", json={"assigned_employee_id": "emp-B", "scheduled_at": "2026-06-02T10:00:00Z"})
    assert r.status_code == 422, r.text


def test_appointment_create_accepts_same_org(monkeypatch):
    _override(monkeypatch, appt)
    r = client.post("/api/appointments", json={"customer_id": "cust-A", "assigned_employee_id": "emp-A", "scheduled_at": "2026-06-02T10:00:00Z"})
    assert r.status_code == 200, r.text


def test_appointment_patch_rejects_cross_org_employee(monkeypatch):
    _override(monkeypatch, appt)
    r = client.patch("/api/appointments/appt-A", json={"assigned_employee_id": "emp-B"})
    assert r.status_code == 422, r.text


# ─── Documents ────────────────────────────────────────────────────────────────
def test_document_upload_rejects_cross_org_customer(monkeypatch):
    _override(monkeypatch, docs)
    r = client.post(
        "/api/customers/cust-B/documents",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 422, r.text


def test_document_upload_accepts_same_org_customer(monkeypatch):
    _override(monkeypatch, docs)
    r = client.post(
        "/api/customers/cust-A/documents",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 200, r.text


# ─── Employee absences ────────────────────────────────────────────────────────
def test_absence_create_rejects_cross_org_employee(monkeypatch):
    _override(monkeypatch, emp)
    r = client.post(
        "/api/employees/emp-B/absences",
        json={"type": "vacation", "starts_at": "2026-06-02T00:00:00Z", "ends_at": "2026-06-03T00:00:00Z"},
    )
    assert r.status_code == 422, r.text


def test_absence_create_accepts_same_org_employee(monkeypatch):
    _override(monkeypatch, emp)
    r = client.post(
        "/api/employees/emp-A/absences",
        json={"type": "vacation", "starts_at": "2026-06-02T00:00:00Z", "ends_at": "2026-06-03T00:00:00Z"},
    )
    assert r.status_code == 200, r.text


# ─── Service-layer defense-in-depth (elevenlabs_agent) ────────────────────────
def test_rollback_to_snapshot_scoped_by_org(monkeypatch):
    db = FakeDB({"agent_config_snapshots": [
        {"id": "snap-A", "org_id": "org-A", "agent_id": "ag", "full_config": {}},
    ]})
    monkeypatch.setattr(ea, "get_service_client", lambda: db)
    # Cross-org snapshot id → looks up to nothing → refuses (no agent reached).
    with pytest.raises(ea.ElevenLabsWriteError):
        ea.rollback_to_snapshot(snapshot_id="snap-A", actor_id=None, org_id="org-B")


def test_push_knowledge_resource_scoped_by_org(monkeypatch):
    db = FakeDB({"knowledge_resources": [{"id": "kr-A", "org_id": "org-A", "kind": "url", "source": "x", "display_name": "x"}]})
    monkeypatch.setattr(ea, "get_service_client", lambda: db)
    with pytest.raises(ea.ElevenLabsWriteError):
        ea.push_knowledge_resource_to_elevenlabs(resource_id="kr-A", org_id="org-B")


def test_remove_knowledge_resource_scoped_by_org_is_noop(monkeypatch):
    db = FakeDB({"knowledge_resources": [{"id": "kr-A", "org_id": "org-A", "elevenlabs_doc_id": "d1"}]})
    monkeypatch.setattr(ea, "get_service_client", lambda: db)
    # Cross-org id → safe no-op (returns None, never reaches the agent).
    assert ea.remove_knowledge_resource_from_elevenlabs(resource_id="kr-A", org_id="org-B") is None
