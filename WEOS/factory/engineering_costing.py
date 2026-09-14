"""Engineering Costing Engine — BOM → Material/Processing → Total Cost → Selling.

Strict separation: Engineering BOM | Cost Calculation | Selling Price | Tax | Payment.
Cost NEVER derived from Quote selling rate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.db.models import (
    COST_BREAKDOWN_CATEGORIES,
    CostingDocument,
    CostingLine,
    DesignElement,
    EngineeringBomDocument,
)
from WEOS.factory import cost_rules as cr
from WEOS.factory import engineering_bom as eb
from WEOS.factory import engineering_masters as em
from WEOS.factory import selling_price_engine as sp
from WEOS.factory.canonical_customer import _norm_company_gst

_log = logging.getLogger("weos.engineering_costing")

GENERATOR_VERSION = "eng-cost-1.0.0"
BATCH_ID = "ENG-COST"

_BOM_TO_BREAKDOWN = {
    "PROFILE": "MATERIAL",
    "MATERIAL": "MATERIAL",
    "GLASS": "GLASS",
    "HARDWARE": "HARDWARE",
    "MESH": "ACCESSORIES",
    "GASKET": "ACCESSORIES",
    "EPDM": "ACCESSORIES",
    "FASTENER": "ACCESSORIES",
    "ANCHOR": "ACCESSORIES",
    "FINISH": "COATING",
    "ACCESSORY": "ACCESSORIES",
    "OTHER": "OTHER",
}

_INTERNAL_KEYS = frozenset(
    {
        "totalCost",
        "categoryTotals",
        "grossProfit",
        "grossMarginPct",
        "markupPct",
        "targetMarginPct",
        "effectiveMarkupPct",
        "lines",
        "unitCost",
        "extendedCost",
        "costBasisValue",
        "originalUnitCost",
        "overrideUnitCost",
        "purchaseRate",
        "cost",
        "profit",
        "margin",
        "markup",
    }
)


def new_costing_id() -> str:
    return "ECOST-" + uuid.uuid4().hex[:16].upper()


def new_costing_line_id() -> str:
    return "ECL-" + uuid.uuid4().hex[:16].upper()


def _require_db() -> None:
    if not db_available():
        raise RuntimeError("Database unavailable for engineering costing")
    init_db()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def strip_internal_cost_fields(data: Any) -> Any:
    """Audit helper — remove cost/markup/profit from any public serialization."""
    if isinstance(data, list):
        return [strip_internal_cost_fields(x) for x in data]
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k in _INTERNAL_KEYS or k.lower() in {x.lower() for x in _INTERNAL_KEYS}:
                continue
            if "cost" in k.lower() and k not in ("costingId",):
                continue
            if any(x in k.lower() for x in ("markup", "margin", "profit", "purchase")):
                continue
            out[k] = strip_internal_cost_fields(v)
        return out
    return data


def public_commercial_view(costing: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "costingId": costing.get("costingId"),
        "elementId": costing.get("elementId"),
        "projectId": costing.get("projectId"),
        "sellingSubtotal": costing.get("actualSelling")
        if costing.get("actualSelling") is not None
        else costing.get("sellingSubtotal"),
        "commercialUnit": costing.get("commercialUnit"),
        "billingQty": costing.get("billingQty"),
        "lockStatus": costing.get("lockStatus"),
        "batch": "ENG-COST-PUBLIC",
    }


# ── Unit-aware cost basis ─────────────────────────────────────────────────────


def quantity_for_basis(line: Mapping[str, Any], basis: str | None) -> tuple[float, str]:
    """Return (qty, unit) for a cost basis type from a BOM line."""
    b = str(basis or "").upper()
    qty = float(line.get("quantity") or 1)
    if b == "PER_KG":
        return float(line.get("weightKg") or 0), "KG"
    if b in ("PER_RMT", "PER_LENGTH", "PER_M"):
        if line.get("lengthM") is not None:
            return float(line["lengthM"]), "RMT"
        if line.get("requiredLengthMm") is not None:
            return float(line["requiredLengthMm"]) / 1000.0, "RMT"
        return 0.0, "RMT"
    if b == "PER_RFT":
        mm = line.get("requiredLengthMm") or line.get("lengthMm") or 0
        return float(mm) / 304.8, "RFT"
    if b == "PER_MM":
        return float(line.get("requiredLengthMm") or line.get("lengthMm") or 0), "MM"
    if b in ("PER_SFT",):
        area = line.get("areaSqm")
        if area is None and line.get("widthMm") and line.get("heightMm"):
            area = (float(line["widthMm"]) * float(line["heightMm"]) * qty) / 1_000_000.0
        return float(area or 0) * 10.7639, "SFT"
    if b == "PER_SQM":
        area = line.get("areaSqm")
        if area is None and line.get("widthMm") and line.get("heightMm"):
            area = (float(line["widthMm"]) * float(line["heightMm"]) * qty) / 1_000_000.0
        return float(area or 0), "SQM"
    if b in ("PER_PC", "PER_NOS", "PER_SET", "PER_UNIT"):
        return qty, b.replace("PER_", "")
    # Fallback: piece qty
    return qty, "PC"


def line_material_cost(bom_line: Mapping[str, Any]) -> dict[str, Any]:
    """Cost one BOM line from its cost basis (or master). ESTIMATED_STOCK when no optimizer."""
    basis = bom_line.get("costBasisType")
    value = bom_line.get("costBasisValue")
    precision = "EXACT"
    issues: list[dict[str, Any]] = []

    # NOMINAL glass → ESTIMATED not EXACT
    if bom_line.get("deductionMode") == "NOMINAL" or (
        str(bom_line.get("category") or "").upper() == "GLASS"
        and bom_line.get("deductionMode") != "EXACT"
    ):
        precision = "ESTIMATED"

    # Stock consumption without optimizer → ESTIMATED_STOCK
    if bom_line.get("stockConsumptionMm") is not None and not (bom_line.get("meta") or {}).get(
        "optimizerResult"
    ):
        if str(bom_line.get("category") or "").upper() == "PROFILE":
            precision = "ESTIMATED_STOCK"

    if basis is None or value is None:
        # Try master lookup already stamped on line; else missing
        issues.append(
            {
                "code": "MISSING_COST_BASIS",
                "severity": "warning",
                "message": f"No cost basis for {bom_line.get('code') or bom_line.get('description')}",
            }
        )
        return {
            "unitCost": None,
            "extendedCost": 0.0,
            "quantityBasis": None,
            "quantityUnit": None,
            "costBasisType": basis,
            "costBasisValue": value,
            "precisionMode": precision,
            "issues": issues,
            "partial": True,
        }

    q_basis, q_unit = quantity_for_basis(bom_line, str(basis))
    # Prefer stock consumption length for profile PER_RMT when ESTIMATED_STOCK
    if precision == "ESTIMATED_STOCK" and str(basis).upper() in ("PER_RMT", "PER_LENGTH", "PER_M"):
        stock_mm = bom_line.get("stockConsumptionMm")
        if stock_mm is not None:
            q_basis = float(stock_mm) / 1000.0
            q_unit = "RMT"
    unit_cost = float(value)
    extended = round(unit_cost * q_basis, 6)
    return {
        "unitCost": unit_cost,
        "extendedCost": extended,
        "quantityBasis": q_basis,
        "quantityUnit": q_unit,
        "costBasisType": str(basis).upper(),
        "costBasisValue": unit_cost,
        "precisionMode": precision,
        "issues": issues,
        "partial": False,
    }


def _breakdown_for(category: str) -> str:
    return _BOM_TO_BREAKDOWN.get(str(category or "OTHER").upper(), "OTHER")


def _empty_totals() -> dict[str, float]:
    return {k: 0.0 for k in COST_BREAKDOWN_CATEGORIES}


def _apply_rule_charges(
    *,
    material_lines: list[dict[str, Any]],
    totals: dict[str, float],
    resolved: Mapping[str, Any],
    element: Mapping[str, Any] | None,
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply wastage / coating / fabrication / installation / transport / overhead."""
    extra: list[dict[str, Any]] = []
    domains = (resolved or {}).get("domains") or {}

    # Wastage — may be multiple conceptual applies; use resolved single rule params
    wastage_res = domains.get("WASTAGE") or {}
    if wastage_res.get("conflict"):
        issues.append(wastage_res.get("issues") or {"code": "COST_RULE_CONFLICT", "domain": "WASTAGE"})
    wrule = wastage_res.get("rule")
    if wrule:
        params = wrule.get("params") or {}
        pct = float(params.get("pct") or 0)
        applies = [str(x).upper() for x in (params.get("appliesTo") or ["MATERIAL", "PROFILE", "GLASS"])]
        base = 0.0
        for ln in material_lines:
            bc = ln.get("breakdownCategory")
            cat = ln.get("category")
            if bc in applies or cat in applies or (bc == "MATERIAL" and "PROFILE" in applies):
                base += float(ln.get("extendedCost") or 0)
        amt = round(base * pct / 100.0, 4)
        totals["WASTAGE"] += amt
        extra.append(
            {
                "lineId": new_costing_line_id(),
                "category": "WASTAGE",
                "breakdownCategory": "WASTAGE",
                "description": wrule.get("name") or "Wastage",
                "extendedCost": amt,
                "unitCost": pct,
                "quantityBasis": base,
                "quantityUnit": "PCT_BASE",
                "costBasisType": "PERCENT",
                "precisionMode": "ESTIMATED",
                "meta": {"ruleId": wrule.get("ruleId"), "pct": pct},
            }
        )
        # Optional nested glass wastage in same sample rule
        g_pct = params.get("glassPct")
        if g_pct is not None:
            g_applies = [str(x).upper() for x in (params.get("glassAppliesTo") or ["GLASS"])]
            g_base = sum(
                float(ln.get("extendedCost") or 0)
                for ln in material_lines
                if ln.get("breakdownCategory") in g_applies or ln.get("category") in g_applies
            )
            g_amt = round(g_base * float(g_pct) / 100.0, 4)
            totals["WASTAGE"] += g_amt
            extra.append(
                {
                    "lineId": new_costing_line_id(),
                    "category": "WASTAGE",
                    "breakdownCategory": "WASTAGE",
                    "description": "Glass wastage",
                    "extendedCost": g_amt,
                    "unitCost": float(g_pct),
                    "quantityBasis": g_base,
                    "quantityUnit": "PCT_BASE",
                    "costBasisType": "PERCENT",
                    "precisionMode": "ESTIMATED",
                    "meta": {"ruleId": wrule.get("ruleId"), "pct": float(g_pct)},
                }
            )

    # Coating
    coat_res = domains.get("COATING") or {}
    crule = coat_res.get("rule")
    if crule:
        params = crule.get("params") or {}
        mode = str(params.get("mode") or "SEPARATE").upper()
        if mode == "SEPARATE":
            rate = float(params.get("rate") or 0)
            basis = str(params.get("basis") or "PER_KG").upper()
            q = 0.0
            if basis == "PER_KG":
                q = sum(float(ln.get("meta", {}).get("weightKg") or ln.get("quantityBasis") or 0)
                        for ln in material_lines if ln.get("breakdownCategory") == "MATERIAL")
                # Prefer actual weight from bom meta
                q = 0.0
                for ln in material_lines:
                    if ln.get("breakdownCategory") == "MATERIAL":
                        q += float((ln.get("meta") or {}).get("weightKg") or 0)
            elif basis == "PER_SQM":
                q = sum(float((ln.get("meta") or {}).get("areaSqm") or 0) for ln in material_lines)
            amt = round(rate * q, 4)
            totals["COATING"] += amt
            extra.append(
                {
                    "lineId": new_costing_line_id(),
                    "category": "COATING",
                    "breakdownCategory": "COATING",
                    "description": crule.get("name") or "Coating",
                    "extendedCost": amt,
                    "unitCost": rate,
                    "quantityBasis": q,
                    "costBasisType": basis,
                    "precisionMode": "ESTIMATED",
                    "meta": {"ruleId": crule.get("ruleId"), "mode": mode},
                }
            )
        elif mode == "INCLUDED":
            extra.append(
                {
                    "lineId": new_costing_line_id(),
                    "category": "COATING",
                    "breakdownCategory": "COATING",
                    "description": (crule.get("name") or "Coating") + " (included in material)",
                    "extendedCost": 0.0,
                    "precisionMode": "EXACT",
                    "meta": {"ruleId": crule.get("ruleId"), "mode": mode},
                }
            )
        # NOT_APPLICABLE → skip

    el = element or {}
    w = float(el.get("widthMm") or 0)
    h = float(el.get("heightMm") or 0)
    area_sqm = (w * h) / 1_000_000.0 if w and h else 0.0

    def _material_base() -> float:
        return sum(
            float(ln.get("extendedCost") or 0)
            for ln in material_lines
            if ln.get("breakdownCategory") in ("MATERIAL", "GLASS", "HARDWARE", "ACCESSORIES")
        )

    def _direct_cost_base() -> float:
        return sum(float(v or 0) for k, v in totals.items() if k not in ("OVERHEAD",))

    def _charge_amount(params: Mapping[str, Any]) -> tuple[float, float, str]:
        basis = str(params.get("basis") or "FLAT").upper()
        rate = float(params.get("rate") or params.get("pct") or 0)
        if basis in ("PERCENT_MATERIAL",):
            q = _material_base()
            return round(q * rate / 100.0, 4), q, basis
        if basis in ("PERCENT_DIRECT_COST", "PERCENT"):
            q = _direct_cost_base()
            return round(q * rate / 100.0, 4), q, basis
        if basis in ("FIXED", "FLAT"):
            return round(rate, 4), 1.0, basis
        if basis in ("PER_OPENING", "PER_ASSEMBLY"):
            return round(rate * 1.0, 4), 1.0, basis
        if basis == "PER_SQM":
            return round(rate * area_sqm, 4), area_sqm, basis
        if basis == "PER_KG":
            q = sum(
                float((ln.get("meta") or {}).get("weightKg") or 0)
                for ln in material_lines
                if ln.get("breakdownCategory") == "MATERIAL"
            )
            return round(rate * q, 4), q, basis
        return round(rate, 4), 1.0, basis

    def _simple_charge(domain: str, breakdown: str) -> None:
        res = domains.get(domain) or {}
        rule = res.get("rule")
        if not rule:
            return
        params = rule.get("params") or {}
        amt, q, basis = _charge_amount(params)
        rate = float(params.get("rate") or params.get("pct") or 0)
        totals[breakdown] = totals.get(breakdown, 0.0) + amt
        extra.append(
            {
                "lineId": new_costing_line_id(),
                "category": domain,
                "breakdownCategory": breakdown,
                "description": rule.get("name") or domain.title(),
                "extendedCost": amt,
                "unitCost": rate,
                "quantityBasis": q,
                "costBasisType": basis,
                "precisionMode": "ESTIMATED",
                "meta": {"ruleId": rule.get("ruleId"), "basis": basis},
            }
        )

    _simple_charge("FABRICATION", "FABRICATION")
    _simple_charge("INSTALLATION", "INSTALLATION")
    _simple_charge("TRANSPORT", "TRANSPORT")
    _simple_charge("OTHER", "OTHER")

    # Overhead on subtotal before overhead — never treated as profit
    oh_res = domains.get("OVERHEAD") or {}
    orule = oh_res.get("rule")
    if orule:
        params = orule.get("params") or {}
        basis = str(params.get("basis") or "PERCENT").upper()
        if basis in ("PERCENT_DIRECT_COST", "PERCENT", "") or params.get("pct") is not None:
            pct = float(params.get("pct") or params.get("rate") or 0)
            sub = sum(v for k, v in totals.items() if k != "OVERHEAD")
            amt = round(sub * pct / 100.0, 4)
            rate = pct
            q = sub
            cost_basis = "PERCENT_DIRECT_COST"
        else:
            amt, q, cost_basis = _charge_amount(params)
            rate = float(params.get("rate") or params.get("pct") or 0)
        totals["OVERHEAD"] += amt
        extra.append(
            {
                "lineId": new_costing_line_id(),
                "category": "OVERHEAD",
                "breakdownCategory": "OVERHEAD",
                "description": orule.get("name") or "Overhead",
                "extendedCost": amt,
                "unitCost": rate,
                "quantityBasis": q,
                "costBasisType": cost_basis,
                "precisionMode": "ESTIMATED",
                "meta": {"ruleId": orule.get("ruleId"), "notProfit": True},
            }
        )

    return extra


