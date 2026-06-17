"""Grouping endpoints — propose (LLM), apply (confirm), and move.

Case↔Project split (migration 0073): the grouping ticket the user sees is the
**Fall (case)** again — apply/move/create write `cases` rows and stamp
`inquiries.case_id`. `cases` IS the renamed former `projects` table, so it carries
the project-style schema (`title`/`description`/status planning|active|…) and the
`FL-` number. A top-layer **Project** sits above cases (see routes/projects.py) and
is joined manually; it is never created here.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.services.cases.grouper import propose_cases_for_customer
from app.services.common import gen_case_number, validate_fk_in_org
from app.services import invoices

router = APIRouter(prefix="/api", tags=["cases"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(user: CurrentUser):
    return getattr(user, "id", None) or getattr(user, "user_id", None)


def _customer_name(client, org_id: str, customer_id: str) -> str | None:
    r = (
        client.table("customers").select("full_name")
        .eq("org_id", org_id).eq("id", customer_id).limit(1).execute().data
    )
    return r[0].get("full_name") if r else None


_CLOSED_INQ = {"completed", "closed", "done", "resolved", "deleted"}


@router.get("/cases")
async def list_cases(user: CurrentUser = Depends(require_org)) -> list[dict]:
    """All Fälle for the org with per-case rollup stats (powers the Cases page).
    A Fall is a ticket: customer + the call(s) and the five linked things
    (Anfragen/Anrufe · Termine · KVA · Rechnungen · Mitarbeiter). Batched (no N+1)."""
    def _run():
        client = get_service_client()
        org_id = user.org_id
        cases = (
            client.table("cases")
            .select("id, number, title, status, customer_id, created_at, updated_at, project_id")
            .eq("org_id", org_id).order("created_at", desc=True).execute().data or []
        )
        if not cases:
            return []
        case_ids = [c["id"] for c in cases]

        cust_ids = list({c["customer_id"] for c in cases if c.get("customer_id")})
        cust_name: dict[str, str | None] = {}
        if cust_ids:
            for r in (client.table("customers").select("id, full_name")
                      .eq("org_id", org_id).in_("id", cust_ids).execute().data or []):
                cust_name[r["id"]] = r.get("full_name")

        # inquiries per case (+ inquiry→case map for the call rollup). emergency_flag
        # rolls up so the list can show the Notdienst pill + drive the status filter.
        inqs = (client.table("inquiries").select("id, case_id, status, emergency_flag")
                .eq("org_id", org_id).in_("case_id", case_ids).neq("status", "deleted")
                .execute().data or [])
        inq_by_case: dict[str, list[dict]] = {}
        case_of_inq: dict[str, str] = {}
        for i in inqs:
            inq_by_case.setdefault(i["case_id"], []).append(i)
            case_of_inq[i["id"]] = i["case_id"]
        inq_ids = list(case_of_inq.keys())

        def _count_by_case(table: str, by_inquiry: bool = False) -> dict[str, int]:
            col = "inquiry_id" if by_inquiry else "case_id"
            ids = inq_ids if by_inquiry else case_ids
            out: dict[str, int] = {}
            if not ids:
                return out
            q = client.table(table).select(col).eq("org_id", org_id).in_(col, ids)
            if table == "calls":
                q = q.is_("deleted_at", "null")
            for r in (q.execute().data or []):
                cid = case_of_inq.get(r[col]) if by_inquiry else r[col]
                if cid:
                    out[cid] = out.get(cid, 0) + 1
            return out

        calls_n = _count_by_case("calls", by_inquiry=True)
        kva_n = _count_by_case("cost_estimates")
        inv_n = _count_by_case("invoices")

        appt_n: dict[str, int] = {}
        appt_done: dict[str, int] = {}
        for r in (client.table("appointments").select("case_id, status")
                  .eq("org_id", org_id).in_("case_id", case_ids).execute().data or []):
            cid = r["case_id"]
            appt_n[cid] = appt_n.get(cid, 0) + 1
            if r.get("status") in ("completed", "done"):
                appt_done[cid] = appt_done.get(cid, 0) + 1

        emp_n: dict[str, int] = {}
        for r in (client.table("case_employees").select("case_id")
                  .in_("case_id", case_ids).execute().data or []):
            emp_n[r["case_id"]] = emp_n.get(r["case_id"], 0) + 1

        out = []
        for c in cases:
            cid = c["id"]
            members = inq_by_case.get(cid, [])
            out.append({
                "id": cid, "number": c.get("number"), "title": c.get("title"),
                "status": c.get("status"), "customer_id": c.get("customer_id"),
                "customer_name": cust_name.get(c.get("customer_id")),
                "created_at": c.get("created_at"), "updated_at": c.get("updated_at"),
                "project_id": c.get("project_id"),
                "emergency": any(bool(i.get("emergency_flag")) for i in members),
                "stats": {
                    "calls": calls_n.get(cid, 0),
                    "inquiries": len(members),
                    "open_inquiries": sum(1 for i in members if (i.get("status") or "") not in _CLOSED_INQ),
                    "appointments": appt_n.get(cid, 0),
                    "appointments_done": appt_done.get(cid, 0),
                    "cost_estimates": kva_n.get(cid, 0),
                    "invoices": inv_n.get(cid, 0),
                    "employees": emp_n.get(cid, 0),
                },
            })
        return out

    return await run_in_threadpool(_run)


@router.post("/customers/{customer_id}/cases/propose")
async def propose_cases(customer_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    """Run the LLM matchmaker for one customer and return the proposed grouping
    (cases + confidence + reason). Writes nothing."""
    # LLM-spend endpoint — bound per org in addition to the monthly cap below.
    from app.services.ratelimit import enforce_rate_limit
    enforce_rate_limit("cases_propose", user.org_id, max_calls=6, per_seconds=60)

    def _run():
        # Monthly AI cost cap — the offline runners (apply_run/dryrun) enforce it,
        # but this live endpoint skipped it (audit 2026-06-11): any org user could
        # loop the route into unmetered gpt-4o spend. Same ledger, same cap.
        from app.services.ai import usage as ai_usage

        if not ai_usage.within_cap(user.org_id):
            raise HTTPException(
                status_code=429,
                detail="Das monatliche KI-Budget Ihrer Organisation ist erreicht — "
                "die automatische Fall-Gruppierung ist bis zum Monatswechsel pausiert.",
            )
        client = get_service_client()
        validate_fk_in_org(client, table="customers", fk_id=customer_id, org_id=user.org_id, label="Kunde")
        name = _customer_name(client, user.org_id, customer_id)
        return propose_cases_for_customer(client, user.org_id, customer_id, name)

    return await run_in_threadpool(_run)


class GroupIn(BaseModel):
    label: str | None = None
    members: list[str]  # inquiry NUMBERS (ANF-…)
    confidence: float | None = None
    reason: str | None = None


class ApplyIn(BaseModel):
    customer_id: str
    groups: list[GroupIn]


@router.post("/cases/apply")
async def apply_cases(payload: ApplyIn, user: CurrentUser = Depends(require_org)) -> dict:
    """Materialise confirmed groups: create a Fall per group and stamp its
    inquiries' case_id (+ confidence/reason for the audit trail)."""
    def _run():
        client = get_service_client()
        org_id = user.org_id
        validate_fk_in_org(client, table="customers", fk_id=payload.customer_id, org_id=org_id, label="Kunde")
        created = []
        for g in payload.groups:
            members = [m for m in (g.members or []) if m]
            if not members:
                continue
            rows = (
                client.table("inquiries").select("id, number")
                .eq("org_id", org_id).eq("customer_id", payload.customer_id)
                .in_("number", members).neq("status", "deleted")
                # Only fold UNGROUPED inquiries (audit 2026-06-11): the grouper
                # proposes case_id-null only, but apply trusted client-supplied
                # numbers. A stale/double-submit would re-stamp already-grouped
                # inquiries — orphaning their old case as an empty row.
                .is_("case_id", "null")
                .execute().data or []
            )
            ids = [r["id"] for r in rows]
            # No fresh inquiries (e.g. a double-submit where they're all already
            # grouped) → don't mint an empty case.
            if not ids:
                continue
            case = client.table("cases").insert({
                "org_id": org_id, "customer_id": payload.customer_id,
                "title": (g.label or "Fall")[:120], "created_by": _uid(user),
                "number": gen_case_number(client, org_id),
                "status": "active",
                "description": "Aus KI-Gruppierung erstellt.",
            }).execute().data[0]
            client.table("inquiries").update({
                "case_id": case["id"],
                "case_confidence": g.confidence,
                "case_reason": ((g.reason or "")[:200] or None),
                "case_source": "ai_confirmed",
            }).eq("org_id", org_id).in_("id", ids).execute()
            created.append({
                "id": case["id"], "label": case["title"],
                "number": case.get("number"),
                "members": [r["number"] for r in rows],
            })
        return {"created": created, "count": len(created)}

    return await run_in_threadpool(_run)


