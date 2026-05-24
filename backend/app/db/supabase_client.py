from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


@lru_cache
def get_service_client() -> Client:
    """Service-role client. Bypasses RLS — backend-only, never expose to the browser."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in the backend environment."
        )
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