def calculate_from_bom(
    bom: Mapping[str, Any],
    *,
    company_gst: str,
    element: Mapping[str, Any] | None = None,
    selling: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure calculation — does not persist. Cost from BOM + rules only."""
    gst = _norm_company_gst(company_gst)
    lines_in = list(bom.get("lines") or [])
    issues: list[dict[str, Any]] = []
    if bom.get("usesQuoteSellingRate"):
        issues.append(
            {
                "code": "FORBIDDEN_SELLING_AS_COST",
                "severity": "error",
                "message": "BOM must not use quote selling rate as cost",
            }
        )

    ctx = {
        "projectId": bom.get("projectId"),
        "designDocumentId": bom.get("designDocumentId"),
        "elementId": bom.get("elementId"),
        "seriesId": (bom.get("series") or {}).get("seriesId") if isinstance(bom.get("series"), dict) else None,
        "seriesCode": (bom.get("series") or {}).get("code") if isinstance(bom.get("series"), dict) else None,
        "family": "WINDOW",
        **dict(context or {}),
    }
    resolved = cr.resolve_all_domains(company_gst=gst, context=ctx)
    issues.extend(resolved.get("issues") or [])

    cost_lines: list[dict[str, Any]] = []
    totals = _empty_totals()
    partial = False

    for bl in lines_in:
        # Skip rollup-only duplicates if meta says so — piece lines are source of truth
        if bl.get("scopeLevel") and str(bl.get("scopeLevel")).upper() not in ("PIECE", "CELL", "ELEMENT"):
            if (bl.get("meta") or {}).get("rolledOnly"):
                continue
        calc = line_material_cost(bl)
        if calc.get("partial"):
            partial = True
        issues.extend(calc.get("issues") or [])
        bc = _breakdown_for(bl.get("category") or "OTHER")
        ext = float(calc.get("extendedCost") or 0)
        totals[bc] = totals.get(bc, 0.0) + ext
        cost_lines.append(
            {
                "lineId": new_costing_line_id(),
                "bomLineId": bl.get("lineId"),
                "category": bl.get("category"),
                "breakdownCategory": bc,
                "masterId": bl.get("masterId"),
                "masterKind": bl.get("masterKind"),
                "code": bl.get("code"),
                "description": bl.get("description") or "",
                "costBasisType": calc.get("costBasisType"),
                "costBasisValue": calc.get("costBasisValue"),
                "quantityBasis": calc.get("quantityBasis"),
                "quantityUnit": calc.get("quantityUnit"),
                "unitCost": calc.get("unitCost"),
                "extendedCost": ext,
                "precisionMode": calc.get("precisionMode"),
                "cellId": bl.get("cellId"),
                "memberId": bl.get("memberId"),
                "elementId": bl.get("elementId") or bom.get("elementId"),
                "originalUnitCost": calc.get("unitCost"),
                "originalExtendedCost": ext,
                "meta": {
                    "weightKg": bl.get("weightKg"),
                    "areaSqm": bl.get("areaSqm"),
                    "profileRole": bl.get("profileRole"),
                    "deductionMode": bl.get("deductionMode"),
                    "outerFrame": (bl.get("meta") or {}).get("outerFrame"),
                },
                "usesQuoteSellingRate": False,
            }
        )

    extra = _apply_rule_charges(
        material_lines=cost_lines,
        totals=totals,
        resolved=resolved,
        element=element,
        issues=issues,
    )
    cost_lines.extend(extra)

    total_cost = round(sum(totals.values()), 4)

    # Selling (separate domain)
    sell_in = dict(selling or {})
    el = element or {}
    w = float(el.get("widthMm") or sell_in.get("widthMm") or 0)
    h = float(el.get("heightMm") or sell_in.get("heightMm") or 0)
    geom_qty = float(sell_in.get("qty") or el.get("quantity") or 1)
    unit = sell_in.get("commercialUnit") or sell_in.get("saleUnit") or "SFT"
    calc_q = sp.calculated_billing_qty(
        width_mm=w, height_mm=h, qty=geom_qty, commercial_unit=unit
    )
    bill = sp.apply_billing_qty(calc_q["calculatedQty"], sell_in.get("billingQtyOverride"))
    sell_out = sp.compute_selling_price(
        total_cost=total_cost,
        method=sell_in.get("method") or sell_in.get("sellingMethod") or "COST_PLUS_MARKUP",
        markup_pct=sell_in.get("markupPct"),
        target_margin_pct=sell_in.get("targetMarginPct"),
        manual_rate=sell_in.get("manualRate"),
        manual_amount=sell_in.get("manualAmount"),
        unit_rate=sell_in.get("unitRate"),
        billing_qty=bill["billingQty"],
        legacy_selling_rate=sell_in.get("legacySellingRate") or sell_in.get("sellingRate"),
        commercial_unit=calc_q["commercialUnit"],
        actual_selling_override=sell_in.get("actualSelling"),
        lock_status=sell_in.get("lockStatus") or "DRAFT",
    )
    issues.extend(sell_out.get("issues") or [])

    calc_status = "READY"
    if any(i.get("severity") == "error" for i in issues):
        calc_status = "ERROR"
    elif partial or any(i.get("severity") == "warning" for i in issues):
        calc_status = "PARTIAL"
    if bom.get("status") == "STALE":
        calc_status = "STALE"

    doc_status = "CURRENT"
    if calc_status == "STALE":
        doc_status = "STALE"
    elif calc_status == "ERROR":
        doc_status = "ERROR"
    elif calc_status == "PARTIAL":
        doc_status = "PARTIAL"

    return {
        "companyGst": gst,
        "projectId": bom.get("projectId"),
        "designDocumentId": bom.get("designDocumentId"),
        "assemblyId": bom.get("assemblyId"),
        "elementId": bom.get("elementId"),
        "bomId": bom.get("bomId"),
        "scopeLevel": "ELEMENT",
        "status": doc_status,
        "calcStatus": calc_status,
        "generatorVersion": GENERATOR_VERSION,
        "bomRevisionToken": bom.get("sourceFingerprint") or bom.get("bomId"),
        "masterRevisionToken": bom.get("masterRevisionToken") or em.master_revision_token(gst),
        "costRuleRevisionToken": cr.cost_rule_revision_token(gst),
        "categoryTotals": {k: round(v, 4) for k, v in totals.items()},
        "totalCost": total_cost,
        "lines": cost_lines,
        "issues": issues,
        "summary": {
            "lineCount": len(cost_lines),
            "bomLineCount": len(lines_in),
            "totalCost": total_cost,
            "usesQuoteSellingRate": False,
        },
        "sellingMethod": sell_out["method"],
        "sellingSubtotal": sell_out["sellingSubtotal"],
        "suggestedSelling": sell_out["suggestedSelling"],
        "actualSelling": sell_out["actualSelling"],
        "grossProfit": sell_out["grossProfit"],
        "grossMarginPct": sell_out["grossMarginPct"],
        "markupPct": sell_out.get("markupPct"),
        "targetMarginPct": sell_out.get("targetMarginPct"),
        "commercialUnit": sell_out["commercialUnit"],
        "calculatedQty": bill["calculatedQty"],
        "billingQty": bill["billingQty"],
        "billingQtyOverride": bill.get("billingQtyOverride"),
        "lockStatus": sell_out["lockStatus"],
        "selling": sell_out,
        "resolvedRules": {k: (v.get("rule") or {}).get("ruleId") for k, v in (resolved.get("domains") or {}).items()},
        "editableSource": False,
        "usesQuoteSellingRateAsCost": False,
        "batch": BATCH_ID,
    }


def _persist_costing(payload: dict[str, Any], *, supersede_element_id: str | None = None) -> dict[str, Any]:
    _require_db()
    costing_id = new_costing_id()
    fp = _fingerprint(
        {
            "bom": payload.get("bomId"),
            "bomRev": payload.get("bomRevisionToken"),
            "master": payload.get("masterRevisionToken"),
            "rules": payload.get("costRuleRevisionToken"),
            "gen": GENERATOR_VERSION,
            "sell": payload.get("sellingMethod"),
            "mk": payload.get("markupPct"),
            "mg": payload.get("targetMarginPct"),
        }
    )
    with session_scope() as s:
        if supersede_element_id:
            olds = (
                s.query(CostingDocument)
                .filter(
                    CostingDocument.element_id == supersede_element_id,
                    CostingDocument.is_current.is_(True),
                )
                .all()
            )
            for old in olds:
                old.is_current = False
                old.superseded_by = costing_id
        doc = CostingDocument(
            costing_id=costing_id,
            company_gst=payload["companyGst"],
            project_id=payload["projectId"],
            design_document_id=payload.get("designDocumentId"),
            assembly_id=payload.get("assemblyId"),
            element_id=payload.get("elementId"),
            bom_id=payload.get("bomId"),
            scope_level=payload.get("scopeLevel") or "ELEMENT",
            status=payload.get("status") or "CURRENT",
            calc_status=payload.get("calcStatus") or "READY",
            generator_version=payload.get("generatorVersion") or GENERATOR_VERSION,
            bom_revision_token=payload.get("bomRevisionToken"),
            master_revision_token=payload.get("masterRevisionToken"),
            cost_rule_revision_token=payload.get("costRuleRevisionToken"),
            source_fingerprint=fp,
            category_totals=payload.get("categoryTotals") or {},
            total_cost=float(payload.get("totalCost") or 0),
            selling_method=payload.get("sellingMethod"),
            selling_subtotal=payload.get("sellingSubtotal"),
            suggested_selling=payload.get("suggestedSelling"),
            actual_selling=payload.get("actualSelling"),
            gross_profit=payload.get("grossProfit"),
            gross_margin_pct=payload.get("grossMarginPct"),
            markup_pct=payload.get("markupPct"),
            target_margin_pct=payload.get("targetMarginPct"),
            commercial_unit=payload.get("commercialUnit"),
            calculated_qty=payload.get("calculatedQty"),
            billing_qty=payload.get("billingQty"),
            billing_qty_override=payload.get("billingQtyOverride"),
            lock_status=payload.get("lockStatus") or "DRAFT",
            issues=payload.get("issues") or [],
            summary=payload.get("summary") or {},
            lines_payload=payload.get("lines") or [],
            selling_payload=payload.get("selling") or {},
            is_current=True,
            meta={
                "resolvedRules": payload.get("resolvedRules"),
                "batch": BATCH_ID,
            },
        )
        s.add(doc)
        synced: list[dict[str, Any]] = []
        for i, ln in enumerate(payload.get("lines") or []):
            new_lid = new_costing_line_id()
            meta = dict(ln.get("meta") or {})
            if ln.get("lineId"):
                meta["priorLineId"] = ln.get("lineId")
            row = CostingLine(
                line_id=new_lid,
                costing_id=costing_id,
                company_gst=payload["companyGst"],
                bom_line_id=ln.get("bomLineId"),
                category=ln.get("category") or "OTHER",
                breakdown_category=ln.get("breakdownCategory") or "OTHER",
                master_id=ln.get("masterId"),
                master_kind=ln.get("masterKind"),
                code=ln.get("code"),
                description=ln.get("description") or "",
                cost_basis_type=ln.get("costBasisType"),
                cost_basis_value=ln.get("costBasisValue"),
                quantity_basis=ln.get("quantityBasis"),
                quantity_unit=ln.get("quantityUnit"),
                unit_cost=ln.get("unitCost"),
                extended_cost=float(ln.get("extendedCost") or 0),
                precision_mode=ln.get("precisionMode"),
                cell_id=ln.get("cellId"),
                member_id=ln.get("memberId"),
                element_id=ln.get("elementId") or payload.get("elementId"),
                original_unit_cost=ln.get("originalUnitCost"),
                original_extended_cost=ln.get("originalExtendedCost"),
                override_unit_cost=ln.get("overrideUnitCost"),
                override_extended_cost=ln.get("overrideExtendedCost"),
                override_reason=ln.get("overrideReason"),
                override_user=ln.get("overrideUser"),
                sort_order=i,
                meta=meta,
            )
            s.add(row)
            synced.append({**ln, "lineId": new_lid, "meta": meta})
        doc.lines_payload = synced
        s.flush()
        out = doc.to_dict(include_internal=True)
        out["resolvedRules"] = payload.get("resolvedRules")
        return out


def generate_element_costing(
    element_id: str,
    *,
    company_gst: str,
    persist: bool = True,
    force: bool = False,
    selling: Mapping[str, Any] | None = None,
    ensure_bom: bool = True,
) -> dict[str, Any]:
    _require_db()
    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        el = s.get(DesignElement, element_id)
        if not el or el.company_gst != gst:
            raise PermissionError("element not found")
        element = el.to_dict()

    bom = eb.get_current_bom(element_id=element_id, company_gst=gst)
    if bom is None and ensure_bom:
        bom = eb.generate_element_bom(element_id, company_gst=gst, persist=True, force=False)
    elif ensure_bom and bom is not None and (force or bom.get("status") == "STALE" or bom.get("freshness") == "STALE"):
        # Cost regenerate refreshes from a current BOM — does not redesign BOM domain
        bom = eb.generate_element_bom(element_id, company_gst=gst, persist=True, force=True)
    if bom is None:
        raise ValueError("no BOM available for costing")

    if not force and persist:
        existing = get_current_costing(element_id=element_id, company_gst=gst)
        if (
            existing
            and existing.get("bomId") == bom.get("bomId")
            and existing.get("calcStatus") != "STALE"
            and existing.get("status") != "STALE"
            and existing.get("costRuleRevisionToken") == cr.cost_rule_revision_token(gst)
        ):
            return existing

    payload = calculate_from_bom(bom, company_gst=gst, element=element, selling=selling)
    if persist:
        return _persist_costing(payload, supersede_element_id=element_id)
    payload["costingId"] = new_costing_id()
    payload["isCurrent"] = True
    return payload


def regenerate_costing(
    element_id: str,
    *,
    company_gst: str,
    selling: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create new CostingDocument and supersede prior current — never mutate historical."""
    return generate_element_costing(
        element_id, company_gst=company_gst, persist=True, force=True, selling=selling
    )


def get_current_costing(
    *,
    element_id: str | None = None,
    costing_id: str | None = None,
    company_gst: str,
) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        if costing_id:
            doc = s.get(CostingDocument, costing_id)
            if not doc or doc.company_gst != gst:
                return None
        else:
            doc = (
                s.query(CostingDocument)
                .filter(
                    CostingDocument.element_id == element_id,
                    CostingDocument.company_gst == gst,
                    CostingDocument.is_current.is_(True),
                )
                .order_by(CostingDocument.created_at.desc())
                .first()
            )
            if not doc:
                return None
        out = doc.to_dict(include_internal=True)
        # Stale checks
        if doc.status == "STALE" or doc.calc_status == "STALE":
            out["freshness"] = "STALE"
            return out
        # BOM stale → cost stale
        if doc.element_id:
            bom = (
                s.query(EngineeringBomDocument)
                .filter(
                    EngineeringBomDocument.element_id == doc.element_id,
                    EngineeringBomDocument.company_gst == gst,
                    EngineeringBomDocument.is_current.is_(True),
                )
                .first()
            )
            if bom and (bom.status == "STALE" or bom.bom_id != doc.bom_id):
                out["freshness"] = "STALE"
                out["status"] = "STALE"
                out["calcStatus"] = "STALE"
                out["staleReason"] = "bom_stale_or_superseded"
                return out
        try:
            if doc.master_revision_token and doc.master_revision_token != em.master_revision_token(gst):
                out["freshness"] = "STALE"
                out["status"] = "STALE"
                out["calcStatus"] = "STALE"
                out["staleReason"] = "master_cost_changed"
                return out
            if doc.cost_rule_revision_token and doc.cost_rule_revision_token != cr.cost_rule_revision_token(
                gst
            ):
                out["freshness"] = "STALE"
                out["status"] = "STALE"
                out["calcStatus"] = "STALE"
                out["staleReason"] = "cost_rule_changed"
                return out
        except Exception:
            pass
        out["freshness"] = "CURRENT" if doc.is_current else doc.status
        return out


def mark_stale_for_element(element_id: str, *, company_gst: str, reason: str = "design_changed") -> int:
    _require_db()
    gst = _norm_company_gst(company_gst)
    n = 0
    with session_scope() as s:
        rows = (
            s.query(CostingDocument)
            .filter(
                CostingDocument.element_id == element_id,
                CostingDocument.company_gst == gst,
                CostingDocument.is_current.is_(True),
            )
            .all()
        )
        for r in rows:
            r.status = "STALE"
            r.calc_status = "STALE"
            meta = dict(r.meta or {})
            meta["staleReason"] = reason
            r.meta = meta
            n += 1
    return n


def mark_stale_for_project(project_id: str, *, company_gst: str, reason: str = "master_changed") -> int:
    _require_db()
    gst = _norm_company_gst(company_gst)
    n = 0
    with session_scope() as s:
        rows = (
            s.query(CostingDocument)
            .filter(
                CostingDocument.project_id == project_id,
                CostingDocument.company_gst == gst,
                CostingDocument.is_current.is_(True),
            )
            .all()
        )
        for r in rows:
            r.status = "STALE"
            r.calc_status = "STALE"
            meta = dict(r.meta or {})
            meta["staleReason"] = reason
            r.meta = meta
            n += 1
    return n


def apply_line_override(
    costing_id: str,
    line_id: str,
    *,
    company_gst: str,
    override_unit_cost: float | None = None,
    override_extended_cost: float | None = None,
    reason: str,
    user: str | None = None,
) -> dict[str, Any]:
    """Manual override — preserves original; never overwrites master/BOM source."""
    _require_db()
    if not reason or not str(reason).strip():
        raise ValueError("override reason required")
    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        doc = s.get(CostingDocument, costing_id)
        if not doc or doc.company_gst != gst:
            raise PermissionError("costing not found")
        if doc.lock_status == "LOCKED":
            raise ValueError("costing is LOCKED")
        lines = list(doc.lines_payload or [])
        found = False
        for ln in lines:
            if ln.get("lineId") != line_id:
                continue
            found = True
            if ln.get("originalUnitCost") is None:
                ln["originalUnitCost"] = ln.get("unitCost")
            if ln.get("originalExtendedCost") is None:
                ln["originalExtendedCost"] = ln.get("extendedCost")
            if override_unit_cost is not None:
                ln["overrideUnitCost"] = float(override_unit_cost)
                ln["unitCost"] = float(override_unit_cost)
                qb = float(ln.get("quantityBasis") or 1)
                ln["extendedCost"] = round(float(override_unit_cost) * qb, 6)
                ln["overrideExtendedCost"] = ln["extendedCost"]
            if override_extended_cost is not None:
                ln["overrideExtendedCost"] = float(override_extended_cost)
                ln["extendedCost"] = float(override_extended_cost)
            ln["overrideReason"] = reason
            ln["overrideUser"] = user
            ln["overrideAt"] = _now().isoformat()
            # Master/BOM source preserved in meta
            meta = dict(ln.get("meta") or {})
            meta["masterSourcePreserved"] = True
            meta["bomSourcePreserved"] = True
            ln["meta"] = meta
            break
        if not found:
            raise ValueError("costing line not found")

        # Re-sum material categories; keep rule lines as-is then regenerate via force is cleaner
        # For override path: recompute totals from lines
        totals = _empty_totals()
        for ln in lines:
            bc = ln.get("breakdownCategory") or "OTHER"
            if bc in totals:
                totals[bc] += float(ln.get("extendedCost") or 0)
            else:
                totals["OTHER"] += float(ln.get("extendedCost") or 0)
        total_cost = round(sum(totals.values()), 4)
        sell = sp.compute_selling_price(
            total_cost=total_cost,
            method=doc.selling_method or "COST_PLUS_MARKUP",
            markup_pct=doc.markup_pct,
            target_margin_pct=doc.target_margin_pct,
            billing_qty=doc.billing_qty,
            commercial_unit=doc.commercial_unit or "SFT",
            actual_selling_override=doc.actual_selling if doc.selling_method in ("MANUAL_AMOUNT",) else None,
            lock_status=doc.lock_status or "DRAFT",
        )
        # Create NEW document (never silently mutate historical) when regenerating;
        # for override on current DRAFT/UNLOCKED we update current payload but bump via new doc.
        payload = doc.to_dict(include_internal=True)
        payload["lines"] = lines
        payload["categoryTotals"] = {k: round(v, 4) for k, v in totals.items()}
        payload["totalCost"] = total_cost
        payload["selling"] = sell
        payload["sellingSubtotal"] = sell["sellingSubtotal"]
        payload["suggestedSelling"] = sell["suggestedSelling"]
        payload["actualSelling"] = sell["actualSelling"]
        payload["grossProfit"] = sell["grossProfit"]
        payload["grossMarginPct"] = sell["grossMarginPct"]
        payload["summary"] = {**(payload.get("summary") or {}), "overrideApplied": True}
    return _persist_costing(payload, supersede_element_id=payload.get("elementId"))


def update_selling(
    costing_id: str,
    *,
    company_gst: str,
    selling: Mapping[str, Any],
) -> dict[str, Any]:
    """Update selling without altering cost lines (unless method depends on cost)."""
    _require_db()
    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        doc = s.get(CostingDocument, costing_id)
        if not doc or doc.company_gst != gst:
            raise PermissionError("costing not found")
        if doc.lock_status == "LOCKED":
            raise ValueError("costing is LOCKED — unlock before changing selling")
        payload = doc.to_dict(include_internal=True)
        total_cost = float(doc.total_cost or 0)
        # Billing override must not change geometry / cost
        bill = sp.apply_billing_qty(
            float(doc.calculated_qty or doc.billing_qty or 1),
            selling.get("billingQtyOverride", doc.billing_qty_override),
        )
        sell_out = sp.compute_selling_price(
            total_cost=total_cost,
            method=selling.get("method") or selling.get("sellingMethod") or doc.selling_method,
            markup_pct=selling.get("markupPct", doc.markup_pct),
            target_margin_pct=selling.get("targetMarginPct", doc.target_margin_pct),
            manual_rate=selling.get("manualRate"),
            manual_amount=selling.get("manualAmount"),
            unit_rate=selling.get("unitRate"),
            billing_qty=bill["billingQty"],
            legacy_selling_rate=selling.get("legacySellingRate") or selling.get("sellingRate"),
            commercial_unit=selling.get("commercialUnit") or doc.commercial_unit or "SFT",
            actual_selling_override=selling.get("actualSelling"),
            lock_status=selling.get("lockStatus") or doc.lock_status or "DRAFT",
        )
        payload["selling"] = sell_out
        payload["sellingMethod"] = sell_out["method"]
        payload["sellingSubtotal"] = sell_out["sellingSubtotal"]
        payload["suggestedSelling"] = sell_out["suggestedSelling"]
        payload["actualSelling"] = sell_out["actualSelling"]
        payload["grossProfit"] = sell_out["grossProfit"]
        payload["grossMarginPct"] = sell_out["grossMarginPct"]
        payload["markupPct"] = sell_out.get("markupPct")
        payload["targetMarginPct"] = sell_out.get("targetMarginPct")
        payload["commercialUnit"] = sell_out["commercialUnit"]
        payload["calculatedQty"] = bill["calculatedQty"]
        payload["billingQty"] = bill["billingQty"]
        payload["billingQtyOverride"] = bill.get("billingQtyOverride")
        payload["lockStatus"] = sell_out["lockStatus"]
        # Cost lines unchanged
        payload["lines"] = list(doc.lines_payload or [])
        payload["totalCost"] = total_cost
        payload["categoryTotals"] = doc.category_totals or {}
        element_id = doc.element_id
    return _persist_costing(payload, supersede_element_id=element_id)


def rollup_project_costing(*, project_id: str, company_gst: str) -> dict[str, Any]:
    """Design → Floor → Location → Project commercial + internal cost rollup."""
    _require_db()
    from WEOS.factory import design_scene as ds

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        docs = (
            s.query(CostingDocument)
            .filter(
                CostingDocument.project_id == project_id,
                CostingDocument.company_gst == gst,
                CostingDocument.is_current.is_(True),
                CostingDocument.scope_level == "ELEMENT",
            )
            .all()
        )
        costings = [d.to_dict(include_internal=True) for d in docs]

    # Attach floor/location from elements when available
    by_floor: dict[str, dict[str, Any]] = {}
    by_location: dict[str, dict[str, Any]] = {}
    project_totals = _empty_totals()
    project_cost = 0.0
    project_sell = 0.0

    for c in costings:
        floor = "UNASSIGNED"
        loc = "UNASSIGNED"
        eid = c.get("elementId")
        if eid:
            try:
                el = ds.get_element(eid, company_gst=gst)
                if el:
                    floor = el.get("floor") or el.get("floorLabel") or (el.get("meta") or {}).get("floor") or floor
                    loc = el.get("location") or el.get("locationLabel") or (el.get("meta") or {}).get("location") or loc
            except Exception:
                pass
        c["_floor"] = floor
        c["_location"] = loc
        tc = float(c.get("totalCost") or 0)
        ts = float(c.get("actualSelling") or c.get("sellingSubtotal") or 0)
        project_cost += tc
        project_sell += ts
        for k, v in (c.get("categoryTotals") or {}).items():
            project_totals[k] = project_totals.get(k, 0.0) + float(v or 0)

        bf = by_floor.setdefault(floor, {"floor": floor, "totalCost": 0.0, "selling": 0.0, "designs": []})
        bf["totalCost"] += tc
        bf["selling"] += ts
        bf["designs"].append(c.get("costingId"))

        lk = f"{floor}|{loc}"
        bl = by_location.setdefault(
            lk, {"floor": floor, "location": loc, "totalCost": 0.0, "selling": 0.0, "designs": []}
        )
        bl["totalCost"] += tc
        bl["selling"] += ts
        bl["designs"].append(c.get("costingId"))

    return {
        "projectId": project_id,
        "companyGst": gst,
        "designs": costings,
        "floors": list(by_floor.values()),
        "locations": list(by_location.values()),
        "categoryTotals": {k: round(v, 4) for k, v in project_totals.items()},
        "totalCost": round(project_cost, 4),
        "sellingSubtotal": round(project_sell, 4),
        "grossProfit": round(project_sell - project_cost, 4),
        "hierarchy": ["DESIGN", "FLOOR", "LOCATION", "PROJECT"],
        "batch": BATCH_ID,
        "internalOnly": True,
    }


# ── Brief-aligned aliases (factory API surface) ───────────────────────────────

calculate_bom_line_cost = line_material_cost


def resolve_cost_rules(*, company_gst: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Resolve all cost-rule domains with DESIGN>PROJECT>ITEM>SERIES>FAMILY>COMPANY precedence."""
    return cr.resolve_all_domains(company_gst=company_gst, context=context)


def calculate_selling_price(**kwargs: Any) -> dict[str, Any]:
    """Selling-price entry point — never mutates cost inputs."""
    return sp.compute_selling_price(**kwargs)
