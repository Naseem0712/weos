"""Selling price engine — strictly separate from cost calculation and tax/payment.

Methods: COST_PLUS_MARKUP | COST_PLUS_TARGET_MARGIN | MANUAL_RATE | MANUAL_AMOUNT |
         UNIT_RATE | LEGACY_MANUAL_RATE

Markup ≠ margin:
  selling = cost * (1 + markup/100)
  selling = cost / (1 - margin/100)   when margin < 100
"""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.db.models import COMMERCIAL_UNITS, SELLING_LOCK_STATUSES, SELLING_PRICE_METHODS
from WEOS.factory.live_pricing import area_metrics

# Aliases accepted from UI / legacy
_METHOD_ALIASES = {
    "COST+MARKUP": "COST_PLUS_MARKUP",
    "COST_MARKUP": "COST_PLUS_MARKUP",
    "MARKUP": "COST_PLUS_MARKUP",
    "COST+TARGET_MARGIN": "COST_PLUS_TARGET_MARGIN",
    "COST_TARGET_MARGIN": "COST_PLUS_TARGET_MARGIN",
    "TARGET_MARGIN": "COST_PLUS_TARGET_MARGIN",
    "MARGIN": "COST_PLUS_TARGET_MARGIN",
    "MANUAL": "MANUAL_AMOUNT",
    "LEGACY": "LEGACY_MANUAL_RATE",
}

_UNIT_ALIASES = {
    "sqft": "SFT",
    "sft": "SFT",
    "sq.ft": "SFT",
    "sqm": "SQM",
    "m2": "SQM",
    "nos": "NOS",
    "opening": "OPENING",
    "pc": "PC",
    "pcs": "PC",
    "rft": "RFT",
    "rmt": "RMT",
    "set": "SET",
    "unit": "UNIT",
}


def normalize_method(method: str | None) -> str:
    raw = str(method or "COST_PLUS_MARKUP").strip().upper().replace(" ", "_")
    return _METHOD_ALIASES.get(raw, raw)


def normalize_commercial_unit(unit: str | None) -> str:
    raw = str(unit or "SFT").strip().upper()
    low = raw.lower()
    if low in _UNIT_ALIASES:
        return _UNIT_ALIASES[low]
    if raw in COMMERCIAL_UNITS:
        return raw
    return "SFT"


def calculated_billing_qty(
    *,
    width_mm: float,
    height_mm: float,
    qty: float = 1.0,
    commercial_unit: str = "SFT",
) -> dict[str, Any]:
    """Commercial billing quantity from geometry — never mutates design geometry."""
    metrics = area_metrics(width_mm, height_mm)
    unit = normalize_commercial_unit(commercial_unit)
    q = max(float(qty or 1), 0.0)
    if unit == "SFT":
        calc = metrics["areaSqft"] * q
    elif unit == "SQM":
        calc = metrics["areaSqm"] * q
    elif unit in ("NOS", "OPENING", "PC", "SET", "UNIT"):
        calc = q
    elif unit == "RFT":
        calc = metrics["perimeterFt"] * q
    elif unit == "RMT":
        calc = metrics["perimeterM"] * q
    else:
        calc = metrics["areaSqft"] * q
    return {
        "commercialUnit": unit,
        "calculatedQty": round(calc, 6),
        "geometryQty": q,
        "metrics": metrics,
        "geometryUnchanged": True,
    }


def apply_billing_qty(
    calculated_qty: float,
    billing_override: float | None = None,
) -> dict[str, Any]:
    """Billing override changes commercial qty only — not BOM/geometry."""
    calc = float(calculated_qty or 0)
    if billing_override is not None and float(billing_override) >= 0:
        bill = float(billing_override)
        return {
            "calculatedQty": calc,
            "billingQty": bill,
            "billingQtyOverride": bill,
            "overrideActive": True,
            "geometryUnchanged": True,
        }
    return {
        "calculatedQty": calc,
        "billingQty": calc,
        "billingQtyOverride": None,
        "overrideActive": False,
        "geometryUnchanged": True,
    }


def selling_from_markup(cost: float, markup_pct: float) -> float:
    return float(cost) * (1.0 + float(markup_pct) / 100.0)


def selling_from_target_margin(cost: float, margin_pct: float) -> float:
    m = float(margin_pct)
    if m >= 100.0:
        raise ValueError("target margin must be < 100%")
    if m <= -1000:
        raise ValueError("target margin out of range")
    return float(cost) / (1.0 - m / 100.0)


