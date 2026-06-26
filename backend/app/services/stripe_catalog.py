"""Canonical Kiki plan catalog (Solo / Team / Premium) — idempotent ensure + lookup.

Each tier = a BASE product (licensed flat price) + a METERED product (graduated:
the included minutes are tier-1 at €0, overage is tier-2 per-minute). That graduated
shape is what makes soft-stop work: report ALL minutes to the metered item, the first
N are free, the rest bill automatically. Monthly + annual price per product.

PRICES CONFIRMED by Amber 2026-06-10 (Solo €99 +€1.00/min / Team €179 +€0.75/min /
Premium €499 +€0.50/min; supersedes the 2026-06-08 set). These now live only in the
Stripe TEST sandbox — the canonical LIVE catalog must still be created with the live
key at go-live (run ensure_catalog()). ensure_catalog() is price-drift-aware: when a
lookup-keyed price no longer matches PLANS, a new price is created and the lookup key
is transferred (Stripe prices are immutable), so re-running after a price change is
safe in both TEST and LIVE.

TAX: every price is NET (tax_behavior="exclusive") — 19% German VAT (MwSt) is added
ON TOP at checkout via automatic_tax (Amber 2026-06-12: VAT must never be absorbed
into the plan price; applies to base + overage minutes for all tiers; EU B2B
reverse-charge still applies when a valid VAT-ID is collected). Drift detection now
includes tax_behavior, so an inclusive→exclusive switch mints fresh prices on the
next ensure_catalog() run and transfers the lookup key. (For the 19% to actually be
charged, HeyKiki's Stripe Tax registration must be active — Dashboard › Tax — not
Kleinunternehmer/exempt.)
Metadata matches STRIPE_INTEGRATION_HANDOVER.md §4a so Phase-1 quota derivation works.
"""

from __future__ import annotations

from app.services.stripe_billing import get_stripe

TAX_CODE = "txcd_10103001"  # SaaS – cloud-based (handover §3)

# plan_title -> included minutes, monthly base (cents), per-minute overage (cents),
# and self_serve (default True). Pricing CONFIRMED by Amber 2026-06-26:
#   Basis €99/100min/€1.00 · Legacy €179/200min/€0.75 · Pro €249/200min/€0.75 ·
#   Enterprise €599/750min/€0.50. 'Kiki Legacy' is a GRANDFATHER tier for existing
#   customers only — created in Stripe (so it can be assigned/migrated) but hidden from
#   the new-customer self-serve plan picker (self_serve=False).
PLANS: dict[str, dict] = {
    "Kiki Basis": {"minutes": 100, "monthly_cents": 9900, "overage_cents": 100},
    "Kiki Legacy": {"minutes": 200, "monthly_cents": 17900, "overage_cents": 75, "self_serve": False},
    "Kiki Pro": {"minutes": 200, "monthly_cents": 24900, "overage_cents": 75},
    "Kiki Enterprise": {"minutes": 750, "monthly_cents": 59900, "overage_cents": 50},
}
ANNUAL_MONTHS = 10  # annual = 10× monthly (2 months free)
INTERVALS = ("month", "year")

# Upgrade ladder (low → high). In-CRM plan changes are gated to UPGRADES only
# (a downgrade/cancellation goes through support per Amber's policy), so callers
# compare ranks before allowing a change.
PLAN_ORDER: tuple[str, ...] = ("Kiki Basis", "Kiki Legacy", "Kiki Pro", "Kiki Enterprise")


def plan_rank(title: str | None) -> int:
    """Position in the upgrade ladder; -1 for an unknown/custom plan."""
    try:
        return PLAN_ORDER.index(title or "")
    except ValueError:
        return -1


def overage_cents_for(title: str | None) -> int | None:
    """Per-minute overage tariff (cents) for a plan, or None for unknown plans."""
    spec = PLANS.get(title or "")
    return spec["overage_cents"] if spec else None


def _slug(title: str) -> str:
    return title.lower().replace(" ", "_")


