"""ElevenLabs post-call webhook processing.

Receives the post-call payload forwarded from N8N. No audio handling — only the
conversation_id is stored; Call Logs fetches audio on demand via the ElevenLabs
API. Idempotent on conversation_id. Org resolves from agent_id in the payload.
Returns a debug-friendly result envelope per conversation (always a list).
"""

import logging
import re
import threading
import time
from datetime import datetime, timezone

from app.db.realtime import broadcast_new_call
from app.db.supabase_client import get_service_client

logger = logging.getLogger(__name__)


def _now_iso_ms() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _fire_level3_confirmations(org_id: str, conversation_id: str | None) -> None:
    """At autonomy level 3, auto-confirm the appointments this call just booked.

    Spawns a daemon thread so the confirmation call+email never block post-call
    ingest. The work: read agent_configs.kiki_level; return immediately if != 3;
    find this org's pending appointments correlated to THIS conversation
    (source_conversation_id) and, for each, flip status→'confirmed' + stamp
    confirmed_at, then fire notify_appointment_outcome(..., 'confirm').

    Why POST-call: book_appointment lands L3 bookings as 'pending' too, and the
    confirmation only fires here — so the outbound confirmation call never
    collides with the still-active inbound booking call. The _process_one
    `already_processed` dedup guarantees this runs at most once per conversation,
    so retries don't double-confirm. Wrapped in try/except end-to-end: a failure
    here must NEVER break post-call ingest."""
    if not conversation_id:
        return

    def _run() -> None:
        try:
            client = get_service_client()
            cfg = (
                client.table("agent_configs")
                .select("appointments_enabled, appointments_level, kiki_level")
                .eq("org_id", org_id)
                .limit(1)
                .execute()
                .data
            )
            row = cfg[0] if cfg else {}
            if row.get("appointments_enabled") is False:
                return
            level = row.get("appointments_level")
            if level is None:
                level = row.get("kiki_level")
            try:
                level = int(level) if level is not None else 2
            except (TypeError, ValueError):
                level = 2
            if level != 3:
                return

            pending = (
                client.table("appointments")
                .select("id, status, customer_id, title, case_id")
                .eq("org_id", org_id)
                .eq("source_conversation_id", conversation_id)
                .eq("status", "pending")
                .execute()
                .data
                or []
            )
            if not pending:
                return

            from app.services.appointment_notify import notify_appointment_outcome
            from app.services.projects import maybe_create_case_for_appointment

            for appt in pending:
                appt_id = appt["id"]
                try:
                    # Idempotent flip: only update rows STILL 'pending'. PostgREST
                    # returns the rows it actually changed, so if two overlapping
                    # post-call deliveries race, exactly ONE update flips the row
                    # and gets a non-empty result — the loser sees [] and skips the
                    # notify, so the customer never gets a DUPLICATE confirmation
                    # call/email. (This is the OUTBOUND, real-customer path.)
                    confirmed = (
                        client.table("appointments")
                        .update(
                            {
                                "status": "confirmed",
                                "confirmed_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        .eq("org_id", org_id)
                        .eq("id", appt_id)
                        .eq("status", "pending")
                        .execute()
                        .data
                    )
                    if not confirmed:
                        continue  # already confirmed by a concurrent delivery
                    notify_appointment_outcome(org_id, appt_id, "confirm")
                    maybe_create_case_for_appointment(org_id, appt, None, client)
                except Exception:  # noqa: BLE001 — one bad appt must not stop the rest
                    logger.exception(
                        "L3 auto-confirm failed for appointment %s (conv %s)",
                        appt_id, conversation_id,
                    )
        except Exception:  # noqa: BLE001 — never break post-call ingest
            logger.exception(
                "L3 auto-confirm sweep failed (org %s, conv %s)",
                org_id, conversation_id,
            )

    threading.Thread(target=_run, daemon=True).start()


def _extract(item) -> tuple[dict | None, str]:
    """Return (elevenlabs `data` object, payload_format) from any wrapper shape."""
    if not isinstance(item, dict):
        return None, "unknown"
    # N8N item wrapper: { headers, body: { type, event_timestamp, data } }
    if isinstance(item.get("body"), dict):
        body = item["body"]
        if isinstance(body.get("data"), dict):
            return body["data"], "envelope"
        if body.get("conversation_id"):
            return body, "flat"
    # ElevenLabs envelope: { type, event_timestamp, data }
    if isinstance(item.get("data"), dict):
        return item["data"], "envelope"
    # Flat: data fields at top level
    if item.get("conversation_id"):
        return item, "flat"
    return None, "unknown"


def _normalize(payload) -> list[tuple[dict | None, str]]:
    if isinstance(payload, list):
        return [_extract(el) for el in payload] or [(None, "unknown")]
    return [_extract(payload)]


def _trim_transcript(transcript) -> list[dict]:
    out = []
    for turn in transcript or []:
        out.append(
            {
                "role": turn.get("role"),
                "message": turn.get("message"),
                "time_in_call_secs": turn.get("time_in_call_secs"),
                "tool_calls": [
                    tc.get("tool_name") for tc in (turn.get("tool_calls") or [])
                ],
                "tool_results": [
                    {"tool_name": tr.get("tool_name"), "is_error": tr.get("is_error")}
                    for tr in (turn.get("tool_results") or [])
                ],
            }
        )
    return out


def _data_collection_values(analysis: dict) -> dict:
    results = (analysis or {}).get("data_collection_results") or {}
    return {k: v.get("value") for k, v in results.items() if isinstance(v, dict)}


# ─── missed-call detection + writer (CALL-039) ───────────────────────────────
# The missed_calls table feeds BOTH the `missed_callback` outbound occasion
# (services/outbound_occasions.py) AND the `callback_owed` Open Action
# (routes/actions.py:_callback_owed reads status='pending'). Both consumers were
# fully wired but NOTHING wrote the table, so a genuinely-abandoned inbound call
# left no callback trail. This writer closes that gap.
#
# A post-call webhook DOES fire for an inbound leg the caller abandoned almost
# immediately (connected, agent greeted, caller hung up before stating a concern).
# We treat such a call as "missed" so the team rings back. Deliberately
# CONSERVATIVE — a call that captured ANYTHING actionable must never be flagged:
_MISSED_MAX_SECONDS = 15  # abandoned within the greeting window


def _is_missed_inbound(
    direction: str | None,
    *,
    caller_number: str | None,
    duration_seconds,
    trimmed: list[dict],
    summary: str | None,
    customer_concern: bool,
    call_successful,
) -> bool:
    """True when an INBOUND call looks abandoned before any concern was captured.

    Requires a usable caller number (we have to be able to ring back). Flags only
    when NOTHING actionable came out of the call: no caller turn in the transcript,
    no transcript summary, and no captured customer concern. A very short duration
    OR an explicit ``analysis.call_successful == 'failure'`` confirms abandonment.
    """
    if direction != "inbound":
        return False
    if not caller_number or not str(caller_number).strip():
        return False
    if customer_concern:
        return False  # a concern was captured → it's a real, handled call
    # Any substantive caller turn means the caller actually engaged.
    if any((t.get("role") == "user" and (t.get("message") or "").strip()) for t in trimmed):
        return False
    if (summary or "").strip():
        return False
    try:
        dur = float(duration_seconds) if duration_seconds is not None else None
    except (TypeError, ValueError):
        dur = None
    short = dur is not None and dur <= _MISSED_MAX_SECONDS
    failed = str(call_successful or "").lower() == "failure"
    return short or failed


def record_missed_call(
    client,
    org_id: str,
    *,
    caller_number: str,
    customer_id: str | None = None,
    missed_at: str | None = None,
) -> str | None:
    """Insert a `missed_calls` row (status='pending') so the team owes a callback.

    Idempotent on (org_id, caller_number): if a still-pending row already exists
    for this caller we DON'T stack a second one (avoids N callback actions for one
    repeat-dialer). Returns the row id (existing or new), or None on failure.
    Best-effort — never raises into post-call ingest.
    """
    try:
        existing = (
            client.table("missed_calls")
            .select("id")
            .eq("org_id", org_id)
            .eq("caller_number", caller_number)
            .eq("status", "pending")
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing:
            return existing[0]["id"]
        row = {
            "org_id": org_id,
            "caller_number": caller_number,
            "status": "pending",
        }
        if customer_id:
            row["customer_id"] = customer_id
        if missed_at:
            row["missed_at"] = missed_at
        inserted = client.table("missed_calls").insert(row).execute().data or []
        return inserted[0]["id"] if inserted else None
    except Exception:  # noqa: BLE001 — never break post-call ingest over a callback row
        logger.warning("record_missed_call failed (org %s, caller %s)", org_id, caller_number)
        return None


# ─── phantom-capture detector (eval 2026-06-11: 3/23 real calls promised
# "Anliegen aufgenommen" with NO write-tool call — the request silently
# evaporated). Conservative claim patterns on purpose: generic reassurances
# ("wir melden uns") are excluded, only explicit capture/forward claims count.
_CAPTURE_CLAIM_RE = re.compile(
    r"anliegen aufgenommen|habe alles aufgenommen|nehme ihr anliegen"
    r"|ich notiere|notiert\b|geben? (wir |das |es )+(so )?weiter"
    r"|leite .{0,30}weiter|weitergeleitet",
    re.IGNORECASE,
)
_WRITE_TOOLS = {
    "hk_createInquiry", "hk_bookAppointment", "hk_changeAppointment",
    "hk_cancelAppointment", "hk_updateCustomerData", "hk_draftCostEstimate",
    "hk_transferCall", "transfer_to_number",
}


def _phantom_capture(trimmed: list[dict]) -> bool:
    """True when the agent CLAIMED the caller's concern was captured/forwarded
    but no write tool was even attempted in the call. Stored as
    data_collection.phantom_capture (no schema change) and surfaced as a badge
    in the call log so staff re-check the call instead of trusting the claim."""
    claimed = wrote = False
    for t in trimmed:
        if t.get("role") == "agent" and _CAPTURE_CLAIM_RE.search(t.get("message") or ""):
            claimed = True
        for name in t.get("tool_calls") or []:
            if name in _WRITE_TOOLS:
                wrote = True
    return claimed and not wrote


def _result(
    status: str,
    conversation_id,
    agent_id,
    fmt: str,
    started: float,
    *,
    call_log_id=None,
    org_id=None,
    skip_reason=None,
    transcript_received=False,
    direction=None,
    kunde_matched=None,
    anfrage_matched=None,
) -> dict:
    return {
        "status": status,
        "conversationId": conversation_id,
        "callLogId": call_log_id,
        "orgId": org_id,
        "agentId": agent_id,
        "skipReason": skip_reason,
        "processedAt": _now_iso_ms(),
        "transcriptReceived": transcript_received,
        "processingTimeMs": int((time.time() - started) * 1000),
        "authMethod": "x-heykiki-secret",
        "payloadFormat": fmt,
        "direction": direction,
        "kundeMatched": kunde_matched,
        "anfrageMatched": anfrage_matched,
        "recordingScheduled": False,
    }


def _process_one(data: dict | None, fmt: str) -> dict:
    started = time.time()
    if not data:
        return _result("skipped", None, None, fmt, started, skip_reason="unparseable_payload")

    conversation_id = data.get("conversation_id")
    agent_id = data.get("agent_id")
    transcript = data.get("transcript") or []
    transcript_received = bool(transcript)

    client = get_service_client()
    org = (
        client.table("organizations")
        .select("id")
        .eq("elevenlabs_agent_id", agent_id)
        .limit(1)
        .execute()
        .data
    )
    if not org:
        return _result(
            "skipped", conversation_id, agent_id, fmt, started,
            skip_reason="unknown_agent", transcript_received=transcript_received,
        )
    org_id = org[0]["id"]

    # ─── Dedup early (P0.2) ──────────────────────────────────────────────────
    # Defense against N8N / ElevenLabs retries on the same conversation_id within
    # milliseconds. The DB-level `elevenlabs_conversation_id text unique` constraint
    # (0001_init_schema.sql) prevents the row from duplicating, but without this
    # short-circuit each retry would still run get_or_create_customer, broadcast,
    # and ensure_call_inquiry — wasted work and unnecessary realtime noise.
    #
    # A row counts as "fully processed" when status=completed AND it has either
    # a summary or a transcript. A partial row (e.g. the first webhook crashed
    # mid-processing before analysis was filled) is NOT skipped — we want the
    # retry to complete the work.
    if conversation_id:
        prior = (
            client.table("calls")
            .select("id, status, summary, transcript")
            .eq("org_id", org_id)
            .eq("elevenlabs_conversation_id", conversation_id)
            .limit(1)
            .execute()
            .data
        )
        if prior:
            row = prior[0]
            already_done = (
                row.get("status") == "completed"
                and (row.get("summary") or (row.get("transcript") or []))
            )
            if already_done:
                return _result(
                    "skipped", conversation_id, agent_id, fmt, started,
                    call_log_id=row["id"], org_id=org_id,
                    skip_reason="already_processed",
                    transcript_received=transcript_received,
                )

    metadata = data.get("metadata") or {}
    phone_call = metadata.get("phone_call") or {}
    analysis = data.get("analysis") or {}
    direction = phone_call.get("direction")
    caller_number = phone_call.get("external_number")

    # ─── started_at fallback cascade (P0.3) ───────────────────────────────
    # ElevenLabs/N8N payloads vary: usually metadata.start_time_unix_secs is
    # populated, but linktest / minimal-metadata payloads can lack it. Without
    # this cascade the row gets started_at=NULL and the Call Logs list renders
    # the timestamp as "—" (e.g. "Eingehend · — · 1:00" for Petra Linktest).
    # Cascade: metadata.start_time_unix_secs → metadata.start_time →
    # phone_call.start_time_unix_secs → now() as last resort.
    start_value = (
        metadata.get("start_time_unix_secs")
        or metadata.get("start_time")
        or phone_call.get("start_time_unix_secs")
    )
    started_at: str | None = None
    if start_value is not None:
        try:
            started_at = datetime.fromtimestamp(float(start_value), tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            started_at = None
    if started_at is None:
        # Better than NULL for list ordering / display — webhook received time
        # is at most a few seconds after the call actually started.
        started_at = datetime.now(tz=timezone.utc).isoformat()

    # Link a customer: Caller-ID first, then the AI-extracted phone/name.
    # Creates the customer when no match exists so no-Caller-ID calls (Viber,
    # withheld numbers) still link cleanly.
    from app.services.customers import get_or_create_customer

    dc_values = _data_collection_values(analysis)

    def _ok(v: str | None) -> bool:
        return bool(v) and v.strip().lower() not in (
            "", "unbekannt", "keiner", "anonymous",
        )

    link_phone = caller_number if _ok(caller_number) else None
    if not link_phone and _ok(dc_values.get("customer_phone")):
        link_phone = dc_values["customer_phone"]
    dc_name = dc_values.get("customer_name") if _ok(dc_values.get("customer_name")) else None
    dc_addr = dc_values.get("customer_address") if _ok(dc_values.get("customer_address")) else None

    customer_id = None
    kunde_matched = False
    if link_phone or dc_name:
        customer = get_or_create_customer(
            org_id, phone=link_phone, name=dc_name, address=dc_addr
        )
        customer_id = customer["id"]
        kunde_matched = True

    # Match an open inquiry for that customer (debug signal).
    anfrage_matched = False
    if customer_id:
        inq = (
            client.table("inquiries")
            .select("id")
            .eq("org_id", org_id)
            .eq("customer_id", customer_id)
            .neq("status", "deleted")
            .limit(1)
            .execute()
            .data
        )
        anfrage_matched = bool(inq)

    trimmed = _trim_transcript(transcript)
    dc = _data_collection_values(analysis)
    if _phantom_capture(trimmed):
        # Stored inside the existing jsonb (no DDL) — the call-log badge and any
        # later analytics read it from here.
        dc["phantom_capture"] = True
        logger.warning(
            "phantom capture detected (org %s, conv %s): agent claimed the "
            "concern was recorded but no write tool was called",
            org_id, conversation_id,
        )
    row = {
        "org_id": org_id,
        "elevenlabs_conversation_id": conversation_id,
        "agent_id": agent_id,
        "customer_id": customer_id,
        "caller_number": caller_number,
        "direction": direction if direction in ("inbound", "outbound") else None,
        "started_at": started_at,
        "duration_seconds": metadata.get("call_duration_secs"),
        "status": "completed",
        "transcript": trimmed,
        "summary": analysis.get("transcript_summary"),
        "summary_title": analysis.get("call_summary_title"),
        "data_collection": dc,
    }
    # Idempotent on conversation_id (unique). Update on conflict, no duplicates.
    upserted = (
        client.table("calls")
        .upsert(row, on_conflict="elevenlabs_conversation_id")
        .execute()
        .data
    )
    call_log_id = upserted[0]["id"] if upserted else None

    # ─── Missed-call writer (CALL-039) ───────────────────────────────────────
    # An INBOUND call the caller abandoned before stating a concern leaves no
    # actionable trail otherwise. Record it in missed_calls so the team owes a
    # callback: that single row drives BOTH the `callback_owed` Open Action
    # (routes/actions.py) and the `missed_callback` outbound occasion. Conservative
    # detection (see _is_missed_inbound) so a real, handled call is never flagged.
    # Best-effort — never breaks ingest.
    if direction == "inbound":
        try:
            concern_captured = bool(
                dc.get("issue_summary")
                or dc.get("ultimate_summary")
                or dc.get("next_action")
                or dc.get("customer_concern")
            )
            if _is_missed_inbound(
                direction,
                caller_number=caller_number,
                duration_seconds=metadata.get("call_duration_secs"),
                trimmed=trimmed,
                summary=analysis.get("transcript_summary"),
                customer_concern=concern_captured,
                call_successful=analysis.get("call_successful"),
            ):
                record_missed_call(
                    client,
                    org_id,
                    caller_number=caller_number,
                    customer_id=customer_id,
                    missed_at=started_at,
                )
        except Exception:  # noqa: BLE001 — never break post-call ingest
            logger.warning("missed-call recording failed (conv %s)", conversation_id)

    # Every INBOUND call becomes an actionable request in Call Logs.
    # OUTBOUND calls do NOT spawn their own inquiry — they are already linked to
    # the triggering case via outbound_calls.inquiry_id (set at dispatch). Letting
    # ensure_call_inquiry run here would orphan a duplicate inquiry per outbound
    # call (the bug that produced ANF-2026-0020). Inbound path unchanged.
    if call_log_id and direction != "outbound":
        from app.services.inquiries import ensure_call_inquiry

        ensure_call_inquiry(client, org_id, upserted[0])
    elif call_log_id and direction == "outbound":
        # OUTBOUND: tie the call to the case that TRIGGERED it (via the outbound_calls
        # ledger) so the Vorgang thread + call-log action buttons resolve. Outbound
        # never spawns its own inquiry. Best-effort — must never break ingest.
        try:
            from app.services.inquiries import link_outbound_call_to_case

            link_outbound_call_to_case(client, org_id, upserted[0])
        except Exception:  # noqa: BLE001 — never break post-call ingest
            logger.warning("outbound case-link failed (conv %s)", conversation_id)

    # PDS auto-sync (n8n "Log Call" workflow, now native): when the org has the
    # PDS integration with Automatische Synchronisation ON, every ingested call
    # is logged into PDS as an Aufgabe. Best-effort — never breaks ingest.
    if call_log_id:
        from app.services.pds import safe_auto_log_call

        safe_auto_log_call(client, org_id, upserted[0])

    # AI enrichment (our-LLM-over-transcript): structured bullet summary + intent
    # flags (KVA/Rechnung/Termin) + pre-fill fields. Powers the bullet summary,
    # smarter form pre-fill, and the kva_suggested/invoice_suggested Open Actions.
    # Best-effort, no-op without OPENAI_API_KEY — never breaks ingest.
    if call_log_id:
        from app.services.call_enrichment import safe_enrich

        safe_enrich(client, org_id, upserted[0])

    # Category back-fill: when the agent booked without (or with an unknown)
    # `kategorie`, classify the call summary against the org's Terminkategorien
    # so the Offene-Aktion card arrives pre-filled. Best-effort, never breaks
    # ingest — and it runs BEFORE level-3 confirmation so an auto-confirmed
    # appointment already carries its category/duration/employee.
    try:
        from app.services.appointment_classifier import classify_and_apply

        classify_and_apply(client, org_id, conversation_id, row.get("summary"))
    except Exception:  # noqa: BLE001 — never break post-call ingest
        logger.warning("appointment auto-categorization failed (conv %s)", conversation_id)

    # Level-3 auto-confirmation fires POST-call (in a background thread) so the
    # outbound confirmation call never collides with the still-active booking
    # call. No-op unless the org is at autonomy level 3. The `already_processed`
    # dedup above prevents this from re-firing on N8N/ElevenLabs retries.
    _fire_level3_confirmations(org_id, conversation_id)

    # Topic 18: re-call if an OUTBOUND call hung up within the org's short-hangup
    # window (best-effort; no-op unless the org enabled short-hangup recall).
    if direction == "outbound" and conversation_id:
        try:
            from app.services.outbound_dispatch import schedule_short_hangup_retry

            schedule_short_hangup_retry(
                client, org_id, conversation_id, row.get("duration_seconds")
            )
        except Exception:  # noqa: BLE001 — never break post-call ingest
            logger.warning("short-hangup retry scheduling failed (conv %s)", conversation_id)

    broadcast_new_call(
        org_id,
        {
            "call_id": call_log_id,
            "conversation_id": conversation_id,
            "caller_number": caller_number,
            "summary_title": analysis.get("call_summary_title"),
        },
    )

    return _result(
        "processed", conversation_id, agent_id, fmt, started,
        call_log_id=call_log_id, org_id=org_id,
        transcript_received=transcript_received, direction=direction,
        kunde_matched=kunde_matched, anfrage_matched=anfrage_matched,
    )


def process_post_call(payload) -> list[dict]:
    return [_process_one(data, fmt) for data, fmt in _normalize(payload)]
