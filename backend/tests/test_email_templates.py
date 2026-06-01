"""Tests for email_templates: crash-safe placeholder substitution + the
dynamic (per-org) company name in the branded shell."""
from __future__ import annotations

from app.services import email_templates as et


# ─── substitute() — replaces the placeholder fragility (str.format → safe) ──
def test_substitute_replaces_known_placeholders():
    out = et.substitute(
        "Rechnung {number} für {customer_name} von {org_name}",
        number="RE-1", customer_name="Max Mustermann", org_name="Muster GmbH",
    )
    assert out == "Rechnung RE-1 für Max Mustermann von Muster GmbH"


def test_substitute_leaves_unknown_placeholder_and_stray_brace_literal():
    # Unknown {betrag} and a stray "{" must NOT raise (str.format would) —
    # they degrade to literal text instead of a 500 at send time.
    tpl = "Hallo {customer_name}, Betrag {betrag} — 100% sicher {"
    out = et.substitute(tpl, customer_name="Max", org_name="X", number="N")
    assert out == "Hallo Max, Betrag {betrag} — 100% sicher {"


def test_substitute_handles_none_and_empty():
    assert et.substitute(None, number="x") == ""
    assert et.substitute("", number="x") == ""


# ─── company name is dynamic, per-org (the "same name" report = one-org test) ─
def test_company_name_is_dynamic_per_org():
    a = et.render_message_email(company_name="Muster Heizungsbau GmbH", message_text="Hallo")
    b = et.render_message_email(company_name="Sharma Elektro UG", message_text="Hallo")
    assert "Muster Heizungsbau GmbH" in a and "Muster Heizungsbau GmbH" not in b
    assert "Sharma Elektro UG" in b and "Sharma Elektro UG" not in a


def test_company_name_falls_back_when_missing():
    out = et.render_message_email(company_name=None, message_text="Hallo")
    # White-label: a NEUTRAL fallback, never HeyKiki/Kiki-Chat branding.
    assert "Ihr Dienstleister" in out
    assert "Heykiki" not in out and "Kiki-Chat" not in out and "kikichat.de" not in out


def test_footer_is_white_label_company_contact():
    out = et.render_message_email(
        company_name="Muster Heizungsbau GmbH", message_text="Hallo",
        contact_email="info@muster.de", address="Hauptstr. 1, 12345 Berlin",
    )
    assert "info@muster.de" in out and "Hauptstr. 1, 12345 Berlin" in out
    # No HeyKiki/Kiki-Chat anywhere in the customer-facing email.
    assert "Kiki-Chat" not in out and "kikichat.de" not in out and "Telefonistin" not in out


# ─── German placeholders the template editor emits actually interpolate ──────
def test_substitute_supports_editor_german_aliases():
    out = et.substitute(
        "Hallo {kundename}, Ihre Rechnung {rechnungsnummer} von {firmenname}",
        firmenname="Muster GmbH", kundename="Max", rechnungsnummer="RE-7",
    )
    assert out == "Hallo Max, Ihre Rechnung RE-7 von Muster GmbH"


def test_kva_builder_interpolates_firmenname_and_kundename():
    """The editor offers {firmenname}/{kundename}/{kvanummer}; the KVA builder
    must interpolate them per-org (bug 3) — not leave them literal or crash."""
    from app.api.routes.cost_estimates import _build_kva_email
    from app.schemas.admin import CostEstimateSend

    _, body_html = _build_kva_email(
        ce_row={"type": "kva", "number": "KVA-1"},
        org={"name": "Muster Heizungsbau GmbH"},
        customer={"full_name": "Max Mustermann"},
        email_config={"kva_email_body": "Hallo {kundename}, von {firmenname}. Nr {kvanummer}."},
        payload=CostEstimateSend(),
    )
    assert "Muster Heizungsbau GmbH" in body_html  # {firmenname} → org name, per-org
    assert "Max Mustermann" in body_html           # {kundename}
    assert "KVA-1" in body_html                    # {kvanummer}
    assert "{firmenname}" not in body_html         # interpolated, not literal
