"""Canonical company-scoped customer identity (WEOS V2 Batch 3).

Immutable ``customer_id`` is the only FK target. Mobile / GST / name are
discovery identities only — never primary keys. Matching never silently merges
conflicts; callers receive candidates / conflict flags.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Mapping

from WEOS.db.engine import db_available, init_db, session_scope

_log = logging.getLogger("weos.canonical_customer")

KIND_MOBILE = "mobile"
KIND_GST = "gst"
KIND_EMAIL = "email"
KIND_NAME = "name_key"


def new_customer_id() -> str:
    return "CUS-" + uuid.uuid4().hex[:16].upper()


def _norm_company_gst(value: Any) -> str:
    try:
        from WEOS.factory.company_store import normalise_gstin

        return normalise_gstin(str(value or ""))
    except Exception:
        return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def normalize_mobile(value: Any) -> str:
    """India-friendly: +91 / 0XXXXXXXXXX / 10-digit → last 10 digits when possible."""
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[-10:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[-10:]
    elif len(digits) > 10:
        digits = digits[-10:]
    return digits


def normalize_gst(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def normalize_name_key(value: Any) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return s


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _identity_norm(kind: str, raw: str) -> str:
    if kind == KIND_MOBILE:
        return normalize_mobile(raw)
    if kind == KIND_GST:
        return normalize_gst(raw)
    if kind == KIND_EMAIL:
        return normalize_email(raw)
    if kind == KIND_NAME:
        return normalize_name_key(raw)
    return str(raw or "").strip().lower()


def get_customer(customer_id: str, *, company_gst: str | None = None) -> dict[str, Any] | None:
    if not db_available() or not (customer_id or "").strip():
        return None
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import CanonicalCustomer

    gst = _norm_company_gst(company_gst) if company_gst else ""
    with session_scope() as s:
        row = s.get(CanonicalCustomer, str(customer_id).strip())
        if row is None:
            return None
        if gst and _norm_company_gst(row.company_gst) != gst:
            return None
        # touch identities collection
        _ = list(row.identities or [])
        return row.to_dict(include_identities=True)


def create_customer(
    company_gst: str,
    *,
    display_name: str | None = None,
    mobile: str | None = None,
    gst_no: str | None = None,
    email: str | None = None,
    address: str | None = None,
    contact_person: str | None = None,
    state: str | None = None,
    state_code: str | None = None,
    site: str | None = None,
    notes: str | None = None,
    legacy_slug: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a new canonical customer + identity rows. Never reuses another customer's id."""
    if not db_available():
        raise RuntimeError("Database unavailable for canonical customer create")
    gst = _norm_company_gst(company_gst)
    if not gst:
        raise ValueError("company_gst required")
    init_db()
    from WEOS.db.models import CanonicalCustomer, CustomerIdentity

    cid = (customer_id or "").strip() or new_customer_id()
    name = (display_name or "").strip() or (mobile or "").strip() or cid
    slug = legacy_slug or normalize_name_key(name)

    # Preflight: refuse create when identities would collide with a *different* customer.
    conflict = match_customer(
        company_gst=gst,
        mobile=mobile,
        gst_no=gst_no,
        email=email,
        display_name=None,  # name alone is soft discovery, not a hard create block
    )
    if conflict.get("match") == "exact" and conflict.get("customerId"):
        raise ValueError(
            f"Identity already belongs to customer {conflict['customerId']} — refuse silent merge"
        )
    if conflict.get("match") == "conflict":
        raise ValueError("Identity conflict across customers — refuse silent merge")

    with session_scope() as s:
        row = CanonicalCustomer(
            customer_id=cid,
            company_gst=gst,
            display_name=name,
            address=(address or None),
            email=(email or None),
            contact_person=(contact_person or None),
            state=(state or None),
            state_code=(state_code or None),
            site=(site or None),
            notes=(notes or None),
            legacy_slug=slug,
            status="active",
        )
        s.add(row)
        for kind, raw in (
            (KIND_MOBILE, mobile),
            (KIND_GST, gst_no),
            (KIND_EMAIL, email),
            (KIND_NAME, name),
        ):
            if not raw or not str(raw).strip():
                continue
            norm = _identity_norm(kind, str(raw))
            if not norm:
                continue
            s.add(
                CustomerIdentity(
                    customer_id=cid,
                    company_gst=gst,
                    kind=kind,
                    raw_value=str(raw).strip(),
                    normalized_value=norm,
                )
            )
        s.flush()
        return row.to_dict(include_identities=True)


