"""Post-approval project pack — process updates, bills, warranty, challan, photos.

Durable Postgres blobs + JSON metadata, scoped to company GST + customer/quote.
Hidden from the public scan page until the quote is approved (or an advance
auto-approved it).
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Mapping

from WEOS.factory.ledger_store import CONFIRMED_STATUSES

_log = logging.getLogger("weos.project_pack")

PACK_FILE_KINDS = ("bill", "warranty", "challan", "photo")
PACK_KINDS = ("update",) + PACK_FILE_KINDS
MAX_BYTES = 15 * 1024 * 1024

_KIND_ALIASES = {
    "update": "update",
    "note": "update",
    "process": "update",
    "process_update": "update",
    "bill": "bill",
    "bills": "bill",
    "invoice": "bill",
    "warranty": "warranty",
    "warranty_card": "warranty",
    "challan": "challan",
    "delivery": "challan",
    "delivery_challan": "challan",
    "photo": "photo",
    "photos": "photo",
    "process_photo": "photo",
    "image": "photo",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_gst(value: Any) -> str:
    try:
        from WEOS.factory.company_store import normalise_gstin

        return normalise_gstin(str(value or ""))
    except Exception:
        return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def meta_key(project_id: str) -> str:
    return f"project_pack:{(project_id or '').strip()}"


def blob_key(project_id: str, item_id: str) -> str:
    return f"project_pack_blob:{(project_id or '').strip()}:{item_id}"


def normalise_kind(raw: Any) -> str:
    key = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _KIND_ALIASES.get(key, "")


def is_quote_approved(doc: Mapping[str, Any] | None, *, advances: list[Any] | None = None) -> bool:
    if not isinstance(doc, Mapping):
        return False
    st = str(doc.get("status") or "").strip().lower()
    if st in CONFIRMED_STATUSES:
        return True
    if advances:
        return True
    return False


def _empty_meta(doc: Mapping[str, Any] | None = None) -> dict[str, Any]:
    doc = doc if isinstance(doc, Mapping) else {}
    return {
        "projectId": str(doc.get("projectId") or "").strip(),
        "companyGst": _norm_gst(doc.get("companyGst")),
        "customer": str(doc.get("customer") or "").strip(),
        "quoteId": str(doc.get("quotationId") or doc.get("quoteNumber") or doc.get("quoteId") or "").strip(),
        "items": [],
        "updatedAt": _now(),
    }


def _load_meta(project_id: str) -> dict[str, Any]:
    try:
        from WEOS.db.durable_store import get_json

        row = get_json(meta_key(project_id))
        if isinstance(row, dict):
            items = list(row.get("items") or [])
            row["items"] = [it for it in items if isinstance(it, dict)]
            return row
    except Exception:
        _log.debug("project pack meta load skipped", exc_info=True)
    return _empty_meta({"projectId": project_id})


def _save_meta(meta: dict[str, Any]) -> bool:
    meta["updatedAt"] = _now()
    try:
        from WEOS.db.durable_store import put_json

        return bool(put_json(meta_key(str(meta.get("projectId") or "")), "project_pack", meta))
    except Exception:
        _log.exception("project pack meta save failed")
        return False


def _assert_gst_scope(doc: Mapping[str, Any], company_gst: str | None) -> None:
    want = _norm_gst(company_gst)
    if not want:
        return
    got = _norm_gst(doc.get("companyGst"))
    if got and got != want:
        raise PermissionError("Project does not belong to this GST workspace")


def _load_project(project_id: str) -> dict[str, Any]:
    from WEOS.factory.project_store import load_project

    return load_project(project_id)


def _require_approved(doc: Mapping[str, Any]) -> None:
    advances = None
    try:
        from WEOS.factory.ledger_store import list_advances

        cust = str(doc.get("customer") or "").strip()
        pid = str(doc.get("projectId") or "").strip()
        if cust and pid:
            advances = [
                a
                for a in list_advances(cust)
                if str(a.get("projectId") or "") == pid
            ]
    except Exception:
        advances = None
    if not is_quote_approved(doc, advances=advances):
        raise PermissionError("Project pack is available after the quote is approved")


def list_pack(project_id: str, *, company_gst: str | None = None) -> dict[str, Any]:
    doc = _load_project(project_id)
    _assert_gst_scope(doc, company_gst)
    meta = _load_meta(project_id)
    if not meta.get("projectId"):
        meta["projectId"] = str(doc.get("projectId") or project_id)
    if not meta.get("customer"):
        meta["customer"] = str(doc.get("customer") or "")
    if not meta.get("companyGst"):
        meta["companyGst"] = _norm_gst(doc.get("companyGst"))
    if not meta.get("quoteId"):
        meta["quoteId"] = str(doc.get("quotationId") or doc.get("quoteNumber") or "")
    approved = is_quote_approved(doc)
    items = list(meta.get("items") or [])
    return {
        "ok": True,
        "projectId": meta.get("projectId") or project_id,
        "customer": meta.get("customer"),
        "companyGst": meta.get("companyGst"),
        "quoteId": meta.get("quoteId"),
        "approved": approved,
        "status": str(doc.get("status") or "draft"),
        "updates": [it for it in items if it.get("kind") == "update"],
        "documents": [it for it in items if it.get("kind") in PACK_FILE_KINDS and it.get("kind") != "photo"],
        "photos": [it for it in items if it.get("kind") == "photo"],
        "items": items,
        "updatedAt": meta.get("updatedAt"),
    }


def add_update(
    project_id: str,
    text: str,
    *,
    date: str | None = None,
    company_gst: str | None = None,
) -> dict[str, Any]:
    note = str(text or "").strip()
    if not note:
        raise ValueError("Process update text is required")
    doc = _load_project(project_id)
    _assert_gst_scope(doc, company_gst)
    _require_approved(doc)
    meta = _load_meta(project_id)
    meta.update({k: v for k, v in _empty_meta(doc).items() if k != "items" and not meta.get(k)})
    item = {
        "id": secrets.token_urlsafe(10),
        "kind": "update",
        "text": note,
        "date": (date or "").strip() or _now()[:10],
        "createdAt": _now(),
    }
    items = list(meta.get("items") or [])
    items.append(item)
    meta["items"] = items
    if not _save_meta(meta):
        raise RuntimeError("Could not persist process update (database unavailable)")
    return item


def add_file(
    project_id: str,
    *,
    kind: str,
    raw: bytes,
    filename: str | None = None,
    content_type: str | None = None,
    note: str | None = None,
    date: str | None = None,
    company_gst: str | None = None,
) -> dict[str, Any]:
    k = normalise_kind(kind)
    if k not in PACK_FILE_KINDS:
        raise ValueError("kind must be bill, warranty, challan, or photo")
    if not raw:
        raise ValueError("Empty upload")
    if len(raw) > MAX_BYTES:
        raise ValueError("File too large (max 15 MB)")
    doc = _load_project(project_id)
    _assert_gst_scope(doc, company_gst)
    _require_approved(doc)
    ct = (content_type or "").split(";")[0].strip().lower() or "application/octet-stream"
    if k == "photo" and not ct.startswith("image/"):
        raise ValueError("Process photos must be images")
    if k != "photo" and not (ct.startswith("image/") or ct == "application/pdf"):
        raise ValueError("Bills / warranty / challan must be PDF or image")
    item_id = secrets.token_urlsafe(10)
    meta = _load_meta(project_id)
    meta.update({k2: v for k2, v in _empty_meta(doc).items() if k2 != "items" and not meta.get(k2)})
    item = {
        "id": item_id,
        "kind": k,
        "filename": (filename or f"{k}.bin").strip() or f"{k}.bin",
        "contentType": ct,
        "note": str(note or "").strip(),
        "date": (date or "").strip() or _now()[:10],
        "createdAt": _now(),
        "url": f"/api/projects/{project_id}/pack/files/{item_id}",
        "publicUrl": None,
    }
    try:
        from WEOS.db.durable_store import put_blob

        ok = put_blob(
            blob_key(project_id, item_id),
            kind=f"project_pack_{k}",
            raw=raw,
            content_type=ct,
            filename=item["filename"],
            payload={
                "projectId": project_id,
                "itemId": item_id,
                "kind": k,
                "companyGst": _norm_gst(doc.get("companyGst")),
                "customer": doc.get("customer"),
            },
        )
        if not ok:
            raise RuntimeError("Could not persist file (database unavailable)")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not persist file: {exc}") from exc
    items = list(meta.get("items") or [])
    items.append(item)
    meta["items"] = items
    if not _save_meta(meta):
        raise RuntimeError("Could not persist pack metadata")
    return item


def delete_item(project_id: str, item_id: str, *, company_gst: str | None = None) -> dict[str, Any]:
    doc = _load_project(project_id)
    _assert_gst_scope(doc, company_gst)
    meta = _load_meta(project_id)
    iid = str(item_id or "").strip()
    items = [it for it in (meta.get("items") or []) if str(it.get("id") or "") != iid]
    if len(items) == len(meta.get("items") or []):
        raise FileNotFoundError(f"Pack item not found: {item_id}")
    meta["items"] = items
    try:
        from WEOS.db.durable_store import delete_key

        delete_key(blob_key(project_id, iid))
    except Exception:
        _log.debug("pack blob delete skipped", exc_info=True)
    _save_meta(meta)
    return {"ok": True, "deleted": iid}


def get_file(project_id: str, item_id: str) -> tuple[bytes | None, str | None, str | None, dict[str, Any] | None]:
    meta = _load_meta(project_id)
    item = next((it for it in (meta.get("items") or []) if str(it.get("id") or "") == str(item_id)), None)
    if not item:
        return None, None, None, None
    try:
        from WEOS.db.durable_store import get_blob

        raw, ct, fname = get_blob(blob_key(project_id, str(item_id)))
    except Exception:
        return None, None, None, item
    return raw, ct or item.get("contentType"), fname or item.get("filename"), item


def public_pack_payload(
    doc: Mapping[str, Any] | None,
    *,
    share_token: str | None = None,
    approved: bool | None = None,
) -> dict[str, Any]:
    """Customer-safe pack for the public scan page."""
    doc = doc if isinstance(doc, Mapping) else {}
    pid = str(doc.get("projectId") or "").strip()
    ok_approved = bool(approved) if approved is not None else is_quote_approved(doc)
    if not pid or not ok_approved:
        return {
            "available": False,
            "reason": "Available after approval" if pid else "",
            "updates": [],
            "documents": [],
            "photos": [],
        }
    meta = _load_meta(pid)
    token = (share_token or "").strip()
    updates, documents, photos = [], [], []
    for it in meta.get("items") or []:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "")
        pub = {
            "id": it.get("id"),
            "kind": kind,
            "text": it.get("text") or "",
            "note": it.get("note") or "",
            "date": it.get("date") or (str(it.get("createdAt") or "")[:10]),
            "filename": it.get("filename") or "",
            "contentType": it.get("contentType") or "",
            "createdAt": it.get("createdAt"),
        }
        if token and kind in PACK_FILE_KINDS:
            pub["url"] = f"/api/public/quote/{token}/pack/files/{it.get('id')}"
        elif kind in PACK_FILE_KINDS:
            pub["url"] = it.get("url") or f"/api/projects/{pid}/pack/files/{it.get('id')}"
        if kind == "update":
            updates.append(pub)
        elif kind == "photo":
            photos.append(pub)
        elif kind in PACK_FILE_KINDS:
            documents.append(pub)
    updates.sort(key=lambda r: str(r.get("date") or r.get("createdAt") or ""))
    documents.sort(key=lambda r: str(r.get("createdAt") or ""))
    photos.sort(key=lambda r: str(r.get("createdAt") or ""))
    return {
        "available": True,
        "updates": updates,
        "documents": documents,
        "photos": photos,
        "updateCount": len(updates),
        "documentCount": len(documents),
        "photoCount": len(photos),
    }
