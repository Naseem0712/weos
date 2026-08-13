"""Shower partition — pricing + unified-canvas SVG (elevation + floor plan).

Gallery product (not a hardcoded-only SKU). Designs: straight / L / U.
Sliding 1+1 = half width fix + half sliding (marked on drawing + PDF).
Hardware defaults are overridable from Product Library setup.
"""

from __future__ import annotations

from typing import Any, Mapping
from xml.sax.saxutils import escape

from WEOS.factory.fmt import mm_n, money_n
from WEOS.factory.geometry import (
    casement_hinge_svg,
    hinge_capsule_size_mm,
    hinge_centers_mm,
    hinge_gap_axis,
)

MM_PER_FT = 304.8
SQMM_PER_SQFT = 92903.04

DEFAULT_COLOURS = ("matt_black", "brush_gold", "gold", "grey", "rose_gold")
DEFAULT_VERT = "16×45 mm slim"
DEFAULT_HORIZ = "16×45 mm"
DEFAULT_CHOKHAT = "22×50 mm"
DEFAULT_HANDLE = "D-type"
DEFAULT_HINGE = "casement"
DOOR_BOTTOM_CLEAR_MM = 20.0


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _s(value: Any, default: str = "") -> str:
    t = "" if value is None else str(value).strip()
    return t or default


def _bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _shape(cfg: Mapping[str, Any]) -> str:
    raw = _s(cfg.get("shape") or cfg.get("design") or cfg.get("designType"), "straight").lower()
    if raw in ("l", "l_shape", "l-shape", "corner"):
        return "L"
    if raw in ("u", "u_shape", "u-shape"):
        return "U"
    return "straight"


def _operation(cfg: Mapping[str, Any]) -> str:
    raw = _s(cfg.get("operation") or cfg.get("openingType") or cfg.get("type"), "sliding").lower()
    if raw in ("hinged", "hinge", "openable", "door", "swing"):
        return "hinged"
    if raw in ("fix", "fixed", "frameless_fix"):
        return "fixed"
    return "sliding"


def _frame_kind(cfg: Mapping[str, Any]) -> str:
    """Shower elevation chrome: ``frameless`` (glass + track/jambs) or ``profile`` (16×45 sashes)."""
    raw = _s(cfg.get("frameKind") or cfg.get("frameType") or cfg.get("frameMode"), "").lower().replace("-", "_")
    if raw in ("frameless", "no_frame", "glass", "unframed"):
        return "frameless"
    if raw in ("profile", "framed", "frame", "aluminium", "aluminum", "sash"):
        return "profile"
    if "frameless" in cfg and _bool(cfg.get("frameless"), False):
        return "frameless"
    return "profile"


def _door_side(cfg: Mapping[str, Any]) -> str:
    """Door / sliding-leaf side: left or right (default right)."""
    raw = _s(
        cfg.get("doorSide") or cfg.get("slidingSide") or cfg.get("slideSide"),
        "right",
    ).lower()
    return "left" if raw == "left" else "right"


def _handle_side(cfg: Mapping[str, Any], *, door_side: str) -> str:
    """Handle stile. Independent for hinged; sliding defaults to door side."""
    raw = _s(cfg.get("handleSide"), "").lower()
    if raw in ("left", "right"):
        return raw
    return door_side if door_side in ("left", "right") else "right"


def _hinge_side(handle_side: str) -> str:
    """Hinges always sit on the opposite vertical from the handle."""
    return "left" if handle_side == "right" else "right"


def _front_role(cfg: Mapping[str, Any]) -> str:
    """Foreground leaf at the meeting: operable door/slide, or fix."""
    raw = _s(cfg.get("frontPanel") or cfg.get("frontLeaf"), "").lower()
    if raw in ("fix", "fixed", "back"):
        return "fix"
    return "door"


def ensure_shower_dims(
    cfg: Mapping[str, Any] | None,
    *,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, Any]:
    out = dict(cfg or {})
    if _f(out.get("widthMm") or out.get("width")) <= 0:
        for cand in (width, out.get("width")):
            v = _f(cand)
            if v > 0:
                out["widthMm"] = v
                break
    if _f(out.get("heightMm") or out.get("height")) <= 0:
        for cand in (height, out.get("height")):
            v = _f(cand)
            if v > 0:
                out["heightMm"] = v
                break
    return out


def format_shower_description(q: Mapping[str, Any] | None = None, cfg: Mapping[str, Any] | None = None) -> str:
    q = q if isinstance(q, Mapping) else {}
    cfg = cfg if isinstance(cfg, Mapping) else {}
    shape = _s(q.get("shape") or cfg.get("shape"), "straight")
    op = _s(q.get("operation") or cfg.get("operation"), "sliding")
    w = q.get("widthMm") or cfg.get("widthMm") or 0
    h = q.get("heightMm") or cfg.get("heightMm") or 0
    glass = _s(q.get("glassLabel") or cfg.get("glassLabel"))
    if not glass:
        thk = q.get("glassThicknessMm") or cfg.get("glassThicknessMm")
        col = q.get("glassColour") or cfg.get("glassColour") or ""
        glass = " ".join(str(x) for x in (f"{thk} mm" if thk else "", col) if x).strip()
    bits = ["Shower partition", shape, op, f"{mm_n(w)}×{mm_n(h)} mm"]
    fk = _s(q.get("frameKind") or cfg.get("frameKind"), "frameless" if q.get("frameless") or cfg.get("frameless") else "profile")
    if fk:
        bits.append(fk)
    if glass:
        bits.append(glass)
    return " · ".join(str(b) for b in bits if b)


def _panel_plan(cfg: Mapping[str, Any], *, width_mm: float, depth_a: float, depth_b: float) -> list[dict[str, Any]]:
    """Elevation panels + footprint segments for straight / L / U."""
    shape = _shape(cfg)
    op = _operation(cfg)
    door_side = _door_side(cfg)
    height = _f(cfg.get("heightMm") or cfg.get("height"), 2000.0)

    def pane(role: str, w: float, *, wall: str = "front", label: str | None = None) -> dict[str, Any]:
        return {
            "role": role,
            "label": label or ("FIX" if role == "fix" else ("SLIDE" if role == "sliding" else "OPEN")),
            "widthMm": mm_n(w),
            "heightMm": mm_n(height),
            "wall": wall,
        }

    panels: list[dict[str, Any]] = []
    if op == "sliding":
        # 1+1 — half fix, half sliding on the front run.
        half = max(width_mm / 2.0, 1.0)
        if door_side == "left":
            panels.append(pane("sliding", half, label="SLIDE"))
            panels.append(pane("fix", half, label="FIX"))
        else:
            panels.append(pane("fix", half, label="FIX"))
            panels.append(pane("sliding", half, label="SLIDE"))
    elif op == "hinged":
        door_w = _f(cfg.get("doorWidthMm") or cfg.get("doorWidth"), width_mm * 0.55)
        door_w = min(max(door_w, 400.0), max(width_mm - 80.0, 400.0))
        fix_w = max(width_mm - door_w, 0.0)
        if door_side == "left":
            panels.append(pane("openable", door_w, label="OPEN"))
            if fix_w > 20:
                panels.append(pane("fix", fix_w, label="FIX"))
        else:
            if fix_w > 20:
                panels.append(pane("fix", fix_w, label="FIX"))
            panels.append(pane("openable", door_w, label="OPEN"))
    else:
        panels.append(pane("fix", width_mm, label="FIX"))

    # L / U returns — treat as fix glass unless user marks otherwise.
    if shape == "L" and depth_a > 0:
        panels.append(pane("fix", depth_a, wall="return_a", label="FIX (L)"))
    elif shape == "U":
        if depth_a > 0:
            panels.append(pane("fix", depth_a, wall="return_l", label="FIX (L)"))
        if depth_b > 0:
            panels.append(pane("fix", depth_b, wall="return_r", label="FIX (R)"))
    return panels


