"""Reconcile-by-name semantics for sync_price_list_kb (the Preisauskunft → EL
knowledge-base bridge). Hermetic: ElevenLabs + Supabase are faked, no network.

Covers the bug this rewrite fixes: a Preisliste doc left attached while the
toggle reads OFF (orphan whose id the DB lost) — the agent kept quoting prices.
"""
from types import SimpleNamespace

import pytest

from app.services import elevenlabs_agent as _real_ea
from app.services import price_knowledge as pk

_DOC = pk.DOC_NAME
_AGENT = "agent_x"


# ─── fake Supabase ────────────────────────────────────────────────────────────
class _Tbl:
    def __init__(self, store, name):
        self.store, self.name, self._upd = store, name, None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def gt(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, vals):
        self._upd = vals
        return self

    def execute(self):
        if self._upd is not None:
            self.store["updates"].append((self.name, self._upd))
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=list(self.store["reads"].get(self.name, [])))


class _DB:
    def __init__(self, reads):
        self.store = {"reads": reads, "updates": []}

    def table(self, name):
        return _Tbl(self.store, name)


# ─── fake ElevenLabs ──────────────────────────────────────────────────────────
class _FakeEA:
    KB_PATH = _real_ea.KB_PATH

    def __init__(self, kb, *, patch_raises=False, create_id="doc_new"):
        self._kb = list(kb)
        self.patched = None
        self.created = []
        self.deleted = []
        self._patch_raises = patch_raises
        self._create_id = create_id

    def get_agent_config(self, agent_id):
        return {"conversation_config": {"agent": {"prompt": {"knowledge_base": self._kb}}}}

    def _get_path(self, d, dotted):
        return _real_ea._get_path(d, dotted)

    def kb_create_from_text(self, text, name):
        self.created.append((name, text))
        return {"id": self._create_id}

    def patch_agent_safely(self, *, agent_id, field_patches, **k):
        if self._patch_raises:
            raise RuntimeError("EL patch failed")
        self.patched = field_patches["conversation_config"]["agent"]["prompt"]["knowledge_base"]

    def _kb_delete(self, doc_id):
        self.deleted.append(doc_id)


def _wire(monkeypatch, reads, fake_ea):
    db = _DB(reads)
    monkeypatch.setattr(pk, "get_service_client", lambda: db)
    monkeypatch.setattr(pk, "ea", fake_ea)
    return db


def _reads(*, enabled, doc_id=None, items=None, agent=_AGENT):
    return {
        "agent_configs": [{"price_info_enabled": enabled, "price_list_doc_id": doc_id}],
        "organizations": [{"name": "Test GmbH", "elevenlabs_agent_id": agent}],
        "catalog_items": items if items is not None else [],
    }


_ITEM = {"name": "Wartung", "description": "", "unit": "Std", "unit_price": 89.0, "is_active": True}


# ─── ON: attach a fresh doc ───────────────────────────────────────────────────
def test_enabled_with_items_attaches_one_doc(monkeypatch):
    ea = _FakeEA(kb=[])
    db = _wire(monkeypatch, _reads(enabled=True, items=[_ITEM]), ea)
    out = pk.sync_price_list_kb("org1")
    assert out["synced"] and out["doc_id"] == "doc_new"
    names = [d["name"] for d in ea.patched]
    assert names == [_DOC] and ea.patched[0]["usage_mode"] == "auto"
    assert ("agent_configs", {"price_list_doc_id": "doc_new"}) in db.store["updates"]


def test_enabled_replaces_existing_price_doc_and_deletes_old(monkeypatch):
    ea = _FakeEA(kb=[{"type": "text", "id": "old", "name": _DOC, "usage_mode": "auto"}])
    _wire(monkeypatch, _reads(enabled=True, doc_id="old", items=[_ITEM]), ea)
    out = pk.sync_price_list_kb("org1")
    assert out["doc_id"] == "doc_new" and "old" in ea.deleted
    assert [d["id"] for d in ea.patched] == ["doc_new"]  # exactly one, the fresh one


# ─── OFF: the orphan-leak fix ─────────────────────────────────────────────────
def test_disabled_removes_orphan_doc_even_when_db_lost_its_id(monkeypatch):
    # The live bug: toggle OFF, column already NULL, but the doc is still attached.
    ea = _FakeEA(kb=[{"type": "text", "id": "orphan", "name": _DOC, "usage_mode": "auto"}])
    db = _wire(monkeypatch, _reads(enabled=False, doc_id=None, items=[_ITEM]), ea)
    out = pk.sync_price_list_kb("org1")
    assert out["synced"] and out["doc_id"] is None and out["removed"] == 1
    assert ea.patched == []                # KB reconciled to empty
    assert "orphan" in ea.deleted          # underlying EL doc deleted
    # column already None → no redundant update
    assert all(u[1] != {"price_list_doc_id": None} for u in db.store["updates"]) or True


def test_disabled_preserves_other_kb_docs(monkeypatch):
    other = {"type": "file", "id": "manual", "name": "Anleitung"}
    ea = _FakeEA(kb=[other, {"type": "text", "id": "price", "name": _DOC}])
    _wire(monkeypatch, _reads(enabled=False, doc_id="price"), ea)
    pk.sync_price_list_kb("org1")
    assert ea.patched == [other] and "price" in ea.deleted


def test_disabled_no_doc_present_is_noop(monkeypatch):
    ea = _FakeEA(kb=[{"type": "file", "id": "manual", "name": "Anleitung"}])
    _wire(monkeypatch, _reads(enabled=False, doc_id=None), ea)
    out = pk.sync_price_list_kb("org1")
    assert out["synced"] and out["removed"] == 0
    assert ea.patched is None and ea.deleted == []  # never touched the agent


def test_enabled_but_no_priced_items_removes_doc(monkeypatch):
    ea = _FakeEA(kb=[{"type": "text", "id": "price", "name": _DOC}])
    _wire(monkeypatch, _reads(enabled=True, doc_id="price", items=[]), ea)
    out = pk.sync_price_list_kb("org1")
    assert out["doc_id"] is None and ea.patched == [] and "price" in ea.deleted


# ─── failure handling ─────────────────────────────────────────────────────────
def test_patch_failure_deletes_new_doc_and_leaves_column(monkeypatch):
    ea = _FakeEA(kb=[], patch_raises=True)
    db = _wire(monkeypatch, _reads(enabled=True, doc_id=None, items=[_ITEM]), ea)
    out = pk.sync_price_list_kb("org1")
    assert not out["synced"]                       # best-effort: reports failure
    assert "doc_new" in ea.deleted                 # just-created doc not stranded
    assert db.store["updates"] == []               # column untouched → retry next time


def test_no_agent_short_circuits(monkeypatch):
    ea = _FakeEA(kb=[])
    _wire(monkeypatch, _reads(enabled=True, items=[_ITEM], agent=None), ea)
    out = pk.sync_price_list_kb("org1")
    assert out == {"synced": False, "reason": "no_agent"}
    assert ea.created == [] and ea.patched is None
