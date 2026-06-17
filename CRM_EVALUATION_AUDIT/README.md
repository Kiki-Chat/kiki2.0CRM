# KikiJarvis CRM — Audit Deliverables

Authoritative, evidence-based reverse-engineering of the KikiJarvis CRM, generated **2026-06-17**.
Method: static code analysis (14 domains, **436 business rules**, 123 features) + live runtime validation against the **kiki-test-007** sandbox. Every rule cites `path:line` evidence; runtime-confirmed behavior is cross-referenced in the runtime report.

## The 15 deliverables

| # | Document | What it is |
|---|---|---|
| 1 | [BUSINESS_RULES.md](BUSINESS_RULES.md) | Full catalog of all 436 rules, grouped by domain, with the complete field set + evidence |
| 2 | [AUDIT_REPORT.md](AUDIT_REPORT.md) | Functional audit narrative: domain findings, risks, prioritized observations |
| 3 | [AI_COPILOT_RULEBOOK.md](AI_COPILOT_RULEBOOK.md) | Governance rules for an AI Copilot to safely operate the CRM (allowed/forbidden/approval) |
| 4 | [REPOSITORY_MAP.md](REPOSITORY_MAP.md) | Structure, modules, 52 tables, dependency + data-flow diagrams |
| 5 | [WORKFLOW_DIAGRAMS.md](WORKFLOW_DIAGRAMS.md) | 12 end-to-end workflows with Mermaid flowcharts + tables |
| 6 | [TRACEABILITY_MATRIX.md](TRACEABILITY_MATRIX.md) | Every rule → modules / APIs / tables / source refs |
| 7 | [BUSINESS_RULE_COVERAGE.md](BUSINESS_RULE_COVERAGE.md) | Coverage score (94%), classification breakdown, per-domain coverage |
| 8 | [FEATURE_TO_RULE_MATRIX.md](FEATURE_TO_RULE_MATRIX.md) | 123 features ↔ governing rules; orphan analysis |
| 9 | [KIKI_CENTRAL_AUDIT.md](KIKI_CENTRAL_AUDIT.md) | Kiki-Zentrale voice-agent config subsystem audit |
| 10 | [ELEVENLABS_SYNC_AUDIT.md](ELEVENLABS_SYNC_AUDIT.md) | What syncs to ElevenLabs, overwrite risks, safety layer |
| 11 | [RUNTIME_VALIDATION_REPORT.md](RUNTIME_VALIDATION_REPORT.md) | Live validation vs kiki-test-007 (DB, deployed stack, ElevenLabs, security advisors) |
| 12 | [CRM_GLOSSARY.md](CRM_GLOSSARY.md) | Onboarding dictionary (German UI labels + English) |
| 13 | [SECURITY_OBSERVATION_REPORT.md](SECURITY_OBSERVATION_REPORT.md) | 25 static observations + live Supabase advisor findings (observations only) |
| 14 | [INTEGRATION_DEPENDENCY_MAP.md](INTEGRATION_DEPENDENCY_MAP.md) | 13 integrations, 47 env vars, auth + failure modes |
| 15 | [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) | Decision-oriented overview for executives & product owners |
| + | [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) | Independent adversarial second pass: 18 agents re-checked 170 rules against source + fact-checked the narrative docs (0 hallucinations, 0 major issues, 89% mean confidence) |

## Domains (rule-ID prefixes)

`AUTH` Auth/Roles/Multi-tenancy · `CUST` Customers/Leads · `INQ` Inquiries (ANF) · `CASE` Cases (FL) · `PROJ` Projects (PR) · `APPT` Appointments/Calendar/Dispatch · `EMP` Employees/Technicians · `INV` Invoices/KVA/Catalog · `BILL` Stripe Billing · `COMM` Email/Notifications · `OUT` Outbound calls · `CALL` Inbound calls/Conversation logic · `COP` AI Copilot · `KIKI` Kiki-Zentrale/ElevenLabs

## Evidence base

`_data/` holds the structured JSON evidence the deliverables were generated from (one file per domain under `_data/rules/`, plus `repo_map.json`, `workflows.json`, `security.json`, `kiki_deep.json`, and the runtime evidence `runtime_db.json` / `elevenlabs_runtime.json`). `_data/_render.py` deterministically generates the structured deliverables (1, 6, 7, 8, 5, 13, 4, 14) from that evidence — re-run it to regenerate them faithfully.
