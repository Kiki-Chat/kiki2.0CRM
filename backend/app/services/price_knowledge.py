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
    """Reconcile the org's Preisliste knowledge-base doc with the Preisauskunft
    toggle — RECONCILE-BY-NAME, so it is self-healing.

    Desired end state:
      • Preisauskunft ON  + priced Artikel → exactly ONE fresh ``DOC_NAME`` doc
        attached to the agent's native knowledge base (``usage_mode: auto`` — the
        agent reads Richtpreise straight from it; the prompt block points there).
      • Preisauskunft OFF, or no priced Artikel → NO ``DOC_NAME`` doc attached, so
        the agent has no price data to read and the OFF prompt block forbids
        quoting prices.

    Every run removes ALL knowledge-base entries named ``DOC_NAME`` from the
    agent — INCLUDING orphans whose id the DB lost (the previous detach swallowed
    EL errors then nulled ``price_list_doc_id``, stranding the doc attached while
    the toggle read OFF → the agent kept quoting prices). Matching by name, not by
    stored id, is what heals that. Other knowledge-base docs are preserved.

    Ordering guarantees the DB never claims a state the agent doesn't have:
      1. create the fresh doc (if ON),
      2. PATCH the agent's KB array to the desired set — on failure, delete the
         just-created doc and leave ``price_list_doc_id`` untouched so the next
         sync retries,
      3. only AFTER a confirmed PATCH: delete the detached EL docs and advance
         ``price_list_doc_id`` to reality.

    Best-effort: never raises (a failed sync must not break the catalog/toggle
    save). NOTE: the GET→PATCH window is still not serialized — two concurrent
    syncs for the same org can race; that is tracked separately and out of scope
    here (the leak this fixes is the orphaned-while-OFF doc)."""
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
        enabled = bool(cfg.get("price_info_enabled"))
        want_doc = enabled and bool(items)

        # Snapshot the agent's current KB; split out EVERY Preisliste-named entry
        # (orphans included) and keep the rest untouched.
        current = ea.get_agent_config(agent_id)
        kb = list(ea._get_path(current, ea.KB_PATH) or [])
        stale_ids = [d.get("id") for d in kb if d.get("name") == DOC_NAME and d.get("id")]
        desired = [d for d in kb if d.get("name") != DOC_NAME]

        new_doc_id = None
        if want_doc:
            text = render_price_list_text(org.get("name") or "", items)
            created = ea.kb_create_from_text(text, DOC_NAME)
            new_doc_id = created.get("id")
            desired.append(
                {"type": "text", "id": new_doc_id, "name": DOC_NAME, "usage_mode": "auto"}
            )

        # Skip the write only when there is genuinely nothing to change: OFF and no
        # Preisliste doc is currently attached.
        if want_doc or stale_ids:
            try:
                ea.patch_agent_safely(
                    agent_id=agent_id,
                    field_patches={
                        "conversation_config": {
                            "agent": {"prompt": {"knowledge_base": desired}}
                        }
                    },
                    merge_arrays=[],  # full replace = reconcile the KB array
                    actor_id=None,
                    org_id=org_id,
                    endpoint_label="price_list_kb_sync",
                )
            except Exception:  # noqa: BLE001
                # Patch failed → don't strand the doc we just created, and leave
                # price_list_doc_id as-is so the next sync retries cleanly.
                if new_doc_id:
                    try:
                        ea._kb_delete(new_doc_id)
                    except Exception:  # noqa: BLE001
                        pass
                raise

        # PATCH confirmed (or nothing needed): safe to delete detached docs and
        # advance the tracking column to the real state.
        for sid in stale_ids:
            if sid and sid != new_doc_id:
                try:
                    ea._kb_delete(sid)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "price-list KB stale-delete failed (org %s, doc %s): %s",
                        org_id, sid, str(exc)[:200],
                    )
        if cfg.get("price_list_doc_id") != new_doc_id:
            db.table("agent_configs").update({"price_list_doc_id": new_doc_id}).eq(
                "org_id", org_id
            ).execute()

        logger.info(
            "price-list KB reconciled (org %s, enabled=%s items=%d doc=%s removed=%d)",
            org_id, enabled, len(items), new_doc_id, len(stale_ids),
        )
        return {
            "synced": True, "doc_id": new_doc_id,
            "items": len(items), "removed": len(stale_ids),
        }
    except Exception as exc:  # noqa: BLE001 — never break the triggering save
        logger.warning("price-list KB sync failed (org %s): %s", org_id, str(exc)[:300])
        return {"synced": False, "reason": str(exc)[:300]}
