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


# ─── create_org response shape — no org_secret leak (B.6) ───────────────────
def test_create_org_response_omits_org_secret(monkeypatch):
    """B.6 (2026-05-27): the per-org `org_secret` was misleading in the UI
    (it's a system-level webhook secret, not a per-customer credential).
    The route must echo back ONLY org_id / admin_user_id / heykiki_org_id,
    even if the underlying provision_org service still returns a secret.
    """
    import asyncio
    from app.schemas.provision import ProvisionRequest

    # Stub provision_org to return a ProvisionResponse-shaped object that
    # still includes a secret — verifies the route layer drops it.
    class _StubProvisionResponse:
        org_id = "00000000-0000-0000-0000-000000000aaa"
        user_id = "00000000-0000-0000-0000-000000000bbb"
        heykiki_org_id = "kiki-customer-test"
        org_secret = "should-NOT-appear-in-response"

    monkeypatch.setattr(sa, "provision_org", lambda payload: _StubProvisionResponse())
    monkeypatch.setattr(sa, "import_agent_history", lambda **_kw: None)

    payload = ProvisionRequest(
        heykikiOrgId="kiki-customer-test",
        orgName="Kiki Customer Test",
        loginEmail="admin@example.com",
        loginPassword="password-1234",
        elevenlabsAgentId="agent_test",
    )

    # FastAPI normally injects BackgroundTasks; pass a real one for the unit test.
    from starlette.background import BackgroundTasks

    bg = BackgroundTasks()
    user = deps.CurrentUser(id="u", email="a@b", org_id=None, role="super_admin", full_name=None)
    result = asyncio.run(sa.create_org(payload=payload, background_tasks=bg, _user=user))

    # Returned object is the new CreateOrgResponse — no `org_secret` attribute.
    assert isinstance(result, sa.CreateOrgResponse)
    assert result.org_id == "00000000-0000-0000-0000-000000000aaa"
    assert result.admin_user_id == "00000000-0000-0000-0000-000000000bbb"
    assert result.heykiki_org_id == "kiki-customer-test"

    # JSON serialization (what FastAPI sends over the wire) must not contain the secret.
    dumped = result.model_dump()
    assert "org_secret" not in dumped
    assert set(dumped.keys()) == {"org_id", "admin_user_id", "heykiki_org_id"}


# ─── B.7 sync-agent-config route ─────────────────────────────────────────────
def _super_admin_user() -> deps.CurrentUser:
    return deps.CurrentUser(
        id="00000000-0000-0000-0000-000000000001",
        email="amber@gmail.com",
        org_id=None,
        role="super_admin",
        full_name="Amber",
    )


def _org_admin_user() -> deps.CurrentUser:
    return deps.CurrentUser(
        id="user-1",
        email="admin@example.com",
        org_id="org-1",
        role="org_admin",
        full_name=None,
    )


def test_sync_agent_config_rejects_non_super_admin():
    """Auth gate: org_admin / employee MUST NOT be able to hit this route.
    require_super_admin raises 403 — the route never executes."""
    with pytest.raises(HTTPException) as exc:
        deps.require_super_admin(_org_admin_user())
    assert exc.value.status_code == 403


def test_sync_agent_config_returns_404_when_org_missing(monkeypatch):
    """404 when org_id has no matching row."""
    import asyncio

    monkeypatch.setattr(sa, "_get_org", lambda _oid: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            sa.sync_agent_config(
                org_id="missing-org",
                payload=None,
                _user=_super_admin_user(),
            )
        )
    assert exc.value.status_code == 404
    assert "nicht gefunden" in exc.value.detail


def test_sync_agent_config_400_when_org_has_no_agent_id(monkeypatch):
    """400 when the org row exists but has no elevenlabs_agent_id."""
    import asyncio

    monkeypatch.setattr(
        sa,
        "_get_org",
        lambda _oid: {"id": _oid, "name": "Acme", "elevenlabs_agent_id": None},
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            sa.sync_agent_config(
                org_id="org-no-agent",
                payload=None,
                _user=_super_admin_user(),
            )
        )
    assert exc.value.status_code == 400
    assert "Agent ID" in exc.value.detail


