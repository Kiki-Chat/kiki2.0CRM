import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org, require_org_admin
from app.core import cache
from app.core.crypto import encrypt
from app.db.supabase_client import get_service_client
from app.services.common import now_berlin
from app.services import email_templates
from app.services.email_send import send_email

router = APIRouter(prefix="/api/settings", tags=["settings"])

ORG_ASSETS_BUCKET = "org-assets"
MAX_LOGO_BYTES = 2 * 1024 * 1024
_EXT_BY_TYPE = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/svg+xml": "svg", "image/webp": "webp"}
_DEFAULT_THRESHOLDS = {
    "ai_suggestions_enabled": True,
    "kva_followup_days": 7,
    "payment_reminder_days": 14,
    "appointment_reminder_days": 1,
    "maintenance_reminder_days": 30,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Schemas ──────────────────────────────────────────────────────────────────
class GeneralUpdate(BaseModel):
    name: str | None = None
    trade: str | None = None
    phone_number: str | None = None
    fax: str | None = None
    email: str | None = None
    website: str | None = None
    address: dict | None = None
    bank_details: dict | None = None
    tax_info: dict | None = None
    management: dict | None = None
    chamber_of_crafts: str | None = None

    model_config = {"extra": "ignore"}


class DesignUpdate(BaseModel):
    accent_color: str | None = None
    font_preference: str | None = None


class AiSuggestionsUpdate(BaseModel):
    ai_suggestions_enabled: bool | None = None
    kva_followup_days: int | None = None
    payment_reminder_days: int | None = None
    appointment_reminder_days: int | None = None
    maintenance_reminder_days: int | None = None

    model_config = {"extra": "ignore"}


class GoogleReviewsUpdate(BaseModel):
    google_reviews_enabled: bool


class EmailConfigUpdate(BaseModel):
    provider: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None  # plaintext in → encrypted at rest
    smtp_sender_name: str | None = None
    smtp_sender_email: str | None = None
    use_ssl: bool | None = None
    invoice_email_subject: str | None = None
    invoice_email_body: str | None = None
    kva_email_subject: str | None = None
    kva_email_body: str | None = None

    model_config = {"extra": "ignore"}


class PdsConfigUpdate(BaseModel):
    api_url: str | None = None
    api_user: str | None = None
    api_key: str | None = None  # plaintext in → encrypted at rest
    auto_sync_enabled: bool | None = None
    sync_interval: str | None = None
    sync_entities: dict | None = None

    model_config = {"extra": "ignore"}


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _clean_email(ec: dict | None) -> dict | None:
    if not ec:
        return None
    out = {k: v for k, v in ec.items() if k != "smtp_password_encrypted"}
    out["has_password"] = bool(ec.get("smtp_password_encrypted"))
    return out


def _clean_pds(pc: dict | None) -> dict | None:
    if not pc:
        return None
    out = {k: v for k, v in pc.items() if k != "api_key_encrypted"}
    out["has_api_key"] = bool(pc.get("api_key_encrypted"))
    return out


def _usage(client, org_id: str, org: dict) -> dict:
    month_start = now_berlin().replace(day=1).date().isoformat()
    calls = (
        client.table("calls").select("duration_seconds")
        .eq("org_id", org_id).gte("created_at", month_start).execute().data or []
    )
    minutes_used = round(sum((c.get("duration_seconds") or 0) for c in calls) / 60)
    employees = client.table("users").select("id", count="exact").eq("org_id", org_id).execute().count or 0
    docs = client.table("documents").select("size_bytes").eq("org_id", org_id).execute().data or []
    return {
        "ai_minutes_used": minutes_used,
        "ai_minutes_quota": org.get("ai_minutes_quota"),
        "active_employees": employees,
        "document_count": len(docs),
        "document_size_bytes": sum((d.get("size_bytes") or 0) for d in docs),
    }


# ─── GET full settings ────────────────────────────────────────────────────────
def _get_settings(org_id: str) -> dict:
    client = get_service_client()
    org = (client.table("organizations").select("*").eq("id", org_id).limit(1).execute().data or [{}])[0]
    ec = (client.table("email_configs").select("*").eq("org_id", org_id).limit(1).execute().data or [None])[0]
    pc = (client.table("pds_configs").select("*").eq("org_id", org_id).limit(1).execute().data or [None])[0]
    ac = (
        client.table("agent_configs")
        .select("ai_suggestions_enabled, kva_followup_days, payment_reminder_days, appointment_reminder_days, maintenance_reminder_days")
        .eq("org_id", org_id).limit(1).execute().data or [None]
    )[0]
    return {
        "organization": org,
        "email_config": _clean_email(ec),
        "pds_config": _clean_pds(pc),
        "ai_suggestions": ac or dict(_DEFAULT_THRESHOLDS),
        "usage": _usage(client, org_id, org),
    }


@router.get("")
async def get_settings(user: CurrentUser = Depends(require_org_admin)) -> dict:
    return await run_in_threadpool(_get_settings, user.org_id)


# ─── General / Design / Google Reviews (org table) ────────────────────────────
def _update_org(org_id: str, fields: dict) -> dict:
    client = get_service_client()
    if fields:
        client.table("organizations").update(fields).eq("id", org_id).execute()
        # Item 4: the org row backs the cached `org_name` (PATCH /general changes
        # it). Invalidate on any org write so a renamed company never serves stale.
        # No-op until caching is enabled. NOTE for rollout: super-admin org edits
        # must also invalidate `org_name` when caching is turned on.
        cache.invalidate(org_id, "org_name")
    return (client.table("organizations").select("*").eq("id", org_id).limit(1).execute().data or [{}])[0]


@router.patch("/general")
async def update_general(payload: GeneralUpdate, user: CurrentUser = Depends(require_org_admin)) -> dict:
    return await run_in_threadpool(_update_org, user.org_id, payload.model_dump(exclude_unset=True))


@router.patch("/design")
async def update_design(payload: DesignUpdate, user: CurrentUser = Depends(require_org_admin)) -> dict:
    return await run_in_threadpool(_update_org, user.org_id, payload.model_dump(exclude_unset=True))


@router.patch("/google-reviews")
async def update_google_reviews(payload: GoogleReviewsUpdate, user: CurrentUser = Depends(require_org_admin)) -> dict:
    return await run_in_threadpool(_update_org, user.org_id, {"google_reviews_enabled": payload.google_reviews_enabled})


# ─── Logo ─────────────────────────────────────────────────────────────────────
@router.post("/logo")
async def upload_logo(file: UploadFile = File(...), user: CurrentUser = Depends(require_org_admin)) -> dict:
    content = await file.read()
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="Logo zu groß (max. 2 MB).")
    ext = _EXT_BY_TYPE.get((file.content_type or "").lower())
    if not ext and file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "svg", "webp"):
        raise HTTPException(status_code=415, detail="Nur PNG, JPG oder SVG erlaubt.")

    def _do() -> str:
        client = get_service_client()
        path = f"{user.org_id}/logo.{ext}"
        client.storage.from_(ORG_ASSETS_BUCKET).upload(
            path, content,
            {"content-type": file.content_type or "application/octet-stream", "upsert": "true"},
        )
        url = client.storage.from_(ORG_ASSETS_BUCKET).get_public_url(path).rstrip("?")
        url = f"{url}?t={int(time.time())}"  # cache-bust on replace
        client.table("organizations").update({"logo_url": url}).eq("id", user.org_id).execute()
        return url

    return {"logo_url": await run_in_threadpool(_do)}


