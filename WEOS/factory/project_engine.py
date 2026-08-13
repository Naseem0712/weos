"""Project engine — multi-line cart calculate + combine + optimize."""

from __future__ import annotations

import copy
import logging
import uuid
from typing import Any, Mapping

from WEOS.factory.optimize_engine import CutPiece, GlassPiece, optimize_project_materials

_log = logging.getLogger("weos.project_engine")
from WEOS.factory.line_kind import is_railing_cart_line as _is_railing_cart_line
from WEOS.factory.line_kind import is_shower_cart_line as _is_shower_cart_line
from WEOS.factory.line_kind import is_ventilator_cart_line as _is_ventilator_cart_line
from WEOS.factory.line_kind import quote_qty_breakdown as _quote_qty_breakdown
from WEOS.factory.line_kind import line_location_name as _line_location_name
from WEOS.factory.pipeline import generate_job
from WEOS.factory.product_loader import load_product
from WEOS.factory.project_store import new_quotation_id
from WEOS.factory.svg_export import layout_summary_for_job, preview_svgs_for_drawing


def _persist_window_options(
    lo: Mapping[str, Any],
    line: Mapping[str, Any],
    *,
    base: Mapping[str, Any] | None = None,
    track_count: float | None = None,
) -> dict[str, Any]:
    """Options blob that PDF elevation re-derive must see (system/fold/sections)."""
    options: dict[str, Any] = dict(base or {})
    options["glass"] = line.get("glass") if line.get("glass") is not None else options.get("glass")
    options["colour"] = line.get("colour") if line.get("colour") is not None else options.get("colour")
    options["handle"] = line.get("handle") if line.get("handle") is not None else options.get("handle")
    options["partitions"] = lo.get("partitions") or options.get("partitions") or []
    options["mesh"] = bool(lo.get("mesh"))
    if track_count is not None:
        options["trackCount"] = float(track_count)
    elif lo.get("trackCount") is not None:
        options["trackCount"] = float(lo.get("trackCount"))
    options["system"] = lo.get("system") or options.get("system") or "sliding"
    if lo.get("glassCount") is not None:
        options["glassShutters"] = lo.get("glassCount")
    if lo.get("meshCount") is not None:
        options["meshShutters"] = lo.get("meshCount")
    op = lo.get("opening")
    if op in ("auto", "", None):
        options.pop("opening", None)
    elif op:
        options["opening"] = op
    if lo.get("openingSide"):
        options["openingSide"] = lo.get("openingSide")
    if lo.get("openingExplicit"):
        options["openingExplicit"] = True
    if lo.get("fixShuttersRaw") not in (None, ""):
        options["fixShutters"] = lo.get("fixShuttersRaw")
    if lo.get("foldLeft") is not None:
        options["foldLeft"] = lo.get("foldLeft")
    if lo.get("foldRight") is not None:
        options["foldRight"] = lo.get("foldRight")
    if lo.get("sectionSizes"):
        options["sectionSizes"] = lo.get("sectionSizes")
    if lo.get("handleLevel") is not None:
        options["handleLevel"] = lo.get("handleLevel")
    if lo.get("handleOverrides"):
        options["handleOverrides"] = lo.get("handleOverrides")
    if lo.get("gridSpec"):
        options["grid"] = lo.get("gridSpec")
    series = lo.get("sectionSeries") or line.get("sectionSeries")
    if series:
        options["sectionSeries"] = series
    _opts_in = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    for _k in (
        "handleName",
        "meshName",
        "powderCoatName",
        "handleFinish",
        "frameMaterial",
        "reinforcement",
        "reinforcementMaterial",
        "hardwareBrand",
        "hardwareType",
        "hardwareColour",
        "glassBrand",
        "glassColour",
        "glassMakeup",
    ):
        _v = lo.get(_k) or line.get(_k) or (_opts_in or {}).get(_k)
        if _v is not None and _v != "":
            options[_k] = _v
    # Optional panel fill (glass → louvers / sheet) — composable feature, not a product type.
    pf = lo.get("panelFill") or line.get("panelFill") or (_opts_in or {}).get("panelFill")
    if isinstance(pf, Mapping) and str(pf.get("fillType") or "glass") != "glass":
        options["panelFill"] = dict(pf)
        feats = options.get("features")
        if not isinstance(feats, list):
            feats = list(feats) if isinstance(feats, tuple) else []
        if not any(isinstance(f, Mapping) and str(f.get("type") or "") == "panel_fill" for f in feats):
            feats.append({"type": "panel_fill", **dict(pf)})
        options["features"] = feats
    # Fold / casement / shower must never carry a sliding trackCount that prints as "2-track"
    sys_l = str(options.get("system") or "").lower()
    if sys_l in ("bifold", "fold", "fold_sliding", "fold_and_sliding", "casement", "openable", "opening", "shower"):
        options.pop("trackCount", None)
    cp = lo.get("casementPanels") or line.get("casementPanels") or (_opts_in or {}).get("casementPanels")
    if isinstance(cp, (list, tuple)) and cp:
        options["casementPanels"] = list(cp)
    if lo.get("productType") or line.get("productType"):
        options["productType"] = lo.get("productType") or line.get("productType")
    return options


