"""Project (Projekt) helpers: numbering."""

from app.services.common import now_berlin


def gen_project_number(client, org_id: str) -> str:
    year = now_berlin().year
    res = (
        client.table("projects")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .gte("created_at", f"{year}-01-01")
        .execute()
    )
    return f"PRJ-{year}-{(res.count or 0) + 1:05d}"
