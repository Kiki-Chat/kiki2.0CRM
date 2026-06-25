"""Last-resort customer linking: pull a phone number out of the conversation when
Caller-ID and the structured data_collection fields gave us nothing (migrated/web
conversations). Pure unit coverage of the two helpers."""
from __future__ import annotations

from app.services.post_call import _normalize_de_phone, _phone_from_transcript


def test_normalize_de_phone_variants():
    assert _normalize_de_phone("+49 170 1234567") == "+491701234567"
    assert _normalize_de_phone("0170 1234567") == "+491701234567"
    assert _normalize_de_phone("0049/170-1234567") == "+491701234567"
    # Too short / too long → rejected (not phone-plausible).
    assert _normalize_de_phone("12345") is None
    assert _normalize_de_phone("0049 170 1234567890123") is None


def test_phone_from_transcript_scans_customer_turns_only():
    transcript = [
        {"role": "agent", "message": "Guten Tag, wie ist Ihre Nummer?"},
        {"role": "user", "message": "Ja, meine Nummer ist 0170 1234567, danke."},
    ]
    assert _phone_from_transcript(transcript) == "+491701234567"


def test_phone_from_transcript_ignores_agent_and_returns_none_when_absent():
    # A number only the AGENT says (e.g. reading back an office line) is not used.
    transcript = [
        {"role": "agent", "message": "Unsere Zentrale erreichen Sie unter 0170 1234567."},
        {"role": "user", "message": "Alles klar, vielen Dank!"},
    ]
    assert _phone_from_transcript(transcript) is None
    assert _phone_from_transcript([]) is None
    assert _phone_from_transcript(None) is None
