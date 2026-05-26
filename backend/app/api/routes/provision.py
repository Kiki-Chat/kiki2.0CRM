from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.deps import verify_master_secret
from app.schemas.provision import ProvisionRequest, ProvisionResponse
from app.services.history_import import import_agent_history
from app.services.provisioning import provision_org

router = APIRouter(prefix="/api/heykiki", tags=["provisioning"])


@router.post(
    "/provision",
    response_model=ProvisionResponse,
    dependencies=[Depends(verify_master_secret)],
)
async def provision(
    payload: ProvisionRequest,
    background_tasks: BackgroundTasks,
) -> ProvisionResponse:
    response = provision_org(payload)
    # P0.9 — Backfill the agent's historical EL conversations into the new
    # org's calls table so the customer's Call Logs aren't empty on day 1.
    # Runs async after the HTTP response returns; idempotent so a manual
    # re-trigger via /api/super-admin/orgs/{id}/import-history is safe.
    background_tasks.add_task(
        import_agent_history,
        org_id=response.org_id,
        agent_id=payload.elevenlabs_agent_id,
    )
    return response
