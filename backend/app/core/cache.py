"""Org-scoped Redis cache (Item 4 — BUILD-ONLY, dormant until REDIS_URL is set).

This layer exists to speed up read-heavy, per-org endpoints. It is built to be
SAFE to merge while staying inert in production until Amber enables it:

1. **Disabled by default.** When ``settings.redis_url`` is empty (the default), the
   cache is OFF: ``get_or_set`` just calls the loader, ``get`` misses, ``set`` /
   ``invalidate`` are no-ops. The app behaves exactly as it does without Redis.

2. **Org-scoped keys ONLY.** The public API *requires* ``org_id`` and namespaces
   every key as ``{prefix}:org:{org_id}:{name}``. There is no way to read or write a
   key without an org_id, so one tenant's cache can never be served to another. A
   falsy ``org_id`` short-circuits to a miss/no-op (never caches across orgs).

3. **Fail-open.** Any Redis error is logged and treated as a miss / no-op — a cache
   problem never breaks a request and never serves wrong data.

The real client is created lazily from ``redis_url`` (the ``redis`` package is
imported only then, so it isn't required unless caching is enabled). Tests inject
an in-memory fake via :func:`set_test_client`.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from app.core.config import settings

log = logging.getLogger(__name__)

# Sentinel client states: None = not yet initialised; False = init failed/disabled.
_client: Any = None
_init_done = False
_test_client: Any = None


def set_test_client(client: Any) -> None:
    """Inject a fake Redis client (tests only). Pass ``None`` to clear."""
    global _test_client, _client, _init_done
    _test_client = client
    _client = None
    _init_done = False


def _get_client() -> Any:
    """Return a live client, or None when caching is disabled/unavailable."""
    global _client, _init_done
    if _test_client is not None:
        return _test_client
    if _init_done:
        return _client
    _init_done = True
    url = (settings.redis_url or "").strip()
    if not url:
        _client = None  # disabled — no REDIS_URL configured
        return None
    try:
        import redis  # lazy: only needed when caching is actually enabled

        _client = redis.Redis.from_url(
            url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0
        )
        log.info("cache: Redis client initialised (caching enabled)")
    except Exception as exc:  # noqa: BLE001 — fail-open: never block startup on cache
        log.warning("cache: Redis init failed (%s) — caching disabled", exc)
        _client = None
    return _client


def enabled() -> bool:
    """True when a usable cache backend is configured (REDIS_URL set / test client)."""
    return _get_client() is not None


def org_key(org_id: str, name: str) -> str:
    """Namespaced, org-scoped key. The ONLY way keys are built — guarantees every
    cached value is partitioned by org_id."""
    return f"{settings.cache_prefix}:org:{org_id}:{name}"


def get(org_id: str | None, name: str) -> Any | None:
    """Return the cached value for (org, name), or None on miss/disabled/error."""
    client = _get_client()
    if client is None or not org_id:
        return None
    try:
        raw = client.get(org_key(org_id, name))
        return json.loads(raw) if raw is not None else None
    except Exception as exc:  # noqa: BLE001 — fail-open
        log.warning("cache.get failed for org=%s name=%s: %s", org_id, name, exc)
        return None


def set(org_id: str | None, name: str, value: Any, ttl: int | None = None) -> None:
    """Cache ``value`` for (org, name) with a TTL (defaults to cache_default_ttl).
    No-op when disabled, org_id is falsy, or the value isn't JSON-serialisable."""
    client = _get_client()
    if client is None or not org_id:
        return
    try:
        payload = json.dumps(value, default=str)
    except (TypeError, ValueError) as exc:
        log.warning("cache.set skip (unserialisable) org=%s name=%s: %s", org_id, name, exc)
        return
    try:
        client.setex(org_key(org_id, name), ttl or settings.cache_default_ttl, payload)
    except Exception as exc:  # noqa: BLE001 — fail-open
        log.warning("cache.set failed for org=%s name=%s: %s", org_id, name, exc)


def get_or_set(
    org_id: str | None, name: str, loader: Callable[[], Any], ttl: int | None = None
) -> Any:
    """Return the cached value, or call ``loader()``, cache its result, and return it.

    When caching is disabled (or org_id is falsy), this is exactly ``loader()`` —
    so wiring it into a read path is a no-op until Redis is configured.
    """
    if not org_id or not enabled():
        return loader()
    hit = get(org_id, name)
    if hit is not None:
        return hit
    value = loader()
    if value is not None:
        set(org_id, name, value, ttl)
    return value


def invalidate(org_id: str | None, name: str) -> None:
    """Delete one cached entry. No-op when disabled or org_id is falsy."""
    client = _get_client()
    if client is None or not org_id:
        return
    try:
        client.delete(org_key(org_id, name))
    except Exception as exc:  # noqa: BLE001 — fail-open
        log.warning("cache.invalidate failed for org=%s name=%s: %s", org_id, name, exc)


def invalidate_org(org_id: str | None) -> None:
    """Delete EVERY cached entry for an org (blanket per-tenant flush). Scoped to
    ``{prefix}:org:{org_id}:*`` so it can never touch another org's keys."""
    client = _get_client()
    if client is None or not org_id:
        return
    pattern = f"{settings.cache_prefix}:org:{org_id}:*"
    try:
        keys = list(client.scan_iter(match=pattern))
        if keys:
            client.delete(*keys)
    except Exception as exc:  # noqa: BLE001 — fail-open
        log.warning("cache.invalidate_org failed for org=%s: %s", org_id, exc)
