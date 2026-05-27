"""Super-admin standalone admin surface — backend behavior.

Covers:
 - _org_stats fans out across calls/cost_estimates/employees/appointments,
   filters by org_id, and only counts cost_estimates rows where status='sent'
   (matches the customer-visible "KVAs sent" semantic).
 - last_activity = max(created_at) across calls/appointments/cost_estimates/invoices.
 - super_admin with org_id=None passes the require_super_admin gate (the
   role check is the only check; no org binding required).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import HTTPException
import pytest

from app.api import deps
from app.api.routes import super_admin as sa


# ─── _org_stats ──────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, *, count=None, data=None):
        self.count = count
        self.data = data or []


def _build_client_for_stats(per_table_counts: dict, per_table_latest: dict) -> MagicMock:
    """Build a service-client mock whose .table().select().eq()... chain yields:
       - count="exact" head=True → Resp(count=...)
       - order/limit + .execute() → Resp(data=...) for the last_activity lookups
    """
    client = MagicMock()
    state: dict = {"table": None, "head": False}

    def _table(name):
        state["table"] = name
        state["head"] = False
        state["status_eq"] = None
        state["org_eq"] = None
        chain = MagicMock()

        def _select(cols, count=None, head=False):
            state["head"] = head
            return chain

        def _eq(col, val):
            if col == "org_id":
                state["org_eq"] = val
            elif col == "status":
                state["status_eq"] = val
            return chain

        def _order(*a, **k):
            return chain

        def _limit(*a, **k):
            return chain

        def _execute():
            t = state["table"]
            oid = state["org_eq"]
            if state["head"]:
                # COUNT path
                if t == "cost_estimates" and state["status_eq"] == "sent":
                    return _Resp(count=per_table_counts.get((t, "sent", oid), 0))
                return _Resp(count=per_table_counts.get((t, oid), 0))
            # SELECT path (last_activity)
            ts = per_table_latest.get((t, oid))
            return _Resp(data=[{"created_at": ts}] if ts else [])

        chain.select = _select
        chain.eq = _eq
        chain.order = _order
        chain.limit = _limit
        chain.execute = _execute
        return chain

    client.table = _table
    return client


def test_org_stats_counts_and_last_activity(monkeypatch):
    counts = {
        ("calls", "org-A"): 7,
        ("calls", "org-B"): 0,
        ("cost_estimates", "sent", "org-A"): 3,
        ("cost_estimates", "sent", "org-B"): 0,
        ("employees", "org-A"): 4,
        ("employees", "org-B"): 1,
        ("appointments", "org-A"): 9,
        ("appointments", "org-B"): 0,
    }
    latest = {
        ("calls", "org-A"): "2026-05-25T10:00:00+00:00",
        ("appointments", "org-A"): "2026-05-27T08:00:00+00:00",  # newest
        ("cost_estimates", "org-A"): "2026-05-01T00:00:00+00:00",
        ("invoices", "org-A"): "2026-04-01T00:00:00+00:00",
    }
    client = _build_client_for_stats(counts, latest)
    monkeypatch.setattr(sa, "get_service_client", lambda: client)

    out = sa._org_stats(["org-A", "org-B"])

    assert out["org-A"]["calls"] == 7
    assert out["org-A"]["kvas_sent"] == 3  # only status='sent' counts as KVA-sent
    assert out["org-A"]["employees"] == 4
    assert out["org-A"]["appointments"] == 9
    assert out["org-A"]["last_activity"] == "2026-05-27T08:00:00+00:00"  # max wins

    assert out["org-B"]["calls"] == 0
    assert out["org-B"]["kvas_sent"] == 0
    assert out["org-B"]["last_activity"] is None  # no activity → None


def test_org_stats_empty_org_ids_returns_empty_dict():
    assert sa._org_stats([]) == {}


# ─── require_super_admin accepts org_id=None ────────────────────────────────
def test_require_super_admin_accepts_user_with_null_org_id():
    """After the standalone-admin rewrite, the super_admin user is re-bound to
    org_id=NULL. The role check in `require_super_admin` is the only gate —
    org binding is intentionally not required for super-admins."""
    u = deps.CurrentUser(
        id="00000000-0000-0000-0000-000000000001",
        email="amber@gmail.com",
        org_id=None,
        role="super_admin",
        full_name="Amber",
    )
    # Should not raise.
    assert deps.require_super_admin(u) is u


def test_require_super_admin_rejects_org_admin():
    u = deps.CurrentUser(id="x", email="a@b", org_id="org-1", role="org_admin", full_name=None)
    with pytest.raises(HTTPException) as exc:
        deps.require_super_admin(u)
    assert exc.value.status_code == 403
