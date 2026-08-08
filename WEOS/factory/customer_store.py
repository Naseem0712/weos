"""Customer profile store + customer quote account.

- Customer details (name, address, GST, contact) persisted per customer (JSON).
  Auto-printed into the quotation bill-to block.
- Customer account: every quote/project for a customer, with all saved versions,
  so any version can be printed, edited or reused (duplicated to a new version).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import data_dir, projects_dir


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "customer"


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


def load_customer_profile(customer: str) -> dict[str, Any]:
    if not (customer or "").strip():
        return _empty()
    path = profile_path(customer)
    if not path.is_file():
        return _empty(customer)
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return _empty(customer)
    base = _empty(customer)
    base.update(doc)
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
    return doc


def list_customer_profiles() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    root = customers_dir()
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        p = d / "profile.json"
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        out.append(
            {
                "name": doc.get("name") or d.name,
                "slug": doc.get("slug") or d.name,
                "gstNo": doc.get("gstNo"),
                "phone": doc.get("phone"),
                "email": doc.get("email"),
                "updatedAt": doc.get("updatedAt"),
            }
        )
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


def customer_quotes(customer: str) -> dict[str, Any]:
    """All projects/quotes for a customer, each with its saved version history."""
    from WEOS.factory.project_store import list_projects

    cust = (customer or "").strip()
    target = _slug(cust)
    rows = list_projects(include_archived=True)
    quotes: list[dict[str, Any]] = []
    for row in rows:
        rc = row.get("customer") or ""
        if _slug(str(rc)) != target:
            continue
        pid = row.get("projectId")
        versions = _project_versions(str(pid))
        quotes.append(
            {
                "projectId": pid,
                "name": row.get("name"),
                "customer": rc,
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
