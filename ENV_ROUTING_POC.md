# PoC: one shared tool → two backends (ElevenLabs Environment Variables)

Proves that a SINGLE shared tool routes to UAT vs prod by environment — using a harmless
`ping` tool that reports which backend answered. Test agent: `agent_5001…` (kiki-test-007).

URLs (per Amber, 2026-06-22):
- **production** = `backend-production-7bca.up.railway.app`
- **uat**        = `backend-production-3f88a.up.railway.app`
- ⚠️ Code note: the constant `_PROD_BACKEND_URL` (agent_config.py:121) is set to `3f88a`, which is
  actually **UAT** — mislabeled. Harmless for env-var routing (routing is env-driven), but the
  health-check's "webhook_url_is_prod" compares against it; fix when convenient.

## What the branch already added (code, tested — 988 pass)
- `GET/POST /api/elevenlabs/tools/ping` → returns `{backend_environment, backend_host, message}`.
  The German `message` ("Antwort vom <env>-Backend (<host>)") can be read aloud on a voice test.
- Conversation-init webhook now returns `"environment": settings.el_environment` → tells EL which
  environment the call runs in, so `{{system__env_api_host}}` resolves to THIS backend.
- New setting `EL_ENVIRONMENT` (default `uat`). Each deployment sets its own.

## Run the PoC

**1. Deploy this branch to the UAT backend (3f88a)** with env `EL_ENVIRONMENT=uat`. *(For the
full two-way test, also deploy to prod 7bca with `EL_ENVIRONMENT=production`.)* The `ping`
endpoint is harmless.

**2. ElevenLabs dashboard — one-time setup:**
- Environments: ensure `production` exists; **create `uat`**.
- Environment variable **`api_host`** (host only, no `https://`, no slash):
  - `production` = `backend-production-7bca.up.railway.app`
  - `uat` = `backend-production-3f88a.up.railway.app`
- Create a webhook tool, e.g. **`hk_ping`**:
  - URL: `https://{{system__env_api_host}}/api/elevenlabs/tools/ping`
  - Method: GET
  - Description (so the agent knows when to call it): *"Diagnose-Tool. Rufe es auf, wenn der
    Anrufer „Backend-Test" oder „Ping" sagt, und lies die zurückgegebene `message` vor."*
- Attach `hk_ping` to `agent_5001…`.

**3. Test — watch the SAME tool route to the right backend:**
- Call the test number **+4925197593899** and say: **„Bitte machen Sie einen Backend-Test."**
- The agent calls `hk_ping`. Its conversation-init webhook (on the UAT backend) returns
  `environment: uat` → `{{system__env_api_host}}` = `…3f88a…` → the agent says
  **„Antwort vom uat-Backend (…3f88a…)."** ✅ The shared tool resolved via the env var.

**4. Prove it ROUTES (the key) — flip one thing, hear it change:**
- Easiest: in EL, temporarily set `api_host` for the **uat** environment to `…7bca…` → call again →
  the agent now says **„…(7bca)…"**. Same tool, different backend, zero tool edits. Set it back.
- Real two-way: deploy to 7bca with `EL_ENVIRONMENT=production`, point a prod agent's init webhook
  at 7bca → its calls return `environment: production` → the SAME `hk_ping` resolves to 7bca.

## Answers to your two questions
- **One shared tool across all agents?** YES — `hk_ping` (and later all `hk_*`) is created once and
  attached to every agent; the environment routes it. No per-environment tool duplication.
- **One agent for both environments, or separate agents?** In production you'll have **separate
  AGENTS per environment** (each bound to its own phone number + backend) — that's normal and cheap —
  but they **share the one tool set**. Each backend talks to its **own Supabase** (UAT agent → UAT
  backend → UAT DB; prod agent → prod backend → prod DB), so your data stays separated. The shared
  tool just routes the HTTP call to the correct backend. For TESTING, the single `agent_5001` can
  exercise both environments (step 4).
