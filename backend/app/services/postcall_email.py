"""Post-call summary email — CRM port of HeyKiki's canonical n8n template.

Sent to the tradesperson after Kiki handles a customer call. Brand + structure
MUST stay identical to the n8n flow so the experience is constant across both.

This module renders the email; it does NOT wire the post-call trigger/data flow.
``build_context_from_records`` maps real CRM records → the render fields (the
deterministic bindings); ``render_postcall_summary`` applies the German
fallbacks + formatting and returns (subject, html). For a test send, call
``render_postcall_summary`` with dummy values directly.

Fallback discipline mirrors the reference exactly:
  name → "Geschätzte Kundin/Geschätzter Kunde", missing → "unbekannt",
  anonymous/empty phone → "Nummer nicht übertragen", missing link → "#",
  empty summary → "Keine Zusammenfassung verfügbar."
isEmpty() treats null / "null" / "n/a" / whitespace all as empty.
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo

    _BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover
    _BERLIN = timezone.utc

_NAME_FALLBACK = "Geschätzte Kundin/Geschätzter Kunde"
_UNKNOWN = "unbekannt"
_PHONE_FALLBACK = "Nummer nicht übertragen"
_SUMMARY_FALLBACK = "Keine Zusammenfassung verfügbar."
_DE_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

_SECTION_HEADERS = {
    "Kundeninformationen:", "Hauptanliegen:", "Besprochene Details:",
    "Nächste Schritte:", "Zusätzliche Informationen:", "Anmerkungen:",
}
_BULLET_RE = re.compile(r"^(?:[-•\*\+]|\d+\.)\s+(.+)$")
_BOLD_HEADER_RE = re.compile(r"^\*\*(.+?)\*\*$")
_INLINE_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def is_empty(v) -> bool:
    if v is None:
        return True
    s = v if isinstance(v, str) else str(v)
    s = s.strip()
    if not s:
        return True
    return s.lower() in ("null", "n/a")


def _or(value, fallback):
    return value if not is_empty(value) else fallback


def german_timestamp(raw) -> str:
    """de-DE: 'Montag, 28.05.2026, 14:32 Uhr' (converted to Europe/Berlin)."""
    if is_empty(raw):
        return _UNKNOWN
    dt = None
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:  # epoch (s or ms)
                num = float(s)
                dt = datetime.fromtimestamp(num / (1000 if num > 1e12 else 1), tz=timezone.utc)
            except ValueError:
                return _UNKNOWN
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(_BERLIN)
    return f"{_DE_WEEKDAYS[dt.weekday()]}, {dt:%d.%m.%Y}, {dt:%H:%M} Uhr"


def format_summary(text: str | None) -> str:
    """Port of the reference formatSummary(): markdown-ish → styled HTML."""
    if is_empty(text):
        return '<p style="margin: 0; line-height: 1.6; color: #555555;">' + _SUMMARY_FALLBACK + "</p>"
    text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    html_out = ""
    current_list: list[str] = []

    def _flush() -> str:
        nonlocal current_list
        if not current_list:
            return ""
        out = '<ul style="margin: 8px 0 16px 0; padding: 0 0 0 20px; list-style-type: disc;">\n'
        for item in current_list:
            out += f'  <li style="margin: 0 0 8px 0; line-height: 1.6; color: #555555;">{item}</li>\n'
        out += "</ul>\n"
        current_list = []
        return out

    for line in lines:
        bold_h = _BOLD_HEADER_RE.match(line)
        if bold_h:
            html_out += _flush()
            html_out += (
                f'<p style="margin: 16px 0 8px 0; font-weight: 600; font-size: 15px; color: #333333; '
                f"font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;\">{bold_h.group(1)}</p>\n"
            )
            continue
        if line in _SECTION_HEADERS:
            html_out += _flush()
            html_out += (
                f'<p style="margin: 16px 0 8px 0; font-weight: 600; font-size: 15px; color: #333333; '
                f"font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;\">{line}</p>\n"
            )
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            current_list.append(_INLINE_BOLD_RE.sub(r"<strong>\1</strong>", bullet.group(1)))
            continue
        html_out += _flush()
        content = _INLINE_BOLD_RE.sub(r"<strong>\1</strong>", line)
        html_out += (
            f'<p style="margin: 0 0 12px 0; line-height: 1.6; color: #555555; '
            f"font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;\">{content}</p>\n"
        )

    html_out += _flush()
    return html_out or '<p style="margin: 0; line-height: 1.6; color: #555555;">Keine Details verfügbar.</p>'


def _clean_address(address: str, postal: str) -> str:
    if is_empty(address):
        return _UNKNOWN
    address = str(address)
    if postal and postal != _UNKNOWN and postal in address:
        address = re.sub(re.escape(postal), "", address).strip()
        address = re.sub(r"[,\s]*$", "", address)
        address = re.sub(r"^[,\s]*", "", address)
    return address.strip() or _UNKNOWN


def render_postcall_summary(
    *,
    client_name=None,
    dashboard_link=None,
    customer_name=None,
    address=None,
    postal_code=None,
    customer_phone=None,
    call_time=None,
    next_action=None,
    summary=None,
    summary_title=None,
) -> tuple[str, str]:
    """Return (subject, html). Applies all reference fallbacks + helpers."""
    client = _or(client_name, _NAME_FALLBACK)
    link = _or(dashboard_link, "#")
    cust_name = _or(customer_name, client)
    postal = _or(postal_code, _UNKNOWN)
    addr = _clean_address(address if not is_empty(address) else _UNKNOWN, postal)
    phone = _PHONE_FALLBACK if (is_empty(customer_phone) or str(customer_phone).strip().lower() == "anonymous") else str(customer_phone)
    ts = german_timestamp(call_time)
    nxt = _or(next_action, _UNKNOWN)
    summary_html = format_summary(summary)
    subject = _or(summary_title, "Verpasster Anruf").strip() if not is_empty(summary_title) else "Verpasster Anruf"

    def esc(s):  # escape plain-text fields (summary_html is already HTML)
        return _html.escape(str(s), quote=True)

    body = _TEMPLATE
    for token, value in (
        ("@@CLIENTNAME@@", esc(client)),
        ("@@CUSTOMERNAME@@", esc(cust_name)),
        ("@@ADDRESS@@", esc(addr)),
        ("@@POSTAL@@", esc(postal)),
        ("@@PHONE@@", esc(phone)),
        ("@@TIMESTAMP@@", esc(ts)),
        ("@@NEXTACTION@@", esc(nxt)),
        ("@@DASHBOARD@@", esc(link)),
        ("@@SUMMARY@@", summary_html),  # already HTML
    ):
        body = body.replace(token, value)
    return subject, body


def build_context_from_records(*, call: dict, customer: dict | None, org: dict | None, dashboard_base: str) -> dict:
    """Deterministic bindings from real CRM records → render_postcall_summary kwargs.
    (Not wired to a trigger here — documents the field mapping.)"""
    customer = customer or {}
    org = org or {}
    addr = customer.get("address")
    street = postal = None
    if isinstance(addr, dict):
        street = addr.get("street") or addr.get("raw")
        postal = addr.get("postal_code")
        if street is None and addr.get("city"):
            street = addr.get("city")
    elif isinstance(addr, str):
        street = addr
    return {
        "client_name": org.get("name"),
        "dashboard_link": f"{dashboard_base.rstrip('/')}/calls/{call.get('id')}" if call.get("id") else None,
        "customer_name": customer.get("full_name"),
        "address": street,
        "postal_code": postal,
        "customer_phone": customer.get("phone") or call.get("caller_number"),
        "call_time": call.get("started_at") or call.get("created_at"),
        "next_action": None,  # NO direct CRM field — flagged for Amber
        "summary": call.get("summary"),
        "summary_title": call.get("summary_title"),
        # reply_to (Reply-To header) is org.get("email") — passed to send_email separately
    }


_TEMPLATE = r"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="de">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Heykiki - Neuer Kundenanruf</title>
  <!--[if mso]>
  <noscript>
    <xml>
      <o:OfficeDocumentSettings>
        <o:PixelsPerInch>96</o:PixelsPerInch>
      </o:OfficeDocumentSettings>
    </xml>
  </noscript>
  <![endif]-->
  <style type="text/css">
    body, table, td, p, a, li, blockquote { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
    table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
    img { -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; }
    table { border-collapse: collapse !important; }
    .ReadMsgBody { width: 100%; }
    .ExternalClass { width: 100%; }
    .ExternalClass, .ExternalClass p, .ExternalClass span, .ExternalClass font, .ExternalClass td, .ExternalClass div { line-height: 100%; }
    body { margin: 0 !important; padding: 0 !important; background-color: #f7f7f7 !important; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif !important; color: #333333 !important; }
    .email-wrapper { width: 100% !important; background-color: #f7f7f7 !important; }
    .email-container { width: 600px; max-width: 600px; background-color: #ffffff; margin: 0 auto; }
    .header-cell { background-color: #AFC4C4; background-image: linear-gradient(135deg, #AFC4C4 0%, #03423A 100%); padding: 25px 20px; text-align: center; }
    .logo { display: block; margin: 0 auto; width: 105px; height: auto; border: 0; }
    .header-title { margin: 12px 0 0 0; color: #ffffff; font-size: 22px; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .greeting { margin: 0 0 10px 0; font-size: 18px; color: #333333; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .intro-text { margin: 0 0 20px 0; color: #555555; font-size: 14px; line-height: 1.6; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .summary-container { background-color: #f0f8f6; border-left: 4px solid #03423A; margin-bottom: 22px; }
    .summary-title { margin: 0 0 12px 0; font-size: 16px; color: #333333; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .summary-content { font-size: 14px; color: #555555; line-height: 1.6; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .info-table { background-color: #f9f9f9; width: 100%; }
    .info-row { border-bottom: 1px solid #e5e5e5; }
    .info-label { color: #666666; font-size: 14px; vertical-align: top; padding: 8px 0; width: 35%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .info-value { font-weight: 600; font-size: 14px; color: #333333; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .cta-button { display: inline-block; background-color: #03423A; color: #ffffff !important; padding: 14px 40px; border-radius: 30px; font-weight: 600; font-size: 16px; text-decoration: none !important; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; border: none; mso-padding-alt: 0; mso-text-raise: 0; }
    .footer-cell { background-color: #AFC4C4; padding: 30px 25px; text-align: center; }
    .footer-brand { margin: 0 0 10px 0; color: #03423A; font-weight: 600; font-size: 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .footer-tagline { margin: 0 0 12px 0; color: #555555; font-size: 14px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .footer-company { margin: 0 0 14px 0; color: #ffffff; font-size: 14px; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .footer-email { margin: 0 0 10px 0; }
    .footer-email a { color: #03423A; text-decoration: none; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .footer-disclaimer { margin: 12px 0 0 0; color: #555555; font-size: 11px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    @media only screen and (max-width: 600px) {
      .email-container { width: 100% !important; margin: 0 !important; }
      .header-cell, .footer-cell { padding: 20px 15px !important; }
      .content-cell { padding: 20px 15px !important; }
      .logo { width: 80px !important; }
      .header-title { font-size: 18px !important; }
      .info-table { font-size: 12px !important; }
      .info-label, .info-value { display: block !important; width: 100% !important; padding: 4px 0 !important; }
      .cta-button { display: block !important; text-align: center !important; margin: 0 auto !important; }
    }
    @media (prefers-color-scheme: dark) {
      .email-container { background-color: #ffffff !important; }
      .greeting { color: #333333 !important; }
      .intro-text { color: #555555 !important; }
      .summary-container { background-color: #f0f8f6 !important; }
      .summary-title { color: #333333 !important; }
      .info-table { background-color: #f9f9f9 !important; }
      .info-value { color: #333333 !important; }
      .info-label { color: #666666 !important; }
    }
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: #f7f7f7;">
  <table role="presentation" class="email-wrapper" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #f7f7f7; padding: 20px 0;">
    <tr>
      <td align="center" valign="top">
        <table role="presentation" class="email-container" cellpadding="0" cellspacing="0" border="0" style="width: 600px; max-width: 600px; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.08);">
          <tr>
            <td class="header-cell" style="background-color: #AFC4C4; background-image: linear-gradient(135deg, #AFC4C4 0%, #03423A 100%); padding: 25px 20px; text-align: center;">
              <h1 class="header-title" style="margin: 12px 0 0 0; color: #ffffff; font-size: 22px; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">&#128222; Neuer Kundenanruf</h1>
            </td>
          </tr>
          <tr>
            <td class="content-cell" style="padding: 30px 25px;">
              <h2 class="greeting" style="margin: 0 0 10px 0; font-size: 18px; color: #333333; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">Guten Tag @@CLIENTNAME@@,</h2>
              <p class="intro-text" style="margin: 0 0 20px 0; color: #555555; font-size: 14px; line-height: 1.6; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">
                Kiki hat soeben einen Kundenanruf erfolgreich bearbeitet. Hier finden Sie eine detaillierte Zusammenfassung.
              </p>
              <table role="presentation" class="summary-container" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #f0f8f6; border-left: 4px solid #03423A; margin-bottom: 22px;">
                <tr>
                  <td style="padding: 20px;">
                    <h3 class="summary-title" style="margin: 0 0 12px 0; font-size: 16px; color: #333333; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">Zusammenfassung</h3>
                    <div class="summary-content">@@SUMMARY@@</div>
                  </td>
                </tr>
              </table>
              <table role="presentation" class="info-table" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #f9f9f9;">
                <tr>
                  <td style="padding: 20px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                      <tr class="info-row" style="border-bottom: 1px solid #e5e5e5;">
                        <td class="info-label" style="color: #666666; font-size: 14px; vertical-align: top; padding: 8px 0; width: 35%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">&#128100; Kundenname:</td>
                        <td class="info-value" style="font-weight: 600; font-size: 14px; color: #333333; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">@@CUSTOMERNAME@@</td>
                      </tr>
                      <tr class="info-row" style="border-bottom: 1px solid #e5e5e5;">
                        <td class="info-label" style="color: #666666; font-size: 14px; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">&#127968; Adresse:</td>
                        <td class="info-value" style="font-weight: 600; font-size: 14px; color: #333333; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">@@ADDRESS@@</td>
                      </tr>
                      <tr class="info-row" style="border-bottom: 1px solid #e5e5e5;">
                        <td class="info-label" style="color: #666666; font-size: 14px; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">&#128238; PLZ:</td>
                        <td class="info-value" style="font-weight: 600; font-size: 14px; color: #333333; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">@@POSTAL@@</td>
                      </tr>
                      <tr class="info-row" style="border-bottom: 1px solid #e5e5e5;">
                        <td class="info-label" style="color: #666666; font-size: 14px; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">&#128241; Telefonnummer:</td>
                        <td class="info-value" style="font-weight: 600; font-size: 14px; color: #03423A; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">
                          <a href="tel:@@PHONE@@" style="color: #03423A; text-decoration: none; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">@@PHONE@@</a>
                        </td>
                      </tr>
                      <tr class="info-row" style="border-bottom: 1px solid #e5e5e5;">
                        <td class="info-label" style="color: #666666; font-size: 14px; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">&#9200; Anrufzeit:</td>
                        <td class="info-value" style="font-weight: 600; font-size: 14px; color: #333333; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">@@TIMESTAMP@@</td>
                      </tr>
                      <tr>
                        <td class="info-label" style="color: #666666; font-size: 14px; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">&#10145;&#65039; Nächster Schritt:</td>
                        <td class="info-value" style="font-weight: 600; font-size: 14px; color: #333333; vertical-align: top; padding: 8px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">@@NEXTACTION@@</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top: 20px;">
                <tr>
                  <td align="center" style="padding: 20px 0 0 0;">
                    <!--[if mso]>
                    <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="@@DASHBOARD@@" style="height:50px;v-text-anchor:middle;width:280px;" arcsize="60%" strokecolor="#03423A" fillcolor="#03423A">
                      <w:anchorlock/>
                      <center style="color:#ffffff;font-family:'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;font-size:16px;font-weight:600;">Dashboard &amp; Details ansehen</center>
                    </v:roundrect>
                    <![endif]-->
                    <!--[if !mso]><!-->
                    <a href="@@DASHBOARD@@" target="_blank" class="cta-button" style="display: inline-block; background-color: #03423A; color: #ffffff; padding: 14px 40px; border-radius: 30px; font-weight: 600; font-size: 16px; text-decoration: none; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">Dashboard &amp; Details ansehen</a>
                    <!--<![endif]-->
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td class="footer-cell" style="background-color: #AFC4C4; padding: 30px 25px; text-align: center;">
              <p class="footer-brand" style="margin: 0 0 10px 0; color: #03423A; font-weight: 600; font-size: 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">Heykiki</p>
              <p class="footer-tagline" style="margin: 0 0 12px 0; color: #555555; font-size: 14px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">Die smarte KI-Telefonistin für Handwerksbetriebe</p>
              <p class="footer-company" style="margin: 0 0 14px 0; color: #ffffff; font-size: 14px; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">Kiki-Chat GmbH</p>
              <p class="footer-email" style="margin: 0 0 10px 0;">
                <a href="mailto:info@kikichat.de" style="color: #03423A; text-decoration: none; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">info@kikichat.de</a>
              </p>
              <p class="footer-disclaimer" style="margin: 12px 0 0 0; color: #555555; font-size: 11px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">Diese E-Mail wurde automatisch generiert. Bei Fragen wenden Sie sich bitte an unser Support-Team.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