@router.delete("/logo")
async def delete_logo(user: CurrentUser = Depends(require_org_admin)) -> dict:
    def _do() -> bool:
        client = get_service_client()
        try:
            existing = client.storage.from_(ORG_ASSETS_BUCKET).list(user.org_id)
            paths = [f"{user.org_id}/{f['name']}" for f in (existing or []) if f.get("name")]
            if paths:
                client.storage.from_(ORG_ASSETS_BUCKET).remove(paths)
        except Exception:
            pass
        client.table("organizations").update({"logo_url": None}).eq("id", user.org_id).execute()
        return True

    await run_in_threadpool(_do)
    return {"success": True}


# ─── AI suggestions (agent_configs) ───────────────────────────────────────────
@router.patch("/ai-suggestions")
async def update_ai_suggestions(payload: AiSuggestionsUpdate, user: CurrentUser = Depends(require_org_admin)) -> dict:
    fields = payload.model_dump(exclude_unset=True)

    def _do() -> dict:
        client = get_service_client()
        row = {**fields, "org_id": user.org_id, "updated_at": _now()}
        client.table("agent_configs").upsert(row, on_conflict="org_id").execute()
        ac = (
            client.table("agent_configs")
            .select("ai_suggestions_enabled, kva_followup_days, payment_reminder_days, appointment_reminder_days, maintenance_reminder_days")
            .eq("org_id", user.org_id).limit(1).execute().data or [dict(_DEFAULT_THRESHOLDS)]
        )[0]
        return ac

    return await run_in_threadpool(_do)


@router.post("/generate-suggestions")
async def generate_suggestions(user: CurrentUser = Depends(require_org_admin)) -> dict:
    # Stub: real generation runs on the nightly job; manual trigger acknowledged.
    return {"success": True, "generated": 0, "message": "Vorschläge werden in Kürze generiert."}


