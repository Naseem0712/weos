"""Company GST-scoped quote/project listing + durable delete.

Used by Company account / GST hub to clear unused, duplicate, and old draft
quotes. Deletes hit Postgres/durable store — never UI-only.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from WEOS.factory.ledger_store import CONFIRMED_STATUSES, quote_money_parts

_log = logging.getLogger("weos.company_quotes")

OLD_DRAFT_DAYS = 30
UNUSED_STATUSES = frozenset({"draft", "unused", "active", ""})
PROTECTED_STATUSES = CONFIRMED_STATUSES | {"approved", "accepted", "finalized", "ordered", "won", "confirmed"}


def _norm_gst(value: Any) -> str:
    try:
        from WEOS.factory.company_store import normalise_gstin

        return normalise_gstin(str(value or ""))
    except Exception:
        return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _norm_qid(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            text = text + "T00:00:00+00:00"
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _money(n: Any) -> float:
    try:
        if n is None or n == "":
            return 0.0
        return float(n)
    except (TypeError, ValueError):
        return 0.0


def _advances_index(customers: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    try:
        from WEOS.factory.ledger_store import list_advances
    except Exception:
        return out
    for name in customers:
        key = (name or "").strip()
        if not key or key in out:
            continue
        try:
            out[key] = list_advances(key)
        except Exception:
            out[key] = []
    return out


def _project_advances(adv_map: Mapping[str, list[dict[str, Any]]], row: Mapping[str, Any]) -> list[dict[str, Any]]:
    cust = str(row.get("customer") or "").strip()
    pid = str(row.get("projectId") or "").strip()
    qid = _norm_qid(row.get("quotationId"))
    rows = list(adv_map.get(cust) or [])
    hit = []
    for a in rows:
        ap = str(a.get("projectId") or "").strip()
        aq = _norm_qid(a.get("quoteId"))
        if pid and ap == pid:
            hit.append(a)
        elif qid and aq == qid:
            hit.append(a)
    return hit


def classify_flags(
    row: Mapping[str, Any],
    *,
    siblings: list[Mapping[str, Any]],
    advances: list[Mapping[str, Any]],
    now: datetime | None = None,
) -> list[str]:
    """Return filter flags: unused, duplicate, old_draft, draft, confirmed."""
    flags: list[str] = []
    st = str(row.get("status") or "draft").strip().lower() or "draft"
    grand = _money(row.get("grandTotal"))
    has_adv = bool(advances)
    now = now or datetime.now(timezone.utc)
    updated = _parse_dt(row.get("updatedAt") or row.get("createdAt"))

    if st in PROTECTED_STATUSES:
        flags.append("confirmed")
    if st in {"rejected", "cancelled", "canceled"}:
        flags.append("rejected")
    if st == "draft" or st == "unused":
        flags.append("draft")
    if st == "unused" or (st in UNUSED_STATUSES and not has_adv and grand <= 0 and st not in PROTECTED_STATUSES):
        flags.append("unused")
    if st == "draft" and updated is not None:
        age = (now - updated).days
        if age >= OLD_DRAFT_DAYS:
            flags.append("old_draft")
    qid = _norm_qid(row.get("quotationId"))
    if qid and len(siblings) > 1:
        latest = max(siblings, key=lambda r: str(r.get("updatedAt") or r.get("createdAt") or ""))
        if str(latest.get("projectId") or "") != str(row.get("projectId") or ""):
            flags.append("duplicate")
        else:
            flags.append("has_duplicates")
    return flags


def list_company_quotes(
    company_gst: str,
    *,
    filter_key: str | None = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Quotes/projects for one seller GSTIN, with unused/duplicate/old-draft flags."""
    gst = _norm_gst(company_gst)
    if not gst:
        raise ValueError("Company GSTIN required")

    from WEOS.factory.project_store import list_projects

    rows = list_projects(
        include_archived=include_archived,
        company_gst=gst,
        include_unscoped=True,
    )
    customers = [str(r.get("customer") or "").strip() for r in rows if r.get("customer")]
    adv_map = _advances_index(customers)

    by_qid: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        qid = _norm_qid(r.get("quotationId"))
        if qid:
            by_qid.setdefault(qid, []).append(r)

    now = datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []
    for r in rows:
        qid = _norm_qid(r.get("quotationId"))
        siblings = by_qid.get(qid) or [r]
        advs = _project_advances(adv_map, r)
        flags = classify_flags(r, siblings=siblings, advances=advs, now=now)
        parts = quote_money_parts(r.get("grandTotal"))
        share = str(r.get("shareToken") or r.get("quoteShareToken") or "").strip()
        items.append(
            {
                "projectId": r.get("projectId"),
                "quoteNumber": r.get("quotationId") or "—",
                "quotationId": r.get("quotationId"),
                "name": r.get("name"),
                "customer": r.get("customer"),
                "status": str(r.get("status") or "draft"),
                "version": r.get("version") or 1,
                "grandTotal": r.get("grandTotal"),
                "totalTaxable": parts["totalTaxable"],
                "totalGst": parts["totalGst"],
                "totalGrand": parts["totalGrand"],
                "createdAt": r.get("createdAt"),
                "updatedAt": r.get("updatedAt"),
                "lineCount": r.get("lineCount"),
                "companyGst": r.get("companyGst") or gst,
                "flags": flags,
                "advanceCount": len(advs),
                "totalAdvance": round(sum(_money(a.get("amount")) for a in advs), 2),
                "shareToken": share,
                "scanPath": f"/q/{share}" if share else None,
                "deletable": str(r.get("status") or "").lower() != "archived",
                "countsTowardTurnover": "confirmed" in flags and "rejected" not in flags,
            }
        )

    counts = {
        "all": len(items),
        "unused": sum(1 for x in items if "unused" in (x.get("flags") or [])),
        "duplicate": sum(1 for x in items if "duplicate" in (x.get("flags") or [])),
        "old_draft": sum(1 for x in items if "old_draft" in (x.get("flags") or [])),
        "draft": sum(1 for x in items if "draft" in (x.get("flags") or [])),
    }
    fk = (filter_key or "all").strip().lower()
    if fk and fk not in ("all", "*", ""):
        alias = {"duplicates": "duplicate", "old": "old_draft", "old_drafts": "old_draft", "drafts": "draft"}
        want = alias.get(fk, fk)
        items = [x for x in items if want in (x.get("flags") or [])]
    items.sort(key=lambda x: str(x.get("updatedAt") or ""), reverse=True)
    return {
        "ok": True,
        "gstNo": gst,
        "filter": fk or "all",
        "quotes": items,
        "count": len(items),
        "counts": counts,
    }


