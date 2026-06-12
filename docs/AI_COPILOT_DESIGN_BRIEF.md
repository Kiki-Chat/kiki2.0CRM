# HeyKiki — AI Copilot ("Kiki Assistent") · Strategy & Design Brief

> **For the build + product team.** This is the strategy for a **centralized, OpenAI-powered copilot**
> that lets a CRM *user* (owner / admin / employee) operate the CRM by **typing today, voice later** —
> ask questions, get guidance, apply changes, and escalate anything out of reach to support.
> It is grounded in the current codebase (FastAPI backend + React/Vite frontend + Supabase) so the build
> reuses what exists instead of reinventing it.
> German-only UI · light **and** dark mode (CSS-var tokens) · brand = `green-primary`.
>
> **Locked decisions (from product, 2026-06-04):**
> 1. **Voice = text-first.** Ship the text/chat copilot first; OpenAI **Realtime** voice is **Phase 5**.
> 2. **Escalation = register + email out.** No in-platform ticket tables; the copilot **registers a complaint
>    and emails it to `info@kikichat.de`** (via the existing Brevo `send_email` chain, trigger-only).
> 3. **v1 capability = reads + confirmed writes.** v1 answers/reads freely **and** can create/update
>    (customer, inquiry, appointment, draft KVA/invoice) — every write behind a **mandatory UI confirm**.
>    ⇒ the confirmation + audit layer must exist **at launch**, not later.
> 4. **UI = a floating chat widget, NOT the search bar.** A pop-up chat launcher docked at the **bottom
>    corner** of the CRM (using the **Kiki avatar**) opens the chat panel. The ⌘K command palette /
>    "Kiki fragen" search bar is **left completely untouched**.
> 5. **Scope guardrail = CRM-only.** The copilot answers **only CRM questions/actions** and politely refuses
>    everything else — off-topic/personal requests, general-purpose LLM use, and any vulgar, dangerous, or
>    harmful content. It must not be usable as a free general AI, and refusals are logged. (See §7.)
> 6. **Model = small / fast** (a `4o-mini`-class tier, env-overridable) — lower cost + latency, ample for CRM.

---

## 1. Why this exists — and why it's not a cold start

The ask: *one* intelligent assistant that can **guide, explain, find, do, and escalate** across the whole CRM,
so a busy tradesperson doesn't have to learn 18 screens or remember where a setting lives.

The important context: **this is already half-sanctioned.**
- `OPENAI_API_KEY` is **already set in Railway prod, dormant** (`SESSION_HANDOVER.md:151` — "classifier deferred").
- There is a **standing directive** to build **one shared LLM service**, not scattered per-feature calls
  (`SESSION_HANDOVER.md:153` — *"build on a shared LLM classification service … do NOT build per-feature LLM calls"*).

What you're asking for **is** that shared service, scaled into a user-facing copilot. Building it also unblocks
two deferred features that were explicitly told to wait for it: **emergency-flag detection** and **employee
auto-assign matching**. So the foundation pays for itself three times over.

## 2. The two AIs — keep them straight

The codebase already has an AI, and it is **not** this one. Confusing them will cause bugs.

| | **Existing: Kiki voice agent** | **New: Kiki copilot (this brief)** |
|---|---|---|
| Who talks to it | the business's **end customers**, by phone | the business's **own users**, in the app |
| Engine | **ElevenLabs** (closed LLM) | **OpenAI** (function calling) |
| Purpose | answer/place calls, book, take inquiries | operate the CRM: ask, guide, do, escalate |
| Auth | org secret / `agent_id` (`resolve_tool_org`) | **logged-in user's JWT** → inherits org + role |
| Lives in | `services/elevenlabs_agent.py`, `routes/tools/*` | new `services/ai/` + `services/copilot/` |

We **reuse the patterns** of the voice stack (tool contract, org resolution, snapshot/audit/rollback), never its
purpose or its engine.

## 3. Architecture — four layers, built bottom-up

