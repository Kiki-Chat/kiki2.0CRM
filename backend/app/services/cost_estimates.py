"""Cost estimate (Kostenvoranschlag) helpers: numbering, totals, PDF."""

from datetime import datetime, timedelta
from pathlib import Path

from fpdf import FPDF

from app.db.supabase_client import get_service_client
from app.services.common import format_address, now_berlin

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

DOC_TITLES = {"kva": "KOSTENVORANSCHLAG", "offer": "ANGEBOT", "invoice": "RECHNUNG"}


def gen_number(client, org_id: str, doc_type: str = "kva") -> str:
    year = now_berlin().year
    prefix = {"kva": "KVA", "offer": "ANG", "invoice": "RE"}.get(doc_type, "KVA")
    res = (
        client.table("cost_estimates")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .gte("created_at", f"{year}-01-01")
        .execute()
    )
    return f"{prefix}-{year}-{(res.count or 0) + 1:05d}"


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

    def footer(self) -> None:
        self.set_y(-22)
        self.set_font("DejaVu", size=7)
        self.set_text_color(110)
        self.multi_cell(0, 3, self.legal, align="L")
        self.set_y(-9)
        self.cell(0, 4, f"Seite {self.page_no()} von {{nb}}", align="C")
        self.set_text_color(0)


def build_pdf(org: dict, customer: dict | None, ce: dict, totals: dict) -> bytes:
    doc_type = ce.get("type") or "kva"
    title = DOC_TITLES.get(doc_type, "KOSTENVORANSCHLAG")
    tol = ce.get("tolerance_pct", 20)
    binding = ce.get("is_binding")
    if doc_type == "kva":
        subtitle = "(verbindlich)" if binding else f"(unverbindlich, Toleranz ±{tol}%)"
    else:
        subtitle = ""

    legal = (
        f"Dieser Kostenvoranschlag ist gemäß § 632 Abs. 3 BGB unverbindlich. "
        f"Der tatsächliche Preis kann nach Leistungserbringung um bis zu {tol}% von der "
        "Schätzung abweichen. Bei voraussichtlicher wesentlicher Überschreitung werden "
        "wir Sie unverzüglich informieren (§ 650c BGB)."
        if doc_type == "kva" and not binding
        else "Vielen Dank für Ihr Vertrauen."
    )
    valid_until = ce.get("valid_until")
    if valid_until:
        legal += f" Gültig bis {_fmt_de_date(valid_until)}."

    pdf = _KvaPDF(format="A4")
    pdf.add_font("DejaVu", "", str(_FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(_FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.legal = legal
    pdf.set_auto_page_break(auto=True, margin=28)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    org_addr = format_address(org.get("address")) or ""
    # ── Company header (right aligned) ──
    pdf.set_xy(110, 15)
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(85, 5, (org.get("name") or "")[:48], align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", size=8)
    pdf.set_text_color(90)
    for line in [org_addr, f"Tel: {org.get('phone_number') or ''}", org.get("email") or "",
                 f"USt-IdNr: {org.get('tax_info')}" if org.get("tax_info") else ""]:
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
    nr_label = {"kva": "KVA-Nr.:", "offer": "Angebot-Nr.:", "invoice": "Rechnung-Nr.:"}.get(
        doc_type, "KVA-Nr.:"
    )
    pdf.set_xy(128, 56)
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
        pdf.cell(0, 6, f"Zu Ihrer Anfrage: {subject[:70]}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    intro = ce.get("intro_text") or (
        f'Für Ihre Anfrage erstellen wir Ihnen folgenden {title.title()}:'
    )
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

    out = pdf.output()
    return bytes(out)


# ─── Data helpers ────────────────────────────────────────────────────────────
def fetch_org(client, org_id: str) -> dict:
    rows = (
        client.table("organizations")
        .select("name, address, phone_number, email, tax_info, logo_url")
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
        .select("full_name, address, customer_number, email")
        .eq("org_id", org_id).eq("id", customer_id).limit(1).execute().data
    )
    return rows[0] if rows else None


def valid_until_for(validity_days: int) -> str:
    return (now_berlin().date() + timedelta(days=int(validity_days or 30))).isoformat()
