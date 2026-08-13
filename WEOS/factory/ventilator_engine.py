"""Bathroom ventilator — pricing + unified-canvas SVG (same for PDF).

Gallery product (casement family, not a one-off SKU). Outer frame always.
Split: one side fix glass OR horizontal louvers; remaining fix glass OR top-hung.
Optional exhaust fan opening. Extra mode: full glass + round fan cut-out (Ø mm).
Top-hung: handle at bottom, casement hinges at top. Default glass = frosted.
"""

from __future__ import annotations

import math
from typing import Any, Mapping
from xml.sax.saxutils import escape

from WEOS.factory.fmt import mm_n, money_n
from WEOS.factory.geometry import casement_hinge_svg, hinge_capsule_size_mm, hinge_gap_axis

MM_PER_FT = 304.8
SQMM_PER_SQFT = 92903.04

DEFAULT_COLOURS = ("matt_black", "white", "grey", "wood_finish")
DEFAULT_OUTER = "25×40 mm"
DEFAULT_SASH = "20×35 mm"
DEFAULT_MULLION = "25×40 mm"
DEFAULT_HANDLE = "D-type"
DEFAULT_HINGE = "casement"
DEFAULT_GLASS_LABEL = "5mm Frosted tuff"


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
    if value is None:
        return default
    t = str(value).strip()
    return t if t else default


def _bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def _mode(cfg: Mapping[str, Any]) -> str:
    raw = _s(cfg.get("mode") or cfg.get("layout") or cfg.get("ventMode"), "split").lower()
    if raw in ("full_cutout", "full", "cutout", "cut-out", "round", "fan_cut"):
        return "full_cutout"
    return "split"


def _side(value: Any, default: str = "left") -> str:
    t = _s(value, default).lower()
    if t in ("r", "right"):
        return "right"
    if t in ("c", "centre", "center", "mid"):
        return "center"
    return "left"


def _fill_side(value: Any, *, allowed: tuple[str, ...], default: str) -> str:
    t = _s(value, default).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fix": "glass",
        "fixed": "glass",
        "fix_glass": "glass",
        "frosted": "glass",
        "louver": "louvers",
        "louvre": "louvers",
        "horizontal_louvers": "louvers",
        "tophung": "top_hung",
        "top": "top_hung",
        "vent": "top_hung",
        "openable": "top_hung",
        "fan": "fan",
        "exhaust": "fan",
        "opening": "fan",
    }
    t = aliases.get(t, t)
    return t if t in allowed else default


def ensure_ventilator_dims(
    cfg: Mapping[str, Any] | None,
    *,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, Any]:
    out = dict(cfg or {})
    if _f(out.get("widthMm") or out.get("width")) <= 0:
        for cand in (width, out.get("width"), 600):
            v = _f(cand)
            if v > 0:
                out["widthMm"] = v
                break
    if _f(out.get("heightMm") or out.get("height")) <= 0:
        for cand in (height, out.get("height"), 450):
            v = _f(cand)
            if v > 0:
                out["heightMm"] = v
                break
    if not out.get("glassLabel") and not out.get("glassColour"):
        out.setdefault("glassColour", "frosted")
        out.setdefault("glassThicknessMm", 5)
        out.setdefault("glassLabel", DEFAULT_GLASS_LABEL)
        out.setdefault("glassToughened", True)
    return out