```
┌───────────────────────────────────────────────────────────────┐
│ FRONTEND — floating chat widget · bottom-corner pop-up         │
│ Kiki-avatar launcher · chat + streaming · action-confirm cards │
│ in-app navigation · German · light/dark · (NOT the ⌘K search)  │
│ mounted globally in AppLayout, on every authenticated page     │
└───────────────────────────────┬───────────────────────────────┘
                                 │ SSE stream (JWT-authed)
┌───────────────────────────────▼───────────────────────────────┐
│ COPILOT ORCHESTRATOR  (new: app/services/copilot/)             │
│ agentic loop: system prompt + tools → model → execute → loop   │
│ conversation state · per-action audit · confirmation gating    │
│ identity = the logged-in user (inherits org_id + role)         │
└───────────────────────────────┬───────────────────────────────┘
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                         ▼
┌───────────────┐   ┌────────────────────────┐   ┌──────────────────┐
│ TOOL REGISTRY │   │ CENTRAL AI SERVICE      │   │ ESCALATION       │
│ CRM ops as    │   │ (new: app/services/ai/) │   │ registers the    │
│ OpenAI fns;   │   │ OpenAI SDK · caching ·  │   │ complaint &      │
│ each tagged   │   │ usage + cost logging ·  │   │ emails it to     │
│ read/write +  │   │ model tiering. ALSO     │   │ info.kikichat@   │
│ role+confirm; │   │ hosts the deferred      │   │ gmail.com (via   │
│ REUSE the     │   │ classifiers (emergency, │   │ Brevo, trigger-  │
│ services/*.py │   │ auto-assign)            │   │ only)            │
└───────────────┘   └────────────────────────┘   └──────────────────┘
```

The **Central AI Service is the foundation** (the "shared LLM service"); the copilot is its first consumer,
the two classifiers are the next two.

## 4. Central AI Service — `app/services/ai/`

A single, thin module that every AI feature calls. Net-new.

- **OpenAI client wrapper** — one place that holds the key, picks the model, sets timeouts/retries, and
  supports **streaming** + **function/tool calling**. Model IDs are **pinned at build time, env-overridable** —
  and per the 2026-06-04 decision the copilot uses a **small / fast** model (a `4o-mini`-class tier), not a
  flagship: lower cost + latency, ample for CRM tasks. Classifiers use the same mini tier; Realtime is for the
  Phase-5 voice layer; Whisper only if a STT path is ever added.
- **Prompt caching** — cache the large, stable system-prompt + tool-schema prefix; only the conversation
  tail varies. (Material cost/latency win on a chatty copilot.)
- **Usage + cost logging** — every call writes a row to `ai_usage_log` (tokens in/out, model, feature,
  org, user, estimated cost) so usage ties into the existing **KI-Nutzung** dashboard + per-org caps.
- **Shared classifiers** — `classify_emergency(text)` and `suggest_employee(inquiry)` live here too,
  satisfying the "one shared service" directive and unblocking the deferred work.

## 5. Copilot orchestrator — `app/services/copilot/`

The agentic loop, exposed at a JWT-authed streaming endpoint (e.g. `POST /api/copilot/chat` → SSE).

