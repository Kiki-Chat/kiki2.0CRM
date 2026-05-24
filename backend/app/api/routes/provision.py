from fastapi import APIRouter, Depends

from app.api.deps import verify_master_secret
from app.schemas.provision import ProvisionRequest, ProvisionResponse
from app.services.provisioning import provision_org

router = APIRouter(prefix="/api/heykiki", tags=["provisioning"])


@router.post(
    "/provision",
    response_model=ProvisionResponse,
    dependencies=[Depends(verify_master_secret)],
)
async def provision(payload: ProvisionRequest) -> ProvisionResponse:
    return provision_org(payload)