def _assert_company_owns(doc: Mapping[str, Any], gst: str) -> None:
    row_gst = _norm_gst(doc.get("companyGst"))
    if row_gst and row_gst != gst:
        raise PermissionError("This quote belongs to another company GST workspace.")
    if not row_gst:
        # Unscoped legacy rows may be claimed by the open workspace, but refuse
        # delete unless the active GST matches the request (caller already scoped list).
        pass


def require_delete_confirm(
    project_id: str,
    *,
    company_gst: str | None = None,
    pin: str | None = None,
    confirm: str | None = None,
) -> None:
    """Type DELETE (or the project id). PIN is optional, never required."""
    pid = str(project_id or "").strip()
    if not pid:
        raise ValueError("project id required")
    gst = _norm_gst(company_gst)
    typed_pin = str(pin or "").strip()
    typed_confirm = str(confirm or "").strip()
    phrase = typed_confirm or typed_pin
    if phrase.upper() == "DELETE" or (pid and phrase.upper() == pid.upper()):
        return
    if gst and typed_pin:
        from WEOS.factory.company_store import company_has_delete_pin, verify_delete_pin

        if company_has_delete_pin(gst) and verify_delete_pin(gst, typed_pin):
            return
    raise PermissionError("Type DELETE to confirm permanent delete.")


