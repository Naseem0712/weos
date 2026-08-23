"""Durable public quote share tokens + live scan record.

QR codes encode ``/q/{token}`` (also ``/scan/{token}``). The token is stable
across quote edits; scanning always reads the latest project + ledger from DB,
never a frozen PDF snapshot.

Tokens live on the project document (``shareToken``) and as a durable index
row ``quote_share:{token}`` so lookup survives redeploys.
"""

from __future__ import annotations

import html
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

_log = logging.getLogger("weos.quote_share")

TOKEN_KEY_PREFIX = "quote_share:"
OLD_DRAFT_DAYS = 30
SCANNER_REJECT_DAYS = 7
SCANNER_APPROVE_DAYS = 15
ACCESS_PERMISSION_KEYS = ("design", "rate", "amount", "advances", "pdf")
DEFAULT_ACCESS_PERMISSIONS = {
    "design": True,
    "rate": False,
    "amount": False,
    "advances": True,
    "pdf": False,
}


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def scanner_decision_windows(doc: Mapping[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Public QR scanner: reject ≤ 7 days, approve ≤ 15 days from generate date.

    Company panel approve/reject is unlimited and must not use this helper.
    """
    src = doc if isinstance(doc, Mapping) else {}
    generated = _parse_iso(src.get("createdAt") or src.get("generatedAt") or src.get("updatedAt"))
    stamp = now or datetime.now(timezone.utc)
    if generated is not None and generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    status = str(src.get("status") or "draft").strip().lower() or "draft"
    from WEOS.factory.ledger_store import CONFIRMED_STATUSES

    already_approved = status in CONFIRMED_STATUSES
    already_rejected = status in {"rejected", "cancelled", "canceled"}
    age_days = None
    if generated is not None:
        age_days = max(0.0, (stamp - generated).total_seconds() / 86400.0)
    can_reject = (not already_rejected) and age_days is not None and age_days <= SCANNER_REJECT_DAYS
    can_approve = (not already_approved) and age_days is not None and age_days <= SCANNER_APPROVE_DAYS
    reject_until = (generated + timedelta(days=SCANNER_REJECT_DAYS)).isoformat() if generated else None
    approve_until = (generated + timedelta(days=SCANNER_APPROVE_DAYS)).isoformat() if generated else None
    return {
        "generatedAt": generated.isoformat() if generated else None,
        "ageDays": round(age_days, 2) if age_days is not None else None,
        "canApprove": bool(can_approve),
        "canReject": bool(can_reject),
        "approveUntil": approve_until,
        "rejectUntil": reject_until,
        "approveDays": SCANNER_APPROVE_DAYS,
        "rejectDays": SCANNER_REJECT_DAYS,
        "alreadyApproved": already_approved,
        "alreadyRejected": already_rejected,
    }


def _clean_phone(value: Any) -> str:
    import re

    return re.sub(r"\D", "", str(value or ""))


def _mask_phone(value: Any, *, prefix: int = 4, suffix: int = 1) -> str:
    digits = _clean_phone(value)
    if not digits:
        return ""
    n = len(digits)
    # Show the beginning for recognition and only one ending digit. The hidden
    # middle must include the last-6 verification digits, so never expose last 4.
    pre = max(1, min(int(prefix or 0), n - 2))
    suf = max(0, min(int(suffix or 0), n - pre - 1))
    if n <= 6:
        pre = 1
        suf = 1 if n > 2 else 0
    hidden = max(1, n - pre - suf)
    return digits[:pre] + ("*" * hidden) + (digits[-suf:] if suf else "")


def _last_digits(value: Any, *, count: int = 6) -> str:
    digits = _clean_phone(value)
    return digits[-count:] if digits and len(digits) >= count else digits


def _customer_phone_for_doc(doc: Mapping[str, Any]) -> str:
    phone = _clean_phone(doc.get("customerMobile"))
    if phone:
        return phone
    customer_name = str(doc.get("customer") or "").strip()
    if customer_name:
        try:
            from WEOS.factory.customer_store import load_customer_profile

            profile = load_customer_profile(customer_name) or {}
            return _clean_phone(profile.get("phone"))
        except Exception:
            return ""
    return ""


def _verify_last6(expected_phone: Any, provided: Any, *, who: str = "mobile") -> str:
    expected = _clean_phone(expected_phone)
    got = _clean_phone(provided)
    if len(expected) < 6:
        raise ValueError(f"{who.title()} number is not saved for verification.")
    if len(got) < 6:
        raise ValueError(f"Enter last 6 digits of the {who} number.")
    if _last_digits(got) != _last_digits(expected):
        raise PermissionError(f"Last 6 digits do not match the {who} number.")
    return expected


def _access_permissions(raw: Mapping[str, Any] | None = None) -> dict[str, bool]:
    src = raw if isinstance(raw, Mapping) else {}
    return {key: bool(src.get(key, DEFAULT_ACCESS_PERMISSIONS[key])) for key in ACCESS_PERMISSION_KEYS}


def _customer_scanner_approved(doc: Mapping[str, Any]) -> bool:
    from WEOS.factory.ledger_store import CONFIRMED_STATUSES

    status = str(doc.get("status") or "").strip().lower()
    if status not in CONFIRMED_STATUSES:
        return False
    approval = doc.get("approval") if isinstance(doc.get("approval"), Mapping) else {}
    source = str(approval.get("source") or doc.get("approvalSource") or "").strip().lower()
    if source != "scanner":
        return False
    customer_mobile = _customer_phone_for_doc(doc)
    approved_mobile = approval.get("byMobile") or doc.get("approvedByMobile")
    return bool(customer_mobile and _last_digits(customer_mobile) == _last_digits(approved_mobile))


def apply_scanner_status(
    ref: str,
    status: str,
    *,
    confirm_reject: bool = False,
    name: Any = None,
    mobile: Any = None,
    verify_last6: Any = None,
    note: Any = None,
) -> dict[str, Any]:
    """Approve/reject from the public QR page only — time-windowed."""
    doc = resolve_public_ref(ref)
    if not isinstance(doc, Mapping) or not doc.get("projectId"):
        raise FileNotFoundError("Quote not found")
    win = scanner_decision_windows(doc)
    want = str(status or "").strip().lower()
    pid = str(doc.get("projectId"))
    from WEOS.factory.project_store import set_project_status

    if want == "approved":
        if not win.get("canApprove"):
            raise PermissionError("Approve from this scan page is only available for 15 days from the generate date.")
        by_name = str(name or "").strip()
        if not by_name:
            raise ValueError("Enter your name to approve this quote.")
        expected_mobile = _customer_phone_for_doc(doc)
        by_mobile = _verify_last6(expected_mobile, verify_last6 or mobile, who="customer mobile")
        return set_project_status(
            pid,
            "approved",
            source="scanner",
            by_name=by_name,
            by_mobile=by_mobile,
            note=note,
        )
    if want in {"rejected", "reject"}:
        if not confirm_reject:
            raise ValueError("Confirm reject to un-approve this quote.")
        if not win.get("canReject"):
            raise PermissionError("Reject from this scan page is only available for 7 days from the generate date.")
        by_name = str(name or "").strip()
        if not by_name:
            raise ValueError("Enter your name to reject this quote.")
        expected_mobile = _customer_phone_for_doc(doc)
        by_mobile = _verify_last6(expected_mobile, verify_last6 or mobile, who="customer mobile")
        return set_project_status(
            pid,
            "rejected",
            source="scanner",
            by_name=by_name,
            by_mobile=by_mobile,
            note=note,
        )
    raise ValueError("Choose approve or reject")


def _public_access_grants(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    grants = doc.get("publicAccessGrants") if isinstance(doc, Mapping) else []
    out: list[dict[str, Any]] = []
    for row in grants or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("status") or "active").lower() not in {"active", "approved"}:
            continue
        out.append(
            {
                "role": str(row.get("role") or "").strip(),
                "name": str(row.get("name") or "").strip(),
                "phoneMasked": _mask_phone(row.get("mobile")),
                "createdAt": row.get("createdAt"),
                "grantedByName": row.get("grantedByName") or "",
                "permissions": _access_permissions(row.get("permissions") if isinstance(row.get("permissions"), Mapping) else None),
            }
        )
    return out[-30:]


def add_monitor_access(
    ref: str,
    *,
    role: Any,
    name: Any,
    mobile: Any,
    granted_by_name: Any = None,
    customer_last6: Any = None,
    permissions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Customer-scanner grants a protected monitor link to another stakeholder."""
    doc = resolve_public_ref(ref)
    if not isinstance(doc, dict) or not doc.get("projectId"):
        raise FileNotFoundError("Quote not found")
    if not _customer_scanner_approved(doc):
        raise PermissionError("Monitor access can be given only after the customer approves this quote from the scanner.")
    expected_mobile = _customer_phone_for_doc(doc)
    _verify_last6(expected_mobile, customer_last6, who="customer mobile")
    role_s = str(role or "").strip()
    name_s = str(name or "").strip()
    mobile_s = _clean_phone(mobile)
    grantor = str(granted_by_name or doc.get("customer") or "").strip()
    if not role_s:
        raise ValueError("Enter role, e.g. Architect / Site incharge / Accounts.")
    if not name_s:
        raise ValueError("Enter access person's name.")
    if len(mobile_s) < 8:
        raise ValueError("Enter a valid mobile number for this access.")
    perms = _access_permissions(permissions)
    if not any(perms.values()):
        raise ValueError("Select at least one thing to show for this access.")
    token = secrets.token_urlsafe(12)
    grant = {
        "token": token,
        "role": role_s[:60],
        "name": name_s[:80],
        "mobile": mobile_s,
        "mobileMasked": _mask_phone(mobile_s),
        "status": "active",
        "permissions": perms,
        "createdAt": _now_iso(),
        "grantedByName": grantor[:80],
        "grantedByMobile": expected_mobile,
    }
    grants = [g for g in (doc.get("publicAccessGrants") or []) if isinstance(g, dict)]
    grants.append(grant)
    doc["publicAccessGrants"] = grants[-30:]
    try:
        from WEOS.factory.project_store import save_project

        save_project(doc, bump_version=False, action="public_access_grant")
    except Exception:
        _log.exception("public access grant save failed for %s", doc.get("projectId"))
        raise
    share = ensure_project_share_token(doc, persist=True)
    return {
        "ok": True,
        "role": grant["role"],
        "name": grant["name"],
        "phoneMasked": grant["mobileMasked"],
        "permissions": perms,
        "accessToken": token,
        "accessPath": f"/q/{share}/access/{token}",
        "createdAt": grant["createdAt"],
    }


def verify_monitor_access(ref: str, access_token: str, *, last6: Any) -> dict[str, Any]:
    doc = resolve_public_ref(ref)
    if not isinstance(doc, Mapping):
        raise FileNotFoundError("Quote not found")
    tok = str(access_token or "").strip()
    for row in doc.get("publicAccessGrants") or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("token") or "").strip() != tok:
            continue
        if str(row.get("status") or "active").lower() not in {"active", "approved"}:
            raise PermissionError("This access link is not active.")
        _verify_last6(row.get("mobile"), last6, who="access mobile")
        rec = build_public_quote_record(ref)
        if not rec:
            raise FileNotFoundError("Quote not found")
        rec["accessVerified"] = True
        rec["accessRole"] = row.get("role") or ""
        rec["accessName"] = row.get("name") or ""
        rec["accessPermissions"] = _access_permissions(
            row.get("permissions") if isinstance(row.get("permissions"), Mapping) else None
        )
        return rec
    raise FileNotFoundError("Access link not found")


def public_monitor_access_meta(ref: str, access_token: str) -> dict[str, Any] | None:
    doc = resolve_public_ref(ref)
    if not isinstance(doc, Mapping):
        return None
    tok = str(access_token or "").strip()
    for row in doc.get("publicAccessGrants") or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("token") or "").strip() != tok:
            continue
        return {
            "role": row.get("role") or "",
            "name": row.get("name") or "",
            "phoneMasked": _mask_phone(row.get("mobile")),
            "createdAt": row.get("createdAt"),
            "status": row.get("status") or "active",
            "permissions": _access_permissions(row.get("permissions") if isinstance(row.get("permissions"), Mapping) else None),
        }
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_share_token() -> str:
    """URL-safe token; stable once stored on the quote/project."""
    return secrets.token_urlsafe(18)


