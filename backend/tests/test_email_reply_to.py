"""Reply-To is ALWAYS the company's (org's) email — for every email type.

Recipients reply to the COMPANY, never the Brevo relay / HeyKiki "via" address,
and never a per-connection sending account. One consistent reply target across
appointment calls/emails, KVA, invoice, employee invite, and test mail (all route
through send_email).
"""
from __future__ import annotations

from app.services import email_send


def _capture_brevo(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(email_send, "_send_via_brevo", lambda **kw: (captured.update(kw) or "msg-id"))
    return captured


def test_reply_to_is_org_email_over_connected_account(monkeypatch):
    """A connected sending account must NOT override the company email."""
    cap = _capture_brevo(monkeypatch)
    monkeypatch.setattr(email_send, "_load_org_email", lambda oid: "company@muster.de")
    monkeypatch.setattr(email_send, "_load_org_name", lambda oid: "Muster")
    # connected account present, but no oauth_provider/refresh + no smtp_host →
    # tiers 1+2 skip → brevo fires. Old behaviour replied to the connected account.
    monkeypatch.setattr(email_send, "_load_email_config", lambda oid: {"oauth_account_email": "connected@gmail.com"})

    res = email_send.send_email(
        org_id="org-1", to_email="cust@x.de", subject="S", body_html="<p>B</p>",
        reply_to="caller@x.de",
    )
    assert res.success
    assert cap["reply_to"] == "company@muster.de"  # NOT connected@gmail.com, NOT caller@x.de


def test_reply_to_set_even_when_caller_omits_it(monkeypatch):
    """Employee invite / test mail don't pass reply_to — still get the org email."""
    cap = _capture_brevo(monkeypatch)
    monkeypatch.setattr(email_send, "_load_org_email", lambda oid: "company@muster.de")
    monkeypatch.setattr(email_send, "_load_org_name", lambda oid: "Muster")
    monkeypatch.setattr(email_send, "_load_email_config", lambda oid: None)

    email_send.send_email(org_id="org-1", to_email="c@x.de", subject="S", body_html="<p>B</p>")
    assert cap["reply_to"] == "company@muster.de"


def test_reply_to_falls_back_to_caller_when_org_has_no_email(monkeypatch):
    """Org with no email on file → fall back to the caller-supplied reply_to."""
    cap = _capture_brevo(monkeypatch)
    monkeypatch.setattr(email_send, "_load_org_email", lambda oid: None)
    monkeypatch.setattr(email_send, "_load_org_name", lambda oid: "Muster")
    monkeypatch.setattr(email_send, "_load_email_config", lambda oid: None)

    email_send.send_email(
        org_id="org-1", to_email="c@x.de", subject="S", body_html="<p>B</p>", reply_to="fallback@x.de",
    )
    assert cap["reply_to"] == "fallback@x.de"
