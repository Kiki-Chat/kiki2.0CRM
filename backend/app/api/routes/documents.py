import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_org
from app.db.supabase_client import get_service_client

router = APIRouter(prefix="/api/customers", tags=["documents"])

BUCKET = "customer-files"
MAX_BYTES = 10 * 1024 * 1024


def _signed_url(client, path: str) -> str | None:
    try:
        res = client.storage.from_(BUCKET).create_signed_url(path, 3600)
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
        return None
    except Exception:
        return None


def _list(org_id: str, customer_id: str) -> list[dict]:
    client = get_service_client()
    rows = (
        client.table("documents")
        .select("*")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .order("uploaded_at", desc=True)
        .execute()
        .data
        or []
    )
    for d in rows:
        d["url"] = _signed_url(client, d["path"])
    return rows


def _upload(
    org_id: str,
    customer_id: str,
    filename: str,
    content: bytes,
    content_type: str | None,
    category: str | None,
) -> dict:
    client = get_service_client()
    is_image = bool(content_type and content_type.startswith("image/"))
    safe = (filename or "datei").replace("/", "_")
    path = f"{org_id}/{customer_id}/{uuid.uuid4().hex}_{safe}"
    client.storage.from_(BUCKET).upload(
        path, content, {"content-type": content_type or "application/octet-stream"}
    )
    row = (
        client.table("documents")
        .insert(
            {
                "org_id": org_id,
                "customer_id": customer_id,
                "name": filename,
                "path": path,
                "category": category,
                "mime_type": content_type,
                "size_bytes": len(content),
                "is_image": is_image,
            }
        )
        .execute()
        .data[0]
    )
    row["url"] = _signed_url(client, path)
    return row


@router.get("/{customer_id}/documents")
async def list_documents(
    customer_id: str, user: CurrentUser = Depends(require_org)
) -> list[dict]:
    return await run_in_threadpool(_list, user.org_id, customer_id)


@router.post("/{customer_id}/documents")
async def upload_document(
    customer_id: str,
    file: UploadFile = File(...),
    category: str | None = Form(default=None),
    user: CurrentUser = Depends(require_org),
) -> dict:
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Datei zu groß (max 10MB)")
    return await run_in_threadpool(
        _upload, user.org_id, customer_id, file.filename, content, file.content_type, category
    )
