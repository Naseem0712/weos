"""Stamp / signature image assets for company + customer documents.

Persisted as durable blobs (same pattern as company logo) with a filesystem
cache under ``data_dir()/company`` or ``data_dir()/customers/{slug}``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from WEOS.paths import data_dir

_log = logging.getLogger("weos.media_assets")

Kind = Literal["stamp", "signature"]
Owner = Literal["company", "customer"]

_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/gif": ".gif",
}


def _slug(name: str) -> str:
    import re

    s = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "customer"


def _owner_dir(owner: Owner, customer: str | None = None) -> Path:
    if owner == "company":
        d = data_dir() / "company"
    else:
        d = data_dir() / "customers" / _slug(customer or "customer")
    d.mkdir(parents=True, exist_ok=True)
    return d


def blob_key(owner: Owner, kind: Kind, customer: str | None = None) -> str:
    if owner == "company":
        return f"company:{kind}"
    return f"customer:{_slug(customer or 'customer')}:{kind}"


def save_media(
    raw: bytes,
    *,
    owner: Owner,
    kind: Kind,
    customer: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    if not raw:
        raise ValueError("Empty upload")
    if kind not in ("stamp", "signature"):
        raise ValueError("kind must be stamp or signature")
    ct = (content_type or "").lower() or None
    ext = _EXT.get(ct or "")
    if not ext and filename:
        suffix = Path(filename).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}:
            ext = ".jpg" if suffix == ".jpeg" else suffix
            if not ct:
                ct = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".webp": "image/webp",
                    ".svg": "image/svg+xml",
                    ".gif": "image/gif",
                }.get(ext)
    ext = ext or ".png"
    ct = ct or "image/png"
    folder = _owner_dir(owner, customer)
    for old in folder.glob(f"{kind}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = folder / f"{kind}{ext}"
    dest.write_bytes(raw)
    key = blob_key(owner, kind, customer)
    try:
        from WEOS.db.durable_store import put_blob

        put_blob(
            key,
            kind=f"{owner}_{kind}",
            raw=raw,
            content_type=ct,
            filename=dest.name,
            payload={"owner": owner, "kind": kind, "customer": customer},
        )
    except Exception:
        _log.exception("%s %s DB put failed", owner, kind)
    url = (
        f"/api/company/{kind}"
        if owner == "company"
        else f"/api/customers/{_slug(customer or '')}/{kind}"
    )
    return {"ok": True, "kind": kind, "owner": owner, "path": str(dest), "url": url, "contentType": ct}


def _ensure_cache(owner: Owner, kind: Kind, customer: str | None = None) -> Path | None:
    folder = _owner_dir(owner, customer)
    existing = list(folder.glob(f"{kind}.*"))
    if existing:
        return existing[0]
    try:
        from WEOS.db.durable_store import get_blob

        raw, content_type, filename = get_blob(blob_key(owner, kind, customer))
    except Exception:
        return None
    if not raw:
        return None
    ext = Path(filename).suffix.lower() if filename else None
    if not ext and content_type:
        ext = _EXT.get(content_type.lower())
    ext = ext or ".png"
    dest = folder / f"{kind}{ext}"
    try:
        dest.write_bytes(raw)
        return dest
    except OSError:
        return None


def media_file(owner: Owner, kind: Kind, customer: str | None = None) -> Path | None:
    return _ensure_cache(owner, kind, customer)


def media_bytes(owner: Owner, kind: Kind, customer: str | None = None) -> tuple[bytes | None, str | None]:
    path = media_file(owner, kind, customer)
    if not path or not path.is_file():
        return None, None
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")
    try:
        return path.read_bytes(), mime
    except OSError:
        return None, None


def draw_stamp_signature_block(
    c,
    *,
    x: float,
    y: float,
    width: float,
    company_name: str = "",
    customer_name: str = "",
    stamp_path: str | Path | None = None,
    signature_path: str | Path | None = None,
    left_label: str = "Authorized Signatory",
    right_label: str = "Received by / Customer",
) -> float:
    """Draw a bottom stamp+signature block. ``y`` is the top of the block; returns bottom y."""
    from reportlab.lib.utils import ImageReader

    col_w = (width - 20) / 2.0
    left_x = x
    right_x = x + col_w + 20
    img_h = 48.0
    img_w_max = min(col_w - 8, 120.0)

    def _draw_img(path: str | Path | None, cx: float, cy: float) -> None:
        if not path:
            return
        p = Path(path)
        if not p.is_file():
            return
        try:
            img = ImageReader(str(p))
            iw, ih = img.getSize()
            if iw <= 0 or ih <= 0:
                return
            scale = min(img_w_max / float(iw), img_h / float(ih))
            dw, dh = iw * scale, ih * scale
            c.drawImage(img, cx, cy - dh, width=dw, height=dh, mask="auto")
        except Exception:
            pass

    _draw_img(stamp_path, left_x + 4, y)
    _draw_img(signature_path, right_x + 4, y)

    c.setStrokeColorRGB(0.55, 0.55, 0.55)
    c.setLineWidth(0.6)
    line_y = y - img_h - 6
    c.line(left_x, line_y, left_x + col_w - 10, line_y)
    c.line(right_x, line_y, right_x + col_w - 10, line_y)
    c.setFillColorRGB(0.25, 0.25, 0.25)
    c.setFont("Helvetica", 8)
    c.drawString(left_x, line_y - 12, left_label)
    c.drawString(right_x, line_y - 12, right_label)
    if company_name:
        c.setFont("Helvetica", 7)
        c.drawString(left_x, line_y - 24, str(company_name)[:40])
    if customer_name:
        c.setFont("Helvetica", 7)
        c.drawString(right_x, line_y - 24, str(customer_name)[:40])
    return line_y - 32


def resolve_doc_images(
    *,
    customer: str | None = None,
) -> dict[str, Path | None]:
    """Company stamp+sign for authorized block; customer stamp+sign when available."""
    co_stamp = media_file("company", "stamp")
    co_sign = media_file("company", "signature")
    cu_stamp = media_file("customer", "stamp", customer) if customer else None
    cu_sign = media_file("customer", "signature", customer) if customer else None
    return {
        "companyStamp": co_stamp,
        "companySignature": co_sign,
        "customerStamp": cu_stamp,
        "customerSignature": cu_sign,
        # Convenience for authorized (left) / received (right). Keep company
        # signature on the company side; never mirror it into the customer side.
        "authImage": co_sign or co_stamp,
        "recvImage": cu_sign or cu_stamp,
    }