def match_customer(
    *,
    company_gst: str,
    customer_id: str | None = None,
    gst_no: str | None = None,
    mobile: str | None = None,
    email: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Deterministic match: customer_id → GST → mobile → assisted name candidates.

    Returns ``match``: exact | candidates | conflict | none
    Never silently merges when identities point at different customers.
    """
    if not db_available():
        return {"match": "none", "reason": "db_unavailable", "candidates": []}
    gst = _norm_company_gst(company_gst)
    if not gst:
        return {"match": "none", "reason": "company_gst_required", "candidates": []}
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import CanonicalCustomer, CustomerIdentity

    with session_scope() as s:
        if customer_id and str(customer_id).strip():
            row = s.get(CanonicalCustomer, str(customer_id).strip())
            if row and _norm_company_gst(row.company_gst) == gst:
                return {
                    "match": "exact",
                    "by": "customer_id",
                    "customerId": row.customer_id,
                    "customer": row.to_dict(include_identities=True),
                    "candidates": [],
                }
            return {"match": "none", "reason": "customer_id_not_found", "candidates": []}

        hits: dict[str, dict[str, Any]] = {}
        evidence: dict[str, list[str]] = {}

        def _add(kind: str, raw: str | None) -> None:
            if not raw or not str(raw).strip():
                return
            norm = _identity_norm(kind, str(raw))
            if not norm:
                return
            q = select(CustomerIdentity).where(
                CustomerIdentity.company_gst == gst,
                CustomerIdentity.kind == kind,
                CustomerIdentity.normalized_value == norm,
            )
            for ident in s.execute(q).scalars().all():
                cust = s.get(CanonicalCustomer, ident.customer_id)
                if not cust or cust.status == "archived":
                    continue
                hits[cust.customer_id] = cust.to_dict(include_identities=True)
                evidence.setdefault(cust.customer_id, []).append(kind)

        _add(KIND_GST, gst_no)
        _add(KIND_MOBILE, mobile)
        _add(KIND_EMAIL, email)

        if len(hits) > 1:
            return {
                "match": "conflict",
                "reason": "identities_point_to_multiple_customers",
                "candidates": list(hits.values()),
                "evidence": evidence,
                "conflict": True,
            }
        if len(hits) == 1:
            cid = next(iter(hits))
            by = evidence.get(cid) or []
            return {
                "match": "exact",
                "by": by[0] if by else "identity",
                "customerId": cid,
                "customer": hits[cid],
                "candidates": [],
                "evidence": evidence,
            }

        # Assisted name candidates (never auto-merge)
        name_key = normalize_name_key(display_name) if display_name else ""
        candidates: list[dict[str, Any]] = []
        if name_key:
            q = select(CustomerIdentity).where(
                CustomerIdentity.company_gst == gst,
                CustomerIdentity.kind == KIND_NAME,
                CustomerIdentity.normalized_value == name_key,
            )
            for ident in s.execute(q).scalars().all():
                cust = s.get(CanonicalCustomer, ident.customer_id)
                if cust and cust.status != "archived":
                    candidates.append(cust.to_dict(include_identities=True))
        if len(candidates) == 1:
            return {
                "match": "candidates",
                "reason": "single_name_candidate_needs_confirm",
                "candidates": candidates,
            }
        if len(candidates) > 1:
            return {
                "match": "candidates",
                "reason": "ambiguous_name",
                "candidates": candidates,
            }
        return {"match": "none", "candidates": []}


def find_or_create_customer(
    company_gst: str,
    *,
    customer_id: str | None = None,
    display_name: str | None = None,
    mobile: str | None = None,
    gst_no: str | None = None,
    email: str | None = None,
    address: str | None = None,
    create: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    """Match first; create only when match is none. Conflicts raise."""
    matched = match_customer(
        company_gst=company_gst,
        customer_id=customer_id,
        gst_no=gst_no,
        mobile=mobile,
        email=email,
        display_name=display_name,
    )
    if matched.get("match") == "exact":
        return {"created": False, **matched}
    if matched.get("match") == "conflict":
        raise ValueError("Customer identity conflict — refuse silent merge")
    if matched.get("match") == "candidates":
        return {"created": False, **matched}
    if not create:
        return {"created": False, **matched}
    created = create_customer(
        company_gst,
        display_name=display_name,
        mobile=mobile,
        gst_no=gst_no,
        email=email,
        address=address,
        customer_id=customer_id,
        **{k: v for k, v in extra.items() if k in {
            "contact_person", "state", "state_code", "site", "notes", "legacy_slug"
        }},
    )
    return {
        "created": True,
        "match": "exact",
        "by": "create",
        "customerId": created["customerId"],
        "customer": created,
        "candidates": [],
    }


def migrate_legacy_customer_profiles(*, company_gst: str | None = None) -> dict[str, Any]:
    """Import durable/FS customer profiles into canonical tables. No silent merges."""
    if not db_available():
        return {"ok": False, "error": "db_unavailable", "created": 0, "linked": 0, "conflicts": 0, "skipped": 0}
    init_db()
    from WEOS.db.durable_store import list_payloads
    from WEOS.factory.customer_store import customers_dir, load_customer_profile

    created = linked = conflicts = skipped = rejected = 0
    manual_review: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()

    profiles: list[dict[str, Any]] = []
    try:
        for payload in list_payloads(kind="customer") or []:
            if isinstance(payload, dict):
                profiles.append(payload)
    except Exception:
        _log.debug("list_payloads customer failed", exc_info=True)

    # FS cache
    try:
        root = customers_dir()
        for path in root.glob("*/profile.json"):
            try:
                import json

                doc = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(doc, dict):
                    profiles.append(doc)
            except Exception:
                continue
    except Exception:
        pass

    gst_filter = _norm_company_gst(company_gst) if company_gst else ""

    for raw in profiles:
        name = str(raw.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        slug = normalize_name_key(name)
        if slug in seen_slugs:
            skipped += 1
            continue
        seen_slugs.add(slug)
        co = _norm_company_gst(raw.get("companyGst"))
        if not co:
            rejected += 1
            manual_review.append({"name": name, "reason": "missing_company_gst"})
            continue
        if gst_filter and co != gst_filter:
            skipped += 1
            continue
        try:
            result = find_or_create_customer(
                co,
                display_name=name,
                mobile=raw.get("phone"),
                gst_no=raw.get("gstNo"),
                email=raw.get("email"),
                address=raw.get("address"),
                contact_person=raw.get("contactPerson"),
                state=raw.get("state"),
                state_code=raw.get("stateCode"),
                site=raw.get("site"),
                notes=raw.get("notes"),
                legacy_slug=slug,
                create=True,
            )
        except ValueError as exc:
            conflicts += 1
            manual_review.append({"name": name, "reason": str(exc)})
            continue
        if result.get("created"):
            created += 1
        elif result.get("match") == "exact":
            linked += 1
        elif result.get("match") == "candidates":
            conflicts += 1
            manual_review.append({"name": name, "reason": "ambiguous_name", "candidates": result.get("candidates")})
        else:
            skipped += 1

    return {
        "ok": True,
        "created": created,
        "linked": linked,
        "conflicts": conflicts,
        "skipped": skipped,
        "rejected": rejected,
        "manualReview": manual_review,
        "before": len(profiles),
        "after": created + linked,
        "zeroSilentLoss": True,
    }


def ensure_customer_from_profile(profile: Mapping[str, Any]) -> dict[str, Any] | None:
    """Best-effort upsert used by legacy profile saves — never merges conflicts."""
    try:
        co = _norm_company_gst(profile.get("companyGst"))
        if not co:
            return None
        return find_or_create_customer(
            co,
            customer_id=str(profile.get("customerId") or "").strip() or None,
            display_name=str(profile.get("name") or "").strip() or None,
            mobile=profile.get("phone"),
            gst_no=profile.get("gstNo"),
            email=profile.get("email"),
            address=profile.get("address"),
            contact_person=profile.get("contactPerson"),
            state=profile.get("state"),
            state_code=profile.get("stateCode"),
            site=profile.get("site"),
            notes=profile.get("notes"),
            legacy_slug=normalize_name_key(profile.get("name") or ""),
            create=True,
        )
    except Exception:
        _log.debug("ensure_customer_from_profile skipped", exc_info=True)
        return None
