from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "org_id": user.org_id,
        "role": user.role,
        "full_name": user.full_name,
    }
