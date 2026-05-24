"""Server-side Supabase Realtime broadcast.

Sends a broadcast message via the Realtime REST endpoint so the Call Logs page
(subscribed to ``org:{org_id}:calls``) updates live when a new call lands.
Best-effort: a broadcast failure must never fail the webhook.
"""

import httpx

from app.core.config import settings


def broadcast_new_call(org_id: str, payload: dict) -> bool:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return False
    url = f"{settings.supabase_url}/realtime/v1/api/broadcast"
    key = settings.supabase_service_role_key
    body = {
        "messages": [
            {
                "topic": f"org:{org_id}:calls",
                "event": "new_call",
                "payload": payload,
            }
        ]
    }
    try:
        resp = httpx.post(
            url,
            json=body,
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=5,
        )
        return resp.status_code in (200, 202)
    except Exception:
        return False