def share_index_key(token: str) -> str:
    return f"{TOKEN_KEY_PREFIX}{(token or '').strip()}"


def _norm_gst(value: Any) -> str:
    try:
        from WEOS.factory.company_store import normalise_gstin

        return normalise_gstin(str(value or ""))
    except Exception:
        import re

        return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def ensure_project_share_token(doc: dict[str, Any], *, persist: bool = False) -> str:
    """Guarantee ``shareToken`` on a project dict. Optionally write-through."""
    token = str(doc.get("shareToken") or doc.get("quoteShareToken") or "").strip()
    if not token:
        token = new_share_token()
        doc["shareToken"] = token
        doc["quoteShareToken"] = token
        if persist and doc.get("projectId"):
            try:
                from WEOS.factory.project_store import save_project

                save_project(doc, bump_version=False, action="share_token")
            except Exception:
                _log.exception("persist share token failed for %s", doc.get("projectId"))
    else:
        doc["shareToken"] = token
        doc.setdefault("quoteShareToken", token)
    _index_share_token(token, doc)
    return token


def _index_share_token(token: str, doc: Mapping[str, Any]) -> None:
    token = (token or "").strip()
    if not token:
        return
    payload = {
        "token": token,
        "projectId": doc.get("projectId"),
        "quotationId": doc.get("quotationId") or doc.get("quoteNumber") or doc.get("quoteId"),
        "companyGst": _norm_gst(doc.get("companyGst")),
        "customer": doc.get("customer"),
        "updatedAt": _now_iso(),
    }
    try:
        from WEOS.db.durable_store import put_json

        put_json(share_index_key(token), "quote_share", payload)
    except Exception:
        _log.debug("share token index write skipped", exc_info=True)


