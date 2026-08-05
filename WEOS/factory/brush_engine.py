"""Brush Engine — pile / wool pile lengths from profile brush rules."""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory.formula import eval_formula
from WEOS.factory.job_types import LineItem


def compute_brush(brush_rules: Mapping[str, Any], ctx: Mapping[str, float]) -> list[LineItem]:
    items: list[LineItem] = []
    total_mm = 0.0
    total_pcs = 0.0
    for side in ("handleSide", "meetingSide", "top", "bottom"):
        block = brush_rules.get(side) or {}
        if not block:
            continue
        pieces = eval_formula(block.get("piecesFormula", 0), ctx)
        length = eval_formula(block.get("lengthFormula", 0), ctx)
        items.append(
            LineItem(
                category="brush",
                description=f"Brush — {side}",
                quantity=pieces,
                unit="pcs",
                length_mm=length,
                remarks=f"each ≈ {length:.1f} mm",
            )
        )
        total_mm += pieces * length
        total_pcs += pieces
    items.append(
        LineItem(
            category="brush",
            description="Brush — TOTAL",
            quantity=total_pcs,
            unit="pcs",
            length_mm=total_mm,
            remarks=f"running length {total_mm:.1f} mm ({total_mm/1000:.3f} m)",
        )
    )
    return items

