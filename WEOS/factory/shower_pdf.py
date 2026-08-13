"""ReportLab shower elevation — slim solid black, matches canvas (no Cairo hang)."""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory.geometry import (
    HINGE_FILL_RGB,
    hinge_capsule_geom,
    hinge_capsule_size_mm,
    hinge_centers_mm,
    hinge_gap_axis,
)
from WEOS.factory.shower_engine import (
    DOOR_BOTTOM_CLEAR_MM,
    compute_shower,
    ensure_shower_dims,
    _door_side,
    _front_role,
    _handle_side,
    _hinge_side,
)


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
    cfg = opts.get("shower") if isinstance(opts, Mapping) else None
    if not isinstance(cfg, Mapping):
        cfg = line.get("shower") if isinstance(line.get("shower"), Mapping) else {}
    cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
    cfg = ensure_shower_dims(cfg, width=line.get("width"), height=line.get("height"))
    q = opts.get("showerQuote") if isinstance(opts, Mapping) else None
    if not isinstance(q, Mapping) or not q:
        q = compute_shower(cfg)
    return cfg, dict(q)


def draw_shower_elevation(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    cfg, q = _cfg_and_quote(line)
    panels = list(q.get("panels") or [])
    if not panels:
        return False
    height = _f(q.get("heightMm"), 2000)
    front_panels = [p for p in panels if str(p.get("wall") or "front") == "front"]
    if not front_panels:
        front_panels = panels[:2] or panels
    front_w = sum(_f(p.get("widthMm")) for p in front_panels) or _f(q.get("widthMm"), 1200)
    shape = _s(q.get("shape"), "straight")
    op = _s(q.get("operation"), "sliding")
    frame_kind = _s(q.get("frameKind"), "").lower()
    if frame_kind not in ("frameless", "profile"):
        frame_kind = "frameless" if bool(q.get("frameless")) else "profile"
    frameless = frame_kind == "frameless"
    handle_on = bool(q.get("handle"))
    door_side = _s(q.get("doorSide"), _door_side(cfg))
    if door_side not in ("left", "right"):
        door_side = "right"
    handle_side = _s(q.get("handleSide"), "")
    if handle_side not in ("left", "right"):
        handle_side = _handle_side(cfg, door_side=door_side)
    hinge_side = _s(q.get("hingeSide"), _hinge_side(handle_side) if op == "hinged" else "")
    hinge_count = min(max(_i(q.get("hingeCount") or q.get("hingesPerDoor"), 3), 2), 6)
    front_leaf = _front_role(cfg)
    depth_a = _f(q.get("depthMm"))
    depth_b = _f(q.get("depthBMm"))

    try:
        c.setDash()
    except Exception:
        pass
    c.setFillColorRGB(1, 1, 1)
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.40)
    c.rect(x, y, box_w, box_h, fill=1, stroke=1)

    want_plan = shape != "straight" and box_h > 78
    plan_h = 22.0 if want_plan else 0.0
    plan_gap = 6.0 if want_plan else 0.0
    m_left, m_right, m_bottom, m_top = 16.0, 14.0, 18.0 + plan_h + plan_gap, 12.0
    draw_w = max(box_w - m_left - m_right, 16.0)
    draw_h = max(box_h - m_bottom - m_top, 16.0)
    scale = min(draw_w / max(front_w, 1.0), draw_h / max(height, 1.0))
    ox = x + m_left + (draw_w - front_w * scale) / 2.0
    oy = y + m_bottom + (draw_h - height * scale) / 2.0

    def px(mx: float) -> float:
        return ox + mx * scale

    def py(my: float) -> float:
        return oy + my * scale

    stroke = (0.07, 0.07, 0.08)
    glass_fix = (0.90, 0.94, 0.97)
    glass_door = (0.82, 0.88, 0.94) if op == "sliding" else (0.91, 0.88, 0.80)
    lw = 0.62
    frame_t = 45.0
    chok_t = 50.0
    overlap = 10.0
    clear = DOOR_BOTTOM_CLEAR_MM  # 20 mm door shorter than fix
    lap_meet = max(frame_t * 0.28, 1.4)

    # Outer plate already white. Draw elevation in y-up mm (floor=0, head=height).
    geom: list[tuple[dict[str, Any], float, float]] = []
    cursor = 0.0
    for p in front_panels:
        pw = _f(p.get("widthMm"))
        geom.append((p, cursor, pw))
        cursor += pw

    door_g = next((g0 for g0 in geom if str(g0[0].get("role")) in ("sliding", "openable")), None)
    fix_g = next((g0 for g0 in geom if str(g0[0].get("role")) == "fix"), None)

    def _glass(x0, y0, w, h, fill) -> None:
        if w <= 0.5 or h <= 0.5:
            return
        c.setFillColorRGB(*fill)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        c.rect(px(x0), py(y0), w * scale, h * scale, fill=1, stroke=1)

    def _frame_ring(x0, y0, w, h, t, *, skip: set[str] | None = None, omit_side: str | None = None) -> None:
        t = min(max(t, 8.0), w / 2.4, h / 2.4)
        skip = set(skip or ())
        if omit_side == "right":
            skip.update(("tr", "br"))
        elif omit_side == "left":
            skip.update(("tl", "bl"))
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        c.setFillColorRGB(0.95, 0.95, 0.96)
        # Outer + inner as even-odd via two rects (outer stroke, inner hole implied by glass)
        c.rect(px(x0), py(y0), w * scale, h * scale, fill=0, stroke=1)
        ix0, iy0 = x0 + t, y0 + t
        iw, ih = w - 2 * t, h - 2 * t
        if omit_side == "right":
            c.rect(px(x0), py(y0), (w - t) * scale, h * scale, fill=0, stroke=1)
            c.line(px(x0 + w), py(y0 + t), px(x0 + w - t), py(y0 + h - t))
        elif omit_side == "left":
            c.rect(px(x0 + t), py(y0), (w - t) * scale, h * scale, fill=0, stroke=1)
        else:
            if iw > 1 and ih > 1:
                c.rect(px(ix0), py(iy0), iw * scale, ih * scale, fill=0, stroke=1)
        x1, y1 = x0 + w, y0 + h
        corners = {
            "tl": (x0, y1, x0 + t, y1 - t),
            "tr": (x1, y1, x1 - t, y1 - t),
            "br": (x1, y0, x1 - t, y0 + t),
            "bl": (x0, y0, x0 + t, y0 + t),
        }
        for key, (ax, ay, bx, by) in corners.items():
            if key in skip:
                continue
            c.line(px(ax), py(ay), px(bx), py(by))

    def _u_chokhat(x0, y0, w, h, t) -> None:
        t = min(max(t, 10.0), w / 2.8, h / 3.2)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        # Left jamb
        c.rect(px(x0), py(y0), t * scale, h * scale, fill=0, stroke=1)
        # Right jamb
        c.rect(px(x0 + w - t), py(y0), t * scale, h * scale, fill=0, stroke=1)
        # Head
        c.rect(px(x0), py(y0 + h - t), w * scale, t * scale, fill=0, stroke=1)
        # 45° miters at head/jamb
        c.line(px(x0), py(y0 + h), px(x0 + t), py(y0 + h - t))
        c.line(px(x0 + w), py(y0 + h), px(x0 + w - t), py(y0 + h - t))

    def _d_handle(stile_inner_x: float, y_mid: float, h: float, side: str) -> None:
        rod_w = max(min(h * 0.11, 18.0), 10.0)
        rod_h = max(h, 80.0)
        y0 = y_mid - rod_h / 2.0
        if side == "right":
            x0 = stile_inner_x - rod_w - 4.0
        else:
            x0 = stile_inner_x + 4.0
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.55)
        c.setFillColorRGB(0.91, 0.91, 0.92)
        c.roundRect(px(x0), py(y0), rod_w * scale, rod_h * scale, (rod_w / 2.0) * scale, fill=0, stroke=1)

    def _hinge_at(cx_mm: float, cy_mm: float, leaf_h_mm: float, stile_t_mm: float) -> None:
        ww, hh = hinge_capsule_size_mm(leaf_h_mm, stile_t_mm)
        gcap = hinge_capsule_geom(cx_mm, cy_mm, ww, hh)
        c.setFillColorRGB(*HINGE_FILL_RGB)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.40)
        c.roundRect(
            px(gcap["x"]), py(gcap["y"]),
            gcap["w"] * scale, gcap["h"] * scale,
            gcap["rx"] * scale, fill=1, stroke=1,
        )
        c.setLineWidth(0.30)
        c.line(px(gcap["x1"]), py(gcap["y1"]), px(gcap["x2"]), py(gcap["y2"]))

    door_box = None  # (x0, y0, w, h) y-up mm
    inner_x, inner_r = chok_t, front_w - chok_t
    inner_top = height - chok_t

    if frameless:
        xcur = 0.0
        for p, _px0, pw in geom:
            role = str(p.get("role") or "fix")
            gh = height - (clear if role in ("sliding", "openable") else 0.0)
            fill = glass_door if role in ("sliding", "openable") else glass_fix
            _glass(xcur, 0.0 if role == "fix" else clear, pw, gh, fill)
            if role in ("sliding", "openable"):
                door_box = (xcur, clear, pw, gh)
            xcur += pw
    elif op == "hinged" and len(geom) >= 2 and door_g and fix_g:
        operable_is_front = front_leaf == "door"
        if door_side == "right":
            junction = door_g[1]
            fix_x0, fix_w = inner_x, max(junction - inner_x, frame_t * 2)
            fix_y0, fix_h = 0.0, inner_top
            door_x0 = junction
            door_x1 = inner_r + overlap
            door_y0 = clear
            door_h = max(inner_top + overlap - clear, frame_t * 3)
            door_w = max(door_x1 - door_x0, frame_t * 2)
            fix_skip: set[str] = set()
            door_skip: set[str] = set()
            if operable_is_front:
                door_x0 -= lap_meet
                door_w += lap_meet
                fix_skip = {"tr", "br"}
            else:
                fix_w += lap_meet
                door_skip = {"tl", "bl"}
        else:
            junction = door_g[1] + door_g[2]
            door_x0 = inner_x - overlap
            door_y0 = clear
            door_w = max(junction - door_x0, frame_t * 2)
            door_h = max(inner_top + overlap - clear, frame_t * 3)
            fix_x0, fix_w = junction, max(inner_r - junction, frame_t * 2)
            fix_y0, fix_h = 0.0, inner_top
            fix_skip = set()
            door_skip = set()
            if operable_is_front:
                door_w += lap_meet
                fix_skip = {"tl", "bl"}
            else:
                fix_x0 -= lap_meet
                fix_w += lap_meet
                door_skip = {"tr", "br"}
        # Glass fills first
        _glass(fix_x0 + frame_t * 0.15, fix_y0 + 2, max(fix_w - frame_t * 0.3, 4), max(fix_h - 4, 4), glass_fix)
        _glass(door_x0 + frame_t * 0.15, door_y0 + 2, max(door_w - frame_t * 0.3, 4), max(door_h - 4, 4), glass_door)
        if operable_is_front:
            _frame_ring(fix_x0, fix_y0, fix_w, fix_h, frame_t, skip=fix_skip)
            _frame_ring(door_x0, door_y0, door_w, door_h, frame_t, skip=door_skip)
        else:
            _frame_ring(door_x0, door_y0, door_w, door_h, frame_t, skip=door_skip)
            _frame_ring(fix_x0, fix_y0, fix_w, fix_h, frame_t, skip=fix_skip)
        _u_chokhat(0.0, 0.0, front_w, height, chok_t)
        door_box = (door_x0, door_y0, door_w, door_h)
        # Hinges on outer | door gap
        if hinge_side in ("left", "right"):
            chok_inner = (front_w - chok_t) if hinge_side == "right" else chok_t
            sash_face = (door_x0 + door_w) if hinge_side == "right" else door_x0
            hx = hinge_gap_axis(sash_face, chok_inner, toward_frame=1.0 if hinge_side == "right" else -1.0)
            for y_from_top in hinge_centers_mm(door_h, hinge_count):
                cy = door_y0 + door_h - y_from_top
                _hinge_at(hx, cy, door_h, frame_t)
    elif op == "sliding" and len(geom) >= 2:
        junction = geom[0][1] + geom[0][2]
        stile_x = junction - frame_t / 2.0
        slide_on_right = bool(door_g and fix_g and door_g[1] >= fix_g[1])
        slide_h = max(height - clear, frame_t * 3)
        if slide_on_right:
            _glass(0.0, 0.0, max(stile_x + frame_t, frame_t * 2), height, glass_fix)
            _glass(stile_x, clear, max(front_w - stile_x, frame_t * 2), slide_h, glass_door)
            _frame_ring(0.0, 0.0, max(stile_x + frame_t, frame_t * 2), height, frame_t, omit_side="right")
            _frame_ring(stile_x, clear, max(front_w - stile_x, frame_t * 2), slide_h, frame_t)
            door_box = (stile_x, clear, max(front_w - stile_x, frame_t * 2), slide_h)
        else:
            _glass(0.0, clear, max(stile_x + frame_t, frame_t * 2), slide_h, glass_door)
            _glass(stile_x, 0.0, max(front_w - stile_x, frame_t * 2), height, glass_fix)
            _frame_ring(0.0, clear, max(stile_x + frame_t, frame_t * 2), slide_h, frame_t)
            _frame_ring(stile_x, 0.0, max(front_w - stile_x, frame_t * 2), height, frame_t, omit_side="left")
            door_box = (0.0, clear, max(stile_x + frame_t, frame_t * 2), slide_h)
        # Top track
        c.setFillColorRGB(0.82, 0.82, 0.85)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        c.rect(px(0), py(height), front_w * scale, max(14.0 * scale, 3.5), fill=1, stroke=1)
    else:
        _glass(0.0, 0.0, front_w, height, glass_fix)
        _frame_ring(0.0, 0.0, front_w, height, frame_t)
        if door_g:
            role = str(door_g[0].get("role") or "")
            dh = height - (clear if role in ("sliding", "openable") else 0.0)
            door_box = (door_g[1], clear if role in ("sliding", "openable") else 0.0, door_g[2], dh)

    if door_box and handle_on:
        dx, dy, dw, dh = door_box
        if handle_side == "right":
            stile_inner = dx + dw - (0.0 if frameless else frame_t)
        else:
            stile_inner = dx + (0.0 if frameless else frame_t)
        _d_handle(stile_inner, dy + dh * 0.48, max(dh * 0.16, 90.0), handle_side)

    # Panel labels
    c.setFillColorRGB(0.04, 0.24, 0.48)
    c.setFont("Helvetica-Bold", 6.5)
    xcur = 0.0
    for p, _px0, pw in geom:
        lab = str(p.get("label") or str(p.get("role") or "").upper())
        c.drawCentredString(px(xcur + pw / 2.0), py(height * 0.52), lab[:10])
        xcur += pw

    c.setFillColorRGB(0.15, 0.15, 0.16)
    c.setFont("Helvetica", 6.0)
    c.drawString(x + 4, y + box_h - 10, f"Shower · {shape} · {op}")

    if want_plan:
        py0 = y + 6
        psw = 0.70
        max_return = max(depth_a, depth_b, 1.0)
        pscale = min(0.22, (box_w - 28) / max(front_w, 1.0), 18.0 / max_return)
        fw = front_w * pscale
        da = depth_a * pscale
        db = depth_b * pscale
        px0 = x + 14
        fy = py0 + 4
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(psw)
        if shape == "L":
            c.line(px0, fy, px0, fy + da)
            c.line(px0, fy + da, px0 + fw, fy + da)
        elif shape == "U":
            c.line(px0, fy, px0, fy + da)
            c.line(px0, fy + da, px0 + fw, fy + da)
            c.line(px0 + fw, fy + da, px0 + fw, fy + da - db if db < da else fy)
            c.line(px0 + fw, fy + da, px0 + fw, fy)
        c.setFillColorRGB(0.35, 0.35, 0.38)
        c.setFont("Helvetica", 5.0)
        c.drawString(px0, fy + max(da, 8) + 4, f"plan {shape}")
    return True
