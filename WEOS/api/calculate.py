"""API calculate service — single-line JSON response (WEOS)."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from WEOS.factory.image_engine import svg_to_png_data_url
from WEOS.factory.pdf_engine import build_quote_pdf_bytes, export_pdf
from WEOS.factory.pipeline import generate_job
from WEOS.factory.product_loader import list_products, load_product
from WEOS.factory.svg_export import render_svg_string
from WEOS.paths import PACKAGE_ROOT, output_dir

WEOS_ROOT = PACKAGE_ROOT
OUTPUT_DIR = output_dir()


def _brush_summary(brush_items: list) -> dict[str, Any]:
    total_m = 0.0
    pieces = []
    for b in brush_items:
        d = b.as_dict() if hasattr(b, "as_dict") else b
        if str(d.get("description", "")).endswith("TOTAL"):
            total_m = float(d.get("length_mm", 0)) / 1000.0
        else:
            pieces.append(
                {
                    "name": d.get("description"),
                    "qty": d.get("quantity"),
                    "lengthMm": d.get("length_mm"),
                    "unit": d.get("unit"),
                }
            )
    return {"totalMeters": round(total_m, 3), "pieces": pieces}


def build_api_response(
    *,
    product: str = "29mm_sliding",
    width: float,
    height: float,
    glass: str | None = "5mm_clear",
    colour: str | None = "white",
    handle: str | None = "standard",
    include_quote: bool = True,
    include_pdf: bool = True,
    include_svg: bool = True,
    include_png: bool = True,
    include_json: bool = True,
    include_bom: bool = True,
    include_dxf: bool = False,
    persist: bool = True,
) -> dict[str, Any]:
    """Single opening calculate — DXF defaults OFF."""
    job = generate_job(
        width,
        height,
        product,
        glass=glass,
        colour=colour,
        handle=handle,
    )

    colour_id = (colour or "white").lower().replace(" ", "_")
    svg = render_svg_string(job.drawing, colour=colour_id) if include_svg or include_png or include_pdf else ""

    png_data_url = None
    if include_png and svg:
        png_data_url = svg_to_png_data_url(svg, scale=0.5)

    quote = job.quotation.as_dict() if job.quotation else None
    weight = job.weight.as_dict() if job.weight else None

    price_block = None
    if include_quote and quote:
        price_block = {
            "currency": quote["currency"],
            "subtotal": quote["subtotal"],
            "markupPercent": quote["markup_percent"],
            "markupAmount": quote.get("markup_amount", 0),
            "afterMarkup": quote.get("after_markup", quote["subtotal"]),
            "gstPercent": quote.get("gst_percent", 0),
            "gstAmount": quote.get("gst_amount", 0),
            "total": quote["total"],
        }

    job_id = f"{job.profile_id}_{int(width)}x{int(height)}_{uuid.uuid4().hex[:8]}"
    downloads: dict[str, str | None] = {"pdf": None, "image": None, "json": None, "svg": None, "dxf": None}

    if persist:
        out = OUTPUT_DIR / job_id
        out.mkdir(parents=True, exist_ok=True)
        if include_svg and svg:
            svg_path = out / "preview.svg"
            svg_path.write_text(svg, encoding="utf-8")
            downloads["svg"] = str(svg_path.as_posix())
        if include_png and png_data_url:
            from WEOS.factory.image_engine import export_png_from_svg

            png_path = export_png_from_svg(svg, out / "preview.png")
            downloads["image"] = str(png_path.as_posix()) if png_path else ("data-url" if png_data_url else None)
        if include_json:
            from WEOS.factory.json_export import export_json

            jp = export_json(job, out / "manufacturing.json")
            downloads["json"] = str(jp.as_posix())
        if include_dxf:
            from WEOS.factory.dxf_export import export_dxf

            downloads["dxf"] = str(export_dxf(job.drawing, out / "factory.dxf").as_posix())

    response: dict[str, Any] = {
        "jobId": job_id,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "product": {"id": job.profile_id, "displayName": job.display_name},
        "width": job.width,
        "height": job.height,
        "options": {
            "glass": glass,
            "colour": colour_id,
            "handle": (handle or "standard").lower().replace(" ", "_"),
        },
        "preview": {"svg": svg if include_svg else None, "png": png_data_url if include_png else None},
        "price": price_block,
        "weight": {
            "aluminiumKg": round(weight["aluminium_kg"], 3) if weight else None,
            "glassKg": round(weight["glass_kg"], 3) if weight else None,
            "hardwareKg": round(weight["hardware_kg"], 3) if weight else None,
            "totalKg": round(weight["total_kg"], 3) if weight else None,
        }
        if weight
        else None,
        "glass": [
            {
                "name": g.name,
                "qty": g.quantity,
                "width": round(g.width_mm, 1),
                "height": round(g.height_mm, 1),
                "thicknessMm": g.thickness_mm,
                "areaM2": round(g.area_m2, 4),
                "weightKg": round(g.weight_kg, 3),
            }
            for g in job.glass
        ],
        "hardware": [
            {
                "name": h.description,
                "qty": h.quantity,
                "unit": h.unit,
                "lengthMm": h.length_mm,
                "unitRate": h.unit_rate,
                "remarks": h.remarks,
            }
            for h in job.hardware
        ],
        "brush": _brush_summary(job.brush),
        "trackRail": [
            {"name": t.description, "qty": t.quantity, "lengthMm": t.length_mm, "unit": t.unit}
            for t in job.track_rail
        ],
        "cutList": [c.as_dict() for c in job.cut_list] if include_bom else None,
        "bom": [b.as_dict() for b in job.bom] if include_bom else None,
        "quotation": quote if include_quote else None,
        "downloads": downloads,
        "flags": {
            "includeQuote": include_quote,
            "includePdf": include_pdf,
            "includeSvg": include_svg,
            "includePng": include_png,
            "includeJson": include_json,
            "includeBom": include_bom,
            "includeDxf": include_dxf,
        },
    }

    if include_pdf and persist:
        out = OUTPUT_DIR / job_id
        pdf_path = export_pdf(response, out / "quotation.pdf", kind="customer")
        downloads["pdf"] = str(pdf_path.as_posix())
        response["downloads"] = downloads
        response["pdfBase64"] = base64.b64encode(build_quote_pdf_bytes(response)).decode("ascii")
    elif include_pdf:
        response["pdfBase64"] = base64.b64encode(build_quote_pdf_bytes(response)).decode("ascii")

    return response


def products_catalog() -> list[dict[str, Any]]:
    items = []
    for pid, name in list_products():
        try:
            p = load_product(pid, strict=False)
            pricing = p.get("pricing") or {}
            items.append(
                {
                    "id": pid,
                    "displayName": name,
                    "status": p.get("status", "active"),
                    "category": p.get("category", "Windows"),
                    "tagline": p.get("tagline"),
                    "description": p.get("description"),
                    "heroImage": p.get("heroImage"),
                    "gallery": p.get("gallery") or [],
                    "specifications": p.get("specifications") or {},
                    "warranty": p.get("warranty"),
                    "colours": pricing.get("colours") or [],
                    "handles": pricing.get("handles") or [],
                    "hardwareOptions": pricing.get("hardwareOptions") or [],
                    "glassOptions": (p.get("glass") or {}).get("options") or [],
                    "defaults": pricing.get("defaultOptions") or {},
                    "catalogue": p.get("catalogue") or {},
                    "sectionSeries": p.get("sectionSeries"),
                    "manufacturingReady": not (p.get("_stub") or p.get("status") == "stub"),
                }
            )
        except Exception as exc:
            items.append({"id": pid, "displayName": name, "error": str(exc)})
    return items


def get_product_detail(product_id: str) -> dict[str, Any]:
    """Full catalogue + engineering rules summary for Product Details UI."""
    p = load_product(product_id, strict=False)
    pricing = p.get("pricing") or {}
    geom = p.get("geometry") or {}
    glass = p.get("glass") or {}
    specs = dict(p.get("specifications") or {})
    # Merge live geometry into specs display (rules JSON is source of truth)
    if geom:
        specs.setdefault("trackWidthMm", geom.get("trackWidth"))
        specs.setdefault("frameWidthMm", geom.get("frameWidth"))
        specs.setdefault("interlockWidthMm", geom.get("interlockWidth"))
        specs.setdefault("overlapMm", geom.get("overlap"))
        specs.setdefault("glassClipMm", geom.get("glassClip"))
        specs.setdefault("trackCount", geom.get("trackCount"))
        specs.setdefault("shutterCount", geom.get("shutterCount"))
    if glass:
        specs.setdefault("glassThicknessMm", glass.get("thicknessMm"))
        specs.setdefault("glassDensityKgPerM3", glass.get("densityKgPerM3"))
    return {
        "id": p.get("id", product_id),
        "displayName": p.get("displayName"),
        "category": p.get("category", "Windows"),
        "status": p.get("status", "active"),
        "tagline": p.get("tagline"),
        "description": p.get("description"),
        "warranty": p.get("warranty"),
        "heroImage": p.get("heroImage"),
        "gallery": p.get("gallery") or [],
        "sectionDrawings": p.get("sectionDrawings") or [],
        "specifications": specs,
        "colours": pricing.get("colours") or [],
        "handles": pricing.get("handles") or [],
        "hardwareOptions": pricing.get("hardwareOptions") or [],
        "glassOptions": glass.get("options") or [],
        "defaults": pricing.get("defaultOptions") or {},
        "quotation": p.get("quotation") or {},
        "manufacturingReady": not (p.get("_stub") or p.get("status") == "stub"),
        "rulesPath": p.get("_path"),
        "geometry": geom,
        "provenance": p.get("_provenance") or {},
        "materials": p.get("materials") or [],
        "formulas": p.get("formulas") or {},
        "pdfLayout": p.get("pdfLayout") or {},
        "brand": p.get("brand") or "woodenmax",
        "catalogue": p.get("catalogue") or {},
        "sectionSeries": p.get("sectionSeries"),
    }