def compute_shower(cfg: Mapping[str, Any]) -> dict[str, Any]:
    cfg = dict(cfg or {})
    width_mm = _f(cfg.get("widthMm") or cfg.get("width"), 1200.0)
    height_mm = _f(cfg.get("heightMm") or cfg.get("height"), 2000.0)
    depth_a = _f(cfg.get("depthMm") or cfg.get("legAMm") or cfg.get("returnMm"), 0.0)
    depth_b = _f(cfg.get("depthBMm") or cfg.get("legBMm"), depth_a if _shape(cfg) == "U" else 0.0)
    shape = _shape(cfg)
    op = _operation(cfg)
    if width_mm <= 0:
        width_mm = 1200.0
    if height_mm <= 0:
        height_mm = 2000.0
    if shape == "L" and depth_a <= 0:
        depth_a = 900.0
    if shape == "U":
        if depth_a <= 0:
            depth_a = 800.0
        if depth_b <= 0:
            depth_b = 800.0

    colour = _s(cfg.get("colour") or cfg.get("systemColor"), "matt_black")
    frame_kind = _frame_kind(cfg)
    frameless = frame_kind == "frameless"
    vert_name = _s(cfg.get("verticalProfile") or cfg.get("profileVertical"), DEFAULT_VERT)
    horiz_name = _s(cfg.get("horizontalProfile") or cfg.get("profileHorizontal"), DEFAULT_HORIZ)
    chokhat_name = _s(cfg.get("chokhat") or cfg.get("frameSize"), DEFAULT_CHOKHAT)
    chokhat_side = _s(cfg.get("chokhatSide") or cfg.get("frameSideSize"), "")
    handle_on = _bool(cfg.get("handle") if not isinstance(cfg.get("handle"), Mapping) else True, True)
    handle_cfg = cfg.get("handle") if isinstance(cfg.get("handle"), Mapping) else {}
    if isinstance(cfg.get("handle"), Mapping):
        handle_on = _bool(handle_cfg.get("enabled"), True)
    handle_name = _s(handle_cfg.get("name") or cfg.get("handleName"), DEFAULT_HANDLE)
    handle_type = _s(handle_cfg.get("type") or cfg.get("handleType"), "d_type")
    lock_on = _bool(cfg.get("lock") if not isinstance(cfg.get("lock"), Mapping) else True, False)
    lock_cfg = cfg.get("lock") if isinstance(cfg.get("lock"), Mapping) else {}
    if isinstance(cfg.get("lock"), Mapping):
        lock_on = _bool(lock_cfg.get("enabled"), False)
    lock_name = _s(lock_cfg.get("name") or cfg.get("lockName"), "Lock")
    hw_brand = _s(cfg.get("hardwareBrand") or cfg.get("brand"), "")
    hw_origin = _s(cfg.get("hardwareOrigin") or cfg.get("origin"), "")  # indian | imported
    gi_per_door = max(_i(cfg.get("giConnectorsPerDoor"), 4), 0)
    hinge_count = min(max(_i(cfg.get("hingesPerDoor") or cfg.get("hingeCount"), 3), 2), 6)
    hinge_type = _s(cfg.get("hingeType"), DEFAULT_HINGE)
    door_side = _door_side(cfg)
    handle_side = _handle_side(cfg, door_side=door_side)
    hinge_side = _hinge_side(handle_side) if op == "hinged" else None
    sale_unit = _s(cfg.get("saleUnit"), "sqft").lower()
    if sale_unit in ("sft", "sq.ft", "sq.ft."):
        sale_unit = "sqft"
    if sale_unit in ("nos", "pcs", "each", "pc"):
        sale_unit = "opening"

    glass_thk = _f(cfg.get("glassThicknessMm") or cfg.get("glassThk"), 8.0)
    glass_colour = _s(cfg.get("glassColour") or cfg.get("glassColor"), "clear")
    glass_kind = _s(cfg.get("glassKind") or cfg.get("glassMakeup"), "tinted")
    if "flut" in glass_kind:
        glass_kind = "fluted"
    elif glass_kind in ("tint", "tuff", "toughened"):
        glass_kind = "tinted"
    glass_tough = _bool(cfg.get("glassToughened"), True)
    glass_label = _s(
        cfg.get("glassLabel") or cfg.get("glassName"),
        f"{glass_kind} {glass_thk:g} mm {glass_colour}" + (" tuff" if glass_tough else ""),
    )
    r_glass = _f(cfg.get("glassRatePerSqft") or (cfg.get("rates") or {}).get("glassPerSqft"), 0.0)

    panels = _panel_plan(cfg, width_mm=width_mm, depth_a=depth_a, depth_b=depth_b)
    area_sqmm = sum(_f(p.get("widthMm")) * _f(p.get("heightMm")) for p in panels)
    area_sqft = area_sqmm / SQMM_PER_SQFT
    doors = sum(1 for p in panels if p.get("role") in ("sliding", "openable"))
    fix_n = sum(1 for p in panels if p.get("role") == "fix")
    slide_n = sum(1 for p in panels if p.get("role") == "sliding")
    open_n = sum(1 for p in panels if p.get("role") == "openable")

    # Linear lengths (mm) for profiles
    vert_len_mm = height_mm * (2 + max(len(panels) - 1, 0))  # stiles at joints
    if frameless:
        vert_len_mm = height_mm * max(fix_n + slide_n + open_n, 1)
    horiz_len_mm = 0.0
    if op == "sliding":
        slide_w = sum(_f(p.get("widthMm")) for p in panels if p.get("role") == "sliding")
        horiz_len_mm = slide_w * 2.0  # top + bottom on sliding only
    chokhat_len_mm = 0.0 if frameless else (2.0 * height_mm + width_mm)

    rates = cfg.get("rates") if isinstance(cfg.get("rates"), Mapping) else {}
    r_vert = _f(rates.get("verticalPerRft") or cfg.get("verticalRate"), 0.0)
    r_horiz = _f(rates.get("horizontalPerRft") or cfg.get("horizontalRate"), 0.0)
    r_chok = _f(rates.get("chokhatPerRft") or cfg.get("chokhatRate"), 0.0)
    r_gi = _f(rates.get("giConnectorPerPc") or cfg.get("giRate"), 0.0)
    r_track = _f(rates.get("trackPerRft") or cfg.get("trackRate"), 0.0)
    r_cover = _f(rates.get("coverPlatePerRft") or cfg.get("coverRate"), 0.0)
    r_handle = _f(rates.get("handlePerPc") or cfg.get("handleRate"), 0.0)
    r_lock = _f(rates.get("lockPerPc") or cfg.get("lockRate"), 0.0)
    r_hinge = _f(rates.get("hingePerPc") or cfg.get("hingeRate"), 0.0)

    items: list[dict[str, Any]] = []

    def add(key: str, label: str, qty: float, unit: str, rate: float, **extra: Any) -> None:
        if qty <= 0:
            return
        row = {
            "key": key,
            "label": label,
            "qty": round(qty, 3),
            "unit": unit,
            "rate": money_n(rate),
            "amount": money_n(qty * rate),
            "color": colour,
        }
        row.update({k: v for k, v in extra.items() if v not in (None, "")})
        items.append(row)

    if area_sqft > 0:
        add("glass", glass_label, round(area_sqft, 3), "sqft", r_glass, sizeMm=f"{glass_thk:g} mm", glassColour=glass_colour)
    vert_rft = vert_len_mm / MM_PER_FT
    add("vertical", f"Vertical profile · {vert_name}", round(vert_rft, 3), "rft", r_vert, sizeMm=vert_name)
    if horiz_len_mm > 0:
        add("horizontal", f"Top/bottom slim · {horiz_name} (sliding only)", round(horiz_len_mm / MM_PER_FT, 3), "rft", r_horiz, sizeMm=horiz_name)
    if chokhat_len_mm > 0:
        side_bit = f" · side {chokhat_side}" if chokhat_side else ""
        add("chokhat", f"Chokhat / frame · {chokhat_name}{side_bit}", round(chokhat_len_mm / MM_PER_FT, 3), "rft", r_chok, sizeMm=chokhat_name)
    if doors and gi_per_door:
        add("giConnector", f"GI connectors · {gi_per_door}/door", doors * gi_per_door, "pc", r_gi)
    if op == "sliding":
        slide_w = sum(_f(p.get("widthMm")) for p in panels if p.get("role") == "sliding")
        add("track", "Sliding track (top)", round(slide_w / MM_PER_FT, 3), "rft", r_track)
        add("coverPlate", "Track cover plate (top)", round(slide_w / MM_PER_FT, 3), "rft", r_cover)
    if handle_on and doors:
        add("handle", f"Handle · {handle_name}", doors, "pc", r_handle, handleType=handle_type)
    if lock_on and doors:
        add("lock", f"Lock · {lock_name}", doors, "pc", r_lock)
    if op == "hinged" and not frameless and doors:
        add("hinge", f"{hinge_type.title()} hinges · {hinge_count}/door", doors * hinge_count, "pc", r_hinge)

    extras_in = cfg.get("extras") if isinstance(cfg.get("extras"), (list, tuple)) else []
    extras_total = 0.0
    extras: list[dict[str, Any]] = []
    for ex in extras_in:
        if not isinstance(ex, Mapping):
            continue
        amt = _f(ex.get("amount"))
        extras.append({"name": _s(ex.get("name"), "Extra"), "amount": money_n(amt)})
        extras_total += amt

    bom_total = sum(_f(it.get("amount")) for it in items) + extras_total
    qty = max(_i(cfg.get("qty") or cfg.get("quantity"), 1), 1)
    if sale_unit == "opening":
        billable = float(qty)
    else:
        billable = round(area_sqft * qty, 4)
    manual = cfg.get("manualRatePerUnit")
    if manual in (None, ""):
        manual = cfg.get("sellingRate")
    manual_rate = _f(manual) if manual not in (None, "") else None
    if manual_rate is not None and manual_rate <= 0:
        manual_rate = None
    # Cascade fallback: bom / billable when no manual rate.
    cascade_rate = round(bom_total / max(area_sqft, 0.001), 2) if sale_unit != "opening" else round(bom_total, 2)
    selling_per_unit = manual_rate if manual_rate is not None else cascade_rate
    selling_total = round(selling_per_unit * (billable if sale_unit != "opening" else float(qty)) + extras_total, 2)
    if sale_unit == "opening":
        selling_total = round(selling_per_unit * qty + extras_total, 2)

    footprint = {"kind": shape, "frontMm": mm_n(width_mm)}
    if shape == "L":
        footprint["returnMm"] = mm_n(depth_a)
    elif shape == "U":
        footprint["leftMm"] = mm_n(depth_a)
        footprint["rightMm"] = mm_n(depth_b)

    return {
        "shape": shape,
        "designType": shape,
        "operation": op,
        "slidingFormat": "1+1" if op == "sliding" else None,
        "slidingSide": door_side if op == "sliding" else None,
        "doorSide": door_side,
        "handleSide": handle_side if handle_on and op in ("sliding", "hinged") else None,
        "hingeSide": hinge_side,
        "widthMm": mm_n(width_mm),
        "heightMm": mm_n(height_mm),
        "depthMm": mm_n(depth_a) if shape in ("L", "U") else None,
        "depthBMm": mm_n(depth_b) if shape == "U" else None,
        "colour": colour,
        "frameKind": frame_kind,
        "frameless": frameless,
        "verticalProfile": vert_name,
        "horizontalProfile": horiz_name,
        "chokhat": None if frameless else chokhat_name,
        "chokhatSide": chokhat_side or None,
        "glassThicknessMm": glass_thk,
        "glassColour": glass_colour,
        "glassKind": glass_kind,
        "glassToughened": glass_tough,
        "glassLabel": glass_label,
        "handle": handle_on,
        "handleName": handle_name if handle_on else None,
        "handleType": handle_type if handle_on else None,
        "lock": lock_on,
        "lockName": lock_name if lock_on else None,
        "hardwareBrand": hw_brand or None,
        "hardwareOrigin": hw_origin or None,
        "hingesPerDoor": hinge_count if op == "hinged" and not frameless else None,
        "hingeCount": hinge_count if op == "hinged" and not frameless else None,
        "hingeType": hinge_type if op == "hinged" and not frameless else None,
        "giConnectorsPerDoor": gi_per_door,
        "panels": panels,
        "doorCount": doors,
        "fixCount": fix_n,
        "slideCount": slide_n,
        "openableCount": open_n,
        "areaSqft": round(area_sqft, 4),
        "saleUnit": sale_unit,
        "billableQty": billable,
        "items": items,
        "bomDetails": items,
        "extras": extras,
        "extrasTotal": money_n(extras_total),
        "bomTotal": money_n(bom_total),
        "manualRatePerUnit": money_n(manual_rate) if manual_rate is not None else None,
        "sellingPerUnit": money_n(selling_per_unit),
        "sellingTotal": money_n(selling_total),
        "footprint": footprint,
        "qty": qty,
    }


