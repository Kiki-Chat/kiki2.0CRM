"""Natural language → Gesprächslogik tree (the "easy mode" for craftsmen).

The owner describes their call rules in plain German ("Wenn ein Lieferant
anruft, frag nach der Lieferantennummer …"); the LLM emits a ConversationLogic
JSON tree which is then run through the SAME validator + compiler as the manual
editor — so a generated tree can never be saved in a shape the prompt renderer
would reject. On a validation failure the error is fed back to the model for
ONE repair attempt before giving up with the German validator message.
"""
from __future__ import annotations

import json
import logging
import uuid

from app.schemas.conversation_logic import (
    MAX_ACTIONS,
    MAX_BLOCKS,
    MAX_BRANCHES,
    MAX_CONDITIONS,
    MAX_TEXT,
    ConversationLogic,
    LogicError,
    compile_conversation_logic,
    validate_conversation_logic,
)
from app.services.ai import client as ai_client
from app.services.ai.usage import log_usage

log = logging.getLogger(__name__)


class GenerationFailed(ValueError):
    """User-facing German message: the description could not be converted."""


_SYSTEM = f"""Du wandelst die frei formulierte Beschreibung eines Handwerksbetriebs in eine strukturierte Gesprächslogik für seinen KI-Telefonassistenten um.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt dieser Form (keine Erklärungen):
{{"version": 1, "blocks": [
  {{"branches": [
    {{"kind": "wenn", "conditions": ["<Bedingung>"], "condition_op": "und",
      "actions": [{{"type": "ask", "text": "<Frage>"}}]}},
    {{"kind": "sonst_wenn", "conditions": ["<Bedingung>"], "condition_op": "und", "actions": [...]}},
    {{"kind": "sonst", "actions": [...]}}
  ]}}
]}}

Regeln:
- Aktions-Typen: "ask" (freie Frage, text nötig), "ask_field" (ein Leitfaden-Feld abfragen: field_key + text=Feldname — IMMER bevorzugen, wenn die gewünschte Frage einem verfügbaren Leitfaden-Feld entspricht, z. B. Name/Telefon/Kundennummer), "say" (Hinweis sagen, text nötig), "goto" (target: "schritt_2" = Daten aufnehmen, "schritt_3" = Termin, "abschluss" = Gespräch beenden).
- Eine Regel = ein Block mit Wenn/Sonst-wenn/Sonst-Zweigen. Erster Zweig immer "wenn"; "sonst" hat KEINE conditions.
- Bedingungen sind kurze deutsche Aussagen über den Anrufer/das Gespräch. Sie werden wörtlich hinter "Wenn" eingesetzt — formuliere sie also mit Verb am Ende, z. B. "der Anrufer ein Lieferant ist" (NICHT "der Anrufer ist ein Lieferant").
- Mehrere Bedingungen in einem Zweig: condition_op "und" oder "oder".
- Limits: max. {MAX_BLOCKS} Regeln, {MAX_BRANCHES} Zweige/Regel, {MAX_CONDITIONS} Bedingungen/Zweig, {MAX_ACTIONS} Aktionen/Zweig, {MAX_TEXT} Zeichen pro Text. Bleib DEUTLICH darunter — kurz und präzise.
- Fragen formulierst du als wörtliche, höfliche deutsche Sätze (Du-Form).
- Erfinde NICHTS dazu: nur was die Beschreibung verlangt. Unklare Wünsche lässt du weg.
- Wenn die Beschreibung bestehende Regeln ergänzen soll, bekommst du diese als JSON — gib dann den GESAMTEN neuen Stand zurück (bestehende Regeln unverändert lassen, sofern die Beschreibung nichts anderes sagt)."""


def _strip_code_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _ensure_ids(raw: dict) -> dict:
    """The manual editor keys rows by id — give generated nodes stable uuids."""
    for rule in raw.get("blocks") or []:
        rule.setdefault("id", f"r-{uuid.uuid4().hex[:8]}")
        for br in rule.get("branches") or []:
            br.setdefault("id", f"b-{uuid.uuid4().hex[:8]}")
            for a in br.get("actions") or []:
                a.setdefault("id", f"a-{uuid.uuid4().hex[:8]}")
                if a.get("rule"):
                    sub = a["rule"]
                    sub.setdefault("id", f"r-{uuid.uuid4().hex[:8]}")
                    for sbr in sub.get("branches") or []:
                        sbr.setdefault("id", f"b-{uuid.uuid4().hex[:8]}")
                        for sa in sbr.get("actions") or []:
                            sa.setdefault("id", f"a-{uuid.uuid4().hex[:8]}")
    return raw


def _call_model(messages: list[dict]) -> tuple[dict, object]:
    resp = ai_client.chat(messages, temperature=0.1, response_format={"type": "json_object"})
    content = resp.choices[0].message.content or ""
    try:
        raw = json.loads(_strip_code_fence(content))
    except Exception as exc:
        raise GenerationFailed(f"Die KI-Antwort war kein gültiges JSON ({exc}).") from exc
    if not isinstance(raw, dict):
        raise GenerationFailed("Die KI-Antwort hatte nicht die erwartete Form.")
    return raw, resp


def generate_logic_from_text(
    *,
    org_id: str,
    user_id: str | None,
    description: str,
    existing: dict | None = None,
    fields: list[dict] | None = None,
) -> dict:
    """Returns {"logic": <validated tree>, "text": <compiled German preview>}.

    ``fields`` = the org's Leitfaden fields ([{field_key, label}]) so the model
    can emit ask_field references (shared vocabulary with the guide) instead of
    re-inventing free-text questions for Name/Telefon/Kundennummer & Co.
    Raises GenerationFailed / AIServiceDisabled with user-facing messages.
    """
    user_msg = f"Beschreibung des Betriebs:\n{description.strip()}"
    if fields:
        listing = "\n".join(f'- field_key "{f["field_key"]}": {f["label"]}' for f in fields if f.get("field_key"))
        user_msg += (
            "\n\nVerfügbare Leitfaden-Felder (für ask_field; text = Feldname):\n" + listing
        )
    if existing and (existing.get("blocks") or []):
        user_msg += "\n\nBestehende Regeln (ergänzen/anpassen):\n" + json.dumps(
            existing, ensure_ascii=False
        )
    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user_msg}]

    last_error: str | None = None
    for attempt in range(2):
        raw, resp = _call_model(messages)
        usage = getattr(resp, "usage", None)
        log_usage(
            org_id=org_id, user_id=user_id, feature="logic_generator",
            model=getattr(resp, "model", "") or "",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
        raw.setdefault("version", 1)
        raw = _ensure_ids(raw)
        try:
            logic = ConversationLogic.model_validate(raw)
            validate_conversation_logic(logic)
            compiled = compile_conversation_logic(logic)
            if not compiled:
                raise LogicError(
                    "Aus der Beschreibung konnten keine Regeln abgeleitet werden — "
                    "bitte konkreter beschreiben (z. B. „Wenn …, dann frage …“)."
                )
            return {"logic": logic.model_dump(exclude_none=True), "text": compiled}
        except (LogicError, ValueError) as exc:
            last_error = str(exc)
            log.info("logic_generator: attempt %d invalid (%s) — repair", attempt + 1, last_error)
            messages.append({"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)})
            messages.append({
                "role": "user",
                "content": f"Dein JSON war ungültig: {last_error}\nGib das korrigierte, vollständige JSON-Objekt zurück.",
            })
    raise GenerationFailed(f"Die Regeln konnten nicht erstellt werden: {last_error}")
