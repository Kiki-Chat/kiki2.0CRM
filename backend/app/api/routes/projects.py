import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import ProjectEmployeeAdd, ProjectPatch, ProjectUpsert
from app.services.common import fetch_all_rows, now_berlin, run_parallel, validate_fk_in_org
from app.services.invoices import maybe_create_invoice_for_project
from app.services.projects import gen_project_number

router = APIRouter(prefix="/api/projects", tags=["projects"])

BUCKET = "customer-files"
MAX_BYTES = 10 * 1024 * 1024
_STATUSES = {"planning", "active", "completed", "archived"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return now_berlin().date().isoformat()


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

    def rows(table: str, sel: str) -> list[dict]:
        # Paged: these feed per-project COUNTS, so a silent 1000-row truncation
        # would undercount stats for orgs with many projects/rows.
        return fetch_all_rows(
            lambda: client.table(table).select(sel).eq("org_id", org_id).in_("project_id", pids)
        )

    # Five independent enrichment reads — run them concurrently instead of serially.
    inq, appts, kvas, invs, pe = run_parallel(
        lambda: rows("inquiries", "project_id, status"),
        lambda: rows("appointments", "project_id, status"),
        lambda: rows("cost_estimates", "project_id"),
        lambda: rows("invoices", "project_id, total, status"),
        lambda: fetch_all_rows(
            lambda: client.table("project_employees")
            .select("project_id, employee_id")
            .in_("project_id", pids)
        ),
    )

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

    def count(rs: list[dict]) -> dict[str, int]:
        d: dict[str, int] = {}
        for r in rs:
            d[r["project_id"]] = d.get(r["project_id"], 0) + 1
        return d

    inq_c, kva_c, emp_c = count(inq), count(kvas), count(pe)
    open_inq: dict[str, int] = {}
    for r in inq:
        if r.get("status") in ("open", "in_progress"):
            open_inq[r["project_id"]] = open_inq.get(r["project_id"], 0) + 1
    appt_total, appt_done = {}, {}
    for a in appts:
        appt_total[a["project_id"]] = appt_total.get(a["project_id"], 0) + 1
        if a.get("status") == "completed":
            appt_done[a["project_id"]] = appt_done.get(a["project_id"], 0) + 1
    inv_count, inv_actual, inv_open = {}, {}, {}
    for v in invs:
        pid = v["project_id"]
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
            "inquiries": inq_c.get(pid, 0),
            "open_inquiries": open_inq.get(pid, 0),
            "appointments": total,
            "appointments_done": done,
            "cost_estimates": kva_c.get(pid, 0),
            "invoices": inv_count.get(pid, 0),
            "employees": emp_c.get(pid, 0),
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

    # Six independent reads (all scoped to this project / its customer) — run them
    # concurrently, and PAGE the row-returning ones so a project with >1000 related
    # rows can't silently truncate its stats.
    def _inq():
        return fetch_all_rows(
            lambda: client.table("inquiries").select("status").eq("org_id", org_id).eq("project_id", project_id)
        )

    def _appts():
        return fetch_all_rows(
            lambda: client.table("appointments").select("status, scheduled_at").eq("org_id", org_id).eq("project_id", project_id)
        )

    def _kvas():
        return fetch_all_rows(
            lambda: client.table("cost_estimates").select("id").eq("org_id", org_id).eq("project_id", project_id)
        )

    def _invs():
        return fetch_all_rows(
            lambda: client.table("invoices").select("total, status").eq("org_id", org_id).eq("project_id", project_id)
        )

    def _docs():
        return fetch_all_rows(
            lambda: client.table("documents").select("id").eq("org_id", org_id).eq("project_id", project_id)
        )

    def _calls_count():
        if not cid:
            return 0
        return (
            client.table("calls").select("id", count="exact")
            .eq("org_id", org_id).eq("customer_id", cid).execute().count or 0
        )

    inquiries, appts, kvas, invs, docs, calls = run_parallel(_inq, _appts, _kvas, _invs, _docs, _calls_count)

    pe = client.table("project_employees").select("employee_id, added_at").eq("project_id", project_id).execute().data or []
    employees: list[dict] = []
    if pe:
        edata = {
            e["id"]: e
            for e in (
                client.table("employees")
                .select("id, display_name, role_in_company, access_role, calendar_color")
                .eq("org_id", org_id).in_("id", [e["employee_id"] for e in pe]).execute().data or []
            )
        }
        for e in pe:
            emp = edata.get(e["employee_id"]) or {}
            employees.append({
                "id": e["employee_id"],
                "name": emp.get("display_name"),
                "role": emp.get("role_in_company") or emp.get("access_role"),
                "color": emp.get("calendar_color"),
                "added_at": e["added_at"],
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
    # Back-office automation: a completed project auto-drafts an invoice from its
    # accepted KVA, gated by invoices_enabled/level. Best-effort, non-blocking.
    if getattr(payload, "status", None) == "completed":
        invoice = await run_in_threadpool(
            maybe_create_invoice_for_project, user.org_id, row, user.id
        )
        if invoice:
            row["_auto_invoice_id"] = invoice["id"]
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
    cid = p.get("customer_id")
    items: list[dict] = []
    for i in client.table("inquiries").select("title, created_at, number").eq("org_id", org_id).eq("project_id", project_id).execute().data or []:
        items.append({"type": "inquiry", "date": i.get("created_at"), "label": f"Neue Anfrage: {i.get('title') or ''}".strip()})
    for a in client.table("appointments").select("title, scheduled_at, status").eq("org_id", org_id).eq("project_id", project_id).execute().data or []:
        done = a.get("status") == "completed"
        verb = "abgeschlossen" if done else "geplant"
        items.append({"type": "appointment_done" if done else "appointment", "date": a.get("scheduled_at"), "label": f"Termin {verb}: {a.get('title') or ''}".strip()})
    for k in client.table("cost_estimates").select("number, created_at, total").eq("org_id", org_id).eq("project_id", project_id).execute().data or []:
        items.append({"type": "cost_estimate", "date": k.get("created_at"), "amount": k.get("total"), "label": f"{k.get('number') or 'KVA'} erstellt"})
    for v in client.table("invoices").select("number, created_at, total, status, sent_at, paid_at").eq("org_id", org_id).eq("project_id", project_id).execute().data or []:
        items.append({"type": "invoice", "date": v.get("sent_at") or v.get("created_at"), "amount": v.get("total"), "label": f"{v.get('number') or 'RE'} {'bezahlt' if v.get('status') == 'paid' else 'erstellt'}"})
        if v.get("paid_at"):
            items.append({"type": "payment", "date": v.get("paid_at"), "amount": v.get("total"), "label": f"Zahlung eingegangen · {v.get('number') or ''}".strip()})
    if cid:
        for c in client.table("calls").select("started_at, created_at, duration_seconds, summary_title").eq("org_id", org_id).eq("customer_id", cid).order("created_at", desc=True).limit(10).execute().data or []:
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


# ─── Sub-resource lists (per workspace tab) ───────────────────────────────────
@router.get("/{project_id}/calls")
async def project_calls(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        p = _fetch(client, user.org_id, project_id)
        if not p:
            return None
        if not p.get("customer_id"):
            return []
        return (
            client.table("calls")
            .select("id, started_at, duration_seconds, direction, status, summary, summary_title")
            .eq("org_id", user.org_id).eq("customer_id", p["customer_id"])
            .order("started_at", desc=True).execute().data or []
        )
    rows = await run_in_threadpool(_q)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return rows


@router.get("/{project_id}/inquiries")
async def project_inquiries(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        rows = (
            client.table("inquiries").select("*").eq("org_id", user.org_id)
            .eq("project_id", project_id).order("created_at", desc=True).execute().data or []
        )
        _attach_employee_names(client, user.org_id, rows)
        return rows
    return await run_in_threadpool(_q)


@router.get("/{project_id}/appointments")
async def project_appointments(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        rows = (
            client.table("appointments")
            .select("id, title, scheduled_at, duration_minutes, status, color, customer_id, assigned_employee_id, location, notes")
            .eq("org_id", user.org_id).eq("project_id", project_id).order("scheduled_at").execute().data or []
        )
        _attach_employee_names(client, user.org_id, rows)
        cids = {r.get("customer_id") for r in rows if r.get("customer_id")}
        if cids:
            cn = {c["id"]: c.get("full_name") for c in client.table("customers").select("id, full_name").eq("org_id", user.org_id).in_("id", list(cids)).execute().data or []}
            for r in rows:
                r["customer_name"] = cn.get(r.get("customer_id"))
        return rows
    return await run_in_threadpool(_q)


@router.get("/{project_id}/cost-estimates")
async def project_cost_estimates(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        return (
            client.table("cost_estimates")
            .select("id, number, status, subject, total, created_at, valid_until, type")
            .eq("org_id", user.org_id).eq("project_id", project_id).order("created_at", desc=True).execute().data or []
        )
    return await run_in_threadpool(_q)


@router.get("/{project_id}/invoices")
async def project_invoices(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        rows = (
            client.table("invoices")
            .select("id, number, status, invoice_date, due_date, total, sent_at, paid_at, created_at")
            .eq("org_id", user.org_id).eq("project_id", project_id).order("created_at", desc=True).execute().data or []
        )
        today = _today()
        for r in rows:
            if r.get("status") == "sent" and r.get("due_date") and str(r["due_date"]) < today:
                r["status"] = "overdue"
        return rows
    return await run_in_threadpool(_q)


@router.get("/{project_id}/documents")
async def project_documents(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        p = _fetch(client, user.org_id, project_id)
        if not p:
            return None
        rows = client.table("documents").select("*").eq("org_id", user.org_id).eq("project_id", project_id).execute().data or []
        seen = {r["id"] for r in rows}
        if p.get("customer_id"):
            for d in client.table("documents").select("*").eq("org_id", user.org_id).eq("customer_id", p["customer_id"]).execute().data or []:
                if d["id"] not in seen:
                    rows.append(d)
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
        row = client.table("documents").insert({
            "org_id": user.org_id, "project_id": project_id, "customer_id": p.get("customer_id"),
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
@router.get("/{project_id}/employees")
async def list_project_employees(project_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    def _q():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        pe = client.table("project_employees").select("employee_id, added_at").eq("project_id", project_id).execute().data or []
        if not pe:
            return []
        ids = [e["employee_id"] for e in pe]
        edata = {
            e["id"]: e
            for e in (
                client.table("employees")
                .select("id, display_name, role_in_company, access_role, calendar_color")
                .eq("org_id", user.org_id).in_("id", ids).execute().data or []
            )
        }
        counts: dict[str, int] = {}
        for a in client.table("appointments").select("assigned_employee_id").eq("org_id", user.org_id).eq("project_id", project_id).execute().data or []:
            k = a.get("assigned_employee_id")
            if k:
                counts[k] = counts.get(k, 0) + 1
        out = []
        for e in pe:
            emp = edata.get(e["employee_id"]) or {}
            out.append({
                "id": e["employee_id"],
                "name": emp.get("display_name"),
                "role": emp.get("role_in_company") or emp.get("access_role"),
                "color": emp.get("calendar_color"),
                "appointments_handled": counts.get(e["employee_id"], 0),
                "added_at": e["added_at"],
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
        # Wave 2 — validate the employee belongs to THIS org before linking
        # (same pattern as inquiries._assign). Without this, employee_id from the
        # request body could reference another org's employee (cross-tenant FK).
        emp = (
            client.table("employees").select("id")
            .eq("org_id", user.org_id).eq("id", payload.employee_id)
            .eq("deleted", False).limit(1).execute().data
        )
        if not emp:
            return "bad_employee"
        try:
            client.table("project_employees").insert(
                {"project_id": project_id, "employee_id": payload.employee_id}
            ).execute()
        except Exception:
            pass  # already assigned (unique constraint)
        return "ok"

    res = await run_in_threadpool(_add)
    if res == "no_project":
        raise HTTPException(status_code=404, detail="Project not found")
    if res == "bad_employee":
        raise HTTPException(status_code=404, detail="Mitarbeiter nicht gefunden")
    return {"success": True}


@router.delete("/{project_id}/employees/{employee_id}")
async def remove_project_employee(
    project_id: str, employee_id: str, user: CurrentUser = Depends(require_org)
) -> dict:
    def _rm():
        client = get_service_client()
        if not _fetch(client, user.org_id, project_id):
            return None
        client.table("project_employees").delete().eq("project_id", project_id).eq("employee_id", employee_id).execute()
        return True

    ok = await run_in_threadpool(_rm)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True}
