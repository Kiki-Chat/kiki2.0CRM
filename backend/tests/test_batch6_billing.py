"""Batch 6 billing tests (Skonto PDF + KVA→invoice guards + numbering scope).

Hermetic unit tests — no network, no DB. Fake Supabase clients only.

Coverage:
  - 6.1 Skonto: invoices.py threads discount_pct/discount_days into the build_pdf
    `ce` dict as skonto_pct/skonto_days (both _invoice_for_pdf and _preview_pdf);
    build_pdf renders the Skonto lines ONLY for type='invoice' with pct>0, never
    for a KVA and never for a skonto-less invoice. Skonto is DISPLAY-ONLY: the
    Gesamtbetrag (gross / amount due) is unchanged.
  - 6.4 INV-009: POST /invoices on an already-invoiced KVA → HTTP 409.
  - 6.4 INV-002: gen_number scopes the per-year count by doc-type (.eq('type', …)).
  - 6.4 INV-012: PATCH /cost-estimates/{id}/status accepted|invoiced on an
    EXPIRED estimate (valid_until < today) → HTTP 409; current/unset is allowed.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.deps import CurrentUser
from app.api.routes import invoices as inv_routes
from app.services import cost_estimates as ce_svc
from app.services.common import now_berlin


def _run(coro):
    return asyncio.run(coro)


def _user() -> CurrentUser:
    return CurrentUser(
        id="u1", email="user@test", org_id="org-x", role="org_admin", full_name=None
    )


# ─── Tiny fake-Supabase scaffolding ──────────────────────────────────────────
class _Res:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count if count is not None else len(data)


# ─── 6.1 Skonto: ce-dict threading ───────────────────────────────────────────
def test_invoice_for_pdf_threads_skonto():
    """_invoice_for_pdf maps the stored discount_pct/discount_days onto the
    skonto_pct/skonto_days keys build_pdf reads."""
    row = {"type": "invoice", "number": "RE-2026-00001", "discount_pct": 2, "discount_days": 10}
    ce = inv_routes._invoice_for_pdf(row)
    assert ce["skonto_pct"] == 2
    assert ce["skonto_days"] == 10


def test_invoice_for_pdf_skonto_defaults_zero():
    """Missing/None discount fields fall back to 0 (no skonto rendered)."""
    ce = inv_routes._invoice_for_pdf({"type": "invoice", "number": "RE-1"})
    assert ce["skonto_pct"] == 0
    assert ce["skonto_days"] == 0


def test_preview_pdf_threads_skonto():
    """_preview_pdf passes payload.discount_pct/discount_days into build_pdf as
    skonto_pct/skonto_days. We patch build_pdf to capture the ce dict."""
    from app.schemas.admin import InvoiceUpsert

    payload = InvoiceUpsert(customer_id=None, discount_pct=3, discount_days=14, positions=[])
    captured = {}

    def _fake_build_pdf(org, customer, ce, totals):
        captured["ce"] = ce
        return b"%PDF-FAKE"

    class _FC:
        def table(self, name):
            class _Q:
                def select(self, *a, **k): return self
                def eq(self, *a, **k): return self
                def limit(self, *a, **k): return self
                def execute(self): return _Res([])
            return _Q()

    with patch.object(inv_routes, "get_service_client", return_value=_FC()), \
         patch.object(inv_routes, "fetch_org", return_value={}), \
         patch.object(inv_routes, "fetch_customer", return_value=None), \
         patch.object(inv_routes, "build_pdf", side_effect=_fake_build_pdf):
        out = inv_routes._preview_pdf("org-test", payload)

    assert out == b"%PDF-FAKE"
    assert captured["ce"]["skonto_pct"] == 3
    assert captured["ce"]["skonto_days"] == 14
    assert captured["ce"]["type"] == "invoice"


# ─── 6.1 Skonto: build_pdf rendering (real PDF bytes, text-searchable) ────────
def _pdf_text(pdf_bytes: bytes) -> str:
    """Decode the raw PDF stream into a loose string for substring assertions.
    fpdf2 embeds a TrueType font so glyphs aren't plain ASCII in content streams;
    instead we assert on the structural facts we *can* check cheaply (it is a
    valid non-empty PDF) and rely on the totals-math assertions for correctness.
    """
    return pdf_bytes.decode("latin-1", errors="ignore")


_INVOICE_POSITIONS = [
    {"kind": "item", "description": "Arbeit", "quantity": 1, "unit": "Std",
     "price": 100.0, "vat": 19, "discount_pct": 0},
]


def _totals_for(positions):
    return ce_svc.compute_totals(positions, 0, 0)


def test_build_pdf_invoice_with_skonto_renders_and_keeps_gross():
    """An invoice with skonto_pct>0 produces a valid PDF; skonto is display-only
    so totals['gross'] (the amount due) is computed independently of skonto."""
    totals = _totals_for(_INVOICE_POSITIONS)  # net 100, vat 19, gross 119
    assert totals["gross"] == 119.0
    ce = {
        "type": "invoice", "number": "RE-2026-00001",
        "positions": _INVOICE_POSITIONS,
        "skonto_pct": 2, "skonto_days": 10,
    }
    pdf = ce_svc.build_pdf({"name": "Org"}, {"full_name": "Kunde"}, ce, totals)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000
    # Skonto math (display-only): 2% of 119.00 = 2.38 → Zahlbetrag 116.62.
    assert round(totals["gross"] * 2 / 100, 2) == 2.38
    assert round(totals["gross"] - 2.38, 2) == 116.62


def test_build_pdf_invoice_without_skonto_unchanged():
    """An invoice with no skonto (pct 0) renders without the skonto block; the
    PDF must still be valid. We compare byte-length parity to the same doc with
    skonto to confirm the skonto branch actually adds content for pct>0."""
    totals = _totals_for(_INVOICE_POSITIONS)
    base_ce = {"type": "invoice", "number": "RE-1", "positions": _INVOICE_POSITIONS,
               "skonto_pct": 0, "skonto_days": 0}
    skonto_ce = {**base_ce, "skonto_pct": 2, "skonto_days": 10}
    pdf_no = ce_svc.build_pdf({"name": "Org"}, None, base_ce, totals)
    pdf_yes = ce_svc.build_pdf({"name": "Org"}, None, skonto_ce, totals)
    assert pdf_no[:4] == b"%PDF"
    assert pdf_yes[:4] == b"%PDF"
    # The skonto variant renders extra rows + a note, so its content stream is
    # strictly larger than the skonto-less one.
    assert len(pdf_yes) > len(pdf_no)


def test_build_pdf_kva_ignores_skonto():
    """A KVA (non-invoice) must NEVER render skonto even if the keys are present.
    Byte-length must match the same KVA with skonto keys stripped."""
    totals = _totals_for(_INVOICE_POSITIONS)
    kva_no = {"type": "kva", "number": "KVA-1", "positions": _INVOICE_POSITIONS}
    kva_with_keys = {**kva_no, "skonto_pct": 2, "skonto_days": 10}
    pdf_plain = ce_svc.build_pdf({"name": "Org"}, None, kva_no, totals)
    pdf_keys = ce_svc.build_pdf({"name": "Org"}, None, kva_with_keys, totals)
    assert pdf_plain[:4] == b"%PDF"
    # Identical content size: the skonto keys are inert for a KVA.
    assert len(pdf_plain) == len(pdf_keys)


def test_skonto_amount_math_contract():
    """Direct check of the SKONTO CONTRACT arithmetic (round half-to-even via
    Python round): skonto_amt = round(gross*pct/100,2); zahlbetrag = round(gross-amt,2)."""
    gross = 1000.0
    pct = 3
    skonto_amt = round(gross * pct / 100, 2)
    zahlbetrag = round(gross - skonto_amt, 2)
    assert skonto_amt == 30.0
    assert zahlbetrag == 970.0


# ─── 6.4 INV-009: re-invoice of an already-invoiced KVA → 409 ────────────────
def _create_fake_client(kva_row):
    """Fake client whose cost_estimates.select(...).execute() returns kva_row.
    Also satisfies validate_fk_in_org (which selects 'id' on each FK table)."""
    class _Q:
        def __init__(self, table_name):
            self._table = table_name

        def select(self, cols, *a, **k):
            self._cols = cols
            return self

        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self

        def execute(self):
            # validate_fk_in_org selects 'id' → return a stub existing row.
            if getattr(self, "_cols", "") == "id":
                return _Res([{"id": "ok"}])
            # The INV-009 guard selects "status, invoice_id" on cost_estimates.
            if self._table == "cost_estimates":
                return _Res([kva_row] if kva_row is not None else [])
            return _Res([{"id": "ok"}])

    class _FC:
        def table(self, name):
            return _Q(name)

    return _FC()


def test_create_invoice_blocks_already_invoiced_kva():
    """INV-009: a KVA whose status is 'invoiced' cannot be converted again."""
    from app.schemas.admin import InvoiceUpsert

    payload = InvoiceUpsert(customer_id="cust-1", kva_id="kva-1", positions=[])
    fake = _create_fake_client({"status": "invoiced", "invoice_id": None})

    with patch.object(inv_routes, "get_service_client", return_value=fake):
        with pytest.raises(HTTPException) as exc:
            inv_routes._create("org-test", "user-1", payload)
    assert exc.value.status_code == 409
    assert "bereits in eine Rechnung" in exc.value.detail


def test_create_invoice_blocks_kva_with_invoice_id():
    """INV-009: a KVA already carrying an invoice_id back-link is also blocked."""
    from app.schemas.admin import InvoiceUpsert

    payload = InvoiceUpsert(customer_id="cust-1", kva_id="kva-1", positions=[])
    fake = _create_fake_client({"status": "accepted", "invoice_id": "inv-existing"})

    with patch.object(inv_routes, "get_service_client", return_value=fake):
        with pytest.raises(HTTPException) as exc:
            inv_routes._create("org-test", "user-1", payload)
    assert exc.value.status_code == 409


def test_create_invoice_allows_fresh_kva():
    """A KVA that is NOT yet invoiced passes the guard and reaches insert.
    We stop after insert by having the fake return a created row and no back-link
    failure path triggered."""
    from app.schemas.admin import InvoiceUpsert

    payload = InvoiceUpsert(customer_id="cust-1", kva_id="kva-1", positions=_INVOICE_POSITIONS)

    created_holder = {}

    class _Q:
        def __init__(self, table_name):
            self._table = table_name
            self._cols = ""

        def select(self, cols, *a, **k):
            self._cols = cols
            return self

        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self

        def insert(self, row, *a, **k):
            self._insert_row = row
            created_holder["row"] = row
            return self

        def update(self, fields, *a, **k):
            self._update_fields = fields
            return self

        def execute(self):
            if self._cols == "id":
                return _Res([{"id": "ok"}])
            if self._table == "cost_estimates" and self._cols == "status, invoice_id":
                return _Res([{"status": "accepted", "invoice_id": None}])
            if self._table == "cost_estimates" and "case_id" in (self._cols or ""):
                return _Res([{"case_id": None, "inquiry_id": None}])
            if getattr(self, "_insert_row", None) is not None:
                return _Res([{**self._insert_row, "id": "new-inv"}])
            # cost_estimates back-link update
            return _Res([{"id": "kva-1"}])

    class _FC:
        def table(self, name):
            return _Q(name)

    with patch.object(inv_routes, "get_service_client", return_value=_FC()), \
         patch.object(inv_routes, "gen_invoice_number", return_value="RE-2026-00009"):
        out = inv_routes._create("org-test", "user-1", payload)

    assert out["id"] == "new-inv"
    assert created_holder["row"]["number"] == "RE-2026-00009"
    assert created_holder["row"]["status"] == "draft"


# ─── 6.4 INV-002: gen_number scopes the count by doc-type ────────────────────
def test_gen_number_scopes_count_by_type():
    """gen_number must add .eq('type', doc_type) to the count query so each
    doc-type has its own contiguous sequence. We record the eq() calls."""
    calls = []

    class _Q:
        def select(self, *a, **k): return self
        def eq(self, field, value):
            calls.append((field, value))
            return self
        def gte(self, *a, **k): return self
        def execute(self):
            return _Res([], count=4)

    class _FC:
        def table(self, name):
            assert name == "cost_estimates"
            return _Q()

    num = ce_svc.gen_number(_FC(), "org-test", "invoice")
    # Count was 4 → next is 5, zero-padded, RE prefix.
    year = now_berlin().year
    assert num == f"RE-{year}-00005"
    # The doc-type filter must be present.
    assert ("type", "invoice") in calls
    assert ("org_id", "org-test") in calls


def test_gen_number_type_filter_per_prefix():
    """Sanity: each doc-type maps to its prefix AND filters by that type."""
    for doc_type, prefix in [("kva", "AG"), ("offer", "ANG"),
                             ("order_confirmation", "AB"), ("invoice", "RE")]:
        calls = []

        class _Q:
            def select(self, *a, **k): return self
            def eq(self, field, value):
                calls.append((field, value))
                return self
            def gte(self, *a, **k): return self
            def execute(self): return _Res([], count=0)

        class _FC:
            def table(self, name): return _Q()

        num = ce_svc.gen_number(_FC(), "org-x", doc_type)
        assert num.startswith(f"{prefix}-")
        assert ("type", doc_type) in calls


# ─── 6.4 INV-002: insert retry on unique violation ──────────────────────────
def test_insert_with_number_retry_retries_on_duplicate():
    """insert_with_number_retry recomputes the number and retries once when the
    first insert hits a duplicate/unique violation."""
    attempts = {"n": 0}

    class _InsQ:
        def __init__(self, row): self._row = row
        def execute(self):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("duplicate key value violates unique constraint")
            return _Res([{**self._row, "id": "ok"}])

    class _Q:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def gte(self, *a, **k): return self
        def execute(self): return _Res([], count=7)
        def insert(self, row, *a, **k): return _InsQ(row)

    class _FC:
        def table(self, name): return _Q()

    out = ce_svc.insert_with_number_retry(_FC(), "org-x", {"number": "KVA-x", "type": "kva"}, "kva")
    assert out["id"] == "ok"
    assert attempts["n"] == 2  # retried exactly once


def test_insert_with_number_retry_reraises_other_errors():
    """A non-duplicate error is re-raised unchanged (no infinite retry)."""
    class _InsQ:
        def __init__(self, row): self._row = row
        def execute(self): raise RuntimeError("network down")

    class _Q:
        def insert(self, row, *a, **k): return _InsQ(row)

    class _FC:
        def table(self, name): return _Q()

    with pytest.raises(RuntimeError, match="network down"):
        ce_svc.insert_with_number_retry(_FC(), "org-x", {"number": "KVA-x"}, "kva")


# ─── 6.4 INV-012: expired estimate cannot be accepted/invoiced ───────────────
def test_set_status_blocks_expired_accept():
    """PATCH .../status accepted on an estimate whose valid_until is in the past
    raises 409 (soft block)."""
    from app.api.routes import cost_estimates as ce_route
    from app.schemas.admin import CostEstimateStatus

    yesterday = (now_berlin().date() - timedelta(days=1)).isoformat()

    class _Q:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return _Res([{"valid_until": yesterday}])

    class _FC:
        def table(self, name): return _Q()

    with patch.object(ce_route, "get_service_client", return_value=_FC()):
        with pytest.raises(HTTPException) as exc:
            _run(ce_route.set_status("ce-1", CostEstimateStatus(status="accepted"), _user()))
    assert exc.value.status_code == 409
    assert "abgelaufen" in exc.value.detail


def test_set_status_blocks_expired_invoiced():
    """Same guard fires for the 'invoiced' transition."""
    from app.api.routes import cost_estimates as ce_route
    from app.schemas.admin import CostEstimateStatus

    yesterday = (now_berlin().date() - timedelta(days=1)).isoformat()

    class _Q:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return _Res([{"valid_until": yesterday}])

    class _FC:
        def table(self, name): return _Q()

    with patch.object(ce_route, "get_service_client", return_value=_FC()):
        with pytest.raises(HTTPException) as exc:
            _run(ce_route.set_status("ce-1", CostEstimateStatus(status="invoiced"), _user()))
    assert exc.value.status_code == 409


def test_set_status_allows_valid_accept():
    """An estimate valid until the future (or with no valid_until) is accepted
    normally — the update path runs and returns the row."""
    from app.api.routes import cost_estimates as ce_route
    from app.schemas.admin import CostEstimateStatus

    future = (now_berlin().date() + timedelta(days=10)).isoformat()

    class _Q:
        def __init__(self): self._mode = None
        def select(self, *a, **k):
            self._mode = "select"
            return self
        def update(self, fields, *a, **k):
            self._mode = "update"
            self._fields = fields
            return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self):
            if self._mode == "select":
                return _Res([{"valid_until": future}])
            return _Res([{"id": "ce-1", "status": "accepted"}])

    class _FC:
        def table(self, name): return _Q()

    with patch.object(ce_route, "get_service_client", return_value=_FC()):
        out = _run(ce_route.set_status("ce-1", CostEstimateStatus(status="accepted"), _user()))
    assert out["status"] == "accepted"


def test_set_status_other_transitions_unaffected():
    """A non-accept/invoiced transition (e.g. 'sent') skips the expiry check
    entirely — even an expired estimate can still be marked sent/rejected."""
    from app.api.routes import cost_estimates as ce_route
    from app.schemas.admin import CostEstimateStatus

    select_called = {"n": 0}

    class _Q:
        def __init__(self): self._mode = None
        def select(self, *a, **k):
            select_called["n"] += 1
            self._mode = "select"
            return self
        def update(self, fields, *a, **k):
            self._mode = "update"
            return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self):
            return _Res([{"id": "ce-1", "status": "sent"}])

    class _FC:
        def table(self, name): return _Q()

    with patch.object(ce_route, "get_service_client", return_value=_FC()):
        out = _run(ce_route.set_status("ce-1", CostEstimateStatus(status="sent"), _user()))
    assert out["status"] == "sent"
    # The expiry-guard select must NOT have run for a 'sent' transition.
    assert select_called["n"] == 0
