import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client
from app.schemas.admin import CatalogItemUpsert

router = APIRouter(prefix="/api/catalog", tags=["catalog"])
# Legacy alias still used by the KVA quick-select until it is repointed.
items_router = APIRouter(prefix="/api/catalog-items", tags=["catalog"])

_COLS = (
    "id, article_number, name, description, category, unit, vat_rate, is_wage, "
    "unit_price, purchase_price, supplier_id, is_active, created_at"
)


def _list(org_id: str, category: str | None, status: str | None, q: str | None) -> list[dict]:
    client = get_service_client()
    query = client.table("catalog_items").select(_COLS).eq("org_id", org_id)
    if category and category not in ("all", ""):
        query = query.eq("category", category)
    if status == "active":
        query = query.eq("is_active", True)
    elif status == "inactive":
        query = query.eq("is_active", False)
    if q:
        query = query.or_(
            f"name.ilike.%{q}%,article_number.ilike.%{q}%,category.ilike.%{q}%"
        )
    rows = query.order("name").execute().data or []

    supplier_ids = {r["supplier_id"] for r in rows if r.get("supplier_id")}
    suppliers: dict[str, str] = {}
    if supplier_ids:
        for s in (
            client.table("customers").select("id, full_name").eq("org_id", org_id)
            .in_("id", list(supplier_ids)).execute().data or []
        ):
            suppliers[s["id"]] = s.get("full_name")
    for r in rows:
        r["supplier_name"] = suppliers.get(r.get("supplier_id"))
    return rows


@router.get("")
async def list_catalog(
    category: str | None = None,
    status: str | None = None,
    q: str | None = None,
    user: CurrentUser = Depends(require_org),
) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id, category, status, q)


@items_router.get("")
async def list_catalog_items(
    status: str | None = None, user: CurrentUser = Depends(require_org)
) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id, None, status, None)


def _create(org_id: str, payload: CatalogItemUpsert) -> dict:
    client = get_service_client()
    row = payload.model_dump(exclude_unset=True)
    row["org_id"] = org_id
    row.setdefault("name", "Position")
    row.setdefault("unit", "Stk")
    row.setdefault("unit_price", 0)
    row.setdefault("is_active", True)
    return client.table("catalog_items").insert(row).execute().data[0]


@router.post("")
async def create_catalog(
    payload: CatalogItemUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    return await run_in_threadpool(_create, user.org_id, payload)


def _export_csv(org_id: str) -> str:
    rows = _list(org_id, None, None, None)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([
        "Artikelnummer", "Bezeichnung", "Beschreibung", "Kategorie", "Einheit",
        "MwSt", "Verkaufspreis", "Einkaufspreis", "Aktiv",
    ])
    for r in rows:
        w.writerow([
            r.get("article_number") or "", r.get("name") or "", r.get("description") or "",
            r.get("category") or "", r.get("unit") or "", r.get("vat_rate") or "",
            r.get("unit_price") or "", r.get("purchase_price") or "",
            "ja" if r.get("is_active") else "nein",
        ])
    return buf.getvalue()


@router.get("/export")
async def export_catalog(user: CurrentUser = Depends(require_org)) -> Response:
    csv_text = await run_in_threadpool(_export_csv, user.org_id)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="katalog.csv"'},
    )


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def _import_csv(org_id: str, content: bytes) -> dict:
    client = get_service_client()
    text = content.decode("utf-8-sig", errors="ignore")
    delim = ";" if text.count(";") >= text.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)

    def pick(row: dict, *keys: str):
        for k in row:
            if k and k.strip().lower() in keys:
                return row[k]
        return None

    rows: list[dict] = []
    skipped = 0
    for row in reader:
        name = pick(row, "bezeichnung", "name", "designation")
        if not name or not name.strip():
            skipped += 1
            continue
        rows.append({
            "org_id": org_id,
            "article_number": pick(row, "artikelnummer", "article_number", "artikel-nr.", "artikel nr"),
            "name": name.strip(),
            "description": pick(row, "beschreibung", "description"),
            "category": pick(row, "kategorie", "category"),
            "unit": (pick(row, "einheit", "unit") or "Stk"),
            "vat_rate": _num(pick(row, "mwst", "mwst %", "vat", "vat_rate")) or 19,
            "unit_price": _num(pick(row, "verkaufspreis", "selling_price", "preis", "price")) or 0,
            "purchase_price": _num(pick(row, "einkaufspreis", "purchase_price")),
            "is_active": (pick(row, "aktiv", "active", "is_active") or "ja").strip().lower()
            in ("ja", "true", "1", "yes", "aktiv"),
        })
    created = 0
    if rows:
        created = len(client.table("catalog_items").insert(rows).execute().data or [])
    return {"created": created, "skipped": skipped, "total": created + skipped}


@router.post("/import")
async def import_catalog(
    file: UploadFile = File(...), user: CurrentUser = Depends(require_org)
) -> dict:
    content = await file.read()
    return await run_in_threadpool(_import_csv, user.org_id, content)


def _update(org_id: str, item_id: str, payload: CatalogItemUpsert) -> dict | None:
    client = get_service_client()
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        rows = (
            client.table("catalog_items").select(_COLS).eq("org_id", org_id)
            .eq("id", item_id).limit(1).execute().data
        )
        return rows[0] if rows else None
    res = (
        client.table("catalog_items").update(fields).eq("org_id", org_id)
        .eq("id", item_id).execute()
    )
    return res.data[0] if res.data else None


@router.patch("/{item_id}")
async def update_catalog(
    item_id: str, payload: CatalogItemUpsert, user: CurrentUser = Depends(require_org)
) -> dict:
    row = await run_in_threadpool(_update, user.org_id, item_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    return row


@router.delete("/{item_id}")
async def delete_catalog(item_id: str, user: CurrentUser = Depends(require_org)) -> dict:
    def _delete() -> bool:
        client = get_service_client()
        res = (
            client.table("catalog_items").delete().eq("org_id", user.org_id)
            .eq("id", item_id).execute()
        )
        return bool(res.data)

    ok = await run_in_threadpool(_delete)
    if not ok:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    return {"success": True}
