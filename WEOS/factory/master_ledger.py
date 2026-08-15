"""Master Ledger — one job's quotes, advances, GST, balance. No cross-job leak.

A job is a ``masterJobId`` (defaults to the project's own id). Package quotes
and the WEOS cart quote on that job roll into project value. Advances must
name a quote id; running balance = project value − all advances on this job.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from WEOS.factory.package_quote import package_money_for_doc

_log = logging.getLogger("weos.master_ledger")


def _money(n: Any) -> float:
    try:
        if n is None or n == "":
            return 0.0
        return round(float(n), 2)
    except (TypeError, ValueError):
        return 0.0


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _norm_qid(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def _blob(doc: Mapping[str, Any]) -> str:
    bits = [
        doc.get("projectId"),
        doc.get("name"),
        doc.get("customer"),
        doc.get("customerMobile"),
        doc.get("quotationId"),
        doc.get("masterJobId"),
        doc.get("customerAddress"),
    ]
    for q in doc.get("packageQuotes") or []:
        if isinstance(q, Mapping):
            bits.append(q.get("quotationId"))
            bits.append(q.get("id"))
    return " ".join(str(b or "") for b in bits).lower()


def match_master_query(doc: Mapping[str, Any] | None, query: str) -> bool:
    """True when this project belongs to the search (name / mobile / quote no)."""
    if not isinstance(doc, Mapping):
        return False
    q = str(query or "").strip()
    if not q:
        return False
    blob = _blob(doc)
    if q.lower() in blob:
        return True
    digits = _digits(q)
    mob = _digits(doc.get("customerMobile"))
    if digits and len(digits) >= 7 and mob and (digits in mob or mob in digits):
        return True
    want = _norm_qid(q)
    if want and _norm_qid(doc.get("quotationId")) == want:
        return True
    for pq in doc.get("packageQuotes") or []:
        if isinstance(pq, Mapping) and want and _norm_qid(pq.get("quotationId")) == want:
            return True
    return False


def _company_ok(doc: Mapping[str, Any], company_gst: str | None) -> bool:
    if not company_gst:
        return True
    try:
        from WEOS.factory.project_store import _belongs_to_company, _norm_company_gst

        return _belongs_to_company(doc, _norm_company_gst(company_gst), include_unscoped=True)
    except Exception:
        return True


def _cart_quote_row(doc: Mapping[str, Any]) -> dict[str, Any] | None:
    from WEOS.factory.project_store import cart_quote_money

    lines = doc.get("lines") or []
    pkg = package_money_for_doc(doc)
    money = cart_quote_money(doc)
    cart_grand = _money(money.get("totalGrand"))
    has_lines = isinstance(lines, list) and len(lines) > 0
    if not has_lines and cart_grand <= 0:
        return None
    if not has_lines and pkg.get("quoteCount"):
        return None
    qid = str(doc.get("quotationId") or "").strip() or None
    return {
        "id": "cart",
        "kind": "weos",
        "projectId": doc.get("projectId"),
        "quotationId": qid,
        "name": doc.get("name"),
        "status": doc.get("status"),
        "lineCount": len(lines) if isinstance(lines, list) else 0,
        "totalTaxable": _money(money.get("totalTaxable")),
        "gstAmount": _money(money.get("totalGst")),
        "totalGrand": cart_grand,
        "projectValue": cart_grand,
        "gstMode": "exclude",
        "gstPercent": money.get("gstPercent"),
        "items": [],
    }


def job_quote_rows(docs: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in docs:
        cart = _cart_quote_row(doc)
        if cart:
            rows.append(cart)
        pkg = package_money_for_doc(doc)
        for q in pkg.get("quotes") or []:
            rows.append(
                {
                    "id": q.get("id"),
                    "kind": "package",
                    "projectId": doc.get("projectId"),
                    "quotationId": q.get("quotationId"),
                    "name": doc.get("name"),
                    "status": doc.get("status"),
                    "note": q.get("note"),
                    "items": q.get("items") or [],
                    "totalTaxable": _money(q.get("totalTaxable")),
                    "gstAmount": _money(q.get("gstAmount")),
                    "totalGrand": _money(q.get("projectValue")),
                    "projectValue": _money(q.get("projectValue")),
                    "gstMode": q.get("gstMode"),
                    "gstPercent": q.get("gstPercent"),
                    "attachmentName": q.get("attachmentName"),
                    "attachmentKey": q.get("attachmentKey"),
                }
            )
    return rows


def _internal_quote_ids(quotes: list[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for q in quotes:
        qid = str(q.get("id") or "").strip()
        if qid:
            out.append(qid)
        # Bind advances to this project+internal id only.
        pid = str(q.get("projectId") or "").strip()
        if pid and qid:
            out.append(f"{pid}:{qid}")
    return out


def _advances_for_job(project_ids: list[str], quotes: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    from WEOS.factory.ledger_store import list_advances_for_projects, list_advances_for_quote_ids

    by_id: dict[int, dict[str, Any]] = {}
    try:
        for row in list_advances_for_projects(project_ids):
            if row.get("id") is not None:
                by_id[int(row["id"])] = row
    except Exception:
        _log.debug("list_advances_for_projects failed", exc_info=True)
    internal = _internal_quote_ids(quotes)
    try:
        for row in list_advances_for_quote_ids(internal):
            pid = str(row.get("projectId") or "").strip()
            if pid and pid not in set(project_ids):
                continue
            if row.get("id") is not None:
                by_id[int(row["id"])] = row
    except Exception:
        _log.debug("list_advances_for_quote_ids failed", exc_info=True)
    rows = list(by_id.values())
    rows.sort(key=lambda a: (str(a.get("paidAt") or ""), int(a.get("id") or 0)))
    return rows


def _load_job_docs(seed: Mapping[str, Any], *, company_gst: str | None) -> list[dict[str, Any]]:
    from WEOS.factory.project_store import list_projects, load_project

    seed_id = str(seed.get("projectId") or "").strip()
    mid = str(seed.get("masterJobId") or seed_id).strip()
    ids = {seed_id} if seed_id else set()
    try:
        rows = list_projects(
            include_archived=True,
            company_gst=company_gst,
            include_unscoped=bool(company_gst),
        )
    except Exception:
        rows = []
    for row in rows:
        rid = str(row.get("projectId") or "").strip()
        rmid = str(row.get("masterJobId") or rid).strip()
        if mid and rmid == mid:
            ids.add(rid)
    docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pid in ids:
        if not pid or pid in seen:
            continue
        seen.add(pid)
        try:
            doc = load_project(pid)
        except FileNotFoundError:
            if pid == seed_id and isinstance(seed, dict):
                doc = dict(seed)
            else:
                continue
        if not _company_ok(doc, company_gst):
            continue
        docs.append(doc)
    if not docs and isinstance(seed, dict):
        docs = [dict(seed)]
    docs.sort(key=lambda d: str(d.get("createdAt") or d.get("updatedAt") or ""))
    return docs


def _running_advances(advances: list[dict[str, Any]], project_value: float) -> list[dict[str, Any]]:
    running = 0.0
    out: list[dict[str, Any]] = []
    for a in advances:
        amt = _money(a.get("amount"))
        running = round(running + amt, 2)
        row = dict(a)
        row["runningAdvance"] = running
        row["balanceAfter"] = round(project_value - running, 2)
        out.append(row)
    return out


def ledger_from_docs(docs: list[Mapping[str, Any]], *, company_gst: str | None = None) -> dict[str, Any]:
    quotes = job_quote_rows(list(docs))
    pids = [str(d.get("projectId") or "") for d in docs if d.get("projectId")]
    advances = _running_advances(
        _advances_for_job(pids, quotes),
        round(sum(_money(q.get("projectValue")) for q in quotes), 2),
    )
    taxable = round(sum(_money(q.get("totalTaxable")) for q in quotes), 2)
    gst_amt = round(sum(_money(q.get("gstAmount")) for q in quotes), 2)
    value = round(sum(_money(q.get("projectValue")) for q in quotes), 2)
    adv_total = round(sum(_money(a.get("amount")) for a in advances), 2)
    seed = docs[0] if docs else {}
    return {
        "kind": "master",
        "masterJobId": str(seed.get("masterJobId") or seed.get("projectId") or ""),
        "projectId": seed.get("projectId"),
        "projectIds": pids,
        "name": seed.get("name"),
        "customer": seed.get("customer"),
        "customerMobile": seed.get("customerMobile"),
        "customerAddress": seed.get("customerAddress"),
        "customerGst": seed.get("customerGst"),
        "companyGst": seed.get("companyGst") or company_gst,
        "quotes": quotes,
        "quoteCount": len(quotes),
        "advances": advances,
        "advanceCount": len(advances),
        "totals": {
            "totalTaxable": taxable,
            "totalGst": gst_amt,
            "gstAmount": gst_amt,
            "totalGrand": value,
            "projectValue": value,
            "totalAdvances": adv_total,
            "balance": round(value - adv_total, 2),
            "currency": "INR",
        },
        "asOf": datetime.now(timezone.utc).isoformat(),
    }


def build_master_ledger(
    *,
    q: str | None = None,
    project_id: str | None = None,
    company_gst: str | None = None,
) -> dict[str, Any]:
    """Search by mobile / name / quote number, or open one job by project id."""
    from WEOS.factory.project_store import list_projects, load_project

    gst = (company_gst or "").strip() or None
    if project_id:
        doc = load_project(str(project_id).strip())
        if not _company_ok(doc, gst):
            raise PermissionError("Project is not in this company workspace")
        docs = _load_job_docs(doc, company_gst=gst)
        led = ledger_from_docs(docs, company_gst=gst)
        return {"matches": [_match_row(docs[0] if docs else doc, led)], "ledger": led}

    query = str(q or "").strip()
    if not query:
        return {"matches": [], "ledger": None, "needQuery": True}

    rows = list_projects(
        q=None,
        include_archived=True,
        company_gst=gst,
        include_unscoped=bool(gst),
    )
    hits: list[dict[str, Any]] = []
    seen_jobs: set[str] = set()
    for row in rows:
        pid = str(row.get("projectId") or "").strip()
        if not pid:
            continue
        try:
            doc = load_project(pid)
        except FileNotFoundError:
            continue
        if not _company_ok(doc, gst):
            continue
        if not match_master_query(doc, query):
            continue
        mid = str(doc.get("masterJobId") or pid)
        if mid in seen_jobs:
            continue
        seen_jobs.add(mid)
        job_docs = _load_job_docs(doc, company_gst=gst)
        led = ledger_from_docs(job_docs, company_gst=gst)
        hits.append(_match_row(job_docs[0] if job_docs else doc, led))

    hits.sort(key=lambda r: str(r.get("updatedAt") or ""), reverse=True)
    ledger = None
    if len(hits) == 1:
        try:
            one = load_project(hits[0]["projectId"])
            ledger = ledger_from_docs(_load_job_docs(one, company_gst=gst), company_gst=gst)
        except FileNotFoundError:
            ledger = None
    return {"matches": hits, "ledger": ledger, "query": query}


def _match_row(doc: Mapping[str, Any], ledger: Mapping[str, Any] | None) -> dict[str, Any]:
    t = (ledger or {}).get("totals") or {}
    return {
        "projectId": doc.get("projectId"),
        "masterJobId": doc.get("masterJobId") or doc.get("projectId"),
        "name": doc.get("name"),
        "customer": doc.get("customer"),
        "customerMobile": doc.get("customerMobile"),
        "quotationId": doc.get("quotationId"),
        "updatedAt": doc.get("updatedAt"),
        "quoteCount": (ledger or {}).get("quoteCount"),
        "projectValue": t.get("projectValue"),
        "totalAdvances": t.get("totalAdvances"),
        "balance": t.get("balance"),
    }
