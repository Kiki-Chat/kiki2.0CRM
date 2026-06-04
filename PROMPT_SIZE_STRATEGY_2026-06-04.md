# 11Labs Prompt-Size Reduction — Strategy (topic 23)

> Strategy only — no code changes here. The goal is to roughly **halve** the agent
> system prompt so a stronger/lower-latency model (we're on Gemini 3.5 Flash for
> latency) has less to chew through per turn, while keeping behaviour identical.

## 1. The problem
- The 11Labs system prompt is the single biggest input on every turn. The template
  alone is ~906 lines / ~56k chars (**~14k tokens**); fully rendered for a real org
  it reaches **~16–18k tokens**.
- Big prompts hurt twice: higher per-turn latency, and weaker instruction-following
  (the model has more to track). With a fast/cheaper model the effect is sharper.
- Much of the prompt is **static and repeated every call** even though it rarely
  changes and isn't needed on most turns.

## 2. Where the tokens go (anatomy)
| Section | ~Tokens | Changes per call? | Reducible? |
|---|---|---|---|
| Tool reference cards (10× `hk_*`, usage rules) | 3,000–4,000 | No | **Yes — biggest win** |
| Conversation-flow guide (6 steps, branching) | 3,000–4,000 | No | Partly (tighten) |
| Personality / tone / guardrails | 1,500 | No | Partly |
| Company identity + service area + hours | 800 | Per org | Keep (small) |
| Required fields / categories / scheduling / emergency | 1,500–2,500 | Per org | Partly (KB) |
| Knowledge-base + email rules | 1,500 | No | **Yes (KB/tooling)** |
| Autonomy block | ~100 | Per org | Already minimal ✅ |

## 3. Levers, ranked by impact

### A. Move tools to an MCP server (highest impact, ~3–4k tokens)
Today every tool is hand-described in the prompt *and* the agent is coached at length
on when to call each one. With an **MCP server** exposing the `hk_*` tools, 11Labs
discovers tool schemas/descriptions out-of-band — the prompt keeps only a 2–3 line
"use the available tools when appropriate" note instead of ~3–4k tokens of cards.
- **Action:** stand up an MCP endpoint that re-exports the existing `hk_*` tools (they
  already exist as 11Labs tools); attach it to the agent; delete the per-tool cards
  from `agent_prompt_template.txt`, leaving only the few genuinely behavioural rules
  (e.g. "identify the customer first", autonomy gating).
- **Risk:** MCP transport reliability + the model leaning on schema descriptions
  rather than prose. Mitigate by keeping ~5 high-value behavioural lines in-prompt.

### B. Knowledge-base offload (~1.5–2.5k tokens)
Static, rarely-needed, or long-tail content (detailed email rules, edge-case handling,
verbose examples, per-trade nuance) moves into the **knowledge base** and is pulled on
demand via `hk_queryKnowledgeBase` instead of living in every prompt.
- **Action:** identify "reference, not every-turn" passages and migrate them to KB
  documents; replace with a one-line pointer.

### C. Dynamic per-call injection (structural, ~2–4k tokens situationally)
The **conversation-init webhook** (already the injection point we used for topic 20)
can return a per-call `conversation_config_override.prompt.prompt`. So instead of a
single maximal prompt, assemble a **lean base** + only the blocks this call needs
(e.g. emergency block only outside business hours; KVA flow only if KVA is enabled).
- **Action:** render the prompt in tiers — always-on core vs. conditionally-injected
  blocks — and inject per call. This is the same Path-A override pattern outbound
  already uses.

### D. Dedup + concision (~1–2k tokens)
- Collapse repeated instructions (the "don't name tools / German only / be brief"
  rules are restated in several places — state once).
- Tighten verbose German prose; convert prose lists to compact bullets.
- Remove mundane filler that doesn't change behaviour.

### E. Capability-gated rendering (already started ✅)
The autonomy redesign already **keeps Projekte/Rechnungen out of the prompt**
(back-office) and **strips suggestion language at level 1**. Extend this: when a
capability/feature is off for an org, its block shouldn't render at all (emergency,
KVA, price-info, outbound all gate cleanly).

## 4. Target budget
| | Now | Target |
|---|---|---|
| Tool cards | ~3,500 | ~300 (MCP) |
| Flow guide | ~3,500 | ~2,000 (tighten + tier) |
| KB-able content | ~2,000 | ~400 (pointers) |
| Dedup/concision | — | −1,500 |
| **Rendered total** | **~16–18k** | **~8–9k** |

## 5. Recommended phasing
1. **Quick wins (no infra):** dedup + concision (D) and finish capability-gating (E).
   Low risk, immediate ~3k token cut.
2. **KB offload (B):** migrate reference content; medium effort.
3. **MCP for tools (A):** the structural win; needs an MCP endpoint + agent attach +
   careful eval that tool-calling quality holds with terse descriptions.
4. **Tiered per-call injection (C):** reuse the conversation-init override to assemble
   lean prompts; biggest structural change, do last with A/B/E in place.

## 6. Guardrails
- Change one lever at a time and **A/B against transcripts** — fewer tokens must not
  regress identification, booking, or emergency handling.
- Keep the ~5–10 non-negotiable behavioural lines in-prompt regardless of MCP.
- Measure: log rendered prompt token count per org + per-turn latency before/after.