def format_ventilator_description(
    q: Mapping[str, Any] | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> str:
    q = q if isinstance(q, Mapping) else {}
    cfg = cfg if isinstance(cfg, Mapping) else {}
    w = q.get("widthMm") or cfg.get("widthMm") or 0
    h = q.get("heightMm") or cfg.get("heightMm") or 0
    glass = _s(q.get("glassLabel") or cfg.get("glassLabel"), DEFAULT_GLASS_LABEL)
    colour = _s(q.get("colour") or cfg.get("colour"), "matt_black").replace("_", " ")
    mode = _s(q.get("mode") or cfg.get("mode"), "split")
    bits = ["Bathroom ventilator", f"{mm_n(w)}×{mm_n(h)} mm", glass, colour]
    if mode == "full_cutout":
        bits.append(f"fan cut-out Ø{mm_n(q.get('fanDiameterMm') or cfg.get('fanDiameterMm') or 200)} mm")
    else:
        louvers_side = _s(q.get("louversSide") or cfg.get("louversSide"), "left")
        louvers_fill = _s(q.get("louversFill") or cfg.get("louversFill"), "glass")
        remain_fill = _s(q.get("remainFill") or cfg.get("remainFill"), "top_hung")
        bits.append(f"{louvers_side} {louvers_fill.replace('_', ' ')}")
        bits.append(f"remain {remain_fill.replace('_', ' ')}")
        if q.get("exhaust") or cfg.get("exhaust"):
            bits.append(f"exhaust Ø{mm_n(q.get('fanDiameterMm') or cfg.get('fanDiameterMm') or 200)} mm")
    return " · ".join(str(b) for b in bits if b)


def compute_ventilator(cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cfg = ensure_ventilator_dims(cfg or {})
    width_mm = max(_f(cfg.get("widthMm") or cfg.get("width"), 600), 180.0)
    height_mm = max(_f(cfg.get("heightMm") or cfg.get("height"), 450), 180.0)
    qty = max(_i(cfg.get("qty") or cfg.get("quantity"), 1), 1)
    mode = _mode(cfg)
    colour = _s(cfg.get("colour"), "matt_black")
    louvers_side = _side(cfg.get("louversSide") or cfg.get("oneSide"), "left")
    if louvers_side == "center":
        louvers_side = "left"
    louvers_fill = _fill_side(
        cfg.get("louversFill") or cfg.get("oneSideFill") or cfg.get("leftFill"),
        allowed=("glass", "louvers"),
        default="glass",
    )
    remain_fill = _fill_side(
        cfg.get("remainFill") or cfg.get("rightFill") or cfg.get("remainingFill"),
        allowed=("glass", "top_hung"),
        default="top_hung",
    )
    exhaust = _bool(cfg.get("exhaust") or cfg.get("exhaustFan"), False) or mode == "full_cutout"
    exhaust_side = _side(cfg.get("exhaustSide") or cfg.get("fanSide"), "center" if mode == "full_cutout" else louvers_side)
    fan_d = max(_f(cfg.get("fanDiameterMm") or cfg.get("fanDiaMm") or cfg.get("fanDiameter"), 200.0), 80.0)
    left_w = _f(cfg.get("leftWidthMm") or cfg.get("splitLeftMm"), 0.0)
    if left_w <= 0:
        ratio = min(max(_f(cfg.get("splitRatio"), 0.5), 0.28), 0.72)
        left_w = width_mm * ratio
    left_w = min(max(left_w, 80.0), width_mm - 80.0)
    right_w = width_mm - left_w

    glass_thk = _f(cfg.get("glassThicknessMm") or cfg.get("glassThk"), 5.0) or 5.0
    glass_colour = _s(cfg.get("glassColour") or cfg.get("glassColor"), "frosted").lower()
    if not glass_colour:
        glass_colour = "frosted"
    glass_tough = _bool(cfg.get("glassToughened"), True)
    glass_label = _s(cfg.get("glassLabel") or cfg.get("glassName"), "")
    if not glass_label:
        glass_label = f"{glass_thk:g}mm {glass_colour.title()}{' tuff' if glass_tough else ''}"

    outer_name = _s(cfg.get("outerProfile") or cfg.get("frameProfile"), DEFAULT_OUTER)
    sash_name = _s(cfg.get("sashProfile"), DEFAULT_SASH)
    mullion_name = _s(cfg.get("mullionProfile"), DEFAULT_MULLION)
    handle_on = _bool(cfg.get("handle"), True)
    handle_name = _s(cfg.get("handleName") or cfg.get("handleType"), DEFAULT_HANDLE)
    hinge_count = min(max(_i(cfg.get("hingesPerDoor") or cfg.get("hingeCount"), 2), 2), 4)
    hinge_type = _s(cfg.get("hingeType"), DEFAULT_HINGE)
    hw_brand = _s(cfg.get("hardwareBrand"))
    hw_origin = _s(cfg.get("hardwareOrigin"))
    sale_unit = _s(cfg.get("saleUnit"), "sqft").lower()
    if sale_unit not in ("sqft", "sft", "opening", "nos", "unit"):
        sale_unit = "sqft"
    if sale_unit == "sft":
        sale_unit = "sqft"

    area_sqft = (width_mm * height_mm) / SQMM_PER_SQFT
    billable = area_sqft * qty if sale_unit == "sqft" else float(qty)
    rates = cfg.get("rates") if isinstance(cfg.get("rates"), Mapping) else {}
    r_glass = _f(cfg.get("glassRatePerSqft") or (rates or {}).get("glassPerSqft"), 0.0)
    r_outer = _f(rates.get("outerPerRft") or cfg.get("outerRate"), 0.0)
    r_sash = _f(rates.get("sashPerRft") or cfg.get("sashRate"), 0.0)
    r_mull = _f(rates.get("mullionPerRft") or cfg.get("mullionRate"), 0.0)
    r_handle = _f(rates.get("handlePerPc") or cfg.get("handleRate"), 0.0)
    r_hinge = _f(rates.get("hingePerPc") or cfg.get("hingeRate"), 0.0)
    r_louver = _f(rates.get("louverPerSqft") or cfg.get("louverRate"), 0.0)
    r_fan = _f(rates.get("fanOpeningPerPc") or cfg.get("fanRate"), 0.0)

    items: list[dict[str, Any]] = []

    def add(key: str, label: str, qty_v: float, unit: str, rate: float, **extra: Any) -> None:
        if qty_v <= 0:
            return
        row = {
            "key": key,
            "label": label,
            "qty": round(qty_v, 3),
            "unit": unit,
            "rate": money_n(rate),
            "amount": money_n(qty_v * rate),
            "color": colour,
        }
        row.update({k: v for k, v in extra.items() if v not in (None, "")})
        items.append(row)

    if area_sqft > 0:
        add("glass", glass_label, round(area_sqft, 3), "sqft", r_glass, sizeMm=f"{glass_thk:g} mm", glassColour=glass_colour)
    peri = 2.0 * (width_mm + height_mm)
    add("outer", f"Outer frame · {outer_name}", round(peri / MM_PER_FT, 3), "rft", r_outer, sizeMm=outer_name)
    if mode == "split":
        add("mullion", f"Mullion · {mullion_name}", round(height_mm / MM_PER_FT, 3), "rft", r_mull, sizeMm=mullion_name)
        if remain_fill == "top_hung":
            sash_peri = 2.0 * (right_w if louvers_side == "left" else left_w) + 2.0 * height_mm
            add("sash", f"Top-hung sash · {sash_name}", round(sash_peri / MM_PER_FT, 3), "rft", r_sash, sizeMm=sash_name)
            if handle_on:
                add("handle", f"Handle · {handle_name} (bottom)", 1, "pc", r_handle)
            add("hinge", f"{hinge_type.title()} hinges · {hinge_count} (top)", hinge_count, "pc", r_hinge)
        if louvers_fill == "louvers":
            lw = left_w if louvers_side == "left" else right_w
            add("louvers", "Horizontal louvers", round((lw * height_mm) / SQMM_PER_SQFT, 3), "sqft", r_louver)
    if exhaust:
        add("exhaust", f"Exhaust opening Ø{mm_n(fan_d)} mm", 1, "pc", r_fan, sizeMm=f"Ø{mm_n(fan_d)}")

    extras = cfg.get("extras") if isinstance(cfg.get("extras"), list) else []
    extras_total = 0.0
    for ex in extras:
        if not isinstance(ex, Mapping):
            continue
        amt = money_n(ex.get("amount") or ex.get("value") or 0)
        extras_total += amt
    bom_total = money_n(sum(_f(it.get("amount")) for it in items) + extras_total)
    selling_per_unit = _f(cfg.get("manualRatePerUnit") or cfg.get("sellingRate") or cfg.get("sellingPerUnit"), 0.0)
    selling_total = money_n(selling_per_unit * billable) if selling_per_unit else money_n(0)

    left_role = louvers_fill if louvers_side == "left" else remain_fill
    right_role = remain_fill if louvers_side == "left" else louvers_fill
    panels = []
    if mode == "split":
        panels.append({
            "role": left_role,
            "label": left_role.replace("_", " ").upper(),
            "side": "left",
            "widthMm": mm_n(left_w),
            "heightMm": mm_n(height_mm),
        })
        panels.append({
            "role": right_role,
            "label": right_role.replace("_", " ").upper(),
            "side": "right",
            "widthMm": mm_n(right_w),
            "heightMm": mm_n(height_mm),
        })
    else:
        panels.append({
            "role": "glass",
            "label": "GLASS + FAN CUT",
            "side": "full",
            "widthMm": mm_n(width_mm),
            "heightMm": mm_n(height_mm),
        })

    return {
        "productType": "bathroom_ventilator",
        "mode": mode,
        "widthMm": mm_n(width_mm),
        "heightMm": mm_n(height_mm),
        "leftWidthMm": mm_n(left_w),
        "rightWidthMm": mm_n(right_w),
        "louversSide": louvers_side,
        "louversFill": louvers_fill,
        "remainFill": remain_fill,
        "leftRole": left_role,
        "rightRole": right_role,
        "exhaust": bool(exhaust),
        "exhaustSide": exhaust_side,
        "fanDiameterMm": mm_n(fan_d),
        "colour": colour,
        "outerProfile": outer_name,
        "sashProfile": sash_name,
        "mullionProfile": mullion_name,
        "glassLabel": glass_label,
        "glassColour": glass_colour,
        "glassThicknessMm": glass_thk,
        "glassToughened": glass_tough,
        "handle": handle_on and remain_fill == "top_hung" and mode == "split",
        "handleName": handle_name,
        "handlePosition": "bottom",
        "hingeType": hinge_type,
        "hingeCount": hinge_count if (remain_fill == "top_hung" and mode == "split") else 0,
        "hingesPerDoor": hinge_count,
        "hingePosition": "top",
        "hardwareBrand": hw_brand,
        "hardwareOrigin": hw_origin,
        "panels": panels,
        "areaSqft": round(area_sqft, 4),
        "saleUnit": sale_unit,
        "billableQty": round(billable, 4),
        "items": items,
        "bomDetails": items,
        "extras": extras,
        "extrasTotal": money_n(extras_total),
        "bomTotal": bom_total,
        "manualRatePerUnit": money_n(selling_per_unit) if selling_per_unit else None,
        "sellingPerUnit": money_n(selling_per_unit),
        "sellingTotal": selling_total,
        "qty": qty,
    }


def _frame_d(x: float, y: float, w: float, h: float, t: float) -> str:
    x1, y1 = x + w, y + h
    xi0, yi0, xi1, yi1 = x + t, y + t, x1 - t, y1 - t
    return (
        f"M {x:.1f},{y:.1f} L {x1:.1f},{y:.1f} L {x1:.1f},{y1:.1f} L {x:.1f},{y1:.1f} Z "
        f"M {xi0:.1f},{yi0:.1f} L {xi0:.1f},{yi1:.1f} L {xi1:.1f},{yi1:.1f} L {xi1:.1f},{yi0:.1f} Z"
    )


def _miter_corners(parts: list[str], x: float, y: float, w: float, h: float, t: float, stroke: str, sw: float) -> None:
    x1, y1 = x + w, y + h
    for x0, y0, xi, yi in (
        (x, y, x + t, y + t),
        (x1, y, x1 - t, y + t),
        (x1, y1, x1 - t, y1 - t),
        (x, y1, x + t, y1 - t),
    ):
        parts.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{xi:.1f}" y2="{yi:.1f}" '
            f'stroke="{stroke}" stroke-width="{sw:.2f}" data-miter="1" data-frame-miter="45"/>'
        )


def _outer_frame(parts: list[str], x: float, y: float, w: float, h: float, t: float, stroke: str, sw: float) -> None:
    t = min(max(t, 2.6), w / 2.6, h / 2.6)
    parts.append(
        f'<path d="{_frame_d(x, y, w, h, t)}" fill="#f2f2f3" fill-rule="evenodd" '
        f'stroke="{stroke}" stroke-width="{sw:.2f}" data-outer-frame="1"/>'
    )
    _miter_corners(parts, x, y, w, h, t, stroke, sw)


def _sash_frame(parts: list[str], x: float, y: float, w: float, h: float, t: float, stroke: str, sw: float) -> None:
    t = min(max(t, 2.2), w / 2.8, h / 2.8)
    parts.append(
        f'<path d="{_frame_d(x, y, w, h, t)}" fill="#efefef" fill-rule="evenodd" '
        f'stroke="{stroke}" stroke-width="{sw:.2f}" data-sash="1" data-sash-miter="45"/>'
    )
    _miter_corners(parts, x, y, w, h, t, stroke, sw)


def _mullion_90(parts: list[str], x: float, y: float, t: float, h: float, stroke: str, sw: float) -> None:
    parts.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{t:.1f}" height="{h:.1f}" fill="#e8e8ea" '
        f'stroke="{stroke}" stroke-width="{sw:.2f}" data-mullion="1" data-mullion-joint="90"/>'
    )


