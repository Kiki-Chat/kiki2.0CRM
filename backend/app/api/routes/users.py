from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api/users", tags=["users"])


class MeUpdate(BaseModel):
    full_name: str | None = None
    language_preference: str | None = None  # 'de' | 'en'

    model_config = {"extra": "ignore"}


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


def _me(user_id: str) -> dict | None:
    client = get_service_client()
    rows = (
        client.table("users")
        .select("id, full_name, email, role, avatar_url, language_preference")
        .eq("id", user_id).limit(1).execute().data
    )
    return rows[0] if rows else None


@router.get("/me")
async def get_me(user: CurrentUser = Depends(get_current_user)) -> dict:
    row = await run_in_threadpool(_me, user.id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.patch("/me")
async def update_me(payload: MeUpdate, user: CurrentUser = Depends(get_current_user)) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    if "language_preference" in fields and fields["language_preference"] not in ("de", "en"):
        raise HTTPException(status_code=422, detail="Invalid language")

    def _update() -> dict | None:
        client = get_service_client()
        if fields:
            client.table("users").update(fields).eq("id", user.id).execute()
        return _me(user.id)

    row = await run_in_threadpool(_update)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.post("/me/change-password")
async def change_password(
    payload: ChangePassword, user: CurrentUser = Depends(get_current_user)
) -> dict:
    if not payload.new_password or len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Neues Passwort muss mindestens 8 Zeichen haben.")
    if not user.email:
        raise HTTPException(status_code=400, detail="Kein E-Mail-Konto hinterlegt.")

    def _do() -> str:
        from supabase import create_client

        # Verify the current password with a throwaway client (don't touch the cached one).
        verifier = create_client(settings.supabase_url, settings.supabase_service_role_key)
        try:
            verifier.auth.sign_in_with_password(
                {"email": user.email, "password": payload.current_password}
            )
        except Exception:
            return "wrong"
        # Set the new password via the admin API.
        get_service_client().auth.admin.update_user_by_id(user.id, {"password": payload.new_password})
        return "ok"

    res = await run_in_threadpool(_do)
    if res == "wrong":
        raise HTTPException(status_code=400, detail="Aktuelles Passwort ist falsch.")
    return {"success": True}
