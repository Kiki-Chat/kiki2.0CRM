"""PDS-Software integration — NATIVE port of the two n8n workflows
("PDS - Log Call BolteKG" + "PDS - User Greeting Flow BolteKG", Amber 2026-06-12).

The n8n flows are the contract; this module replicates them 1:1 so the CRM can
replace the n8n webhooks without the PDS side noticing:

  LOG CALL   phone +→00 → person/listpersonen (suchwort) → found: Aufgabe via
             crm/createaufgabe attached to the personUUID; not found: Aufgabe
             without person + "manuell zuordnen" note. Subject normalised into
             the 9 PDS categories; description = the German "📞 ANRUFPROTOKOLL".
  GREETING   phone → lookup → {"greeting": "Hallo {Vorname} {Name} , Willkommen
             zurück.", "status": "found"} | new-caller greeting ("status":"new").
  CREATE     fullName+phone(+address) → person/create (PRIVATPERSON, apiID=
  CONTACT    00-phone) → createEKommunikationsweg (MOBIL/PRIVAT) → optional
             createPostKommunikationsweg (HAUPTANSCHRIFT, Deutschland) →
             {"message", "status": "created", "personUUID"}.

Config lives in ``pds_configs`` (api_url + Bearer key encrypted at rest, Fernet);
auto-sync is invoked best-effort from post-call ingest — a PDS failure must
never break call processing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.core.crypto import decrypt
from app.db.supabase_client import get_service_client

log = logging.getLogger(__name__)

_TIMEOUT = 15.0
_BERLIN = ZoneInfo("Europe/Berlin")

# n8n "Create Call Log Task" node: the PDS Aufgaben-Typ. Per-org override via
# pds_configs.sync_entities.task_type_uuid (tenant UUIDs differ); this default
# is the BolteKG demo tenant's type.
DEFAULT_TASK_TYPE_UUID = "92ff1220-74cf-4fa8-9b0e-ebacb02705bf"

# n8n "Process Call Data": the valid PDS subject categories.
VALID_SUBJECTS = [
    "Neuer Benutzer",
    "Notdienstanfrage",
    "Angebotsanfrage",
    "Kundendienstanfrage",
    "Terminanfrage",
    "Terminänderung",
    "Allgemeine Anfrage",
    "Beschwerde",
    "Rückruf",
]

# Our inquiry types → PDS categories (when the agent payload has no explicit subject).
_TYPE_TO_SUBJECT = {
    "appointment_request": "Terminanfrage",
    "appointment": "Terminanfrage",
    "offer": "Angebotsanfrage",
    "recall": "Rückruf",
    "complaint": "Beschwerde",
    "emergency": "Notdienstanfrage",
}


class PdsError(Exception):
    """User-facing PDS failure (config missing, HTTP/auth errors)."""


# ─── Config + HTTP ────────────────────────────────────────────────────────────
def get_config(client, org_id: str) -> dict | None:
    rows = client.table("pds_configs").select("*").eq("org_id", org_id).limit(1).execute().data
    return rows[0] if rows else None


def _ready(cfg: dict | None) -> bool:
    return bool(cfg and (cfg.get("api_url") or "").strip() and cfg.get("api_key_encrypted"))


def _post(cfg: dict, path: str, body: dict) -> dict:
    """One PDS REST call: POST {api_url}/pds/rest/api/{path} with the Bearer key."""
    base = (cfg.get("api_url") or "").strip().rstrip("/")
    if not base:
        raise PdsError("Keine API-URL hinterlegt.")
    if "://" not in base:
        base = "https://" + base
    # Accept either the bare host (https://41309.pdscloud.de) or a URL that
    # already includes the REST root.
    url = base if base.endswith("/pds/rest/api") else f"{base}/pds/rest/api"
    token = decrypt(cfg.get("api_key_encrypted"))
    if not token:
        raise PdsError("Kein API-Schlüssel hinterlegt.")
    try:
        resp = httpx.post(
            f"{url}/{path}",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise PdsError(f"PDS nicht erreichbar: {exc}") from exc
    if resp.status_code == 401:
        raise PdsError("PDS-Anmeldung fehlgeschlagen — bitte den API-Schlüssel prüfen.")
    if resp.status_code >= 400:
        raise PdsError(f"PDS-Fehler {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError:
        return {}


# ─── Pure helpers (ported 1:1 from the n8n Code nodes) ───────────────────────
def transform_phone(phone: str | None) -> str:
    """'+4915511357330' → '004915511357330' (PDS stores 00-format)."""
    return phone.replace("+", "00", 1) if phone else ""


def normalize_subject(subject: str | None) -> str:
    """Validate against the 9 PDS categories; case-insensitive match, else
    'Allgemeine Anfrage' — exactly the n8n logic."""
    s = (subject or "").strip()
    if s in VALID_SUBJECTS:
        return s
    match = next((v for v in VALID_SUBJECTS if v.lower() == s.lower()), None)
    return match or "Allgemeine Anfrage"


def _fmt_duration(seconds: int) -> str:
    return f"{int(seconds // 60)}m {int(seconds % 60)}s"


def _fmt_dt(iso: str | None) -> tuple[str, str]:
    """German date + time strings (Berlin) for the task subject/description."""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_BERLIN)
    return local.strftime("%d.%m.%Y"), local.strftime("%H:%M:%S")


def build_task(call_data: dict, person: dict | None) -> dict:
    """The n8n 'Format Task Data' / 'Format Unknown Caller Task' nodes."""
    date_str, time_str = _fmt_dt(call_data.get("timestamp"))
    duration_str = _fmt_duration(int(call_data.get("duration") or 0))
    subject = call_data["subject"]
    if (call_data.get("callTitle") or "").strip():
        subject += f": {call_data['callTitle']}"
    if person is None:
        subject += f" (Unbekannt) - {date_str} {time_str}"
    else:
        subject += f" - {date_str} {time_str}"

    person_name = ""
    if person is not None:
        person_name = f"{person.get('vorname') or ''} {person.get('name') or ''}".strip()

    desc = "📞 ANRUFPROTOKOLL" + ("" if person is not None else " (Kontakt nicht gefunden)") + "\n\n"
    desc += f"Kategorie: {call_data['subject']}\n"
    if person is not None:
        desc += f"Anrufer: {person_name}\n"
    desc += f"Telefonnummer: {call_data.get('originalPhone') or ''}\n"
    desc += f"Datum/Uhrzeit: {date_str} um {time_str}\n"
    desc += f"Dauer: {duration_str}\n\n"
    desc += f"ZUSAMMENFASSUNG:\n{call_data.get('summary') or 'No summary provided'}\n\n"
    if call_data.get("transcriptLink"):
        desc += f"Transkript/Aufzeichnung: {call_data['transcriptLink']}\n"
    if person is None:
        desc += "\n⚠️ HINWEIS: Dieser Anrufer wurde nicht in PDS gefunden. Bitte manuell zuordnen."

    return {
        "subject": subject,
        "description": desc,
        "personUUID": (person or {}).get("uuid"),
        "personName": person_name,
        "timestamp": call_data.get("timestamp"),
    }


# ─── PDS operations ───────────────────────────────────────────────────────────
def find_person(cfg: dict, phone: str) -> dict | None:
    """person/listpersonen by 00-format phone; the first hit or None."""
    out = _post(cfg, "person/listpersonen", {
        "suchwort": transform_phone(phone),
        "suchfelder": ["ALLES"],
        "page": 0,
        "entriesPerPage": 1,
    })
    if (out.get("totalHitCount") or 0) > 0 and out.get("resultList"):
        return out["resultList"][0]
    return None


def create_task(cfg: dict, task: dict) -> dict:
    body = {
        "betreff": task["subject"],
        "beschreibung": task["description"],
        "gueltigab": task.get("timestamp"),
        "typUUID": (cfg.get("sync_entities") or {}).get("task_type_uuid") or DEFAULT_TASK_TYPE_UUID,
    }
    if task.get("personUUID"):
        body["personUUID"] = task["personUUID"]
    return _post(cfg, "crm/createaufgabe", body)


def test_connection(org_id: str) -> dict:
    """The settings 'Verbindung testen' — a real listpersonen probe, returning
    something tangible for the demo (reachability + how many Personen exist)."""
    client = get_service_client()
    cfg = get_config(client, org_id)
    if not _ready(cfg):
        return {"success": False, "message": "Bitte zuerst API-URL und API-Schlüssel speichern."}
    try:
        out = _post(cfg, "person/listpersonen", {
            "suchwort": "", "suchfelder": ["ALLES"], "page": 0, "entriesPerPage": 1,
        })
    except PdsError as exc:
        return {"success": False, "message": str(exc)}
    total = out.get("totalHitCount") or 0
    sample = ""
    if out.get("resultList"):
        p = out["resultList"][0]
        sample = f" (z. B. {p.get('vorname') or ''} {p.get('name') or ''})".rstrip(" ()")
        if sample == " (z. B.":
            sample = ""
    return {
        "success": True,
        "message": f"Verbindung erfolgreich — {total} Personen in PDS gefunden{sample}.",
        "total_persons": total,
    }


# ─── Workflow 1: Log Call ─────────────────────────────────────────────────────
def _call_to_payload(call: dict) -> dict:
    """Map OUR call row onto the n8n webhook payload shape."""
    dc = call.get("data_collection") or {}
    subject = dc.get("subject") or _TYPE_TO_SUBJECT.get((dc.get("type") or "").lower()) or ""
    return {
        "originalPhone": call.get("caller_number") or "",
        "duration": call.get("duration_seconds") or 0,
        "callTitle": call.get("summary_title") or dc.get("issue_summary") or "",
        "summary": dc.get("ultimate_summary") or call.get("summary") or "No summary provided",
        "subject": normalize_subject(subject),
        "transcriptLink": dc.get("transcript_url") or "",
        "timestamp": call.get("started_at") or call.get("created_at") or datetime.now(timezone.utc).isoformat(),
    }


def log_call(org_id: str, call: dict) -> dict:
    """Workflow 1 end-to-end for one of OUR call rows. Raises PdsError on failure."""
    client = get_service_client()
    cfg = get_config(client, org_id)
    if not _ready(cfg):
        raise PdsError("PDS ist nicht konfiguriert.")
    payload = _call_to_payload(call)
    person = find_person(cfg, payload["originalPhone"]) if payload["originalPhone"] else None
    task = build_task(payload, person)
    created = create_task(cfg, task)
    client.table("calls").update({"pds_synced_at": datetime.now(timezone.utc).isoformat()}).eq(
        "org_id", org_id
    ).eq("id", call["id"]).execute()
    return {
        "success": True,
        "message": (
            f"Anruf erfolgreich protokolliert für {task['personName']}"
            if person is not None else "Anruf für unbekannten Anrufer protokolliert"
        ),
        "taskUUID": created.get("uuid"),
        "person_found": person is not None,
    }


def safe_auto_log_call(client, org_id: str, call: dict) -> None:
    """Post-call ingest hook: when auto-sync is ON, log the call into PDS.
    Best-effort by contract — NOTHING here may break call processing."""
    try:
        cfg = get_config(client, org_id)
        if not (_ready(cfg) and cfg.get("auto_sync_enabled")):
            return
        if call.get("pds_synced_at"):
            return
        result = log_call(org_id, call)
        log.info("pds: auto-logged call %s (org=%s, person_found=%s)",
                 call.get("id"), org_id, result.get("person_found"))
    except Exception as exc:  # noqa: BLE001
        log.warning("pds: auto-sync failed (org=%s call=%s): %s", org_id, call.get("id"), exc)


def sync_recent_calls(org_id: str, limit: int = 20) -> dict:
    """Manual 'Jetzt synchronisieren': push the newest un-synced calls as PDS
    Aufgaben (skips already-synced via calls.pds_synced_at)."""
    client = get_service_client()
    cfg = get_config(client, org_id)
    if not _ready(cfg):
        return {"success": False, "message": "Bitte zuerst API-URL und API-Schlüssel speichern."}
    calls = (
        client.table("calls")
        .select("id, caller_number, duration_seconds, summary_title, summary, data_collection, started_at, created_at, pds_synced_at")
        .eq("org_id", org_id).is_("pds_synced_at", "null").is_("deleted_at", "null")
        .order("created_at", desc=True).limit(limit).execute().data or []
    )
    synced, failed = 0, 0
    for c in calls:
        try:
            log_call(org_id, c)
            synced += 1
        except PdsError as exc:
            failed += 1
            log.warning("pds: manual sync failed for call %s: %s", c.get("id"), exc)
    client.table("pds_configs").update({"last_sync_at": datetime.now(timezone.utc).isoformat()}).eq(
        "org_id", org_id
    ).execute()
    msg = f"{synced} Anruf(e) nach PDS übertragen."
    if failed:
        msg += f" {failed} fehlgeschlagen — Details im Log."
    if not calls:
        msg = "Alles aktuell — keine neuen Anrufe zu übertragen."
    return {"success": failed == 0, "message": msg, "synced": synced, "failed": failed}


# ─── Workflow 2: Greeting + Create Contact ────────────────────────────────────
def greeting_for_phone(org_id: str, phone: str) -> dict:
    """EXACT n8n response contract: {'greeting': …, 'status': 'found'|'new'}."""
    client = get_service_client()
    cfg = get_config(client, org_id)
    if not _ready(cfg):
        raise PdsError("PDS ist nicht konfiguriert.")
    person = find_person(cfg, phone)
    if person is not None:
        return {
            "greeting": f"Hallo {person.get('vorname') or ''} {person.get('name') or ''} , Willkommen zurück.",
            "status": "found",
        }
    return {
        "greeting": "Hallo, ich sehe, Sie sind ein neuer Anrufer. Könnten Sie mir bitte Ihren vollständigen Namen nennen?",
        "status": "new",
    }


def create_contact(
    org_id: str, *, full_name: str, phone: str,
    city: str | None = None, postal_code: str | None = None, street: str | None = None,
) -> dict:
    """EXACT n8n create-contact flow: person/create → add MOBIL phone →
    optional HAUPTANSCHRIFT address → {'message', 'status', 'personUUID'}."""
    client = get_service_client()
    cfg = get_config(client, org_id)
    if not _ready(cfg):
        raise PdsError("PDS ist nicht konfiguriert.")
    name_parts = (full_name or "Unknown").strip().split()
    first = name_parts[0] if name_parts else "Unknown"
    last = " ".join(name_parts[1:]) or first
    person = _post(cfg, "person/create", {
        "name": last, "vorname": first, "typ": "PRIVATPERSON",
        "apiID": transform_phone(phone),
    })
    person_uuid = person.get("uuid")
    _post(cfg, "person/createEKommunikationsweg", {
        "personUUID": person_uuid,
        "ekommunikationswegDaten": {"typ": "MOBIL", "kategorie": "PRIVAT", "value": phone},
    })
    if (city or "").strip():
        _post(cfg, "person/createPostKommunikationsweg", {
            "personUUID": person_uuid,
            "postKommunikationsweg": {
                "typ": "HAUPTANSCHRIFT", "ort": city,
                "plz": postal_code or "", "strasse": street or "", "land": "Deutschland",
            },
        })
    return {
        "message": f"Vielen Dank, {first}! Ich habe Ihren Namen notiert. Wie kann ich Ihnen heute behilflich sein ?",
        "status": "created",
        "personUUID": person_uuid,
    }
