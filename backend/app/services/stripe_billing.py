"""The ONLY module permitted to talk to Stripe on behalf of the CRM.

Mirrors the "safe writes, not blocked writes" model of ``patch_agent_safely``
(elevenlabs_agent.py), adapted for an already-LIVE Stripe account:

  1. Config guard          — refuse if STRIPE_SECRET_KEY is unset (billing disabled).
  2. Audit row FIRST        — every mutation writes a billing_events row (status
                              'pending') BEFORE the Stripe call, flipped to
                              'succeeded'/'failed' after. Never skipped.
  3. Connect-attribution    — a write that targets a subscription is REFUSED when
     write block               subscription.application is non-null (legacy ChatDash
                              / Connect sub). These are read-only in KikiCRM.
  4. Cross-org guard         — the targeted subscription's customer must match the
                              org's stored stripe_customer_id (defense-in-depth).
  5. Idempotency key         — every mutating call carries {op}:{org_id}:{hash} so a
                              retry deduplicates server-side at Stripe for 24h.
  6. Additive metadata       — metadata writes merge {**existing, **new}; we never
                              clobber keys we did not set (matches the handover).
  7. Optional verify         — re-check the write landed. NOTE: unlike the EL wrapper
                              there is NO auto-rollback — Stripe writes (usage records,
                              sessions) are not safely reversible, so verification is
                              detect-and-alert. Phase-1 writes are intentionally low risk.

Pure reads go through ``stripe_read`` (no idempotency / Connect block; audited only
on error so high-volume polling never floods the ledger). The billing_events table
stays a *write* ledger, like agent_writes_audit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

import stripe

from app.core.config import settings
from app.db.supabase_client import get_service_client


# ─── Exceptions ──────────────────────────────────────────────────────────────
class StripeBillingError(Exception):
    """Generic billing failure (wraps stripe.error.StripeError with context)."""


class StripeConfigError(StripeBillingError):
    """Raised when a Stripe call is attempted without STRIPE_SECRET_KEY set."""


class ConnectAttributionError(StripeBillingError):
    """Raised when a write targets a Connect-attributed (legacy) subscription."""


class StripeCrossOrgError(StripeBillingError):
    """Raised when the targeted Stripe object does not belong to the calling org."""


class StripeVerificationError(StripeBillingError):
    """Raised when post-write verification fails (no rollback — detect-and-alert)."""


# ─── Pure helpers (hermetically unit-tested) ─────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def idempotency_key(op: str, org_id: Any, payload: dict | None) -> str:
    """Stable key for a mutating call: {op}:{org_id}:{sha256(payload)[:16]}.

    Same op + org + logical input ⇒ same key ⇒ Stripe dedupes the retry."""
    blob = json.dumps(payload or {}, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"{op}:{org_id}:{digest}"


def additive_metadata(existing: dict | None, new: dict | None) -> dict:
    """Merge metadata additively: keep every existing key, layer new on top.

    Mirrors the client_events union philosophy — never drop fields we did not set."""
    merged = dict(existing or {})
    merged.update({k: v for k, v in (new or {}).items() if v is not None})
    return merged


def _to_jsonable(obj: Any) -> Any:
    """Best-effort convert a Stripe object / response into JSON-storable form."""
    if obj is None:
        return None
    try:
        if hasattr(obj, "to_dict_recursive"):
            return obj.to_dict_recursive()
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if isinstance(obj, (dict, list, str, int, float, bool)):
            return json.loads(json.dumps(obj, default=str))
        return json.loads(json.dumps(obj, default=str))
    except Exception:  # noqa: BLE001 — audit must never break the call
        return {"repr": str(obj)[:1000]}


# ─── Stripe client ───────────────────────────────────────────────────────────
def _client():
    """Return the configured ``stripe`` module, or raise if no key is set."""
    if not settings.stripe_secret_key:
        raise StripeConfigError(
            "STRIPE_SECRET_KEY is not set — the billing module is disabled."
        )
    stripe.api_key = settings.stripe_secret_key
    return stripe


def is_configured() -> bool:
    return bool(settings.stripe_secret_key)


def get_stripe():
    """Public accessor for the configured ``stripe`` module (raises if no key).

    For callers that need to handle *expected* Stripe errors inline (e.g. the
    'no upcoming invoice' 400 on an unsubscribed customer) without routing through
    the audit-on-error ``stripe_read`` — keeps benign errors out of the ledger.
    """
    return _client()


# ─── Audit ledger (billing_events) ───────────────────────────────────────────
def _audit_insert(
    db,
    *,
    op: str,
    org_id: Any,
    actor_id: Any,
    stripe_object: str | None = None,
    request_payload: Any = None,
    idem: str | None = None,
    status: str = "pending",
    error_code: str | None = None,
    error_message: str | None = None,
) -> str | None:
    row = {
        "org_id": str(org_id) if org_id else None,
        "actor_user_id": str(actor_id) if actor_id else None,
        "event_type": op,
        "stripe_object": stripe_object,
        "request_payload": request_payload,
        "status": status,
        "idempotency_key": idem,
        "error_code": error_code,
        "error_message": (error_message or None) and error_message[:2000],
    }
    res = db.table("billing_events").insert(row).execute().data
    return res[0]["id"] if res else None


def _audit_update(db, audit_id: str | None, **fields: Any) -> None:
    if not audit_id:
        return
    fields["updated_at"] = _now()
    if fields.get("error_message"):
        fields["error_message"] = str(fields["error_message"])[:2000]
    db.table("billing_events").update(fields).eq("id", audit_id).execute()


def _org_stripe_customer(db, org_id: Any) -> str | None:
    rows = (
        db.table("organizations")
        .select("stripe_customer_id")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
    )
    return rows[0]["stripe_customer_id"] if rows else None


# ─── Read wrapper (no idempotency / Connect block; error-only audit) ─────────
def stripe_read(*, op: str, fn: Callable[[], Any], org_id: Any = None, actor_id: Any = None) -> Any:
    """Run a pure Stripe read. Records a billing_events row ONLY on failure."""
    _client()
    try:
        return fn()
    except stripe.error.StripeError as exc:  # type: ignore[attr-defined]
        try:
            _audit_insert(
                get_service_client(),
                op=op,
                org_id=org_id,
                actor_id=actor_id,
                request_payload={"read": True},
                status="failed",
                error_code=getattr(exc, "code", None) or exc.__class__.__name__,
                error_message=getattr(exc, "user_message", None) or str(exc),
            )
        except Exception:  # noqa: BLE001 — never let auditing mask the real error
            pass
        raise StripeBillingError(f"{op} read failed: {exc}") from exc


# ─── Core safe write ─────────────────────────────────────────────────────────
def stripe_call_safely(
    *,
    op: str,
    org_id: str | UUID | None,
    actor_id: str | UUID | None,
    builder: Callable[[str | None, dict | None], Any],
    subscription_id: str | None = None,
    metadata_merge: dict | None = None,
    metadata_existing: dict | None = None,
    verifier: Callable[[Any], tuple[bool, str]] | None = None,
    idempotency_payload: dict | None = None,
    stripe_object: str | None = None,
    request_payload: Any = None,
) -> Any:
    """Audit → (Connect block) → (no-op?) → call → (verify) → audit. See module docstring.

    ``builder(idempotency_key, merged_metadata)`` performs the actual Stripe write.
    """
    stripe_mod = _client()
    db = get_service_client()

    idem = idempotency_key(op, org_id, idempotency_payload) if idempotency_payload is not None else None
    merged_metadata = (
        additive_metadata(metadata_existing, metadata_merge) if metadata_merge is not None else None
    )

    # Audit row FIRST — every attempted mutation is recorded, including refusals.
    audit_id = _audit_insert(
        db,
        op=op,
        org_id=org_id,
        actor_id=actor_id,
        stripe_object=stripe_object,
        request_payload=request_payload or {},
        idem=idem,
        status="pending",
    )

    try:
        # Connect-attribution write block + cross-org guard (subscription targets only).
        if subscription_id is not None:
            sub = stripe_mod.Subscription.retrieve(subscription_id)
            application = sub.get("application")
            if application:
                raise ConnectAttributionError(
                    f"Refusing write to subscription {subscription_id}: created by Connect "
                    f"application {application}. Legacy subscription is read-only in KikiCRM."
                )
            if org_id is not None:
                org_customer = _org_stripe_customer(db, org_id)
                sub_customer = sub.get("customer")
                if org_customer and sub_customer and sub_customer != org_customer:
                    raise StripeCrossOrgError(
                        f"subscription {subscription_id} belongs to customer {sub_customer}, "
                        f"not org {org_id}'s customer {org_customer}. Refusing cross-org write."
                    )

        # No-op short-circuit (additive metadata produced no change).
        if metadata_merge is not None and merged_metadata == (metadata_existing or {}):
            _audit_update(db, audit_id, status="succeeded", response_payload={"noop": True})
            return None

        result = builder(idem, merged_metadata)

        if verifier is not None:
            ok, reason = verifier(result)
            if not ok:
                _audit_update(
                    db, audit_id, status="failed",
                    error_code="verification_failed", error_message=reason,
                    response_payload=_to_jsonable(result),
                )
                raise StripeVerificationError(f"{op}: post-write verification failed ({reason})")

        _audit_update(
            db, audit_id, status="succeeded",
            stripe_object=stripe_object or getattr(result, "id", None),
            response_payload=_to_jsonable(result),
        )
        return result

    except (ConnectAttributionError, StripeCrossOrgError) as exc:
        _audit_update(
            db, audit_id, status="failed",
            error_code=("connect_attribution" if isinstance(exc, ConnectAttributionError) else "cross_org"),
            error_message=str(exc),
        )
        raise
    except StripeVerificationError:
        raise  # already audited above
    except stripe.error.StripeError as exc:  # type: ignore[attr-defined]
        _audit_update(
            db, audit_id, status="failed",
            error_code=getattr(exc, "code", None) or exc.__class__.__name__,
            error_message=getattr(exc, "user_message", None) or str(exc),
        )
        raise StripeBillingError(f"{op} failed: {exc}") from exc
