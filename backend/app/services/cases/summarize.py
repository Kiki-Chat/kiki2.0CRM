"""Aggregate Vorgang (ticket) titling + summary.

A Vorgang bundles MANY calls to the same matter; its headline and summary should
reflect the whole collection and refresh as calls join/leave — not stay frozen from
the first call. One LLM pass over the ticket's calls returns:

  * ``title``   — a concise German headline for the *whole* matter,
  * ``summary`` — 1–2 German sentences (what's going on / where it stands),
  * ``material_change`` — whether the headline should actually move (so a stable title
    only changes on real news, not on every attached call).

English call content is translated into German by the model. Best-effort everywhere:
any failure leaves the existing title/summary untouched.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.services.ai import client as ai_client
from app.services.ai import usage as ai_usage
from app.services.cases.titles import existing_case_titles, make_unique_case_title

logger = logging.getLogger(__name__)

_MAX_CALLS = 14          # newest calls fed to the model (a huge ticket is rare)
_MAX_BLOB = 600          # chars per call

_SYS = (
    "Du betitelst und fasst einen VORGANG (Ticket) eines Handwerker-CRM zusammen. Ein "
    "Vorgang bündelt MEHRERE Anrufe zum SELBEN Anliegen EINES Kunden. Antworte "
    "AUSSCHLIESSLICH auf DEUTSCH und NUR mit JSON.\n"
    '"title": prägnante, konkrete Überschrift (4-8 Wörter) für das GESAMT-Anliegen '
    "(z. B. 'Heizung Fehler F28 – kein Warmwasser'), nicht nur das Gewerk ('Heizung').\n"
    '"summary": 1-2 KURZE Sätze — worum es geht, aktueller Stand, nächster Schritt.\n'
    '"material_change": true NUR, wenn der aktuelle Titel das Anliegen nicht mehr gut '
    "trifft und geändert werden sollte; sonst false (Titel bleibt stabil).\n"
    "Erfinde nichts — fasse nur zusammen, was in den Anrufen steht. Sind Anrufe auf "
    "Englisch, übersetze ins Deutsche."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gather_case_calls(client, org_id: str, case_id: str) -> list[str]:
    """Per-call content blobs (issue_summary/title + summary + customer transcript
    turns) for the calls that make up this Vorgang, newest first."""
    inqs = (
        client.table("inquiries").select("id")
        .eq("org_id", org_id).eq("case_id", case_id).neq("status", "deleted")
        .execute().data or []
    )
    ids = [i["id"] for i in inqs]
    if not ids:
        return []
    calls = (
        client.table("calls")
        .select("summary_title, summary, data_collection, direction, started_at, transcript")
        .eq("org_id", org_id).in_("inquiry_id", ids).is_("deleted_at", "null")
        .order("started_at", desc=True).limit(_MAX_CALLS)
        .execute().data or []
    )
    blobs: list[str] = []
    for c in calls:
        dc = c.get("data_collection") or {}
        parts = [dc.get("issue_summary") or c.get("summary_title") or "", c.get("summary") or ""]
        tr = c.get("transcript")
        if isinstance(tr, list):
            parts.append(" ".join(
                str(t.get("message") or "") for t in tr
                if isinstance(t, dict) and (t.get("role") or "") != "agent" and t.get("message")
            ))
        blob = " ".join(p for p in parts if p).strip().replace("\n", " ")[:_MAX_BLOB]
        if blob:
            blobs.append(f"({c.get('direction') or '?'}) {blob}")
    return blobs


def summarize_case(client, org_id: str, case_id: str, current_title: str | None = None) -> dict | None:
    """Run the LLM titling/summary pass. Returns {title, summary, material} or None."""
    if not ai_client.is_configured():
        return None
    blobs = _gather_case_calls(client, org_id, case_id)
    if not blobs:
        return None
    user = (
        (f'Aktueller Titel: "{current_title}"\n\n' if current_title else "")
        + "ANRUFE DIESES VORGANGS:\n"
        + "\n".join(f"- {b}" for b in blobs)
        + '\n\nGib JSON zurück: {"title": "...", "summary": "...", "material_change": true|false}'
    )
    try:
        resp = ai_client.chat(
            [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
            model=settings.openai_classifier_model,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        u = getattr(resp, "usage", None)
        ai_usage.log_usage(
            org_id=org_id, user_id=None, feature="case_summary",
            model=settings.openai_classifier_model,
            prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(u, "completion_tokens", 0) or 0,
        )
        raw = json.loads(resp.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("summarize_case failed (case=%s): %s", case_id, str(exc)[:200])
        return None
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()[:120]
    summary = str(raw.get("summary") or "").strip()[:600]
    if not title:
        return None
    return {"title": title, "summary": summary or None, "material": bool(raw.get("material_change"))}


def retitle_case(client, org_id: str, case_id: str, *, force: bool = False) -> dict | None:
    """Refresh a Vorgang's ``ai_summary`` (always) and ``title`` (only on a material
    change, unless ``force``) from the whole collection. Never overwrites a
    human-locked title, and keeps the title unique within the customer. Best-effort."""
    rows = (
        client.table("cases").select("title, title_locked, customer_id")
        .eq("org_id", org_id).eq("id", case_id).limit(1).execute().data
    )
    if not rows:
        return None
    cur_title = rows[0].get("title")
    locked = bool(rows[0].get("title_locked"))
    customer_id = rows[0].get("customer_id")

    res = summarize_case(client, org_id, case_id, current_title=cur_title)
    if not res:
        return None

    update: dict[str, Any] = {}
    if res.get("summary"):
        update["ai_summary"] = res["summary"]
    if not locked and (force or res["material"]) and res["title"] != cur_title:
        taken = existing_case_titles(client, org_id, customer_id, exclude_id=case_id)
        update["title"] = make_unique_case_title(res["title"], taken)
    if update:
        update["updated_at"] = _now_iso()
        client.table("cases").update(update).eq("org_id", org_id).eq("id", case_id).execute()
    return res


def safe_retitle(client, org_id: str, case_id: str, *, force: bool = False) -> dict | None:
    """try/except wrapper for ingest/route call sites — never raises."""
    try:
        return retitle_case(client, org_id, case_id, force=force)
    except Exception:  # noqa: BLE001
        logger.warning("safe_retitle failed (case=%s)", case_id)
        return None
