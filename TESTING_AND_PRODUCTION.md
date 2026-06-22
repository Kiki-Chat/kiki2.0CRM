# Testing the branch + production (HK_Prod_*) setup

Test org: **Kiki Chat GmbH** (`kiki-test-007`), org_id `c4dbf596-86fd-4484-88d9-095b2c082afb`,
agent `agent_5001ksahz3w7fhx90j71xr800py4`, inbound number **+4925197593899**,
your mobile **+917879997839**, test inbox `dixitrahul825@gmail.com`.

---

## 1. Verified NOW — branch code run against the REAL test-org config (no deploy, no calls)

| Change | Result on the real org |
|---|---|
| **Dedup** (inbound) | Branch prompt **64,266 chars vs live 66,209 → −1,943**. Business-hours block: **1× (was 2×)**. Emergency keyword list: **1× (was 2×)**. |
| **Universal trade** | Real trade `Heizung & Sanitär` → SHK profile, heating diagnostics rendered. Switching trade → `Autowerkstatt` → **car diagnostics, no plumbing** (`Manometer` gone). |
| **Region engine** | Emergency ON → Notdienst procedure present. Emergency OFF → procedure **removed**, "kein Notdienst" fallback kept (**−2,641 chars**). |
| **Outbound emergency** | Emergency on → in-call escalation note injected. |
| **Outbound autonomy** | Org is L2 → no directive (books as reservation, correct). Set to L1 → "don't book" directive appears. |
| **hk_sendKVA gating** | Org is KVA **L2 → tool DECLINES** ("Team versendet"). At L3 → sends. |

Full rendered prompts saved (local, ephemeral): `/tmp/kikitest_demo/inbound_REAL_branch.txt`,
`…_carmechanic.txt`, `…_emergency_off.txt`. The live agent is confirmed running the OLD prompt
(hardcoded Heizung/Elektrik/Dach + duplicated hours/emergency, no hk_sendKVA).

**Conclusion:** every change behaves correctly on the real config. What remains is *live* validation,
which needs a deploy + a phone call (below).

---

## 2. To test LIVE — the procedure (needs YOU)

The branch is **not deployed**, so the live agent runs old code. To see the changes live:

1. **Deploy the branch to UAT Railway** (your approval — backend). 
2. **Push the new prompt to the agent:** in Kiki-Zentrale for kiki-test-007, hit **"Force Resync"**
   (or save any setting). This re-renders with the new code AND now also re-pushes the system tools
   (the force-resync fix). 
3. **Confirm the new prompt landed:** re-read the agent (EL dashboard, or the simplified MCP view) —
   the duplicated hours/emergency should be gone and the SHK examples should come from the trade profile.
4. **Call inbound** (+4925197593899) and run the scripts in §3.
5. **Trade test:** change the test org's trade to e.g. `Autowerkstatt` in Kiki-Zentrale → Force Resync →
   call again → the agent should ask **car** questions, not plumbing.
6. **hk_sendKVA + outbound transfer:** see §3.3 / §3.4 — these need the prod-tool step (§5) and/or an
   outbound trigger.

---

## 3. German call scripts (read these aloud; English in parentheses)

### 3.1 Inbound — core scenarios (call +4925197593899)
1. **Greeting / identification + SHK diagnostics**
   - You: **„Hallo, meine Heizung wird nicht mehr richtig warm."** (My heating won't get warm.)
   - Expect: it greets you by name (caller-ID), then asks a heating question, e.g. *„Kommt denn noch warmes Wasser?"* or *„Zeigt das Gerät eine Fehleranzeige?"* → proves the **SHK trade profile**.
2. **Appointment** (L2 = reservation wording)
   - You: **„Ich hätte gern einen Termin."** (I'd like an appointment.)
   - Then answer **„Vormittags."** (mornings) when asked.
   - Expect: it offers two slots and says *„Ich reserviere den Termin für Sie…"* (reserve, not "booked").
3. **Price** (price info is ON)
   - You: **„Was kostet eine Heizungswartung ungefähr?"** (Roughly what does a heating service cost?)
   - Expect: a Richtpreis from the price list, or an offer to prepare a Kostenvoranschlag.
4. **Status of an inquiry**
   - You: **„Können Sie mir den Status meiner letzten Anfrage sagen?"** (Status of my last request?)
5. **Speak to a person** (staff transfer — ⚠️ REAL transfer to +4925197590002)
   - You: **„Können Sie mich bitte mit einem Mitarbeiter verbinden?"**
6. **Close**
   - You: **„Nein danke, das war alles. Auf Wiederhören."** (No thanks, that's all.)
   - Expect: a closing line, then it hangs up.

### 3.2 Emergency + region-engine (⚠️ REAL Notdienst transfer to 015734432281)
- You: **„Bei mir riecht es stark nach Gas!"** (Strong gas smell — the `Gasgeruch` keyword.)
- Expect: it treats it as an emergency and offers to connect you to the Notdienst (transfer).
- **Region-engine test:** in Kiki-Zentrale turn **Notdienst OFF** → Force Resync → call → say the same →
  it should **NOT** offer a Notdienst transfer (that whole block is gone) and instead take an urgent note.

