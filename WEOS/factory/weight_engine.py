"""Weight Engine — aluminium + glass + hardware allowance from profile weight rules."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from WEOS.factory.formula import eval_formula
from WEOS.factory.job_types import GlassPane, WeightBreakdown


def compute_weight(
    weight_rules: Mapping[str, Any],
    glass: Sequence[GlassPane],
    ctx: Mapping[str, float],
) -> WeightBreakdown:
    if "aluminiumDensityKgPerM3" not in weight_rules:
        raise KeyError("profile.weight.aluminiumDensityKgPerM3 is required (no Python default)")
    density = float(weight_rules["aluminiumDensityKgPerM3"])
    waste = float(weight_rules.get("wasteFactor", 1.0))
    hw_allow = float(weight_rules.get("hardwareAllowanceKg", 0.0))
    details: dict[str, float] = {}
    alu = 0.0
    for sec in weight_rules.get("profileSections") or []:
        area_mm2 = float(sec.get("crossSectionAreaMm2", 0))
        length_mm = eval_formula(sec.get("lengthFormula", 0), ctx)
        # mass = density * area * length  (convert mm → m)
        vol_m3 = (area_mm2 * 1e-6) * (length_mm / 1000.0)
        kg = vol_m3 * density * waste
        name = str(sec.get("name", "section"))
        details[name] = kg
        alu += kg

    glass_kg = sum(g.weight_kg * g.quantity for g in glass)
    details["glass"] = glass_kg
    details["hardware_allowance"] = hw_allow
    total = alu + glass_kg + hw_allow
    return WeightBreakdown(
        aluminium_kg=alu,
        glass_kg=glass_kg,
        hardware_kg=hw_allow,
        total_kg=total,
        details=details,
    )

