"""Top-layer Project (Projekt) CRUD — the container ABOVE cases.

Case↔Project split (migration 0073): the grouping ticket the user files calls
into is the **Fall (case)** — see routes/cases.py + services/projects_auto.py.
A **Project** is the optional restored top container that bundles several cases
(``PR-{TOKEN}-NNNN``). It owns NO inquiries/actions directly; every per-project
relation resolves through the chain

    Project → its cases (cases.project_id = {id})
            → their inquiries (inquiries.case_id ∈ case_ids)
            → actions (action.inquiry_id ∈ inquiry_ids  OR  action.case_id ∈ case_ids)

There is NO ``inquiries.project_id`` / ``appointments.project_id`` etc. anymore —
those columns were renamed to ``case_id`` and re-pointed at ``cases``. The team
table is ``case_employees`` (case-level); a project's team is the UNION of its
cases' teams (see the /employees endpoints + their POST/DELETE notes).
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import ProjectEmployeeAdd, ProjectPatch, ProjectUpsert
from app.services.common import fetch_all_rows, now_berlin, run_parallel, validate_fk_in_org
from app.services.projects import gen_project_number

router = APIRouter(prefix="/api/projects", tags=["projects"])

BUCKET = "customer-files"
MAX_BYTES = 10 * 1024 * 1024
_STATUSES = {"planning", "active", "completed", "archived"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return now_berlin().date().isoformat()


# ─── Project → cases → inquiries chain ────────────────────────────────────────
def _case_ids(client, org_id: str, project_id: str) -> list[str]:
    """The project's member CASE ids (cases.project_id = project_id, this org)."""
    rows = (
        client.table("cases").select("id")
        .eq("org_id", org_id).eq("project_id", project_id).execute().data or []
    )
    return [r["id"] for r in rows]


def _inquiry_ids(client, org_id: str, case_ids: list[str]) -> list[str]:
    """Inquiries belonging to the project's cases (inquiries.case_id ∈ case_ids).
    Actions created from calls only carry inquiry_id, so the project's action set =
    inquiry_id ∈ these OR case_id ∈ case_ids."""
    if not case_ids:
        return []
    rows = fetch_all_rows(
        lambda: client.table("inquiries").select("id")
        .eq("org_id", org_id).in_("case_id", case_ids).neq("status", "deleted")
    )
    return [r["id"] for r in rows]


def _chain_ids(client, org_id: str, project_id: str) -> tuple[list[str], list[str]]:
    """(case_ids, inquiry_ids) for one project — the two filters every per-project
    relation read needs."""
    case_ids = _case_ids(client, org_id, project_id)
    return case_ids, _inquiry_ids(client, org_id, case_ids)


def _action_rows(
    client, org_id: str, table: str, sel: str,
    case_ids: list[str], inquiry_ids: list[str],
) -> list[dict]:
    """Read an action table for a project: union of rows whose case_id ∈ case_ids
    OR inquiry_id ∈ inquiry_ids (both columns exist on appointments/cost_estimates/
    documents). De-duped by id."""
    by_case = fetch_all_rows(
        lambda: client.table(table).select(sel).eq("org_id", org_id).in_("case_id", case_ids)
    ) if case_ids else []
    by_inq = fetch_all_rows(
        lambda: client.table(table).select(sel).eq("org_id", org_id).in_("inquiry_id", inquiry_ids)
    ) if inquiry_ids else []
    seen = {r["id"] for r in by_case}
    return by_case + [r for r in by_inq if r["id"] not in seen]


def _invoice_rows(
    client, org_id: str, sel: str, case_ids: list[str], kva_ids: list[str],
) -> list[dict]:
    """Invoices for a project: case_id ∈ case_ids OR cost_estimate_id ∈ kva_ids
    (invoices have NO inquiry_id — only case_id + cost_estimate_id)."""
    by_case = fetch_all_rows(
        lambda: client.table("invoices").select(sel).eq("org_id", org_id).in_("case_id", case_ids)
    ) if case_ids else []
    by_kva = fetch_all_rows(
        lambda: client.table("invoices").select(sel).eq("org_id", org_id).in_("cost_estimate_id", kva_ids)
    ) if kva_ids else []
    seen = {r["id"] for r in by_case}
    return by_case + [r for r in by_kva if r["id"] not in seen]


def _fetch(client, org_id: str, project_id: str) -> dict | None:
    rows = (
        client.table("projects").select("*").eq("org_id", org_id)
        .eq("id", project_id).limit(1).execute().data
    )
    return rows[0] if rows else None


