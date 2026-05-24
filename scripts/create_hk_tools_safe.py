#!/usr/bin/env python3
"""Safe HeyKiki tool provisioner for ElevenLabs.

Improvements over create_hk_tools_final.sh:
  1. API key from $ELEVENLABS_API_KEY (never hardcoded/committed).
  2. Idempotent: reuses existing workspace tools by name (no duplicates).
  3. Safe agent assignment: fetches the agent, MERGES new tool ids into the
     existing prompt.tool_ids, and PATCHes back the full prompt object — so the
     system prompt, first_message, and existing tools are never overwritten
     (handover known-bug #1).

Usage:
  ELEVENLABS_API_KEY=sk_... ./create_hk_tools_safe.py <BASE_URL>
"""

import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.elevenlabs.io/v1/convai"
AGENT_ID = "agent_5001ksahz3w7fhx90j71xr800py4"


def req(method: str, url: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("xi-api-key", key)
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {method} {url}\n{e.read().decode()}")


SYS = [
    {"name": "_toolName", "type": "string", "description": "Tool id", "constant_value": None},
    {"name": "_callerNumber", "type": "string", "description": "Caller phone", "dynamic_variable": "system__caller_id"},
    {"name": "_conversationId", "type": "string", "description": "Conversation ID", "dynamic_variable": "system__conversation_id"},
    {"name": "_agentId", "type": "string", "description": "Agent ID", "dynamic_variable": "system__agent_id"},
    {"name": "_callSid", "type": "string", "description": "Call SID", "dynamic_variable": "system__call_sid"},
]


def sysfields(tool_name: str) -> list[dict]:
    fields = [dict(f) for f in SYS]
    fields[0]["constant_value"] = tool_name
    return fields


# (toolName, endpoint, description, extra_props, timeout)
TOOLS = [
    ("identifyCustomer", "/identify-customer",
     "MUST be the very first action in every call. Identify caller by Caller-ID or identifiers.",
     [{"name": "phoneNumber", "type": "string", "description": "Caller own number after FORWARDED_CALL"},
      {"name": "customerNumber", "type": "string", "description": "Stated customer number"},
      {"name": "address", "type": "string", "description": "Address for identification"},
      {"name": "lastName", "type": "string", "description": "Last name to confirm"}], 10),
    ("updateCustomerData", "/update-customer",
     "Update master data for an existing customer.",
     [{"name": "customerId", "type": "string", "description": "Customer ID", "required": True},
      {"name": "address", "type": "string", "description": "New address"},
      {"name": "email", "type": "string", "description": "New email"},
      {"name": "phone", "type": "string", "description": "New phone"},
      {"name": "name", "type": "string", "description": "Corrected name"}], 10),
    ("createInquiry", "/create-inquiry",
     "Record a caller message or inquiry. Collect all info first.",
     [{"name": "inquiryTitle", "type": "string", "description": "Short title 3-6 words"},
      {"name": "message", "type": "string", "description": "Concern summary", "required": True},
      {"name": "name", "type": "string", "description": "Caller name", "required": True},
      {"name": "phone", "type": "string", "description": "Callback phone"},
      {"name": "address", "type": "string", "description": "Address with zip"},
      {"name": "email", "type": "string", "description": "Email lowercase"},
      {"name": "urgent", "type": "boolean", "description": "Is urgent"},
      {"name": "callbackRequested", "type": "boolean", "description": "Callback requested"}], 15),
    ("getAvailableAppointments", "/get-available-slots",
     "Search available slots. Always call before bookAppointment.",
     [{"name": "days", "type": "number", "description": "Days ahead default 7 max 14"},
      {"name": "durationMinutes", "type": "number", "description": "Duration default 60"},
      {"name": "preferredDate", "type": "string", "description": "Preferred date verbatim"},
      {"name": "preferredTime", "type": "string", "description": "Preferred time of day"}], 15),
    ("bookAppointment", "/create-appointment",
     "Book a slot. Only after getAvailableAppointments and caller confirmation.",
     [{"name": "date", "type": "string", "description": "Date", "required": True},
      {"name": "name", "type": "string", "description": "Caller name", "required": True},
      {"name": "time", "type": "string", "description": "Time"},
      {"name": "phone", "type": "string", "description": "Phone"},
      {"name": "address", "type": "string", "description": "Job site address"},
      {"name": "description", "type": "string", "description": "Concern derived from context"},
      {"name": "inquiryTitle", "type": "string", "description": "Short title"},
      {"name": "email", "type": "string", "description": "Email lowercase"},
      {"name": "category", "type": "string", "description": "Category if configured"}], 15),
    ("cancelAppointment", "/cancel-appointment",
     "Cancel an existing appointment. Phone auto-detected from Caller-ID. If the "
     "caller is not identified by phone, provide name AND the appointment date to "
     "confirm the correct booking.",
     [{"name": "phoneNumber", "type": "string", "description": "Different number than Caller-ID"},
      {"name": "name", "type": "string", "description": "Caller name (fallback identification when no phone match)"},
      {"name": "date", "type": "string", "description": "Appointment date to confirm a name-based match, e.g. 27.05. or next Monday"},
      {"name": "reason", "type": "string", "description": "Reason"}], 10),
    ("changeAppointment", "/change-appointment",
     "Reschedule an appointment to a new date/time.",
     [{"name": "newDate", "type": "string", "description": "New date", "required": True},
      {"name": "phoneNumber", "type": "string", "description": "Phone for identification"},
      {"name": "name", "type": "string", "description": "Name fallback"},
      {"name": "newTime", "type": "string", "description": "New time"},
      {"name": "reason", "type": "string", "description": "Reason"}], 10),
    ("searchCustomerInquiries", "/search-inquiries",
     "Search customer inquiries and return status.",
     [{"name": "customerId", "type": "string", "description": "Customer ID"},
      {"name": "status", "type": "string", "description": "Filter status"},
      {"name": "dateFrom", "type": "string", "description": "From YYYY-MM-DD"},
      {"name": "dateTo", "type": "string", "description": "To YYYY-MM-DD"},
      {"name": "sortOrder", "type": "string", "description": "newest or oldest"}], 10),
    ("queryKnowledgeBase", "/query-knowledge-base",
     "Search the knowledge base for an answer.",
     [{"name": "question", "type": "string", "description": "Question", "required": True}], 20),
    ("transferCall", "/transfer-call",
     "Transfer emergencies (emergency true) or to staff (emergency false).",
     [{"name": "emergency", "type": "boolean", "description": "true emergency false staff", "required": True},
      {"name": "reason", "type": "string", "description": "Reason"}], 10),
]


def build_tool(name, path, desc, extra, timeout, base_url):
    return {
        "tool_config": {
            "type": "webhook",
            "name": f"hk_{name}",
            "description": desc,
            "response_timeout_secs": timeout,
            "api_schema": {
                "url": f"{base_url}/api/elevenlabs/tools{path}",
                "method": "POST",
                "request_headers": [],
                "path_params_schema": [],
                "query_params_schema": [],
                "request_body_schema": {
                    "type": "object",
                    "description": name,
                    "properties": sysfields(name) + extra,
                },
            },
        }
    }


def main():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("Set ELEVENLABS_API_KEY in the environment")
    if len(sys.argv) < 2:
        sys.exit(f"Usage: {sys.argv[0]} <BASE_URL>")
    base_url = sys.argv[1].rstrip("/")

    print(f"Target agent : {AGENT_ID}")
    print(f"Backend URL  : {base_url}")
    print("=" * 48)

    existing = req("GET", f"{API_BASE}/tools", key)
    existing_list = existing.get("tools", existing) if isinstance(existing, dict) else existing
    by_name = {}
    valid_ids = set()
    for t in existing_list or []:
        cfg = t.get("tool_config", t)
        if t.get("id"):
            valid_ids.add(t["id"])
        if cfg.get("name"):
            by_name[cfg["name"]] = t.get("id")

    tool_ids = []
    for name, path, desc, extra, timeout in TOOLS:
        full = f"hk_{name}"
        target_url = f"{base_url}/api/elevenlabs/tools{path}"
        if full in by_name:
            # Non-destructive in-place update: fetch the tool, change ONLY the
            # webhook URL (preserving the server's stored schema format), PATCH.
            tid = by_name[full]
            tool = req("GET", f"{API_BASE}/tools/{tid}", key)
            cfg = tool.get("tool_config", tool)
            cfg.setdefault("api_schema", {})["url"] = target_url
            req("PATCH", f"{API_BASE}/tools/{tid}", key, {"tool_config": cfg})
            print(f"  updated url for {full} -> {tid}")
        else:
            body = build_tool(name, path, desc, extra, timeout, base_url)
            resp = req("POST", f"{API_BASE}/tools", key, body)
            tid = resp.get("id")
            print(f"  created {full} -> {tid}")
        tool_ids.append(tid)

    print("=" * 48)
    print(f"Safe-merging {len(tool_ids)} tool(s) into agent {AGENT_ID}...")

    agent = req("GET", f"{API_BASE}/agents/{AGENT_ID}", key)
    prompt = (agent.get("conversation_config", {}).get("agent", {}).get("prompt", {})) or {}
    existing_ids = prompt.get("tool_ids") or []
    # ElevenLabs rejects a prompt that carries both `tools` and `tool_ids`.
    # The deprecated inline `tools` field must be removed when using tool_ids.
    inline_tools = prompt.pop("tools", None)
    if inline_tools:
        print(f"  WARNING: removed {len(inline_tools)} deprecated inline tool(s) "
              "from prompt to allow tool_ids assignment")
    # Safe merge: keep existing + new, but DROP dangling references to tools
    # that no longer exist in the workspace (else the PATCH 404s).
    valid_ids.update(tool_ids)
    merged = [i for i in dict.fromkeys([*existing_ids, *tool_ids]) if i in valid_ids]
    dropped = [i for i in existing_ids if i not in valid_ids]
    if dropped:
        print(f"  dropped {len(dropped)} dangling tool_id reference(s)")
    prompt["tool_ids"] = merged
    print(f"  existing tool_ids: {len(existing_ids)} -> merged: {len(merged)}")

    patched = req(
        "PATCH",
        f"{API_BASE}/agents/{AGENT_ID}",
        key,
        {"conversation_config": {"agent": {"prompt": prompt}}},
    )
    final_ids = (
        patched.get("conversation_config", {})
        .get("agent", {})
        .get("prompt", {})
        .get("tool_ids", [])
    )
    print(f"SUCCESS — agent now has {len(final_ids)} tool(s) assigned.")


if __name__ == "__main__":
    main()