def lookup_share_index(token: str) -> dict[str, Any] | None:
    token = (token or "").strip()
    if not token:
        return None
    try:
        from WEOS.db.durable_store import get_json

        row = get_json(share_index_key(token))
        return row if isinstance(row, dict) else None
    except Exception:
        return None


def find_project_by_share_token(token: str) -> dict[str, Any] | None:
    """Resolve a live project document from a public share token."""
    token = (token or "").strip()
    if not token:
        return None
    idx = lookup_share_index(token)
    pid = str((idx or {}).get("projectId") or "").strip()
    if pid:
        try:
            from WEOS.factory.project_store import load_project

            doc = load_project(pid)
            if str(doc.get("shareToken") or doc.get("quoteShareToken") or "").strip() == token:
                return doc
            # Token index can outlive a regenerated token — still return live doc
            # if the project id matches (scan must never die after quote update).
            if not str(doc.get("shareToken") or "").strip():
                doc["shareToken"] = token
            return doc
        except FileNotFoundError:
            pass
        except Exception:
            _log.exception("load project by share token id failed: %s", pid)

    # Scan durable + filesystem projects (dev / missing index).
    try:
        from WEOS.factory.project_store import list_projects, load_project

        for row in list_projects(include_archived=True, company_gst=None, include_unscoped=True):
            try:
                doc = load_project(str(row.get("projectId") or ""))
            except Exception:
                continue
            if str(doc.get("shareToken") or doc.get("quoteShareToken") or "").strip() == token:
                _index_share_token(token, doc)
                return doc
    except Exception:
        _log.exception("share token project scan failed")
    return None


def resolve_public_ref(ref: str) -> dict[str, Any] | None:
    """Resolve ``/q/{ref}`` — token, quote number, quote id, or project id."""
    ref = (ref or "").strip()
    if not ref:
        return None
    doc = find_project_by_share_token(ref)
    if doc:
        return doc
    try:
        from WEOS.factory.project_store import find_project_by_quotation_id, load_project

        hit = find_project_by_quotation_id(ref)
        if isinstance(hit, dict) and hit.get("projectId"):
            return load_project(str(hit["projectId"]))
        try:
            return load_project(ref)
        except FileNotFoundError:
            pass
    except Exception:
        pass
    try:
        from WEOS.db.quote_store import get_quote_by_ref

        q = get_quote_by_ref(ref)
        if isinstance(q, dict):
            pid = q.get("projectId")
            if pid:
                try:
                    from WEOS.factory.project_store import load_project

                    return load_project(str(pid))
                except Exception:
                    pass
            return {"_quoteRow": q, "projectId": q.get("projectId"), "quotationId": q.get("quoteNumber") or q.get("quoteId")}
    except Exception:
        pass
    return None


def _money(n: Any) -> float:
    try:
        if n is None or n == "":
            return 0.0
        return float(n)
    except (TypeError, ValueError):
        return 0.0


