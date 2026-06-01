"""Shared branded email shell for all CRM-sent emails (Invoice, KVA, Test, …).

Brand/style is HeyKiki's canonical template (ported from the n8n post-call
reference): sage→green gradient header, 600px container, 8px radius, Kiki-Chat
footer, Outlook/MSO + responsive + dark-mode. Differences from the reference:
  * the header text is the SENDING COMPANY's name (the org/account using the
    CRM to email its own customers) — not a fixed title,
  * NO "Dashboard & Details" CTA,
  * NO post-call info-table — the body is the per-type message (e.g. the
    client's customizable Rechnungs-/KVA-E-Mail text from E-Mail-Vorlagen).

Usage: build the per-type subject + message (placeholders already substituted by
the caller), then ``render_email(company_name=org_name, body_text=message)`` and
send via email_send.send_email(reply_to=<org email>, attachments=[pdf?]).
"""
from __future__ import annotations

import html as _html
import re


def message_to_html(text: str | None) -> str:
    """Convert a client-authored plain-text message (with newlines) into styled
    HTML paragraphs: blank line → new <p>, single newline → <br>. HTML-escaped."""
    if not text or not str(text).strip():
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = re.split(r"\n\s*\n", text)
    para_style = (
        "margin: 0 0 14px 0; color: #555555; font-size: 14px; line-height: 1.6; "
        "font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;"
    )
    out = ""
    for block in blocks:
        lines = [_html.escape(l) for l in block.split("\n")]
        out += f'<p style="{para_style}">' + "<br>".join(lines) + "</p>\n"
    return out


def addr_line(address: dict | None) -> str | None:
    """One-line address from the org's address jsonb (street, PLZ + city)."""
    if not address:
        return None
    city = " ".join(p for p in [address.get("postal_code") or address.get("zip"), address.get("city")] if p).strip()
    line = ", ".join(p for p in [address.get("street"), city] if p)
    return line or None


_FF = "font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;"


def _footer_html(company: str, contact_email: str | None, address: str | None) -> str:
    """White-label footer = the SENDING company's own contact (name + address +
    email). NEVER HeyKiki/Kiki-Chat branding."""
    parts = [
        f'<p class="footer-brand" style="margin: 0 0 8px 0; color: #03423A; font-weight: 600; font-size: 18px; {_FF}">{company}</p>'
    ]
    if address:
        parts.append(f'<p class="footer-tagline" style="margin: 0 0 8px 0; color: #555555; font-size: 13px; {_FF}">{_html.escape(address)}</p>')
    if contact_email:
        em = _html.escape(contact_email)
        parts.append(f'<p style="margin: 0 0 8px 0;"><a href="mailto:{em}" style="color: #03423A; text-decoration: none; {_FF}">{em}</a></p>')
    parts.append(f'<p class="footer-disclaimer" style="margin: 12px 0 0 0; color: #555555; font-size: 11px; {_FF}">Diese E-Mail wurde automatisch generiert. Bei Fragen antworten Sie bitte direkt auf diese E-Mail.</p>')
    return "\n".join(parts)


def render_email(
    *, company_name: str | None, body_html: str,
    contact_email: str | None = None, address: str | None = None,
) -> str:
    """Wrap pre-rendered body HTML in the branded shell. Header + footer carry the
    SENDING company's identity (name + contact), never HeyKiki/Kiki-Chat."""
    company = _html.escape(company_name) if company_name and str(company_name).strip() else "Ihr Dienstleister"
    footer = _footer_html(company, (contact_email or "").strip() or None, (address or "").strip() or None)
    return (
        _SHELL.replace("@@COMPANY@@", company)
        .replace("@@BODY@@", body_html)
        .replace("@@FOOTER@@", footer)
    )


def render_message_email(
    *, company_name: str | None, message_text: str | None,
    contact_email: str | None = None, address: str | None = None,
) -> str:
    """Shell + a client-authored plain-text message (Invoice / KVA / Test)."""
    return render_email(
        company_name=company_name, body_html=message_to_html(message_text),
        contact_email=contact_email, address=address,
    )


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def substitute(template: str | None, **values: str) -> str:
    """Substitute ``{key}`` placeholders from ``values`` into a customer-authored
    template. Unknown ``{placeholders}`` and stray/literal braces are left
    untouched.

    Unlike ``str.format``, this NEVER raises on a template that contains a
    literal ``{`` / ``}`` or an unrecognised placeholder — a malformed template
    degrades to (mostly) literal text instead of crashing the whole send with a
    500. Known keys today: ``number`` / ``customer_name`` / ``org_name``.
    """
    if not template:
        return template or ""
    return _PLACEHOLDER_RE.sub(
        lambda m: str(values.get(m.group(1), m.group(0))), template
    )


_SHELL = r"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="de">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>@@COMPANY@@</title>
  <!--[if mso]>
  <noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript>
  <![endif]-->
  <style type="text/css">
    body, table, td, p, a, li, blockquote { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
    table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
    img { -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; }
    table { border-collapse: collapse !important; }
    .ExternalClass { width: 100%; }
    .ExternalClass, .ExternalClass p, .ExternalClass span, .ExternalClass font, .ExternalClass td, .ExternalClass div { line-height: 100%; }
    body { margin: 0 !important; padding: 0 !important; background-color: #f7f7f7 !important; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif !important; color: #333333 !important; }
    .email-container { width: 600px; max-width: 600px; background-color: #ffffff; margin: 0 auto; }
    .header-cell { background-color: #AFC4C4; background-image: linear-gradient(135deg, #AFC4C4 0%, #03423A 100%); padding: 25px 20px; text-align: center; }
    .header-title { margin: 0; color: #ffffff; font-size: 22px; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .footer-cell { background-color: #AFC4C4; padding: 30px 25px; text-align: center; }
    .footer-brand { margin: 0 0 10px 0; color: #03423A; font-weight: 600; font-size: 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .footer-tagline { margin: 0 0 12px 0; color: #555555; font-size: 14px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .footer-company { margin: 0 0 14px 0; color: #ffffff; font-size: 14px; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    .footer-disclaimer { margin: 12px 0 0 0; color: #555555; font-size: 11px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif; }
    @media only screen and (max-width: 600px) {
      .email-container { width: 100% !important; margin: 0 !important; }
      .header-cell, .footer-cell { padding: 20px 15px !important; }
      .content-cell { padding: 20px 15px !important; }
      .header-title { font-size: 18px !important; }
    }
    @media (prefers-color-scheme: dark) {
      .email-container { background-color: #ffffff !important; }
    }
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: #f7f7f7;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #f7f7f7; padding: 20px 0;">
    <tr>
      <td align="center" valign="top">
        <table role="presentation" class="email-container" cellpadding="0" cellspacing="0" border="0" style="width: 600px; max-width: 600px; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.08);">
          <tr>
            <td class="header-cell" style="background-color: #AFC4C4; background-image: linear-gradient(135deg, #AFC4C4 0%, #03423A 100%); padding: 25px 20px; text-align: center;">
              <h1 class="header-title" style="margin: 0; color: #ffffff; font-size: 22px; font-weight: 600; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, Arial, sans-serif;">@@COMPANY@@</h1>
            </td>
          </tr>
          <tr>
            <td class="content-cell" style="padding: 30px 25px;">
@@BODY@@
            </td>
          </tr>
          <tr>
            <td class="footer-cell" style="background-color: #AFC4C4; padding: 30px 25px; text-align: center;">
@@FOOTER@@
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
