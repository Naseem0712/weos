"""Persistent quote store (Part 1 / 2 / 7 / 8) — the cloud source of truth.

Every quote/customer/version/BOM/event/suggestion lives in the database
(PostgreSQL in production, sqlite dev fallback). The browser never owns this
data — it only caches transient UI state.

High-level API used by the FastAPI layer + Agent Orchestrator:

* ``login_by_mobile`` / ``upsert_customer_by_mobile`` — mobile-number login (no OTP)
* ``create_quote`` / ``get_quote`` / ``list_quotes`` / ``update_quote`` /
  ``delete_quote`` / ``duplicate_quote`` / ``list_versions`` / ``finalize_quote``
* ``add_event`` — quote activity audit trail
* ``save_suggestions`` — persist live Agent suggestions
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from WEOS.db.engine import db_available, get_session, init_db, session_scope

_MOBILE_RE = re.compile(r"^\+?\d{7,15}$")


def normalise_mobile(mobile: str) -> str:
    """Keep a leading + and digits only; validate a plausible length."""
    raw = (mobile or "").strip()
    cleaned = re.sub(r"[\s\-()]", "", raw)
    if not _MOBILE_RE.match(cleaned):
        raise ValueError(
            "Enter a valid mobile number (7-15 digits, optional leading +)."
        )
    return cleaned


def _ensure_ready() -> None:
    if not db_available():
        raise RuntimeError(
            "Database unavailable — server persistence is offline. "
            "Set DATABASE_URL (PostgreSQL) on Railway. Quotes are never stored in the browser."
        )
    init_db()


# ── quote number generation ──────────────────────────────────────────────────

def _next_quote_number(session: Any) -> str:
    from WEOS.db.models import Quote

    year = datetime.now(timezone.utc).year
    prefix = f"WQ-{year}-"
    # Count existing quotes this year → next sequence. Good enough for this scale.
    from sqlalchemy import func, select

    like = f"{prefix}%"
    count = session.execute(
        select(func.count()).select_from(Quote).where(Quote.quote_number.like(like))
    ).scalar_one()
    return f"{prefix}{int(count) + 1:05d}"


# ── customers / mobile login ──────────────────────────────────────────────────

def upsert_customer_by_mobile(mobile: str, **fields: Any) -> dict[str, Any]:
    """Find-or-create a customer keyed by mobile number. No OTP/password."""
    _ensure_ready()
    from sqlalchemy import select

    from WEOS.db.models import Customer

    mob = normalise_mobile(mobile)
    with session_scope() as s:
        cust = s.execute(select(Customer).where(Customer.mobile == mob)).scalar_one_or_none()
        if cust is None:
            cust = Customer(mobile=mob)
            s.add(cust)
        for key in ("name", "email", "gst_no", "address", "state", "state_code", "contact_person"):
            val = fields.get(key)
            if val is not None and str(val).strip():
                setattr(cust, key, str(val).strip())
        s.flush()
        return cust.to_dict()


def login_by_mobile(mobile: str, name: str | None = None) -> dict[str, Any]:
    """Mobile-number login: validate format → find/create account → return it + quotes."""
    cust = upsert_customer_by_mobile(mobile, name=name)
    quotes = list_quotes(customer_id=cust["id"])
    return {"ok": True, "customer": cust, "quotes": quotes, "quoteCount": len(quotes)}


def login_flexible(
    mobile: str | None = None,
    name: str | None = None,
    quote_number: str | None = None,
) -> dict[str, Any]:
    """OTP-less login by mobile, quote number, OR name (any one; name optional).

    Resolution priority: quote number → mobile → name.
    * quote number (or quote id) → its customer (and all that customer's quotes)
    * mobile → find-or-create customer keyed by mobile (existing behaviour)
    * name → look up an existing customer by name (never creates a new account)
    Returns the matched customer + their quotes; the DB is the source of truth.
    """
    _ensure_ready()
    from sqlalchemy import func, select

    from WEOS.db.models import Customer, Quote

    qn = (quote_number or "").strip()
    mob = (mobile or "").strip()
    nm = (name or "").strip()

    # 1) Quote number / quote id — the most specific handle.
    if qn:
        cust_dict: dict[str, Any] | None = None
        cust_id: int | None = None
        fallback_quote: dict[str, Any] | None = None
        with session_scope() as s:
            q = s.execute(
                select(Quote).where((Quote.quote_number == qn) | (Quote.quote_id == qn))
            ).scalar_one_or_none()
            if q is None:
                raise ValueError(f"No quote found for '{qn}'. Check the quote number.")
            if q.customer_id:
                cust = s.get(Customer, q.customer_id)
                if cust is not None:
                    cust_dict = cust.to_dict()
                    cust_id = cust.id
            if cust_id is None:
                fallback_quote = q.to_dict()
        if cust_id is not None:
            quotes = list_quotes(customer_id=cust_id)
            return {"ok": True, "customer": cust_dict, "quotes": quotes, "quoteCount": len(quotes), "matchedBy": "quote"}
        return {"ok": True, "customer": None, "quotes": [fallback_quote], "quoteCount": 1, "matchedBy": "quote"}

    # 2) Mobile number — find-or-create (existing OTP-less flow).
    if mob:
        res = login_by_mobile(mob, name=nm or None)
        res["matchedBy"] = "mobile"
        return res

    # 3) Name only — look up an existing account (exact first, then partial). No create.
    if nm:
        cust_dict = None
        cust_id = None
        with session_scope() as s:
            cust = s.execute(
                select(Customer).where(func.lower(Customer.name) == nm.lower())
            ).scalar_one_or_none()
            if cust is None:
                cust = s.execute(
                    select(Customer).where(Customer.name.ilike(f"%{nm}%"))
                ).scalars().first()
            if cust is not None:
                cust_dict = cust.to_dict()
                cust_id = cust.id
        if cust_id is None:
            raise ValueError(
                f"No customer found matching '{nm}'. Try your mobile or quote number."
            )
        quotes = list_quotes(customer_id=cust_id)
        return {"ok": True, "customer": cust_dict, "quotes": quotes, "quoteCount": len(quotes), "matchedBy": "name"}

    raise ValueError("Enter your mobile number, quote number, or name to continue.")


def get_customer(customer_id: int) -> dict[str, Any] | None:
    _ensure_ready()
    from WEOS.db.models import Customer

    with session_scope() as s:
        cust = s.get(Customer, customer_id)
        return cust.to_dict() if cust else None


# ── quote helpers ─────────────────────────────────────────────────────────────

def _apply_payload(quote: Any, payload: dict[str, Any]) -> None:
    """Map an incoming quote payload onto the ORM object (partial-update safe)."""
    field_map = {
        "product": "product",
        "series": "series",
        "colour": "colour",
        "glass": "glass",
        "hardware": "hardware",
        "materials": "materials",
        "bom": "bom",
        "rates": "rates",
        "lines": "lines",
        "status": "status",
        "createdBy": "created_by",
    }
    for src, dst in field_map.items():
        if src in payload and payload[src] is not None:
            setattr(quote, dst, payload[src])
    num_map = {
        "width": "width_mm",
        "height": "height_mm",
        "quantity": "quantity",
        "trackCount": "track_count",
        "shutterCount": "shutter_count",
        "sellingPrice": "selling_price",
        "gstPercent": "gst_percent",
        "gstAmount": "gst_amount",
        "grandTotal": "grand_total",
    }
    for src, dst in num_map.items():
        if src in payload and payload[src] is not None:
            setattr(quote, dst, payload[src])


def _snapshot(quote: Any) -> dict[str, Any]:
    return quote.to_dict(include_children=False)


def _record_version(session: Any, quote: Any, created_by: str | None) -> None:
    from WEOS.db.models import QuoteVersion

    session.add(
        QuoteVersion(
            quote_id=quote.id,
            version=quote.version,
            snapshot=_snapshot(quote),
            created_by=created_by,
        )
    )


def _add_event_obj(session: Any, quote_pk: int, event_type: str, message: str, data: dict | None, created_by: str | None) -> None:
    from WEOS.db.models import QuoteAgentEvent

    session.add(
        QuoteAgentEvent(
            quote_id=quote_pk,
            event_type=event_type,
            message=message,
            data=data or {},
            created_by=created_by,
        )
    )


# ── quote CRUD ────────────────────────────────────────────────────────────────

def create_quote(payload: dict[str, Any], *, created_by: str | None = None) -> dict[str, Any]:
    """Create a persistent quote (+ initial version, calculation, BOM, audit event).

    If ``quoteNumber`` already exists for the same customer, bump that quote as a
    new version instead of creating an orphan row.
    """
    _ensure_ready()
    from WEOS.db.models import Quote, QuoteBom, QuoteCalculation, QuoteItem

    with session_scope() as s:
        # Resolve / create the customer from mobile when provided.
        customer_id = payload.get("customerId")
        mobile = payload.get("mobile") or payload.get("customerMobile")
        if not customer_id and mobile:
            from sqlalchemy import select

            from WEOS.db.models import Customer

            mob = normalise_mobile(str(mobile))
            cust = s.execute(select(Customer).where(Customer.mobile == mob)).scalar_one_or_none()
            if cust is None:
                cust = Customer(mobile=mob, name=payload.get("customerName"))
                s.add(cust)
                s.flush()
            customer_id = cust.id

        wanted_number = (payload.get("quoteNumber") or "").strip()
        if wanted_number and customer_id:
            from sqlalchemy import select

            existing = s.execute(
                select(Quote)
                .where(Quote.quote_number == wanted_number, Quote.customer_id == int(customer_id))
                .order_by(Quote.updated_at.desc())
            ).scalars().first()
            if existing is not None:
                # Version bump on the existing quote (same customer + number).
                before = _snapshot(existing)
                _apply_payload(existing, payload)
                existing.quote_number = wanted_number
                existing.version = int(existing.version or 1) + 1
                if payload.get("lines") is not None:
                    for it in list(existing.items):
                        s.delete(it)
                    for i, line in enumerate(payload.get("lines") or []):
                        s.add(
                            QuoteItem(
                                quote_id=existing.id,
                                line_no=i,
                                product=line.get("product"),
                                width_mm=_num(line.get("width")),
                                height_mm=_num(line.get("height")),
                                quantity=int(line.get("qty") or line.get("quantity") or 1),
                                payload=line,
                                line_total=_num((line.get("price") or {}).get("total")),
                            )
                        )
                if payload.get("calculation") is not None or payload.get("grandTotal") is not None:
                    s.add(
                        QuoteCalculation(
                            quote_id=existing.id,
                            result=payload.get("calculation") or {},
                            grand_total=existing.grand_total,
                        )
                    )
                if existing.bom is not None:
                    s.add(QuoteBom(quote_id=existing.id, bom=existing.bom))
                _record_version(s, existing, created_by)
                _add_event_obj(
                    s,
                    existing.id,
                    "quote_number_version",
                    f"Quote {existing.quote_number} new version (v{existing.version})",
                    {"version": existing.version, "beforeVersion": before.get("version")},
                    created_by,
                )
                s.flush()
                data = existing.to_dict(include_children=True)
                data["quoteNumberVersioned"] = True
                return data

        quote = Quote(
            quote_id=payload.get("quoteId") or f"Q-{uuid.uuid4().hex[:12]}",
            customer_id=customer_id,
            project_id=payload.get("projectId"),
            version=1,
            status=payload.get("status") or "draft",
            created_by=created_by or payload.get("createdBy"),
        )
        _apply_payload(quote, payload)
        quote.quote_number = wanted_number or _next_quote_number(s)
        s.add(quote)
        s.flush()

        # Multi-line items mirror
        for i, line in enumerate(payload.get("lines") or []):
            s.add(
                QuoteItem(
                    quote_id=quote.id,
                    line_no=i,
                    product=line.get("product"),
                    width_mm=_num(line.get("width")),
                    height_mm=_num(line.get("height")),
                    quantity=int(line.get("qty") or line.get("quantity") or 1),
                    payload=line,
                    line_total=_num((line.get("price") or {}).get("total")),
                )
            )
        if payload.get("calculation") is not None or payload.get("grandTotal") is not None:
            s.add(
                QuoteCalculation(
                    quote_id=quote.id,
                    result=payload.get("calculation") or {},
                    grand_total=quote.grand_total,
                )
            )
        if quote.bom is not None:
            s.add(QuoteBom(quote_id=quote.id, bom=quote.bom))
        _record_version(s, quote, created_by)
        _add_event_obj(s, quote.id, "created", f"Quote {quote.quote_number} created", {"version": 1}, created_by)
        s.flush()
        return quote.to_dict(include_children=True)


def _get_quote_obj(session: Any, quote_id: str) -> Any:
    from sqlalchemy import select

    from WEOS.db.models import Quote

    q = session.execute(select(Quote).where(Quote.quote_id == quote_id)).scalar_one_or_none()
    if q is None:
        raise FileNotFoundError(f"Quote not found: {quote_id}")
    return q


def get_quote(quote_id: str) -> dict[str, Any]:
    _ensure_ready()
    with session_scope() as s:
        return _get_quote_obj(s, quote_id).to_dict(include_children=True)


def get_quote_by_ref(ref: str) -> dict[str, Any] | None:
    """Resolve a quote for a public share link. Tries, in order: quote_id,
    quote_number, then project_id (most recent). Returns None when not found or
    when the DB is unavailable (so callers can fall back to file projects)."""
    ref = (ref or "").strip()
    if not ref:
        return None
    try:
        _ensure_ready()
    except Exception:
        return None
    from sqlalchemy import select

    from WEOS.db.models import Quote

    try:
        with session_scope() as s:
            q = s.execute(
                select(Quote).where((Quote.quote_id == ref) | (Quote.quote_number == ref))
            ).scalars().first()
            if q is None:
                q = s.execute(
                    select(Quote).where(Quote.project_id == ref).order_by(Quote.id.desc())
                ).scalars().first()
            return q.to_dict(include_children=True) if q is not None else None
    except Exception:
        return None


def list_quotes(
    *,
    customer_id: int | None = None,
    mobile: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    _ensure_ready()
    from sqlalchemy import select

    from WEOS.db.models import Customer, Quote

    with session_scope() as s:
        stmt = select(Quote)
        if mobile:
            mob = normalise_mobile(mobile)
            cust = s.execute(select(Customer).where(Customer.mobile == mob)).scalar_one_or_none()
            if cust is None:
                return []
            customer_id = cust.id
        if customer_id:
            stmt = stmt.where(Quote.customer_id == customer_id)
        if status:
            stmt = stmt.where(Quote.status == status)
        stmt = stmt.order_by(Quote.updated_at.desc()).limit(limit)
        return [q.to_dict() for q in s.execute(stmt).scalars().all()]


def update_quote(quote_id: str, payload: dict[str, Any], *, created_by: str | None = None) -> dict[str, Any]:
    """Update a quote, bump version, snapshot the new version + audit each change."""
    _ensure_ready()
    from WEOS.db.models import QuoteBom, QuoteCalculation, QuoteItem

    with session_scope() as s:
        quote = _get_quote_obj(s, quote_id)
        before = _snapshot(quote)
        _apply_payload(quote, payload)
        quote.version = int(quote.version or 1) + 1

        # Refresh line items when lines provided.
        if payload.get("lines") is not None:
            for it in list(quote.items):
                s.delete(it)
            for i, line in enumerate(payload.get("lines") or []):
                s.add(
                    QuoteItem(
                        quote_id=quote.id,
                        line_no=i,
                        product=line.get("product"),
                        width_mm=_num(line.get("width")),
                        height_mm=_num(line.get("height")),
                        quantity=int(line.get("qty") or line.get("quantity") or 1),
                        payload=line,
                        line_total=_num((line.get("price") or {}).get("total")),
                    )
                )
        if payload.get("calculation") is not None:
            s.add(QuoteCalculation(quote_id=quote.id, result=payload["calculation"], grand_total=quote.grand_total))
        if payload.get("bom") is not None:
            s.add(QuoteBom(quote_id=quote.id, bom=payload["bom"]))
        _record_version(s, quote, created_by)

        # Field-level audit trail (Part 8): dimensions / glass / hardware / price.
        for label, keys in (
            ("dimension_changed", ("width", "height")),
            ("glass_changed", ("glass",)),
            ("hardware_changed", ("hardware",)),
            ("price_changed", ("grandTotal", "sellingPrice")),
        ):
            changed = any(k in payload for k in keys)
            if changed:
                _add_event_obj(
                    s,
                    quote.id,
                    label,
                    f"{label.replace('_', ' ').title()} on {quote.quote_number}",
                    {"before": {k: before.get(k) for k in keys}, "keys": list(keys)},
                    created_by,
                )
        _add_event_obj(s, quote.id, "saved", f"Quote {quote.quote_number} saved (v{quote.version})", {"version": quote.version}, created_by)
        s.flush()
        return quote.to_dict(include_children=True)


def delete_quote(quote_id: str) -> dict[str, Any]:
    _ensure_ready()
    with session_scope() as s:
        quote = _get_quote_obj(s, quote_id)
        s.delete(quote)
        return {"ok": True, "deleted": quote_id}


def duplicate_quote(quote_id: str, *, created_by: str | None = None) -> dict[str, Any]:
    _ensure_ready()
    src = get_quote(quote_id)
    payload = {k: v for k, v in src.items() if k not in ("id", "quoteId", "quoteNumber", "version", "createdAt", "updatedAt", "finalizedAt", "items", "events", "suggestions", "documents", "customer")}
    payload["status"] = "draft"
    return create_quote(payload, created_by=created_by)


def list_versions(quote_id: str) -> list[dict[str, Any]]:
    _ensure_ready()
    from sqlalchemy import select

    from WEOS.db.models import QuoteVersion

    with session_scope() as s:
        quote = _get_quote_obj(s, quote_id)
        rows = s.execute(
            select(QuoteVersion).where(QuoteVersion.quote_id == quote.id).order_by(QuoteVersion.version.desc())
        ).scalars().all()
        return [r.to_dict() for r in rows]


def finalize_quote(quote_id: str, *, created_by: str | None = None) -> dict[str, Any]:
    _ensure_ready()
    with session_scope() as s:
        quote = _get_quote_obj(s, quote_id)
        quote.status = "finalized"
        quote.finalized_at = datetime.now(timezone.utc)
        quote.version = int(quote.version or 1) + 1
        _record_version(s, quote, created_by)
        _add_event_obj(s, quote.id, "finalized", f"Quote {quote.quote_number} finalized", {"version": quote.version}, created_by)
        s.flush()
        return quote.to_dict(include_children=True)


# ── audit + suggestions ─────────────────────────────────────────────────────

def add_event(quote_id: str, event_type: str, message: str = "", data: dict | None = None, *, created_by: str | None = None) -> dict[str, Any]:
    _ensure_ready()
    with session_scope() as s:
        quote = _get_quote_obj(s, quote_id)
        _add_event_obj(s, quote.id, event_type, message or event_type, data, created_by)
        return {"ok": True}


def list_events(quote_id: str) -> list[dict[str, Any]]:
    _ensure_ready()
    from sqlalchemy import select

    from WEOS.db.models import QuoteAgentEvent

    with session_scope() as s:
        quote = _get_quote_obj(s, quote_id)
        rows = s.execute(
            select(QuoteAgentEvent).where(QuoteAgentEvent.quote_id == quote.id).order_by(QuoteAgentEvent.id.asc())
        ).scalars().all()
        return [r.to_dict() for r in rows]


def save_suggestions(quote_id: str, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist the current live suggestions for a quote (replaces open ones)."""
    _ensure_ready()
    from sqlalchemy import select

    from WEOS.db.models import QuoteSuggestion

    with session_scope() as s:
        quote = _get_quote_obj(s, quote_id)
        existing = s.execute(
            select(QuoteSuggestion).where(QuoteSuggestion.quote_id == quote.id, QuoteSuggestion.status == "open")
        ).scalars().all()
        for e in existing:
            e.status = "superseded"
        out = []
        for sug in suggestions or []:
            row = QuoteSuggestion(
                quote_id=quote.id,
                suggestion_key=sug.get("key") or sug.get("id"),
                type=sug.get("type") or "info",
                message=sug.get("message"),
                reason=sug.get("reason"),
                source=sug.get("source"),
                confidence=sug.get("confidence"),
                action=sug.get("action"),
                why=sug.get("why") or {},
                data=sug.get("data") or {},
                status="open",
            )
            s.add(row)
            s.flush()
            out.append(row.to_dict())
        _add_event_obj(s, quote.id, "suggestions_shown", f"{len(out)} suggestion(s) shown", {"count": len(out)}, None)
        return out


def set_suggestion_status(quote_id: str, suggestion_id: int, status: str, *, created_by: str | None = None) -> dict[str, Any]:
    """Accept / ignore a suggestion (records an audit event either way)."""
    _ensure_ready()
    from WEOS.db.models import QuoteSuggestion

    with session_scope() as s:
        quote = _get_quote_obj(s, quote_id)
        row = s.get(QuoteSuggestion, suggestion_id)
        if row is None or row.quote_id != quote.id:
            raise FileNotFoundError(f"Suggestion not found: {suggestion_id}")
        row.status = status
        event = "suggestion_accepted" if status == "accepted" else "suggestion_rejected"
        _add_event_obj(s, quote.id, event, f"Suggestion {row.suggestion_key} {status}", {"suggestionId": suggestion_id}, created_by)
        return {"ok": True, "suggestion": row.to_dict()}


def store_health() -> dict[str, Any]:
    """Quote-store readiness for the admin health endpoint (Part 10)."""
    try:
        _ensure_ready()
        counts = _counts()
        return {"status": "READY", **counts}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def _counts() -> dict[str, Any]:
    from sqlalchemy import func, select

    from WEOS.db.models import Customer, Quote

    with session_scope() as s:
        quotes = s.execute(select(func.count()).select_from(Quote)).scalar_one()
        customers = s.execute(select(func.count()).select_from(Customer)).scalar_one()
        return {"quotes": int(quotes), "customers": int(customers)}


def _num(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
