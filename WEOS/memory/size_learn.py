"""Teach-by-upload + size-scale learning — suggest only, never auto-apply."""

from __future__ import annotations

from typing import Any

from WEOS.memory.schemas import MEM_ENGINEERING, empty_memory
from WEOS.memory.store import get_store, write_observation_as_learning


def _area_sqft(w_mm: float, h_mm: float) -> float:
    return (w_mm * h_mm) / 92903.04  # mm² → ft²


def _area_sqm(w_mm: float, h_mm: float) -> float:
    return (w_mm * h_mm) / 1_000_000.0


def _perimeter_m(w_mm: float, h_mm: float) -> float:
    return 2 * (w_mm + h_mm) / 1000.0


def compare_sizes(
    *,
    small: dict[str, Any],
    large: dict[str, Any],
    series_id: str | None = None,
    product_type: str | None = None,
    profiles_used: list[Any] | None = None,
    joint_types: list[Any] | None = None,
    design_why: str = "",
    material_rate_per_kg: float = 280.0,
    glass_rate_per_sqm: float = 450.0,
    save_observation: bool = True,
) -> dict[str, Any]:
    """
    Learn from same design at different sizes (e.g. 5×5 ft vs 3×4 ft).

    Returns material/cost deltas + scale rules as **suggestions** only.
    Stores Learning Memory observation + Engineering Memory draft for admin review.
    """
    sw = float(small.get("width_mm") or small.get("widthMm") or 0)
    sh = float(small.get("height_mm") or small.get("heightMm") or 0)
    lw = float(large.get("width_mm") or large.get("widthMm") or 0)
    lh = float(large.get("height_mm") or large.get("heightMm") or 0)
    if sw <= 0 or sh <= 0 or lw <= 0 or lh <= 0:
        return {"ok": False, "error": "Both small and large need width_mm and height_mm > 0"}

    s_area = _area_sqm(sw, sh)
    l_area = _area_sqm(lw, lh)
    s_perim = _perimeter_m(sw, sh)
    l_perim = _perimeter_m(lw, lh)
    area_ratio = l_area / s_area if s_area else None
    perim_ratio = l_perim / s_perim if s_perim else None

    # Heuristic material: profiles follow perimeter; glass follows area
    profile_kg_per_m = float(small.get("profileKgPerM") or large.get("profileKgPerM") or 0.85)
    s_profile_kg = s_perim * profile_kg_per_m
    l_profile_kg = l_perim * profile_kg_per_m
    glass_kg_per_sqm = float(small.get("glassKgPerSqm") or 12.5)
    s_glass_kg = s_area * glass_kg_per_sqm
    l_glass_kg = l_area * glass_kg_per_sqm

    s_mat_cost = s_profile_kg * material_rate_per_kg + s_area * glass_rate_per_sqm
    l_mat_cost = l_profile_kg * material_rate_per_kg + l_area * glass_rate_per_sqm

    delta = {
        "perimeter_m": round(l_perim - s_perim, 4),
        "area_sqm": round(l_area - s_area, 4),
        "profile_kg": round(l_profile_kg - s_profile_kg, 4),
        "glass_kg": round(l_glass_kg - s_glass_kg, 4),
        "material_cost_inr": round(l_mat_cost - s_mat_cost, 2),
        "area_ratio": round(area_ratio, 4) if area_ratio else None,
        "perimeter_ratio": round(perim_ratio, 4) if perim_ratio else None,
        "cost_ratio": round(l_mat_cost / s_mat_cost, 4) if s_mat_cost else None,
    }

    why = (
        design_why
        or "Profiles scale with perimeter (linear); glass/fill scale with area (quadratic). "
        "Larger openings therefore raise glass cost faster than frame cost."
    )

    scale_rule = {
        "id": f"scale_{series_id or 'generic'}",
        "seriesId": series_id,
        "productType": product_type,
        "rule": "profile_kg ≈ perimeter_m × kg_per_m; glass_sqm ≈ W×H/1e6",
        "profileScale": "perimeter",
        "glassScale": "area",
        "observed": {
            "small_ft": {"w": round(_area_sqft(sw, sh) and sw / 304.8, 2), "h": round(sh / 304.8, 2), "area_sqft": round(_area_sqft(sw, sh), 2)},
            "large_ft": {"w": round(lw / 304.8, 2), "h": round(lh / 304.8, 2), "area_sqft": round(_area_sqft(lw, lh), 2)},
            "delta": delta,
        },
        "suggestion": (
            f"When scaling this design, expect ~{delta['perimeter_ratio']}× profile length "
            f"and ~{delta['area_ratio']}× glass area; est. material Δ ₹{delta['material_cost_inr']}."
        ),
        "autoApply": False,
    }

    suggestion_text = (
        f"Size compare ({sw:g}×{sh:g} → {lw:g}×{lh:g} mm): "
        f"profile Δ {delta['profile_kg']} kg, glass Δ {delta['area_sqm']} sqm, "
        f"cost Δ ₹{delta['material_cost_inr']}. {why}"
    )

    learning = None
    eng_draft = None
    if save_observation:
        learning = write_observation_as_learning(
            observation_type="size_scale",
            summary=suggestion_text,
            evidence={
                "small": {"width_mm": sw, "height_mm": sh, "perimeter_m": s_perim, "area_sqm": s_area},
                "large": {"width_mm": lw, "height_mm": lh, "perimeter_m": l_perim, "area_sqm": l_area},
                "delta": delta,
                "profilesUsed": profiles_used or [],
                "jointTypes": joint_types or [],
                "designWhy": why,
                "scaleRule": scale_rule,
            },
            suggestion=scale_rule["suggestion"],
            target_memory_type=MEM_ENGINEERING,
            target_payload={"scaleRules": [scale_rule]},
            domain="engineering",
        )
        store = get_store()
        eng = empty_memory(MEM_ENGINEERING)
        eng.update(
            {
                "id": f"eng_scale_{series_id or 'generic'}_{int(sw)}x{int(sh)}_{int(lw)}x{int(lh)}",
                "title": f"Size-scale suggestion {series_id or ''}".strip(),
                "seriesId": series_id or "",
                "scaleRules": [scale_rule],
                "notes": why,
                "status": "pending_approval",
                "confidence": 70,
                "sourceKind": "learned",
                "source": {"kind": "size_compare", "quote": suggestion_text},
                "priority": 40,
            }
        )
        eng_draft = store.save(MEM_ENGINEERING, eng, as_approved=False)

    return {
        "ok": True,
        "small": {"width_mm": sw, "height_mm": sh, "perimeter_m": round(s_perim, 4), "area_sqm": round(s_area, 4), "material_cost_inr": round(s_mat_cost, 2)},
        "large": {"width_mm": lw, "height_mm": lh, "perimeter_m": round(l_perim, 4), "area_sqm": round(l_area, 4), "material_cost_inr": round(l_mat_cost, 2)},
        "delta": delta,
        "why": why,
        "scaleRule": scale_rule,
        "profilesUsed": profiles_used or [],
        "jointTypes": joint_types or [],
        "learning": learning,
        "engineeringDraft": eng_draft,
        "autoApplied": False,
        "message": "Suggestion only — admin must approve before Brain production use.",
        "production_modified": False,
    }