def _signed_url(client, path: str) -> str | None:
    try:
        res = client.storage.from_(BUCKET).create_signed_url(path, 3600)
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
    except Exception:
        return None
    return None


def _attach_employee_names(client, org_id: str, rows: list[dict]) -> None:
    ids = {r.get("assigned_employee_id") for r in rows if r.get("assigned_employee_id")}
    if not ids:
        return
    names = {
        e["id"]: e.get("display_name")
        for e in (
            client.table("employees").select("id, display_name").eq("org_id", org_id)
            .in_("id", list(ids)).execute().data or []
        )
    }
    for r in rows:
        r["employee_name"] = names.get(r.get("assigned_employee_id"))


# ─── List (with per-project stats) ────────────────────────────────────────────
def _list(org_id: str, status: str | None, customer_id: str | None, search: str | None) -> list[dict]:
    client = get_service_client()

    # Page past the 1000-row cap: the list is filtered/searched client-side, so it
    # must contain EVERY project — a silent truncation would hide projects on large
    # orgs. fetch_all_rows rebuilds the (filtered) query per page.
    def _projects_query():
        qq = client.table("projects").select("*").eq("org_id", org_id)
        if status:
            qq = qq.eq("status", status)
        if customer_id:
            qq = qq.eq("customer_id", customer_id)
        return qq.order("created_at", desc=True)

    projects = fetch_all_rows(_projects_query)
    if not projects:
        return []
    pids = [p["id"] for p in projects]
    cids = list({p["customer_id"] for p in projects if p.get("customer_id")})

    # Project → cases: map every member case to its parent project, then carry the
    # case set forward to resolve inquiries/actions (a project owns nothing direct).
    cases = fetch_all_rows(
        lambda: client.table("cases").select("id, project_id")
        .eq("org_id", org_id).in_("project_id", pids)
    )
    proj_of_case = {c["id"]: c["project_id"] for c in cases}
    case_ids = list(proj_of_case.keys())
    cases_per_project: dict[str, int] = {}
    for c in cases:
        cases_per_project[c["project_id"]] = cases_per_project.get(c["project_id"], 0) + 1

    # cases → inquiries: keep each inquiry's case_id so counts roll up to a project.
    inquiries = fetch_all_rows(
        lambda: client.table("inquiries").select("id, status, case_id")
        .eq("org_id", org_id).in_("case_id", case_ids).neq("status", "deleted")
    ) if case_ids else []
    proj_of_inq: dict[str, str] = {}
    for i in inquiries:
        pid = proj_of_case.get(i.get("case_id"))
        if pid:
            proj_of_inq[i["id"]] = pid
    inquiry_ids = list(proj_of_inq.keys())

    def _proj_of_action(r: dict) -> str | None:
        # Action rolls up to a project via its case OR its inquiry.
        return proj_of_case.get(r.get("case_id")) or proj_of_inq.get(r.get("inquiry_id"))

    def actions(table: str, sel: str) -> list[dict]:
        by_case = fetch_all_rows(
            lambda: client.table(table).select(sel).eq("org_id", org_id).in_("case_id", case_ids)
        ) if case_ids else []
        by_inq = fetch_all_rows(
            lambda: client.table(table).select(sel).eq("org_id", org_id).in_("inquiry_id", inquiry_ids)
        ) if inquiry_ids else []
        seen = {r["id"] for r in by_case}
        return by_case + [r for r in by_inq if r["id"] not in seen]

    # Independent enrichment reads — concurrently. Team is case-level (case_employees).
    appts, kvas, pe = run_parallel(
        lambda: actions("appointments", "id, case_id, inquiry_id, status"),
        lambda: actions("cost_estimates", "id, case_id, inquiry_id"),
        lambda: (
            fetch_all_rows(
                lambda: client.table("case_employees").select("case_id, employee_id").in_("case_id", case_ids)
            ) if case_ids else []
        ),
    )

    # Invoices: case_id ∈ cases OR via the Angebot chain (no inquiry_id on invoices).
    kva_ids = [k["id"] for k in kvas]
    proj_of_kva = {k["id"]: _proj_of_action(k) for k in kvas}
    invs_by_case = fetch_all_rows(
        lambda: client.table("invoices").select("id, case_id, total, status")
        .eq("org_id", org_id).in_("case_id", case_ids)
    ) if case_ids else []
    invs_by_kva = fetch_all_rows(
        lambda: client.table("invoices").select("id, cost_estimate_id, total, status")
        .eq("org_id", org_id).in_("cost_estimate_id", kva_ids)
    ) if kva_ids else []
    seen_inv = {v["id"] for v in invs_by_case}
    invs = invs_by_case + [v for v in invs_by_kva if v["id"] not in seen_inv]

    def _proj_of_invoice(v: dict) -> str | None:
        return proj_of_case.get(v.get("case_id")) or proj_of_kva.get(v.get("cost_estimate_id"))

    customers: dict[str, str] = {}
    calls_by_cust: dict[str, int] = {}
    if cids:
        cust_rows, call_rows = run_parallel(
            lambda: fetch_all_rows(
                lambda: client.table("customers").select("id, full_name")
                .eq("org_id", org_id).in_("id", cids)
            ),
            lambda: fetch_all_rows(
                lambda: client.table("calls").select("customer_id")
                .eq("org_id", org_id).in_("customer_id", cids)
            ),
        )
        for c in cust_rows:
            customers[c["id"]] = c.get("full_name")
        for cl in call_rows:
            calls_by_cust[cl["customer_id"]] = calls_by_cust.get(cl["customer_id"], 0) + 1

    # ── Roll the chain rows up to per-project counts ──
    inq_c: dict[str, int] = {}
    open_inq: dict[str, int] = {}
    for i in inquiries:
        pid = proj_of_case.get(i.get("case_id"))
        if not pid:
            continue
        inq_c[pid] = inq_c.get(pid, 0) + 1
        if i.get("status") in ("open", "in_progress"):
            open_inq[pid] = open_inq.get(pid, 0) + 1

    appt_total, appt_done = {}, {}
    for a in appts:
        pid = _proj_of_action(a)
        if not pid:
            continue
        appt_total[pid] = appt_total.get(pid, 0) + 1
        if a.get("status") == "completed":
            appt_done[pid] = appt_done.get(pid, 0) + 1

    kva_c: dict[str, int] = {}
    for k in kvas:
        pid = _proj_of_action(k)
        if pid:
            kva_c[pid] = kva_c.get(pid, 0) + 1

    emp_sets: dict[str, set] = {}
    for e in pe:
        pid = proj_of_case.get(e.get("case_id"))
        if pid:
            emp_sets.setdefault(pid, set()).add(e.get("employee_id"))

    inv_count, inv_actual, inv_open = {}, {}, {}
    for v in invs:
        pid = _proj_of_invoice(v)
        if not pid:
            continue
        inv_count[pid] = inv_count.get(pid, 0) + 1
        if v.get("status") != "cancelled":
            inv_actual[pid] = inv_actual.get(pid, 0) + (v.get("total") or 0)
        if v.get("status") == "sent":
            inv_open[pid] = inv_open.get(pid, 0) + (v.get("total") or 0)

    for p in projects:
        pid = p["id"]
        p["customer_name"] = customers.get(p.get("customer_id"))
        total, done = appt_total.get(pid, 0), appt_done.get(pid, 0)
        p["stats"] = {
            "calls": calls_by_cust.get(p.get("customer_id"), 0),
            "cases": cases_per_project.get(pid, 0),
            "inquiries": inq_c.get(pid, 0),
            "open_inquiries": open_inq.get(pid, 0),
            "appointments": total,
            "appointments_done": done,
            "cost_estimates": kva_c.get(pid, 0),
            "invoices": inv_count.get(pid, 0),
            "employees": len(emp_sets.get(pid, ())),
        }
        p["progress"] = round(done / total * 100) if total else 0
        p["actual_budget"] = round(inv_actual.get(pid, 0), 2)
        p["open_amount"] = round(inv_open.get(pid, 0), 2)

    if search:
        s = search.lower()
        projects = [
            p for p in projects
            if s in (p.get("title") or "").lower() or s in (p.get("customer_name") or "").lower()
        ]
    return projects


