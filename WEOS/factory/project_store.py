"""Project persistence — save / reload / version / archive WEOS projects.

Filesystem under ``projects_dir()`` is a working cache. When DATABASE_URL is
available, every project JSON (and the ID counter) is mirrored to Postgres so
Project Setup / quotes survive Railway redeploys.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import PACKAGE_ROOT, projects_dir

_log = logging.getLogger("weos.project_store")

WEOS_ROOT = PACKAGE_ROOT
PROJECTS_DIR = projects_dir()
ARCHIVE_DIR = PROJECTS_DIR / "archived"
COUNTER_FILE = PROJECTS_DIR / "_counter.json"
HISTORY_DIR = PROJECTS_DIR / "history"

_COUNTER_KEY = "projects:counter"


def _project_db_key(project_id: str, *, archived: bool = False) -> str:
    prefix = "project_archived" if archived else "project"
    return f"{prefix}:{project_id}"


def _db_put_project(doc: dict[str, Any], *, archived: bool = False) -> bool:
    pid = str(doc.get("projectId") or "").strip()
    if not pid:
        return False
    try:
        from WEOS.db.durable_store import put_json

        clean = {k: v for k, v in doc.items() if not str(k).startswith("_")}
        kind = "project_archived" if archived else "project"
        return put_json(_project_db_key(pid, archived=archived), kind, clean)
    except Exception:
        _log.exception("project DB put failed for %s", pid)
        return False


def _db_get_project(project_id: str) -> dict[str, Any] | None:
    try:
        from WEOS.db.durable_store import get_json

        for archived in (False, True):
            payload = get_json(_project_db_key(project_id, archived=archived))
            if isinstance(payload, dict):
                return payload
        return None
    except Exception:
        _log.exception("project DB get failed for %s", project_id)
        return None


def _db_delete_project(project_id: str) -> None:
    try:
        from WEOS.db.durable_store import delete_key

        delete_key(_project_db_key(project_id, archived=False))
        delete_key(_project_db_key(project_id, archived=True))
    except Exception:
        _log.exception("project DB delete failed for %s", project_id)


def _db_put_counter(data: dict[str, Any]) -> None:
    try:
        from WEOS.db.durable_store import put_json

        put_json(_COUNTER_KEY, "counter", data)
    except Exception:
        _log.exception("project counter DB put failed")


def _db_get_counter() -> dict[str, Any] | None:
    try:
        from WEOS.db.durable_store import get_json

        payload = get_json(_COUNTER_KEY)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def ensure_projects_dir() -> Path:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECTS_DIR / "versions").mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return PROJECTS_DIR


def _load_counter() -> dict[str, Any]:
    ensure_projects_dir()
    data: dict[str, Any] = {"year": 0, "seq": 0, "quote_seq": 0}
    db = _db_get_counter()
    if isinstance(db, dict):
        data.update(db)
    elif COUNTER_FILE.is_file():
        try:
            data.update(json.loads(COUNTER_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return data


def _save_counter(data: dict[str, Any]) -> None:
    ensure_projects_dir()
    COUNTER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _db_put_counter(data)


def _next_seq(year: int) -> int:
    data = _load_counter()
    if int(data.get("year", 0)) != year:
        data = {"year": year, "seq": 0, "quote_seq": int(data.get("quote_seq", 0))}
    data["seq"] = int(data.get("seq", 0)) + 1
    data["year"] = year
    _save_counter(data)
    return int(data["seq"])


def new_project_id() -> str:
    year = datetime.now(timezone.utc).year
    return f"PRJ-{year}-{_next_seq(year):05d}"


def new_quotation_id(company_name: str | None = None) -> str:
    """Allocate next company-prefixed quote number: ``AK-26/00001/A1``."""
    from WEOS.factory.quote_number import format_quote_number, resolve_company_name

    year = datetime.now(timezone.utc).year
    data = _load_counter()
    if int(data.get("year", 0)) != year:
        data = {"year": year, "seq": int(data.get("seq", 0)), "quote_seq": 0}
    data["quote_seq"] = int(data.get("quote_seq", 0)) + 1
    data["year"] = year
    _save_counter(data)
    name = resolve_company_name(company_name)
    # Preserve historical width when counter already past 5 digits; else 5.
    width = 5 if int(data["quote_seq"]) < 100000 else 6
    return format_quote_number(
        company_name=name,
        year=year,
        serial=int(data["quote_seq"]),
        version=1,
        serial_width=width,
    )


def project_path(project_id: str) -> Path:
    return ensure_projects_dir() / f"{project_id}.json"


def _append_history(project_id: str, action: str, version: int) -> None:
    path = HISTORY_DIR / f"{project_id}.jsonl"
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "version": version,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def save_project(doc: dict[str, Any], *, bump_version: bool = True, action: str = "save") -> dict[str, Any]:
    ensure_projects_dir()
    # Same quotation number for this customer/company → fold into canonical project as a new version.
    doc, versioned = apply_quote_number_versioning(doc)
    if versioned and action == "save":
        action = "quote_number_version"
    pid = doc.get("projectId") or new_project_id()
    doc["projectId"] = pid
    if not str(doc.get("quotationId") or "").strip():
        try:
            doc["quotationId"] = new_quotation_id()
        except Exception:
            _log.debug("auto quotation id skipped for %s", pid, exc_info=True)
    try:
        from WEOS.factory.quote_discount import normalize_discount

        doc["quoteDiscount"] = normalize_discount(doc.get("quoteDiscount"))
    except Exception:
        pass
    try:
        from WEOS.factory.package_quote import apply_package_fields

        apply_package_fields(doc, doc)
    except Exception:
        _log.debug("package quote stamp skipped for %s", pid, exc_info=True)
    if not str(doc.get("masterJobId") or "").strip():
        doc["masterJobId"] = pid
    doc.setdefault("status", "active")  # active | draft | archived
    # Stamp seller GST from active workspace when missing.
    if not _norm_company_gst(doc.get("companyGst")):
        try:
            from WEOS.factory.company_store import get_active_gst

            active = get_active_gst()
            if active:
                doc["companyGst"] = active
        except Exception:
            pass
    elif doc.get("companyGst"):
        doc["companyGst"] = _norm_company_gst(doc.get("companyGst"))
    if not str(doc.get("shareToken") or doc.get("quoteShareToken") or "").strip():
        try:
            from WEOS.factory.quote_share import new_share_token

            tok = new_share_token()
            doc["shareToken"] = tok
            doc["quoteShareToken"] = tok
        except Exception:
            pass
    elif doc.get("shareToken") and not doc.get("quoteShareToken"):
        doc["quoteShareToken"] = doc["shareToken"]
    now = datetime.now(timezone.utc).isoformat()
    if "createdAt" not in doc:
        doc["createdAt"] = now
    doc["updatedAt"] = now
    ver = int(doc.get("version", 0))
    if bump_version:
        ver += 1
    doc["version"] = ver

    # undo stack (last 20 snapshots of lines+meta for client undo)
    undo = list(doc.get("_undoStack") or [])
    if bump_version and project_path(pid).is_file():
        prev = json.loads(project_path(pid).read_text(encoding="utf-8"))
        undo.append(
            {
                "version": prev.get("version"),
                "lines": prev.get("lines"),
                "name": prev.get("name"),
                "customer": prev.get("customer"),
            }
        )
        undo = undo[-20:]
    doc["_undoStack"] = undo
    if bump_version:
        doc["_redoStack"] = []
        log = list(doc.get("revisionLog") or [])
        log.append({"at": now, "action": str(action or "save"), "version": ver})
        doc["revisionLog"] = log[-80:]

    path = project_path(pid)
    if path.is_file() and bump_version:
        snap = PROJECTS_DIR / "versions" / f"{pid}_v{ver - 1}.json"
        shutil.copy2(path, snap)

    # strip runtime
    out = {k: v for k, v in doc.items() if k != "_path"}
    try:
        from WEOS.factory.quote_item_snapshot import freeze_project_lines

        out["lines"] = freeze_project_lines(out.get("lines") or [], overwrite_identity=False)
        doc["lines"] = out["lines"]
    except Exception:
        _log.exception("quote item snapshot freeze failed for %s", pid)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    archived = str(doc.get("status") or "") == "archived"
    _db_put_project(out, archived=archived)
    if archived:
        # Active key must not linger after archive.
        try:
            from WEOS.db.durable_store import delete_key

            delete_key(_project_db_key(pid, archived=False))
        except Exception:
            pass
    _append_history(pid, action, ver)
    try:
        from WEOS.factory.company_index import upsert_project

        upsert_project(out)
    except Exception:
        _log.debug("company index upsert skipped for %s", pid, exc_info=True)
    try:
        from WEOS.factory.quote_share import _index_share_token

        tok = str(out.get("shareToken") or out.get("quoteShareToken") or "").strip()
        if tok:
            _index_share_token(tok, out)
    except Exception:
        _log.debug("share token index skipped for %s", pid, exc_info=True)
    doc["_path"] = path.as_posix()
    if versioned:
        doc["quoteNumberVersioned"] = True
    # Keep customer profile in sync so Project Setup and Customers tab share one record.
    _sync_customer_from_project(out)
    return doc


def _sync_customer_from_project(doc: Mapping[str, Any] | dict[str, Any]) -> None:
    """Upsert customer profile from project bill-to fields (no orphan duplicates)."""
    name = str(doc.get("customer") or "").strip()
    mobile = str(doc.get("customerMobile") or "").strip()
    if not name and not mobile:
        return
    cust_name = name or mobile
    payload: dict[str, Any] = {"name": cust_name}
    if mobile:
        payload["phone"] = mobile
    addr = str(doc.get("customerAddress") or "").strip()
    if addr:
        payload["address"] = addr
    gst = str(doc.get("customerGst") or "").strip()
    if gst:
        payload["gstNo"] = gst
    co = _norm_company_gst(doc.get("companyGst"))
    if co:
        payload["companyGst"] = co
    try:
        from WEOS.factory.customer_store import save_customer_profile

        save_customer_profile(cust_name, payload)
    except Exception:
        _log.exception("sync customer profile from project %s failed", doc.get("projectId"))


def set_project_status(project_id: str, status: str) -> dict[str, Any]:
    """Set project status (draft → approved → rejected/cancelled; archive)."""
    st = (status or "").strip().lower() or "draft"
    allowed = {
        "draft", "active", "unused", "approved", "confirmed", "accepted", "finalized",
        "ordered", "order", "won", "rejected", "cancelled", "canceled", "archived",
    }
    if st not in allowed:
        raise ValueError(f"Unknown status {status!r}")
    doc = load_project(project_id)
    prev = str(doc.get("status") or "draft").strip().lower()
    doc["status"] = st
    now = datetime.now(timezone.utc).isoformat()
    if st in {"approved", "confirmed", "accepted", "finalized", "ordered", "order", "won"}:
        doc["approvedAt"] = now
        if prev in {"rejected", "cancelled", "canceled"}:
            doc["reapprovedFrom"] = prev
    if st in {"rejected", "cancelled", "canceled"}:
        doc["rejectedAt"] = now
        doc["rejectedFrom"] = prev
    return save_project(doc, bump_version=False, action=f"status_{st}")


def _norm_company_gst(value: Any) -> str:
    try:
        from WEOS.factory.company_store import normalise_gstin

        return normalise_gstin(str(value or ""))
    except Exception:
        return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _norm_quote_number(value: Any) -> str:
    """Normalise for exact-id compares; prefer base key for version-family matches."""
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def _belongs_to_company(doc: Mapping[str, Any] | dict[str, Any], company_gst: str | None, *, include_unscoped: bool) -> bool:
    if not company_gst:
        return True
    row_gst = _norm_company_gst(doc.get("companyGst"))
    if row_gst == company_gst:
        return True
    if include_unscoped and not row_gst:
        return True
    return False


def find_project_by_quotation_id(
    quotation_id: str,
    *,
    customer: str | None = None,
    company_gst: str | None = None,
    exclude_project_id: str | None = None,
) -> dict[str, Any] | None:
    """Canonical live project for an exact quotation number within customer/company scope.

    Extra text on a quote number (e.g. ``AK-26/00007/A1`` vs ``AK-26/00007``) is a
    different quote — it must not fold into the older job.
    """
    qid = _norm_quote_number(quotation_id)
    if not qid:
        return None
    cust_slug = None
    if customer:
        cust_slug = re.sub(r"[^a-zA-Z0-9]+", "_", customer.strip().lower()).strip("_")
    gst = _norm_company_gst(company_gst) if company_gst else ""
    rows = list_projects(include_archived=False, company_gst=gst or None, include_unscoped=bool(gst))
    matches: list[dict[str, Any]] = []
    for row in rows:
        if _norm_quote_number(row.get("quotationId")) != qid:
            continue
        if exclude_project_id and str(row.get("projectId")) == str(exclude_project_id):
            continue
        if cust_slug:
            rc = re.sub(r"[^a-zA-Z0-9]+", "_", str(row.get("customer") or "").strip().lower()).strip("_")
            if rc and rc != cust_slug:
                continue
        matches.append(row)
    if not matches:
        return None
    matches.sort(key=lambda r: str(r.get("updatedAt") or ""), reverse=True)
    try:
        return load_project(str(matches[0]["projectId"]))
    except FileNotFoundError:
        return None


def apply_quote_number_versioning(doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Keep each saved job on its own project id.

    Reusing a customer or editing a quote number must save *this* project.
    Folding into an older job deleted the draft id the browser still held
    (Project not found: PRJ-…) and could overwrite the previous quote.
    Versions still stack on the same projectId via ``save_project``.
    """
    return doc, False