1. Build the **system prompt** (German, role/org-aware: who the user is, what they can/can't do).
2. Offer the **tool schemas** the user's role is allowed (registry-filtered).
3. Model responds with text and/or **tool calls**.
4. **Read** tool calls execute immediately (org/role-scoped). **Write** tool calls are **not executed** —
   they're returned to the UI as a **proposed action** the user must confirm; on confirm, the UI calls a
   `POST /api/copilot/confirm` that runs the tool and feeds the result back into the loop.
5. Loop until the model produces a final answer; **stream** tokens throughout.
6. Persist the turn (messages + any actions) and **audit** every executed write.

**Identity:** the orchestrator runs entirely as the logged-in user. There is no separate copilot identity,
no privilege elevation — `org_id` and `role` come straight from the JWT via the same dependency the REST API uses.

## 6. Tool registry — the heart of "control anything"

Every tool is a small declaration that wraps an **existing service function** (never raw SQL, never a
re-implementation):

```
Tool = {
  name, description (de),              # what the model sees
  params: JSONSchema,                  # validated before execution
  required_role: employee|admin|super, # gate (same guards as REST)
  kind: read | write | sensitive | dangerous,
  confirm: bool,                       # write/sensitive ⇒ true
  run: (user, args) -> result          # calls services/*.py
}
```

**v1 tool set (reads + confirmed writes), mapped to what already exists:**

| Capability | Tools (examples) | Backs onto | Kind |
|---|---|---|---|
| **Find / answer** | `search_customers`, `get_customer`, `list_appointments`, `list_calls`, `get_call`, `list_cost_estimates`, `list_invoices`, `list_catalog` | `GET /api/customers`, `/appointments`, `/calls`, `/cost-estimates`, `/invoices`, `/catalog` | read |
| **"What needs me?"** | `list_pending_actions`, `dashboard_overview`, `dashboard_finanzen`, `dashboard_anrufe`, `ki_nutzung` | `GET /api/actions/pending`, `/api/dashboard/*` | read |
| **Guide / explain** | `explain_setting`, `how_do_i` | settings dictionary (content artifact) + optional RAG over `knowledge_resources` | read |
| **Navigate** | `navigate_to(route)` | frontend `useNavigate` | read |
| **Do (confirmed)** | `create_customer`, `update_customer`, `create_inquiry`, `set_inquiry_status`, `assign_inquiry`, `create_appointment` (pending), `create_cost_estimate` (draft), `create_invoice` (draft), `create_text_module`, `create_catalog_item` | `POST/PATCH /api/customers`, `/inquiries`, `/appointments`, `/cost-estimates`, `/invoices`, `/text-modules`, `/catalog` | write (confirm) |
| **Do (sensitive)** | `confirm_appointment`, `reschedule_appointment`, `send_cost_estimate`, `send_invoice` | `POST .../confirm`, `.../propose-alternative`, `.../send` | sensitive (confirm + side-effect warning: *fires a call / emails the customer*) |

**Phase 3 adds** the *settings copilot* tools (`apply_setting`, Kiki-Zentrale config) as **sensitive/dangerous**.
**Forbidden to the copilot entirely:** delete org, bulk-delete, raw queries, cross-org access — these stay manual.

A **settings dictionary** (plain-language meaning + side-effects + required role for each setting field) is a
content artifact we author; it powers `explain_setting` and guards `apply_setting`.

## 7. Security, safety & scope guardrails (the non-negotiable part)

The backend uses the Supabase **service-role key, which bypasses RLS** (`supabase_client.py:8`); org isolation is
**application-level only** (`.eq("org_id", …)` everywhere). A copilot is a powerful new caller into that, so:

- **Tools run only through existing guarded service paths** — same `require_org` / `require_org_admin` /
  `require_super_admin` checks as the REST API. No new query surface, no SQL from the model.
- **Confirmation tiers:** read = free · write = UI confirm · sensitive = confirm + explicit side-effect warning ·
  dangerous = admin + double-confirm · forbidden = blocked.
- **No auto-chaining of writes.** A write always needs a fresh human confirm; the model can *propose* a sequence,
  but each executes only on its own confirmation.
- **Prompt-injection containment.** Call transcripts, customer notes, knowledge docs are **untrusted data**.
  Tool *outputs* can never trigger a write on their own; they're just context. The system prompt states this.
- **Full audit.** Every executed write logs to `copilot_action_audit` (user, org, tool, args, result) — mirrors
  the existing `agent_writes_audit` discipline. Settings changes additionally snapshot for rollback.
- **Feature flag.** The whole copilot ships behind an off-by-default flag (like Redis/observability did), so it
  can be deployed inert and switched on under supervision.

**Topical confinement & abuse refusal — Kiki only does CRM.** A real risk is people trying to use the assistant
as a free general-purpose AI, or pushing it toward inappropriate content. Three layers keep it on-task:

- **System-prompt confinement.** Kiki is instructed it is a **CRM assistant only**. It politely declines (in
  German) anything off-topic — personal favours, general knowledge, homework, coding help, "write me a poem" —
  and **redirects** to what it *can* do (*"Dabei kann ich leider nicht helfen — ich bin nur für das CRM da. Ich
  kann z. B. …"*).
- **Abuse / safety refusal.** It refuses vulgar, sexual, hateful, or dangerous/harmful requests outright and
  never "plays along" with jailbreak attempts ("ignore your instructions", scope-escaping role-play, etc.). An
  optional cheap **moderation pass** (via the central AI service) can pre-screen inputs and flag abuse first.
- **The tool boundary is the hard stop.** Even a *successful* jailbreak can't make Kiki *do* anything outside the
  CRM: it can only ever call the **curated, role-scoped tool registry**, and there is no tool for a non-CRM
  action. The worst case of an off-topic prompt is a refusal or some wasted tokens — never a harmful action.
- **Logged.** Off-topic / abuse attempts are recorded (audit) so misuse patterns stay visible.

## 8. Data model additions (all **additive** — spec only, not yet applied)

Per the additive-migrations-pre-authorized rule these are safe to add, but they're **specified here, not run**,
until the build phase:

- `copilot_conversations` — `id, org_id, user_id, title, created_at, updated_at`
- `copilot_messages` — `id, conversation_id, role (user|assistant|tool), content, tool_calls jsonb, tool_call_id, created_at`
- `copilot_action_audit` — `id, org_id, user_id, conversation_id, tool_name, args jsonb, result_status, confirmed bool, created_at`
- `copilot_escalations` — `id, org_id, user_id, conversation_id, summary, body, emailed_to, email_status, created_at` — **"registers"** each complaint before it's emailed out (§9)
- `ai_usage_log` — `id, org_id, user_id, feature, model, prompt_tokens, completion_tokens, cost_estimate, created_at`

(No `support_tickets` table — escalation is an external email, see §9.)

## 9. Escalation — register the complaint + email it out

When the copilot **can't** help (no tool fits, a tool fails, or the user asks for a human / wants to report a
problem), it **registers the complaint and emails it out** — no in-platform ticketing:

- **Target (locked): `info@kikichat.de`.** Every escalation / complaint is sent there.
- **Register:** the complaint is logged to `copilot_escalations` (§8) — who, which org, the conversation snippet,
  the unmet request — so nothing is lost even if mail fails, and there's a record to follow up on.
- **Send:** the email is fired through the **existing Brevo `send_email` chain**. ⚠️ Per the standing rule the
  email-send chain is **Amber-owned** — we **only trigger** it, never modify it. The mail is a plain internal
  support notification (subject = the complaint summary; body = user / org + conversation snippet + the request).
- **Phase-4 check:** make sure this internal mail is **not** caught by the `OUTBOUND_TEST_SCOPE_ONLY` scope guard
  (that guard governs *customer-facing* outbound; an internal support mail to `info@kikichat.de` must send
  regardless of its state).

## 10. Frontend plan — a floating chat widget (NOT the search bar)

- **Separate, self-contained widget.** A **floating launcher** docked at the **bottom corner** of the CRM —
  a round button showing the **Kiki avatar** (`frontend/src/assets/kiki-avatar.png`). Clicking it opens a
  **chat pop-up** anchored above the launcher. The ⌘K command palette / "Kiki fragen" search bar is **left
  completely untouched** — this is a brand-new affordance, not a reuse of the palette.
- **Mounted globally** in `components/layout/AppLayout.tsx` so it's on every authenticated page, collapsed by
  default, with open/closed state persisted per user (localStorage).
- **Chat UI:** a Kiki-branded panel — avatar + greeting header, message thread (user / **Kiki** / tool),
  **streaming** replies via `fetch().getReader()` over SSE, plus loading / empty / error states. German-only;
  light/dark via the CSS-var tokens.
- **Action-confirm cards:** a proposed write renders inline as a card ("Kiki möchte … anlegen") showing the exact
  values + **Bestätigen / Abbrechen**; confirm → `POST /api/copilot/confirm`.
- **Complaint / escalation:** a "Problem melden" affordance (and the model's own out-of-scope path) collect the
  complaint and **register + email it to `info@kikichat.de`** (see §9).
- **Navigation:** `navigate_to` results call `useNavigate()` so Kiki can take the user to a screen.
- **Wiring is ready:** `useMe()` (role/org) + `apiFetch()` (token-attached). No new deps for text/SSE.

## 11. Phased rollout (safety-first, matches house conventions)

| Phase | Deliverable | Risk |
|---|---|---|
| **0 — Foundation** | Central AI service (OpenAI client, caching, `ai_usage_log`) + copilot backend skeleton (JWT endpoint, conversation state, audit, confirmation plumbing). **Flag OFF.** | none (inert) |
| **1 — Read & guide** | Read tools + navigation + `explain_setting`; the floating chat widget; streaming. The "ask anything / guide me" MVP. | low |
| **2 — Confirmed writes** | The write tools from §6 behind UI confirm + audit. *(In scope for v1 per the locked decision — 1+2 ship together as the first usable release.)* | medium |
| **3 — Settings copilot** | `apply_setting` + Kiki-Zentrale config, with guardrails, side-effect warnings, snapshot rollback. Admin-gated. | high |
| **4 — Escalation** | Register complaints (`copilot_escalations`) + email them to `info@kikichat.de`. | low |
| **5 — Voice** | OpenAI Realtime layered over the proven text copilot (mic toggle in the same widget). | medium |
| **Cross-cutting** | Usage caps tied to `ai_minutes_quota`/KI-Nutzung; cost ceilings; observability. | — |

**"v1" = Phases 0+1+2** (reads + confirmed writes), shipped together.

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Cross-org leak via service-role key | tools run only through guarded service functions; no model-authored SQL |
| Destructive action by the model | confirmation tiers + forbidden list + no auto-chaining |
| Prompt injection from call/customer data | untrusted-data boundary; tool outputs never trigger writes |
| Runaway cost / latency | prompt caching, model tiering, per-org usage caps, streaming |
| Operational footguns | German-only UX; **restart uvicorn after backend edits** (no hot-reload); **local = UAT, no Railway deploy without explicit OK**; migrations additive |

## 13. Open inputs

1. ~~**Escalation target**~~ — ✅ **resolved: `info@kikichat.de`** (§9).
2. ~~**Model + budget**~~ — ✅ **resolved: a small / fast OpenAI model** (`4o-mini`-class, env-overridable) for
   the copilot **and** the classifiers — lower cost + latency, fine for CRM. Per-org usage cap via `ai_usage_log`.
3. **Super-admin copilot?** — v1 assumes **org users** (owner/admin/employee). A cross-org copilot for the
   `/admin` super-admin surface is a deliberate later extension, not in v1.

---

## Appendix — reuse map & new modules (for engineers)

**Reuse (existing → role in the copilot):**
- `app/api/deps.py` (`get_current_user`, `require_org*`) → the copilot's identity + per-tool guards.
- `app/services/*.py` (customers, inquiries, appointments, cost_estimates, invoices, catalog, settings,
  kiki_zentrale) → the bodies of the tool `run()` functions.
- `app/services/elevenlabs_agent.py` snapshot/audit/rollback pattern → `copilot_action_audit` + settings rollback.
- `app/services/email_send.py` (`send_email`) → **triggered only** to send the escalation mail (Amber-owned chain).
- `app/services/knowledge.py` + `knowledge_resources` → optional RAG for `explain` / `how_do_i`.
- `frontend/src/components/layout/CommandPalette.tsx` → **left untouched**; the copilot is a **separate floating
  widget** mounted in `AppLayout.tsx` (the ⌘K search stays exactly as-is).
- `frontend/src/assets/kiki-avatar.png` → the launcher bubble + the assistant's chat avatar.
- `frontend/src/lib/useMe.ts` + `lib/api.ts` (`apiFetch`) → frontend auth/data wiring.

**New (net-new modules):**
- Backend: `app/services/ai/` (OpenAI wrapper + classifiers), `app/services/copilot/` (orchestrator + tool
  registry), `app/api/routes/copilot.py` (`/chat` SSE + `/confirm`), migrations for the five tables in §8.
- Frontend: a `CopilotWidget` (floating launcher + chat pop-up, Kiki avatar) mounted in `AppLayout`, plus a small
  SSE client in `lib/`. (**No change to `CommandPalette`.**)

**Dependencies to add:** `openai` (backend `requirements.txt`). No new frontend deps required for text/SSE
(use native `fetch` streaming); voice (Phase 5) adds an audio/WebRTC client.
