from functools import lru_cache

import httpx
from supabase import Client, create_client

from app.core.config import settings


@lru_cache
def get_service_client() -> Client:
    """Process-wide service-role Supabase client. Bypasses RLS — backend-only,
    NEVER expose to the browser.

    Thread-safety: ONE client (wrapping an ``httpx.Client``) is shared across the
    request event loop and every AnyIO threadpool worker. Many handlers fan out
    concurrent reads on it — ``asyncio.gather(run_in_threadpool(...))`` (e.g.
    ``customers._list``, ``dashboard``) and ``run_parallel`` (timelines).

    The PostgREST session is forced to **HTTP/1.1** (below). PostgREST's default
    httpx client uses HTTP/2, which multiplexes EVERY concurrent request onto a
    SINGLE connection — a sync ``httpx.Client`` can't safely share that one
    connection across threads, so the fan-out intermittently corrupts it
    (``httpx.RemoteProtocolError: ConnectionTerminated``) and the endpoint 500s
    (observed on ``/api/customers``, spiky/timing-dependent). HTTP/1.1 uses a
    connection POOL (a separate connection per concurrent request), which IS safe
    for concurrent thread use. We never mutate shared client state after construction.
    Sync calls MUST run via ``run_in_threadpool`` from async handlers (never block the loop).

    ``@lru_cache`` makes this a singleton for connection reuse; credential/URL env
    changes are only picked up on restart. Tests can ``get_service_client.cache_clear()``.
    """
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in the backend environment."
        )
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    # Swap the PostgREST session's HTTP/2 client for an HTTP/1.1 one (reusing the
    # base_url + auth headers PostgREST already computed). This is the data path used
    # by every ``.table(...)`` query, so it fixes the concurrent-fan-out 500s globally.
    pg = client.postgrest  # property → lazily builds the sub-client
    _default = pg.session
    pg.session = httpx.Client(
        base_url=_default.base_url,
        headers=_default.headers,
        timeout=pg.timeout,
        follow_redirects=True,
        http2=False,
    )
    try:
        _default.close()
    except Exception:  # noqa: BLE001 — best-effort cleanup of the unused default session
        pass
    return client
