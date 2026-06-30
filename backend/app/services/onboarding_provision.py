"""In-house paid-onboarding orchestrator — replaces the three n8n workflows.

On ``checkout.session.completed`` (Stripe webhook, background task) for a session that
matches an ``onboarding_leads`` token, ``onboard_from_session`` runs the full chain:

  1. create an ElevenLabs agent          (replaces n8n "Production demo")
  2. assign a Twilio number              (replaces n8n "Twilio Prod" — reuse idle pool
     row first, buy a fresh +49 local only if none and TWILIO_PURCHASE_ENABLED) + bind
     it to the agent in ElevenLabs
  3. provision_org(...)                  (replaces n8n "HeyKiki CRM Provision") — creates
     org + admin user + agent_configs, links the Stripe customer + plan, and
     configure_agent writes the master prompt / tools / webhook (it finds the bound phone)
  4. send ONE welcome email              (login + Kiki number + forwarding how-to; Stripe
     sends its own receipt/invoice separately)

Idempotent end-to-end on ``checkout_session_id`` via ``onboarding_events`` (stage + a
payload that carries agent_id / phone ids / org_id), so a Stripe retry or a manual
``retry_onboarding`` resumes from the last good stage and never double-creates an agent,
double-buys a number, or double-provisions.

Ships INERT: every entry point returns early unless ``settings.onboarding_enabled``.
"""

from __future__ import annotations

import html as _html
import logging
import re
import secrets
import time

import httpx

from app.core.config import settings
from app.core.crypto import decrypt
from app.db.supabase_client import get_service_client

log = logging.getLogger(__name__)

EL_BASE = "https://api.elevenlabs.io"
_TIMEOUT = 30.0

# Defaults carried from the legacy n8n agent-creation flow. configure_agent (run inside
# provision_org) overwrites the prompt/tools/webhook afterwards, so the create payload is
# only a valid starting point (name + Kiki voice + language).
KIKI_VOICE_ID = "v3V1d2rk6528UrLKRuy8"
TTS_MODEL = "eleven_turbo_v2_5"
AGENT_LLM = "gpt-5.1"
CALENDLY_URL = "https://calendly.com/kiki-chat/einrichtung-der-testphase-von-heykiki"
SUPPORT_EMAIL = "info@kikichat.de"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _el_key() -> str:
    import os

    key = settings.elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY not configured")
    return key


def _slug_suffix() -> str:
    return secrets.token_hex(3).upper()


# ─── 1. ElevenLabs agent creation (replaces n8n "Create Agent") ───────────────
def create_agent(company_name: str, trade: str | None) -> str:
    """Create a fresh ElevenLabs agent and return its agent_id. Minimal config —
    provision_org → configure_agent applies the master German prompt + tools + webhook."""
    base = re.sub(r"[^A-Za-z0-9_\- ]", "", f"{company_name}_{trade or 'Handwerk'}")[:40]
    # 'kiki2.0' marker (verbatim, incl. the dot) tags agents created by the provision
    # API so they're identifiable in the ElevenLabs workspace — distinct from the legacy
    # '..._demo_<suffix>' demo-funnel agents. Format: <company>_<trade>_kiki2.0_<alnum>.
    name = f"{base}_kiki2.0_{_slug_suffix()}"
    first_message = (
        f'Hallo, hier ist Kiki von "{company_name}". Meine Kollegen sind gerade '
        "alle im Gespräch und ich vertrete sie. Wie kann ich Ihnen helfen?"
    )
    body = {
        "name": name,
        "tags": ["kiki2.0", "onboarding"],
        "conversation_config": {
            "agent": {
                "first_message": first_message,
                "language": "de",
                "prompt": {
                    "prompt": f"Du bist Kiki, die freundliche KI-Telefonistin von {company_name}.",
                    "llm": AGENT_LLM,
                },
            },
            "tts": {"model_id": TTS_MODEL, "voice_id": KIKI_VOICE_ID},
        },
    }
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.post(
            "/v1/convai/agents/create",
            headers={"xi-api-key": _el_key()},
            json=body,
        )
    if r.status_code >= 300:
        raise RuntimeError(f"EL agent create failed: {r.status_code} {r.text[:300]}")
    data = r.json()
    agent_id = data.get("agent_id") or data.get("id")
    if not agent_id:
        raise RuntimeError(f"EL agent create returned no agent_id: {str(data)[:300]}")
    return agent_id


