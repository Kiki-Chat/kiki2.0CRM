"""Best-effort English→German safety net.

The voice agent and its data-collection fields are German, so this almost never
fires — but if an English summary/title ever reaches the backend we translate it so
nothing English surfaces to the user. Returns the input unchanged on any failure,
when AI is disabled, or when the text already looks German.
"""
from __future__ import annotations

import logging
import re

from app.core.config import settings
from app.services.ai import client as ai_client

logger = logging.getLogger(__name__)

# Cheap heuristic so the common German case never costs an LLM call: looks English
# only when clearly-English words appear AND no German-specific letters/words do.
_EN_HINT = re.compile(
    r"\b(the|a|repair|request|heating|water|leak|appointment|customer|greeting|"
    r"morning|not working|inquiry|identification|service|report|booking)\b",
    re.I,
)
_DE_HINT = re.compile(
    r"[äöüß]|\b(der|die|das|und|nicht|kein|Heizung|Termin|Kunde|Anruf|Wasser|"
    r"defekt|Rechnung|Angebot|Dach|Reparatur)\b",
    re.I,
)


def looks_english(text: str | None) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_EN_HINT.search(t)) and not _DE_HINT.search(t)


def ensure_german(text: str | None) -> str | None:
    """Translate ``text`` to German iff it looks English; otherwise return it as-is."""
    t = (text or "").strip()
    if not t or not looks_english(t) or not ai_client.is_configured():
        return text
    try:
        resp = ai_client.chat(
            [
                {
                    "role": "system",
                    "content": "Übersetze den folgenden Text ins Deutsche. Gib NUR die "
                    "Übersetzung zurück — keine Anführungszeichen, keine Erklärung. "
                    "Eigennamen, Marken und Fehlercodes unverändert lassen.",
                },
                {"role": "user", "content": t},
            ],
            model=settings.openai_classifier_model,
            temperature=0.0,
            max_tokens=120,
        )
        out = (resp.choices[0].message.content or "").strip().strip('"').strip()
        return out or text
    except Exception as exc:  # noqa: BLE001 — best-effort, never raise
        logger.warning("ensure_german failed: %s", str(exc)[:120])
        return text