def _base_metadata(title: str, minutes: int) -> dict:
    return {
        "is_saas_plan": "true",
        "plan_title": title,
        "type": "base",
        "included_call_minutes": str(minutes),
        "included_interactions": "0",
        "voice_enabled": "true",
    }


def _metered_metadata(title: str) -> dict:
    return {
        "is_saas_plan": "true",
        "plan_title": title,
        "type": "metered",
        "metric_type": "call_minutes",
    }


def _ensure_price(s, lookup_key: str, *, matches=None, **params):
    """Return the lookup-keyed price when it still matches PLANS; otherwise
    create a replacement and transfer the lookup key (prices are immutable,
    so a price change = new price + moved key; old subs keep their old price)."""
    found = s.Price.list(lookup_keys=[lookup_key], limit=1, expand=["data.tiers"]).data
    if found and (matches is None or matches(found[0])):
        return found[0]
    return s.Price.create(lookup_key=lookup_key, transfer_lookup_key=True, **params)


def ensure_catalog() -> dict:
    """Create the canonical products+prices in Stripe if missing. Idempotent."""
    s = get_stripe()
    existing: dict[tuple, dict] = {}
    for p in s.Product.list(limit=100, active=True).auto_paging_iter():
        md = p.get("metadata") or {}
        if md.get("is_saas_plan") == "true":
            existing[(md.get("plan_title"), md.get("type"))] = p

    out: dict[str, dict] = {}
    for title, spec in PLANS.items():
        base = existing.get((title, "base")) or s.Product.create(
            name=title, tax_code=TAX_CODE, metadata=_base_metadata(title, spec["minutes"])
        )
        metered = existing.get((title, "metered")) or s.Product.create(
            name=f"{title} – Mehrverbrauch", tax_code=TAX_CODE, metadata=_metered_metadata(title)
        )
        price_ids: dict[str, str] = {}
        for interval in INTERVALS:
            mult = 1 if interval == "month" else ANNUAL_MONTHS
            base_price = _ensure_price(
                s, f"{_slug(title)}_base_{interval}",
                matches=lambda p, want=spec["monthly_cents"] * mult: (
                    p.get("unit_amount") == want and p.get("tax_behavior") == "exclusive"
                ),
                product=base["id"], currency="eur",
                unit_amount=spec["monthly_cents"] * mult,
                recurring={"interval": interval}, tax_behavior="exclusive",
            )

            def _metered_matches(p, *, minutes=spec["minutes"], overage=spec["overage_cents"]):
                tiers = p.get("tiers") or []
                if len(tiers) != 2:
                    return False
                if p.get("tax_behavior") != "exclusive":
                    return False
                return (
                    tiers[0].get("up_to") == minutes
                    and (tiers[0].get("unit_amount") or 0) == 0
                    and tiers[1].get("unit_amount") == overage
                )

            metered_price = _ensure_price(
                s, f"{_slug(title)}_metered_{interval}",
                matches=_metered_matches,
                product=metered["id"], currency="eur",
                recurring={"interval": interval, "usage_type": "metered"},
                billing_scheme="tiered", tiers_mode="graduated",
                tiers=[
                    {"up_to": spec["minutes"], "unit_amount": 0},
                    {"up_to": "inf", "unit_amount": spec["overage_cents"]},
                ],
                tax_behavior="exclusive",
            )
            price_ids[f"base_{interval}"] = base_price["id"]
            price_ids[f"metered_{interval}"] = metered_price["id"]
        out[title] = {"base_product": base["id"], "metered_product": metered["id"], "prices": price_ids}
    return out


def find_plan_prices(plan_title: str, interval: str) -> dict:
    """Resolve {base_price, metered_price} for a tier+interval via lookup_keys."""
    s = get_stripe()
    slug = _slug(plan_title)
    base = s.Price.list(lookup_keys=[f"{slug}_base_{interval}"], limit=1).data
    metered = s.Price.list(lookup_keys=[f"{slug}_metered_{interval}"], limit=1).data
    return {
        "base_price": base[0]["id"] if base else None,
        "metered_price": metered[0]["id"] if metered else None,
    }
