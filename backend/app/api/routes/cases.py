"""Case (Vorgang) grouping — propose (LLM), apply (confirm), and move.

The matchmaker proposes how to fold a customer's scattered inquiries into real
cases; a human confirms (or edits) here, then inquiries.case_id carries it. Nothing
is auto-applied — propose writes nothing; apply/move are explicit, human-driven, and
reversible.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.services.cases.grouper import propose_cases_for_customer
from app.services.common import gen_case_number, validate_fk_in_org

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
    """Materialise confirmed groups: create a `cases` row per group and stamp its
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
                # numbers. A stale/double-submit would re-stamp already-cased
                # inquiries — orphaning their old case as an empty K-numbered row.
                .is_("case_id", "null")
                .execute().data or []
            )
            ids = [r["id"] for r in rows]
            # No fresh inquiries (e.g. a double-submit where they're all already
            # cased) → don't mint an empty case.
            if not ids:
                continue
            case = client.table("cases").insert({
                "org_id": org_id, "customer_id": payload.customer_id,
                "label": (g.label or "Vorgang")[:120], "created_by": _uid(user),
                "number": gen_case_number(client, org_id),
            }).execute().data[0]
            client.table("inquiries").update({
                "case_id": case["id"],
                "case_confidence": g.confidence,
                "case_reason": ((g.reason or "")[:200] or None),
                "case_source": "ai_confirmed",
            }).eq("org_id", org_id).in_("id", ids).execute()
            created.append({"id": case["id"], "label": case["label"], "members": [r["number"] for r in rows]})
        return {"created": created, "count": len(created)}

    return await run_in_threadpool(_run)


class MoveIn(BaseModel):
    case_id: str | None = None       # existing case to move into; null = ungroup (standalone)
    new_case_label: str | None = None  # create a new case and move into it


@router.post("/inquiries/{inquiry_id}/case")
async def move_inquiry_case(
    inquiry_id: str, payload: MoveIn, user: CurrentUser = Depends(require_org)
) -> dict:
    """Move one inquiry to another case (the one-click override): into an existing
    case, into a brand-new case, or out (case_id=null)."""
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
                "label": payload.new_case_label[:120], "created_by": _uid(user),
                "number": gen_case_number(client, org_id),
            }).execute().data[0]
            target = case["id"]
        elif target:
            # Same-customer guard (audit 2026-06-11): a case is customer-scoped,
            # so an inquiry may only join a case belonging to ITS customer.
            # Org-membership alone let staff file customer A's inquiry into
            # customer B's case, mixing two customers' data under one umbrella.
            tgt = (
                client.table("cases").select("id, customer_id")
                .eq("org_id", org_id).eq("id", target).limit(1).execute().data or []
            )
            if not tgt:
                raise HTTPException(status_code=422, detail="Vorgang nicht gefunden.")
            if tgt[0].get("customer_id") != inq[0].get("customer_id"):
                raise HTTPException(
                    status_code=422,
                    detail="Dieser Vorgang gehört zu einem anderen Kunden — eine "
                    "Anfrage kann nur einem Vorgang desselben Kunden zugeordnet werden.",
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
    """The case tab: header + member inquiries + ONE umbrella timeline across them all."""
    from app.api.routes.calls import build_case_umbrella

    bundle = await run_in_threadpool(build_case_umbrella, user.org_id, case_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Fall not found")
    return bundle


class CaseCreateIn(BaseModel):
    label: str | None = None


@router.post("/customers/{customer_id}/cases")
async def create_case(
    customer_id: str, payload: CaseCreateIn, user: CurrentUser = Depends(require_org)
) -> dict:
    """Create a new empty case (Fall) for a customer; inquiries are moved into it via
    the per-inquiry move action."""
    def _run():
        client = get_service_client()
        validate_fk_in_org(client, table="customers", fk_id=customer_id, org_id=user.org_id, label="Kunde")
        return client.table("cases").insert({
            "org_id": user.org_id, "customer_id": customer_id,
            "label": (payload.label or "Neuer Fall")[:120], "created_by": _uid(user),
            "number": gen_case_number(client, user.org_id),
        }).execute().data[0]

    return await run_in_threadpool(_run)