# ─── Email config ─────────────────────────────────────────────────────────────
@router.patch("/email-config")
async def update_email_config(payload: EmailConfigUpdate, user: CurrentUser = Depends(require_org_admin)) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    pw = fields.pop("smtp_password", None)

    def _do() -> dict | None:
        client = get_service_client()
        row = {**fields, "org_id": user.org_id, "updated_at": _now()}
        if pw:  # only re-encrypt when a new password is supplied
            row["smtp_password_encrypted"] = encrypt(pw)
        client.table("email_configs").upsert(row, on_conflict="org_id").execute()
        ec = (client.table("email_configs").select("*").eq("org_id", user.org_id).limit(1).execute().data or [None])[0]
        return _clean_email(ec)

    return await run_in_threadpool(_do)


@router.post("/email-test")
async def email_test(user: CurrentUser = Depends(require_org_admin)) -> dict:
    """Test the org's email-send chain by sending a self-addressed message.

    Uses the 3-tier fallback (OAuth → customer SMTP → Brevo); the chain +
    final provider are returned so the admin can see which tier succeeded.
    Useful for verifying a freshly-pasted SMTP config or OAuth link.
    """
    def _do() -> dict:
        client = get_service_client()
        org = (
            client.table("organizations").select("name, email")
            .eq("id", user.org_id).limit(1).execute().data or [{}]
        )[0]
        ec = (
            client.table("email_configs")
            .select("oauth_account_email, smtp_sender_email")
            .eq("org_id", user.org_id).limit(1).execute().data or [None]
        )[0]
        # Send the test to the CONNECTED sending account's own inbox — that's
        # where a tradesperson clicking "Test-E-Mail" expects it. When nothing is
        # connected (Brevo fallback), send to the REGISTERED USER's own email
        # (the admin clicking the button) — NOT the org's generic address.
        to_email = (
            (ec or {}).get("oauth_account_email")
            or (ec or {}).get("smtp_sender_email")
            or user.email
            or org.get("email")
        )
        if not to_email:
            return {"success": False, "message": "Keine Empfänger-E-Mail hinterlegt."}
        try:
            result = send_email(
                org_id=user.org_id,
                to_email=to_email,
                subject="HeyKiki — Test-E-Mail",
                body_html=email_templates.render_message_email(
                    company_name=org.get("name"),
                    message_text=(
                        "Dies ist eine Test-E-Mail von HeyKiki.\n\n"
                        "Ihre E-Mail-Konfiguration funktioniert."
                    ),
                ),
                body_text=(
                    "Dies ist eine Test-E-Mail von HeyKiki. "
                    "Ihre E-Mail-Konfiguration funktioniert."
                ),
                reply_to=org.get("email"),
            )
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "message": f"Senden fehlgeschlagen: {exc}"}
        return {
            "success": True,
            "message": f"Test-E-Mail an {to_email} gesendet via {result.provider_used}.",
            "provider_used": result.provider_used,
            "fallback_chain": result.fallback_chain,
        }

    return await run_in_threadpool(_do)


# ─── PDS config ───────────────────────────────────────────────────────────────
@router.patch("/pds-config")
async def update_pds_config(payload: PdsConfigUpdate, user: CurrentUser = Depends(require_org_admin)) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    key = fields.pop("api_key", None)

    def _do() -> dict | None:
        client = get_service_client()
        row = {**fields, "org_id": user.org_id, "updated_at": _now()}
        if key:
            row["api_key_encrypted"] = encrypt(key)
        client.table("pds_configs").upsert(row, on_conflict="org_id").execute()
        pc = (client.table("pds_configs").select("*").eq("org_id", user.org_id).limit(1).execute().data or [None])[0]
        return _clean_pds(pc)

    return await run_in_threadpool(_do)


@router.post("/pds-test")
async def pds_test(user: CurrentUser = Depends(require_org_admin)) -> dict:
    return {"success": False, "message": "Verbindungstest in Kürze verfügbar."}


@router.post("/pds-sync")
async def pds_sync(user: CurrentUser = Depends(require_org_admin)) -> dict:
    return {"success": False, "message": "Synchronisierung in Kürze verfügbar."}


# ─── Danger zone: delete organization ─────────────────────────────────────────
@router.delete("/organization")
async def delete_organization(
    user: CurrentUser = Depends(require_org),
    x_confirm_delete: str | None = Header(default=None, alias="X-Confirm-Delete"),
) -> dict:
    if user.role != "org_admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen die Organisation löschen.")

    def _do() -> str:
        client = get_service_client()
        org = (client.table("organizations").select("name").eq("id", user.org_id).limit(1).execute().data or [None])[0]
        if not org:
            return "missing"
        if (x_confirm_delete or "").strip() != (org.get("name") or "").strip():
            return "mismatch"
        client.table("organizations").delete().eq("id", user.org_id).execute()
        return "ok"

    res = await run_in_threadpool(_do)
    if res == "missing":
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden.")
    if res == "mismatch":
        raise HTTPException(status_code=400, detail="Bestätigungstext stimmt nicht mit dem Organisationsnamen überein.")
    return {"success": True}
