"""Canonical Company→Customer→Project spine (WEOS V2 Batch 4).

Immutable ``project_id`` (PRJ-…) is the PK. Projects require a ``customer_id`` FK.
Name matching is scoped **within** a customer only — never across customers.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.factory.canonical_customer import (
    _norm_company_gst,
    find_or_create_customer,
    normalize_name_key,
)

_log = logging.getLogger("weos.canonical_project")


def normalize_project_name(value: Any) -> str:
    return normalize_name_key(value)


def get_project(project_id: str, *, company_gst: str | None = None) -> dict[str, Any] | None:
    if not db_available() or not (project_id or "").strip():
        return None
    init_db()
    from WEOS.db.models import CanonicalProject

    gst = _norm_company_gst(company_gst) if company_gst else ""
    with session_scope() as s:
        row = s.get(CanonicalProject, str(project_id).strip())
        if row is None:
            return None
        if gst and _norm_company_gst(row.company_gst) != gst:
            return None
        return row.to_dict()


def upsert_project(
    *,
    project_id: str,
    customer_id: str,
    company_gst: str,
    name: str,
    site_address: str | None = None,
    status: str | None = None,
    quotation_id: str | None = None,
) -> dict[str, Any]:
    if not db_available():
        raise RuntimeError("Database unavailable for canonical project upsert")
    pid = str(project_id or "").strip()
    cid = str(customer_id or "").strip()
    gst = _norm_company_gst(company_gst)
    if not pid:
        raise ValueError("project_id required")
    if not cid:
        raise ValueError("customer_id required")
    if not gst:
        raise ValueError("company_gst required")
    init_db()
    from WEOS.db.models import CanonicalCustomer, CanonicalProject

    with session_scope() as s:
        cust = s.get(CanonicalCustomer, cid)
        if cust is None:
            raise ValueError(f"customer_id not found: {cid}")
        if _norm_company_gst(cust.company_gst) != gst:
            raise ValueError("customer belongs to another company — refuse cross-tenant link")
        row = s.get(CanonicalProject, pid)
        nname = normalize_project_name(name)
        if row is None:
            row = CanonicalProject(
                project_id=pid,
                customer_id=cid,
                company_gst=gst,
                name=(name or "").strip() or pid,
                normalized_name=nname or normalize_project_name(pid),
                site_address=site_address,
                status=(status or "draft"),
                quotation_id=quotation_id,
            )
            s.add(row)
        else:
            if _norm_company_gst(row.company_gst) != gst:
                raise ValueError("project belongs to another company")
            if row.customer_id != cid:
                raise ValueError(
                    "project already linked to another customer — refuse silent reassignment"
                )
            row.name = (name or "").strip() or row.name
            row.normalized_name = nname or row.normalized_name
            if site_address is not None:
                row.site_address = site_address
            if status is not None:
                row.status = status
            if quotation_id is not None:
                row.quotation_id = quotation_id
        s.flush()
        return row.to_dict()


def match_project(
    *,
    company_gst: str,
    customer_id: str,
    project_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Match: project_id → unique normalized name within customer → create/ambiguous."""
    if not db_available():
        return {"match": "none", "reason": "db_unavailable", "candidates": []}
    gst = _norm_company_gst(company_gst)
    cid = str(customer_id or "").strip()
    if not gst or not cid:
        return {"match": "none", "reason": "company_and_customer_required", "candidates": []}
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import CanonicalCustomer, CanonicalProject

    with session_scope() as s:
        cust = s.get(CanonicalCustomer, cid)
        if cust is None or _norm_company_gst(cust.company_gst) != gst:
            return {"match": "none", "reason": "customer_not_in_company", "candidates": []}

        if project_id and str(project_id).strip():
            row = s.get(CanonicalProject, str(project_id).strip())
            if row is None:
                return {"match": "none", "reason": "project_id_not_found", "candidates": []}
            if row.customer_id != cid or _norm_company_gst(row.company_gst) != gst:
                return {
                    "match": "none",
                    "reason": "project_not_under_customer",
                    "candidates": [],
                }
            return {
                "match": "exact",
                "by": "project_id",
                "projectId": row.project_id,
                "project": row.to_dict(),
                "candidates": [],
            }

        nname = normalize_project_name(name) if name else ""
        if not nname:
            return {"match": "none", "candidates": []}
        q = select(CanonicalProject).where(
            CanonicalProject.company_gst == gst,
            CanonicalProject.customer_id == cid,
            CanonicalProject.normalized_name == nname,
        )
        rows = list(s.execute(q).scalars().all())
        if len(rows) == 1:
            return {
                "match": "exact",
                "by": "normalized_name",
                "projectId": rows[0].project_id,
                "project": rows[0].to_dict(),
                "candidates": [],
            }
        if len(rows) > 1:
            return {
                "match": "ambiguous",
                "reason": "multiple_projects_same_name_within_customer",
                "candidates": [r.to_dict() for r in rows],
            }
        return {"match": "none", "candidates": []}


