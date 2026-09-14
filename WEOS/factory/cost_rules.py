"""Cost Rule master — wastage / coating / fabrication / installation / transport / overhead.

Deterministic precedence: Design > Project > Item > Series > Family > Company.
Conflict if unresolvable at same precedence with equal priority.
Never stores quote selling rates.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.db.models import (
    COST_RULE_DOMAINS,
    COST_RULE_PRECEDENCE,
    COST_RULE_SCOPES,
    COATING_MODES,
    CostRule,
)
from WEOS.factory.canonical_customer import _norm_company_gst

_log = logging.getLogger("weos.cost_rules")

BATCH_ID = "ENG-COST"
SEED_TAG = "safe_sample"


def new_rule_id() -> str:
    return "CR-" + uuid.uuid4().hex[:16].upper()


def _require_db() -> None:
    if not db_available():
        raise RuntimeError("Database unavailable for cost rules")
    init_db()


def cost_rule_revision_token(company_gst: str | None = None) -> str:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        q = s.query(CostRule)
        if gst:
            q = q.filter((CostRule.company_gst == gst) | (CostRule.company_gst.is_(None)))
        total = 0
        for r in q.all():
            total += int(r.revision or 0)
        return f"cr-{total}"


def create_cost_rule(
    *,
    domain: str,
    name: str,
    company_gst: str | None = None,
    scope: str = "COMPANY",
    scope_ref: str | None = None,
    params: dict[str, Any] | None = None,
    priority: int = 100,
    source: str = "manual",
    manual_review: bool = False,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_db()
    dom = str(domain or "").strip().upper()
    if dom not in COST_RULE_DOMAINS:
        raise ValueError(f"invalid cost rule domain: {domain}")
    sc = str(scope or "COMPANY").strip().upper()
    if sc not in COST_RULE_SCOPES:
        raise ValueError(f"invalid cost rule scope: {scope}")
    p = dict(params or {})
    if dom == "COATING":
        mode = str(p.get("mode") or "SEPARATE").upper()
        if mode not in COATING_MODES:
            raise ValueError(f"invalid coating mode: {mode}")
        p["mode"] = mode
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        row = CostRule(
            rule_id=new_rule_id(),
            company_gst=gst,
            domain=dom,
            scope=sc,
            scope_ref=scope_ref,
            name=name,
            params=p,
            priority=int(priority),
            source=source,
            manual_review=bool(manual_review),
            meta={**(meta or {}), "batch": BATCH_ID},
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def list_cost_rules(
    *,
    company_gst: str | None = None,
    domain: str | None = None,
    scope: str | None = None,
) -> list[dict[str, Any]]:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        q = s.query(CostRule).filter(CostRule.status == "active")
        if gst:
            q = q.filter((CostRule.company_gst == gst) | (CostRule.company_gst.is_(None)))
        if domain:
            q = q.filter(CostRule.domain == str(domain).upper())
        if scope:
            q = q.filter(CostRule.scope == str(scope).upper())
        return [r.to_dict() for r in q.order_by(CostRule.domain, CostRule.priority).all()]


def update_cost_rule(rule_id: str, *, company_gst: str | None = None, **fields: Any) -> dict[str, Any]:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        row = s.get(CostRule, rule_id)
        if not row:
            raise ValueError("cost rule not found")
        if gst and row.company_gst and row.company_gst != gst:
            raise PermissionError("cost rule not found")
        mapping = {
            "name": "name",
            "params": "params",
            "priority": "priority",
            "status": "status",
            "scope": "scope",
            "scopeRef": "scope_ref",
            "scope_ref": "scope_ref",
            "manualReview": "manual_review",
            "manual_review": "manual_review",
            "meta": "meta",
        }
        for k, v in fields.items():
            col = mapping.get(k)
            if not col or v is None:
                continue
            if col == "scope":
                v = str(v).upper()
                if v not in COST_RULE_SCOPES:
                    raise ValueError(f"invalid scope: {v}")
            if col == "params" and isinstance(v, dict):
                p = dict(v)
                if row.domain == "COATING" and "mode" in p:
                    mode = str(p["mode"]).upper()
                    if mode not in COATING_MODES:
                        raise ValueError(f"invalid coating mode: {mode}")
                    p["mode"] = mode
                v = p
            setattr(row, col, v)
        row.revision = int(row.revision or 1) + 1
        s.flush()
        return row.to_dict()


def resolve_rule(
    domain: str,
    *,
    company_gst: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one active rule for domain using precedence. Conflict → error payload."""
    _require_db()
    ctx = dict(context or {})
    dom = str(domain).upper()
    gst = _norm_company_gst(company_gst)
    candidates = list_cost_rules(company_gst=gst, domain=dom)
    if not candidates:
        return {"ok": True, "rule": None, "domain": dom, "resolvedScope": None}

    scope_refs = {
        "DESIGN": ctx.get("designDocumentId") or ctx.get("designId"),
        "PROJECT": ctx.get("projectId"),
        "ITEM": ctx.get("elementId") or ctx.get("itemId") or ctx.get("lineId"),
        "SERIES": ctx.get("seriesId") or ctx.get("seriesCode"),
        "FAMILY": (ctx.get("family") or ctx.get("productFamily") or "WINDOW"),
        "COMPANY": gst,
    }

    by_scope: dict[str, list[dict[str, Any]]] = {s: [] for s in COST_RULE_PRECEDENCE}
    for r in candidates:
        sc = r.get("scope") or "COMPANY"
        ref = r.get("scopeRef")
        expected = scope_refs.get(sc)
        if sc == "COMPANY":
            by_scope[sc].append(r)
            continue
        if expected is None:
            continue
        if ref is None or str(ref) == str(expected):
            by_scope[sc].append(r)

    for sc in COST_RULE_PRECEDENCE:
        hits = by_scope.get(sc) or []
        if not hits:
            continue
        hits_sorted = sorted(hits, key=lambda x: (int(x.get("priority") or 100), x.get("ruleId") or ""))
        top_pri = int(hits_sorted[0].get("priority") or 100)
        tops = [h for h in hits_sorted if int(h.get("priority") or 100) == top_pri]
        if len(tops) > 1:
            # Same precedence + priority with different params → conflict
            # Exception: WASTAGE rules with disjoint appliesTo can coexist
            import json

            if dom == "WASTAGE":
                applies_sets = []
                overlap = False
                for h in tops:
                    applies = {
                        str(x).upper()
                        for x in ((h.get("params") or {}).get("appliesTo") or ["MATERIAL"])
                    }
                    for prev in applies_sets:
                        if applies & prev:
                            # Same category targeted with potentially different pct
                            pcts = {
                                float((x.get("params") or {}).get("pct") or 0)
                                for x in tops
                                if applies
                                & {
                                    str(a).upper()
                                    for a in ((x.get("params") or {}).get("appliesTo") or ["MATERIAL"])
                                }
                            }
                            if len(pcts) > 1:
                                overlap = True
                                break
                    applies_sets.append(applies)
                    if overlap:
                        break
                if not overlap:
                    return {
                        "ok": True,
                        "rule": tops[0],
                        "rules": tops,
                        "domain": dom,
                        "resolvedScope": sc,
                    }
            param_keys = {
                json.dumps(h.get("params") or {}, sort_keys=True, default=str) for h in tops
            }
            if len(param_keys) > 1:
                return {
                    "ok": False,
                    "conflict": True,
                    "domain": dom,
                    "resolvedScope": sc,
                    "rules": tops,
                    "message": f"Unresolvable {dom} rule conflict at scope {sc}",
                }
        return {"ok": True, "rule": tops[0], "domain": dom, "resolvedScope": sc}

    return {"ok": True, "rule": None, "domain": dom, "resolvedScope": None}


