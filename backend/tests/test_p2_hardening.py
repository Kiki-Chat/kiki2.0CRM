"""Hermetic tests for the P2/P3 hardening pass:
  - services.common.fetch_all_rows  — pages past PostgREST's ~1000-row cap
  - services.common.run_parallel    — concurrent fan-out, order + error semantics
  - dashboard._validate_date_params — fail-loud on malformed date filters
  - config.validate_runtime_config  — prod fail-fast on missing secrets
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import cost_estimates as ce_route
from app.api.routes import dashboard as dash
from app.api.routes import invoices as invoices_route
from app.api.routes import projects as projects_route
from app.core.config import validate_runtime_config
from app.schemas.admin import CostEstimateUpsert, InvoiceUpsert, ProjectPatch
from app.schemas.tools import BookAppointmentRequest
from app.services import appointments as appt
from app.services.common import fetch_all_rows, run_parallel


# ─── fetch_all_rows (pagination past the 1000-row cap) ───────────────────────
class _PagedQuery:
    """Fake PostgREST builder: .range(lo,hi).execute().data returns that slice of
    a `total`-row table, capping each page at 1000 like the real backend."""

    def __init__(self, total: int):
        self.total = total
        self.lo = 0
        self.hi = 0

    def range(self, lo, hi):
        self.lo, self.hi = lo, max(lo, min(hi, lo + 999))  # PostgREST caps a page at 1000
        return self

    def execute(self):
        rows = [{"i": i} for i in range(self.lo, min(self.hi + 1, self.total))]
        return SimpleNamespace(data=rows, count=self.total)


def test_fetch_all_rows_pages_past_1000():
    out = fetch_all_rows(lambda: _PagedQuery(2500))
    assert len(out) == 2500
    assert out[0]["i"] == 0 and out[-1]["i"] == 2499  # every row, in order


def test_fetch_all_rows_exact_multiple_of_page():
    out = fetch_all_rows(lambda: _PagedQuery(2000))  # 2 full pages + an empty 3rd
    assert len(out) == 2000


def test_fetch_all_rows_single_partial_page():
    out = fetch_all_rows(lambda: _PagedQuery(5))
    assert [r["i"] for r in out] == [0, 1, 2, 3, 4]


def test_fetch_all_rows_empty():
    assert fetch_all_rows(lambda: _PagedQuery(0)) == []


# ─── run_parallel (fan-out helper) ───────────────────────────────────────────
def test_run_parallel_preserves_call_order():
    assert run_parallel(lambda: "a", lambda: "b", lambda: "c") == ["a", "b", "c"]


def test_run_parallel_empty_and_single():
    assert run_parallel() == []
    assert run_parallel(lambda: 42) == [42]


def test_run_parallel_runs_concurrently():
    # If the two thunks ran serially the total would be ~0.2s; concurrently ~0.1s.
    import time

    def slow():
        time.sleep(0.1)
        return 1

    start = time.time()
    out = run_parallel(slow, slow)
    assert out == [1, 1]
    assert time.time() - start < 0.18  # well under the 0.2s a serial run would take


def test_run_parallel_propagates_first_exception():
    def boom():
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        run_parallel(lambda: 1, boom)


# ─── dashboard date-filter validation (fail loud, not silent fallback) ───────
def test_validate_date_params_accepts_valid_and_empty():
    # None / "" = not provided (allowed); valid ISO date / datetime = allowed.
    dash._validate_date_params(None, "", "2026-01-15", "2026-03-01T10:00:00")


def test_validate_date_params_rejects_malformed():
    for bad in ("2026-13-45", "not-a-date", "15.01.2026"):
        with pytest.raises(HTTPException) as exc:
            dash._validate_date_params(bad)
        assert exc.value.status_code == 422


# ─── prod config fail-fast ───────────────────────────────────────────────────
def test_validate_runtime_config_flags_missing_secret_in_production():
    cfg = SimpleNamespace(
        is_production=True,
        master_webhook_secret="",
        supabase_url="https://x.supabase.co",
        supabase_service_role_key="svc",
    )
    problems = validate_runtime_config(cfg)
    assert any("MASTER_WEBHOOK_SECRET" in p for p in problems)


def test_validate_runtime_config_flags_missing_db_in_production():
    cfg = SimpleNamespace(
        is_production=True,
        master_webhook_secret="strong-secret",
        supabase_url="",
        supabase_service_role_key="",
    )
    problems = validate_runtime_config(cfg)
    assert any("SUPABASE" in p for p in problems)


def test_validate_runtime_config_silent_in_dev():
    cfg = SimpleNamespace(
        is_production=False,
        master_webhook_secret="",
        supabase_url="",
        supabase_service_role_key="",
    )
    assert validate_runtime_config(cfg) == []  # dev only warns, never blocks


# ─── book_appointment atomicity (orphan-inquiry rollback) ────────────────────
class _RollbackProbeClient:
    """inquiry insert succeeds; appointment insert RAISES; records inquiry deletes
    so the test can assert the orphaned inquiry was compensated."""

    def __init__(self):
        self.deleted: list[str] = []

    def table(self, name):
        return _RollbackProbeQuery(name, self)


class _RollbackProbeQuery:
    def __init__(self, name, parent):
        self.name, self.parent, self.op, self.vals = name, parent, None, None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, vals):
        if self.name == "appointments":
            raise RuntimeError("appointment insert failed")  # the mid-write failure
        self.op, self.vals = "insert", vals
        return self

    def delete(self):
        self.op = "delete"
        return self

    def execute(self):
        if self.op == "insert":
            row = dict(self.vals)
            row.setdefault("id", f"{self.name}-1")
            return SimpleNamespace(data=[row])
        if self.op == "delete":
            self.parent.deleted.append(self.name)
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[])


def test_book_appointment_rolls_back_inquiry_on_appointment_failure(monkeypatch):
    client = _RollbackProbeClient()
    monkeypatch.setattr(appt, "get_service_client", lambda: client)
    monkeypatch.setattr(appt, "_get_kiki_level", lambda c, o: 2)  # L2 → creates appointment
    monkeypatch.setattr(appt, "parse_when", lambda d, t: datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(appt, "get_or_create_customer", lambda *a, **k: {"id": "cust1", "display_name": "X"})
    monkeypatch.setattr(appt, "_first_employee", lambda c, o: {"id": "emp1", "display_name": "M"})
    monkeypatch.setattr(appt, "gen_inquiry_number", lambda c, o: "ANF-1")
    monkeypatch.setattr(appt, "_scheduling", lambda c, o: {"parallel_slots": 1})

    payload = BookAppointmentRequest(
        date="morgen", time="10:00", name="Test", phone="+4915112345678", conversation_id="c1"
    )
    # The appointment insert fails AFTER the inquiry was created → book_appointment
    # must delete the orphan inquiry and re-raise (no half-written state remains).
    with pytest.raises(RuntimeError):
        appt.book_appointment("org1", payload)
    assert client.deleted == ["inquiries"]


# ─── IDOR: write paths reject cross-tenant FK ids (POST *and* PATCH/UPDATE) ───
class _EmptyClient:
    """Every FK existence check returns no rows → validate_fk_in_org raises 422.
    Proves the guard fires; the write is never reached."""

    def table(self, name):
        return _EmptyQuery()


class _EmptyQuery:
    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=[], count=0)


@pytest.mark.parametrize(
    "invoke",
    [
        lambda: projects_route._patch("org1", "p1", ProjectPatch(customer_id="foreign")),
        lambda: invoices_route._update("org1", "i1", InvoiceUpsert(customer_id="foreign")),
        lambda: ce_route._create("org1", None, CostEstimateUpsert(customer_id="foreign")),
        lambda: ce_route._update("org1", "c1", CostEstimateUpsert(customer_id="foreign")),
    ],
    ids=["projects._patch", "invoices._update", "cost_estimates._create", "cost_estimates._update"],
)
def test_write_paths_reject_cross_org_fk(monkeypatch, invoke):
    # A customer_id from ANOTHER org (not found in this org) must 422 before any write.
    monkeypatch.setattr(projects_route, "get_service_client", lambda: _EmptyClient())
    monkeypatch.setattr(invoices_route, "get_service_client", lambda: _EmptyClient())
    monkeypatch.setattr(ce_route, "get_service_client", lambda: _EmptyClient())
    with pytest.raises(HTTPException) as exc:
        invoke()
    assert exc.value.status_code == 422
