"""Shower partition — pricing + unified-canvas SVG (elevation + floor plan).

Gallery product (not a hardcoded-only SKU). Designs: straight / L / U.
Sliding 1+1 = half width fix + half sliding (marked on drawing + PDF).
Hardware defaults are overridable from Product Library setup.
"""

from __future__ import annotations

from typing import Any, Mapping
from xml.sax.saxutils import escape

MM_PER_FT = 304.8
SQMM_PER_SQFT = 92903.04

DEFAULT_COLOURS = ("matt_black", "brush_gold", "gold", "grey", "rose_gold")
DEFAULT_VERT = "16×45 mm slim"
DEFAULT_HORIZ = "16×45 mm"
DEFAULT_CHOKHAT = "22×50 mm"
DEFAULT_HANDLE = "D-type"
DEFAULT_HINGE = "butterfly"


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
    bits = ["Shower partition", shape, op, f"{w:g}×{h:g} mm"]
    if glass:
        bits.append(glass)
    return " · ".join(str(b) for b in bits if b)


def _panel_plan(cfg: Mapping[str, Any], *, width_mm: float, depth_a: float, depth_b: float) -> list[dict[str, Any]]:
    """Elevation panels + footprint segments for straight / L / U."""
    shape = _shape(cfg)
    op = _operation(cfg)
    sliding_side = _s(cfg.get("slidingSide") or cfg.get("slideSide"), "right").lower()
    if sliding_side not in ("left", "right"):
        sliding_side = "right"
    height = _f(cfg.get("heightMm") or cfg.get("height"), 2000.0)

    def pane(role: str, w: float, *, wall: str = "front", label: str | None = None) -> dict[str, Any]:
        return {
            "role": role,
            "label": label or ("FIX" if role == "fix" else ("SLIDE" if role == "sliding" else "OPEN")),
            "widthMm": round(w, 1),
            "heightMm": round(height, 1),
            "wall": wall,
        }

    panels: list[dict[str, Any]] = []
    if op == "sliding":
        # 1+1 — half fix, half sliding on the front run.
        half = max(width_mm / 2.0, 1.0)
        if sliding_side == "left":
            panels.append(pane("sliding", half, label="SLIDE"))
            panels.append(pane("fix", half, label="FIX"))
        else:
            panels.append(pane("fix", half, label="FIX"))
            panels.append(pane("sliding", half, label="SLIDE"))
    elif op == "hinged":
        door_w = _f(cfg.get("doorWidthMm") or cfg.get("doorWidth"), width_mm * 0.55)
        door_w = min(max(door_w, 400.0), max(width_mm - 80.0, 400.0))
        fix_w = max(width_mm - door_w, 0.0)
        hinge = _s(cfg.get("hingeSide") or cfg.get("handleSide"), "right").lower()
        if hinge == "left":
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
    frameless = _bool(cfg.get("frameless"), False)
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
            "rate": round(rate, 3),
            "amount": round(qty * rate, 2),
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
        extras.append({"name": _s(ex.get("name"), "Extra"), "amount": round(amt, 2)})
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

    footprint = {"kind": shape, "frontMm": round(width_mm, 1)}
    if shape == "L":
        footprint["returnMm"] = round(depth_a, 1)
    elif shape == "U":
        footprint["leftMm"] = round(depth_a, 1)
        footprint["rightMm"] = round(depth_b, 1)

    return {
        "shape": shape,
        "designType": shape,
        "operation": op,
        "slidingFormat": "1+1" if op == "sliding" else None,
        "slidingSide": _s(cfg.get("slidingSide"), "right") if op == "sliding" else None,
        "widthMm": round(width_mm, 2),
        "heightMm": round(height_mm, 2),
        "depthMm": round(depth_a, 2) if shape in ("L", "U") else None,
        "depthBMm": round(depth_b, 2) if shape == "U" else None,
        "colour": colour,
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
        "extrasTotal": round(extras_total, 2),
        "bomTotal": round(bom_total, 2),
        "manualRatePerUnit": manual_rate,
        "sellingPerUnit": round(float(selling_per_unit), 4),
        "sellingTotal": selling_total,
        "footprint": footprint,
        "qty": qty,
    }


def _gi_plate(parts: list[str], cx: float, cy: float, size: float, stroke: str) -> None:
    """Small GI connector plate at a frame junction."""
    h = size / 2.0
    parts.append(
        f'<rect x="{cx - h:.1f}" y="{cy - h:.1f}" width="{size:.1f}" height="{size:.1f}" '
        f'fill="#f4f4f4" stroke="{stroke}" stroke-width="0.7" data-gi-plate="1"/>'
    )


def _d_handle(parts: list[str], x: float, y_mid: float, h: float, *, flip: bool = False) -> None:
    """D-type handle on the meeting stile."""
    w = max(min(h * 0.22, 14.0), 7.0)
    y0 = y_mid - h / 2.0
    x0 = x - w if flip else x
    parts.append(
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{w * 0.45:.1f}" '
        f'fill="none" stroke="#222" stroke-width="0.85"/>'
    )
    bar_x = x0 + (2.0 if not flip else w - 2.0)
    parts.append(
        f'<line x1="{bar_x:.1f}" y1="{y0 + 2:.1f}" x2="{bar_x:.1f}" y2="{y0 + h - 2:.1f}" '
        f'stroke="#222" stroke-width="0.7"/>'
    )