# ─── 2. Twilio number pool (replaces n8n "Twilio Prod") ───────────────────────
def _twilio_buy_number(area: str) -> tuple[str, str]:
    """Search DE local AvailablePhoneNumbers (Contains=area) and buy the first.
    Returns (e164, twilio_sid). Gated by TWILIO_PURCHASE_ENABLED in the caller."""
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    if not (sid and token):
        raise RuntimeError("Twilio credentials not configured")
    if not (settings.twilio_address_sid and settings.twilio_bundle_sid):
        raise RuntimeError("TWILIO_ADDRESS_SID / TWILIO_BUNDLE_SID required to buy a DE number")
    auth = (sid, token)
    with httpx.Client(timeout=_TIMEOUT, auth=auth) as c:
        r = c.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/AvailablePhoneNumbers/DE/Local.json",
            params={"Contains": area},
        )
        if r.status_code >= 300:
            raise RuntimeError(f"Twilio search failed: {r.status_code} {r.text[:300]}")
        avail = (r.json().get("available_phone_numbers") or [])
        if not avail:
            raise RuntimeError(f"No Twilio DE numbers available for area {area}")
        e164 = avail[0]["phone_number"]
        buy = c.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json",
            data={
                "PhoneNumber": e164,
                "AddressSid": settings.twilio_address_sid,
                "BundleSid": settings.twilio_bundle_sid,
            },
        )
        if buy.status_code >= 300:
            raise RuntimeError(f"Twilio buy failed: {buy.status_code} {buy.text[:300]}")
        return e164, buy.json().get("sid")


def _el_register_number(e164: str, label: str) -> str:
    """Register a Twilio number with ElevenLabs → returns phone_number_id (phnum_...)."""
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    body = {"phone_number": e164, "label": label[:100], "sid": sid, "token": token}
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.post(
            "/v1/convai/phone-numbers", headers={"xi-api-key": _el_key()}, json=body
        )
    if r.status_code >= 300:
        raise RuntimeError(f"EL phone register failed: {r.status_code} {r.text[:300]}")
    pid = r.json().get("phone_number_id")
    if not pid:
        raise RuntimeError("EL phone register returned no phone_number_id")
    return pid


def _el_bind_number(phone_number_id: str, agent_id: str) -> None:
    """Bind an EL phone number to an agent (PATCH /v1/convai/phone-numbers/{id})."""
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.patch(
            f"/v1/convai/phone-numbers/{phone_number_id}",
            headers={"xi-api-key": _el_key()},
            json={"agent_id": agent_id},
        )
    if r.status_code >= 300:
        raise RuntimeError(f"EL phone bind failed: {r.status_code} {r.text[:300]}")


