"""Glass Engine — sizes from shutter clear opening + per-side overlaps in profile JSON."""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory.formula import eval_formula
from WEOS.factory.geometry_engine import SlidingLayout
from WEOS.factory.job_types import GlassPane


def compute_glass(
    layout: SlidingLayout,
    glass_rules: Mapping[str, Any],
    ctx: Mapping[str, float],
) -> list[GlassPane]:
    """
    Glass NEVER guessed from magic numbers.
    pane_width  = clear_opening_width  + handleSideOverlap + interlockSideOverlap
    pane_height = clear_opening_height + topOverlap + bottomOverlap
    """
    hs = float(glass_rules["handleSideOverlap"])
    ils = float(glass_rules["interlockSideOverlap"])
    top = float(glass_rules["topOverlap"])
    bot = float(glass_rules["bottomOverlap"])
    if "thicknessMm" not in glass_rules:
        raise KeyError("profile.glass.thicknessMm is required (no Python default)")
    if "densityKgPerM3" not in glass_rules:
        raise KeyError("profile.glass.densityKgPerM3 is required (no Python default)")
    thk = float(glass_rules["thicknessMm"])
    density = float(glass_rules["densityKgPerM3"])
    qty = int(round(eval_formula(glass_rules.get("quantityFormula", "shutterCount"), ctx)))

    panes: list[GlassPane] = []
    specs = (
        ("left_glass", layout.left_glass.width, layout.left_glass.height),
        ("right_glass", layout.right_glass.width, layout.right_glass.height),
    )
    # quantityFormula is total panes; for 2-track emit one pane per shutter opening
    n = min(qty, len(specs)) if qty > 0 else 0
    for i in range(n):
        name, ow, oh = specs[i]
        gw = ow + hs + ils
        gh = oh + top + bot
        area = (gw / 1000.0) * (gh / 1000.0)
        vol_m3 = area * (thk / 1000.0)
        weight = vol_m3 * density
        panes.append(
            GlassPane(
                name=name,
                width_mm=gw,
                height_mm=gh,
                thickness_mm=thk,
                area_m2=area,
                weight_kg=weight,
                quantity=1,
            )
        )
    return panes

