"""Cluster C — emails for the existing 7 occasions (ship INERT behind the flag).

  * render_occasion_email → German subject/body for each of the 7;
  * flag OFF (default) → no send even though email_render is wired (inert);
  * flag ON → sends, scope-guarded to the test inbox;
  * the frontend↔backend missed_callback key now aligns (the dead toggle is fixed).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.config import settings as cfg
from app.services import outbound_dispatch
from app.services.occasion_emails import render_occasion_email
from app.services.outbound_occasions import OCCASIONS

TEST_ORG = "c4dbf596-86fd-4484-88d9-095b2c082afb"
_ORG = {"id": TEST_ORG, "name": "Muster Heizungsbau GmbH", "email": "info@muster.de", "address": None}
_CUST = {"id": "c", "full_name": "Max Mustermann", "email": "max@real.de"}

RECORDS = {
    "appointment_reminder": {"scheduled_at": "2026-06-10T08:00:00+00:00", "title": "Wartung"},
    "kva_followup": {"number": "KVA-7", "subject": "Heizung", "total": 1234.5, "sent_at": "2026-05-20T09:00:00+00:00"},
    "payment_reminder": {"number": "RE-9", "total": 339.15, "due_date": "2026-05-15"},
    "satisfaction_survey": {"title": "Heizung Reparatur"},
    "review_request": {"title": "Heizung Reparatur"},
    "maintenance_due": {},
    "missed_callback": {},
}


@pytest.mark.parametrize("occ", list(RECORDS))
def test_each_occasion_email_renders(occ):
    subj, html = render_occasion_email(occ, RECORDS[occ], _CUST, _ORG)
    assert subj and isinstance(subj, str)
    assert "Max Mustermann" in html
    assert "Muster Heizungsbau GmbH" in html  # white-label header/footer


def test_kva_email_has_amount_and_number():
    _subj, html = render_occasion_email("kva_followup", RECORDS["kva_followup"], _CUST, _ORG)
    assert "KVA-7" in html and "1.234,50" in html  # German EUR grouping


def test_payment_email_soft_tone():
    _subj, html = render_occasion_email("payment_reminder", RECORDS["payment_reminder"], _CUST, _ORG)
    assert "gegenstandslos" in html  # soft, explicitly-not-a-Mahnung tone


def test_unknown_occasion_raises():
    with pytest.raises(ValueError):
        render_occasion_email("nope", {}, _CUST, _ORG)


# ─── flag gating at the dispatch chokepoint ──────────────────────────────────
@pytest.fixture
def scope(monkeypatch):
    monkeypatch.setattr(cfg, "outbound_test_scope_only", True)
    monkeypatch.setattr(cfg, "outbound_test_email", "agrawalamber01@gmail.com")
    monkeypatch.setattr(cfg, "outbound_test_org_ids", TEST_ORG)


def test_existing_occasion_inert_when_flag_off(monkeypatch, scope):
    monkeypatch.setattr(cfg, "outbound_occasion_emails_enabled", False)
    send = MagicMock()
    monkeypatch.setattr(outbound_dispatch, "send_email", send)
    to = outbound_dispatch._maybe_send_occasion_email(
        spec=OCCASIONS["kva_followup"], record=RECORDS["kva_followup"], customer=_CUST, org=_ORG, org_id=TEST_ORG
    )
    assert to is None
    send.assert_not_called()


def test_existing_occasion_sends_when_flag_on(monkeypatch, scope):
    monkeypatch.setattr(cfg, "outbound_occasion_emails_enabled", True)
    sent: dict = {}
    monkeypatch.setattr(outbound_dispatch, "send_email", lambda **kw: sent.update(kw))
    to = outbound_dispatch._maybe_send_occasion_email(
        spec=OCCASIONS["kva_followup"], record=RECORDS["kva_followup"], customer=_CUST, org=_ORG, org_id=TEST_ORG
    )
    assert to == "agrawalamber01@gmail.com"
    assert sent["to_email"] == "agrawalamber01@gmail.com"  # scope-forced even with the flag on


def test_missed_callback_key_aligned_and_wired():
    # The frontend toggle key now matches the backend registry (no dead toggle);
    # and the occasion has an email_render wired (flag-gated).
    assert "missed_callback" in OCCASIONS
    assert OCCASIONS["missed_callback"].email_render is not None
    assert OCCASIONS["missed_callback"].email_always is False
