"""EMP-030 — auto-assign an appointment to the employee whose Tätigkeitsbereich
(activity_area) best matches the call's signal.

This is an ADDITIVE fallback that runs only when the category-default path can't
supply a responsible employee:
  explicit category.default_employee_id  →  resolve_auto_assignee(...)  →  first
The match is intentionally conservative — it returns a single, *distinctive*
winner (best score > 0 AND strictly greater than the runner-up). A tie loses
(returns None) so an ambiguous signal never silently pins the wrong person.

Token overlap reuses appointment_classifier._tokens, which drops German
stopwords. That matters for the activity_area field: admins sometimes type a
whole sentence ("Wenn der Mitarbeiter X genannt wird") instead of keywords —
the stopword filter strips the connective words so only the real signal tokens
(here: "mitarbeiter", "genannt") survive and can be scored honestly.
"""

from __future__ import annotations

import logging

from app.services.appointment_classifier import _tokens

logger = logging.getLogger(__name__)


def resolve_auto_assignee(
    client,
    org_id: str,
    *,
    category_name: str | None,
    summary: str | None,
    exclude_inactive: bool = True,
) -> dict | None:
    """Best Tätigkeitsbereich match among auto-assign-enabled employees, or None.

    Returns the single employee dict (id, display_name, activity_area, …) whose
    activity_area tokens overlap the signal (category_name + ' ' + summary) most
    — but only when that best score is > 0 AND strictly beats the runner-up.
    Ties, empty signals and "no candidates" all return None. Never raises:
    auto-assign is a best-effort convenience, never a hard dependency of booking.
    """
    try:
        signal_tokens = _tokens(f"{category_name or ''} {summary or ''}")
        if not signal_tokens:
            return None

        q = (
            client.table("employees")
            .select("id, display_name, activity_area, auto_assign, is_active")
            .eq("org_id", org_id)
            .eq("auto_assign", True)
        )
        if exclude_inactive:
            q = q.eq("is_active", True)
        rows = q.execute().data or []

        best: dict | None = None
        best_score = 0
        second_score = 0
        for emp in rows:
            area = emp.get("activity_area")
            if not area or not str(area).strip():
                continue  # "non-empty activity_area" requirement
            score = len(signal_tokens & _tokens(area))
            if score > best_score:
                second_score = best_score
                best, best_score = emp, score
            elif score > second_score:
                second_score = score

        # Distinctive winner only: a positive score that strictly beats #2.
        # (Equal top scores → second_score == best_score → tie → None.)
        if best is None or best_score == 0 or best_score <= second_score:
            return None
        return best
    except Exception as exc:  # noqa: BLE001 — auto-assign is best-effort
        logger.warning("resolve_auto_assignee failed (org %s): %s", org_id, str(exc)[:200])
        return None
