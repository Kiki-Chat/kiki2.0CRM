"""Copilot tool registry — CRM operations the model may call.

Every tool wraps EXISTING service/route logic (org-scoped), never raw SQL beyond
small read-only lookups. Each tool carries metadata used by the orchestrator:
  - kind: read | write | sensitive | dangerous  (write/sensitive/dangerous ⇒ confirm)
  - roles: which user roles may use it (same tiers as the REST guards)

Phase 0/1 starter set: a few read tools + navigation + one confirmed-write
(create_customer). The set expands in later increments; the framework is final.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.api.deps import CurrentUser
from app.db.supabase_client import get_service_client

ROLES_ALL = ("employee", "org_admin", "super_admin")
ROLES_ADMIN = ("org_admin", "super_admin")

# Whitelisted in-app navigation targets (mirrors frontend/src/App.tsx routes).
KNOWN_ROUTES = (
    "/", "/calls", "/customers", "/calendar", "/meine-abwesenheit",
    "/projects", "/planning-board", "/cost-estimates", "/invoices",
    "/catalog", "/employees", "/settings", "/kiki-zentrale",
)

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]            # JSON Schema for the args
    run: Callable[[CurrentUser, dict], Any]
    kind: str = "read"                    # read | write | sensitive | dangerous
    roles: tuple[str, ...] = ROLES_ALL
    client_side: bool = False             # executed by the frontend (e.g. navigation)

    @property
    def needs_confirm(self) -> bool:
        return self.kind in ("write", "sensitive", "dangerous")

    def allowed_for(self, role: str | None) -> bool:
        return (role or "") in self.roles

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ─── helpers ─────────────────────────────────────────────────────────────────
def _sanitize_search(q: str) -> str:
    """Strip PostgREST/ilike filter metacharacters so a tool arg (which may carry
    injected text) can't break out of the or-filter. Keeps it a plain search term."""
    return re.sub(r"[,()%*\\]", " ", (q or "").strip()[:60]).strip()


# ─── read tools ──────────────────────────────────────────────────────────────
def _search_customers(user: CurrentUser, args: dict) -> dict:
    q = _sanitize_search(args.get("query", ""))
    client = get_service_client()
    sel = "id, full_name, phone, email, customer_number"
    query = client.table("customers").select(sel).eq("org_id", user.org_id)
    if q:
        query = query.or_(
            f"full_name.ilike.%{q}%,phone.ilike.%{q}%,email.ilike.%{q}%,customer_number.ilike.%{q}%"
        )
    rows = query.limit(10).execute().data or []
    return {"customers": rows, "count": len(rows)}


def _get_customer(user: CurrentUser, args: dict) -> dict:
    cid = (args.get("customer_id") or "").strip()
    if not _UUID_RE.match(cid):
        return {"error": "Ungültige Kunden-ID."}
    rows = (
        get_service_client()
        .table("customers")
        .select("id, full_name, phone, email, address, customer_number, created_at")
        .eq("org_id", user.org_id)
        .eq("id", cid)
        .limit(1)
        .execute()
        .data
        or []
    )
    return {"customer": rows[0]} if rows else {"error": "Kunde nicht gefunden."}


def _list_pending_actions(user: CurrentUser, args: dict) -> dict:
    from app.api.routes import actions  # lazy — avoids service→route import at load

    items = actions._aggregate(user.org_id)
    return {"actions": items, "count": len(items)}


def _get_finance_summary(user: CurrentUser, args: dict) -> dict:
    from app.api.routes import dashboard  # lazy

    return dashboard._finanzen(user.org_id)


def _navigate_to(user: CurrentUser, args: dict) -> dict:
    route = (args.get("route") or "").strip()
    if route not in KNOWN_ROUTES:
        return {"error": "Unbekannte Seite.", "allowed": list(KNOWN_ROUTES)}
    return {"navigate": route}


# ─── confirmed-write tools (proposed by the model, executed only on /confirm) ─
def _create_customer(user: CurrentUser, args: dict) -> dict:
    from app.services.customers import get_or_create_customer

    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "Name ist erforderlich."}
    customer = get_or_create_customer(
        user.org_id,
        name=name,
        phone=args.get("phone"),
        email=args.get("email"),
        address=args.get("address"),
    )
    return {"customer": customer}


# ─── Phase 2/3/4 tools (writes, settings, escalation) ────────────────────────
ESCALATION_EMAIL = "info.kikichat@gmail.com"
_INQUIRY_STATUS = ("open", "in_progress", "completed")
_ORG_PROFILE_FIELDS = ("name", "trade", "phone_number", "fax", "email", "website", "chamber_of_crafts")

