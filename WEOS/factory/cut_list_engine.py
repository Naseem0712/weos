"""Profile Cut List Engine — lengths/angles from profile cutList rules."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from WEOS.factory.formula import eval_formula
from WEOS.factory.job_types import CutListItem


def compute_cut_list(
    rules: Sequence[Mapping[str, Any]],
    ctx: Mapping[str, float],
    *,
    waste_factor: float = 1.0,
) -> list[CutListItem]:
    items: list[CutListItem] = []
    for rule in rules or []:
        length = eval_formula(rule.get("lengthFormula", 0), ctx) * waste_factor
        qty = int(round(eval_formula(rule.get("quantityFormula", rule.get("qty", 1)), ctx)))
        items.append(
            CutListItem(
                profile=str(rule.get("profile", "profile")),
                length_mm=length,
                quantity=max(qty, 0),
                cut_angle=str(rule.get("cutAngle", "90")),
                machine_notes=str(rule.get("machineNotes", "")),
                total_length_mm=length * max(qty, 0),
            )
        )
    return items


def cut_list_totals(items: Sequence[CutListItem]) -> dict[str, float]:
    running = sum(i.length_mm * i.quantity for i in items)
    return {"total_running_length_mm": running, "total_running_length_m": running / 1000.0, "piece_count": float(sum(i.quantity for i in items))}

