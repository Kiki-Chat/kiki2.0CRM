"""Read-only prompt-difference classifier for the super-admin Migration view.

Compares an agent's LIVE ElevenLabs system prompt against the prompt the CRM
*would* render for that org today (``render_prompt_for_org``) and summarises how
far they diverge. This reproduces the offline "Custom Prompt Classification"
triage (coverage %, CUSTOM vs DEFAULT, what's been added/dropped) inside the
product so staff can see, per org, what a future migration would have to
preserve.

STRICTLY READ-ONLY: it never writes to ElevenLabs or the DB and never ports a
prompt. It is the visibility surface — the actual merge strategy is deliberately
NOT executed here (the open design is to route a customer's genuine deltas into
Kiki-Zentrale config fields rather than concatenating raw prompt text, so the
rendered prompt stays lean instead of bloating).
"""
from __future__ import annotations

import logging
import re
from uuid import UUID

from app.services.agent_config import render_prompt_for_org
from app.services.elevenlabs_agent import PROMPT_PATH, _get_path, get_agent_config

logger = logging.getLogger(__name__)

# Below this share of the standard template's lines surviving in the live prompt,
# the agent is treated as CUSTOM (heavily hand-tuned → port manually / preserve).
# Picked to roughly match the offline triage boundary; it's a heuristic, surfaced
# as such in the UI, not a hard gate on anything.
_CUSTOM_COVERAGE_THRESHOLD = 0.55

# EL runtime variables ({{system__time}} …) legitimately remain in any prompt and
# are not a "customisation" — don't let them skew the line comparison.
_EL_VAR_RE = re.compile(r"\{\{\s*system__[a-z_]+\s*\}\}")


def _norm_lines(text: str) -> list[str]:
    """Normalise a prompt into comparable content lines: trim, collapse internal
    whitespace, lowercase, drop blanks and EL runtime variables. Markdown bullet
    markers are stripped so '- foo' and 'foo' compare equal."""
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = _EL_VAR_RE.sub("", raw)
        line = re.sub(r"\s+", " ", line).strip()
        # Strip leading markdown/list/header markers so '# Rolle', '== Rolle =='
        # and 'Rolle' all compare equal.
        line = re.sub(r"^[-*•#=\d.)\s]+", "", line)
        line = re.sub(r"[=\s]+$", "", line).strip()
        if len(line) >= 4:  # ignore noise like "#", "==", single tokens
            out.append(line.lower())
    return out


def classify_agent_prompt(
    org_id: str | UUID, agent_id: str, org_name: str, org: dict | None = None
) -> dict:
    """Return a read-only divergence summary of the live prompt vs. the CRM's
    standard rendered prompt.

    Shape::

        {
          "available": bool,            # False when a side couldn't be read
          "error": str | None,
          "status": "CUSTOM" | "DEFAULT" | None,
          "coverage_pct": float,        # % of template lines present live (0–100)
          "live_chars": int,
          "template_chars": int,
          "added_count": int,           # content lines live has but template doesn't
          "removed_count": int,         # template lines missing from live
          "sample_added": [str],        # up to 12 of the customer's own lines
          "sample_removed": [str],      # up to 12 standard lines they dropped
        }
    """
    empty = {
        "available": False,
        "error": None,
        "status": None,
        "coverage_pct": 0.0,
        "live_chars": 0,
        "template_chars": 0,
        "added_count": 0,
        "removed_count": 0,
        "sample_added": [],
        "sample_removed": [],
    }

    try:
        cfg = get_agent_config(agent_id)
        live = (_get_path(cfg, PROMPT_PATH) or "").strip()
    except Exception as exc:  # noqa: BLE001 — surface, never 500 the board
        logger.warning("prompt_diff: live read failed for %s: %s", agent_id, exc)
        return {**empty, "error": f"Live-Prompt nicht lesbar: {str(exc)[:150]}"}

    if not live:
        return {**empty, "error": "Der Agent hat keinen Prompt hinterlegt."}

    try:
        template = render_prompt_for_org(org_name, org=org, org_id=org_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("prompt_diff: template render failed for %s: %s", org_id, exc)
        return {**empty, "error": f"Standard-Template nicht renderbar: {str(exc)[:150]}"}

    live_lines = _norm_lines(live)
    tmpl_lines = _norm_lines(template)
    live_set, tmpl_set = set(live_lines), set(tmpl_lines)

    matched = tmpl_set & live_set
    coverage = (len(matched) / len(tmpl_set)) if tmpl_set else 0.0
    added = [ln for ln in dict.fromkeys(live_lines) if ln not in tmpl_set]
    removed = [ln for ln in dict.fromkeys(tmpl_lines) if ln not in live_set]

    return {
        "available": True,
        "error": None,
        "status": "CUSTOM" if coverage < _CUSTOM_COVERAGE_THRESHOLD else "DEFAULT",
        "coverage_pct": round(coverage * 100, 1),
        "live_chars": len(live),
        "template_chars": len(template),
        "added_count": len(added),
        "removed_count": len(removed),
        "sample_added": added[:12],
        "sample_removed": removed[:12],
    }