@router.get("")
async def list_projects(
    status: str | None = None,
    customer_id: str | None = None,
    search: str | None = None,
    user: CurrentUser = Depends(require_org),
) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id, status, customer_id, search)


# ─── Create ──────────────────────────────────────────────────────────────────
def _create(org_id: str, user_id: str | None, payload: ProjectUpsert) -> dict:
    client = get_service_client()
    # Service-role bypasses RLS — verify a client-supplied customer_id actually
    # belongs to this org before linking it (cross-tenant integrity / IDOR).
    validate_fk_in_org(client, table="customers", fk_id=payload.customer_id, org_id=org_id, label="Kunde")
    row = {
        "org_id": org_id,
        "customer_id": payload.customer_id,
        "number": gen_project_number(client, org_id),
        "title": payload.title,
        "description": payload.description,
        "status": payload.status or "planning",
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "planned_budget": payload.planned_budget,
        "project_address": payload.project_address,
        "internal_notes": payload.internal_notes,
        "created_by": user_id,
    }
    if payload.internal_notes:
        row["notes_updated_at"] = _now()
    return client.table("projects").insert(row).execute().data[0]


@router.post("")
async def create_project(payload: ProjectUpsert, user: CurrentUser = Depends(require_org)) -> dict:
    return await run_in_threadpool(_create, user.org_id, user.id, payload)


