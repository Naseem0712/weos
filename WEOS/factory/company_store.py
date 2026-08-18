"""Company profile store — seller identity keyed by GSTIN (multi-tenant).

Persisted to Postgres (``durable_records``) when DATABASE_URL is available, with
a local filesystem cache under ``data_dir()/company`` for fast reads and offline
dev. Company name renders in UPPERCASE on documents.

* ``company:gst:{GSTIN}`` — durable per-workspace seller profile (source of truth)
* ``company:profile`` — active workspace mirror (PDF branding / legacy API)
* ``company:active_gst`` — which GSTIN is currently open
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import data_dir, website_dir

_log = logging.getLogger("weos.company_store")

_COMPANY_KEY = "company:profile"
_ACTIVE_GST_KEY = "company:active_gst"
_LOGO_KEY = "company:logo"


def normalise_gstin(gst: str | None) -> str:
    """Uppercase alphanumeric GSTIN (strip spaces / dashes). Empty if blank."""
    raw = re.sub(r"[^A-Za-z0-9]", "", (gst or "").strip()).upper()
    return raw


def company_gst_key(gst: str) -> str:
    g = normalise_gstin(gst)
    if not g:
        raise ValueError("GSTIN required")
    return f"company:gst:{g}"


def hash_delete_pin(pin: str, gst: str | None = None) -> str:
    """SHA-256 of company delete PIN (GST-scoped). Never store the PIN itself."""
    g = normalise_gstin(gst)
    raw = f"weos-delete-pin|{g}|{str(pin or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_delete_pin(gst: str, pin: str | None) -> bool:
    """True when the typed PIN matches the stored company delete PIN."""
    g = normalise_gstin(gst)
    typed = str(pin or "").strip()
    if not g or not typed:
        return False
    doc = load_company_by_gst(g) or {}
    stored = str(doc.get("deletePinHash") or "").strip()
    if not stored:
        return False
    return stored == hash_delete_pin(typed, g)


def company_has_delete_pin(gst: str | None = None, doc: Mapping[str, Any] | None = None) -> bool:
    if isinstance(doc, Mapping) and doc.get("deletePinHash"):
        return True
    g = normalise_gstin(gst or (doc or {}).get("gstNo") if isinstance(doc, Mapping) else gst)
    if not g:
        return False
    row = load_company_by_gst(g) or {}
    return bool(str(row.get("deletePinHash") or "").strip())


def hash_login_pin(pin: str, gst: str | None = None) -> str:
    """SHA-256 of the 4-digit company login PIN. Never store the PIN itself."""
    g = normalise_gstin(gst)
    raw = f"weos-login-pin|{g}|{str(pin or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalise_login_pin(pin: str | None) -> str:
    digits = re.sub(r"\D", "", str(pin or ""))
    return digits


def validate_login_pin(pin: str | None) -> str:
    digits = normalise_login_pin(pin)
    if len(digits) != 4:
        raise ValueError("Company login PIN must be exactly 4 digits")
    return digits


def verify_login_pin(gst: str, pin: str | None) -> bool:
    g = normalise_gstin(gst)
    try:
        typed = validate_login_pin(pin)
    except ValueError:
        return False
    if not g:
        return False
    doc = load_company_by_gst(g) or {}
    stored = str(doc.get("loginPinHash") or "").strip()
    if not stored:
        return False
    return stored == hash_login_pin(typed, g)


def company_has_login_pin(gst: str | None = None, doc: Mapping[str, Any] | None = None) -> bool:
    if isinstance(doc, Mapping) and str(doc.get("loginPinHash") or "").strip():
        return True
    g = normalise_gstin(gst or ((doc or {}).get("gstNo") if isinstance(doc, Mapping) else gst))
    if not g:
        return False
    row = load_company_by_gst(g) or {}
    return bool(str(row.get("loginPinHash") or "").strip())


def hash_session_token(token: str, gst: str | None = None) -> str:
    g = normalise_gstin(gst)
    raw = f"weos-ws-session|{g}|{str(token or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def public_company_profile(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """Company payload safe for API / UI — never includes PIN hashes or sessions."""
    out = dict(doc or {})
    has_del = bool(str(out.get("deletePinHash") or "").strip() or out.get("hasDeletePin"))
    has_login = bool(str(out.get("loginPinHash") or "").strip() or out.get("hasLoginPin"))
    email = str(out.get("email") or "").strip()
    out.pop("deletePinHash", None)
    out.pop("deletePin", None)
    out.pop("loginPinHash", None)
    out.pop("loginPin", None)
    out.pop("pin", None)
    out.pop("loginSessions", None)
    out.pop("pinResetHash", None)
    out.pop("pinResetExpiresAt", None)
    out.pop("pinResetSentTo", None)
    out["hasDeletePin"] = has_del
    out["hasLoginPin"] = has_login
    out["hasEmail"] = bool(email)
    return out

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
    "pdfBrand",
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
        "pdfBrand": "",
        "logoPath": None,
        "logoUrl": None,
        "hasDeletePin": False,
        "hasLoginPin": False,
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


def _db_put(doc: dict[str, Any], *, key: str = _COMPANY_KEY) -> bool:
    try:
        from WEOS.db.durable_store import put_json

        clean = {k: v for k, v in doc.items() if k not in ("persisted", "storage")}
        return put_json(key, "company", clean)
    except Exception:
        _log.exception("company DB put failed")
        return False


def _db_get(key: str = _COMPANY_KEY) -> dict[str, Any] | None:
    try:
        from WEOS.db.durable_store import get_json

        payload = get_json(key)
        return payload if isinstance(payload, dict) else None
    except Exception:
        _log.exception("company DB get failed")
        return None


def get_active_gst() -> str | None:
    try:
        from WEOS.db.durable_store import get_json

        payload = get_json(_ACTIVE_GST_KEY)
        if isinstance(payload, dict):
            g = normalise_gstin(payload.get("gstNo"))
            return g or None
    except Exception:
        pass
    # Fall back to active profile GST.
    doc = _db_get(_COMPANY_KEY) or _read_file() or {}
    g = normalise_gstin(doc.get("gstNo") if isinstance(doc, dict) else "")
    return g or None


def set_active_gst(gst: str) -> str:
    g = normalise_gstin(gst)
    if not g:
        raise ValueError("GSTIN required")
    try:
        from WEOS.db.durable_store import put_json

        put_json(_ACTIVE_GST_KEY, "company_active", {"gstNo": g})
    except Exception:
        _log.exception("set_active_gst failed")
    # Keep legacy active profile in sync for PDF /api/company.
    by_gst = load_company_by_gst(g)
    if by_gst:
        clean = {k: v for k, v in by_gst.items() if k not in ("persisted", "storage")}
        _write_file(clean)
        _db_put(clean, key=_COMPANY_KEY)
    return g


def load_company_by_gst(gst: str) -> dict[str, Any] | None:
    g = normalise_gstin(gst)
    if not g:
        return None
    payload = _db_get(company_gst_key(g))
    if isinstance(payload, dict):
        base = _empty()
        base.update(payload)
        base["gstNo"] = g
        base["persisted"] = True
        base["storage"] = "db"
        return base
    return None


def save_company_by_gst(gst: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    g = normalise_gstin(gst) or normalise_gstin(payload.get("gstNo"))
    if not g:
        raise ValueError("GSTIN required to save company workspace")
    doc = load_company_by_gst(g) or _empty()
    for key in _FIELDS:
        if key in payload and payload[key] is not None:
            doc[key] = str(payload[key])
    doc["gstNo"] = g
    if payload.get("logoPath") is not None:
        doc["logoPath"] = str(payload["logoPath"]) or None
    if payload.get("logoUrl") is not None:
        doc["logoUrl"] = str(payload["logoUrl"]) or None
    _apply_delete_pin(doc, payload, gst=g)
    _apply_login_pin(doc, payload, gst=g)
    for key in ("loginSessions", "pinResetHash", "pinResetExpiresAt", "pinResetSentTo"):
        if key in payload:
            doc[key] = payload[key]
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    clean = {
        k: v
        for k, v in doc.items()
        if k not in ("persisted", "storage", "hasDeletePin", "hasLoginPin", "hasEmail", "deletePin", "loginPin", "pin")
    }
    ok = _db_put(clean, key=company_gst_key(g))
    # Mirror to active profile + filesystem for branding.
    _write_file(clean)
    _db_put(clean, key=_COMPANY_KEY)
    try:
        from WEOS.db.durable_store import put_json

        put_json(_ACTIVE_GST_KEY, "company_active", {"gstNo": g})
    except Exception:
        pass
    doc["persisted"] = ok
    doc["storage"] = "db" if ok else "file"
    return public_company_profile(doc)


def load_company() -> dict[str, Any]:
    """Load active company profile — prefer GST workspace, then legacy key/file."""
    base = _empty()
    active_gst = get_active_gst()
    db_doc = load_company_by_gst(active_gst) if active_gst else None
    if db_doc is None:
        db_doc = _db_get()
    file_doc = _read_file()
    source = None
    if db_doc:
        base.update(db_doc)
        source = "db"
        # Keep filesystem cache warm for logo_file / PDF paths.
        try:
            _write_file({k: v for k, v in base.items() if k not in ("persisted", "storage")})
        except Exception:
            pass
        _ensure_logo_cache()
        # Promote legacy profile into GST key when GSTIN is present.
        g = normalise_gstin(base.get("gstNo"))
        if g and load_company_by_gst(g) is None:
            _db_put({k: v for k, v in base.items() if k not in ("persisted", "storage")}, key=company_gst_key(g))
            source = "db+promoted"
    elif file_doc:
        base.update(file_doc)
        source = "file"
        # Migrate legacy file → DB when possible.
        if _db_put(base):
            source = "file+migrated"
        g = normalise_gstin(base.get("gstNo"))
        if g:
            _db_put({k: v for k, v in base.items() if k not in ("persisted", "storage")}, key=company_gst_key(g))
    base["persisted"] = source in ("db", "file+migrated", "db+promoted")
    base["storage"] = source or "empty"
    if base.get("gstNo"):
        base["gstNo"] = normalise_gstin(base.get("gstNo"))
    base["hasDeletePin"] = bool(str(base.get("deletePinHash") or "").strip())
    base["hasLoginPin"] = bool(str(base.get("loginPinHash") or "").strip())
    return base


def _apply_delete_pin(doc: dict[str, Any], payload: Mapping[str, Any], *, gst: str) -> None:
    """Store hashed delete PIN; never persist the typed PIN."""
    if payload.get("clearDeletePin"):
        doc.pop("deletePinHash", None)
        doc["hasDeletePin"] = False
        return
    if "deletePin" not in payload or payload.get("deletePin") is None:
        return
    pin = str(payload.get("deletePin") or "").strip()
    if not pin:
        return
    doc["deletePinHash"] = hash_delete_pin(pin, gst)
    doc["hasDeletePin"] = True


def _apply_login_pin(doc: dict[str, Any], payload: Mapping[str, Any], *, gst: str) -> None:
    """Store hashed 4-digit login PIN; never persist the typed PIN."""
    if payload.get("clearLoginPin"):
        doc.pop("loginPinHash", None)
        doc["hasLoginPin"] = False
        return
    raw = payload.get("loginPin")
    if raw is None and "pin" in payload:
        raw = payload.get("pin")
    if raw is None:
        return
    pin = validate_login_pin(raw)
    doc["loginPinHash"] = hash_login_pin(pin, gst)
    doc["hasLoginPin"] = True


def save_company(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Save active company; when GSTIN present, also upsert the GST workspace."""
    gst = normalise_gstin(payload.get("gstNo") if payload.get("gstNo") is not None else None)
    if not gst:
        gst = normalise_gstin((load_company() or {}).get("gstNo") or "")
    if gst:
        return save_company_by_gst(gst, payload)

    doc = load_company()
    for key in _FIELDS:
        if key in payload and payload[key] is not None:
            doc[key] = str(payload[key])
    if payload.get("logoPath") is not None:
        doc["logoPath"] = str(payload["logoPath"]) or None
    if payload.get("logoUrl") is not None:
        doc["logoUrl"] = str(payload["logoUrl"]) or None
    _apply_delete_pin(doc, payload, gst="")
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    clean = {k: v for k, v in doc.items() if k not in ("persisted", "storage", "hasDeletePin", "deletePin")}
    _write_file(clean)
    ok = _db_put(clean)
    doc["persisted"] = ok
    doc["storage"] = "db" if ok else "file"
    if not ok:
        _log.warning("Company saved to filesystem only — set DATABASE_URL for durable storage")
    return public_company_profile(doc)


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