# key -> (German trigger terms, explanation). Powers explain_setting.
_SETTINGS_DICT: dict[str, tuple[tuple[str, ...], str]] = {
    "autonomy": (("autonom", "kiki-stufe", "stufe", "eigenständig", "kiki level"),
        "Die Kiki-Stufe (kiki_level) steuert, wie eigenständig die Telefon-KI handelt: Stufe 1 = nimmt nur das Anliegen auf, Stufe 2 = bucht Termine vorläufig (du bestätigst), Stufe 3 = bucht & bestätigt selbst. Unter Kiki-Zentrale → Verhalten."),
    "ai_suggestions": (("vorschläge", "vorschlag", "erinnerung", "nachfassen"),
        "KI-Vorschläge erinnern dich automatisch (KVA nachfassen, offene Rechnungen, Wartung). Die Schwellen in Tagen stellst du unter Einstellungen → KI-Vorschläge ein."),
    "emergency": (("notdienst", "notfall", "dringend"),
        "Der Notdienst leitet dringende Anrufe außerhalb der Geschäftszeiten an eine Notfallnummer weiter (erkannt über Stichwörter). Unter Kiki-Zentrale → Notdienst."),
    "business_hours": (("geschäftszeiten", "öffnungszeiten", "arbeitszeit"),
        "Die Geschäftszeiten bestimmen, wann Termine vergeben werden und wann der Notdienst greift. Unter Kalender → Geschäftszeiten."),
    "outbound": (("ausgehend", "rückruf", "automatisch anrufen"),
        "Ausgehende Anrufe/E-Mails (Terminerinnerung, KVA-Nachfassen) sendet Kiki automatisch zu bestimmten Anlässen. Unter Kiki-Zentrale → Ausgehende Anrufe."),
    "kva_automation": (("kva", "kostenvoranschlag", "automatisierung"),
        "Bei aktiver KVA-Automatisierung erstellt Kiki nach passenden Anrufen automatisch einen KVA-Entwurf (Stufe 3 versendet ihn). Unter Kiki-Zentrale."),
    "email": (("e-mail", "email", "smtp", "versand"),
        "Die E-Mail-Konfiguration legt fest, über welches Konto Rechnungen/KVAs versendet werden (eigenes SMTP oder verbundenes Google/Outlook). Unter Einstellungen → E-Mail. Änderungen mit Vorsicht — falsche Daten stoppen den Mailversand."),
    "company_profile": (("stammdaten", "firma", "betrieb", "anschrift", "adresse"),
        "Die Stammdaten (Name, Anschrift, Telefon, Bank, Steuer) erscheinen auf Rechnungen/KVAs und im Briefkopf. Unter Einstellungen → Allgemein."),
}


def _update_customer(user: CurrentUser, args: dict) -> dict:
    from app.schemas.tools import UpdateCustomerDataRequest
    from app.services.customers import update_customer_data

    cid = (args.get("customer_id") or "").strip()
    if not _UUID_RE.match(cid):
        return {"error": "Ungültige Kunden-ID."}
    req = UpdateCustomerDataRequest(
        customer_id=cid, name=args.get("name"), email=args.get("email"),
        phone=args.get("phone"), address=args.get("address"),
    )
    return update_customer_data(user.org_id, req)


def _create_inquiry(user: CurrentUser, args: dict) -> dict:
    from app.schemas.tools import CreateInquiryRequest
    from app.services.inquiries import create_inquiry

    title = (args.get("title") or "").strip()
    if not title and not (args.get("message") or "").strip():
        return {"error": "Bitte einen Titel oder eine Beschreibung angeben."}
    req = CreateInquiryRequest(
        inquiry_title=title or None, message=args.get("message"),
        name=args.get("name"), phone=args.get("phone"), email=args.get("email"),
        urgent=bool(args["urgent"]) if args.get("urgent") is not None else None,
    )
    return create_inquiry(user.org_id, req)


def _set_inquiry_status(user: CurrentUser, args: dict) -> dict:
    iid = (args.get("inquiry_id") or "").strip()
    status = (args.get("status") or "").strip()
    if not _UUID_RE.match(iid):
        return {"error": "Ungültige Anfrage-ID."}
    if status not in _INQUIRY_STATUS:
        return {"error": f"Status muss eines von {list(_INQUIRY_STATUS)} sein."}
    rows = (
        get_service_client().table("inquiries")
        .update({"status": status}).eq("org_id", user.org_id).eq("id", iid)
        .execute().data or []
    )
    return {"updated": True, "status": status} if rows else {"error": "Anfrage nicht gefunden."}