class MoveIn(BaseModel):
    case_id: str | None = None        # existing case to move into; null = ungroup
    new_case_label: str | None = None  # create a new case and move into it


@router.post("/inquiries/{inquiry_id}/case")
async def move_inquiry_case(
    inquiry_id: str, payload: MoveIn, user: CurrentUser = Depends(require_org)
) -> dict:
    """Move one inquiry to another Fall (the one-click override): into an existing
    case, into a brand-new one, or out (case_id=null)."""
    def _run():
        client = get_service_client()
        org_id = user.org_id
        inq = (
            client.table("inquiries").select("id, customer_id")
            .eq("org_id", org_id).eq("id", inquiry_id).limit(1).execute().data
        )
        if not inq:
            return None
        target = payload.case_id
        if payload.new_case_label:
            case = client.table("cases").insert({
                "org_id": org_id, "customer_id": inq[0].get("customer_id"),
                "title": payload.new_case_label[:120], "created_by": _uid(user),
                "number": gen_case_number(client, org_id),
                "status": "active",
            }).execute().data[0]
            target = case["id"]
        elif target:
            # Same-customer guard (audit 2026-06-11): a case is customer-scoped,
            # so an inquiry may only join a case belonging to ITS customer.
            tgt = (
                client.table("cases").select("id, customer_id")
                .eq("org_id", org_id).eq("id", target).limit(1).execute().data or []
            )
            if not tgt:
                raise HTTPException(status_code=422, detail="Fall nicht gefunden.")
            if tgt[0].get("customer_id") and tgt[0].get("customer_id") != inq[0].get("customer_id"):
                raise HTTPException(
                    status_code=422,
                    detail="Dieser Fall gehört zu einem anderen Kunden — eine "
                    "Anfrage kann nur einem Fall desselben Kunden zugeordnet werden.",
                )
        client.table("inquiries").update({
            "case_id": target, "case_source": "human",
            "case_confidence": None if target is None else 1.0,
            "case_reason": None if target is None else "manuell zugeordnet",
        }).eq("org_id", org_id).eq("id", inquiry_id).execute()
        return {"success": True, "case_id": target}

    res = await run_in_threadpool(_run)
    if res is None:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return res


