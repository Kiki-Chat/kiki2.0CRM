"""AI usage + cost ledger (writes ``ai_usage_log``).

Every OpenAI call records tokens + an estimated USD cost so usage can surface in
the KI-Nutzung dashboard and be capped per org. **Fail-open**: a logging hiccup
(or the table not existing yet in Phase 0) never breaks the AI call itself.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.db.supabase_client import get_service_client

log = logging.getLogger(__name__)

# Rough USD per 1K tokens by model: (input, output). Defaults are the
# 4o-mini-class tier; adjust here when OpenAI pricing changes. Unknown models
# fall back to the mini price so cost is never wildly under-counted.
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.00015, 0.0006),
}
_DEFAULT_PRICE = (0.00015, 0.0006)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated USD cost for a single completion."""
    price_in, price_out = _PRICING.get(model, _DEFAULT_PRICE)
    return round(
        (prompt_tokens / 1000) * price_in + (completion_tokens / 1000) * price_out, 6
    )


def log_usage(
    *,
    org_id: str | None,
    user_id: str | None,
    feature: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """Insert one usage row. Best-effort — swallows every error."""
    try:
        cost = estimate_cost(model, prompt_tokens, completion_tokens)
        get_service_client().table("ai_usage_log").insert(
            {
                "org_id": org_id,
                "user_id": user_id,
                "feature": feature,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_estimate": cost,
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 — fail-open: usage logging never breaks a call
        log.warning("ai.usage: log failed (org=%s feature=%s): %s", org_id, feature, exc)


def month_cost(org_id: str | None) -> float:
    """Sum ``cost_estimate`` for the org so far this UTC month. 0.0 on any error."""
    if not org_id:
        return 0.0
    try:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = (
            get_service_client()
            .table("ai_usage_log")
            .select("cost_estimate")
            .eq("org_id", org_id)
            .gte("created_at", month_start.isoformat())
            .execute()
            .data
            or []
        )
        return round(sum(float(r.get("cost_estimate") or 0) for r in rows), 6)
    except Exception as exc:  # noqa: BLE001 — fail-open
        log.warning("ai.usage: month_cost failed (org=%s): %s", org_id, exc)
        return 0.0


def within_cap(org_id: str | None) -> bool:
    """True when the org is under its monthly spend cap (or no cap is set)."""
    cap = settings.copilot_monthly_cost_cap_usd
    if not cap or cap <= 0:
        return True
    return month_cost(org_id) < cap
