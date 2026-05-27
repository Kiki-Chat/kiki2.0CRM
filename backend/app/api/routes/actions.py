"""Wave 2 / Agent 2.2 — pending Aktionen aggregation.

Surfaces "open decisions" across the org as a single ranked list for the
left-sidebar Aktionen tab on /calls. Each row points at a concrete entity
(appointment / cost_estimate / inquiry) so the UI can navigate when clicked.

Aggregation today (live schema):

* **termin_anfrage**   appointments.status = 'pending'
  (Schema enum is pending|confirmed|cancelled|completed — there's no
  'pending_confirmation' value, so 'pending' is the right "Kiki proposed,
  human hasn't confirmed yet" bucket.)

* **kva_to_send**      cost_estimates.status = 'draft' AND created > 24h ago
* **kva_pending_acceptance**  cost_estimates.status = 'sent' AND
  sent_at within the last 7 days AND no accepted_at/rejected_at.

* **callback_owed**    EMPTY — inquiries.status enum is
  open|in_progress|completed|deleted; there is no 'callback_required' value
  in current schema. Returns an empty list for this kind until a new
  inquiry status / flag is introduced. Documented in handover.

* **alt_time_proposal** EMPTY — appointments has no
  alternative_proposed_at column today. Returns empty for this kind until
  the alternative-time-proposal feature ships.

Sort: priority desc, due_at asc nulls last, created_at desc.
Auth: org-scoped via require_org.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api/actions", tags=["actions"])

# Kept narrow on purpose: the UI only renders an ActionItem if the kind is one
# of these. Adding a new kind is a typed change so the frontend label map can be
# updated in lockstep.
ActionKind = Literal[
    "termin_anfrage",
    "kva_to_send",
    "kva_pending_acceptance",
    "callback_owed",
    "alt_time_proposal",
]


# ─── Helpers ────────────────────────────────────────────────────────────────
def _iso_minus_hours(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _iso_minus_days(days: int) -> str:
    return _iso_minus_hours(days * 24)


def _customer_name_map(client, org_id: str, ids: list[str]) -> dict[str, str | None]:
    ids = list({i for i in ids if i})
    if not ids:
        return {}
    rows = (
        client.table("customers")
        .select("id, full_name")
        .eq("org_id", org_id)
        .in_("id", ids)
        .execute()
        .data
        or []
    )
    return {r["id"]: r.get("full_name") for r in rows}


# ─── Per-kind aggregators (org-scoped) ──────────────────────────────────────
def _termin_anfrage(client, org_id: str) -> list[dict[str, Any]]:
    """Appointments Kiki proposed but no human has confirmed yet.

    The DB constraint allows pending|confirmed|cancelled|completed. 'pending'
    is the only value that means "needs a decision".
    """
    rows = (
        client.table("appointments")
        .select(
            "id, inquiry_id, customer_id, title, scheduled_at, "
            "created_at, status"
        )
        .eq("org_id", org_id)
        .eq("status", "pending")
        .order("scheduled_at")
        .execute()
        .data
        or []
    )
    name_by_cust = _customer_name_map(
        client, org_id, [r.get("customer_id") for r in rows]
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        nm = name_by_cust.get(r.get("customer_id")) or "Unbekannter Kunde"
        title = r.get("title") or "Termin"
        out.append(
            {
                "kind": "termin_anfrage",
                "id": r["id"],
                "inquiry_id": r.get("inquiry_id"),
                "call_id": None,
                "customer_name": nm,
                "customer_id": r.get("customer_id"),
                "summary": f"Terminbestätigung ausstehend: {title}",
                "created_at": r.get("created_at"),
                "due_at": r.get("scheduled_at"),
                "priority": "normal",
            }
        )
    return out


def _kva_to_send(client, org_id: str) -> list[dict[str, Any]]:
    """Draft KVAs older than 24h — assumed to have stalled and need sending."""
    cutoff = _iso_minus_hours(24)
    rows = (
        client.table("cost_estimates")
        .select(
            "id, inquiry_id, customer_id, number, total, "
            "created_at, status"
        )
        .eq("org_id", org_id)
        .eq("status", "draft")
        .lte("created_at", cutoff)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    name_by_cust = _customer_name_map(
        client, org_id, [r.get("customer_id") for r in rows]
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        nm = name_by_cust.get(r.get("customer_id")) or "Unbekannter Kunde"
        num = r.get("number") or "KVA"
        out.append(
            {
                "kind": "kva_to_send",
                "id": r["id"],
                "inquiry_id": r.get("inquiry_id"),
                "call_id": None,
                "customer_name": nm,
                "customer_id": r.get("customer_id"),
                "summary": f"{num} bereit zum Versand",
                "created_at": r.get("created_at"),
                "due_at": None,
                "priority": "normal",
            }
        )
    return out


def _kva_pending_acceptance(client, org_id: str) -> list[dict[str, Any]]:
    """Sent KVAs from the last 7 days with no accept/reject yet."""
    cutoff = _iso_minus_days(7)
    rows = (
        client.table("cost_estimates")
        .select(
            "id, inquiry_id, customer_id, number, total, "
            "sent_at, accepted_at, rejected_at, status, created_at"
        )
        .eq("org_id", org_id)
        .eq("status", "sent")
        .gte("sent_at", cutoff)
        .order("sent_at", desc=True)
        .execute()
        .data
        or []
    )
    # belt-and-braces: enum constraint already drops accepted/rejected, but a
    # row could carry both status='sent' and an old accepted_at if a downstream
    # flip didn't update status. Filter explicitly.
    rows = [
        r for r in rows
        if not r.get("accepted_at") and not r.get("rejected_at")
    ]
    name_by_cust = _customer_name_map(
        client, org_id, [r.get("customer_id") for r in rows]
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        nm = name_by_cust.get(r.get("customer_id")) or "Unbekannter Kunde"
        num = r.get("number") or "KVA"
        out.append(
            {
                "kind": "kva_pending_acceptance",
                "id": r["id"],
                "inquiry_id": r.get("inquiry_id"),
                "call_id": None,
                "customer_name": nm,
                "customer_id": r.get("customer_id"),
                "summary": f"{num} versendet — Kundenantwort ausstehend",
                "created_at": r.get("created_at"),
                "due_at": None,
                "priority": "normal",
            }
        )
    return out


def _callback_owed(_client, _org_id: str) -> list[dict[str, Any]]:
    """No-op: the inquiries.status enum has no 'callback_required' value in the
    current schema. Returns empty until a callback status/flag is added.
    """
    return []


def _alt_time_proposal(_client, _org_id: str) -> list[dict[str, Any]]:
    """No-op: appointments has no alternative_proposed_at column today.
    Returns empty until the alt-time proposal feature ships.
    """
    return []


# ─── Sort: priority desc, due_at asc nulls last, created_at desc ────────────
_PRIORITY_RANK = {"high": 0, "normal": 1}


def _sort_key(row: dict) -> tuple[int, int, str, str]:
    pri = _PRIORITY_RANK.get(row.get("priority") or "normal", 1)
    due = row.get("due_at")
    # "asc nulls last": rows without a due date sort after rows with one.
    return (
        pri,
        0 if due else 1,
        due or "",
        # invert created_at for desc — but sorted() is ascending; we negate by
        # mapping with reverse on the created_at string only. Easiest: use a
        # second pass — Python's sort is stable, so do priority/due first, then
        # re-sort by created_at desc within ties... actually a single key works
        # if we reverse just created_at by mapping "z" - char. The simpler path:
        # build a list of (pri, due_present, due, neg_created). For ISO strings
        # we'd need a different trick. Easiest: negate by sorting on tuple AND
        # the created_at as descending later via stable re-sort. We use a
        # straightforward stable two-pass below in _aggregate instead.
        row.get("created_at") or "",
    )


def _aggregate(org_id: str) -> list[dict[str, Any]]:
    client = get_service_client()
    items: list[dict[str, Any]] = []
    items.extend(_termin_anfrage(client, org_id))
    items.extend(_kva_to_send(client, org_id))
    items.extend(_kva_pending_acceptance(client, org_id))
    items.extend(_callback_owed(client, org_id))
    items.extend(_alt_time_proposal(client, org_id))

    # Sort: priority desc, due_at asc nulls last, created_at desc.
    # Python sorted() is stable — do passes in reverse priority order:
    #   1) created_at desc (least significant)
    #   2) due_at asc nulls last
    #   3) priority desc (most significant — wins ties)
    items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    items.sort(key=lambda r: (0 if r.get("due_at") else 1, r.get("due_at") or ""))
    items.sort(key=lambda r: _PRIORITY_RANK.get(r.get("priority") or "normal", 1))
    return items


# ─── Route ──────────────────────────────────────────────────────────────────
@router.get("/pending")
async def list_pending_actions(
    user: CurrentUser = Depends(require_org),
) -> list[dict[str, Any]]:
    """Aggregated open decisions for the current org.

    Returns a list of ActionItem dicts (see module docstring). Empty list when
    the org has nothing pending. Org-scoped via require_org.
    """
    return await run_in_threadpool(_aggregate, user.org_id)
