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
import time
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
from app.services.elevenlabs_agent import (
    CLIENT_EVENTS_PATH,
    OVERRIDES_WHITELIST_AGENT_PATH,
    PROMPT_PATH,
    REQUIRED_AUDIO_EVENT,
    TOOL_IDS_PATH,
    WEBHOOK_ENABLED_PATH,
    WEBHOOK_URL_PATH,
    ElevenLabsWriteError,
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
# "/api/elevenlabs", path "/conversation-init"). Built at runtime from
# ``settings.backend_public_url`` so it follows local vs. prod automatically.
_CONVERSATION_INIT_PATH = "/api/elevenlabs/conversation-init"

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
    """Return ``{"phone_number", "phone_number_id"}`` for the Twilio number
    bound to ``agent_id`` in ElevenLabs.

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
        .select("field_key, label, description, is_duty, identification_role, sort_order")
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
            "emergency_surcharge_text, incoming_forwarding_number, price_info_enabled"
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
def render_required_fields_block(fields: list[dict]) -> str:
    """Pflicht/optional field list for the ``## Pflichtfelder`` body.

    Each field → ``- **{label}**{' (optional)'} — {description}``. Fields with an
    identification_role are noted as auto-recognised. Empty config → a sensible
    default field set so the agent never loses its data-capture instruction."""
    if not fields:
        return (
            "PFLICHTFELDER: Name, Telefonnummer, Adresse, Anliegen. "
            "OPTIONALE FELDER: Kundennummer."
        )
    lines = []
    for f in fields:
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
        "Erfasse die folgenden Felder in DIESER Reihenfolge (oberstes Feld = höchste "
        "Priorität, zuerst). Felder, die bereits bekannt sind oder automatisch erkannt "
        "wurden (z. B. die Telefonnummer über die Anrufererkennung bzw. "
        "hk_identifyCustomer), NICHT erneut erfragen — höchstens kurz bestätigen:"
    )
    return lead + "\n" + "\n".join(lines)


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
        kws = list(_DEFAULT_EMERGENCY_KEYWORDS)

    lines = ["  Ein NOTFALL liegt nur bei einem dieser Fälle vor:"]
    lines += [f"  - {k}" for k in kws]
    lines.append(
        "  Tropfender Wasserhahn, gelegentliches Gluckern, geplante Wartung oder "
        "Beratung"
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
            "INNERHALB der Geschäftszeiten (z. B. Gasgeruch, Rohrbruch). Ein per "
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
        "  Sag dem Anrufer bei bestätigtem Notfall ZUERST kurz, dass du ihn jetzt mit "
        "dem Notdienst verbindest, und rufe DANN `hk_transferCall` mit `emergency=true` "
        "auf — die Weiterleitung erfolgt sofort, sprich danach nicht weiter."
    )
    return "\n".join(lines)


def render_staff_transfer_block(cfg: dict) -> str:
    """Explicit "connect me to a person" handling for the ``{{KZ_STAFF_TRANSFER}}``
    token. Live staff transfer is only offered when an ``incoming_forwarding_number``
    is configured AND it is inside business hours; otherwise the agent takes a
    callback note (the existing default). This is distinct from the Notdienst path
    (emergency=true) — here ``hk_transferCall`` is called with ``emergency=false``."""
    number_set = bool((cfg.get("incoming_forwarding_number") or "").strip())
    if not number_set:
        return (
            "  Es ist KEINE Mitarbeiter-Weiterleitung hinterlegt. Bei der Bitte, mit "
            "einer Person zu sprechen, nimm eine Rückrufnotiz auf (kein Live-Transfer)."
        )
    return (
        "  Wenn der Anrufer AUSDRÜCKLICH darum bittet, sofort mit einem Mitarbeiter/"
        "einer Person verbunden zu werden, UND es INNERHALB der Geschäftszeiten ist:\n"
        "  - Sage kurz, dass du verbindest, und rufe `hk_transferCall` mit "
        "`emergency=false` auf. Die Mitarbeiter-Nummer ist im Backend hinterlegt — du "
        "musst sie weder kennen noch ansagen.\n"
        "  - Außerhalb der Geschäftszeiten ODER wenn keine sofortige Verbindung "
        "gewünscht ist (reine Rückrufbitte): nimm stattdessen eine Notiz mit "
        "`hk_createInquiry` (`rueckrufGewuenscht=true`) auf — nicht weiterleiten."
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
        "BUSINESS_HOURS": _render_business_hours(kz_cfg.get("scheduling")),
        "KZ_REQUIRED_FIELDS": render_required_fields_block(required_fields),
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
        "KZ_SCHEDULING_RULES": render_scheduling_rules_block(kz_cfg),
        "KZ_EMERGENCY": render_emergency_block(kz_cfg),
        "KZ_STAFF_TRANSFER": render_staff_transfer_block(kz_cfg),
        "KZ_AUTONOMY": render_autonomy_block(kz_cfg),
        "KZ_PRICE_INFO": render_price_info_block(kz_cfg),
    }
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
    """
    summary: dict[str, Any] = {
        "phone_number": None,
        "phone_number_id": None,
        "tools_attached": [],
        "prompt_applied": False,
        "prompt_skipped_reason": None,
        "webhook_enabled": False,
        "audio_ok": False,
        "overrides_whitelist_enabled": False,
    }
    is_first_run = not _is_agent_already_provisioned(org_id)

    # ─── B.1 Phone (number + the ElevenLabs phone_number_id for outbound) ────
    phone_meta = fetch_phone_meta_for_agent(agent_id)
    _store_phone_on_org(
        org_id, phone_meta["phone_number"], phone_meta.get("phone_number_id")
    )
    summary["phone_number"] = phone_meta["phone_number"]
    summary["phone_number_id"] = phone_meta.get("phone_number_id")

    # ─── B.2 Tools (additive merge of tool_ids) ──────────────────────────────
    tool_map = _resolve_hk_tool_ids(HK_TOOL_NAMES)
    required_ids = list(tool_map.values())
    current = get_agent_config(agent_id)
    current_ids = _get_path(current, TOOL_IDS_PATH) or []
    to_add = [tid for tid in required_ids if tid not in current_ids]
    if to_add:
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {
                    "agent": {"prompt": {"tool_ids": required_ids}}
                }
            },
            merge_arrays=[TOOL_IDS_PATH],
            actor_id=actor_id,
            org_id=org_id,
            endpoint_label="provision_tools",
        )
    summary["tools_attached"] = to_add

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
    # ElevenLabs validates the full webhook object on PATCH — sending a
    # partial {url: ...} resets siblings and trips "Field required" on
    # request_headers. So we always carry the existing request_headers in
    # the patch body to preserve them. Empty {} is a valid default.
    webhook_url = f"{settings.backend_public_url.rstrip('/')}{_CONVERSATION_INIT_PATH}"
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
    needs_url = cur_url != webhook_url
    needs_toggle = not cur_enabled
    if needs_url or needs_toggle:
        webhook_patch: dict = {}
        if needs_url:
            # Carry existing request_headers so EL doesn't reject the PATCH
            # for "Field required: request_headers". Preserves the
            # X-HeyKiki-Secret value already wired on the agent.
            webhook_patch.setdefault("workspace_overrides", {})[
                "conversation_initiation_client_data_webhook"
            ] = {"url": webhook_url, "request_headers": cur_headers}
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

    # ─── Stamp the org so re-runs skip the prompt step. ──────────────────────
    if is_first_run:
        _stamp_agent_provisioned(org_id)

    return summary


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
def rerender_and_push_for_org(
    *, org_id: str | UUID, actor_id: str | UUID | None = None, endpoint_label: str
) -> dict:
    """Re-render the org's prompt from the live template + config and push it to
    the agent. Best-effort: NEVER raises to the caller.

    - If ``agent_configs.prompt_manual_override`` is True → no-op
      ``{"updated": False, "reason": "manual_override"}`` (the tradesperson edited
      the prompt by hand; auto-regeneration would clobber it).
    - If the org has no ``elevenlabs_agent_id`` →
      ``{"updated": False, "reason": "no_agent"}``.
    - On an ElevenLabs write error → ``{"updated": False, "reason": str(e)}``.
    - On success → ``{"updated": True}``.

    The actual write routes through ``patch_agent_safely`` (snapshot → assert
    audio → PATCH → verify → auto-rollback → audit), so the per-call safety net is
    identical to provisioning.
    """
    db = get_service_client()

    # Manual-override gate: read the flag straight off the config row.
    cfg_rows = (
        db.table("agent_configs")
        .select("prompt_manual_override")
        .eq("org_id", str(org_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    if cfg_rows and cfg_rows[0].get("prompt_manual_override"):
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

    try:
        identity = _fetch_org_identity(org_id)
        prompt_text = render_prompt_for_org(
            org.get("name") or identity.get("name") or "",
            org=identity,
            org_id=org_id,
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
    return {"updated": True}
