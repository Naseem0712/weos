"""Mesh fabric costing + preview cues (in-track / rolling / collapsible / vent).

In-track (sliding shutters)
  ``standard`` / ``premium`` — mesh sash on its own track.
  Area = (window width / 2) × height in sft.
  Rates: Standard ₹150/sft · Premium ₹220/sft.

Add-ons (no extra track)
  ``rolling`` — charged on full W×H · ₹450/sft.
    Preview: strip of mesh on one side + 38 mm vertical member.
  ``collapsible`` (alias ``pleated``) — charged on full W×H · ₹480/sft.
    Preview: center opening → strips on both sides + vertical members;
    top style → strip on top + horizontal member. Mesh sits *inside*.

Ventilator
  Outside fix mesh · ₹250/sft on vent area.

Line / options keys: ``meshType``, ``meshGrade``, ``meshPlacement``,
``meshCollapseStyle`` (center|top), ``meshW`` / ``meshH``, ``meshRate``,
``meshAmount``.
"""

from __future__ import annotations

from typing import Any, Mapping

MESH_TYPES: dict[str, str] = {
    "standard": "Standard mesh (in-track)",
    "premium": "Premium mesh (in-track)",
    "sliding": "Standard mesh (in-track)",  # legacy alias → standard
    "rolling": "Rolling mesh",
    "collapsible": "Collapsible mesh",
    "pleated": "Collapsible mesh",  # legacy alias → collapsible
}
INTRACK_MESH_TYPES = ("standard", "premium", "sliding")
ADDON_MESH_TYPES = ("rolling", "collapsible", "pleated")
MESH_PLACEMENTS: dict[str, str] = {
    "full": "Whole window",
    "left": "Left side (one shutter width)",
    "right": "Right side (one shutter width)",
    "custom": "Custom size",
}
MESH_COLLAPSE_STYLES: dict[str, str] = {
    "center": "Center opening (both sides)",
    "top": "Top opening (top band)",
}

# Default fabric rates ₹ / sft
DEFAULT_MESH_RATES: dict[str, float] = {
    "standard": 150.0,
    "premium": 220.0,
    "sliding": 150.0,
    "rolling": 450.0,
    "collapsible": 480.0,
    "pleated": 480.0,
    "vent_fix": 250.0,
}

# Preview geometry
MESH_MEMBER_MM = 38.0
MESH_PREVIEW_BAND_FRAC = 0.12  # "bit of mesh" ≈ 12% of clear opening
MESH_PREVIEW_BAND_MIN_MM = 80.0
MESH_PREVIEW_BAND_MAX_MM = 220.0

SQFT_PER_MM2 = 10.7639 / 1_000_000.0


def normalize_mesh_type(raw: Any) -> str:
    t = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not t:
        return "standard"
    if t in ("standard", "std", "normal"):
        return "standard"
    if t in ("premium", "prem"):
        return "premium"
    if "pleat" in t or "collaps" in t or "fold" == t:
        return "collapsible"
    if "roll" in t:
        return "rolling"
    if t in ("sliding", "in_track", "intrack", "wire", "sash"):
        return "standard"
    return "standard"


def normalize_mesh_placement(raw: Any) -> str:
    t = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if t in ("left", "left_side", "l"):
        return "left"
    if t in ("right", "right_side", "r"):
        return "right"
    if t in ("custom", "size", "custom_size"):
        return "custom"
    return "full"


def normalize_collapse_style(raw: Any) -> str:
    t = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if t in ("top", "top_down", "top_to_bottom", "vertical", "down"):
        return "top"
    return "center"


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick(line: Mapping[str, Any], *keys: str) -> Any:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    for k in keys:
        if line.get(k) is not None and line.get(k) != "":
            return line.get(k)
        if isinstance(opts, Mapping) and opts.get(k) is not None and opts.get(k) != "":
            return opts.get(k)
    return None


