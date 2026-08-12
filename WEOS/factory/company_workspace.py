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
    load_company,
    load_company_by_gst,
    normalise_gstin,
    save_company_by_gst,
    set_active_gst,
)

_log = logging.getLogger("weos.company_workspace")

# Documented ledger / account total rule (also returned in API payloads):
TOTALS_RULE = (
    "Account billed = sum of latest quote grand totals per quotation number "
    "(each version is retained as history; only the live/latest version per "
    "quote number counts toward project and customer totals). "
    "Balance = billed − advances."
)


def open_workspace(
    gst_no: str,
    *,
    profile: Mapping[str, Any] | None = None,
    create: bool = True,
) -> dict[str, Any]:
    """Login / open seller company workspace by GSTIN.

    First-time: creates the company (optionally with profile fields).
    Returns company + customers + projects + aggregates.
    """
    gst = normalise_gstin(gst_no)
    if not gst:
        raise ValueError("Enter a valid GSTIN to open the company workspace.")

    existing = load_company_by_gst(gst)
    created = False
    if existing is None:
        if not create:
            raise FileNotFoundError(f"No company workspace for GSTIN {gst}")
        payload = dict(profile or {})
        payload["gstNo"] = gst
        if not (payload.get("companyName") or "").strip():
            payload.setdefault("companyName", f"Company {gst[-4:]}")
        company = save_company_by_gst(gst, payload)
        created = True
        # Migrate unscoped legacy data onto this company when it is the first GST workspace.
        _migrate_legacy_into(gst)
    else:
        if profile:
            # Allow completing / updating profile on open without wiping.
            patch = {k: profile[k] for k in _FIELDS if k in profile and profile[k] is not None}
            if patch:
                existing = save_company_by_gst(gst, {**existing, **patch})
        company = existing

    set_active_gst(gst)
    summary = build_workspace_summary(gst)
    return {
        "ok": True,
        "created": created,
        "gstNo": gst,
        "company": company,
        "totalsRule": TOTALS_RULE,
        **summary,
    }


def build_workspace_summary(gst_no: str | None = None) -> dict[str, Any]:
    """Customers / projects / accounts for a company GST workspace."""
    gst = normalise_gstin(gst_no) if gst_no else normalise_gstin((load_company() or {}).get("gstNo") or "")
    if not gst:
        # Fall back to active / legacy company if any.
        active = load_company()
        gst = normalise_gstin(active.get("gstNo") or "")

    from WEOS.factory.customer_store import customer_quotes, list_customer_profiles
    from WEOS.factory.ledger_store import build_ledger
    from WEOS.factory.project_store import list_projects

    customers_raw = list_customer_profiles(company_gst=gst or None)
    projects_raw = list_projects(include_archived=False, company_gst=gst or None)

    customer_rows: list[dict[str, Any]] = []
    total_billed = 0.0
    total_advances = 0.0
    total_balance = 0.0
    total_quote_versions = 0

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
            led = {"totals": {"billed": 0, "advances": 0, "balance": 0}, "projects": quotes}
        t = led.get("totals") or {}
        billed = float(t.get("billed") or 0)
        adv = float(t.get("advances") or 0)
        bal = float(t.get("balance") or 0)
        total_billed += billed
        total_advances += adv
        total_balance += bal
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
                "totalBilled": round(billed, 2),
                "totalAdvances": round(adv, 2),
                "balance": round(bal, 2),
                "ledgerUrl": f"/api/customers/{name}/ledger",
                "ledgerPdfUrl": f"/api/customers/{name}/ledger.pdf",
                "updatedAt": c.get("updatedAt"),
            }
        )

    project_rows = []
    year_value = 0.0
    orders_confirmed = 0
    projects_running = 0
    calendar_year = datetime.now(timezone.utc).year

    from WEOS.factory.ledger_store import CONFIRMED_STATUSES

    for p in projects_raw:
        st = str(p.get("status") or "draft").strip().lower()
        # list_projects(include_archived=False) already excludes archived.
        projects_running += 1
        if st in CONFIRMED_STATUSES:
            orders_confirmed += 1
        # Year value: live rows are already latest-per-quotation-number.
        ysrc = str(p.get("updatedAt") or p.get("createdAt") or "")
        try:
            y = int(ysrc[:4]) if len(ysrc) >= 4 else 0
        except ValueError:
            y = 0
        if y == calendar_year:
            try:
                year_value += float(p.get("grandTotal") or 0)
            except (TypeError, ValueError):
                pass
        project_rows.append(
            {
                "projectId": p.get("projectId"),
                "name": p.get("name"),
                "customer": p.get("customer"),
                "quotationId": p.get("quotationId"),
                "version": p.get("version"),
                "status": p.get("status"),
                "grandTotal": p.get("grandTotal"),
                "lineCount": p.get("lineCount"),
                "updatedAt": p.get("updatedAt"),
                "companyGst": p.get("companyGst") or gst,
            }
        )

    accounts = [
        {
            "customer": r["name"],
            "billed": r["totalBilled"],
            "advances": r["totalAdvances"],
            "balance": r["balance"],
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
        "yearValueGenerated": round(year_value, 2),
        "balanceOutstanding": round(total_balance, 2),
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
            "Year value = sum of live (latest-per-quotation-number) grand totals whose "
            "updatedAt falls in the current calendar year."
        ),
        "balanceDefinition": "Balance outstanding = total billed − total advances (receivables).",
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
            "billed": round(total_billed, 2),
            "advances": round(total_advances, 2),
            "balance": round(total_balance, 2),
            "quoteVersions": total_quote_versions,
            "yearValue": round(year_value, 2),
            "ordersConfirmed": orders_confirmed,
            "projectsRunning": projects_running,
            "currency": "INR",
            "basis": "latest_per_quotation_number",
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
