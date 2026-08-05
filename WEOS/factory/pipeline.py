"""Factory calculate pipeline — orchestrates engines → JobResult.

DXF export is NOT part of the default calculate path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from WEOS.factory.bom_engine import compute_bom
from WEOS.factory.brush_engine import compute_brush
from WEOS.factory.cut_list_engine import compute_cut_list
from WEOS.factory.formula import build_context
from WEOS.factory.geometry_engine import build_drawing, compute_two_track_layout, dim_style_from_profile
from WEOS.factory.glass_engine import compute_glass
from WEOS.factory.hardware_engine import compute_hardware
from WEOS.factory.job_types import JobResult
from WEOS.factory.product_loader import (
    apply_customer_options,
    apply_geometry_overrides,
    geometry_as_engine_dict,
    load_product,
)
from WEOS.factory.quotation_engine import compute_quotation
from WEOS.factory.track_rail_engine import compute_track_rail
from WEOS.factory.weight_engine import compute_weight


def generate_job(
    width: float,
    height: float,
    product_id: str | Path | None = "29mm_sliding",
    overrides: Mapping[str, Any] | None = None,
    *,
    glass: str | None = None,
    colour: str | None = None,
    handle: str | None = None,
) -> JobResult:
    product = load_product(product_id)
    product = apply_customer_options(product, glass=glass, colour=colour, handle=handle)
    product = apply_geometry_overrides(product, overrides)

    # Strip non-engineering meta from glass before engine (options catalogue)
    glass_rules = {k: v for k, v in (product.get("glass") or {}).items() if not str(k).startswith("_") and k != "options"}

    geom = product["geometry"]
    layout = compute_two_track_layout(width, height, geom)
    params = geometry_as_engine_dict(product)
    style = dim_style_from_profile(product.get("dimensioning") or {})
    drawing = build_drawing(
        layout,
        product_name=str(product.get("displayName", product.get("id", "opening"))),
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

    glass_items = compute_glass(layout, glass_rules, ctx)
    hardware = compute_hardware(product.get("hardware") or [], ctx)
    brush = compute_brush(product.get("brush") or {}, ctx)
    track_rail = compute_track_rail(product.get("trackRail") or {}, ctx)
    cut_list = compute_cut_list(product.get("cutList") or [], ctx, waste_factor=1.0)
    bom = compute_bom(
        cut_list=cut_list,
        glass=glass_items,
        hardware=hardware,
        brush=brush,
        track_rail=track_rail,
        extras=product.get("bomExtras"),
        ctx=ctx,
    )
    weight = compute_weight(product.get("weight") or {}, glass_items, ctx)
    quotation = compute_quotation(
        product.get("quotation") or {},
        weight=weight,
        glass=glass_items,
        hardware=hardware,
        brush=brush,
        track_rail=track_rail,
        hardware_rules=product.get("hardware") or [],
    )

    return JobResult(
        profile_id=str(product.get("id", "")),
        display_name=str(product.get("displayName", "")),
        width=float(width),
        height=float(height),
        geometry_params=params,
        layout_meta=layout.meta(),
        drawing=drawing,
        glass=glass_items,
        hardware=hardware,
        brush=brush,
        track_rail=track_rail,
        cut_list=cut_list,
        bom=bom,
        weight=weight,
        quotation=quotation,
        profile_path=str(product.get("_path", "")),
    )


# Keep old name for shims
def export_job_package(job: JobResult, out_dir: str | Path, *, basename: str | None = None, include_dxf: bool = False) -> dict[str, Path]:
    from WEOS.factory.json_export import export_json
    from WEOS.factory.svg_export import export_svg

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = basename or f"{job.profile_id}_{int(job.width)}x{int(job.height)}"
    paths: dict[str, Path] = {
        "svg": export_svg(job.drawing, out_dir / f"{base}.svg"),
        "json": export_json(job, out_dir / f"{base}.json"),
    }
    if include_dxf:
        from WEOS.factory.dxf_export import export_dxf

        paths["dxf"] = export_dxf(job.drawing, out_dir / f"{base}.dxf")
    return paths