def _augment_weight_with_louvers(
    result: dict[str, Any],
    panel_fill: Mapping[str, Any] | None,
    *,
    width: float,
    height: float,
    qty: float = 1.0,
) -> None:
    """Add aluminium louver blade kg into the line weight (does not remove glass kg)."""
    if not isinstance(panel_fill, Mapping):
        return
    if str(panel_fill.get("fillType") or "glass") != "louvers":
        return
    try:
        from WEOS.factory.panel_fills import compute_louver_weight
    except Exception:
        return
    try:
        lw = compute_louver_weight(
            panel_fill,
            opening_width_mm=float(width),
            opening_height_mm=float(height),
            qty=float(qty or 1.0),
        )
    except Exception:
        return
    kg = float((lw or {}).get("weightKg") or 0.0)
    if kg <= 0:
        return
    w = result.get("weight")
    if not isinstance(w, dict):
        w = {}
        result["weight"] = w
    w["aluminiumKg"] = round(float(w.get("aluminiumKg") or 0) + kg, 3)
    w["totalKg"] = round(float(w.get("totalKg") or 0) + kg, 3)
    w["louverKg"] = round(kg, 3)
    result["louverWeight"] = lw


def _section_details_for_product(product: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Series Setup section rows for quote specs (name / dims / weight / std length)."""
    if not isinstance(product, Mapping):
        return []
    setup = product.get("setup")
    if isinstance(setup, Mapping) and setup:
        try:
            from WEOS.factory.product_setup import flatten_setup_sections

            rows = flatten_setup_sections(setup)
            if rows:
                return rows
        except Exception:
            pass
    cat = product.get("catalogue") if isinstance(product.get("catalogue"), Mapping) else {}
    sizes = (cat or {}).get("sectionSizes") if isinstance(cat, Mapping) else None
    if isinstance(sizes, Mapping) and sizes:
        return [
            {"name": k, "use": k, "wMm": v, "hMm": None}
            for k, v in sizes.items()
            if v is not None
        ]
    return []


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
        "description": line.get("description") or product.get("displayName"),
        "category": product.get("category", "Windows"),
        "status": "stub",
        "width": float(line.get("width", 0)),
        "height": float(line.get("height", 0)),
        "qty": qty,
        "options": {},
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


def _railing_weight_summary(
    bom: list[dict[str, Any]] | None,
    glass_pieces: list[dict[str, Any]] | None,
    quote: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Additive weight summary from railing BOM via Universal Weight Engine.

    Does not invent weights — sums known BOM/glass kg and reports unknowns.
    Pricing is untouched.
    """
    try:
        from WEOS.factory.weight_engine import analyze_missing_weights, enrich_bom_with_weights
    except Exception:
        return {"aluminiumKg": 0, "glassKg": 0, "hardwareKg": 0, "totalKg": 0}

    items: list[dict[str, Any]] = []
    for row in bom or []:
        if not isinstance(row, dict):
            continue
        it = dict(row)
        # Map common railing BOM fields
        if it.get("weightKg") is not None and it.get("weightPerUnit") is None:
            it["weightPerUnit"] = it.get("weightKg")
            it.setdefault("weightSource", "catalogue")
        items.append(it)
    for g in glass_pieces or []:
        if isinstance(g, dict):
            items.append(
                {
                    "name": g.get("name") or "railing glass",
                    "material": "glass",
                    "category": "glass",
                    "widthMm": g.get("widthMm"),
                    "heightMm": g.get("heightMm"),
                    "thicknessMm": g.get("thicknessMm"),
                    "quantity": g.get("qty") or g.get("quantity") or 1,
                    "weightKg": g.get("weightKg"),
                    "unit": "pcs",
                }
            )

    enriched = enrich_bom_with_weights(items)
    glass_kg = 0.0
    alu_kg = 0.0
    hw_kg = 0.0
    other_kg = 0.0
    for row in enriched:
        tw = row.get("totalWeight")
        if tw is None:
            continue
        cat = str(row.get("category") or row.get("materialKind") or "").lower()
        if "glass" in cat:
            glass_kg += float(tw)
        elif any(x in cat for x in ("rail", "profile", "aluminium", "alu", "handrail", "bottom")):
            alu_kg += float(tw)
        elif any(x in cat for x in ("hardware", "anchor", "connector", "block", "cap", "stud")):
            hw_kg += float(tw)
        else:
            other_kg += float(tw)

    # Prefer explicit quote total when already computed with known weights
    q = quote or {}
    if q.get("totalWeightKg") is not None:
        try:
            explicit = float(q["totalWeightKg"])
            if explicit > 0:
                return {
                    "aluminiumKg": round(alu_kg, 3),
                    "glassKg": round(glass_kg, 3),
                    "hardwareKg": round(hw_kg + other_kg, 3),
                    "totalKg": round(explicit, 3),
                    "weightSource": "catalogue",
                }
        except (TypeError, ValueError):
            pass

    total = glass_kg + alu_kg + hw_kg + other_kg
    report = analyze_missing_weights(items)
    out: dict[str, Any] = {
        "aluminiumKg": round(alu_kg, 3),
        "glassKg": round(glass_kg, 3),
        "hardwareKg": round(hw_kg + other_kg, 3),
        "totalKg": round(total, 3) if total > 0 else 0,
        "missingWeight": report.get("summary") if report.get("missingCount") else None,
        "missingWeightReport": {
            "missingCount": report.get("missingCount"),
            "calculableCount": report.get("calculableCount"),
            "needsCatalogueCount": report.get("needsCatalogueCount"),
            "offerCalculateNow": report.get("offerCalculateNow"),
        }
        if report.get("missingCount")
        else None,
    }
    return out


def _railing_line_result(line: Mapping[str, Any], *, include_preview: bool = True) -> dict[str, Any]:
    """Price a railing line from its own designer config (no window geometry).

    Uses :func:`railing_engine.compute_railing` for the cost breakdown and the
    2D SVG. The customer price is the railing ``sellingTotal`` (per-unit rate ×
    width, or the user's manual rate override) × qty.

    Always refreshes ``options.railing`` + ``options.railingQuote`` so customer /
    factory PDFs can redraw the designed elevation and print BOM details.
    """
    from WEOS.factory.line_kind import railing_product_type_for_line
    from WEOS.factory.railing_engine import (
        compute_railing,
        ensure_railing_dims,
        format_railing_description,
        railing_svg,
    )

    opts_in = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    cfg = (opts_in or {}).get("railing") if isinstance(opts_in, Mapping) else {}
    cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
    # Staircase product type without an explicit shape → stair world (no window fallback).
    # Prefer live cfg.shape when set (Normal/straight must not resurrect staircase).
    if not cfg.get("shape") and railing_product_type_for_line(line) == "staircase_railing":
        cfg["shape"] = "staircase"
    # Do NOT copy cart sellingRate into manualRatePerUnit — that froze Total Amount
    # at RFT×old rate and dropped BOM / material rate edits from the cascade.
    # Only options.railing.manualRatePerUnit (designer Manual rate) may override.
    # Cart width/height (mm) must drive designer length when options.railing is empty
    # or missing lengthMm — otherwise PDF drew a collapsed 1 mm stub.
    cfg = ensure_railing_dims(
        cfg,
        width=float(line.get("width") or 0) or None,
        height=float(line.get("height") or 0) or None,
    )
    q = compute_railing(cfg)
    qty = int(line.get("qty") or line.get("quantity") or 1)
    unit_total = float(q.get("sellingTotal") or 0.0)
    subtotal = round(unit_total * qty, 2)
    sale_unit = str(q.get("saleUnit") or line.get("saleUnit") or "rft").lower()
    billable = float(q.get("widthUnit") or (q.get("lengthRft") if sale_unit == "rft" else q.get("lengthRmt")) or 0)
    glass_spec = " · ".join(
        str(x) for x in (
            f"{q.get('glassThicknessMm') or cfg.get('glassThicknessMm') or 12} mm",
            cfg.get("glassType") or cfg.get("glassColour") or q.get("glassType"),
            cfg.get("glassBrand") or q.get("glassBrand"),
        ) if x
    ) or "railing glass"

    glass_pieces = [
        {"qty": 1, "width": round(w, 1), "height": round(float(q.get("heightMm") or q.get("glassHeightMm") or 0), 1),
         "thicknessMm": float(q.get("glassThicknessMm") or cfg.get("glassThicknessMm") or 12),
         "spec": glass_spec}
        for w in (q.get("panelWidthsMm") or [])
    ]
    bom = [
        {"name": it.get("label"), "qty": it.get("qty"), "unit": it.get("unit"),
         "rate": it.get("rate"), "amount": it.get("amount"),
         "color": it.get("color"), "grade": it.get("grade"), "sizeMm": it.get("sizeMm")}
        for it in (q.get("items") or [])
    ]
    # Product Library materials[] — LengthRft / ActualLength evaluate to commercial run length
    lib_materials: list[dict[str, Any]] = []
    product_id = str(line.get("product") or line.get("productId") or "railings_stub")
    try:
        from WEOS.factory.formula import build_context
        from WEOS.factory.materials_engine import compute_materials
        from WEOS.factory.product_loader import load_product

        product = load_product(product_id, strict=False)
        mats = product.get("materials") or []
        if mats:
            length_mm = float(q.get("lengthMm") or line.get("width") or 0)
            height_mm = float(q.get("heightMm") or q.get("glassHeightMm") or line.get("height") or 0)
            extras = {
                "commercialRailingLengthRFT": float(
                    q.get("commercialRailingLengthRFT") or q.get("lengthRft") or 0
                ),
                "commercialRailingLengthRMT": float(
                    q.get("commercialRailingLengthRMT") or q.get("lengthRmt") or 0
                ),
                "railingLengthMm": length_mm,
                "commercialLengthMm": length_mm,
            }
            ctx = build_context(length_mm, height_mm, {}, qty=1.0, extras=extras)
            computed = compute_materials(mats, ctx, line_qty=float(qty))
            for m in computed:
                row = {
                    "name": m.description,
                    "category": m.category,
                    "qty": m.quantity,
                    "unit": m.unit,
                    "rate": m.unit_rate,
                    "amount": round(float(m.quantity or 0) * float(m.unit_rate or 0), 2)
                    if m.unit_rate is not None
                    else None,
                    "source": "product_library",
                }
                lib_materials.append(row)
                bom.append(row)
    except Exception:
        _log.exception("railing product-library materials failed for %s", product_id)
        lib_materials = []

    ptype = railing_product_type_for_line({**dict(line), "options": {**(opts_in or {}), "railing": cfg}, "railing": q})
    photo = line.get("designPhoto") if isinstance(line.get("designPhoto"), Mapping) else None
    # Persist cfg + fresh quote so PDF draw_line_elevation / _spec_lines never lose the design.
    # Strip window layout keys so specs never mix Track / Fold / Panels S1 Sliding.
    opts_out = {
        "railing": cfg,
        "railingQuote": q,
        "productType": ptype,
        "commercialOnly": q.get("commercial") or {
            "sellingRatePerUnit": q.get("sellingPerUnit"),
            "saleUnit": sale_unit,
        },
    }
    svg = railing_svg(cfg, quote=q) if include_preview else ""
    selling = {
        "saleUnit": sale_unit,
        "saleUnitLabel": f"Per {sale_unit.upper()}",
        "sellingRate": float(q.get("sellingPerUnit") or 0.0),
        "billableQty": round(billable * qty, 4),
        "sellingAmount": subtotal,
        "qty": qty,
    }
    # Always rebuild from the live quote — never keep a stale cart description
    # (e.g. "staircase · 4 panels" after switching to Normal / straight).
    description = format_railing_description(q, cfg)
    display = "Staircase railing" if ptype == "staircase_railing" else "Railing"
    prior_name = str(line.get("displayName") or "")
    if ptype != "staircase_railing" and prior_name and "stair" not in prior_name.lower():
        display = prior_name
    return {
        "lineId": line.get("lineId") or uuid.uuid4().hex[:8],
        "product": product_id,
        "productType": ptype,
        "displayName": display,
        "category": "Railings",
        "status": "railing",
        "description": description,
        "width": float(line.get("width") or q.get("lengthMm") or 0),
        "height": float(line.get("height") or q.get("heightMm") or q.get("glassHeightMm") or 0),
        "qty": qty,
        "saleUnit": sale_unit,
        "sellingRate": float(q.get("sellingPerUnit") or 0.0),
        "selling": selling,
        "commercialTotal": subtotal,
        "railing": q,
        "options": opts_out,
        # Explicitly absent — never inherit window Product Library / series setup.
        "sectionSeries": None,
        "sectionSpecs": {},
        "sectionDetails": [],
        "layout": {},
        "specifications": {},
        "glass": glass_pieces,
        "hardware": [],
        "materials": lib_materials,
        "brush": {"totalMeters": 0, "pieces": []},
        "trackRail": [],
        "cutList": [],
        "bom": bom,
        "weight": _railing_weight_summary(bom, glass_pieces, q),
        "price": {
            "currency": "INR",
            "unitRate": float(q.get("sellingPerUnit") or 0.0),
            "unitTotal": round(unit_total, 2),
            "subtotal": subtotal,
            "markupPercent": 0,
            "gstPercent": 0,
            "total": subtotal,
            "saleUnit": sale_unit,
        },
        "preview": {"svg": svg},
        "note": "Railing — BOM rates → cost cascade → per-unit rate; designer Manual rate only when set.",
        **({"designPhoto": dict(photo)} if photo else {}),
    }


def _shower_line_result(line: Mapping[str, Any], *, include_preview: bool = True) -> dict[str, Any]:
    """Price a shower partition from designer config (unified canvas + PDF)."""
    from WEOS.factory.shower_engine import (
        compute_shower,
        ensure_shower_dims,
        format_shower_description,
        shower_svg,
    )

    opts_in = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    cfg = (opts_in or {}).get("shower") if isinstance(opts_in, Mapping) else {}
    cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
    if not cfg and isinstance(line.get("shower"), Mapping):
        cfg = dict(line.get("shower") or {})
    cfg = ensure_shower_dims(
        cfg,
        width=float(line.get("width") or 0) or None,
        height=float(line.get("height") or 0) or None,
    )
    if line.get("colour") and not cfg.get("colour"):
        cfg["colour"] = line.get("colour")
    if line.get("glass") and not cfg.get("glassLabel"):
        cfg["glassLabel"] = str(line.get("glass")).replace("_", " ")
    if line.get("saleUnit") and not cfg.get("saleUnit"):
        cfg["saleUnit"] = line.get("saleUnit")
    # Cart selling rate is the commercial override when the designer didn't set manual.
    if cfg.get("manualRatePerUnit") in (None, "") and line.get("sellingRate") not in (None, ""):
        cfg["sellingRate"] = line.get("sellingRate")
    q = compute_shower(cfg)
    qty = int(line.get("qty") or line.get("quantity") or 1)
    unit_total = float(q.get("sellingTotal") or 0.0)
    # compute_shower already multiplies qty when saleUnit=opening; for sqft it uses area×qty.
    if int(q.get("qty") or 1) == 1 and qty > 1 and str(q.get("saleUnit") or "sqft") == "sqft":
        unit_total = round(float(q.get("sellingPerUnit") or 0) * float(q.get("areaSqft") or 0) * qty, 2)
    subtotal = round(unit_total, 2)
    sale_unit = str(q.get("saleUnit") or line.get("saleUnit") or "sqft").lower()
    svg = shower_svg(cfg, quote=q) if include_preview else ""
    description = format_shower_description(q, cfg)
    opts_out = {
        "shower": cfg,
        "showerQuote": q,
        "productType": "shower_partition",
        "colour": q.get("colour") or line.get("colour"),
        "glass": cfg.get("glassLabel") or line.get("glass"),
    }
    selling = {
        "saleUnit": sale_unit,
        "saleUnitLabel": f"Per {sale_unit.upper()}",
        "sellingRate": float(q.get("sellingPerUnit") or 0.0),
        "billableQty": float(q.get("billableQty") or q.get("areaSqft") or qty),
        "sellingAmount": subtotal,
        "qty": qty,
    }
    return {
        "lineId": line.get("lineId") or uuid.uuid4().hex[:8],
        "product": str(line.get("product") or line.get("productId") or "shower_partition"),
        "productType": "shower_partition",
        "displayName": str(line.get("displayName") or "Shower Partition"),
        "category": "Bathrooms",
        "status": "shower",
        "description": description,
        "width": float(line.get("width") or q.get("widthMm") or 0),
        "height": float(line.get("height") or q.get("heightMm") or 0),
        "qty": qty,
        "saleUnit": sale_unit,
        "sellingRate": float(q.get("sellingPerUnit") or 0.0),
        "selling": selling,
        "commercialTotal": subtotal,
        "shower": q,
        "options": opts_out,
        "sectionSeries": None,
        "sectionSpecs": {},
        "sectionDetails": [],
        "layout": {"system": "shower", "kind": "shower_partition", "panels": q.get("panels") or [],
                   "footprint": q.get("footprint"), "trackCount": None},
        "specifications": {},
        "glass": [{"spec": q.get("glassLabel"), "thicknessMm": q.get("glassThicknessMm"),
                   "colour": q.get("glassColour"), "qty": 1}],
        "hardware": q.get("items") or [],
        "materials": [],
        "brush": {"totalMeters": 0, "pieces": []},
        "trackRail": [],
        "cutList": [],
        "bom": q.get("items") or [],
        "weight": {"aluminiumKg": 0, "glassKg": 0, "hardwareKg": 0, "totalKg": 0},
        "price": {
            "currency": "INR",
            "unitRate": float(q.get("sellingPerUnit") or 0.0),
            "unitTotal": round(float(q.get("sellingPerUnit") or 0) * float(q.get("areaSqft") or 0), 2),
            "subtotal": subtotal,
            "markupPercent": 0,
            "gstPercent": 0,
            "total": subtotal,
            "saleUnit": sale_unit,
        },
        "preview": {"svg": svg},
        "note": "Shower partition — selling rate × billed unit (sft/opening).",
        **({"designPhoto": dict(line["designPhoto"])} if isinstance(line.get("designPhoto"), Mapping) else {}),
    }


def _ventilator_line_result(line: Mapping[str, Any], *, include_preview: bool = True) -> dict[str, Any]:
    """Price a bathroom ventilator from designer config (unified canvas + PDF)."""
    from WEOS.factory.ventilator_engine import (
        compute_ventilator,
        ensure_ventilator_dims,
        format_ventilator_description,
        ventilator_svg,
    )

    opts_in = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    cfg = (opts_in or {}).get("ventilator") if isinstance(opts_in, Mapping) else {}
    cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
    if not cfg and isinstance(line.get("ventilator"), Mapping):
        cfg = dict(line.get("ventilator") or {})
    cfg = ensure_ventilator_dims(
        cfg,
        width=float(line.get("width") or 0) or None,
        height=float(line.get("height") or 0) or None,
    )
    if line.get("colour") and not cfg.get("colour"):
        cfg["colour"] = line.get("colour")
    if line.get("glass") and not cfg.get("glassLabel"):
        cfg["glassLabel"] = str(line.get("glass")).replace("_", " ")
    if line.get("saleUnit") and not cfg.get("saleUnit"):
        cfg["saleUnit"] = line.get("saleUnit")
    if cfg.get("manualRatePerUnit") in (None, "") and line.get("sellingRate") not in (None, ""):
        cfg["sellingRate"] = line.get("sellingRate")
    q = compute_ventilator(cfg)
    qty = int(line.get("qty") or line.get("quantity") or 1)
    unit_total = float(q.get("sellingTotal") or 0.0)
    if int(q.get("qty") or 1) == 1 and qty > 1 and str(q.get("saleUnit") or "sqft") == "sqft":
        unit_total = round(float(q.get("sellingPerUnit") or 0) * float(q.get("areaSqft") or 0) * qty, 2)
    subtotal = round(unit_total, 2)
    sale_unit = str(q.get("saleUnit") or line.get("saleUnit") or "sqft").lower()
    svg = ventilator_svg(cfg, quote=q) if include_preview else ""
    description = format_ventilator_description(q, cfg)
    opts_out = {
        "ventilator": cfg,
        "ventilatorQuote": q,
        "productType": "bathroom_ventilator",
        "colour": q.get("colour") or line.get("colour"),
        "glass": cfg.get("glassLabel") or line.get("glass"),
    }
    selling = {
        "saleUnit": sale_unit,
        "saleUnitLabel": f"Per {sale_unit.upper()}",
        "sellingRate": float(q.get("sellingPerUnit") or 0.0),
        "billableQty": float(q.get("billableQty") or q.get("areaSqft") or qty),
        "sellingAmount": subtotal,
        "qty": qty,
    }
    return {
        "lineId": line.get("lineId") or uuid.uuid4().hex[:8],
        "product": str(line.get("product") or line.get("productId") or "bathroom_ventilator"),
        "productType": "bathroom_ventilator",
        "displayName": str(line.get("displayName") or "Bathroom ventilator"),
        "category": "Bathrooms",
        "status": "ventilator",
        "description": description,
        "width": float(line.get("width") or q.get("widthMm") or 0),
        "height": float(line.get("height") or q.get("heightMm") or 0),
        "qty": qty,
        "saleUnit": sale_unit,
        "sellingRate": float(q.get("sellingPerUnit") or 0.0),
        "selling": selling,
        "commercialTotal": subtotal,
        "ventilator": q,
        "options": opts_out,
        "sectionSeries": None,
        "sectionSpecs": {},
        "sectionDetails": [],
        "layout": {"system": "ventilator", "kind": "bathroom_ventilator", "panels": q.get("panels") or [],
                   "trackCount": None},
        "specifications": {},
        "glass": [{"spec": q.get("glassLabel"), "thicknessMm": q.get("glassThicknessMm"),
                   "colour": q.get("glassColour"), "qty": 1}],
        "hardware": q.get("items") or [],
        "materials": [],
        "brush": {"totalMeters": 0, "pieces": []},
        "trackRail": [],
        "cutList": [],
        "bom": [],
        "weight": {"aluminiumKg": 0, "glassKg": 0, "hardwareKg": 0, "totalKg": 0},
        "price": {
            "currency": "INR",
            "unitRate": float(q.get("sellingPerUnit") or 0.0),
            "unitTotal": round(unit_total, 2),
            "subtotal": subtotal,
            "markupPercent": 0,
            "gstPercent": 0,
            "total": subtotal,
            "saleUnit": sale_unit,
        },
        "preview": {"svg": svg},
        "note": "Bathroom ventilator — selling rate × billed unit (sft/opening).",
        **({"designPhoto": dict(line["designPhoto"])} if isinstance(line.get("designPhoto"), Mapping) else {}),
    }


def _attach_location(src: Mapping[str, Any] | None, result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy optional location/position name onto a calculated line for PDF serial."""
    out = dict(result or {})
    loc = _line_location_name(src) or _line_location_name(out)
    if not loc:
        return out
    out["locationName"] = loc
    out["positionName"] = loc
    opts = dict(out.get("options") or {}) if isinstance(out.get("options"), Mapping) else {}
    opts["locationName"] = loc
    opts["positionName"] = loc
    out["options"] = opts
    return out


def calculate_line(line: Mapping[str, Any], *, include_preview: bool = True) -> dict[str, Any]:
    """Calculate one cart line (product × size × qty × options)."""
    return _attach_location(line, _calculate_line_raw(line, include_preview=include_preview))


def _calculate_line_raw(line: Mapping[str, Any], *, include_preview: bool = True) -> dict[str, Any]:
    """Calculate one cart line (product × size × qty × options)."""
    from WEOS.factory.live_pricing import apply_selling_to_line_result

    from WEOS.factory.layout_options import line_layout_options
    from WEOS.factory.line_kind import (
        is_railing_product_type,
        is_shower_product_type,
        is_ventilator_product_type,
        product_world,
    )

    product_id = str(line.get("product") or line.get("productId") or "29mm_sliding")
    # Railing lines are self-priced from their designer config.
    if _is_railing_cart_line(line):
        try:
            return _railing_line_result(line, include_preview=include_preview)
        except Exception as exc:  # pragma: no cover - keep the quote rendering
            _log.exception("railing line calc failed: %s", exc)
            return _error_line_result(line, f"railing calc failed: {exc}")
    if _is_ventilator_cart_line(line):
        try:
            return _ventilator_line_result(line, include_preview=include_preview)
        except Exception as exc:  # pragma: no cover
            _log.exception("ventilator line calc failed: %s", exc)
            return _error_line_result(line, f"ventilator calc failed: {exc}")
    if _is_shower_cart_line(line):
        try:
            return _shower_line_result(line, include_preview=include_preview)
        except Exception as exc:  # pragma: no cover
            _log.exception("shower line calc failed: %s", exc)
            return _error_line_result(line, f"shower calc failed: {exc}")
    product = load_product(product_id, strict=False)
    # Product Library type lock: even without options.railing yet, never run window geometry.
    world = product_world(
        line.get("productType") or product.get("productType"),
        category=line.get("category") or product.get("category"),
        product_id=product_id,
    )
    if world == "ventilator" or is_ventilator_product_type(product.get("productType")):
        enriched = dict(line) if isinstance(line, Mapping) else {}
        enriched.setdefault("productType", "bathroom_ventilator")
        enriched.setdefault("category", product.get("category") or "Bathrooms")
        try:
            return _ventilator_line_result(enriched, include_preview=include_preview)
        except Exception as exc:  # pragma: no cover
            _log.exception("ventilator line calc failed: %s", exc)
            return _error_line_result(enriched, f"ventilator calc failed: {exc}")
    if world == "shower" or is_shower_product_type(product.get("productType")):
        enriched = dict(line) if isinstance(line, Mapping) else {}
        enriched.setdefault("productType", "shower_partition")
        enriched.setdefault("category", product.get("category") or "Bathrooms")
        try:
            return _shower_line_result(enriched, include_preview=include_preview)
        except Exception as exc:  # pragma: no cover
            _log.exception("shower line calc failed: %s", exc)
            return _error_line_result(enriched, f"shower calc failed: {exc}")
    if world in ("railing", "staircase_railing") or is_railing_product_type(product.get("productType")):
        enriched = dict(line) if isinstance(line, Mapping) else {}
        enriched.setdefault("productType", product.get("productType") or world)
        enriched.setdefault("category", product.get("category") or "Railings")
        try:
            return _railing_line_result(enriched, include_preview=include_preview)
        except Exception as exc:  # pragma: no cover
            _log.exception("railing line calc failed: %s", exc)
            return _error_line_result(enriched, f"railing calc failed: {exc}")
    qty = int(line.get("qty") or line.get("quantity") or 1)
    width = float(line.get("width", 0))
    height = float(line.get("height", 0))
    lo = line_layout_options(line)

    if product.get("_stub") or product.get("status") == "stub":
        # Catalogue/imported products price via a manual rate, but they now carry a
        # synthesised renderable geometry — so draw a real elevation + layout so the
        # preview and PDF don't fall back to a "Catalogue placeholder".
        result = _stub_line_result(line, product)
        try:
            colour = line.get("colour") or "white"
            grid = line.get("grid") or (line.get("options") or {}).get("grid")
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
                glass_count=lo.get("glassCount"),
                mesh_count=lo.get("meshCount"),
                opening=lo.get("opening"),
                opening_side=lo.get("openingSide"),
                opening_explicit=bool(lo.get("openingExplicit")),
                fixed_shutters=lo.get("fixShuttersRaw"),
                system=lo.get("system"),
                fold_left=lo.get("foldLeft"),
                fold_right=lo.get("foldRight"),
                section_sizes=lo.get("sectionSizes"),
                handle_finish=lo.get("handleFinish"),
                handle_level=lo.get("handleLevel"),
                handle_overrides=lo.get("handleOverrides"),
                grid=lo.get("gridSpec"),
                sash_overlap_mm=lo.get("sashOverlapMm"),
                mullion_gap_mm=lo.get("mullionGapMm"),
                frame_material=lo.get("frameMaterial") or line.get("frameMaterial"),
            )
            if lo.get("panelFill"):
                from WEOS.factory.panel_fills import attach_fill_to_drawing

                attach_fill_to_drawing(job.drawing, lo.get("panelFill"))
            result["preview"] = (
                preview_svgs_for_drawing(
                    job.drawing,
                    colour=str(colour).lower().replace(" ", "_"),
                    grid=grid,
                    include_plan=True,
                )
                if include_preview
                else {"svg": None}
            )
            result["layout"] = layout_summary_for_job(
                width=width, height=height, layout_meta=job.layout_meta
            )
            # Resolve glass so specs don't show blank glazing.
            glass_out = []
            for g in job.glass or []:
                if hasattr(g, "as_dict"):
                    d = g.as_dict()
                    glass_out.append(
                        {
                            "name": d.get("name") or getattr(g, "name", None),
                            "qty": getattr(g, "quantity", d.get("qty") or 1) * qty,
                            "width": round(float(getattr(g, "width_mm", d.get("width") or 0)), 1),
                            "height": round(float(getattr(g, "height_mm", d.get("height") or 0)), 1),
                            "thicknessMm": getattr(g, "thickness_mm", d.get("thicknessMm") or d.get("thickness_mm")),
                            "areaM2": round(float(getattr(g, "area_m2", 0) or 0) * qty, 4),
                            "weightKg": round(float(getattr(g, "weight_kg", 0) or 0) * qty, 3),
                        }
                    )
                elif isinstance(g, Mapping):
                    glass_out.append(dict(g))
            if glass_out:
                result["glass"] = glass_out
            if job.weight and hasattr(job.weight, "as_dict"):
                wd = job.weight.as_dict()
                result["weight"] = {
                    "aluminiumKg": round(float(wd.get("aluminium_kg") or 0) * qty, 3),
                    "glassKg": round(float(wd.get("glass_kg") or 0) * qty, 3),
                    "hardwareKg": round(float(wd.get("hardware_kg") or 0) * qty, 3),
                    "totalKg": round(float(wd.get("total_kg") or 0) * qty, 3),
                    "weightSource": wd.get("weight_source") or wd.get("weightSource"),
                }
            # Persist resolved config so the PDF re-render reproduces the same type.
            result["options"] = _persist_window_options(
                lo,
                line,
                base=result.get("options") if isinstance(result.get("options"), Mapping) else {},
                track_count=(job.layout_meta or {}).get("track_count") if lo.get("system") != "bifold" else None,
            )
            result["description"] = line.get("description") or result.get("displayName")
            result["sectionDetails"] = _section_details_for_product(product)
            if line.get("sectionSeries"):
                result["sectionSeries"] = line.get("sectionSeries")
        except Exception as exc:  # keep the manual-rate result even if drawing fails
            _log.warning("stub preview render failed for %s: %s", product_id, exc)
        return apply_selling_to_line_result(result, line)

    # Thread the FULL window configuration (system / fold / grid / shutter counts /
    # fix panels / section sizes / handle placement) into the job. Without this,
    # every line was generated as a default sliding window regardless of the chosen
    # system, so all types rendered identically in the preview + PDF.
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
        glass_count=lo.get("glassCount"),
        mesh_count=lo.get("meshCount"),
        opening=lo.get("opening"),
        opening_side=lo.get("openingSide"),
        opening_explicit=bool(lo.get("openingExplicit")),
        fixed_shutters=lo.get("fixShuttersRaw"),
        system=lo.get("system"),
        fold_left=lo.get("foldLeft"),
        fold_right=lo.get("foldRight"),
        section_sizes=lo.get("sectionSizes"),
        handle_finish=lo.get("handleFinish"),
        handle_level=lo.get("handleLevel"),
        handle_overrides=lo.get("handleOverrides"),
        grid=lo.get("gridSpec"),
        sash_overlap_mm=lo.get("sashOverlapMm"),
        mullion_gap_mm=lo.get("mullionGapMm"),
        frame_material=lo.get("frameMaterial") or line.get("frameMaterial"),
    )
    if lo.get("panelFill"):
        from WEOS.factory.panel_fills import attach_fill_to_drawing

        attach_fill_to_drawing(job.drawing, lo.get("panelFill"))
    quote = job.quotation.as_dict() if job.quotation else {}
    weight = job.weight.as_dict() if job.weight else {}
    colour = (line.get("colour") or "white")
    grid = line.get("grid") or (line.get("options") or {}).get("grid") or (line.get("options") or {}).get("grille")
    preview_pack = (
        preview_svgs_for_drawing(
            job.drawing,
            colour=str(colour).lower().replace(" ", "_"),
            grid=grid,
            include_plan=True,
        )
        if include_preview
        else {"svg": None}
    )
    svg = preview_pack.get("svg")
    layout = layout_summary_for_job(width=width, height=height, layout_meta=job.layout_meta)

    # Scale commercial totals by qty
    unit_total = float(quote.get("total", 0))
    unit_sub = float(quote.get("subtotal", 0))

    brush_m = 0.0
    for b in job.brush:
        if b.description.endswith("TOTAL"):
            brush_m = b.length_mm / 1000.0
            break

    options = _persist_window_options(
        lo,
        line,
        track_count=(
            None
            if str(lo.get("system") or "") == "bifold"
            else float((job.layout_meta or {}).get("track_count") or lo.get("trackCount") or 2)
        ),
    )
    if grid and "grid" not in options:
        options["grid"] = grid

    result_base = {
        "lineId": line.get("lineId") or uuid.uuid4().hex[:8],
        **({"designPhoto": dict(line["designPhoto"])} if isinstance(line.get("designPhoto"), Mapping) else {}),
        "product": job.profile_id,
        "displayName": job.display_name,
        "description": line.get("description") or job.display_name,
        "category": product.get("category", "Windows"),
        "status": "active",
        "width": width,
        "height": height,
        "qty": qty,
        "sectionSeries": line.get("sectionSeries"),
        "sectionDetails": _section_details_for_product(product),
        "partitions": lo.get("partitions") or [],
        "mesh": bool(lo.get("mesh")),
        "trackCount": options.get("trackCount"),
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
                "colour": (lo.get("glassColour") or line.get("glassColour")),
                "brand": (lo.get("glassBrand") or line.get("glassBrand")),
                "makeup": (lo.get("glassMakeup") or line.get("glassMakeup")),
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
            "weightSource": weight.get("weight_source") or weight.get("weightSource"),
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
        "preview": preview_pack,
        "layoutMeta": dict(job.layout_meta or {}),
        "_rawCutList": [{"length_mm": c.length_mm, "quantity": c.quantity * qty, "profile": c.profile} for c in job.cut_list],
        "_rawGlass": [
            {"width_mm": g.width_mm, "height_mm": g.height_mm, "qty": g.quantity * qty, "thickness_mm": g.thickness_mm, "name": g.name}
            for g in job.glass
        ],
    }
    _augment_weight_with_louvers(result_base, lo.get("panelFill"), width=width, height=height, qty=qty)
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
        "qtyByGroup": [{"label": lab, "qty": n} for lab, n in _quote_qty_breakdown(line_results)],
    }


def calculate_project(
    project: Mapping[str, Any],
    *,
    optimize: bool = True,
    include_preview: bool = True,
) -> dict[str, Any]:
    """Full project calculation: each line → combine → material optimization."""
    lines = project.get("lines") or []
    results: list[dict[str, Any]] = []
    for idx, ln in enumerate(lines):
        try:
            results.append(calculate_line(ln, include_preview=include_preview))
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

    quotation_id = project.get("quotationId")
    if not quotation_id:
        co = str(project.get("companyName") or "").strip()
        if not co:
            try:
                from WEOS.factory.company_store import load_company

                co = str((load_company() or {}).get("companyName") or "").strip()
            except Exception:
                co = ""
        quotation_id = new_quotation_id(co or None)
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
