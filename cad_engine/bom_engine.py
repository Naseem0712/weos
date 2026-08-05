"""BOM Engine — consolidate profiles, glass, hardware, brush, track, extras."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from cad_engine.formula import eval_formula
from cad_engine.job_types import CutListItem, GlassPane, LineItem


def compute_bom(
    *,
    cut_list: Sequence[CutListItem],
    glass: Sequence[GlassPane],
    hardware: Sequence[LineItem],
    brush: Sequence[LineItem],
    track_rail: Sequence[LineItem],
    extras: Sequence[Mapping[str, Any]] | None,
    ctx: Mapping[str, float],
) -> list[LineItem]:
    bom: list[LineItem] = []

    for c in cut_list:
        bom.append(
            LineItem(
                category="profile",
                description=c.profile,
                quantity=c.quantity,
                unit="pcs",
                length_mm=c.length_mm,
                remarks=f"{c.cut_angle}° — {c.machine_notes}".strip(" —"),
            )
        )

    for g in glass:
        bom.append(
            LineItem(
                category="glass",
                description=f"Glass {g.name} {g.width_mm:.0f}x{g.height_mm:.0f}x{g.thickness_mm:g}",
                quantity=g.quantity,
                unit="pcs",
                length_mm=0.0,
                remarks=f"area {g.area_m2:.4f} m², {g.weight_kg:.3f} kg",
            )
        )

    for h in hardware:
        bom.append(h)

    for b in brush:
        if b.description.endswith("TOTAL"):
            continue
        bom.append(b)

    for t in track_rail:
        bom.append(t)

    for ex in extras or []:
        bom.append(
            LineItem(
                category=str(ex.get("category", "accessory")),
                description=str(ex.get("description", "extra")),
                quantity=eval_formula(ex.get("quantityFormula", 1), ctx),
                unit=str(ex.get("unit", "pcs")),
                length_mm=eval_formula(ex.get("lengthFormula", 0), ctx),
                remarks=str(ex.get("remarks", "")),
            )
        )

    return bom
