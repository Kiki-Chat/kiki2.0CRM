"""Plan-based feature entitlements (Phase 2 — menu/route gating).

Single source of truth: a plan title → the set of feature keys it unlocks. The frontend
gates nav items + routes on these (soft preview + upgrade CTA); the backend can enforce
them on data routes via ``require_entitlement`` (HTTP 402). Confirmed packaging — Amber
2026-06-26/27 (see project_entitlements_billing_strategy).

CORE surfaces (Übersicht, Anrufe, Kontakte, Kiki-Zentrale config, Posteingang, Settings)
are implicit — NEVER gated. Only the keys in ``FEATURES`` are gateable. Grandfather tiers
(Kiki Legacy) resolve straight off ``billing_plan_title``; future add-ons / comps will
layer on via a per-org overrides column (not needed for v1).
"""

from __future__ import annotations

# Gateable feature key → German label (drives the upgrade CTA copy).
FEATURES: dict[str, str] = {
    "cases": "Vorgänge",
    "calendar": "Kalender & Terminverwaltung",
    "planning": "Planungstafel",
    "projects": "Projekte",
    "finance": "Finanzen (Angebote, Rechnungen, Artikel)",
}

# Plan title → granted feature keys. 'Aufträge' and the notes features are sub-features
# (inside Vorgänge/Anrufe), not menus — deferred to sub-feature gating; only menus here.
PLAN_FEATURES: dict[str, frozenset[str]] = {
    "Kiki Basis": frozenset(),
    "Kiki Legacy": frozenset({"cases"}),
    "Kiki Pro": frozenset({"cases", "calendar", "planning"}),
    "Kiki Enterprise": frozenset({"cases", "calendar", "planning", "projects", "finance"}),
}


# feature key → lowest SELF-SERVE plan that grants it (the "ab Tarif X" upgrade target;
# Kiki Legacy is grandfather-only, so it's never a target). Static — mirrors
# PLAN_FEATURES above; keep in sync if the matrix changes.
FEATURE_MIN_PLAN: dict[str, str] = {
    "cases": "Kiki Pro",
    "calendar": "Kiki Pro",
    "planning": "Kiki Pro",
    "projects": "Kiki Enterprise",
    "finance": "Kiki Enterprise",
}


# Max employees (Mitarbeiter / seats) per plan — Amber 2026-06-27. Unknown/no plan →
# DEFAULT_SEATS. Surfaced in the plan cards + comparison; enforced on employee creation.
PLAN_SEATS: dict[str, int] = {
    "Kiki Basis": 1,
    "Kiki Legacy": 5,
    "Kiki Pro": 5,
    "Kiki Enterprise": 10,
}
DEFAULT_SEATS = 1


def seat_limit(plan_title: str | None) -> int:
    return PLAN_SEATS.get(plan_title or "", DEFAULT_SEATS)


def features_for_plan(plan_title: str | None) -> set[str]:
    """The feature keys a plan grants by default (no overrides)."""
    return set(PLAN_FEATURES.get(plan_title or "", frozenset()))


def effective_features(plan_title: str | None, overrides: dict | None = None) -> set[str]:
    """Resolve an org's effective feature set: plan defaults + grants − revokes.
    ``overrides`` (org-level, future) carries grandfather grants / comps / add-ons."""
    feats = features_for_plan(plan_title)
    ov = overrides or {}
    feats |= {f for f in (ov.get("grant") or []) if f in FEATURES}
    feats -= set(ov.get("revoke") or [])
    return feats


# ─── Enforcement (Phase 2) ────────────────────────────────────────────────────
def _org_plan_and_features(org_id: str | None) -> tuple[str | None, set[str]]:
    """(billing_plan_title, effective feature set) for an org — DB read, uncached."""
    if not org_id:
        return None, set()
    from app.db.supabase_client import get_service_client

    rows = (
        get_service_client()
        .table("organizations")
        .select("billing_plan_title")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
    )
    plan = (rows[0] if rows else {}).get("billing_plan_title")
    return plan, effective_features(plan)


def org_has_feature(org_id: str | None, role: str | None, feature: str) -> bool:
    """Authoritative entitlement check used by BOTH the route dependency and the copilot
    guardrail. Fails open (returns True) when enforcement is off, the caller is
    super_admin, or the org has no plan yet — so it never locks out staff or
    not-yet-subscribed/unmigrated orgs."""
    from app.core.config import settings

    if not settings.entitlements_enforced or role == "super_admin":
        return True
    plan, feats = _org_plan_and_features(org_id)
    if plan is None:  # org not on a plan yet → don't block
        return True
    return feature in feats


def org_can_add_seat(org_id: str | None, role: str | None, current_count: int) -> bool:
    """True if the org may add another Mitarbeiter (current_count < plan seat limit).
    Same flag / super_admin-bypass / fail-open-on-no-plan rules as feature gating."""
    from app.core.config import settings

    if not settings.entitlements_enforced or role == "super_admin":
        return True
    plan, _ = _org_plan_and_features(org_id)
    if plan is None:  # org not on a plan yet → don't block
        return True
    return current_count < seat_limit(plan)


def org_seat_limit(org_id: str | None) -> int:
    """The seat limit for the org's current plan (for the 'X von Y' upgrade message)."""
    plan, _ = _org_plan_and_features(org_id)
    return seat_limit(plan)


def require_entitlement(feature: str):
    """FastAPI dependency factory: 402s a request to a gated route when the org's plan
    doesn't grant ``feature``. Add at the router level: ``dependencies=[Depends(
    require_entitlement('finance'))]``. Inert unless ENTITLEMENTS_ENFORCED=1."""
    from fastapi import Depends, HTTPException
    from starlette.concurrency import run_in_threadpool

    from app.api.deps import CurrentUser, require_org

    async def _dep(user: CurrentUser = Depends(require_org)) -> CurrentUser:
        from app.core.config import settings

        # Fast path: enforcement off or platform staff → no DB read, no threadpool hop.
        if not settings.entitlements_enforced or user.role == "super_admin":
            return user
        allowed = await run_in_threadpool(org_has_feature, user.org_id, user.role, feature)
        if not allowed:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "feature_locked",
                    "feature": feature,
                    "min_plan": FEATURE_MIN_PLAN.get(feature),
                },
            )
        return user

    return _dep