def _customer_safe_products(lines: list[Any] | None, *, doc: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Customer-facing line list — no factory BOM / purchase rates."""
    from WEOS.factory.customer_line_view import public_product_row, public_products_from_doc

    if isinstance(doc, Mapping):
        rows = public_products_from_doc(doc)
        if rows:
            return rows
    out: list[dict[str, Any]] = []
    for i, ln in enumerate(lines or []):
        if not isinstance(ln, dict):
            continue
        out.append(public_product_row(i, ln))
    return out


def _advances_for_project(customer: str, project_id: str | None, quote_id: str | None) -> list[dict[str, Any]]:
    if not customer:
        return []
    try:
        from WEOS.factory.ledger_store import list_advances

        rows = list_advances(customer)
    except Exception:
        return []
    pid = str(project_id or "").strip()
    qid = str(quote_id or "").strip().upper()
    matched: list[dict[str, Any]] = []
    for a in rows:
        ap = str(a.get("projectId") or "").strip()
        aq = str(a.get("quoteId") or "").strip().upper()
        if pid and ap == pid:
            matched.append(a)
        elif qid and aq and aq == qid:
            matched.append(a)
        elif not pid and not qid:
            matched.append(a)
    # If none linked to this quote, still show customer advances that name this quote.
    if not matched and (pid or qid):
        return []
    # Chronological for running total
    matched.sort(key=lambda r: str(r.get("paidAt") or r.get("createdAt") or ""))
    running = 0.0
    out = []
    for i, a in enumerate(matched, 1):
        amt = round(_money(a.get("amount")), 2)
        running = round(running + amt, 2)
        out.append(
            {
                "n": i,
                "id": a.get("id"),
                "amount": amt,
                "paymentMode": a.get("paymentMode") or a.get("mode") or "—",
                "date": a.get("paidAt") or a.get("createdAt"),
                "reference": a.get("reference") or "",
                "quoteVersion": a.get("quoteVersion"),
                "runningTotal": running,
            }
        )
    return out


def build_public_quote_record(ref: str) -> dict[str, Any] | None:
    """Live customer/project record for the public scan page."""
    doc = resolve_public_ref(ref)
    quote_row = None
    if isinstance(doc, dict) and doc.get("_quoteRow"):
        quote_row = doc.get("_quoteRow")
        doc = {k: v for k, v in doc.items() if k != "_quoteRow"}
        if not doc.get("lines") and isinstance(quote_row, dict):
            doc["lines"] = quote_row.get("lines") or []
            doc["quotationId"] = doc.get("quotationId") or quote_row.get("quoteNumber")
            doc["status"] = doc.get("status") or quote_row.get("status")
            doc["version"] = doc.get("version") or quote_row.get("version")
            doc["grandTotal"] = doc.get("grandTotal") or quote_row.get("grandTotal")
            doc["customer"] = doc.get("customer") or (
                (quote_row.get("customer") or {}).get("name")
                if isinstance(quote_row.get("customer"), dict)
                else quote_row.get("customer")
            )
            doc["updatedAt"] = doc.get("updatedAt") or quote_row.get("updatedAt")
    if not doc:
        return None

    token = ensure_project_share_token(doc, persist=bool(doc.get("projectId")))
    gst = _norm_gst(doc.get("companyGst"))
    company: dict[str, Any] = {}
    try:
        from WEOS.factory.company_store import load_company, load_company_by_gst

        if gst:
            company = dict(load_company_by_gst(gst) or {})
        if not company:
            company = dict(load_company() or {})
    except Exception:
        company = {}

    customer_name = str(doc.get("customer") or "").strip()
    customer_profile: dict[str, Any] = {}
    try:
        if customer_name:
            from WEOS.factory.customer_store import load_customer_profile

            customer_profile = dict(load_customer_profile(customer_name) or {})
    except Exception:
        customer_profile = {}

    calc = doc.get("lastCalculation") if isinstance(doc.get("lastCalculation"), dict) else {}
    price = (calc.get("price") or {}) if isinstance(calc, dict) else {}
    commercial = _money(price.get("total") if price.get("total") is not None else doc.get("grandTotal"))
    from WEOS.factory.ledger_store import quote_money_parts

    money = quote_money_parts(commercial)
    qid = str(doc.get("quotationId") or doc.get("quoteNumber") or doc.get("quoteId") or "").strip()
    pid = str(doc.get("projectId") or "").strip()
    advances = _advances_for_project(customer_name, pid or None, qid or None)
    total_adv = round(sum(_money(a.get("amount")) for a in advances), 2)
    taxable = money["totalTaxable"]
    grand = money["totalGrand"]
    balance = round(taxable - total_adv, 2)
    balance_gst = round(grand - total_adv, 2)

    versions: list[dict[str, Any]] = []
    try:
        from WEOS.factory.customer_store import _project_versions

        if pid:
            versions = list(_project_versions(pid) or [])
    except Exception:
        versions = []
    version_count = max(int(doc.get("version") or 1), len(versions) + 1)

    status = str(doc.get("status") or "draft").strip().lower() or "draft"
    approval = doc.get("approval") if isinstance(doc.get("approval"), Mapping) else {}
    rejection = doc.get("rejection") if isinstance(doc.get("rejection"), Mapping) else {}
    customer_phone_raw = doc.get("customerMobile") or customer_profile.get("phone") or ""
    products = _customer_safe_products(list(doc.get("lines") or []), doc=doc)
    # Never expose revisionLog / importMeta / undo stacks on the public scan page.
    from WEOS.factory.customer_line_view import totals_by_type
    from WEOS.factory.ledger_store import CONFIRMED_STATUSES
    from WEOS.factory.project_pack import public_pack_payload

    approved = status in CONFIRMED_STATUSES or bool(advances)
    type_totals = totals_by_type(list(doc.get("lines") or []))
    pack = public_pack_payload(doc, share_token=token, approved=True)
    scan_win = scanner_decision_windows(doc)
    ledger_html = f"/q/{token}/ledger" if token else None
    all_pdf = f"/api/public/quote/{token}/all.pdf" if token else None

    return {
        "ok": True,
        "live": True,
        "shareToken": token,
        "scanPath": f"/q/{token}",
        "scanAltPath": f"/scan/{token}",
        "projectId": pid or None,
        "quoteNumber": qid or pid or token,
        "version": int(doc.get("version") or 1),
        "versionCount": version_count,
        "versions": [
            {
                "version": v.get("version"),
                "updatedAt": v.get("updatedAt") or v.get("savedAt"),
                "grandTotal": v.get("grandTotal"),
            }
            for v in versions[-12:]
        ],
        "status": status,
        "approvalStatus": status,
        "approved": approved,
        "approval": {
            "status": approval.get("status") or status,
            "source": approval.get("source") or doc.get("approvalSource") or "",
            "at": approval.get("at") or doc.get("approvedAt"),
            "byName": approval.get("byName") or doc.get("approvedBy") or "",
            "byMobile": _mask_phone(approval.get("byMobile") or doc.get("approvedByMobile") or ""),
            "note": approval.get("note") or "",
        },
        "rejection": {
            "status": rejection.get("status") or ("rejected" if status in {"rejected", "cancelled", "canceled"} else ""),
            "source": rejection.get("source") or doc.get("rejectionSource") or "",
            "at": rejection.get("at") or doc.get("rejectedAt"),
            "byName": rejection.get("byName") or doc.get("rejectedBy") or "",
            "byMobile": _mask_phone(rejection.get("byMobile") or doc.get("rejectedByMobile") or ""),
            "note": rejection.get("note") or doc.get("rejectNote") or "",
        },
        "approvalHistory": [
            {
                "status": h.get("status"),
                "source": h.get("source"),
                "at": h.get("at"),
                "byName": h.get("byName"),
                "byMobile": _mask_phone(h.get("byMobile")),
                "note": h.get("note"),
            }
            for h in (doc.get("approvalHistory") or [])[-8:]
            if isinstance(h, Mapping)
        ],
        "scanner": scan_win,
        "generatedAt": scan_win.get("generatedAt") or doc.get("createdAt"),
        "customer": {
            "name": customer_name or customer_profile.get("name") or "—",
            "phone": _mask_phone(customer_phone_raw),
            "phoneMasked": _mask_phone(customer_phone_raw),
            "verifyDigits": 6 if len(_clean_phone(customer_phone_raw)) >= 6 else 0,
            "gstNo": doc.get("customerGst") or customer_profile.get("gstNo") or "",
            "address": doc.get("customerAddress") or customer_profile.get("address") or "",
        },
        "company": {
            "name": company.get("companyName") or company.get("name") or "",
            "gstNo": company.get("gstNo") or gst or "",
            "phone": company.get("phone") or "",
            "email": company.get("email") or "",
            "address": company.get("address") or "",
            "website": company.get("website") or "",
        },
        "value": {
            "totalTaxable": taxable,
            "totalGst": money["totalGst"],
            "gstPercent": money["gstPercent"],
            "totalGrand": grand,
        },
        "advances": advances,
        "advanceCount": len(advances),
        "totalAdvance": total_adv,
        "balance": balance,
        "balanceWithGst": balance_gst,
        "products": products,
        "productCount": len(products),
        "typeTotals": type_totals,
        "pack": pack,
        "accessGrants": _public_access_grants(doc),
        "canGrantAccess": _customer_scanner_approved(doc),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt") or _now_iso(),
        "customerPdfUrl": f"/api/projects/{pid}/customer-pdf" if pid else None,
        "ledgerPdfUrl": f"/api/customers/{customer_name}/ledger.pdf" if customer_name else None,
        "ledgerHtmlUrl": ledger_html,
        "allPdfUrl": all_pdf,
    }


def public_quote_url(payload: Mapping[str, Any], *, base: str = "") -> str:
    token = str(
        payload.get("shareToken")
        or payload.get("quoteShareToken")
        or payload.get("quoteRef")
        or payload.get("quoteId")
        or payload.get("quoteNumber")
        or payload.get("quotationId")
        or payload.get("projectId")
        or ""
    ).strip()
    from urllib.parse import quote as _urlquote

    ref = _urlquote(token or "WEOS", safe="")
    b = (base or "").rstrip("/")
    return f"{b}/q/{ref}" if b else f"/q/{ref}"


def render_access_verify_html(
    record: Mapping[str, Any] | None,
    *,
    ref: str,
    access_token: str,
    grant: Mapping[str, Any] | None = None,
    message: str = "",
) -> str:
    co = (record or {}).get("company") if isinstance(record, Mapping) else {}
    cust = (record or {}).get("customer") if isinstance(record, Mapping) else {}
    quote_no = (record or {}).get("quoteNumber") if isinstance(record, Mapping) else ref

    def esc(x: Any) -> str:
        return html.escape("" if x is None else str(x))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="robots" content="noindex"/>
<title>Verify access · {esc(quote_no)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#e8e3d8;color:#141410}}
.wrap{{max-width:560px;margin:0 auto;padding:1.25rem 1rem 2.5rem}}
.card{{background:#fffdf9;border:1px solid rgba(20,20,16,.12);border-radius:14px;padding:1rem 1.1rem;box-shadow:0 10px 40px rgba(20,20,16,.06)}}
.muted{{color:#5c584f;font-size:.86rem}}h1{{font-size:1.25rem;margin:.15rem 0 .45rem}}
input{{font:inherit;width:100%;padding:.7rem;border:1px solid rgba(20,20,16,.16);border-radius:10px;background:#fffdf9;margin-top:.25rem}}
.btn{{display:inline-block;background:#0a5a48;color:#f4faf7;border:0;border-radius:10px;padding:.58rem .85rem;font-weight:700;font-size:.92rem;margin-top:.75rem;cursor:pointer}}
.err{{color:#9f1239;margin-top:.65rem;font-size:.86rem}}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="muted">Protected monitor link</div>
    <h1>{esc(co.get('name') if isinstance(co, Mapping) else '') or 'WEOS'} · Quote {esc(quote_no)}</h1>
    <p class="muted">Customer: {esc(cust.get('name') if isinstance(cust, Mapping) else '')} {(' · ' + esc(cust.get('phoneMasked') or cust.get('phone'))) if isinstance(cust, Mapping) and (cust.get('phoneMasked') or cust.get('phone')) else ''}</p>
    {f"<p class='muted'>Access for: <strong>{esc(grant.get('name'))}</strong> · {esc(grant.get('role'))} · {esc(grant.get('phoneMasked'))}</p>" if isinstance(grant, Mapping) else ""}
    <form method="get" action="/q/{esc(ref)}/access/{esc(access_token)}">
      <label><span class="muted">Assigned mobile ke last 6 digits</span><input name="last6" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="Last 6 digits" autofocus/></label>
      <button class="btn" type="submit">Open monitor page</button>
    </form>
    {f'<div class="err">{esc(message)}</div>' if message else ''}
    <p class="muted" style="margin:.8rem 0 0">Number match hone par hi quote, project, advance aur balance view open hoga.</p>
  </div>
</div>
</body>
</html>"""


def render_scan_html(record: Mapping[str, Any], *, base_url: str = "") -> str:
    """Self-contained public HTML — no login. Always reflects ``record`` (live DB)."""
    co = record.get("company") or {}
    cust = record.get("customer") or {}
    val = record.get("value") or {}
    status = str(record.get("status") or "draft")
    approved = bool(record.get("approved"))
    badge = "Approved" if approved else status.replace("_", " ").title()
    badge_bg = "#0a5a48" if approved else ("#b45324" if status in ("draft", "unused") else "#334155")
    access_restricted = bool(record.get("accessVerified"))
    perms = _access_permissions(record.get("accessPermissions") if access_restricted else {k: True for k in ACCESS_PERMISSION_KEYS})
    show_design = (not access_restricted) or perms.get("design")
    show_rate = (not access_restricted) or perms.get("rate")
    show_amount = (not access_restricted) or perms.get("amount")
    show_advances = (not access_restricted) or perms.get("advances")
    show_pdf_links = (not access_restricted) or perms.get("pdf")

    def inr(n: Any) -> str:
        try:
            return f"₹{float(n or 0):,.2f}"
        except (TypeError, ValueError):
            return "₹—"

    def esc(x: Any) -> str:
        return html.escape("" if x is None else str(x))

    def fmt_dt(iso: Any) -> str:
        if not iso:
            return "—"
        text = str(iso)
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.strftime("%d %b %Y, %I:%M %p")
        except Exception:
            return esc(text[:19].replace("T", " "))

    adv_rows = ""
    if show_advances:
        for a in record.get("advances") or []:
            adv_rows += (
                f"<tr><td>{esc(a.get('n'))}</td><td>{inr(a.get('amount'))}</td>"
                f"<td>{esc(a.get('paymentMode'))}</td><td>{fmt_dt(a.get('date'))}</td>"
                f"<td>{inr(a.get('runningTotal'))}</td></tr>"
            )
        if not adv_rows:
            adv_rows = '<tr><td colspan="5" class="muted">No advances recorded yet</td></tr>'

    product_header = "<th>Serial</th><th>Location</th><th>Type</th><th>Size</th><th>Qty</th>"
    if show_rate:
        product_header += "<th>Rate</th>"
    if show_amount:
        product_header += "<th>Amount</th>"
    prod_rows = ""
    if show_design:
        col_count = 5 + (1 if show_rate else 0) + (1 if show_amount else 0)
        for p in record.get("products") or []:
            amt = inr(p.get("amount")) if p.get("amount") is not None else "—"
            rate = esc(p.get("rate") or "—")
            loc = p.get("location") or p.get("locationName") or p.get("positionName") or "—"
            extra = " · ".join(
                x
                for x in (
                    "" if not p.get("glass") or str(p.get("glass")) == "—" else str(p.get("glass")),
                    "" if not p.get("colour") or str(p.get("colour")) == "—" else str(p.get("colour")),
                )
                if x
            )
            type_cell = esc(p.get("type"))
            if extra:
                type_cell += f'<div class="muted" style="font-size:.72rem">{esc(extra)}</div>'
            row = (
                f"<tr><td>{esc(p.get('serial'))}</td><td>{esc(loc)}</td>"
                f"<td>{type_cell}</td><td>{esc(p.get('size'))}</td>"
                f"<td>{esc(p.get('qty'))}</td>"
            )
            if show_rate:
                row += f"<td>{rate}</td>"
            if show_amount:
                row += f"<td>{amt}</td>"
            prod_rows += row + "</tr>"
        if not prod_rows:
            prod_rows = f'<tr><td colspan="{col_count}" class="muted">No products on this quote</td></tr>'

    type_tot_html = ""
    if show_amount:
        for trow in record.get("typeTotals") or []:
            type_tot_html += (
                f"<div class='muted' style='margin:.15rem 0'>{esc(trow.get('type'))} × {esc(trow.get('qty'))}"
                f" · {inr(trow.get('amount'))}</div>"
            )

    pack = record.get("pack") or {}
    pack_html = ""
    upd_html = ""
    for u in pack.get("updates") or []:
        upd_html += (
            f"<div class='item'><div class='muted'>{fmt_dt(u.get('date') or u.get('createdAt'))}</div>"
            f"<div>{esc(u.get('text') or u.get('note') or '')}</div></div>"
        )
    if not upd_html:
        upd_html = '<p class="muted">No process updates yet</p>'
    doc_html = ""
    labels = {"bill": "Bill", "warranty": "Warranty card", "challan": "Delivery challan"}
    for d in pack.get("documents") or []:
        href = esc(d.get("url") or "#")
        if base_url and href.startswith("/"):
            href = base_url.rstrip("/") + href
        kind = labels.get(str(d.get("kind") or ""), str(d.get("kind") or "File").title())
        note = esc(d.get("note") or d.get("filename") or kind)
        ct = str(d.get("contentType") or "")
        thumb = ""
        if ct.startswith("image/"):
            thumb = f'<a href="{href}" target="_blank" rel="noopener"><img src="{href}" alt="" style="max-height:72px;max-width:110px;border-radius:8px;border:1px solid var(--line);object-fit:cover"/></a>'
        open_link = f'<a class="btn ghost" href="{href}" target="_blank" rel="noopener">Open / download</a>' if show_pdf_links else ""
        doc_html += (
            f'<div class="item" style="display:flex;gap:.6rem;align-items:center;flex-wrap:wrap">'
            f"{thumb}<div><strong>{esc(kind)}</strong>"
            f'<div class="muted">{fmt_dt(d.get("date") or d.get("createdAt"))} · {note}</div>'
            f"{open_link}</div></div>"
        )
    if not doc_html:
        doc_html = '<p class="muted">No bills, warranty cards, or delivery challans yet</p>'
    photo_html = ""
    for ph in pack.get("photos") or []:
        href = esc(ph.get("url") or "#")
        if base_url and href.startswith("/"):
            href = base_url.rstrip("/") + href
        cap = esc(ph.get("note") or ph.get("filename") or "Photo")
        photo_html += (
            f'<a href="{href}" target="_blank" rel="noopener" style="display:inline-block;margin:.2rem">'
            f'<img src="{href}" alt="{cap}" style="max-height:140px;max-width:180px;border-radius:10px;border:1px solid var(--line);object-fit:cover"/>'
            f'<div class="muted" style="font-size:.72rem">{fmt_dt(ph.get("date") or ph.get("createdAt"))} · {cap}</div></a>'
        )
    if not photo_html:
        photo_html = '<p class="muted">No process photos yet</p>'
    pack_html = f"""
  <div class="card">
    <h2>Process updates</h2>
    {upd_html}
  </div>
  <div class="card">
    <h2>Bills / warranty / delivery challan</h2>
    {doc_html}
  </div>
  <div class="card">
    <h2>Process photos</h2>
    {photo_html}
  </div>"""
    if access_restricted and not show_design:
        pack_html = ""

    ver_bits = []
    for v in record.get("versions") or []:
        ver_bits.append(f"v{esc(v.get('version'))}")
    if not ver_bits:
        ver_bits.append(f"v{esc(record.get('version') or 1)}")
    versions_txt = ", ".join(ver_bits)
    if int(record.get("versionCount") or 1) > 1:
        versions_txt += f" · {esc(record.get('versionCount'))} versions"

    pdf_url = record.get("customerPdfUrl") or ""
    led_url = record.get("ledgerPdfUrl") or ""
    all_url = record.get("allPdfUrl") or ""
    led_html = record.get("ledgerHtmlUrl") or ""
    if base_url:
        b = base_url.rstrip("/")
        if pdf_url and pdf_url.startswith("/"):
            pdf_url = b + pdf_url
        if led_url and led_url.startswith("/"):
            led_url = b + led_url
        if all_url and all_url.startswith("/"):
            all_url = b + all_url
        if led_html and led_html.startswith("/"):
            led_html = b + led_html

    links = []
    if show_pdf_links and all_url:
        links.append(f'<a class="btn" href="{esc(all_url)}" target="_blank" rel="noopener">Download all (A4 PDF)</a>')
        links.append(f'<a class="btn ghost" href="{esc(all_url)}" target="_blank" rel="noopener">🖨 Print all</a>')
    if show_pdf_links and pdf_url:
        links.append(f'<a class="btn ghost" href="{esc(pdf_url)}" target="_blank" rel="noopener">Customer PDF</a>')
        links.append(f'<a class="btn ghost" href="{esc(pdf_url)}" target="_blank" rel="noopener">🖨 Print quote</a>')
    if show_pdf_links and show_advances and led_url:
        links.append(f'<a class="btn ghost" href="{esc(led_url)}" target="_blank" rel="noopener">Ledger PDF</a>')
        links.append(f'<a class="btn ghost" href="{esc(led_url)}" target="_blank" rel="noopener">🖨 Print ledger</a>')
    if show_pdf_links and show_advances and led_html:
        links.append(f'<a class="btn ghost" href="{esc(led_html)}" target="_blank" rel="noopener">Ledger</a>')
    links_html = " ".join(links) if links else ""

    scan = record.get("scanner") or {}
    approval_info = record.get("approval") or {}
    rejection_info = record.get("rejection") or {}
    active_decision = approval_info if approved else (rejection_info if status in ("rejected", "cancelled", "canceled") else {})
    source_label = str(active_decision.get("source") or "").replace("_", " ").title() or "Pending"
    by_bits = [x for x in (active_decision.get("byName"), active_decision.get("byMobile")) if x]
    decision_by = " · ".join(esc(x) for x in by_bits) or "—"
    decision_at = fmt_dt(active_decision.get("at")) if active_decision else "—"
    decision_note = active_decision.get("note")
    approval_card = f"""
  <div class="card">
    <h2>Approval status</h2>
    <div class="kpis">
      <div class="kpi"><div class="l">Status</div><div class="v">{esc(badge)}</div></div>
      <div class="kpi"><div class="l">Source</div><div class="v">{esc(source_label)}</div></div>
      <div class="kpi"><div class="l">Approved / decided by</div><div class="v">{decision_by}</div></div>
      <div class="kpi"><div class="l">Date & time</div><div class="v">{esc(decision_at)}</div></div>
    </div>
    {f'<p class="muted" style="margin:.55rem 0 0">Note: {esc(decision_note)}</p>' if decision_note else ''}
  </div>"""
    grants_rows = ""
    for g in record.get("accessGrants") or []:
        grants_rows += (
            f"<tr><td>{esc(g.get('role'))}</td><td>{esc(g.get('name'))}</td>"
            f"<td>{esc(g.get('phoneMasked'))}</td><td>{fmt_dt(g.get('createdAt'))}</td></tr>"
        )
    if not grants_rows:
        grants_rows = '<tr><td colspan="4" class="muted">No monitor access links issued yet</td></tr>'
    access_notice = ""
    if record.get("accessVerified"):
        access_notice = (
            f'<div class="card"><h2>Access verified</h2><p class="muted" style="margin:0">'
            f'Role: {esc(record.get("accessRole"))} · Name: {esc(record.get("accessName"))}. '
            f'This protected link is read-only for quote, project, advance and balance monitoring.</p></div>'
        )
    token = esc(record.get("shareToken") or "")
    decide_bits = []
    if not access_restricted and scan.get("canApprove"):
        decide_bits.append('<button class="btn" type="button" id="scanApprove">Approve quote</button>')
    if not access_restricted and scan.get("canReject"):
        decide_bits.append('<button class="btn ghost" type="button" id="scanReject">Reject quote</button>')
    if decide_bits:
        decide_html = f"""
  <div class="card" id="scanDecide">
    <h2>Approve / Reject</h2>
    <p class="muted">From generate date {esc(fmt_dt(scan.get('generatedAt')))}: reject up to {esc(scan.get('rejectDays') or 7)} days, approve up to {esc(scan.get('approveDays') or 15)} days. After that these buttons disappear here — the company panel can still decide any time.</p>
    <div id="scanIdentity" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.5rem;margin:.65rem 0 .35rem">
      <label><span class="muted">Your name</span><input id="scanName" autocomplete="name" value="{esc(cust.get('name') if cust.get('name') != '—' else '')}" style="width:100%;padding:.55rem;border:1px solid var(--line);border-radius:10px;margin-top:.18rem"/></label>
      <label><span class="muted">Customer mobile last 6 digits</span><input id="scanLast6" autocomplete="one-time-code" inputmode="numeric" maxlength="6" placeholder="Last 6 digits" style="width:100%;padding:.55rem;border:1px solid var(--line);border-radius:10px;margin-top:.18rem"/></label>
    </div>
    <div style="margin-top:.45rem">{''.join(decide_bits)}</div>
    <p class="muted" id="scanDecideMsg" style="margin:.45rem 0 0"></p>
  </div>
<script>
(function(){{
    var token = {json.dumps(record.get("shareToken") or "")};
  function go(path, extra){{
    var msg = document.getElementById('scanDecideMsg');
    extra = extra || {{}};
    extra.name = (document.getElementById('scanName') || {{value:''}}).value.trim();
    extra.verifyLast6 = (document.getElementById('scanLast6') || {{value:''}}).value.trim();
    if (!extra.name || !extra.verifyLast6) {{
      if (msg) msg.textContent = 'Naam aur saved customer mobile ke last 6 digits zaroori hain.';
      return;
    }}
    fetch('/api/public/quote/' + encodeURIComponent(token) + '/' + path, {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify(extra)
    }}).then(function(r){{ return r.json().then(function(j){{ return {{ok:r.ok, j:j}}; }}); }})
      .then(function(res){{
        if (!res.ok) {{ if (msg) msg.textContent = (res.j && (res.j.detail||res.j.message)) || 'Could not save'; return; }}
        location.reload();
      }}).catch(function(e){{ if (msg) msg.textContent = e.message || 'Network error'; }});
  }}
  var a = document.getElementById('scanApprove');
  if (a) a.onclick = function(){{ if (confirm('Approve this quote?')) go('approve'); }};
  var r = document.getElementById('scanReject');
  if (r) r.onclick = function(){{ if (confirm('Reject this quote? It drops out of turnover.')) go('reject', {{confirm:true}}); }};
}})();
</script>"""
    elif (not access_restricted) and not approved and not scan.get("alreadyRejected"):
        decide_html = """
  <div class="card">
    <h2>Approve / Reject</h2>
    <p class="muted">Scanner window has ended (reject 7 days / approve 15 days from generate date). The company can still approve or reject from WEOS.</p>
  </div>"""
    else:
        decide_html = ""

    monitor_html = ""
    if (not access_restricted) and bool(record.get("canGrantAccess")):
        monitor_html = f"""
  <div class="card" id="monitorAccess">
    <h2>Monitor access</h2>
    <p class="muted">Customer apna saved mobile last-6 verify karke architect, site incharge, accounts ya kisi trusted person ko read-only project/quote/advance/balance link de sakta hai.</p>
    <div style="overflow:auto;margin:.55rem 0">
      <table><thead><tr><th>Role</th><th>Name</th><th>Mobile</th><th>Issued</th></tr></thead><tbody>{grants_rows}</tbody></table>
    </div>
    <div id="monitorForm" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.5rem;margin-top:.65rem">
      <label><span class="muted">Your name</span><input id="grantBy" autocomplete="name" value="{esc(cust.get('name') if cust.get('name') != '—' else '')}" style="width:100%;padding:.55rem;border:1px solid var(--line);border-radius:10px;margin-top:.18rem"/></label>
      <label><span class="muted">Customer mobile last 6</span><input id="grantLast6" inputmode="numeric" maxlength="6" placeholder="Last 6 digits" style="width:100%;padding:.55rem;border:1px solid var(--line);border-radius:10px;margin-top:.18rem"/></label>
      <label><span class="muted">Role</span><input id="grantRole" placeholder="Architect / Accounts" style="width:100%;padding:.55rem;border:1px solid var(--line);border-radius:10px;margin-top:.18rem"/></label>
      <label><span class="muted">Person name</span><input id="grantName" autocomplete="name" style="width:100%;padding:.55rem;border:1px solid var(--line);border-radius:10px;margin-top:.18rem"/></label>
      <label><span class="muted">Person mobile</span><input id="grantMobile" autocomplete="tel" inputmode="tel" style="width:100%;padding:.55rem;border:1px solid var(--line);border-radius:10px;margin-top:.18rem"/></label>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:.45rem .8rem;margin-top:.7rem">
      <label class="muted"><input id="permDesign" type="checkbox" checked style="width:auto;margin-right:.25rem"/>Design/details</label>
      <label class="muted"><input id="permRate" type="checkbox" style="width:auto;margin-right:.25rem"/>Rate</label>
      <label class="muted"><input id="permAmount" type="checkbox" style="width:auto;margin-right:.25rem"/>Amount/totals</label>
      <label class="muted"><input id="permAdvances" type="checkbox" checked style="width:auto;margin-right:.25rem"/>Advance/balance</label>
      <label class="muted"><input id="permPdf" type="checkbox" style="width:auto;margin-right:.25rem"/>PDF/print/import links</label>
    </div>
    <button class="btn" type="button" id="grantAccessBtn" style="margin-top:.55rem">Generate monitor link</button>
    <p class="muted" id="grantAccessMsg" style="margin:.55rem 0 0"></p>
  </div>
<script>
(function(){{
  var token = {json.dumps(record.get("shareToken") or "")};
  var btn = document.getElementById('grantAccessBtn');
  var msg = document.getElementById('grantAccessMsg');
  if (!btn) return;
  btn.onclick = function(){{
    var payload = {{
      grantedByName: (document.getElementById('grantBy') || {{value:''}}).value.trim(),
      customerLast6: (document.getElementById('grantLast6') || {{value:''}}).value.trim(),
      role: (document.getElementById('grantRole') || {{value:''}}).value.trim(),
      name: (document.getElementById('grantName') || {{value:''}}).value.trim(),
      mobile: (document.getElementById('grantMobile') || {{value:''}}).value.trim(),
      showDesign: !!(document.getElementById('permDesign') || {{checked:false}}).checked,
      showRate: !!(document.getElementById('permRate') || {{checked:false}}).checked,
      showAmount: !!(document.getElementById('permAmount') || {{checked:false}}).checked,
      showAdvances: !!(document.getElementById('permAdvances') || {{checked:false}}).checked,
      allowPdf: !!(document.getElementById('permPdf') || {{checked:false}}).checked
    }};
    if (!payload.customerLast6 || !payload.role || !payload.name || !payload.mobile) {{
      if (msg) msg.textContent = 'Last-6, role, name aur mobile sab required hain.';
      return;
    }}
    if (!payload.showDesign && !payload.showRate && !payload.showAmount && !payload.showAdvances && !payload.allowPdf) {{
      if (msg) msg.textContent = 'Kam se kam ek visibility option select karo.';
      return;
    }}
    btn.disabled = true;
    if (msg) msg.textContent = 'Generating protected link...';
    fetch('/api/public/quote/' + encodeURIComponent(token) + '/access', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify(payload)
    }}).then(function(r){{ return r.json().then(function(j){{ return {{ok:r.ok,j:j}}; }}); }})
      .then(function(res){{
        btn.disabled = false;
        if (!res.ok) {{ if (msg) msg.textContent = (res.j && (res.j.detail||res.j.message)) || 'Could not generate link'; return; }}
        var url = location.origin + res.j.accessPath;
        if (msg) msg.innerHTML = 'Monitor link: <a href="' + url + '" target="_blank" rel="noopener">' + url + '</a>';
      }}).catch(function(e){{ btn.disabled = false; if (msg) msg.textContent = e.message || 'Network error'; }});
  }};
}})();
</script>"""

    kpis_html = ""
    if show_amount:
        kpis_html = f"""
    <div class="kpis" style="margin-top:.7rem">
      <div class="kpi"><div class="l">Taxable</div><div class="v">{inr(val.get('totalTaxable'))}</div></div>
      <div class="kpi"><div class="l">GST {esc(val.get('gstPercent') or 18)}%</div><div class="v">{inr(val.get('totalGst'))}</div></div>
      <div class="kpi"><div class="l">Grand (w/ GST)</div><div class="v">{inr(val.get('totalGrand'))}</div></div>
      <div class="kpi"><div class="l">Advance ({esc(record.get('advanceCount') or 0)}x)</div><div class="v">{inr(record.get('totalAdvance'))}</div></div>
      <div class="kpi"><div class="l">Balance outstanding</div><div class="v">{inr(record.get('balanceWithGst'))}</div></div>
    </div>"""
    elif access_restricted:
        kpis_html = '<p class="muted" style="margin:.65rem 0 0">Commercial value hidden by customer permission.</p>'

    advances_html = ""
    if show_advances:
        advances_html = f"""
  <div class="card">
    <h2>Advances</h2>
    <table>
      <thead><tr><th>#</th><th>Amount</th><th>Mode</th><th>Date</th><th>Running total</th></tr></thead>
      <tbody>{adv_rows}</tbody>
    </table>
  </div>"""

    products_html = ""
    if show_design:
        products_html = f"""
  <div class="card">
    <h2>Products</h2>
    <table>
      <thead><tr>{product_header}</tr></thead>
      <tbody>{prod_rows}</tbody>
    </table>
    {f'<div style="margin-top:.55rem">{type_tot_html}</div>' if type_tot_html else ''}
  </div>"""

    co_name = esc(co.get("name") or "WEOS")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="robots" content="noindex"/>
<title>Quote {esc(record.get('quoteNumber'))} · {co_name}</title>
<style>
:root{{--ink:#141410;--muted:#5c584f;--bg:#e8e3d8;--card:#fffdf9;--line:rgba(20,20,16,.12);--green:#0a5a48}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);
  background:radial-gradient(ellipse 80% 50% at 0% -10%,#c9e5db,transparent 55%),
             radial-gradient(ellipse 60% 40% at 100% 0%,#efd6c2,transparent 50%),var(--bg)}}
.wrap{{max-width:820px;margin:0 auto;padding:1.1rem 1rem 2.5rem}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem;margin-bottom:.85rem;
  box-shadow:0 10px 40px rgba(20,20,16,.06)}}
h1{{font-size:1.35rem;margin:.15rem 0 .25rem}}
h2{{font-size:.95rem;margin:0 0 .55rem}}
.muted{{color:var(--muted);font-size:.82rem}}
.badge{{display:inline-block;background:{badge_bg};color:#fff;border-radius:999px;padding:.18rem .65rem;font-size:.75rem;font-weight:600}}
.kpis{{display:flex;flex-wrap:wrap;gap:.6rem}}
.kpi{{flex:1;min-width:140px;background:#f7f4ee;border-radius:10px;padding:.55rem .7rem}}
.kpi .l{{font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
.kpi .v{{font-size:1.05rem;font-weight:650;margin-top:.15rem}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th,td{{text-align:left;padding:.4rem .35rem;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}
.btn{{display:inline-block;background:var(--green);color:#f4faf7;text-decoration:none;border-radius:10px;
  padding:.45rem .75rem;font-weight:600;font-size:.85rem;margin:.15rem .25rem 0 0}}
.btn.ghost{{background:transparent;color:var(--green);border:1px solid var(--green)}}
input{{font:inherit;background:#fffdf9;color:var(--ink)}}
.item{{padding:.45rem 0;border-bottom:1px solid var(--line)}}
.item:last-child{{border-bottom:0}}
.foot{{margin-top:.8rem;font-size:.75rem;color:var(--muted)}}
@page{{size:A4 portrait;margin:12mm}}
@media print{{
  html,body{{background:#fff!important}}
  .wrap{{max-width:none;margin:0;padding:0}}
  .card{{box-shadow:none;break-inside:avoid;border-radius:8px}}
  .btn{{display:none!important}}
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="muted">Live quote · powered by WEOS</div>
    <h1>{co_name}</h1>
    <div class="muted">GSTIN {esc(co.get('gstNo') or '—')}
      {(' · ' + esc(co.get('phone'))) if co.get('phone') else ''}
      {(' · ' + esc(co.get('email'))) if co.get('email') else ''}
    </div>
    {f"<div class='muted' style='margin-top:.25rem'>{esc(co.get('address'))}</div>" if co.get('address') else ""}
  </div>
  <div class="card">
    <div class="row" style="display:flex;justify-content:space-between;gap:.6rem;flex-wrap:wrap;align-items:center">
      <div>
        <div class="muted">Quote number</div>
        <strong style="font-size:1.15rem">{esc(record.get('quoteNumber'))}</strong>
        <div class="muted" style="margin-top:.2rem">Versions: {versions_txt}</div>
      </div>
      <span class="badge">{esc(badge)}</span>
    </div>
    <div class="muted" style="margin-top:.45rem">Customer: {esc(cust.get('name'))}
      {(' · ' + esc(cust.get('phone'))) if cust.get('phone') else ''}
    </div>
    {kpis_html}
    {f'<div style="margin-top:.75rem">{links_html}</div>' if links_html else ''}
  </div>
  {access_notice}
  {approval_card}
  {advances_html}
  {products_html}
  {pack_html}
  {decide_html}
  {monitor_html}
  <p class="foot">Last updated {fmt_dt(record.get('updatedAt'))}. This page always loads the live project from the company database — not a PDF snapshot.</p>
</div>
</body>
</html>"""
