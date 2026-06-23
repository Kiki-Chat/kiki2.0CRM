#!/usr/bin/env python3
"""Offline eye-test for the OUTBOUND prompt assembly (no DB, no calls, no EL).

Renders the assembled outbound system prompt for a few config combinations so you
can see exactly what ships per call — including the two new config-driven blocks:
  • the emergency-escalation note (only when emergency_enabled), and
  • the autonomy level-1 "don't book" directive (only on booking occasions at L1).

Run:  python scripts/preview_outbound.py
(loads outbound_occasions in isolation — pure functions only, nothing live.)
"""
import importlib.util, sys, types, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]   # backend/
for name in ("app", "app.services"):
    m = types.ModuleType(name); m.__path__ = []; sys.modules[name] = m
spec = importlib.util.spec_from_file_location(
    "app.services.outbound_occasions", ROOT / "app/services/outbound_occasions.py"
)
oo = importlib.util.module_from_spec(spec)
sys.modules["app.services.outbound_occasions"] = oo
spec.loader.exec_module(oo)

TASK = (
    "## PRIMÄRE AUFGABE\n"
    "Du erinnerst Herrn Mustermann an seinen Termin am 24. Juni um 10 Uhr. "
    "Bestätige, verschiebe (über hk_getAvailableAppointments + hk_changeAppointment) "
    "oder sage ab. Niemals ohne Bestätigung buchen."
)

def show(title: str, *, cfg: dict, books: bool):
    anlass = oo._render_outbound_autonomy(cfg, books=books) + oo._render_outbound_emergency(cfg)
    prompt = oo.assemble_system_prompt(
        company="Mustermann GmbH", kunden_name="Herr Mustermann",
        task_block=TASK, anlass_regeln=anlass,
    )
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)
    print(prompt)

# Baseline: no Notdienst, autonomy L2 (current default) — base behaviour unchanged.
show("A) Baseline (emergency off, autonomy L2)  — unchanged base",
     cfg={"emergency_enabled": False, "appointments_level": 2}, books=True)

# Emergency ON (number set) — escalation note appears.
show("B) Emergency ON (Notdienst + Nummer)  — adds the in-call emergency note",
     cfg={"emergency_enabled": True, "emergency_keywords": ["Gasgeruch", "Rohrbruch"],
          "emergency_number": "+4915112345678", "appointments_level": 2}, books=True)

# Autonomy LEVEL 1 on a booking occasion — "don't book" directive appears.
show("C) Autonomy L1 on a booking occasion  — adds the don't-book directive",
     cfg={"emergency_enabled": False, "appointments_level": 1}, books=True)

# L1 + emergency together on a booking occasion.
show("D) Autonomy L1 + Emergency ON (booking occasion)  — both blocks",
     cfg={"emergency_enabled": True, "emergency_number": "+4915112345678",
          "appointments_level": 1}, books=True)

print("\n[OK] preview rendered — pure offline assembly, no DB / EL / calls.")