def suggest_for_size_change(
    *,
    base_width_mm: float,
    base_height_mm: float,
    new_width_mm: float,
    new_height_mm: float,
    series_id: str | None = None,
) -> dict[str, Any]:
    """Quick suggest deltas when user changes opening size (no persistence required)."""
    return compare_sizes(
        small={"width_mm": base_width_mm, "height_mm": base_height_mm},
        large={"width_mm": new_width_mm, "height_mm": new_height_mm},
        series_id=series_id,
        save_observation=True,
    )


def learn_from_upload(
    *,
    series_id: str | None = None,
    product_type: str | None = None,
    profiles_used: list[Any] | None = None,
    joint_types: list[Any] | None = None,
    design_why: str = "",
    sizes: list[dict[str, Any]] | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Teach-by-upload entry: record which profiles / joints / why for a design.
    If two+ sizes provided, also run size-scale compare.
    """
    obs = write_observation_as_learning(
        observation_type="design_upload",
        summary=f"Upload learn: {product_type or series_id or 'design'} — profiles={len(profiles_used or [])}",
        evidence={
            "seriesId": series_id,
            "productType": product_type,
            "profilesUsed": profiles_used or [],
            "jointTypes": joint_types or [],
            "designWhy": design_why,
            "sizes": sizes or [],
            "source": source or {},
        },
        suggestion=design_why or "Review uploaded design profiles/joints for KB",
        target_memory_type=MEM_ENGINEERING,
        target_payload={
            "profiles": profiles_used or [],
            "notes": design_why,
        },
        domain="engineering",
    )
    size_result = None
    if sizes and len(sizes) >= 2:
        # Pick smallest & largest by area
        scored = []
        for s in sizes:
            w = float(s.get("width_mm") or s.get("widthMm") or 0)
            h = float(s.get("height_mm") or s.get("heightMm") or 0)
            scored.append((w * h, s))
        scored.sort(key=lambda x: x[0])
        size_result = compare_sizes(
            small=scored[0][1],
            large=scored[-1][1],
            series_id=series_id,
            product_type=product_type,
            profiles_used=profiles_used,
            joint_types=joint_types,
            design_why=design_why,
            save_observation=True,
        )
    return {
        "ok": True,
        "learning": obs,
        "sizeCompare": size_result,
        "autoApplied": False,
        "production_modified": False,
    }