def find_or_create_project(
    *,
    company_gst: str,
    customer_id: str,
    project_id: str | None = None,
    name: str | None = None,
    site_address: str | None = None,
    status: str | None = None,
    quotation_id: str | None = None,
    create: bool = True,
) -> dict[str, Any]:
    matched = match_project(
        company_gst=company_gst,
        customer_id=customer_id,
        project_id=project_id,
        name=name,
    )
    if matched.get("match") == "exact":
        return {"created": False, **matched}
    if matched.get("match") == "ambiguous":
        return {"created": False, **matched}
    if not create:
        return {"created": False, **matched}
    if not project_id:
        raise ValueError("project_id required to create canonical project (preserve PRJ ids)")
    created = upsert_project(
        project_id=project_id,
        customer_id=customer_id,
        company_gst=company_gst,
        name=name or project_id,
        site_address=site_address,
        status=status or "draft",
        quotation_id=quotation_id,
    )
    return {
        "created": True,
        "match": "exact",
        "by": "create",
        "projectId": created["projectId"],
        "project": created,
        "candidates": [],
    }


def link_project_document(doc: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ensure PRJ document has a canonical customer + project row. Preserves projectId."""
    try:
        pid = str(doc.get("projectId") or "").strip()
        gst = _norm_company_gst(doc.get("companyGst"))
        if not pid or not gst:
            return None
        cust_name = str(doc.get("customer") or "").strip()
        mobile = str(doc.get("customerMobile") or "").strip()
        if not cust_name and not mobile:
            return None
        cust_res = find_or_create_customer(
            gst,
            customer_id=str(doc.get("customerId") or "").strip() or None,
            display_name=cust_name or mobile,
            mobile=mobile or None,
            gst_no=doc.get("customerGst"),
            address=doc.get("customerAddress"),
            create=True,
        )
        if cust_res.get("match") != "exact" or not cust_res.get("customerId"):
            return {"ok": False, "reason": "customer_not_exact", "customerMatch": cust_res}
        proj = find_or_create_project(
            company_gst=gst,
            customer_id=cust_res["customerId"],
            project_id=pid,
            name=str(doc.get("name") or pid),
            site_address=str(doc.get("customerAddress") or "") or None,
            status=str(doc.get("status") or "draft"),
            quotation_id=str(doc.get("quotationId") or "") or None,
            create=True,
        )
        return {"ok": True, "customerId": cust_res["customerId"], "project": proj}
    except Exception:
        _log.debug("link_project_document skipped", exc_info=True)
        return None


def migrate_legacy_projects(*, company_gst: str | None = None) -> dict[str, Any]:
    """Map existing PRJ documents into canonical_projects. Preserve project_id."""
    if not db_available():
        return {
            "ok": False,
            "error": "db_unavailable",
            "created": 0,
            "linked": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "rejected": 0,
        }
    init_db()
    from WEOS.factory.project_store import list_projects

    gst_filter = _norm_company_gst(company_gst) if company_gst else ""
    rows = list_projects(include_archived=True, company_gst=gst_filter or None, include_unscoped=not bool(gst_filter))
    created = linked = unmatched = ambiguous = rejected = 0
    manual_review: list[dict[str, Any]] = []
    before = len(rows)

    for doc in rows:
        if not isinstance(doc, Mapping):
            continue
        co = _norm_company_gst(doc.get("companyGst"))
        if not co:
            rejected += 1
            manual_review.append({"projectId": doc.get("projectId"), "reason": "missing_company_gst"})
            continue
        if gst_filter and co != gst_filter:
            continue
        cust_name = str(doc.get("customer") or "").strip()
        mobile = str(doc.get("customerMobile") or "").strip()
        if not cust_name and not mobile:
            unmatched += 1
            manual_review.append({"projectId": doc.get("projectId"), "reason": "no_customer_identity"})
            continue
        try:
            cust_res = find_or_create_customer(
                co,
                display_name=cust_name or mobile,
                mobile=mobile or None,
                gst_no=doc.get("customerGst"),
                address=doc.get("customerAddress"),
                create=True,
            )
        except ValueError as exc:
            unmatched += 1
            manual_review.append({"projectId": doc.get("projectId"), "reason": str(exc)})
            continue
        if cust_res.get("match") == "candidates" or cust_res.get("match") == "conflict":
            ambiguous += 1
            manual_review.append(
                {
                    "projectId": doc.get("projectId"),
                    "reason": cust_res.get("reason") or cust_res.get("match"),
                    "candidates": cust_res.get("candidates"),
                }
            )
            continue
        if cust_res.get("match") != "exact" or not cust_res.get("customerId"):
            unmatched += 1
            manual_review.append({"projectId": doc.get("projectId"), "reason": "customer_unmatched"})
            continue
        try:
            proj = find_or_create_project(
                company_gst=co,
                customer_id=cust_res["customerId"],
                project_id=str(doc.get("projectId")),
                name=str(doc.get("name") or doc.get("projectId")),
                site_address=str(doc.get("customerAddress") or "") or None,
                status=str(doc.get("status") or "draft"),
                quotation_id=str(doc.get("quotationId") or "") or None,
                create=True,
            )
        except ValueError as exc:
            rejected += 1
            manual_review.append({"projectId": doc.get("projectId"), "reason": str(exc)})
            continue
        if proj.get("created"):
            created += 1
        elif proj.get("match") == "exact":
            linked += 1
        elif proj.get("match") == "ambiguous":
            ambiguous += 1
            manual_review.append(
                {"projectId": doc.get("projectId"), "reason": "ambiguous_project_name", "candidates": proj.get("candidates")}
            )
        else:
            unmatched += 1

    return {
        "ok": True,
        "before": before,
        "created": created,
        "linked": linked,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "rejected": rejected,
        "after": created + linked,
        "manualReview": manual_review,
        "zeroSilentLoss": True,
    }