def _frame_d(x: float, y: float, w: float, h: float, t: float, omit_side: str | None) -> str:
    x1, y1 = x + w, y + h
    xi0, yi0, xi1, yi1 = x + t, y + t, x1 - t, y1 - t
    if omit_side == "right":
        return (
            f"M {x1:.1f},{y:.1f} L {x:.1f},{y:.1f} L {x:.1f},{y1:.1f} L {x1:.1f},{y1:.1f} "
            f"L {x1:.1f},{yi1:.1f} L {xi0:.1f},{yi1:.1f} L {xi0:.1f},{yi0:.1f} L {x1:.1f},{yi0:.1f} Z"
        )
    if omit_side == "left":
        return (
            f"M {x:.1f},{y:.1f} L {x1:.1f},{y:.1f} L {x1:.1f},{y1:.1f} L {x:.1f},{y1:.1f} "
            f"L {x:.1f},{yi1:.1f} L {xi1:.1f},{yi1:.1f} L {xi1:.1f},{yi0:.1f} L {x:.1f},{yi0:.1f} Z"
        )
    return (
        f"M {x:.1f},{y:.1f} L {x1:.1f},{y:.1f} L {x1:.1f},{y1:.1f} L {x:.1f},{y1:.1f} Z "
        f"M {xi0:.1f},{yi0:.1f} L {xi0:.1f},{yi1:.1f} L {xi1:.1f},{yi1:.1f} L {xi1:.1f},{yi0:.1f} Z"
    )


