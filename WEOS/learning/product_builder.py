"""Product Builder — load an approved Product Series into a ready-to-use config.

Does not write production products unless explicitly asked via publish_to_product_stub
(still creates a draft product JSON under products/ only when admin confirms).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from WEOS.learning.v2_store import (
    build_series_tree,
    ensure_v2_dirs,
    get_library_item,
    list_library,
)
from WEOS.paths import products_dir


def list_buildable_series() -> list[dict[str, Any]]:
    ensure_v2_dirs()
    out = []
    for s in list_library("product_series"):
        tree = build_series_tree(s.get("id"))
        profile_count = tree[0]["profileCount"] if tree else 0
        out.append(
            {
                "id": s.get("id"),
                "seriesName": s.get("seriesName"),
                "brand": s.get("brand"),
                "productCategory": s.get("productCategory"),
                "profileCount": profile_count,
                "status": s.get("status", "approved"),
            }
        )
    return out


def load_series_for_builder(series_id: str) -> dict[str, Any]:
    """
    Auto-load Geometry / Profiles / Glass / Hardware / Quotation / PDF / Cutting /
    Weight / Pricing rules from approved KB for the happy path.
    """
    ensure_v2_dirs()
    try:
        series = get_library_item("product_series", series_id)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Product series not approved yet: {series_id}") from exc

    profiles = [
        p
        for p in list_library("profiles")
        if series_id in (p.get("compatibleSeries") or []) or p.get("seriesId") == series_id
    ]
    # Prefer linked ids on series
    for ref in series.get("profiles") or []:
        pid = ref if isinstance(ref, str) else ref.get("id")
        if pid and not any(p.get("id") == pid for p in profiles):
            try:
                profiles.append(get_library_item("profiles", pid))
            except FileNotFoundError:
                pass

    hardware = [
        h
        for h in list_library("hardware")
        if series_id in (h.get("compatibleSeries") or [])
    ]
    glass = [
        g
        for g in list_library("glass")
        if series_id in (g.get("compatibleProducts") or [])
    ]
    formulas = [
        f
        for f in list_library("formulas")
        if series_id in (f.get("compatibleSeries") or []) or not (f.get("compatibleSeries") or [])
    ]

    # Geometry hints from profile dims
    geometry: dict[str, Any] = {}
    for p in profiles:
        role = (p.get("bomRole") or p.get("usageRules", {}).get("bomRole") or "").lower()
        w = p.get("crossSectionWidthMm")
        h = p.get("crossSectionHeightMm")
        if role in ("outer_frame",) and w:
            geometry.setdefault("trackWidth", w)
            geometry.setdefault("frameWidth", h or w)
        if role == "interlock" and w:
            geometry.setdefault("interlockWidth", w)
        if role in ("shutter_frame", "sash") and w:
            geometry.setdefault("shutterFrameWidth", w)

    # Usage rules → BOM role map
    bom_usage = []
    for p in profiles:
        bom_usage.append(
            {
                "profileId": p.get("id"),
                "profileName": p.get("profileName"),
                "profileType": p.get("profileType"),
                "bomRole": p.get("bomRole") or (p.get("usageRules") or {}).get("bomRole"),
                "positions": p.get("usePosition") or (p.get("usageRules") or {}).get("positions") or [],
                "orientation": (p.get("usageRules") or {}).get("orientation") or [],
                "weightPerMeterKg": p.get("weightPerMeterKg"),
                "crossSectionWidthMm": p.get("crossSectionWidthMm"),
                "crossSectionHeightMm": p.get("crossSectionHeightMm"),
            }
        )

    materials = []
    for p in profiles:
        materials.append(
            {
                "id": p.get("id"),
                "name": p.get("profileName"),
                "category": "profile",
                "unit": "RFT",
                "quantityFormula": "runningFeet",
                "weightPerMeter": p.get("weightPerMeterKg"),
                "unitRate": None,
                "bomRole": p.get("bomRole"),
                "remarks": p.get("engineeringNotes") or "",
            }
        )
    for h in hardware:
        materials.append(
            {
                "id": h.get("id"),
                "name": h.get("name"),
                "category": "hardware",
                "unit": h.get("unit") or "PC",
                "quantityFormula": "shutterCount" if "handle" in (h.get("name") or "").lower() else "1",
                "unitRate": h.get("sellingRate") or h.get("purchaseRate"),
                "remarks": h.get("remarks") or "",
                "mapToHardware": True,
            }
        )
    for g in glass:
        materials.append(
            {
                "id": g.get("id"),
                "name": g.get("name"),
                "category": "glass",
                "unit": "SQM",
                "quantityFormula": "glassArea",
                "unitRate": None,
                "remarks": f"{g.get('thicknessMm')}mm {g.get('glassType')}",
            }
        )

    tree = build_series_tree(series_id)

    return {
        "seriesId": series_id,
        "series": series,
        "geometry": geometry,
        "profiles": profiles,
        "hardware": hardware,
        "glass": glass,
        "formulas": formulas,
        "quotationRules": series.get("quotationRules") or {},
        "pdfLayout": series.get("pdfLayout") or {"customer": "marqt_customer", "factory": "woodenmax_factory"},
        "cuttingRules": series.get("cuttingRules") or {},
        "weightRules": series.get("weightRules") or {},
        "pricingRules": series.get("pricingRules") or {},
        "bomUsageRules": bom_usage,
        "materials": materials,
        "tree": tree[0] if tree else None,
        "ready": bool(profiles),
        "message": (
            f"Loaded {series.get('seriesName')} — {len(profiles)} profiles, "
            f"{len(hardware)} hardware, {len(glass)} glass. Ready for Product Builder."
            if profiles
            else "Series approved but no profiles linked yet."
        ),
        "productionHint": "Use Publish Draft Product only when you want a products/*.json stub — never automatic.",
    }


def publish_product_draft(series_id: str, *, overwrite: bool = False) -> dict[str, Any]:
    """
    Explicit admin action: write a draft product.json under products/<id>/.
    Never called automatically from approve.
    """
    bundle = load_series_for_builder(series_id)
    series = bundle["series"]
    pid = series.get("id") or series_id
    dest_dir = products_dir() / pid
    dest = dest_dir / "product.json"
    if dest.is_file() and not overwrite:
        return {
            "ok": False,
            "error": f"Product {pid} already exists. Pass overwrite=true to replace (admin only).",
            "path": str(dest),
        }

    product = {
        "id": pid,
        "displayName": series.get("seriesName") or pid,
        "productType": "two_track_sliding" if "sliding" in (series.get("seriesName") or "").lower() else "generic",
        "category": series.get("productCategory") or "Windows",
        "units": "mm",
        "version": 1,
        "status": "stub",
        "description": series.get("productDescription") or "",
        "tagline": series.get("seriesName") or "",
        "brand": (series.get("brand") or "woodenmax").lower().replace(" ", "") or "woodenmax",
        "pdfLayout": bundle["pdfLayout"],
        "formulas": {
            f.get("id") or f"fx_{i}": f.get("expression")
            for i, f in enumerate(bundle["formulas"])
            if f.get("expression")
        } or {
            "shutterCount": "shutterCount",
            "glassArea": "glassArea",
            "runningFoot": "runningFeet",
        },
        "materials": bundle["materials"],
        "geometryHints": bundle["geometry"],
        "bomUsageRules": bundle["bomUsageRules"],
        "knowledgeBaseSeriesId": series_id,
        "source": "learning_engine_v2_product_builder",
        "note": "Draft from approved Knowledge Base — review formulas and rates before activating.",
    }
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(product, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "productId": pid, "path": str(dest), "status": "stub"}
