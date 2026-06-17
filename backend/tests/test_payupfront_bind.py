"""Hermetic tests for the n8n BIND-ONLY agent-provisioning seam.

n8n now CREATES the ElevenLabs agent (prompt + tools + webhook + number)
externally; the CRM must BIND it WITHOUT re-running ``configure_agent`` (which
would clobber n8n's prompt/tools/webhook). These tests pin that contract:

  * ``provision_org(agent_externally_managed=True)`` does NOT call
    configure_agent, DOES run the read-only verify_agent_health, and STORES the
    agent id + phone + phone_number_id + agent_provisioned_at on the org row.
  * ``provision_org(agent_externally_managed=False)`` (default) is unchanged —
    it still calls configure_agent and does NOT verify.
  * ``POST /api/super-admin/orgs/{id}/bind-agent`` writes the agent/phone fields,
    stamps provisioned, runs verify_agent_health, and returns the report — all
    WITHOUT calling configure_agent.

No network, no DB: the Supabase client + auth + configure_agent /
verify_agent_health are stubbed.
"""

from __future__ import annotations

import asyncio

import pytest

from app.api import deps
from app.api.routes import super_admin as sa
from app.schemas.provision import ProvisionRequest
from app.services import provisioning as prov


AGENT_ID = "agent_n8n_built"
PHONE = "+4925197593899"
PHONE_ID = "phnum_n8n_1"

# A green-ish verify report shape (verify_agent_health's return contract).
_VERIFY_OK = {
    "ok": True,
    "provisioned_at": "2026-06-17T10:00:00+00:00",
    "checks": [
        {"name": "hk_tools_attached", "ok": True, "detail": "ok"},
        {"name": "webhook_url_is_prod", "ok": True, "detail": "ok"},
        {"name": "webhook_enabled", "ok": True, "detail": "ok"},
        {"name": "audio_event_present", "ok": True, "detail": "ok"},
        {"name": "prompt_rendered", "ok": True, "detail": "ok"},
        {"name": "override_flags_on", "ok": True, "detail": "ok"},
        {"name": "phone_bound", "ok": True, "detail": "ok"},
    ],
}


# ─── table-routing fake Supabase client (mirrors test_round2_features) ────────
class _Result:
    def __init__(self, data):
        self.data = data
        self.count = len(data) if data else 0


class _Query:
    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._insert_rows = None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def delete(self, *a, **k):
        return self

    def update(self, vals):
        self._store["updates"].append((self._table, dict(vals)))
        return self

    def insert(self, vals):
        rows = vals if isinstance(vals, list) else [vals]
        out = []
        for i, r in enumerate(rows):
            row = dict(r)
            row.setdefault("id", f"{self._table}-{i}")
            out.append(row)
        self._store["inserts"].append((self._table, [dict(r) for r in rows]))
        self._insert_rows = out
        return self

    def execute(self):
        if self._insert_rows is not None:
            return _Result(self._insert_rows)
        return _Result(list(self._store["reads"].get(self._table, [])))


class _Auth:
    class admin:  # noqa: N801 — mirrors supabase client.auth.admin namespace
        @staticmethod
        def create_user(payload):
            class _U:
                id = "user-stub-id"

            class _R:
                user = _U()

            return _R()

        @staticmethod
        def delete_user(uid):
            return None


class FakeClient:
    def __init__(self, reads=None):
        self.store = {"reads": reads or {}, "inserts": [], "updates": []}
        self.auth = _Auth()

    def table(self, name):
        return _Query(self.store, name)


def _org_inserts(client: FakeClient) -> list[dict]:
    return [
        r
        for (t, rows) in client.store["inserts"]
        if t == "organizations"
        for r in rows
    ]


def _base_payload(**overrides) -> ProvisionRequest:
    data = dict(
        heykikiOrgId="kiki-bind-test",
        orgName="Bind Test GmbH",
        loginEmail="admin@bindtest.example",
        loginPassword="password-1234",
        elevenlabsAgentId=AGENT_ID,
    )
    data.update(overrides)
    return ProvisionRequest(**data)


def _wire_provisioning(monkeypatch):
    """Stub the service client + configure_agent + verify_agent_health, return a
    call-recorder dict so each test can assert which path ran."""
    client = FakeClient(reads={"organizations": [], "users": []})
    monkeypatch.setattr(prov, "get_service_client", lambda: client)

    calls = {"configure": 0, "verify": 0, "verify_args": None}

    def _configure(*, org_id, agent_id, org_name, **kw):
        calls["configure"] += 1
        return {"phone_number": None}

    def _verify(org_id, agent_id):
        calls["verify"] += 1
        calls["verify_args"] = (org_id, agent_id)
        return dict(_VERIFY_OK)

    monkeypatch.setattr(prov, "configure_agent", _configure)
    monkeypatch.setattr(prov, "verify_agent_health", _verify)
    return client, calls


