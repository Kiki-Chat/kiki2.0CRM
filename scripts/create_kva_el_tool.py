"""One-off: create the hk_draftCostEstimate tool in the ElevenLabs workspace by
cloning an existing hk_ tool's auth/structure. Idempotent. Prints no secrets.

Run: set -a; . backend/.env; set +a; python scripts/create_kva_el_tool.py
"""
import copy
import json
import os
import sys

import httpx

EL = "https://api.elevenlabs.io"
PROD = "https://backend-production-3f88a.up.railway.app"
KEY = os.environ.get("ELEVENLABS_API_KEY", "")
if not KEY:
    print("ERROR: ELEVENLABS_API_KEY not in env")
    sys.exit(1)

H = {"xi-api-key": KEY}
tools = httpx.get(f"{EL}/v1/convai/tools", headers=H, timeout=30).json()
tools = tools.get("tools", tools) if isinstance(tools, dict) else tools
by_name = {(t.get("tool_config") or t).get("name"): t for t in tools}

if "hk_draftCostEstimate" in by_name:
    print("ALREADY_EXISTS id=", by_name["hk_draftCostEstimate"].get("id"))
    sys.exit(0)

tmpl = by_name.get("hk_createInquiry")
if not tmpl:
    print("ERROR: template tool hk_createInquiry not found")
    sys.exit(1)

cfg = copy.deepcopy(tmpl.get("tool_config") or tmpl)
cfg.pop("id", None)
desc = ("Erstellt einen Kostenvoranschlag (KVA) als ENTWURF aus dem Gespräch. "
        "Nur aufrufen, wenn der Anrufer einen Kostenvoranschlag wünscht ODER Preise "
        "besprochen wurden. Das Team prüft den Entwurf; ab Autonomie-Stufe 3 wird er "
        "direkt versendet. Wirkt nur, wenn die KVA-Automatisierung aktiv ist.")
cfg["name"] = "hk_draftCostEstimate"
cfg["description"] = desc
api = cfg["api_schema"]
api["url"] = f"{PROD}/api/elevenlabs/tools/draft-cost-estimate"
api["method"] = "POST"
if "description" in api:
    api["description"] = desc
# Keep the cloned request_headers (the X-API-Key auth) verbatim. Replace the body
# schema with the draft params (all optional — the service handles missing fields).
api["request_body_schema"] = {
    "type": "object",
    "description": "Kostenvoranschlag-Entwurf",
    "properties": {
        "customerId": {"type": "string", "description": "Kunden-ID aus hk_identifyCustomer, falls bekannt."},
        "inquiryId": {"type": "string", "description": "Zugehörige Anfrage-ID, falls bekannt."},
        "subject": {"type": "string", "description": "Kurzer Betreff, z. B. 'Heizungswartung'."},
        "notes": {"type": "string", "description": "Besprochener Leistungsumfang/Details für den KVA."},
    },
    "required": [],
}

r = httpx.post(f"{EL}/v1/convai/tools", headers={**H, "Content-Type": "application/json"},
               json={"tool_config": cfg}, timeout=30)
print("POST status", r.status_code)
try:
    body = r.json()
    print("created id=", body.get("id"), "name=", (body.get("tool_config") or body).get("name"))
except Exception:
    print("resp:", r.text[:400])
