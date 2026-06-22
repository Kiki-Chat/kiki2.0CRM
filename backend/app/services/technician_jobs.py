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
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.db.supabase_client import get_service_client
from app.services.common import format_address

log = logging.getLogger(__name__)

PHOTO_BUCKET = "customer-files"
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTOS = 30
# Hard expiry for a per-job capability link (AUTH-029). The token IS the
# credential, so a stale link must die on its own even if the case never closes.
LINK_TTL_DAYS = 30

# A technician uploads from their phone, where the browser often sends an empty
# or "application/octet-stream" content-type (especially for HEIC photos). Fall
# back to the file extension so valid camera uploads aren't wrongly rejected.
_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "heic", "heif", "webp", "bmp", "tiff"}
_EXT_CONTENT_TYPE = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "heic": "image/heic", "heif": "image/heif", "webp": "image/webp", "bmp": "image/bmp",
    "tiff": "image/tiff",
}


def _file_ext(filename: str | None) -> str:
    return (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""


def _looks_like_image(filename: str | None, mime: str | None) -> bool:
    return (mime or "").startswith("image/") or _file_ext(filename) in _IMAGE_EXTS


def _content_type_for(filename: str | None, mime: str | None) -> str:
    if (mime or "").startswith("image/"):
        return mime
    return _EXT_CONTENT_TYPE.get(_file_ext(filename), "image/jpeg")

# A technician uploads from their phone, where the browser often sends an empty
# or "application/octet-stream" content-type (especially for HEIC photos). Fall
# back to the file extension so valid camera uploads aren't wrongly rejected.
_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "heic", "heif", "webp", "bmp", "tiff"}
_EXT_CONTENT_TYPE = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "heic": "image/heic", "heif": "image/heif", "webp": "image/webp", "bmp": "image/bmp",
    "tiff": "image/tiff",
}


def _file_ext(filename: str | None) -> str:
    return (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""


def _looks_like_image(filename: str | None, mime: str | None) -> bool:
    return (mime or "").startswith("image/") or _file_ext(filename) in _IMAGE_EXTS


def _content_type_for(filename: str | None, mime: str | None) -> str:
    if (mime or "").startswith("image/"):
        return mime
    return _EXT_CONTENT_TYPE.get(_file_ext(filename), "image/jpeg")


class JobLinkError(ValueError):
    """User-facing German message (404/410-style failures resolved by caller)."""


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _is_expired(expires_at) -> bool:
    """True when a link's expires_at is set and already in the past. Tolerant of
    the timestamptz coming back as an ISO string (Supabase) or a datetime."""
    if not expires_at:
        return False
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < _now_dt()


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
    created = _now_dt()
    row = {
        "org_id": org_id,
        "appointment_id": appointment_id,
        "inquiry_id": appt_rows[0].get("inquiry_id"),
        "employee_id": employee_id,
        "token": secrets.token_urlsafe(32),
        # Hard expiry: created_at + 30 days (AUTH-029). created_at also defaults
        # to now() server-side; we set it explicitly so expires_at is exactly
        # +TTL and never depends on clock skew between insert and default.
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(days=LINK_TTL_DAYS)).isoformat(),
    }
    return client.table("technician_job_links").insert(row).execute().data[0]


def job_link_url(token: str) -> str:
    base = settings.public_app_url
    return f"{base}/job/{token}"


def technician_portal_url(token: str) -> str:
    base = settings.public_app_url
    return f"{base}/techniker/{token}"


