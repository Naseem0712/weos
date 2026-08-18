"""Shared QR helper for WEOS PDFs.

The QR encodes an ABSOLUTE, public URL to the quote (``{base}/q/{ref}``) so that
scanning it on a phone fetches the quote from the database. It must never encode a
custom scheme (``weos://``), a localhost/``/tmp`` path, or a bare id — those do not
open on a phone.

Base URL resolution order (first non-empty wins):
1. ``WEOS_PUBLIC_BASE_URL`` env (explicit override)
2. ``RAILWAY_PUBLIC_DOMAIN`` env (Railway's public hostname)
3. ``payload['publicBaseUrl']`` (derived from the incoming request base URL)

If none resolve, a relative ``/q/{ref}`` path is used as a last resort (still far
better than a localhost/scheme URL, and works when scanned from the same origin).
"""

from __future__ import annotations

import io
import os
from typing import Any, Mapping
from urllib.parse import quote as _urlquote

_REF_KEYS = (
    "shareToken",
    "quoteShareToken",
    "quoteRef",
    "quoteId",
    "quoteNumber",
    "quotationId",
    "projectId",
)


def public_base_url(payload: Mapping[str, Any] | None = None) -> str:
    """Absolute base URL (no trailing slash) for public quote links, or ''."""
    env = (os.environ.get("WEOS_PUBLIC_BASE_URL") or "").strip()
    if env:
        return env.rstrip("/")
    dom = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    if dom:
        if not dom.startswith("http://") and not dom.startswith("https://"):
            dom = "https://" + dom
        return dom.rstrip("/")
    if payload:
        b = str(payload.get("publicBaseUrl") or "").strip()
        if b:
            return b.rstrip("/")
    return ""


def quote_ref(payload: Mapping[str, Any]) -> str:
    for k in _REF_KEYS:
        v = payload.get(k)
        if v:
            return str(v)
    return "WEOS"


def quote_url(payload: Mapping[str, Any]) -> str:
    """Absolute (or relative fallback) URL that opens the quote when scanned.

    Optional ``qrSuffix`` on the payload appends a path (e.g. ``ledger`` →
    ``/q/{ref}/ledger``) so an advance slip can open the customer account.
    """
    ref = _urlquote(quote_ref(payload), safe="")
    extra = str(payload.get("qrSuffix") or "").strip().strip("/")
    path = f"/q/{ref}" + (f"/{extra}" if extra else "")
    base = public_base_url(payload)
    return f"{base}{path}" if base else path


def qr_png(data: str) -> bytes | None:
    try:
        import qrcode

        img = qrcode.make(data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def draw_quote_qr(
    c: Any,
    payload: Mapping[str, Any],
    *,
    x: float,
    y: float,
    size: float = 64.0,
    label: str = "Scan to view quote",
) -> bool:
    """Draw a labelled QR (encoding the absolute quote URL) at (x, y). Best-effort."""
    try:
        from reportlab.lib.utils import ImageReader

        png = qr_png(quote_url(payload))
        if not png:
            return False
        img = ImageReader(io.BytesIO(png))
        c.drawImage(img, x, y, width=size, height=size, mask="auto")
        if label:
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.35, 0.35, 0.35)
            c.drawCentredString(x + size / 2.0, y - 9, label)
            c.setFillColorRGB(0, 0, 0)
        return True
    except Exception:
        return False