def load_project(project_id: str) -> dict[str, Any]:
    path = project_path(project_id)
    if not path.is_file():
        archived = ARCHIVE_DIR / f"{project_id}.json"
        if archived.is_file():
            path = archived
        else:
            # Rehydrate from durable DB after a redeploy wiped the volume.
            db_doc = _db_get_project(project_id)
            if db_doc is None:
                raise FileNotFoundError(f"Project not found: {project_id}")
            ensure_projects_dir()
            status = str(db_doc.get("status") or "active")
            dest = ARCHIVE_DIR / f"{project_id}.json" if status == "archived" else project_path(project_id)
            dest.write_text(json.dumps(db_doc, indent=2), encoding="utf-8")
            path = dest
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["_path"] = path.as_posix()
    return doc


def format_tenure(iso: Any, *, now: datetime | None = None) -> str:
    """Short age since created/updated, e.g. ``12d`` / ``3h`` / ``40m``."""
    raw = str(iso or "").strip()
    if not raw:
        return ""
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    sec = max(0.0, (now_dt - stamp.astimezone(timezone.utc)).total_seconds())
    if sec < 3600:
        return f"{max(1, int(round(sec / 60.0)))}m"
    if sec < 86400:
        return f"{max(1, int(round(sec / 3600.0)))}h"
    days = sec / 86400.0
    if days < 60:
        return f"{max(1, int(round(days)))}d"
    if days < 365:
        return f"{max(1, int(round(days / 30.0)))}mo"
    return f"{max(1, int(round(days / 365.0)))}y"


