"""Public paid-onboarding funnel (NO auth). Gated by ONBOARDING_ENABLED (mounted only
when on). The org does not exist yet — the lead `token` is the bind key carried through
Stripe (client_reference_id) until the webhook creates the org.

Flow: GET /plans → POST /check-email (Q4 dup-check) → POST /start (lead row) →
POST /checkout (Stripe Checkout). POST /retry/{sid} resumes a failed provision
(master-secret guarded).
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.api.deps import verify_master_secret
from app.core.crypto import encrypt
from app.db.supabase_client import get_service_client
from app.schemas.billing import PlanOption
from app.schemas.onboarding import (
    CheckEmailRequest,
    CheckEmailResponse,
    OnboardingCheckoutRequest,
    OnboardingCheckoutResponse,
    OnboardingSessionResponse,
    OnboardingStartRequest,
    OnboardingStartResponse,
)
from app.services.stripe_billing import StripeBillingError

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
log = logging.getLogger(__name__)


def _email_taken(db, email: str) -> bool:
    """An email is taken if a CRM login already uses it (a converted lead → its admin
    user). Un-converted leads do not block a re-try."""
    norm = (email or "").strip()
    if not norm:
        return True
    rows = db.table("users").select("id").ilike("email", norm).limit(1).execute().data
    return bool(rows)


# ─── GET /api/onboarding/plans (public catalog for the funnel) ────────────────
@router.get("/plans", response_model=list[PlanOption])
async def onboarding_plans() -> list[PlanOption]:
    from app.api.routes.billing import _plans

    return await run_in_threadpool(_plans)


# ─── POST /api/onboarding/check-email (Q4 dup-check) ──────────────────────────
@router.post("/check-email", response_model=CheckEmailResponse)
async def onboarding_check_email(body: CheckEmailRequest) -> CheckEmailResponse:
    db = get_service_client()
    taken = await run_in_threadpool(_email_taken, db, body.email)
    return CheckEmailResponse(available=not taken)


# ─── POST /api/onboarding/start (create the lead) ─────────────────────────────
def _start(body: OnboardingStartRequest) -> str:
    db = get_service_client()
    email = body.email.strip()
    if _email_taken(db, email):
        raise HTTPException(status_code=409, detail="Diese E-Mail ist bereits registriert.")

    fields: dict = {
        "company_name": body.company_name.strip(),
        "contact_name": body.contact_name.strip(),
        "email": email,
        "phone": body.phone.strip(),
        "trade": body.trade.strip(),
        # Q6 password — stored Fernet-encrypted, cleared on conversion (see 0097).
        "password_encrypted": encrypt(body.password),
    }
    if body.utm is not None:
        fields["utm"] = body.utm
    if body.referral_code:
        fields["referral_code"] = body.referral_code.strip()

    # Idempotent resume: reuse an existing UN-converted lead so a refresh / back /
    # aborted session (or a re-submit of the same email) never spawns a duplicate — the
    # token stays the stable session + payment binding key. Prefer the token the funnel
    # carried in its URL; else fall back to the newest un-converted lead for this email.
    existing = None
    if body.token:
        rows = (
            db.table("onboarding_leads").select("token, status")
            .eq("token", body.token).limit(1).execute().data
        )
        existing = rows[0] if rows else None
    if existing is None:
        rows = (
            db.table("onboarding_leads").select("token, status")
            .eq("email", email).neq("status", "converted")
            .order("created_at", desc=True).limit(1).execute().data
        )
        existing = rows[0] if rows else None

    if existing and existing.get("status") != "converted":
        db.table("onboarding_leads").update(fields).eq("token", existing["token"]).execute()
        return existing["token"]

    token = secrets.token_urlsafe(24)
    fields["token"] = token
    fields["status"] = "created"
    db.table("onboarding_leads").insert(fields).execute()
    return token


@router.post("/start", response_model=OnboardingStartResponse)
async def onboarding_start(body: OnboardingStartRequest) -> OnboardingStartResponse:
    token = await run_in_threadpool(_start, body)
    return OnboardingStartResponse(token=token)


# ─── GET /api/onboarding/session/{token} (resume a funnel session) ────────────
def _session(token: str) -> dict:
    db = get_service_client()
    rows = (
        db.table("onboarding_leads")
        .select("token, status, company_name, contact_name, email, phone, trade, plan_title, interval")
        .eq("token", token)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Onboarding-Sitzung nicht gefunden.")
    return rows[0]


@router.get("/session/{token}", response_model=OnboardingSessionResponse)
async def onboarding_session(token: str) -> OnboardingSessionResponse:
    row = await run_in_threadpool(_session, token)
    return OnboardingSessionResponse(**row)


# ─── POST /api/onboarding/checkout (Stripe Checkout for the lead) ──────────────
def _checkout(body: OnboardingCheckoutRequest) -> dict:
    from app.services.stripe_provisioning import create_checkout_session_for_lead

    db = get_service_client()
    rows = (
        db.table("onboarding_leads").select("*").eq("token", body.token).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Onboarding-Sitzung nicht gefunden.")
    lead = rows[0]
    if lead.get("status") == "converted":
        raise HTTPException(status_code=409, detail="Dieses Konto wurde bereits erstellt.")
    try:
        return create_checkout_session_for_lead(
            token=body.token,
            plan_title=body.plan_title,
            interval=body.interval,
            company_name=lead["company_name"],
            contact_name=lead.get("contact_name"),
            email=lead["email"],
            phone=lead.get("phone"),
            return_origin=body.return_origin,
        )
    except StripeBillingError as exc:
        raise HTTPException(status_code=502, detail=f"Checkout fehlgeschlagen: {exc}") from exc


@router.post("/checkout", response_model=OnboardingCheckoutResponse)
async def onboarding_checkout(body: OnboardingCheckoutRequest) -> OnboardingCheckoutResponse:
    result = await run_in_threadpool(_checkout, body)
    return OnboardingCheckoutResponse(url=result["url"], session_id=result["session_id"])


# ─── POST /api/onboarding/retry/{sid} (master-secret; resume a failed provision) ─
@router.post("/retry/{checkout_session_id}", dependencies=[Depends(verify_master_secret)])
async def onboarding_retry(checkout_session_id: str) -> dict:
    from app.services.onboarding_provision import retry_onboarding

    org_id = await run_in_threadpool(retry_onboarding, checkout_session_id)
    return {"org_id": org_id, "checkout_session_id": checkout_session_id}
