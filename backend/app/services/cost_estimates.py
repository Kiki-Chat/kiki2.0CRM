"""Cost estimate (Angebot) helpers: numbering, totals, PDF."""

from datetime import datetime, timedelta
from pathlib import Path

from fpdf import FPDF

from app.db.supabase_client import get_service_client
from app.services.common import format_address, now_berlin

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

DOC_TITLES = {
    "kva": "ANGEBOT",  # KVA→Angebot product-wide (Amber's call); doc_type key stays "kva"
    "offer": "ANGEBOT",
    "order_confirmation": "AUFTRAGSBESTÄTIGUNG",
    "invoice": "RECHNUNG",
}


def gen_number(client, org_id: str, doc_type: str = "kva") -> str:
    # INV-002: scope the per-year sequence by doc-type so the numbers
    # are contiguous *per type* (AG-2026-00001, AG-2026-00002, …) instead of
    # sharing one cross-type counter (which left gaps in each type's series).
    # Angebot→AG: the former "kva" type is now branded "Angebot" → AG- Aktenzeichen.
    year = now_berlin().year
    prefix = {"kva": "AG", "offer": "ANG", "order_confirmation": "AB", "invoice": "RE"}.get(
        doc_type, "AG"
    )
    res = (
        client.table("cost_estimates")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .eq("type", doc_type)
        .gte("created_at", f"{year}-01-01")
        .execute()
    )
    return f"{prefix}-{year}-{(res.count or 0) + 1:05d}"


def insert_with_number_retry(client, org_id: str, row: dict, doc_type: str = "kva") -> dict:
    """Insert a cost_estimates row, retrying once on a unique-violation of the
    generated ``number`` (INV-002). The count-based ``gen_number`` is not atomic,
    so two near-simultaneous drafts of the same doc-type could compute the same
    number; if the DB rejects the duplicate we recompute and retry a single time.
    No DB unique constraint is assumed — if there isn't one this is simply a
    pass-through, and any non-duplicate error is re-raised unchanged."""
    try:
        return client.table("cost_estimates").insert(row).execute().data[0]
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "duplicate" in msg or "unique" in msg or "23505" in msg:
            row = {**row, "number": gen_number(client, org_id, doc_type)}
            return client.table("cost_estimates").insert(row).execute().data[0]
        raise


def _line_net(p: dict) -> float:
    if p.get("kind") not in (None, "item", "optional"):
        return 0.0
    qty = float(p.get("quantity") or 0)
    price = float(p.get("price") or 0)
    disc = float(p.get("discount_pct") or 0)
    return qty * price * (1 - disc / 100)


def compute_totals(positions: list[dict], surcharge: float, total_discount_pct: float) -> dict:
    """Net/VAT/gross. Optional items are shown but excluded from totals."""
    surcharge = float(surcharge or 0)
    factor = 1 - float(total_discount_pct or 0) / 100
    net_sum = 0.0
    vat_sum = 0.0
    for p in positions:
        if p.get("kind") not in (None, "item"):
            continue
        ln = _line_net(p)
        net_sum += ln
        vat_sum += ln * float(p.get("vat") or 0) / 100
    net = net_sum * factor + surcharge
    vat = vat_sum * factor + surcharge * 0.19
    return {"net": round(net, 2), "vat": round(vat, 2), "gross": round(net + vat, 2)}


# ─── PDF ─────────────────────────────────────────────────────────────────────
def _fmt_eur(v: float) -> str:
    s = f"{float(v or 0):,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def _fmt_de_date(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                value = datetime.strptime(value[:10], "%Y-%m-%d")
            except ValueError:
                return value
    return value.strftime("%d.%m.%Y")


