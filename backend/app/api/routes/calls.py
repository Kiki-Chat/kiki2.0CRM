from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.common import fetch_all_rows, run_parallel

router = APIRouter(prefix="/api/calls", tags=["calls"])

_LIST_SELECT = (
    "id, elevenlabs_conversation_id, caller_number, summary_title, direction, "
    "duration_seconds, started_at, status, data_collection, customer_id, read_at, "
    "created_at, inquiry_id, customers(full_name)"
)

# Wave 2 / Agent 2.1 — list-item enrichment.
# Category strings that should be treated as emergency even if `emergency_flag`
# isn't set on the inquiry row (covers existing data + AI-classified turns where
# the agent stuffed the urgency into `type` instead of toggling the flag).
_EMERGENCY_CATEGORIES = {"notdienst", "notfall", "emergency"}


def _employee_initials(display_name: str | None) -> str | None:
    """Derive max-2-char initials from `employees.display_name` for the
    list-card avatar. Returns None when the row isn't an assigned employee
    (caller can render `?` in a neutral circle instead)."""
    if not display_name:
        return None
    parts = [p for p in display_name.strip().split() if p]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _enrich_calls_with_inquiries(client, org_id: str, calls: list[dict]) -> list[dict]:
    """Attach the call's Vorgang (case) + assignment fields to every row:
    `inquiry_id`, `inquiry_status`, `inquiry_number`, `inquiry_subject`,
    `emergency_flag`, `assigned_employee_id`, `assigned_employee_initials`.

    Primary link is `calls.inquiry_id` — stamped for INBOUND *and* OUTBOUND since
    Vorgang threading, so outbound calls now resolve their case (which is why the
    action buttons used to die). For any row not yet stamped we fall back to the
    legacy `inquiries.call_id` reverse-lookup (earliest non-deleted), so pre-backfill
    rows keep working. Batched: ≤2 SELECTs for inquiries + 1 for the employees.
    """
    if not calls:
        return calls

    _INQ_COLS = (
        "id, call_id, status, type, emergency_flag, assigned_employee_id, "
        "number, subject, title, created_at"
    )

    # Primary: resolve by the case id already stamped on the call.
    direct_ids = {c["inquiry_id"] for c in calls if c.get("inquiry_id")}
    # Fallback: calls with no stamped case → legacy reverse-lookup by call_id.
    unstamped_call_ids = [c["id"] for c in calls if c.get("id") and not c.get("inquiry_id")]

    inquiry_by_id: dict[str, dict] = {}
    if direct_ids:
        for row in (
            client.table("inquiries").select(_INQ_COLS)
            .eq("org_id", org_id).in_("id", list(direct_ids))
            .execute().data or []
        ):
            inquiry_by_id[row["id"]] = row

    inquiry_by_call: dict[str, dict] = {}
    if unstamped_call_ids:
        for row in (
            client.table("inquiries").select(_INQ_COLS)
            .eq("org_id", org_id).in_("call_id", unstamped_call_ids)
            .neq("status", "deleted").order("created_at")
            .execute().data or []
        ):
            cid = row.get("call_id")
            if cid and cid not in inquiry_by_call:
                inquiry_by_call[cid] = row

    # Batch-fetch employees referenced by the chosen inquiries.
    chosen = list(inquiry_by_id.values()) + list(inquiry_by_call.values())
    employee_ids = {i["assigned_employee_id"] for i in chosen if i.get("assigned_employee_id")}
    employees_by_id: dict[str, dict] = {}
    if employee_ids:
        for e in (
            client.table("employees")
            .select("id, display_name")
            .eq("org_id", org_id)
            .in_("id", list(employee_ids))
            .execute()
            .data
            or []
        ):
            employees_by_id[e["id"]] = e

    for c in calls:
        inq = inquiry_by_id.get(c.get("inquiry_id")) or inquiry_by_call.get(c.get("id"))
        if inq is None:
            c["inquiry_id"] = None
            c["inquiry_status"] = None
            c["inquiry_number"] = None
            c["inquiry_subject"] = None
            c["emergency_flag"] = False
            c["assigned_employee_id"] = None
            c["assigned_employee_initials"] = None
            continue

        c["inquiry_id"] = inq["id"]
        c["inquiry_status"] = inq.get("status")
        c["inquiry_number"] = inq.get("number")
        c["inquiry_subject"] = inq.get("subject")
        # Flag-driven, OR category-driven for legacy/AI-classified rows.
        type_lower = (inq.get("type") or "").lower()
        c["emergency_flag"] = bool(inq.get("emergency_flag")) or (
            type_lower in _EMERGENCY_CATEGORIES
        )

        emp_id = inq.get("assigned_employee_id")
        c["assigned_employee_id"] = emp_id
        if emp_id and emp_id in employees_by_id:
            c["assigned_employee_initials"] = _employee_initials(
                employees_by_id[emp_id].get("display_name")
            )
        else:
            c["assigned_employee_initials"] = None
    return calls