PDF_BRANDS = ("marqt", "woodenmax", "allkraft")
PDF_BRAND_LABELS = {
    "marqt": "MAR-QT Style",
    "woodenmax": "WoodenMax",
    "allkraft": "AllKraft",
}


def resolve_pdf_brand(doc: Mapping[str, Any] | None = None, *, gst: str | None = None) -> str:
    """Logged-in company's quote layout only — never a random other brand."""
    if not isinstance(doc, Mapping) or not doc:
        g = normalise_gstin(gst or "")
        doc = (load_company_by_gst(g) if g else None) or load_company() or {}
    raw = str(doc.get("pdfBrand") or doc.get("brand") or "").strip().lower().replace("-", "").replace(" ", "")
    if raw == "mar-qt":
        raw = "marqt"
    if raw in PDF_BRANDS:
        return raw
    blob = " ".join(
        str(doc.get(k) or "")
        for k in ("companyName", "name", "tagline", "gstNo")
    ).lower()
    if "woodenmax" in blob or "wooden max" in blob:
        return "woodenmax"
    if "allkraft" in blob or "all kraft" in blob or "allukraft" in blob:
        return "allkraft"
    if "mar-qt" in blob or "marqt" in blob:
        return "marqt"
    return "marqt"


def company_branding(gst: str | None = None) -> dict[str, Any]:
    """Branding dict for PDF templates. Company name in UPPERCASE for headers.

    When ``gst`` is set, prefer that workspace profile (quote's company GST)
    over the currently open hub — so ALLUKRAFT quotes never print WoodenMax.
    """
    doc: dict[str, Any] = {}
    g = normalise_gstin(gst or "")
    if g:
        by = load_company_by_gst(g)
        if isinstance(by, dict) and (by.get("companyName") or by.get("gstNo")):
            doc = dict(by)
    if not doc:
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
    branding["pdfBrand"] = resolve_pdf_brand(doc, gst=gst)
    lf = logo_file()
    if lf:
        branding["logoPath"] = str(lf)
    return branding


