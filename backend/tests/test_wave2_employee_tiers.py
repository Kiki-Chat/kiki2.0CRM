"""Wave 2 — three-tier access control + org-isolation + employee invite.

Covers the required tests:
  1. An org-A employee gets 403/404 for org-B data (isolation).
  2. An employee is BLOCKED (403) from every admin endpoint (set-password,
     access_role change, create-admin, delete-employee, org settings, KVA/
     invoice/catalog mutations, Kiki-Zentrale mutations).
  3. An org-admin / super-admin passes the admin gate.
  4. A created employee inherits the CREATOR's org_id + maps access_role→role.
  5. The invite email sends through the pipeline, carries the set-password LINK
     and NO password (no password value is ever generated or transmitted).

Role gates are FastAPI dependencies, so 403s are asserted end-to-end via
TestClient with ``require_org`` overridden (the gate short-circuits before the
handler, so no DB is touched). Isolation is asserted behaviorally with a
filter-applying fake Supabase client.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import deps
from app.api.routes import customers as cust
from app.api.routes import employees as emp
from app.api.routes import kiki_zentrale as kz
from app.main import app
from app.schemas.admin import EmployeeCreate
from app.services import employee_invite

client = TestClient(app)


def _user(role: str, org_id: str | None = "org-A") -> deps.CurrentUser:
    return deps.CurrentUser(id=f"u-{role}", email=f"{role}@a.de", org_id=org_id, role=role, full_name=None)


# ─── Fake Supabase that actually applies .eq/.neq/.in_ filters ────────────────
class _Res:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count if count is not None else len(data)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)
        self._filters: list[tuple] = []
        self._insert = None

    # filter ops that matter for isolation
    def eq(self, col, val):
        self._filters.append(("eq", col, val)); return self

    def neq(self, col, val):
        self._filters.append(("neq", col, val)); return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals))); return self

    def is_(self, col, val):
        self._filters.append(("is", col, val)); return self

    # no-ops for the isolation test
    def select(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def lt(self, *a, **k): return self
    def gt(self, *a, **k): return self
    def or_(self, *a, **k): return self

    def insert(self, row):
        self._insert = row; return self

    def update(self, fields):
        self._update = fields; return self

    def delete(self):
        self._delete = True; return self

    def _apply(self):
        out = []
        for r in self._rows:
            ok = True
            for op, col, val in self._filters:
                rv = r.get(col)
                if op == "eq" and rv != val:
                    ok = False; break
                if op == "neq" and rv == val:
                    ok = False; break
                if op == "in" and rv not in val:
                    ok = False; break
                if op == "is" and val == "null" and rv is not None:
                    ok = False; break
            if ok:
                out.append(r)
        return out

    def execute(self):
        if self._insert is not None:
            return _Res([self._insert])
        # select / update / delete all return the rows matching the filters
        return _Res(self._apply())


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, name: str):
        return _FakeQuery(self.tables.get(name, []))


def _two_org_customers():
    return [
        {"id": "cust-A", "org_id": "org-A", "full_name": "Kunde A", "status": "active",
         "customer_number": "K-001", "email": "a@a.de", "phone": None, "customer_type": "regular"},
        {"id": "cust-B", "org_id": "org-B", "full_name": "Kunde B", "status": "active",
         "customer_number": "K-002", "email": "b@b.de", "phone": None, "customer_type": "regular"},
    ]


# ─── 1. Dependency unit tests ─────────────────────────────────────────────────
def test_require_org_admin_blocks_employee():
    with pytest.raises(HTTPException) as ei:
        deps.require_org_admin(_user("employee"))
    assert ei.value.status_code == 403


def test_require_org_admin_allows_org_admin_and_super_admin():
    assert deps.require_org_admin(_user("org_admin")).role == "org_admin"
    assert deps.require_org_admin(_user("super_admin")).role == "super_admin"


def test_kiki_require_admin_blocks_employee_allows_admin():
    # Kiki-Zentrale mutations gate on the local _require_admin (org_admin only).
    with pytest.raises(HTTPException) as ei:
        kz._require_admin(_user("employee"))
    assert ei.value.status_code == 403
    kz._require_admin(_user("org_admin"))  # no raise


# ─── 2. Employee BLOCKED (403) from every admin endpoint (end-to-end) ─────────
# Each path is gated by require_org_admin (chains require_org). Overriding
# require_org with an employee makes the gate 403 before the handler runs.
_ADMIN_ENDPOINTS = [
    ("POST", "/api/employees", {"display_name": "X", "email": "x@a.de", "access_role": "admin", "login_access": True}),
    ("PATCH", "/api/employees/emp-1", {"access_role": "admin"}),
    ("DELETE", "/api/employees/emp-1", None),
    ("POST", "/api/employees/emp-1/set-password", {"password": "supersecret123"}),
    ("POST", "/api/employees/emp-1/resend-invite", None),
    ("GET", "/api/settings", None),
    ("PATCH", "/api/settings/general", {"name": "Hacked GmbH"}),
    ("PATCH", "/api/settings/email-config", {}),
    ("PATCH", "/api/settings/pds-config", {}),
    ("POST", "/api/invoices", {}),
    ("DELETE", "/api/invoices/inv-1", None),
    ("PATCH", "/api/invoices/inv-1/status", {"status": "paid"}),
    ("POST", "/api/cost-estimates", {}),
    ("DELETE", "/api/cost-estimates/ce-1", None),
    ("POST", "/api/catalog", {}),
    ("DELETE", "/api/catalog/item-1", None),
]


def test_employee_blocked_from_all_admin_endpoints():
    app.dependency_overrides[deps.require_org] = lambda: _user("employee")
    try:
        for method, path, body in _ADMIN_ENDPOINTS:
            r = client.request(method, path, json=body)
            assert r.status_code == 403, f"{method} {path} expected 403, got {r.status_code} ({r.text[:120]})"
    finally:
        app.dependency_overrides.clear()


def test_org_admin_passes_admin_gate(monkeypatch):
    """An org-admin gets PAST the gate — set-password reaches the handler and
    404s on a missing employee (404, NOT 403 → gate allowed admin through)."""
    monkeypatch.setattr(emp, "get_service_client", lambda: FakeSupabase({"employees": []}))
    app.dependency_overrides[deps.require_org] = lambda: _user("org_admin")
    try:
        r = client.post("/api/employees/emp-1/set-password", json={"password": "supersecret123"})
        assert r.status_code == 404, f"expected 404 (gate passed), got {r.status_code}"
    finally:
        app.dependency_overrides.clear()


# ─── 3. Isolation — org-A employee cannot read/write org-B data ───────────────
def test_employee_cannot_read_other_orgs_customer(monkeypatch):
    monkeypatch.setattr(cust, "get_service_client", lambda: FakeSupabase({"customers": _two_org_customers()}))
    app.dependency_overrides[deps.require_org] = lambda: _user("employee", org_id="org-A")
    try:
        # Own org: visible.
        own = client.get("/api/customers/cust-A")
        assert own.status_code == 200
        assert own.json()["full_name"] == "Kunde A"
        # Other org: 404 (org_id filter excludes it — no cross-tenant read).
        other = client.get("/api/customers/cust-B")
        assert other.status_code == 404, f"cross-org read leaked: {other.status_code}"
    finally:
        app.dependency_overrides.clear()


def test_employee_cannot_update_other_orgs_customer(monkeypatch):
    monkeypatch.setattr(cust, "get_service_client", lambda: FakeSupabase({"customers": _two_org_customers()}))
    app.dependency_overrides[deps.require_org] = lambda: _user("employee", org_id="org-A")
    try:
        r = client.patch("/api/customers/cust-B", json={"full_name": "HIJACKED"})
        assert r.status_code == 404, f"cross-org write leaked: {r.status_code}"
    finally:
        app.dependency_overrides.clear()


# ─── 4. Created employee inherits creator's org_id + role mapping ─────────────
class _CreateFake:
    """Captures the users + employees inserts during emp._create."""
    def __init__(self):
        self.users_inserted: list[dict] = []
        self.employees_inserted: list[dict] = []
        self._outer = self

    def table(self, name):
        outer = self

        class _T:
            def __init__(self):
                self._insert = None
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def limit(self, *a, **k): return self
            def update(self, *a, **k): return self
            def insert(self, row):
                self._insert = row; return self
            def execute(self):
                if name == "users" and self._insert is not None:
                    outer.users_inserted.append(self._insert)
                    return _Res([self._insert])
                if name == "employees" and self._insert is not None:
                    row = dict(self._insert); row["id"] = "emp-new"
                    outer.employees_inserted.append(row)
                    return _Res([row])
                if name == "organizations":
                    return _Res([{"name": "Org A"}])
                return _Res([])  # users select-by-email → no existing user
        return _T()


@pytest.mark.parametrize("access_role,expected_role", [("employee", "employee"), ("admin", "org_admin")])
def test_created_employee_inherits_org_and_maps_role(monkeypatch, access_role, expected_role):
    fake = _CreateFake()
    monkeypatch.setattr(emp, "get_service_client", lambda: fake)
    monkeypatch.setattr(
        emp.employee_invite, "generate_set_password_link",
        lambda email, *, new_user: ("https://app.example/set-password#tok123", "new-uid"),
    )
    sent: dict = {}
    monkeypatch.setattr(emp.employee_invite, "send_employee_welcome", lambda **kw: sent.update(kw))

    payload = EmployeeCreate(display_name="New Emp", email="new@a.de", login_access=True, access_role=access_role)
    emp._create("org-A", payload)

    assert len(fake.users_inserted) == 1
    row = fake.users_inserted[0]
    assert row["org_id"] == "org-A"          # inherits CREATOR's org
    assert row["role"] == expected_role       # access_role → users.role
    assert row["id"] == "new-uid"
    assert fake.employees_inserted[0]["org_id"] == "org-A"
    # Invite carried the set-password LINK and NO password field.
    assert sent["set_password_link"] == "https://app.example/set-password#tok123"
    assert "password" not in sent


# ─── 5. Invite email — set-password LINK present, NO password ─────────────────
def test_welcome_email_html_has_link_and_login_id():
    link = "https://app.example/set-password#token-abc"
    html = employee_invite.build_welcome_email_html(
        company_name="Muster GmbH", display_name="Max", login_email="max@a.de", set_password_link=link,
    )
    assert link in html                 # the set-password mechanism is the link
    assert "max@a.de" in html           # login ID shown
    assert "Passwort festlegen" in html  # CTA, German


def test_send_employee_welcome_uses_pipeline_with_link_no_password(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(employee_invite.email_send, "send_email", lambda **kw: captured.update(kw))
    link = "https://app.example/set-password#tok"
    employee_invite.send_employee_welcome(
        org_id="org-A", company_name="Muster", display_name="Max",
        login_email="max@a.de", set_password_link=link,
    )
    assert captured["to_email"] == "max@a.de"
    assert link in captured["body_html"]
    assert "password" not in captured           # send_email has no password param
    assert "body_text" not in captured or "tok" not in str(captured.get("body_text", ""))
