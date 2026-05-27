from pydantic import BaseModel, EmailStr, Field


class ProvisionRequest(BaseModel):
    heykiki_org_id: str = Field(..., alias="heykikiOrgId")
    org_name: str = Field(..., alias="orgName")
    login_email: EmailStr = Field(..., alias="loginEmail")
    login_password: str = Field(..., alias="loginPassword", min_length=8)
    elevenlabs_agent_id: str = Field(..., alias="elevenlabsAgentId")
    admin_name: str | None = Field(default=None, alias="adminName")
    contact_email: EmailStr | None = Field(default=None, alias="contactEmail")

    model_config = {"populate_by_name": True}


class ProvisionResponse(BaseModel):
    org_id: str
    user_id: str
    heykiki_org_id: str
    # Step B.6 (2026-05-27) — provision_org no longer generates an org_secret
    # (per-org secret was misleading; identification is now agent_id + caller
    # phone_number via _lookup_org_id). Field kept Optional so existing
    # callers / response shapes don't break, and so the legacy
    # /api/heykiki/provision route still type-checks.
    org_secret: str | None = None
