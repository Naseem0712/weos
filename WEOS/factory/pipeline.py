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
from WEOS.factory.materials_engine import compute_materials
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
    partitions: Any = None,
    mesh: bool = False,
    track_count: float | None = None,
    section_series: str | None = None,
    glass_count: int | None = None,
    mesh_count: int | None = None,
    opening: str | None = None,
    fixed_shutters: Any = None,
    system: str | None = None,
    fold_left: int | None = None,
    fold_right: int | None = None,
    section_sizes: Mapping[str, Any] | None = None,
    handle_finish: str | None = None,
) -> JobResult:
    from WEOS.factory.layout_options import resolve_mesh_track, resolve_shutter_config

    product = load_product(product_id)
    product = apply_customer_options(product, glass=glass, colour=colour, handle=handle)
    product = apply_geometry_overrides(product, overrides)

    # Strip non-engineering meta from glass before engine (options catalogue)
    glass_rules = {k: v for k, v in (product.get("glass") or {}).items() if not str(k).startswith("_") and k != "options"}

    geom = dict(product["geometry"])
    series_doc = None
    if section_series:
        try:
            from WEOS.factory.section_catalogue import get_series

            series_doc = get_series(str(section_series))
        except Exception:
            series_doc = None
    mesh_res = resolve_mesh_track(
        mesh=bool(mesh),
        track_count=track_count if track_count is not None else float(geom.get("trackCount") or 2),
        series=series_doc,
    )
    geom["trackCount"] = mesh_res["trackCount"]

    sys_kind = str(system or "sliding").strip().lower()
    is_bifold = sys_kind in ("bifold", "fold", "fold_sliding", "fold_and_sliding")

    if is_bifold:
        fl = int(fold_left) if fold_left is not None else 2
        fr = int(fold_right) if fold_right is not None else 1
        total_leaves = max(fl + fr, 1)
        shutter_cfg = {
            "glassCount": total_leaves,
            "meshCount": 0,
            "opening": "center",
            "fixedShutters": [],
        }
    else:
        shutter_cfg = resolve_shutter_config(
            glass_count=glass_count,
            mesh_count=mesh_count,
            mesh=bool(mesh_res.get("mesh")),
            track_count=float(mesh_res["trackCount"]),
            fixed_shutters=fixed_shutters,
            opening=opening,
            default_glass=int(float(geom.get("shutterCount") or 2)),
        )

    layout = compute_two_track_layout(
        width,
        height,
        geom,
        partitions=partitions,
        mesh=bool(mesh_res.get("mesh")) and not is_bifold,
        track_count=float(mesh_res["trackCount"]),
        glass_count=shutter_cfg["glassCount"],
        mesh_count=shutter_cfg["meshCount"],
        opening=shutter_cfg["opening"],
        fixed_shutters=shutter_cfg["fixedShutters"],
        system="bifold" if is_bifold else "sliding",
        fold_left=fold_left,
        fold_right=fold_right,
        section_sizes=section_sizes,
    )
    params = geometry_as_engine_dict(product)
    params["track_count"] = float(mesh_res["trackCount"])
    params["shutter_count"] = float(layout.glass_count)
    style = dim_style_from_profile(product.get("dimensioning") or {})
    drawing = build_drawing(
        layout,
        product_name=str(product.get("displayName", product.get("id", "opening"))),
        parameters=params,
        style=style,
    )
    # Stash mesh/track resolution on drawing metadata for PDF/preview consumers
    meta = dict(drawing.metadata or {})
    meta["mesh"] = (bool(mesh_res.get("mesh")) or shutter_cfg["meshCount"] > 0) and not is_bifold
    meta["track_count"] = float(mesh_res["trackCount"])
    meta["mesh_track"] = mesh_res
    meta["glass_count"] = int(layout.glass_count)
    meta["mesh_count"] = int(layout.mesh_count)
    meta["opening"] = layout.opening
    meta["system"] = layout.system
    if handle_finish:
        meta["handle_finish"] = str(handle_finish)
    elif colour and ("black" in str(colour).lower() or "dark" in str(colour).lower()):
        meta["handle_finish"] = "black"
    else:
        meta["handle_finish"] = "silver"
    drawing.metadata = meta

    # Glass / hardware quantities follow the actual glass shutter / leaf count
    geom["shutterCount"] = float(layout.glass_count)

    extras_ctx = {
        "leftShutterWidth": layout.left_shutter_width,
        "rightShutterWidth": layout.right_shutter_width,
        "leftGlassWidth": layout.left_glass_width,
        "rightGlassWidth": layout.right_glass_width,
        "glassHeight": layout.glass_height,
        "shutterInset": layout.shutter_inset,
        "interlockLeft": layout.interlock_left,
        "interlockRight": layout.interlock_right,
        "trackCount": float(mesh_res["trackCount"]),
    }
    ctx = build_context(width, height, geom, extras=extras_ctx)

    glass_items = compute_glass(layout, glass_rules, ctx)
    hardware = compute_hardware(product.get("hardware") or [], ctx)
    brush = compute_brush(product.get("brush") or {}, ctx)
    track_rail = compute_track_rail(product.get("trackRail") or {}, ctx)
    cut_list = compute_cut_list(product.get("cutList") or [], ctx, waste_factor=1.0)
    # Product Library materials[] — formula-driven; keeps 29mm hardware engines intact
    materials = compute_materials(product.get("materials") or [], ctx, line_qty=1.0)
    bom = compute_bom(
        cut_list=cut_list,
        glass=glass_items,
        hardware=hardware,
        brush=brush,
        track_rail=track_rail,
        extras=product.get("bomExtras"),
        ctx=ctx,
    )
    # Append library materials into BOM when present
    if materials:
        bom = list(bom) + list(materials)
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
        materials=materials,
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