def margin_from_cost_selling(cost: float, selling: float) -> float | None:
    s = float(selling)
    if s == 0:
        return None
    return ((s - float(cost)) / s) * 100.0


def markup_from_cost_selling(cost: float, selling: float) -> float | None:
    c = float(cost)
    if c == 0:
        return None
    return ((float(selling) - c) / c) * 100.0


def compute_selling_price(
    *,
    total_cost: float,
    method: str = "COST_PLUS_MARKUP",
    markup_pct: float | None = None,
    target_margin_pct: float | None = None,
    manual_rate: float | None = None,
    manual_amount: float | None = None,
    unit_rate: float | None = None,
    billing_qty: float | None = None,
    legacy_selling_rate: float | None = None,
    commercial_unit: str = "SFT",
    actual_selling_override: float | None = None,
    lock_status: str = "DRAFT",
) -> dict[str, Any]:
    """Produce suggested vs actual selling; never alters cost."""
    meth = normalize_method(method)
    if meth not in SELLING_PRICE_METHODS:
        raise ValueError(f"invalid selling method: {method}")
    lock = str(lock_status or "DRAFT").upper()
    if lock not in SELLING_LOCK_STATUSES:
        lock = "DRAFT"

    cost = float(total_cost or 0)
    qty = float(billing_qty if billing_qty is not None else 1.0)
    unit = normalize_commercial_unit(commercial_unit)
    issues: list[dict[str, Any]] = []
    suggested = 0.0
    rate_used: float | None = None

    if meth == "COST_PLUS_MARKUP":
        mk = float(markup_pct if markup_pct is not None else 0.0)
        suggested = selling_from_markup(cost, mk)
        rate_used = (suggested / qty) if qty else suggested
    elif meth == "COST_PLUS_TARGET_MARGIN":
        mg = float(target_margin_pct if target_margin_pct is not None else 0.0)
        suggested = selling_from_target_margin(cost, mg)
        rate_used = (suggested / qty) if qty else suggested
    elif meth == "MANUAL_RATE":
        rate_used = float(manual_rate or 0)
        suggested = rate_used * qty
    elif meth == "UNIT_RATE":
        rate_used = float(unit_rate if unit_rate is not None else (manual_rate or 0))
        suggested = rate_used * qty
    elif meth == "MANUAL_AMOUNT":
        suggested = float(manual_amount or 0)
        rate_used = (suggested / qty) if qty else suggested
    elif meth == "LEGACY_MANUAL_RATE":
        # Compatibility: existing quote rates become commercial selling, NOT cost
        rate_used = float(
            legacy_selling_rate if legacy_selling_rate is not None else (manual_rate or 0)
        )
        suggested = rate_used * qty
        issues.append(
            {
                "code": "LEGACY_MANUAL_RATE",
                "severity": "info",
                "message": "Legacy quote selling rate used as commercial selling only — not as cost basis",
            }
        )

    if actual_selling_override is not None:
        actual = float(actual_selling_override)
    else:
        actual = suggested

    gp = actual - cost
    gm = margin_from_cost_selling(cost, actual)
    mk_eff = markup_from_cost_selling(cost, actual)

    # Prove markup ≠ margin when both provided
    markup_margin_distinct = True
    if markup_pct is not None and target_margin_pct is not None:
        try:
            s_mk = selling_from_markup(cost, float(markup_pct))
            s_mg = selling_from_target_margin(cost, float(target_margin_pct))
            markup_margin_distinct = abs(s_mk - s_mg) > 1e-9 or abs(float(markup_pct) - float(target_margin_pct)) > 1e-9
        except ValueError:
            markup_margin_distinct = True

    return {
        "method": meth,
        "commercialUnit": unit,
        "billingQty": qty,
        "suggestedSelling": round(suggested, 4),
        "actualSelling": round(actual, 4),
        "sellingSubtotal": round(actual, 4),
        "unitRate": round(rate_used, 6) if rate_used is not None else None,
        "totalCost": round(cost, 4),
        "grossProfit": round(gp, 4),
        "grossMarginPct": round(gm, 6) if gm is not None else None,
        "effectiveMarkupPct": round(mk_eff, 6) if mk_eff is not None else None,
        "markupPct": float(markup_pct) if markup_pct is not None else None,
        "targetMarginPct": float(target_margin_pct) if target_margin_pct is not None else None,
        "lockStatus": lock,
        "costUnchanged": True,
        "usesCostAsSelling": False,
        "markupDistinctFromMargin": markup_margin_distinct,
        "issues": issues,
        "batch": "ENG-PRICE",
    }
