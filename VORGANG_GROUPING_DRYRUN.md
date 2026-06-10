# Vorgang grouping — DRY RUN (TobiasDachdecker)

## How it ran
- Pipeline: real signal (topic + call summaries + appointment) → text-embedding-3-small
  cosine pre-cluster → gpt-4o adjudication (JSON, temp 0, conservative, no prose).
- Scope: 5 customers (3 with ≥2 inquiries → sent to the LLM).
- Runtime 23.79s · tokens: embed 2690, prompt 3835, completion 1056 · est. cost **$0.015537**.

## Results
- Inquiries in: **40** → proposed cases out: **21**  (compression 1.9×).
- Real merges (multi-inquiry cases): **6**, folding **25** inquiries together.
- Tiers: auto(≥.80)=4 · review(.50–.79)=2 · low(<.50)=0 · single=15 · avg merge conf 0.9.

## Per customer
### Govind Yadav — 31 inquiries → 15 cases (4 merged)
- **Heating Not Working** · conf 0.9 · _auto_ · ANF-2026-0001, ANF-2026-0003, ANF-2026-0005
    ↳ All inquiries relate to a non-functional heating system, including a cancellation related 
- **Roof Damage Repair** · conf 0.79 · _review_ · ANF-2026-0006, ANF-2026-0007, ANF-2026-0034, ANF-2026-0035, ANF-2026-0037, ANF-2026-0039, ANF-2026-0040
    ↳ All inquiries and appointments relate to roof damage and repair scheduling.
- **Gas Heating Maintenance** · conf 0.9 · _auto_ · ANF-2026-0008, ANF-2026-0009, ANF-2026-0016
    ↳ All inquiries and appointments relate to maintenance of the gas heating system.
- **Leaking Ceiling** · conf 0.79 · _review_ · ANF-2026-0011, ANF-2026-0012, ANF-2026-0013, ANF-2026-0014, ANF-2026-0019, ANF-2026-0025, ANF-2026-0028
    ↳ All inquiries and appointments relate to a leaking ceiling issue.
- _standalone (11):_ ANF-2026-0002, ANF-2026-0004, ANF-2026-0010, ANF-2026-0017, ANF-2026-0021, ANF-2026-0022, ANF-2026-0033, ANF-2026-0015, ANF-2026-0018, ANF-2026-0020, ANF-2026-0038

### Nikhil Yadav — 4 inquiries → 2 cases (1 merged)
- **Panasonic Heizung (Modell 2015) im Badezimmer heizt nicht** · conf 1.0 · _auto_ · ANF-2026-0023, ANF-2026-0024, ANF-2026-0032
    ↳ Anliegen betrifft die gleiche Heizung und den gleichen Termin.
- _standalone (1):_ ANF-2026-0029

### Thomas Muller — 3 inquiries → 2 cases (1 merged)
- **Toilette defekt - Wasseraustritt im Bad** · conf 1.0 · _auto_ · ANF-2026-0030, ANF-2026-0031
    ↳ Beide Anfragen betreffen das gleiche Anliegen einer defekten Toilette.
- _standalone (1):_ ANF-2026-0036

### Keshav Lalit — 1 inquiries → 1 cases (0 merged)
- _standalone (1):_ ANF-2026-0026

### Keshav Lalit — 1 inquiries → 1 cases (0 merged)
- _standalone (1):_ ANF-2026-0027

