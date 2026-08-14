"""Customer account ledger — projects totals, advances, balance.

**Totals rule (documented):**
Account billed = sum of *latest* quote grand totals **per quotation number**.
Each project version is retained under ``projects/versions/``; only the live
project row for a given quotation number counts toward billed / project value.
When a quote number is reused, versioning folds into the same project so the
account total stays live (no orphan double-count).

Balance = billed − advances.
Grand totals follow the existing quote calculation (same figure shown on
Projects / Customer account); treat as tax-inclusive when the quote engine
included GST in ``price.total``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from WEOS.db.engine import db_available, init_db, session_scope

_log = logging.getLogger("weos.ledger")

PAYMENT_MODES = ("cash", "cheque", "upi", "neft", "rtgs", "card", "other")

# Project / quote statuses that count as a confirmed order on the company hub.
CONFIRMED_STATUSES = frozenset(
    {"confirmed", "accepted", "approved", "finalized", "ordered", "order", "won"}
)
RUNNING_STATUSES = frozenset(
    {"active", "draft", "confirmed", "accepted", "finalized", "ordered", "order", "won"}
)

TOTALS_BASIS = "latest_per_quotation_number"
DEFAULT_GST_PERCENT = 18.0
TOTALS_NOTE = (
    "Taxable / billed = sum of latest quote commercial totals per quotation number "
    "for Approved (or confirmed/won) quotes only — drafts, testing, rejected and cancelled "
    "quotes are excluded. Versions are retained as history. "
    "With GST = taxable + GST@18% (same split as customer quote PDF). "
    "Billed / balance use taxable so advances match quote line totals; "
    "balanceWithGst = totalGrand − advances (refunds are negative advances). "
    "Year totals use the current calendar year of the live approved quote."
)
REFUND_ENTRY_TYPES = frozenset({"refund", "reversal", "return"})


def status_counts_toward_turnover(status: Any) -> bool:
    """Year turnover / billed: approved + confirmed/won only — never drafts."""
    st = str(status or "draft").strip().lower() or "draft"
    if st in {"draft", "unused", "active", "archived", "rejected", "cancelled", "canceled"}:
        return False
    return st in CONFIRMED_STATUSES


def quote_money_parts(
    commercial_total: Any,
    *,
    gst_percent: float | None = None,
    includes_gst: bool = False,
) -> dict[str, float]:
    """Split a stored quote commercial total into taxable / GST / grand (PDF parity).

    Customer quote PDFs treat selling amounts as ex-GST by default and add GST@18%.
    When ``includes_gst`` is True, GST is backed out of the commercial figure.
    """
    try:
        basic = float(commercial_total or 0)
    except (TypeError, ValueError):
        basic = 0.0
    pct = float(gst_percent if gst_percent is not None else DEFAULT_GST_PERCENT)
    if pct < 0:
        pct = 0.0
    if includes_gst and pct > 0:
        grand = round(basic, 2)
        gst_amt = round(grand * pct / (100.0 + pct), 2)
        taxable = round(grand - gst_amt, 2)
    else:
        taxable = round(basic, 2)
        gst_amt = round(taxable * pct / 100.0, 2) if pct else 0.0
        grand = round(taxable + gst_amt, 2)
    return {
        "totalTaxable": taxable,
        "totalGst": gst_amt,
        "totalGrand": grand,
        "gstPercent": pct,
    }


def _ensure_advance_schema() -> None:
    """Add quote_version on existing DBs (create_all does not ALTER)."""
    try:
        from sqlalchemy import text

        from WEOS.db.engine import get_engine

        eng = get_engine()
        if eng is None:
            return
        with eng.begin() as conn:
            conn.execute(
                text("ALTER TABLE customer_advances ADD COLUMN IF NOT EXISTS quote_version INTEGER")
            )
            conn.execute(
                text("ALTER TABLE customer_advances ADD COLUMN IF NOT EXISTS entry_type VARCHAR(20)")
            )
    except Exception:
        # SQLite < 3.35 / some drivers lack IF NOT EXISTS on ADD COLUMN — try bare add.
        try:
            from sqlalchemy import text

            from WEOS.db.engine import get_engine

            eng = get_engine()
            if eng is None:
                return
            with eng.begin() as conn:
                conn.execute(text("ALTER TABLE customer_advances ADD COLUMN quote_version INTEGER"))
        except Exception:
            pass
    try:
        from sqlalchemy import text

        from WEOS.db.engine import get_engine

        eng = get_engine()
        if eng is None:
            return
        with eng.begin() as conn:
            conn.execute(text("ALTER TABLE customer_advances ADD COLUMN entry_type VARCHAR(20)"))
    except Exception:
        pass


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "customer"


def customer_key(customer: str) -> str:
    return _slug(customer)


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        # Allow date-only YYYY-MM-DD
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            text = text + "T00:00:00+00:00"
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _ensure_ready() -> None:
    if not db_available():
        raise RuntimeError(
            "Database unavailable — ledger advances require DATABASE_URL (PostgreSQL)."
        )
    init_db()
    _ensure_advance_schema()


def list_advances(customer: str) -> list[dict[str, Any]]:
    _ensure_ready()
    from sqlalchemy import select

    from WEOS.db.models import CustomerAdvance

    key = customer_key(customer)
    with session_scope() as s:
        rows = (
            s.execute(
                select(CustomerAdvance)
                .where(CustomerAdvance.customer_key == key)
                .order_by(CustomerAdvance.paid_at.desc(), CustomerAdvance.id.desc())
            )
            .scalars()
            .all()
        )
        return [r.to_dict() for r in rows]


def add_advance(customer: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    _ensure_ready()
    from WEOS.db.models import CustomerAdvance

    name = (payload.get("customerName") or customer or "").strip()
    if not name:
        raise ValueError("Customer name required")
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Advance amount must be a number") from exc
    entry_type = str(payload.get("entryType") or payload.get("kind") or payload.get("type") or "").strip().lower()
    if entry_type in REFUND_ENTRY_TYPES or amount < 0:
        if amount == 0:
            raise ValueError("Refund amount must not be zero")
        amount = -abs(amount)
        entry_type = "refund"
    else:
        if amount <= 0:
            raise ValueError("Advance amount must be greater than zero")
        entry_type = "advance"
    mode = str(payload.get("paymentMode") or payload.get("mode") or "cash").strip().lower()
    if mode not in PAYMENT_MODES:
        mode = "other"
    paid_at = _parse_dt(payload.get("paidAt") or payload.get("date")) or datetime.now(timezone.utc)
    qver = payload.get("quoteVersion")
    try:
        qver_i = int(qver) if qver is not None and str(qver).strip() != "" else None
    except (TypeError, ValueError):
        qver_i = None
    note = str(payload.get("note") or "").strip() or None
    if entry_type == "refund" and not note:
        note = "Refund / reversal (advance returned)"
    with session_scope() as s:
        row = CustomerAdvance(
            customer_key=customer_key(name),
            customer_name=name,
            amount=round(amount, 2),
            payment_mode=mode,
            reference=(str(payload.get("reference") or "").strip() or None),
            note=note,
            project_id=(str(payload.get("projectId") or "").strip() or None),
            quote_id=(str(payload.get("quoteId") or "").strip() or None),
            quote_version=qver_i,
            entry_type=entry_type,
            paid_at=paid_at,
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def delete_advance(customer: str, advance_id: int) -> dict[str, Any]:
    _ensure_ready()
    from sqlalchemy import select

    from WEOS.db.models import CustomerAdvance

    key = customer_key(customer)
    with session_scope() as s:
        row = s.execute(
            select(CustomerAdvance).where(
                CustomerAdvance.id == int(advance_id),
                CustomerAdvance.customer_key == key,
            )
        ).scalar_one_or_none()
        if row is None:
            raise FileNotFoundError(f"Advance {advance_id} not found for {customer}")
        data = row.to_dict()
        s.delete(row)
        return {"deleted": True, "advance": data}


def _money(n: Any) -> float:
    try:
        if n is None or n == "":
            return 0.0
        return float(n)
    except (TypeError, ValueError):
        return 0.0


def _norm_qid(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def _latest_per_quotation(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one live row per quotation number (most recently updated).

    Projects without a quotation id are each counted separately (keyed by projectId).
    """
    best: dict[str, dict[str, Any]] = {}
    for q in quotes:
        qid = _norm_qid(q.get("quotationId"))
        key = qid or f"PROJECT:{q.get('projectId')}"
        prev = best.get(key)
        if prev is None:
            best[key] = q
            continue
        if str(q.get("updatedAt") or "") >= str(prev.get("updatedAt") or ""):
            best[key] = q
    return list(best.values())