def _create_appointment(user: CurrentUser, args: dict) -> dict:
    from app.api.routes import appointments as appt_routes
    from app.schemas.admin import AppointmentCreate

    scheduled_at = (args.get("scheduled_at") or "").strip()
    if not scheduled_at:
        return {"error": "scheduled_at (ISO-Datum/Uhrzeit) ist erforderlich."}
    try:
        payload = AppointmentCreate(
            customer_id=args.get("customer_id"), title=args.get("title"),
            scheduled_at=scheduled_at, duration_minutes=int(args.get("duration_minutes") or 60),
            location=args.get("location"), assigned_employee_id=args.get("assigned_employee_id"),
            notes=args.get("notes"),
        )
        return {"appointment": appt_routes._create(user.org_id, payload)}
    except Exception as exc:  # noqa: BLE001 — FK validation raises; surface a clean message
        return {"error": f"Termin nicht angelegt: {getattr(exc, 'detail', str(exc))}"}


def _report_problem(user: CurrentUser, args: dict) -> dict:
    summary = (args.get("summary") or "").strip()
    details = (args.get("details") or "").strip()
    if not summary:
        return {"error": "Bitte beschreibe das Problem kurz."}
    body_text = (
        "Support-Meldung aus dem Kiki-Copiloten\n\n"
        f"Nutzer: {user.full_name or '—'} ({user.email or '—'})\n"
        f"Org-ID: {user.org_id} · Rolle: {user.role}\n\n"
        f"Betreff: {summary}\n\nDetails:\n{details or '—'}"
    )
    email_status = "skipped"
    try:
        from app.services.email_send import send_email

        res = send_email(
            org_id=user.org_id, to_email=ESCALATION_EMAIL,
            subject=f"[Kiki Support] {summary[:120]}",
            body_html=body_text.replace("\n", "<br>"), body_text=body_text,
        )
        email_status = "sent" if getattr(res, "success", False) else (getattr(res, "error", None) or "failed")
    except Exception as exc:  # noqa: BLE001 — still registered even if mail fails
        email_status = f"error: {exc}"[:200]
    try:
        get_service_client().table("copilot_escalations").insert({
            "org_id": user.org_id, "user_id": user.id, "summary": summary,
            "body": details or None, "emailed_to": ESCALATION_EMAIL, "email_status": email_status,
        }).execute()
    except Exception:  # noqa: BLE001 — fail-open
        pass
    return {
        "registered": True, "emailed_to": ESCALATION_EMAIL, "email_status": email_status,
        "message": "Deine Meldung wurde aufgenommen und an das Support-Team weitergeleitet.",
    }


def _get_settings_tool(user: CurrentUser, args: dict) -> dict:
    from app.api.routes import settings as settings_routes

    s = settings_routes._get_settings(user.org_id)
    org = s.get("organization") or {}
    ec = s.get("email_config") or {}
    return {
        "organization": {k: org.get(k) for k in (
            "name", "trade", "email", "phone_number", "fax", "website",
            "address", "chamber_of_crafts", "accent_color", "ai_minutes_quota",
        )},
        "ai_suggestions": s.get("ai_suggestions"),
        "email_configured": bool(ec.get("has_password") or ec.get("oauth_account_email")),
        "usage": s.get("usage"),
    }


def _explain_setting(user: CurrentUser, args: dict) -> dict:
    topic = (args.get("topic") or "").lower().strip()
    for key, (terms, text) in _SETTINGS_DICT.items():
        if key in topic or any(t in topic for t in terms):
            return {"topic": key, "explanation": text}
    return {
        "available_topics": list(_SETTINGS_DICT),
        "message": "Dazu habe ich keine feste Erklärung. Verfügbare Themen: " + ", ".join(_SETTINGS_DICT),
    }


def _update_org_profile(user: CurrentUser, args: dict) -> dict:
    from app.api.routes import settings as settings_routes

    fields = {k: args[k] for k in _ORG_PROFILE_FIELDS if args.get(k) is not None}
    if isinstance(args.get("address"), dict):
        fields["address"] = args["address"]
    if not fields:
        return {"error": "Keine gültigen Felder zum Aktualisieren."}
    org = settings_routes._update_org(user.org_id, fields)
    return {"updated_fields": list(fields), "organization": {k: org.get(k) for k in _ORG_PROFILE_FIELDS}}


