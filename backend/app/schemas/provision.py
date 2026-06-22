from pydantic import BaseModel, EmailStr, Field


class ProvisionRequest(BaseModel):
    heykiki_org_id: str = Field(..., alias="heykikiOrgId")
    org_name: str = Field(..., alias="orgName")
    login_email: EmailStr = Field(..., alias="loginEmail")
    login_password: str = Field(..., alias="loginPassword", min_length=8)
    elevenlabs_agent_id: str = Field(..., alias="elevenlabsAgentId")
    admin_name: str | None = Field(default=None, alias="adminName")
    contact_email: EmailStr | None = Field(default=None, alias="contactEmail")

    # ── n8n BIND-ONLY seam (additive, opt-in) ─────────────────────────────────
    # When ``agent_externally_managed=True`` the ElevenLabs agent (prompt + tools
    # + webhook + number) is built EXTERNALLY by n8n; provision_org must BIND the
    # already-built agent (store ids, stamp provisioned, run a read-only
    # verify_agent_health) WITHOUT calling configure_agent — which would clobber
    # n8n's prompt/tools/webhook. Default False preserves the existing super-admin
    # / self-serve path (configure_agent is still called).
    #
    # ``phone_number`` (E.164) + ``elevenlabs_phone_number_id`` are the values n8n
    # already bound to the agent; the CRM persists them verbatim (the
    # phone_number_id is needed for outbound). They are optional so the legacy
    # path is untouched.
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    elevenlabs_phone_number_id: str | None = Field(
        default=None, alias="elevenlabsPhoneNumberId"
    )
    agent_externally_managed: bool = Field(
        default=False, alias="agentExternallyManaged"
    )

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
    # n8n BIND-ONLY seam: when ``agent_externally_managed=True`` provision_org
    # runs a read-only verify_agent_health(org_id, agent_id) instead of
    # configure_agent and surfaces the report here (the verify_agent_health
    # return dict: {ok, provisioned_at, checks:[{name, ok, detail}]}). None on
    # the default (configure_agent) path so existing response shapes are
    # unchanged.
    agent_health: dict | None = None
