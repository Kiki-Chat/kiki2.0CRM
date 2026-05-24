from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import verify_post_call_secret
from app.services.post_call import process_post_call

router = APIRouter(prefix="/api/elevenlabs", tags=["elevenlabs"])


@router.post("/post-call", dependencies=[Depends(verify_post_call_secret)])
async def post_call(request: Request) -> list[dict]:
    # Body shape varies (ElevenLabs envelope, flat, or an N8N item array), so we
    # read the raw JSON and let the service normalise it.
    payload = await request.json()
    return await run_in_threadpool(process_post_call, payload)
