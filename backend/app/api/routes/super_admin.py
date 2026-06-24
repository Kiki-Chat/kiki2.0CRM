"""Super-admin org management (P0.6).

All endpoints gated by `require_super_admin` (role='super_admin'). Provides
CRUD + soft-disable/re-enable + delete (with X-Confirm-Delete header matching
the org name) over the organizations table.

The CREATE endpoint is a thin wrapper around app.services.provisioning.provision_org
— the same code path the existing POST /api/heykiki/provision uses with the
master secret. Super-admin auth replaces the master-secret check.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_super_admin
from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.schemas.provision import ProvisionRequest
from app.services.agent_config import (
    configure_agent,
    fetch_phone_meta_for_agent,
    set_phone_environment,
    verify_agent_health,
)
from app.services.history_import import import_agent_history
from app.services.provisioning import provision_org

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/super-admin", tags=["super-admin"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Schemas ─────────────────────────────────────────────────────────────────
class OrgPatch(BaseModel):
    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    elevenlabs_agent_id: str | None = None
    model_config = {"extra": "ignore"}


class CreateOrgResponse(BaseModel):
    """Response shape for POST /api/super-admin/orgs.

    Deliberately omits `org_secret` — that value is system-level (used by the
    ElevenLabs post-call webhook handler) and NOT per-customer, so exposing it
    in this UI was misleading. Identification of the right org for an incoming
    payload happens via `agent_id` + caller `phone_number` lookup, not via a
    per-org secret. The provisioning service-layer may still generate / persist
    a value into `org_secrets`; we just don't echo it back here.
    """

    org_id: str
    admin_user_id: str
    heykiki_org_id: str


# ─── Helpers ─────────────────────────────────────────────────────────────────
_ORG_LIST_COLS = (
    "id, heykiki_org_id, name, email, phone_number, elevenlabs_agent_id, "
    "disabled_at, created_at, updated_at"
)


def _list_orgs() -> list[dict]:
    client = get_service_client()
    rows = (
        client.table("organizations")
        .select(_ORG_LIST_COLS)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    return rows


def _get_org(org_id: str) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("organizations")
        .select("*")
        .eq("id", org_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _patch_org(org_id: str, payload: dict) -> dict | None:
    if not payload:
        return _get_org(org_id)
    # P0.6 safety: never expose disabled_at via PATCH — must go through
    # /disable + /enable so the audit story stays clean. Same for created_at.
    for forbidden in ("disabled_at", "created_at", "id"):
        payload.pop(forbidden, None)
    payload["updated_at"] = _now()
    client = get_service_client()
    rows = (
        client.table("organizations")
        .update(payload)
        .eq("id", org_id)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _set_disabled(org_id: str, disabled: bool) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("organizations")
        .update(
            {
                "disabled_at": _now() if disabled else None,
                "updated_at": _now(),
            }
        )
        .eq("id", org_id)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _delete_org(org_id: str) -> bool:
    """Hard delete. organizations cascades to users / customers / calls / etc.
    via ON DELETE CASCADE in 0001_init_schema.sql."""
    client = get_service_client()
    res = client.table("organizations").delete().eq("id", org_id).execute()
    return bool(res.data)


# ─── Routes ──────────────────────────────────────────────────────────────────
def _org_stats(org_ids: list[str]) -> dict[str, dict]:
    """Per-org usage counts + last activity for the standalone admin list.

    Cheap aggregate over the major tables. Each query is org_id-filtered and
    returns only the counts; no row data is read. ``last_activity`` = max of
    calls.created_at / appointments.created_at / cost_estimates.created_at
    / invoices.created_at, or None if all tables are empty for the org.
    """
    if not org_ids:
        return {}
    client = get_service_client()
    stats: dict[str, dict] = {
        oid: {
            "calls": 0,
            "kvas_sent": 0,
            "employees": 0,
            "appointments": 0,
            "last_activity": None,
        }
        for oid in org_ids
    }

    def _count_by_org(table: str, key: str, extra_eq: tuple[str, str] | None = None) -> None:
        for oid in org_ids:
            q = client.table(table).select("id", count="exact", head=True).eq("org_id", oid)
            if extra_eq:
                q = q.eq(extra_eq[0], extra_eq[1])
            try:
                res = q.execute()
                stats[oid][key] = int(getattr(res, "count", 0) or 0)
            except Exception:
                stats[oid][key] = 0

    _count_by_org("calls", "calls")
    _count_by_org("cost_estimates", "kvas_sent", extra_eq=("status", "sent"))
    _count_by_org("employees", "employees")
    _count_by_org("appointments", "appointments")

    # Last activity: max(created_at) across calls / appointments / cost_estimates / invoices.
    for oid in org_ids:
        latest: str | None = None
        for table in ("calls", "appointments", "cost_estimates", "invoices"):
            try:
                rows = (
                    client.table(table)
                    .select("created_at")
                    .eq("org_id", oid)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                if rows and rows[0].get("created_at"):
                    ts = rows[0]["created_at"]
                    if latest is None or ts > latest:
                        latest = ts
            except Exception:
                continue
        stats[oid]["last_activity"] = latest

    return stats


@router.get("/orgs")
async def list_orgs(_user: CurrentUser = Depends(require_super_admin)) -> dict:
    """List all organizations (super-admin only)."""
    rows = await run_in_threadpool(_list_orgs)
    return {"orgs": rows}


@router.get("/orgs-stats")
async def list_orgs_stats(_user: CurrentUser = Depends(require_super_admin)) -> dict:
    """Usage counters per org for the standalone admin org list.

    Returns ``{org_id: {calls, kvas_sent, employees, appointments, last_activity}}``.
    Separate from ``GET /orgs`` so the master-data list stays cheap and the
    counter query (which fans out across 4 tables × N orgs) can be loaded
    lazily / cached independently on the frontend.
    """
    orgs = await run_in_threadpool(_list_orgs)
    org_ids = [o["id"] for o in orgs]
    stats = await run_in_threadpool(_org_stats, org_ids)
    return {"stats": stats}


@router.get("/orgs/{org_id}")
async def get_org(
    org_id: str,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    org = await run_in_threadpool(_get_org, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    return org


@router.patch("/orgs/{org_id}")
async def patch_org(
    org_id: str,
    payload: OrgPatch,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    body = payload.model_dump(exclude_unset=True)
    updated = await run_in_threadpool(_patch_org, org_id, body)
    if not updated:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    return updated


@router.post("/orgs/{org_id}/disable")
async def disable_org(
    org_id: str,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Soft-disable: sets disabled_at = now(). Users in this org will be blocked
    from login with 'Diese Organisation ist deaktiviert' until re-enabled."""
    updated = await run_in_threadpool(_set_disabled, org_id, True)
    if not updated:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    return updated


