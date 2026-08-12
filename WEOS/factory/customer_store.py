"""Customer profile store + customer quote account.

Customer details (name, address, GST, contact) persist per customer. When
``DATABASE_URL`` is set they live in Postgres (``durable_records``); the
filesystem under ``data_dir()/customers`` is a cache. Customer account lists
every quote/project for that customer for reuse and ledger roll-up.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import data_dir, projects_dir

_log = logging.getLogger("weos.customer_store")


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "customer"


def customer_key(customer: str) -> str:
    return f"customer:{_slug(customer)}"


_FIELDS = (
    "name",
    "address",
    "gstNo",
    "phone",
    "email",
    "contactPerson",
    "state",
    "stateCode",
    "site",
    "notes",
)


def customers_dir() -> Path:
    d = data_dir() / "customers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def profile_path(customer: str) -> Path:
    d = customers_dir() / _slug(customer)
    d.mkdir(parents=True, exist_ok=True)
    return d / "profile.json"


def _empty(customer: str = "") -> dict[str, Any]:
    return {
        "name": customer.strip(),
        "slug": _slug(customer) if customer else "",
        "address": "",
        "gstNo": "",
        "phone": "",
        "email": "",
        "contactPerson": "",
        "state": "",
        "stateCode": "",
        "site": "",
        "notes": "",
        "updatedAt": None,
    }


def _db_get(customer: str) -> dict[str, Any] | None:
    try:
        from WEOS.db.durable_store import get_json

        payload = get_json(customer_key(customer))
        return payload if isinstance(payload, dict) else None
    except Exception:
        _log.exception("customer DB get failed")
        return None


def _db_put(doc: dict[str, Any]) -> bool:
    name = (doc.get("name") or "").strip()
    if not name:
        return False
    try:
        from WEOS.db.durable_store import put_json

        return put_json(customer_key(name), "customer", doc)
    except Exception:
        _log.exception("customer DB put failed")
        return False


def _read_file(customer: str) -> dict[str, Any] | None:
    path = profile_path(customer)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def load_customer_profile(customer: str) -> dict[str, Any]:
    if not (customer or "").strip():
        return _empty()
    base = _empty(customer)
    db_doc = _db_get(customer)
    file_doc = _read_file(customer)
    if db_doc:
        base.update(db_doc)
        try:
            profile_path(customer).write_text(
                json.dumps({k: v for k, v in base.items()}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass
    elif file_doc:
        base.update(file_doc)
        _db_put(base)  # migrate
    base["name"] = base.get("name") or customer.strip()
    base["slug"] = _slug(base["name"])
    return base


def save_customer_profile(customer: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    name = (payload.get("name") or customer or "").strip()
    if not name:
        raise ValueError("Customer name required")
    doc = load_customer_profile(name)
    for key in _FIELDS:
        if key in payload and payload[key] is not None:
            doc[key] = str(payload[key])
    doc["name"] = name
    doc["slug"] = _slug(name)
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    profile_path(name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ok = _db_put(doc)
    doc["persisted"] = ok
    # Keep the mobile-keyed Customer row in sync when phone is present.
    phone = (doc.get("phone") or "").strip()
    if phone:
        try:
            from WEOS.db.quote_store import upsert_customer_by_mobile

            upsert_customer_by_mobile(
                phone,
                name=name,
                email=doc.get("email"),
                gst_no=doc.get("gstNo"),
                address=doc.get("address"),
                state=doc.get("state"),
                state_code=doc.get("stateCode"),
                contact_person=doc.get("contactPerson"),
            )
        except Exception:
            pass
    return doc


def list_customer_profiles() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Prefer durable DB rows (survive redeploy).
    try:
        from WEOS.db.durable_store import list_payloads

        for row in list_payloads(kind="customer", prefix="customer:"):
            doc = row.get("payload") or {}
            if not isinstance(doc, dict):
                continue
            name = str(doc.get("name") or "").strip()
            if not name:
                continue
            slug = doc.get("slug") or _slug(name)
            if slug in seen:
                continue
            seen.add(slug)
            out.append(
                {
                    "name": name,
                    "slug": slug,
                    "gstNo": doc.get("gstNo"),
                    "phone": doc.get("phone"),
                    "email": doc.get("email"),
                    "updatedAt": doc.get("updatedAt") or row.get("updatedAt"),
                }
            )
    except Exception:
        _log.exception("list customer profiles from DB failed")

    root = customers_dir()
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        p = d / "profile.json"
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        name = doc.get("name") or d.name
        slug = doc.get("slug") or d.name
        if slug in seen:
            continue
        seen.add(slug)
        out.append(
            {
                "name": name,
                "slug": slug,
                "gstNo": doc.get("gstNo"),
                "phone": doc.get("phone"),
                "email": doc.get("email"),
                "updatedAt": doc.get("updatedAt"),
            }
        )
        # Migrate file → DB.
        if isinstance(doc, dict) and doc.get("name"):
            _db_put(doc)
    out.sort(key=lambda r: str(r.get("name") or "").lower())
    return out


def _project_versions(project_id: str) -> list[dict[str, Any]]:
    versions_dir = projects_dir() / "versions"
    out: list[dict[str, Any]] = []
    if not versions_dir.is_dir():
        return out
    for vf in sorted(versions_dir.glob(f"{project_id}_v*.json")):
        m = re.search(r"_v(\d+)\.json$", vf.name)
        ver = int(m.group(1)) if m else None
        try:
            doc = json.loads(vf.read_text(encoding="utf-8"))
        except Exception:
            doc = {}
        out.append(
            {
                "version": ver if ver is not None else doc.get("version"),
                "file": vf.name,
                "updatedAt": doc.get("updatedAt"),
                "createdAt": doc.get("createdAt"),
                "lineCount": len(doc.get("lines") or []),
                "grandTotal": (doc.get("lastCalculation") or {}).get("price", {}).get("total"),
            }
        )
    return out


def _matches_customer(row: Mapping[str, Any], target_slug: str, target_name: str) -> bool:
    rc = str(row.get("customer") or "").strip()
    if rc and _slug(rc) == target_slug:
        return True
    mob = str(row.get("customerMobile") or "").strip()
    # When the account was opened by mobile-as-name, match that too.
    if mob and (_slug(mob) == target_slug or mob == target_name):
        return True
    return False


def customer_quotes(customer: str) -> dict[str, Any]:
    """All projects/quotes for a customer, each with its saved version history."""
    from WEOS.factory.project_store import list_projects

    cust = (customer or "").strip()
    target = _slug(cust)
    rows = list_projects(include_archived=True)
    quotes: list[dict[str, Any]] = []
    for row in rows:
        if not _matches_customer(row, target, cust):
            continue
        pid = row.get("projectId")
        versions = _project_versions(str(pid))
        quotes.append(
            {
                "projectId": pid,
                "name": row.get("name"),
                "customer": row.get("customer"),
                "customerMobile": row.get("customerMobile"),
                "status": row.get("status"),
                "version": row.get("version"),
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
                "lineCount": row.get("lineCount"),
                "quotationId": row.get("quotationId"),
                "grandTotal": row.get("grandTotal"),
                "versions": versions,
                "versionCount": len(versions) + 1,
            }
        )
    quotes.sort(key=lambda q: str(q.get("updatedAt") or ""), reverse=True)
    profile = load_customer_profile(cust) if cust else _empty()
    return {
        "customer": cust,
        "profile": profile,
        "quotes": quotes,
        "quoteCount": len(quotes),
    }


def bootstrap_customers() -> dict[str, Any]:
    """Rehydrate customer profile files from durable DB."""
    n = 0
    try:
        from WEOS.db.durable_store import list_payloads

        for row in list_payloads(kind="customer", prefix="customer:"):
            doc = row.get("payload")
            if not isinstance(doc, dict):
                continue
            name = (doc.get("name") or "").strip()
            if not name:
                continue
            path = profile_path(name)
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            n += 1
    except Exception:
        _log.exception("customer bootstrap failed")
    return {"ok": True, "restored": n}
