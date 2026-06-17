# BUSINESS RULE COVERAGE — KikiJarvis CRM

*Generated 2026-06-17 from 436 extracted rules across 14 domains and 123 features.*

## Coverage Score

> **Coverage Score: 94%**  
> Clearly Defined (`CLEAR`+`WELL_IMPLEMENTED`): **410/436 = 94%**  
> Partially Implemented: **22/436 = 5%**  
> Ambiguous / Missing / Undefined / Orphan / Deprecated: **4/436 = 1%**

**Justification:** the score is the share of rules classified `CLEAR` or `WELL_IMPLEMENTED` — i.e. behavior that is unambiguous in code and safe to document as authoritative. `PARTIALLY_IMPLEMENTED` rules work but have gaps; the remaining bucket needs product decisions or carries undefined behavior. See `AUDIT_REPORT.md` for the narrative and `RUNTIME_VALIDATION_REPORT.md` for live confirmation.

## Classification Breakdown

| Classification | Count | % |
|---|---|---|
| CLEAR | 103 | 24% |
| WELL_IMPLEMENTED | 307 | 70% |
| PARTIALLY_IMPLEMENTED | 22 | 5% |
| AMBIGUOUS | 2 | 0% |
| MISSING | 1 | 0% |
| ORPHAN | 1 | 0% |
| **Total** | **436** | 100% |

## Runtime Validation

- **Domains with live runtime confirmation** (9 of 14): APPT, AUTH, CALL, CASE, CUST, INQ, KIKI, OUT, PROJ — covering ~281 rules (64% of all rules) touched by the DB / deployed-stack / ElevenLabs checks in `RUNTIME_VALIDATION_REPORT.md`.
- **Code-only domains** (no live runtime exercise this round): EMP, INV, BILL, COMM, COP — validated by static evidence; runtime procedures documented for outbound/email.
- Runtime confirmed: pipeline linkage, org-code numbering, status machines, emergency flagging, AI case grouping, outbound occasion taxonomy, DB write-persist round-trip, ElevenLabs prompt render. Unverified at runtime: ElevenLabs tool/webhook/audio (MCP simplified view), appointment proposal/reschedule states (no live rows).

## Per-Domain Coverage

| Domain | Rules | Features | Clearly-defined % | Avg conf | Runtime |
|---|---|---|---|---|---|
| AUTH | 32 | 7 | 94% | 97 | ✅ |
| CUST | 25 | 10 | 88% | 96 | ✅ |
| INQ | 20 | 12 | 100% | 96 | ✅ |
| CASE | 25 | 4 | 96% | 93 | ✅ |
| PROJ | 28 | 10 | 96% | 98 | ✅ |
| APPT | 46 | 10 | 100% | 98 | ✅ |
| EMP | 31 | 6 | 90% | 96 | — |
| INV | 33 | 10 | 82% | 97 | — |
| BILL | 34 | 9 | 97% | 97 | — |
| COMM | 25 | 8 | 100% | 96 | — |
| OUT | 28 | 6 | 89% | 96 | ✅ |
| CALL | 40 | 8 | 95% | 95 | ✅ |
| COP | 32 | 8 | 91% | 95 | — |
| KIKI | 37 | 15 | 97% | 91 | ✅ |

