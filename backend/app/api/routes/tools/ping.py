"""Diagnostic 'ping' tool — proves which BACKEND answered a shared tool call.

Purpose: a harmless, auth-free, DB-free endpoint to validate the ElevenLabs
Environment Variables routing. Create ONE shared EL tool whose URL host is the
env var, e.g. `https://{{system__env_api_host}}/api/elevenlabs/tools/ping`, attach
it to an agent, and call it. The JSON (and the German `message`, which the agent can
read aloud) tells you EXACTLY which backend handled the call — so you can watch the
same tool resolve to UAT vs production by environment.

GET (browser-friendly) and POST (how EL calls tools) both work.
"""
from fastapi import APIRouter, Request

from app.core.config import settings

router = APIRouter(prefix="/api/elevenlabs/tools", tags=["elevenlabs-tools"])


def _identity(request: Request) -> dict:
    host = request.headers.get("host") or request.url.hostname or "unknown"
    env = settings.el_environment
    return {
        "ok": True,
        "backend_environment": env,
        "backend_host": host,
        "backend_public_url": settings.backend_public_url,
        # German so the agent can speak it during a voice test.
        "message": f"Antwort vom {env}-Backend ({host}).",
    }


@router.get("/ping")
async def ping_get(request: Request) -> dict:
    return _identity(request)


@router.post("/ping")
async def ping_post(request: Request) -> dict:
    return _identity(request)
