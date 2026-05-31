"""Item 4 — org-scoped cache layer (hermetic; in-memory fake Redis).

The non-negotiable property is CROSS-ORG ISOLATION: a value cached for org A must
never be returned for org B. Also covered: disabled-by-default no-op, get_or_set
caching, invalidation, per-org flush, and fail-open on Redis errors.
"""
import fnmatch

import pytest

from app.core import cache


class FakeRedis:
    """Minimal in-memory stand-in (decode_responses=True semantics)."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, ttl, v):
        self.store[k] = v

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)

    def scan_iter(self, match=None):
        for k in list(self.store):
            if match is None or fnmatch.fnmatch(k, match):
                yield k


class RaisingRedis(FakeRedis):
    def get(self, k):
        raise RuntimeError("redis down")

    def setex(self, k, ttl, v):
        raise RuntimeError("redis down")


@pytest.fixture(autouse=True)
def _reset_cache():
    cache.set_test_client(None)
    yield
    cache.set_test_client(None)


# ─── Disabled by default ──────────────────────────────────────────────────────
def test_disabled_by_default_is_noop():
    assert cache.enabled() is False
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return {"v": 1}

    assert cache.get_or_set("org-A", "k", loader) == {"v": 1}
    assert cache.get_or_set("org-A", "k", loader) == {"v": 1}
    assert calls["n"] == 2  # never cached → loader runs every time
    assert cache.get("org-A", "k") is None


# ─── get_or_set caches ────────────────────────────────────────────────────────
def test_get_or_set_caches_after_first_load():
    cache.set_test_client(FakeRedis())
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return {"v": 42}

    assert cache.get_or_set("org-A", "settings", loader) == {"v": 42}
    assert cache.get_or_set("org-A", "settings", loader) == {"v": 42}
    assert calls["n"] == 1  # second call served from cache


# ─── CROSS-ORG ISOLATION (the critical property) ─────────────────────────────
def test_value_cached_for_one_org_is_never_served_to_another():
    cache.set_test_client(FakeRedis())
    cache.set("org-A", "secret", {"owner": "A"})
    assert cache.get("org-A", "secret") == {"owner": "A"}
    # Same logical name, different org → miss (keys are namespaced by org_id).
    assert cache.get("org-B", "secret") is None


def test_keys_are_namespaced_by_org():
    assert cache.org_key("org-A", "x") == "kj:org:org-A:x"
    assert cache.org_key("org-B", "x") == "kj:org:org-B:x"
    assert cache.org_key("org-A", "x") != cache.org_key("org-B", "x")


def test_falsy_org_id_never_caches():
    cache.set_test_client(FakeRedis())
    calls = {"n": 0}
    cache.set("", "k", {"v": 1})           # no-op
    cache.set(None, "k", {"v": 1})         # no-op
    assert cache.get("", "k") is None
    assert cache.get_or_set(None, "k", lambda: (calls.__setitem__("n", calls["n"] + 1) or {"v": 9})) == {"v": 9}
    assert calls["n"] == 1                 # loader ran; nothing cached


# ─── Invalidation ─────────────────────────────────────────────────────────────
def test_invalidate_removes_entry():
    cache.set_test_client(FakeRedis())
    cache.set("org-A", "k", {"v": 1})
    cache.invalidate("org-A", "k")
    assert cache.get("org-A", "k") is None


def test_invalidate_org_only_flushes_that_org():
    fake = FakeRedis()
    cache.set_test_client(fake)
    cache.set("org-A", "a1", {"v": 1})
    cache.set("org-A", "a2", {"v": 2})
    cache.set("org-B", "b1", {"v": 3})
    cache.invalidate_org("org-A")
    assert cache.get("org-A", "a1") is None
    assert cache.get("org-A", "a2") is None
    assert cache.get("org-B", "b1") == {"v": 3}  # untouched


# ─── Fail-open ────────────────────────────────────────────────────────────────
def test_fail_open_on_redis_error():
    cache.set_test_client(RaisingRedis())
    # get returns None (miss), get_or_set falls back to the loader, nothing raises.
    assert cache.get("org-A", "k") is None
    assert cache.get_or_set("org-A", "k", lambda: {"v": 7}) == {"v": 7}
