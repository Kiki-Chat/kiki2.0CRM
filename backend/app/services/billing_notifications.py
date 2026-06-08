"""Billing notifications — recorded to billing_notifications (the source of truth +
in-app feed). Always recorded; the dedup_key UNIQUE index prevents duplicates
(e.g. one over-quota alert per period).

EMAIL: actual email dispatch is intentionally NOT wired here — email delivery is
Amber's separate track (Brevo/send_email). When billing emails are wanted, hook the
existing send_email chain in `_maybe_dispatch_email`; until then notifications surface
in-app (Abrechnung + super-admin), which already satisfies "notifications come".
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.supabase_client import get_service_client
from app.services.common import now_berlin


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
    _maybe_dispatch_email(org_id, ntype, title, body)
    return nid


def _maybe_dispatch_email(org_id, ntype, title, body) -> None:
    """Extension point for Amber's email track. No-op by design (in-app only for now)."""
    return None


# ─── Typed helpers ───────────────────────────────────────────────────────────
def notify_trial_will_end(org_id: str) -> None:
    record_notification(
        org_id, "trial_will_end",
        title="Testphase endet bald",
        body="Ihre kostenlose Testphase endet in Kürze. Bitte hinterlegen Sie eine "
        "Zahlungsmethode, damit Ihre KI ohne Unterbrechung weiterläuft.",
        dedup_key=f"trial_will_end:{org_id}",
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


def check_and_notify_over_quota(org_id: str) -> None:
    """Best-effort: if the org has crossed its quota this period, record one alert."""
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
    if used > quota:
        notify_over_quota(org_id, str(start)[:10], used, int(quota))
