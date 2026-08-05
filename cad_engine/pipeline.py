"""
Pipeline — orchestrate all manufacturing modules for one opening.

User inputs: width, height, profile series (+ optional overrides).
Output: JobResult with drawing, glass, BOM, weight, quotation, …
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from cad_engine.bom_engine import compute_bom
from cad_engine.brush_engine import compute_brush
from cad_engine.cut_list_engine import compute_cut_list
from cad_engine.formula import build_context
from cad_engine.geometry_engine import build_drawing, compute_two_track_layout, dim_style_from_profile
from cad_engine.glass_engine import compute_glass
from cad_engine.hardware_engine import compute_hardware
from cad_engine.job_types import JobResult
from cad_engine.profile_loader import (
    apply_geometry_overrides,
    geometry_as_engine_dict,
    load_profile,
)
from cad_engine.quotation_engine import compute_quotation
from cad_engine.track_rail_engine import compute_track_rail
from cad_engine.weight_engine import compute_weight


def generate_job(
    width: float,
    height: float,
    profile_id: str | Path | None = "29mm_sliding",
    overrides: Mapping[str, Any] | None = None,
) -> JobResult:
    profile = load_profile(profile_id)
    profile = apply_geometry_overrides(profile, overrides)

    geom = profile["geometry"]
    layout = compute_two_track_layout(width, height, geom)
    params = geometry_as_engine_dict(profile)
    style = dim_style_from_profile(profile.get("dimensioning") or {})
    drawing = build_drawing(
        layout,
        product_name=str(profile.get("displayName", profile.get("id", "opening"))),
        parameters=params,
        style=style,
    )

    extras_ctx = {
        "leftShutterWidth": layout.left_shutter_width,
        "rightShutterWidth": layout.right_shutter_width,
        "leftGlassWidth": layout.left_glass_width,
        "rightGlassWidth": layout.right_glass_width,
        "glassHeight": layout.glass_height,
        "shutterInset": layout.shutter_inset,
        "interlockLeft": layout.interlock_left,
        "interlockRight": layout.interlock_right,
    }
    ctx = build_context(width, height, geom, extras=extras_ctx)

    glass = compute_glass(layout, profile.get("glass") or {}, ctx)
    hardware = compute_hardware(profile.get("hardware") or [], ctx)
    brush = compute_brush(profile.get("brush") or {}, ctx)
    track_rail = compute_track_rail(profile.get("trackRail") or {}, ctx)
    waste = float((profile.get("weight") or {}).get("wasteFactor", 1.0))
    # Cut list uses waste on aluminium stock optionally — apply only if rules say; keep 1.0 for exact fab lengths
    cut_list = compute_cut_list(profile.get("cutList") or [], ctx, waste_factor=1.0)
    bom = compute_bom(
        cut_list=cut_list,
        glass=glass,
        hardware=hardware,
        brush=brush,
        track_rail=track_rail,
        extras=profile.get("bomExtras"),
        ctx=ctx,
    )
    weight = compute_weight(profile.get("weight") or {}, glass, ctx)
    quotation = compute_quotation(
        profile.get("quotation") or {},
        weight=weight,
        glass=glass,
        hardware=hardware,
        brush=brush,
        track_rail=track_rail,
        hardware_rules=profile.get("hardware") or [],
    )

    return JobResult(
        profile_id=str(profile.get("id", "")),
        display_name=str(profile.get("displayName", "")),
        width=float(width),
        height=float(height),
        geometry_params=params,
        layout_meta=layout.meta(),
        drawing=drawing,
        glass=glass,
        hardware=hardware,
        brush=brush,
        track_rail=track_rail,
        cut_list=cut_list,
        bom=bom,
        weight=weight,
        quotation=quotation,
        profile_path=str(profile.get("_path", "")),
    )


def export_job_package(job: JobResult, out_dir: str | Path, *, basename: str | None = None) -> dict[str, Path]:
    """Write DXF + SVG + JSON manufacturing package."""
    from cad_engine.dxf_export import export_dxf
    from cad_engine.json_export import export_json
    from cad_engine.svg_export import export_svg

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = basename or f"{job.profile_id}_{int(job.width)}x{int(job.height)}"
    paths = {
        "dxf": export_dxf(job.drawing, out_dir / f"{base}.dxf"),
        "svg": export_svg(job.drawing, out_dir / f"{base}.svg"),
        "json": export_json(job, out_dir / f"{base}.json"),
    }
    return paths