# ─── provision_org: bind-only path ───────────────────────────────────────────
def test_bind_only_skips_configure_and_verifies(monkeypatch):
    client, calls = _wire_provisioning(monkeypatch)
    payload = _base_payload(
        agentExternallyManaged=True,
        phoneNumber=PHONE,
        elevenlabsPhoneNumberId=PHONE_ID,
    )

    resp = prov.provision_org(payload)

    # configure_agent NOT called; verify_agent_health WAS called on the new agent.
    assert calls["configure"] == 0
    assert calls["verify"] == 1
    assert calls["verify_args"][1] == AGENT_ID

    # The verify report is surfaced on the response.
    assert resp.agent_health == _VERIFY_OK

    # Org row stored agent id + phone + phone_number_id + provisioned stamp.
    org = _org_inserts(client)[0]
    assert org["elevenlabs_agent_id"] == AGENT_ID
    assert org["phone_number"] == PHONE
    assert org["elevenlabs_phone_number_id"] == PHONE_ID
    assert org.get("agent_provisioned_at")  # non-empty ISO timestamp


def test_bind_only_without_phone_still_stamps_and_verifies(monkeypatch):
    """phone fields are optional — bind still stamps provisioned + verifies."""
    client, calls = _wire_provisioning(monkeypatch)
    payload = _base_payload(agentExternallyManaged=True)

    resp = prov.provision_org(payload)

    assert calls["configure"] == 0
    assert calls["verify"] == 1
    org = _org_inserts(client)[0]
    assert org["elevenlabs_agent_id"] == AGENT_ID
    assert org.get("agent_provisioned_at")
    # No phone passed → no phone keys forced onto the row.
    assert "phone_number" not in org
    assert "elevenlabs_phone_number_id" not in org
    assert resp.agent_health == _VERIFY_OK


# ─── provision_org: default (CRM-builds-the-agent) path unchanged ────────────
def test_default_path_still_calls_configure_agent(monkeypatch):
    client, calls = _wire_provisioning(monkeypatch)
    payload = _base_payload()  # agent_externally_managed defaults to False

    resp = prov.provision_org(payload)

    # Default behavior preserved: configure_agent runs, verify does NOT.
    assert calls["configure"] == 1
    assert calls["verify"] == 0
    assert resp.agent_health is None

    # No bind-only fields stamped onto the org insert.
    org = _org_inserts(client)[0]
    assert "agent_provisioned_at" not in org
    assert "phone_number" not in org
    assert "elevenlabs_phone_number_id" not in org


# ─── bind-agent endpoint ─────────────────────────────────────────────────────
def _super_admin_user() -> deps.CurrentUser:
    return deps.CurrentUser(
        id="00000000-0000-0000-0000-000000000001",
        email="amber@gmail.com",
        org_id=None,
        role="super_admin",
        full_name="Amber",
    )


def test_bind_agent_endpoint_writes_fields_and_verifies(monkeypatch):
    existing_org = {"id": "org-existing", "name": "Bestehende GmbH"}
    client = FakeClient(reads={"organizations": [existing_org]})

    monkeypatch.setattr(sa, "get_service_client", lambda: client)
    monkeypatch.setattr(sa, "_get_org", lambda oid: dict(existing_org))

    verify_calls = {"n": 0, "args": None}

    def _verify(org_id, agent_id):
        verify_calls["n"] += 1
        verify_calls["args"] = (org_id, agent_id)
        return dict(_VERIFY_OK)

    monkeypatch.setattr(sa, "verify_agent_health", _verify)

    payload = sa.BindAgentRequest(
        elevenlabsAgentId="agent_rebuilt_by_n8n",
        phoneNumber=PHONE,
        elevenlabsPhoneNumberId=PHONE_ID,
    )

    result = asyncio.run(
        sa.bind_agent(
            org_id="org-existing", payload=payload, _user=_super_admin_user()
        )
    )

    # verify ran against the newly-bound agent.
    assert verify_calls["n"] == 1
    assert verify_calls["args"] == ("org-existing", "agent_rebuilt_by_n8n")

    # The org row was UPDATED (not configured) with agent id + phone + stamp.
    org_updates = [v for (t, v) in client.store["updates"] if t == "organizations"]
    assert len(org_updates) == 1
    patch = org_updates[0]
    assert patch["elevenlabs_agent_id"] == "agent_rebuilt_by_n8n"
    assert patch["phone_number"] == PHONE
    assert patch["elevenlabs_phone_number_id"] == PHONE_ID
    assert patch.get("agent_provisioned_at")

    # Response carries the ids + verify report.
    assert result.elevenlabs_agent_id == "agent_rebuilt_by_n8n"
    assert result.phone_number == PHONE
    assert result.elevenlabs_phone_number_id == PHONE_ID
    assert result.verify.ok is True
    assert [c.name for c in result.verify.checks] == [
        c["name"] for c in _VERIFY_OK["checks"]
    ]


def test_bind_agent_endpoint_404_when_org_missing(monkeypatch):
    monkeypatch.setattr(sa, "_get_org", lambda oid: None)
    monkeypatch.setattr(
        sa, "verify_agent_health", lambda *a, **k: pytest.fail("must not verify")
    )
    payload = sa.BindAgentRequest(elevenlabsAgentId="agent_x")
    with pytest.raises(Exception) as exc:
        asyncio.run(
            sa.bind_agent(org_id="missing", payload=payload, _user=_super_admin_user())
        )
    # FastAPI HTTPException with 404.
    assert getattr(exc.value, "status_code", None) == 404
