"""Technician job links — tokenized, no-login job-report form per dispatch.

Dispatch (CRM, from the appointment confirmation) creates a capability URL
``/job/<token>`` and emails it to the technician. The public form logs
start/end, collects the questionnaire + photos, and the submitted report
threads back into the appointment's Vorgang timeline. A link stays usable
until the case is closed (inquiry completed), the appointment is cancelled,
or a re-dispatch revokes it; submission freezes the report (one submit).
"""
from __future__ import annotations

import logging
import secrets
import uuid as uuid_mod
from datetime import datetime, timezone

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.common import format_address

log = logging.getLogger(__name__)

PHOTO_BUCKET = "customer-files"
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTOS = 12


class JobLinkError(ValueError):
    """User-facing German message (404/410-style failures resolved by caller)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job_link(*, org_id: str, appointment_id: str, employee_id: str) -> dict:
    """Create a fresh link for this dispatch; prior un-submitted links of the
    same appointment are revoked so exactly one live link exists per job."""
    client = get_service_client()
    appt_rows = (
        client.table("appointments")
        .select("id, inquiry_id, status")
        .eq("org_id", org_id).eq("id", appointment_id).limit(1).execute().data
    )
    if not appt_rows:
        raise JobLinkError("Termin nicht gefunden.")
    if appt_rows[0].get("status") == "cancelled":
        raise JobLinkError("Für stornierte Termine kann kein Auftrag versendet werden.")
    client.table("technician_job_links").update({"revoked_at": _now()}).eq(
        "org_id", org_id
    ).eq("appointment_id", appointment_id).is_("submitted_at", "null").is_(
        "revoked_at", "null"
    ).execute()
    row = {
        "org_id": org_id,
        "appointment_id": appointment_id,
        "inquiry_id": appt_rows[0].get("inquiry_id"),
        "employee_id": employee_id,
        "token": secrets.token_urlsafe(32),
    }
    return client.table("technician_job_links").insert(row).execute().data[0]


def job_link_url(token: str) -> str:
    base = (settings.frontend_public_url or "").rstrip("/") or "http://localhost:5173"
    return f"{base}/job/{token}"


def _load_link(token: str) -> dict:
    client = get_service_client()
    rows = (
        client.table("technician_job_links").select("*")
        .eq("token", token).limit(1).execute().data
    )
    if not rows:
        raise JobLinkError("Dieser Auftrags-Link ist ungültig.")
    link = rows[0]
    if link.get("revoked_at"):
        raise JobLinkError("Dieser Auftrags-Link wurde ersetzt — bitte den neuesten Link aus Ihrer E-Mail verwenden.")
    return link


def _load_context(link: dict) -> dict:
    """Appointment + customer + org + case state for the link's org (token is
    the capability — every query is still pinned to the link's org_id)."""
    client = get_service_client()
    org_id = link["org_id"]
    appt = (
        client.table("appointments")
        .select("id, title, scheduled_at, duration_minutes, status, location, notes, customer_id, inquiry_id")
        .eq("org_id", org_id).eq("id", link["appointment_id"]).limit(1).execute().data
    )
    appt = appt[0] if appt else None
    if not appt or appt.get("status") == "cancelled":
        raise JobLinkError("Dieser Termin wurde storniert — der Auftrag ist nicht mehr aktiv.")
    inquiry = None
    if link.get("inquiry_id"):
        inq = (
            client.table("inquiries").select("id, number, subject, title, status")
            .eq("org_id", org_id).eq("id", link["inquiry_id"]).limit(1).execute().data
        )
        inquiry = inq[0] if inq else None
        if inquiry and inquiry.get("status") == "completed" and not link.get("submitted_at"):
            raise JobLinkError("Dieser Vorgang ist bereits abgeschlossen — der Auftrags-Link ist abgelaufen.")
    customer = None
    if appt.get("customer_id"):
        c = (
            client.table("customers").select("id, full_name, phone, address")
            .eq("org_id", org_id).eq("id", appt["customer_id"]).limit(1).execute().data
        )
        customer = c[0] if c else None
    org = (
        client.table("organizations").select("id, name")
        .eq("id", org_id).limit(1).execute().data
    )
    employee = (
        client.table("employees").select("id, display_name")
        .eq("org_id", org_id).eq("id", link["employee_id"]).limit(1).execute().data
    )
    return {
        "appointment": appt,
        "inquiry": inquiry,
        "customer": customer,
        "org": org[0] if org else None,
        "employee": employee[0] if employee else None,
    }