def _louvers(parts: list[str], x: float, y: float, w: float, h: float, stroke: str) -> None:
    gap = max(min(h * 0.08, 10.0), 5.5)
    blade = max(min(h * 0.055, 7.0), 3.2)
    y_cur = y + blade
    while y_cur + blade < y + h - 1.0:
        parts.append(
            f'<rect x="{x:.1f}" y="{y_cur:.1f}" width="{w:.1f}" height="{blade:.1f}" '
            f'fill="#d8d8dc" stroke="{stroke}" stroke-width="0.45" data-louver="1"/>'
        )
        y_cur += blade + gap


def _handle_bottom(parts: list[str], x: float, y_bot: float, w: float) -> None:
    hw = max(min(w * 0.28, 18.0), 8.0)
    hh = max(min(w * 0.08, 6.5), 3.6)
    hx = x + (w - hw) / 2.0
    hy = y_bot - hh - 1.2
    parts.append(
        f'<rect x="{hx:.1f}" y="{hy:.1f}" width="{hw:.1f}" height="{hh:.1f}" rx="{hh * 0.4:.1f}" '
        f'fill="none" stroke="#222" stroke-width="0.65" data-handle="1" data-handle-pos="bottom"/>'
    )
    parts.append(
        f'<line x1="{hx + 2:.1f}" y1="{hy + hh / 2:.1f}" x2="{hx + hw - 2:.1f}" y2="{hy + hh / 2:.1f}" '
        f'stroke="#222" stroke-width="0.65"/>'
    )


