"""Content-based (bilingual) emergency detection for the call-log emergency flag.

Locks the fix for the 2026-06-09 finding: the agent's data_collection almost never
carries an explicit emergency field, so `ensure_call_inquiry` also derives urgency
from the call's summary/extraction text. The matcher must catch DE *and* EN
emergencies while NOT mis-flagging routine after-hours repairs.
"""
from __future__ import annotations

from app.services.inquiries import _content_signals_emergency


def _call(title: str = "", **dc) -> dict:
    return {"summary_title": title, "data_collection": dc}


# ── should flag (DE) ─────────────────────────────────────────────────────────
def test_german_notfall_in_summary_flags():
    call = _call(
        "Toilet Emergency Inquiry",
        ultimate_summary=(
            "Es handelt sich um eine Notfallsituation mit Wasseraustritt. "
            "Das Anliegen wird als dringend markiert."
        ),
    )
    assert _content_signals_emergency(call) is True


def test_german_gasgeruch_flags():
    assert _content_signals_emergency(_call(issue_summary="Starker Gasgeruch in der Küche")) is True


def test_german_rohrbruch_flags():
    assert _content_signals_emergency(_call("Wasserschaden", next_action="Rohrbruch sofort abdichten")) is True


# ── should flag (EN) — the language-agnostic requirement ─────────────────────
def test_english_emergency_flags():
    assert _content_signals_emergency(_call("Toilet emergency", ultimate_summary="urgent toilet issue")) is True


def test_english_burst_pipe_flags():
    assert _content_signals_emergency(_call(ultimate_summary="A burst pipe is flooding the kitchen.")) is True


# ── should NOT flag (precision: routine work isn't an emergency) ─────────────
def test_routine_toilet_repair_does_not_flag():
    call = _call(
        "Toilet Repair Inquiry",
        issue_summary="Defekte Toilette mit hohem Wasserstand",
        ultimate_summary=(
            "Die Toilette ist kaputt und das Wasser steht hoch. Der Kunde hat das "
            "Ventil zugedreht. Das Team meldet sich zur Terminvereinbarung."
        ),
    )
    assert _content_signals_emergency(call) is False


def test_normal_question_does_not_flag():
    call = _call("General question", ultimate_summary="Asked about opening hours and pricing.")
    assert _content_signals_emergency(call) is False


def test_empty_call_does_not_flag():
    assert _content_signals_emergency({"summary_title": None, "data_collection": None}) is False
    assert _content_signals_emergency({}) is False
