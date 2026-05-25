# STEP 5 — Kiki-Zentrale E2E test results

_Run: 2026-05-25 23:30:02_  ·  **15/15 E2E checks passed**

## Baseline

```
{
  "name": "Mathew Murdock",
  "language": "en",
  "voice": "Aa6nEBJJMKJwJkCx8VU2",
  "first": "Good afternoon, this is Kiki from Murdock and Law How can I help you?",
  "plen": 52877,
  "tools": 13,
  "kb": 0,
  "audio": true
}
```

## E2E checks (route → safety layer → live ElevenLabs)

| Check | Expected | Actual | Result |
|---|---|---|---|
| Verhalten: persona_name applied | `Kiki Test` | `Kiki Test` | ✅ |
| Verhalten: language applied | `de` | `de` | ✅ |
| Verhalten: voice applied | `CwhRBWXzGAHq8TQ4Fs17` | `CwhRBWXzGAHq8TQ4Fs17` | ✅ |
| Verhalten: first_message applied | `Hallo, hier ist Kiki. Wie kann ich helfe…` | `Hallo, hier ist Kiki. Wie kann ich helfe…` | ✅ |
| Verhalten: tools preserved (no clobber) | `13` | `13` | ✅ |
| Verhalten: audio present after write | `True` | `True` | ✅ |
| Verhalten: rollback restored name | `Mathew Murdock` | `Mathew Murdock` | ✅ |
| Verhalten: rollback restored language | `en` | `en` | ✅ |
| Verhalten: rollback restored first_message | `Good afternoon, this is Kiki from Murdoc…` | `Good afternoon, this is Kiki from Murdoc…` | ✅ |
| Prompt: applied | `116` | `116` | ✅ |
| Prompt: tools preserved | `13` | `13` | ✅ |
| Prompt: rollback restored length | `52877` | `52877` | ✅ |
| Quota: 7 occasions over 100-min quota | `True` | `True` | ✅ |
| Quota: 2 occasions under 100-min quota | `True` | `True` | ✅ |
| Restore-to-baseline: agent == baseline | `{'name': 'Mathew Murdock', 'language': '…` | `{'name': 'Mathew Murdock', 'language': '…` | ✅ |

## pytest suite (unit + live)

- 8 safety unit tests (test_elevenlabs_safety.py) — silent-agent abort, cross-org block, no-op gating, verification-failure auto-rollback, snapshot rollback, tools/client_events union — **PASS**
- 6 live tests (test_elevenlabs_live.py) — GET, audio-assertion-untouched, cross-org, patch+rollback, first_message round-trip, KB push/remove (chunk_count>0) — **PASS**
- 8 pre-existing tool-schema tests — **PASS**
- **Total: 22 passed** (`pytest tests/`, ~47s)

## Typecheck

- Kiki-Zentrale frontend module (7 files): **0 errors** (`tsc -b`).
- 22 pre-existing `tsc -b` errors remain in 6 unrelated modules (InvoiceFormPage, ProjectWorkspacePage, SettingsPage, projectTabs, CostEstimateFormPage, EmployeesPage) — present at HEAD eb972ae, not introduced by this work.

## Final agent state

Equal to baseline: **True**
