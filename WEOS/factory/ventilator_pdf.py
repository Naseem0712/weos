"""ReportLab bathroom-ventilator elevation — PDF fallback when SVG rasterize fails.

Same geometry as ``ventilator_svg``: outer 45° frame, split bays (glass / louvers /
top-hung), optional exhaust circle, full-cutout fan. Never a grey placeholder.
"""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory.geometry import HINGE_FILL_RGB, hinge_capsule_geom, hinge_capsule_size_mm
from WEOS.factory.ventilator_engine import compute_ventilator, ensure_ventilator_dims


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
    t = str(value or "").strip()
    return t if t else default


def _cfg_and_quote(line: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    cfg = opts.get("ventilator") if isinstance(opts, Mapping) else None
    if not isinstance(cfg, Mapping):
        cfg = line.get("ventilator") if isinstance(line.get("ventilator"), Mapping) else {}
    cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
    cfg = ensure_ventilator_dims(cfg, width=line.get("width"), height=line.get("height"))
    q = opts.get("ventilatorQuote") if isinstance(opts, Mapping) else None
    if not isinstance(q, Mapping) or not q.get("widthMm"):
        q = line.get("ventilator") if isinstance(line.get("ventilator"), Mapping) else {}
    if not isinstance(q, Mapping) or not q.get("widthMm"):
        q = compute_ventilator(cfg)
    return cfg, dict(q) if isinstance(q, Mapping) else {}


def draw_ventilator_elevation(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    """Draw ventilator 2D into a PDF cell. Always draws geometry when size is known."""
    _cfg, q = _cfg_and_quote(line)
    width = _f(q.get("widthMm") or line.get("width"), 600)
    height = _f(q.get("heightMm") or line.get("height"), 450)
    if width <= 1.0 or height <= 1.0:
        return False
    mode = _s(q.get("mode"), "split").lower()
    if mode in ("full", "cutout", "cut-out", "round", "fan_cut"):
        mode = "full_cutout"
    frost = "frost" in _s(q.get("glassColour"), "frosted").lower()
    glass_fill = (0.82, 0.83, 0.85) if frost else (0.67, 0.80, 0.90)
    stroke = (0.10, 0.10, 0.11)
    left_w = _f(q.get("leftWidthMm"), width / 2.0)
    left_role = _s(q.get("leftRole"), "glass")
    right_role = _s(q.get("rightRole"), "top_hung")
    exhaust = bool(q.get("exhaust")) or mode == "full_cutout"
    exhaust_side = _s(q.get("exhaustSide"), "center")
    fan_d = max(_f(q.get("fanDiameterMm"), 200), 40.0)
    hinge_n = min(max(_i(q.get("hingeCount") or q.get("hingesPerDoor"), 2), 2), 6)
    handle_on = bool(q.get("handle"))
    frame_t = 50.0
    sash_t = 42.0
    mull_t = 35.0

    try:
        c.setDash()
    except Exception:
        pass
    c.setFillColorRGB(1, 1, 1)
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.40)
    c.rect(x, y, box_w, box_h, fill=1, stroke=1)

    m_left, m_right, m_bottom, m_top = 14.0, 12.0, 20.0, 16.0
    draw_w = max(box_w - m_left - m_right, 16.0)
    draw_h = max(box_h - m_bottom - m_top, 16.0)
    scale = min(draw_w / max(width, 1.0), draw_h / max(height, 1.0))
    ox = x + m_left + (draw_w - width * scale) / 2.0
    oy = y + m_bottom + (draw_h - height * scale) / 2.0

    def px(mx: float) -> float:
        return ox + mx * scale

    def py(my: float) -> float:
        return oy + my * scale

    lw = 0.62

    def _frame_ring(x0: float, y0: float, w: float, h: float, t: float) -> None:
        t = min(max(t, 8.0), w / 2.4, h / 2.4)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        c.rect(px(x0), py(y0), w * scale, h * scale, fill=0, stroke=1)
        if w > 2 * t and h > 2 * t:
            c.rect(px(x0 + t), py(y0 + t), (w - 2 * t) * scale, (h - 2 * t) * scale, fill=0, stroke=1)
        # 45° miters
        c.line(px(x0), py(y0), px(x0 + t), py(y0 + t))
        c.line(px(x0 + w), py(y0), px(x0 + w - t), py(y0 + t))
        c.line(px(x0), py(y0 + h), px(x0 + t), py(y0 + h - t))
        c.line(px(x0 + w), py(y0 + h), px(x0 + w - t), py(y0 + h - t))

    def _glass(x0: float, y0: float, w: float, h: float) -> None:
        if w <= 0.5 or h <= 0.5:
            return
        c.setFillColorRGB(*glass_fill)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.40)
        c.rect(px(x0), py(y0), w * scale, h * scale, fill=1, stroke=0)

    def _louvers(x0: float, y0: float, w: float, h: float) -> None:
        _glass(x0, y0, w, h)
        n = max(int(h / 28.0), 4)
        gap = h / n
        slat = max(gap * 0.45, 4.0)
        c.setFillColorRGB(0.85, 0.85, 0.86)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.40)
        for i in range(n):
            sy = y0 + i * gap + (gap - slat) / 2.0
            c.rect(px(x0 + 2), py(sy), max(w - 4, 2) * scale, slat * scale, fill=1, stroke=1)

    def _fan(cx_mm: float, cy_mm: float, d: float) -> None:
        r = max(d / 2.0, 8.0)
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.70)
        c.circle(px(cx_mm), py(cy_mm), r * scale, fill=1, stroke=1)
        c.setFont("Helvetica", max(5.0, min(8.0, r * scale * 0.28)))
        c.setFillColorRGB(0.35, 0.35, 0.38)
        c.drawCentredString(px(cx_mm), py(cy_mm) - 2.5, f"FAN Ø{int(round(d))}")

    def _hinge_h(cx_mm: float, cy_mm: float, leaf_w: float, stile: float) -> None:
        ww, hh = hinge_capsule_size_mm(leaf_w, stile, orientation="horizontal")
        g = hinge_capsule_geom(cx_mm, cy_mm, ww, hh)
        c.setFillColorRGB(*HINGE_FILL_RGB)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.40)
        c.roundRect(px(g["x"]), py(g["y"]), g["w"] * scale, g["h"] * scale, g["rx"] * scale, fill=1, stroke=1)
        c.setLineWidth(0.30)
        c.line(px(g["x1"]), py(g["y1"]), px(g["x2"]), py(g["y2"]))

    def _bay(role: str, bx: float, by: float, bw: float, bh: float) -> None:
        role = (role or "glass").lower()
        if role == "louvers":
            _louvers(bx, by, bw, bh)
            return
        if role == "top_hung":
            ov = min(max(frame_t * 0.20, 8.0), 16.0)
            sx, sy = bx - ov * 0.35, by
            swd, sh = bw + ov * 0.70, bh + ov * 0.35
            _glass(sx + sash_t, sy + sash_t, max(swd - 2 * sash_t, 4), max(sh - 2 * sash_t, 4))
            _frame_ring(sx, sy, swd, sh, sash_t)
            if handle_on:
                hx = sx + swd / 2.0
                hy = sy + sash_t * 0.55
                c.setStrokeColorRGB(*stroke)
                c.setLineWidth(0.50)
                c.circle(px(hx), py(hy), max(5.0 * scale, 2.2), fill=0, stroke=1)
            leaf_w = max(swd - 2 * sash_t, 40.0)
            xs = [sx + sash_t + leaf_w * (i + 1) / (hinge_n + 1) for i in range(hinge_n)]
            cy = sy + sh - sash_t * 0.50
            for cx in xs:
                _hinge_h(cx, cy, leaf_w, sash_t)
            # opening hint
            c.setStrokeColorRGB(0.04, 0.24, 0.48)
            c.setLineWidth(0.70)
            mx = sx + swd / 2.0
            c.line(px(mx), py(sy + sh * 0.55), px(mx), py(sy + sash_t + 8))
            return
        _glass(bx, by, bw, bh)

    if mode == "full_cutout":
        _glass(frame_t, frame_t, width - 2 * frame_t, height - 2 * frame_t)
        _frame_ring(0.0, 0.0, width, height, frame_t)
        _fan(width / 2.0, height * 0.52, min(fan_d, min(width, height) * 0.55))
    else:
        inner_y = frame_t
        inner_h = height - 2 * frame_t
        left_inner = max(left_w - frame_t - mull_t / 2.0, 8.0)
        right_inner = max(width - left_w - frame_t - mull_t / 2.0, 8.0)
        lx = frame_t
        rx = left_w + mull_t / 2.0
        _bay(left_role, lx, inner_y, left_inner, inner_h)
        _bay(right_role, rx, inner_y, right_inner, inner_h)
        if exhaust:
            if exhaust_side == "left":
                fcx = lx + left_inner / 2.0
            elif exhaust_side == "right":
                fcx = rx + right_inner / 2.0
            else:
                fcx = width / 2.0
            fcy = inner_y + min(max(fan_d * 0.45, 40.0), inner_h * 0.42)
            _fan(fcx, fcy, min(fan_d, min(left_inner, right_inner, inner_h) * 0.70))
        _frame_ring(0.0, 0.0, width, height, frame_t)
        # Mullion 90°
        mx0 = left_w - mull_t / 2.0
        c.setFillColorRGB(0.96, 0.96, 0.97)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        c.rect(px(mx0), py(frame_t), mull_t * scale, (height - 2 * frame_t) * scale, fill=1, stroke=1)
        c.setFillColorRGB(0.04, 0.24, 0.48)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawCentredString(px(lx + left_inner / 2.0), py(height / 2.0), left_role.replace("_", " ").upper())
        c.drawCentredString(px(rx + right_inner / 2.0), py(height / 2.0), right_role.replace("_", " ").upper())

    c.setFillColorRGB(0.20, 0.20, 0.22)
    c.setFont("Helvetica", 6.0)
    c.drawCentredString(px(width / 2.0), y + 5.0, f"{int(round(width))} × {int(round(height))} mm")
    return True