def _panel_frame(
    parts: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    t: float,
    stroke: str,
    sw: float,
    *,
    tag: str = "frame",
    omit_side: str | None = None,
    skip_miters: frozenset[str] | set[str] | None = None,
    meeting: bool = False,
    bottom_clear: bool = False,
) -> None:
    """Aluminium leaf: filled ring + 45° miters. Back leaf omits meeting stile / miters."""
    t = min(max(t, 2.4), w / 2.4, h / 2.4)
    skip = set(skip_miters or ())
    if omit_side == "right":
        skip.update(("tr", "br"))
    elif omit_side == "left":
        skip.update(("tl", "bl"))
    d = _frame_d(x, y, w, h, t, omit_side)
    extra = ' data-meeting-stile="1"' if meeting else ""
    if bottom_clear:
        extra += f' data-bottom-clear-mm="{int(DOOR_BOTTOM_CLEAR_MM)}"'
    parts.append(
        f'<path d="{d}" fill="#f2f2f3" fill-rule="evenodd" stroke="{stroke}" '
        f'stroke-width="{sw:.2f}" stroke-linejoin="miter" stroke-miterlimit="1.25" '
        f'stroke-linecap="butt" data-{tag}="1"{extra}/>'
    )
    x1, y1 = x + w, y + h
    corners = {
        "tl": (x, y, x + t, y + t),
        "tr": (x1, y, x1 - t, y + t),
        "br": (x1, y1, x1 - t, y1 - t),
        "bl": (x, y1, x + t, y1 - t),
    }
    for key, (x0, y0, xi, yi) in corners.items():
        if key in skip:
            continue
        meet_flag = ' data-meeting-miter="1"' if meeting else ""
        parts.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{xi:.1f}" y2="{yi:.1f}" '
            f'stroke="{stroke}" stroke-width="{sw:.2f}" data-miter="1"{meet_flag}"/>'
        )


def _u_chokhat_d(x: float, y: float, w: float, h: float, t: float) -> str:
    """Single U path (open at floor) so head/jamb strokes do not double at corners."""
    x1, y1 = x + w, y + h
    xi0, yi0, xi1 = x + t, y + t, x1 - t
    return (
        f"M {x:.1f},{y1:.1f} L {x:.1f},{y:.1f} L {x1:.1f},{y:.1f} L {x1:.1f},{y1:.1f} "
        f"L {xi1:.1f},{y1:.1f} L {xi1:.1f},{yi0:.1f} L {xi0:.1f},{yi0:.1f} L {xi0:.1f},{y1:.1f} Z"
    )


def _u_chokhat(
    parts: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    t: float,
    stroke: str,
    sw: float,
) -> None:
    """Hinged chokhat: L+T+R as one 45°-mitered U. No bottom member, no extra corner stroke."""
    t = min(max(t, 2.8), w / 2.8, h / 3.2)
    parts.append(
        f'<path d="{_u_chokhat_d(x, y, w, h, t)}" fill="#e6e6e8" fill-rule="evenodd" '
        f'stroke="{stroke}" stroke-width="{sw:.2f}" stroke-linejoin="miter" stroke-miterlimit="1.2" '
        f'stroke-linecap="butt" data-chokhat="1" data-chokhat-side="u" data-chokhat-overlap="1"/>'
    )
    parts.append(
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x + t:.1f}" y2="{y + t:.1f}" '
        f'stroke="{stroke}" stroke-width="{sw:.2f}" data-miter="1" data-chokhat-miter="45"/>'
    )
    parts.append(
        f'<line x1="{x + w:.1f}" y1="{y:.1f}" x2="{x + w - t:.1f}" y2="{y + t:.1f}" '
        f'stroke="{stroke}" stroke-width="{sw:.2f}" data-miter="1" data-chokhat-miter="45"/>'
    )


def _d_handle_on_glass(
    parts: list[str],
    stile_inner_x: float,
    y_mid: float,
    h: float,
    *,
    side: str,
) -> None:
    """Vertical cylindrical D-pull on the glass near the free edge (not a flat oval blob)."""
    rod_w = max(min(h * 0.11, 6.0), 3.4)
    rod_h = max(h, 24.0)
    y0 = y_mid - rod_h / 2.0
    if side == "right":
        x0 = stile_inner_x - rod_w - 1.0
    else:
        x0 = stile_inner_x + 1.0
    cx = x0 + rod_w / 2.0
    parts.append(
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{rod_w:.1f}" height="{rod_h:.1f}" '
        f'rx="{rod_w / 2.0:.1f}" fill="#e8e8ea" stroke="#111" stroke-width="0.65" '
        f'data-handle="1" data-handle-side="{side}" data-handle-kind="d-cylinder"/>'
    )
    hx = cx - rod_w * 0.18
    parts.append(
        f'<line x1="{hx:.1f}" y1="{y0 + 2.0:.1f}" x2="{hx:.1f}" y2="{y0 + rod_h - 2.0:.1f}" '
        f'stroke="#111" stroke-width="0.55" opacity="0.55" data-handle="1"/>'
    )


def _slide_wheel_connectors(
    parts: list[str],
    leaf_x: float,
    leaf_w: float,
    track_bot_y: float,
    stroke: str,
    sw: float,
) -> None:
    """Two circular rollers + small brackets on the sliding leaf, sitting on the header."""
    if leaf_w < 12.0:
        return
    inset = min(max(leaf_w * 0.20, 14.0), leaf_w * 0.34)
    xs = [leaf_x + inset, leaf_x + leaf_w - inset]
    r = max(min(leaf_w * 0.038, 7.8), 4.8)
    br_w = max(r * 0.78, 3.2)
    br_h = max(r * 1.25, 5.2)
    for cx in xs:
        parts.append(
            f'<rect x="{cx - br_w / 2:.1f}" y="{track_bot_y:.1f}" width="{br_w:.1f}" height="{br_h:.1f}" '
            f'rx="0.7" fill="#ececee" stroke="{stroke}" stroke-width="{sw:.2f}" '
            f'data-wheel-bracket="1"/>'
        )
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{track_bot_y:.1f}" r="{r:.1f}" fill="#f6f6f7" '
            f'stroke="{stroke}" stroke-width="{max(sw, 0.9):.2f}" data-wheel="1" data-roller="1"/>'
        )
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{track_bot_y:.1f}" r="{max(r * 0.28, 1.1):.1f}" fill="none" '
            f'stroke="{stroke}" stroke-width="{sw * 0.8:.2f}"/>'
        )


def _sliding_side_jambs(
    parts: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    t: float,
    stroke: str,
    sw: float,
) -> None:
    """Frameless sliding: vertical wall jambs (header already drawn separately)."""
    t = min(max(t, 3.2), w / 8.0)
    fill = "#e2e2e4"
    parts.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{t:.1f}" height="{h:.1f}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{sw:.2f}" data-jamb="left"/>'
    )
    parts.append(
        f'<rect x="{x + w - t:.1f}" y="{y:.1f}" width="{t:.1f}" height="{h:.1f}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{sw:.2f}" data-jamb="right"/>'
    )


def _sliding_bottom_guide(
    parts: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    stroke: str,
    sw: float,
) -> None:
    """Low bottom guide rail under frameless sliding glass."""
    h = max(h, 2.8)
    parts.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#e4e4e6" '
        f'stroke="{stroke}" stroke-width="{sw:.2f}" data-guide="bottom"/>'
    )


