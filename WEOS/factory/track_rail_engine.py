"""Track Rail Engine — quantity/length from profile trackRail rules."""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory.formula import eval_formula
from WEOS.factory.job_types import LineItem


def compute_track_rail(rules: Mapping[str, Any], ctx: Mapping[str, float]) -> list[LineItem]:
    if not rules:
        return []
    qty = eval_formula(rules.get("quantityFormula", "trackCount"), ctx)
    length = eval_formula(rules.get("lengthFormula", "width"), ctx)
    return [
        LineItem(
            category="track_rail",
            description="Track rail",
            quantity=qty,
            unit=str(rules.get("unit", "mm")),
            length_mm=length,
            remarks=str(rules.get("remarks", "")),
        )
    ]

