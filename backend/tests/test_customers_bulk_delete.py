"""Bulk customer soft-delete (Kunden multi-select remove).

Hermetic: a fake supabase client applies the org_id + id-in filters so the test
proves the delete is SCOPED to the caller's org (no cross-tenant delete) and is a
soft-delete (status='deleted').
"""
from __future__ import annotations

import asyncio

from app.api import deps
from app.api.routes import customers as cust


class _Chain:
    def __init__(self, db):
        self.db = db
        self.filters: dict = {}
        self._update = None

    def update(self, fields):
        self._update = fields
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def in_(self, col, vals):
        self.filters[(col, "in")] = list(vals)
        return self

    def execute(self):
        org = self.filters.get("org_id")
        ids = self.filters.get(("id", "in"), [])
        matched = [r for r in self.db.rows if r["org_id"] == org and r["id"] in ids]
        for r in matched:
            r.update(self._update or {})

        class _R:
            data = matched

        return _R()


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _Chain(self)


def _user(org="org-A"):
    return deps.CurrentUser(id="u1", email="a@a.de", org_id=org, role="org_admin", full_name=None)


def test_bulk_delete_soft_deletes_scoped_to_org(monkeypatch):
    db = _DB([
        {"id": "c1", "org_id": "org-A", "status": "active"},
        {"id": "c2", "org_id": "org-A", "status": "active"},
        {"id": "c3", "org_id": "org-B", "status": "active"},  # other tenant — must NOT delete
    ])
    monkeypatch.setattr(cust, "get_service_client", lambda: db)
    out = asyncio.run(
        cust.bulk_delete_customers(cust.BulkDeleteRequest(ids=["c1", "c2", "c3"]), user=_user())
    )
    assert out["deleted"] == 2  # only org-A's c1 + c2
    assert db.rows[0]["status"] == "deleted" and db.rows[1]["status"] == "deleted"
    assert db.rows[2]["status"] == "active"  # cross-org row untouched


def test_bulk_delete_empty_is_noop(monkeypatch):
    db = _DB([])
    monkeypatch.setattr(cust, "get_service_client", lambda: db)
    out = asyncio.run(cust.bulk_delete_customers(cust.BulkDeleteRequest(ids=[]), user=_user()))
    assert out["deleted"] == 0
