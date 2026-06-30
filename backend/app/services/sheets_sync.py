"""Google Sheets ↔ Supabase sync. THE DATABASE IS THE SOURCE OF TRUTH.

Two directions, both explicit and on-demand (no automatic write-back from a sheet edit —
past incident: editable sheets broke the workflows):

  IMPORT  (Sheets → DB): one-time / refresh seed of the legacy Twilio pool into
          `twilio_numbers`. Upserts on phone_number; never deletes.
  MIRROR  (DB → Sheets): rewrites the mirror sheet from the DB so non-tech staff can
          read the current pool / client roster. The sheet is a VIEW of the DB.

Future-proof path: the funnel already writes the pool + clients to the DB; this module
just (a) seeds the DB from the existing sheets once, and (b) mirrors back for visibility.

Ships INERT: every entry point requires SHEETS_SYNC_ENABLED + a service-account JSON +
the sheet id. The Google libraries are imported lazily so the app boots without them.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.db.supabase_client import get_service_client

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Twilio pool sheet headers (mirror of the legacy `twilio_pool` sheet, order preserved).
_POOL_HEADERS = [
    "Session_Id",
    "Phone_number",
    "Eleven_phone_id",
    "Status",
    "Assigned_agent_id",
    "Label",
    "Last_updated",
    "Notes",
]
# Final-Client sheet headers (CD Project ID -> Org ID, CD Dashboard Link -> static URL).
_CLIENT_HEADERS = [
    "Client name",
    "Voice Agent Number",
    "Email",
    "Org ID",
    "Dashboard Link",
    "Client Phone Number",
    "Agent ID",
    "Emergency Number",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_enabled() -> None:
    if not settings.sheets_sync_enabled:
        raise RuntimeError("SHEETS_SYNC_ENABLED is off")
    if not settings.google_service_account_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set")


def _gspread_client():
    """Authorized gspread client from the service account (JSON content OR a file path)."""
    try:
        import gspread  # lazy — keeps the app importable without the dep
        from google.oauth2.service_account import Credentials
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "google sheets libs missing — add gspread + google-auth to requirements"
        ) from exc
    raw = settings.google_service_account_json.strip()
    info = json.loads(raw) if raw.startswith("{") else json.load(open(raw))
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


def _worksheet(sheet_id: str):
    if not sheet_id:
        raise RuntimeError("sheet id not configured")
    return _gspread_client().open_by_key(sheet_id).sheet1


def _e164(v: object) -> str:
    s = str(v or "").strip()
    if s and not s.startswith("+"):
        s = "+" + s
    return s


# ─── IMPORT: Sheets → DB (seed the canonical pool from the legacy sheet) ───────
def import_twilio_pool() -> dict:
    """Upsert the legacy twilio_pool sheet rows into `twilio_numbers` (DB = canonical).
    Keyed on phone_number; existing rows are updated, new ones inserted; nothing deleted."""
    _ensure_enabled()
    ws = _worksheet(settings.twilio_pool_sheet_id)
    records = ws.get_all_records()  # list[dict] keyed by header row
    db = get_service_client()
    inserted = updated = skipped = 0
    for rec in records:
        phone = _e164(rec.get("Phone_number"))
        if not phone:
            skipped += 1
            continue
        status = str(rec.get("Status") or "idle").strip().lower()
        if status not in ("idle", "reserved", "assigned"):
            status = "idle"
        row = {
            "session_id": str(rec.get("Session_Id") or "") or None,
            "eleven_phone_id": str(rec.get("Eleven_phone_id") or "") or None,
            "status": status,
            "assigned_agent_id": str(rec.get("Assigned_agent_id") or "") or None,
            "label": str(rec.get("Label") or "") or None,
            "notes": str(rec.get("Notes") or "") or None,
            "last_updated": _now(),
        }
        existing = (
            db.table("twilio_numbers").select("id").eq("phone_number", phone).limit(1).execute().data
        )
        if existing:
            db.table("twilio_numbers").update(row).eq("id", existing[0]["id"]).execute()
            updated += 1
        else:
            db.table("twilio_numbers").insert({**row, "phone_number": phone}).execute()
            inserted += 1
    log.info("sheets import twilio_pool: +%d ~%d skip%d", inserted, updated, skipped)
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


# ─── MIRROR: DB → Sheets (read-only view for non-tech staff) ──────────────────
def _rewrite(sheet_id: str, headers: list[str], rows: list[list]) -> int:
    ws = _worksheet(sheet_id)
    ws.clear()
    ws.update("A1", [headers] + rows)
    return len(rows)


def mirror_twilio_pool() -> dict:
    """Rewrite the twilio_pool mirror sheet from `twilio_numbers` (DB = canonical)."""
    _ensure_enabled()
    db = get_service_client()
    data = (
        db.table("twilio_numbers")
        .select("session_id, phone_number, eleven_phone_id, status, assigned_agent_id, label, last_updated, notes")
        .order("created_at")
        .execute()
        .data
        or []
    )
    rows = [
        [
            r.get("session_id") or "",
            r.get("phone_number") or "",
            r.get("eleven_phone_id") or "",
            (r.get("status") or "").capitalize(),
            r.get("assigned_agent_id") or "",
            r.get("label") or "",
            r.get("last_updated") or "",
            r.get("notes") or "",
        ]
        for r in data
    ]
    n = _rewrite(settings.twilio_pool_sheet_id, _POOL_HEADERS, rows)
    return {"mirrored": n}


def mirror_final_clients() -> dict:
    """Rewrite the Final-Client mirror sheet from the `final_client_export` view."""
    _ensure_enabled()
    db = get_service_client()
    data = db.table("final_client_export").select("*").order("created_at").execute().data or []
    rows = [
        [
            r.get("client_name") or "",
            r.get("voice_agent_number") or "",
            r.get("email") or "",
            r.get("org_id") or "",
            r.get("dashboard_link") or "",
            r.get("client_phone_number") or "",
            r.get("agent_id") or "",
            r.get("emergency_number") or "",
        ]
        for r in data
    ]
    n = _rewrite(settings.final_client_sheet_id, _CLIENT_HEADERS, rows)
    return {"mirrored": n}