def cart_quote_money(doc: Mapping[str, Any] | None) -> dict[str, float]:
    """WEOS cart / drawing quote only — never package-deal amounts."""
    from WEOS.factory.customer_line_view import customer_line_amount
    from WEOS.factory.ledger_store import quote_money_parts

    doc = doc if isinstance(doc, Mapping) else {}
    line_sum = 0.0
    any_amt = False
    for ln in doc.get("lines") or []:
        if not isinstance(ln, Mapping):
            continue
        amt = customer_line_amount(ln)
        if amt is not None and amt > 0:
            line_sum += float(amt)
            any_amt = True
    calc = doc.get("lastCalculation") if isinstance(doc.get("lastCalculation"), Mapping) else {}
    price = calc.get("price") if isinstance(calc.get("price"), Mapping) else {}
    combined = calc.get("combined") if isinstance(calc.get("combined"), Mapping) else {}
    stored = (
        combined.get("commercialGrandTotal")
        or price.get("commercialTotal")
        or price.get("total")
        or doc.get("grandTotal")
    )
    try:
        stored_n = float(stored) if stored is not None and str(stored).strip() != "" else 0.0
    except (TypeError, ValueError):
        stored_n = 0.0
    pkg_n = 0.0
    try:
        from WEOS.factory.package_quote import package_money_for_doc

        pkg_n = float((package_money_for_doc(doc) or {}).get("projectValue") or 0)
    except Exception:
        pkg_n = 0.0
    # Stale lastCalculation must not count as a cart total on package-only jobs.
    if not any_amt and pkg_n > 0 and not (doc.get("lines") or []):
        stored_n = 0.0
    taxable = line_sum if any_amt and line_sum > 0 else stored_n
    if taxable <= 0:
        return quote_money_parts(0)
    return quote_money_parts(taxable)


