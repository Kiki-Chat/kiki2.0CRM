"""Force re-sync the kiki-test-007 TEST agent (agent_5001) against PROD:
attach all 11 hk_ tools (incl. the new hk_draftCostEstimate) + re-render the
dynamic prompt + point the conversation-init webhook at the prod backend.

Run from backend/ dir:  ./.venv/bin/python ../scripts/force_sync_test_agent.py
(BACKEND_PUBLIC_URL is forced to prod here so B.4 sets the right webhook.)
"""
import os
# MUST be set before the settings/agent_config import so B.4 uses the prod URL.
os.environ["BACKEND_PUBLIC_URL"] = "https://backend-production-3f88a.up.railway.app"

import json  # noqa: E402

from app.db.supabase_client import get_service_client  # noqa: E402
from app.services.agent_config import configure_agent  # noqa: E402

OID = "c4dbf596-86fd-4484-88d9-095b2c082afb"   # kiki-test-007
AID = "agent_5001ksahz3w7fhx90j71xr800py4"      # the SAFE test agent (NOT prod agent_7201)

c = get_service_client()
name = c.table("organizations").select("name").eq("id", OID).execute().data[0]["name"]
# force=True equivalent: clear the provisioned stamp so the prompt re-renders.
c.table("organizations").update({"agent_provisioned_at": None}).eq("id", OID).execute()
res = configure_agent(org_id=OID, agent_id=AID, org_name=name)
print("tools_attached:", res.get("tools_attached"))
print("prompt_applied:", res.get("prompt_applied"),
      "| webhook_enabled:", res.get("webhook_enabled"),
      "| audio_ok:", res.get("audio_ok"))
print("full:", json.dumps(res, default=str)[:500])