def _top_hinges(
    parts: list[str],
    x: float,
    y: float,
    w: float,
    t: float,
    count: int,
    stroke: str,
    *,
    gap_y: float | None = None,
    leaf_w_mm: float | None = None,
    stile_t_mm: float | None = None,
    scale: float = 1.0,
) -> None:
    """Top-hung hinges: horizontal capsule centred on the outer | sash head gap."""
    count = min(max(int(count), 2), 4)
    inset = min(max(w * 0.12, 10.0), w * 0.22)
    if count == 2:
        xs = [x + inset, x + w - inset]
    elif count == 3:
        xs = [x + inset, x + w / 2.0, x + w - inset]
    else:
        span = w - 2 * inset
        xs = [x + inset + span * i / (count - 1) for i in range(count)]
    sc = max(float(scale), 1e-6)
    span_mm = float(leaf_w_mm) if leaf_w_mm and leaf_w_mm > 0 else (w / sc)
    stile_mm = float(stile_t_mm) if stile_t_mm and stile_t_mm > 0 else (t / sc)
    hw_mm, hh_mm = hinge_capsule_size_mm(span_mm, stile_mm, orientation="horizontal")
    hw, hh = max(hw_mm * sc, 2.4), max(hh_mm * sc, 0.9)
    # Default = sash top outer (stile gap), not mid-stile / frame-inner.
    cy = float(gap_y) if gap_y is not None else float(y)
    for cx in xs:
        parts.append(
            casement_hinge_svg(
                cx,
                cy,
                w=hw,
                h=hh,
                stroke=stroke,
                stroke_width=0.55,
                extra_attrs='data-hinge-style="casement" data-hinge-pos="top"',
            )
        )


