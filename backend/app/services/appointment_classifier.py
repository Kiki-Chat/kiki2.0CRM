"""Post-call fallback categorization for agent-booked appointments.

The agent is instructed to pass `kategorie` on every hk_bookAppointment call;
when it didn't (or the name didn't match a configured Terminkategorie), this
module classifies the call summary against the org's category descriptions and
back-fills category, duration and default employee on the still-untouched
pending appointment.

Two strategies, fail-open:
1. OpenAI (app.services.ai.client) when OPENAI_API_KEY is configured — one tiny
   temperature-0 completion that must answer with an exact category name or NONE.
2. Keyword-overlap fallback — tokenize each category's name+description (minus
   German stopwords) and score overlap against the summary; the best match with
   at least one distinctive hit wins, ties lose.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "einer", "und", "oder", "ist", "im", "in", "an", "am", "auf", "für", "fuer",
    "mit", "von", "zu", "zum", "zur", "wenn", "wird", "werden", "bei", "nach",
    "kunde", "kunden", "anruft", "anruf", "fragt", "termin", "dies", "diese",
    "dieser", "wie", "als", "es", "um", "sich", "nicht", "auch", "hat", "sind",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zäöüß]{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def classify_keyword(summary: str, categories: list[dict]) -> dict | None:
    """Best keyword-overlap match, or None when nothing distinctive matches."""
    summary_tokens = _tokens(summary)
    if not summary_tokens:
        return None
    best, best_score = None, 0
    tied = False
    for cat in categories:
        cat_tokens = _tokens(f"{cat.get('name') or ''} {cat.get('description') or ''}")
        score = len(summary_tokens & cat_tokens)
        if score > best_score:
            best, best_score, tied = cat, score, False
        elif score == best_score and score > 0:
            tied = True
    if best is None or best_score == 0 or tied:
        return None
    return best


def _classify_ai(summary: str, categories: list[dict]) -> dict | None:
    """One tiny temperature-0 completion; answer must be an exact name or NONE."""
    from app.services.ai import client as ai

    if not ai.is_configured():
        return None
    listing = "\n".join(
        f"- {c.get('name')}: {c.get('description') or '(keine Beschreibung)'}"
        for c in categories
    )
    try:
        resp = ai.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Du ordnest das Anliegen eines Telefonats GENAU EINER "
                        "Terminkategorie zu. Antworte AUSSCHLIESSLICH mit dem "
                        "exakten Kategorienamen aus der Liste oder mit NONE, wenn "
                        "keine eindeutig passt. Keine Begründung."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Anliegen:\n{summary}\n\nKategorien:\n{listing}",
                },
            ],
            temperature=0,
            max_tokens=30,
        )
        answer = (resp.choices[0].message.content or "").strip().strip('"„“')
    except Exception as exc:  # noqa: BLE001 — classification is best-effort
        logger.warning("appointment AI classification failed: %s", str(exc)[:200])
        return None
    if not answer or answer.upper() == "NONE":
        return None
    for cat in categories:
        if (cat.get("name") or "").strip().lower() == answer.lower():
            return cat
    return None


def classify_and_apply(client, org_id: str, conversation_id: str | None, summary: str | None) -> None:
    """Back-fill category/duration/employee on category-less pending appointments
    booked during this conversation. Safe: the rows are seconds old and untouched
    by humans (category is null), so overwriting duration/assignment is fine."""
    if not conversation_id or not (summary or "").strip():
        return
    appts = (
        client.table("appointments")
        .select("id, category, duration_minutes")
        .eq("org_id", org_id)
        .eq("source_conversation_id", conversation_id)
        .eq("status", "pending")
        .is_("category", "null")
        .execute()
        .data
        or []
    )
    if not appts:
        return
    categories = (
        client.table("appointment_categories")
        .select("id, name, description, duration_minutes, default_employee_id")
        .eq("org_id", org_id)
        .execute()
        .data
        or []
    )
    if not categories:
        return

    match = _classify_ai(summary, categories) or classify_keyword(summary, categories)
    if not match:
        return

    patch: dict = {"category": match.get("name")}
    if match.get("duration_minutes"):
        patch["duration_minutes"] = match["duration_minutes"]
    emp_id = match.get("default_employee_id")
    if emp_id:
        emp = (
            client.table("employees").select("id, is_active")
            .eq("org_id", org_id).eq("id", emp_id).limit(1).execute().data or []
        )
        if emp and emp[0].get("is_active"):
            patch["assigned_employee_id"] = emp_id
    # EMP-030 (ADDITIVE): the matched category has no usable default employee
    # (none configured, or the configured one is inactive) → fall back to an
    # activity-area match among auto-assign employees. Best-effort, never raises.
    if "assigned_employee_id" not in patch:
        from app.services.dispatch import resolve_auto_assignee

        auto = resolve_auto_assignee(
            client, org_id, category_name=match.get("name"), summary=summary
        )
        if auto:
            patch["assigned_employee_id"] = auto["id"]
    for a in appts:
        client.table("appointments").update(patch).eq("id", a["id"]).eq(
            "org_id", org_id
        ).execute()
    logger.info(
        "appointment auto-categorized as %r (conv %s, %d row(s))",
        match.get("name"), conversation_id, len(appts),
    )