def _mortice_lock(
    parts: list[str],
    stile_x: float,
    stile_t: float,
    cy: float,
    *,
    glass_side: str,
) -> None:
    """Mortice lock: faceplate in the stile + case on the glass edge (not a lone dot)."""
    fp_w = max(min(stile_t * 0.72, 5.2), 2.6)
    fp_h = max(stile_t * 3.5, 15.0)
    fp_x = stile_x + (stile_t - fp_w) / 2.0
    parts.append(
        f'<rect x="{fp_x:.1f}" y="{cy - fp_h / 2:.1f}" width="{fp_w:.1f}" height="{fp_h:.1f}" rx="0.6" '
        f'fill="#ececec" stroke="#333" stroke-width="0.7" data-lock="1" data-lock-kind="mortice"/>'
    )
    case_w = max(stile_t * 1.25, 6.2)
    case_h = fp_h * 0.58
    if glass_side == "left":
        case_x = stile_x - case_w + stile_t * 0.28
        bolt_x = stile_x + stile_t
    else:
        case_x = stile_x + stile_t - stile_t * 0.28
        bolt_x = stile_x - 2.3
    parts.append(
        f'<rect x="{case_x:.1f}" y="{cy - case_h / 2:.1f}" width="{case_w:.1f}" height="{case_h:.1f}" rx="0.8" '
        f'fill="#f6f6f6" stroke="#333" stroke-width="0.75" data-lock="1"/>'
    )
    cyl_x = case_x + case_w / 2.0
    cyl_r = min(case_h, case_w) * 0.20
    parts.append(
        f'<circle cx="{cyl_x:.1f}" cy="{cy:.1f}" r="{cyl_r:.1f}" fill="none" stroke="#333" '
        f'stroke-width="0.65" data-lock="1"/>'
    )
    parts.append(f'<circle cx="{cyl_x:.1f}" cy="{cy:.1f}" r="0.7" fill="#333" data-lock="1"/>')
    bolt_h = max(case_h * 0.26, 2.4)
    parts.append(
        f'<rect x="{bolt_x:.1f}" y="{cy - bolt_h / 2:.1f}" width="2.3" height="{bolt_h:.1f}" '
        f'fill="#ddd" stroke="#333" stroke-width="0.5" data-lock="1"/>'
    )


def _casement_hinge(
    parts: list[str],
    cx: float,
    cy: float,
    stroke: str,
    *,
    from_top_mm: float,
    leaf_h_mm: float,
    stile_t_mm: float,
    scale: float,
) -> None:
    """Shared stadium hinge (round heads + horizontal barrel split)."""
    w_mm, h_mm = hinge_capsule_size_mm(leaf_h_mm, stile_t_mm)
    sc = max(float(scale), 1e-6)
    parts.append(
        casement_hinge_svg(
            cx,
            cy,
            w=max(w_mm * sc, 0.9),
            h=max(h_mm * sc, 4.0),
            stroke=stroke,
            stroke_width=0.55,
            extra_attrs=f'data-hinge-style="casement" data-hinge-from-top-mm="{from_top_mm:.0f}"',
        )
    )


def _open_arrow(parts: list[str], x0: float, x1: float, y: float, *, toward_left: bool) -> None:
    """Opening-direction arrow on the door glass."""
    if toward_left:
        xa, xb = max(x0, x1), min(x0, x1)
    else:
        xa, xb = min(x0, x1), max(x0, x1)
    parts.append(
        f'<line x1="{xa:.1f}" y1="{y:.1f}" x2="{xb:.1f}" y2="{y:.1f}" '
        f'stroke="#0b3d7a" stroke-width="0.9" marker-end="url(#shArrow)" '
        f'data-arrow="1" data-arrow-dir="{"left" if toward_left else "right"}"/>'
    )


