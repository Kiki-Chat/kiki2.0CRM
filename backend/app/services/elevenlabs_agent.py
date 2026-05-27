"""The ONLY module permitted to write the ElevenLabs agent configuration.

Every Kiki-Zentrale write routes through ``patch_agent_safely``, which implements
the "safe writes, not blocked writes" model:

  1. Cross-org guard       — agent_id must equal the org's stored elevenlabs_agent_id.
  2. Pre-write snapshot     — the full current config is saved to agent_config_snapshots.
  3. Additive array merge   — paths in ``merge_arrays`` are unioned with current, never
                              stripped. client_events always keeps "audio".
  4. Audio assertion        — "audio" must be present in the merged client_events BEFORE
                              the PATCH is sent; otherwise SilentAgentRiskError (no call,
                              no wasted snapshot).
  5. Post-write verify      — re-GET confirms the change landed, audio is still present,
                              the agent is reachable, and pre-existing tools weren't
                              clobbered. On failure: automatic rollback from the snapshot.
  6. Per-field audit        — agent_writes_audit records the diff + ElevenLabs response.

Reads use the direct REST API (xi-api-key) because the ElevenLabs MCP get_agent_config
does NOT expose tools / client_events.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from app.core.config import settings
from app.db.supabase_client import get_service_client

EL_BASE = "https://api.elevenlabs.io"
_TIMEOUT = 30.0

REQUIRED_AUDIO_EVENT = "audio"
CLIENT_EVENTS_PATH = "conversation_config.conversation.client_events"
# The deprecated inline-tool form lives here (objects with id/name).
TOOLS_PATH = "conversation_config.agent.prompt.tools"
# The CURRENT tool-binding form (list of tool_id strings). Step B (2026-05-27)
# uses this path to merge the 10 hk_* tool ids onto a provisioned agent —
# the inline `tools` array is legacy data left over from older agent builds.
TOOL_IDS_PATH = "conversation_config.agent.prompt.tool_ids"
KB_PATH = "conversation_config.agent.prompt.knowledge_base"
PROMPT_PATH = "conversation_config.agent.prompt.prompt"
FIRST_MESSAGE_PATH = "conversation_config.agent.first_message"
LANGUAGE_PATH = "conversation_config.agent.language"
VOICE_PATH = "conversation_config.tts.voice_id"
# Webhook (conversation initiation client data) lives outside conversation_config.
WEBHOOK_URL_PATH = (
    "platform_settings.workspace_overrides."
    "conversation_initiation_client_data_webhook.url"
)
WEBHOOK_ENABLED_PATH = (
    "platform_settings.overrides."
    "enable_conversation_initiation_client_data_from_webhook"
)


# ─── Exceptions ──────────────────────────────────────────────────────────────
class SilentAgentRiskError(Exception):
    """Raised when a write would leave client_events without 'audio' (silent agent)."""


class CrossOrgAgentWriteError(Exception):
    """Raised when agent_id does not match the calling org's stored agent."""


class ElevenLabsWriteError(Exception):
    """Raised when the ElevenLabs API returns a non-success status."""


class VerificationFailedError(Exception):
    """Raised when post-write verification fails (after an automatic rollback)."""


# ─── HTTP plumbing (mock these in unit tests) ────────────────────────────────
def _headers(json: bool = True) -> dict[str, str]:
    h = {"xi-api-key": settings.elevenlabs_api_key}
    if json:
        h["Content-Type"] = "application/json"
    return h


def get_agent_config(agent_id: str) -> dict:
    """Direct REST GET of the full agent payload."""
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.get(f"/v1/convai/agents/{agent_id}", headers=_headers(json=False))
    if r.status_code != 200:
        raise ElevenLabsWriteError(
            f"GET agent {agent_id} failed: {r.status_code} {r.text[:300]}"
        )
    return r.json()


def _patch_agent(agent_id: str, body: dict) -> httpx.Response:
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        return c.patch(
            f"/v1/convai/agents/{agent_id}", headers=_headers(), json=body
        )


