"""Mesh add-on — pleated / rolling mesh priced and printed separately.

The classic ``Sliding mesh shutter (wire, SS304)`` is a geometry feature (an
extra sash on its own track, see ``geometry_engine._build_shutters``). Pleated and
rolling mesh are *add-ons*: they do not change the window geometry or the track
count, they sit over the opening (whole window / one side / custom size) and
their amount (area × rate × qty) is added as a SEPARATE row to the line price.

Line / options keys: ``meshType`` (sliding | pleated | rolling),
``meshPlacement`` (full | left | right | custom), ``meshW`` / ``meshH`` (mm, custom),
``meshRate`` (₹ per sqft), ``meshAmount`` (persisted result).
"""

from __future__ import annotations

from typing import Any, Mapping

MESH_TYPES: dict[str, str] = {
    "sliding": "Sliding mesh shutter (wire, SS304)",
    "pleated": "Pleated mesh",
    "rolling": "Rolling mesh",
}
ADDON_MESH_TYPES = ("pleated", "rolling")
MESH_PLACEMENTS: dict[str, str] = {
    "full": "Whole window",
    "left": "Left side (one shutter width)",
    "right": "Right side (one shutter width)",
    "custom": "Custom size",
}
SQFT_PER_MM2 = 10.7639 / 1_000_000.0


def normalize_mesh_type(raw: Any) -> str:
    t = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not t:
        return "sliding"
    if "pleat" in t:
        return "pleated"
    if "roll" in t:
        return "rolling"
    return "sliding"


def normalize_mesh_placement(raw: Any) -> str:
    t = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if t in ("left", "left_side", "l"):
        return "left"
    if t in ("right", "right_side", "r"):
        return "right"
    if t in ("custom", "size", "custom_size"):
        return "custom"
    return "full"


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
        return "sliding"
    return normalize_mesh_type(_pick(line, "meshType", "mesh_type"))


def is_addon_mesh(line: Mapping[str, Any] | None) -> bool:
    return mesh_type_of_line(line) in ADDON_MESH_TYPES


