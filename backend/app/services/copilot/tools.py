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
]

_BY_NAME: dict[str, Tool] = {t.name: t for t in REGISTRY}


def get_tool(name: str) -> Tool | None:
    return _BY_NAME.get(name)


def tools_for_role(role: str | None) -> list[Tool]:
    return [t for t in REGISTRY if t.allowed_for(role)]


def schemas_for_role(role: str | None) -> list[dict[str, Any]]:
    return [t.openai_schema() for t in tools_for_role(role)]