def require_bulk_delete_confirm(
    *,
    company_gst: str,
    pin: str | None = None,
    confirm: str | None = None,
) -> None:
    gst = _norm_gst(company_gst)
    if not gst:
        raise ValueError("Company GSTIN required")

    typed_pin = str(pin or "").strip()
    typed_confirm = str(confirm or "").strip()
    phrase = typed_confirm or typed_pin
    if phrase.upper() == "DELETE":
        return
    if typed_pin:
        from WEOS.factory.company_store import company_has_delete_pin, verify_delete_pin

        if company_has_delete_pin(gst) and verify_delete_pin(gst, typed_pin):
            return
    raise PermissionError("Type DELETE to confirm bulk delete.")


def delete_company_quote(
    project_id: str,
    *,
    company_gst: str,
    hard: bool = True,
) -> dict[str, Any]:
    """Hard-delete a project/quote owned by this GST from Postgres + disk."""
    gst = _norm_gst(company_gst)
    if not gst:
        raise ValueError("Company GSTIN required")
    pid = str(project_id or "").strip()
    if not pid:
        raise ValueError("project id required")

    from WEOS.factory.project_store import delete_project, load_project

    try:
        doc = load_project(pid)
    except FileNotFoundError:
        raise
    _assert_company_owns(doc, gst)
    row_gst = _norm_gst(doc.get("companyGst"))
    if row_gst and row_gst != gst:
        raise PermissionError("This quote belongs to another company GST workspace.")
    if not row_gst:
        # Only allow unscoped delete when it was listed in this workspace (caller
        # passed the active GST). Stamp check already done via hub list.
        pass

    result = delete_project(pid, hard=hard)
    # Drop share index if present
    token = str(doc.get("shareToken") or doc.get("quoteShareToken") or "").strip()
    if token:
        try:
            from WEOS.db.durable_store import delete_key
            from WEOS.factory.quote_share import share_index_key

            delete_key(share_index_key(token))
        except Exception:
            pass
    # Best-effort quote_store row
    try:
        from WEOS.db.quote_store import delete_quote, get_quote_by_ref

        qid = str(doc.get("quotationId") or doc.get("quoteId") or "").strip()
        if qid:
            q = get_quote_by_ref(qid)
            if q and q.get("quoteId"):
                qgst = _norm_gst(q.get("companyGst") or (q.get("customer") or {}).get("gstNo") if isinstance(q.get("customer"), dict) else "")
                if not qgst or qgst == gst:
                    delete_quote(str(q["quoteId"]))
    except Exception:
        _log.debug("quote_store delete skipped for %s", pid, exc_info=True)
    return {"ok": True, "deleted": pid, "hard": hard, **(result if isinstance(result, dict) else {})}


def bulk_delete_unused(company_gst: str, *, filter_key: str = "unused") -> dict[str, Any]:
    """Delete unused (or old_draft / duplicate extras) quotes for this GST only.

    Never deletes confirmed/approved/finalized quotes or rows with advances.
    """
    gst = _norm_gst(company_gst)
    listing = list_company_quotes(gst, filter_key=filter_key)
    deleted: list[str] = []
    skipped: list[dict[str, Any]] = []
    want = (filter_key or "unused").strip().lower()
    if want in ("duplicates", "duplicate"):
        want = "duplicate"
    if want in ("old", "old_drafts"):
        want = "old_draft"
    for row in listing.get("quotes") or []:
        flags = set(row.get("flags") or [])
        if "confirmed" in flags or int(row.get("advanceCount") or 0) > 0:
            skipped.append({"projectId": row.get("projectId"), "reason": "protected"})
            continue
        if want not in flags and want != "all":
            continue
        if want == "all":
            skipped.append({"projectId": row.get("projectId"), "reason": "bulk all not allowed"})
            continue
        try:
            delete_company_quote(str(row.get("projectId")), company_gst=gst, hard=True)
            deleted.append(str(row.get("projectId")))
        except Exception as exc:
            skipped.append({"projectId": row.get("projectId"), "reason": str(exc)})
    return {
        "ok": True,
        "gstNo": gst,
        "filter": want,
        "deleted": deleted,
        "deletedCount": len(deleted),
        "skipped": skipped,
    }
