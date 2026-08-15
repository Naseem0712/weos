"""GST-based company workspace — seller login + multi-tenant hub.

Seller companies are keyed by normalised GSTIN (unique). Opening a workspace
loads the company profile plus customers, projects, and ledger aggregates
scoped to that GST. Legacy single-tenant rows (no ``companyGst``) are attached
to the first/open company so existing data is not orphaned.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from WEOS.factory.company_store import (
    _FIELDS,
    clear_active_gst,
    company_has_login_pin,
    consume_pin_reset_token,
    iter_company_docs,
    load_company,
    load_company_by_gst,
    mint_pin_reset_token,
    mint_workspace_session,
    normalise_gstin,
    public_company_profile,
    revoke_workspace_session,
    save_company_by_gst,
    set_active_gst,
    validate_login_pin,
    verify_login_pin,
    verify_workspace_session,
)

_log = logging.getLogger("weos.company_workspace")

# Documented ledger / account total rule (also returned in API payloads):
TOTALS_RULE = (
    "Grand total = all live quotes on a customer (with GST). "
    "Year turnover = every Approved project this calendar year. "
    "Balance = grand total − advances. Any advance reduces that customer’s full balance."
)


def find_companies_for_login(query: str) -> list[dict[str, Any]]:
    """Match GSTIN, company name, or registered mobile (last 10 digits)."""
    raw = str(query or "").strip()
    if not raw:
        return []
    gst_q = normalise_gstin(raw)
    digits = re.sub(r"\D", "", raw)
    name_q = re.sub(r"[^a-z0-9]+", "", raw.lower())
    hits: list[dict[str, Any]] = []
    for doc in iter_company_docs():
        g = normalise_gstin(doc.get("gstNo"))
        if not g:
            continue
        phone = re.sub(r"\D", "", str(doc.get("phone") or ""))
        name = re.sub(r"[^a-z0-9]+", "", str(doc.get("companyName") or "").lower())
        ok = False
        if gst_q and g == gst_q:
            ok = True
        if digits and len(digits) >= 7 and phone:
            if digits[-10:] == phone[-10:] or digits in phone or phone.endswith(digits):
                ok = True
        if name_q and len(name_q) >= 3 and name and (name_q == name or name_q in name or name in name_q):
            ok = True
        if ok:
            hits.append(doc)
    # Prefer exact GST / exact 10-digit mobile.
    def _rank(d: Mapping[str, Any]) -> tuple[int, str]:
        g = normalise_gstin(d.get("gstNo"))
        phone = re.sub(r"\D", "", str(d.get("phone") or ""))
        if gst_q and g == gst_q:
            return (0, g)
        if digits and len(digits) >= 10 and phone[-10:] == digits[-10:]:
            return (1, g)
        return (2, g)

    hits.sort(key=_rank)
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for d in hits:
        g = normalise_gstin(d.get("gstNo"))
        if g in seen:
            continue
        seen.add(g)
        uniq.append(d)
    return uniq


def _login_match_row(doc: Mapping[str, Any]) -> dict[str, Any]:
    phone = re.sub(r"\D", "", str(doc.get("phone") or ""))
    masked = (("******" + phone[-4:]) if len(phone) >= 4 else "") 
    return {
        "gstNo": doc.get("gstNo"),
        "companyName": doc.get("companyName") or "",
        "phoneMasked": masked,
        "hasLoginPin": bool(str(doc.get("loginPinHash") or "").strip()),
        "hasEmail": bool(str(doc.get("email") or "").strip()),
    }


def open_workspace(
    gst_no: str | None = None,
    *,
    profile: Mapping[str, Any] | None = None,
    create: bool = True,
    pin: str | None = None,
    session_token: str | None = None,
    login: str | None = None,
) -> dict[str, Any]:
    """Login / open seller company workspace by GSTIN, name, or mobile + PIN.

    First-time: creates the company (PIN + profile). Returning companies with a
    login PIN need that PIN or a valid session token. Same mobile/name/GST is
    one company workspace — data is fetched after login.
    """
    prof = dict(profile or {})
    gst = normalise_gstin(gst_no or prof.get("gstNo") or "")
    login_q = str(login or "").strip()
    matches: list[dict[str, Any]] = []
    if not gst and login_q:
        matches = find_companies_for_login(login_q)
        if len(matches) > 1:
            return {
                "ok": False,
                "needPick": True,
                "matches": [_login_match_row(m) for m in matches],
                "message": "More than one company matched. Pick GSTIN, then enter the PIN.",
            }
        if len(matches) == 1:
            gst = normalise_gstin(matches[0].get("gstNo"))
        elif not create:
            raise FileNotFoundError("No company workspace matches that GST / name / mobile.")
        else:
            gst = normalise_gstin(login_q)
            if len(gst) != 15:
                raise FileNotFoundError(
                    "No company matched. For a new company enter the 15-character GSTIN, name, mobile, PIN and email."
                )

    if not gst:
        raise ValueError("Enter company GSTIN, registered name, or mobile to log in.")

    existing = load_company_by_gst(gst)
    created = False
    enrolled = False
    if existing is None:
        if not create:
            raise FileNotFoundError(f"No company workspace for GSTIN {gst}")
        payload = dict(prof)
        payload["gstNo"] = gst
        if not (payload.get("companyName") or "").strip():
            payload.setdefault("companyName", f"Company {gst[-4:]}")
        if pin:
            payload["loginPin"] = validate_login_pin(pin)
        company = save_company_by_gst(gst, payload)
        created = True
        _migrate_legacy_into(gst)
    else:
        has_pin = company_has_login_pin(gst, existing)
        session_ok = verify_workspace_session(gst, session_token)
        if has_pin:
            if not session_ok and not verify_login_pin(gst, pin):
                raise PermissionError("Enter the 4-digit company PIN to open this workspace.")
        elif pin:
            save_company_by_gst(gst, {**existing, "loginPin": validate_login_pin(pin)})
            enrolled = True
            existing = load_company_by_gst(gst) or existing
        if pin or session_ok or enrolled:
            patch = {k: prof[k] for k in _FIELDS if k in prof and prof[k] is not None}
            if patch:
                existing = save_company_by_gst(gst, {**existing, **patch})
        company = existing

    set_active_gst(gst)
    token = mint_workspace_session(gst)
    summary = build_workspace_summary(gst)
    return {
        "ok": True,
        "created": created,
        "enrolledPin": enrolled,
        "gstNo": gst,
        "sessionToken": token,
        "company": public_company_profile(company),
        "totalsRule": TOTALS_RULE,
        **summary,
    }


def logout_workspace(*, gst_no: str | None = None, session_token: str | None = None) -> dict[str, Any]:
    gst = normalise_gstin(gst_no or "")
    if gst:
        revoke_workspace_session(gst, session_token)
        clear_active_gst(gst)
    else:
        clear_active_gst()
    return {"ok": True, "loggedOut": True}


def request_pin_reset(query: str, *, base_url: str = "") -> dict[str, Any]:
    """Always returns a generic ack. Emails a link when a registered mail exists."""
    from WEOS.factory.company_mail import public_base_url, send_pin_reset_email

    matches = find_companies_for_login(query)
    ack = {
        "ok": True,
        "sent": False,
        "message": "If this company has a registered email, a PIN reset link was sent.",
    }
    if len(matches) != 1:
        return ack
    doc = matches[0]
    email = str(doc.get("email") or "").strip()
    gst = normalise_gstin(doc.get("gstNo"))
    if not email or "@" not in email or not gst:
        return ack
    token = mint_pin_reset_token(gst)
    base = (base_url or public_base_url()).rstrip("/")
    reset_url = f"{base}/pin-reset?token={token}" if base else f"/pin-reset?token={token}"
    sent = send_pin_reset_email(
        to_email=email,
        company_name=str(doc.get("companyName") or gst),
        reset_url=reset_url,
    )
    ack["sent"] = bool(sent)
    return ack


def confirm_pin_reset(token: str, new_pin: str) -> dict[str, Any]:
    row = consume_pin_reset_token(token, new_pin)
    gst = row.get("gstNo")
    session = mint_workspace_session(str(gst)) if gst else None
    if gst:
        set_active_gst(str(gst))
    return {"ok": True, "gstNo": gst, "sessionToken": session, "companyName": row.get("companyName")}


def build_workspace_summary(gst_no: str | None = None) -> dict[str, Any]:
    """Customers / projects / accounts for a company GST workspace."""
    gst = normalise_gstin(gst_no) if gst_no else normalise_gstin((load_company() or {}).get("gstNo") or "")
    if not gst:
        # Fall back to active / legacy company if any.
        active = load_company()
        gst = normalise_gstin(active.get("gstNo") or "")

    from WEOS.factory.customer_store import customer_quotes, list_customer_profiles
    from WEOS.factory.ledger_store import build_ledger, quote_money_parts
    from WEOS.factory.project_store import list_projects

    customers_raw = list_customer_profiles(company_gst=gst or None)
    projects_raw = list_projects(include_archived=False, company_gst=gst or None)

    customer_rows: list[dict[str, Any]] = []
    total_taxable = 0.0
    total_gst = 0.0
    total_grand = 0.0
    total_advances = 0.0
    total_balance = 0.0
    total_balance_gst = 0.0
    total_quote_versions = 0
    year_taxable = 0.0
    year_gst = 0.0
    year_grand = 0.0
    calendar_year = datetime.now(timezone.utc).year
    seen_pids: set[str] = set()

    for c in customers_raw:
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        quotes_info = customer_quotes(name, company_gst=gst or None)
        quotes = list(quotes_info.get("quotes") or [])
        version_count = sum(int(q.get("versionCount") or 1) for q in quotes)
        total_quote_versions += version_count
        led: dict[str, Any] = {}
        try:
            led = build_ledger(name, company_gst=gst or None)
        except Exception:
            _log.exception("workspace ledger failed for %s", name)
            led = {
                "totals": {
                    "billed": 0,
                    "totalTaxable": 0,
                    "totalGst": 0,
                    "totalGrand": 0,
                    "advances": 0,
                    "balance": 0,
                    "balanceWithGst": 0,
                    "yearTaxable": 0,
                    "yearGst": 0,
                    "yearGrand": 0,
                },
                "projects": quotes,
            }
        t = led.get("totals") or {}
        pids = [str(p.get("projectId") or "") for p in (led.get("projects") or quotes) if p.get("projectId")]
        already = bool(pids) and all(pid in seen_pids for pid in pids)
        for pid in pids:
            seen_pids.add(pid)
        taxable = float(t.get("totalTaxable") if t.get("totalTaxable") is not None else t.get("billed") or 0)
        gst_amt = float(t.get("totalGst") or 0)
        grand = float(t.get("totalGrand") or 0)
        if not grand and taxable:
            parts = quote_money_parts(taxable)
            gst_amt = parts["totalGst"]
            grand = parts["totalGrand"]
        adv = float(t.get("advances") or t.get("totalAdvances") or 0)
        bal = float(t.get("balance") or 0)
        bal_gst = float(t.get("balanceWithGst") if t.get("balanceWithGst") is not None else (grand - adv))
        if not already:
            total_taxable += taxable
            total_gst += gst_amt
            total_grand += grand
            total_advances += adv
            total_balance += bal
            total_balance_gst += bal_gst
            year_taxable += float(t.get("yearTaxable") or 0)
            year_gst += float(t.get("yearGst") or 0)
            year_grand += float(t.get("yearGrand") or 0)
        customer_rows.append(
            {
                "name": name,
                "slug": c.get("slug"),
                "gstNo": c.get("gstNo"),
                "phone": c.get("phone"),
                "email": c.get("email"),
                "companyGst": c.get("companyGst") or gst,
                "projectCount": len(quotes),
                "quoteVersionCount": version_count,
                "totalBilled": round(taxable, 2),
                "totalTaxable": round(taxable, 2),
                "totalGst": round(gst_amt, 2),
                "totalGrand": round(grand, 2),
                "totalAdvances": round(adv, 2),
                "balance": round(bal, 2),
                "balanceWithGst": round(bal_gst, 2),
                "ledgerUrl": f"/api/customers/{name}/ledger",
                "ledgerPdfUrl": f"/api/customers/{name}/ledger.pdf",
                "updatedAt": c.get("updatedAt"),
            }
        )

    project_rows = []
    orders_confirmed = 0
    projects_running = 0

    from WEOS.factory.ledger_store import CONFIRMED_STATUSES

    for p in projects_raw:
        st = str(p.get("status") or "draft").strip().lower()
        # list_projects(include_archived=False) already excludes archived.
        projects_running += 1
        if st in CONFIRMED_STATUSES:
            orders_confirmed += 1
        parts = quote_money_parts(p.get("grandTotal"))
        project_rows.append(
            {
                "projectId": p.get("projectId"),
                "name": p.get("name"),
                "customer": p.get("customer"),
                "quotationId": p.get("quotationId"),
                "version": p.get("version"),
                "status": p.get("status"),
                "grandTotal": p.get("grandTotal"),
                "totalTaxable": parts["totalTaxable"],
                "totalGst": parts["totalGst"],
                "totalGrand": parts["totalGrand"],
                "lineCount": p.get("lineCount"),
                "updatedAt": p.get("updatedAt"),
                "createdAt": p.get("createdAt"),
                "tenure": p.get("tenure") or "",
                "companyGst": p.get("companyGst") or gst,
            }
        )

    accounts = [
        {
            "customer": r["name"],
            "billed": r["totalTaxable"],
            "totalTaxable": r["totalTaxable"],
            "totalGst": r["totalGst"],
            "totalGrand": r["totalGrand"],
            "advances": r["totalAdvances"],
            "balance": r["balance"],
            "balanceWithGst": r["balanceWithGst"],
            "projectCount": r["projectCount"],
            "quoteVersionCount": r["quoteVersionCount"],
            "ledgerPdfUrl": r["ledgerPdfUrl"],
        }
        for r in customer_rows
    ]

    dashboard = {
        "projectsRunning": projects_running,
        "ordersConfirmed": orders_confirmed,
        "totalAdvances": round(total_advances, 2),
        "yearValueGenerated": round(year_taxable, 2),
        "yearTaxable": round(year_taxable, 2),
        "yearGst": round(year_gst, 2),
        "yearGrand": round(year_grand, 2),
        "totalTaxable": round(total_taxable, 2),
        "totalGst": round(total_gst, 2),
        "totalGrand": round(total_grand, 2),
        "balanceOutstanding": round(total_balance, 2),
        "balanceWithGst": round(total_balance_gst, 2),
        "yearBasis": "calendar",
        "year": calendar_year,
        "ordersConfirmedDefinition": (
            "Orders confirmed = projects/quotes with status in "
            f"{sorted(CONFIRMED_STATUSES)} (default status is draft/active — mark confirmed explicitly)."
        ),
        "projectsRunningDefinition": (
            "Projects running = non-archived projects in the company workspace."
        ),
        "yearValueDefinition": (
            "Year taxable / year turnover = sum of live (latest-per-quotation-number) commercial "
            "totals for Approved (or confirmed/won) quotes whose updatedAt falls in the current "
            "calendar year. Drafts and rejected quotes are excluded. Year with GST adds GST@18%."
        ),
        "balanceDefinition": (
            "Balance outstanding = total taxable − total advances. "
            "Balance with GST = totalGrand − advances."
        ),
    }

    return {
        "customers": customer_rows,
        "customerCount": len(customer_rows),
        "projects": project_rows,
        "projectCount": len(project_rows),
        "accounts": accounts,
        "accountCount": len(accounts),
        "dashboard": dashboard,
        "totals": {
            "billed": round(total_taxable, 2),
            "totalTaxable": round(total_taxable, 2),
            "totalGst": round(total_gst, 2),
            "totalGrand": round(total_grand, 2),
            "advances": round(total_advances, 2),
            "totalAdvances": round(total_advances, 2),
            "balance": round(total_balance, 2),
            "balanceWithGst": round(total_balance_gst, 2),
            "quoteVersions": total_quote_versions,
            "yearValue": round(year_taxable, 2),
            "yearTaxable": round(year_taxable, 2),
            "yearGst": round(year_gst, 2),
            "yearGrand": round(year_grand, 2),
            "ordersConfirmed": orders_confirmed,
            "projectsRunning": projects_running,
            "currency": "INR",
            "basis": "latest_per_quotation_number",
            "turnoverStatuses": "approved+confirmed/won",
            "note": TOTALS_RULE,
        },
    }


def _migrate_legacy_into(gst: str) -> None:
    """Attach unscoped customers/projects to this GST when none are scoped yet."""
    from WEOS.factory.customer_store import list_customer_profiles, save_customer_profile
    from WEOS.factory.project_store import list_projects, load_project, save_project

    gst_n = normalise_gstin(gst)
    if not gst_n:
        return

    # Only migrate when this would be the sole company home for orphan rows.
    try:
        from WEOS.db.durable_store import list_keys

        gst_keys = list_keys(kind="company", prefix="company:gst:")
        # If other GST companies already exist, leave orphans alone (operator choice).
        if len(gst_keys) > 1:
            return
    except Exception:
        pass

    for c in list_customer_profiles(company_gst=None, include_unscoped=True):
        if c.get("companyGst"):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        try:
            save_customer_profile(name, {"companyGst": gst_n})
        except Exception:
            _log.exception("migrate customer %s failed", name)

    for row in list_projects(include_archived=True, company_gst=None, include_unscoped=True):
        if row.get("companyGst"):
            continue
        pid = row.get("projectId")
        if not pid:
            continue
        try:
            doc = load_project(str(pid))
            if doc.get("companyGst"):
                continue
            doc["companyGst"] = gst_n
            save_project(doc, bump_version=False, action="migrate_company_gst")
        except Exception:
            _log.exception("migrate project %s failed", pid)


_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z0-9]{10}[A-Z0-9]{3}$")


def validate_gstin_format(gst: str) -> bool:
    """Soft GSTIN shape check (15 chars). Does not verify checksum."""
    g = normalise_gstin(gst)
    return bool(g) and len(g) == 15 and bool(_GSTIN_RE.match(g))