def allocate_number(session_id: str, agent_id: str, label: str) -> dict:
    """Allocate + bind a Kiki number for ``agent_id``. Reuse an idle twilio_numbers row
    first; buy a fresh +49 local only when none is free and purchase is armed. Idempotent
    on ``session_id``: a number already reserved/assigned for this session is returned.
    Returns {phone_number, eleven_phone_id, twilio_sid}."""
    db = get_service_client()

    # Idempotency: a prior run for this session already grabbed a number.
    existing = (
        db.table("twilio_numbers").select("*").eq("session_id", session_id).limit(1).execute().data
    )
    row = existing[0] if existing else None

    if row is None:
        # Reuse an idle pooled number first.
        idle = (
            db.table("twilio_numbers").select("*").eq("status", "idle").limit(1).execute().data
        )
        if idle:
            row = idle[0]
            db.table("twilio_numbers").update(
                {"status": "reserved", "session_id": session_id, "last_updated": _now()}
            ).eq("id", row["id"]).execute()
        elif settings.twilio_purchase_enabled:
            e164, twilio_sid = _twilio_buy_number(settings.twilio_number_area)
            ins = (
                db.table("twilio_numbers")
                .insert(
                    {
                        "phone_number": e164,
                        "status": "reserved",
                        "session_id": session_id,
                        "twilio_sid": twilio_sid,
                        "notes": "Purchased during onboarding",
                        "last_updated": _now(),
                    }
                )
                .execute()
                .data
            )
            row = ins[0]
        else:
            raise RuntimeError(
                "No idle Twilio number in the pool and TWILIO_PURCHASE_ENABLED is off"
            )

    phone_number = row["phone_number"]
    eleven_phone_id = row.get("eleven_phone_id")
    if not eleven_phone_id:
        eleven_phone_id = _el_register_number(phone_number, label)
    _el_bind_number(eleven_phone_id, agent_id)

    db.table("twilio_numbers").update(
        {
            "eleven_phone_id": eleven_phone_id,
            "assigned_agent_id": agent_id,
            "status": "assigned",
            "label": label[:100],
            "last_updated": _now(),
        }
    ).eq("id", row["id"]).execute()

    return {
        "phone_number": phone_number,
        "eleven_phone_id": eleven_phone_id,
        "twilio_sid": row.get("twilio_sid"),
    }


def _wait_for_agent_phone(agent_id: str, *, attempts: int = 8, delay: float = 2.0) -> None:
    """Poll until ElevenLabs reports the bound phone on the agent, so the subsequent
    provision_org → configure_agent (which hard-fails on zero phones) sees it. EL is
    eventually-consistent after a bind (the legacy n8n flow waited 15s + re-checked)."""
    from app.services import agent_config

    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            agent_config.fetch_phone_meta_for_agent(agent_id)
            return
        except Exception as exc:  # noqa: BLE001 — HTTPException(400) until the bind propagates
            last_exc = exc
            time.sleep(delay)
    raise RuntimeError(f"Agent {agent_id} phone not visible after bind: {last_exc}")


