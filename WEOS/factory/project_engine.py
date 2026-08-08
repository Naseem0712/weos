"""Project engine — multi-line cart calculate + combine + optimize."""

from __future__ import annotations

import copy
import logging
import uuid
from typing import Any, Mapping

from WEOS.factory.optimize_engine import CutPiece, GlassPiece, optimize_project_materials

_log = logging.getLogger("weos.project_engine")
from WEOS.factory.pipeline import generate_job
from WEOS.factory.product_loader import load_product
from WEOS.factory.project_store import new_quotation_id
from WEOS.factory.svg_export import layout_summary_for_job, render_svg_string


def _stub_line_result(line: Mapping[str, Any], product: Mapping[str, Any]) -> dict[str, Any]:
    qty = int(line.get("qty") or line.get("quantity") or 1)
    quote = product.get("quotation") or {}
    rate = float(quote.get("manualRatePerOpening", 0))
    labour = float(quote.get("labourPerOpening", 0))
    markup = float(quote.get("markupPercent", 15))
    gst = float(quote.get("gstPercent", 18))
    unit = rate + labour
    sub = unit * qty
    after_markup = sub * (1 + markup / 100.0)
    total = after_markup * (1 + gst / 100.0)
    return {
        "lineId": line.get("lineId") or uuid.uuid4().hex[:8],
        "product": product.get("id"),
        "displayName": product.get("displayName"),
        "category": product.get("category", "Windows"),
        "status": "stub",
        "width": float(line.get("width", 0)),
        "height": float(line.get("height", 0)),
        "qty": qty,
        "glass": [],
        "hardware": [],
        "brush": {"totalMeters": 0, "pieces": []},
        "trackRail": [],
        "cutList": [],
        "bom": [],
        "weight": {"aluminiumKg": 0, "glassKg": 0, "hardwareKg": 0, "totalKg": 0},
        "price": {
            "currency": quote.get("currency", "INR"),
            "unitRate": round(unit, 2),
            "subtotal": round(sub, 2),
            "markupPercent": markup,
            "gstPercent": gst,
            "total": round(total, 2),
        },
        "preview": {"svg": None},
        "note": "Stub product — manual rate until engines are wired",
    }


def _error_line_result(line: Mapping[str, Any], error: str = "") -> dict[str, Any]:
    """Minimal, render-safe line result used when a single line fails to calculate.

    Keeps the row visible in the PDF (size / qty / an error note) instead of
    letting one bad line blank the whole quotation.
    """
    def _num(val: Any) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    try:
        qty = int(float(line.get("qty") or line.get("quantity") or 1))
    except (TypeError, ValueError):
        qty = 1
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    merged_opts = {
        "glass": line.get("glass"),
        "colour": line.get("colour"),
        "handle": line.get("handle"),
    }
    if isinstance(opts, Mapping):
        merged_opts.update({k: v for k, v in opts.items()})
    return {
        "lineId": line.get("lineId") or uuid.uuid4().hex[:8],
        "product": line.get("product") or line.get("productId"),
        "displayName": line.get("displayName") or line.get("product") or "Item",
        "category": line.get("category") or "Windows",
        "status": "error",
        "error": str(error or "calculation failed"),
        "width": _num(line.get("width")),
        "height": _num(line.get("height")),
        "qty": qty,
        "sectionSeries": line.get("sectionSeries"),
        "partitions": [],
        "mesh": False,
        "trackCount": 2.0,
        "options": merged_opts,
        "layout": {},
        "glass": [],
        "hardware": [],
        "materials": [],
        "brush": {"totalMeters": 0},
        "trackRail": [],
        "cutList": [],
        "bom": [],
        "weight": {"aluminiumKg": 0, "glassKg": 0, "hardwareKg": 0, "totalKg": 0},
        "price": {"currency": "INR", "unitTotal": 0, "subtotal": 0, "total": 0},
        "preview": {"svg": None},
    }


