"""Server-side customer-id (heykiki_org_id) auto-generation.

next_heykiki_org_id replaces manual entry (which produced clashes + typos like
'kiki-cutomer-0023'); it advances the Kiki-Kunde-NNN series. Offline: the
Supabase client is a tiny stub.
"""
from __future__ import annotations

from app.services import provisioning as pv


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *_a, **_k):
        return self

    def execute(self):
        return _Resp(self._data)


class _Client:
    def __init__(self, rows):
        self._rows = rows

    def table(self, *_a, **_k):
        return _Query(self._rows)


def test_next_id_increments_highest_in_series():
    client = _Client([
        {"heykiki_org_id": "Kiki-Kunde-001"},
        {"heykiki_org_id": "kiki-kunde-005"},      # lowercase still counts (no dup risk)
        {"heykiki_org_id": "Kiki-customer-1009"},  # different series → ignored
        {"heykiki_org_id": "kiki-accept-vennemann"},  # no number → ignored
        {"heykiki_org_id": None},
    ])
    assert pv.next_heykiki_org_id(client) == "Kiki-Kunde-006"


def test_next_id_starts_at_001_when_series_empty():
    client = _Client([{"heykiki_org_id": "kiki-customer-007"}, {"heykiki_org_id": "kiki-test-007"}])
    assert pv.next_heykiki_org_id(client) == "Kiki-Kunde-001"


def test_next_id_zero_pads_to_three_digits():
    client = _Client([{"heykiki_org_id": "Kiki-Kunde-008"}])
    assert pv.next_heykiki_org_id(client) == "Kiki-Kunde-009"


def test_next_id_grows_past_three_digits():
    client = _Client([{"heykiki_org_id": "Kiki-Kunde-0999"}])
    assert pv.next_heykiki_org_id(client) == "Kiki-Kunde-1000"