def live_quote_money(doc: Mapping[str, Any] | None) -> dict[str, float]:
    """Taxable + GST-inclusive grand: cart quote plus package quotes, then discount."""
    from WEOS.factory.package_quote import package_money_for_doc
    from WEOS.factory.quote_discount import apply_discount

    cart = cart_quote_money(doc)
    pkg = package_money_for_doc(doc if isinstance(doc, Mapping) else {})
    if not pkg.get("quoteCount"):
        parts = dict(cart)
    elif cart.get("totalGrand", 0) <= 0 and cart.get("totalTaxable", 0) <= 0:
        parts = {
            "totalTaxable": float(pkg.get("totalTaxable") or 0),
            "totalGst": float(pkg.get("gstAmount") or 0),
            "totalGrand": float(pkg.get("projectValue") or 0),
            "gstPercent": pkg.get("gstPercent") if pkg.get("gstPercent") is not None else cart.get("gstPercent"),
        }
    else:
        parts = {
            "totalTaxable": round(float(cart.get("totalTaxable") or 0) + float(pkg.get("totalTaxable") or 0), 2),
            "totalGst": round(float(cart.get("totalGst") or 0) + float(pkg.get("gstAmount") or 0), 2),
            "totalGrand": round(float(cart.get("totalGrand") or 0) + float(pkg.get("projectValue") or 0), 2),
            "gstPercent": cart.get("gstPercent"),
        }
    disc = (doc or {}).get("quoteDiscount") if isinstance(doc, Mapping) else None
    return apply_discount(parts, disc)