def calculate_line(line: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate one cart line (product × size × qty × options)."""
    from WEOS.factory.live_pricing import apply_selling_to_line_result

    from WEOS.factory.layout_options import line_layout_options

    product_id = str(line.get("product") or line.get("productId") or "29mm_sliding")
    product = load_product(product_id, strict=False)
    qty = int(line.get("qty") or line.get("quantity") or 1)
    width = float(line.get("width", 0))
    height = float(line.get("height", 0))
    lo = line_layout_options(line)

    if product.get("_stub") or product.get("status") == "stub":
        return apply_selling_to_line_result(_stub_line_result(line, product), line)

    job = generate_job(
        width,
        height,
        product_id,
        glass=line.get("glass"),
        colour=line.get("colour"),
        handle=line.get("handle"),
        partitions=lo.get("partitions"),
        mesh=bool(lo.get("mesh")),
        track_count=lo.get("trackCount"),
        section_series=lo.get("sectionSeries") or line.get("sectionSeries"),
    )
    quote = job.quotation.as_dict() if job.quotation else {}
    weight = job.weight.as_dict() if job.weight else {}
    colour = (line.get("colour") or "white")
    grid = line.get("grid") or (line.get("options") or {}).get("grid") or (line.get("options") or {}).get("grille")
    svg = render_svg_string(
        job.drawing,
        colour=str(colour).lower().replace(" ", "_"),
        annotations=True,
        grid=grid,
        include_plan=True,
    )
    layout = layout_summary_for_job(width=width, height=height, layout_meta=job.layout_meta)

    # Scale commercial totals by qty
    unit_total = float(quote.get("total", 0))
    unit_sub = float(quote.get("subtotal", 0))

    brush_m = 0.0
    for b in job.brush:
        if b.description.endswith("TOTAL"):
            brush_m = b.length_mm / 1000.0
            break

    options = {
        "glass": line.get("glass"),
        "colour": line.get("colour"),
        "handle": line.get("handle"),
        "partitions": lo.get("partitions") or [],
        "mesh": bool(lo.get("mesh")),
        "trackCount": float((job.layout_meta or {}).get("track_count") or lo.get("trackCount") or 2),
    }
    if grid:
        options["grid"] = grid
    if line.get("sectionSeries"):
        options["sectionSeries"] = line.get("sectionSeries")

    result_base = {
        "lineId": line.get("lineId") or uuid.uuid4().hex[:8],
        "product": job.profile_id,
        "displayName": job.display_name,
        "category": product.get("category", "Windows"),
        "status": "active",
        "width": width,
        "height": height,
        "qty": qty,
        "sectionSeries": line.get("sectionSeries"),
        "partitions": lo.get("partitions") or [],
        "mesh": bool(lo.get("mesh")),
        "trackCount": options["trackCount"],
        "options": options,
        "layout": layout,
        "glass": [
            {
                "name": g.name,
                "qty": g.quantity * qty,
                "width": round(g.width_mm, 1),
                "height": round(g.height_mm, 1),
                "thicknessMm": g.thickness_mm,
                "areaM2": round(g.area_m2 * qty, 4),
                "weightKg": round(g.weight_kg * qty, 3),
            }
            for g in job.glass
        ],
        "hardware": [
            {
                "name": h.description,
                "qty": h.quantity * qty,
                "unit": h.unit,
                "lengthMm": h.length_mm,
                "unitRate": h.unit_rate,
            }
            for h in job.hardware
        ],
        "materials": [
            {
                **m.as_dict(),
                "quantity": m.quantity * qty,
            }
            for m in (job.materials or [])
        ],
        "brush": {"totalMeters": round(brush_m * qty, 3)},
        "trackRail": [
            {
                "name": t.description,
                "qty": t.quantity * qty,
                "lengthMm": t.length_mm,
                "unit": t.unit,
            }
            for t in job.track_rail
        ],
        "cutList": [
            {
                **c.as_dict(),
                "quantity": c.quantity * qty,
                "total_length_mm": c.length_mm * c.quantity * qty,
            }
            for c in job.cut_list
        ],
        "bom": [{**b.as_dict(), "quantity": b.quantity * qty} for b in job.bom],
        "weight": {
            "aluminiumKg": round(weight.get("aluminium_kg", 0) * qty, 3),
            "glassKg": round(weight.get("glass_kg", 0) * qty, 3),
            "hardwareKg": round(weight.get("hardware_kg", 0) * qty, 3),
            "totalKg": round(weight.get("total_kg", 0) * qty, 3),
        },
        "price": {
            "currency": quote.get("currency", "INR"),
            "unitTotal": round(unit_total, 2),
            "subtotal": round(unit_sub * qty, 2),
            "markupPercent": quote.get("markup_percent", 0),
            "gstPercent": quote.get("gst_percent", 0),
            "total": round(unit_total * qty, 2),
            "lines": quote.get("lines"),
        },
        "quotationDetail": quote,
        "preview": {"svg": svg},
        "layoutMeta": dict(job.layout_meta or {}),
        "_rawCutList": [{"length_mm": c.length_mm, "quantity": c.quantity * qty, "profile": c.profile} for c in job.cut_list],
        "_rawGlass": [
            {"width_mm": g.width_mm, "height_mm": g.height_mm, "qty": g.quantity * qty, "thickness_mm": g.thickness_mm, "name": g.name}
            for g in job.glass
        ],
    }
    return apply_selling_to_line_result(result_base, line)


def combine_lines(line_results: list[dict[str, Any]]) -> dict[str, Any]:
    total_items = sum(int(r.get("qty", 0)) for r in line_results)
    currency = "INR"
    grand = 0.0
    commercial_grand = 0.0
    has_commercial = False
    alu = glass_kg = hw_kg = total_kg = 0.0
    brush_m = 0.0
    glass_pcs = 0
    glass_area = 0.0
    by_category: dict[str, float] = {}
    hardware_roll: dict[str, float] = {}
    track_roll: list[dict[str, Any]] = []

    for r in line_results:
        currency = (r.get("price") or {}).get("currency", currency)
        total = float((r.get("price") or {}).get("total", 0))
        grand += total
        if r.get("commercialTotal") is not None and r.get("selling"):
            has_commercial = True
            commercial_grand += float(r.get("commercialTotal") or 0)
        else:
            commercial_grand += total
        cat = r.get("category") or "Windows"
        by_category[cat] = by_category.get(cat, 0.0) + float(r.get("commercialTotal") or total)
        w = r.get("weight") or {}
        alu += float(w.get("aluminiumKg") or 0)
        glass_kg += float(w.get("glassKg") or 0)
        hw_kg += float(w.get("hardwareKg") or 0)
        total_kg += float(w.get("totalKg") or 0)
        brush_m += float((r.get("brush") or {}).get("totalMeters") or 0)
        for g in r.get("glass") or []:
            glass_pcs += int(g.get("qty") or 0)
            glass_area += float(g.get("areaM2") or 0)
        for h in r.get("hardware") or []:
            key = str(h.get("name"))
            hardware_roll[key] = hardware_roll.get(key, 0.0) + float(h.get("qty") or 0)
        for t in r.get("trackRail") or []:
            track_roll.append(t)

    return {
        "totalItems": total_items,
        "lineCount": len(line_results),
        "currency": currency,
        "grandTotal": round(grand, 2),
        "commercialGrandTotal": round(commercial_grand, 2) if has_commercial else round(grand, 2),
        "hasSellingRates": has_commercial,
        "categoryTotals": {k: round(v, 2) for k, v in by_category.items()},
        "weight": {
            "aluminiumKg": round(alu, 3),
            "glassKg": round(glass_kg, 3),
            "hardwareKg": round(hw_kg, 3),
            "totalKg": round(total_kg, 3),
        },
        "glass": {"pieces": glass_pcs, "areaM2": round(glass_area, 4)},
        "brushMeters": round(brush_m, 3),
        "hardwareRolled": [{"name": k, "qty": v} for k, v in sorted(hardware_roll.items())],
        "trackRail": track_roll,
    }


def calculate_project(project: Mapping[str, Any], *, optimize: bool = True) -> dict[str, Any]:
    """Full project calculation: each line → combine → material optimization."""
    lines = project.get("lines") or []
    results: list[dict[str, Any]] = []
    for idx, ln in enumerate(lines):
        try:
            results.append(calculate_line(ln))
        except Exception as exc:
            # One bad line must NEVER blank the whole quotation/PDF — log the real
            # traceback and keep the row with an error note so the rest render.
            _log.exception(
                "calculate_line failed for line %d (product=%s); using error stub",
                idx,
                (ln or {}).get("product") if isinstance(ln, Mapping) else None,
            )
            results.append(_error_line_result(ln if isinstance(ln, Mapping) else {}, error=str(exc)))
    combined = combine_lines(results)

    cut_pieces: list[CutPiece] = []
    glass_pieces: list[GlassPiece] = []
    for r in results:
        for c in r.get("_rawCutList") or []:
            cut_pieces.append(CutPiece(length_mm=float(c["length_mm"]), label=str(c.get("profile", "")), qty=int(c["quantity"])))
        for g in r.get("_rawGlass") or []:
            glass_pieces.append(
                GlassPiece(
                    width_mm=float(g["width_mm"]),
                    height_mm=float(g["height_mm"]),
                    label=str(g.get("name", "")),
                    qty=int(g["qty"]),
                    thickness_mm=float(g.get("thickness_mm", 5)),
                )
            )

    optimization = None
    if optimize and (cut_pieces or glass_pieces):
        optimization = optimize_project_materials(cut_pieces=cut_pieces, glass_pieces=glass_pieces)

    # strip internal keys from line results for API
    public_lines = []
    for r in results:
        clean = {k: v for k, v in r.items() if not str(k).startswith("_")}
        public_lines.append(clean)

    quotation_id = project.get("quotationId") or new_quotation_id()
    price_total = combined.get("commercialGrandTotal", combined["grandTotal"])
    return {
        "projectId": project.get("projectId"),
        "name": project.get("name"),
        "customer": project.get("customer"),
        "quotationId": quotation_id,
        "lines": public_lines,
        "combined": combined,
        "optimization": optimization,
        "price": {
            "currency": combined["currency"],
            "total": price_total,
            "costTotal": combined["grandTotal"],
            "commercialTotal": combined.get("commercialGrandTotal", combined["grandTotal"]),
            "hasSellingRates": combined.get("hasSellingRates", False),
            "categoryTotals": combined["categoryTotals"],
        },
    }