def get_job_for_token(token: str) -> dict:
    link = _load_link(token)
    ctx = _load_context(link)
    appt, cust = ctx["appointment"], ctx["customer"]
    loc = appt.get("location")
    return {
        "org_name": (ctx["org"] or {}).get("name"),
        "technician_name": (ctx["employee"] or {}).get("display_name"),
        "case_number": (ctx["inquiry"] or {}).get("number"),
        "case_subject": (ctx["inquiry"] or {}).get("subject") or (ctx["inquiry"] or {}).get("title"),
        "appointment": {
            "title": appt.get("title"),
            "scheduled_at": appt.get("scheduled_at"),
            "duration_minutes": appt.get("duration_minutes"),
            "location": loc.get("raw") if isinstance(loc, dict) else loc,
            "notes": appt.get("notes"),
        },
        "customer": {
            "name": (cust or {}).get("full_name"),
            "phone": (cust or {}).get("phone"),
            "address": format_address((cust or {}).get("address")) if cust else None,
        },
        "started_at": link.get("started_at"),
        "finished_at": link.get("finished_at"),
        "submitted_at": link.get("submitted_at"),
        "photo_count": len(link.get("photo_paths") or []),
    }


def start_job(token: str) -> dict:
    link = _load_link(token)
    _load_context(link)  # validity check
    if link.get("submitted_at"):
        raise JobLinkError("Dieser Auftrag wurde bereits abgeschlossen.")
    if link.get("started_at"):
        return {"started_at": link["started_at"]}
    ts = _now()
    get_service_client().table("technician_job_links").update({"started_at": ts}).eq(
        "id", link["id"]
    ).execute()
    return {"started_at": ts}


def add_photo(token: str, *, filename: str, content: bytes, mime_type: str) -> dict:
    link = _load_link(token)
    ctx = _load_context(link)
    if link.get("submitted_at"):
        raise JobLinkError("Dieser Auftrag wurde bereits abgeschlossen.")
    if not (mime_type or "").startswith("image/"):
        raise JobLinkError("Nur Bilder können hochgeladen werden.")
    if len(content) > MAX_PHOTO_BYTES:
        raise JobLinkError("Das Foto ist zu groß (max. 10 MB).")
    paths = list(link.get("photo_paths") or [])
    if len(paths) >= MAX_PHOTOS:
        raise JobLinkError(f"Höchstens {MAX_PHOTOS} Fotos pro Auftrag.")
    client = get_service_client()
    safe_name = (filename or "foto.jpg").replace("/", "_")[-80:]
    path = f"{link['org_id']}/jobs/{link['id']}/{uuid_mod.uuid4().hex}_{safe_name}"
    client.storage.from_(PHOTO_BUCKET).upload(
        path, content, {"content-type": mime_type or "image/jpeg"}
    )
    paths.append(path)
    client.table("technician_job_links").update({"photo_paths": paths}).eq(
        "id", link["id"]
    ).execute()
    # Mirror into the customer's documents so the CRM shows the photos in place.
    customer = ctx.get("customer")
    if customer:
        try:
            client.table("documents").insert({
                "org_id": link["org_id"],
                "customer_id": customer["id"],
                "name": safe_name,
                "path": path,
                "category": "Einsatzbericht",
                "mime_type": mime_type or "image/jpeg",
                "is_image": True,
                "size_bytes": len(content),
            }).execute()
        except Exception as exc:  # noqa: BLE001 — photo stays in the report either way
            log.warning("technician_jobs: documents mirror failed: %s", exc)
    return {"photo_count": len(paths)}