def bootstrap_company() -> dict[str, Any]:
    """On boot: rehydrate filesystem cache from DB (or migrate file → DB)."""
    doc = load_company()
    _ensure_logo_cache()
    return {"ok": True, "storage": doc.get("storage"), "hasName": bool((doc.get("companyName") or "").strip())}


SESSION_DAYS = 30
PIN_RESET_HOURS = 1


def clear_active_gst(gst: str | None = None) -> None:
    """Clear the server active-workspace pointer (logout)."""
    want = normalise_gstin(gst) if gst else ""
    current = get_active_gst() or ""
    if want and current and want != current:
        return
    try:
        from WEOS.db.durable_store import put_json

        put_json(_ACTIVE_GST_KEY, "company_active", {"gstNo": ""})
    except Exception:
        _log.exception("clear_active_gst failed")


def iter_company_docs() -> list[dict[str, Any]]:
    """All GST workspace profiles (DB first, then local file)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        from WEOS.db.durable_store import list_payloads

        for row in list_payloads(kind="company", prefix="company:gst:") or []:
            payload = row.get("payload") if isinstance(row, dict) else None
            if not isinstance(payload, dict):
                continue
            g = normalise_gstin(payload.get("gstNo"))
            if not g or g in seen:
                continue
            seen.add(g)
            doc = dict(payload)
            doc["gstNo"] = g
            out.append(doc)
    except Exception:
        _log.debug("iter_company_docs DB list skipped", exc_info=True)
    file_doc = _read_file()
    if isinstance(file_doc, dict):
        g = normalise_gstin(file_doc.get("gstNo"))
        if g and g not in seen:
            out.append(dict(file_doc))
    return out


def mint_workspace_session(gst: str) -> str:
    """Create a session token for this GST workspace and persist its hash."""
    g = normalise_gstin(gst)
    if not g:
        raise ValueError("GSTIN required")
    token = secrets.token_urlsafe(24)
    digest = hash_session_token(token, g)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=SESSION_DAYS)
    doc = load_company_by_gst(g) or _empty()
    sessions = [s for s in (doc.get("loginSessions") or []) if isinstance(s, dict)]
    sessions = [
        s
        for s in sessions
        if str(s.get("expiresAt") or "") > now.isoformat()
    ]
    sessions.append({"hash": digest, "createdAt": now.isoformat(), "expiresAt": exp.isoformat()})
    sessions = sessions[-8:]
    save_company_by_gst(g, {**doc, "loginSessions": sessions})
    return token


def gst_for_session_token(token: str | None) -> str | None:
    """Resolve which GST workspace a session token belongs to."""
    raw = str(token or "").strip()
    if not raw:
        return None
    for doc in iter_company_docs():
        g = normalise_gstin(doc.get("gstNo"))
        if g and verify_workspace_session(g, raw):
            return g
    return None


def verify_workspace_session(gst: str, token: str | None) -> bool:
    g = normalise_gstin(gst)
    raw = str(token or "").strip()
    if not g or not raw:
        return False
    doc = load_company_by_gst(g) or {}
    digest = hash_session_token(raw, g)
    now = datetime.now(timezone.utc).isoformat()
    for s in doc.get("loginSessions") or []:
        if not isinstance(s, dict):
            continue
        if str(s.get("hash") or "") == digest and str(s.get("expiresAt") or "") >= now:
            return True
    return False


def revoke_workspace_session(gst: str, token: str | None = None, *, all_sessions: bool = False) -> None:
    g = normalise_gstin(gst)
    if not g:
        return
    doc = load_company_by_gst(g) or {}
    if all_sessions or not token:
        save_company_by_gst(g, {**doc, "loginSessions": []})
        return
    digest = hash_session_token(str(token).strip(), g)
    sessions = [s for s in (doc.get("loginSessions") or []) if isinstance(s, dict) and str(s.get("hash") or "") != digest]
    save_company_by_gst(g, {**doc, "loginSessions": sessions})


def mint_pin_reset_token(gst: str) -> str:
    g = normalise_gstin(gst)
    if not g:
        raise ValueError("GSTIN required")
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(f"weos-pin-reset|{g}|{token}".encode("utf-8")).hexdigest()
    exp = datetime.now(timezone.utc) + timedelta(hours=PIN_RESET_HOURS)
    doc = load_company_by_gst(g) or _empty()
    save_company_by_gst(
        g,
        {
            **doc,
            "pinResetHash": digest,
            "pinResetExpiresAt": exp.isoformat(),
        },
    )
    return token


def consume_pin_reset_token(token: str, new_pin: str) -> dict[str, Any]:
    """Set a new login PIN from an emailed reset token. Returns the company GST."""
    raw = str(token or "").strip()
    pin = validate_login_pin(new_pin)
    if not raw:
        raise ValueError("Reset link is missing")
    now = datetime.now(timezone.utc).isoformat()
    for doc in iter_company_docs():
        g = normalise_gstin(doc.get("gstNo"))
        stored = str(doc.get("pinResetHash") or "").strip()
        exp = str(doc.get("pinResetExpiresAt") or "")
        if not g or not stored or not exp or exp < now:
            continue
        digest = hashlib.sha256(f"weos-pin-reset|{g}|{raw}".encode("utf-8")).hexdigest()
        if digest != stored:
            continue
        save_company_by_gst(
            g,
            {
                **doc,
                "loginPin": pin,
                "pinResetHash": None,
                "pinResetExpiresAt": None,
                "loginSessions": [],
            },
        )
        return {"ok": True, "gstNo": g, "companyName": doc.get("companyName")}
    raise ValueError("This PIN reset link is invalid or has expired")
