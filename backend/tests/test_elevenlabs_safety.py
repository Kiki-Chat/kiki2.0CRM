"""Hermetic unit tests for the ElevenLabs safety layer.

No network, no DB: the ElevenLabs HTTP functions are replaced by an in-memory
FakeServer and get_service_client by a FakeDB that records inserts/updates.
"""

import copy

import pytest

from app.services import elevenlabs_agent as ea

AGENT = "agent_unit_test_xyz"


def base_cfg(agent_id: str = AGENT) -> dict:
    return {
        "agent_id": agent_id,
        "name": "Demo",
        "conversation_config": {
            "agent": {
                "first_message": "Hi",
                "language": "en",
                "prompt": {
                    "prompt": "OLD PROMPT",
                    "tools": [{"id": "t1", "name": "hk_a"}, {"id": "t2", "name": "hk_b"}],
                    "knowledge_base": [],
                },
            },
            "tts": {"voice_id": "v1"},
            "conversation": {
                "client_events": ["audio", "interruption", "agent_response"]
            },
        },
    }


# ─── Fakes ───────────────────────────────────────────────────────────────────
class _HTTP:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text


def _deep_apply(dst: dict, src: dict) -> None:
    """Model ElevenLabs' confirmed deep-merge of nested conversation_config objects."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_apply(dst[k], v)
        else:
            dst[k] = v


class FakeServer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.patches = []
        self.get_calls = 0

    def get(self, agent_id):
        self.get_calls += 1
        return copy.deepcopy(self.cfg)

    def patch(self, agent_id, body):
        self.patches.append(copy.deepcopy(body))
        _deep_apply(self.cfg, body)
        return _HTTP(200, "ok")


class BreakingServer(FakeServer):
    """Drops the audio event on the FIRST patch to force a verification failure."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self._broke = False

    def patch(self, agent_id, body):
        resp = super().patch(agent_id, body)
        if not self._broke:
            self._broke = True
            self.cfg["conversation_config"]["conversation"]["client_events"] = [
                "agent_response"
            ]
        return resp


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self._op == "insert":
            self.store["inserts"].append((self.table, self._payload))
            data = (
                [{"id": "snap-1"}]
                if self.table == "agent_config_snapshots"
                else [dict(self._payload, id="row-1")]
            )
            return _Res(data)
        if self._op == "update":
            self.store["updates"].append((self.table, self._payload))
            return _Res([])
        return _Res(self.store["canned"].get(self.table, []))


class FakeDB:
    def __init__(self, canned):
        self.store = {"canned": canned, "inserts": [], "updates": []}

    def table(self, name):
        return _Q(name, self.store)


def _wire(monkeypatch, server, db):
    monkeypatch.setattr(ea, "get_service_client", lambda: db)
    monkeypatch.setattr(ea, "get_agent_config", server.get)
    monkeypatch.setattr(ea, "_patch_agent", server.patch)


def _db(agent_id=AGENT, extra=None):
    canned = {"organizations": [{"elevenlabs_agent_id": agent_id}]}
    if extra:
        canned.update(extra)
    return FakeDB(canned)


# ─── Tests ───────────────────────────────────────────────────────────────────
def test_patch_prompt_writes_snapshot_and_audit(monkeypatch):
    server = FakeServer(base_cfg())
    db = _db()
    _wire(monkeypatch, server, db)

    out = ea.patch_agent_safely(
        agent_id=AGENT,
        field_patches={"conversation_config": {"agent": {"prompt": {"prompt": "NEW"}}}},
        actor_id="u1",
        org_id="o1",
        endpoint_label="prompt",
    )

    assert ea._get_path(out, ea.PROMPT_PATH) == "NEW"
    inserted = [t for t, _ in db.store["inserts"]]
    assert "agent_config_snapshots" in inserted
    assert "agent_writes_audit" in inserted
    # Existing tools preserved (not clobbered by the prompt write).
    assert len(ea._get_path(out, ea.TOOLS_PATH)) == 2


def test_client_events_without_audio_raises_no_write(monkeypatch):
    server = FakeServer(base_cfg())
    db = _db()
    _wire(monkeypatch, server, db)

    with pytest.raises(ea.SilentAgentRiskError):
        ea.patch_agent_safely(
            agent_id=AGENT,
            field_patches={"conversation_config": {"conversation": {"client_events": []}}},
            actor_id="u1",
            org_id="o1",
            endpoint_label="x",
        )
    assert server.patches == []  # no PATCH issued
    assert server.get_calls == 0  # rejected before the GET
    assert db.store["inserts"] == []  # no snapshot wasted


