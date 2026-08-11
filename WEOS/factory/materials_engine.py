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
        weight_meta: dict[str, Any] = {}
        if mat.get("weightFormula"):
            wctx = dict(local)
            wctx["qty"] = qty
            wctx["quantity"] = qty
            if length_val:
                wctx["runningMeters"] = length_val if normalize_unit(mat.get("unit")) == "RM" else length_val / 1000.0
            weight_kg = eval_formula(mat["weightFormula"], wctx)
            weight_meta = {
                "weightSource": "manually entered",
                "weightStatus": "known",
                "weightFormula": str(mat.get("weightFormula")),
                "sourceLabel": "Manual",
            }
        else:
            # Universal Weight Engine — catalogue → calculated → unknown (never guess)
            weight_kg, weight_meta = _universal_material_weight(mat, ctx, qty, length_val)

        unit = normalize_unit(mat.get("unit", "PC"))
        unit_rate = mat.get("unitRate")
        remarks = str(mat.get("remarks") or "")
        if weight_kg is not None:
            src = weight_meta.get("sourceLabel") or weight_meta.get("weightSource") or ""
            remarks = (remarks + f" · {weight_kg:.3f} kg [{src}]").strip(" ·")
        elif weight_meta.get("weightStatus") in ("missing", "needs_catalogue", "calculable"):
            remarks = (remarks + " · weight Missing").strip(" ·")

        # Store length in mm when unit implies linear measure in meters/feet formulas
        length_mm = 0.0
        if length_val:
            if unit == "RM":
                length_mm = length_val * 1000.0
            elif unit == "RFT":
                length_mm = length_val * 304.8
            else:
                length_mm = length_val

        # LineItem stays lean for pricing; weight transparency lives in remarks + optional attrs
        li = LineItem(
            category=str(mat.get("category") or "material"),
            description=str(mat.get("name") or mat.get("id") or "material"),
            quantity=round(qty, 4),
            unit=unit,
            length_mm=round(length_mm, 2),
            remarks=remarks,
            unit_rate=float(unit_rate) if unit_rate is not None else None,
        )
        # Attach weight metadata for BOM / agent (ignored by asdict consumers that only use known fields)
        for k, v in weight_meta.items():
            try:
                setattr(li, k, v)
            except Exception:
                pass
        if weight_kg is not None:
            try:
                setattr(li, "totalWeight", float(weight_kg))
                setattr(li, "weightPerUnit", float(weight_kg) / qty if qty else float(weight_kg))
            except Exception:
                pass
        items.append(li)
    return items


def _universal_material_weight(
    mat: Mapping[str, Any],
    ctx: Mapping[str, float],
    qty: float,
    length_val: float,
) -> tuple[float | None, dict[str, Any]]:
    """Delegate to Universal Weight Engine. Non-fatal on any error."""
    try:
        from WEOS.factory.weight_engine import calculate_material_weight
    except Exception:
        return None, {}

    material_key = str(
        mat.get("materialType")
        or mat.get("material")
        or mat.get("weightMaterial")
        or mat.get("category")
        or mat.get("name")
        or "unknown"
    )

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

    dims: dict[str, Any] = {}
    for key in (
        "widthMm",
        "heightMm",
        "thicknessMm",
        "lengthMm",
        "crossSectionAreaMm2",
        "areaM2",
        "layersMm",
        "makeup",
        "glass1Mm",
        "glass2Mm",
        "pvbMm",
    ):
        if mat.get(key) is not None:
            dims[key] = mat[key]
    w = _num("widthMm", "width")
    h = _num("heightMm", "height")
    if w is not None:
        dims.setdefault("widthMm", w)
    if h is not None:
        dims.setdefault("heightMm", h)
    thk = _num("thicknessMm", "thickness")
    if thk is not None:
        dims.setdefault("thicknessMm", thk)
    if length_val:
        unit = normalize_unit(mat.get("unit"))
        if unit == "RM":
            dims["lengthM"] = length_val
        elif unit == "RFT":
            dims["lengthRft"] = length_val
        else:
            dims["lengthMm"] = length_val

    try:
        res = calculate_material_weight(
            material_key,
            dimensions=dims,
            quantity=qty,
            density=_num("densityKgPerM3", "density"),
            unit=str(mat.get("unit") or "PC"),
            catalogue_weight=_num("catalogueWeight", "weightKgPerUnit"),
            weight_per_unit=_num("weightPerUnit", "weightKg"),
            weight_per_meter=_num("weightPerMeter", "weightPerMeterKg", "weightKgPerM", "weightKgPerMtr"),
            weight_source=str(mat.get("weightSource") or "") or None,
            waste_factor=_num("wasteFactor"),
            learned_weight=_num("learnedWeight"),
            learned_approved=bool(mat.get("learnedApproved")),
        )
    except Exception:
        return None, {}

    meta = {
        "weightSource": res.get("weightSource"),
        "weightStatus": res.get("weightStatus"),
        "weightFormula": res.get("formula"),
        "weightWhy": res.get("why"),
        "missingHints": res.get("missingHints"),
        "sourceLabel": res.get("sourceLabel"),
        "confidence": res.get("confidence"),
    }
    if res.get("ok") and res.get("totalWeight") is not None:
        return float(res["totalWeight"]), meta
    return None, meta


def _default_material_weight(
    mat: Mapping[str, Any], ctx: Mapping[str, float], qty: float
) -> float | None:
    """Compatibility shim — prefer Universal Weight Engine."""
    kg, _meta = _universal_material_weight(mat, ctx, qty, 0.0)
    return kg


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
