"""Company profile store — single company identity used across all quotes.

Persisted JSON (never hardcoded). Company details (name, address, GST, website,
phone, email, logo) are saved once and auto-applied to every quotation header /
PDF branding. Company name renders in UPPERCASE on documents.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import data_dir

_LOGO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/gif": ".gif",
}

_FIELDS = (
    "companyName",
    "address",
    "website",
    "gstNo",
    "phone",
    "email",
    "tagline",
    "state",
    "stateCode",
    "pan",
    "bankDetails",
    "cin",
    "terms",
)


def company_dir() -> Path:
    d = data_dir() / "company"
    d.mkdir(parents=True, exist_ok=True)
    return d


def company_path() -> Path:
    return company_dir() / "profile.json"


def _empty() -> dict[str, Any]:
    return {
        "companyName": "",
        "address": "",
        "website": "",
        "gstNo": "",
        "phone": "",
        "email": "",
        "tagline": "Design • Calculate • Manufacture • Quote",
        "state": "",
        "stateCode": "",
        "pan": "",
        "bankDetails": "",
        "cin": "",
        "terms": "",
        "logoPath": None,
        "logoUrl": None,
        "updatedAt": None,
    }


def load_company() -> dict[str, Any]:
    path = company_path()
    if not path.is_file():
        return _empty()
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return _empty()
    base = _empty()
    base.update(doc)
    return base


def save_company(payload: Mapping[str, Any]) -> dict[str, Any]:
    doc = load_company()
    for key in _FIELDS:
        if key in payload and payload[key] is not None:
            doc[key] = str(payload[key])
    # allow explicit logo path/url pass-through
    if payload.get("logoPath") is not None:
        doc["logoPath"] = str(payload["logoPath"]) or None
    if payload.get("logoUrl") is not None:
        doc["logoUrl"] = str(payload["logoUrl"]) or None
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    company_path().write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def save_logo(raw: bytes, filename: str | None = None, content_type: str | None = None) -> dict[str, Any]:
    ext = None
    if content_type and content_type.lower() in _LOGO_EXT:
        ext = _LOGO_EXT[content_type.lower()]
    if not ext and filename:
        suffix = Path(filename).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}:
            ext = ".jpg" if suffix == ".jpeg" else suffix
    ext = ext or ".png"
    # Clean out old logo files so only one remains
    for old in company_dir().glob("logo.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = company_dir() / f"logo{ext}"
    dest.write_bytes(raw)
    doc = load_company()
    doc["logoPath"] = str(dest)
    doc["logoUrl"] = "/api/company/logo"
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    company_path().write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def logo_file() -> Path | None:
    doc = load_company()
    p = doc.get("logoPath")
    if p and Path(p).is_file():
        return Path(p)
    for cand in company_dir().glob("logo.*"):
        return cand
    return None


def logo_data_url() -> str | None:
    lf = logo_file()
    if not lf:
        return None
    try:
        raw = lf.read_bytes()
    except OSError:
        return None
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".gif": "image/gif",
    }.get(lf.suffix.lower(), "image/png")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def company_branding() -> dict[str, Any]:
    """Branding dict for PDF templates. Company name in UPPERCASE for headers."""
    doc = load_company()
    name = (doc.get("companyName") or "").strip()
    branding: dict[str, Any] = {}
    if name:
        branding["companyName"] = name.upper()
        branding["logoText"] = name.upper()
    for key in (
        "address", "website", "phone", "email", "tagline", "gstNo",
        "state", "stateCode", "pan", "bankDetails", "cin", "terms",
    ):
        val = (doc.get(key) or "").strip()
        if val:
            branding[key] = val
    lf = logo_file()
    if lf:
        branding["logoPath"] = str(lf)
    return branding
