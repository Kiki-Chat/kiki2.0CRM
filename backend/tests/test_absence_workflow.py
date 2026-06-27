"""Item A — employee absence self-service + admin approval.

Required behaviours:
  * employee applies for their OWN absence → pending; employee_id is resolved
    from the caller, never from the request (no filing for colleagues);
  * employee CANNOT approve, CANNOT list all absences, CANNOT create for others;
  * employee CANNOT see colleagues' HR data (roster strips rates/balances/email);
  * admin CAN approve / reject (stamps status + reviewer);
  * an admin can't review another org's absence (org-scoped → 404).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import employees as emp
from app.main import app

client = TestClient(app)


def _user(role: str, org_id: str = "org-A", uid: str = "u-emp") -> deps.CurrentUser:
    return deps.CurrentUser(id=uid, email=f"{role}@a.de", org_id=org_id, role=role, full_name=None)


# ─── filter-applying fake (eq filters exclude rows; captures insert/update) ───
class _Res:
    def __init__(self, data):
        self.data = data
        self.count = len(data)


class _Q:
    def __init__(self, rows, sink):
        self._rows = rows
        self._sink = sink
        self._f: list[tuple] = []
        self._insert = None
        self._update = None

    def eq(self, c, v):
        self._f.append((c, v)); return self

    def in_(self, c, v):
        self._f.append((c, list(v), "in")); return self

    def select(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def lt(self, *a, **k): return self

    def insert(self, row):
        self._insert = row; return self

    def update(self, fields):
        self._update = fields; return self

    def _match(self):
        out = []
        for r in self._rows:
            ok = True
            for f in self._f:
                if len(f) == 3:
                    if r.get(f[0]) not in f[1]:
                        ok = False; break
                elif r.get(f[0]) != f[1]:
                    ok = False; break
            if ok:
                out.append(r)
        return out

    def execute(self):
        if self._insert is not None:
            row = dict(self._insert); row.setdefault("id", "abs-new")
            self._sink.append(("insert", row))
            self._rows.append(row)
            return _Res([row])
        if self._update is not None:
            matched = self._match()
            for r in matched:
                r.update(self._update)
            self._sink.append(("update", self._update, [r["id"] for r in matched]))
            return _Res(matched)
        return _Res(self._match())


class FakeDB:
    def __init__(self, tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.ops: list = []

    def table(self, name):
        return _Q(self.tables.setdefault(name, []), self.ops)


def _tables():
    return {
        "employees": [
            {"id": "e-emp", "org_id": "org-A", "user_id": "u-emp", "deleted": False,
             "display_name": "Emp", "calendar_color": "#111", "hourly_rate": 42,
             "email": "emp@a.de", "remaining_vacation_days": 10, "is_active": True},
        ],
        "users": [],
        "employee_absences": [
            {"id": "abs-1", "org_id": "org-A", "employee_id": "e-emp", "status": "pending",
             "type": "vacation", "starts_at": "2026-07-01T00:00:00Z", "ends_at": "2026-07-05T00:00:00Z"},
            {"id": "abs-B", "org_id": "org-B", "employee_id": "e-b", "status": "pending",
             "type": "vacation", "starts_at": "2026-07-01T00:00:00Z", "ends_at": "2026-07-05T00:00:00Z"},
        ],
    }


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def _use(monkeypatch, role, db=None):
    db = db or FakeDB(_tables())
    monkeypatch.setattr(emp, "get_service_client", lambda: db)
    app.dependency_overrides[deps.require_org] = lambda: _user(role)
    return db


# ─── employee self-service ────────────────────────────────────────────────────
def test_employee_applies_for_own_absence_pending(monkeypatch):
    db = _use(monkeypatch, "employee")
    r = client.post("/api/employees/me/absences", json={
        "type": "vacation", "starts_at": "2026-08-01T00:00:00Z", "ends_at": "2026-08-03T00:00:00Z"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["employee_id"] == "e-emp"     # resolved from caller, not the request
    assert body["org_id"] == "org-A"


def test_employee_applies_with_substitute(monkeypatch):
    tables = _tables()
    tables["employees"].append(
        {"id": "e-sub", "org_id": "org-A", "user_id": "u-sub", "deleted": False,
         "display_name": "Sub", "is_active": True}
    )
    _use(monkeypatch, "employee", db=FakeDB(tables))
    r = client.post("/api/employees/me/absences", json={
        "type": "vacation", "starts_at": "2026-08-01T00:00:00Z", "ends_at": "2026-08-03T00:00:00Z",
        "substitute_employee_id": "e-sub"})
    assert r.status_code == 200, r.text
    assert r.json()["substitute_employee_id"] == "e-sub"


def test_employee_cannot_pick_self_as_substitute(monkeypatch):
    _use(monkeypatch, "employee")
    r = client.post("/api/employees/me/absences", json={
        "type": "vacation", "starts_at": "2026-08-01T00:00:00Z", "ends_at": "2026-08-03T00:00:00Z",
        "substitute_employee_id": "e-emp"})  # e-emp is the caller's own employee row
    assert r.status_code == 400


def test_apply_without_employee_record_404(monkeypatch):
    # caller's user_id has no matching employees row
    db = FakeDB({"employees": [], "employee_absences": []})
    monkeypatch.setattr(emp, "get_service_client", lambda: db)
    app.dependency_overrides[deps.require_org] = lambda: _user("employee", uid="ghost")
    r = client.post("/api/employees/me/absences", json={
        "type": "vacation", "starts_at": "2026-08-01T00:00:00Z", "ends_at": "2026-08-03T00:00:00Z"})
    assert r.status_code == 404


def test_employee_sees_only_own_absences(monkeypatch):
    _use(monkeypatch, "employee")
    r = client.get("/api/employees/me/absences")
    assert r.status_code == 200
    assert all(a["employee_id"] == "e-emp" for a in r.json())


# ─── employee is blocked from admin actions ───────────────────────────────────
def test_employee_cannot_approve(monkeypatch):
    _use(monkeypatch, "employee")
    r = client.post("/api/employees/absences/abs-1/approve")
    assert r.status_code == 403


def test_employee_cannot_list_all_or_create_for_others(monkeypatch):
    _use(monkeypatch, "employee")
    assert client.get("/api/employees/absences").status_code == 403
    assert client.get("/api/employees/absences/pending").status_code == 403
    assert client.post("/api/employees/e-other/absences", json={
        "type": "vacation", "starts_at": "2026-08-01T00:00:00Z", "ends_at": "2026-08-03T00:00:00Z"}).status_code == 403


def test_employee_cannot_see_others_hr_data(monkeypatch):
    _use(monkeypatch, "employee")
    r = client.get("/api/employees")
    assert r.status_code == 200
    item = r.json()[0]
    assert "display_name" in item                 # roster still usable
    for f in ("hourly_rate", "email", "remaining_vacation_days", "vacation_days_per_year"):
        assert f not in item, f"HR field {f} leaked to employee"


def test_admin_sees_hr_data(monkeypatch):
    _use(monkeypatch, "org_admin")
    r = client.get("/api/employees")
    assert r.status_code == 200
    item = r.json()[0]
    assert "hourly_rate" in item and "remaining_vacation_days" in item


# ─── admin approval ───────────────────────────────────────────────────────────
def test_admin_approves(monkeypatch):
    db = _use(monkeypatch, "org_admin")
    r = client.post("/api/employees/absences/abs-1/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["reviewed_by"] == "u-emp"     # the admin's id (test reuses uid)
    updates = [o for o in db.ops if o[0] == "update"]
    assert updates and updates[-1][1]["status"] == "approved"


def test_admin_rejects_with_note(monkeypatch):
    db = _use(monkeypatch, "org_admin")
    r = client.post("/api/employees/absences/abs-1/reject", json={"note": "zu kurzfristig"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["internal_note"] == "zu kurzfristig"


def test_review_nonexistent_404(monkeypatch):
    _use(monkeypatch, "org_admin")
    assert client.post("/api/employees/absences/nope/approve").status_code == 404


def test_admin_cannot_review_other_orgs_absence(monkeypatch):
    # org-A admin tries to approve org-B's absence → org filter excludes it → 404
    _use(monkeypatch, "org_admin")
    r = client.post("/api/employees/absences/abs-B/approve")
    assert r.status_code == 404, "cross-org absence review must not succeed"