def test_cross_org_raises_no_http(monkeypatch):
    server = FakeServer(base_cfg())
    db = _db(agent_id="agent_some_other_org")
    _wire(monkeypatch, server, db)

    with pytest.raises(ea.CrossOrgAgentWriteError):
        ea.patch_agent_safely(
            agent_id=AGENT,
            field_patches={"name": "X"},
            actor_id="u1",
            org_id="o1",
            endpoint_label="x",
        )
    assert server.get_calls == 0
    assert server.patches == []
    assert db.store["inserts"] == []


def test_noop_returns_without_snapshot_or_patch(monkeypatch):
    server = FakeServer(base_cfg())
    db = _db()
    _wire(monkeypatch, server, db)

    out = ea.patch_agent_safely(
        agent_id=AGENT,
        field_patches={"name": "Demo"},  # identical to current
        actor_id="u1",
        org_id="o1",
        endpoint_label="x",
    )
    assert out["name"] == "Demo"
    assert server.patches == []
    assert db.store["inserts"] == []


def test_verification_failure_triggers_rollback(monkeypatch):
    server = BreakingServer(base_cfg())
    db = _db()
    _wire(monkeypatch, server, db)

    with pytest.raises(ea.VerificationFailedError):
        ea.patch_agent_safely(
            agent_id=AGENT,
            field_patches={"conversation_config": {"agent": {"first_message": "Neu"}}},
            actor_id="u1",
            org_id="o1",
            endpoint_label="verhalten",
        )
    # write PATCH + rollback PATCH both issued
    assert len(server.patches) >= 2
    audits = [p for t, p in db.store["inserts"] if t == "agent_writes_audit"]
    assert audits and audits[-1]["rolled_back"] is True
    # audio restored from snapshot
    assert "audio" in server.cfg["conversation_config"]["conversation"]["client_events"]


def test_rollback_to_snapshot_restores_and_audits(monkeypatch):
    snap_cfg = base_cfg()
    snap_cfg["name"] = "ORIGINAL"
    server = FakeServer(base_cfg())
    server.cfg["name"] = "CHANGED"
    db = _db(
        extra={
            "agent_config_snapshots": [
                {
                    "id": "snap-1",
                    "agent_id": AGENT,
                    "org_id": "o1",
                    "full_config": snap_cfg,
                }
            ]
        }
    )
    _wire(monkeypatch, server, db)

    out = ea.rollback_to_snapshot(snapshot_id="snap-1", actor_id="u1")

    assert out["name"] == "ORIGINAL"  # agent restored
    audit_inserts = [p for t, p in db.store["inserts"] if t == "agent_writes_audit"]
    assert any(p["endpoint_label"] == "rollback" for p in audit_inserts)
    audit_updates = [p for t, p in db.store["updates"] if t == "agent_writes_audit"]
    assert audit_updates and audit_updates[0]["rolled_back"] is True


def test_tools_union_preserves_existing(monkeypatch):
    server = FakeServer(base_cfg())
    db = _db()
    _wire(monkeypatch, server, db)

    out = ea.patch_agent_safely(
        agent_id=AGENT,
        field_patches={
            "conversation_config": {
                "agent": {"prompt": {"tools": [{"id": "t3", "name": "hk_c"}]}}
            }
        },
        merge_arrays=[ea.TOOLS_PATH],
        actor_id="u1",
        org_id="o1",
        endpoint_label="tools",
    )
    ids = {t["id"] for t in ea._get_path(out, ea.TOOLS_PATH)}
    assert ids == {"t1", "t2", "t3"}  # existing preserved + new added


def test_client_events_union_always_keeps_audio(monkeypatch):
    server = FakeServer(base_cfg())
    db = _db()
    _wire(monkeypatch, server, db)

    out = ea.patch_agent_safely(
        agent_id=AGENT,
        field_patches={
            "conversation_config": {
                "conversation": {"client_events": ["user_transcript"]}
            }
        },
        merge_arrays=[ea.CLIENT_EVENTS_PATH],
        actor_id="u1",
        org_id="o1",
        endpoint_label="verhalten",
    )
    ce = ea._get_path(out, ea.CLIENT_EVENTS_PATH)
    assert "audio" in ce  # never stripped
    assert "user_transcript" in ce  # added
    assert "interruption" in ce  # pre-existing preserved
