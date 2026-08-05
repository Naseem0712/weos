"""Hardware Engine — part list from profile JSON formulas."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from WEOS.factory.formula import eval_formula
from WEOS.factory.job_types import LineItem


def compute_hardware(rules: Sequence[Mapping[str, Any]], ctx: Mapping[str, float]) -> list[LineItem]:
    items: list[LineItem] = []
    for rule in rules or []:
        qty = eval_formula(rule.get("quantityFormula", rule.get("quantity", 0)), ctx)
        length = eval_formula(rule.get("lengthFormula", 0), ctx)
        # length formulas in meters stay as-is in length_mm field if unit is m — store raw formula result
        unit = str(rule.get("unit", "pcs"))
        length_mm = length * 1000.0 if unit == "m" else length
        unit_rate = rule.get("unitRate")
        items.append(
            LineItem(
                category="hardware",
                description=str(rule.get("part", "part")),
                quantity=qty,
                unit=unit,
                length_mm=length_mm,
                remarks=str(rule.get("remarks", "")),
                unit_rate=float(unit_rate) if unit_rate is not None else None,
            )
        )
    return items

