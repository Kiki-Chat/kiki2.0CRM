"""Call enrichment — one LLM pass over the transcript.

Produces the structured data that the call drawer and Open Actions need but
ElevenLabs' flat ``transcript_summary`` paragraph doesn't give us:

  • ``summary_bullets`` — a short, structured German bullet list (the drawer
    renders these instead of the paragraph),
  • ``intent`` — did the caller ask about an Angebot / Rechnung /
    Termin (drives the kva_suggested / invoice_suggested Open Actions so a card
    appears "when discussed", mirroring how appointments work),
  • ``prefill`` — service description / address / problem / preferred time, used
    to pre-fill the KVA / Rechnung / Termin create-forms.

Best-effort everywhere: with no ``OPENAI_API_KEY`` (AI disabled) or on any error
the functions return ``None`` and callers fall back to the ElevenLabs summary +
no AI-suggested actions. The result is cached on ``calls.enrichment`` (0077) so
the LLM runs once per call (at ingest, or lazily when an old call is opened).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

ENRICHMENT_VERSION = 1
_MAX_TRANSCRIPT_CHARS = 6000


def _summary_from_bullets(result: dict) -> str | None:
    bullets = result.get("summary_bullets") or []
    cleaned = [str(b).strip() for b in bullets if str(b).strip()]
    if not cleaned:
        return None
    return "\n".join(f"• {b}" for b in cleaned)

_SYSTEM_PROMPT = (
    "Du bist eine Assistenz für ein Handwerksbetrieb-CRM. Du analysierst das "
    "Transkript EINES Telefonats und gibst AUSSCHLIESSLICH ein JSON-Objekt "
    "zurück (Deutsch). Schema:\n"
    "{\n"
    '  "summary_bullets": [string],   // 3-6 KURZE Stichpunkte, je eine Zeile, '
    "Telegrammstil, das Wichtigste zuerst (Anliegen, Details, Ergebnis). DAS ist der Hauptinhalt.\n"
    '  "next_steps": [string],        // 0-3 KURZE, imperative Folge-Schritte fürs Team '
    '(z.B. "Termin am Dienstag bestätigen", "Anna Bauer zuweisen"); leer wenn nichts zu tun ist\n'
    '  "intent": {\n'
    '    "wants_kva": boolean,         // NUR true, wenn der Kunde im Gespräch AUSDRÜCKLICH ein Angebot / einen Kostenvoranschlag anfordert. Eine beiläufige Preisfrage ("was kostet das ungefähr?") ist NICHT genug.\n'
    '    "wants_invoice": boolean,     // NUR true, wenn der Kunde AUSDRÜCKLICH eine Rechnung für eine bereits erbrachte oder vereinbarte Leistung verlangt. Eine reine Termin- oder Preisanfrage ist NICHT genug.\n'
    '    "wants_appointment": boolean  // Kunde möchte einen Termin/Besuch\n'
    "  },\n"
    '  "prefill": {\n'
    '    "service_description": string|null, // gewünschte Leistung/Arbeit, kurz (z.B. "Heizung entlüften")\n'
    '    "address": string|null,             // genannte Adresse\n'
    '    "problem": string|null,             // 1-2 Sätze Problembeschreibung\n'
    '    "preferred_time": string|null       // genannter Wunschtermin/-zeit als Freitext\n'
    "  }\n"
    "}\n"
    "WICHTIG zur Genauigkeit: Fasse AUSSCHLIESSLICH zusammen, was im Transkript "
    "tatsächlich gesagt wurde. Erfinde KEINE Namen, Termine, Preise, Adressen oder "
    "Zusagen, die nicht im Transkript stehen. Jeder Stichpunkt muss durch das "
    "Transkript belegt sein; im Zweifel weglassen. Unbekanntes => null bzw. false. "
    "Keine Erklärungen, nur das JSON."
)


def _transcript_text(transcript: Any) -> str:
    """Flatten the stored turn list into a compact 'Kunde:/Kiki:' dialogue."""
    if not isinstance(transcript, list):
        return ""
    lines: list[str] = []
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        msg = (turn.get("message") or "").strip()
        if not msg:
            continue
        who = "Kiki" if turn.get("role") == "agent" else "Kunde"
        lines.append(f"{who}: {msg}")
    text = "\n".join(lines)
    # Cap to keep token use low; the tail of a call usually holds the resolution,
    # so keep the END if it overflows.
    if len(text) > _MAX_TRANSCRIPT_CHARS:
        text = "…\n" + text[-_MAX_TRANSCRIPT_CHARS:]
    return text


def _coerce(raw: dict) -> dict:
    """Validate/normalise the model output into our stable shape."""
    bullets = raw.get("summary_bullets")
    if not isinstance(bullets, list):
        bullets = []
    bullets = [str(b).strip() for b in bullets if str(b).strip()][:6]

    steps = raw.get("next_steps")
    if not isinstance(steps, list):
        steps = []
    steps = [str(s).strip() for s in steps if str(s).strip()][:3]

    intent_in = raw.get("intent") or {}
    intent = {
        "wants_kva": bool(intent_in.get("wants_kva")),
        "wants_invoice": bool(intent_in.get("wants_invoice")),
        "wants_appointment": bool(intent_in.get("wants_appointment")),
    }

    pf_in = raw.get("prefill") or {}

    def _str_or_none(v: Any) -> str | None:
        s = str(v).strip() if v is not None else ""
        return s or None

    prefill = {
        "service_description": _str_or_none(pf_in.get("service_description")),
        "address": _str_or_none(pf_in.get("address")),
        "problem": _str_or_none(pf_in.get("problem")),
        "preferred_time": _str_or_none(pf_in.get("preferred_time")),
    }
    return {
        "version": ENRICHMENT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary_bullets": bullets,
        "next_steps": steps,
        "intent": intent,
        "prefill": prefill,
    }


def generate(
    transcript: Any,
    summary: str | None = None,
    data_collection: dict | None = None,
) -> dict | None:
    """Run the LLM enrichment pass. Returns the structured dict or None when the
    AI is disabled, there's nothing to analyse, or the call fails."""
    from app.services.ai import client as ai

    if not ai.is_configured():
        return None
    convo = _transcript_text(transcript)
    if not convo and not (summary or "").strip():
        return None

    hints = []
    if (summary or "").strip():
        hints.append(f"ElevenLabs-Zusammenfassung (Hinweis):\n{summary.strip()}")
    dc = data_collection or {}
    dc_hint = {k: dc.get(k) for k in ("customer_name", "customer_address", "issue_summary") if dc.get(k)}
    if dc_hint:
        hints.append("Bereits erfasste Felder (Hinweis): " + json.dumps(dc_hint, ensure_ascii=False))
    user_content = (
        (("\n\n".join(hints) + "\n\n") if hints else "")
        + f"Transkript:\n{convo or '(kein Transkript)'}\n\n"
        "Gib das JSON gemäß Schema zurück."
    )

    try:
        resp = ai.chat(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            model=settings.openai_classifier_model,
            temperature=0.1,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        raw = json.loads(content)
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        logger.warning("call enrichment LLM failed: %s", str(exc)[:200])
        return None
    if not isinstance(raw, dict):
        return None
    return _coerce(raw)


def enrich_call(client, org_id: str, call_row: dict) -> dict | None:
    """Generate enrichment for ``call_row`` and persist it to calls.enrichment.
    Returns the enrichment dict, or None when it couldn't be produced."""
    call_id = call_row.get("id")
    if not call_id:
        return None
    result = generate(
        call_row.get("transcript"),
        summary=call_row.get("summary"),
        data_collection=call_row.get("data_collection"),
    )
    if not result:
        return None
    update: dict[str, Any] = {"enrichment": result}
    summary_text = _summary_from_bullets(result)
    if summary_text:
        update["summary"] = summary_text
    (
        client.table("calls")
        .update(update)
        .eq("org_id", org_id)
        .eq("id", call_id)
        .execute()
    )
    return result


def safe_enrich(client, org_id: str, call_row: dict) -> dict | None:
    """try/except wrapper for the post-call ingest path — never raises."""
    try:
        return enrich_call(client, org_id, call_row)
    except Exception:  # noqa: BLE001 — never break post-call ingest
        logger.warning("call enrichment failed (call %s)", call_row.get("id"))
        return None
