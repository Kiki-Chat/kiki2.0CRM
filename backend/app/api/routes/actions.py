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
from pydantic import BaseModel
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
    "appointment_cancelled",
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


def _resolve_call_ids(client, org_id: str, rows: list[dict]) -> dict[str, str]:
    """Map appointment_id -> call_id for a set of appointment rows.

    Resolves via the linked inquiry's call_id (preferred), else the agent-booking
    conversation (source_conversation_id -> calls.conversation_id). Rows must carry
    ``inquiry_id`` and ``source_conversation_id``. Appointments with no resolvable
    call are simply omitted from the map.
    """
    inq_ids = [r.get("inquiry_id") for r in rows if r.get("inquiry_id")]
    conv_ids = [r.get("source_conversation_id") for r in rows if r.get("source_conversation_id")]
    inq_call: dict[str, str] = {}
    if inq_ids:
        for row in (
            client.table("inquiries").select("id, call_id")
            .eq("org_id", org_id).in_("id", inq_ids).execute().data or []
        ):
            if row.get("call_id"):
                inq_call[row["id"]] = row["call_id"]
    conv_call: dict[str, str] = {}
    if conv_ids:
        for row in (
            client.table("calls").select("id, elevenlabs_conversation_id")
            .eq("org_id", org_id).in_("elevenlabs_conversation_id", conv_ids).execute().data or []
        ):
            if row.get("elevenlabs_conversation_id"):
                conv_call[row["elevenlabs_conversation_id"]] = row["id"]
    out: dict[str, str] = {}
    for r in rows:
        cid = inq_call.get(r.get("inquiry_id")) or conv_call.get(r.get("source_conversation_id"))
        if cid:
            out[r["id"]] = cid
    return out


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
            "created_at, status, source_conversation_id"
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
    # Resolve a call_id per appointment so clicking the worklist row opens the
    # call whose action card carries the Bestätigen/Ablehnen buttons (the only
    # place a pending appointment can be confirmed) — via the inquiry's call_id,
    # else the agent-booking conversation link. Without this the row had no call
    # to open and wrongly fell back to the customer page (no confirm there).
    call_by_appt = _resolve_call_ids(client, org_id, rows)
    out: list[dict[str, Any]] = []
    for r in rows:
        nm = name_by_cust.get(r.get("customer_id")) or "Unbekannter Kunde"
        title = r.get("title") or "Termin"
        out.append(
            {
                "kind": "termin_anfrage",
                "id": r["id"],
                "inquiry_id": r.get("inquiry_id"),
                "call_id": call_by_appt.get(r["id"]),
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


def _callback_owed(client, org_id: str) -> list[dict[str, Any]]:
    """Missed inbound calls that still owe a callback (missed_calls.status='pending')."""
    rows = (
        client.table("missed_calls")
        .select("id, customer_id, caller_number, missed_at, created_at, status")
        .eq("org_id", org_id)
        .eq("status", "pending")
        .order("missed_at", desc=True)
        .execute()
        .data
        or []
    )
    name_by_cust = _customer_name_map(
        client, org_id, [r.get("customer_id") for r in rows]
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        nm = name_by_cust.get(r.get("customer_id")) or r.get("caller_number") or "Unbekannter Anrufer"
        out.append(
            {
                "kind": "callback_owed",
                "id": r["id"],
                "inquiry_id": None,
                "call_id": None,
                "customer_name": nm,
                "customer_id": r.get("customer_id"),
                "summary": f"Rückruf offen — verpasster Anruf von {r.get('caller_number') or nm}",
                "created_at": r.get("created_at"),
                "due_at": None,
                "priority": "high",
            }
        )
    return out


def _alt_time_proposal(client, org_id: str) -> list[dict[str, Any]]:
    """Appointments with an OPEN alternative-time proposal: the customer counter-
    proposed a slot (awaiting a team decision — high priority) or the team sent an
    alternative (awaiting the customer)."""
    cols = (
        "id, inquiry_id, customer_id, title, created_at, status, "
        "alternative_proposed_at, alternative_start_time, "
        "customer_proposed_at, customer_proposed_start_time, source_conversation_id"
    )
    cust = (
        client.table("appointments").select(cols).eq("org_id", org_id)
        .neq("status", "cancelled").not_.is_("customer_proposed_at", "null")
        .execute().data
        or []
    )
    alt = (
        client.table("appointments").select(cols).eq("org_id", org_id)
        .neq("status", "cancelled").not_.is_("alternative_proposed_at", "null")
        .execute().data
        or []
    )
    by_id: dict[str, tuple[dict, bool]] = {}
    for r in alt:
        by_id[r["id"]] = (r, False)  # awaiting customer
    for r in cust:
        by_id[r["id"]] = (r, True)  # customer counter-proposal — awaiting team (priority)
    name_by_cust = _customer_name_map(
        client, org_id, [r.get("customer_id") for r, _ in by_id.values()]
    )
    # Resolve a call_id for each appointment so the worklist card can deep-link to
    # the call whose action card carries the Genehmigen/Ablehnen buttons — via the
    # inquiry's call_id, else the agent-booking conversation link. Without this the
    # card had no call to open and wrongly fell back to the customer page.
    inq_ids = [r.get("inquiry_id") for r, _ in by_id.values() if r.get("inquiry_id")]
    conv_ids = [
        r.get("source_conversation_id") for r, _ in by_id.values() if r.get("source_conversation_id")
    ]
    inq_call: dict[str, str] = {}
    if inq_ids:
        for row in (
            client.table("inquiries").select("id, call_id")
            .eq("org_id", org_id).in_("id", inq_ids).execute().data or []
        ):
            if row.get("call_id"):
                inq_call[row["id"]] = row["call_id"]
    conv_call: dict[str, str] = {}
    if conv_ids:
        for row in (
            client.table("calls").select("id, elevenlabs_conversation_id")
            .eq("org_id", org_id).in_("elevenlabs_conversation_id", conv_ids).execute().data or []
        ):
            if row.get("elevenlabs_conversation_id"):
                conv_call[row["elevenlabs_conversation_id"]] = row["id"]
    out: list[dict[str, Any]] = []
    for r, is_cust in by_id.values():
        nm = name_by_cust.get(r.get("customer_id")) or "Unbekannter Kunde"
        if is_cust:
            summary = "Kunde schlägt neuen Termin vor — Entscheidung ausstehend"
            due = r.get("customer_proposed_start_time")
            priority = "high"
        else:
            summary = "Alternativtermin gesendet — Kundenantwort ausstehend"
            due = r.get("alternative_start_time")
            priority = "normal"
        out.append(
            {
                "kind": "alt_time_proposal",
                "id": r["id"],
                "inquiry_id": r.get("inquiry_id"),
                "call_id": inq_call.get(r.get("inquiry_id"))
                or conv_call.get(r.get("source_conversation_id")),
                "customer_name": nm,
                "customer_id": r.get("customer_id"),
                "summary": summary,
                "created_at": r.get("created_at"),
                "due_at": due,
                "priority": priority,
                # 'customer' → the customer counter-proposed a slot (the team can
                # Genehmigen/Ablehnen it in one click); 'team' → we sent an alternative
                # and are awaiting the customer's reply (nothing to approve yet).
                "proposal_role": "customer" if is_cust else "team",
            }
        )
    return out


def _appointment_cancelled(client, org_id: str) -> list[dict[str, Any]]:
    """Recently-cancelled appointments — kept visible so the team is INFORMED instead
    of the worklist item silently vanishing on cancel. Windowed to the last 14 days
    (no dismissal table); the team can re-book from the customer card if needed.

    Sourced from cancelled_at (set on /cancel + the agent cancel tool), so only NEW
    cancellations appear — a staff 'Ablehnen' of a pending request (rejected_at) is a
    different lifecycle event and is not surfaced here."""
    cutoff = _iso_minus_days(14)
    rows = (
        client.table("appointments")
        .select(
            "id, inquiry_id, customer_id, title, scheduled_at, cancelled_at, "
            "created_at, status, source_conversation_id"
        )
        .eq("org_id", org_id)
        .eq("status", "cancelled")
        .gte("cancelled_at", cutoff)
        .order("cancelled_at", desc=True)
        .execute()
        .data
        or []
    )
    if not rows:
        return []
    name_by_cust = _customer_name_map(
        client, org_id, [r.get("customer_id") for r in rows]
    )
    call_by_appt = _resolve_call_ids(client, org_id, rows)
    out: list[dict[str, Any]] = []
    for r in rows:
        nm = name_by_cust.get(r.get("customer_id")) or "Unbekannter Kunde"
        title = r.get("title") or "Termin"
        out.append(
            {
                "kind": "appointment_cancelled",
                "id": r["id"],
                "inquiry_id": r.get("inquiry_id"),
                "call_id": call_by_appt.get(r["id"]),
                "customer_name": nm,
                "customer_id": r.get("customer_id"),
                "summary": f"Termin storniert: {title} — Team informieren / ggf. neu vereinbaren",
                "created_at": r.get("created_at"),
                "due_at": None,
                "priority": "high",
            }
        )
    return out


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


# Struck-through (done) tasks linger this long after they were marked done, then drop.
_DONE_VISIBLE_DAYS = 3


def _apply_task_states(client, org_id: str, items: list[dict]) -> list[dict]:
    """Overlay the manual to-do state (action_tasks) onto the derived actions.

    dismissed → hidden · done → struck (state='done') until 3 days after done_at, then
    dropped · claimed → state='claimed' + claimer name · else state='open'."""
    if not items:
        return items
    keys = [it["action_key"] for it in items]
    rows = (
        client.table("action_tasks")
        .select("action_key, status, claimed_by, done_at")
        .eq("org_id", org_id).in_("action_key", keys).execute().data
        or []
    )
    by_key = {r["action_key"]: r for r in rows}
    claimer_ids = list({r.get("claimed_by") for r in rows if r.get("claimed_by")})
    name_by_user: dict[str, str | None] = {}
    if claimer_ids:
        for u in (
            client.table("users").select("id, full_name")
            .in_("id", claimer_ids).execute().data or []
        ):
            name_by_user[u["id"]] = u.get("full_name")
    cutoff = _iso_minus_days(_DONE_VISIBLE_DAYS)
    out: list[dict] = []
    for it in items:
        st = by_key.get(it["action_key"])
        it["state"], it["claimed_by_name"], it["done_at_task"] = "open", None, None
        if not st:
            out.append(it)
            continue
        status = st.get("status")
        if status == "dismissed":
            continue  # deleted by the user
        if status == "done":
            if (st.get("done_at") or "") < cutoff:
                continue  # struck > 3 days ago → drop
            it["state"], it["done_at_task"] = "done", st.get("done_at")
        elif status == "claimed":
            it["state"] = "claimed"
            it["claimed_by_name"] = name_by_user.get(st.get("claimed_by"))
        out.append(it)
    return out


def _aggregate(org_id: str) -> list[dict[str, Any]]:
    client = get_service_client()
    items: list[dict[str, Any]] = []
    items.extend(_termin_anfrage(client, org_id))
    items.extend(_kva_to_send(client, org_id))
    items.extend(_kva_pending_acceptance(client, org_id))
    items.extend(_callback_owed(client, org_id))
    items.extend(_alt_time_proposal(client, org_id))
    items.extend(_appointment_cancelled(client, org_id))

    # Stable per-action key so the manual to-do state (claim/done/dismiss) sticks.
    for it in items:
        it["action_key"] = f"{it['kind']}:{it['id']}"
    items = _apply_task_states(client, org_id, items)

    # Sort: priority desc, due_at asc nulls last, created_at desc.
    # Python sorted() is stable — do passes in reverse priority order:
    #   1) created_at desc (least significant)
    #   2) due_at asc nulls last
    #   3) priority desc (most significant — wins ties)
    items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    items.sort(key=lambda r: (0 if r.get("due_at") else 1, r.get("due_at") or ""))
    items.sort(key=lambda r: _PRIORITY_RANK.get(r.get("priority") or "normal", 1))
    # Struck-through (done) tasks sink to the bottom — they stay as a 3-day record.
    items.sort(key=lambda r: 1 if r.get("state") == "done" else 0)
    return items


# ─── Routes ─────────────────────────────────────────────────────────────────
@router.get("/pending")
async def list_pending_actions(
    user: CurrentUser = Depends(require_org),
) -> list[dict[str, Any]]:
    """Aggregated open decisions for the current org.

    Returns a list of ActionItem dicts (see module docstring). Empty list when
    the org has nothing pending. Org-scoped via require_org.
    """
    return await run_in_threadpool(_aggregate, user.org_id)


class ActionStateRequest(BaseModel):
    action_key: str
    status: Literal["open", "claimed", "done", "dismissed"]


def _set_action_state(user: CurrentUser, payload: ActionStateRequest) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    row: dict[str, Any] = {
        "org_id": user.org_id,
        "action_key": payload.action_key,
        "status": payload.status,
        "updated_at": now,
    }
    if payload.status == "claimed":
        row["claimed_by"] = user.id
        row["done_at"] = None
    elif payload.status == "done":
        row["done_at"] = now
    elif payload.status == "open":  # reopen — clear claim + done
        row["claimed_by"] = None
        row["done_at"] = None
    get_service_client().table("action_tasks").upsert(
        row, on_conflict="org_id,action_key"
    ).execute()
    return {"ok": True, "action_key": payload.action_key, "status": payload.status}


@router.post("/state")
async def set_action_state(
    payload: ActionStateRequest, user: CurrentUser = Depends(require_org)
) -> dict:
    """Set the manual to-do state of one action (Übernehmen / Erledigt / Löschen /
    reopen). Upserts into action_tasks keyed by (org_id, action_key)."""
    return await run_in_threadpool(_set_action_state, user, payload)
