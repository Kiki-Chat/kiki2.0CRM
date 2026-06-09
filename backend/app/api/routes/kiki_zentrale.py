"""Kiki-Zentrale — the tradesperson's full control surface over their AI agent.

Reads/writes the org's single agent_configs row plus the child tables, and routes
EVERY ElevenLabs write through app.services.elevenlabs_agent.patch_agent_safely
(snapshot → additive merge → audio assertion → verify → audit). No direct httpx
PATCH here.
"""

import difflib
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org, require_super_admin
from app.db.supabase_client import get_service_client
from app.services import agent_config as ac
from app.services import elevenlabs_agent as ea

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kiki-zentrale", tags=["kiki-zentrale"])

KNOWLEDGE_BUCKET = "agent-knowledge"
MAX_PDF_BYTES = 20 * 1024 * 1024

# agent_configs columns owned by Kiki-Zentrale (returned in the GET aggregator).
_CONFIG_COLS = (
    "kiki_level, appointments_enabled, appointments_level, kva_enabled, kva_level, "
    "projects_enabled, projects_level, invoices_enabled, invoices_level, "
    "welcome_message, trade, knowledge_text, problem_description, "
    "prompt_manual_override, forwarding_number, "
    "incoming_forwarding_number, scheduling_enabled, buffer_minutes, "
    "max_appointments_per_day, parallel_slots, lead_time_days, lead_time_only_weekdays, "
    "lead_time_earliest_clock, price_info_enabled, kva_automation_enabled, "
    "emergency_enabled, emergency_number, emergency_only_outside_business_hours, "
    "emergency_keywords, emergency_extra_windows, emergency_surcharge_notice_enabled, "
    "emergency_surcharge_text, outbound_enabled, outbound_occasions, outbound_time_from, "
    "outbound_time_to, outbound_weekdays, outbound_appt_confirm_enabled, "
    "outbound_appt_cancel_enabled, outbound_appt_reschedule_enabled, "
    "outbound_retry_max_attempts, outbound_retry_interval_minutes, "
    "outbound_recall_on_short_hangup, outbound_short_hangup_seconds, welcome_messages"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_admin(user: CurrentUser) -> None:
    if user.role != "org_admin":
        raise HTTPException(
            status_code=403, detail="Nur Administratoren dürfen die Kiki-Zentrale ändern."
        )


def _upsert_config(org_id: str, fields: dict) -> dict:
    client = get_service_client()
    row = {**fields, "org_id": org_id, "updated_at": _now()}
    client.table("agent_configs").upsert(row, on_conflict="org_id").execute()
    return (
        client.table("agent_configs").select(_CONFIG_COLS).eq("org_id", org_id).limit(1)
        .execute().data or [{}]
    )[0]


def _repush_bg(org_id: str, user_id: str | None, endpoint_label: str, seq: int = 0) -> None:
    """Best-effort re-render + push of the org's prompt after a config save.

    Runs as a FastAPI BackgroundTask AFTER the HTTP response is sent, so the
    ~2-3s ElevenLabs round-trip no longer blocks the request. The DB write still
    happens synchronously in the handler, so the returned row reflects the saved
    state; only the EL push is deferred. Wrapped so a push failure (un-provisioned
    org, EL outage, manual override) NEVER surfaces — rerender_and_push_for_org
    already swallows its own errors; this is belt-and-braces + a log line.

    `seq` (from ac.begin_sync) resolves the frontend sync banner: applied on
    success AND on legit no-ops (manual override / no agent — nothing to push is
    not a failure), failed on a real EL error."""
    try:
        result = ac.rerender_and_push_for_org(
            org_id=org_id, actor_id=user_id, endpoint_label=endpoint_label
        )
        reason = result.get("reason")
        ok = bool(result.get("updated")) or reason in ("manual_override", "no_agent")
        ac.finish_sync(org_id, seq, ok=ok, reason=reason)
    except Exception as exc:  # noqa: BLE001 — never let a background push crash
        logger.warning(
            "background prompt re-push failed (org=%s, label=%s): %s",
            org_id, endpoint_label, str(exc)[:200],
        )
        ac.finish_sync(org_id, seq, ok=False, reason=str(exc)[:300])


def _schedule_repush(
    background: BackgroundTasks, user: CurrentUser, endpoint_label: str
) -> None:
    """begin_sync (synchronous, so the first poll already sees 'pending') +
    deferred re-push. The single entry point for ALL config-mutating handlers."""
    seq = ac.begin_sync(user.org_id, endpoint_label)
    background.add_task(_repush_bg, user.org_id, user.id, endpoint_label, seq)


# ─── Schemas ─────────────────────────────────────────────────────────────────
class VerhaltenUpdate(BaseModel):
    kiki_level: int | None = None       # legacy (dormant)
    # Per-capability autonomy (topics 19/21/22)
    appointments_enabled: bool | None = None
    appointments_level: int | None = None
    kva_enabled: bool | None = None
    kva_level: int | None = None
    projects_enabled: bool | None = None
    projects_level: int | None = None
    invoices_enabled: bool | None = None
    invoices_level: int | None = None
    welcome_message: str | None = None
    welcome_messages: list[dict] | None = None  # 20 — time-based variants [{from,to,message}]
    persona_name: str | None = None     # ElevenLabs `name`
    first_message: str | None = None    # ElevenLabs
    voice_id: str | None = None         # ElevenLabs
    language: str | None = None         # ElevenLabs
    model_config = {"extra": "ignore"}


class PromptUpdate(BaseModel):
    prompt: str


class PromptDiffRequest(BaseModel):
    proposed_prompt: str


class RequiredFieldCreate(BaseModel):
    field_key: str
    label: str
    description: str | None = None
    is_duty: bool = True
    identification_role: str | None = None
    model_config = {"extra": "ignore"}


class RequiredFieldUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    is_duty: bool | None = None
    identification_role: str | None = None
    model_config = {"extra": "ignore"}


class ReorderRequest(BaseModel):
    ordered_ids: list[str]


class ContextUpdate(BaseModel):
    trade: str | None = None
    knowledge_text: str | None = None
    model_config = {"extra": "ignore"}


class ProblemDescriptionUpdate(BaseModel):
    problem_description: str | None = None
    model_config = {"extra": "ignore"}


class KnowledgeUrlCreate(BaseModel):
    url: str
    display_name: str


class CategoryCreate(BaseModel):
    name: str
    description: str | None = None
    duration_minutes: int = 60
    default_employee_id: str | None = None
    model_config = {"extra": "ignore"}


class CategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    default_employee_id: str | None = None
    sort_order: int | None = None
    model_config = {"extra": "ignore"}


class ServiceCreate(BaseModel):
    name: str
    is_offered: bool = True


class ServiceUpdate(BaseModel):
    name: str | None = None
    is_offered: bool | None = None
    model_config = {"extra": "ignore"}


class SchedulingRulesUpdate(BaseModel):
    scheduling_enabled: bool | None = None
    buffer_minutes: int | None = None
    max_appointments_per_day: int | None = None
    parallel_slots: int | None = None
    lead_time_days: int | None = None
    lead_time_only_weekdays: bool | None = None
    lead_time_earliest_clock: str | None = None
    model_config = {"extra": "ignore"}


class EmergencyUpdate(BaseModel):
    emergency_enabled: bool | None = None
    emergency_number: str | None = None
    emergency_only_outside_business_hours: bool | None = None
    emergency_keywords: list[str] | None = None
    emergency_extra_windows: list[dict] | None = None
    emergency_surcharge_notice_enabled: bool | None = None
    emergency_surcharge_text: str | None = None
    model_config = {"extra": "ignore"}


class OutboundUpdate(BaseModel):
    outbound_enabled: bool | None = None
    outbound_occasions: dict | None = None
    outbound_time_from: str | None = None
    outbound_time_to: str | None = None
    outbound_weekdays: list[str] | None = None
    # 17 — appointment outbound sub-options
    outbound_appt_confirm_enabled: bool | None = None
    outbound_appt_cancel_enabled: bool | None = None
    outbound_appt_reschedule_enabled: bool | None = None
    # 18 — outbound retry config
    outbound_retry_max_attempts: int | None = None
    outbound_retry_interval_minutes: int | None = None
    outbound_recall_on_short_hangup: bool | None = None
    outbound_short_hangup_seconds: int | None = None
    model_config = {"extra": "ignore"}


class PhoneUpdate(BaseModel):
    forwarding_number: str | None = None
    incoming_forwarding_number: str | None = None
    existing_business_number: str | None = None
    model_config = {"extra": "ignore"}

    @classmethod
    def _looks_like_phone(cls, v: str) -> bool:
        # Lenient: trim, strip common separators, then require + and digits-only,
        # 8–15 digits after the country code (E.164 max). Empty/None handled by caller.
        s = v.strip()
        if not s:
            return False
        stripped = (
            s.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            .replace(" ", "")
        )
        if not stripped.startswith("+"):
            return False
        rest = stripped[1:]
        return rest.isdigit() and 8 <= len(rest) <= 15

    def cleaned_existing_business_number(self) -> str | None:
        """Returns the trimmed value if it looks like an E.164 number,
        None if blank/whitespace, or raises HTTPException(422) if non-empty
        but malformed."""
        if self.existing_business_number is None:
            return None
        s = self.existing_business_number.strip()
        if not s:
            return None
        if not self._looks_like_phone(s):
            raise HTTPException(
                status_code=422,
                detail="Bitte geben Sie eine gültige Telefonnummer im Format +49 ... ein.",
            )
        return s


class TogglePayload(BaseModel):
    enabled: bool


# ─── EL helpers ──────────────────────────────────────────────────────────────
def _el_patch(persona_name=None, first_message=None, language=None, voice_id=None) -> dict:
    patch: dict = {}
    if persona_name is not None:
        patch["name"] = persona_name
    agent: dict = {}
    if first_message is not None:
        agent["first_message"] = first_message
    if language is not None:
        agent["language"] = language
    tts: dict = {}
    if voice_id is not None:
        tts["voice_id"] = voice_id
    cc: dict = {}
    if agent:
        cc["agent"] = agent
    if tts:
        cc["tts"] = tts
    if cc:
        patch["conversation_config"] = cc
    return patch


def _el_read_state(agent_id: str) -> dict:
    try:
        cfg = ea.get_agent_config(agent_id)
    except Exception as exc:  # noqa: BLE001
        # Log so an EL outage / auth failure is diagnosable (was silent before).
        logger.warning("ElevenLabs agent state unreachable (agent %s): %s", agent_id, exc)
        return {"reachable": False, "error": str(exc)[:200]}
    ce = ea._get_path(cfg, ea.CLIENT_EVENTS_PATH) or []
    return {
        "reachable": True,
        "persona_name": cfg.get("name"),
        "first_message": ea._get_path(cfg, ea.FIRST_MESSAGE_PATH),
        "language": ea._get_path(cfg, ea.LANGUAGE_PATH),
        "voice_id": ea._get_path(cfg, ea.VOICE_PATH),
        "audio_event_present": ea.REQUIRED_AUDIO_EVENT in ce,
        "tools_count": len(ea._get_path(cfg, ea.TOOLS_PATH) or []),
        "knowledge_count": len(ea._get_path(cfg, ea.KB_PATH) or []),
        "prompt_length": len(ea._get_path(cfg, ea.PROMPT_PATH) or ""),
    }


# ─── GET aggregator ──────────────────────────────────────────────────────────
def _get_overview(org_id: str) -> dict:
    client = get_service_client()
    org = (
        client.table("organizations")
        .select(
            "phone_number, existing_business_number, elevenlabs_agent_id, "
            "name, ai_minutes_quota"
        )
        .eq("id", org_id).limit(1).execute().data or [{}]
    )[0]
    cfg = (
        client.table("agent_configs").select(_CONFIG_COLS).eq("org_id", org_id).limit(1)
        .execute().data or [{}]
    )[0]
    agent_id = org.get("elevenlabs_agent_id")
    recent = (
        client.table("agent_config_snapshots")
        .select("id, endpoint_label, created_at")
        .eq("org_id", org_id).order("created_at", desc=True).limit(20).execute().data or []
    )
    return {
        "config": cfg,
        "phone_number": org.get("phone_number"),
        "existing_business_number": org.get("existing_business_number"),
        "ai_minutes_quota": org.get("ai_minutes_quota"),
        "agent": _el_read_state(agent_id) if agent_id else {"reachable": False},
        "recent_snapshots": recent,
    }


@router.get("")
async def get_overview(user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_get_overview, user.org_id)


# ─── Agent-sync status (frontend loader banner) ──────────────────────────────
_SYNC_STALE_SECONDS = 300  # a pending sync older than this = process died mid-push


def _get_sync_status(org_id: str) -> dict:
    client = get_service_client()
    row = (
        client.table("agent_configs")
        .select(
            "agent_sync_status, agent_sync_label, agent_sync_error, "
            "agent_sync_seq, agent_sync_requested_at, agent_sync_finished_at"
        )
        .eq("org_id", org_id).limit(1).execute().data or [{}]
    )[0]
    status = row.get("agent_sync_status") or "idle"
    requested_at = row.get("agent_sync_requested_at")
    error = row.get("agent_sync_error")
    # Stale coercion (read-side, no DB write): a backend restart mid-push would
    # otherwise leave the banner spinning forever.
    if status == "pending" and requested_at:
        try:
            ts = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > _SYNC_STALE_SECONDS:
                status, error = "failed", "timeout"
        except ValueError:
            pass
    return {
        "status": status,
        "label": row.get("agent_sync_label"),
        "error": error,
        "seq": row.get("agent_sync_seq") or 0,
        "requested_at": requested_at,
        "finished_at": row.get("agent_sync_finished_at"),
    }


@router.get("/sync-status")
async def get_sync_status(user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_get_sync_status, user.org_id)


@router.post("/sync-status/retry")
async def retry_sync(background: BackgroundTasks, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)
    _schedule_repush(background, user, "kz_retry")
    return {"success": True}


@router.get("/agent-health")
async def get_agent_health(user: CurrentUser = Depends(require_org)) -> dict:
    agent_id = await run_in_threadpool(ea.get_org_agent_id, user.org_id)
    return await run_in_threadpool(ea.agent_health_check, agent_id)


@router.get("/voices")
async def list_voices(user: CurrentUser = Depends(require_org)) -> dict:
    import httpx

    def _do() -> dict:
        with httpx.Client(base_url=ea.EL_BASE, timeout=20) as c:
            r = c.get("/v1/voices", headers=ea._headers(json=False))
        if r.status_code != 200:
            return {"voices": []}
        out = []
        for v in r.json().get("voices", []):
            out.append(
                {
                    "voice_id": v.get("voice_id"),
                    "name": v.get("name"),
                    "preview_url": v.get("preview_url"),
                    "labels": v.get("labels") or {},
                    "languages": [
                        x.get("language")
                        for x in (v.get("verified_languages") or [])
                        if x.get("language")
                    ],
                }
            )
        return {"voices": out}

    return await run_in_threadpool(_do)


# ─── Verhalten (Supabase + ElevenLabs) ───────────────────────────────────────
@router.patch("/verhalten")
async def update_verhalten(
    payload: VerhaltenUpdate, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    _require_admin(user)
    data = payload.model_dump(exclude_unset=True)
    supa = {
        k: data[k]
        for k in (
            "kiki_level", "welcome_message", "welcome_messages",
            "appointments_enabled", "appointments_level",
            "kva_enabled", "kva_level",
            "projects_enabled", "projects_level",
            "invoices_enabled", "invoices_level",
        )
        if k in data
    }
    el_patch = _el_patch(
        persona_name=data.get("persona_name"),
        first_message=data.get("first_message"),
        language=data.get("language"),
        voice_id=data.get("voice_id"),
    )

    def _do() -> dict:
        cfg = _upsert_config(user.org_id, supa) if supa else None
        agent_state = None
        if el_patch:
            agent_id = ea.get_org_agent_id(user.org_id)
            ea.patch_agent_safely(
                agent_id=agent_id,
                field_patches=el_patch,
                merge_arrays=[],
                actor_id=user.id,
                org_id=user.org_id,
                endpoint_label="verhalten",
            )
            agent_state = _el_read_state(agent_id)
        if cfg is None:
            cfg = (
                get_service_client().table("agent_configs").select(_CONFIG_COLS)
                .eq("org_id", user.org_id).limit(1).execute().data or [{}]
            )[0]
        return {"success": True, "config": cfg, "agent": agent_state}

    result = await run_in_threadpool(_do)
    # The per-capability autonomy (and welcome) feed the agent prompt → re-render
    # and push to ElevenLabs in the background, like the other config sections.
    if supa:
        _schedule_repush(background, user, "kz_verhalten")
    return result


# ─── Prompt-Editor (ElevenLabs) ──────────────────────────────────────────────
@router.get("/prompt")
async def get_prompt(user: CurrentUser = Depends(require_super_admin)) -> dict:
    def _do() -> dict:
        agent_id = ea.get_org_agent_id(user.org_id)
        current = ea._get_path(ea.get_agent_config(agent_id), ea.PROMPT_PATH) or ""
        snaps = (
            get_service_client().table("agent_config_snapshots")
            .select("id, endpoint_label, actor_id, created_at, full_config")
            .eq("org_id", user.org_id).order("created_at", desc=True).limit(20)
            .execute().data or []
        )
        history = []
        for s in snaps:
            if s.get("endpoint_label") not in ("prompt-editor", "rollback"):
                continue
            p = ea._get_path(s.get("full_config") or {}, ea.PROMPT_PATH)
            if p is None:
                continue
            history.append(
                {
                    "snapshot_id": s["id"],
                    "created_at": s["created_at"],
                    "actor_id": s.get("actor_id"),
                    "prompt": p,
                }
            )
            if len(history) >= 5:
                break
        return {"prompt": current, "history": history}

    return await run_in_threadpool(_do)


@router.patch("/prompt")
async def update_prompt(payload: PromptUpdate, user: CurrentUser = Depends(require_super_admin)) -> dict:
    def _do() -> dict:
        agent_id = ea.get_org_agent_id(user.org_id)
        ea.patch_agent_safely(
            agent_id=agent_id,
            field_patches={"conversation_config": {"agent": {"prompt": {"prompt": payload.prompt}}}},
            merge_arrays=[],
            actor_id=user.id,
            org_id=user.org_id,
            endpoint_label="prompt-editor",
        )
        # A manual prompt edit takes ownership of the prompt: flag the org so the
        # config-driven re-render no longer overwrites these hand-made changes.
        _upsert_config(user.org_id, {"prompt_manual_override": True})
        new_prompt = ea._get_path(ea.get_agent_config(agent_id), ea.PROMPT_PATH) or ""
        return {"success": True, "prompt": new_prompt}

    return await run_in_threadpool(_do)


@router.post("/prompt/diff")
async def prompt_diff(payload: PromptDiffRequest, user: CurrentUser = Depends(require_super_admin)) -> dict:
    def _do() -> dict:
        agent_id = ea.get_org_agent_id(user.org_id)
        current = ea._get_path(ea.get_agent_config(agent_id), ea.PROMPT_PATH) or ""
        diff = "\n".join(
            difflib.unified_diff(
                current.splitlines(), payload.proposed_prompt.splitlines(),
                fromfile="aktuell", tofile="neu", lineterm="",
            )
        )
        return {
            "diff": diff,
            "current_length": len(current),
            "proposed_length": len(payload.proposed_prompt),
            "changed": current != payload.proposed_prompt,
        }

    return await run_in_threadpool(_do)


# ─── Pflichtfelder ───────────────────────────────────────────────────────────
@router.get("/required-fields")
async def list_required_fields(user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        rows = (
            get_service_client().table("agent_required_fields").select("*")
            .eq("org_id", user.org_id).order("sort_order").execute().data or []
        )
        return {"fields": rows}

    return await run_in_threadpool(_do)


@router.post("/required-fields")
async def create_required_field(
    payload: RequiredFieldCreate, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    _require_admin(user)

    def _do() -> dict:
        client = get_service_client()
        existing = (
            client.table("agent_required_fields").select("sort_order")
            .eq("org_id", user.org_id).order("sort_order", desc=True).limit(1).execute().data
        )
        nxt = (existing[0]["sort_order"] + 1) if existing else 0
        row = {**payload.model_dump(), "org_id": user.org_id, "is_locked": False, "sort_order": nxt}
        return client.table("agent_required_fields").insert(row).execute().data[0]

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_required_fields")
    return result


@router.patch("/required-fields/{field_id}")
async def update_required_field(
    field_id: str, payload: RequiredFieldUpdate, background: BackgroundTasks,
    user: CurrentUser = Depends(require_org),
) -> dict:
    _require_admin(user)
    fields = payload.model_dump(exclude_unset=True)

    def _do() -> dict:
        client = get_service_client()
        client.table("agent_required_fields").update(fields).eq("id", field_id).eq(
            "org_id", user.org_id
        ).execute()
        return (
            client.table("agent_required_fields").select("*").eq("id", field_id)
            .eq("org_id", user.org_id).limit(1).execute().data or [{}]
        )[0]

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_required_fields")
    return result


@router.delete("/required-fields/{field_id}")
async def delete_required_field(
    field_id: str, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    _require_admin(user)

    def _do() -> str:
        client = get_service_client()
        row = (
            client.table("agent_required_fields").select("is_locked").eq("id", field_id)
            .eq("org_id", user.org_id).limit(1).execute().data
        )
        if not row:
            return "missing"
        if row[0].get("is_locked"):
            return "locked"
        client.table("agent_required_fields").delete().eq("id", field_id).eq(
            "org_id", user.org_id
        ).execute()
        return "ok"

    res = await run_in_threadpool(_do)
    if res == "missing":
        raise HTTPException(status_code=404, detail="Feld nicht gefunden.")
    if res == "locked":
        raise HTTPException(status_code=400, detail="Pflichtfeld ist gesperrt und kann nicht gelöscht werden.")
    # Only re-push after a real delete (not on missing/locked no-ops).
    _schedule_repush(background, user, "kz_required_fields")
    return {"success": True}


@router.post("/required-fields/reorder")
async def reorder_required_fields(
    payload: ReorderRequest, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    _require_admin(user)

    def _do() -> dict:
        client = get_service_client()
        for idx, fid in enumerate(payload.ordered_ids):
            client.table("agent_required_fields").update({"sort_order": idx}).eq(
                "id", fid
            ).eq("org_id", user.org_id).execute()
        return {"success": True}

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_required_fields")
    return result


# ─── Branche & Kontext ───────────────────────────────────────────────────────
@router.patch("/context")
async def update_context(
    payload: ContextUpdate, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    _require_admin(user)
    fields = payload.model_dump(exclude_unset=True)

    def _do() -> dict:
        return _upsert_config(user.org_id, fields)

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_identity")
    return result


@router.patch("/problem-description")
async def update_problem_description(
    payload: ProblemDescriptionUpdate, background: BackgroundTasks,
    user: CurrentUser = Depends(require_org),
) -> dict:
    """Upsert the org's free-text 'what to capture per typical problem' instruction
    (agent_configs.problem_description), then re-push the prompt (deferred to a
    background task so the EL round-trip doesn't block the response)."""
    _require_admin(user)
    fields = payload.model_dump(exclude_unset=True)

    def _do() -> dict:
        return _upsert_config(user.org_id, fields)

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_problem_description")
    return result


@router.get("/knowledge-resources")
async def list_knowledge_resources(user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        rows = (
            get_service_client().table("knowledge_resources").select("*")
            .eq("org_id", user.org_id).order("created_at", desc=True).execute().data or []
        )
        return {"resources": rows}

    return await run_in_threadpool(_do)


@router.post("/knowledge-resources/url")
async def add_knowledge_url(payload: KnowledgeUrlCreate, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)

    def _do() -> dict:
        client = get_service_client()
        dup = (
            client.table("knowledge_resources").select("id")
            .eq("org_id", user.org_id).eq("source", payload.url).execute().data
        )
        if dup:
            raise HTTPException(status_code=409, detail="Diese URL ist bereits vorhanden.")
        row = client.table("knowledge_resources").insert(
            {
                "org_id": user.org_id, "kind": "url", "source": payload.url,
                "display_name": payload.display_name, "status": "pending",
            }
        ).execute().data[0]
        ea.push_knowledge_resource_to_elevenlabs(resource_id=row["id"], org_id=user.org_id)
        return (
            client.table("knowledge_resources").select("*").eq("id", row["id"])
            .limit(1).execute().data or [row]
        )[0]

    return await run_in_threadpool(_do)


@router.post("/knowledge-resources/pdf")
async def add_knowledge_pdf(file: UploadFile = File(...), user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)
    content = await file.read()
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF zu groß (max. 20 MB).")
    display_name = file.filename or "Dokument.pdf"

    def _do() -> dict:
        client = get_service_client()
        path = f"{user.org_id}/{uuid4()}.pdf"
        client.storage.from_(KNOWLEDGE_BUCKET).upload(
            path, content, {"content-type": file.content_type or "application/pdf"}
        )
        row = client.table("knowledge_resources").insert(
            {
                "org_id": user.org_id, "kind": "pdf", "source": path,
                "display_name": display_name, "status": "pending",
            }
        ).execute().data[0]
        ea.push_knowledge_resource_to_elevenlabs(resource_id=row["id"], org_id=user.org_id)
        return (
            client.table("knowledge_resources").select("*").eq("id", row["id"])
            .limit(1).execute().data or [row]
        )[0]

    return await run_in_threadpool(_do)


@router.delete("/knowledge-resources/{resource_id}")
async def delete_knowledge_resource(resource_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)

    def _do() -> str:
        client = get_service_client()
        row = (
            client.table("knowledge_resources").select("*").eq("id", resource_id)
            .eq("org_id", user.org_id).limit(1).execute().data
        )
        if not row:
            return "missing"
        res = row[0]
        ea.remove_knowledge_resource_from_elevenlabs(resource_id=resource_id, org_id=user.org_id)
        if res.get("kind") == "pdf" and res.get("source"):
            try:
                client.storage.from_(KNOWLEDGE_BUCKET).remove([res["source"]])
            except Exception:  # noqa: BLE001
                pass
        client.table("knowledge_resources").delete().eq("id", resource_id).eq(
            "org_id", user.org_id
        ).execute()
        return "ok"

    res = await run_in_threadpool(_do)
    if res == "missing":
        raise HTTPException(status_code=404, detail="Wissens-Quelle nicht gefunden.")
    return {"success": True}


@router.post("/knowledge-resources/{resource_id}/reindex")
async def reindex_knowledge_resource(resource_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)

    def _do() -> dict:
        client = get_service_client()
        row = (
            client.table("knowledge_resources").select("*").eq("id", resource_id)
            .eq("org_id", user.org_id).limit(1).execute().data
        )
        if not row:
            raise HTTPException(status_code=404, detail="Wissens-Quelle nicht gefunden.")
        # Detach the old document, then re-push fresh.
        ea.remove_knowledge_resource_from_elevenlabs(resource_id=resource_id, org_id=user.org_id)
        client.table("knowledge_resources").update(
            {"elevenlabs_doc_id": None, "status": "pending", "updated_at": _now()}
        ).eq("id", resource_id).execute()
        ea.push_knowledge_resource_to_elevenlabs(resource_id=resource_id, org_id=user.org_id)
        return (
            client.table("knowledge_resources").select("*").eq("id", resource_id)
            .limit(1).execute().data or [{}]
        )[0]

    return await run_in_threadpool(_do)


# ─── Terminregeln ────────────────────────────────────────────────────────────
@router.patch("/scheduling-rules")
async def update_scheduling_rules(
    payload: SchedulingRulesUpdate, background: BackgroundTasks,
    user: CurrentUser = Depends(require_org),
) -> dict:
    _require_admin(user)
    fields = payload.model_dump(exclude_unset=True)

    def _do() -> dict:
        return _upsert_config(user.org_id, fields)

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_scheduling")
    return result


# ─── Terminkategorien ────────────────────────────────────────────────────────
@router.get("/appointment-categories")
async def list_categories(user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        rows = (
            get_service_client().table("appointment_categories").select("*")
            .eq("org_id", user.org_id).order("sort_order").execute().data or []
        )
        return {"categories": rows}

    return await run_in_threadpool(_do)


@router.post("/appointment-categories")
async def create_category(
    payload: CategoryCreate, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    _require_admin(user)

    def _do() -> dict:
        client = get_service_client()
        existing = (
            client.table("appointment_categories").select("sort_order")
            .eq("org_id", user.org_id).order("sort_order", desc=True).limit(1).execute().data
        )
        nxt = (existing[0]["sort_order"] + 1) if existing else 0
        row = {**payload.model_dump(), "org_id": user.org_id, "sort_order": nxt}
        return client.table("appointment_categories").insert(row).execute().data[0]

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_categories")
    return result


@router.patch("/appointment-categories/{category_id}")
async def update_category(
    category_id: str, payload: CategoryUpdate, background: BackgroundTasks,
    user: CurrentUser = Depends(require_org),
) -> dict:
    _require_admin(user)
    fields = payload.model_dump(exclude_unset=True)

    def _do() -> dict:
        client = get_service_client()
        client.table("appointment_categories").update(fields).eq("id", category_id).eq(
            "org_id", user.org_id
        ).execute()
        return (
            client.table("appointment_categories").select("*").eq("id", category_id)
            .eq("org_id", user.org_id).limit(1).execute().data or [{}]
        )[0]

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_categories")
    return result


@router.delete("/appointment-categories/{category_id}")
async def delete_category(
    category_id: str, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    _require_admin(user)

    def _do() -> dict:
        get_service_client().table("appointment_categories").delete().eq(
            "id", category_id
        ).eq("org_id", user.org_id).execute()
        return {"success": True}

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_categories")
    return result


# ─── KVA-Automatisierung / Preisauskunft ─────────────────────────────────────
@router.patch("/kva-automation")
async def update_kva_automation(payload: TogglePayload, user: CurrentUser = Depends(require_org)) -> dict:
    # Legacy toggle (no frontend caller; the field does not feed the prompt) —
    # deliberately no repush here.
    _require_admin(user)
    return await run_in_threadpool(_upsert_config, user.org_id, {"kva_automation_enabled": payload.enabled})


@router.patch("/price-info")
async def update_price_info(
    payload: TogglePayload, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    _require_admin(user)
    result = await run_in_threadpool(
        _upsert_config, user.org_id, {"price_info_enabled": payload.enabled}
    )
    # This PATCH previously never re-pushed the prompt — the toggle changed the
    # DB but the live agent kept its old price behaviour. Repush is the fix.
    _schedule_repush(background, user, "kz_price_info")
    return result


# ─── Leistungsangebot ────────────────────────────────────────────────────────
@router.get("/services")
async def list_services(user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        rows = (
            get_service_client().table("agent_services").select("*")
            .eq("org_id", user.org_id).order("created_at").execute().data or []
        )
        return {"services": rows}

    return await run_in_threadpool(_do)


@router.post("/services")
async def create_service(payload: ServiceCreate, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)

    def _do() -> dict:
        row = {**payload.model_dump(), "org_id": user.org_id}
        return get_service_client().table("agent_services").insert(row).execute().data[0]

    return await run_in_threadpool(_do)


@router.patch("/services/{service_id}")
async def update_service(service_id: str, payload: ServiceUpdate, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)
    fields = payload.model_dump(exclude_unset=True)

    def _do() -> dict:
        client = get_service_client()
        client.table("agent_services").update(fields).eq("id", service_id).eq(
            "org_id", user.org_id
        ).execute()
        return (
            client.table("agent_services").select("*").eq("id", service_id)
            .eq("org_id", user.org_id).limit(1).execute().data or [{}]
        )[0]

    return await run_in_threadpool(_do)


@router.delete("/services/{service_id}")
async def delete_service(service_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)

    def _do() -> dict:
        get_service_client().table("agent_services").delete().eq("id", service_id).eq(
            "org_id", user.org_id
        ).execute()
        return {"success": True}

    return await run_in_threadpool(_do)


# ─── Notdienst ───────────────────────────────────────────────────────────────
@router.patch("/emergency")
async def update_emergency(
    payload: EmergencyUpdate, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    _require_admin(user)
    fields = payload.model_dump(exclude_unset=True)

    def _do() -> dict:
        return _upsert_config(user.org_id, fields)

    result = await run_in_threadpool(_do)
    _schedule_repush(background, user, "kz_emergency")
    return result


# ─── Telefon ─────────────────────────────────────────────────────────────────
@router.patch("/phone")
async def update_phone(
    payload: PhoneUpdate, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    """Update the org's Telefon section.

    - `forwarding_number` / `incoming_forwarding_number` → `agent_configs`
      (these drive the transferCall tool at runtime).
    - `existing_business_number` → `organizations` (tradesperson's own
      number; HeyKiki never dials it — the tradesperson sets up telco-level
      forwarding from this number to their HeyKiki number).
    """
    _require_admin(user)
    # Validate + normalise the new business-number field BEFORE any write.
    cleaned_existing = payload.cleaned_existing_business_number()
    set_existing = "existing_business_number" in payload.model_fields_set

    def _do() -> dict:
        client = get_service_client()

        # agent_configs write (forwarding pair).
        cfg_fields = payload.model_dump(
            exclude_unset=True,
            exclude={"existing_business_number"},
        )
        if cfg_fields:
            _upsert_config(user.org_id, cfg_fields)

        # organizations write (existing_business_number).
        if set_existing:
            client.table("organizations").update(
                {"existing_business_number": cleaned_existing, "updated_at": _now()}
            ).eq("id", user.org_id).execute()

        # Return the combined view (same shape as agent_configs select + the
        # one extra field so the frontend doesn't need a second fetch).
        cfg = (
            client.table("agent_configs").select(_CONFIG_COLS).eq("org_id", user.org_id)
            .limit(1).execute().data or [{}]
        )[0]
        org = (
            client.table("organizations").select("existing_business_number")
            .eq("id", user.org_id).limit(1).execute().data or [{}]
        )[0]
        return {**cfg, "existing_business_number": org.get("existing_business_number")}

    result = await run_in_threadpool(_do)
    # incoming_forwarding_number feeds the KZ_STAFF_TRANSFER prompt block — the
    # agent must learn about a changed/removed staff-transfer number immediately.
    _schedule_repush(background, user, "kz_phone")
    return result


# ─── Ausgehende Anrufe ───────────────────────────────────────────────────────
@router.patch("/outbound")
async def update_outbound(payload: OutboundUpdate, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)
    return await run_in_threadpool(_upsert_config, user.org_id, payload.model_dump(exclude_unset=True))


# ─── Verlauf & Rückgängig (audit + rollback) ─────────────────────────────────
@router.get("/audit")
async def list_audit(user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        client = get_service_client()
        rows = (
            client.table("agent_writes_audit").select("*")
            .eq("org_id", user.org_id).order("created_at", desc=True).limit(50)
            .execute().data or []
        )
        users = (
            client.table("users").select("id, full_name")
            .eq("org_id", user.org_id).execute().data or []
        )
        names = {u["id"]: u.get("full_name") for u in users}
        for r in rows:
            r["actor_name"] = names.get(r.get("actor_id"))
        return {"entries": rows}

    return await run_in_threadpool(_do)


@router.get("/audit/{audit_id}")
async def get_audit_entry(audit_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        row = (
            get_service_client().table("agent_writes_audit").select("*")
            .eq("id", audit_id).eq("org_id", user.org_id).limit(1).execute().data
        )
        if not row:
            raise HTTPException(status_code=404, detail="Audit-Eintrag nicht gefunden.")
        return row[0]

    return await run_in_threadpool(_do)


@router.post("/rollback/{snapshot_id}")
async def rollback(snapshot_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)

    def _do() -> dict:
        client = get_service_client()
        snap = (
            client.table("agent_config_snapshots").select("id, org_id")
            .eq("id", snapshot_id).eq("org_id", user.org_id).limit(1).execute().data
        )
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot nicht gefunden.")
        ea.rollback_to_snapshot(snapshot_id=snapshot_id, actor_id=user.id, org_id=user.org_id)
        return {"success": True}

    return await run_in_threadpool(_do)
