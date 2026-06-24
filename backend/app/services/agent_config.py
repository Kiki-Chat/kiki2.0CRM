"""Reusable ElevenLabs agent-configuration helper (Step B, 2026-05-27).

This module is the single place that knows how to turn a "fresh" ElevenLabs
agent into a HeyKiki-wired agent. ``provision_org`` calls it after the DB
inserts; the manual sync route (Agent 2's surface, ``POST /api/super-admin/
orgs/{id}/sync-agent-config``) imports the same ``configure_agent`` so the
two paths can never drift.

What it does, in order:

  B.1  Fetch the phone number bound to the agent in ElevenLabs and persist
       it on ``organizations.phone_number``. Hard-fails (HTTPException 400)
       when zero phones are bound, so the caller can roll back the org row.
       With multiple phones bound it picks the first and logs a warning
       rather than failing.

  B.2  Look up the ``hk_*`` workspace tools by name, then ADDITIVELY
       merge their ``tool_id``s onto the agent's ``prompt.tool_ids`` via
       ``patch_agent_safely`` (snapshot → assert audio → PATCH → verify →
       auto-rollback → audit). Any missing tools fail loudly — they're a
       workspace-config decision, not auto-created here.

  B.3  Apply the master German prompt (``agent_prompt_template.txt``) with
       per-org name substitution. SKIPPED on re-runs (detected via
       ``organizations.agent_provisioned_at IS NOT NULL``) — once a customer
       has the agent live, their prompt is untouchable from this code path.

  B.4  Enable the ``conversation_initiation_client_data`` webhook pointing
       at our backend.

  B.5  Assert "audio" is present in client_events.

  B.6  Enable the Path A conversation_config_override whitelist (prompt,
       first_message, language) so the CRM-provisioned (N8N-created) agent
       accepts the per-call outbound override with ZERO manual toggling. Sets
       ONLY booleans — never a prompt. Additive + idempotent (backfills on
       re-sync, the way the phone_number_id capture does).

All ElevenLabs writes route through ``patch_agent_safely`` (the only module
permitted to PATCH agent config — see ``elevenlabs_agent`` module docstring).

Where ``hk_*`` tool IDs are cached: a module-level dict keyed by tool name.
Populated on first call, lives for the process lifetime. Simplest option per
the design brief — survives the uvicorn process, re-populates cheaply on
restart, and a missing workspace tool is detected on every call (no
stale-cache risk).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.common import format_address
from app.services.scheduling import WEEKDAY_KEYS, normalize_business_hours
from app.services.trade_profiles import (
    default_emergency_keywords,
    render_trade_diagnostics,
    render_trade_selfhelp,
)
from app.services.elevenlabs_agent import (
    CLIENT_EVENTS_PATH,
    OVERRIDES_WHITELIST_AGENT_PATH,
    PROMPT_PATH,
    REQUIRED_AUDIO_EVENT,
    TOOL_IDS_PATH,
    WEBHOOK_ENABLED_PATH,
    WEBHOOK_URL_PATH,
    ElevenLabsWriteError,
    VerificationFailedError,
    _get_path,
    get_agent_config,
    override_flags_ok,
    patch_agent_safely,
)

logger = logging.getLogger(__name__)

EL_BASE = "https://api.elevenlabs.io"
_TIMEOUT = 30.0

# The hk_* tool names that every HeyKiki-wired agent must carry.
HK_TOOL_NAMES: list[str] = [
    "hk_identifyCustomer",
    "hk_updateCustomerData",
    "hk_createInquiry",
    "hk_getAvailableAppointments",
    "hk_bookAppointment",
    "hk_cancelAppointment",
    "hk_changeAppointment",
    "hk_searchCustomerInquiries",
    "hk_queryKnowledgeBase",
    "hk_transferCall",
    "hk_draftCostEstimate",
]

# Conversation-initiation client-data webhook route on this backend.
# Verified live at backend/app/api/routes/conversation_init.py (router prefix
# "/api/elevenlabs", path "/conversation-init").
_CONVERSATION_INIT_PATH = "/api/elevenlabs/conversation-init"

# The conversation-init webhook URL we write onto every agent. Host is the
# ElevenLabs env-var placeholder so the SAME webhook resolves to the correct
# backend per the call's environment (the phone-number ``environment`` pin →
# ``api_host``) — no per-environment agent duplication. ``https://`` MUST be
# literal before any ``{{...}}`` per EL's URL rules.
_CONVERSATION_INIT_WEBHOOK_URL = "https://{{system__env_api_host}}" + _CONVERSATION_INIT_PATH

# verify_agent_health's webhook_url_is_prod check accepts the env-routed URL (the
# correct target going forward) OR a legacy hardcoded backend host, so agents not
# yet re-synced don't red-flag during the migration. (3f88a = UAT, 7bca =
# production — the old ``_PROD_BACKEND_URL`` was mislabeled at 3f88a.)
_UAT_BACKEND_URL = "https://backend-production-3f88a.up.railway.app"
_PROD_BACKEND_URL = "https://backend-production-7bca.up.railway.app"
_PROD_WEBHOOK_URL = f"{_PROD_BACKEND_URL}{_CONVERSATION_INIT_PATH}"
_ACCEPTED_WEBHOOK_URLS = frozenset({
    _CONVERSATION_INIT_WEBHOOK_URL,
    f"{_UAT_BACKEND_URL}{_CONVERSATION_INIT_PATH}",
    _PROD_WEBHOOK_URL,
})

# Unrendered CRM template tokens are UPPER_SNAKE ({{COMPANY_NAME}}, {{KZ_EMERGENCY}},
# {{TRADE_SELFHELP_EXAMPLES}}, …) and MUST be gone after render. ElevenLabs dynamic
# variables are lowercase ({{system__time}}, {{system__caller_id}}, {{customer_name}}, …)
# and legitimately REMAIN in the prompt — EL fills them per call — so the verify gate
# must NOT flag them. (The old "any '{{'" rule false-positived every agent.)
_CRM_TOKEN_RE = re.compile(r"\{\{\s*[A-Z][A-Z0-9_]*\s*\}\}")

# Actionable German message surfaced when an agent has no phone bound (2.3).
NO_PHONE_MESSAGE = (
    "Keine Telefonnummer im ElevenLabs-Agent hinterlegt — bitte zuerst eine "
    "Nummer zuweisen"
)

# Module-level cache: {tool_name: tool_id}. Populated on first lookup and
# refreshed on a TTL so a tool DELETED or RENAMED in the workspace can't be served
# stale for the whole process lifetime (the old code never re-fetched once a name
# was cached, so an orphaned id could be patched onto an agent).
_HK_TOOL_ID_CACHE: dict[str, str] = {}
_HK_TOOL_ID_CACHE_TS: float = 0.0
_HK_TOOL_ID_TTL = 3600  # seconds; bound on how long a stale tool id can survive

# Path to the German master prompt template (committed at this path so
# provisioning is self-contained — not loaded from Amber's Downloads dir).
# The template carries PLACEHOLDER TOKENS ({{COMPANY_NAME}}, {{KZ_EMERGENCY}},
# …) that ``render_prompt_for_org`` fills from the org record + Kiki-Zentrale
# config. There are no more hardcoded company literals to substitute.
_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "agent_prompt_template.txt"

# The complete token contract the template must satisfy. ``render_prompt_for_org``
# fills every one of these; after filling, an assertion guarantees no ``{{…}}``
# survives. Company-identity tokens + Kiki-Zentrale-config tokens.
_PROMPT_TOKENS = [
    "COMPANY_NAME", "COMPANY_TRADE", "COMPANY_CONTACT", "COMPANY_PROFILE",
    "SERVICE_AREA", "BUSINESS_HOURS",
    "KZ_REQUIRED_FIELDS", "KZ_PROBLEM_DESCRIPTION", "KZ_APPOINTMENT_CATEGORIES",
    "KZ_SCHEDULING_RULES", "KZ_EMERGENCY", "KZ_STAFF_TRANSFER", "KZ_AUTONOMY",
    "KZ_PRICE_INFO",
]


# ─── Tool lookup ─────────────────────────────────────────────────────────────
def _fetch_workspace_tools() -> dict[str, str]:
    """Return ``{tool_name: tool_id}`` for the workspace, filtered to ``hk_*``.

    Refreshes the module-level cache. Called inside ``_resolve_hk_tool_ids``
    when any required name is missing from the cache.
    """
    key = settings.elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise ElevenLabsWriteError(
            "ELEVENLABS_API_KEY not configured; cannot fetch workspace tools."
        )
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.get("/v1/convai/tools", headers={"xi-api-key": key})
    if r.status_code != 200:
        raise ElevenLabsWriteError(
            f"GET /v1/convai/tools failed: {r.status_code} {r.text[:300]}"
        )
    payload = r.json()
    items = payload.get("tools", payload) if isinstance(payload, dict) else payload
    out: dict[str, str] = {}
    for t in items or []:
        cfg = t.get("tool_config") or t
        name = cfg.get("name")
        tid = t.get("id")
        if name and tid and name.startswith("hk_"):
            out[name] = tid
    return out


def _refresh_tool_cache() -> None:
    """Full-replace the tool-id cache from the workspace and stamp the time.

    Uses clear()+update() (not a merge) so tools removed/renamed in the workspace
    are EVICTED — a merge-only update could never drop an orphaned id."""
    global _HK_TOOL_ID_CACHE_TS
    fresh = _fetch_workspace_tools()
    _HK_TOOL_ID_CACHE.clear()
    _HK_TOOL_ID_CACHE.update(fresh)
    _HK_TOOL_ID_CACHE_TS = time.time()


def _resolve_hk_tool_ids(required: list[str] | None = None) -> dict[str, str]:
    """Return ``{name: tool_id}`` for all required hk_* names.

    Fails with HTTPException(400) listing the missing names if any of the
    required tools aren't found in the workspace — operations are expected
    to create them outside this code path (workspace-config decision).

    Re-fetches when a required name is missing OR the cache is older than the TTL,
    so a workspace-side delete/rename converges instead of being served forever.
    """
    names = list(required or HK_TOOL_NAMES)
    stale = (time.time() - _HK_TOOL_ID_CACHE_TS) > _HK_TOOL_ID_TTL
    missing = [n for n in names if n not in _HK_TOOL_ID_CACHE]
    if missing or stale:
        _refresh_tool_cache()
        missing = [n for n in names if n not in _HK_TOOL_ID_CACHE]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"ElevenLabs workspace is missing required hk_* tool(s): "
                f"{', '.join(missing)}. Create them in the workspace first, "
                "then retry provisioning."
            ),
        )
    return {n: _HK_TOOL_ID_CACHE[n] for n in names}


# ─── B.1 Phone fetch ─────────────────────────────────────────────────────────
def _list_phone_numbers() -> list[dict]:
    key = settings.elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise ElevenLabsWriteError(
            "ELEVENLABS_API_KEY not configured; cannot fetch phone numbers."
        )
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.get("/v1/convai/phone-numbers", headers={"xi-api-key": key})
    if r.status_code != 200:
        raise ElevenLabsWriteError(
            f"GET /v1/convai/phone-numbers failed: {r.status_code} {r.text[:300]}"
        )
    data = r.json()
    if isinstance(data, dict):
        # Some EL list endpoints wrap items; handle both shapes.
        return data.get("phone_numbers") or data.get("items") or []
    return data or []


def fetch_phone_meta_for_agent(agent_id: str) -> dict:
    """Return ``{"phone_number", "phone_number_id", "environment"}`` for the
    Twilio number bound to ``agent_id`` in ElevenLabs.

    ``phone_number_id`` is the ElevenLabs resource id — the
    ``agent_phone_number_id`` the outbound-call API requires, distinct from the
    agent id. Raises HTTPException(400) when zero phones are bound (the caller
    MUST roll back the half-provisioned org). With multiple phones bound, picks
    the first and logs a warning rather than failing.
    """
    phones = _list_phone_numbers()
    matches = [
        p for p in phones
        if (p.get("assigned_agent") or {}).get("agent_id") == agent_id
    ]
    if not matches:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Agent has no phone number assigned in ElevenLabs — "
                "assign one first, then retry."
            ),
        )
    if len(matches) > 1:
        logger.warning(
            "Agent %s has %d phones bound; using the first (%s).",
            agent_id, len(matches), matches[0].get("phone_number"),
        )
    chosen = matches[0]
    return {
        "phone_number": chosen.get("phone_number"),
        "phone_number_id": chosen.get("phone_number_id"),
        # The environment this number is pinned to in ElevenLabs (drives
        # {{system__env_api_host}} routing). ``None`` → EL default 'production'.
        "environment": (chosen.get("assigned_agent") or {}).get("environment"),
    }


def fetch_phone_for_agent(agent_id: str) -> str:
    """Return just the E.164 phone number bound to ``agent_id`` (see
    ``fetch_phone_meta_for_agent`` for the full meta incl. phone_number_id)."""
    return fetch_phone_meta_for_agent(agent_id)["phone_number"]


def _store_phone_on_org(
    org_id: str | UUID, phone_e164: str, phone_number_id: str | None = None
) -> None:
    db = get_service_client()
    patch: dict[str, Any] = {"phone_number": phone_e164}
    if phone_number_id:
        patch["elevenlabs_phone_number_id"] = phone_number_id
    db.table("organizations").update(patch).eq("id", str(org_id)).execute()


def set_phone_environment(
    phone_number_id: str, environment: str, agent_id: str | None = None
) -> None:
    """Pin an ElevenLabs phone number to an ENVIRONMENT (env-var routing).

    Sets the phone's ``environment`` via ``PATCH /v1/convai/phone-numbers/{id}``
    so ElevenLabs resolves ``{{system__env_api_host}}`` (shared tools + the
    conversation-init webhook) to the matching backend for every call on this
    number. A phone *resource* write — distinct from agent config — so it goes
    direct (like ``_list_phone_numbers``), NOT through ``patch_agent_safely``.

    PATCH is partial; we carry the current ``agent_id`` when supplied as the
    safe mirror of the webhook-PATCH lesson (EL has rejected sibling-less
    patches). Raises ``ElevenLabsWriteError`` on a non-2xx response.
    """
    key = settings.elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise ElevenLabsWriteError(
            "ELEVENLABS_API_KEY not configured; cannot set phone environment."
        )
    body: dict[str, Any] = {"environment": environment}
    if agent_id:
        body["agent_id"] = agent_id
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.patch(
            f"/v1/convai/phone-numbers/{phone_number_id}",
            headers={"xi-api-key": key},
            json=body,
        )
    if r.status_code not in (200, 204):
        raise ElevenLabsWriteError(
            f"PATCH /v1/convai/phone-numbers/{phone_number_id} failed: "
            f"{r.status_code} {r.text[:300]}"
        )


# ─── B.3 Prompt template ─────────────────────────────────────────────────────
def _load_prompt_template() -> str:
    with open(_PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


# Company-identity literals that must NEVER survive rendering for any non-Husmann
# org. The renderer fills tokens (it no longer substitutes literals), so these are
# a defense-in-depth guard against a template regression that re-introduces them.
_IDENTITY_RESIDUE = [
    "Husmann", "Dreier", "Buxtehude", "Stader", "04161", "husmann-dreier",
]

# German weekday labels for business-hours rendering (Monday-first; index aligns
# with scheduling.WEEKDAY_KEYS / datetime.weekday()).
_WEEKDAY_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
               "Samstag", "Sonntag"]

# Fallback emergency keywords — used ONLY when the org configured none. Kept
# trade-neutral-ish but practical for the SHK launch customer; an org with its
# own list always overrides this.
_DEFAULT_EMERGENCY_KEYWORDS = [
    "Rohrbruch / unkontrolliert austretendes Wasser",
    "Kompletter Heizungsausfall",
    "Kompletter Warmwasserausfall",
    "Gasgeruch",
]


# ─── Config fetchers (all via the service client) ────────────────────────────
def _fetch_org_identity(org_id: str | UUID) -> dict:
    """Name + address + phone + email + trade + management for prompt rendering."""
    db = get_service_client()
    rows = (
        db.table("organizations")
        .select("name, address, phone_number, email, trade, management")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


def _fetch_required_fields(org_id: str | UUID) -> list[dict]:
    """The org's agent_required_fields rows, ordered by sort_order."""
    db = get_service_client()
    return (
        db.table("agent_required_fields")
        .select(
            "field_key, label, description, is_duty, identification_role, "
            "sort_order, is_active, linked_setting"
        )
        .eq("org_id", str(org_id))
        .order("sort_order")
        .execute()
        .data
        or []
    )