def rotate_portal_token(org_id: str, employee_id: str, *, notify=None) -> dict:
    """Re-mint a technician's standing portal token (AUTH-029): the OLD
    /techniker/<token> link instantly stops working and a fresh one is issued.
    Used when a token may be compromised (lost phone, ex-technician, shared link).

    Pinned to the org; the employee must be a non-deleted technician. Triggers the
    existing welcome-email path (so the technician gets their new link) via the
    optional ``notify`` callback — the route passes the real sender; tests pass a
    mock. Never leaks the raw token in the return value.
    """
    client = get_service_client()
    rows = (
        client.table("employees")
        .select("id, org_id, display_name, email, is_technician, deleted, technician_portal_token")
        .eq("org_id", org_id).eq("id", employee_id).limit(1).execute().data
    )
    if not rows or rows[0].get("deleted"):
        raise JobLinkError("Mitarbeiter nicht gefunden.")
    emp = rows[0]
    if not emp.get("is_technician"):
        raise JobLinkError("Dieser Mitarbeiter ist kein Techniker.")
    new_token = secrets.token_urlsafe(32)
    client.table("employees").update(
        {"technician_portal_token": new_token}
    ).eq("org_id", org_id).eq("id", employee_id).execute()
    portal_url = technician_portal_url(new_token)
    email_sent = False
    if emp.get("email") and notify is not None:
        try:
            org_name = None
            org = client.table("organizations").select("name").eq("id", org_id).limit(1).execute().data
            org_name = org[0].get("name") if org else None
            notify(org_id, org_name, emp.get("display_name"), emp["email"], portal_url)
            email_sent = True
        except Exception as exc:  # noqa: BLE001 — email must never block the rotate
            log.warning("rotate_portal_token: welcome email failed (org=%s emp=%s): %s",
                        org_id, employee_id, exc)
    # NEVER return the raw token (matches the list/create pattern — only the URL,
    # which the admin sees, plus whether the technician was notified).
    return {
        "id": employee_id,
        "technician_portal_url": portal_url,
        "email_sent": email_sent,
    }


