"""queryKnowledgeBase tool (hk_queryKnowledgeBase).

DECISION (Batch 4 / CALL-036 / KIKI-032): the agent's PRIMARY knowledge source is
the NATIVE ElevenLabs knowledge base — PDF/URL docs and the auto-generated
Preisliste (Richtpreise) doc are attached to the agent there and read via RAG
WITHOUT calling this tool (see services/price_knowledge.py). This backend tool is
the *fallback* the agent reaches for when the native KB had no hit.

Previously this returned a static no-answer stub that simply told the caller
"keine Informationen" — misleading, because the ONE structured source we DO own
(the org's priced catalog / Preisliste) was never consulted. This handler now:

  1. If Preisauskunft (price_info_enabled) is ON, tries to answer a PRICE question
     directly from the org's priced ``catalog_items`` (Richtpreise) by matching the
     question text against item names. This is a SAFE, read-only, org-scoped lookup.
  2. Otherwise (or no catalog hit) returns an HONEST, structured response: no direct
     answer, a colleague will follow up — instead of pretending nothing exists. This
     keeps the agent's spoken behaviour graceful (take a message / refer to the
     office) while never fabricating an answer.

Everything is best-effort and org-scoped; a lookup failure degrades to the honest
no-answer response and never raises into the tool webhook.
"""

import logging
import re

from app.db.supabase_client import get_service_client
from app.schemas.tools import QueryKnowledgeBaseRequest

logger = logging.getLogger(__name__)

# German price-intent markers. Conservative on purpose: only treat the question as
# a price question when the caller clearly asks about cost/price, so a generic
# "wie funktioniert X" never gets a price reply.
_PRICE_INTENT_RE = re.compile(
    r"preis|kosten|kostet|teuer|günstig|guenstig|wieviel|wie viel|euro|€|tarif|richtpreis",
    re.IGNORECASE,
)

# Stopwords stripped before matching the question against catalog item names, so
# "Was kostet eine Heizungswartung?" matches the item "Heizungswartung".
_STOPWORDS = {
    "was", "wie", "viel", "wieviel", "kostet", "kosten", "der", "die", "das",
    "ein", "eine", "einen", "euro", "preis", "preise", "für", "fuer", "von",
    "bei", "ist", "sind", "und", "oder", "denn", "mich", "mir", "ihr", "eure",
    "ungefähr", "ungefaehr", "circa", "ca",
}


def _fmt_eur(value) -> str:
    try:
        s = f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0,00"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _no_answer() -> dict:
    """Honest, structured fallback — NOT a dead stub. The caller's question is
    acknowledged, no answer is fabricated, and the agent is told a colleague will
    follow up (take a message / refer to the office)."""
    return {
        "success": True,
        "answer": None,
        "source": "none",
        "followUp": True,
        "message": "Dazu habe ich keine direkte Auskunft. Ein Kollege meldet sich "
        "dazu bei dir — ich kann gern dein Anliegen und eine Rückrufnummer "
        "aufnehmen.",
    }


def _tokens(question: str) -> list[str]:
    words = re.findall(r"[a-zA-ZäöüÄÖÜß]+", question.lower())
    return [w for w in words if len(w) >= 3 and w not in _STOPWORDS]


def _match_price_items(question: str, items: list[dict]) -> list[dict]:
    """Items whose name shares a meaningful token with the question. Falls back to
    substring containment so multi-word item names still match."""
    toks = _tokens(question)
    if not toks:
        return []
    ql = question.lower()
    hits = []
    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        name_l = name.lower()
        name_toks = set(_tokens(name))
        if name_l in ql or any(t in name_toks for t in toks):
            hits.append(it)
    return hits


def query_knowledge_base(org_id: str, payload: QueryKnowledgeBaseRequest) -> dict:
    question = (payload.question or "").strip()
    if not question:
        return _no_answer()

    # Only the price path has a structured backend source today; everything else
    # is served by the native EL knowledge base (primary) and falls through to the
    # honest no-answer here when the native KB had no hit.
    if not _PRICE_INTENT_RE.search(question):
        return _no_answer()

    try:
        client = get_service_client()
        cfg = (
            client.table("agent_configs")
            .select("price_info_enabled")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
            or [{}]
        )[0]
        if not cfg.get("price_info_enabled"):
            # Preisauskunft OFF — the prompt forbids quoting prices, so do NOT.
            return _no_answer()

        items = (
            client.table("catalog_items")
            .select("name, description, unit, unit_price")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .gt("unit_price", 0)
            .order("name")
            .execute()
            .data
            or []
        )
        hits = _match_price_items(question, items)[:5]
        if not hits:
            return _no_answer()

        lines = []
        for it in hits:
            unit = (it.get("unit") or "").strip()
            unit_txt = (
                f" pro {unit}"
                if unit and unit.lower() not in ("stk", "stück", "pauschal")
                else ""
            )
            lines.append(f"{it['name']}: ca. {_fmt_eur(it.get('unit_price'))} €{unit_txt}")
        answer = "; ".join(lines)
        return {
            "success": True,
            "answer": answer,
            "source": "price_catalog",
            "followUp": False,
            "items": [
                {
                    "name": it.get("name"),
                    "unitPrice": it.get("unit_price"),
                    "unit": it.get("unit"),
                }
                for it in hits
            ],
            "message": (
                f"Als Richtwert: {answer}. Alle Preise sind Richtwerte und können je "
                "nach Aufwand vor Ort abweichen."
            ),
        }
    except Exception:  # noqa: BLE001 — never break the tool webhook over a lookup
        logger.warning("queryKnowledgeBase price lookup failed (org %s)", org_id)
        return _no_answer()