def resolve_all_domains(*, company_gst: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "domains": {}, "conflicts": [], "issues": []}
    for dom in COST_RULE_DOMAINS:
        res = resolve_rule(dom, company_gst=company_gst, context=context)
        out["domains"][dom] = res
        if res.get("conflict"):
            out["ok"] = False
            out["conflicts"].append(res)
            out["issues"].append(
                {
                    "code": "COST_RULE_CONFLICT",
                    "severity": "error",
                    "domain": dom,
                    "message": res.get("message") or f"Conflict in {dom}",
                }
            )
    return out


def seed_safe_sample_cost_rules(*, company_gst: str | None = None) -> dict[str, Any]:
    """Seed ONLY safe test/sample rules — not invented production rates."""
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    existing = list_cost_rules(company_gst=gst)
    tagged = [r for r in existing if (r.get("meta") or {}).get("seedTag") == SEED_TAG]
    if tagged:
        return {"created": [], "skipped": len(tagged), "rules": tagged}

    samples = [
        (
            "WASTAGE",
            "Sample wastage 5% profiles / 3% glass",
            {
                "pct": 5.0,
                "appliesTo": ["MATERIAL", "PROFILE"],
                "glassPct": 3.0,
                "glassAppliesTo": ["GLASS"],
            },
        ),
        (
            "COATING",
            "Sample coating separate per kg",
            {"mode": "SEPARATE", "basis": "PER_KG", "rate": 12.0},
        ),
        (
            "FABRICATION",
            "Sample fabrication per opening",
            {"basis": "PER_OPENING", "rate": 150.0},
        ),
        (
            "INSTALLATION",
            "Sample installation per sqm",
            {"basis": "PER_SQM", "rate": 80.0},
        ),
        (
            "TRANSPORT",
            "Sample transport flat",
            {"basis": "FLAT", "rate": 200.0},
        ),
        (
            "OVERHEAD",
            "Sample overhead 8%",
            {"pct": 8.0, "base": "SUBTOTAL_BEFORE_OVERHEAD"},
        ),
    ]
    created: list[str] = []
    for domain, name, params in samples:
        row = create_cost_rule(
            domain=domain,
            name=name,
            company_gst=gst,
            scope="COMPANY",
            params=params,
            priority=100,
            source="seed",
            manual_review=False,
            meta={"seedTag": SEED_TAG, "safeSample": True, "notProductionRate": True},
        )
        created.append(row["ruleId"])
    return {"created": created, "skipped": 0, "count": len(created)}


