# Session handover — prompt engine + per-environment tool routing (2026-06-23)

Read this to continue with zero context loss. Your auto-memory (`MEMORY.md` index +
`project_prompt_engine_optimization.md`, `project_outbound_transfers_versioning.md`,
`project_prompt_engine_deployed.md`) loads automatically — this doc is the narrative tying it together.

The two threads to continue: **(1) keep improving the prompts**, **(2) finish tool customization per environment.**

---

## 0. CURRENT STATE (where things stand right now)

- Branch **`feature/prompt-engine-optimization`** is MERGED + DEPLOYED. Both repos sit at commit **`bc01f94`**:
  - PROD repo `Kiki-Chat/kiki2.0CRM` (remote `company`) — auto-deploys → backend **7bca**.
  - UAT repo `imamber20/kikijarvis-crm` (remote `origin`) — backend **3f88a**.
- **Both backends verified live:** `…/api/elevenlabs/tools/ping` returns `"backend_environment":"uat"` on 3f88a and `"production"` on 7bca.
- **988 backend tests green** on the merged code.
- **Env-var routing PoC is set up in ElevenLabs:** variable `api_host` (`production`=`backend-production-7bca.up.railway.app`, `uat`=`backend-production-3f88a.up.railway.app`); shared tool `hk_ping` URL `https://{{system__env_api_host}}/api/elevenlabs/tools/ping` attached to both agents.
- **Test agents:** `agent_5001ksahz3w7fhx90j71xr800py4` = UAT, `agent_4901ktny383nerqt1c6qjyxadne2` = prod.

**THE ONE UNVERIFIED STEP:** the live phone test — call agent_5001 (+4925197593899) and agent_4901, say **„Bitte machen Sie einen Backend-Test."**; each should say its own backend (uat-Backend …3f88a… vs production-Backend …7bca…). That proves the shared-tool env routing end-to-end. Use a REAL call (the dashboard "Test" widget may not fire the conversation-init webhook → would default to `production`). Pre-check: agent_5001's conversation-init webhook → `…3f88a…/api/elevenlabs/conversation-init`, enabled.

⚠️ Production goes live to real customers in ~30–40h (new accounts). Prod isn't serving customers yet.

---

## 1. THREAD A — Per-environment tool customization (the env-var routing)

**The model (ElevenLabs Environment Variables — verified against docs):** ONE shared tool serves every agent across environments. Its URL host is a placeholder `{{system__env_api_host}}`; ElevenLabs resolves it per-conversation from the `api_host` variable's value for that conversation's environment. The environment is chosen **per call** by the **conversation-init webhook returning an `environment` field** (NOT a per-agent tag — there is no env tag on an agent). Each backend stamps its own env via the `EL_ENVIRONMENT` Railway var (`uat` on 3f88a, `production` on 7bca; default in code = `uat`). `https://` must be hardcoded in the tool URL; custom `{{var}}` does NOT work in a URL host — only `{{system__env_*}}`.

**What's DONE:** the mechanism (code: `conversation_init.py` returns `environment`; new `EL_ENVIRONMENT` setting; `ping` tool at `/api/elevenlabs/tools/ping`); the `api_host` variable + `hk_ping` tool in EL; both backends deployed + verified.

**NEXT (this is "tools customization according to environment"):**
1. **Confirm the live call test** (above) works.
2. **Convert the OTHER hk_ tools' URLs to `{{system__env_api_host}}`.** Right now ONLY `hk_ping` uses the env-var host; the real tools (`hk_identifyCustomer`, `hk_bookAppointment`, …) still have **hardcoded** backend URLs. Edit each shared tool's URL in the EL workspace from `https://backend-production-XXXX…/api/elevenlabs/tools/<endpoint>` to `https://{{system__env_api_host}}/api/elevenlabs/tools/<endpoint>`. Then ONE shared tool set serves UAT + prod (no `HK_Prod_*` duplicates). Endpoints unchanged. Test one tool first (the Beeceptor/ping method proved the concept).
3. **`hk_sendKVA`** (new tool, backend at `/api/elevenlabs/tools/send-cost-estimate`, L3-gated, currently INERT): create the EL tool (env-var URL) + add `"hk_sendKVA"` to `HK_TOOL_NAMES` in `agent_config.py` so provisioning attaches it.
4. **Fix UAT auto-deploy:** 3f88a does NOT auto-deploy from `origin/main`. Either wire its Railway service (proj `kikijarvis-backend`, service `backend` id `f6ec2789`) to the repo, or keep deploying via the railway MCP `deploy` tool (tarball of `backend/`). Prod (7bca) auto-deploys fine from `company`.
5. **Fix the mislabeled constant:** `_PROD_BACKEND_URL` (`agent_config.py:~121`) = `…3f88a…` is labeled prod but 3f88a is UAT. Used only by the health-check `webhook_url_is_prod`. Make it env-driven or correct it.