def mesh_type_of_line(line: Mapping[str, Any] | None) -> str:
    if not isinstance(line, Mapping):
        return "standard"
    raw = _pick(line, "meshType", "mesh_type")
    # Legacy: meshType=sliding + meshGrade=premium → premium
    grade = _pick(line, "meshGrade", "mesh_grade")
    if raw is None or str(raw).strip() == "":
        if grade:
            return normalize_mesh_type(grade)
        return "standard"
    t = normalize_mesh_type(raw)
    if t == "standard" and grade:
        g = normalize_mesh_type(grade)
        if g in ("standard", "premium"):
            return g
    return t


def is_addon_mesh(line: Mapping[str, Any] | None) -> bool:
    return mesh_type_of_line(line) in ("rolling", "collapsible")


def is_intrack_mesh(line: Mapping[str, Any] | None) -> bool:
    return mesh_type_of_line(line) in ("standard", "premium")


def default_mesh_rate(mtype: str) -> float:
    return float(DEFAULT_MESH_RATES.get(normalize_mesh_type(mtype), 150.0))


def _preview_band_mm(clear: float) -> float:
    band = float(clear) * MESH_PREVIEW_BAND_FRAC
    return max(MESH_PREVIEW_BAND_MIN_MM, min(MESH_PREVIEW_BAND_MAX_MM, band))


def _mm_to_sft(w_mm: float, h_mm: float) -> float:
    return round(max(w_mm, 0.0) * max(h_mm, 0.0) * SQFT_PER_MM2, 4)


def _line_wh(line: Mapping[str, Any]) -> tuple[float, float]:
    width = _num(line.get("width")) or _num(_pick(line, "widthMm")) or 0.0
    height = _num(line.get("height")) or _num(_pick(line, "heightMm")) or 0.0
    return float(width), float(height)


def _line_qty(line: Mapping[str, Any]) -> int:
    try:
        return max(int(round(float(line.get("qty") or line.get("quantity") or 1))), 1)
    except (TypeError, ValueError):
        return 1


def _mesh_applied(line: Mapping[str, Any]) -> bool:
    mesh_flag = _pick(line, "mesh")
    if mesh_flag is False or (
        isinstance(mesh_flag, str) and mesh_flag.strip().lower() in ("false", "no", "0", "off")
    ):
        return False
    mesh_n = _num(_pick(line, "meshShutters", "meshCount", "mesh_count")) or 0.0
    placement_raw = _pick(line, "meshPlacement", "mesh_placement")
    rate = _num(_pick(line, "meshRate", "mesh_rate"))
    mw_in = _num(_pick(line, "meshW", "meshWidthMm", "mesh_w"))
    mh_in = _num(_pick(line, "meshH", "meshHeightMm", "mesh_h"))
    if bool(mesh_flag) or mesh_n > 0:
        return True
    if placement_raw not in (None, "") or rate is not None or bool(mw_in and mh_in):
        return True
    return False