def import_legacy_cost_semantics(payload: Mapping[str, Any], *, company_gst: str) -> dict[str, Any]:
    """Import only known semantics; unknown → manualReview; zeroSilentLoss."""
    known = {
        "wastage_pct": ("WASTAGE", lambda v: {"pct": float(v)}),
        "coating_mode": ("COATING", lambda v: {"mode": str(v).upper()}),
        "coating_rate_per_kg": ("COATING", lambda v: {"mode": "SEPARATE", "basis": "PER_KG", "rate": float(v)}),
        "fabrication_per_opening": ("FABRICATION", lambda v: {"basis": "PER_OPENING", "rate": float(v)}),
        "installation_per_sqm": ("INSTALLATION", lambda v: {"basis": "PER_SQM", "rate": float(v)}),
        "transport_flat": ("TRANSPORT", lambda v: {"basis": "FLAT", "rate": float(v)}),
        "overhead_pct": ("OVERHEAD", lambda v: {"pct": float(v), "base": "SUBTOTAL_BEFORE_OVERHEAD"}),
    }
    imported: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for key, raw in (payload or {}).items():
        # Never treat selling fields as cost
        if str(key).lower() in ("selling", "selling_rate", "sellingrate", "markup", "margin", "price"):
            review.append(
                {
                    "key": key,
                    "reason": "selling_not_cost",
                    "manualReview": True,
                    "zeroSilentLoss": True,
                }
            )
            continue
        if key not in known:
            review.append({"key": key, "value": raw, "manualReview": True, "zeroSilentLoss": True})
            continue
        domain, builder = known[key]
        try:
            params = builder(raw)
            if domain == "COATING" and "mode" in params and params["mode"] not in COATING_MODES:
                review.append({"key": key, "reason": "unknown_coating_mode", "manualReview": True})
                continue
            row = create_cost_rule(
                domain=domain,
                name=f"Legacy {key}",
                company_gst=company_gst,
                scope="COMPANY",
                params=params,
                source="legacy",
                manual_review=False,
                meta={"legacyKey": key},
            )
            imported.append(row)
        except Exception as exc:
            review.append({"key": key, "error": str(exc), "manualReview": True, "zeroSilentLoss": True})
    return {"imported": imported, "manualReview": review, "zeroSilentLoss": True}
