"""Canonical Kiki plan catalog (Solo / Team / Premium) — idempotent ensure + lookup.

Each tier = a BASE product (licensed flat price) + a METERED product (graduated:
the included minutes are tier-1 at €0, overage is tier-2 per-minute). That graduated
shape is what makes soft-stop work: report ALL minutes to the metered item, the first
N are free, the rest bill automatically. Monthly + annual price per product.

⚠️ PLACEHOLDER PRICES (test mode). Confirm the real amounts with Amber before go-live.
Metadata matches STRIPE_INTEGRATION_HANDOVER.md §4a so Phase-1 quota derivation works.
"""

from __future__ import annotations

from app.services.stripe_billing import get_stripe

TAX_CODE = "txcd_10103001"  # SaaS – cloud-based (handover §3)

# plan_title -> included minutes, monthly base (cents), per-minute overage (cents)
PLANS: dict[str, dict] = {
    "Kiki Solo": {"minutes": 99, "monthly_cents": 9900, "overage_cents": 119},
    "Kiki Team": {"minutes": 250, "monthly_cents": 24900, "overage_cents": 100},
    "Kiki Premium": {"minutes": 750, "monthly_cents": 59900, "overage_cents": 70},
}
ANNUAL_MONTHS = 10  # annual = 10× monthly (2 months free)
INTERVALS = ("month", "year")


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


def _ensure_price(s, lookup_key: str, **params):
    found = s.Price.list(lookup_keys=[lookup_key], limit=1).data
    if found:
        return found[0]
    return s.Price.create(lookup_key=lookup_key, **params)


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
                product=base["id"], currency="eur",
                unit_amount=spec["monthly_cents"] * mult,
                recurring={"interval": interval}, tax_behavior="inclusive",
            )
            metered_price = _ensure_price(
                s, f"{_slug(title)}_metered_{interval}",
                product=metered["id"], currency="eur",
                recurring={"interval": interval, "usage_type": "metered"},
                billing_scheme="tiered", tiers_mode="graduated",
                tiers=[
                    {"up_to": spec["minutes"], "unit_amount": 0},
                    {"up_to": "inf", "unit_amount": spec["overage_cents"]},
                ],
                tax_behavior="inclusive",
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