@router.post("/orgs/{org_id}/enable")
async def enable_org(
    org_id: str,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Re-enable a previously disabled org. Clears disabled_at."""
    updated = await run_in_threadpool(_set_disabled, org_id, False)
    if not updated:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    return updated


@router.delete("/orgs/{org_id}")
async def delete_org(
    org_id: str,
    x_confirm_delete: str | None = Header(default=None, alias="X-Confirm-Delete"),
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Hard delete — irreversible. Cascades to users / customers / calls /
    inquiries / appointments / cost_estimates / invoices / etc.

    Requires X-Confirm-Delete header matching the org's `name` exactly.
    Same pattern as the org_admin /api/settings/organization DELETE."""
    org = await run_in_threadpool(_get_org, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    expected = (org.get("name") or "").strip()
    if (x_confirm_delete or "").strip() != expected:
        raise HTTPException(
            status_code=400,
            detail="Bestätigungstext stimmt nicht mit dem Organisationsnamen überein.",
        )
    ok = await run_in_threadpool(_delete_org, org_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Löschen fehlgeschlagen.")
    return {"success": True, "deleted_org_id": org_id}


# ─── Create org (thin wrapper around provisioning) ──────────────────────────
@router.post("/orgs", response_model=CreateOrgResponse)
async def create_org(
    payload: ProvisionRequest,
    background_tasks: BackgroundTasks,
    _user: CurrentUser = Depends(require_super_admin),
) -> CreateOrgResponse:
    """Create a new org. Reuses app.services.provisioning.provision_org —
    the same code path as POST /api/heykiki/provision. Super-admin auth
    replaces the master-secret check here, since the caller is already a
    trusted super-admin (no shared-secret round-trip needed).

    Response shape deliberately omits `org_secret` (B.6, 2026-05-27): that
    value is system-level (used by the ElevenLabs post-call webhook handler)
    and NOT per-customer. The "show secret once" panel was misleading —
    payload-to-org identification happens via `agent_id` + caller `phone_number`
    lookup, not via per-org secret matching. provision_org may still return /
    persist a secret-shaped value; we ignore it at this layer.

    P0.9 parity (2026-05-27 fix): mirrors /api/heykiki/provision by
    scheduling import_agent_history as a BackgroundTask so historical
    ElevenLabs conversations get backfilled into the new org's calls
    table. Without this, orgs created via the super-admin surface would
    start with empty Call Logs even when the bound agent had prior
    conversations. Idempotent via the P0.2 SELECT-first dedup.
    """
    response = await run_in_threadpool(provision_org, payload)
    background_tasks.add_task(
        import_agent_history,
        org_id=response.org_id,
        agent_id=payload.elevenlabs_agent_id,
    )
    return CreateOrgResponse(
        org_id=response.org_id,
        admin_user_id=response.user_id,
        heykiki_org_id=response.heykiki_org_id,
    )


# ─── Convenience: promote/demote (for the one-shot super-admin user flow) ────
class RoleChange(BaseModel):
    role: str  # 'super_admin' | 'org_admin' | 'employee'


# ─── Manual re-trigger for the post-provision history import (P0.9) ─────────
@router.post("/orgs/{org_id}/import-history")
async def import_history(
    org_id: str,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Re-trigger the historical EL-conversation import for an existing org.
    Idempotent via the P0.2 SELECT-first dedup, so re-runs only process
    newly-appeared conversations."""
    org = await run_in_threadpool(_get_org, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    agent_id = org.get("elevenlabs_agent_id")
    if not agent_id:
        raise HTTPException(
            status_code=400,
            detail="Diese Organisation hat keine ElevenLabs Agent ID hinterlegt.",
        )
    counters = await run_in_threadpool(import_agent_history, org_id, agent_id)
    return {"success": True, "org_id": org_id, **counters}


# ─── B.7: manual agent-config sync (backfill for pre-Wave-1 orgs) ───────────
class SyncAgentConfigRequest(BaseModel):
    """Body for POST /api/super-admin/orgs/{id}/sync-agent-config.

    ``force=False`` (default) is the safe behavior: ``configure_agent`` skips
    the prompt step on orgs whose ``agent_provisioned_at`` is already set, so
    customer-edited prompts are never overwritten.

    ``force=True`` clears ``agent_provisioned_at`` before the run so the prompt
    step is re-applied from the master template. **Destructive** — any local
    edits to the agent's prompt in ElevenLabs will be replaced. Reserved for
    deliberate template re-rollouts. The safety layer's pre-write snapshot
    still allows manual rollback if needed.
    """

    force: bool = False
    model_config = {"extra": "ignore"}


class AgentHealthCheck(BaseModel):
    name: str
    ok: bool
    detail: str


class AgentHealthReport(BaseModel):
    """2.1 verify-gate report — matches verify_agent_health()'s return shape and
    the shared per-org agent-health contract."""

    ok: bool
    provisioned_at: str | None = None
    checks: list[AgentHealthCheck]


class SyncAgentConfigResponse(BaseModel):
    """Response shape mirrors the summary dict returned by ``configure_agent``,
    plus the 2.1 post-provision verify report so the caller sees ok/red and is
    never silently told a red agent is provisioned."""

    org_id: str
    agent_id: str
    phone_number: str | None
    phone_bound: bool
    phone_message: str | None
    tools_attached: list[str]
    prompt_applied: bool
    prompt_skipped_reason: str | None
    webhook_enabled: bool
    audio_ok: bool
    verify: AgentHealthReport


@router.post("/orgs/{org_id}/sync-agent-config", response_model=SyncAgentConfigResponse)
async def sync_agent_config(
    org_id: str,
    payload: SyncAgentConfigRequest | None = None,
    _user: CurrentUser = Depends(require_super_admin),
) -> SyncAgentConfigResponse:
    """Backfill / re-apply the ElevenLabs agent configuration for an existing org.

    Calls the same ``configure_agent`` helper that ``provision_org`` invokes
    on first-create (B.1 phone fetch → B.2 hk_* tools merge → B.3 master prompt
    (skipped on re-runs unless ``force=True``) → B.4 conversation-init webhook →
    B.5 audio assertion). All ElevenLabs writes route through ``patch_agent_safely``
    (snapshot + verify + auto-rollback + audit) so a failure mid-run leaves
    an audit trail and a snapshot for manual recovery.

    Use case: orgs created before Wave 1 (commit ``9c3aaf1``) had no automatic
    agent configuration on provision — they need this one-shot backfill so the
    agent gets phone/tools/webhook wired without a full re-provision.

    Errors raised by ``configure_agent`` (missing phone, missing workspace tool,
    EL HTTP error, verify failure) surface as HTTP 400 with the error message —
    these are operator-actionable, not 500s.
    """
    org = await run_in_threadpool(_get_org, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    agent_id = org.get("elevenlabs_agent_id")
    if not agent_id:
        raise HTTPException(
            status_code=400,
            detail="Diese Organisation hat keine ElevenLabs Agent ID hinterlegt.",
        )
    org_name = (org.get("name") or "").strip()
    if not org_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "Diese Organisation hat keinen Namen — der Prompt-Substitution "
                "fehlt damit der Wert für die Firmennamen-Platzhalter."
            ),
        )

    body = payload or SyncAgentConfigRequest()
    if body.force:
        # Clear the provisioned-at stamp so configure_agent re-applies the prompt.
        # The configure_agent call below will re-stamp on success.
        def _clear_stamp() -> None:
            client = get_service_client()
            client.table("organizations").update(
                {"agent_provisioned_at": None}
            ).eq("id", org_id).execute()

        await run_in_threadpool(_clear_stamp)

    try:
        summary = await run_in_threadpool(
            configure_agent,
            org_id=org_id,
            agent_id=agent_id,
            org_name=org_name,
            actor_id=_user.id,
        )
    except HTTPException:
        # configure_agent raises HTTPException(400) for user-actionable failures
        # (missing phone, missing workspace tool). Let those propagate as-is.
        raise
    except Exception as e:
        # ElevenLabsWriteError / SilentAgentRiskError / VerificationFailedError
        # and any other service-layer failure: surface as 400 with the message
        # so the operator can act on it. Snapshot + audit row already exist
        # via patch_agent_safely; manual rollback is possible.
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 2.1 — post-provision verify gate: re-read the live agent and assert every
    # contract check. Surfaced in the response so the operator sees ok/red and is
    # NOT silently told a red agent is provisioned. Read-only; never writes.
    report = await run_in_threadpool(verify_agent_health, org_id, agent_id)

    return SyncAgentConfigResponse(
        org_id=org_id,
        agent_id=agent_id,
        phone_number=summary.get("phone_number"),
        phone_bound=bool(summary.get("phone_bound")),
        phone_message=summary.get("phone_message"),
        tools_attached=list(summary.get("tools_attached") or []),
        prompt_applied=bool(summary.get("prompt_applied")),
        prompt_skipped_reason=summary.get("prompt_skipped_reason"),
        webhook_enabled=bool(summary.get("webhook_enabled")),
        audio_ok=bool(summary.get("audio_ok")),
        verify=AgentHealthReport(**report),
    )


# ─── n8n BIND-ONLY: re-bind an externally-rebuilt agent ─────────────────────
class BindAgentRequest(BaseModel):
    """Body for POST /api/super-admin/orgs/{id}/bind-agent.

    n8n now CREATES the ElevenLabs agent (prompt + tools + webhook + number)
    externally and the CRM only BINDS it. This endpoint writes the agent ids
    onto an EXISTING org and runs the READ-ONLY ``verify_agent_health`` — it
    NEVER calls ``configure_agent`` (which would clobber n8n's prompt/tools/
    webhook). Use it to re-bind an org to an agent n8n rebuilt.

    Assumptions (n8n contract): n8n set the EL conversation-init webhook to the
    prod backend URL + ``X-HeyKiki-Secret`` header (the CRM only verifies it),
    and passes ``elevenlabs_phone_number_id`` (needed for outbound).
    """

    elevenlabs_agent_id: str = Field(..., alias="elevenlabsAgentId")
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    elevenlabs_phone_number_id: str | None = Field(
        default=None, alias="elevenlabsPhoneNumberId"
    )
    model_config = {"populate_by_name": True, "extra": "ignore"}


class BindAgentResponse(BaseModel):
    """Response for the bind-agent endpoint: the written ids + verify report."""

    org_id: str
    elevenlabs_agent_id: str
    phone_number: str | None
    elevenlabs_phone_number_id: str | None
    # The ElevenLabs environment this number was pinned to during the bind
    # (``"uat"`` on the UAT backend, ``None`` otherwise — prod keeps EL's
    # default 'production'). Lets the super-admin UI confirm the pin took.
    environment: str | None = None
    verify: AgentHealthReport


@router.post("/orgs/{org_id}/bind-agent", response_model=BindAgentResponse)
async def bind_agent(
    org_id: str,
    payload: BindAgentRequest,
    _user: CurrentUser = Depends(require_super_admin),
) -> BindAgentResponse:
    """BIND an n8n-rebuilt ElevenLabs agent onto an existing org (no re-config).

    Writes ``elevenlabs_agent_id`` + ``phone_number`` +
    ``elevenlabs_phone_number_id`` onto the org, stamps ``agent_provisioned_at``,
    then runs the READ-ONLY ``verify_agent_health`` and returns the report.

    Deliberately does NOT call ``configure_agent`` — n8n owns the agent's
    prompt/tools/webhook/number and re-running configure_agent would clobber
    them. For the legacy CRM-builds-the-agent path use ``sync-agent-config``
    instead. A red verify is reported (not an error): the agent is n8n's to
    fix, and the operator sees ok/red.
    """
    org = await run_in_threadpool(_get_org, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")

    agent_id = (payload.elevenlabs_agent_id or "").strip()
    if not agent_id:
        raise HTTPException(
            status_code=400,
            detail="Es wurde keine ElevenLabs Agent ID übergeben.",
        )

    def _bind() -> None:
        client = get_service_client()
        patch: dict = {
            "elevenlabs_agent_id": agent_id,
            "agent_provisioned_at": _now(),
            "updated_at": _now(),
        }
        if payload.phone_number is not None:
            patch["phone_number"] = payload.phone_number
        if payload.elevenlabs_phone_number_id is not None:
            patch["elevenlabs_phone_number_id"] = payload.elevenlabs_phone_number_id
        client.table("organizations").update(patch).eq("id", org_id).execute()

    await run_in_threadpool(_bind)

    # Pin the phone to the UAT environment so ElevenLabs resolves
    # {{system__env_api_host}} (shared tools + the conversation-init webhook) to
    # the UAT backend for every call on this number. UAT-ONLY: the prod backend
    # (el_environment='production') leaves the phone at EL's default 'production',
    # and n8n / the /provision path are untouched — "production remains the same".
    # Best-effort: a pin failure must NOT fail the bind (the agent is already
    # bound); it's logged and surfaced as environment=None.
    pinned_environment: str | None = None
    if settings.el_environment == "uat":
        def _pin() -> str | None:
            phone_id = (payload.elevenlabs_phone_number_id or "").strip()
            if not phone_id:
                # n8n didn't pass the id — resolve it from the agent binding.
                phone_id = (
                    fetch_phone_meta_for_agent(agent_id).get("phone_number_id") or ""
                )
            if not phone_id:
                logger.warning(
                    "bind-agent: no phone_number_id for org %s agent %s; "
                    "skipped environment pin.", org_id, agent_id,
                )
                return None
            set_phone_environment(phone_id, "uat", agent_id)
            return "uat"

        try:
            pinned_environment = await run_in_threadpool(_pin)
        except Exception:  # noqa: BLE001 — never fail the bind over the pin
            logger.warning(
                "bind-agent: environment pin failed for org %s agent %s",
                org_id, agent_id, exc_info=True,
            )

    # Read-only verify gate — never writes to the agent.
    report = await run_in_threadpool(verify_agent_health, org_id, agent_id)

    return BindAgentResponse(
        org_id=org_id,
        elevenlabs_agent_id=agent_id,
        phone_number=payload.phone_number,
        elevenlabs_phone_number_id=payload.elevenlabs_phone_number_id,
        environment=pinned_environment,
        verify=AgentHealthReport(**report),
    )


# ─── 2.4: agent-health endpoints (per the shared B2 contract) ───────────────
class AgentHealthBoardRow(BaseModel):
    """One row of the cross-org agent-health board.

    ``red_checks`` lists the names of the failed checks (empty when ok=true).
    Orgs with no agent bound are reported with ok=false and a single
    ``no_agent`` red marker rather than being dropped, so the board stays a
    complete census of provisioned orgs.
    """

    org_id: str
    name: str
    ok: bool
    red_checks: list[str]


def _agent_health_board() -> list[dict]:
    """Build the board summary across all orgs.

    Reuses ``verify_agent_health`` per org. Orgs without an
    ``elevenlabs_agent_id`` are reported red with a ``no_agent`` marker (no live
    read attempted). Each org's verify is independently guarded so one
    unreachable agent can't sink the whole board.
    """
    orgs = _list_orgs()
    board: list[dict] = []
    for org in orgs:
        oid = org["id"]
        name = org.get("name") or ""
        agent_id = org.get("elevenlabs_agent_id")
        if not agent_id:
            board.append(
                {"org_id": oid, "name": name, "ok": False, "red_checks": ["no_agent"]}
            )
            continue
        try:
            report = verify_agent_health(oid, agent_id)
            red = [c["name"] for c in report.get("checks", []) if not c.get("ok")]
            board.append(
                {"org_id": oid, "name": name, "ok": bool(report.get("ok")), "red_checks": red}
            )
        except Exception:  # noqa: BLE001 — one bad org never sinks the board
            board.append(
                {"org_id": oid, "name": name, "ok": False, "red_checks": ["verify_failed"]}
            )
    return board


@router.get("/agent-health", response_model=list[AgentHealthBoardRow])
async def agent_health_board(
    _user: CurrentUser = Depends(require_super_admin),
) -> list[AgentHealthBoardRow]:
    """Cross-org agent-health board summary (super-admin only).

    Returns ``[{org_id, name, ok, red_checks}]`` for every org. Reuses
    ``verify_agent_health`` per org; orgs with no agent or an unreachable agent
    read red rather than erroring the whole board.
    """
    rows = await run_in_threadpool(_agent_health_board)
    return [AgentHealthBoardRow(**r) for r in rows]


@router.get("/orgs/{org_id}/agent-health", response_model=AgentHealthReport)
async def org_agent_health(
    org_id: str,
    _user: CurrentUser = Depends(require_super_admin),
) -> AgentHealthReport:
    """Per-org agent-health report (super-admin only).

    Returns the full ``verify_agent_health`` report: ``{ok, provisioned_at,
    checks:[{name, ok, detail}]}``. Read-only — never writes to the agent.
    An org with no agent bound reads red (every check failed) rather than 500.
    """
    org = await run_in_threadpool(_get_org, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    agent_id = org.get("elevenlabs_agent_id")
    if not agent_id:
        # No agent bound: report red with a single actionable check, not a 500.
        return AgentHealthReport(
            ok=False,
            provisioned_at=org.get("agent_provisioned_at"),
            checks=[
                AgentHealthCheck(
                    name="no_agent",
                    ok=False,
                    detail="Diese Organisation hat keine ElevenLabs Agent ID hinterlegt.",
                )
            ],
        )
    report = await run_in_threadpool(verify_agent_health, org_id, agent_id)
    return AgentHealthReport(**report)


@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: str | UUID,
    payload: RoleChange,
    _user: CurrentUser = Depends(require_super_admin),
) -> dict:
    """Promote/demote a user's role. Allowed roles match the existing schema.

    Enforces Amber's 'only one super_admin' constraint: rejects any attempt
    to promote a second user to super_admin. The DB-level partial unique
    index `uniq_one_super_admin` (migration 0020) is the backstop.
    """
    if payload.role not in ("super_admin", "org_admin", "employee"):
        raise HTTPException(status_code=400, detail="Unbekannte Rolle.")

    def _do() -> dict | None:
        client = get_service_client()
        if payload.role == "super_admin":
            existing = (
                client.table("users")
                .select("id")
                .eq("role", "super_admin")
                .neq("id", str(user_id))
                .limit(1)
                .execute()
                .data
                or []
            )
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Es kann nur einen Super-Admin geben. Bitte zuerst den "
                        "bestehenden Super-Admin demoten."
                    ),
                )
        rows = (
            client.table("users")
            .update({"role": payload.role})
            .eq("id", str(user_id))
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    updated = await run_in_threadpool(_do)
    if not updated:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
    return {"id": updated["id"], "role": updated["role"]}