def get_technician_portal(token: str) -> dict:
    """Public, no-login: a technician's own jobs (past + current) for their
    standing portal token. Pinned to the technician's org (the token IS the
    credential — same model as the per-job link). Newest first; each job carries
    its per-job form token so the technician can open / continue the report."""
    client = get_service_client()
    emp_rows = (
        client.table("employees")
        .select("id, org_id, display_name, deleted")
        .eq("technician_portal_token", token).limit(1).execute().data
    )
    if not emp_rows or emp_rows[0].get("deleted"):
        raise JobLinkError("Dieser Techniker-Link ist ungültig.")
    emp = emp_rows[0]
    org_id = emp["org_id"]
    org = client.table("organizations").select("name").eq("id", org_id).limit(1).execute().data
    links = (
        client.table("technician_job_links")
        .select("token, appointment_id, started_at, finished_at, submitted_at, revoked_at, expires_at, photo_paths, created_at")
        .eq("org_id", org_id).eq("employee_id", emp["id"])
        .order("created_at", desc=True).limit(100).execute().data
        or []
    )
    appt_ids = [l["appointment_id"] for l in links if l.get("appointment_id")]
    appts: dict[str, dict] = {}
    if appt_ids:
        for a in (
            client.table("appointments")
            .select("id, title, scheduled_at, status, customer_id, location")
            .eq("org_id", org_id).in_("id", appt_ids).execute().data or []
        ):
            appts[a["id"]] = a
    cust_ids = list({a.get("customer_id") for a in appts.values() if a.get("customer_id")})
    custs: dict[str, dict] = {}
    if cust_ids:
        for c in (
            client.table("customers").select("id, full_name, address")
            .eq("org_id", org_id).in_("id", cust_ids).execute().data or []
        ):
            custs[c["id"]] = c

    jobs: list[dict] = []
    for l in links:
        # Hide superseded/cancelled/expired links that never produced a report;
        # keep every SUBMITTED one forever — that's the technician's track record.
        if l.get("revoked_at") and not l.get("submitted_at"):
            continue
        if _is_expired(l.get("expires_at")) and not l.get("submitted_at"):
            continue
        a = appts.get(l.get("appointment_id")) or {}
        if a.get("status") == "cancelled" and not l.get("submitted_at"):
            continue
        cust = custs.get(a.get("customer_id")) or {}
        loc = a.get("location")
        addr = (
            format_address(cust.get("address")) if cust.get("address")
            else (loc.get("raw") if isinstance(loc, dict) else loc)
        )
        status = (
            "abgeschlossen" if l.get("submitted_at")
            else "läuft" if l.get("started_at")
            else "offen"
        )
        jobs.append({
            "job_token": l["token"],
            "title": a.get("title") or "Termin",
            "scheduled_at": a.get("scheduled_at"),
            "customer_name": cust.get("full_name"),
            "customer_address": addr,
            "status": status,
            "submitted_at": l.get("submitted_at"),
            "photo_count": len(l.get("photo_paths") or []),
        })
    return {
        "technician_name": emp.get("display_name"),
        "org_name": (org[0]["name"] if org else None),
        "jobs": jobs,
    }


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
    if _is_expired(link.get("expires_at")):
        raise JobLinkError("Dieser Link ist abgelaufen.")
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
    # Stamp the first time the technician actually opens the link (AUTH-029
    # audit signal — was the dispatch link ever seen?). Once only.
    if not link.get("first_viewed_at"):
        ts = _now()
        try:
            get_service_client().table("technician_job_links").update(
                {"first_viewed_at": ts}
            ).eq("id", link["id"]).is_("first_viewed_at", "null").execute()
            link["first_viewed_at"] = ts
        except Exception as exc:  # noqa: BLE001 — audit stamp must never block the view
            log.warning("technician_jobs: first_viewed_at stamp failed: %s", exc)
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
    if not _looks_like_image(filename, mime_type):
        raise JobLinkError("Nur Bilder können hochgeladen werden.")
    if len(content) > MAX_PHOTO_BYTES:
        raise JobLinkError("Das Foto ist zu groß (max. 10 MB).")
    paths = list(link.get("photo_paths") or [])
    if len(paths) >= MAX_PHOTOS:
        raise JobLinkError(f"Höchstens {MAX_PHOTOS} Fotos pro Auftrag.")
    client = get_service_client()
    safe_name = (filename or "foto.jpg").replace("/", "_")[-80:]
    path = f"{link['org_id']}/jobs/{link['id']}/{uuid_mod.uuid4().hex}_{safe_name}"
    content_type = _content_type_for(filename, mime_type)
    client.storage.from_(PHOTO_BUCKET).upload(
        path, content, {"content-type": content_type}
    )
    paths.append(path)
    client.table("technician_job_links").update({"photo_paths": paths}).eq(
        "id", link["id"]
    ).execute()
    # Mirror into the customer's documents so the CRM shows the photos in place.
    # Stamped with inquiry + Fall (case) + technician name, so the case's
    # Dokumente tab shows WHO uploaded each Einsatzbericht photo (item 6).
    customer = ctx.get("customer")
    if customer:
        try:
            case_id = None
            if link.get("inquiry_id"):
                inq = (
                    client.table("inquiries").select("case_id")
                    .eq("org_id", link["org_id"]).eq("id", link["inquiry_id"])
                    .limit(1).execute().data
                )
                case_id = inq[0].get("case_id") if inq else None
            technician = (ctx.get("employee") or {}).get("display_name")
            client.table("documents").insert({
                "org_id": link["org_id"],
                "customer_id": customer["id"],
                "inquiry_id": link.get("inquiry_id"),
                "case_id": case_id,
                "name": safe_name,
                "path": path,
                "category": "Einsatzbericht",
                "mime_type": content_type,
                "is_image": True,
                "size_bytes": len(content),
                "uploaded_by_name": f"Techniker: {technician}" if technician else None,
            }).execute()
        except Exception as exc:  # noqa: BLE001 — photo stays in the report either way
            # DO NOT swallow silently: the photo is already in photo_paths, so a
            # failed documents insert means the report and the customer's Dokumente
            # tab have diverged. Log loudly with the exact link + path so it can be
            # reconciled (AUTH-029).
            log.warning(
                "technician_jobs: documents mirror FAILED — photo_paths/documents "
                "diverged for link=%s org=%s path=%s: %s",
                link.get("id"), link.get("org_id"), path, exc,
            )
    return {"photo_count": len(paths)}


def submit_job(
    token: str,
    report: dict,
    *,
    submitted_ip: str | None = None,
    submitted_user_agent: str | None = None,
) -> dict:
    """Final submit — requires an end-of-job description and ≥1 photo (always,
    not only when finished). The report threads into the Vorgang timeline via
    build_case_thread (read side), nothing else to write.

    submitted_ip / submitted_user_agent are forensic audit fields (AUTH-029):
    who actually filed this report, from where. Passed by the route."""
    link = _load_link(token)
    _load_context(link)
    if link.get("submitted_at"):
        raise JobLinkError("Dieser Auftrag wurde bereits abgeschlossen.")
    finished = bool(report.get("job_finished"))
    description = (report.get("description") or "").strip()
    if not description:
        raise JobLinkError("Bitte beschreiben Sie kurz, was vor Ort gemacht wurde.")
    if not (link.get("photo_paths") or []):
        raise JobLinkError("Bitte laden Sie mindestens ein Foto hoch.")
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
    if submitted_ip:
        fields["submitted_ip"] = submitted_ip[:64]
    if submitted_user_agent:
        fields["submitted_user_agent"] = submitted_user_agent[:512]
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