def _fetch_appointment_categories(org_id: str | UUID) -> list[dict]:
    """The org's appointment_categories, ordered by sort_order, with each
    ``default_employee_id`` resolved to a display name (best-effort)."""
    db = get_service_client()
    cats = (
        db.table("appointment_categories")
        .select("name, description, duration_minutes, default_employee_id, sort_order")
        .eq("org_id", str(org_id))
        .order("sort_order")
        .execute()
        .data
        or []
    )
    # default_employee_id now references employees(id) (FK retargeted from
    # users.id), so resolve the name from employees.display_name.
    emp_ids = [c["default_employee_id"] for c in cats if c.get("default_employee_id")]
    names: dict[str, str] = {}
    if emp_ids:
        employees = (
            db.table("employees")
            .select("id, display_name")
            .in_("id", list(set(emp_ids)))
            .execute()
            .data
            or []
        )
        names = {e["id"]: (e.get("display_name") or "").strip() for e in employees}
    for c in cats:
        eid = c.get("default_employee_id")
        c["employee_name"] = names.get(eid) or None
    return cats


def _fetch_kz_config(org_id: str | UUID) -> dict:
    """The org's Kiki-Zentrale agent_configs row (the columns that drive the
    prompt). Missing row → empty dict (renderers degrade gracefully)."""
    db = get_service_client()
    rows = (
        db.table("agent_configs")
        .select(
            "kiki_level, appointments_enabled, appointments_level, kva_enabled, kva_level, "
            "problem_description, prompt_manual_override, trade, scheduling, "
            "scheduling_enabled, buffer_minutes, max_appointments_per_day, "
            "parallel_slots, lead_time_hours, lead_time_days, lead_time_only_weekdays, "
            "lead_time_earliest_clock, emergency_enabled, emergency_number, "
            "emergency_only_outside_business_hours, emergency_keywords, "
            "emergency_extra_windows, emergency_surcharge_notice_enabled, "
            # forwarding_number is the LEGACY emergency fallback — build_transfer_tool
            # and render_emergency_block fall back to it when emergency_number is
            # unset; omitting it here made that fallback dead code (audit 2026-06-11:
            # affected orgs silently got NO transfer tool + a "leite NICHT weiter"
            # prompt on real emergencies).
            "emergency_surcharge_text, forwarding_number, incoming_forwarding_number, "
            "price_info_enabled, conversation_logic, conversation_logic_enabled"
        )
        .eq("org_id", str(org_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


def render_price_info_block(cfg: dict) -> str:
    """``# Preise`` body, gated by the Preisauskunft toggle (price_info_enabled).

    ON  → Kiki quotes Richtpreise from the knowledge base (legacy behavior).
    OFF (default) → Kiki gives NO prices and offers a Kostenvoranschlag instead.
    Wires the Kiki-Zentrale toggle to real call behavior (previously decorative)."""
    if cfg.get("price_info_enabled"):
        return (
            "  Wenn nach Preisen gefragt wird, agiere Stichpunkt für Stichpunkt — nicht\n"
            "  zu viele Informationen auf einmal. Einleitung wörtlich:\n"
            "  „Gerne sage ich Ihnen, was die gewünschte Leistung ungefähr kostet. Ich\n"
            "  nenne Ihnen jeweils einen Richtpreis — der kann je nach Situation vor Ort\n"
            "  etwas abweichen.“\n"
            "  Nenne AUSSCHLIESSLICH Preise aus dem Wissensbasis-Dokument „Preisliste\n"
            "  (Richtpreise)“ — exakt den dort hinterlegten Betrag, inkl. Einheit. ERFINDE\n"
            "  NIEMALS einen Preis und runde nicht frei. Steht die angefragte Leistung\n"
            "  NICHT in der Preisliste: sage ehrlich, dass du dafür keinen Richtpreis\n"
            "  nennen kannst, und biete an, dass das Team einen unverbindlichen\n"
            "  Kostenvoranschlag erstellt — keine Preise raten."
        )
    return (
        "  Nenne am Telefon KEINE Preise oder Richtpreise — auch keine ungefähren.\n"
        "  Wenn nach Preisen gefragt wird, erkläre freundlich, dass sich der genaue\n"
        "  Preis erst nach einer Einschätzung beziffern lässt, und biete an, dass das\n"
        "  Team einen unverbindlichen Kostenvoranschlag erstellt:\n"
        "  „Das hängt von den Details vor Ort ab — ich nehme Ihr Anliegen gern auf und\n"
        "  das Team meldet sich mit einem unverbindlichen Kostenvoranschlag.“"
    )


# ─── Company-identity render helpers (German prose, empty-safe) ──────────────
def _render_company_contact(address: str, phone: str, email: str) -> str:
    """Body for the ``=== Firmeninformationen ===`` block (heading lives in the
    template). Omits any empty field; never invents data."""
    lines = []
    if address:
        lines.append(f"Adresse: {address}")
    if phone:
        lines.append(f"Telefon: {phone}")
    if email:
        lines.append(f"E-Mail: {email}")
    return "\n".join(lines) if lines else "Die Kontaktdaten sind im System hinterlegt."


def _render_company_profile(
    name: str, trade: str, address: str, phone: str, mgmt_name: str
) -> str:
    """Body for the Wissensbasis ``# Unternehmen`` block (heading in template).
    Two-space indented to match the surrounding Wissensbasis indentation."""
    first = f"{name} — {trade}." if trade else f"{name}."
    lines = [first]
    contact = []
    if address:
        contact.append(address)
    if phone:
        contact.append(f"Telefon {phone}")
    if contact:
        lines.append(". ".join(contact) + ".")
    if mgmt_name:
        lines.append(f"Geschäftsführung: {mgmt_name}.")
    return "\n".join("  " + ln for ln in lines)


def _render_service_area() -> str:
    """Generic service-area instruction (body for the ``# Einsatzgebiet`` block).
    No per-org town list exists today — keep it intake-friendly."""
    return (
        "  Nimm Anliegen aus dem üblichen Einzugsgebiet regulär auf; liegt der "
        "Einsatzort\n"
        "  möglicherweise außerhalb, nimm das Anliegen trotzdem auf und sage, dass "
        "das Team\n"
        "  die Anfahrt prüft."
    )


def _render_business_hours(scheduling: dict | None) -> str:
    """Per-weekday business-hours prose (Mo–So) from scheduling['business_hours'].
    Falls back to a neutral sentence when no hours are configured."""
    sched = scheduling if isinstance(scheduling, dict) else {}
    raw = sched.get("business_hours")
    if not isinstance(raw, dict) or not raw:
        return "  Die genauen Geschäftszeiten sind im System hinterlegt."
    hours = normalize_business_hours(raw)
    lines = []
    for idx, key in enumerate(WEEKDAY_KEYS):
        day = hours.get(key) or {}
        label = _WEEKDAY_DE[idx]
        if not day.get("open"):
            lines.append(f"  {label}: geschlossen")
            continue
        start, end = day.get("start"), day.get("end")
        if day.get("break_start") and day.get("break_end"):
            span = (
                f"{start}–{day['break_start']} und {day['break_end']}–{end}"
            )
        else:
            span = f"{start}–{end}"
        lines.append(f"  {label}: {span} Uhr")
    return "\n".join(lines)


# ─── Kiki-Zentrale config render helpers (German prose, empty-safe) ──────────
# Leitfaden offer-steps: linked rows render an OFFER instruction at their dragged
# position instead of a question. The negative case (setting off) is carried by
# KZ_AUTONOMY / KZ_PRICE_INFO — an inactive linked row simply renders nothing.
_LINKED_OFFER_LINES = {
    "offer_appointment": (
        "- **Termin anbieten** — biete an DIESER Stelle aktiv einen Termin an "
        "(weiter mit Schritt 3 — Termin)."
    ),
    "offer_kva": (
        "- **Kostenvoranschlag anbieten** — biete an dieser Stelle aktiv einen "
        "unverbindlichen Kostenvoranschlag an."
    ),
    "offer_price_info": (
        "- **Preisauskunft** — beantworte Preisfragen an dieser Stelle gemäß "
        "Abschnitt „# Preise“."
    ),
}


def _field_effective_active(f: dict, cfg: dict | None) -> bool:
    """Linked rows derive their active state from the live agent_configs boolean
    (the row's own is_active is position-only); plain rows use is_active."""
    linked = f.get("linked_setting")
    if linked:
        if cfg is None:
            return True
        return bool(cfg.get(linked))
    active = f.get("is_active")
    return True if active is None else bool(active)


def render_required_fields_block(fields: list[dict], cfg: dict | None = None) -> str:
    """The ordered Leitfaden for the ``## Pflichtfelder`` body: fields to ask plus
    offer-steps (Termin/KVA/Preisauskunft) at their configured position.

    Each field → ``- **{label}**{' (optional)'} — {description}``. Fields with an
    identification_role are noted as auto-recognised; inactive rows are skipped.
    Empty config → a sensible default field set so the agent never loses its
    data-capture instruction."""
    if not fields:
        return (
            "PFLICHTFELDER: Name, Telefonnummer, Adresse, Anliegen. "
            "OPTIONALE FELDER: Kundennummer."
        )
    lines = []
    for f in fields:
        if not _field_effective_active(f, cfg):
            continue
        linked = f.get("linked_setting")
        if linked:
            offer = _LINKED_OFFER_LINES.get((f.get("field_key") or "").strip())
            if offer:
                lines.append(offer)
            continue
        label = (f.get("label") or f.get("field_key") or "").strip()
        if not label:
            continue
        opt = "" if f.get("is_duty", True) else " (optional)"
        desc = (f.get("description") or "").strip()
        line = f"- **{label}**{opt}"
        if desc:
            line += f" — {desc}"
        if f.get("identification_role"):
            line += " (wird automatisch erkannt, falls verfügbar)"
        lines.append(line)
    if not lines:
        return (
            "PFLICHTFELDER: Name, Telefonnummer, Adresse, Anliegen. "
            "OPTIONALE FELDER: Kundennummer."
        )
    # Topic 8: fields arrive in the org's configured priority order
    # (agent_required_fields.sort_order) — ask them in that order, top first.
    # BUT never re-ask a field that's already known / auto-recognised (caller-ID,
    # hk_identifyCustomer) — only confirm it briefly. (Fixes the agent re-asking
    # for the phone number it already has.)
    lead = (
        "Arbeite die folgenden Punkte in DIESER Reihenfolge ab (oberster Punkt = "
        "höchste Priorität, zuerst): Felder erfragen bzw. Angebote (Termin/KVA/"
        "Preisauskunft) aktiv an genau dieser Stelle machen. Felder, die bereits "
        "bekannt sind oder automatisch erkannt wurden (z. B. die Telefonnummer über "
        "die Anrufererkennung bzw. hk_identifyCustomer), NICHT erneut erfragen — "
        "höchstens kurz bestätigen:"
    )
    return lead + "\n" + "\n".join(lines)


def render_conversation_logic_block(cfg: dict) -> str:
    """``{{KZ_CONVERSATION_LOGIC}}`` — the org's Wenn/Dann-Gesprächslogik as a
    numbered block ("Schritt 1a"), compiled from agent_configs.conversation_logic.
    Disabled/empty → "" (token vanishes, zero prompt cost)."""
    if cfg.get("conversation_logic_enabled") is False:
        return ""
    raw = cfg.get("conversation_logic")
    if not raw or not isinstance(raw, dict) or not raw.get("blocks"):
        return ""
    from app.schemas.conversation_logic import (
        ConversationLogic,
        compile_conversation_logic,
    )

    try:
        compiled = compile_conversation_logic(ConversationLogic.model_validate(raw))
    except Exception as exc:  # noqa: BLE001 — a bad stored tree must not kill rendering
        logger.warning("conversation_logic compile failed: %s", str(exc)[:200])
        return ""
    if not compiled:
        return ""
    return (
        "## Schritt 1a — Firmenspezifische Gesprächslogik (VERBINDLICH)\n\n"
        "Diese Wenn/Dann-Regeln ERGÄNZEN Schritt 1 und gehen den allgemeinen 1–2\n"
        "Rückfragen aus Schritt 1 vor: Trifft ein Zweig zu, arbeite ihn vollständig\n"
        "ab und überspringe die generischen Rückfragen. Schritt 0 (Identifikation),\n"
        "Schritt 2 (Daten) und Schritt 3 (Termin) bleiben unverändert, sofern eine\n"
        "„Gehe zu“-Anweisung nichts anderes sagt.\n\n"
        + compiled
    )


def render_problem_description_block(text: str | None) -> str:
    """Short instruction paragraph telling Kiki what to capture for this org's
    typical problems. Empty config → empty string (the token just disappears)."""
    text = (text or "").strip()
    if not text:
        return ""
    return (
        "  Erfasse bei den typischen Anliegen dieses Betriebs gezielt die "
        "folgenden Details,\n"
        "  bevor du zu Schritt 2 übergehst:\n"
        f"  {text}"
    )


def render_appointment_categories_block(categories: list[dict]) -> str:
    """Bookable-category list for the ``## Termin-Kategorien`` body.

    ``- **„{name}"** ({duration} Min)[ — Standard-Ansprechpartner: {emp}][: {desc}]``.
    Empty config → a fallback that tells the agent to pick the closest category or
    omit the parameter."""
    if not categories:
        return (
            "Beim Buchen die naheliegendste Kategorie wählen; im Zweifel den "
            "Parameter weglassen."
        )
    lines = []
    for c in categories:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        dur = c.get("duration_minutes")
        dur_txt = f" ({dur} Min)" if dur else ""
        line = f"- **„{name}“**{dur_txt}"
        emp = (c.get("employee_name") or "").strip()
        if emp:
            line += f" — Standard-Ansprechpartner: {emp}"
        desc = (c.get("description") or "").strip()
        if desc:
            line += f": {desc}"
        lines.append(line)
    if not lines:
        return (
            "Beim Buchen die naheliegendste Kategorie wählen; im Zweifel den "
            "Parameter weglassen."
        )
    lines.append(
        "Gib `kategorie` bei JEDEM `hk_bookAppointment`-Aufruf an: Wähle die "
        "Kategorie, deren Beschreibung am besten zum geschilderten Anliegen passt "
        "— nutze dafür die Beschreibungen oben und verwende den Kategorienamen "
        "EXAKT wie aufgeführt. Nur wenn wirklich keine passt, lasse den Parameter "
        "weg. Die Kategorie bestimmt automatisch Dauer und Zuständigkeit."
    )
    return "\n".join(lines)


def render_scheduling_rules_block(cfg: dict) -> str:
    """Prose scheduling rules for the ``{{KZ_SCHEDULING_RULES}}`` token: lead time
    (hours), earliest clock on the first bookable day, buffer/parallel/max-per-day.
    If appointment booking is disabled (autonomy "Termine" off — or the legacy
    scheduling_enabled flag), instruct the agent NOT to book and take a message."""
    if cfg.get("appointments_enabled") is False or cfg.get("scheduling_enabled") is False:
        return (
            "**Keine Online-Terminbuchung:** Buche in diesem Betrieb KEINE festen "
            "Termine.\n"
            "Nimm den Terminwunsch stattdessen mit `hk_createInquiry` "
            "(`rueckrufGewuenscht=true`)\n"
            "auf — das Team stimmt den Termin telefonisch ab. Rufe weder "
            "`hk_getAvailableAppointments`\n"
            "noch `hk_bookAppointment` auf."
        )

    lines = []
    hours = cfg.get("lead_time_hours")
    if hours is None and isinstance(cfg.get("lead_time_days"), int):
        hours = cfg["lead_time_days"] * 24  # legacy orgs without the new column
    if isinstance(hours, int) and hours > 0:
        unit_note = " (gezählt nur über Werktage)" if cfg.get("lead_time_only_weekdays") else ""
        sentence = (
            f"**Vorlauf:** Termine sind frühestens {hours} Stunden nach dem Anruf "
            f"buchbar{unit_note}; frühere Zeiten bietest du NICHT an."
        )
        clock = _clock_str(cfg.get("lead_time_earliest_clock"))
        if clock:
            sentence += (
                f" Am frühestmöglichen Tag beginnen Termine frühestens um {clock} Uhr "
                "— biete dort keine früheren Zeiten an; an späteren Tagen gelten die "
                "normalen Geschäftszeiten."
            )
        lines.append(sentence)
    else:
        lines.append(
            "**Vorlauf:** Verlasse dich auf das Tool-Result von "
            "`hk_getAvailableAppointments` — biete genau die zurückgegebenen Slots "
            "an und erfinde keine früheren Zeiten."
        )

    parallel = cfg.get("parallel_slots")
    if isinstance(parallel, int) and parallel > 1:
        lines.append(
            f"Es können bis zu {parallel} Termine parallel stattfinden."
        )
    max_day = cfg.get("max_appointments_per_day")
    if isinstance(max_day, int) and max_day > 0:
        lines.append(
            f"Pro Tag sind höchstens {max_day} Termine möglich."
        )
    lines.append(
        "Verlasse dich beim Anbieten von Slots immer auf das Tool-Result; erfinde "
        "keine Zeiten."
    )
    return "\n".join(lines)


def render_emergency_block(cfg: dict) -> str:
    """Notfall-Definition + when-active + surcharge prose for ``{{KZ_EMERGENCY}}``.

    Disabled → a short 'no emergency service' instruction. Enabled → the configured
    keyword list (fallback set only if empty), the active-window clause, and the
    optional surcharge notice. Transfer is always via hk_transferCall emergency=true."""
    if not cfg.get("emergency_enabled"):
        return (
            "  Kein Notdienst aktiv: außerhalb der Geschäftszeiten Anliegen "
            "aufnehmen, nicht weiterleiten."
        )

    kws = cfg.get("emergency_keywords")
    kws = [str(k).strip() for k in kws if str(k).strip()] if isinstance(kws, list) else []
    if not kws:
        # Trade-aware fallback (generic for unrecognised trades) instead of the old
        # SHK-only default list — so each genre gets sensible emergency keywords until
        # the org configures its own.
        kws = default_emergency_keywords(cfg.get("trade"))

    lines = ["  Ein NOTFALL liegt nur bei einem dieser Fälle vor:"]
    lines += [f"  - {k}" for k in kws]
    lines.append(
        "  Kleinere, nicht akute Probleme, geplante Wartung oder Beratung"
    )
    lines.append(
        "  sind KEINE Notfälle — auch wenn der Anrufer es so nennt. Bei "
        "Unsicherheit GENAU"
    )
    lines.append("  EINMAL gezielt nachfragen und nur bei klarer Bestätigung weiterleiten.")

    # When is the emergency path active?
    windows = cfg.get("emergency_extra_windows")
    window_txt = _emergency_windows_str(windows)
    if cfg.get("emergency_only_outside_business_hours"):
        active = (
            "  Der Notdienst greift NUR außerhalb der Geschäftszeiten (siehe "
            "Abschnitt „=== Geschäftszeiten ===“)."
        )
    else:
        active = (
            "  Der Notdienst greift bei einem bestätigten Notfall JEDERZEIT — auch "
            "INNERHALB der Geschäftszeiten. Ein per "
            "Notfall-Stichwort bestätigter Notfall wird also unabhängig von der "
            "Uhrzeit sofort weitergeleitet."
        )
    if window_txt:
        active += f" Zusätzliche Notdienst-Zeiten: {window_txt}."
    lines.append(active)

    # Optional surcharge notice.
    if cfg.get("emergency_surcharge_notice_enabled"):
        surcharge = (cfg.get("emergency_surcharge_text") or "").strip()
        if surcharge:
            lines.append(f"  Weise vor der Weiterleitung auf den Notdienst-Zuschlag hin: {surcharge}")
        else:
            lines.append(
                "  Weise vor der Weiterleitung darauf hin, dass für den Notdienst "
                "ein Zuschlag anfallen kann."
            )

    lines.append(
        "  Bei einem bestätigten NOTFALL buchst du KEINEN Termin — rufe weder "
        "`hk_getAvailableAppointments` noch `hk_bookAppointment` auf. Notfall und "
        "Terminvergabe schließen sich aus."
    )
    if (cfg.get("emergency_number") or cfg.get("forwarding_number") or "").strip():
        lines.append(
            "  Sag dem Anrufer bei bestätigtem Notfall ZUERST kurz, dass du ihn jetzt mit "
            "dem Notdienst verbindest, und rufe DANN das System-Werkzeug "
            "`transfer_to_number` auf — die Weiterleitung erfolgt sofort, sprich danach "
            "nicht weiter. Schlägt sie fehl, nimm sofort eine dringende Rückrufnotiz auf "
            "(`hk_createInquiry`, `dringend=true`, `rueckrufGewuenscht=true`)."
        )
    else:
        lines.append(
            "  Es ist KEINE Notdienst-Nummer hinterlegt — leite NICHT weiter. Nimm bei "
            "bestätigtem Notfall stattdessen sofort eine dringende Rückrufnotiz auf "
            "(`hk_createInquiry`, `dringend=true`, `rueckrufGewuenscht=true`) und sichere "
            "einen unverzüglichen Rückruf zu."
        )
    return "\n".join(lines)


def render_staff_transfer_block(cfg: dict) -> str:
    """Explicit "connect me to a person" handling for the ``{{KZ_STAFF_TRANSFER}}``
    token. Live staff transfer is only offered when an ``incoming_forwarding_number``
    is configured AND it is inside business hours; otherwise the agent takes a
    callback note (the existing default). The transfer itself is the native
    ``transfer_to_number`` system tool (the staff rule is configured there)."""
    number_set = bool((cfg.get("incoming_forwarding_number") or "").strip())
    if not number_set:
        return (
            "  Es ist KEINE Mitarbeiter-Weiterleitung hinterlegt. Bei der Bitte, mit "
            "einer Person zu sprechen, nimm eine Rückrufnotiz auf (kein Live-Transfer)."
        )
    return (
        "  Wenn der Anrufer AUSDRÜCKLICH darum bittet, sofort mit einem Mitarbeiter/"
        "einer Person verbunden zu werden, UND es INNERHALB der Geschäftszeiten ist:\n"
        "  - Sage kurz, dass du verbindest, und rufe das System-Werkzeug "
        "`transfer_to_number` auf (Mitarbeiter-Weiterleitung). Die Nummer ist dort "
        "hinterlegt — du musst sie weder kennen noch ansagen.\n"
        "  - Außerhalb der Geschäftszeiten ODER wenn keine sofortige Verbindung "
        "gewünscht ist (reine Rückrufbitte): nimm stattdessen eine Notiz mit "
        "`hk_createInquiry` (`rueckrufGewuenscht=true`) auf — nicht weiterleiten.\n"
        "  - Schlägt die Weiterleitung fehl: entschuldige dich kurz und nimm eine "
        "Rückrufnotiz mit `hk_createInquiry` (`rueckrufGewuenscht=true`) auf."
    )


def render_autonomy_block(cfg: dict) -> str:
    """Per-capability autonomy guidance for the ``{{KZ_AUTONOMY}}`` token.

    Emits a Termine sub-block and a KVA sub-block, each gated by its own enable
    toggle + level (1/2/3) on agent_configs (appointments_enabled/_level,
    kva_enabled/_level). Falls back to the legacy single kiki_level when a
    per-capability level is unset. Projekte + Rechnungen are back-office
    automations and contribute nothing to the prompt."""
    def _legacy() -> int:
        try:
            return int(cfg.get("kiki_level", 2) or 2)
        except (TypeError, ValueError):
            return 2

    def _level(key: str) -> int:
        v = cfg.get(key)
        if v is None:
            return _legacy()
        try:
            return int(v)
        except (TypeError, ValueError):
            return 2

    lines: list[str] = []

    # ── Termine ──
    appt_enabled = cfg.get("appointments_enabled")
    appt_enabled = True if appt_enabled is None else bool(appt_enabled)
    if not appt_enabled or _level("appointments_level") == 1:
        lines.append(
            "  Termine: Du nimmst Terminwünsche nur auf (hk_createInquiry) und buchst "
            "KEINE Termine — das Team meldet sich beim Kunden."
        )
    elif _level("appointments_level") == 3:
        lines.append(
            "  Termine: Du buchst Termine verbindlich (hk_bookAppointment) und "
            "bestätigst sie dem Anrufer direkt im Gespräch."
        )
    else:
        lines.append(
            "  Termine: Du buchst Termine als Reservierung (hk_bookAppointment); das "
            "Team bestätigt sie anschließend — sag dem Anrufer, dass die Bestätigung folgt."
        )

    # ── Kostenvoranschläge (KVA) ──
    if not bool(cfg.get("kva_enabled")) or _level("kva_level") == 1:
        lines.append(
            "  Kostenvoranschläge: Du erstellst KEINE Kostenvoranschläge und schlägst "
            "auch keine vor — nimm einen entsprechenden Wunsch nur als Anliegen auf."
        )
    elif _level("kva_level") == 3:
        lines.append(
            "  Kostenvoranschläge: Erstelle aus den besprochenen Positionen einen "
            "KVA-Entwurf (hk_draftCostEstimate); er wird — sofern eine E-Mail-Adresse "
            "vorliegt — direkt an den Kunden versendet."
        )
    else:
        lines.append(
            "  Kostenvoranschläge: Erstelle aus den besprochenen Positionen einen "
            "KVA-Entwurf (hk_draftCostEstimate); das TEAM prüft und versendet ihn."
        )

    return "\n".join(lines)


def _clock_str(value: Any) -> str:
    """Normalise a time value (``datetime.time``, ``"13:00:00"``, ``"13:00"``) to
    ``"HH:MM"``; empty/unparseable → ""."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    m = re.match(r"^(\d{1,2}):(\d{2})", s)
    if not m:
        return ""
    try:
        return f"{int(m[1]):02d}:{int(m[2]):02d}"
    except ValueError:
        return ""


# NB: distinct name from the `_WEEKDAY_DE` LIST near the top (full names, int-indexed
# by `_render_business_hours`). This short-form abbreviation map previously REUSED the
# `_WEEKDAY_DE` name and shadowed the list at runtime → `_WEEKDAY_DE[0]` raised
# KeyError, breaking BUSINESS_HOURS render for every org with business hours.
_WEEKDAY_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WEEKDAY_ABBR_DE = {
    "mon": "Mo", "tue": "Di", "wed": "Mi", "thu": "Do",
    "fri": "Fr", "sat": "Sa", "sun": "So",
}


def _weekdays_str(days: Any) -> str:
    """Render a window's weekday keys (``["mon","wed"]``) into ``"Mo, Mi"`` in
    canonical order; empty/missing → "" (meaning: the window applies every day)."""
    if not isinstance(days, list):
        return ""
    keys = {str(d).strip().lower() for d in days}
    return ", ".join(_WEEKDAY_ABBR_DE[k] for k in _WEEKDAY_ORDER if k in keys)


def _emergency_windows_str(windows: Any) -> str:
    """Render the emergency_extra_windows list (``[{from,to,label?,weekdays?}, …]``)
    into a short German phrase. Best-effort — skips malformed entries. Selected
    weekdays prefix the time range (e.g. ``Mo, Mi 18:00–22:00 Uhr``); no weekdays
    → the window applies on every day."""
    if not isinstance(windows, list):
        return ""
    parts = []
    for w in windows:
        if not isinstance(w, dict):
            continue
        frm = _clock_str(w.get("from"))
        to = _clock_str(w.get("to"))
        if not (frm and to):
            continue
        seg = f"{frm}–{to} Uhr"
        days = _weekdays_str(w.get("weekdays"))
        if days:
            seg = f"{days} {seg}"
        label = (w.get("label") or "").strip()
        if label:
            seg = f"{label} ({seg})"
        parts.append(seg)
    return ", ".join(parts)


# ─── Feature-region conditional rendering ────────────────────────────────────
# The template can wrap a whole feature's prose in HTML-comment markers:
#   <!-- FEAT:notdienst -->  …emitted only when the feature is ON…  <!-- /FEAT:notdienst -->
# render_prompt_for_org strips the markers when the feature is ON — leaving the
# content BYTE-IDENTICAL to the pre-marker template, so any org that currently has
# the feature on sees zero change — and removes the ENTIRE region when the feature is
# OFF, so a disabled capability leaves no footprint and cannot interfere with the rest
# of the prompt. Each feature is independent (its own marker name). To gate a new
# region: wrap it in the template + add one entry to the map in render_prompt_for_org.
def _apply_feature_regions(text: str, features: dict[str, bool]) -> str:
    """Strip ``<!-- FEAT:name -->…<!-- /FEAT:name -->`` regions per ``features``.

    ON  → drop just the two marker lines (content kept, byte-identical to no-marker).
    OFF → drop the whole region between and including the markers.
    Raises if any ``<!-- FEAT: -->`` marker survives unprocessed (its feature name was
    never registered) — that would otherwise leak a raw comment into the live prompt."""
    for name, enabled in features.items():
        open_m = re.escape(f"<!-- FEAT:{name} -->")
        close_m = re.escape(f"<!-- /FEAT:{name} -->")
        if enabled:
            text = re.sub(open_m + r"\n?", "", text)
            text = re.sub(close_m + r"\n?", "", text)
        else:
            text = re.sub(open_m + r".*?" + close_m + r"\n?", "", text, flags=re.DOTALL)
    leftover = sorted(set(re.findall(r"<!-- /?FEAT:[^>]+-->", text)))
    if leftover:
        raise RuntimeError(f"unprocessed feature-region marker(s): {leftover}")
    return text


def render_prompt_for_org(
    org_name: str, org: dict | None = None, org_id: str | UUID | None = None
) -> str:
    """Master inbound prompt: fill every PLACEHOLDER TOKEN in the template.

    Company-identity tokens come from the ``org`` record (name + address + phone +
    email + trade + management.name). Kiki-Zentrale-config tokens (required fields,
    problem description, categories, scheduling rules, emergency) come from the
    per-org config tables — fetched only when ``org_id`` is given; otherwise the
    config tokens render with empty/fallback content so the function still works
    name-only (e.g. provisioning before any config exists).

    After filling, the function asserts NO ``{{…}}`` survives, keeps the company-
    identity residue guard, and keeps the legacy ``wkp_shared_`` tool-token guard.
    """
    org = org or {}
    text = _load_prompt_template()

    # ── Company identity (omit empty fields — never invent). ──
    address = format_address(org.get("address")) or ""
    phone = (org.get("phone_number") or "").strip()
    email = (org.get("email") or "").strip()
    mgmt = org.get("management") if isinstance(org.get("management"), dict) else {}
    mgmt_name = (mgmt.get("name") or "").strip()

    # ── Kiki-Zentrale config (only when we have an org_id to read it). ──
    kz_cfg: dict = {}
    required_fields: list[dict] = []
    categories: list[dict] = []
    if org_id is not None:
        kz_cfg = _fetch_kz_config(org_id)
        required_fields = _fetch_required_fields(org_id)
        categories = _fetch_appointment_categories(org_id)

    # Trade: prefer the Kiki-Zentrale config trade, fall back to the org record,
    # finally a neutral default so the persona sentence never reads oddly.
    trade = (kz_cfg.get("trade") or org.get("trade") or "").strip() or "Handwerk"

    tokens = {
        "COMPANY_NAME": org_name,
        "COMPANY_TRADE": trade,
        "COMPANY_CONTACT": _render_company_contact(address, phone, email),
        "COMPANY_PROFILE": _render_company_profile(
            org_name, trade, address, phone, mgmt_name
        ),
        "SERVICE_AREA": _render_service_area(),
        # Trade-aware intake examples (universal across crafts/genres): the org's
        # trade selects an appropriate diagnostic + self-help set, generic fallback
        # for anything unrecognised — so a car mechanic / locksmith / IT firm is
        # never shown plumbing examples. See app/services/trade_profiles.py.
        "TRADE_DIAGNOSTIC_EXAMPLES": render_trade_diagnostics(trade),
        "TRADE_SELFHELP_EXAMPLES": render_trade_selfhelp(trade),
        "BUSINESS_HOURS": _render_business_hours(kz_cfg.get("scheduling")),
        "KZ_REQUIRED_FIELDS": render_required_fields_block(required_fields, kz_cfg),
        # The problem detail is now a reorderable required field (field_key
        # 'problem_description'), so it renders INSIDE the required-fields block at
        # its chosen sort position. Suppress the old standalone block whenever that
        # field exists; fall back to it for any org not yet migrated (0052).
        "KZ_PROBLEM_DESCRIPTION": (
            ""
            if any(f.get("field_key") == "problem_description" for f in required_fields)
            else render_problem_description_block(kz_cfg.get("problem_description"))
        ),
        "KZ_APPOINTMENT_CATEGORIES": render_appointment_categories_block(categories),
        "KZ_CONVERSATION_LOGIC": render_conversation_logic_block(kz_cfg),
        "KZ_SCHEDULING_RULES": render_scheduling_rules_block(kz_cfg),
        "KZ_EMERGENCY": render_emergency_block(kz_cfg),
        "KZ_STAFF_TRANSFER": render_staff_transfer_block(kz_cfg),
        "KZ_AUTONOMY": render_autonomy_block(kz_cfg),
        "KZ_PRICE_INFO": render_price_info_block(kz_cfg),
    }
    # Conditionally render feature regions BEFORE token substitution, so a disabled
    # feature's region (and anything inside it) leaves no trace. Byte-identical when
    # ON. Currently gated: Notdienst (the emergency-transfer procedure) — when no
    # emergency service is configured, the agent isn't told to transfer to a Notdienst
    # number that doesn't exist; the {{KZ_EMERGENCY}} block still renders its short
    # "kein Notdienst aktiv → Anliegen aufnehmen" fallback.
    text = _apply_feature_regions(
        text, {"notdienst": bool(kz_cfg.get("emergency_enabled"))}
    )
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", value)

    # ── Guards. ──
    # ElevenLabs fills its own {{system__*}} dynamic vars at call time — those are
    # intentional and must remain. Any OTHER {{…}} means a token went unfilled.
    leftover = sorted(
        t for t in set(re.findall(r"\{\{[^}]+\}\}", text))
        if not t.startswith("{{system__")
    )
    if leftover:
        raise RuntimeError(
            f"unfilled prompt token(s) after render: {leftover}"
        )
    if "wkp_shared_" in text:
        raise RuntimeError(
            "agent_prompt_template.txt still contains 'wkp_shared_' tokens — "
            "the tool-name mapping is incomplete."
        )
    # The residue scan catches the DEMO identity left hardcoded in the template, but it
    # must NOT trip on a real customer whose OWN name/address legitimately contains a
    # marker word (e.g. "Husman & Dreier GmbH" → "Dreier", a common surname). Mask the
    # values we just substituted; whatever REMAINS is genuine un-templated residue.
    scan = text
    for _v in (
        tokens["COMPANY_NAME"],
        tokens["COMPANY_TRADE"],
        tokens["COMPANY_CONTACT"],
        tokens["COMPANY_PROFILE"],
    ):
        if _v:
            scan = scan.replace(_v, " ")
    residue = [m for m in _IDENTITY_RESIDUE if m in scan]
    if residue:
        raise RuntimeError(f"company-identity residue after render: {residue}")
    return text


# ─── Tiny org-state read ─────────────────────────────────────────────────────
def _is_agent_already_provisioned(org_id: str | UUID) -> bool:
    """True iff organizations.agent_provisioned_at is set for ``org_id``."""
    db = get_service_client()
    rows = (
        db.table("organizations")
        .select("agent_provisioned_at")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(rows and rows[0].get("agent_provisioned_at"))


def _stamp_agent_provisioned(org_id: str | UUID) -> None:
    from datetime import datetime, timezone
    db = get_service_client()
    db.table("organizations").update(
        {
            "agent_provisioned_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", str(org_id)).execute()


# ─── Reusable additive steps (shared by configure_agent + the bind path) ─────
def attach_hk_tools(
    agent_id: str,
    *,
    actor_id: str | UUID | None = None,
    org_id: str | UUID | None = None,
) -> list[str]:
    """Additively merge the 11 ``hk_*`` tool ids onto the agent (step B.2).

    Returns the ids newly added (``[]`` when all were already present).
    Idempotent. Raises HTTPException(400) if a required workspace tool is
    missing. Goes through ``patch_agent_safely`` (snapshot/verify/rollback).
    """
    tool_map = _resolve_hk_tool_ids(HK_TOOL_NAMES)
    required_ids = list(tool_map.values())
    current = get_agent_config(agent_id)
    current_ids = _get_path(current, TOOL_IDS_PATH) or []
    to_add = [tid for tid in required_ids if tid not in current_ids]
    if to_add:
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {"agent": {"prompt": {"tool_ids": required_ids}}}
            },
            merge_arrays=[TOOL_IDS_PATH],
            actor_id=actor_id,
            org_id=org_id,
            endpoint_label="provision_tools",
        )
    return to_add


def set_conversation_init_webhook(
    agent_id: str,
    *,
    actor_id: str | UUID | None = None,
    org_id: str | UUID | None = None,
) -> None:
    """Point the agent's conversation-init webhook at the env-routed URL and
    enable it (step B.4).

    ElevenLabs validates the full webhook object on PATCH — a partial
    ``{url: ...}`` resets siblings and trips "Field required" on
    request_headers — so we carry the existing ``request_headers`` (preserving
    the X-HeyKiki-Secret). Idempotent: no write when the URL already matches and
    the toggle is on. Goes through ``patch_agent_safely``.
    """
    current = get_agent_config(agent_id)
    cur_webhook = (
        _get_path(
            current,
            "platform_settings.workspace_overrides."
            "conversation_initiation_client_data_webhook",
        )
        or {}
    )
    cur_url = cur_webhook.get("url")
    cur_headers = cur_webhook.get("request_headers") or {}
    cur_enabled = bool(_get_path(current, WEBHOOK_ENABLED_PATH))
    needs_url = cur_url != _CONVERSATION_INIT_WEBHOOK_URL
    needs_toggle = not cur_enabled
    if needs_url or needs_toggle:
        webhook_patch: dict = {}
        if needs_url:
            webhook_patch.setdefault("workspace_overrides", {})[
                "conversation_initiation_client_data_webhook"
            ] = {"url": _CONVERSATION_INIT_WEBHOOK_URL, "request_headers": cur_headers}
        if needs_toggle:
            webhook_patch.setdefault("overrides", {})[
                "enable_conversation_initiation_client_data_from_webhook"
            ] = True
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={"platform_settings": webhook_patch},
            actor_id=actor_id,
            org_id=org_id,
            endpoint_label="provision_webhook",
        )


# ─── Public entry point ──────────────────────────────────────────────────────
def configure_agent(
    *,
    org_id: str | UUID,
    agent_id: str,
    org_name: str,
    actor_id: str | UUID | None = None,
) -> dict:
    """Wire up an ElevenLabs agent for HeyKiki use.

    Performs B.1 + B.2 + B.3 + B.4 + B.5 in order. Returns a summary dict::

        {
          "phone_number": "+49251...",
          "tools_attached": ["tool_xxx", ...],   # tool_ids newly added (may be [])
          "prompt_applied": True | False,        # False on re-runs
          "prompt_skipped_reason": "...",        # populated when False
          "webhook_enabled": True | False,       # True if our URL is set & toggle on
          "audio_ok": True,                      # always True post-call (else raise)
          "overrides_whitelist_enabled": True,   # Path A per-call override flags on
        }

    Raises:
      * HTTPException(400) on B.1 zero-phones or B.2 missing workspace tool —
        the caller is expected to roll back the org row insert.
      * ``elevenlabs_agent.ElevenLabsWriteError`` / ``SilentAgentRiskError`` /
        ``VerificationFailedError`` for ElevenLabs-side failures (these
        propagate; the snapshot/rollback inside ``patch_agent_safely`` already
        handled the EL side, the caller still needs to handle DB rollback).

    NOTE on the prompt step: SKIPPED when ``organizations.agent_provisioned_at``
    is already set (re-runs on existing orgs do not trample customer edits).
    Other steps are additive and safe to re-run.

    2.2 SEED-AT-PROVISION investigation (conservative — intentionally a no-op):
      (a) Post-call summaries: ``app.services.post_call`` reads
          ``analysis.transcript_summary`` + ``analysis.call_summary_title`` from
          the ElevenLabs post-call webhook payload. Those are ElevenLabs BUILT-IN
          analysis fields produced server-side for every conversation — they need
          NO per-agent analysis/eval config. Nothing to seed here.
      (b) Outbound occasion scripts/enablement: every occasion's spoken text is
          rendered in-backend per call (``outbound_occasions.build_call_content``)
          and shipped via the Path-A ``conversation_config_override`` — whose
          agent-side whitelist flags are already enabled in B.6 above. The org's
          outbound config row is created at provision (``agent_configs`` insert in
          ``provisioning.provision_org``) with the DB defaults
          (``outbound_enabled=false``, empty ``outbound_occasions``, sensible
          time/weekday windows). Outbound being OFF until the customer opts in is
          the intended default, not a gap — so no seeding is added.
    """
    summary: dict[str, Any] = {
        "phone_number": None,
        "phone_number_id": None,
        "phone_bound": False,
        "phone_message": None,
        "tools_attached": [],
        "prompt_applied": False,
        "prompt_skipped_reason": None,
        "webhook_enabled": False,
        "audio_ok": False,
        "overrides_whitelist_enabled": False,
        "system_tools_synced": False,
        "system_tools_reason": None,
    }
    is_first_run = not _is_agent_already_provisioned(org_id)

    # ─── B.1 Phone (number + the ElevenLabs phone_number_id for outbound) ────
    # 2.3 — GRACEFUL NO-PHONE: a missing phone must NOT abort the whole provision.
    # We record phone_bound=false + an actionable German message and continue with
    # B.2-B.6 (tools, prompt, webhook, audio, overrides) so the agent is otherwise
    # fully wired; verify_agent_health surfaces the missing phone as a red check.
    # The happy path (a phone IS bound) is unchanged.
    try:
        phone_meta = fetch_phone_meta_for_agent(agent_id)
        _store_phone_on_org(
            org_id, phone_meta["phone_number"], phone_meta.get("phone_number_id")
        )
        summary["phone_number"] = phone_meta["phone_number"]
        summary["phone_number_id"] = phone_meta.get("phone_number_id")
        summary["phone_bound"] = True
    except HTTPException:
        # fetch_phone_meta_for_agent raises HTTPException(400) only for the
        # zero-phones-bound case (an operator-actionable state). Any other
        # failure (EL HTTP error etc.) is an ElevenLabsWriteError and still
        # propagates. Degrade gracefully here instead of failing provision.
        summary["phone_bound"] = False
        summary["phone_message"] = NO_PHONE_MESSAGE
        logger.warning(
            "Agent %s (org %s) has no phone bound — provisioning the rest of "
            "the config and reporting phone_bound=false.",
            agent_id, org_id,
        )

    # ─── B.2 Tools (additive merge of tool_ids) ──────────────────────────────
    summary["tools_attached"] = attach_hk_tools(
        agent_id, actor_id=actor_id, org_id=org_id
    )

    # ─── B.3 Prompt (FIRST run only) ─────────────────────────────────────────
    if is_first_run:
        prompt_text = render_prompt_for_org(
            org_name, org=_fetch_org_identity(org_id), org_id=org_id
        )
        # Read current after the tool merge so we don't false-positive on a stale GET.
        current = get_agent_config(agent_id)
        existing_prompt = (_get_path(current, PROMPT_PATH) or "").strip()
        if existing_prompt == prompt_text.strip():
            summary["prompt_applied"] = False
            summary["prompt_skipped_reason"] = "identical_to_template"
        else:
            patch_agent_safely(
                agent_id=agent_id,
                field_patches={
                    "conversation_config": {"agent": {"prompt": {"prompt": prompt_text}}}
                },
                actor_id=actor_id,
                org_id=org_id,
                endpoint_label="provision_prompt",
            )
            summary["prompt_applied"] = True
    else:
        summary["prompt_applied"] = False
        summary["prompt_skipped_reason"] = "already_provisioned"

    # ─── B.4 Webhook (conversation initiation client data) ───────────────────
    set_conversation_init_webhook(agent_id, actor_id=actor_id, org_id=org_id)
    summary["webhook_enabled"] = True

    # ─── B.5 Audio in client_events ──────────────────────────────────────────
    current = get_agent_config(agent_id)
    ce = _get_path(current, CLIENT_EVENTS_PATH) or []
    if REQUIRED_AUDIO_EVENT not in ce:
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {
                    "conversation": {"client_events": [REQUIRED_AUDIO_EVENT]}
                }
            },
            merge_arrays=[CLIENT_EVENTS_PATH],
            actor_id=actor_id,
            org_id=org_id,
            endpoint_label="provision_audio",
        )
    summary["audio_ok"] = True

    # ─── B.6 Overrides whitelist (per-call conversation_config_override) ──────
    # Path A outbound ships the German prompt / first message / language as a
    # per-call override; ElevenLabs only honors it when the agent whitelists
    # those fields. Enabling the three flags here means a CRM-provisioned
    # (N8N-created) agent accepts the per-call override with ZERO manual
    # toggling. Set ONLY these booleans — never a prompt; the outbound prompt
    # text stays per-call (hard constraint). Additive + idempotent (the
    # required_override_flags verify confirms the flags actually took, else
    # patch_agent_safely rolls back).
    current = get_agent_config(agent_id)
    if not override_flags_ok(_get_path(current, OVERRIDES_WHITELIST_AGENT_PATH)):
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "platform_settings": {
                    "overrides": {
                        "conversation_config_override": {
                            "agent": {
                                "first_message": True,
                                "language": True,
                                "prompt": {"prompt": True},
                            }
                        }
                    }
                }
            },
            required_override_flags=True,
            actor_id=actor_id,
            org_id=org_id,
            endpoint_label="provision_overrides_whitelist",
        )
    summary["overrides_whitelist_enabled"] = True

    # ─── B.7 System tools (transfer_to_number / voicemail_detection /
    #         transfer_to_agent) ───────────────────────────────────────────────
    # Onboarding gap fix (2026-06-22): previously the native system tools were
    # attached ONLY on a later Notdienst/Telefon save (sync_system_tools_for_org
    # had a single caller in kiki_zentrale._repush_bg). A freshly-provisioned org
    # therefore had NO transfer_to_number/transfer_to_agent/voicemail_detection on
    # its agent until someone re-saved a Kiki-Zentrale screen — so the prompt could
    # already say "leite weiter" with no bridge behind it, and outbound→inbound
    # handoff (transfer_to_agent) was unavailable. Attaching them here means every
    # org that comes through provisioning has the full system-tool set from day one,
    # built from whatever Kiki-Zentrale defaults/numbers exist at provision time.
    # sync_system_tools_for_org is best-effort (never raises) and idempotent, so it
    # is safe to call on first run AND re-runs; it returns a categorized result.
    sys_tools_result = sync_system_tools_for_org(org_id)
    summary["system_tools_synced"] = bool(sys_tools_result.get("updated"))
    summary["system_tools_reason"] = sys_tools_result.get("reason")

    # ─── Stamp the org so re-runs skip the prompt step. ──────────────────────
    if is_first_run:
        _stamp_agent_provisioned(org_id)

    return summary


# ─── 2.1 + 2.4: post-provision verify gate / agent-health report ─────────────
def _check(name: str, ok: bool, detail: str) -> dict:
    """Shape one check row for the agent-health contract."""
    return {"name": name, "ok": bool(ok), "detail": detail}


def _fetch_provisioned_at(org_id: str | UUID) -> str | None:
    db = get_service_client()
    rows = (
        db.table("organizations")
        .select("agent_provisioned_at")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0].get("agent_provisioned_at") if rows else None


def verify_agent_health(org_id: str | UUID, agent_id: str) -> dict:
    """Read-only post-provision verify gate (2.1).

    Re-reads the LIVE ElevenLabs agent via the direct REST
    ``get_agent_config`` (never the MCP — the MCP omits tools / client_events)
    and asserts every check in the Batch-2 contract. NEVER writes to the agent.

    Returns::

        {
          "ok": bool,                      # AND of every check.ok
          "provisioned_at": str | None,    # organizations.agent_provisioned_at
          "checks": [{name, ok, detail}],  # the 7 contract checks, in order
        }

    Checks (names are the contract):
      * hk_tools_attached    — all 11 hk_* tool ids are on the agent
      * webhook_url_is_prod  — conversation-init webhook url == prod backend url
      * webhook_enabled      — the init-webhook toggle is on
      * audio_event_present  — 'audio' is in client_events (else the agent is silent)
      * prompt_rendered      — prompt non-empty AND no unsubstituted '{{' tokens
      * override_flags_on    — Path-A per-call override flags all true
      * phone_bound          — a phone number is bound to the agent

    If the agent is unreachable, returns ok=false with every check failed and
    the error in each detail (so a no-agent / unreachable org reads red, not 500).
    """
    provisioned_at = _fetch_provisioned_at(org_id)

    try:
        cfg = get_agent_config(agent_id)
    except Exception as exc:  # noqa: BLE001 — surface unreachable as red, not 500
        msg = f"Agent nicht erreichbar: {str(exc)[:200]}"
        names = [
            "hk_tools_attached", "webhook_url_is_prod", "webhook_enabled",
            "audio_event_present", "prompt_rendered", "override_flags_on",
            "phone_bound",
        ]
        return {
            "ok": False,
            "provisioned_at": provisioned_at,
            "checks": [_check(n, False, msg) for n in names],
        }

    checks: list[dict] = []

    # hk_tools_attached — all 11 required hk_* ids present on the agent.
    try:
        tool_map = _resolve_hk_tool_ids(HK_TOOL_NAMES)
        required_ids = set(tool_map.values())
        current_ids = set(_get_path(cfg, TOOL_IDS_PATH) or [])
        missing_ids = required_ids - current_ids
        # Map any missing id back to its tool name for an actionable detail.
        id_to_name = {tid: n for n, tid in tool_map.items()}
        missing_names = sorted(id_to_name.get(tid, tid) for tid in missing_ids)
        checks.append(_check(
            "hk_tools_attached",
            not missing_ids,
            "Alle 11 hk_*-Tools sind verknüpft."
            if not missing_ids
            else f"Fehlende Tools: {', '.join(missing_names)}",
        ))
    except HTTPException as exc:
        # Workspace is missing a required tool entirely (config decision upstream).
        checks.append(_check("hk_tools_attached", False, str(exc.detail)))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("hk_tools_attached", False, f"Tool-Prüfung fehlgeschlagen: {str(exc)[:150]}"))

    # webhook_url_is_prod — the conversation-init webhook points at the
    # env-routed URL (or a tolerated legacy backend host during migration).
    cur_url = _get_path(cfg, WEBHOOK_URL_PATH)
    url_ok = cur_url in _ACCEPTED_WEBHOOK_URLS
    checks.append(_check(
        "webhook_url_is_prod",
        url_ok,
        f"Webhook-URL: {cur_url or '—'}"
        if url_ok
        else f"Webhook-URL ist nicht env-geroutet/bekannt (ist: {cur_url or '—'}).",
    ))

    # webhook_enabled — the init-webhook toggle is on.
    enabled = bool(_get_path(cfg, WEBHOOK_ENABLED_PATH))
    checks.append(_check(
        "webhook_enabled",
        enabled,
        "Webhook ist aktiviert." if enabled else "Webhook ist deaktiviert.",
    ))

    # audio_event_present — 'audio' in client_events (else the agent goes silent).
    ce = _get_path(cfg, CLIENT_EVENTS_PATH) or []
    has_audio = REQUIRED_AUDIO_EVENT in ce
    checks.append(_check(
        "audio_event_present",
        has_audio,
        "'audio' ist in client_events."
        if has_audio
        else "'audio' fehlt in client_events — der Agent bliebe im Anruf stumm.",
    ))

    # prompt_rendered — non-empty AND no UNRENDERED CRM token. Our tokens are
    # UPPER_SNAKE ({{COMPANY_NAME}}, {{KZ_EMERGENCY}}, …) and must be substituted;
    # EL dynamic variables ({{system__time}}, {{customer_name}}, …) are lowercase
    # and legitimately REMAIN (EL fills them per call) — flagging any '{{' wrongly
    # red-flagged every agent on its {{system__*}} variables.
    prompt = (_get_path(cfg, PROMPT_PATH) or "").strip()
    leftover = sorted(set(_CRM_TOKEN_RE.findall(prompt)))
    prompt_ok = bool(prompt) and not leftover
    if not prompt:
        prompt_detail = "Prompt ist leer."
    elif leftover:
        prompt_detail = (
            "Prompt enthält nicht ersetzte Platzhalter: " + ", ".join(leftover)
        )
    else:
        prompt_detail = "Prompt ist gesetzt und vollständig ersetzt."
    checks.append(_check("prompt_rendered", prompt_ok, prompt_detail))

    # override_flags_on — Path-A per-call override flags all true.
    flags_ok = override_flags_ok(_get_path(cfg, OVERRIDES_WHITELIST_AGENT_PATH))
    checks.append(_check(
        "override_flags_on",
        flags_ok,
        "Path-A Override-Flags sind aktiv."
        if flags_ok
        else "Path-A Override-Flags (prompt/first_message/language) sind nicht alle aktiv.",
    ))

    # phone_bound — a phone number is bound to the agent in ElevenLabs.
    try:
        phone_meta = fetch_phone_meta_for_agent(agent_id)
        phone_no = phone_meta.get("phone_number")
        checks.append(_check(
            "phone_bound",
            bool(phone_no),
            f"Telefonnummer: {phone_no}" if phone_no else NO_PHONE_MESSAGE,
        ))
    except HTTPException:
        checks.append(_check("phone_bound", False, NO_PHONE_MESSAGE))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check(
            "phone_bound", False, f"Telefon-Prüfung fehlgeschlagen: {str(exc)[:150]}"
        ))

    return {
        "ok": all(c["ok"] for c in checks),
        "provisioned_at": provisioned_at,
        "checks": checks,
    }


# ─── Native transfer_to_number system tool sync ──────────────────────────────
def _dial_clean(number: str | None) -> str:
    """Normalize to E.164: strip formatting; German local numbers (leading 0)
    become +49…, 00-prefixed international becomes +… — Twilio rejects
    non-E.164 transfer targets, which would surface as an audible error."""
    n = re.sub(r"[^\d+]", "", number or "")
    if not n or n.startswith("+"):
        return n
    if n.startswith("00"):
        return "+" + n[2:]
    if n.startswith("0"):
        return "+49" + n[1:]
    return "+" + n


def build_transfer_tool(cfg: dict) -> dict | None:
    """The agent's ``built_in_tools.transfer_to_number`` object, derived from the
    Kiki-Zentrale numbers. None ⇒ the tool should be absent.

    Replaces the raw-Twilio-redirect webhook path (services/transfer.py) as the
    PRIMARY transfer mechanism: ElevenLabs executes the bridge natively on its
    own call leg, which is the supported way to hand off a live call (the TwiML
    redirect audibly errored for callers). The webhook tool stays attached as a
    diagnostic fallback but the prompt no longer references it."""
    transfers: list[dict] = []
    emergency = _dial_clean(cfg.get("emergency_number") or cfg.get("forwarding_number"))
    staff = _dial_clean(cfg.get("incoming_forwarding_number"))
    emergency_added = False
    if emergency and cfg.get("emergency_enabled"):
        transfers.append(
            {
                "transfer_destination": {"type": "phone", "phone_number": emergency},
                "condition": (
                    "NOTDIENST: Ein bestätigter NOTFALL laut Abschnitt "
                    "„Notfall-Definition“ liegt vor (Notfall-Stichwort bestätigt, "
                    "Notdienst-Zeitfenster aktiv). Sofort hierhin weiterleiten."
                ),
                "transfer_type": "conference",
            }
        )
        emergency_added = True
    # Dedupe ONLY against an emergency entry that was actually added: when the
    # Notdienst is disabled but staff == emergency number, the old `staff !=
    # emergency` check dropped the staff entry too → the tool vanished entirely
    # while the prompt still offered Mitarbeiter-transfers (audit 2026-06-11).
    if staff and (not emergency_added or staff != emergency):
        transfers.append(
            {
                "transfer_destination": {"type": "phone", "phone_number": staff},
                "condition": (
                    "MITARBEITER: Der Anrufer bittet ausdrücklich, sofort mit einem "
                    "Mitarbeiter/Menschen verbunden zu werden, und es ist innerhalb "
                    "der Geschäftszeiten (KEIN Notfall)."
                ),
                "transfer_type": "conference",
            }
        )
    if not transfers:
        return None
    return {
        "type": "system",
        "name": "transfer_to_number",
        "description": (
            "Verbindet den Anrufer live mit einer hinterlegten Nummer (Notdienst "
            "bzw. Mitarbeiter) gemäß den Weiterleitungs-Bedingungen. Sage dem "
            "Anrufer VOR dem Aufruf kurz, dass du verbindest. Nur gemäß den im "
            "Prompt definierten Regeln verwenden."
        ),
        "params": {
            "system_tool_type": "transfer_to_number",
            "transfers": transfers,
        },
    }


def build_voicemail_tool() -> dict:
    """Hardened voicemail_detection config: the loose default description made the
    LLM fire it on live humans right after connect — the caller then heard the
    voicemail text ('…ist bestätigt … Auf Wiederhören!') and the call ended
    (the reported outbound 'announces and hangs up' bug)."""
    return {
        "type": "system",
        "name": "voicemail_detection",
        "description": (
            "Trigger ONLY when you are CERTAIN an answering machine/voicemail "
            "picked up: a RECORDED greeting explicitly states the called party is "
            "unavailable ('Please leave a message after the tone…', 'You have "
            "reached the voicemail of…', 'Der Teilnehmer ist zurzeit nicht "
            "erreichbar…'), typically followed by a beep. NEVER trigger in the "
            "first seconds of a call, on silence, on background noise, or after a "
            "live human has said ANYTHING — a plain 'Hallo?', 'Ja?' or a company "
            "name IS a human. When in ANY doubt, treat the answerer as human and "
            "simply continue the conversation. The tool plays the stored "
            "voicemail_message in full and then ends the call."
        ),
        "params": {
            "system_tool_type": "voicemail_detection",
            "voicemail_message": "{{voicemailMessage}}",
        },
    }


def build_transfer_to_agent_tool(agent_id: str) -> dict:
    """transfer_to_agent (off-topic handoff during OUTBOUND calls). Target is the
    org's own agent: the new leg starts WITHOUT the per-call outbound override,
    i.e. with the standard inbound configuration and full tool access."""
    return {
        "type": "system",
        "name": "transfer_to_agent",
        "description": (
            "Hands the conversation over to this organization's standard inbound "
            "assistant (fresh configuration, full tools). Use EXCLUSIVELY during "
            "OUTBOUND calls when the customer raises an issue UNRELATED to this "
            "call's stated purpose that you cannot complete with your current "
            "tools. NEVER invoke during inbound calls — there you already are the "
            "primary agent. Announce the handoff briefly before transferring."
        ),
        "params": {
            "system_tool_type": "transfer_to_agent",
            "transfers": [
                {
                    "agent_id": agent_id,
                    "condition": (
                        "Only during an outbound call: the customer raises a "
                        "DIFFERENT concern than the announced purpose of this call "
                        "(new repair request, complaint, separate inquiry, new "
                        "appointment on another topic, cost estimate) AND it cannot "
                        "be completed with the currently available tools."
                    ),
                }
            ],
        },
    }


def sync_system_tools_for_org(org_id: str | UUID) -> dict:
    """Push the org's system-tool configs (transfer_to_number, voicemail_detection,
    transfer_to_agent) to its agent in one safe write.

    Called after Notdienst-/Telefon-saves (alongside the prompt repush). NEVER
    raises (best-effort contract). Returns a CATEGORIZED reason on failure so the
    caller can tell a real divergence from a benign no-op (1.4):

        {"updated": True}
        {"updated": False, "reason": "no_agent"}
        {"updated": False, "reason": "verify_failed:<detail>"}   # auto-rolled-back
        {"updated": False, "reason": "el_error:<detail>"}        # EL/transport error

    A single bounded retry is attempted ONLY on a transient transport error
    (httpx network/timeout) — NEVER on a VerificationFailedError, which already
    auto-rolled-back inside patch_agent_safely (retrying would just snapshot +
    fail again)."""
    db = get_service_client()
    org_rows = (
        db.table("organizations").select("elevenlabs_agent_id")
        .eq("id", str(org_id)).limit(1).execute().data or []
    )
    agent_id = (org_rows[0] if org_rows else {}).get("elevenlabs_agent_id")
    if not agent_id:
        return {"updated": False, "reason": "no_agent"}
    cfg = _fetch_kz_config(org_id)

    def _do_write() -> None:
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {
                    "agent": {
                        "prompt": {
                            "built_in_tools": {
                                "transfer_to_number": build_transfer_tool(cfg),
                                "voicemail_detection": build_voicemail_tool(),
                                "transfer_to_agent": build_transfer_to_agent_tool(agent_id),
                            }
                        }
                    }
                }
            },
            merge_arrays=[],
            actor_id=None,
            org_id=org_id,
            endpoint_label="system_tools_sync",
        )

    attempted_retry = False
    while True:
        try:
            _do_write()
            return {"updated": True}
        except VerificationFailedError as exc:
            # Already auto-rolled-back — categorize, never retry.
            logger.warning(
                "system tools sync verify failed (org %s): %s", org_id, str(exc)[:200]
            )
            return {"updated": False, "reason": f"verify_failed:{str(exc)[:180]}"}
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            # Transient transport blip — one bounded retry, then give up.
            if not attempted_retry:
                attempted_retry = True
                logger.warning(
                    "system tools sync transient error (org %s), retrying once: %s",
                    org_id, str(exc)[:200],
                )
                continue
            logger.warning(
                "system tools sync el_error after retry (org %s): %s",
                org_id, str(exc)[:200],
            )
            return {"updated": False, "reason": f"el_error:{str(exc)[:180]}"}
        except Exception as exc:  # noqa: BLE001 — never break the triggering save
            logger.warning(
                "system tools sync failed (org %s): %s", org_id, str(exc)[:200]
            )
            return {"updated": False, "reason": f"el_error:{str(exc)[:180]}"}


# Backwards-compatible alias (Phase-6 call sites).
sync_transfer_tool_for_org = sync_system_tools_for_org


# ─── hk_ tool_ids reconcile (1.5 — HIGH RISK, super-admin only) ───────────────
def reconcile_hk_tool_ids(
    org_id: str | UUID, agent_id: str, actor_id: str | UUID | None = None
) -> dict:
    """Reconcile the agent's ``prompt.tool_ids`` to the exact desired hk_* set.

    HIGH RISK — a bad write here could strip every tool off a live agent, so the
    guards are deliberately strict:

      1. Resolve ALL desired hk_* ids first. If ANY fails to resolve (a workspace
         blip / a tool renamed mid-flight), ABORT with reason 'resolve_failed'
         and write NOTHING — a transient lookup miss must never cause mass tool
         removal.
      2. GET the agent's current tool_ids.
      3. Compute the desired set = (all current ids that are NOT one of our hk_*
         ids) + (the 11 resolved desired ids). This PRESERVES every unknown /
         custom tool_id the org may have added, and only ever removes a STALE
         hk_* id (an old/duplicate hk_ binding no longer in the desired set).
      4. Write the explicit set via patch_agent_safely with merge_arrays=[] (an
         EXPLICIT replacement of tool_ids, NOT a union — that's the whole point of
         a reconcile). The audio assertion + verify + auto-rollback still apply.

    ``built_in_tools`` (transfer_to_number / voicemail / transfer_to_agent) live
    under a DIFFERENT path (prompt.built_in_tools), so the patch body carries ONLY
    tool_ids and cannot touch them.

    Returns ``{"removed": [...], "kept": [...], "desired": [...]}`` (the SHARED
    contract for POST /reconcile-tools). On a resolve abort returns
    ``{"removed": [], "kept": [], "desired": [], "reason": "resolve_failed:..."}``
    and writes nothing. NEVER auto-called on routine saves."""
    # 1) Resolve ALL desired ids up front; abort hard if any are missing.
    try:
        tool_map = _resolve_hk_tool_ids(HK_TOOL_NAMES)
    except HTTPException as exc:
        logger.warning(
            "reconcile_hk_tool_ids abort (org %s): resolve failed: %s",
            org_id, str(exc.detail)[:200],
        )
        return {
            "removed": [], "kept": [], "desired": [],
            "reason": f"resolve_failed:{str(exc.detail)[:180]}",
        }
    desired_hk_ids = list(tool_map.values())
    desired_hk_set = set(desired_hk_ids)
    # Every hk_* id we KNOW about (the resolved set IS the desired set; there are
    # no extra hk_ ids to recognise beyond what the workspace currently resolves).
    known_hk_set = set(desired_hk_ids)

    # 2) Current tool_ids on the agent.
    current = get_agent_config(agent_id)
    current_ids = list(_get_path(current, TOOL_IDS_PATH) or [])

    # 3) Build the explicit desired set: preserve all non-hk_ (unknown/custom)
    # ids, drop stale hk_ ids, ensure all 11 desired ids are present.
    preserved = [tid for tid in current_ids if tid not in known_hk_set]
    desired_set = preserved + [tid for tid in desired_hk_ids if tid not in preserved]
    removed = [
        tid for tid in current_ids
        if tid in known_hk_set and tid not in desired_set
    ]
    # Defensive invariant: we must never drop a non-hk_ (custom) id.
    assert all(tid in desired_set for tid in preserved), (
        "reconcile would drop a non-hk_ tool_id — refusing"
    )

    if set(current_ids) == set(desired_set):
        # Already reconciled — no write (patch_agent_safely would no-op anyway).
        return {"removed": [], "kept": current_ids, "desired": desired_set}

    # 4) Explicit replacement (merge_arrays=[] → NOT a union). Audio assertion +
    # verify + auto-rollback inside patch_agent_safely are the safety net.
    patch_agent_safely(
        agent_id=agent_id,
        field_patches={
            "conversation_config": {"agent": {"prompt": {"tool_ids": desired_set}}}
        },
        merge_arrays=[],
        actor_id=actor_id,
        org_id=org_id,
        endpoint_label="reconcile_tools",
    )
    return {"removed": removed, "kept": desired_set, "desired": desired_set}


# ─── Agent-sync status (frontend loader banner) ──────────────────────────────
# Every Kiki-Zentrale save flips the org's agent_configs row to 'pending' BEFORE
# the HTTP response returns, and the background re-push resolves it to
# 'applied'/'failed'. agent_sync_seq is a per-org request id: finish_sync only
# writes when its seq is still the latest, so overlapping saves are
# last-write-wins and a slow old push can never overwrite a newer pending state.

def begin_sync(org_id: str | UUID, label: str) -> int:
    """Mark the org's agent sync as pending; returns the new sync seq.

    Upserts the config row first so orgs that never saved a config still get
    sync tracking. Never raises — a tracking failure must not block the save."""
    db = get_service_client()
    try:
        existing = (
            db.table("agent_configs").select("org_id").eq("org_id", str(org_id))
            .limit(1).execute().data or []
        )
        if not existing:
            db.table("agent_configs").upsert(
                {"org_id": str(org_id)}, on_conflict="org_id"
            ).execute()
        res = db.rpc(
            "kz_begin_agent_sync", {"p_org": str(org_id), "p_label": label}
        ).execute()
        data = res.data
        if isinstance(data, list):
            data = data[0] if data else 0
        return int(data or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("begin_sync(%s, %s) failed: %s", org_id, label, str(exc)[:200])
        return 0


def finish_sync(org_id: str | UUID, seq: int, *, ok: bool, reason: str | None = None) -> None:
    """Resolve a pending sync — guarded by seq (stale completions no-op)."""
    if not seq:
        return
    db = get_service_client()
    try:
        (
            db.table("agent_configs")
            .update({
                "agent_sync_status": "applied" if ok else "failed",
                "agent_sync_error": (reason or None) if not ok else (reason or None),
                "agent_sync_finished_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("org_id", str(org_id))
            .eq("agent_sync_seq", seq)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("finish_sync(%s, seq=%s) failed: %s", org_id, seq, str(exc)[:200])


# ─── Live re-render + push (Kiki-Zentrale config changes) ────────────────────
# Per-org serialization for the render→PATCH window. Two overlapping saves used
# to push independently; with this lock + the supersede check below, a slower
# stale push can no longer land its OLD prompt after a newer one (audit
# 2026-06-11). Process-local — fine for the single Railway backend process.
_REPUSH_LOCKS: dict = defaultdict(threading.Lock)


def _current_sync_seq(db, org_id: str | UUID) -> int:
    """The org's latest agent_sync_seq (the request id begin_sync stamped). A
    repush whose own seq is below this has been superseded by a newer save."""
    try:
        rows = (
            db.table("agent_configs").select("agent_sync_seq")
            .eq("org_id", str(org_id)).limit(1).execute().data or []
        )
        return int((rows[0] if rows else {}).get("agent_sync_seq") or 0)
    except Exception:  # noqa: BLE001
        return 0


def _stamp_config_dirty_since(db, org_id: str | UUID) -> None:
    """1.3: stamp config_dirty_since=now() the FIRST time a re-render no-ops on the
    manual-override gate (only when currently NULL, so the oldest un-pushed change
    wins). Best-effort — a tracking write must never break the gate's no-op."""
    try:
        rows = (
            db.table("agent_configs").select("config_dirty_since")
            .eq("org_id", str(org_id)).limit(1).execute().data or []
        )
        if rows and rows[0].get("config_dirty_since"):
            return  # already dirty — keep the oldest timestamp
        db.table("agent_configs").update(
            {"config_dirty_since": datetime.now(timezone.utc).isoformat()}
        ).eq("org_id", str(org_id)).is_("config_dirty_since", "null").execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("stamp config_dirty_since(%s) failed: %s", org_id, str(exc)[:200])


def _clear_config_dirty_since(db, org_id: str | UUID, seq: int | None = None) -> None:
    """1.3: on a SUCCESSFUL push, clear config_dirty_since and record last_repush_at
    (+ last_repush_seq when available). Best-effort."""
    try:
        patch: dict = {
            "config_dirty_since": None,
            "last_repush_at": datetime.now(timezone.utc).isoformat(),
        }
        if seq:
            patch["last_repush_seq"] = int(seq)
        db.table("agent_configs").update(patch).eq("org_id", str(org_id)).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("clear config_dirty_since(%s) failed: %s", org_id, str(exc)[:200])


def compute_drift(org_id: str | UUID) -> dict:
    """1.3 detector. Returns the drift state for GET /drift:

        {drift, dirty_since, manual_override, last_repush_at}

    ``drift`` is True iff the agent prompt is known to be out of step with the
    saved config — i.e. config_dirty_since is set (a config change couldn't be
    pushed because the org sits behind a manual prompt override)."""
    db = get_service_client()
    rows = (
        db.table("agent_configs")
        .select("prompt_manual_override, config_dirty_since, last_repush_at")
        .eq("org_id", str(org_id)).limit(1).execute().data or []
    )
    row = rows[0] if rows else {}
    dirty_since = row.get("config_dirty_since")
    return {
        "drift": bool(dirty_since),
        "dirty_since": dirty_since,
        "manual_override": bool(row.get("prompt_manual_override")),
        "last_repush_at": row.get("last_repush_at"),
    }


def rerender_and_push_for_org(
    *, org_id: str | UUID, actor_id: str | UUID | None = None, endpoint_label: str,
    expected_seq: int | None = None, force: bool = False,
) -> dict:
    """Re-render the org's prompt from the live template + config and push it to
    the agent. Best-effort: NEVER raises to the caller.

    - If ``agent_configs.prompt_manual_override`` is True (and ``force`` is False)
      → no-op ``{"updated": False, "reason": "manual_override"}`` (the tradesperson
      edited the prompt by hand; auto-regeneration would clobber it). The first
      such no-op stamps ``config_dirty_since`` (drift detection, 1.3).
    - If ``force`` is True → bypass the manual-override gate for THIS single call
      (still snapshot/verify/audit via the normal patch_agent_safely path). Used
      by POST /drift/force-resync.
    - If the org has no ``elevenlabs_agent_id`` →
      ``{"updated": False, "reason": "no_agent"}``.
    - If ``expected_seq`` is given and a NEWER save has since begun →
      ``{"updated": False, "reason": "superseded"}`` (the newer push owns the
      latest state; pushing our stale render would clobber it).
    - On an ElevenLabs write error → ``{"updated": False, "reason": str(e)}``.
    - On success → ``{"updated": True}`` (and config_dirty_since is cleared,
      last_repush_at stamped).

    The actual write routes through ``patch_agent_safely`` (snapshot → assert
    audio → PATCH → verify → auto-rollback → audit), so the per-call safety net is
    identical to provisioning. When ``expected_seq`` is provided, the whole
    render→PATCH section is serialized per org and re-checks the seq under the
    lock, so overlapping saves apply strictly last-write-wins on the AGENT too,
    not just on the status banner.
    """
    db = get_service_client()

    # Manual-override gate: read the flag straight off the config row. ``force``
    # bypasses the gate for this single call (1.3 force-resync).
    cfg_rows = (
        db.table("agent_configs")
        .select("prompt_manual_override")
        .eq("org_id", str(org_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    if not force and cfg_rows and cfg_rows[0].get("prompt_manual_override"):
        # Drift: a config change just couldn't be pushed. Stamp the dirty marker
        # (oldest-un-pushed-change-wins) so GET /drift can surface it.
        _stamp_config_dirty_since(db, org_id)
        return {"updated": False, "reason": "manual_override"}

    # Resolve the agent id (do NOT use get_org_agent_id — it raises; we want a
    # soft no-op for un-provisioned orgs).
    org_rows = (
        db.table("organizations")
        .select("name, elevenlabs_agent_id")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    org = org_rows[0] if org_rows else {}
    agent_id = org.get("elevenlabs_agent_id")
    if not agent_id:
        return {"updated": False, "reason": "no_agent"}

    lock = _REPUSH_LOCKS[str(org_id)] if expected_seq is not None else None
    if lock is not None:
        lock.acquire()
    try:
        # Supersede check (under the lock so the winner is deterministic): a save
        # that began after ours already holds the latest config — let IT push.
        if expected_seq is not None and _current_sync_seq(db, org_id) > expected_seq:
            return {"updated": False, "reason": "superseded"}

        identity = _fetch_org_identity(org_id)
        prompt_text = render_prompt_for_org(
            org.get("name") or identity.get("name") or "",
            org=identity,
            org_id=org_id,
        )
        logger.info(
            "prompt_size org=%s label=%s chars=%d tokens_est=%d",
            org_id, endpoint_label, len(prompt_text), len(prompt_text) // 4,
        )
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {"agent": {"prompt": {"prompt": prompt_text}}}
            },
            merge_arrays=[],
            actor_id=actor_id,
            org_id=org_id,
            endpoint_label=endpoint_label,
        )
    except ElevenLabsWriteError as exc:
        return {"updated": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        # Best-effort contract: a verify/cross-org/silent-agent failure (or any
        # other ElevenLabs-side error) must not break the config save that
        # triggered the re-push. patch_agent_safely already rolled back the EL
        # side on a verify failure; the audit row carries the detail.
        logger.warning(
            "rerender_and_push_for_org(%s, %s) failed: %s",
            org_id, endpoint_label, str(exc)[:200],
        )
        return {"updated": False, "reason": str(exc)}
    finally:
        if lock is not None:
            lock.release()
    # Successful push: the agent now reflects the saved config — clear the drift
    # marker and record the push time (1.3).
    _clear_config_dirty_since(db, org_id, expected_seq)
    return {"updated": True}