# ─── Pure helpers ────────────────────────────────────────────────────────────
def assert_audio_event(client_events: Any) -> None:
    """Raise SilentAgentRiskError unless 'audio' is present in the list."""
    if not isinstance(client_events, list) or REQUIRED_AUDIO_EVENT not in client_events:
        raise SilentAgentRiskError(
            "Refusing write: 'audio' is missing from client_events — the agent would "
            "go silent on calls (LLM/text work, caller hears nothing)."
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_path(d: Any, dotted: str) -> Any:
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_path(d: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _union_list(current: list | None, incoming: list | None) -> list:
    """Order-preserving union. Lists of dicts dedupe by id/name; scalars by value."""
    current = list(current or [])
    incoming = list(incoming or [])
    combined = current + incoming
    if any(isinstance(x, dict) for x in combined):
        out: list = []
        seen: set = set()
        for x in combined:
            key = (x.get("id") or x.get("name")) if isinstance(x, dict) else x
            if key in seen:
                continue
            seen.add(key)
            out.append(x)
        return out
    out = list(current)
    for x in incoming:
        if x not in out:
            out.append(x)
    return out


def _deep_merge(base: dict, patch: dict, merge_paths: set[str], prefix: str = "") -> dict:
    """Deep-merge ``patch`` into a copy of ``base``.

    - paths in ``merge_paths`` whose value is a list are UNIONED with current,
    - nested dicts recurse,
    - everything else is replaced.
    """
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for k, v in patch.items():
        path = f"{prefix}.{k}" if prefix else k
        if path in merge_paths and isinstance(v, list):
            out[k] = _union_list(out.get(k) if isinstance(out.get(k), list) else [], v)
        elif isinstance(v, dict):
            base_child = out.get(k) if isinstance(out.get(k), dict) else {}
            out[k] = _deep_merge(base_child, v, merge_paths, path)
        else:
            out[k] = v
    return out


def _diff(old: Any, new: Any, prefix: str = "") -> dict[str, dict]:
    """Flatten changed leaves into {dotted_path: {old, new}}."""
    changes: dict[str, dict] = {}
    keys: set = set()
    if isinstance(old, dict):
        keys |= set(old)
    if isinstance(new, dict):
        keys |= set(new)
    for k in keys:
        ov = old.get(k) if isinstance(old, dict) else None
        nv = new.get(k) if isinstance(new, dict) else None
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(ov, dict) and isinstance(nv, dict):
            changes.update(_diff(ov, nv, path))
        elif ov != nv:
            changes[path] = {"old": ov, "new": nv}
    return changes


def _build_patch_body(merged: dict, changes: dict[str, dict]) -> dict:
    """Minimal surgical PATCH body: only the changed leaves, as a nested dict.

    Verified empirically that ElevenLabs deep-merges nested conversation_config
    objects — a surgical first_message patch preserves tools, the system prompt,
    and knowledge_base. Sending only changed leaves therefore preserves every
    customer-configured sibling without re-echoing read-only fields (built_in_tools,
    tool_ids, …). The post-write verification is the backstop: if a pre-existing
    tool disappears, the write is rolled back.
    """
    body: dict = {}
    for path in changes:
        _set_path(body, path, _get_path(merged, path))
    return body


def _compute_final_client_events(
    current: dict,
    field_patches: dict,
    merge_paths: set[str],
    required_client_events: list[str] | None,
) -> tuple[list[str], bool]:
    """Returns (final_client_events, touched). Encodes the strict-additive policy."""
    cur_ce = _get_path(current, CLIENT_EVENTS_PATH) or []
    explicit = _get_path(field_patches, CLIENT_EVENTS_PATH)
    req = list(required_client_events or [])
    if explicit is not None and CLIENT_EVENTS_PATH in merge_paths:
        # normal feature write: union of everything, audio guaranteed
        final = _union_list(_union_list(cur_ce, explicit), req + [REQUIRED_AUDIO_EVENT])
        return final, True
    if explicit is not None:
        # explicit replacement (not a merge): no base, NO auto-audio — let the
        # assertion reject it if the caller dropped audio.
        return _union_list(explicit, req), True
    if req:
        final = _union_list(cur_ce, req + [REQUIRED_AUDIO_EVENT])
        return final, final != cur_ce
    return cur_ce, False


# ─── Core safe write ─────────────────────────────────────────────────────────
def patch_agent_safely(
    *,
    agent_id: str,
    field_patches: dict,
    merge_arrays: list[str] | None = None,
    required_client_events: list[str] | None = None,
    actor_id: str | UUID | None,
    org_id: str | UUID,
    endpoint_label: str,
) -> dict:
    """Snapshot → merge → assert audio → PATCH → verify → audit. See module docstring."""
    merge_paths = set(merge_arrays or [])
    db = get_service_client()

    # 1) Cross-org guard (DB only — no ElevenLabs call).
    org_rows = (
        db.table("organizations")
        .select("elevenlabs_agent_id")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
    )
    stored = org_rows[0]["elevenlabs_agent_id"] if org_rows else None
    if not stored or stored != agent_id:
        raise CrossOrgAgentWriteError(
            f"agent_id {agent_id!r} does not match org {org_id} (stored {stored!r}). "
            "Refusing cross-org write."
        )

    # 2) Early audio guard for an explicit (non-merge) client_events replacement —
    #    rejects before any ElevenLabs call or snapshot.
    explicit_ce = _get_path(field_patches, CLIENT_EVENTS_PATH)
    if explicit_ce is not None and CLIENT_EVENTS_PATH not in merge_paths:
        assert_audio_event(_union_list(explicit_ce, list(required_client_events or [])))

    # 3) GET current full config.
    current = get_agent_config(agent_id)

    # 4) Merge patches into current; apply client_events policy.
    merged = _deep_merge(current, field_patches, merge_paths)
    final_ce, _touched = _compute_final_client_events(
        current, field_patches, merge_paths, required_client_events
    )
    _set_path(merged, CLIENT_EVENTS_PATH, final_ce)

    # 5) Assert audio on the FINAL client_events (no snapshot/PATCH if this fails).
    assert_audio_event(final_ce)

    # 6) Diff / no-op short-circuit (no snapshot, no PATCH).
    changes = _diff(current, merged)
    if not changes:
        return current

    # 7) Snapshot the full current config BEFORE writing.
    snap = (
        db.table("agent_config_snapshots")
        .insert(
            {
                "org_id": str(org_id),
                "agent_id": agent_id,
                "actor_id": str(actor_id) if actor_id else None,
                "endpoint_label": endpoint_label,
                "full_config": current,
            }
        )
        .execute()
        .data
    )
    snapshot_id = snap[0]["id"]

    # 8) PATCH (surgical — only changed leaves; EL deep-merges, siblings preserved).
    body = _build_patch_body(merged, changes)
    resp = _patch_agent(agent_id, body)
    status_code = resp.status_code
    excerpt = (resp.text or "")[:500]

    if status_code >= 300:
        _audit(
            db, org_id, agent_id, actor_id, endpoint_label, snapshot_id,
            changes, status_code, excerpt, rolled_back=False,
        )
        raise ElevenLabsWriteError(f"PATCH failed {status_code}: {excerpt}")

    # 9) Verify via re-GET; auto-rollback on failure.
    post = get_agent_config(agent_id)
    ok, reason = _verify(post, merged, current, changes)
    if not ok:
        _restore_full(agent_id, current)  # automatic rollback from snapshot
        _audit(
            db, org_id, agent_id, actor_id, endpoint_label, snapshot_id,
            changes, status_code, f"VERIFY FAILED: {reason}",
            rolled_back=True, rolled_back_by=actor_id,
        )
        raise VerificationFailedError(
            f"Post-write verification failed ({reason}); agent rolled back to snapshot."
        )

    # 10) Success audit.
    _audit(
        db, org_id, agent_id, actor_id, endpoint_label, snapshot_id,
        changes, status_code, excerpt, rolled_back=False,
    )
    return post


def _verify(post: dict, intended: dict, pre: dict, changes: dict) -> tuple[bool, str]:
    """Confirm the write landed without breaking the agent."""
    if not isinstance(post, dict) or not post.get("agent_id"):
        return False, "agent unreachable after write"
    ce = _get_path(post, CLIENT_EVENTS_PATH) or []
    if REQUIRED_AUDIO_EVENT not in ce:
        return False, "audio event missing after write"
    # Intended changes actually took effect.
    for path, ch in changes.items():
        actual = _get_path(post, path)
        new = ch["new"]
        if isinstance(new, list):
            if all(isinstance(x, dict) for x in new):
                if len(actual or []) < len(new):
                    return False, f"array {path} not fully applied"
            else:
                missing = set(map(str, new)) - set(map(str, actual or []))
                if missing:
                    return False, f"array {path} missing {missing}"
        elif actual != new:
            return False, f"{path} did not apply"
    # Defense-in-depth: pre-existing tools must not have shrunk (clobber guard).
    if len(_get_path(post, TOOLS_PATH) or []) < len(_get_path(pre, TOOLS_PATH) or []):
        return False, "tools array shrank after write (clobber risk)"
    return True, "ok"


def _restore_full(agent_id: str, full_config: dict) -> None:
    """Direct restore PATCH of the writable sections from a snapshot."""
    body: dict = {"conversation_config": full_config.get("conversation_config")}
    if "name" in full_config:
        body["name"] = full_config.get("name")
    _patch_agent(agent_id, body)


def _audit(
    db, org_id, agent_id, actor_id, endpoint_label, snapshot_id, changes,
    status_code, excerpt, *, rolled_back=False, rolled_back_by=None,
) -> None:
    row = {
        "org_id": str(org_id),
        "agent_id": agent_id,
        "actor_id": str(actor_id) if actor_id else None,
        "endpoint_label": endpoint_label,
        "snapshot_id": snapshot_id,
        "fields_changed": changes,
        "elevenlabs_response_status": status_code,
        "elevenlabs_response_excerpt": excerpt,
        "rolled_back": rolled_back,
    }
    if rolled_back:
        row["rolled_back_at"] = _now()
        row["rolled_back_by"] = str(rolled_back_by) if rolled_back_by else None
    db.table("agent_writes_audit").insert(row).execute()


def rollback_to_snapshot(*, snapshot_id: str | UUID, actor_id: str | UUID | None) -> dict:
    """Restore the agent to a snapshot's full config (itself a safe, audited write)."""
    db = get_service_client()
    rows = (
        db.table("agent_config_snapshots")
        .select("*")
        .eq("id", str(snapshot_id))
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise ElevenLabsWriteError(f"snapshot {snapshot_id} not found")
    snap = rows[0]
    full = snap["full_config"] or {}
    new_config = patch_agent_safely(
        agent_id=snap["agent_id"],
        field_patches={
            "name": full.get("name"),
            "conversation_config": full.get("conversation_config") or {},
        },
        merge_arrays=[],  # restore exactly, not additively
        actor_id=actor_id,
        org_id=snap["org_id"],
        endpoint_label="rollback",
    )
    db.table("agent_writes_audit").update(
        {
            "rolled_back": True,
            "rolled_back_at": _now(),
            "rolled_back_by": str(actor_id) if actor_id else None,
        }
    ).eq("snapshot_id", str(snapshot_id)).eq("rolled_back", False).neq(
        "endpoint_label", "rollback"
    ).execute()
    return new_config


# ─── Read-only probes ────────────────────────────────────────────────────────
def agent_health_check(agent_id: str) -> dict:
    """Read-only health probe used by the Agent-Gesundheit badge."""
    try:
        cfg = get_agent_config(agent_id)
    except Exception as exc:  # noqa: BLE001
        return {
            "reachable": False,
            "audio_event_present": False,
            "prompt_non_empty": False,
            "first_message_non_empty": False,
            "voice_set": False,
            "language": None,
            "error": str(exc)[:200],
            "last_check_at": _now(),
        }
    ce = _get_path(cfg, CLIENT_EVENTS_PATH) or []
    return {
        "reachable": True,
        "audio_event_present": REQUIRED_AUDIO_EVENT in ce,
        "prompt_non_empty": bool((_get_path(cfg, PROMPT_PATH) or "").strip()),
        "first_message_non_empty": bool((_get_path(cfg, FIRST_MESSAGE_PATH) or "").strip()),
        "voice_set": bool(_get_path(cfg, VOICE_PATH)),
        "language": _get_path(cfg, LANGUAGE_PATH),
        "last_check_at": _now(),
    }


def list_knowledge_base(agent_id: str) -> list[dict]:
    """The agent's attached knowledge-base documents."""
    cfg = get_agent_config(agent_id)
    return _get_path(cfg, KB_PATH) or []


# ─── Knowledge-base push / remove ────────────────────────────────────────────
def _kb_create_from_url(url: str, name: str) -> dict:
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.post(
            "/v1/convai/knowledge-base/url",
            headers=_headers(),
            json={"url": url, "name": name},
        )
    if r.status_code >= 300:
        raise ElevenLabsWriteError(f"KB url create failed {r.status_code}: {r.text[:300]}")
    return r.json()


def _kb_create_from_file(filename: str, content: bytes, name: str) -> dict:
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.post(
            "/v1/convai/knowledge-base/file",
            headers=_headers(json=False),
            files={"file": (filename, content)},
            data={"name": name},
        )
    if r.status_code >= 300:
        raise ElevenLabsWriteError(f"KB file create failed {r.status_code}: {r.text[:300]}")
    return r.json()


def _kb_get(doc_id: str) -> dict:
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.get(f"/v1/convai/knowledge-base/{doc_id}", headers=_headers(json=False))
    if r.status_code >= 300:
        raise ElevenLabsWriteError(f"KB get failed {r.status_code}: {r.text[:300]}")
    return r.json()


def _kb_delete(doc_id: str) -> None:
    with httpx.Client(base_url=EL_BASE, timeout=_TIMEOUT) as c:
        r = c.delete(
            f"/v1/convai/knowledge-base/{doc_id}?force=true", headers=_headers(json=False)
        )
    if r.status_code >= 300 and r.status_code != 404:
        raise ElevenLabsWriteError(f"KB delete failed {r.status_code}: {r.text[:300]}")


def push_knowledge_resource_to_elevenlabs(*, resource_id: str | UUID) -> dict:
    """Create the KB document, attach it to the agent (additively), persist doc id."""
    db = get_service_client()
    rows = (
        db.table("knowledge_resources").select("*").eq("id", str(resource_id)).limit(1)
        .execute().data
    )
    if not rows:
        raise ElevenLabsWriteError(f"knowledge_resource {resource_id} not found")
    res = rows[0]
    org_id = res["org_id"]
    agent_id = get_org_agent_id(org_id)

    db.table("knowledge_resources").update({"status": "processing", "updated_at": _now()}).eq(
        "id", str(resource_id)
    ).execute()

    try:
        if res["kind"] == "url":
            created = _kb_create_from_url(res["source"], res["display_name"])
        else:
            signed = db.storage.from_("agent-knowledge").create_signed_url(res["source"], 600)
            file_url = signed.get("signedURL") or signed.get("signedUrl")
            content = httpx.get(file_url, timeout=_TIMEOUT).content
            created = _kb_create_from_file(res["display_name"], content, res["display_name"])
        doc_id = created.get("id")

        # Attach to the agent additively (snapshot + audit + audio assertion all apply).
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {
                    "agent": {
                        "prompt": {
                            "knowledge_base": [
                                {
                                    "type": res["kind"],
                                    "id": doc_id,
                                    "name": res["display_name"],
                                    "usage_mode": "auto",
                                }
                            ]
                        }
                    }
                }
            },
            merge_arrays=[KB_PATH],
            actor_id=None,
            org_id=org_id,
            endpoint_label="knowledge_resource_push",
        )

        # Best-effort chunk count + ready status.
        chunk_count = 0
        try:
            detail = _kb_get(doc_id)
            chunk_count = (
                detail.get("chunk_count")
                or len(detail.get("chunks") or [])
                or (1 if detail else 0)
            )
        except Exception:  # noqa: BLE001
            chunk_count = 1
        db.table("knowledge_resources").update(
            {
                "status": "ready",
                "elevenlabs_doc_id": doc_id,
                "chunk_count": chunk_count,
                "status_message": None,
                "updated_at": _now(),
            }
        ).eq("id", str(resource_id)).execute()
        return {"doc_id": doc_id, "chunk_count": chunk_count, "status": "ready"}
    except Exception as exc:  # noqa: BLE001
        db.table("knowledge_resources").update(
            {"status": "error", "status_message": str(exc)[:300], "updated_at": _now()}
        ).eq("id", str(resource_id)).execute()
        raise


def remove_knowledge_resource_from_elevenlabs(*, resource_id: str | UUID) -> None:
    """Detach the doc from the agent (audited) and delete it from the KB."""
    db = get_service_client()
    rows = (
        db.table("knowledge_resources").select("*").eq("id", str(resource_id)).limit(1)
        .execute().data
    )
    if not rows:
        return
    res = rows[0]
    doc_id = res.get("elevenlabs_doc_id")
    if not doc_id:
        return
    org_id = res["org_id"]
    agent_id = get_org_agent_id(org_id)

    current = get_agent_config(agent_id)
    kb = _get_path(current, KB_PATH) or []
    pruned = [d for d in kb if d.get("id") != doc_id]
    if len(pruned) != len(kb):
        patch_agent_safely(
            agent_id=agent_id,
            field_patches={
                "conversation_config": {"agent": {"prompt": {"knowledge_base": pruned}}}
            },
            merge_arrays=[],  # explicit, targeted removal of one resource
            actor_id=None,
            org_id=org_id,
            endpoint_label="knowledge_resource_remove",
        )
    _kb_delete(doc_id)


# ─── Small shared helper for routes ──────────────────────────────────────────
def get_org_agent_id(org_id: str | UUID) -> str:
    db = get_service_client()
    rows = (
        db.table("organizations")
        .select("elevenlabs_agent_id")
        .eq("id", str(org_id))
        .limit(1)
        .execute()
        .data
    )
    agent_id = rows[0]["elevenlabs_agent_id"] if rows else None
    if not agent_id:
        raise ElevenLabsWriteError(f"org {org_id} has no elevenlabs_agent_id")
    return agent_id
