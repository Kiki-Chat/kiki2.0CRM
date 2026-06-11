"""Billing notifications — recorded to billing_notifications (the source of truth +
in-app feed). Always recorded; the dedup_key UNIQUE index prevents duplicates
(e.g. one over-quota alert per period).

EMAIL: `_maybe_dispatch_email` triggers the EXISTING send_email() fallback chain
(Amber's email infrastructure — we only call it, never modify it). Wired
2026-06-10 on Amber's go-ahead for usage/overage warnings. Best-effort: a failed
email never blocks the in-app notification; the row's status records the outcome.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.supabase_client import get_service_client
from app.services.common import now_berlin

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_notification(
    org_id: str | None,
    ntype: str,
    *,
    title: str | None = None,
    body: str | None = None,
    dedup_key: str | None = None,
    meta: dict | None = None,
) -> str | None:
    """Insert a notification. Returns id, or None on dedup / missing table (no-op)."""
    db = get_service_client()
    try:
        res = (
            db.table("billing_notifications")
            .insert(
                {
                    "org_id": str(org_id) if org_id else None,
                    "type": ntype,
                    "channel": "in_app",
                    "title": title,
                    "body": body,
                    "dedup_key": dedup_key,
                    "meta": meta,
                    "status": "recorded",
                }
            )
            .execute()
            .data
        )
        nid = res[0]["id"] if res else None
    except Exception:  # noqa: BLE001 — dedup_key conflict or pre-0049 table → no-op
        return None
    _maybe_dispatch_email(nid, org_id, ntype, title, body)
    return nid


def _maybe_dispatch_email(nid, org_id, ntype, title, body) -> None:
    """Trigger the existing send_email() chain to the org's contact address.
    Best-effort: in-app notification stands either way; status records the outcome."""
    if not org_id or not title:
        return
    db = get_service_client()
    status = "failed"
    try:
        rows = (
            db.table("organizations").select("email, name")
            .eq("id", str(org_id)).limit(1).execute().data
        )
        to = ((rows[0].get("email") or "").strip() if rows else "")
        if not to:
            status = "recorded"  # no org contact address → in-app only
            return
        from app.services.email_send import send_email

        send_email(
            org_id=org_id, to_email=to,
            subject=f"HeyKiki: {title}",
            body_html=f"<p>{body or title}</p>",
            body_text=body or title,
        )
        status = "sent"
    except Exception as exc:  # noqa: BLE001 — email must never block billing flow
        log.warning("billing email dispatch failed (org=%s type=%s): %s", org_id, ntype, exc)
    finally:
        if nid:
            try:
                db.table("billing_notifications").update({"status": status}).eq("id", nid).execute()
            except Exception:  # noqa: BLE001
                pass


# ─── Typed helpers ───────────────────────────────────────────────────────────
def notify_trial_will_end(org_id: str) -> None:
    record_notification(
        org_id, "trial_will_end",
        title="Testphase endet bald",
        body="Ihre kostenlose Testphase endet in Kürze. Bitte hinterlegen Sie eine "
        "Zahlungsmethode, damit Ihre KI ohne Unterbrechung weiterläuft.",
        dedup_key=f"trial_will_end:{org_id}",
    )


def notify_subscription_activated(org_id: str, plan_title: str | None, subscription_id: str | None) -> None:
    """Welcome / subscription-confirmation — OUR email (Brevo), distinct from
    Stripe's payment receipt + invoice. Deduped per subscription so a re-delivered
    checkout webhook can't double-send."""
    plan = plan_title or "Ihr Tarif"
    record_notification(
        org_id, "subscription_activated",
        title="Abonnement aktiviert",
        body=f"Ihr Abonnement „{plan}“ ist aktiv. Vielen Dank! Ihre KI-Sekretärin läuft "
        "ohne Unterbrechung weiter. Rechnungen und Zahlungsbeleg finden Sie in Ihrem "
        "Konto unter Einstellungen → Abrechnung. Eine Kündigung ist nur per E-Mail an "
        "info.kikichat@gmail.com oder telefonisch möglich.",
        dedup_key=f"subscription_activated:{subscription_id or org_id}",
    )


def notify_payment_failed(org_id: str) -> None:
    record_notification(
        org_id, "payment_failed",
        title="Zahlung fehlgeschlagen",
        body="Ihre letzte Zahlung ist fehlgeschlagen. Bitte aktualisieren Sie Ihre "
        "Zahlungsdetails, um eine Unterbrechung des Dienstes zu vermeiden.",
    )


def notify_over_quota(org_id: str, period_key: str, used: int, quota: int) -> None:
    record_notification(
        org_id, "over_quota",
        title="Minutenkontingent aufgebraucht",
        body=f"Sie haben Ihr Kontingent ({quota} Min.) überschritten ({used} Min. genutzt). "
        "Der Mehrverbrauch wird nach Tarif berechnet.",
        dedup_key=f"over_quota:{org_id}:{period_key}",
        meta={"used": used, "quota": quota},
    )


def notify_quota_warning(org_id: str, period_key: str, used: int, quota: int) -> None:
    """80%-Schwelle: einmal pro Periode vorwarnen, bevor Mehrkosten anfallen."""
    record_notification(
        org_id, "quota_warning",
        title="80 % des Minutenkontingents verbraucht",
        body=f"Sie haben {used} von {quota} inkludierten Minuten genutzt. Ab {quota} Min. "
        "wird jede weitere Minute nach Ihrem Tarif berechnet.",
        dedup_key=f"quota_warning:{org_id}:{period_key}",
        meta={"used": used, "quota": quota},
    )


QUOTA_WARNING_PCT = 0.8


def check_and_notify_over_quota(org_id: str) -> None:
    """Best-effort: warn once at 80 % of the included minutes and once more when
    the quota is crossed (each deduped per billing period)."""
    db = get_service_client()
    rows = (
        db.table("organizations")
        .select("billing_quota_minutes, ai_minutes_quota, billing_period_start")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return
    org = rows[0]
    quota = org.get("billing_quota_minutes") or org.get("ai_minutes_quota") or 0
    if not quota:
        return
    start = org.get("billing_period_start") or now_berlin().replace(day=1).date().isoformat()
    calls = (
        db.table("calls").select("duration_seconds").eq("org_id", str(org_id)).gte("created_at", start).execute().data
        or []
    )
    used = round(sum((c.get("duration_seconds") or 0) for c in calls) / 60)
    period_key = str(start)[:10]
    if used > quota:
        notify_over_quota(org_id, period_key, used, int(quota))
    elif used >= quota * QUOTA_WARNING_PCT:
        notify_quota_warning(org_id, period_key, used, int(quota))