def _fan_opening(parts: list[str], cx: float, cy: float, d: float, stroke: str) -> None:
    r = max(d / 2.0, 8.0)
    box = r * 1.18
    parts.append(
        f'<rect x="{cx - box:.1f}" y="{cy - box:.1f}" width="{box * 2:.1f}" height="{box * 2:.1f}" '
        f'fill="#fafafa" stroke="{stroke}" stroke-width="0.7" data-fan-box="1"/>'
    )
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="#fff" stroke="{stroke}" '
        f'stroke-width="0.85" data-fan="1" data-fan-dia="{d:.0f}"/>'
    )
    for ang_off in (0.0, 45.0):
        rad = math.radians(ang_off)
        x2 = cx + math.cos(rad) * r * 0.88
        y2 = cy + math.sin(rad) * r * 0.88
        x3 = cx - math.cos(rad) * r * 0.88
        y3 = cy - math.sin(rad) * r * 0.88
        parts.append(
            f'<line x1="{x2:.1f}" y1="{y2:.1f}" x2="{x3:.1f}" y2="{y3:.1f}" '
            f'stroke="#888" stroke-width="0.55" data-fan-blade="1"/>'
        )


def _glass_with_cutout(
    parts: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    cx: float,
    cy: float,
    d: float,
    fill: str,
    stroke: str,
) -> None:
    r = max(d / 2.0, 6.0)
    d_path = (
        f"M {x:.1f},{y:.1f} L {x + w:.1f},{y:.1f} L {x + w:.1f},{y + h:.1f} L {x:.1f},{y + h:.1f} Z "
        f"M {cx - r:.1f},{cy:.1f} A {r:.1f},{r:.1f} 0 1 0 {cx + r:.1f},{cy:.1f} "
        f"A {r:.1f},{r:.1f} 0 1 0 {cx - r:.1f},{cy:.1f} Z"
    )
    parts.append(
        f'<path d="{d_path}" fill="{fill}" fill-rule="evenodd" stroke="none" data-glass="1" data-fan-cut="1"/>'
    )
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" stroke="{stroke}" '
        f'stroke-width="0.9" data-fan="1" data-fan-dia="{d:.0f}"/>'
    )


