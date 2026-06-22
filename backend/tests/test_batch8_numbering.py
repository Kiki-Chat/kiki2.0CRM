"""Batch 8 numbering-guard tests.

Hermetic unit tests — no network, no DB.

Coverage:
  - format_ki_number: canonical KI-NNNNNN formatting.
  - csv_import.import_customers: CSV row with verbatim KI-NNNNNN gets a
    fresh minted number instead of being stored verbatim (collision guard).
  - routes/customers._update: PATCH with blank customer_number is rejected 422.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.common import format_ki_number


# ─── 8.4a: format_ki_number ──────────────────────────────────────────────────

def test_format_ki_number_basic():
    assert format_ki_number(7) == "KI-000007"


def test_format_ki_number_zero_padded():
    assert format_ki_number(1) == "KI-000001"
    assert format_ki_number(123456) == "KI-123456"
    assert format_ki_number(1000000) == "KI-1000000"  # beyond 6 digits — still works


# ─── 8.4b: CSV import — KI- verbatim collision guard ─────────────────────────

def _fake_client_for_csv(existing_ki_max: int = 5):
    """Minimal fake Supabase client sufficient for import_customers."""

    class _Res:
        def __init__(self, data):
            self.data = data
            self.count = len(data)

    class _Query:
        def __init__(self, data):
            self._data = data

        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def neq(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, n, **k):
            self._data = self._data[:n]
            return self
        def range(self, s, e): return self
        def insert(self, rows, **k):
            self._inserted = rows
            return self
        def execute(self):
            return _Res(list(self._data))

    class _FakeClient:
        def __init__(self):
            # existing DB: one KI- number at max_seq; dedup will see its phone
            self._customers = [
                {"customer_number": format_ki_number(existing_ki_max),
                 "email": None, "phone": None, "phone2": None, "full_name": "Existing"}
            ]
            self.last_insert = []

        def table(self, name):
            if name == "customers":
                return _TableProxy(self)
            raise ValueError(f"Unknown table: {name}")

    class _TableProxy:
        def __init__(self, fc):
            self._fc = fc

        def select(self, *a, **k): return _SelQuery(self._fc)
        def insert(self, rows, **k):
            self._fc.last_insert = rows
            return _InsQuery(rows)

    class _SelQuery:
        def __init__(self, fc):
            self._fc = fc

        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def neq(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, n, **k): return self
        def range(self, s, e): return self

        def execute(self):
            return _Res(list(self._fc._customers))

    class _InsQuery:
        def __init__(self, rows):
            self._rows = rows

        def execute(self):
            return _Res(list(self._rows))

    return _FakeClient()


def _csv_bytes(rows: list[dict]) -> bytes:
    """Build a minimal semicolon CSV from a list of dicts."""
    import csv, io
    buf = io.StringIO()
    headers = list(rows[0].keys())
    w = csv.DictWriter(buf, fieldnames=headers, delimiter=";")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def test_csv_ki_verbatim_replaced_by_fresh():
    """A CSV row whose Kundennummer starts with 'KI-' must NOT be stored verbatim;
    it should receive a freshly minted KI- number (collision guard)."""
    from app.services import csv_import

    fake = _fake_client_for_csv(existing_ki_max=5)
    csv_data = _csv_bytes([
        {"Name": "Anna Muster", "Telefon": "015123456789", "Kundennummer": "KI-000123"},
    ])
    mapping = {"full_name": "Name", "phone": "Telefon", "customer_number": "Kundennummer"}

    with patch("app.services.csv_import.get_service_client", return_value=fake):
        result = csv_import.import_customers("org-test", csv_data, mapping)

    assert result["imported"] == 1
    inserted = fake.last_insert
    assert len(inserted) == 1
    stored_num = inserted[0]["customer_number"]
    # Must NOT be the verbatim CSV value
    assert stored_num != "KI-000123", f"Stored verbatim KI- value: {stored_num}"
    # Must still be a valid KI- number
    assert stored_num.startswith("KI-"), f"Expected KI- prefix, got: {stored_num}"
    # Must be the next in sequence after the existing DB max (5 → KI-000006)
    assert stored_num == "KI-000006", f"Expected KI-000006, got: {stored_num}"


def test_csv_non_ki_verbatim_kept():
    """A CSV Kundennummer that does NOT start with 'KI-' is preserved verbatim."""
    from app.services import csv_import

    fake = _fake_client_for_csv(existing_ki_max=5)
    csv_data = _csv_bytes([
        {"Name": "Bob Beispiel", "Telefon": "015199887766", "Kundennummer": "101001"},
    ])
    mapping = {"full_name": "Name", "phone": "Telefon", "customer_number": "Kundennummer"}

    with patch("app.services.csv_import.get_service_client", return_value=fake):
        result = csv_import.import_customers("org-test", csv_data, mapping)

    assert result["imported"] == 1
    stored_num = fake.last_insert[0]["customer_number"]
    assert stored_num == "101001"


# ─── 8.4c: PATCH blank customer_number rejected ──────────────────────────────

def test_patch_blank_customer_number_rejected():
    """_update with blank/whitespace-only customer_number must raise HTTP 422.

    We call the sync helper _update directly (bypassing FastAPI routing) so the
    guard in _update itself is exercised, not a mock that replaces it.
    """
    from fastapi import HTTPException
    from app.api.routes.customers import _update
    from app.schemas.admin import CustomerUpsert

    # blank string
    payload_blank = CustomerUpsert(customer_number="")
    with pytest.raises(HTTPException) as exc_info:
        with patch("app.api.routes.customers.get_service_client") as mock_client:
            _update("org-test", "some-uuid", payload_blank)
    assert exc_info.value.status_code == 422

    # whitespace only
    payload_ws = CustomerUpsert(customer_number="   ")
    with pytest.raises(HTTPException) as exc_info2:
        with patch("app.api.routes.customers.get_service_client"):
            _update("org-test", "some-uuid", payload_ws)
    assert exc_info2.value.status_code == 422


def test_patch_nonempty_customer_number_allowed():
    """_update with a non-empty customer_number must pass the guard and reach the DB."""
    from app.api.routes.customers import _update
    from app.schemas.admin import CustomerUpsert

    # Build a minimal fake client that records the update call
    class _Res:
        def __init__(self, data): self.data = data

    class _Q:
        def __init__(self): self._updated = None
        def select(self, *a, **k): return self
        def update(self, fields, **k):
            self._updated = fields
            return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return _Res([{"id": "some-uuid", "customer_number": "MANUAL-1"}])

    q = _Q()

    class _FC:
        def table(self, name): return q

    with patch("app.api.routes.customers.get_service_client", return_value=_FC()):
        # Also stub find_existing_customer so dedup guard passes
        with patch("app.api.routes.customers.find_existing_customer", return_value=None):
            result = _update("org-test", "some-uuid", CustomerUpsert(customer_number="MANUAL-1"))

    assert result is not None
    assert q._updated is not None
    assert q._updated.get("customer_number") == "MANUAL-1"
