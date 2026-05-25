from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

BERLIN = ZoneInfo("Europe/Berlin")


# ─── Date / format helpers (Berlin-local month boundaries) ───────────────────
def _now() -> datetime:
    return datetime.now(BERLIN)


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(dt: datetime, n: int) -> datetime:
    m = dt.month - 1 + n
    return dt.replace(year=dt.year + m // 12, month=m % 12 + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _prev_month_start(dt: datetime) -> datetime:
    return _add_months(_month_start(dt), -1)


def _days_in_month(dt: datetime) -> int:
    return (_add_months(_month_start(dt), 1) - timedelta(days=1)).day


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    s = str(ts).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(BERLIN)


def _eur(v) -> str:
    return f"{float(v or 0):.2f} €"


def _count(client, table: str, org_id: str, **filters) -> int:
    q = client.table(table).select("id", count="exact").eq("org_id", org_id)
    for key, value in filters.items():
        q = q.eq(key, value)
    return q.execute().count or 0


def _customer_names(client, org_id: str, ids: list) -> dict:
    ids = list({i for i in ids if i})
    if not ids:
        return {}
    rows = client.table("customers").select("id, full_name").eq("org_id", org_id).in_("id", ids).execute().data or []
    return {r["id"]: r.get("full_name") for r in rows}


def _fetch_calls(client, org_id: str, since_iso: str) -> list:
    return (
        client.table("calls")
        .select("id, customer_id, direction, started_at, duration_seconds, status, created_at")
        .eq("org_id", org_id)
        .gte("created_at", since_iso)
        .execute()
        .data
        or []
    )


def _split_calls(rows: list, cur_start: datetime, prev_start: datetime):
    cur, prev = [], []
    for r in rows:
        eff = _parse(r.get("started_at") or r.get("created_at"))
        if not eff:
            continue
        if eff >= cur_start:
            cur.append((r, eff))
        elif eff >= prev_start:
            prev.append((r, eff))
    return cur, prev


# ─── Overview (existing) ─────────────────────────────────────────────────────
@router.get("/overview")
async def overview(user: CurrentUser = Depends(require_org)) -> dict:
    client = get_service_client()
    org_id = user.org_id

    open_inquiries = _count(client, "inquiries", org_id, status="open")
    total_customers = _count(client, "customers", org_id)

    appts_res = (
        client.table("appointments")
        .select("id, title, scheduled_at, status, customer_id")
        .eq("org_id", org_id)
        .gte("scheduled_at", datetime.now(timezone.utc).isoformat())
        .order("scheduled_at")
        .limit(5)
        .execute()
    )
    upcoming = appts_res.data or []

    tasks_res = (
        client.table("inquiries")
        .select("id, title, type, status, created_at, customer_id")
        .eq("org_id", org_id)
        .eq("status", "open")
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    open_tasks = tasks_res.data or []

    return {
        "kpis": {
            "open_inquiries": open_inquiries,
            "total_customers": total_customers,
            "upcoming_appointments": len(upcoming),
        },
        "open_tasks": open_tasks,
        "upcoming_appointments": upcoming,
    }


# ─── Anrufe ──────────────────────────────────────────────────────────────────
def _anrufe(org_id: str) -> dict:
    client = get_service_client()
    now = _now()
    cur_start, prev_start = _month_start(now), _prev_month_start(now)
    cur, prev = _split_calls(_fetch_calls(client, org_id, prev_start.isoformat()), cur_start, prev_start)

    def stats(items):
        total = len(items)
        answered = sum(1 for r, _ in items if r.get("status") == "completed")
        outbound = sum(1 for r, _ in items if r.get("direction") == "outbound")
        durs = [r.get("duration_seconds") or 0 for r, _ in items if r.get("status") == "completed"]
        avg = round(sum(durs) / len(durs)) if durs else 0
        return total, answered, outbound, avg

    t, a, o, avg = stats(cur)
    pt, pa, po, pavg = stats(prev)

    daily = defaultdict(int)
    for _, eff in cur:
        daily[eff.day] += 1
    daily_volume = [{"day": d, "count": daily.get(d, 0)} for d in range(1, _days_in_month(now) + 1)]

    inbound = sum(1 for r, _ in cur if r.get("direction") == "inbound")
    missed = sum(1 for r, _ in cur if r.get("status") == "missed")

    recent_sorted = sorted(cur, key=lambda x: x[1], reverse=True)[:5]
    names = _customer_names(client, org_id, [r.get("customer_id") for r, _ in recent_sorted])
    recent = [
        {
            "id": r["id"],
            "customer_name": names.get(r.get("customer_id")),
            "started_at": r.get("started_at") or r.get("created_at"),
            "duration_seconds": r.get("duration_seconds") or 0,
            "direction": r.get("direction"),
            "status": r.get("status"),
        }
        for r, _ in recent_sorted
    ]

    return {
        "kpis": {
            "total_calls": t, "answered": a, "answer_rate": round(a / t * 100) if t else 0,
            "avg_duration_seconds": avg, "outbound": o,
            "prev_total_calls": pt, "prev_answered": pa,
            "prev_avg_duration_seconds": pavg, "prev_outbound": po,
        },
        "daily_volume": daily_volume,
        "breakdown": {"inbound": inbound, "outbound": o, "missed": missed},
        "recent_calls": recent,
    }


@router.get("/anrufe")
async def anrufe(user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_anrufe, user.org_id)


# ─── Finanzen ────────────────────────────────────────────────────────────────
def _finanzen(org_id: str) -> dict:
    client = get_service_client()
    now = _now()
    cur_start = _month_start(now)
    quarter_start = _add_months(cur_start, -2)
    six_start = _add_months(cur_start, -5)

    invoices = (
        client.table("invoices")
        .select("id, number, total, status, due_date, paid_at, created_at, customer_id")
        .eq("org_id", org_id).execute().data or []
    )
    estimates = (
        client.table("cost_estimates")
        .select("id, total, status, created_at").eq("org_id", org_id).execute().data or []
    )

    def inv_dt(i):
        return _parse(i.get("created_at"))

    umsatz_month = sum(float(i.get("total") or 0) for i in invoices
                       if i.get("status") != "cancelled" and (inv_dt(i) or now) >= cur_start)
    open_inv = [i for i in invoices if i.get("status") in ("sent", "overdue")]
    paid_month = sum(float(i.get("total") or 0) for i in invoices
                     if i.get("status") == "paid" and (_parse(i.get("paid_at")) or datetime.min.replace(tzinfo=BERLIN)) >= cur_start)
    kvas_pending = [e for e in estimates if e.get("status") == "sent"]

    # revenue series — last 6 months by paid_at
    months = [_add_months(cur_start, -n) for n in range(5, -1, -1)]
    rev_by_month = {m.strftime("%Y-%m"): 0.0 for m in months}
    for i in invoices:
        if i.get("status") != "paid":
            continue
        pd = _parse(i.get("paid_at")) or inv_dt(i)
        if pd and pd >= six_start:
            key = pd.strftime("%Y-%m")
            if key in rev_by_month:
                rev_by_month[key] += float(i.get("total") or 0)
    revenue_series = [{"month": m.strftime("%Y-%m"), "label": m.strftime("%b"), "revenue": round(rev_by_month[m.strftime("%Y-%m")], 2)} for m in months]

    # top customers this quarter (by invoice total)
    by_cust = defaultdict(float)
    for i in invoices:
        d = inv_dt(i)
        if d and d >= quarter_start and i.get("status") != "cancelled" and i.get("customer_id"):
            by_cust[i["customer_id"]] += float(i.get("total") or 0)
    top_ids = sorted(by_cust, key=lambda c: by_cust[c], reverse=True)[:5]
    names = _customer_names(client, org_id, top_ids)
    top_customers = [{"customer_id": c, "customer_name": names.get(c), "amount": round(by_cust[c], 2)} for c in top_ids]

    recent_sorted = sorted(invoices, key=lambda i: i.get("created_at") or "", reverse=True)[:5]
    rnames = _customer_names(client, org_id, [i.get("customer_id") for i in recent_sorted])
    recent_invoices = [
        {
            "id": i["id"], "number": i.get("number"), "customer_name": rnames.get(i.get("customer_id")),
            "status": i.get("status"), "total": float(i.get("total") or 0), "due_date": i.get("due_date"),
        }
        for i in recent_sorted
    ]

    return {
        "kpis": {
            "umsatz_month": round(umsatz_month, 2),
            "open_invoices_count": len(open_inv),
            "open_invoices_sum": round(sum(float(i.get("total") or 0) for i in open_inv), 2),
            "kvas_pending_count": len(kvas_pending),
            "kvas_pending_sum": round(sum(float(e.get("total") or 0) for e in kvas_pending), 2),
            "paid_month": round(paid_month, 2),
        },
        "revenue_series": revenue_series,
        "top_customers": top_customers,
        "recent_invoices": recent_invoices,
    }


@router.get("/finanzen")
async def finanzen(user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_finanzen, user.org_id)


# ─── KI-Nutzung (AI quota transparency; renamed from Zeiterfassung) ───────────
def _ki_nutzung(org_id: str) -> dict:
    client = get_service_client()
    now = _now()
    cur_start, prev_start = _month_start(now), _prev_month_start(now)

    org = client.table("organizations").select("ai_minutes_quota").eq("id", org_id).limit(1).execute().data
    quota = (org[0].get("ai_minutes_quota") if org else None) or 0

    cur, prev = _split_calls(_fetch_calls(client, org_id, prev_start.isoformat()), cur_start, prev_start)

    def minutes(items):
        return round(sum((r.get("duration_seconds") or 0) for r, _ in items) / 60)

    def avg_dur(items):
        durs = [r.get("duration_seconds") or 0 for r, _ in items if r.get("status") == "completed"]
        return round(sum(durs) / len(durs)) if durs else 0

    minutes_used = minutes(cur)
    calls_count = len(cur)

    daily_min = defaultdict(float)
    daily_calls = defaultdict(int)
    for r, eff in cur:
        daily_min[eff.day] += (r.get("duration_seconds") or 0) / 60
        daily_calls[eff.day] += 1
    daily_consumption = [
        {"day": d, "minutes": round(daily_min.get(d, 0)), "calls": daily_calls.get(d, 0)}
        for d in range(1, _days_in_month(now) + 1)
    ]

    days_elapsed = now.day
    run_rate = minutes_used / days_elapsed if days_elapsed else 0
    if quota and minutes_used > quota:
        est_days = 0  # exhausted/over
    elif run_rate > 0 and quota:
        est_days = max(0, round((quota - minutes_used) / run_rate))
    else:
        est_days = None

    by_cust = defaultdict(lambda: [0.0, 0])
    for r, _ in cur:
        cid = r.get("customer_id")
        if cid:
            by_cust[cid][0] += (r.get("duration_seconds") or 0) / 60
            by_cust[cid][1] += 1
    top_ids = sorted(by_cust, key=lambda c: by_cust[c][0], reverse=True)[:5]
    names = _customer_names(client, org_id, top_ids)
    top_callers = [
        {"customer_id": c, "customer_name": names.get(c), "total_minutes": round(by_cust[c][0]), "call_count": by_cust[c][1]}
        for c in top_ids
    ]

    by_hour_c = defaultdict(int)
    by_hour_m = defaultdict(float)
    for r, eff in cur:
        by_hour_c[eff.hour] += 1
        by_hour_m[eff.hour] += (r.get("duration_seconds") or 0) / 60
    calls_by_hour = [{"hour": h, "count": by_hour_c.get(h, 0), "minutes": round(by_hour_m.get(h, 0))} for h in range(24)]

    return {
        "kpis": {
            "minutes_used": minutes_used,
            "minutes_quota": quota,
            "calls_count": calls_count,
            "avg_duration_seconds": avg_dur(cur),
            "estimated_days_remaining": est_days,
            "over_quota": bool(quota and minutes_used > quota),
            "previous_month_minutes": minutes(prev),
            "previous_month_calls": len(prev),
            "previous_month_avg_duration": avg_dur(prev),
        },
        "daily_consumption": daily_consumption,
        "top_callers": top_callers,
        "calls_by_hour": calls_by_hour,
    }


@router.get("/ki-nutzung")
async def ki_nutzung(user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_ki_nutzung, user.org_id)


# ─── KI-Insights ─────────────────────────────────────────────────────────────
def _ai_insights(org_id: str) -> dict:
    client = get_service_client()
    now = _now()
    today = now.date()

    cfg = (
        client.table("agent_configs")
        .select("proactive_ai_enabled, ai_suggestions_enabled, kva_followup_days, payment_reminder_days")
        .eq("org_id", org_id).limit(1).execute().data
    )
    cfg = cfg[0] if cfg else {}
    enabled = bool(cfg.get("ai_suggestions_enabled", True)) and bool(cfg.get("proactive_ai_enabled", True))
    kva_days = cfg.get("kva_followup_days") or 7
    pay_days = cfg.get("payment_reminder_days") or 14

    actions = client.table("ai_suggestion_actions").select("suggestion_key, action, until_date").eq("org_id", org_id).execute().data or []
    suppressed = set()
    for a in actions:
        if a["action"] == "done":
            suppressed.add(a["suggestion_key"])
        elif a["action"] == "snooze":
            until = _parse(a.get("until_date"))
            if until and until > now:
                suppressed.add(a["suggestion_key"])

    suggestions = []
    cust_ids = []

    ce = client.table("cost_estimates").select("id, number, total, sent_at, customer_id").eq("org_id", org_id).eq("status", "sent").execute().data or []
    for e in ce:
        sent = _parse(e.get("sent_at"))
        if sent and (now - sent).days >= kva_days:
            key = f"kva_followup:{e['id']}"
            if key in suppressed:
                continue
            cust_ids.append(e.get("customer_id"))
            suggestions.append({
                "id": key, "category": "kva_followup",
                "title": f"{e.get('number') or 'KVA'} wurde vor {(now - sent).days} Tagen versendet, noch keine Antwort",
                "subtitle": f"Betrag: {_eur(e.get('total'))}",
                "customer_id": e.get("customer_id"), "created_at": e.get("sent_at"),
            })

    inv = client.table("invoices").select("id, number, total, due_date, customer_id").eq("org_id", org_id).in_("status", ["sent", "overdue"]).execute().data or []
    for i in inv:
        if not i.get("due_date"):
            continue
        try:
            dd = date.fromisoformat(str(i["due_date"]))
        except ValueError:
            continue
        if (today - dd).days >= pay_days:
            key = f"invoice_overdue:{i['id']}"
            if key in suppressed:
                continue
            cust_ids.append(i.get("customer_id"))
            suggestions.append({
                "id": key, "category": "invoice_overdue",
                "title": f"Rechnung {i.get('number') or ''} ist seit {(today - dd).days} Tagen überfällig",
                "subtitle": f"Betrag: {_eur(i.get('total'))}",
                "customer_id": i.get("customer_id"), "created_at": str(i.get("due_date")),
            })

    six = now - timedelta(days=182)
    custs = client.table("customers").select("id, full_name, updated_at, created_at").eq("org_id", org_id).execute().data or []
    for c in custs:
        last = _parse(c.get("updated_at") or c.get("created_at"))
        if last and last < six:
            key = f"inactive_customer:{c['id']}"
            if key in suppressed:
                continue
            suggestions.append({
                "id": key, "category": "inactive_customer",
                "title": f"{c.get('full_name') or 'Kunde'} war seit über 6 Monaten nicht aktiv",
                "subtitle": "Reaktivierung erwägen",
                "customer_id": c.get("id"), "created_at": c.get("updated_at") or c.get("created_at"),
            })

    # enrich subtitle with customer name where available
    names = _customer_names(client, org_id, cust_ids)
    for s in suggestions:
        nm = names.get(s.get("customer_id"))
        if nm and s["category"] in ("kva_followup", "invoice_overdue"):
            s["subtitle"] = f"{nm} · {s['subtitle']}"

    suggestions.sort(key=lambda s: s.get("created_at") or "", reverse=True)

    return {
        "enabled": enabled,
        "kpis": {
            "open_count": len(suggestions),
            "kva_followup_count": sum(1 for s in suggestions if s["category"] == "kva_followup"),
            "overdue_invoices_count": sum(1 for s in suggestions if s["category"] == "invoice_overdue"),
            "inactive_customers_count": sum(1 for s in suggestions if s["category"] == "inactive_customer"),
        },
        "suggestions": suggestions,
    }


@router.get("/ai-insights")
async def ai_insights(user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_ai_insights, user.org_id)


class SuggestionAction(BaseModel):
    suggestion_key: str
    action: str  # 'done' | 'snooze'
    snooze_days: int | None = 3


@router.post("/ai-insights/action")
async def ai_insight_action(payload: SuggestionAction, user: CurrentUser = Depends(require_org)) -> dict:
    def _do() -> dict:
        client = get_service_client()
        row = {"org_id": user.org_id, "suggestion_key": payload.suggestion_key, "action": payload.action}
        if payload.action == "snooze":
            row["until_date"] = (_now() + timedelta(days=payload.snooze_days or 3)).isoformat()
        client.table("ai_suggestion_actions").insert(row).execute()
        return {"success": True}

    return await run_in_threadpool(_do)
