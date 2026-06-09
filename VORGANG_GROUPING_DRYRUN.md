# Vorgang grouping — DRY RUN (TobiasDachdecker)

## How it ran
- Pipeline: real signal (topic + call summaries + appointment) → text-embedding-3-small
  cosine pre-cluster → gpt-4o-mini adjudication (JSON, temp 0, conservative, no prose).
- Scope: 5 customers (3 with ≥2 inquiries → sent to the LLM).
- Runtime 23.72s · tokens: embed 2589, prompt 3521, completion 706 · est. cost **$0.001003**.

## Results
- Inquiries in: **40** → proposed cases out: **13**  (compression 3.08×).
- Real merges (multi-inquiry cases): **6**, folding **33** inquiries together.
- Tiers: auto(≥.80)=5 · review(.50–.79)=1 · low(<.50)=0 · single=7 · avg merge conf 0.88.

## Per customer
### Govind Yadav — 31 inquiries → 8 cases (4 merged)
- **Heating Issues and Appointments** · conf 0.9 · _auto_ · ANF-2026-0001, ANF-2026-0003, ANF-2026-0005, ANF-2026-0006, ANF-2026-0009, ANF-2026-0010, ANF-2026-0016, ANF-2026-0018, ANF-2026-0019, ANF-2026-0020, ANF-2026-0033, ANF-2026-0035, ANF-2026-0037, ANF-2026-0039
    ↳ Alle Anfragen betreffen Heizungsprobleme und damit verbundene Termine.
- **Roof Damage and Repairs** · conf 0.9 · _auto_ · ANF-2026-0007, ANF-2026-0011, ANF-2026-0012, ANF-2026-0014, ANF-2026-0034, ANF-2026-0038
    ↳ Alle Anfragen betreffen Dachschäden und Reparaturtermine.
- **General Inquiries and Humor** · conf 0.8 · _auto_ · ANF-2026-0002, ANF-2026-0004, ANF-2026-0017
    ↳ Anfragen sind allgemeiner Natur und betreffen keine spezifischen Reparaturen.
- **Other Appointments** · conf 0.7 · _review_ · ANF-2026-0021, ANF-2026-0022, ANF-2026-0025, ANF-2026-0028
    ↳ Anfragen betreffen verschiedene andere Termine, die nicht direkt mit den vorherigen Fällen
- _standalone (4):_ ANF-2026-0008, ANF-2026-0013, ANF-2026-0015, ANF-2026-0040

### Nikhil Yadav — 4 inquiries → 2 cases (1 merged)
- **Panasonic Heizung im Badezimmer** · conf 1.0 · _auto_ · ANF-2026-0023, ANF-2026-0024, ANF-2026-0032
    ↳ Anliegen bezüglich der Panasonic Heizung im Badezimmer, inklusive Buchung und Stornierung 
- _standalone (1):_ ANF-2026-0029

### Thomas Muller — 3 inquiries → 1 cases (1 merged)
- **Toilette defekt - Wasseraustritt im Bad** · conf 1.0 · _auto_ · ANF-2026-0030, ANF-2026-0031, ANF-2026-0036
    ↳ Eindeutiges Anliegen bezüglich defekter Toilette und Terminänderung

### Keshav Lalit — 1 inquiries → 1 cases (0 merged)
- _standalone (1):_ ANF-2026-0026

### Keshav Lalit — 1 inquiries → 1 cases (0 merged)
- _standalone (1):_ ANF-2026-0027

