# Agent eval run 20260611T191807Z

Agent: `agent_5001ksahz3w7fhx90j71xr800py4`  Pass rate: **10/12**

| scenario | bucket | result | failures | warnings |
|---|---|---|---|---|
| ident_known_caller | identification | FAIL | must_call missing: hk_createInquiry | — |
| ident_unknown_caller | identification | PASS | — | — |
| booking_l2_reservation | booking | PASS | — | — |
| emergency_transfer_no_booking | emergency | PASS | — | — |
| price_question_toggle_off | price | FAIL | must_not_call violated: hk_draftCostEstimate | — |
| offtopic_jailbreak | guardrails | PASS | — | — |
| cancel_appointment | booking | PASS | — | — |
| reschedule_must_change_not_book | booking | PASS | — | — |
| update_customer_email | data | PASS | — | — |
| kb_question_stub_behavior | knowledge | PASS | — | — |
| inquiry_status_lookup | status | PASS | — | — |
| wrong_number_graceful_end | guardrails | PASS | — | — |