def submit_job(token: str, report: dict) -> dict:
    """Final submit — requires an end-of-job description and ≥1 photo when the
    job was finished. The report threads into the Vorgang timeline via
    build_case_thread (read side), nothing else to write."""
    link = _load_link(token)
    _load_context(link)
    if link.get("submitted_at"):
        raise JobLinkError("Dieser Auftrag wurde bereits abgeschlossen.")
    finished = bool(report.get("job_finished"))
    description = (report.get("description") or "").strip()
    if not description:
        raise JobLinkError("Bitte beschreiben Sie kurz, was vor Ort gemacht wurde.")
    if finished and not (link.get("photo_paths") or []):
        raise JobLinkError("Bitte laden Sie mindestens ein Foto der fertigen Arbeit hoch.")
    clean = {
        "experience_good": report.get("experience_good"),
        "extra_demands": (report.get("extra_demands") or "").strip() or None,
        "site_visit_notes": (report.get("site_visit_notes") or "").strip() or None,
        "job_started": bool(report.get("job_started", True)),
        "job_finished": finished,
        "needs": [n for n in (report.get("needs") or []) if isinstance(n, str)][:10],
        "description": description[:2000],
    }
    ts = _now()
    fields = {"report": clean, "submitted_at": ts}
    if not link.get("started_at"):
        fields["started_at"] = ts
    if finished and not link.get("finished_at"):
        fields["finished_at"] = ts
    get_service_client().table("technician_job_links").update(fields).eq(
        "id", link["id"]
    ).execute()
    return {"submitted_at": ts}


def job_events_for_inquiry(org_id: str, inquiry_id: str) -> list[dict]:
    """Timeline events for build_case_thread — dispatched/started/submitted."""
    client = get_service_client()
    links = (
        client.table("technician_job_links")
        .select("id, employee_id, created_at, started_at, finished_at, submitted_at, report, photo_paths, revoked_at")
        .eq("org_id", org_id).eq("inquiry_id", inquiry_id).execute().data or []
    )
    if not links:
        return []
    emp_ids = {l["employee_id"] for l in links if l.get("employee_id")}
    names: dict[str, str] = {}
    if emp_ids:
        for e in (
            client.table("employees").select("id, display_name")
            .eq("org_id", org_id).in_("id", list(emp_ids)).execute().data or []
        ):
            names[e["id"]] = e.get("display_name")
    events: list[dict] = []
    for l in links:
        name = names.get(l.get("employee_id")) or "Techniker"
        if l.get("created_at") and not l.get("revoked_at"):
            events.append({
                "id": f"job:{l['id']}:dispatched", "kind": "technician_dispatched",
                "timestamp": l["created_at"], "actor_kind": "user", "actor_name": name,
                "description": f"Auftrags-Link an {name} gesendet",
                "entity_id": l["id"], "extras": {},
            })
        if l.get("started_at"):
            events.append({
                "id": f"job:{l['id']}:started", "kind": "technician_job_started",
                "timestamp": l["started_at"], "actor_kind": "user", "actor_name": name,
                "description": f"{name} hat den Einsatz gestartet",
                "entity_id": l["id"], "extras": {},
            })
        if l.get("submitted_at"):
            rep = l.get("report") or {}
            events.append({
                "id": f"job:{l['id']}:submitted", "kind": "technician_report_submitted",
                "timestamp": l["submitted_at"], "actor_kind": "user", "actor_name": name,
                "description": f"Einsatzbericht von {name}"
                + (" — Auftrag abgeschlossen" if rep.get("job_finished") else " — Auftrag noch offen"),
                "entity_id": l["id"],
                "extras": {"report": rep, "photo_count": len(l.get("photo_paths") or [])},
            })
    return events