def list_projects(
    *,
    q: str | None = None,
    status: str | None = None,
    sort: str = "updatedAt",
    order: str = "desc",
    include_archived: bool = False,
    company_gst: str | None = None,
    include_unscoped: bool = False,
    fy: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    use_index: bool = True,
) -> list[dict[str, Any]]:
    gst = _norm_company_gst(company_gst) if company_gst else ""
    if use_index and gst and not include_unscoped:
        try:
            from WEOS.factory.company_index import query_projects

            packed = query_projects(
                gst,
                q=q,
                status=status,
                fy=fy,
                include_archived=include_archived or status == "archived",
                sort=sort,
                order=order,
                limit=limit,
                offset=offset,
            )
            return list(packed.get("items") or [])
        except Exception:
            _log.exception("company index list failed for %s — falling back to scan", gst)
    ensure_projects_dir()
    files = list(PROJECTS_DIR.glob("PRJ-*.json"))
    if include_archived or status == "archived":
        files += list(ARCHIVE_DIR.glob("PRJ-*.json"))
    # Also surface DB-only projects that have not been rehydrated to disk yet.
    try:
        from WEOS.db.durable_store import list_payloads

        seen_ids = {p.stem for p in files}
        for row in list_payloads(kind="project") + (
            list_payloads(kind="project_archived") if include_archived or status == "archived" else []
        ):
            doc = row.get("payload") or {}
            if not isinstance(doc, dict):
                continue
            pid = str(doc.get("projectId") or "").strip()
            if not pid or pid in seen_ids:
                continue
            # Write through to cache so subsequent loads work.
            try:
                dest = (
                    ARCHIVE_DIR / f"{pid}.json"
                    if str(doc.get("status") or "") == "archived"
                    else project_path(pid)
                )
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.is_file():
                    dest.write_text(json.dumps(doc, indent=2), encoding="utf-8")
                    files.append(dest)
                    seen_ids.add(pid)
            except Exception:
                pass
    except Exception:
        pass
    gst = _norm_company_gst(company_gst) if company_gst else ""
    out: list[dict[str, Any]] = []
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            st = d.get("status", "active")
            if status and st != status:
                continue
            if not include_archived and status != "archived" and st == "archived" and p.parent == ARCHIVE_DIR:
                continue
            if gst and not _belongs_to_company(d, gst, include_unscoped=include_unscoped):
                continue
            money = live_quote_money(d)
            pkg_quotes = d.get("packageQuotes") if isinstance(d.get("packageQuotes"), list) else []
            pkg_nos = " ".join(
                str((pq or {}).get("quotationId") or "")
                for pq in pkg_quotes
                if isinstance(pq, dict)
            )
            row = {
                "projectId": d.get("projectId", p.stem),
                "name": d.get("name"),
                "customer": d.get("customer"),
                "customerMobile": d.get("customerMobile"),
                "customerAddress": d.get("customerAddress") or "",
                "customerGst": d.get("customerGst") or "",
                "status": st,
                "updatedAt": d.get("updatedAt"),
                "createdAt": d.get("createdAt"),
                "version": d.get("version"),
                "lineCount": len(d.get("lines") or []),
                "quotationId": d.get("quotationId") or d.get("projectId", p.stem),
                "grandTotal": money["totalTaxable"],
                "totalTaxable": money["totalTaxable"],
                "totalGst": money["totalGst"],
                "totalGrand": money["totalGrand"],
                "discountMode": (d.get("quoteDiscount") or {}).get("mode") if isinstance(d.get("quoteDiscount"), dict) else "off",
                "tenure": format_tenure(d.get("updatedAt") or d.get("createdAt")),
                "companyGst": d.get("companyGst") or "",
                "shareToken": d.get("shareToken") or d.get("quoteShareToken") or "",
                "masterJobId": d.get("masterJobId") or d.get("projectId", p.stem),
                "quoteKind": d.get("quoteKind") or ("package" if pkg_quotes else "cart"),
                "packageQuoteCount": len(pkg_quotes),
                "lastFollowUpAt": d.get("lastFollowUpAt") or "",
            }
            if q:
                blob = (
                    f"{row['projectId']} {row['name']} {row['customer']} {row.get('quotationId')} "
                    f"{row.get('customerMobile') or ''} {pkg_nos} {row.get('masterJobId') or ''}"
                ).lower()
                qn = q.lower()
                digits = re.sub(r"\D", "", q)
                mob = re.sub(r"\D", "", str(row.get("customerMobile") or ""))
                hit = qn in blob
                if not hit and digits and len(digits) >= 7 and mob and (digits in mob or mob in digits):
                    hit = True
                if not hit:
                    continue
            out.append(row)
        except Exception:
            out.append({"projectId": p.stem, "status": "unknown"})
    reverse = order.lower() != "asc"
    out.sort(key=lambda r: r.get(sort) or "", reverse=reverse)
    return out