def build_ledger(customer: str, *, company_gst: str | None = None) -> dict[str, Any]:
    """Full account view: profile, projects, advances, totals, balance."""
    from WEOS.factory.customer_store import customer_quotes, load_customer_profile

    cust = (customer or "").strip()
    if not cust:
        raise ValueError("Customer name required")

    account = customer_quotes(cust, company_gst=company_gst)
    profile = account.get("profile") or load_customer_profile(cust)
    quotes = list(account.get("quotes") or [])
    live = _latest_per_quotation(quotes)
    billed_live = [q for q in live if status_counts_toward_turnover(q.get("status"))]

    projects = []
    total_taxable = 0.0
    total_gst = 0.0
    total_grand = 0.0
    year_taxable = 0.0
    year_gst = 0.0
    year_grand = 0.0
    calendar_year = datetime.now(timezone.utc).year
    by_pid: dict[str, dict[str, Any]] = {}
    for q in billed_live:
        amt = _money(q.get("grandTotal"))
        parts = quote_money_parts(amt)
        total_taxable += parts["totalTaxable"]
        total_gst += parts["totalGst"]
        total_grand += parts["totalGrand"]
        ysrc = str(q.get("updatedAt") or q.get("createdAt") or "")
        try:
            y = int(ysrc[:4]) if len(ysrc) >= 4 else 0
        except ValueError:
            y = 0
        if y == calendar_year:
            year_taxable += parts["totalTaxable"]
            year_gst += parts["totalGst"]
            year_grand += parts["totalGrand"]
    for q in live:
        amt = _money(q.get("grandTotal"))
        parts = quote_money_parts(amt)
        counts = status_counts_toward_turnover(q.get("status"))
        row = {
            "projectId": q.get("projectId"),
            "name": q.get("name"),
            "quotationId": q.get("quotationId"),
            "status": q.get("status"),
            "version": q.get("version"),
            "updatedAt": q.get("updatedAt"),
            "createdAt": q.get("createdAt"),
            "grandTotal": amt if q.get("grandTotal") is not None else None,
            "totalTaxable": parts["totalTaxable"],
            "totalGst": parts["totalGst"],
            "totalGrand": parts["totalGrand"],
            "lineCount": q.get("lineCount"),
            "versionCount": q.get("versionCount"),
            "versions": q.get("versions") or [],
            "countsTowardTurnover": counts,
        }
        projects.append(row)
        if row.get("projectId"):
            by_pid[str(row["projectId"])] = row

    # Full version history for UI / PDF (every saved version + live row).
    all_versions: list[dict[str, Any]] = []
    for q in quotes:
        live_amt = _money(q.get("grandTotal"))
        all_versions.append(
            {
                "projectId": q.get("projectId"),
                "quotationId": q.get("quotationId"),
                "name": q.get("name"),
                "version": q.get("version"),
                "status": q.get("status"),
                "grandTotal": live_amt if q.get("grandTotal") is not None else None,
                "updatedAt": q.get("updatedAt"),
                "live": True,
            }
        )
        for v in q.get("versions") or []:
            all_versions.append(
                {
                    "projectId": q.get("projectId"),
                    "quotationId": q.get("quotationId"),
                    "name": q.get("name"),
                    "version": v.get("version"),
                    "status": "history",
                    "grandTotal": v.get("grandTotal"),
                    "updatedAt": v.get("updatedAt") or v.get("createdAt"),
                    "live": False,
                }
            )

    advances: list[dict[str, Any]] = []
    try:
        advances = list_advances(cust)
    except RuntimeError:
        advances = []
    except Exception:
        _log.exception("list advances failed for %s", cust)
        advances = []

    # Enrich advances with linked quote number / version when project is known.
    for a in advances:
        pid = str(a.get("projectId") or "").strip()
        linked = by_pid.get(pid) if pid else None
        if linked:
            if not a.get("quoteId"):
                a["quoteId"] = linked.get("quotationId")
            if a.get("quoteVersion") is None:
                a["quoteVersion"] = linked.get("version")
            a["linkedQuote"] = {
                "projectId": linked.get("projectId"),
                "quotationId": linked.get("quotationId"),
                "version": linked.get("version"),
                "name": linked.get("name"),
                "grandTotal": linked.get("grandTotal"),
                "status": linked.get("status"),
            }
            a["quoteStatus"] = linked.get("status")
            st = str(linked.get("status") or "").strip().lower()
            if st in {"rejected", "cancelled", "canceled"}:
                a["quoteRejected"] = True
                note = str(a.get("note") or "").strip()
                tag = "Quote rejected — advance retained on account"
                if tag.lower() not in note.lower():
                    a["note"] = (note + (" · " if note else "") + tag)
        else:
            a["linkedQuote"] = None
        et = str(a.get("entryType") or "").strip().lower()
        if not et:
            a["entryType"] = "refund" if _money(a.get("amount")) < 0 else "advance"

    total_advances = round(sum(_money(a.get("amount")) for a in advances), 2)
    total_taxable = round(total_taxable, 2)
    total_gst = round(total_gst, 2)
    total_grand = round(total_grand, 2)
    year_taxable = round(year_taxable, 2)
    year_gst = round(year_gst, 2)
    year_grand = round(year_grand, 2)
    # Billed / balance stay on taxable (commercial) so advances match quote line totals.
    balance = round(total_taxable - total_advances, 2)
    balance_with_gst = round(total_grand - total_advances, 2)
    as_of = datetime.now(timezone.utc).isoformat()

    totals = {
        "billed": total_taxable,
        "value": total_taxable,
        "totalTaxable": total_taxable,
        "totalGst": total_gst,
        "totalGrand": total_grand,
        "totalAdvances": total_advances,
        "advances": total_advances,
        "balance": balance,
        "balanceWithGst": balance_with_gst,
        "yearTaxable": year_taxable,
        "yearGst": year_gst,
        "yearGrand": year_grand,
        "year": calendar_year,
        "gstPercent": DEFAULT_GST_PERCENT,
        "currency": "INR",
        "basis": TOTALS_BASIS,
        "turnoverStatuses": sorted(CONFIRMED_STATUSES),
        "note": TOTALS_NOTE,
    }
    return {
        "customer": cust,
        "customerKey": customer_key(cust),
        "profile": profile,
        "projects": projects,
        "projectCount": len(projects),
        "allQuoteRows": len(quotes),
        "allVersions": all_versions,
        "advances": advances,
        "advanceCount": len(advances),
        "totals": totals,
        # Top-level aliases for aggregate clients / workspace open payload.
        "totalTaxable": total_taxable,
        "totalGst": total_gst,
        "totalGrand": total_grand,
        "totalAdvances": total_advances,
        "balance": balance,
        "asOf": as_of,
        "paymentModes": list(PAYMENT_MODES),
    }