# ─── registry ────────────────────────────────────────────────────────────────
REGISTRY: list[Tool] = [
    Tool(
        name="search_customers",
        description="Suche Kunden des Betriebs nach Name, Telefon, E-Mail oder Kundennummer.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Suchbegriff"}},
            "required": ["query"],
        },
        run=_search_customers,
        kind="read",
    ),
    Tool(
        name="get_customer",
        description="Hole die Details eines Kunden anhand seiner ID.",
        parameters={
            "type": "object",
            "properties": {"customer_id": {"type": "string", "description": "Kunden-UUID"}},
            "required": ["customer_id"],
        },
        run=_get_customer,
        kind="read",
    ),
    Tool(
        name="list_pending_actions",
        description="Liste alle offenen Aufgaben/Entscheidungen (offene Aktionen) des Betriebs.",
        parameters={"type": "object", "properties": {}},
        run=_list_pending_actions,
        kind="read",
    ),
    Tool(
        name="get_finance_summary",
        description="Finanz-Überblick: Umsatz, bezahlte/offene Rechnungen, ausstehende KVAs.",
        parameters={"type": "object", "properties": {}},
        run=_get_finance_summary,
        kind="read",
    ),
    Tool(
        name="navigate_to",
        description="Öffne eine Seite im CRM für die angemeldete Person.",
        parameters={
            "type": "object",
            "properties": {
                "route": {"type": "string", "enum": list(KNOWN_ROUTES), "description": "Zielseite"}
            },
            "required": ["route"],
        },
        run=_navigate_to,
        kind="read",
        client_side=True,
    ),
    Tool(
        name="create_customer",
        description="Lege einen neuen Kunden an (erst nach Bestätigung der Person).",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Vor- und Nachname"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "address": {"type": "string"},
            },
            "required": ["name"],
        },
        run=_create_customer,
        kind="write",
        roles=ROLES_ALL,
    ),
    Tool(
        name="update_customer",
        description="Ändere die Daten eines bestehenden Kunden (Name/Telefon/E-Mail/Adresse).",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Kunden-UUID"},
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "address": {"type": "string"},
            },
            "required": ["customer_id"],
        },
        run=_update_customer,
        kind="write",
    ),
    Tool(
        name="create_inquiry",
        description="Lege eine neue Anfrage (Anliegen/Aufgabe) an, optional mit Kundendaten.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Kurzer Titel des Anliegens"},
                "message": {"type": "string"},
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "urgent": {"type": "boolean"},
            },
            "required": ["title"],
        },
        run=_create_inquiry,
        kind="write",
    ),
    Tool(
        name="set_inquiry_status",
        description="Setze den Status einer Anfrage: open, in_progress oder completed.",
        parameters={
            "type": "object",
            "properties": {
                "inquiry_id": {"type": "string", "description": "Anfrage-UUID"},
                "status": {"type": "string", "enum": list(_INQUIRY_STATUS)},
            },
            "required": ["inquiry_id", "status"],
        },
        run=_set_inquiry_status,
        kind="write",
    ),
    Tool(
        name="create_appointment",
        description="Lege einen Termin an (nach Bestätigung). Zeit als ISO, z. B. 2026-06-10T09:00:00.",
        parameters={
            "type": "object",
            "properties": {
                "scheduled_at": {"type": "string", "description": "ISO-Datum/Uhrzeit"},
                "title": {"type": "string"},
                "customer_id": {"type": "string", "description": "Kunden-UUID (optional)"},
                "duration_minutes": {"type": "integer"},
                "location": {"type": "string"},
                "assigned_employee_id": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["scheduled_at"],
        },
        run=_create_appointment,
        kind="write",
    ),
    Tool(
        name="report_problem",
        description="Nimm eine Support-Meldung/Beschwerde auf (wenn Kiki nicht weiterhelfen kann) und leite sie an das Support-Team weiter.",
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Kurze Problembeschreibung"},
                "details": {"type": "string", "description": "Optionale Details"},
            },
            "required": ["summary"],
        },
        run=_report_problem,
        kind="write",
    ),
    Tool(
        name="explain_setting",
        description="Erkläre eine CRM-Einstellung/Funktion (z. B. Kiki-Stufe, Notdienst, KI-Vorschläge, Geschäftszeiten).",
        parameters={
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "Thema/Einstellung"}},
            "required": ["topic"],
        },
        run=_explain_setting,
        kind="read",
    ),
    Tool(
        name="get_settings",
        description="Lies die aktuellen Organisations-Einstellungen (Stammdaten, KI-Vorschläge, Nutzung). Nur für Admins.",
        parameters={"type": "object", "properties": {}},
        run=_get_settings_tool,
        kind="read",
        roles=ROLES_ADMIN,
    ),
    Tool(
        name="update_org_profile",
        description="Aktualisiere die Stammdaten des Betriebs (Name/Telefon/E-Mail/Website/Gewerk). Nur Admins, nach Bestätigung.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "trade": {"type": "string"},
                "phone_number": {"type": "string"},
                "fax": {"type": "string"},
                "email": {"type": "string"},
                "website": {"type": "string"},
                "chamber_of_crafts": {"type": "string"},
            },
        },
        run=_update_org_profile,
        kind="write",
        roles=ROLES_ADMIN,
    ),
]

_BY_NAME: dict[str, Tool] = {t.name: t for t in REGISTRY}


def get_tool(name: str) -> Tool | None:
    return _BY_NAME.get(name)


def tools_for_role(role: str | None) -> list[Tool]:
    return [t for t in REGISTRY if t.allowed_for(role)]


def schemas_for_role(role: str | None) -> list[dict[str, Any]]:
    return [t.openai_schema() for t in tools_for_role(role)]
