"""Kiki-Zentrale — the tradesperson's full control surface over their AI agent.

Reads/writes the org's single agent_configs row plus the child tables, and routes
EVERY ElevenLabs write through app.services.elevenlabs_agent.patch_agent_safely
(snapshot → additive merge → audio assertion → verify → audit). No direct httpx
PATCH here.
"""

import difflib
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, field_validator
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
    "max_appointments_per_day, parallel_slots, lead_time_hours, lead_time_days, lead_time_only_weekdays, "
    "lead_time_earliest_clock, price_info_enabled, kva_automation_enabled, "
    "emergency_enabled, emergency_number, emergency_only_outside_business_hours, "
    "emergency_keywords, emergency_extra_windows, emergency_surcharge_notice_enabled, "
    "emergency_surcharge_text, outbound_enabled, outbound_occasions, outbound_time_from, "
    "outbound_time_to, outbound_weekdays, outbound_appt_confirm_enabled, "
    "outbound_appt_cancel_enabled, outbound_appt_reschedule_enabled, "
    "outbound_retry_max_attempts, outbound_retry_interval_minutes, "
    "outbound_recall_on_short_hangup, outbound_short_hangup_seconds, welcome_messages, "
    "reschedule_request_timeout_hours"
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
            org_id=org_id, actor_id=user_id, endpoint_label=endpoint_label,
            expected_seq=seq,
        )
        reason = result.get("reason")
        # 'superseded' = a newer save already owns the latest state and pushed it
        # — a benign no-op, not a failure (its own finish_sync resolves the banner).
        ok = bool(result.get("updated")) or reason in (
            "manual_override", "no_agent", "superseded",
        )
        # Notdienst-/Telefon-saves also reconfigure the native transfer_to_number
        # system tool (the actual call-bridge mechanism), not just the prompt.
        if endpoint_label in ("kz_emergency", "kz_phone", "kz_retry"):
            tool_result = ac.sync_transfer_tool_for_org(org_id)
            tool_reason = tool_result.get("reason")
            # 1.4: a categorized verify_failed/el_error means the transfer tool
            # diverged from the saved config — surface it as a real failure (the
            # prompt may have pushed fine, but the call-bridge did NOT). 'no_agent'
            # / None stay benign no-ops.
            if not tool_result.get("updated") and tool_reason not in ("no_agent", None):
                ok, reason = False, f"transfer_tool: {tool_reason}"
        ac.finish_sync(org_id, seq, ok=ok, reason=reason)
    except Exception as exc:  # noqa: BLE001 — never let a background push crash
        logger.warning(
            "background prompt re-push failed (org=%s, label=%s): %s",
            org_id, endpoint_label, str(exc)[:200],
        )
        ac.finish_sync(org_id, seq, ok=False, reason=str(exc)[:300])


async def _schedule_repush(
    background: BackgroundTasks, user: CurrentUser, endpoint_label: str
) -> None:
    """begin_sync (awaited before the response, so the first poll already sees
    'pending') + deferred re-push. The single entry point for ALL config-mutating
    handlers. begin_sync runs in the threadpool — it makes up to three blocking
    Supabase round-trips, which used to run directly on the event loop and stall
    every in-flight request (audit 2026-06-11)."""
    seq = await run_in_threadpool(ac.begin_sync, user.org_id, endpoint_label)
    background.add_task(_repush_bg, user.org_id, user.id, endpoint_label, seq)