# ─── Detail (rich) ────────────────────────────────────────────────────────────
def _detail(org_id: str, project_id: str) -> dict | None:
    client = get_service_client()
    p = _fetch(client, org_id, project_id)
    if not p:
        return None
    cid = p.get("customer_id")
    if cid:
        c = (
            client.table("customers")
            .select("full_name, email, phone, address, customer_number")
            .eq("org_id", org_id).eq("id", cid).limit(1).execute().data
        )
        cust = c[0] if c else {}
        p["customer_name"] = cust.get("full_name")
        p["customer"] = cust

    # Project owns nothing direct — resolve via Project → cases → inquiries → actions.
    case_ids, member_ids = _chain_ids(client, org_id, project_id)

    def _inq():
        if not case_ids:
            return []
        return fetch_all_rows(
            lambda: client.table("inquiries").select("id, status").eq("org_id", org_id)
            .in_("case_id", case_ids).neq("status", "deleted")
        )

    def _appts():
        return _action_rows(client, org_id, "appointments", "id, status, scheduled_at", case_ids, member_ids)

    def _kvas():
        return _action_rows(client, org_id, "cost_estimates", "id", case_ids, member_ids)

    def _docs():
        return _action_rows(client, org_id, "documents", "id", case_ids, member_ids)

    def _calls_count():
        # Calls belong to the project via its member inquiries.
        if not member_ids:
            return 0
        return (
            client.table("calls").select("id", count="exact")
            .eq("org_id", org_id).in_("inquiry_id", member_ids)
            .is_("deleted_at", "null").execute().count or 0
        )

    inquiries, appts, kvas, docs, calls = run_parallel(_inq, _appts, _kvas, _docs, _calls_count)

    # Invoices: case_id ∈ cases OR via the Angebot chain (no project/inquiry on invoices).
    kva_ids = [k["id"] for k in kvas]
    invs = _invoice_rows(client, org_id, "id, total, status", case_ids, kva_ids)

    # Team = UNION of the member cases' case_employees rows.
    pe = fetch_all_rows(
        lambda: client.table("case_employees").select("employee_id, added_at").in_("case_id", case_ids)
    ) if case_ids else []
    employees: list[dict] = []
    if pe:
        # One row per distinct employee (earliest added_at wins) across the cases.
        first_added: dict[str, str] = {}
        for e in pe:
            eid = e["employee_id"]
            if eid not in first_added or (e.get("added_at") or "") < first_added[eid]:
                first_added[eid] = e.get("added_at")
        edata = {
            e["id"]: e
            for e in (
                client.table("employees")
                .select("id, display_name, role_in_company, access_role, calendar_color")
                .eq("org_id", org_id).in_("id", list(first_added)).execute().data or []
            )
        }
        for eid, added in first_added.items():
            emp = edata.get(eid) or {}
            employees.append({
                "id": eid,
                "name": emp.get("display_name"),
                "role": emp.get("role_in_company") or emp.get("access_role"),
                "color": emp.get("calendar_color"),
                "added_at": added,
            })

    today = _today()
    total_appt = len(appts)
    done_appt = sum(1 for a in appts if a.get("status") == "completed")
    future = sorted(
        a["scheduled_at"] for a in appts
        if a.get("scheduled_at") and str(a["scheduled_at"]) >= today and a.get("status") != "cancelled"
    )
    open_inv = round(sum((v.get("total") or 0) for v in invs if v.get("status") == "sent"), 2)
    actual = round(sum((v.get("total") or 0) for v in invs if v.get("status") != "cancelled"), 2)

    p["employees"] = employees
    p["stats"] = {
        "calls": calls,
        "cases": len(case_ids),
        "inquiries": len(inquiries),
        "open_inquiries": sum(1 for i in inquiries if i.get("status") in ("open", "in_progress")),
        "appointments": total_appt,
        "appointments_done": done_appt,
        "cost_estimates": len(kvas),
        "invoices": len(invs),
        "documents": len(docs),
        "employees": len(employees),
        "next_appointment": future[0] if future else None,
        "open_invoices_amount": open_inv,
    }
    p["progress"] = round(done_appt / total_appt * 100) if total_appt else 0
    p["actual_budget"] = actual
    p["open_amount"] = open_inv
    return p