class _KvaPDF(FPDF):
    legal = ""
    bank_footer: list | None = None  # invoices: [(heading, [lines]), ...]

    def footer(self) -> None:
        if self.bank_footer:
            top = self.h - 32
            col_w = 60
            for i, (head, lines) in enumerate(self.bank_footer):
                x = 15 + i * col_w
                self.set_xy(x, top)
                self.set_font("DejaVu", "B", 6.5)
                self.set_text_color(70)
                self.cell(col_w - 4, 3, head[:40])
                yy = top + 3.6
                self.set_font("DejaVu", size=6.5)
                self.set_text_color(110)
                for ln in lines:
                    self.set_xy(x, yy)
                    self.cell(col_w - 4, 3, ln[:42])
                    yy += 3
        else:
            self.set_y(-22)
            self.set_font("DejaVu", size=7)
            self.set_text_color(110)
            self.multi_cell(0, 3, self.legal, align="L")
        self.set_y(-9)
        self.set_font("DejaVu", size=7)
        self.set_text_color(110)
        self.cell(0, 4, f"Seite {self.page_no()} von {{nb}}", align="C")
        self.set_text_color(0)


def _invoice_bank_footer(org: dict) -> list[tuple[str, list[str]]]:
    bd = org.get("bank_details") or {}
    if not isinstance(bd, dict):
        bd = {}
    ti = org.get("tax_info") or {}
    if isinstance(ti, str):
        ti = {"vat_id": ti}
    bank_lines = [bd.get("account_holder") or org.get("name") or ""]
    if bd.get("iban"):
        bank_lines.append(f"IBAN: {bd['iban']}")
    if bd.get("bic"):
        bank_lines.append(f"BIC: {bd['bic']}")
    if bd.get("bank_name"):
        bank_lines.append(bd["bank_name"])
    mgmt_lines = [bd.get("managing_director") or ""]
    tax_lines = []
    if ti.get("vat_id"):
        tax_lines.append(f"USt-IdNr: {ti['vat_id']}")
    if ti.get("tax_number"):
        tax_lines.append(f"Steuernr.: {ti['tax_number']}")
    return [
        ("Bankverbindung", [ln for ln in bank_lines if ln]),
        ("Geschäftsführung", [ln for ln in mgmt_lines if ln]),
        ("Steuernummer", tax_lines),
    ]


def _render_org_logo(pdf, logo_url: str | None) -> None:
    """Top-left org-logo render for Angebot / Invoice / Angebot / AB PDFs (P1.3).
    Best-effort: any fetch failure is swallowed so the PDF still generates."""
    if not logo_url:
        return
    import os
    import tempfile
    import urllib.request
    try:
        with urllib.request.urlopen(logo_url, timeout=5) as resp:  # noqa: S310
            data = resp.read()
        # Suffix doesn't matter to fpdf2 (it sniffs the bytes), but use .png
        # as a safe default for tooling that inspects the file extension.
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(data)
            logo_path = tmp.name
        try:
            # w=40mm wide; height auto-scales by aspect. Fits cleanly above
            # the sender line (y=48) for typical landscape logos.
            pdf.image(logo_path, x=15, y=12, w=40)
        finally:
            try:
                os.unlink(logo_path)
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass  # PDF still generates without the logo


