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

from app.services.stripe_catalog import PLAN_ORDER, PLANS

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


def _lowest_self_serve_with(feature: str) -> str | None:
    """Cheapest SELF-SERVE plan that unlocks ``feature`` — the upgrade target a customer
    is sent to (Kiki Legacy is grandfather-only, so it's never an upgrade target)."""
    for title in PLAN_ORDER:  # low → high
        if not PLANS.get(title, {}).get("self_serve", True):
            continue
        if feature in PLAN_FEATURES.get(title, frozenset()):
            return title
    return None


# feature key → lowest self-serve plan that grants it (for the "ab Tarif X" CTA).
FEATURE_MIN_PLAN: dict[str, str | None] = {f: _lowest_self_serve_with(f) for f in FEATURES}


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