def mesh_fabric_for_line(line: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Resolve mesh fabric for design_cost + materials (any mesh type).

    Returns None when mesh is off. Always uses catalogue default rates unless
    ``meshRate`` overrides a positive value.
    """
    if not isinstance(line, Mapping) or not _mesh_applied(line):
        return None

    mtype = mesh_type_of_line(line)
    width, height = _line_wh(line)
    qty = _line_qty(line)
    rate_override = _num(_pick(line, "meshRate", "mesh_rate"))

    if mtype in ("rolling", "collapsible"):
        # Full window size (placement is preview-only for rolling/collapsible).
        mw, mh = width, height
        placement = normalize_mesh_placement(_pick(line, "meshPlacement", "mesh_placement"))
        if mtype == "rolling" and placement not in ("left", "right"):
            placement = "left"  # one-side preview default
        collapse = normalize_collapse_style(
            _pick(line, "meshCollapseStyle", "mesh_collapse_style", "meshStyle")
        ) if mtype == "collapsible" else None
        rate_n = float(rate_override) if rate_override is not None and rate_override > 0 else default_mesh_rate(mtype)
        area_sqft = _mm_to_sft(mw, mh)
        amount_unit = round(area_sqft * rate_n, 2)
        amount = round(amount_unit * qty, 2)
        name = _pick(line, "meshName", "mesh_name")
        label_bits = [MESH_TYPES.get(mtype, mtype.title()), "full window", f"{mw:g}×{mh:g} mm"]
        if mtype == "collapsible" and collapse:
            label_bits.insert(1, MESH_COLLAPSE_STYLES.get(collapse, collapse).split(" (")[0].lower())
        if name:
            label_bits.append(str(name))
        if rate_n > 0 and area_sqft:
            label_bits.append(f"₹{amount:,.2f} ({area_sqft:g} sft × ₹{rate_n:g})")
        return {
            "kind": "addon",
            "type": mtype,
            "typeLabel": MESH_TYPES.get(mtype, mtype.title()),
            "grade": None,
            "placement": placement,
            "placementLabel": MESH_PLACEMENTS.get(placement, placement),
            "collapseStyle": collapse,
            "widthMm": round(mw, 1),
            "heightMm": round(mh, 1),
            "areaSqft": area_sqft,
            "rate": rate_n,
            "qty": qty,
            "amountUnit": amount_unit,
            "amount": amount,
            "name": str(name) if name else None,
            "label": " · ".join(label_bits),
            "formula": "W × H (full window)",
            "memberMm": MESH_MEMBER_MM,
        }

    # In-track standard / premium — (W/2) × H
    mesh_n = _num(_pick(line, "meshShutters", "meshCount", "mesh_count")) or 0.0
    if mesh_n <= 0 and not _pick(line, "mesh"):
        return None
    if mesh_n <= 0:
        mesh_n = 1.0
    mw, mh = width / 2.0, height
    rate_n = (
        float(rate_override)
        if rate_override is not None and rate_override > 0
        else default_mesh_rate(mtype)
    )
    area_sqft = _mm_to_sft(mw, mh)
    amount_unit = round(area_sqft * rate_n, 2)
    amount = round(amount_unit * qty, 2)
    name = _pick(line, "meshName", "mesh_name")
    grade = "premium" if mtype == "premium" else "standard"
    label_bits = [
        MESH_TYPES.get(mtype, "Standard mesh"),
        f"{int(mesh_n)} shutter" + ("s" if int(mesh_n) != 1 else ""),
        f"(W/2)×H {mw:g}×{mh:g} mm",
    ]
    if name:
        label_bits.append(str(name))
    if rate_n > 0 and area_sqft:
        label_bits.append(f"₹{amount:,.2f} ({area_sqft:g} sft × ₹{rate_n:g})")
    return {
        "kind": "intrack",
        "type": mtype,
        "typeLabel": MESH_TYPES.get(mtype, mtype.title()),
        "grade": grade,
        "placement": "half",
        "placementLabel": "Half window width × height",
        "collapseStyle": None,
        "widthMm": round(mw, 1),
        "heightMm": round(mh, 1),
        "areaSqft": area_sqft,
        "rate": rate_n,
        "qty": qty,
        "amountUnit": amount_unit,
        "amount": amount,
        "name": str(name) if name else None,
        "label": " · ".join(label_bits),
        "formula": "(window width / 2) × height",
        "meshShutters": int(mesh_n),
        "memberMm": MESH_MEMBER_MM,
    }


def mesh_addon_for_line(line: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return rolling / collapsible add-on only (sell row + SVG cue)."""
    fabric = mesh_fabric_for_line(line)
    if not fabric or fabric.get("kind") != "addon":
        return None
    return fabric


def mesh_addon_amount(line: Mapping[str, Any] | None) -> float:
    addon = mesh_addon_for_line(line)
    return float((addon or {}).get("amount") or 0.0)


def mesh_fabric_material_row(fabric: Mapping[str, Any]) -> dict[str, Any]:
    """Row for materials list / design_cost.mesh."""
    return {
        "kind": "mesh",
        "category": "mesh",
        "name": str(fabric.get("typeLabel") or "Mesh"),
        "catalogueName": str(fabric.get("typeLabel") or "Mesh"),
        "qty": round(float(fabric.get("areaSqft") or 0.0), 4),
        "pcs": 1,
        "unit": "sft",
        "unitRate": float(fabric.get("rate") or 0.0),
        "amount": float(fabric.get("amountUnit") or 0.0),
        "areaSft": float(fabric.get("areaSqft") or 0.0),
        "widthMm": fabric.get("widthMm"),
        "heightMm": fabric.get("heightMm"),
        "remarks": str(fabric.get("formula") or fabric.get("label") or ""),
        "formula": fabric.get("formula"),
        "type": fabric.get("type"),
        "grade": fabric.get("grade"),
    }


def mesh_addon_quote_line(addon: Mapping[str, Any]) -> dict[str, Any]:
    """Row for ``price.lines`` / ``quotationDetail.lines`` (per unit)."""
    return {
        "category": "mesh",
        "description": f"{addon.get('typeLabel')} {addon.get('widthMm'):g}×{addon.get('heightMm'):g} mm",
        "qty": round(float(addon.get("areaSqft") or 0.0), 4),
        "unit": "sqft",
        "rate": float(addon.get("rate") or 0.0),
        "amount": float(addon.get("amountUnit") or 0.0),
    }


def vent_fix_mesh_for_line(line: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Outside fix mesh for bathroom ventilator — ₹250/sft on vent area."""
    if not isinstance(line, Mapping):
        return None
    width = _num(line.get("widthMm") or line.get("width")) or 0.0
    height = _num(line.get("heightMm") or line.get("height")) or 0.0
    if width <= 0 or height <= 0:
        return None
    # Explicit off
    mesh_flag = line.get("mesh") if "mesh" in line else line.get("fixMesh", True)
    if mesh_flag is False or (
        isinstance(mesh_flag, str) and mesh_flag.strip().lower() in ("false", "no", "0", "off")
    ):
        return None
    rate_override = _num(line.get("meshRate") or line.get("fixMeshRate"))
    rate_n = float(rate_override) if rate_override is not None and rate_override > 0 else DEFAULT_MESH_RATES["vent_fix"]
    qty = _line_qty(line)
    area_sqft = _mm_to_sft(width, height)
    amount_unit = round(area_sqft * rate_n, 2)
    amount = round(amount_unit * qty, 2)
    return {
        "kind": "vent_fix",
        "type": "vent_fix",
        "typeLabel": "Fix mesh (outside)",
        "grade": None,
        "placement": "outside",
        "widthMm": round(width, 1),
        "heightMm": round(height, 1),
        "areaSqft": area_sqft,
        "rate": rate_n,
        "qty": qty,
        "amountUnit": amount_unit,
        "amount": amount,
        "label": f"Fix mesh (outside) · {width:g}×{height:g} mm · ₹{amount:,.2f} ({area_sqft:g} sft × ₹{rate_n:g})",
        "formula": "vent W × H (outside)",
        "memberMm": MESH_MEMBER_MM,
    }


def persist_mesh_addon_options(options: dict[str, Any], line: Mapping[str, Any], addon: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy the mesh add-on keys onto the persisted options blob."""
    options["meshType"] = mesh_type_of_line(line)
    fabric = addon or mesh_fabric_for_line(line)
    if fabric:
        options["meshType"] = fabric["type"]
        if fabric.get("grade"):
            options["meshGrade"] = fabric["grade"]
        if fabric.get("placement"):
            options["meshPlacement"] = fabric["placement"]
        if fabric.get("collapseStyle"):
            options["meshCollapseStyle"] = fabric["collapseStyle"]
        options["meshW"] = fabric["widthMm"]
        options["meshH"] = fabric["heightMm"]
        options["meshRate"] = fabric["rate"]
        options["meshAmount"] = fabric["amount"]
        options["mesh"] = True
    else:
        for k in ("meshPlacement", "meshW", "meshH", "meshRate", "meshAmount", "meshCollapseStyle", "meshGrade"):
            v = _pick(line, k)
            if v is not None:
                options[k] = v
            else:
                options.pop(k, None)
        options.pop("meshAmount", None)
    return options


def _addon_preview_rects(
    *,
    mtype: str,
    placement: str,
    collapse: str | None,
    bx0: float,
    by0: float,
    bx1: float,
    by1: float,
) -> list[dict[str, Any]]:
    """Bit-of-mesh preview rectangles + 38 mm members (model mm)."""
    band_w, band_h = bx1 - bx0, by1 - by0
    if band_w <= 0 or band_h <= 0:
        return []
    member = MESH_MEMBER_MM
    strip_w = min(_preview_band_mm(band_w), band_w * 0.35)
    strip_h = min(_preview_band_mm(band_h), band_h * 0.35)
    rects: list[dict[str, Any]] = []

    def _rect(x0: float, y0: float, x1: float, y1: float, *, member_orient: str, side: str) -> None:
        rects.append({
            "x0": round(x0, 2),
            "y0": round(y0, 2),
            "x1": round(x1, 2),
            "y1": round(y1, 2),
            "memberOrient": member_orient,
            "memberMm": member,
            "side": side,
            "inside": True,
        })

    if mtype == "rolling":
        side = "right" if placement == "right" else "left"
        if side == "left":
            _rect(bx0, by0, bx0 + strip_w, by1, member_orient="vertical", side="left")
        else:
            _rect(bx1 - strip_w, by0, bx1, by1, member_orient="vertical", side="right")
        return rects

    # Collapsible — inside the window
    if collapse == "top":
        _rect(bx0, by1 - strip_h, bx1, by1, member_orient="horizontal", side="top")
        return rects

    # Center opening — both sides
    _rect(bx0, by0, bx0 + strip_w, by1, member_orient="vertical", side="left")
    _rect(bx1 - strip_w, by0, bx1, by1, member_orient="vertical", side="right")
    return rects


def attach_mesh_addon_to_drawing(drawing: Any, addon: Mapping[str, Any] | None) -> None:
    """Stash add-on preview strips (model mm) on drawing metadata for SVG / PDF."""
    if drawing is None or not addon:
        return
    meta = dict(getattr(drawing, "metadata", None) or {})
    W = float(getattr(drawing, "width", 0) or 0)
    H = float(getattr(drawing, "height", 0) or 0)
    try:
        bx0 = float(meta.get("sliding_x0") or meta.get("shutter_inset") or 0.0)
        bx1 = float(meta.get("sliding_x1") or (W - float(meta.get("shutter_inset") or 0.0)))
        by0 = float(meta.get("sliding_y0") or meta.get("shutter_inset") or 0.0)
        by1 = float(meta.get("sliding_y1") or (H - float(meta.get("shutter_inset") or 0.0)))
    except (TypeError, ValueError):
        bx0, by0, bx1, by1 = 0.0, 0.0, W, H
    if bx1 <= bx0 or by1 <= by0:
        bx0, by0, bx1, by1 = 0.0, 0.0, W, H

    mtype = str(addon.get("type") or "rolling")
    placement = str(addon.get("placement") or "left")
    collapse = addon.get("collapseStyle")
    rects = _addon_preview_rects(
        mtype=mtype,
        placement=placement,
        collapse=str(collapse) if collapse else None,
        bx0=bx0, by0=by0, bx1=bx1, by1=by1,
    )
    # Backward-compat single rect = union / first strip
    if rects:
        x0 = min(r["x0"] for r in rects)
        y0 = min(r["y0"] for r in rects)
        x1 = max(r["x1"] for r in rects)
        y1 = max(r["y1"] for r in rects)
    else:
        x0, y0, x1, y1 = bx0, by0, bx1, by1

    meta["mesh_addon"] = {
        **dict(addon),
        "x0": round(x0, 2),
        "y0": round(y0, 2),
        "x1": round(x1, 2),
        "y1": round(y1, 2),
        "rects": rects,
        "memberMm": MESH_MEMBER_MM,
        "inside": True,
    }
    drawing.metadata = meta