def _list(org_id: str, limit: int, offset: int, customer_id: str | None) -> dict:
    client = get_service_client()
    query = (
        client.table("calls")
        .select(_LIST_SELECT, count="exact")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
    )
    if customer_id:
        query = query.eq("customer_id", customer_id)
    res = (
        query.order("started_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    calls = res.data or []
    calls = _enrich_calls_with_inquiries(client, org_id, calls)
    return {"calls": calls, "total": res.count or 0}


def _detail(org_id: str, call_id: str) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("calls")
        .select("*, customers(full_name, phone, email, customer_number)")
        .eq("org_id", org_id)
        .eq("id", call_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


@router.get("")
async def list_calls(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    customer_id: str | None = None,
    user: CurrentUser = Depends(require_org),
) -> dict:
    # Bound limit/offset so a hand-crafted ?limit=99999 can't force a huge scan.
    return await run_in_threadpool(_list, user.org_id, limit, offset, customer_id)


@router.get("/{call_id}")
async def get_call(call_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    call = await run_in_threadpool(_detail, user.org_id, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


def _delete(org_id: str, call_id: str) -> bool:
    """Soft-delete a call (stamp deleted_at) and soft-delete its linked inquiries
    (status='deleted'), so the call leaves the cockpit list and inquiry views.
    Org-scoped. Returns False when no such call exists for this org."""
    client = get_service_client()
    now = datetime.now(timezone.utc).isoformat()
    rows = (
        client.table("calls")
        .update({"deleted_at": now})
        .eq("org_id", org_id)
        .eq("id", call_id)
        .execute()
        .data
    )
    if not rows:
        return False
    (
        client.table("inquiries")
        .update({"status": "deleted"})
        .eq("org_id", org_id)
        .eq("call_id", call_id)
        .neq("status", "deleted")
        .execute()
    )
    return True


@router.delete("/{call_id}")
async def delete_call(call_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    """Delete a call from the Call Logs cockpit. Soft-delete (reversible by
    clearing deleted_at); also removes the linked inquiry."""
    ok = await run_in_threadpool(_delete, user.org_id, call_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Call not found")
    return {"success": True}


def _ensure_inquiry(org_id: str, call_id: str) -> dict | None:
    from app.services.inquiries import ensure_call_inquiry

    call = _detail(org_id, call_id)
    if not call:
        return None
    return ensure_call_inquiry(get_service_client(), org_id, call)


@router.post("/{call_id}/inquiry")
async def ensure_call_inquiry_route(
    call_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    inquiry = await run_in_threadpool(_ensure_inquiry, user.org_id, call_id)
    if inquiry is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return inquiry


# ─── Gmail-style read/unread (P0.4) ─────────────────────────────────────────
def _mark_read(org_id: str, call_id: str) -> dict | None:
    """Idempotent mark-read: sets read_at = now() ONLY if currently NULL,
    so the original 'first opened at' timestamp is preserved on reopens."""
    client = get_service_client()
    # Common case (first open) = ONE round-trip: conditionally stamp read_at only
    # where it's still NULL and let PostgREST return the row it actually updated.
    updated = (
        client.table("calls")
        .update({"read_at": datetime.now(timezone.utc).isoformat()})
        .eq("org_id", org_id)
        .eq("id", call_id)
        .is_("read_at", "null")
        .execute()
        .data
    )
    if updated:
        return updated[0]
    # Nothing flipped → either already-read or no such call. One read settles it
    # (and preserves the original 'first opened at' timestamp on reopens).
    rows = (
        client.table("calls")
        .select("id, read_at")
        .eq("org_id", org_id)
        .eq("id", call_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


@router.post("/{call_id}/mark-read")
async def mark_call_read(call_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    """Mark a call as read by the current user's org. Idempotent — opening
    the same call twice keeps the original read_at timestamp."""
    result = await run_in_threadpool(_mark_read, user.org_id, call_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return {"id": result["id"], "read_at": result["read_at"]}


@router.get("/{call_id}/audio")
async def get_call_audio(call_id: str, user: CurrentUser = Depends(require_org)):
    """Fetch the recording on demand from ElevenLabs by conversation_id."""
    call = await run_in_threadpool(_detail, user.org_id, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    conversation_id = call.get("elevenlabs_conversation_id")
    if not conversation_id:
        raise HTTPException(status_code=404, detail="No conversation id for this call")
    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=503, detail="ElevenLabs API key not configured")

    url = f"https://api.elevenlabs.io/v1/convai/conversations/{conversation_id}/audio"
    # Classify upstream failures so the client gets an accurate status instead of a
    # bare 500: a hung ElevenLabs → 504, a network/transport error → 502.
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers={"xi-api-key": settings.elevenlabs_api_key})
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504, detail="Zeitüberschreitung beim Laden der Aufnahme von ElevenLabs."
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502, detail="Aufnahme konnte nicht von ElevenLabs geladen werden."
        ) from exc
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"Audio unavailable ({resp.status_code})"
        )
    return Response(content=resp.content, media_type="audio/mpeg")


# ─── Wave 3 / Agent 3.2 — unified timeline for the Verlauf tab ───────────────
@router.get("/{call_id}/timeline")
async def get_call_timeline(
    call_id: str, user: CurrentUser = Depends(require_org)
) -> list[dict]:
    """Aggregated, newest-first list of timeline events for one call.

    Pulls from existing columns — no dedicated `events` table. Sources:

    * `call_created`              — the call row itself (created_at)
    * `inquiry_status_changed`    — `inquiries.updated_at` when status moved
                                    out of 'open' (open→in_progress→completed)
    * `appointment_confirmed`     — `appointments.confirmed_at` (Wave 2 col)
    * `appointment_rejected`      — `appointments.rejected_at`  (Wave 2 col)
    * `alternative_proposed`      — `appointments.alternative_proposed_at`
    * `kva_sent`                  — `cost_estimates.sent_at`
    * `kva_accepted`              — `cost_estimates.accepted_at`
    * `kva_rejected`              — `cost_estimates.rejected_at`
    * `assignment_changed`        — **NOT TRACKED** — `inquiries.assigned_to`
                                    is overwritten in place with no audit
                                    history. Flagged as a follow-up; not
                                    surfaced in v1.

    Org-scoping is enforced at every SELECT via `eq("org_id", ...)`. Cross-org
    call_ids return 404 before any aggregation runs.
    """
    timeline = await run_in_threadpool(_build_timeline, user.org_id, call_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return timeline


def _actor_for_status(status: str | None) -> tuple[str, str]:
    """Map an inquiry status to (actor_kind, actor_name).

    Without a per-row "who flipped it" audit column we can't pin every status
    change to a specific employee, so we use the system-vs-Kiki heuristic:
    'open' is what Kiki creates; transitions out of 'open' are employee work.
    """
    if status in ("in_progress", "completed"):
        return ("employee", "Mitarbeiter")
    return ("system", "System")


_STATUS_LABEL = {
    "open": "Offen",
    "in_progress": "In Bearbeitung",
    "completed": "Erledigt",
    "deleted": "Gelöscht",
}


# ── Shared event emitters (used by BOTH the per-call and the customer timeline) ──
# Each maps one DB row to zero-or-more TimelineEvent dicts so the two views render
# the exact same record of "every move".
def _appointment_events(appt: dict) -> list[dict]:
    title = appt.get("title") or "Termin"
    out: list[dict] = []
    if appt.get("created_at"):
        out.append({
            "id": f"appointment:{appt['id']}:created", "kind": "appointment_created",
            "timestamp": appt["created_at"], "actor_kind": "kiki", "actor_name": "Kiki",
            "description": f"Termin gebucht: {title}", "entity_id": appt["id"],
            "extras": {"scheduled_at": appt.get("scheduled_at")},
        })
    if appt.get("customer_proposed_at"):
        out.append({
            "id": f"appointment:{appt['id']}:rescheduled", "kind": "appointment_rescheduled",
            "timestamp": appt["customer_proposed_at"], "actor_kind": "system", "actor_name": "Kunde",
            "description": f"Terminänderung angefragt: {title}", "entity_id": appt["id"],
            "extras": {"proposed_start_time": appt.get("customer_proposed_start_time")},
        })
    if appt.get("confirmed_at"):
        out.append({
            "id": f"appointment:{appt['id']}:confirmed", "kind": "appointment_confirmed",
            "timestamp": appt["confirmed_at"], "actor_kind": "employee", "actor_name": "Mitarbeiter",
            "description": f"Termin bestätigt: {title}", "entity_id": appt["id"],
            "extras": {"scheduled_at": appt.get("scheduled_at")},
        })
    if appt.get("rejected_at"):
        extras: dict = {"scheduled_at": appt.get("scheduled_at")}
        if appt.get("rejection_reason"):
            extras["reason"] = appt["rejection_reason"]
        out.append({
            "id": f"appointment:{appt['id']}:rejected", "kind": "appointment_rejected",
            "timestamp": appt["rejected_at"], "actor_kind": "employee", "actor_name": "Mitarbeiter",
            "description": f"Termin abgelehnt: {title}", "entity_id": appt["id"], "extras": extras,
        })
    if appt.get("alternative_proposed_at"):
        out.append({
            "id": f"appointment:{appt['id']}:alt", "kind": "alternative_proposed",
            "timestamp": appt["alternative_proposed_at"], "actor_kind": "employee", "actor_name": "Mitarbeiter",
            "description": f"Alternativtermin vorgeschlagen: {title}", "entity_id": appt["id"],
            "extras": {"alternative_start_time": appt.get("alternative_start_time")},
        })
    # Human (calendar) reschedule of an existing time — distinct from a customer
    # counter-proposal (customer_proposed_at, emitted above).
    if appt.get("rescheduled_at"):
        out.append({
            "id": f"appointment:{appt['id']}:rescheduled_admin", "kind": "appointment_rescheduled",
            "timestamp": appt["rescheduled_at"], "actor_kind": "employee", "actor_name": "Mitarbeiter",
            "description": f"Termin verschoben: {title}", "entity_id": appt["id"],
            "extras": {"scheduled_at": appt.get("scheduled_at")},
        })
    # Cancellation (via /cancel or the agent). `not rejected_at` keeps it distinct
    # from a staff "Ablehnen" of a still-pending request (emitted as rejected above).
    if appt.get("cancelled_at") and not appt.get("rejected_at"):
        out.append({
            "id": f"appointment:{appt['id']}:cancelled", "kind": "appointment_cancelled",
            "timestamp": appt["cancelled_at"], "actor_kind": "employee", "actor_name": "Mitarbeiter",
            "description": f"Termin storniert: {title}", "entity_id": appt["id"],
            "extras": {"scheduled_at": appt.get("scheduled_at"), "reason": appt.get("notes")},
        })
    return out


def _kva_events(kva: dict) -> list[dict]:
    num = kva.get("number") or "KVA"
    out: list[dict] = []
    if kva.get("sent_at"):
        out.append({
            "id": f"kva:{kva['id']}:sent", "kind": "kva_sent", "timestamp": kva["sent_at"],
            "actor_kind": "employee", "actor_name": "Mitarbeiter", "description": f"{num} versendet",
            "entity_id": kva["id"], "extras": {"number": kva.get("number"), "total": kva.get("total")},
        })
    if kva.get("accepted_at"):
        out.append({
            "id": f"kva:{kva['id']}:accepted", "kind": "kva_accepted", "timestamp": kva["accepted_at"],
            "actor_kind": "system", "actor_name": "Kunde", "description": f"{num} angenommen",
            "entity_id": kva["id"], "extras": {"number": kva.get("number"), "total": kva.get("total")},
        })
    if kva.get("rejected_at"):
        out.append({
            "id": f"kva:{kva['id']}:rejected", "kind": "kva_rejected", "timestamp": kva["rejected_at"],
            "actor_kind": "system", "actor_name": "Kunde", "description": f"{num} abgelehnt",
            "entity_id": kva["id"], "extras": {"number": kva.get("number")},
        })
    return out


def _build_timeline(org_id: str, call_id: str) -> list[dict] | None:
    """Single-pass aggregator. Returns None if the call doesn't belong to org.

    Each event is a dict matching the TimelineEvent shape in the brief:
      {id, kind, timestamp, actor_kind, actor_name, description, entity_id, extras}
    """
    client = get_service_client()

    # Tenant guard: 404 if the call isn't in this org.
    call_rows = (
        client.table("calls")
        .select("id, created_at, started_at, customer_id, elevenlabs_conversation_id")
        .eq("org_id", org_id)
        .eq("id", call_id)
        .limit(1)
        .execute()
        .data
    )
    if not call_rows:
        return None
    call = call_rows[0]

    events: list[dict] = []

    # 1. call_created — the call itself.
    call_ts = call.get("started_at") or call.get("created_at")
    if call_ts:
        events.append(
            {
                "id": f"call:{call_id}:created",
                "kind": "call_created",
                "timestamp": call_ts,
                "actor_kind": "kiki",
                "actor_name": "Kiki",
                "description": "Anruf entgegengenommen",
                "entity_id": call_id,
                "extras": {},
            }
        )

    # 2. inquiries — for each inquiry linked to this call, emit a
    # status-changed event when status has moved out of 'open' (updated_at
    # tracks the latest write). We don't have a per-change audit, so this
    # represents "current state reached at <updated_at>".
    inquiries = (
        client.table("inquiries")
        .select("id, status, title, type, created_at, updated_at")
        .eq("org_id", org_id)
        .eq("call_id", call_id)
        .execute()
        .data
        or []
    )
    inquiry_ids = [i["id"] for i in inquiries]
    for inq in inquiries:
        status = inq.get("status")
        if status and status != "open":
            ts = inq.get("updated_at") or inq.get("created_at")
            if ts:
                actor_kind, actor_name = _actor_for_status(status)
                label = _STATUS_LABEL.get(status, status)
                events.append(
                    {
                        "id": f"inquiry:{inq['id']}:status:{status}",
                        "kind": "inquiry_status_changed",
                        "timestamp": ts,
                        "actor_kind": actor_kind,
                        "actor_name": actor_name,
                        "description": f"Anfrage-Status: {label}",
                        "entity_id": inq["id"],
                        "extras": {"status": status, "title": inq.get("title")},
                    }
                )

    # 3 + 4. appointments and cost_estimates both depend only on inquiry_ids and
    # are independent of each other → fetch them concurrently (one round-trip
    # instead of two) after the inquiry barrier.
    # An appointment belongs to "this call" if it's on the call's inquiry OR the
    # agent booked it during this conversation (source_conversation_id) — agent
    # bookings create a SEPARATE inquiry, so without the conversation link their
    # confirm/reschedule/cancel events were missing from the per-call Verlauf
    # (they only showed in the customer timeline, which scopes by customer_id).
    conv_id = call.get("elevenlabs_conversation_id")
    appt_ors: list[str] = []
    if inquiry_ids:
        appt_ors.append(f"inquiry_id.in.({','.join(inquiry_ids)})")
    if conv_id:
        appt_ors.append(f"source_conversation_id.eq.{conv_id}")

    appointments: list[dict] = []
    cost_estimates: list[dict] = []
    if appt_ors or inquiry_ids:
        def _fetch_appts():
            if not appt_ors:
                return []
            return (
                client.table("appointments")
                .select(
                    "id, inquiry_id, title, scheduled_at, created_at, status, "
                    "confirmed_at, rejected_at, rejection_reason, cancelled_at, rescheduled_at, "
                    "alternative_start_time, alternative_proposed_at, "
                    "customer_proposed_start_time, customer_proposed_at"
                )
                .eq("org_id", org_id)
                .or_(",".join(appt_ors))
                .execute()
                .data
                or []
            )

        def _fetch_kvas():
            if not inquiry_ids:
                return []
            return (
                client.table("cost_estimates")
                .select(
                    "id, inquiry_id, number, total, created_at, "
                    "sent_at, accepted_at, rejected_at, status"
                )
                .eq("org_id", org_id)
                .in_("inquiry_id", inquiry_ids)
                .execute()
                .data
                or []
            )

        appointments, cost_estimates = run_parallel(_fetch_appts, _fetch_kvas)
    for appt in appointments:
        events.extend(_appointment_events(appt))
    for kva in cost_estimates:
        events.extend(_kva_events(kva))

    # Sort newest-first by timestamp (ISO strings sort correctly).
    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    return events


def build_customer_timeline(org_id: str, customer_id: str) -> list[dict] | None:
    """Customer-wide activity timeline — the SAME event shapes as the per-call
    Verlauf, aggregated across ALL of the customer's calls, inquiries,
    appointments and cost estimates. This is the 'bigger unified' timeline.
    Returns None when the customer doesn't belong to the org."""
    client = get_service_client()

    if not (
        client.table("customers").select("id").eq("org_id", org_id)
        .eq("id", customer_id).limit(1).execute().data
    ):
        return None

    events: list[dict] = []

    # All four reads depend only on customer_id and are independent of each other
    # → fetch them concurrently after the tenant barrier (4 round-trips → ~1).
    # Paged: a long-history customer can have >1000 calls/inquiries/etc.; a plain
    # .execute() would silently truncate the timeline at 1000 (oldest events vanish).
    def _calls():
        return fetch_all_rows(
            lambda: client.table("calls")
            .select("id, summary_title, started_at, created_at")
            .eq("org_id", org_id).eq("customer_id", customer_id)
            .is_("deleted_at", "null")
        )

    def _inqs():
        return fetch_all_rows(
            lambda: client.table("inquiries")
            .select("id, status, title, created_at, updated_at")
            .eq("org_id", org_id).eq("customer_id", customer_id)
            .neq("status", "deleted")
        )

    def _appts():
        return fetch_all_rows(
            lambda: client.table("appointments")
            .select(
                "id, title, scheduled_at, created_at, status, confirmed_at, rejected_at, "
                "rejection_reason, cancelled_at, rescheduled_at, alternative_start_time, "
                "alternative_proposed_at, customer_proposed_start_time, customer_proposed_at"
            )
            .eq("org_id", org_id).eq("customer_id", customer_id)
        )

    def _kvas():
        return fetch_all_rows(
            lambda: client.table("cost_estimates")
            .select("id, number, total, sent_at, accepted_at, rejected_at")
            .eq("org_id", org_id).eq("customer_id", customer_id)
        )

    call_rows, inq_rows, appt_rows, kva_rows = run_parallel(_calls, _inqs, _appts, _kvas)

    for c in call_rows:
        ts = c.get("started_at") or c.get("created_at")
        if ts:
            events.append({
                "id": f"call:{c['id']}:created", "kind": "call_created", "timestamp": ts,
                "actor_kind": "kiki", "actor_name": "Kiki",
                "description": c.get("summary_title") or "Anruf entgegengenommen",
                "entity_id": c["id"], "extras": {},
            })

    for inq in inq_rows:
        status = inq.get("status")
        if status and status != "open":
            ts = inq.get("updated_at") or inq.get("created_at")
            if ts:
                actor_kind, actor_name = _actor_for_status(status)
                events.append({
                    "id": f"inquiry:{inq['id']}:status:{status}", "kind": "inquiry_status_changed",
                    "timestamp": ts, "actor_kind": actor_kind, "actor_name": actor_name,
                    "description": f"Anfrage-Status: {_STATUS_LABEL.get(status, status)}",
                    "entity_id": inq["id"], "extras": {"status": status, "title": inq.get("title")},
                })

    for appt in appt_rows:
        events.extend(_appointment_events(appt))

    for kva in kva_rows:
        events.extend(_kva_events(kva))

    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    return events


def build_case_thread(org_id: str, inquiry_id: str) -> dict | None:
    """One Vorgang (case) = one thread. Returns the case header + a single
    chronological timeline of EVERY call (inbound + outbound, labelled), appointment,
    KVA and status change tied to this inquiry, plus the raw record lists the thread
    view renders. None when the case isn't in this org. Same event shapes as the
    per-call / customer timelines, but scoped to one case via `calls.inquiry_id` —
    exactly the link Vorgang threading made reliable for OUTBOUND calls too."""
    client = get_service_client()

    inq_rows = (
        client.table("inquiries")
        .select(
            "id, number, subject, title, type, status, notes, created_at, updated_at, "
            "customer_id, call_id, assigned_employee_id"
        )
        .eq("org_id", org_id).eq("id", inquiry_id).limit(1)
        .execute().data
    )
    if not inq_rows:
        return None
    inquiry = inq_rows[0]

    def _customer():
        cid = inquiry.get("customer_id")
        if not cid:
            return None
        rows = (client.table("customers").select("id, full_name, phone, email, customer_number")
                .eq("org_id", org_id).eq("id", cid).limit(1).execute().data)
        return rows[0] if rows else None

    def _employee():
        eid = inquiry.get("assigned_employee_id")
        if not eid:
            return None
        rows = (client.table("employees").select("id, display_name")
                .eq("org_id", org_id).eq("id", eid).limit(1).execute().data)
        return rows[0] if rows else None

    def _calls():
        return fetch_all_rows(
            lambda: client.table("calls")
            .select("id, summary_title, direction, started_at, created_at, duration_seconds, status")
            .eq("org_id", org_id).eq("inquiry_id", inquiry_id).is_("deleted_at", "null")
        )

    def _appts():
        return fetch_all_rows(
            lambda: client.table("appointments")
            .select(
                "id, inquiry_id, title, scheduled_at, created_at, status, confirmed_at, "
                "rejected_at, rejection_reason, cancelled_at, rescheduled_at, "
                "alternative_start_time, alternative_proposed_at, "
                "customer_proposed_start_time, customer_proposed_at"
            )
            .eq("org_id", org_id).eq("inquiry_id", inquiry_id)
        )

    def _kvas():
        return fetch_all_rows(
            lambda: client.table("cost_estimates")
            .select("id, number, total, status, created_at, sent_at, accepted_at, rejected_at")
            .eq("org_id", org_id).eq("inquiry_id", inquiry_id)
        )

    customer, employee, call_rows, appt_rows, kva_rows = run_parallel(
        _customer, _employee, _calls, _appts, _kvas
    )

    events: list[dict] = []

    # Calls — labelled inbound/outbound (the heart of the thread; outbound now links).
    for c in call_rows:
        ts = c.get("started_at") or c.get("created_at")
        if not ts:
            continue
        label = "Ausgehender Anruf" if c.get("direction") == "outbound" else "Eingehender Anruf"
        events.append({
            "id": f"call:{c['id']}:created", "kind": "call_created", "timestamp": ts,
            "actor_kind": "kiki", "actor_name": "Kiki",
            "description": c.get("summary_title") or label, "entity_id": c["id"],
            "extras": {"direction": c.get("direction"), "duration_seconds": c.get("duration_seconds"),
                       "status": c.get("status")},
        })

    status = inquiry.get("status")
    if status and status != "open":
        ts = inquiry.get("updated_at") or inquiry.get("created_at")
        if ts:
            actor_kind, actor_name = _actor_for_status(status)
            events.append({
                "id": f"inquiry:{inquiry['id']}:status:{status}", "kind": "inquiry_status_changed",
                "timestamp": ts, "actor_kind": actor_kind, "actor_name": actor_name,
                "description": f"Vorgang-Status: {_STATUS_LABEL.get(status, status)}",
                "entity_id": inquiry["id"], "extras": {"status": status, "title": inquiry.get("title")},
            })

    for a in appt_rows:
        events.extend(_appointment_events(a))
    for k in kva_rows:
        events.extend(_kva_events(k))

    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

    # "Offene Punkte" = pending appointments + KVAs awaiting send/answer.
    open_count = (
        sum(1 for a in appt_rows if a.get("status") == "pending")
        + sum(1 for k in kva_rows if k.get("status") in ("draft", "sent"))
    )

    return {
        "inquiry": {
            "id": inquiry["id"], "number": inquiry.get("number"), "subject": inquiry.get("subject"),
            "title": inquiry.get("title"), "type": inquiry.get("type"), "status": inquiry.get("status"),
            "notes": inquiry.get("notes"), "created_at": inquiry.get("created_at"),
            "updated_at": inquiry.get("updated_at"),
            "customer": customer, "assigned_employee": employee,
        },
        "timeline": events,
        "calls": sorted(
            call_rows, key=lambda c: c.get("started_at") or c.get("created_at") or "", reverse=True
        ),
        "appointments": sorted(appt_rows, key=lambda a: a.get("scheduled_at") or "", reverse=True),
        "cost_estimates": sorted(kva_rows, key=lambda k: k.get("created_at") or "", reverse=True),
        "open_count": open_count,
    }
