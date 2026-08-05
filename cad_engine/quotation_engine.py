"""Quotation Engine — line-item pricing from profile quotation rules + computed BOM.

NEVER uses lump-sum hardware. Every hardware part is priced individually from
profile hardware[].unitRate (or quotation.rates.hardware[part] fallback).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from cad_engine.job_types import GlassPane, LineItem, QuotationResult, WeightBreakdown


def _hardware_billable_qty(item: LineItem) -> float:
    """pcs/set/pack → quantity; m → running meters."""
    unit = (item.unit or "pcs").lower()
    if unit in ("m", "meter", "metre", "meters", "metres"):
        return (item.length_mm / 1000.0) * max(item.quantity, 0.0)
    return float(item.quantity)


def _hardware_rate(item: LineItem, rates: Mapping[str, Any], hw_rules: Sequence[Mapping[str, Any]]) -> float:
    """Resolve unit rate: LineItem.unit_rate → rule.unitRate → rates.hardware[part]."""
    if item.unit_rate is not None:
        return float(item.unit_rate)
    for rule in hw_rules or []:
        if str(rule.get("part", "")) == item.description:
            if "unitRate" in rule:
                return float(rule["unitRate"])
            break
    hw_map = rates.get("hardware") or {}
    if isinstance(hw_map, Mapping) and item.description in hw_map:
        return float(hw_map[item.description])
    return 0.0


def compute_quotation(
    quote_rules: Mapping[str, Any],
    *,
    weight: WeightBreakdown,
    glass: Sequence[GlassPane],
    hardware: Sequence[LineItem],
    brush: Sequence[LineItem],
    track_rail: Sequence[LineItem],
    hardware_rules: Sequence[Mapping[str, Any]] | None = None,
) -> QuotationResult:
    rates = quote_rules.get("rates") or {}
    if "hardwareLumpSum" in rates:
        raise ValueError(
            "quotation.rates.hardwareLumpSum is forbidden — price each hardware part via unitRate"
        )

    currency = str(quote_rules.get("currency", "INR"))
    labour = float(quote_rules.get("labourPerOpening", 0))
    markup = float(quote_rules.get("markupPercent", 0))
    gst_percent = float(quote_rules.get("gstPercent", 0))

    alu_rate = float(rates.get("aluminiumPerKg", 0))
    glass_rate = float(rates.get("glassPerM2", 0))
    brush_rate = float(rates.get("brushPerMeter", 0))
    rail_rate = float(rates.get("trackRailPerMeter", 0))
    packaging = float(rates.get("packagingPerOpening", 0))

    glass_area = sum(g.area_m2 * g.quantity for g in glass)
    brush_m = 0.0
    for b in brush:
        if b.description.endswith("TOTAL"):
            brush_m = b.length_mm / 1000.0
            break
    rail_m = sum((t.length_mm / 1000.0) * t.quantity for t in track_rail)

    lines: list[dict[str, Any]] = [
        {
            "category": "aluminium",
            "description": "Aluminium (kg)",
            "qty": round(weight.aluminium_kg, 3),
            "unit": "kg",
            "rate": alu_rate,
            "amount": round(weight.aluminium_kg * alu_rate, 2),
        },
        {
            "category": "glass",
            "description": "Glass (m²)",
            "qty": round(glass_area, 4),
            "unit": "m2",
            "rate": glass_rate,
            "amount": round(glass_area * glass_rate, 2),
        },
    ]

    hw_rules = hardware_rules or []
    for h in hardware:
        qty = _hardware_billable_qty(h)
        rate = _hardware_rate(h, rates, hw_rules)
        lines.append(
            {
                "category": "hardware",
                "description": h.description,
                "qty": round(qty, 4),
                "unit": h.unit,
                "rate": rate,
                "amount": round(qty * rate, 2),
            }
        )

    lines.extend(
        [
            {
                "category": "brush",
                "description": "Brush (m)",
                "qty": round(brush_m, 3),
                "unit": "m",
                "rate": brush_rate,
                "amount": round(brush_m * brush_rate, 2),
            },
            {
                "category": "trackRail",
                "description": "Track rail (m)",
                "qty": round(rail_m, 3),
                "unit": "m",
                "rate": rail_rate,
                "amount": round(rail_m * rail_rate, 2),
            },
            {
                "category": "labour",
                "description": "Labour",
                "qty": 1,
                "unit": "opening",
                "rate": labour,
                "amount": round(labour, 2),
            },
            {
                "category": "packaging",
                "description": "Packaging",
                "qty": 1,
                "unit": "opening",
                "rate": packaging,
                "amount": round(packaging, 2),
            },
        ]
    )

    subtotal = round(sum(float(x["amount"]) for x in lines), 2)
    markup_amount = round(subtotal * (markup / 100.0), 2)
    after_markup = round(subtotal + markup_amount, 2)
    gst_amount = round(after_markup * (gst_percent / 100.0), 2)
    final_total = round(after_markup + gst_amount, 2)

    return QuotationResult(
        currency=currency,
        lines=lines,
        subtotal=subtotal,
        markup_percent=markup,
        markup_amount=markup_amount,
        after_markup=after_markup,
        gst_percent=gst_percent,
        gst_amount=gst_amount,
        total=final_total,
    )
