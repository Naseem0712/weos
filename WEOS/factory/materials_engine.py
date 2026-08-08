"""Materials Engine — evaluate Product Library material formulas into BOM lines."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from WEOS.factory.formula import eval_formula, normalize_unit
from WEOS.factory.job_types import LineItem


def compute_materials(
    materials: Sequence[Mapping[str, Any]] | None,
    ctx: Mapping[str, float],
    *,
    line_qty: float = 1.0,
) -> list[LineItem]:
    """Evaluate materials[] from product JSON using the safe formula engine."""
    items: list[LineItem] = []
    base = dict(ctx)
    base.setdefault("qty", float(line_qty))

    for mat in materials or []:
        if mat.get("enabled") is False:
            continue
        local = dict(base)
        if "weightPerMeter" in mat:
            local["weightPerMeter"] = float(mat["weightPerMeter"])
        if "unitRate" in mat:
            local["unitRate"] = float(mat["unitRate"])

        qty_expr = mat.get("quantityFormula", mat.get("qtyFormula", mat.get("quantity", 1)))
        qty = eval_formula(qty_expr, local) * float(line_qty)

        length_expr = mat.get("lengthFormula", 0)
        length_val = eval_formula(length_expr, local) if length_expr not in (None, "", 0, "0") else 0.0

        weight_kg = None
        if mat.get("weightFormula"):
            wctx = dict(local)
            wctx["qty"] = qty
            wctx["quantity"] = qty
            if length_val:
                wctx["runningMeters"] = length_val if normalize_unit(mat.get("unit")) == "RM" else length_val / 1000.0
            weight_kg = eval_formula(mat["weightFormula"], wctx)
        else:
            # Default weight formula fallback — makes basic material weights compute
            # out-of-the-box from the preloaded baseline formulas (Part 1).
            weight_kg = _default_material_weight(mat, ctx, qty)

        unit = normalize_unit(mat.get("unit", "PC"))
        unit_rate = mat.get("unitRate")
        remarks = str(mat.get("remarks") or "")
        if weight_kg is not None:
            remarks = (remarks + f" · {weight_kg:.3f} kg").strip(" ·")

        # Store length in mm when unit implies linear measure in meters/feet formulas
        length_mm = 0.0
        if length_val:
            if unit == "RM":
                length_mm = length_val * 1000.0
            elif unit == "RFT":
                length_mm = length_val * 304.8
            else:
                length_mm = length_val

        items.append(
            LineItem(
                category=str(mat.get("category") or "material"),
                description=str(mat.get("name") or mat.get("id") or "material"),
                quantity=round(qty, 4),
                unit=unit,
                length_mm=round(length_mm, 2),
                remarks=remarks,
                unit_rate=float(unit_rate) if unit_rate is not None else None,
            )
        )
    return items


def _default_material_weight(
    mat: Mapping[str, Any], ctx: Mapping[str, float], qty: float
) -> float | None:
    """Compute a material weight from the preloaded baseline formulas when the
    material declares a materialType but no explicit weightFormula.

    Non-fatal: any issue simply returns None (no weight shown), never raises.
    """
    material_key = (
        mat.get("materialType")
        or mat.get("material")
        or mat.get("weightMaterial")
    )
    if not material_key:
        return None
    try:
        from WEOS.learning.material_formulas import (
            DEFAULT_WEIGHT_FORMULA_BY_MATERIAL,
            compute_weight as _fx_weight,
        )
    except Exception:
        return None

    key = str(material_key).strip().lower().replace(" ", "_")
    formula_key = DEFAULT_WEIGHT_FORMULA_BY_MATERIAL.get(key, key)

    def _num(*names: str) -> float | None:
        for n in names:
            if mat.get(n) is not None:
                try:
                    return float(mat[n])
                except (TypeError, ValueError):
                    pass
            if n in ctx:
                try:
                    return float(ctx[n])
                except (TypeError, ValueError):
                    pass
        return None

    params: dict[str, Any] = {"qty": qty}
    width = _num("widthMm", "width")
    height = _num("heightMm", "height")
    if width is not None:
        params["widthMm"] = width
    if height is not None:
        params["heightMm"] = height
    for src, dst in (
        ("thicknessMm", "thicknessMm"),
        ("thickness", "thicknessMm"),
        ("lengthMm", "lengthMm"),
        ("weightPerMeterKg", "weightPerMeterKg"),
        ("weightPerMeter", "weightPerMeterKg"),
        ("densityKgPerM3", "densityKgPerM3"),
        ("glass1Mm", "glass1Mm"),
        ("glass2Mm", "glass2Mm"),
        ("pvbMm", "pvbMm"),
    ):
        if mat.get(src) is not None:
            try:
                params[dst] = float(mat[src])
            except (TypeError, ValueError):
                pass
    try:
        res = _fx_weight(str(material_key), params=params, formula_key=formula_key)
    except Exception:
        return None
    if isinstance(res, dict) and res.get("ok"):
        return float(res.get("weightKg") or 0.0)
    return None


def materials_to_hardware_rules(materials: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Map library materials (hardware category) into legacy hardware rule shape."""
    out: list[dict[str, Any]] = []
    for mat in materials or []:
        cat = str(mat.get("category") or "").lower()
        if cat not in ("hardware", "accessory", "lock", "locks", "roller", "rollers", "connector", "connectors"):
            if mat.get("mapToHardware") is not True:
                continue
        unit = normalize_unit(mat.get("unit", "PC"))
        legacy_unit = {"PC": "pcs", "SET": "set", "PAIR": "pair", "BOX": "pack", "RM": "m"}.get(unit, unit.lower())
        rule: dict[str, Any] = {
            "part": mat.get("name") or mat.get("id"),
            "quantityFormula": mat.get("quantityFormula", mat.get("qtyFormula", "1")),
            "lengthFormula": mat.get("lengthFormula", "0"),
            "unit": legacy_unit,
            "unitRate": mat.get("unitRate", 0),
            "remarks": mat.get("remarks", ""),
            "category": mat.get("category"),
        }
        if mat.get("optionKey"):
            rule["optionKey"] = mat["optionKey"]
        if mat.get("variants"):
            rule["variants"] = mat["variants"]
        out.append(rule)
    return out