def mesh_addon_for_line(line: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the resolved pleated / rolling mesh add-on for a cart line, or None.

    Active when ``meshType`` is pleated / rolling and mesh is applied (``mesh``
    truthy, a placement, a size or a rate is given).
    """
    if not isinstance(line, Mapping):
        return None
    mtype = mesh_type_of_line(line)
    if mtype not in ADDON_MESH_TYPES:
        return None
    mesh_flag = _pick(line, "mesh")
    placement_raw = _pick(line, "meshPlacement", "mesh_placement")
    rate = _num(_pick(line, "meshRate", "mesh_rate"))
    mw_in = _num(_pick(line, "meshW", "meshWidthMm", "mesh_w"))
    mh_in = _num(_pick(line, "meshH", "meshHeightMm", "mesh_h"))
    applied = bool(mesh_flag) or placement_raw not in (None, "") or rate is not None or bool(mw_in and mh_in)
    if mesh_flag is False or (isinstance(mesh_flag, str) and mesh_flag.strip().lower() in ("false", "no", "0", "off")):
        # Mesh explicitly switched off — stale placement / rate must not price a mesh.
        applied = False
    if not applied:
        return None

    width = _num(line.get("width")) or _num(_pick(line, "widthMm")) or 0.0
    height = _num(line.get("height")) or _num(_pick(line, "heightMm")) or 0.0
    placement = normalize_mesh_placement(placement_raw)
    glass_n = _num(_pick(line, "glassShutters", "glassCount")) or 0.0
    layout = line.get("layout") if isinstance(line.get("layout"), Mapping) else {}
    if glass_n <= 0 and isinstance(layout, Mapping):
        glass_n = _num(layout.get("glassCount")) or 0.0
    glass_n = max(int(glass_n), 1)

    if placement == "custom" and mw_in and mh_in and mw_in > 0 and mh_in > 0:
        mw, mh = float(mw_in), float(mh_in)
    elif placement in ("left", "right"):
        mw, mh = width / glass_n, height
    else:
        placement = "full" if placement != "custom" else "custom"
        mw, mh = width, height
        if placement == "custom":
            # custom chosen without a size → fall back to the whole window
            placement = "full"
    mw = max(float(mw or 0.0), 0.0)
    mh = max(float(mh or 0.0), 0.0)
    area_sqft = round(mw * mh * SQFT_PER_MM2, 4)
    try:
        qty = max(int(round(float(line.get("qty") or line.get("quantity") or 1))), 1)
    except (TypeError, ValueError):
        qty = 1
    rate_n = float(rate) if rate is not None and rate > 0 else 0.0
    amount_unit = round(area_sqft * rate_n, 2)
    amount = round(amount_unit * qty, 2)
    name = _pick(line, "meshName", "mesh_name")
    label_bits = [MESH_TYPES.get(mtype, mtype.title())]
    if placement != "custom":
        label_bits.append(MESH_PLACEMENTS.get(placement, placement).split(" (")[0].lower())
    label_bits.append(f"{mw:g}×{mh:g} mm")
    if name:
        label_bits.append(str(name))
    if rate_n > 0:
        label_bits.append(f"₹{amount:,.2f}" + (f" ({area_sqft:g} sft × ₹{rate_n:g})" if area_sqft else ""))
    return {
        "type": mtype,
        "typeLabel": MESH_TYPES.get(mtype, mtype.title()),
        "placement": placement,
        "placementLabel": MESH_PLACEMENTS.get(placement, placement),
        "widthMm": round(mw, 1),
        "heightMm": round(mh, 1),
        "areaSqft": area_sqft,
        "rate": rate_n,
        "qty": qty,
        "amountUnit": amount_unit,
        "amount": amount,
        "name": str(name) if name else None,
        "label": " · ".join(label_bits),
    }


def mesh_addon_amount(line: Mapping[str, Any] | None) -> float:
    addon = mesh_addon_for_line(line)
    return float((addon or {}).get("amount") or 0.0)


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


def persist_mesh_addon_options(options: dict[str, Any], line: Mapping[str, Any], addon: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy the mesh add-on keys onto the persisted options blob."""
    options["meshType"] = mesh_type_of_line(line)
    if addon:
        options["meshType"] = addon["type"]
        options["meshPlacement"] = addon["placement"]
        options["meshW"] = addon["widthMm"]
        options["meshH"] = addon["heightMm"]
        options["meshRate"] = addon["rate"]
        options["meshAmount"] = addon["amount"]
        options["mesh"] = True
    else:
        for k in ("meshPlacement", "meshW", "meshH", "meshRate", "meshAmount"):
            v = _pick(line, k)
            if v is not None:
                options[k] = v
            else:
                options.pop(k, None)
        options.pop("meshAmount", None)
    return options


def attach_mesh_addon_to_drawing(drawing: Any, addon: Mapping[str, Any] | None) -> None:
    """Stash the add-on rectangle (model mm) on drawing metadata for SVG / PDF."""
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
    placement = str(addon.get("placement") or "full")
    mw = float(addon.get("widthMm") or 0.0)
    mh = float(addon.get("heightMm") or 0.0)
    band_w, band_h = bx1 - bx0, by1 - by0
    if placement == "full":
        x0, x1, y0, y1 = bx0, bx1, by0, by1
    elif placement == "left":
        x0, x1, y0, y1 = bx0, min(bx0 + max(mw, 1.0), bx1), by0, by1
    elif placement == "right":
        x0, x1, y0, y1 = max(bx1 - max(mw, 1.0), bx0), bx1, by0, by1
    else:
        w = min(max(mw, 1.0), band_w)
        h = min(max(mh, 1.0), band_h)
        x0 = bx0 + (band_w - w) / 2.0
        x1 = x0 + w
        y0 = by0
        y1 = by0 + h
    meta["mesh_addon"] = {
        **dict(addon),
        "x0": round(x0, 2),
        "y0": round(y0, 2),
        "x1": round(x1, 2),
        "y1": round(y1, 2),
    }
    drawing.metadata = meta