def build_pdf(org: dict, customer: dict | None, ce: dict, totals: dict) -> bytes:
    doc_type = ce.get("type") or "kva"
    title = DOC_TITLES.get(doc_type, "ANGEBOT")
    tol = ce.get("tolerance_pct", 20)
    binding = ce.get("is_binding")
    if doc_type == "kva":
        subtitle = "(verbindlich)" if binding else f"(unverbindlich, Toleranz ±{tol}%)"
    else:
        subtitle = ""

    legal = (
        f"Dieses Angebot ist gemäß § 632 Abs. 3 BGB unverbindlich. "
        f"Der tatsächliche Preis kann nach Leistungserbringung um bis zu {tol}% von der "
        "Schätzung abweichen. Bei voraussichtlicher wesentlicher Überschreitung werden "
        "wir dich unverzüglich informieren (§ 650c BGB)."
        if doc_type == "kva" and not binding
        else "Vielen Dank für dein Vertrauen."
    )
    valid_until = ce.get("valid_until")
    if valid_until:
        legal += f" Gültig bis {_fmt_de_date(valid_until)}."

    pdf = _KvaPDF(format="A4")
    pdf.add_font("DejaVu", "", str(_FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(_FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.legal = legal
    if doc_type == "invoice":
        pdf.bank_footer = _invoice_bank_footer(org)
    pdf.set_auto_page_break(auto=True, margin=34 if doc_type == "invoice" else 28)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    # ── Org logo (top-left, optional) — P1.3 ──
    # fpdf2 needs a local file path or file-like object; Supabase Storage URLs
    # are remote, so we fetch into a tempfile, render, then delete. PDF still
    # generates without the logo if the fetch fails (timeout, 404, etc.).
    _render_org_logo(pdf, org.get("logo_url"))

    org_addr = format_address(org.get("address")) or ""
    # ── Company header (right aligned) ──
    pdf.set_xy(110, 15)
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(85, 5, (org.get("name") or "")[:48], align="L", new_x="LMARGIN", new_y="NEXT")
    tax_info = org.get("tax_info") or {}
    if isinstance(tax_info, str):
        tax_info = {"vat_id": tax_info}
    vat_id = tax_info.get("vat_id")
    pdf.set_font("DejaVu", size=8)
    pdf.set_text_color(90)
    for line in [org_addr, f"Tel: {org.get('phone_number') or ''}", org.get("email") or "",
                 f"USt-IdNr: {vat_id}" if vat_id else ""]:
        if line.strip().rstrip(":"):
            pdf.set_x(110)
            pdf.cell(85, 4, line[:60], new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)

    # ── Sender line + customer address (left) ──
    pdf.set_xy(15, 48)
    pdf.set_font("DejaVu", size=7)
    pdf.set_text_color(120)
    sender = " • ".join([p for p in [org.get("name"), org_addr] if p])
    pdf.cell(120, 4, sender[:90], new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.set_xy(15, 56)
    pdf.set_font("DejaVu", "B", 10)
    cust_name = (customer or {}).get("full_name") or "Kunde auswählen..."
    pdf.cell(110, 5, cust_name[:50], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", size=9)
    cust_addr = format_address((customer or {}).get("address"))
    if cust_addr:
        pdf.set_x(15)
        pdf.multi_cell(110, 4, cust_addr[:120])

    # ── Meta block (right) ──
    pdf.set_xy(128, 56)
    if doc_type == "invoice":
        rows = [
            ("Rechnungsnr.:", ce.get("number") or "VORSCHAU"),
            ("Rechnungsdatum:", _fmt_de_date(ce.get("invoice_date") or ce.get("date") or now_berlin())),
            ("Leistungsdatum:", _fmt_de_date(ce.get("performance_date"))),
            ("Fällig am:", _fmt_de_date(ce.get("due_date"))),
            ("Kundennummer:", (customer or {}).get("customer_number") or "-"),
        ]
    else:
        nr_label = {"kva": "Angebot-Nr.:", "offer": "Angebot-Nr.:"}.get(doc_type, "Angebot-Nr.:")
        rows = [
            (nr_label, ce.get("number") or "VORSCHAU"),
            ("Datum:", _fmt_de_date(ce.get("date") or now_berlin())),
            ("Gültig bis:", _fmt_de_date(ce.get("valid_until"))),
            ("Kundennummer:", (customer or {}).get("customer_number") or "-"),
        ]
    for label, val in rows:
        pdf.set_x(128)
        pdf.set_font("DejaVu", "B", 8.5)
        pdf.cell(33, 5, label)
        pdf.set_font("DejaVu", size=8.5)
        pdf.cell(34, 5, str(val), align="R", new_x="LMARGIN", new_y="NEXT")

    # ── Title ──
    pdf.set_xy(15, 92)
    pdf.set_font("DejaVu", "B", 14)
    pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
    if subtitle:
        pdf.set_font("DejaVu", size=9)
        pdf.set_text_color(90)
        pdf.cell(0, 5, subtitle, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
    subject = ce.get("subject") or ""
    if subject:
        pdf.set_font("DejaVu", "B", 9)
        pdf.cell(0, 6, f"Zu deiner Anfrage: {subject[:70]}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    if doc_type == "invoice":
        default_intro = "Vielen Dank für deinen Auftrag. Wir berechnen dir wie folgt:"
    else:
        default_intro = f'Für deine Anfrage erstellen wir dir folgenden {title.title()}:'
    intro = ce.get("intro_text") or default_intro
    pdf.set_font("DejaVu", size=9)
    pdf.multi_cell(0, 5, intro)
    pdf.ln(2)

    # ── Positions table ──
    positions = ce.get("positions") or []
    headings = ["Pos.", "Beschreibung", "Menge", "Einheit", "Einzelpreis", "MwSt", "Gesamt"]
    widths = (10, 78, 16, 18, 26, 14, 18)
    pdf.set_font("DejaVu", size=8)
    with pdf.table(
        col_widths=widths,
        text_align=("CENTER", "LEFT", "RIGHT", "CENTER", "RIGHT", "CENTER", "RIGHT"),
        line_height=5,
    ) as table:
        table.row(headings)
        pos_no = 0
        for p in positions:
            kind = p.get("kind") or "item"
            if kind == "text":
                table.row(["", p.get("description") or "", "", "", "", "", ""])
                continue
            if kind == "subtotal":
                table.row(["", (p.get("description") or "Zwischensumme"), "", "", "", "", _fmt_eur(_line_net(p))])
                continue
            pos_no += 1
            ln = _line_net(p)
            desc = (p.get("description") or "")
            if kind == "optional":
                desc = f"[Optional] {desc}"
            table.row([
                str(pos_no), desc,
                f"{float(p.get('quantity') or 0):g}", p.get("unit") or "",
                _fmt_eur(p.get("price")), f"{float(p.get('vat') or 0):g}%",
                "-" if kind == "optional" else _fmt_eur(ln),
            ])

    # ── Totals ──
    pdf.ln(2)
    def total_row(label, value, bold=False):
        pdf.set_x(120)
        pdf.set_font("DejaVu", "B" if bold else "", 9 if not bold else 10)
        pdf.cell(45, 6, label, align="R")
        pdf.cell(30, 6, _fmt_eur(value), align="R", new_x="LMARGIN", new_y="NEXT")
    if ce.get("surcharge"):
        total_row(ce.get("surcharge_description") or "Aufschlag", ce.get("surcharge"))
    total_row("Nettobetrag:", totals["net"])
    total_row("zzgl. MwSt:", totals["vat"])
    total_row("Gesamtbetrag:", totals["gross"], bold=True)

    # ── Skonto (invoices only, DISPLAY-ONLY) — 6.1 ──
    # Per the Skonto contract: skonto NEVER reduces the amount due. Gesamtbetrag
    # above stays the amount owed; we only *display* the early-payment discount
    # and the resulting reduced figure. Guarded so Angebot/Angebot/AB and invoices
    # without a skonto% are completely unchanged.
    skonto_pct = float(ce.get("skonto_pct") or 0)
    skonto_days = ce.get("skonto_days") or 0
    show_skonto = doc_type == "invoice" and skonto_pct > 0
    if show_skonto:
        gross = float(totals["gross"] or 0)
        skonto_amt = round(gross * skonto_pct / 100, 2)
        zahlbetrag_skonto = round(gross - skonto_amt, 2)
        days_str = f"{skonto_days:g}" if isinstance(skonto_days, (int, float)) else str(skonto_days)
        total_row(f"abzgl. {skonto_pct:g}% Skonto:", skonto_amt)
        total_row(f"Zahlbetrag bei Zahlung in {days_str} Tagen:", zahlbetrag_skonto, bold=True)

    closing = ce.get("closing_text")
    if closing:
        pdf.ln(4)
        pdf.set_font("DejaVu", size=9)
        pdf.multi_cell(0, 5, closing)
    if ce.get("payment_terms"):
        pdf.ln(2)
        pdf.set_font("DejaVu", "", 8)
        pdf.set_text_color(90)
        pdf.multi_cell(0, 4, ce["payment_terms"])
        pdf.set_text_color(0)
    # One-line Skonto note near the payment terms (invoices with skonto only).
    if show_skonto:
        pdf.ln(1)
        pdf.set_font("DejaVu", "", 8)
        pdf.set_text_color(90)
        pdf.multi_cell(
            0, 4,
            f"Bei Zahlung innerhalb von {days_str} Tagen gewähren wir "
            f"{skonto_pct:g}% Skonto ({_fmt_eur(zahlbetrag_skonto)}).",
        )
        pdf.set_text_color(0)

    out = pdf.output()
    return bytes(out)


# ─── Data helpers ────────────────────────────────────────────────────────────
def fetch_org(client, org_id: str) -> dict:
    rows = (
        client.table("organizations")
        .select("name, address, phone_number, email, tax_info, bank_details, logo_url")
        .eq("id", org_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else {}


def fetch_customer(client, org_id: str, customer_id: str | None) -> dict | None:
    if not customer_id:
        return None
    rows = (
        client.table("customers")
        .select("full_name, address, customer_number, email, vat_id")
        .eq("org_id", org_id).eq("id", customer_id).limit(1).execute().data
    )
    return rows[0] if rows else None


def valid_until_for(validity_days: int) -> str:
    return (now_berlin().date() + timedelta(days=int(validity_days or 30))).isoformat()


# ─── hk_draftCostEstimate (the 11th tool) ────────────────────────────────────
def _normalize_position(p: dict) -> dict:
    """Coerce a raw agent-supplied position dict into the shape compute_totals /
    build_pdf expect. Tolerant: missing keys fall back to the same defaults the
    CostEstimatePosition pydantic model uses."""
    p = p if isinstance(p, dict) else {}
    return {
        "kind": p.get("kind") or "item",
        "description": p.get("description"),
        "quantity": p.get("quantity", 1),
        "unit": p.get("unit") or "Stk",
        "price": p.get("price", 0),
        "vat": p.get("vat", 19),
        "discount_pct": p.get("discount_pct", 0),
        "is_labor": bool(p.get("is_labor", False)),
    }


def _ce_pdf_view(row: dict) -> dict:
    """Minimal cost_estimates row → build_pdf 'ce' dict (mirrors the route's
    _ce_for_pdf, kept here so the service can render without importing the route)."""
    return {
        "type": row.get("type") or "kva",
        "number": row.get("number"),
        "subject": row.get("subject"),
        "is_binding": row.get("is_binding"),
        "tolerance_pct": row.get("tolerance_pct", 20),
        "valid_until": row.get("valid_until"),
        "date": row.get("created_at"),
        "positions": row.get("line_items") or [],
        "intro_text": row.get("intro_text"),
        "closing_text": row.get("closing_text"),
        "payment_terms": row.get("payment_terms"),
        "surcharge": row.get("surcharge") or 0,
        "surcharge_description": row.get("surcharge_description"),
        "total_discount_pct": row.get("total_discount_pct") or 0,
    }


def _send_draft_kva(client, org_id: str, row: dict) -> bool:
    """Best-effort email send of a freshly-drafted Angebot (used by L3). Self-contained
    so the service doesn't import the route. Resolves the recipient from the
    customer's stored email, renders the PDF, sends a default German email, and
    stamps status='sent' + sent_at on success. Returns True iff actually sent;
    any failure (no recipient, render/send error) → returns False, leaves the row
    as a draft, and NEVER raises."""
    try:
        from app.services import email_templates
        from app.services.email_send import Attachment, send_email

        customer = fetch_customer(client, org_id, row.get("customer_id"))
        to_email = ((customer or {}).get("email") or "").strip()
        # Skip @temp.local placeholders — never a real inbox.
        if not to_email or to_email.endswith("@temp.local"):
            return False

        org = fetch_org(client, org_id)
        ce = _ce_pdf_view(row)
        totals = {
            "net": row.get("subtotal") or 0,
            "vat": row.get("vat_amount") or 0,
            "gross": row.get("total") or 0,
        }
        pdf_bytes = build_pdf(org, customer, ce, totals)

        org_name = org.get("name") or "HeyKiki"
        number = row.get("number") or "—"
        cust_name = (customer or {}).get("full_name") or ""
        subject = f"Angebot {number} von {org_name}"
        greeting = f"Sehr geehrte/r {cust_name}," if cust_name else "Guten Tag,"
        body_text = (
            f"{greeting}\n\n"
            f"anbei senden wir dir das Angebot {number}.\n\n"
            f"Bei Rückfragen stehen wir dir gerne zur Verfügung.\n\n"
            f"Mit freundlichen Grüßen\n{org_name}"
        )
        body_html = email_templates.render_message_email(
            company_name=org_name, message_text=body_text,
            contact_email=org.get("email"),
            address=email_templates.addr_line(org.get("address")),
        )
        filename = f"{number}.pdf"  # number already carries its type prefix (AG-/ANG-/RE-)
        send_email(
            org_id=org_id,
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            attachments=[Attachment(filename=filename, content=pdf_bytes)],
            reply_to=(org.get("email") or None),
        )
        # Only stamp 'sent' after a successful send.
        client.table("cost_estimates").update(
            {"status": "sent", "sent_at": datetime.now().astimezone().isoformat()}
        ).eq("org_id", org_id).eq("id", row["id"]).execute()
        return True
    except Exception:  # noqa: BLE001 — sending is best-effort; leave as draft on failure
        return False


def draft_cost_estimate(org_id: str, payload) -> dict:
    """hk_draftCostEstimate handler: create a DRAFT Angebot from the
    agent's collected positions/subject, gated on the org's Angebot-Automatisierung
    toggle.

    - Angebot-Automatisierung off → no-op, returns success=False with a German note.
    - Otherwise: build + insert a draft (type='kva', status='draft'), linking the
      customer + inquiry the agent passed.
    - At autonomy level 3: best-effort email-send via the existing send path; if
      it fails, the Angebot stays a draft (no raise). At L1/L2 it stays a draft for
      the team to review.

    Returns {success, id, number, status, message}."""
    client = get_service_client()

    cfg = (
        client.table("agent_configs")
        .select("kva_enabled, kva_level, kva_automation_enabled, kiki_level")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    cfg_row = cfg[0] if cfg else {}
    # Per-capability toggle, with a legacy fallback to the old automation flag.
    kva_on = cfg_row.get("kva_enabled")
    if kva_on is None:
        kva_on = cfg_row.get("kva_automation_enabled")
    if not kva_on:
        return {"success": False, "message": "Angebot-Erstellung ist nicht aktiviert."}
    # Amber's ruling 2026-06-12 (closes audit item AUT-05): L1 = OFF for EVERY
    # capability, server-side. Projects/invoices/appointments already hard-block
    # at level 1 — Angebot was the only one relying on the prompt alone, so a tool
    # call at L1+enabled would still have created a draft.
    try:
        kva_level = int(cfg_row.get("kva_level") or cfg_row.get("kiki_level") or 2)
    except (TypeError, ValueError):
        kva_level = 2
    if kva_level <= 1:
        return {"success": False, "message": "Angebot-Erstellung ist nicht aktiviert."}

    positions = [_normalize_position(p) for p in (payload.positions or [])]
    totals = compute_totals(positions, 0, 0)
    row = {
        "org_id": org_id,
        "customer_id": payload.customer_id,
        "inquiry_id": payload.inquiry_id,
        "type": "kva",
        "status": "draft",
        "subject": payload.subject,
        "line_items": positions,
        # Free-text notes the agent gathered land in intro_text so they surface
        # on the PDF + in the team's review view.
        "intro_text": payload.notes,
        "validity_days": 30,
        "valid_until": valid_until_for(30),
        "subtotal": totals["net"],
        "vat_amount": totals["vat"],
        "total": totals["gross"],
        "number": gen_number(client, org_id, "kva"),
    }
    created = insert_with_number_retry(client, org_id, row, "kva")

    # Angebot level 3: try to send immediately; otherwise leave as a draft.
    level = cfg_row.get("kva_level")
    if level is None:
        level = cfg_row.get("kiki_level")
    try:
        level = int(level) if level is not None else 2
    except (TypeError, ValueError):
        level = 2

    sent = False
    if level == 3:
        sent = _send_draft_kva(client, org_id, created)

    status = "sent" if sent else "draft"
    message = "Angebot wurde erstellt."
    if sent:
        message += " und versendet."
    return {
        "success": True,
        "id": created["id"],
        "number": created.get("number"),
        "status": status,
        "message": message,
    }


def _kva_level(cfg_row: dict) -> int:
    """KVA autonomy level (1/2/3), legacy kiki_level fallback, default 2."""
    try:
        return int(cfg_row.get("kva_level") or cfg_row.get("kiki_level") or 2)
    except (TypeError, ValueError):
        return 2


def _fetch_kva_to_send(
    client, org_id: str, *, cost_estimate_id=None, number=None, customer_id=None
) -> dict | None:
    """Resolve which KVA to (re)send: by id, then by number, then the customer's
    most recent KVA. Always org-scoped and type='kva'."""
    base = client.table("cost_estimates").select("*").eq("org_id", org_id).eq("type", "kva")
    if cost_estimate_id:
        rows = base.eq("id", cost_estimate_id).limit(1).execute().data
    elif number:
        rows = base.eq("number", number).limit(1).execute().data
    elif customer_id:
        rows = (
            base.eq("customer_id", customer_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
    else:
        rows = []
    return rows[0] if rows else None


def send_cost_estimate(org_id: str, payload) -> dict:
    """hk_sendKVA handler: email an EXISTING Kostenvoranschlag to the customer.

    GATED to the fully-automatic KVA autonomy level (L3) — Amber's decision
    2026-06-22: only a level-3 org sends KVAs straight to the customer; at L1/L2
    the team reviews and sends, so the tool declines with a German note the agent
    can speak. Resolves the KVA by costEstimateId → number → the customer's most
    recent KVA, then reuses the existing _send_draft_kva send path (PDF render +
    email + status='sent' stamp). Never raises.

    Returns {success, message[, id, number, status, needsEmail]}."""
    client = get_service_client()
    cfg = (
        client.table("agent_configs")
        .select("kva_enabled, kva_level, kva_automation_enabled, kiki_level")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
        .data
    )
    cfg_row = cfg[0] if cfg else {}
    kva_on = cfg_row.get("kva_enabled")
    if kva_on is None:
        kva_on = cfg_row.get("kva_automation_enabled")
    # Only the fully-automatic level may send directly; otherwise the team handles it.
    if not kva_on or _kva_level(cfg_row) != 3:
        return {
            "success": False,
            "message": "Der Kostenvoranschlag wird vom Team geprüft und per E-Mail versendet.",
        }

    row = _fetch_kva_to_send(
        client,
        org_id,
        cost_estimate_id=payload.cost_estimate_id,
        number=payload.number,
        customer_id=payload.customer_id,
    )
    if not row:
        return {
            "success": False,
            "message": "Ich konnte den Kostenvoranschlag nicht finden — das Team kümmert sich darum.",
        }

    # A real recipient email is required (placeholder @temp.local never gets mail).
    customer = fetch_customer(client, org_id, row.get("customer_id"))
    to_email = ((customer or {}).get("email") or "").strip()
    if not to_email or to_email.endswith("@temp.local"):
        return {
            "success": False,
            "needsEmail": True,
            "message": "Mir fehlt noch Ihre E-Mail-Adresse, an die ich den Kostenvoranschlag senden kann.",
        }

    sent = _send_draft_kva(client, org_id, row)
    if sent:
        return {
            "success": True,
            "id": row["id"],
            "number": row.get("number"),
            "status": "sent",
            "message": "Der Kostenvoranschlag wurde per E-Mail versendet.",
        }
    return {
        "success": False,
        "message": "Das Versenden hat gerade nicht geklappt — das Team kümmert sich darum.",
    }
