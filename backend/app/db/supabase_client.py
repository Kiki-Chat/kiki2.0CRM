from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


@lru_cache
def get_service_client() -> Client:
    """Process-wide service-role Supabase client. Bypasses RLS — backend-only,
    NEVER expose to the browser.

    Thread-safety contract: ONE client (wrapping an ``httpx.Client``) is shared
    across the request event loop and every AnyIO threadpool worker. This is safe
    because the client is only ever used to EXECUTE requests concurrently
    (``httpx.Client`` supports concurrent requests over its connection pool) — we
    never mutate shared client state (headers/auth/base_url) after construction.
    Each call builds an independent query via ``.table(...)``, so concurrent reads
    (incl. ``run_parallel`` fan-out) don't share mutable state. Sync calls MUST be
    run via ``run_in_threadpool`` from async handlers so they never block the loop.

    ``@lru_cache`` makes this a singleton for connection reuse; a consequence is
    that credential/URL env changes are only picked up on restart (12-factor:
    redeploy to rotate the service key). Tests that need isolation can
    ``get_service_client.cache_clear()``.
    """
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in the backend environment."
        )
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