def shower_svg(cfg: Mapping[str, Any], quote: Mapping[str, Any] | None = None) -> str:
    """Elevation + floor-plan SVG used by live canvas and customer PDF."""
    q = quote if isinstance(quote, Mapping) and quote else compute_shower(cfg)
    panels = list(q.get("panels") or [])
    if not panels:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="160">'
            '<text x="16" y="80" font-size="14">Shower — set width / height</text></svg>'
        )
    height = _f(q.get("heightMm"), 2000)
    front_panels = [p for p in panels if str(p.get("wall") or "front") == "front"]
    if not front_panels:
        front_panels = panels[:2] or panels
    front_w = sum(_f(p.get("widthMm")) for p in front_panels) or _f(q.get("widthMm"), 1200)
    shape = _s(q.get("shape"), "straight")
    colour = _s(q.get("colour"), "matt_black")
    op = _s(q.get("operation"), "sliding")
    frame_kind = _s(q.get("frameKind"), "").lower()
    if frame_kind not in ("frameless", "profile"):
        frame_kind = "frameless" if bool(q.get("frameless")) else "profile"
    frameless = frame_kind == "frameless"
    handle_on = bool(q.get("handle"))
    lock_on = bool(q.get("lock"))
    door_side = _s(q.get("doorSide"), _door_side(cfg if isinstance(cfg, Mapping) else {}))
    if door_side not in ("left", "right"):
        door_side = "right"
    handle_side = _s(q.get("handleSide"), "")
    if handle_side not in ("left", "right"):
        handle_side = _handle_side(cfg if isinstance(cfg, Mapping) else {}, door_side=door_side)
    hinge_side = _s(q.get("hingeSide"), _hinge_side(handle_side) if op == "hinged" else "")
    hinge_count = min(max(_i(q.get("hingeCount") or q.get("hingesPerDoor"), 3), 2), 6)
    stroke = "#111111"
    glass_fill = "rgba(170, 205, 230, 0.22)"
    slide_fill = "rgba(120, 170, 210, 0.30)"
    open_fill = "rgba(210, 190, 140, 0.26)"
    sw = 0.65  # slim 2D CAD strokes (keep dark colour, not beige-on-beige)

    # 16×45 mm slim leaf / 22×50 chokhat face in elevation
    frame_face_mm = 45.0
    chokhat_face_mm = 50.0
    chokhat_overlap_mm = 10.0
    track_h_mm = 36.0
    cover_h_mm = 14.0
    front_leaf = _front_role(cfg if isinstance(cfg, Mapping) else {})

    margin = 52.0
    elev_h = 340.0
    depth_a_mm = _f(q.get("depthMm"))
    depth_b_mm = _f(q.get("depthBMm"))
    max_return = max(depth_a_mm, depth_b_mm, 1.0)
    plan_scale = min(0.28, 200.0 / max(front_w, 1.0), 160.0 / max_return) if shape != "straight" else min(0.28, 220.0 / max(front_w, 1.0))
    fw = front_w * plan_scale
    da = depth_a_mm * plan_scale
    db = depth_b_mm * plan_scale
    plan_h = (max(da, db, 36.0) + 56.0) if shape != "straight" else 70.0

    scale = elev_h / max(height, 1.0)
    frame_t = max(frame_face_mm * scale, 3.2)
    chok_t = max(chokhat_face_mm * scale, 3.6)
    overlap_px = max(chokhat_overlap_mm * scale, 2.0)
    clear_px = max(DOOR_BOTTOM_CLEAR_MM * scale, 2.4)
    track_h = track_h_mm * scale
    cover_h = cover_h_mm * scale
    elev_w = max(front_w * scale, 180.0)
    # Track + cover sit immediately above the top rails (no floating gap).
    track_extra = (track_h + cover_h) if op == "sliding" else 0.0
    svg_w = max(elev_w, fw + 90.0) + margin * 2 + 70
    svg_h = 28.0 + track_extra + elev_h + 28.0 + plan_h + margin + 18.0

    meeting_stiles = 0 if frameless else (1 if op == "sliding" else (2 if op == "hinged" else 0))
    arrow_dir = "left" if door_side == "right" else "right"
    chok_bottom = "0" if (op == "hinged" and not frameless) else ""
    track_gap = "0" if op == "sliding" else ""
    hinge_style = "casement" if (op == "hinged" and not frameless) else ""
    wheel_n = 2 if op == "sliding" else 0
    glass_overlap_flag = "1" if (op == "sliding" and frameless) else "0"
    frame_label = "frameless" if frameless else "16×45 frame"

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w:.1f}" height="{svg_h:.1f}" '
        f'viewBox="0 0 {svg_w:.1f} {svg_h:.1f}" data-model-system="shower" '
        f'data-door-side="{door_side}" data-handle-side="{handle_side}" '
        f'data-hinge-side="{hinge_side or ""}" data-meeting-stiles="{meeting_stiles}" '
        f'data-arrow-dir="{arrow_dir}" data-front-role="{front_leaf}" '
        f'data-corner-markers="0" data-track-gap-px="{track_gap}" '
        f'data-chokhat-bottom="{chok_bottom}" data-hinge-style="{hinge_style}" '
        f'data-frame-kind="{frame_kind}" data-wheel-count="{wheel_n}" '
        f'data-glass-overlap="{glass_overlap_flag}" '
        f'data-door-bottom-clear-mm="{int(DOOR_BOTTOM_CLEAR_MM)}" '
        f'data-chokhat-overlap-mm="'
        f'{int(chokhat_overlap_mm) if op == "hinged" and not frameless else 0}">',
        f"<title>Shower {escape(shape)} {mm_n(front_w)}×{mm_n(height)}</title>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<defs><marker id="shArrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">'
        '<path d="M0,0 L7,3.5 L0,7 Z" fill="#0b3d7a"/></marker></defs>',
        f'<text x="{margin}" y="18" font-size="12" font-family="sans-serif" fill="#222">'
        f'Shower · {escape(shape)} · {escape(op)} · {escape(colour.replace("_", " "))}'
        f' · {escape(frame_label)}</text>',
    ]

    x0 = margin
    y_frame0 = 26.0 + track_extra
    # Top sliding track + cover plate — immediately above panel head rails
    if op == "sliding":
        ty = 26.0
        parts.append(
            f'<rect x="{x0:.1f}" y="{ty:.1f}" width="{elev_w:.1f}" height="{cover_h:.1f}" '
            f'fill="#dcdce0" stroke="{stroke}" stroke-width="{sw:.2f}" data-track="cover"/>'
        )
        parts.append(
            f'<text x="{x0 + elev_w / 2:.1f}" y="{ty + cover_h * 0.78:.1f}" text-anchor="middle" '
            f'font-size="8" font-family="sans-serif" fill="#555">COVER PLATE</text>'
        )
        parts.append(
            f'<rect x="{x0:.1f}" y="{ty + cover_h:.1f}" width="{elev_w:.1f}" height="{track_h:.1f}" '
            f'fill="#cfcfd4" stroke="{stroke}" stroke-width="{sw:.2f}" data-track="top"/>'
        )
        parts.append(
            f'<line x1="{x0 + 4:.1f}" y1="{ty + cover_h + track_h * 0.45:.1f}" '
            f'x2="{x0 + elev_w - 4:.1f}" y2="{ty + cover_h + track_h * 0.45:.1f}" '
            f'stroke="#666" stroke-width="0.6" stroke-dasharray="4 2"/>'
        )
        parts.append(
            f'<text x="{x0 + elev_w / 2:.1f}" y="{ty + cover_h + track_h * 0.82:.1f}" text-anchor="middle" '
            f'font-size="8" font-family="sans-serif" fill="#555">TOP TRACK</text>'
        )

    y0 = y_frame0
    # Panel x ranges (px) + floor-plan mm ranges
    panel_geom: list[tuple[dict[str, Any], float, float, float]] = []  # panel, x, pw, pw_mm
    x = x0
    mm_cursor = 0.0
    slide_plan_ranges: list[tuple[float, float, str]] = []
    for p in front_panels:
        pw_mm = _f(p.get("widthMm"))
        pw = pw_mm * scale
        role = str(p.get("role") or "fix")
        panel_geom.append((p, x, pw, pw_mm))
        if role == "sliding":
            slide_plan_ranges.append((mm_cursor, mm_cursor + pw_mm, "SLIDE"))
        elif role == "openable":
            slide_plan_ranges.append((mm_cursor, mm_cursor + pw_mm, "DOOR"))
        x += pw
        mm_cursor += pw_mm

    def _emit_panel_labels() -> None:
        for p, px_i, pw, pw_mm in panel_geom:
            parts.append(
                f'<text x="{px_i + pw / 2:.1f}" y="{y0 + elev_h / 2:.1f}" text-anchor="middle" '
                f'font-size="13" font-family="sans-serif" font-weight="700" fill="#0b3d7a">'
                f'{escape(str(p.get("label") or str(p.get("role") or "").upper()))}</text>'
            )
            parts.append(
                f'<text x="{px_i + pw / 2:.1f}" y="{y0 + elev_h + 14:.1f}" text-anchor="middle" '
                f'font-size="10" font-family="sans-serif" fill="#444">{mm_n(pw_mm)} mm</text>'
            )

    skip_early_glass = bool(frameless and op == "sliding" and len(panel_geom) >= 2)
    if not skip_early_glass:
        for p, px_i, pw, _pw_mm in panel_geom:
            role = str(p.get("role") or "fix")
            fill = slide_fill if role == "sliding" else (open_fill if role == "openable" else glass_fill)
            gh = elev_h
            if role in ("sliding", "openable"):
                gh = max(elev_h - clear_px, frame_t * 3)
            parts.append(
                f'<rect x="{px_i:.1f}" y="{y0:.1f}" width="{pw:.1f}" height="{gh:.1f}" '
                f'fill="{fill}" stroke="none"/>'
            )

    door_box: tuple[float, float, float, float] | None = None
    slide_g = next((g for g in panel_geom if str(g[0].get("role")) == "sliding"), None)
    fix_g = next((g for g in panel_geom if str(g[0].get("role")) == "fix"), None)
    jamb_t = max(chok_t * 0.70, 4.0)
    guide_h = max(track_h * 0.40, 3.6)
    glass_ov = max(frame_t * 1.20, 6.5)

    if frameless and op == "sliding" and len(panel_geom) >= 2:
        # Glass-on-glass 1+1: header + side jambs + low guide; no chunky 4-side sashes.
        inner_x = x0 + jamb_t
        inner_r = x0 + elev_w - jamb_t
        gh_fix = max(elev_h - guide_h, 8.0)
        gh_slide = max(gh_fix - clear_px, 8.0)
        slide_on_right = bool(slide_g and fix_g and slide_g[1] >= fix_g[1])
        junction = (fix_g[1] + fix_g[2]) if (fix_g and slide_on_right) else (
            slide_g[1] + slide_g[2] if slide_g else (x0 + elev_w / 2.0)
        )
        if slide_on_right:
            fx0, fw0 = inner_x, max(junction + glass_ov - inner_x, 8.0)
            sx0, sw0 = junction - glass_ov, max(inner_r - (junction - glass_ov), 8.0)
        else:
            sx0, sw0 = inner_x, max(junction + glass_ov - inner_x, 8.0)
            fx0, fw0 = junction - glass_ov, max(inner_r - (junction - glass_ov), 8.0)
        parts.append(
            f'<rect x="{fx0:.1f}" y="{y0:.1f}" width="{fw0:.1f}" height="{gh_fix:.1f}" '
            f'fill="{glass_fill}" stroke="none" data-glass="fix"/>'
        )
        parts.append(
            f'<rect x="{sx0:.1f}" y="{y0:.1f}" width="{sw0:.1f}" height="{gh_slide:.1f}" '
            f'fill="{slide_fill}" stroke="none" data-glass="slide" '
            f'data-bottom-clear-mm="{int(DOOR_BOTTOM_CLEAR_MM)}"/>'
        )
        parts.append(
            f'<line x1="{junction:.1f}" y1="{y0:.1f}" x2="{junction:.1f}" y2="{y0 + gh_slide:.1f}" '
            f'stroke="{stroke}" stroke-width="{sw * 0.7:.2f}" data-glass-meet="1"/>'
        )
        _sliding_side_jambs(parts, x0, y0, elev_w, elev_h, jamb_t, stroke, sw)
        _sliding_bottom_guide(parts, x0, y0 + elev_h - guide_h, elev_w, guide_h, stroke, sw)
        door_box = (sx0, y0, sw0, gh_slide)
        _emit_panel_labels()
    elif frameless:
        for p, px_i, pw, _pw_mm in panel_geom:
            parts.append(
                f'<rect x="{px_i:.1f}" y="{y0:.1f}" width="{pw:.1f}" height="{elev_h:.1f}" '
                f'fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
            )
        _emit_panel_labels()
    elif op == "sliding" and len(panel_geom) >= 2:
        # Two overlapping leaves; ONE visible meeting stile with 45° on the FRONT leaf only.
        junction = panel_geom[0][1] + panel_geom[0][2]
        stile_x = junction - frame_t / 2.0
        slide_on_right = bool(slide_g and fix_g and slide_g[1] >= fix_g[1])
        operable_is_front = front_leaf == "door"
        front_is_right = slide_on_right if operable_is_front else (not slide_on_right)
        slide_h = max(elev_h - clear_px, frame_t * 3)
        fix_h = elev_h
        if front_is_right:
            back_box = (x0, y0, max(stile_x + frame_t - x0, frame_t * 2), fix_h if slide_on_right else slide_h)
            fr_box = (stile_x, y0, max(x0 + elev_w - stile_x, frame_t * 2), slide_h if slide_on_right else fix_h)
            back_omit: str | None = "right"
        else:
            fr_box = (x0, y0, max(stile_x + frame_t - x0, frame_t * 2), slide_h if not slide_on_right else fix_h)
            back_box = (stile_x, y0, max(x0 + elev_w - stile_x, frame_t * 2), slide_h if slide_on_right else fix_h)
            back_omit = "left"
        _panel_frame(
            parts, *back_box, frame_t, stroke, sw, tag="back-frame", omit_side=back_omit,
            bottom_clear=(back_box[3] < elev_h - 0.5),
        )
        _panel_frame(
            parts, *fr_box, frame_t, stroke, sw, tag="front-frame", meeting=True,
            bottom_clear=(fr_box[3] < elev_h - 0.5),
        )
        door_box = fr_box if operable_is_front else back_box
        if slide_g and not operable_is_front:
            door_box = back_box
        elif slide_g:
            door_box = fr_box
        _emit_panel_labels()
    elif op == "hinged" and len(panel_geom) >= 2:
        # U-chokhat (L+T+R, no bottom) + both leaves; front leaf miters win at meeting.
        door_p = next((g for g in panel_geom if str(g[0].get("role")) == "openable"), None)
        fix_p = next((g for g in panel_geom if str(g[0].get("role")) == "fix"), None)
        inner_x = x0 + chok_t
        inner_r = x0 + elev_w - chok_t
        inner_y = y0 + chok_t
        floor_y = y0 + elev_h
        lap_meet = max(frame_t * 0.28, 1.4)
        operable_is_front = front_leaf == "door"
        fix_box: tuple[float, float, float, float] | None = None
        fix_skip: frozenset[str] = frozenset()
        door_skip: frozenset[str] = frozenset()
        if door_p and fix_p and door_side == "right":
            junction = door_p[1]
            fix_box = (inner_x, inner_y, max(junction - inner_x, frame_t * 2), floor_y - inner_y)
            door_x = junction
            door_y = inner_y - overlap_px
            door_r = inner_r + overlap_px
            door_box = (
                door_x, door_y, max(door_r - door_x, frame_t * 2),
                max(floor_y - door_y - clear_px, frame_t * 3),
            )
            if operable_is_front:
                dx0, dy0, dw0, dh0 = door_box
                door_box = (dx0 - lap_meet, dy0, dw0 + lap_meet, dh0)
                fix_skip = frozenset({"tr", "br"})
            else:
                fx0, fy0, fw0, fh0 = fix_box
                fix_box = (fx0, fy0, fw0 + lap_meet, fh0)
                door_skip = frozenset({"tl", "bl"})
        elif door_p and fix_p:
            junction = door_p[1] + door_p[2]
            door_x = inner_x - overlap_px
            door_y = inner_y - overlap_px
            door_box = (
                door_x, door_y, max(junction - door_x, frame_t * 2),
                max(floor_y - door_y - clear_px, frame_t * 3),
            )
            fix_box = (junction, inner_y, max(inner_r - junction, frame_t * 2), floor_y - inner_y)
            if operable_is_front:
                dx0, dy0, dw0, dh0 = door_box
                door_box = (dx0, dy0, dw0 + lap_meet, dh0)
                fix_skip = frozenset({"tl", "bl"})
            else:
                fx0, fy0, fw0, fh0 = fix_box
                fix_box = (fx0 - lap_meet, fy0, fw0 + lap_meet, fh0)
                door_skip = frozenset({"tr", "br"})
        if operable_is_front:
            if fix_box:
                _panel_frame(parts, *fix_box, frame_t, stroke, sw, tag="fix-frame", skip_miters=fix_skip)
            if door_box:
                _panel_frame(
                    parts, *door_box, frame_t, stroke, sw, tag="door-frame",
                    skip_miters=door_skip, meeting=True, bottom_clear=True,
                )
        else:
            if door_box:
                _panel_frame(
                    parts, *door_box, frame_t, stroke, sw, tag="door-frame",
                    skip_miters=door_skip, bottom_clear=True,
                )
            if fix_box:
                _panel_frame(parts, *fix_box, frame_t, stroke, sw, tag="fix-frame", skip_miters=fix_skip, meeting=True)
        _u_chokhat(parts, x0, y0, elev_w, elev_h, chok_t, stroke, sw)
        _emit_panel_labels()
    else:
        _panel_frame(parts, x0, y0, elev_w, elev_h, frame_t, stroke, sw, tag="frame")
        _emit_panel_labels()
        door_g = next((g for g in panel_geom if str(g[0].get("role")) in ("sliding", "openable")), None)
        if door_g:
            role_g = str(door_g[0].get("role") or "")
            dh_g = max(elev_h - clear_px, frame_t * 3) if role_g in ("sliding", "openable") else elev_h
            door_box = (door_g[1], y0, door_g[2], dh_g)

    # Arrow + D-handle + lock + casement hinges (hinged only) + sliding rollers
    door_geom = next(
        (g for g in panel_geom if str(g[0].get("role")) in ("sliding", "openable")),
        None,
    )
    if door_box is None and door_geom:
        role_g = str(door_geom[0].get("role") or "")
        dh_g = max(elev_h - clear_px, frame_t * 3) if role_g in ("sliding", "openable") else elev_h
        door_box = (door_geom[1], y0, door_geom[2], dh_g)
    if op == "sliding" and slide_g:
        wx0 = float(slide_g[1])
        ww = float(slide_g[2])
        if frameless:
            wx0 = max(wx0, x0 + jamb_t)
            ww = min(wx0 + ww, x0 + elev_w - jamb_t) - wx0
        _slide_wheel_connectors(parts, wx0, ww, y0, stroke, sw)
    if door_box:
        dx, dy, dw, dh = door_box
        if op in ("sliding", "hinged"):
            _open_arrow(
                parts,
                dx + dw * 0.22,
                dx + dw * 0.78,
                dy + dh * 0.70,
                toward_left=(door_side == "right"),
            )
        if handle_on:
            edge_in = 2.6 if frameless else 0.0
            if handle_side == "right":
                stile_x = dx + dw - (0.0 if frameless else frame_t)
                stile_inner = (dx + dw - edge_in) if frameless else stile_x
            else:
                stile_x = dx
                stile_inner = (dx + edge_in) if frameless else (dx + frame_t)
            hy = dy + dh * 0.48
            hh = max(dh * 0.16, 28.0)
            _d_handle_on_glass(parts, stile_inner, hy, hh, side=handle_side)
            if lock_on and not frameless:
                lock_cy = hy + hh * 0.55 + max(dh * 0.04, 8.0)
                _mortice_lock(
                    parts,
                    stile_x,
                    frame_t,
                    lock_cy,
                    glass_side=("left" if handle_side == "right" else "right"),
                )
        if op == "hinged" and not frameless:
            # Stile gap: sash outer vs chokhat inner (half on outer, half on door).
            chok_inner = (x0 + elev_w - chok_t) if hinge_side == "right" else (x0 + chok_t)
            hx_h = hinge_gap_axis(
                (dx + dw) if hinge_side == "right" else dx,
                chok_inner if len(panel_geom) >= 2 else None,
                toward_frame=1.0 if hinge_side == "right" else -1.0,
            )
            leaf_h_mm = dh / scale if scale else height
            for y_mm in hinge_centers_mm(leaf_h_mm, hinge_count):
                _casement_hinge(
                    parts,
                    hx_h,
                    dy + y_mm * scale,
                    stroke,
                    from_top_mm=y_mm,
                    leaf_h_mm=leaf_h_mm,
                    stile_t_mm=frame_face_mm,
                    scale=scale,
                )

    parts.append(
        f'<text x="{x0 + elev_w + 8:.1f}" y="{y_frame0 + elev_h / 2:.1f}" font-size="10" '
        f'font-family="sans-serif" fill="#8b1e1a">H {mm_n(height)}</text>'
    )

    # Floor plan — all sides dimensioned; door / SLIDE + track marked
    py = y_frame0 + elev_h + 32.0
    parts.append(
        f'<text x="{x0}" y="{py - 10:.1f}" font-size="11" font-family="sans-serif" fill="#555">'
        f'Floor plan · {escape(shape)}</text>'
    )
    px = x0 + (28.0 if shape != "straight" else 8.0)
    plan_y = py + 8.0
    psw = 0.80

    def _dim_h(x1: float, x2: float, y: float, text: str) -> None:
        parts.append(f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="#8b1e1a" stroke-width="0.6"/>')
        for xx in (x1, x2):
            parts.append(f'<line x1="{xx:.1f}" y1="{y - 3:.1f}" x2="{xx:.1f}" y2="{y + 3:.1f}" stroke="#8b1e1a" stroke-width="0.6"/>')
        parts.append(
            f'<text x="{(x1 + x2) / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle" font-size="10" '
            f'font-family="sans-serif" fill="#8b1e1a">{escape(text)}</text>'
        )

    def _dim_v(y1: float, y2: float, x: float, text: str, *, left: bool = True) -> None:
        parts.append(f'<line x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}" stroke="#8b1e1a" stroke-width="0.6"/>')
        for yy in (y1, y2):
            parts.append(f'<line x1="{x - 3:.1f}" y1="{yy:.1f}" x2="{x + 3:.1f}" y2="{yy:.1f}" stroke="#8b1e1a" stroke-width="0.6"/>')
        tx = x - 6 if left else x + 6
        parts.append(
            f'<text x="{tx:.1f}" y="{(y1 + y2) / 2:.1f}" text-anchor="{"end" if left else "start"}" '
            f'font-size="10" font-family="sans-serif" fill="#8b1e1a">{escape(text)}</text>'
        )

    def _mark_door_on_front(front_x0: float, front_y: float, front_len: float) -> None:
        if not slide_plan_ranges or front_w <= 0:
            return
        a0, a1, lab = slide_plan_ranges[0]
        t0 = front_x0 + (a0 / front_w) * front_len
        t1 = front_x0 + (a1 / front_w) * front_len
        mid = (t0 + t1) / 2.0
        parts.append(
            f'<line x1="{t0:.1f}" y1="{front_y:.1f}" x2="{t1:.1f}" y2="{front_y:.1f}" '
            f'stroke="#0b3d7a" stroke-width="2.0"/>'
        )
        if op == "sliding":
            parts.append(
                f'<line x1="{t0:.1f}" y1="{front_y - 5:.1f}" x2="{t1:.1f}" y2="{front_y - 5:.1f}" '
                f'stroke="#0b3d7a" stroke-width="0.7" stroke-dasharray="3 2"/>'
            )
            parts.append(
                f'<text x="{mid:.1f}" y="{front_y - 8:.1f}" text-anchor="middle" font-size="9" '
                f'font-family="sans-serif" fill="#0b3d7a">SLIDE + TRACK</text>'
            )
        else:
            plan_arrow = "←" if door_side == "right" else "→"
            hx = t1 if hinge_side == "right" else t0
            r = min(max(abs(t1 - t0) * 0.38, 10.0), 22.0)
            sx = hx - r if hinge_side == "right" else hx + r
            sweep = 1 if hinge_side == "right" else 0
            parts.append(
                f'<path d="M {sx:.1f},{front_y:.1f} A {r:.1f},{r:.1f} 0 0 {sweep} {hx:.1f},{front_y - r:.1f}" '
                f'fill="none" stroke="#0b3d7a" stroke-width="0.8" stroke-dasharray="3 2" data-swing="1"/>'
            )
            parts.append(
                f'<text x="{mid:.1f}" y="{front_y - r - 6:.1f}" text-anchor="middle" font-size="9" '
                f'font-family="sans-serif" fill="#0b3d7a">{escape(lab)} {plan_arrow}</text>'
            )

    if shape == "straight":
        fy = plan_y + 28.0
        parts.append(f'<line x1="{px:.1f}" y1="{fy:.1f}" x2="{px + fw:.1f}" y2="{fy:.1f}" stroke="{stroke}" stroke-width="{psw:.2f}"/>')
        _dim_h(px, px + fw, fy + 16.0, f"{mm_n(front_w)}")
        _mark_door_on_front(px, fy, fw)
    elif shape == "L":
        # Left return + front
        parts.append(
            f'<polyline fill="none" stroke="{stroke}" stroke-width="{psw:.2f}" '
            f'points="{px:.1f},{plan_y + da:.1f} {px:.1f},{plan_y:.1f} {px + fw:.1f},{plan_y:.1f}"/>'
        )
        _dim_h(px, px + fw, plan_y - 6.0, f"front {mm_n(front_w)}")
        _dim_v(plan_y, plan_y + da, px - 10.0, f"L {mm_n(depth_a_mm)}", left=True)
        _mark_door_on_front(px, plan_y, fw)
    else:  # U — front + left + right, all dimensioned
        parts.append(
            f'<polyline fill="none" stroke="{stroke}" stroke-width="{psw:.2f}" '
            f'points="{px:.1f},{plan_y + da:.1f} {px:.1f},{plan_y:.1f} {px + fw:.1f},{plan_y:.1f} '
            f'{px + fw:.1f},{plan_y + db:.1f}"/>'
        )
        _dim_h(px, px + fw, plan_y - 6.0, f"front {mm_n(front_w)}")
        _dim_v(plan_y, plan_y + da, px - 10.0, f"L {mm_n(depth_a_mm)}", left=True)
        _dim_v(plan_y, plan_y + db, px + fw + 10.0, f"R {mm_n(depth_b_mm)}", left=False)
        _mark_door_on_front(px, plan_y, fw)

    glass_bit = f'{mm_n(q.get("glassThicknessMm"))} mm {_s(q.get("glassColour"))}'
    parts.append(
        f'<text x="{x0}" y="{svg_h - 10:.1f}" font-size="10" font-family="sans-serif" fill="#444">'
        f'{escape(glass_bit)} · {_s(q.get("handleName") or "—")} · lock {"yes" if lock_on else "no"}'
        f' · {round(_f(q.get("areaSqft")), 2)} sft</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)
