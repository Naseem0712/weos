"""Per-company compact index so 10k workspaces never scan each other's files.

Hot UI (dashboard, project list, hub) reads this index for the logged-in GST
only. Closed financial years stay in the index for on-demand fetch; they are
not returned unless ``fy=all`` or an explicit past FY is requested.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from WEOS.factory.fy import current_fy, fy_of

_log = logging.getLogger("weos.company_index")

INDEX_KIND = "company_index"
PAGE_DEFAULT = 50
PAGE_MAX = 200


def index_key(gst: str) -> str:
    return f"company:{str(gst or '').strip().upper()}:index"


def _norm_gst(value: Any) -> str:
    try:
        from WEOS.factory.company_store import normalise_gstin

        return normalise_gstin(value)
    except Exception:
        return str(value or "").replace(" ", "").upper()


def _money(n: Any) -> float:
    try:
        return round(float(n or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _empty(gst: str) -> dict[str, Any]:
    return {
        "gstNo": gst,
        "projects": [],
        "customers": [],
        "ready": False,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


def compact_project(doc: Mapping[str, Any]) -> dict[str, Any] | None:
    pid = str(doc.get("projectId") or "").strip()
    if not pid:
        return None
    created = str(doc.get("createdAt") or doc.get("updatedAt") or "")
    money: dict[str, Any] = {}
    if isinstance(doc.get("lines"), list):
        try:
            from WEOS.factory.project_store import live_quote_money

            money = live_quote_money(doc) or {}
        except Exception:
            money = {}
    pkg = doc.get("packageQuotes") if isinstance(doc.get("packageQuotes"), list) else []
    return {
        "projectId": pid,
        "name": doc.get("name") or "",
        "customer": doc.get("customer") or "",
        "customerMobile": doc.get("customerMobile") or "",
        "quotationId": doc.get("quotationId") or pid,
        "status": doc.get("status") or "draft",
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "fy": fy_of(created),
        "totalTaxable": _money(money.get("totalTaxable") if money else doc.get("totalTaxable")),
        "totalGst": _money(money.get("totalGst") if money else doc.get("totalGst")),
        "totalGrand": _money(money.get("totalGrand") if money else doc.get("totalGrand") or doc.get("grandTotal")),
        "grandTotal": _money(money.get("totalTaxable") if money else doc.get("grandTotal")),
        "version": int(doc.get("version") or 0),
        "lineCount": len(doc.get("lines") or []),
        "companyGst": _norm_gst(doc.get("companyGst")),
        "lastFollowUpAt": doc.get("lastFollowUpAt") or "",
        "masterJobId": doc.get("masterJobId") or pid,
        "quoteKind": doc.get("quoteKind") or ("package" if pkg else "cart"),
        "packageQuoteCount": len(pkg),
        "archived": str(doc.get("status") or "") == "archived",
    }


def load_index(gst: str) -> dict[str, Any]:
    g = _norm_gst(gst)
    if not g:
        return _empty("")
    try:
        from WEOS.db.durable_store import get_json

        payload = get_json(index_key(g))
        if isinstance(payload, dict) and isinstance(payload.get("projects"), list):
            payload["gstNo"] = g
            payload["ready"] = True
            return payload
    except Exception:
        _log.debug("company index load missed for %s", g, exc_info=True)
    return _empty(g)


def save_index(gst: str, doc: Mapping[str, Any]) -> None:
    g = _norm_gst(gst)
    if not g:
        return
    payload = dict(doc)
    payload["gstNo"] = g
    payload["ready"] = True
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    try:
        from WEOS.db.durable_store import put_json

        put_json(index_key(g), INDEX_KIND, payload)
    except Exception:
        _log.exception("company index save failed for %s", g)


def upsert_project(doc: Mapping[str, Any]) -> None:
    g = _norm_gst(doc.get("companyGst"))
    row = compact_project(doc)
    if not g or not row:
        return
    idx = load_index(g)
    pid = row["projectId"]
    projects = [p for p in (idx.get("projects") or []) if str(p.get("projectId") or "") != pid]
    projects.append(row)
    idx["projects"] = projects[-20000:]
    cust = str(row.get("customer") or "").strip()
    if cust:
        customers = [c for c in (idx.get("customers") or []) if str(c.get("name") or "").strip().lower() != cust.lower()]
        customers.append(
            {
                "name": cust,
                "phone": row.get("customerMobile") or "",
                "companyGst": g,
                "updatedAt": row.get("updatedAt"),
            }
        )
        idx["customers"] = customers[-8000:]
    save_index(g, idx)


def remove_project(gst: str, project_id: str) -> None:
    g = _norm_gst(gst)
    pid = str(project_id or "").strip()
    if not g or not pid:
        return
    idx = load_index(g)
    idx["projects"] = [p for p in (idx.get("projects") or []) if str(p.get("projectId") or "") != pid]
    save_index(g, idx)


def upsert_customer(gst: str, profile: Mapping[str, Any]) -> None:
    g = _norm_gst(gst or profile.get("companyGst"))
    name = str(profile.get("name") or "").strip()
    if not g or not name:
        return
    idx = load_index(g)
    customers = [c for c in (idx.get("customers") or []) if str(c.get("name") or "").strip().lower() != name.lower()]
    customers.append(
        {
            "name": name,
            "slug": profile.get("slug") or "",
            "phone": profile.get("phone") or "",
            "email": profile.get("email") or "",
            "gstNo": profile.get("gstNo") or "",
            "companyGst": g,
            "updatedAt": profile.get("updatedAt"),
        }
    )
    idx["customers"] = customers[-8000:]
    save_index(g, idx)


def rebuild_index(gst: str) -> dict[str, Any]:
    """One-time (or repair) scan for this GST only — then all reads use the index."""
    g = _norm_gst(gst)
    if not g:
        return _empty("")
    from WEOS.factory.project_store import list_projects

    rows = list_projects(
        include_archived=True,
        company_gst=g,
        include_unscoped=False,
        use_index=False,
    )
    projects = []
    customers: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = compact_project(r) if "fy" not in r else dict(r)
        if not c:
            c = {
                "projectId": r.get("projectId"),
                "name": r.get("name") or "",
                "customer": r.get("customer") or "",
                "customerMobile": r.get("customerMobile") or "",
                "quotationId": r.get("quotationId") or r.get("projectId"),
                "status": r.get("status") or "draft",
                "createdAt": r.get("createdAt"),
                "updatedAt": r.get("updatedAt"),
                "fy": fy_of(r.get("createdAt") or r.get("updatedAt")),
                "totalTaxable": _money(r.get("totalTaxable") or r.get("grandTotal")),
                "totalGst": _money(r.get("totalGst")),
                "totalGrand": _money(r.get("totalGrand")),
                "grandTotal": _money(r.get("grandTotal")),
                "version": int(r.get("version") or 0),
                "lineCount": int(r.get("lineCount") or 0),
                "companyGst": g,
                "lastFollowUpAt": r.get("lastFollowUpAt") or "",
                "archived": str(r.get("status") or "") == "archived",
            }
        if _norm_gst(c.get("companyGst")) != g:
            continue
        projects.append(c)
        name = str(c.get("customer") or "").strip()
        if name:
            customers[name.lower()] = {
                "name": name,
                "phone": c.get("customerMobile") or "",
                "companyGst": g,
                "updatedAt": c.get("updatedAt"),
            }
    idx = _empty(g)
    idx["projects"] = projects
    idx["customers"] = list(customers.values())
    save_index(g, idx)
    return idx


def _ensure(gst: str) -> dict[str, Any]:
    g = _norm_gst(gst)
    idx = load_index(g)
    if idx.get("ready"):
        return idx
    try:
        return rebuild_index(g)
    except Exception:
        _log.exception("company index rebuild failed for %s", g)
        return idx


def query_projects(
    gst: str,
    *,
    q: str | None = None,
    status: str | None = None,
    fy: str | None = None,
    include_archived: bool = False,
    sort: str = "updatedAt",
    order: str = "desc",
    limit: int | None = PAGE_DEFAULT,
    offset: int = 0,
) -> dict[str, Any]:
    g = _norm_gst(gst)
    idx = _ensure(g)
    want_fy = str(fy if fy is not None else "all").strip().lower()
    if want_fy in {"", "current", "this"}:
        want_fy = current_fy()
    rows = []
    for p in idx.get("projects") or []:
        if _norm_gst(p.get("companyGst")) and _norm_gst(p.get("companyGst")) != g:
            continue
        st = str(p.get("status") or "draft")
        archived = bool(p.get("archived")) or st == "archived"
        if not include_archived and archived and status != "archived":
            continue
        if status and st != status:
            continue
        if want_fy not in {"all", "*", "any"} and str(p.get("fy") or fy_of(p.get("createdAt"))) != want_fy:
            continue
        if q:
            blob = (
                f"{p.get('projectId')} {p.get('name')} {p.get('customer')} "
                f"{p.get('quotationId')} {p.get('customerMobile')}"
            ).lower()
            if q.lower() not in blob:
                continue
        rows.append(p)
    key = sort if sort in {"updatedAt", "createdAt", "name", "projectId"} else "updatedAt"
    reverse = str(order or "desc").lower() != "asc"
    rows.sort(key=lambda r: str(r.get(key) or ""), reverse=reverse)
    total = len(rows)
    off = max(0, int(offset or 0))
    if limit is None:
        page = rows
        lim = total
    else:
        lim = max(0, min(int(limit), PAGE_MAX))
        page = rows[off : off + lim] if lim else []
    fys = sorted({str(p.get("fy") or "") for p in (idx.get("projects") or []) if p.get("fy")})
    return {
        "items": page,
        "total": total,
        "fy": want_fy if want_fy not in {"all", "*", "any"} else "all",
        "availableFy": fys,
        "limit": lim if limit is not None else total,
        "offset": off,
        "hasMore": (off + len(page)) < total,
        "hotLoaded": want_fy not in {"all", "*", "any"},
    }


def query_customers(gst: str, *, q: str | None = None, limit: int | None = PAGE_DEFAULT, offset: int = 0) -> dict[str, Any]:
    g = _norm_gst(gst)
    idx = _ensure(g)
    rows = list(idx.get("customers") or [])
    if q:
        needle = q.lower()
        rows = [
            c
            for c in rows
            if needle in str(c.get("name") or "").lower() or needle in str(c.get("phone") or "")
        ]
    total = len(rows)
    off = max(0, int(offset or 0))
    if limit is None:
        page = rows
        lim = total
    else:
        lim = max(0, min(int(limit), PAGE_MAX))
        page = rows[off : off + lim] if lim else []
    return {"items": page, "total": total, "limit": lim if limit is not None else total, "offset": off, "hasMore": (off + len(page)) < total}


def all_project_rows(gst: str) -> list[dict[str, Any]]:
    """Compact rows for dashboard math (index only — never another company's files)."""
    return list(_ensure(gst).get("projects") or [])
