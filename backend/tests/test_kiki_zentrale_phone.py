"""Kiki-Zentrale Telefon section — `existing_business_number` field.

Wave 1 / Agent 1.3 (2026-05-28) — the tradesperson stores their own existing
business number on `organizations.existing_business_number`, separate from
the `forwarding_number` / `incoming_forwarding_number` pair on
`agent_configs`. HeyKiki never bridges or dials this number — the
tradesperson configures their telco-level forward from this number to the
HeyKiki number (approach A, see §6.3 of the sprint doc).

Covers:
 - GET aggregator surfaces `existing_business_number` alongside `phone_number`.
 - PATCH `/phone` routes `existing_business_number` to the `organizations`
   table (NOT `agent_configs`) and leaves the two forwarding-pair columns on
   `agent_configs` untouched in the unrelated paths.
 - The E.164 validator rejects garbage values with HTTP 422 and accepts None
   / empty (stored as NULL).
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import kiki_zentrale as kz


def _org_admin() -> deps.CurrentUser:
    return deps.CurrentUser(
        id="user-1",
        email="admin@example.com",
        org_id="00000000-0000-0000-0000-000000000aaa",
        role="org_admin",
        full_name="Admin",
    )


# ─── GET aggregator surfaces existing_business_number ────────────────────────
def test_get_overview_surfaces_existing_business_number(monkeypatch):
    """The Telefon section reads `existing_business_number` from
    `data.existing_business_number` (sibling of `phone_number` in the overview
    response), NOT from `data.config.*`."""
    # Build a service client whose .table('organizations') select returns a
    # row carrying both phone_number AND existing_business_number, and whose
    # .table('agent_configs') select returns a stub config row.
    org_row = {
        "phone_number": "+4925197593899",
        "existing_business_number": "+4925112345678",
        "elevenlabs_agent_id": None,
        "name": "Test Org",
        "ai_minutes_quota": 1000,
    }
    cfg_row = {"forwarding_number": "+49 111", "incoming_forwarding_number": "+49 222"}

    client = MagicMock()

    def _table(name):
        chain = MagicMock()
        if name == "organizations":
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = MagicMock(data=[org_row])
        elif name == "agent_configs":
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = MagicMock(data=[cfg_row])
        elif name == "agent_config_snapshots":
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.order.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = MagicMock(data=[])
        return chain

    client.table = _table
    monkeypatch.setattr(kz, "get_service_client", lambda: client)

    out = kz._get_overview("00000000-0000-0000-0000-000000000aaa")

    assert out["phone_number"] == "+4925197593899"
    assert out["existing_business_number"] == "+4925112345678"
    # config dict stays clean — existing_business_number is NOT on agent_configs.
    assert "existing_business_number" not in out["config"]


# ─── PATCH /phone routes existing_business_number to organizations ──────────
def test_patch_phone_writes_existing_business_number_to_organizations(monkeypatch):
    """When the payload carries `existing_business_number`, the route updates
    `organizations.existing_business_number` (NOT agent_configs)."""
    writes: list[tuple[str, dict]] = []
    org_after = {"existing_business_number": "+4925112345678"}
    cfg_after = {"forwarding_number": None, "incoming_forwarding_number": None}

    client = MagicMock()

    def _table(name):
        chain = MagicMock()

        def _update(fields):
            writes.append((name, dict(fields)))
            chain.eq.return_value = chain
            chain.execute.return_value = MagicMock(data=[])
            return chain

        def _upsert(fields, **_kwargs):
            writes.append((name, dict(fields)))
            chain.execute.return_value = MagicMock(data=[])
            return chain

        chain.update = _update
        chain.upsert = _upsert
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        if name == "organizations":
            chain.execute.return_value = MagicMock(data=[org_after])
        elif name == "agent_configs":
            chain.execute.return_value = MagicMock(data=[cfg_after])
        return chain

    client.table = _table
    monkeypatch.setattr(kz, "get_service_client", lambda: client)

    payload = kz.PhoneUpdate(existing_business_number="+4925112345678")
    # The repush/sync pipeline is exercised elsewhere — keep this test offline.
    async def _noop_repush(*a, **k):
        return None

    monkeypatch.setattr(kz, "_schedule_repush", _noop_repush)
    result = asyncio.run(kz.update_phone(payload, MagicMock(), user=_org_admin()))

    # The new field was written to `organizations`.
    org_writes = [w for w in writes if w[0] == "organizations"]
    assert len(org_writes) == 1
    assert org_writes[0][1].get("existing_business_number") == "+4925112345678"
    # No agent_configs write — the only field in the payload belongs on organizations.
    assert all(w[0] != "agent_configs" for w in writes)
    # Response surfaces the new value alongside the cfg.
    assert result["existing_business_number"] == "+4925112345678"


def test_patch_phone_writes_forwarding_pair_to_agent_configs(monkeypatch):
    """When only the forwarding pair is sent, the route still writes
    `agent_configs` and leaves `organizations` alone."""
    writes: list[tuple[str, dict]] = []

    client = MagicMock()

    def _table(name):
        chain = MagicMock()

        def _update(fields):
            writes.append((name, dict(fields)))
            chain.eq.return_value = chain
            chain.execute.return_value = MagicMock(data=[])
            return chain

        def _upsert(fields, **_kwargs):
            writes.append((name, dict(fields)))
            chain.execute.return_value = MagicMock(data=[])
            return chain

        chain.update = _update
        chain.upsert = _upsert
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(
            data=[{"forwarding_number": "+49 151 1111111", "incoming_forwarding_number": "+49 152 2222222"}]
        )
        return chain

    client.table = _table
    monkeypatch.setattr(kz, "get_service_client", lambda: client)

    payload = kz.PhoneUpdate(
        forwarding_number="+49 151 1111111",
        incoming_forwarding_number="+49 152 2222222",
    )
    async def _noop_repush(*a, **k):
        return None

    monkeypatch.setattr(kz, "_schedule_repush", _noop_repush)
    asyncio.run(kz.update_phone(payload, MagicMock(), user=_org_admin()))

    cfg_writes = [w for w in writes if w[0] == "agent_configs"]
    assert len(cfg_writes) == 1
    assert cfg_writes[0][1].get("forwarding_number") == "+49 151 1111111"
    assert cfg_writes[0][1].get("incoming_forwarding_number") == "+49 152 2222222"
    # No organizations write — existing_business_number wasn't in the payload.
    assert all(w[0] != "organizations" for w in writes)


# ─── Validator behavior ─────────────────────────────────────────────────────
def test_existing_business_number_validator_rejects_garbage():
    payload = kz.PhoneUpdate(existing_business_number="not-a-number")
    with pytest.raises(HTTPException) as exc:
        payload.cleaned_existing_business_number()
    assert exc.value.status_code == 422


def test_existing_business_number_validator_accepts_e164():
    payload = kz.PhoneUpdate(existing_business_number="+4925112345678")
    assert payload.cleaned_existing_business_number() == "+4925112345678"


def test_existing_business_number_validator_treats_blank_as_none():
    payload = kz.PhoneUpdate(existing_business_number="   ")
    assert payload.cleaned_existing_business_number() is None


def test_existing_business_number_validator_accepts_none():
    payload = kz.PhoneUpdate(existing_business_number=None)
    assert payload.cleaned_existing_business_number() is None


def test_existing_business_number_validator_allows_spaces_and_dashes():
    """German numbers are often pasted with spaces or dashes — accept them
    as long as the underlying digit-count + leading + are well-formed."""
    payload = kz.PhoneUpdate(existing_business_number="+49 251 1234-5678")
    # The cleaned form keeps the original text (we only normalise for
    # validation, not for storage) — but it must NOT raise.
    assert payload.cleaned_existing_business_number() == "+49 251 1234-5678"
