"""Invoice (Rechnung) helpers: numbering and date math.

Totals and the PDF renderer are shared with the cost-estimate module
(`app/services/cost_estimates.py`); `build_pdf` renders a RECHNUNG when the
document dict carries `type="invoice"`.
"""

from datetime import date, timedelta

from app.services.common import now_berlin


def gen_invoice_number(client, org_id: str) -> str:
    year = now_berlin().year
    res = (
        client.table("invoices")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .gte("created_at", f"{year}-01-01")
        .execute()
    )
    return f"RE-{year}-{(res.count or 0) + 1:05d}"


def add_days(iso_date: str | None, days) -> str | None:
    """Add `days` to an ISO date string (used to derive the due date)."""
    if not iso_date:
        return None
    try:
        d = date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return None
    return (d + timedelta(days=int(days or 0))).isoformat()


def today_iso() -> str:
    return now_berlin().date().isoformat()
