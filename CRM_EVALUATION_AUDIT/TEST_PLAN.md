# TEST PLAN — what to verify before merging to main

*Run on the branch / UAT. Test org **kiki-test-007** (`kikitest01@gmail.com` / `KikiTest2026!`), super-admin login for the admin surfaces. Stripe items use the **TEST** sandbox + card `4242 4242 4242 4242`. ✅ = pass criteria. Items are grouped; skip any area you don't need.*

## A. Kiki-Zentrale (Batch 1)
1. Settings → make a config change with a manual prompt override active → **drift banner appears**; click "Mit Einstellungen synchronisieren" → ✅ banner clears, prompt re-synced.
2. Open the **"Stände"** tab → ✅ snapshots listed with readable German labels + who/when; click **Wiederherstellen** on one → ✅ confirm dialog, then the agent's webhook + overrides (not just prompt) are restored.
3. Save a Notdienst/Telefon change that fails EL sync (or check the banner) → ✅ failure is shown, not silently "applied".

## B. Onboarding / agent health (Batch 2)
4. Super-admin → orgs list → ✅ each org shows an **Agent-Zustand** pill (green OK / red N Probleme / grey kein Agent); click → ✅ modal lists the 7 checks (tools, webhook=prod, audio, prompt, overrides, phone).
5. Provision an org whose EL agent has **no phone bound** → ✅ provisioning completes with a clear "Telefonnummer fehlt" message (no 400 crash); health shows phone red.

## C. Receptionist / calls (Batch 4) — use the test agent `agent_5001`, call `+917879997839`
6. Call as a known customer using their **2nd number (phone2)** → ✅ agent recognises them (not "new customer").
7. Known customer with an open case calls → ✅ agent references the open case ("Ihr offener Vorgang …").
8. Trigger a missed/no-answer call → ✅ a `missed_calls` row + an Open Action (callback) appears.
9. Set a Terminregel **Frühester Termin (Uhrzeit) = 10:00**, place a booking request on a **weekend** → ✅ no slots before 10:00 on the first bookable weekday.

## D. Technician & planning board (Batch 5)
10. Planning board → people filter → ✅ labelled **Techniker**, lists only `is_technician` staff; cards show the assigned technician.
11. Dispatch an appointment to a **non-technician** employee → ✅ 422 "nicht als Techniker hinterlegt".
12. Set an employee `auto_assign=true` + an `activity_area` matching a category; place a call about that topic → ✅ that employee is auto-assigned post-call.
13. Open a technician job link (`/job/<token>`) → ✅ works; check `first_viewed_at` stamped. Super-admin → **rotate-technician-token** → ✅ old standing link invalid, new one emailed. (Expiry is 30 days — verify columns, not by waiting.)

## E. Invoicing (Batch 6)
14. Create an invoice with a **Skonto %/Tage** → ✅ PDF + Summen show "abzgl. X% Skonto" and "Zahlbetrag bei Zahlung in N Tagen"; **Gesamtbetrag (amount due) unchanged**.
15. Open a new invoice from a **customer / case / KVA** → ✅ customer block (Name, Kundennummer, USt-IdNr, Adresse) + Betreff + KVA line items/fields prefilled.
16. Convert a KVA to an invoice, then try again → ✅ second attempt blocked (409). Accept an **expired** KVA → ✅ 409 "abgelaufen".
17. Re-upload the **same catalog CSV** → ✅ items **updated, not doubled**; summary shows hinzugefügt/aktualisiert/übersprungen.
18. (Optional) Enable the `invoices_enabled` toggle, mark a case **completed** → ✅ a **draft** invoice is auto-created (never auto-sent).

## F. Billing / copilot (Batch 7)
19. Set `COPILOT_MONTHLY_COST_CAP_USD` very low (e.g. 0.01), use the copilot → ✅ chat + confirm return **429** "monatliche KI-Budget … erreicht"; set back to 25 → ✅ works.
20. Confirm KI-Nutzung (Settings) and Abrechnung show the **same** monthly minutes (tz fix) and a warning fires at **≥80%** of quota.

## G. Open Actions (Batch 8)
21. Cancel a confirmed appointment → in Posteingang the **"Termin storniert"** card → click the primary button → ✅ it clears (no 409).
22. Reschedule that the system can't auto-match (forwarded to team) → ✅ a **"Terminänderung zuordnen"** Open Action appears (was invisible).

## H. Pay-upfront flow (this session — the new strategy) — Stripe TEST mode
23. **No trial:** run any checkout → ✅ the resulting Stripe subscription is **active/incomplete, NOT trialing**; `trial_period_days` absent.
24. **Email+mobile tie:** set a test org's `email` + `phone_number`; in Stripe TEST, complete a Checkout whose `customer_details` email+phone match → ✅ webhook **auto-links** `stripe_customer_id` to that org. Mismatched phone → ✅ goes to `billing_migration_log` for review (no wrong-org link). No match → ✅ no-op, no crash.
25. **n8n bind-only:** call `POST /api/heykiki/provision` with `agent_externally_managed=true` + `elevenlabs_agent_id` + `phone_number` + `elevenlabs_phone_number_id` → ✅ org created, agent **bound + verified**, `configure_agent` **NOT** run (n8n's prompt/tools intact). Re-bind via `POST /api/super-admin/orgs/{id}/bind-agent` → ✅ updates + verifies.
26. **No upgrade:** as a customer, confirm there is **no plan upgrade/downgrade** control; the Stripe billing portal blocks plan change.
27. **Webhook security:** forged/unsigned webhook body → ✅ 400; valid → 200; replay the same event id → ✅ idempotent (no double-link).

## I. Security (Batch 3) — quick
28. Run Supabase **security advisors** → ✅ only the 6 intentional items remain (4 deny-all tables + `auth_org_id` + leaked-password). Confirm the app still works (it uses the service role, so RLS policies don't affect it).

---
**Regression sanity:** `cd backend && pytest -q -m "not live"` → ✅ all green except the 1 known network test; `cd frontend && tsc -b` → ✅ exit 0.