**Deploy commands:**
- UAT (manual, railway MCP, Amber's account): `deploy(project_id=97ee09d0-0123-4a8f-bd75-873ce08fa942, service_id=f6ec2789-cebb-432c-8fa8-2adefd0000aa, environment_id=227514ef-07a7-476d-9e88-6cd88f815b35, path=<worktree>/backend)`.
- PROD: merge to `company/main` → auto-deploys. (Railway MCP is Amber's account — can NOT see the company/prod project.)
- Rollback: prod `git push company dd8bf6b:main --force`; UAT origin `git push origin fa7a2b3:main --force` (but UAT now runs bc01f94 via tarball).

---

## 2. THREAD B — Prompt improvement

**Verified core fact:** moving prose from the system prompt into a tool description does NOT cut per-turn tokens (ElevenLabs serializes tool schemas every turn) — only **dedupe / delete / conditional-render** do. Verbose tool descriptions help **selection reliability**, not size.

**What's DONE on the branch (all tested, deployed):**
- Universal **trade profiles** (`backend/app/services/trade_profiles.py`): the agent fits ANY craft (plumber/electrician/roofer/car-mechanic/locksmith/IT/cleaning/… + generic fallback), resolved from the org's `trade`. Schritt-1 diagnostics + emergency-keyword fallback render per-genre. Onboarding captures `trade`+`address` (`ProvisionRequest`).
- **Inbound dedup** (removed double-rendered KZ_EMERGENCY + BUSINESS_HOURS).
- **Region engine** (`_apply_feature_regions` + `<!-- FEAT:name -->` markers): a feature OFF removes its whole region; **byte-identical when ON** (regression-tested). First applied to **Notdienst** (emergency).
- **Outbound:** prose tool-list → pointer + mailbox compress; additive **emergency escalation**; **autonomy L1 = don't book** on auto-swept booking occasions.
- **hk_sendKVA** backend (L3-gated; see Thread A #3).

**NEXT (prompt improvements still to do — specs in `DEFERRED_SPECS.md`):**
- ⚠️ **Force-Resync each agent** (Kiki-Zentrale) to actually PUSH the new prompts (trade/region/dedup) — the deploy did NOT re-render existing agents' stored prompts; the new behavior is opt-in per agent until you resync. Reversible (548 snapshots / 123 rollbacks proven on test org; undo store = migration 0015, NOT 0075).
- **Extend the region engine** to booking + the within-hours emergency sentence (needs a small reword first so the woven region is cleanly separable — spec in DEFERRED_SPECS.md). The pattern + the byte-identical-ON regression test (`tests/test_dynamic_prompt.py::test_notdienst_region_gated_in_real_template`) are the template.
- **F: tool-cards → verbose EL tool descriptions** — paste-ready German text for `hk_identifyCustomer` re-call protocol + `hk_draftCostEstimate` fuzzy-match is in DEFERRED_SPECS.md. Needs live EL write + an A/B eval; delete the prompt cards only AFTER.
- **B2 inbound conditional-render** beyond Notdienst — most "disabled" branches are *active* instructions (price-off = "don't quote"), so only the truly-dead regions qualify; needs the region engine + transcript A/B.
- **B4 cross-section dedup** (closing logic ×3, etc.) — behaviour-sensitive, one lever at a time.
- Tools decision: **keep the 11 hk_ tools, merge none** (cancel+change merge would risk hard-cancelling a real appt). Optional new: `hk_searchCustomerProjects` was DECLINED (projects are internal/tradesman, not client-facing).

**Eye-test tool:** `python backend/scripts/preview_outbound.py` renders the outbound prompt across emergency/autonomy combos offline.

---

## 3. Key files / docs (all on the branch)
- `OVERNIGHT_IMPLEMENTATION.md` — the full implementation log (start here for the change list).
- `DEFERRED_SPECS.md` — ready-to-apply specs for everything not-yet-done (B2/B4/region-extension/F/sendKVA EL wiring).
- `TESTING_AND_PRODUCTION.md` — German call scripts for every inbound scenario + production checklist.
- `TRANSFER_VERIFICATION_TESTPLAN.md` — the `transfer_to_agent` handoff live test (still to run).
- `ENV_ROUTING_POC.md` — the env-var routing recipe + Beeceptor proof.
- `PROMPT_SIZE_STRATEGY_2026-06-04.md` — updated lever ranking.

## 4. How to verify / run
- **Tests:** `cp "/Users/iamber/Code Jamming/KikiJarvis/backend/.env" backend/.env` then `/Users/iamber/Code\ Jamming/KikiJarvis/backend/.venv/bin/python -m pytest backend/tests -m "not live" -q` → 988 pass. Remove the temp `.env` after.
- **Render a real org's prompt (branch code, read-only):** the test org is `kiki-test-007` (org_id `c4dbf596-86fd-4484-88d9-095b2c082afb`, agent_5001, trade "Heizung & Sanitär", emergency on, KVA L2). Supabase project `ifbluvdcbcesuhvkxsfn`.
- **transfer_to_agent** is a SELF-transfer → an outbound→inbound handoff loads the FULL inbound prompt (so inbound slimming is a 3-way multiplier).

## 5. Gotchas
- Both repos were DIVERGED (prod ahead of UAT); now synced at bc01f94. Future: keep them in sync.
- `company` remote URL has Amber's prod GitHub PAT embedded (don't expose `git remote -v`).
- Railway MCP auth = Amber's account → sees UAT proj only, not company/prod.
- Listing UAT Railway vars exposes all secrets (Stripe/OpenAI/Supabase/etc.) — consider rotating any seen in transcripts.
- German-only UI; prompts are German. relocation≠reduction. Backend has no hot-reload (restart uvicorn).
