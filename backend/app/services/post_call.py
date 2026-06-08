"""ElevenLabs post-call webhook processing.

Receives the post-call payload forwarded from N8N. No audio handling — only the
conversation_id is stored; Call Logs fetches audio on demand via the ElevenLabs
API. Idempotent on conversation_id. Org resolves from agent_id in the payload.
Returns a debug-friendly result envelope per conversation (always a list).
"""

import logging
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
                .select("id, status, customer_id, title, project_id")
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
            from app.services.projects import maybe_create_project_for_appointment

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
                    maybe_create_project_for_appointment(org_id, appt, None, client)
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
        "transcript": _trim_transcript(transcript),
        "summary": analysis.get("transcript_summary"),
        "summary_title": analysis.get("call_summary_title"),
        "data_collection": _data_collection_values(analysis),
    }
    # Idempotent on conversation_id (unique). Update on conflict, no duplicates.
    upserted = (
        client.table("calls")
        .upsert(row, on_conflict="elevenlabs_conversation_id")
        .execute()
        .data
    )
    call_log_id = upserted[0]["id"] if upserted else None

    # Every INBOUND call becomes an actionable request in Call Logs.
    # OUTBOUND calls do NOT spawn their own inquiry — they are already linked to
    # the triggering case via outbound_calls.inquiry_id (set at dispatch). Letting
    # ensure_call_inquiry run here would orphan a duplicate inquiry per outbound
    # call (the bug that produced ANF-2026-0020). Inbound path unchanged.
    if call_log_id and direction != "outbound":
        from app.services.inquiries import ensure_call_inquiry

        ensure_call_inquiry(client, org_id, upserted[0])

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
