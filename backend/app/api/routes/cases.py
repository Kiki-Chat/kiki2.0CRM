"""Grouping endpoints — propose (LLM), apply (confirm), and move.

PROJECTS MERGE (Luca-meeting item 6, Amber's ruling 2026-06-12): the former
"case" layer materialises as PROJEKTE now. Same URLs (frontend contract), same
propose/confirm flow — but apply/move/create write `projects` rows and stamp
`inquiries.project_id`. The old `cases` table stays read-only for history
(migration 0067 backfilled every case into a project).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.services.cases.grouper import propose_cases_for_customer
from app.services.common import validate_fk_in_org
from app.services.projects import gen_project_number

router = APIRouter(prefix="/api", tags=["cases"])


def _uid(user: CurrentUser):
    return getattr(user, "id", None) or getattr(user, "user_id", None)


def _customer_name(client, org_id: str, customer_id: str) -> str | None:
    r = (
        client.table("customers").select("full_name")
        .eq("org_id", org_id).eq("id", customer_id).limit(1).execute().data
    )
    return r[0].get("full_name") if r else None


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
                "die automatische Vorgangs-Gruppierung ist bis zum Monatswechsel pausiert.",
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
    """Materialise confirmed groups: create a PROJEKT per group and stamp its
    inquiries' project_id (+ confidence/reason for the audit trail)."""
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
                # proposes project_id-null only, but apply trusted client-supplied
                # numbers. A stale/double-submit would re-stamp already-grouped
                # inquiries — orphaning their old project as an empty row.
                .is_("project_id", "null")
                .execute().data or []
            )
            ids = [r["id"] for r in rows]
            # No fresh inquiries (e.g. a double-submit where they're all already
            # grouped) → don't mint an empty project.
            if not ids:
                continue
            project = client.table("projects").insert({
                "org_id": org_id, "customer_id": payload.customer_id,
                "title": (g.label or "Projekt")[:120], "created_by": _uid(user),
                "number": gen_project_number(client, org_id),
                "status": "active",
                "description": "Aus KI-Gruppierung erstellt.",
            }).execute().data[0]
            client.table("inquiries").update({
                "project_id": project["id"],
                "case_confidence": g.confidence,
                "case_reason": ((g.reason or "")[:200] or None),
                "case_source": "ai_confirmed",
            }).eq("org_id", org_id).in_("id", ids).execute()
            created.append({
                "id": project["id"], "label": project["title"],
                "number": project.get("number"),
                "members": [r["number"] for r in rows],
            })
        return {"created": created, "count": len(created)}

    return await run_in_threadpool(_run)


class MoveIn(BaseModel):
    case_id: str | None = None       # existing PROJECT to move into; null = ungroup
    new_case_label: str | None = None  # create a new project and move into it


@router.post("/inquiries/{inquiry_id}/case")
async def move_inquiry_case(
    inquiry_id: str, payload: MoveIn, user: CurrentUser = Depends(require_org)
) -> dict:
    """Move one inquiry to another PROJEKT (the one-click override): into an
    existing project, into a brand-new one, or out (project_id=null). Field names
    keep the historical 'case' wording — same frontend contract, project ids."""
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
            project = client.table("projects").insert({
                "org_id": org_id, "customer_id": inq[0].get("customer_id"),
                "title": payload.new_case_label[:120], "created_by": _uid(user),
                "number": gen_project_number(client, org_id),
                "status": "active",
            }).execute().data[0]
            target = project["id"]
        elif target:
            # Same-customer guard (audit 2026-06-11): a project is customer-scoped,
            # so an inquiry may only join a project belonging to ITS customer.
            tgt = (
                client.table("projects").select("id, customer_id")
                .eq("org_id", org_id).eq("id", target).limit(1).execute().data or []
            )
            if not tgt:
                raise HTTPException(status_code=422, detail="Projekt nicht gefunden.")
            if tgt[0].get("customer_id") and tgt[0].get("customer_id") != inq[0].get("customer_id"):
                raise HTTPException(
                    status_code=422,
                    detail="Dieses Projekt gehört zu einem anderen Kunden — eine "
                    "Anfrage kann nur einem Projekt desselben Kunden zugeordnet werden.",
                )
        client.table("inquiries").update({
            "project_id": target, "case_source": "human",
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
    """The umbrella view: PROJECT header + member inquiries + ONE timeline across
    them all (URL keeps the historical /cases/ path; the id is a project id).
    Legacy fallback: an OLD case id (pre-backfill /fall links) still resolves via
    the case umbrella, so history keeps working until migration 0067 runs."""
    from app.api.routes.calls import build_case_umbrella, build_project_umbrella

    bundle = await run_in_threadpool(build_project_umbrella, user.org_id, case_id)
    if bundle is None:
        bundle = await run_in_threadpool(build_case_umbrella, user.org_id, case_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Projekt not found")
    return bundle


class CaseCreateIn(BaseModel):
    label: str | None = None


@router.post("/customers/{customer_id}/cases")
async def create_case(
    customer_id: str, payload: CaseCreateIn, user: CurrentUser = Depends(require_org)
) -> dict:
    """Create a new empty PROJEKT for a customer; inquiries are moved into it via
    the per-inquiry move action."""
    def _run():
        client = get_service_client()
        validate_fk_in_org(client, table="customers", fk_id=customer_id, org_id=user.org_id, label="Kunde")
        return client.table("projects").insert({
            "org_id": user.org_id, "customer_id": customer_id,
            "title": (payload.label or "Neues Projekt")[:120], "created_by": _uid(user),
            "number": gen_project_number(client, user.org_id),
            "status": "active",
        }).execute().data[0]

    return await run_in_threadpool(_run)