def test_sync_agent_config_happy_path_returns_summary(monkeypatch):
    """Happy path: ``configure_agent`` returns a known summary; the route
    echoes it back as a ``SyncAgentConfigResponse``."""
    import asyncio

    org_id = "00000000-0000-0000-0000-000000000aaa"
    agent_id = "agent_test_001"
    monkeypatch.setattr(
        sa,
        "_get_org",
        lambda _oid: {
            "id": _oid,
            "name": "Acme GmbH",
            "elevenlabs_agent_id": agent_id,
        },
    )

    expected_summary = {
        "phone_number": "+4925197593899",
        "tools_attached": ["tool_aaa", "tool_bbb"],
        "prompt_applied": True,
        "prompt_skipped_reason": None,
        "webhook_enabled": True,
        "audio_ok": True,
    }
    captured: dict = {}

    def _fake_configure(*, org_id, agent_id, org_name, actor_id=None):
        captured["org_id"] = org_id
        captured["agent_id"] = agent_id
        captured["org_name"] = org_name
        captured["actor_id"] = actor_id
        return expected_summary

    monkeypatch.setattr(sa, "configure_agent", _fake_configure)

    result = asyncio.run(
        sa.sync_agent_config(
            org_id=org_id,
            payload=None,
            _user=_super_admin_user(),
        )
    )

    assert isinstance(result, sa.SyncAgentConfigResponse)
    assert result.org_id == org_id
    assert result.agent_id == agent_id
    assert result.phone_number == "+4925197593899"
    assert result.tools_attached == ["tool_aaa", "tool_bbb"]
    assert result.prompt_applied is True
    assert result.prompt_skipped_reason is None
    assert result.webhook_enabled is True
    assert result.audio_ok is True

    # configure_agent received the right args from the route.
    assert captured["org_id"] == org_id
    assert captured["agent_id"] == agent_id
    assert captured["org_name"] == "Acme GmbH"
    assert captured["actor_id"] == "00000000-0000-0000-0000-000000000001"


def test_sync_agent_config_propagates_400_from_configure_agent(monkeypatch):
    """HTTPException raised by configure_agent (missing phone / missing tool)
    passes through unchanged — operator-actionable 400 stays a 400."""
    import asyncio

    monkeypatch.setattr(
        sa,
        "_get_org",
        lambda _oid: {
            "id": _oid,
            "name": "Acme GmbH",
            "elevenlabs_agent_id": "agent_test_001",
        },
    )

    def _raises(**_kw):
        raise HTTPException(
            status_code=400, detail="Agent has no phone number assigned in ElevenLabs."
        )

    monkeypatch.setattr(sa, "configure_agent", _raises)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            sa.sync_agent_config(
                org_id="org-1",
                payload=None,
                _user=_super_admin_user(),
            )
        )
    assert exc.value.status_code == 400
    assert "phone number" in exc.value.detail


def test_sync_agent_config_wraps_unexpected_error_as_400(monkeypatch):
    """ElevenLabsWriteError / VerificationFailedError / generic exceptions
    are wrapped as HTTP 400 (not 500) so the operator sees the actual message."""
    import asyncio

    monkeypatch.setattr(
        sa,
        "_get_org",
        lambda _oid: {
            "id": _oid,
            "name": "Acme GmbH",
            "elevenlabs_agent_id": "agent_test_001",
        },
    )

    def _raises(**_kw):
        raise RuntimeError("EL verify failed: tools array shrank after write.")

    monkeypatch.setattr(sa, "configure_agent", _raises)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            sa.sync_agent_config(
                org_id="org-1",
                payload=None,
                _user=_super_admin_user(),
            )
        )
    assert exc.value.status_code == 400
    assert "tools array shrank" in exc.value.detail


def test_sync_agent_config_force_clears_provisioned_stamp(monkeypatch):
    """force=True must clear organizations.agent_provisioned_at BEFORE
    configure_agent runs so the prompt step gets re-applied."""
    import asyncio

    org_id = "org-1"
    monkeypatch.setattr(
        sa,
        "_get_org",
        lambda _oid: {
            "id": _oid,
            "name": "Acme GmbH",
            "elevenlabs_agent_id": "agent_test_001",
        },
    )

    cleared = {"called": False, "value": None}

    class _Chain:
        def __init__(self, name):
            self.name = name
            self.payload = None

        def update(self, payload):
            self.payload = payload
            return self

        def eq(self, _col, _val):
            return self

        def execute(self):
            if self.name == "organizations" and self.payload is not None:
                cleared["called"] = True
                cleared["value"] = self.payload.get("agent_provisioned_at", "MISSING")
            return MagicMock(data=[])

    client = MagicMock()
    client.table = lambda name: _Chain(name)
    monkeypatch.setattr(sa, "get_service_client", lambda: client)
    monkeypatch.setattr(
        sa,
        "configure_agent",
        lambda **_kw: {
            "phone_number": "+49000",
            "tools_attached": [],
            "prompt_applied": True,
            "prompt_skipped_reason": None,
            "webhook_enabled": True,
            "audio_ok": True,
        },
    )

    asyncio.run(
        sa.sync_agent_config(
            org_id=org_id,
            payload=sa.SyncAgentConfigRequest(force=True),
            _user=_super_admin_user(),
        )
    )

    assert cleared["called"] is True
    assert cleared["value"] is None  # explicit NULL clear, not omission
