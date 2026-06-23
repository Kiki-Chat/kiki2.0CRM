# transfer_to_agent — live verification test plan (NOT run; outbound is LIVE)

`transfer_to_agent` is a **self-transfer**: the org's one agent transfers to its own
`agent_id` (`build_transfer_to_agent_tool`, agent_config.py:1619). On an outbound call the
new leg drops the per-call override and runs the agent's **stored inbound prompt**. Two
things are asserted only in a docstring and must be confirmed empirically before relying on
the handoff. **Requires one controlled live outbound call — I did not place it.**

## Setup
- Use a **test org** (kiki-test-007) and a **safe phone** you control as the callee.
- Confirm `OUTBOUND_TEST_SCOPE_ONLY` posture before dialing (outbound reaches real numbers
  when `=0`). Prefer a test number.
- Pick a booking-capable occasion (e.g. `appointment_reminder`) so a real outbound leg
  starts with the lean override prompt.

## Procedure
1. Trigger one outbound call to your test number.
2. When Kiki delivers the opener, raise an **off-topic** concern ("Eigentlich rufe ich
   wegen einer ganz anderen Sache an — meine Heizung ist kaputt und ich brauche einen neuen
   Termin"). This should satisfy the `transfer_to_agent` condition.
3. Observe the handoff and continue the conversation (ask Kiki to identify you / book).

## What to verify (the two unknowns)
1. **Override drops → inbound prompt active.** After the transfer, the agent should behave
   like the **inbound** agent (full identification + all tools), not keep the lean outbound
   script. Confirm in the EL conversation transcript that post-transfer behaviour matches
   inbound. *(If it kept the outbound prompt, inbound behaviour would be broken on handoff.)*
2. **`dynamic_variables` survive.** Check the **post-call webhook payload / call-log row**
   for the handed-off conversation: are `outboundCallId` / `referenzId` still present and is
   the call correctly attributed to the original outbound record? **If they're lost,
   post-call attribution on handed-off legs silently breaks** — a real bug independent of
   prompt size; fix would be to re-thread the IDs (e.g. via the transfer or a lookup by
   conversation lineage).

## Guardrail to keep regardless
`transfer_to_agent` physically lives in the agent's `built_in_tools` on **inbound** too;
"NEVER during inbound" is enforced only by prompt text. Any inbound-prompt rewrite (B2/B4)
must keep that guard line, or an inbound self-transfer loop becomes possible.
