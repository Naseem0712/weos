"""Company profile store — single company identity used across all quotes.

Persisted to Postgres (``durable_records``) when DATABASE_URL is available, with
a local filesystem cache under ``data_dir()/company`` for fast reads and offline
dev. Company name renders in UPPERCASE on documents.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import data_dir, website_dir

_log = logging.getLogger("weos.company_store")

_COMPANY_KEY = "company:profile"
_LOGO_KEY = "company:logo"

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
        "persisted": False,
    }


def _read_file() -> dict[str, Any] | None:
    path = company_path()
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def _write_file(doc: dict[str, Any]) -> None:
    company_path().write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _db_put(doc: dict[str, Any]) -> bool:
    try:
        from WEOS.db.durable_store import put_json

        clean = {k: v for k, v in doc.items() if k != "persisted"}
        return put_json(_COMPANY_KEY, "company", clean)
    except Exception:
        _log.exception("company DB put failed")
        return False


def _db_get() -> dict[str, Any] | None:
    try:
        from WEOS.db.durable_store import get_json

        payload = get_json(_COMPANY_KEY)
        return payload if isinstance(payload, dict) else None
    except Exception:
        _log.exception("company DB get failed")
        return None


def load_company() -> dict[str, Any]:
    """Load company profile — prefer durable DB, then filesystem cache."""
    base = _empty()
    db_doc = _db_get()
    file_doc = _read_file()
    source = None
    if db_doc:
        base.update(db_doc)
        source = "db"
        # Keep filesystem cache warm for logo_file / PDF paths.
        try:
            _write_file({k: v for k, v in base.items() if k != "persisted"})
        except Exception:
            pass
        _ensure_logo_cache()
    elif file_doc:
        base.update(file_doc)
        source = "file"
        # Migrate legacy file → DB when possible.
        if _db_put(base):
            source = "file+migrated"
    base["persisted"] = source in ("db", "file+migrated")
    base["storage"] = source or "empty"
    return base


def save_company(payload: Mapping[str, Any]) -> dict[str, Any]:
    doc = load_company()
    for key in _FIELDS:
        if key in payload and payload[key] is not None:
            doc[key] = str(payload[key])
    if payload.get("logoPath") is not None:
        doc["logoPath"] = str(payload["logoPath"]) or None
    if payload.get("logoUrl") is not None:
        doc["logoUrl"] = str(payload["logoUrl"]) or None
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    clean = {k: v for k, v in doc.items() if k not in ("persisted", "storage")}
    _write_file(clean)
    ok = _db_put(clean)
    doc["persisted"] = ok
    doc["storage"] = "db" if ok else "file"
    if not ok:
        _log.warning("Company saved to filesystem only — set DATABASE_URL for durable storage")
    return doc


def save_logo(raw: bytes, filename: str | None = None, content_type: str | None = None) -> dict[str, Any]:
    ext = None
    ct = (content_type or "").lower() or None
    if ct and ct in _LOGO_EXT:
        ext = _LOGO_EXT[ct]
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
    for old in company_dir().glob("logo.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = company_dir() / f"logo{ext}"
    dest.write_bytes(raw)
    try:
        from WEOS.db.durable_store import put_blob

        put_blob(
            _LOGO_KEY,
            kind="company_logo",
            raw=raw,
            content_type=ct,
            filename=f"logo{ext}",
            payload={"ext": ext},
        )
    except Exception:
        _log.exception("company logo DB put failed")
    doc = load_company()
    doc["logoPath"] = str(dest)
    doc["logoUrl"] = "/api/company/logo"
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    clean = {k: v for k, v in doc.items() if k not in ("persisted", "storage")}
    _write_file(clean)
    _db_put(clean)
    return doc


def _ensure_logo_cache() -> Path | None:
    """If DB has a logo blob and the filesystem cache is empty, restore it."""
    existing = list(company_dir().glob("logo.*"))
    if existing:
        return existing[0]
    try:
        from WEOS.db.durable_store import get_blob

        raw, content_type, filename = get_blob(_LOGO_KEY)
    except Exception:
        return None
    if not raw:
        return None
    ext = None
    if filename:
        ext = Path(filename).suffix.lower() or None
    if not ext and content_type:
        ext = _LOGO_EXT.get(content_type.lower())
    ext = ext or ".png"
    dest = company_dir() / f"logo{ext}"
    try:
        dest.write_bytes(raw)
        return dest
    except OSError:
        return None


def default_logo_file() -> Path | None:
    """The bundled WEOS brand logo shipped in the website dir (served at
    /static/weos-logo.png). Used as the default app + PDF logo when the company
    has not uploaded their own."""
    for cand in (website_dir() / "weos-logo.png", website_dir() / "weos-logo.svg"):
        if cand.is_file():
            return cand
    return None


def logo_file() -> Path | None:
    """Effective logo: the company's uploaded logo when present, else the bundled
    WEOS default. Company upload always overrides the default."""
    _ensure_logo_cache()
    doc = load_company()
    p = doc.get("logoPath")
    if p and Path(p).is_file():
        return Path(p)
    for cand in company_dir().glob("logo.*"):
        return cand
    return default_logo_file()


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


def bootstrap_company() -> dict[str, Any]:
    """On boot: rehydrate filesystem cache from DB (or migrate file → DB)."""
    doc = load_company()
    _ensure_logo_cache()
    return {"ok": True, "storage": doc.get("storage"), "hasName": bool((doc.get("companyName") or "").strip())}