def duplicate_project(project_id: str, *, name: str | None = None) -> dict[str, Any]:
    src = load_project(project_id)
    src.pop("_path", None)
    src["projectId"] = new_project_id()
    src["name"] = name or f"Copy of {src.get('name') or project_id}"
    src["createdAt"] = datetime.now(timezone.utc).isoformat()
    src["version"] = 0
    src["status"] = "draft"
    src.pop("quotationId", None)
    src.pop("lastCalculation", None)
    src["_undoStack"] = []
    src["_redoStack"] = []
    return save_project(src, bump_version=True, action="duplicate")


def archive_project(project_id: str) -> dict[str, Any]:
    doc = load_project(project_id)
    doc["status"] = "archived"
    path = project_path(project_id)
    # save then move
    save_project(doc, bump_version=True, action="archive")
    if path.is_file():
        dest = ARCHIVE_DIR / path.name
        shutil.move(str(path), str(dest))
    doc["_path"] = (ARCHIVE_DIR / f"{project_id}.json").as_posix()
    return doc


def restore_project(project_id: str) -> dict[str, Any]:
    archived = ARCHIVE_DIR / f"{project_id}.json"
    if not archived.is_file():
        # Try DB-only archived project.
        db_doc = _db_get_project(project_id)
        if db_doc is None:
            raise FileNotFoundError(f"Archived project not found: {project_id}")
        ensure_projects_dir()
        dest = project_path(project_id)
        db_doc["status"] = "active"
        dest.write_text(json.dumps(db_doc, indent=2), encoding="utf-8")
        return save_project(db_doc, bump_version=True, action="restore")
    dest = project_path(project_id)
    shutil.move(str(archived), str(dest))
    doc = json.loads(dest.read_text(encoding="utf-8"))
    doc["status"] = "active"
    return save_project(doc, bump_version=True, action="restore")