@router.get("/{project_id}")
async def get_project(project_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    row = await run_in_threadpool(_detail, user.org_id, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


# ─── Update / Delete ──────────────────────────────────────────────────────────
def _patch(org_id: str, project_id: str, payload: ProjectPatch) -> dict | None:
    client = get_service_client()
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return _fetch(client, org_id, project_id)
    # Service-role bypasses RLS — a re-pointed customer_id on the UPDATE path must
    # still belong to this org (the create path validates; close the PATCH gap too).
    validate_fk_in_org(client, table="customers", fk_id=fields.get("customer_id"), org_id=org_id, label="Kunde")
    if "status" in fields and fields["status"] not in _STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status")
    if "internal_notes" in fields:
        fields["notes_updated_at"] = _now()
    fields["updated_at"] = _now()
    res = client.table("projects").update(fields).eq("org_id", org_id).eq("id", project_id).execute()
    return res.data[0] if res.data else None


@router.patch("/{project_id}")
async def update_project(
    project_id: str, payload: ProjectPatch, user: CurrentUser = Depends(require_org)
) -> dict:
    row = await run_in_threadpool(_patch, user.org_id, project_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@router.delete("/{project_id}")
async def delete_project(project_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    def _archive() -> dict | None:
        client = get_service_client()
        res = (
            client.table("projects")
            .update({"status": "archived", "updated_at": _now()})
            .eq("org_id", user.org_id).eq("id", project_id).execute()
        )
        return res.data[0] if res.data else None

    row = await run_in_threadpool(_archive)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "status": "archived"}


# ─── Activity feed ────────────────────────────────────────────────────────────
def _activity(org_id: str, project_id: str, limit: int) -> list[dict] | None:
    client = get_service_client()
    p = _fetch(client, org_id, project_id)
    if not p:
        return None
    items: list[dict] = []
    # Project → cases → inquiries → actions. Each relation = case_id ∈ cases OR
    # inquiry_id ∈ member inquiries — mirrors the workspace tab endpoints.
    case_ids, member_ids = _chain_ids(client, org_id, project_id)

    if case_ids:
        for i in (
            client.table("inquiries").select("title, created_at, number")
            .eq("org_id", org_id).in_("case_id", case_ids).neq("status", "deleted").execute().data or []
        ):
            items.append({"type": "inquiry", "date": i.get("created_at"), "label": f"Neue Anfrage: {i.get('title') or ''}".strip()})
    for a in _action_rows(client, org_id, "appointments", "id, title, scheduled_at, status", case_ids, member_ids):
        done = a.get("status") == "completed"
        verb = "abgeschlossen" if done else "geplant"
        items.append({"type": "appointment_done" if done else "appointment", "date": a.get("scheduled_at"), "label": f"Termin {verb}: {a.get('title') or ''}".strip()})
    kvas = _action_rows(client, org_id, "cost_estimates", "id, number, created_at, total", case_ids, member_ids)
    for k in kvas:
        items.append({"type": "cost_estimate", "date": k.get("created_at"), "amount": k.get("total"), "label": f"{k.get('number') or 'Angebot'} erstellt"})
    kva_ids = [k["id"] for k in kvas]
    for v in _invoice_rows(client, org_id, "id, number, created_at, total, status, sent_at, paid_at", case_ids, kva_ids):
        items.append({"type": "invoice", "date": v.get("sent_at") or v.get("created_at"), "amount": v.get("total"), "label": f"{v.get('number') or 'RE'} {'bezahlt' if v.get('status') == 'paid' else 'erstellt'}"})
        if v.get("paid_at"):
            items.append({"type": "payment", "date": v.get("paid_at"), "amount": v.get("total"), "label": f"Zahlung eingegangen · {v.get('number') or ''}".strip()})
    if member_ids:
        for c in client.table("calls").select("started_at, created_at, duration_seconds, summary_title").eq("org_id", org_id).in_("inquiry_id", member_ids).is_("deleted_at", "null").order("created_at", desc=True).limit(10).execute().data or []:
            mins = round((c.get("duration_seconds") or 0) / 60)
            items.append({"type": "call", "date": c.get("started_at") or c.get("created_at"), "label": f"Anruf · {mins} min" + (f" · {c.get('summary_title')}" if c.get("summary_title") else "")})
    items = [it for it in items if it.get("date")]
    items.sort(key=lambda x: str(x["date"]), reverse=True)
    return items[:limit]


@router.get("/{project_id}/activity")
async def project_activity(project_id: str, limit: int = 20, user: CurrentUser = Depends(require_org)) -> list[dict]:
    items = await run_in_threadpool(_activity, user.org_id, project_id, limit)
    if items is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return items


# ─── Member cases (the project's case list) ───────────────────────────────────
@router.get("/{project_id}/cases")
async def project_cases(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict] | None:
    def _q():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        rows = fetch_all_rows(
            lambda: client.table("cases")
            .select("id, number, title, status, customer_id, created_at, updated_at")
            .eq("org_id", user.org_id).eq("project_id", project_id).order("created_at", desc=True)
        )
        cids = {r.get("customer_id") for r in rows if r.get("customer_id")}
        if cids:
            cn = {
                c["id"]: c.get("full_name")
                for c in client.table("customers").select("id, full_name")
                .eq("org_id", user.org_id).in_("id", list(cids)).execute().data or []
            }
            for r in rows:
                r["customer_name"] = cn.get(r.get("customer_id"))
        # JSON contract: expose the grouping label under case_label (= case.title).
        for r in rows:
            r["case_label"] = r.get("title")
        return rows
    rows = await run_in_threadpool(_q)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


# ─── Sub-resource lists (per workspace tab) ───────────────────────────────────
@router.get("/{project_id}/calls")
async def project_calls(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        # THIS project's calls = calls of its cases' member inquiries.
        _, member_ids = _chain_ids(client, user.org_id, project_id)
        if not member_ids:
            return []
        return (
            client.table("calls")
            .select("id, started_at, duration_seconds, direction, status, summary, summary_title")
            .eq("org_id", user.org_id).in_("inquiry_id", member_ids)
            .is_("deleted_at", "null")
            .order("started_at", desc=True).execute().data or []
        )
    rows = await run_in_threadpool(_q)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


@router.get("/{project_id}/inquiries")
async def project_inquiries(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict] | None:
    def _q():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        case_ids = _case_ids(client, user.org_id, project_id)
        if not case_ids:
            return []
        rows = (
            client.table("inquiries").select("*").eq("org_id", user.org_id)
            .in_("case_id", case_ids).neq("status", "deleted")
            .order("created_at", desc=True).execute().data or []
        )
        _attach_employee_names(client, user.org_id, rows)
        return rows
    rows = await run_in_threadpool(_q)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


@router.get("/{project_id}/appointments")
async def project_appointments(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict] | None:
    def _q():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        case_ids, member_ids = _chain_ids(client, user.org_id, project_id)
        _APPT_COLS = "id, title, scheduled_at, duration_minutes, status, color, customer_id, assigned_employee_id, location, notes, case_id, inquiry_id"
        rows = sorted(
            _action_rows(client, user.org_id, "appointments", _APPT_COLS, case_ids, member_ids),
            key=lambda r: r.get("scheduled_at") or "",
        )
        _attach_employee_names(client, user.org_id, rows)
        cids = {r.get("customer_id") for r in rows if r.get("customer_id")}
        if cids:
            cn = {c["id"]: c.get("full_name") for c in client.table("customers").select("id, full_name").eq("org_id", user.org_id).in_("id", list(cids)).execute().data or []}
            for r in rows:
                r["customer_name"] = cn.get(r.get("customer_id"))
        return rows
    rows = await run_in_threadpool(_q)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


@router.get("/{project_id}/cost-estimates")
async def project_cost_estimates(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict] | None:
    def _q():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        case_ids, member_ids = _chain_ids(client, user.org_id, project_id)
        _KVA_COLS = "id, number, status, subject, total, created_at, valid_until, type, case_id, inquiry_id"
        rows = _action_rows(client, user.org_id, "cost_estimates", _KVA_COLS, case_ids, member_ids)
        return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)
    rows = await run_in_threadpool(_q)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


@router.get("/{project_id}/invoices")
async def project_invoices(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict] | None:
    def _q():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        case_ids, member_ids = _chain_ids(client, user.org_id, project_id)
        # Angebot chain: invoice → cost_estimate → (case_id ∈ cases OR inquiry_id ∈ members).
        kvas = _action_rows(client, user.org_id, "cost_estimates", "id", case_ids, member_ids)
        kva_ids = [k["id"] for k in kvas]
        _INV_COLS = "id, number, status, invoice_date, due_date, total, sent_at, paid_at, created_at, case_id, cost_estimate_id"
        rows = sorted(
            _invoice_rows(client, user.org_id, _INV_COLS, case_ids, kva_ids),
            key=lambda r: r.get("created_at") or "", reverse=True,
        )
        today = _today()
        for r in rows:
            if r.get("status") == "sent" and r.get("due_date") and str(r["due_date"]) < today:
                r["status"] = "overdue"
        return rows
    rows = await run_in_threadpool(_q)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


@router.get("/{project_id}/documents")
async def project_documents(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        p = _fetch(client, user.org_id, project_id)
        if not p:
            return None
        case_ids, member_ids = _chain_ids(client, user.org_id, project_id)
        rows = _action_rows(client, user.org_id, "documents", "*", case_ids, member_ids)
        seen = {r["id"] for r in rows}
        # Customer-wide docs (uploaded against the customer, not a case/inquiry).
        if p.get("customer_id"):
            for d in client.table("documents").select("*").eq("org_id", user.org_id).eq("customer_id", p["customer_id"]).execute().data or []:
                if d["id"] not in seen:
                    rows.append(d)
                    seen.add(d["id"])
        rows.sort(key=lambda d: d.get("uploaded_at") or "", reverse=True)
        for d in rows:
            d["url"] = _signed_url(client, d["path"])
        return rows
    rows = await run_in_threadpool(_q)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


@router.post("/{project_id}/documents")
async def upload_project_document(
    project_id: str,
    file: UploadFile = File(...),
    category: str | None = Form(default=None),
    user: CurrentUser = Depends(require_org),
) -> dict:
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Datei zu groß (max 10MB)")

    def _up():
        client = get_service_client()
        p = _fetch(client, user.org_id, project_id)
        if not p:
            return None
        is_image = bool(file.content_type and file.content_type.startswith("image/"))
        safe = (file.filename or "datei").replace("/", "_")
        path = f"{user.org_id}/projects/{project_id}/{uuid.uuid4().hex}_{safe}"
        client.storage.from_(BUCKET).upload(path, content, {"content-type": file.content_type or "application/octet-stream"})
        # A top-layer project has no case_id column on documents; file it against
        # the customer (project-scoped view re-discovers it via the customer fan-in).
        row = client.table("documents").insert({
            "org_id": user.org_id, "customer_id": p.get("customer_id"),
            "name": file.filename, "path": path, "category": category,
            "mime_type": file.content_type, "size_bytes": len(content), "is_image": is_image,
        }).execute().data[0]
        row["url"] = _signed_url(client, path)
        return row

    row = await run_in_threadpool(_up)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


# ─── Team (assigned employees) ────────────────────────────────────────────────
# A top-layer project has NO project_employees table — the team lives at CASE
# level (case_employees). GET aggregates the UNION of the member cases' teams.
@router.get("/{project_id}/employees")
async def list_project_employees(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        case_ids, member_ids = _chain_ids(client, user.org_id, project_id)
        pe = fetch_all_rows(
            lambda: client.table("case_employees").select("employee_id, added_at, case_id").in_("case_id", case_ids)
        ) if case_ids else []
        if not pe:
            return []
        # Distinct employee, earliest added_at across the cases.
        first_added: dict[str, str] = {}
        for e in pe:
            eid = e["employee_id"]
            if eid not in first_added or (e.get("added_at") or "") < (first_added[eid] or ""):
                first_added[eid] = e.get("added_at")
        ids = list(first_added)
        edata = {
            e["id"]: e
            for e in (
                client.table("employees")
                .select("id, display_name, role_in_company, access_role, calendar_color")
                .eq("org_id", user.org_id).in_("id", ids).execute().data or []
            )
        }
        # Appointments handled across the project's cases/inquiries.
        counts: dict[str, int] = {}
        for a in _action_rows(client, user.org_id, "appointments", "id, assigned_employee_id", case_ids, member_ids):
            k = a.get("assigned_employee_id")
            if k:
                counts[k] = counts.get(k, 0) + 1
        out = []
        for eid, added in first_added.items():
            emp = edata.get(eid) or {}
            out.append({
                "id": eid,
                "name": emp.get("display_name"),
                "role": emp.get("role_in_company") or emp.get("access_role"),
                "color": emp.get("calendar_color"),
                "appointments_handled": counts.get(eid, 0),
                "added_at": added,
            })
        return out

    rows = await run_in_threadpool(_q)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


@router.post("/{project_id}/employees")
async def add_project_employee(
    project_id: str, payload: ProjectEmployeeAdd, user: CurrentUser = Depends(require_org)
) -> dict:
    def _add():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return "no_project"
        # Validate the employee belongs to THIS org before linking (cross-tenant FK).
        emp = (
            client.table("employees").select("id")
            .eq("org_id", user.org_id).eq("id", payload.employee_id)
            .eq("deleted", False).limit(1).execute().data
        )
        if not emp:
            return "bad_employee"
        # The team table is case_employees (case-level) — a project-level team needs
        # a target case. Attach the employee to EVERY member case so the project's
        # aggregated team (UNION over cases) includes them. No member cases → there
        # is nowhere to attach a project-level member.
        case_ids = _case_ids(client, user.org_id, project_id)
        if not case_ids:
            return "no_cases"
        for cid in case_ids:
            try:
                client.table("case_employees").insert(
                    {"case_id": cid, "employee_id": payload.employee_id}
                ).execute()
            except Exception:
                pass  # already assigned (unique constraint)
        return "ok"

    res = await run_in_threadpool(_add)
    if res == "no_project":
        raise HTTPException(status_code=404, detail="Project not found")
    if res == "bad_employee":
        raise HTTPException(status_code=404, detail="Mitarbeiter nicht gefunden")
    if res == "no_cases":
        raise HTTPException(
            status_code=400,
            detail="Das Projekt hat noch keine Vorgänge — ein Teammitglied kann erst "
            "zugewiesen werden, wenn dem Projekt mindestens ein Vorgang zugeordnet ist "
            "(das Team wird auf Vorgangs-Ebene geführt).",
        )
    return {"success": True}


@router.delete("/{project_id}/employees/{employee_id}")
async def remove_project_employee(
    project_id: str, employee_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    def _rm():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        # Remove from EVERY member case (mirror of the add fan-out).
        case_ids = _case_ids(client, user.org_id, project_id)
        if case_ids:
            client.table("case_employees").delete().in_("case_id", case_ids).eq("employee_id", employee_id).execute()
        return True

    ok = await run_in_threadpool(_rm)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True}


# ─── Link a case into / out of a project ("Add to project") ───────────────────
class CaseLinkIn(BaseModel):
    case_id: str


@router.post("/{project_id}/cases")
async def link_case_to_project(
    project_id: str, payload: CaseLinkIn, user: CurrentUser = Depends(require_org)
) -> dict:
    """Add a case to this top-layer project: set cases.project_id = project_id.
    Validates the case + project are the SAME org and (when both carry one) the
    SAME customer — a project bundles cases of one customer."""
    def _run():
        client = get_service_client()
        org_id = user.org_id
        proj = _fetch(client, org_id, project_id)
        if not proj:
            return "no_project"
        case = (
            client.table("cases").select("id, customer_id, project_id")
            .eq("org_id", org_id).eq("id", payload.case_id).limit(1).execute().data
        )
        if not case:
            return "no_case"
        case = case[0]
        if (
            proj.get("customer_id") and case.get("customer_id")
            and proj["customer_id"] != case["customer_id"]
        ):
            return "wrong_customer"
        client.table("cases").update({"project_id": project_id, "updated_at": _now()}) \
            .eq("org_id", org_id).eq("id", payload.case_id).execute()
        return "ok"

    res = await run_in_threadpool(_run)
    if res == "no_project":
        raise HTTPException(status_code=404, detail="Project not found")
    if res == "no_case":
        raise HTTPException(status_code=404, detail="Vorgang nicht gefunden")
    if res == "wrong_customer":
        raise HTTPException(
            status_code=422,
            detail="Dieser Vorgang gehört zu einem anderen Kunden — ein Projekt bündelt "
            "nur Vorgänge desselben Kunden.",
        )
    return {"success": True, "project_id": project_id, "case_id": payload.case_id}


@router.delete("/{project_id}/cases/{case_id}")
async def unlink_case_from_project(
    project_id: str, case_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    """Remove a case from this project (cases.project_id → null). Only clears the
    pointer when the case is actually linked to THIS project."""
    def _run():
        client = get_service_client()
        org_id = user.org_id
        if not _fetch(client, org_id, project_id):
            return "no_project"
        res = (
            client.table("cases").update({"project_id": None, "updated_at": _now()})
            .eq("org_id", org_id).eq("id", case_id).eq("project_id", project_id).execute()
        )
        return "ok" if res.data else "not_linked"

    res = await run_in_threadpool(_run)
    if res == "no_project":
        raise HTTPException(status_code=404, detail="Project not found")
    if res == "not_linked":
        raise HTTPException(status_code=404, detail="Vorgang ist diesem Projekt nicht zugeordnet")
    return {"success": True, "project_id": project_id, "case_id": case_id}