# ─── Schemas ─────────────────────────────────────────────────────────────────
class VerhaltenUpdate(BaseModel):
    kiki_level: int | None = None       # legacy (dormant)
    # Per-capability autonomy (topics 19/21/22)
    appointments_enabled: bool | None = None
    appointments_level: int | None = None
    # Bug #3: hours a pending reschedule waits before the safety-timer resolves it.
    reschedule_request_timeout_hours: int | None = None
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

    @field_validator("trade", mode="before")
    @classmethod
    def _validate_trade(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 120:
            raise ValueError("Das Gewerk/die Branche darf höchstens 120 Zeichen lang sein.")
        return v

    @field_validator("knowledge_text", mode="before")
    @classmethod
    def _validate_knowledge_text(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 2000:
            raise ValueError("Der Kontext-/Wissenstext darf höchstens 2000 Zeichen lang sein.")
        return v


class ProblemDescriptionUpdate(BaseModel):
    problem_description: str | None = None
    model_config = {"extra": "ignore"}

    @field_validator("problem_description", mode="before")
    @classmethod
    def _validate_problem_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 2000:
            raise ValueError("Die Problembeschreibung darf höchstens 2000 Zeichen lang sein.")
        return v


class KnowledgeUrlCreate(BaseModel):
    url: str
    display_name: str


class CategoryCreate(BaseModel):
    name: str
    description: str | None = None
    duration_minutes: int = 60
    default_employee_id: str | None = None
    model_config = {"extra": "ignore"}

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 80:
            raise ValueError("Der Kategoriename darf höchstens 80 Zeichen lang sein.")
        return v

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 500:
            raise ValueError("Die Kategoriebeschreibung darf höchstens 500 Zeichen lang sein.")
        return v


class CategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    default_employee_id: str | None = None
    sort_order: int | None = None
    model_config = {"extra": "ignore"}

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 80:
            raise ValueError("Der Kategoriename darf höchstens 80 Zeichen lang sein.")
        return v

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 500:
            raise ValueError("Die Kategoriebeschreibung darf höchstens 500 Zeichen lang sein.")
        return v


class ServiceCreate(BaseModel):
    name: str
    is_offered: bool = True


class ServiceUpdate(BaseModel):
    name: str | None = None
    is_offered: bool | None = None
    model_config = {"extra": "ignore"}


class SchedulingRulesUpdate(BaseModel):
    scheduling_enabled: bool | None = None  # legacy — UI gate is autonomy "Termine" now
    buffer_minutes: int | None = None
    max_appointments_per_day: int | None = None
    parallel_slots: int | None = None
    lead_time_hours: int | None = None
    lead_time_days: int | None = None  # legacy fallback (lead_time_hours wins)
    lead_time_only_weekdays: bool | None = None
    lead_time_earliest_clock: str | None = None
    model_config = {"extra": "ignore"}


def _validate_dialable(value: str | None, label: str) -> None:
    """Transfer destinations end up in the EL transfer_to_number tool — Twilio
    rejects a non-E.164 target as an AUDIBLE error mid-call (audit 2026-06-11:
    these numbers were persisted with zero validation; _dial_clean normalizes
    but cannot reject). Accept +E.164 or a 0-prefixed German local number
    (_dial_clean turns it into +49…); anything else is a 422 at save time.
    None/blank = clearing the field, always allowed."""
    if value is None or not value.strip():
        return
    stripped = re.sub(r"[\s\-/().]", "", value.strip())
    if stripped.startswith("+"):
        rest = stripped[1:]
        ok = rest.isdigit() and 8 <= len(rest) <= 15
    elif stripped.startswith("0"):
        ok = stripped.isdigit() and 8 <= len(stripped) <= 15
    else:
        ok = False
    if not ok:
        raise HTTPException(
            status_code=422,
            detail=f"{label}: Bitte eine gültige Telefonnummer im Format +49… (oder 0…) angeben.",
        )


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
    # 1.4: derive a tools_synced signal from the most recent system_tools_sync
    # audit row. False ⇒ the last transfer-tool push diverged (verify_failed /
    # el_error or an auto-rollback) — the call-bridge may not reflect the saved
    # config even though the prompt did. None ⇒ no such write recorded yet.
    tools_synced: bool | None = None
    last_tool_audit = (
        client.table("agent_writes_audit")
        .select("rolled_back, elevenlabs_response_status")
        .eq("org_id", org_id).eq("endpoint_label", "system_tools_sync")
        .order("created_at", desc=True).limit(1).execute().data or []
    )
    if last_tool_audit:
        a = last_tool_audit[0]
        tools_synced = (not a.get("rolled_back")) and int(
            a.get("elevenlabs_response_status") or 0
        ) < 300
    return {
        "status": status,
        "label": row.get("agent_sync_label"),
        "error": error,
        "seq": row.get("agent_sync_seq") or 0,
        "requested_at": requested_at,
        "finished_at": row.get("agent_sync_finished_at"),
        "tools_synced": tools_synced,
    }


@router.get("/sync-status")
async def get_sync_status(user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_get_sync_status, user.org_id)


@router.post("/sync-status/retry")
async def retry_sync(background: BackgroundTasks, user: CurrentUser = Depends(require_org)) -> dict:
    _require_admin(user)
    await _schedule_repush(background, user, "kz_retry")
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
            "reschedule_request_timeout_hours",
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
        # Order matters (audit 2026-06-11): the EL patch runs FIRST. The old
        # order committed the DB write, then a failing EL call aborted the
        # handler BEFORE _schedule_repush — prompt-feeding fields changed in the
        # DB while the agent never re-rendered AND no sync state was set (the
        # banner stayed idle). EL-first means: EL failure → 500 with NOTHING
        # committed (clean retry); a DB failure after EL success only leaves
        # EL-only fields (persona/voice) applied, which have no DB twin to
        # diverge from.
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
        cfg = _upsert_config(user.org_id, supa) if supa else None
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
        await _schedule_repush(background, user, "kz_verhalten")
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


# ─── Pflichtfelder / Leitfaden ───────────────────────────────────────────────
_LINKED_SETTINGS = ("appointments_enabled", "kva_enabled", "price_info_enabled")


@router.get("/required-fields")
async def list_required_fields(user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        client = get_service_client()
        rows = (
            client.table("agent_required_fields").select("*")
            .eq("org_id", user.org_id).order("sort_order").execute().data or []
        )
        # Linked rows mirror the live setting — their own is_active is
        # position-only and must never be shown/used directly.
        if any(r.get("linked_setting") for r in rows):
            cfg = (
                client.table("agent_configs")
                .select(", ".join(_LINKED_SETTINGS))
                .eq("org_id", user.org_id).limit(1).execute().data or [{}]
            )[0]
            for r in rows:
                linked = r.get("linked_setting")
                if linked:
                    r["is_active"] = bool(cfg.get(linked))
        return {"fields": rows}

    return await run_in_threadpool(_do)


class LeitfadenItem(BaseModel):
    id: str
    is_active: bool = True


class LeitfadenSave(BaseModel):
    items: list[LeitfadenItem]


@router.patch("/leitfaden")
async def save_leitfaden(
    payload: LeitfadenSave, background: BackgroundTasks, user: CurrentUser = Depends(require_org)
) -> dict:
    """Batch save of the Leitfaden: the COMPLETE ordered list (index = sort_order)
    + per-row active toggles. Linked-row toggles write through to the real
    agent_configs setting (two-way sync with Autonomie/Preisauskunft). ONE repush
    — replaces the old push-per-drag reorder flow."""
    _require_admin(user)

    def _do() -> str:
        client = get_service_client()
        rows = (
            client.table("agent_required_fields").select("id, linked_setting")
            .eq("org_id", user.org_id).execute().data or []
        )
        current_ids = {r["id"] for r in rows}
        sent_ids = {i.id for i in payload.items}
        if current_ids != sent_ids:
            return "stale"
        linked_by_id = {r["id"]: r.get("linked_setting") for r in rows}
        cfg_updates: dict = {}
        row_updates: list[tuple[str, dict]] = []
        for idx, item in enumerate(payload.items):
            linked = linked_by_id.get(item.id)
            update: dict = {"sort_order": idx}
            if linked:
                # Active state lives on agent_configs; the row keeps position only.
                if linked in _LINKED_SETTINGS:
                    cfg_updates[linked] = item.is_active
            else:
                update["is_active"] = item.is_active
            row_updates.append((item.id, update))
        # Guard BEFORE any write (audit 2026-06-11): the old order committed the
        # per-row updates first, then bailed with 422 — a half-applied save the
        # user was told had failed, with the repush skipped (DB↔agent divergence).
        if cfg_updates.get("price_info_enabled"):
            # Same guard as PATCH /price-info: no priced Artikel → no price talk.
            priced = (
                client.table("catalog_items").select("id")
                .eq("org_id", user.org_id).eq("is_active", True).gt("unit_price", 0)
                .limit(1).execute().data or []
            )
            if not priced:
                return "no_prices"
        for item_id, update in row_updates:
            client.table("agent_required_fields").update(update).eq(
                "id", item_id
            ).eq("org_id", user.org_id).execute()
        if cfg_updates:
            _upsert_config(user.org_id, cfg_updates)
        return "ok"

    res = await run_in_threadpool(_do)
    if res == "stale":
        raise HTTPException(
            status_code=409,
            detail="Die Liste ist veraltet — bitte Seite neu laden und erneut speichern.",
        )
    if res == "no_prices":
        raise HTTPException(
            status_code=422,
            detail="Preisauskunft kann nicht aktiviert werden: Es sind keine Artikel "
            "mit Preisen hinterlegt. Bitte pflegen Sie zuerst Preise im Menü „Artikel“.",
        )
    await _schedule_repush(background, user, "kz_leitfaden")
    return {"success": True}


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
    await _schedule_repush(background, user, "kz_required_fields")
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
    await _schedule_repush(background, user, "kz_required_fields")
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
    await _schedule_repush(background, user, "kz_required_fields")
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
    await _schedule_repush(background, user, "kz_required_fields")
    return result


# ─── Gesprächslogik (Wenn/Dann-Baukasten) ────────────────────────────────────
class ConversationLogicUpdate(BaseModel):
    enabled: bool | None = None
    logic: dict | None = None
    model_config = {"extra": "ignore"}


def _validate_logic_or_422(raw: dict) -> str:
    """Validates + compiles; returns the compiled preview text or raises 422."""
    from app.schemas.conversation_logic import (
        MAX_COMPILED_CHARS,
        ConversationLogic,
        LogicError,
        compile_conversation_logic,
        validate_conversation_logic,
    )

    try:
        logic = ConversationLogic.model_validate(raw)
        validate_conversation_logic(logic)
        compiled = compile_conversation_logic(logic)
    except LogicError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — pydantic shape errors etc.
        raise HTTPException(status_code=422, detail=f"Ungültige Gesprächslogik: {str(exc)[:200]}")
    if len(compiled) > MAX_COMPILED_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Die Gesprächslogik ist zu lang ({len(compiled)} Zeichen, "
            f"max. {MAX_COMPILED_CHARS}). Bitte kürzen Sie Bedingungen oder Aktionen.",
        )
    return compiled


@router.get("/conversation-logic")
async def get_conversation_logic(user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        row = (
            get_service_client().table("agent_configs")
            .select("conversation_logic, conversation_logic_enabled")
            .eq("org_id", user.org_id).limit(1).execute().data or [{}]
        )[0]
        return {
            "enabled": row.get("conversation_logic_enabled", True),
            "logic": row.get("conversation_logic") or {"version": 1, "blocks": []},
        }

    return await run_in_threadpool(_do)


@router.patch("/conversation-logic")
async def update_conversation_logic(
    payload: ConversationLogicUpdate, background: BackgroundTasks,
    user: CurrentUser = Depends(require_org),
) -> dict:
    _require_admin(user)
    fields: dict = {}
    if payload.enabled is not None:
        fields["conversation_logic_enabled"] = payload.enabled
    if payload.logic is not None:
        _validate_logic_or_422(payload.logic)
        fields["conversation_logic"] = payload.logic
    if not fields:
        return {"success": True}
    await run_in_threadpool(_upsert_config, user.org_id, fields)
    await _schedule_repush(background, user, "kz_conversation_logic")
    return {"success": True}


class ConversationLogicPreview(BaseModel):
    logic: dict


@router.post("/conversation-logic/preview")
async def preview_conversation_logic(
    payload: ConversationLogicPreview, user: CurrentUser = Depends(require_org)
) -> dict:
    """Validate + compile WITHOUT saving — the single compiler implementation
    powers the live frontend preview (no drift-prone TS port)."""
    return {"text": _validate_logic_or_422(payload.logic)}


@router.post("/gespraechsablauf/preview")
async def preview_gespraechsablauf(
    payload: ConversationLogicPreview, user: CurrentUser = Depends(require_org)
) -> dict:
    """Combined preview for the merged Gesprächsablauf page: the SAVED Leitfaden
    block (default path) + the posted rules compiled — exactly the two blocks the
    agent prompt receives, so the user sees how guide and rules mesh."""
    logic_text = _validate_logic_or_422(payload.logic)

    def _fields_block() -> str:
        from app.services.agent_config import render_required_fields_block

        client = get_service_client()
        rows = (
            client.table("agent_required_fields").select("*")
            .eq("org_id", user.org_id).order("sort_order").execute().data or []
        )
        cfg = (
            client.table("agent_configs").select("*")
            .eq("org_id", user.org_id).limit(1).execute().data or [{}]
        )[0]
        return render_required_fields_block(rows, cfg)

    fields_text = await run_in_threadpool(_fields_block)
    parts = []
    if logic_text:
        parts.append("## Sonderfälle (gelten zuerst)\n" + logic_text)
    parts.append("## Standard-Ablauf (Leitfaden)\n" + fields_text)
    return {"text": "\n\n".join(parts), "logic_text": logic_text, "fields_text": fields_text}


class ConversationLogicGenerate(BaseModel):
    description: str
    # When set, the model extends/adjusts the current rules instead of replacing.
    existing: dict | None = None


@router.post("/conversation-logic/generate")
async def generate_conversation_logic(
    payload: ConversationLogicGenerate, user: CurrentUser = Depends(require_org)
) -> dict:
    """Natural language → validated rule tree + compiled preview. NOTHING is
    saved — the UI shows the generated rules in the editor and the user saves
    via the normal PATCH (same review/confirm path as manual edits)."""
    _require_admin(user)
    # LLM-spend endpoint — bound per org (audit 2026-06-11).
    from app.services.ratelimit import enforce_rate_limit
    enforce_rate_limit("rule_generate", user.org_id, max_calls=6, per_seconds=60)
    description = (payload.description or "").strip()
    if len(description) < 10:
        raise HTTPException(status_code=422, detail="Bitte beschreiben Sie Ihre Regeln etwas ausführlicher.")
    if len(description) > 4000:
        raise HTTPException(status_code=422, detail="Die Beschreibung ist zu lang (max. 4000 Zeichen).")

    from app.services.ai.client import AIServiceDisabled
    from app.services.conversation_logic_ai import GenerationFailed, generate_logic_from_text

    def _do() -> dict:
        # Shared vocabulary with the Leitfaden: give the model the org's active
        # fields so matching asks become ask_field references, not free text.
        rows = (
            get_service_client().table("agent_required_fields")
            .select("field_key, label, is_active, linked_setting")
            .eq("org_id", user.org_id).order("sort_order").execute().data or []
        )
        fields = [
            {"field_key": r["field_key"], "label": r.get("label") or r["field_key"]}
            for r in rows
            if r.get("field_key") and r.get("is_active") and not r.get("linked_setting")
        ]
        return generate_logic_from_text(
            org_id=user.org_id, user_id=user.id,
            description=description, existing=payload.existing, fields=fields,
        )

    try:
        return await run_in_threadpool(_do)
    except AIServiceDisabled:
        raise HTTPException(status_code=503, detail="KI-Unterstützung ist derzeit nicht verfügbar.")
    except GenerationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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
    await _schedule_repush(background, user, "kz_identity")
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
    await _schedule_repush(background, user, "kz_problem_description")
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
    await _schedule_repush(background, user, "kz_scheduling")
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
    await _schedule_repush(background, user, "kz_categories")
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
    await _schedule_repush(background, user, "kz_categories")
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
    await _schedule_repush(background, user, "kz_categories")
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

    if payload.enabled:
        # Guard: without priced Artikel the agent has nothing real to quote —
        # enabling would invite hallucinated prices.
        def _priced_count() -> int:
            rows = (
                get_service_client().table("catalog_items").select("id")
                .eq("org_id", user.org_id).eq("is_active", True).gt("unit_price", 0)
                .limit(1).execute().data or []
            )
            return len(rows)

        if await run_in_threadpool(_priced_count) == 0:
            raise HTTPException(
                status_code=422,
                detail="Preisauskunft kann nicht aktiviert werden: Es sind keine "
                "Artikel mit Preisen hinterlegt. Bitte pflegen Sie zuerst Preise "
                "im Menü „Artikel“.",
            )

    result = await run_in_threadpool(
        _upsert_config, user.org_id, {"price_info_enabled": payload.enabled}
    )
    # This PATCH previously never re-pushed the prompt — the toggle changed the
    # DB but the live agent kept its old price behaviour. Repush is the fix.
    await _schedule_repush(background, user, "kz_price_info")
    # Keep the Preisliste KB document in step with the toggle (create/remove).
    from app.services.price_knowledge import sync_price_list_kb

    background.add_task(sync_price_list_kb, user.org_id)
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
    _validate_dialable(payload.emergency_number, "Notdienst-Nummer")
    fields = payload.model_dump(exclude_unset=True)

    def _do() -> dict:
        return _upsert_config(user.org_id, fields)

    result = await run_in_threadpool(_do)
    await _schedule_repush(background, user, "kz_emergency")
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
    # Validate + normalise BEFORE any write — the forwarding pair feeds the live
    # transfer tool, so garbage here surfaces as an audible mid-call error.
    _validate_dialable(payload.forwarding_number, "Weiterleitungs-Nummer")
    _validate_dialable(payload.incoming_forwarding_number, "Mitarbeiter-Nummer")
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
    await _schedule_repush(background, user, "kz_phone")
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


# ─── 1.2a — Snapshots list (true undo/rewind surface) ────────────────────────
@router.get("/snapshots")
async def list_snapshots(
    label: str | None = None, user: CurrentUser = Depends(require_org)
) -> list[dict]:
    """Org-scoped snapshot list, newest first, max 50. Each row carries a
    resolved actor_name (same users-name block as /audit) and a derived
    rolled_back flag (any agent_writes_audit row for this snapshot that is
    rolled_back). Optional ?label= filters by endpoint_label."""

    def _do() -> list[dict]:
        client = get_service_client()
        q = (
            client.table("agent_config_snapshots")
            .select("id, endpoint_label, actor_id, created_at")
            .eq("org_id", user.org_id)
        )
        if label:
            q = q.eq("endpoint_label", label)
        snaps = q.order("created_at", desc=True).limit(50).execute().data or []
        # Resolve actor names (same block as list_audit).
        users = (
            client.table("users").select("id, full_name")
            .eq("org_id", user.org_id).execute().data or []
        )
        names = {u["id"]: u.get("full_name") for u in users}
        # Derive rolled_back per snapshot from the audit table (one query).
        snap_ids = [s["id"] for s in snaps]
        rolled: set[str] = set()
        if snap_ids:
            audit_rows = (
                client.table("agent_writes_audit").select("snapshot_id, rolled_back")
                .eq("org_id", user.org_id).in_("snapshot_id", snap_ids)
                .eq("rolled_back", True).execute().data or []
            )
            rolled = {r["snapshot_id"] for r in audit_rows if r.get("snapshot_id")}
        out = []
        for s in snaps:
            out.append(
                {
                    "id": s["id"],
                    "endpoint_label": s.get("endpoint_label"),
                    "actor_id": s.get("actor_id"),
                    "actor_name": names.get(s.get("actor_id")),
                    "created_at": s.get("created_at"),
                    "rolled_back": s["id"] in rolled,
                }
            )
        return out

    return await run_in_threadpool(_do)


# ─── 1.3 — Drift detection ───────────────────────────────────────────────────
@router.get("/drift")
async def get_drift(user: CurrentUser = Depends(require_org)) -> dict:
    """Is the live agent prompt out of step with the saved config?

    {drift, dirty_since, manual_override, last_repush_at}. drift=True means a
    config change couldn't be pushed (org sits behind a manual prompt override)."""
    return await run_in_threadpool(ac.compute_drift, user.org_id)


@router.post("/drift/force-resync")
async def force_resync(background: BackgroundTasks, user: CurrentUser = Depends(require_org)) -> dict:
    """Admin: force a re-render+push that BYPASSES the manual_override gate for
    this single call (still snapshot/verify/audit). Scheduled via the normal
    repush path so the sync banner resolves the same way."""
    _require_admin(user)
    seq = await run_in_threadpool(ac.begin_sync, user.org_id, "kz_force_resync")
    background.add_task(_force_resync_bg, user.org_id, user.id, seq)
    return {"scheduled": True}


def _force_resync_bg(org_id: str, user_id: str | None, seq: int) -> None:
    """Background force-resync (mirrors _repush_bg, but force=True bypasses the
    manual-override gate). Never raises — finish_sync resolves the banner."""
    try:
        result = ac.rerender_and_push_for_org(
            org_id=org_id, actor_id=user_id, endpoint_label="kz_force_resync",
            expected_seq=seq, force=True,
        )
        reason = result.get("reason")
        ok = bool(result.get("updated")) or reason in ("no_agent", "superseded")
        # Drift-recovery must also re-push the native system tools (transfer_to_number
        # / transfer_to_agent / voicemail_detection), not just the prompt (2026-06-22):
        # previously force-resync fixed prompt drift while leaving a stale or missing
        # call-bridge tool untouched, so an operator hitting "Force Resync" to repair a
        # divergent agent would still be left with a broken transfer. Mirrors the
        # _repush_bg behavior for kz_emergency/kz_phone/kz_retry.
        tool_result = ac.sync_system_tools_for_org(org_id)
        tool_reason = tool_result.get("reason")
        if not tool_result.get("updated") and tool_reason not in ("no_agent", None):
            ok, reason = False, f"system_tools: {tool_reason}"
        ac.finish_sync(org_id, seq, ok=ok, reason=reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "force-resync failed (org=%s): %s", org_id, str(exc)[:200]
        )
        ac.finish_sync(org_id, seq, ok=False, reason=str(exc)[:300])


# ─── 1.5 — Reconcile hk_ tool_ids (SUPER-ADMIN only, high risk) ──────────────
@router.post("/reconcile-tools")
async def reconcile_tools(user: CurrentUser = Depends(require_super_admin)) -> dict:
    """Reconcile the agent's prompt.tool_ids to the exact desired hk_* set.
    SUPER-ADMIN only (mirrors /prompt). Aborts without writing if any desired
    tool fails to resolve; never drops a non-hk_ (custom) id. Returns
    {removed, kept, desired}."""

    def _do() -> dict:
        agent_id = ea.get_org_agent_id(user.org_id)
        return ac.reconcile_hk_tool_ids(
            org_id=user.org_id, agent_id=agent_id, actor_id=user.id
        )

    return await run_in_threadpool(_do)