def ventilator_svg(cfg: Mapping[str, Any], quote: Mapping[str, Any] | None = None) -> str:
    """Elevation SVG used by live canvas and customer PDF (identical)."""
    q = quote if isinstance(quote, Mapping) and quote else compute_ventilator(cfg)
    width = _f(q.get("widthMm"), 600)
    height = _f(q.get("heightMm"), 450)
    if width <= 0 or height <= 0:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="140">'
            '<text x="16" y="80" font-size="14">Ventilator — set width / height</text></svg>'
        )
    mode = _s(q.get("mode"), "split")
    colour = _s(q.get("colour"), "matt_black")
    glass_col = _s(q.get("glassColour"), "frosted").lower()
    frost = "frost" in glass_col
    glass_fill = "rgba(210, 212, 218, 0.55)" if frost else "rgba(170, 205, 230, 0.28)"
    stroke = "#1a1a1a"
    sw = 0.55
    margin = 18.0
    elev_h = 210.0
    scale = elev_h / max(height, 1.0)
    elev_w = max(width * scale, 140.0)
    frame_t = max(50.0 * scale, 5.0)  # 50 mm series visual thickness
    sash_t = max(50.0 * scale * 0.85, 4.2)
    mull_t = max(50.0 * scale * 0.70, 4.0)
    fan_d_mm = _f(q.get("fanDiameterMm"), 200)
    fan_d_px = max(fan_d_mm * scale, 18.0)
    svg_w = elev_w + margin * 2 + 36
    svg_h = elev_h + margin + 52
    left_w_mm = _f(q.get("leftWidthMm"), width / 2)
    left_w = left_w_mm * scale
    right_w = elev_w - left_w
    left_role = _s(q.get("leftRole"), "glass")
    right_role = _s(q.get("rightRole"), "top_hung")
    exhaust = bool(q.get("exhaust"))
    exhaust_side = _s(q.get("exhaustSide"), "center")
    hinge_n = _i(q.get("hingeCount") or q.get("hingesPerDoor"), 2)
    handle_on = bool(q.get("handle"))

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w:.1f}" height="{svg_h:.1f}" '
        f'viewBox="0 0 {svg_w:.1f} {svg_h:.1f}" data-model-system="ventilator" '
        f'data-product-type="bathroom_ventilator" data-mode="{escape(mode)}" '
        f'data-corner-markers="0" data-outer-miter="45" data-mullion-joint="90" '
        f'data-fan-dia="{mm_n(fan_d_mm)}">',
        f"<title>Bathroom ventilator {mm_n(width)}×{mm_n(height)}</title>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin}" y="16" font-size="11" font-family="sans-serif" fill="#222">'
        f'Bathroom ventilator · {mm_n(width)}×{mm_n(height)} mm · {escape(colour.replace("_", " "))}'
        f' · {escape(_s(q.get("glassLabel"), DEFAULT_GLASS_LABEL))}</text>',
    ]
    x0 = margin
    y0 = 26.0

    if mode == "full_cutout":
        gx, gy, gw, gh = x0 + frame_t, y0 + frame_t, elev_w - 2 * frame_t, elev_h - 2 * frame_t
        cx, cy = x0 + elev_w / 2.0, y0 + elev_h * 0.46
        _glass_with_cutout(parts, gx, gy, gw, gh, cx, cy, fan_d_px, glass_fill, stroke)
        _outer_frame(parts, x0, y0, elev_w, elev_h, frame_t, stroke, sw)
        parts.append(
            f'<text x="{x0 + elev_w / 2:.1f}" y="{y0 + elev_h / 2 + fan_d_px * 0.7:.1f}" text-anchor="middle" '
            f'font-size="9" font-family="sans-serif" fill="#555">FAN Ø{mm_n(fan_d_mm)}</text>'
        )
    else:
        # Inner glass / louvers / sash first, then outer + mullion on top.
        lx, rx = x0 + frame_t, x0 + left_w + mull_t / 2.0
        inner_y = y0 + frame_t
        inner_h = elev_h - 2 * frame_t
        left_inner_w = max(left_w - frame_t - mull_t / 2.0, 8.0)
        right_inner_w = max(elev_w - left_w - frame_t - mull_t / 2.0, 8.0)

        def _bay(role: str, bx: float, bw: float, side: str) -> None:
            if role == "louvers":
                parts.append(
                    f'<rect x="{bx:.1f}" y="{inner_y:.1f}" width="{bw:.1f}" height="{inner_h:.1f}" '
                    f'fill="{glass_fill}" stroke="none" data-glass="1" data-bay="{side}"/>'
                )
                _louvers(parts, bx + 1.5, inner_y + 1.5, bw - 3.0, inner_h - 3.0, stroke)
            elif role == "top_hung":
                ov = max(min(frame_t * 0.35, 4.0), 2.2)  # 10–20 mm overlap, scaled
                sx = bx - ov
                sy = inner_y - ov
                swd = bw + ov * 2
                sh = inner_h + ov
                # keep sash inside outer inner edge slightly
                sx = max(sx, x0 + 1.0)
                sy = max(sy, y0 + 1.0)
                if sx + swd > x0 + elev_w - 1.0:
                    swd = x0 + elev_w - 1.0 - sx
                if sy + sh > y0 + elev_h - 1.0:
                    sh = y0 + elev_h - 1.0 - sy
                parts.append(
                    f'<rect x="{sx + sash_t:.1f}" y="{sy + sash_t:.1f}" '
                    f'width="{max(swd - 2 * sash_t, 4):.1f}" height="{max(sh - 2 * sash_t, 4):.1f}" '
                    f'fill="{glass_fill}" stroke="none" data-glass="1" data-bay="{side}"/>'
                )
                _sash_frame(parts, sx, sy, swd, sh, sash_t, stroke, sw)
                if handle_on:
                    _handle_bottom(parts, sx + sash_t, sy + sh - sash_t, max(swd - 2 * sash_t, 8))
                _top_hinges(
                    parts, sx, sy, swd, sash_t, hinge_n, stroke,
                    gap_y=hinge_gap_axis(sy, inner_y, toward_frame=-1.0),
                    leaf_w_mm=swd / max(scale, 1e-6),
                    stile_t_mm=50.0 * 0.85,
                    scale=scale,
                )
                # opening hint (down for top-hung)
                mx = sx + swd / 2.0
                parts.append(
                    f'<line x1="{mx:.1f}" y1="{sy + sh * 0.42:.1f}" x2="{mx:.1f}" y2="{sy + sh * 0.78:.1f}" '
                    f'stroke="#0b3d7a" stroke-width="0.8" data-arrow="1" data-arrow-dir="down"/>'
                )
            else:
                parts.append(
                    f'<rect x="{bx:.1f}" y="{inner_y:.1f}" width="{bw:.1f}" height="{inner_h:.1f}" '
                    f'fill="{glass_fill}" stroke="none" data-glass="1" data-bay="{side}"/>'
                )

        _bay(left_role, lx, left_inner_w, "left")
        _bay(right_role, rx, right_inner_w, "right")

        if exhaust and exhaust_side != "":
            if exhaust_side == "left":
                fcx = lx + left_inner_w / 2.0
            elif exhaust_side == "right":
                fcx = rx + right_inner_w / 2.0
            else:
                fcx = x0 + elev_w / 2.0
            fcy = inner_y + min(max(fan_d_px * 0.70, 18.0), inner_h * 0.38)
            _fan_opening(parts, fcx, fcy, min(fan_d_px, min(left_inner_w, right_inner_w, inner_h) * 0.72), stroke)

        _outer_frame(parts, x0, y0, elev_w, elev_h, frame_t, stroke, sw)
        _mullion_90(parts, x0 + left_w - mull_t / 2.0, y0 + frame_t, mull_t, elev_h - 2 * frame_t, stroke, sw)
        # T ticks at mullion/head + sill (90°, not 45°)
        mx0 = x0 + left_w - mull_t / 2.0
        mx1 = mx0 + mull_t
        parts.append(
            f'<line x1="{mx0:.1f}" y1="{y0 + frame_t:.1f}" x2="{mx1:.1f}" y2="{y0 + frame_t:.1f}" '
            f'stroke="{stroke}" stroke-width="{sw:.2f}" data-mullion-t="1"/>'
        )
        parts.append(
            f'<line x1="{mx0:.1f}" y1="{y0 + elev_h - frame_t:.1f}" x2="{mx1:.1f}" y2="{y0 + elev_h - frame_t:.1f}" '
            f'stroke="{stroke}" stroke-width="{sw:.2f}" data-mullion-t="1"/>'
        )

        parts.append(
            f'<text x="{lx + left_inner_w / 2:.1f}" y="{y0 + elev_h / 2:.1f}" text-anchor="middle" '
            f'font-size="11" font-family="sans-serif" font-weight="700" fill="#0b3d7a">'
            f'{escape(left_role.replace("_", " ").upper())}</text>'
        )
        parts.append(
            f'<text x="{rx + right_inner_w / 2:.1f}" y="{y0 + elev_h / 2:.1f}" text-anchor="middle" '
            f'font-size="11" font-family="sans-serif" font-weight="700" fill="#0b3d7a">'
            f'{escape(right_role.replace("_", " ").upper())}</text>'
        )
        parts.append(
            f'<text x="{lx + left_inner_w / 2:.1f}" y="{y0 + elev_h + 14:.1f}" text-anchor="middle" '
            f'font-size="10" font-family="sans-serif" fill="#444">{mm_n(left_w_mm)} mm</text>'
        )
        parts.append(
            f'<text x="{rx + right_inner_w / 2:.1f}" y="{y0 + elev_h + 14:.1f}" text-anchor="middle" '
            f'font-size="10" font-family="sans-serif" fill="#444">{mm_n(width - left_w_mm)} mm</text>'
        )

    parts.append(
        f'<text x="{x0 + elev_w / 2:.1f}" y="{y0 + elev_h + 28:.1f}" text-anchor="middle" '
        f'font-size="10" font-family="sans-serif" fill="#333">{mm_n(width)} × {mm_n(height)} mm</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)
