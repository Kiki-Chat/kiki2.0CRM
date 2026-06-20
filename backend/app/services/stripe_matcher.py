"""Dry-run org ↔ Stripe-customer matcher (Phase 1).

Proposes matches for super-admin review by writing rows to billing_migration_log.
ZERO write-back to Stripe — no Customer.modify, no metadata writes. The
approval-triggered write-back (heykiki_org_id → live Stripe metadata) is Phase 2.

Enumerates customers via the stripe SDK (the Stripe MCP lives on claude.ai, not in
this backend). German B2B names are normalized (legal-suffix stripped) before fuzzy
matching with stdlib difflib — no extra dependency at the ~80-customer scale.
"""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

from app.db.supabase_client import get_service_client
from app.services.identify import _to_e164
from app.services.stripe_billing import get_stripe, stripe_read

# Common German legal-form suffixes, longest first so multi-word forms strip cleanly.
_SUFFIXES = [
    "gmbh & co. kg", "gmbh & co kg", "ug (haftungsbeschränkt)", "co. kg", "co kg",
    "& co", "gmbh", "mbh", "ug", "e.k.", "e.k", "ek", "kg", "ohg", "gbr", "ag",
]
_NAME_THRESHOLD = 0.60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_phone(value: str | None) -> str | None:
    """E.164-normalize a phone for comparison (reuses the customer-table helper so
    different renderings — 0049…, +49…, spaced — collapse to one canonical value)."""
    return _to_e164(value)


def _customer_phone(c: dict | None) -> str | None:
    """Stripe customers carry a phone on the top-level ``phone`` field and a more
    reliable one on ``customer_details.phone`` for checkout-derived records."""
    if not c:
        return None
    phone = c.get("phone")
    if not phone:
        details = c.get("customer_details") or {}
        phone = details.get("phone")
    return normalize_phone(phone)


def normalize_name(name: str | None) -> str:
    """Lowercase, strip legal suffixes + punctuation → comparable token string."""
    if not name:
        return ""
    s = name.lower().strip()
    for suf in _SUFFIXES:
        s = s.replace(suf, " ")
    s = re.sub(r"[^a-z0-9äöüß ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _candidate_snapshot(c: dict | None) -> dict | None:
    if not c:
        return None
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "email": c.get("email"),
        "delinquent": c.get("delinquent"),
        "address": c.get("address"),
        "created": c.get("created"),
        "metadata": c.get("metadata"),
    }


def list_stripe_customers() -> list[dict]:
    """All Stripe customers (auto-paged). Audited on error via stripe_read."""
    return stripe_read(
        op="customer.list",
        fn=lambda: list(get_stripe().Customer.list(limit=100).auto_paging_iter()),
    )


def propose_matches() -> dict:
    """Scan unlinked orgs, propose a Stripe customer for each, write to the log.

    Idempotent-ish: an org that already has ANY billing_migration_log row is
    skipped, so re-runs don't pile up duplicate proposals.
    """
    client = get_service_client()
    orgs = (
        client.table("organizations")
        .select("id, name, email, phone_number, stripe_customer_id")
        .execute()
        .data
        or []
    )
    unlinked = [o for o in orgs if not o.get("stripe_customer_id")]

    customers = list_stripe_customers()
    by_email: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    by_phone: dict[str, dict] = {}
    for c in customers:
        email = (c.get("email") or "").strip().lower()
        if email:
            by_email.setdefault(email, c)
        norm = normalize_name(c.get("name"))
        if norm:
            by_name.setdefault(norm, c)
        phone = _customer_phone(c)
        if phone:
            by_phone.setdefault(phone, c)

    proposals = 0
    for org in unlinked:
        existing = (
            client.table("billing_migration_log")
            .select("id")
            .eq("org_id", org["id"])
            .limit(1)
            .execute()
            .data
        )
        if existing:
            continue  # already proposed/reviewed — don't duplicate

        method, confidence, candidate = "none", 0.0, None
        org_email = (org.get("email") or "").strip().lower()
        org_phone = normalize_phone(org.get("phone_number"))
        email_cand = by_email.get(org_email) if org_email else None
        # Email + phone both pointing at the SAME customer = highest confidence
        # (mirrors the webhook's BOTH-match auto-link rule for the offline tool).
        if (
            email_cand is not None
            and org_phone
            and _customer_phone(email_cand) == org_phone
        ):
            method, confidence, candidate = "email_phone_exact", 0.99, email_cand
        elif email_cand is not None:
            method, confidence, candidate = "email_exact", 0.95, email_cand
        else:
            org_norm = normalize_name(org.get("name"))
            best, best_ratio = None, 0.0
            if org_norm:
                for norm, c in by_name.items():
                    ratio = difflib.SequenceMatcher(None, org_norm, norm).ratio()
                    if ratio > best_ratio:
                        best, best_ratio = c, ratio
            if best is not None and best_ratio >= _NAME_THRESHOLD:
                method, confidence, candidate = "name_fuzzy", round(best_ratio, 3), best

        client.table("billing_migration_log").insert(
            {
                "org_id": org["id"],
                "stripe_customer_id": candidate.get("id") if candidate else None,
                "match_method": method,
                "match_confidence": confidence,
                "candidate_payload": _candidate_snapshot(candidate),
                "status": "proposed",
            }
        ).execute()
        proposals += 1

    return {
        "orgs_scanned": len(unlinked),
        "stripe_customers": len(customers),
        "proposals_created": proposals,
    }