### 3.3 Trade-universality (the headline change)
- Change trade to **`Autowerkstatt`** in Kiki-Zentrale → Force Resync → call:
- You: **„Mein Auto springt nicht an."** (My car won't start.)
- Expect: **car** diagnostics (*„Leuchtet eine Warnleuchte?"*, *„Sind Sie liegengeblieben?"*) — never plumbing.
- (Set the trade back to `Heizung & Sanitär` + Resync afterwards.)

### 3.4 Outbound (the agent calls YOU at +917879997839)
Needs a trigger (an occasion record + the branch running). When it calls:
- It delivers an opener (e.g. an appointment reminder).
- **Confirm:** **„Ja, der Termin passt."** (Yes, the appointment is fine.)
- **Reschedule:** **„Können wir den Termin verschieben?"** (Can we move it?)
- **transfer_to_agent test (off-topic):** **„Eigentlich habe ich ein ganz anderes Problem — meine Heizung ist kaputt."**
  (Actually I have a totally different problem.) → it should hand off to the main inbound agent and continue
  with full tools. *(This is the handoff in `TRANSFER_VERIFICATION_TESTPLAN.md` — confirm the transcript
  attribution survives.)*

---

## 4. Undo / Rewind

- **Status: WORKING for the stored agent** — this org has **548 snapshots / 547 audits / 123 rollbacks**
  already executed (every `patch_agent_safely` write snapshots-before-write; rollback via `POST /rollback/{id}`).
- **Covers:** the inbound prompt, the system tools, voice/name/language, tool_ids — i.e. everything the
  **inbound** agent uses AND everything the **outbound→transfer_to_agent** handoff lands on.
- **Does NOT cover the per-call OUTBOUND scripts:** the outbound prompt is a per-call override that is never
  written to the stored agent, so it isn't snapshotted — it's versioned only as source code (git). So
  "undo an outbound script change" = git revert, not the rollback button. *(This is by design; flag if you
  want per-call overrides snapshotted too.)*
- **Test it:** change a setting in Kiki-Zentrale → confirm a new snapshot row → hit Undo/rollback → confirm
  the agent reverted (and the audit row marked `rolled_back`).

---

## 5. Production setup (HK_Prod_* tools, different backend server)

When you stand up production, the moving parts are:

1. **Tool webhook URLs** — each prod EL tool (`HK_Prod_identifyCustomer`, …) must POST to the **prod**
   backend: `https://<prod-backend>/api/elevenlabs/tools/<endpoint>`. The endpoint **paths are identical**;
   only the host changes. Endpoints: identify-customer, update-customer, create-inquiry,
   get-available-slots, book-appointment, cancel-appointment, change-appointment, search-inquiries,
   query-knowledge-base, transfer-call, draft-cost-estimate, **send-cost-estimate (new, hk_sendKVA)**.
2. **`HK_TOOL_NAMES`** ([agent_config.py](backend/app/services/agent_config.py)) is the list provisioning
   attaches. It is currently hardcoded to `hk_*`. With prod tools named `HK_Prod_*`, this list **won't match
   the prod workspace** and provisioning B.2 will fail to resolve them. **Recommended:** make the prefix
   **env-driven** (e.g. `HK_TOOL_PREFIX`, default `hk_`) so the same code serves UAT (`hk_`) and prod
   (`HK_Prod_`) with no fork. *(I can implement this on request.)*
3. **`hk_sendKVA` (new):** create `HK_Prod_sendKVA` in the prod workspace → webhook to prod
   `/api/elevenlabs/tools/send-cost-estimate` → add its name to `HK_TOOL_NAMES`. Only acts at **KVA L3**.
4. **System tools** (`transfer_to_number` / `transfer_to_agent` / `voicemail_detection`) are **built by code**
   and pushed by `sync_system_tools_for_org` — **not** named `hk_`, so no rename needed. They derive numbers
   from the prod org's config and target the prod agent's own id. (The provisioning + force-resync sync fix
   means a freshly-provisioned prod org gets them automatically.)
5. **Webhooks/env:** the conversation-init + post-call webhooks come from `backend_public_url`; set it to the
   prod URL in the prod env (also prod Supabase + prod EL API key). Re-provision / Force-Resync prod agents
   after deploy.

---

## 6. Human-intervention checklist (what only YOU can do)

- [ ] **Approve + run the UAT deploy** of `feature/prompt-engine-optimization` (backend).
- [ ] **Force Resync** kiki-test-007 after deploy (pushes the new prompt + system tools).
- [ ] **Call +4925197593899** and run §3.1–3.3 (you read the German lines; I can't speak on the call).
- [ ] Decide whether to fire a **real outbound call** to +917879997839 (§3.4) — needs an occasion record;
      tell me and I'll set up a single test send once the branch is deployed/runnable.
- [ ] **Create the prod `HK_Prod_*` tools** (incl. `HK_Prod_sendKVA`) pointing at the prod backend, and tell
      me the prefix so I can wire `HK_TOOL_NAMES` (env-driven) for prod.
- [ ] ⚠️ The emergency + staff-transfer scripts place **real transfers** — use a safe moment.