def delete_project(project_id: str, *, hard: bool = False) -> dict[str, Any]:
    """Soft-delete = archive. hard=True removes active file after version keep."""
    gst = ""
    try:
        prev = load_project(project_id)
        gst = _norm_company_gst(prev.get("companyGst"))
    except Exception:
        prev = None
    if hard:
        path = project_path(project_id)
        if path.is_file():
            snap = PROJECTS_DIR / "versions" / f"{project_id}_deleted.json"
            shutil.copy2(path, snap)
            path.unlink()
            _db_delete_project(project_id)
            _append_history(project_id, "delete", -1)
            if gst:
                try:
                    from WEOS.factory.company_index import remove_project as _drop_idx

                    _drop_idx(gst, project_id)
                except Exception:
                    pass
            return {"deleted": True, "projectId": project_id}
        if _db_get_project(project_id) is not None:
            _db_delete_project(project_id)
            _append_history(project_id, "delete", -1)
            if gst:
                try:
                    from WEOS.factory.company_index import remove_project as _drop_idx

                    _drop_idx(gst, project_id)
                except Exception:
                    pass
            return {"deleted": True, "projectId": project_id}
        raise FileNotFoundError(project_id)
    return archive_project(project_id)


def bootstrap_projects() -> dict[str, Any]:
    """Rehydrate project JSON files + counter from durable DB on boot."""
    ensure_projects_dir()
    restored = 0
    try:
        from WEOS.db.durable_store import list_payloads

        counter = _db_get_counter()
        if isinstance(counter, dict):
            COUNTER_FILE.write_text(json.dumps(counter, indent=2), encoding="utf-8")

        rows = list_payloads(kind="project") + list_payloads(kind="project_archived")
        for row in rows:
            doc = row.get("payload")
            if not isinstance(doc, dict):
                continue
            pid = str(doc.get("projectId") or "").strip()
            if not pid:
                continue
            archived = (row.get("kind") == "project_archived") or str(doc.get("status") or "") == "archived"
            dest = (ARCHIVE_DIR / f"{pid}.json") if archived else project_path(pid)
            if archived:
                ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            restored += 1
    except Exception:
        _log.exception("project bootstrap failed")
    # Seed DB from any files present that are not yet mirrored (first deploy).
    seeded = 0
    try:
        for p in list(PROJECTS_DIR.glob("PRJ-*.json")) + list(ARCHIVE_DIR.glob("PRJ-*.json")):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            archived = p.parent == ARCHIVE_DIR or str(doc.get("status") or "") == "archived"
            if _db_put_project(doc, archived=archived):
                seeded += 1
        if COUNTER_FILE.is_file() and _db_get_counter() is None:
            try:
                _db_put_counter(json.loads(COUNTER_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass
    except Exception:
        _log.exception("project seed-to-DB failed")
    return {"ok": True, "restored": restored, "seeded": seeded}

def project_history(project_id: str) -> list[dict[str, Any]]:
    ensure_projects_dir()
    path = HISTORY_DIR / f"{project_id}.jsonl"
    versions = sorted((PROJECTS_DIR / "versions").glob(f"{project_id}_v*.json"))
    hist = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                hist.append(json.loads(line))
    for v in versions:
        hist.append({"versionFile": v.name, "path": str(v.as_posix())})
    return hist


def undo_project(project_id: str) -> dict[str, Any]:
    doc = load_project(project_id)
    undo = list(doc.get("_undoStack") or [])
    if not undo:
        raise ValueError("Nothing to undo")
    current = {"version": doc.get("version"), "lines": doc.get("lines"), "name": doc.get("name"), "customer": doc.get("customer")}
    prev = undo.pop()
    redo = list(doc.get("_redoStack") or [])
    redo.append(current)
    doc["lines"] = prev.get("lines") or []
    if prev.get("name") is not None:
        doc["name"] = prev["name"]
    if prev.get("customer") is not None:
        doc["customer"] = prev["customer"]
    doc["_undoStack"] = undo
    doc["_redoStack"] = redo[-20:]
    # save without consuming undo again wrongly — manually write
    return save_project(doc, bump_version=True, action="undo")


def redo_project(project_id: str) -> dict[str, Any]:
    doc = load_project(project_id)
    redo = list(doc.get("_redoStack") or [])
    if not redo:
        raise ValueError("Nothing to redo")
    nxt = redo.pop()
    undo = list(doc.get("_undoStack") or [])
    undo.append({"version": doc.get("version"), "lines": doc.get("lines"), "name": doc.get("name"), "customer": doc.get("customer")})
    doc["lines"] = nxt.get("lines") or []
    if nxt.get("name") is not None:
        doc["name"] = nxt["name"]
    if nxt.get("customer") is not None:
        doc["customer"] = nxt["customer"]
    doc["_undoStack"] = undo[-20:]
    doc["_redoStack"] = redo
    return save_project(doc, bump_version=True, action="redo")


def empty_project(*, name: str = "Untitled Project", customer: str = "") -> dict[str, Any]:
    return {
        "projectId": new_project_id(),
        "name": name,
        "customer": customer,
        "status": "draft",
        "lines": [],
        "version": 0,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "_undoStack": [],
        "_redoStack": [],
    }


def dashboard_stats() -> dict[str, Any]:
    from WEOS.factory.ledger_store import status_counts_toward_turnover

    projects = list_projects(include_archived=False)
    archived = list_projects(status="archived", include_archived=True)
    active = [p for p in projects if p.get("status") == "active"]
    drafts = [p for p in projects if p.get("status") == "draft"]
    with_quote = [p for p in projects if p.get("quotationId")]
    today = datetime.now(timezone.utc).date().isoformat()
    year = datetime.now(timezone.utc).year
    todays = [p for p in projects if str(p.get("updatedAt", "")).startswith(today)]
    year_taxable = 0.0
    year_grand = 0.0
    seen: set[str] = set()
    for p in projects:
        pid = str(p.get("projectId") or "").strip()
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        if not status_counts_toward_turnover(p.get("status")):
            continue
        stamp = str(p.get("updatedAt") or p.get("createdAt") or "")
        if not stamp.startswith(str(year)):
            continue
        year_taxable += float(p.get("totalTaxable") or 0)
        year_grand += float(p.get("totalGrand") or 0)
    return {
        "activeProjects": len(active),
        "draftQuotations": len(drafts) + len([p for p in with_quote if p.get("status") == "draft"]),
        "todaysOrders": len(todays),
        "materialRequiredKg": 0.0,
        "productionStatus": {"queued": len(with_quote), "archived": len(archived)},
        "recentProjects": projects[:8],
        "yearTaxable": round(year_taxable, 2),
        "yearGrand": round(year_grand, 2),
        "yearGst": round(year_grand - year_taxable, 2),
        "year": year,
        "yearBasis": "all_approved_projects",
    }