@router.get("/cases/{case_id}")
async def get_case(case_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    """The umbrella view: Fall header + member inquiries + ONE timeline across them
    all. The id is a case id (cases table)."""
    from app.api.routes.calls import build_case_umbrella

    bundle = await run_in_threadpool(build_case_umbrella, user.org_id, case_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Fall not found")
    return bundle


def _job_status(link: dict) -> str:
    if link.get("submitted_at"):
        return "abgeschlossen"
    if link.get("started_at"):
        return "läuft"
    return "offen"


@router.get("/cases/{case_id}/jobs")
async def list_case_jobs(case_id: str, user: CurrentUser = Depends(require_org)) -> list[dict]:
    """Technician job links for a Fall — every dispatch on the case's inquiries, with
    the technician, the appointment, the live status (offen/läuft/abgeschlossen) and the
    submitted report. Powers the case's Techniker table. Revoked (re-dispatched) links
    are excluded so only the live link per appointment shows."""
    from app.services import technician_jobs

    def _run():
        client = get_service_client()
        org_id = user.org_id
        validate_fk_in_org(client, table="cases", fk_id=case_id, org_id=org_id, label="Fall")
        inq_ids = [
            r["id"] for r in (
                client.table("inquiries").select("id")
                .eq("org_id", org_id).eq("case_id", case_id).neq("status", "deleted").execute().data or []
            )
        ]
        if not inq_ids:
            return []
        links = (
            client.table("technician_job_links")
            .select("id, token, appointment_id, inquiry_id, employee_id, started_at, "
                    "finished_at, submitted_at, report, photo_paths, created_at, revoked_at")
            .eq("org_id", org_id).in_("inquiry_id", inq_ids).is_("revoked_at", "null")
            .order("created_at", desc=True).execute().data or []
        )
        if not links:
            return []
        emp_ids = list({l["employee_id"] for l in links if l.get("employee_id")})
        appt_ids = list({l["appointment_id"] for l in links if l.get("appointment_id")})
        emp_name = {r["id"]: r.get("display_name") for r in (
            client.table("employees").select("id, display_name").eq("org_id", org_id).in_("id", emp_ids).execute().data or []
        )} if emp_ids else {}
        appt = {r["id"]: r for r in (
            client.table("appointments").select("id, title, scheduled_at").eq("org_id", org_id).in_("id", appt_ids).execute().data or []
        )} if appt_ids else {}
        out = []
        for l in links:
            a = appt.get(l.get("appointment_id"), {})
            out.append({
                "id": l["id"], "token": l["token"], "url": technician_jobs.job_link_url(l["token"]),
                "employee_id": l.get("employee_id"), "employee_name": emp_name.get(l.get("employee_id")),
                "appointment_id": l.get("appointment_id"), "appointment_title": a.get("title"),
                "scheduled_at": a.get("scheduled_at"), "status": _job_status(l),
                "started_at": l.get("started_at"), "finished_at": l.get("finished_at"),
                "submitted_at": l.get("submitted_at"), "photo_count": len(l.get("photo_paths") or []),
                "report": l.get("report"), "created_at": l.get("created_at"),
            })
        return out

    return await run_in_threadpool(_run)


class CaseCreateIn(BaseModel):
    label: str | None = None


@router.post("/customers/{customer_id}/cases")
async def create_case(
    customer_id: str, payload: CaseCreateIn, user: CurrentUser = Depends(require_org)
) -> dict:
    """Create a new empty Fall for a customer; inquiries are moved into it via the
    per-inquiry move action."""
    def _run():
        client = get_service_client()
        validate_fk_in_org(client, table="customers", fk_id=customer_id, org_id=user.org_id, label="Kunde")
        return client.table("cases").insert({
            "org_id": user.org_id, "customer_id": customer_id,
            "title": (payload.label or "Neuer Fall")[:120], "created_by": _uid(user),
            "number": gen_case_number(client, user.org_id),
            "status": "active",
        }).execute().data[0]

    return await run_in_threadpool(_run)


class CaseUpdateIn(BaseModel):
    status: str | None = None       # planning|active|completed|archived
    title: str | None = None
    project_id: str | None = None   # link to a top-layer Projekt (PR-); empty string unlinks
    model_config = {"extra": "ignore"}


@router.patch("/cases/{case_id}")
async def update_case(case_id: str, payload: CaseUpdateIn, user: CurrentUser = Depends(require_org)) -> dict:
    """Update a Fall: status (Offen/In Bearbeitung/Abgeschlossen), title, or its
    link to a top-layer Projekt — the case action panel's status + Add-to-Project."""
    def _run():
        client = get_service_client()
        org_id = user.org_id
        cur = client.table("cases").select("id").eq("org_id", org_id).eq("id", case_id).limit(1).execute().data
        if not cur:
            raise HTTPException(status_code=404, detail="Fall nicht gefunden.")
        fields: dict = {}
        if payload.status is not None:
            fields["status"] = payload.status
        if payload.title is not None:
            fields["title"] = payload.title[:200]
        if payload.project_id is not None:
            pid = payload.project_id or None
            if pid:
                validate_fk_in_org(client, table="projects", fk_id=pid, org_id=org_id, label="Projekt")
            fields["project_id"] = pid
        if not fields:
            return client.table("cases").select("*").eq("id", case_id).limit(1).execute().data[0]
        fields["updated_at"] = _now()
        return client.table("cases").update(fields).eq("org_id", org_id).eq("id", case_id).execute().data[0]

    case_row = await run_in_threadpool(_run)

    # INV-027 / 6.2: auto-draft an invoice when a Fall is completed.
    # Best-effort — any error in the helper is already swallowed inside the
    # function, but we guard here too so a future refactor can never surface.
    if payload.status == "completed":
        try:
            await run_in_threadpool(
                invoices.maybe_create_invoice_for_project,
                user.org_id,
                case_row,
                _uid(user),
            )
        except Exception:  # noqa: BLE001
            pass  # never fail the case update

    return case_row


class CaseEmployeeIn(BaseModel):
    employee_id: str


@router.post("/cases/{case_id}/employees")
async def add_case_employee(case_id: str, payload: CaseEmployeeIn, user: CurrentUser = Depends(require_org)) -> dict:
    """Assign an employee to a Fall (case_employees). Idempotent."""
    def _run():
        client = get_service_client()
        org_id = user.org_id
        validate_fk_in_org(client, table="cases", fk_id=case_id, org_id=org_id, label="Fall")
        validate_fk_in_org(client, table="employees", fk_id=payload.employee_id, org_id=org_id, label="Mitarbeiter", require_active=True)
        dup = (
            client.table("case_employees").select("id")
            .eq("case_id", case_id).eq("employee_id", payload.employee_id).limit(1).execute().data
        )
        if not dup:
            client.table("case_employees").insert({"case_id": case_id, "employee_id": payload.employee_id}).execute()
        return {"success": True}

    return await run_in_threadpool(_run)


@router.delete("/cases/{case_id}/employees/{employee_id}")
async def remove_case_employee(case_id: str, employee_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    """Unassign an employee from a Fall."""
    def _run():
        client = get_service_client()
        org_id = user.org_id
        validate_fk_in_org(client, table="cases", fk_id=case_id, org_id=org_id, label="Fall")
        client.table("case_employees").delete().eq("case_id", case_id).eq("employee_id", employee_id).execute()
        return {"success": True}

    return await run_in_threadpool(_run)