# ─── onboarding_events idempotency ledger ─────────────────────────────────────
def _get_event(db, checkout_session_id: str) -> dict | None:
    rows = (
        db.table("onboarding_events")
        .select("*")
        .eq("checkout_session_id", checkout_session_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _ensure_event(db, checkout_session_id: str, lead_id: str | None) -> dict:
    existing = _get_event(db, checkout_session_id)
    if existing:
        return existing
    try:
        ins = (
            db.table("onboarding_events")
            .insert(
                {
                    "checkout_session_id": checkout_session_id,
                    "lead_id": lead_id,
                    "stage": "dispatched",
                    "payload": {},
                }
            )
            .execute()
            .data
        )
        return ins[0]
    except Exception:  # noqa: BLE001 — concurrent insert (UNIQUE) → load the winner
        return _get_event(db, checkout_session_id) or {"payload": {}}


def _update_event(db, checkout_session_id: str, **fields) -> None:
    fields["updated_at"] = _now()
    db.table("onboarding_events").update(fields).eq(
        "checkout_session_id", checkout_session_id
    ).execute()


# ─── 3. provision (replaces n8n "/provision") ─────────────────────────────────
def _format_address(addr: dict | None) -> str | None:
    a = addr or {}
    parts = [
        a.get("line1"),
        a.get("line2"),
        " ".join(x for x in [a.get("postal_code"), a.get("city")] if x),
        a.get("country"),
    ]
    s = ", ".join(p for p in parts if p)
    return s or None


def _existing_org_id_for_email(db, email: str) -> str | None:
    rows = (
        db.table("users").select("org_id").ilike("email", (email or "").strip()).limit(1).execute().data
    )
    return rows[0]["org_id"] if rows and rows[0].get("org_id") else None


def _provision(lead: dict, session: dict, agent_id: str, payload: dict) -> str:
    """Create the org via provision_org (chosen password if present, else random + a
    set-password link in the email). Returns org_id. Handles the 409 'already exists'
    that a partial retry would hit by resolving the existing org."""
    from fastapi import HTTPException

    from app.schemas.provision import ProvisionRequest
    from app.services.provisioning import provision_org

    db = get_service_client()
    chosen = decrypt(lead.get("password_encrypted")) if lead.get("password_encrypted") else None
    password = chosen or secrets.token_urlsafe(18)
    details = session.get("customer_details") or {}
    address = _format_address(details.get("address"))

    req = ProvisionRequest(
        org_name=lead["company_name"],
        login_email=lead["email"],
        login_password=password,
        elevenlabs_agent_id=agent_id,
        elevenlabs_phone_number_id=payload.get("eleven_phone_id"),
        phone_number=payload.get("phone_number"),
        admin_name=lead.get("contact_name"),
        contact_email=lead["email"],
        trade=lead.get("trade"),
        address=address,
        stripe_customer_id=session.get("customer"),
        plan_title=lead.get("plan_title"),
    )
    try:
        resp = provision_org(req)
        return resp.org_id
    except HTTPException as exc:
        if exc.status_code == 409:
            org_id = _existing_org_id_for_email(db, lead["email"])
            if org_id:
                log.info("onboard: org for %s already exists (%s); resuming", lead["email"], org_id)
                return org_id
        raise


def _sync_subscription(db, session: dict) -> None:
    """Sync the new subscription onto organizations.billing_* (status/period/quota)."""
    sub_id = session.get("subscription")
    if not sub_id:
        return
    try:
        from app.services.stripe_billing import get_stripe
        from app.services.stripe_webhook import _handle_subscription

        sub = get_stripe().Subscription.retrieve(sub_id, expand=["items.data.price"])
        _handle_subscription(db, sub)
    except Exception as exc:  # noqa: BLE001 — best-effort; plan_title already set at provision
        log.warning("onboard: subscription sync failed for %s: %s", sub_id, exc)


# ─── 4. welcome email ─────────────────────────────────────────────────────────
def _welcome_email_html(
    *, company_name: str, contact_name: str | None, login_email: str,
    phone_number: str | None, set_password_link: str | None,
) -> str:
    from app.services import email_templates

    name = (contact_name or "").strip().split(" ")[0] if contact_name else ""
    greet = f"Willkommen bei HeyKiki, {_html.escape(name)}!" if name else "Willkommen bei HeyKiki!"
    p = (
        "margin:0 0 14px 0;color:#555;font-size:14px;line-height:1.6;"
        "font-family:'Segoe UI',Tahoma,Geneva,Verdana,Arial,sans-serif;"
    )
    login_url = f"{settings.public_app_url}/login"
    if set_password_link:
        pw_block = (
            f'<p style="{p}">Lege über den folgenden sicheren Link dein Passwort fest '
            "und melde dich anschließend an:</p>"
            f'<p style="text-align:center;margin:24px 0;">'
            f'<a href="{set_password_link}" style="display:inline-block;background:#03423A;'
            "color:#fff;padding:12px 30px;border-radius:6px;text-decoration:none;font-weight:600;"
            "font-size:15px;font-family:\'Segoe UI\',Tahoma,Geneva,Verdana,Arial,sans-serif;\">"
            "Passwort festlegen &amp; anmelden</a></p>"
        )
    else:
        pw_block = (
            f'<p style="{p}">Melde dich mit deiner E-Mail und dem von dir gewählten '
            "Passwort an:</p>"
            f'<p style="text-align:center;margin:24px 0;">'
            f'<a href="{login_url}" style="display:inline-block;background:#03423A;color:#fff;'
            "padding:12px 30px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;"
            "font-family:'Segoe UI',Tahoma,Geneva,Verdana,Arial,sans-serif;\">Zum Login</a></p>"
        )
    number_block = ""
    if phone_number:
        number_block = (
            f'<div style="background:#f9f9f9;border:2px solid #03423A;border-radius:8px;'
            f'padding:20px;margin:18px 0;text-align:center;">'
            f'<p style="margin:0 0 6px 0;color:#03423A;font-weight:600;font-size:15px;'
            f"font-family:'Segoe UI',Tahoma,Geneva,Verdana,Arial,sans-serif;\">☎️ Deine Kiki-Nummer</p>"
            f'<p style="margin:0;font-size:18px;font-weight:700;color:#03423A;">{_html.escape(phone_number)}</p>'
            f'<p style="margin:8px 0 0 0;color:#666;font-size:13px;">Leite deine Anrufe per '
            "Rufumleitung auf diese Nummer um – Kiki nimmt dann für dich ab.</p></div>"
        )
    body = (
        f'<h2 style="margin:0 0 16px 0;color:#03423A;font-size:18px;'
        f"font-family:'Segoe UI',Tahoma,Geneva,Verdana,Arial,sans-serif;\">{greet}</h2>"
        f'<p style="{p}">Vielen Dank! Dein Konto für <strong>{_html.escape(company_name)}</strong> '
        "ist eingerichtet und ab sofort einsatzbereit.</p>"
        f'<p style="{p}">Deine Anmelde-E-Mail:<br><strong>{_html.escape(login_email)}</strong></p>'
        f"{pw_block}{number_block}"
        f'<p style="{p}">Brauchst du Hilfe bei der Einrichtung? '
        f'<a href="{CALENDLY_URL}" style="color:#03423A;">Buche hier einen Termin</a> '
        f"oder schreib uns an <a href=\"mailto:{SUPPORT_EMAIL}\" style=\"color:#03423A;\">{SUPPORT_EMAIL}</a>.</p>"
        f'<p style="{p}">Viele Grüße<br>Dein HeyKiki-Team</p>'
    )
    return email_templates.render_email(
        company_name="HeyKiki", body_html=body, contact_email=SUPPORT_EMAIL
    )


def _send_welcome_email(org_id: str, lead: dict, payload: dict) -> None:
    """ONE welcome email (login + number + how-to). Stripe sends the receipt/invoice."""
    from app.services.billing_notifications import record_notification
    from app.services.email_send import send_email

    set_password_link = None
    # Only generate a set-password link when the customer did NOT choose a password in
    # the form (legacy/edge); otherwise they log in with their chosen password.
    if not lead.get("password_encrypted"):
        try:
            from app.services.employee_invite import generate_set_password_link

            set_password_link, _ = generate_set_password_link(lead["email"], new_user=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("onboard: set-password link gen failed: %s", exc)

    html = _welcome_email_html(
        company_name=lead["company_name"],
        contact_name=lead.get("contact_name"),
        login_email=lead["email"],
        phone_number=payload.get("phone_number"),
        set_password_link=set_password_link,
    )
    send_email(
        org_id=org_id,
        to_email=lead["email"],
        subject="Willkommen bei HeyKiki – dein Konto ist bereit",
        body_html=html,
    )
    # In-app record (no second email — dispatch handled above).
    try:
        record_notification(
            org_id, "onboarding_complete",
            title="Konto erstellt",
            body="Dein HeyKiki-Konto wurde erstellt und ist startklar.",
            dedup_key=f"onboarding_complete:{org_id}",
            dispatch_email=False,
        )
    except Exception:  # noqa: BLE001
        pass


# ─── lead lookup ──────────────────────────────────────────────────────────────
def _find_lead(db, token: str | None, session_id: str | None) -> dict | None:
    if token:
        rows = db.table("onboarding_leads").select("*").eq("token", token).limit(1).execute().data
        if rows:
            return rows[0]
    if session_id:
        rows = (
            db.table("onboarding_leads").select("*").eq("stripe_session_id", session_id).limit(1).execute().data
        )
        if rows:
            return rows[0]
    return None


# ─── orchestrator entrypoint (called from the Stripe webhook, background task) ─
def onboard_from_session(session: dict) -> str | None:
    """Create the CRM tenant for a paid onboarding-funnel checkout. Returns the org_id,
    or None when this session is NOT an onboarding lead (caller then runs the normal
    existing-org handler). Idempotent on the checkout session id."""
    if not settings.onboarding_enabled:
        return None
    db = get_service_client()
    token = session.get("client_reference_id")
    session_id = session.get("id")
    customer_id = session.get("customer")

    lead = _find_lead(db, token, session_id)
    if not lead:
        return None  # not our funnel → let _handle_checkout_completed continue
    if lead.get("status") == "converted" and lead.get("org_id"):
        return lead["org_id"]

    ev = _ensure_event(db, session_id, lead.get("id"))
    payload: dict = dict(ev.get("payload") or {})
    org_id = payload.get("org_id") or lead.get("org_id")
    label = f"{lead.get('company_name', 'Kunde')}_{lead.get('trade', '')}"[:100]

    try:
        # 1. agent (skip if a prior run already created one)
        agent_id = payload.get("agent_id")
        if not agent_id:
            agent_id = create_agent(lead["company_name"], lead.get("trade"))
            payload["agent_id"] = agent_id
            _update_event(db, session_id, stage="agent_created", payload=payload)

        # 2. number + bind (idempotent on session_id)
        if not payload.get("eleven_phone_id"):
            num = allocate_number(session_id, agent_id, label)
            payload.update(num)
            _update_event(db, session_id, stage="number_assigned", payload=payload)
        _wait_for_agent_phone(agent_id)

        # 3. provision (skip if a prior run already created the org)
        if not org_id:
            org_id = _provision(lead, session, agent_id, payload)
            payload["org_id"] = org_id
            _update_event(db, session_id, stage="provisioned", payload=payload, org_id=org_id)
            db.table("twilio_numbers").update({"org_id": org_id}).eq(
                "eleven_phone_id", payload.get("eleven_phone_id")
            ).execute()
            _sync_subscription(db, session)

        # 4. mark the lead converted + clear the stored password
        db.table("onboarding_leads").update(
            {
                "org_id": org_id,
                "status": "converted",
                "stripe_customer_id": customer_id,
                "password_encrypted": None,
                "updated_at": _now(),
            }
        ).eq("id", lead["id"]).execute()

        # 5. welcome email (best-effort — never blocks provisioning)
        try:
            _send_welcome_email(org_id, lead, payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("onboard: welcome email failed for org %s: %s", org_id, exc)

        return org_id
    except Exception as exc:  # noqa: BLE001 — record + re-raise so process_event marks it failed (retryable)
        _update_event(db, session_id, stage="failed", error=str(exc)[:2000], payload=payload)
        if org_id:
            try:
                db.table("organizations").update({"onboarding_status": "failed"}).eq("id", org_id).execute()
            except Exception:  # noqa: BLE001
                pass
        raise


def retry_onboarding(checkout_session_id: str) -> str | None:
    """Resume a failed/partial onboarding from the recorded stage. Re-fetches the Stripe
    checkout session so the same idempotent chain runs. Used by the super-admin retry route."""
    db = get_service_client()
    ev = _get_event(db, checkout_session_id)
    if not ev:
        raise RuntimeError(f"no onboarding_events row for {checkout_session_id}")
    from app.services.stripe_billing import get_stripe

    session = get_stripe().checkout.Session.retrieve(checkout_session_id)
    return onboard_from_session(dict(session))
