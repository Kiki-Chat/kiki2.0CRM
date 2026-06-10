"""Preisliste → ElevenLabs knowledge base.

When Preisauskunft is enabled, the org's priced catalog items (Artikel) are
rendered into a single German text document and attached to the agent's native
knowledge base — that is where the agent gets REAL Richtpreise from (previously
the ON-prompt invited price talk with no price data at all → hallucinated
prices). The doc id lives in agent_configs.price_list_doc_id; on every catalog
change or toggle flip the doc is regenerated (delete + recreate + re-attach).

Best-effort everywhere: a failed KB sync must never break the catalog save or
the toggle — the prompt instructs the agent to fall back to the KVA offer when
no price is found.
"""

from __future__ import annotations

import logging

from app.db.supabase_client import get_service_client
from app.services import elevenlabs_agent as ea

logger = logging.getLogger(__name__)

DOC_NAME = "Preisliste (Richtpreise)"


def _fmt_eur(value) -> str:
    try:
        s = f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0,00"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def render_price_list_text(org_name: str, items: list[dict]) -> str:
    lines = [
        f"# {DOC_NAME} — {org_name}",
        "",
        "Diese Liste enthält die Richtpreise (Verkaufspreise) der angebotenen "
        "Artikel und Leistungen. Alle Preise sind Richtwerte in Euro und können "
        "je nach Aufwand vor Ort abweichen. Nenne NUR Preise, die hier stehen.",
        "",
    ]
    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        unit = (it.get("unit") or "").strip()
        unit_txt = f" pro {unit}" if unit and unit.lower() not in ("stk", "stück", "pauschal") else (f" ({unit})" if unit else "")
        desc = (it.get("description") or "").strip()
        line = f"- {name}: {_fmt_eur(it.get('unit_price'))} €{unit_txt}"
        if desc:
            line += f" — {desc}"
        lines.append(line)
    return "\n".join(lines)


def sync_price_list_kb(org_id: str) -> dict:
    """Regenerate + attach (or remove) the org's price-list KB document.

    enabled + priced items → delete old doc, create fresh text doc, attach.
    disabled or no priced items → detach + delete, clear the stored doc id.
    Returns a small status dict; never raises."""
    db = get_service_client()
    try:
        cfg = (
            db.table("agent_configs")
            .select("price_info_enabled, price_list_doc_id")
            .eq("org_id", org_id).limit(1).execute().data or [{}]
        )[0]
        org = (
            db.table("organizations")
            .select("name, elevenlabs_agent_id")
            .eq("id", org_id).limit(1).execute().data or [{}]
        )[0]
        agent_id = org.get("elevenlabs_agent_id")
        if not agent_id:
            return {"synced": False, "reason": "no_agent"}

        items = (
            db.table("catalog_items")
            .select("name, description, unit, unit_price, is_active")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .gt("unit_price", 0)
            .order("name")
            .execute()
            .data
            or []
        )
        old_doc_id = cfg.get("price_list_doc_id")
        enabled = bool(cfg.get("price_info_enabled"))

        if not enabled or not items:
            # Nothing should be quotable → remove any existing doc.
            if old_doc_id:
                _detach_and_delete(db, org_id, agent_id, old_doc_id)
            return {"synced": True, "doc_id": None, "items": len(items)}

        text = render_price_list_text(org.get("name") or "", items)
        created = ea.kb_create_from_text(text, DOC_NAME)
        doc_id = created.get("id")
        ea.patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {
                    "agent": {
                        "prompt": {
                            "knowledge_base": [
                                {
                                    "type": "text",
                                    "id": doc_id,
                                    "name": DOC_NAME,
                                    "usage_mode": "auto",
                                }
                            ]
                        }
                    }
                }
            },
            merge_arrays=[ea.KB_PATH],
            actor_id=None,
            org_id=org_id,
            endpoint_label="price_list_kb_push",
        )
        db.table("agent_configs").update({"price_list_doc_id": doc_id}).eq(
            "org_id", org_id
        ).execute()
        # Drop the superseded doc AFTER the new one is attached (no gap).
        if old_doc_id and old_doc_id != doc_id:
            _detach_and_delete(db, org_id, agent_id, old_doc_id, clear_column=False)
        logger.info("price-list KB synced for org %s (%d items)", org_id, len(items))
        return {"synced": True, "doc_id": doc_id, "items": len(items)}
    except Exception as exc:  # noqa: BLE001 — never break the triggering save
        logger.warning("price-list KB sync failed (org %s): %s", org_id, str(exc)[:300])
        return {"synced": False, "reason": str(exc)[:300]}


def _detach_and_delete(db, org_id: str, agent_id: str, doc_id: str, *, clear_column: bool = True) -> None:
    try:
        current = ea.get_agent_config(agent_id)
        kb = ea._get_path(current, ea.KB_PATH) or []
        pruned = [d for d in kb if d.get("id") != doc_id]
        if len(pruned) != len(kb):
            ea.patch_agent_safely(
                agent_id=agent_id,
                field_patches={
                    "conversation_config": {"agent": {"prompt": {"knowledge_base": pruned}}}
                },
                merge_arrays=[],  # targeted removal
                actor_id=None,
                org_id=org_id,
                endpoint_label="price_list_kb_remove",
            )
        ea._kb_delete(doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("price-list KB removal failed (org %s, doc %s): %s", org_id, doc_id, str(exc)[:200])
    finally:
        if clear_column:
            db.table("agent_configs").update({"price_list_doc_id": None}).eq(
                "org_id", org_id
            ).execute()
