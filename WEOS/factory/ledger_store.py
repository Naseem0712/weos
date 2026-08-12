"""Customer account ledger — projects totals, advances, balance.

Balance = sum(project quote grand totals) − sum(advances).
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
    if amount <= 0:
        raise ValueError("Advance amount must be greater than zero")
    mode = str(payload.get("paymentMode") or payload.get("mode") or "cash").strip().lower()
    if mode not in PAYMENT_MODES:
        mode = "other"
    paid_at = _parse_dt(payload.get("paidAt") or payload.get("date")) or datetime.now(timezone.utc)
    with session_scope() as s:
        row = CustomerAdvance(
            customer_key=customer_key(name),
            customer_name=name,
            amount=round(amount, 2),
            payment_mode=mode,
            reference=(str(payload.get("reference") or "").strip() or None),
            note=(str(payload.get("note") or "").strip() or None),
            project_id=(str(payload.get("projectId") or "").strip() or None),
            quote_id=(str(payload.get("quoteId") or "").strip() or None),
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


def build_ledger(customer: str) -> dict[str, Any]:
    """Full account view: profile, projects, advances, totals, balance."""
    from WEOS.factory.customer_store import customer_quotes, load_customer_profile

    cust = (customer or "").strip()
    if not cust:
        raise ValueError("Customer name required")

    account = customer_quotes(cust)
    profile = account.get("profile") or load_customer_profile(cust)
    quotes = list(account.get("quotes") or [])

    projects = []
    total_billed = 0.0
    for q in quotes:
        amt = _money(q.get("grandTotal"))
        total_billed += amt
        projects.append(
            {
                "projectId": q.get("projectId"),
                "name": q.get("name"),
                "quotationId": q.get("quotationId"),
                "status": q.get("status"),
                "version": q.get("version"),
                "updatedAt": q.get("updatedAt"),
                "createdAt": q.get("createdAt"),
                "grandTotal": amt if q.get("grandTotal") is not None else None,
                "lineCount": q.get("lineCount"),
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

    total_advances = round(sum(_money(a.get("amount")) for a in advances), 2)
    total_billed = round(total_billed, 2)
    balance = round(total_billed - total_advances, 2)
    as_of = datetime.now(timezone.utc).isoformat()

    return {
        "customer": cust,
        "customerKey": customer_key(cust),
        "profile": profile,
        "projects": projects,
        "projectCount": len(projects),
        "advances": advances,
        "advanceCount": len(advances),
        "totals": {
            "billed": total_billed,
            "advances": total_advances,
            "balance": balance,
            "currency": "INR",
            "basis": "quote_grand_total",
            "note": "Billed = sum of project quote grand totals (same as quote PDFs). Balance = billed − advances.",
        },
        "asOf": as_of,
        "paymentModes": list(PAYMENT_MODES),
    }