def _lock_mark(parts: list[str], x: float, y: float) -> None:
    parts.append(
        f'<rect x="{x - 4:.1f}" y="{y - 5:.1f}" width="8" height="10" rx="1.2" '
        f'fill="#fff" stroke="#333" stroke-width="0.7"/>'
    )
    parts.append(f'<circle cx="{x:.1f}" cy="{y - 0.5:.1f}" r="1.4" fill="none" stroke="#333" stroke-width="0.6"/>')
    parts.append(f'<line x1="{x:.1f}" y1="{y + 1.0:.1f}" x2="{x:.1f}" y2="{y + 3.6:.1f}" stroke="#333" stroke-width="0.6"/>')


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
    frameless = bool(q.get("frameless"))
    handle_on = bool(q.get("handle"))
    lock_on = bool(q.get("lock"))
    stroke = "#1a1a1a"
    glass_fill = "rgba(170, 205, 230, 0.22)"
    slide_fill = "rgba(120, 170, 210, 0.30)"
    open_fill = "rgba(210, 190, 140, 0.26)"
    sw = 0.75  # slim professional 2D

    # 16×45 mm slim frame face in elevation
    frame_face_mm = 45.0
    connector_mm = 14.0
    track_h_mm = 30.0
    cover_h_mm = 12.0

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
    conn_s = max(connector_mm * scale, 4.5)
    track_h = track_h_mm * scale
    cover_h = cover_h_mm * scale
    elev_w = max(front_w * scale, 180.0)
    track_extra = (track_h + cover_h + 6.0) if op == "sliding" else 0.0
    svg_w = max(elev_w, fw + 90.0) + margin * 2 + 70
    svg_h = 28.0 + track_extra + elev_h + 28.0 + plan_h + margin + 18.0

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w:.1f}" height="{svg_h:.1f}" '
        f'viewBox="0 0 {svg_w:.1f} {svg_h:.1f}" data-model-system="shower">',
        f"<title>Shower {escape(shape)} {front_w:g}×{height:g}</title>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<defs><marker id="shArrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">'
        '<path d="M0,0 L7,3.5 L0,7 Z" fill="#0b3d7a"/></marker></defs>',
        f'<text x="{margin}" y="18" font-size="12" font-family="sans-serif" fill="#222">'
        f'Shower · {escape(shape)} · {escape(op)} · {escape(colour.replace("_", " "))}'
        f' · 16×45 frame</text>',
    ]

    x0 = margin
    y_frame0 = 26.0 + track_extra
    # Top sliding track + cover plate (distinct from panel frames)
    if op == "sliding":
        ty = 26.0
        parts.append(
            f'<rect x="{x0:.1f}" y="{ty:.1f}" width="{elev_w:.1f}" height="{cover_h:.1f}" '
            f'fill="#f0f0f0" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
        )
        parts.append(
            f'<text x="{x0 + elev_w / 2:.1f}" y="{ty + cover_h * 0.78:.1f}" text-anchor="middle" '
            f'font-size="8" font-family="sans-serif" fill="#555">COVER PLATE</text>'
        )
        parts.append(
            f'<rect x="{x0:.1f}" y="{ty + cover_h:.1f}" width="{elev_w:.1f}" height="{track_h:.1f}" '
            f'fill="#e8e8ea" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
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

    x = x0
    slide_plan_ranges: list[tuple[float, float, str]] = []  # mm along front
    mm_cursor = 0.0
    for p in front_panels:
        pw_mm = _f(p.get("widthMm"))
        pw = pw_mm * scale
        role = str(p.get("role") or "fix")
        fill = slide_fill if role == "sliding" else (open_fill if role == "openable" else glass_fill)
        y0 = y_frame0
        # Glass
        parts.append(
            f'<rect x="{x:.1f}" y="{y0:.1f}" width="{pw:.1f}" height="{elev_h:.1f}" '
            f'fill="{fill}" stroke="none"/>'
        )
        if not frameless:
            # Slim 16×45 aluminium frame (vert + horiz)
            parts.append(
                f'<rect x="{x:.1f}" y="{y0:.1f}" width="{pw:.1f}" height="{elev_h:.1f}" '
                f'fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
            )
            inset = min(frame_t, pw * 0.18, elev_h * 0.08)
            parts.append(
                f'<rect x="{x + inset:.1f}" y="{y0 + inset:.1f}" width="{max(pw - 2 * inset, 1):.1f}" '
                f'height="{max(elev_h - 2 * inset, 1):.1f}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
            )
            # GI connector plates at four corners
            for cx, cy in (
                (x + inset, y0 + inset),
                (x + pw - inset, y0 + inset),
                (x + inset, y0 + elev_h - inset),
                (x + pw - inset, y0 + elev_h - inset),
            ):
                _gi_plate(parts, cx, cy, conn_s, stroke)
        else:
            parts.append(
                f'<rect x="{x:.1f}" y="{y0:.1f}" width="{pw:.1f}" height="{elev_h:.1f}" '
                f'fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
            )
        parts.append(
            f'<text x="{x + pw / 2:.1f}" y="{y0 + elev_h / 2:.1f}" text-anchor="middle" '
            f'font-size="13" font-family="sans-serif" font-weight="700" fill="#0b3d7a">'
            f'{escape(str(p.get("label") or role.upper()))}</text>'
        )
        parts.append(
            f'<text x="{x + pw / 2:.1f}" y="{y0 + elev_h + 14:.1f}" text-anchor="middle" '
            f'font-size="10" font-family="sans-serif" fill="#444">{pw_mm:g} mm</text>'
        )
        if role == "sliding":
            parts.append(
                f'<line x1="{x + pw * 0.22:.1f}" y1="{y0 + elev_h * 0.70:.1f}" '
                f'x2="{x + pw * 0.78:.1f}" y2="{y0 + elev_h * 0.70:.1f}" '
                f'stroke="#0b3d7a" stroke-width="0.9" marker-end="url(#shArrow)"/>'
            )
            slide_plan_ranges.append((mm_cursor, mm_cursor + pw_mm, "SLIDE"))
        if role == "openable":
            slide_plan_ranges.append((mm_cursor, mm_cursor + pw_mm, "DOOR"))
        if handle_on and role in ("sliding", "openable"):
            meeting_right = role == "sliding"  # 1+1: handle on meeting stile toward FIX
            hx = x + pw - frame_t * 0.35 if meeting_right else x + frame_t * 0.35
            _d_handle(parts, hx, y0 + elev_h * 0.48, max(elev_h * 0.16, 28.0), flip=not meeting_right)
            if lock_on:
                _lock_mark(parts, hx + (6 if meeting_right else -6), y0 + elev_h * 0.48 + max(elev_h * 0.10, 18.0))
        x += pw
        mm_cursor += pw_mm

    parts.append(
        f'<text x="{x0 + elev_w + 8:.1f}" y="{y_frame0 + elev_h / 2:.1f}" font-size="10" '
        f'font-family="sans-serif" fill="#8b1e1a">H {height:g}</text>'
    )

    # Floor plan — all sides dimensioned; door / SLIDE + track marked
    py = y_frame0 + elev_h + 32.0
    parts.append(
        f'<text x="{x0}" y="{py - 10:.1f}" font-size="11" font-family="sans-serif" fill="#555">'
        f'Floor plan · {escape(shape)}</text>'
    )
    px = x0 + (28.0 if shape != "straight" else 8.0)
    plan_y = py + 8.0
    psw = 1.15

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
            parts.append(
                f'<text x="{mid:.1f}" y="{front_y - 8:.1f}" text-anchor="middle" font-size="9" '
                f'font-family="sans-serif" fill="#0b3d7a">{escape(lab)} →</text>'
            )

    if shape == "straight":
        fy = plan_y + 28.0
        parts.append(f'<line x1="{px:.1f}" y1="{fy:.1f}" x2="{px + fw:.1f}" y2="{fy:.1f}" stroke="{stroke}" stroke-width="{psw:.2f}"/>')
        _dim_h(px, px + fw, fy + 16.0, f"{front_w:g}")
        _mark_door_on_front(px, fy, fw)
    elif shape == "L":
        # Left return + front
        parts.append(
            f'<polyline fill="none" stroke="{stroke}" stroke-width="{psw:.2f}" '
            f'points="{px:.1f},{plan_y + da:.1f} {px:.1f},{plan_y:.1f} {px + fw:.1f},{plan_y:.1f}"/>'
        )
        _dim_h(px, px + fw, plan_y - 6.0, f"front {front_w:g}")
        _dim_v(plan_y, plan_y + da, px - 10.0, f"L {depth_a_mm:g}", left=True)
        _mark_door_on_front(px, plan_y, fw)
    else:  # U — front + left + right, all dimensioned
        parts.append(
            f'<polyline fill="none" stroke="{stroke}" stroke-width="{psw:.2f}" '
            f'points="{px:.1f},{plan_y + da:.1f} {px:.1f},{plan_y:.1f} {px + fw:.1f},{plan_y:.1f} '
            f'{px + fw:.1f},{plan_y + db:.1f}"/>'
        )
        _dim_h(px, px + fw, plan_y - 6.0, f"front {front_w:g}")
        _dim_v(plan_y, plan_y + da, px - 10.0, f"L {depth_a_mm:g}", left=True)
        _dim_v(plan_y, plan_y + db, px + fw + 10.0, f"R {depth_b_mm:g}", left=False)
        _mark_door_on_front(px, plan_y, fw)

    glass_bit = f'{_f(q.get("glassThicknessMm")):g} mm {_s(q.get("glassColour"))}'
    parts.append(
        f'<text x="{x0}" y="{svg_h - 10:.1f}" font-size="10" font-family="sans-serif" fill="#444">'
        f'{escape(glass_bit)} · {_s(q.get("handleName") or "—")} · lock {"yes" if lock_on else "no"}'
        f' · {round(_f(q.get("areaSqft")), 2)} sft</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)
