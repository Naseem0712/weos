"""ReportLab elevation drawer — same geometry engine as live canvas, sized for PDF columns."""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory.geometry import HINGE_FILL_RGB, hinge_capsule_geom
from WEOS.factory.svg_export import _parse_grid
from WEOS.factory.types import DrawingModel, Polyline


def _handle_finish_rgb(finish: str) -> dict[str, tuple[float, float, float]]:
    """2D outline handle line colour (no solid fill)."""
    if str(finish).lower() in ("black", "black_texture", "matte_black", "dark"):
        return {"stroke": (0.11, 0.12, 0.14)}
    return {"stroke": (0.42, 0.45, 0.47)}


def _resolve_finish(meta: Mapping, colour: str | None) -> str:
    f = str(meta.get("handle_finish") or "")
    if f:
        return f
    cl = str(colour or "").lower()
    return "black" if ("black" in cl or "dark" in cl) else "silver"


def _bbox(pl: Polyline) -> tuple[float, float, float, float] | None:
    if len(pl.points) < 2:
        return None
    xs = [p.x for p in pl.points]
    ys = [p.y for p in pl.points]
    return min(xs), min(ys), max(xs), max(ys)


def _glasses(model: DrawingModel) -> list[tuple[str, float, float, float, float]]:
    out: list[tuple[str, float, float, float, float]] = []
    for pl in model.polylines:
        if pl.layer != "GLASS":
            continue
        bb = _bbox(pl)
        if bb:
            out.append((pl.name or f"glass_{len(out)+1}", *bb))
    out.sort(key=lambda g: (-(g[4] + g[2]) / 2.0, g[1]))  # top→bottom, then left→right
    return out


def _draw_casement_hinge_pdf(c, px, py, scale: float, x0: float, y0: float, x1: float, y1: float, stroke_rgb, *, lw: float = 0.40) -> None:
    """Light stadium hinge + horizontal barrel split — same glyph as live SVG preview."""
    w_m = abs(float(x1) - float(x0))
    h_m = abs(float(y1) - float(y0))
    if w_m <= 0.2 or h_m <= 0.2:
        return
    g = hinge_capsule_geom((float(x0) + float(x1)) / 2.0, (float(y0) + float(y1)) / 2.0, w_m, h_m)
    c.setFillColorRGB(*HINGE_FILL_RGB)
    c.setStrokeColorRGB(*stroke_rgb)
    c.setLineWidth(lw)
    c.roundRect(px(g["x"]), py(g["y"]), g["w"] * scale, g["h"] * scale, g["rx"] * scale, fill=1, stroke=1)
    c.setLineWidth(max(lw * 0.7, 0.3))
    c.line(px(g["x1"]), py(g["y1"]), px(g["x2"]), py(g["y2"]))


def _hollow_plan_band(c, x: float, y: float, w: float, h: float, *, lw: float = 0.55) -> None:
    """Thin hollow sash section for plan view."""
    if w < 1.5 or h < 1.0:
        return
    c.setLineWidth(lw)
    c.rect(x, y, w, h, fill=0, stroke=1)
    ix = min(max(w * 0.015, 0.6), 2.2)
    iy = max(h * 0.22, 0.7)
    if w > ix * 2.5 and h > iy * 2.4:
        c.setLineWidth(lw * 0.75)
        c.rect(x + ix, y + iy, w - 2 * ix, h - 2 * iy, fill=0, stroke=1)


def _draw_grid_pdf(c, *, px, py, scale, meta, W, H, finish, stroke, dim, glass_stroke) -> None:
    """Clean 2D partition-grid in the PDF (frames, per-cell role + hardware, dims)."""
    grid = meta.get("grid") or {}
    cells = grid.get("cells") or []
    fc = _handle_finish_rgb(finish)
    role_rgb = {"fix": (0.35, 0.22, 0.05), "sliding": (0.05, 0.24, 0.48), "openable": (0.04, 0.42, 0.24)}
    role_text = {"fix": "FIX", "sliding": "SLIDING", "openable": "OPENABLE"}

    def rect_ol(x0, y0, x1, y1, lw, rgb=stroke, dash=None):
        c.setStrokeColorRGB(*rgb)
        c.setLineWidth(lw)
        if dash:
            c.setDash(*dash)
        c.rect(px(x0), py(y0), (x1 - x0) * scale, (y1 - y0) * scale, fill=0, stroke=1)
        if dash:
            c.setDash()

    # Outer frame
    rect_ol(0, 0, W, H, 0.70)

    for cell in cells:
        x0, y0, x1, y1 = float(cell["x0"]), float(cell["y0"]), float(cell["x1"]), float(cell["y1"])
        role = cell.get("role") or "fix"
        rect_ol(x0, y0, x1, y1, 0.65)
        for g in cell.get("glass") or []:
            gx0, gy0, gx1, gy1 = float(g["x0"]), float(g["y0"]), float(g["x1"]), float(g["y1"])
            c.setFillColorRGB(0.88, 0.93, 0.97)
            c.setStrokeColorRGB(*glass_stroke)
            c.setLineWidth(0.55)
            c.rect(px(gx0), py(gy0), (gx1 - gx0) * scale, (gy1 - gy0) * scale, fill=1, stroke=1)
        for sx in cell.get("sashLines") or []:
            c.setStrokeColorRGB(*stroke)
            c.setLineWidth(0.55)
            c.line(px(float(sx)), py(y0), px(float(sx)), py(y1))
        m = cell.get("mesh")
        if isinstance(m, Mapping):
            c.setStrokeColorRGB(0.15, 0.45, 0.30)
            c.setLineWidth(0.55)
            c.rect(px(float(m["x0"])), py(float(m["y0"])), (float(m["x1"]) - float(m["x0"])) * scale, (float(m["y1"]) - float(m["y0"])) * scale, fill=0, stroke=1)
        for d in cell.get("diagonals") or []:
            c.setStrokeColorRGB(*role_rgb.get(role, (0.1, 0.1, 0.1)))
            c.setLineWidth(0.50)
            c.line(px(float(d[0])), py(float(d[1])), px(float(d[2])), py(float(d[3])))
        for a in cell.get("arrows") or []:
            c.setStrokeColorRGB(0.05, 0.24, 0.48)
            c.setLineWidth(0.75)
            ax0, ay0, ax1, ay1 = float(a["x0"]), float(a["y0"]), float(a["x1"]), float(a["y1"])
            c.line(px(ax0), py(ay0), px(ax1), py(ay1))
            ah = 2.6
            dirx = 1 if ax1 > ax0 else -1
            c.line(px(ax1), py(ay1), px(ax1) - dirx * ah, py(ay1) + ah * 0.7)
            c.line(px(ax1), py(ay1), px(ax1) - dirx * ah, py(ay1) - ah * 0.7)
        # Hinges (stadium + horizontal barrel split)
        for hg in cell.get("hinges") or []:
            _draw_casement_hinge_pdf(
                c, px, py, scale,
                float(hg["x0"]), float(hg["y0"]), float(hg["x1"]), float(hg["y1"]),
                fc["stroke"], lw=0.40,
            )
        # Handles (outline lever)
        for hd in cell.get("handles") or []:
            hx0, hy0, hx1, hy1 = float(hd["x0"]), float(hd["y0"]), float(hd["x1"]), float(hd["y1"])
            hcx, hcy = (hx0 + hx1) / 2.0, (hy0 + hy1) / 2.0
            pw, ph = (hx1 - hx0), (hy1 - hy0)
            rx = max(pw * 0.6, 2.0)
            ry = max(ph * 0.5, 4.0)
            c.setStrokeColorRGB(*fc["stroke"])
            c.setLineWidth(0.50)
            c.ellipse(px(hcx) - rx * scale, py(hcy) - ry * scale, px(hcx) + rx * scale, py(hcy) + ry * scale, fill=0, stroke=1)
            direction = -1.0 if hd.get("side") == "right" else 1.0
            arm = max(pw * 2.4, 10.0)
            bar_h = max(pw * 0.52, 2.0) * scale
            lx0 = hcx if direction > 0 else hcx - arm
            lx1 = hcx + arm if direction > 0 else hcx
            ly = hcy - ry * 0.35
            c.roundRect(px(lx0), py(ly) - bar_h / 2, (lx1 - lx0) * scale, bar_h, bar_h / 2, fill=0, stroke=1)
        # Labels + size
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        cw = 20
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(0.2, 0.2, 0.2)
        c.setLineWidth(0.5)
        c.roundRect(px(cx) - cw / 2, py(cy) - 5, cw, 10, 1.5, fill=1, stroke=1)
        c.setFillColorRGB(0.05, 0.05, 0.05)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(px(cx), py(cy) - 2.2, str(cell.get("label") or ""))
        c.setFillColorRGB(*role_rgb.get(role, (0.1, 0.1, 0.1)))
        c.setFont("Helvetica-Bold", 6)
        c.drawCentredString(px(cx), py(cy) + 8, role_text.get(role, role.upper()))
        c.setFillColorRGB(0.28, 0.28, 0.28)
        c.setFont("Helvetica", 5.5)
        c.drawCentredString(px(cx), py(cy) - 13, f"{cell.get('wmm')}\u00d7{cell.get('hmm')}")

    # Dimensions
    colX = grid.get("colX") or [0, W]
    rowTop = grid.get("rowTop") or [H, 0]
    c.setStrokeColorRGB(*dim)
    c.setFillColorRGB(*dim)

    def dh(x0, x1, ymm, txt, fs=6.5):
        yy = py(ymm)
        c.setLineWidth(0.55)
        c.line(px(x0), yy, px(x1), yy)
        c.line(px(x0), yy - 2.2, px(x0), yy + 2.2)
        c.line(px(x1), yy - 2.2, px(x1), yy + 2.2)
        c.setFont("Helvetica", fs)
        c.drawCentredString((px(x0) + px(x1)) / 2.0, yy - 8, txt)

    def dv(y0, y1, xmm, txt, fs=6.5):
        xx = px(xmm)
        c.setLineWidth(0.55)
        c.line(xx, py(y0), xx, py(y1))
        c.line(xx - 2.2, py(y0), xx + 2.2, py(y0))
        c.line(xx - 2.2, py(y1), xx + 2.2, py(y1))
        c.setFont("Helvetica", fs)
        c.saveState()
        c.translate(xx - 8, (py(y0) + py(y1)) / 2.0)
        c.rotate(90)
        c.drawCentredString(0, 0, txt)
        c.restoreState()

    dv(0.0, H, -14.0 / max(scale, 1e-6), f"{H:g}")
    dh(0.0, W, -20.0 / max(scale, 1e-6), f"{W:g}")
    for i in range(len(colX) - 1):
        dh(float(colX[i]), float(colX[i + 1]), -9.0 / max(scale, 1e-6), f"{float(colX[i+1])-float(colX[i]):g}", fs=5.5)
    for i in range(len(rowTop) - 1):
        dv(float(rowTop[i + 1]), float(rowTop[i]), W + 12.0 / max(scale, 1e-6), f"{float(rowTop[i])-float(rowTop[i+1]):g}", fs=5.5)


def draw_model_elevation(
    c,
    model: DrawingModel,
    x: float,
    y: float,
    box_w: float,
    box_h: float,
    *,
    colour: str | None = None,
    grid: Any = None,
    include_plan: bool = True,
) -> None:
    """Draw DrawingModel into a PDF box with MAR-QT-style dims / panel labels / optional grids.

    Drafting style: profile outlines only (no solid colour fills), light glass, thin plan.
    ``colour`` is accepted for API compatibility but does not fill frames.
    """
    meta = model.metadata or {}
    finish = _resolve_finish(meta, colour)
    W = float(model.width)
    H = float(model.height)
    glasses = _glasses(model)
    grid_div = _parse_grid(grid)

    plan_h = 20.0 if include_plan else 0.0
    plan_gap = 7.0 if include_plan else 0.0
    # Margins reserved for dimension text (PDF points)
    m_left, m_right, m_bottom, m_top = 28.0, 26.0, 34.0 + plan_h + plan_gap, 8.0
    draw_w = max(box_w - m_left - m_right, 20.0)
    draw_h = max(box_h - m_bottom - m_top, 20.0)
    scale = min(draw_w / max(W, 1.0), draw_h / max(H, 1.0))
    ox = x + m_left + (draw_w - W * scale) / 2.0
    oy = y + m_bottom + (draw_h - H * scale) / 2.0

    def px(mx: float) -> float:
        return ox + mx * scale

    def py(my: float) -> float:
        return oy + my * scale

    stroke = (0.07, 0.07, 0.08)  # solid black frames
    dim = (0.55, 0.12, 0.10)
    glass_stroke = (0.07, 0.07, 0.08)  # solid black glass edge
    try:
        c.setDash()
    except Exception:
        pass

    # White plate behind drawing
    c.setFillColorRGB(1, 1, 1)
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.40)
    c.rect(x, y, box_w, box_h, fill=1, stroke=1)

    # Partition/grid designer — dedicated clean 2D from metadata (matches canvas)
    if str(meta.get("system") or "") == "grid":
        _draw_grid_pdf(c, px=px, py=py, scale=scale, meta=meta, W=W, H=H, finish=finish, stroke=stroke, dim=dim, glass_stroke=glass_stroke)
        return

    # Glass fills first — light tint only (never solid dark)
    for pl in model.polylines:
        if pl.layer != "GLASS" or len(pl.points) < 2:
            continue
        path = c.beginPath()
        path.moveTo(px(pl.points[0].x), py(pl.points[0].y))
        for p in pl.points[1:]:
            path.lineTo(px(p.x), py(p.y))
        path.close()
        c.setFillColorRGB(0.88, 0.93, 0.97)  # very light
        c.setStrokeColorRGB(*glass_stroke)
        c.setLineWidth(0.55)
        c.drawPath(path, fill=1, stroke=1)

    # Closed profile outlines (no fill)
    for pl in model.polylines:
        if len(pl.points) < 2 or pl.layer in ("GLASS", "HARDWARE") or not pl.closed:
            continue
        path = c.beginPath()
        path.moveTo(px(pl.points[0].x), py(pl.points[0].y))
        for p in pl.points[1:]:
            path.lineTo(px(p.x), py(p.y))
        path.close()
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.72)  # slim print-safe profile (not hairline RIP dots)
        c.drawPath(path, fill=0, stroke=1)

    for pl in model.polylines:
        if pl.closed or pl.layer == "GLASS" or len(pl.points) < 2:
            continue
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.62)
        for a, b in zip(pl.points, pl.points[1:]):
            c.line(px(a.x), py(a.y), px(b.x), py(b.y))

    for seg in model.segments:
        lname = (seg.name or "").lower()
        is_il = "interlock" in lname or "meeting" in lname
        if is_il:
            c.setStrokeColorRGB(0.05, 0.05, 0.06)
            c.setLineWidth(0.80)
        else:
            c.setStrokeColorRGB(*stroke if seg.layer == "PROFILES" else (0.20, 0.20, 0.22))
            c.setLineWidth(0.62)
        c.line(px(seg.start.x), py(seg.start.y), px(seg.end.x), py(seg.end.y))

    # Hardware — casement hinge capsules + lever handles (outline)
    fc = _handle_finish_rgb(finish)
    for h in meta.get("hinges") or []:
        if not isinstance(h, Mapping):
            continue
        hx0, hy0, hx1, hy1 = float(h["x0"]), float(h["y0"]), float(h["x1"]), float(h["y1"])
        _draw_casement_hinge_pdf(c, px, py, scale, hx0, hy0, hx1, hy1, fc["stroke"], lw=0.40)
    for sp in meta.get("shutters") or []:
        if not isinstance(sp, Mapping):
            continue
        hd = sp.get("handle")
        if not isinstance(hd, Mapping):
            continue
        hx0, hy0, hx1, hy1 = float(hd["x0"]), float(hd["y0"]), float(hd["x1"]), float(hd["y1"])
        hcx, hcy = (hx0 + hx1) / 2.0, (hy0 + hy1) / 2.0
        pw, ph = (hx1 - hx0), (hy1 - hy0)
        rx = max(pw * 0.60, 2.0)
        ry = max(ph * 0.5, 4.0)
        c.setStrokeColorRGB(*fc["stroke"])
        c.setLineWidth(0.50)
        # oval escutcheon (outline)
        c.ellipse(px(hcx) - rx * scale, py(hcy) - ry * scale, px(hcx) + rx * scale, py(hcy) + ry * scale, fill=0, stroke=1)
        # keyhole hint
        c.circle(px(hcx), py(hcy) + ry * 0.32 * scale, max(pw * 0.16, 1.2) * scale, fill=0, stroke=1)
        # lever arm into the leaf (outline)
        direction = -1.0 if sp.get("handleSide") == "right" else 1.0
        arm = max(pw * 2.4, 10.0)
        bar_h = max(pw * 0.52, 2.0) * scale
        lx0 = hcx if direction > 0 else hcx - arm
        lx1 = hcx + arm if direction > 0 else hcx
        ly = hcy - ry * 0.35
        c.roundRect(px(lx0), py(ly) - bar_h / 2, (lx1 - lx0) * scale, bar_h, bar_h / 2, fill=0, stroke=1)

    # Muntin grids
    if grid_div:
        cols, rows = grid_div
        c.setStrokeColorRGB(0.30, 0.42, 0.55)
        c.setLineWidth(0.55)
        for _n, x0, y0, x1, y1 in glasses:
            gw, gh = x1 - x0, y1 - y0
            for i in range(1, max(cols, 1)):
                gx = x0 + gw * i / cols
                c.line(px(gx), py(y0), px(gx), py(y1))
            for j in range(1, max(rows, 1)):
                gy = y0 + gh * j / rows
                c.line(px(x0), py(gy), px(x1), py(gy))

    # Panel labels + sliding arrows
    import re as _re
    system = str(meta.get("system") or "sliding")
    sys_role = {"casement": "OPENABLE", "openable": "OPENABLE", "bifold": "FOLD"}.get(system, "SLIDING")
    shutters_by_idx = {
        int(s["index"]): s
        for s in (meta.get("shutters") or [])
        if isinstance(s, Mapping) and s.get("index") is not None
    }
    c.setFont("Helvetica-Bold", 7)
    slide_idx = 0
    fix_idx = 0
    # Sliding sashes labelled A1, A2 … from the RIGHT (rightmost = A1), like reference.
    n_slide = sum(
        1 for _nm, *_ in glasses
        if not any(t in (str(_nm) or "").lower() for t in ("fix", "leaf", "door"))
    )
    for name, x0, y0, x1, y1 in glasses:
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        lname = (name or "").lower()
        _m = _re.search(r"(\d+)", lname)
        sp_meta = shutters_by_idx.get(int(_m.group(1))) if _m else None
        is_sliding = False
        if "fix" in lname:
            fix_idx += 1
            panel_id, role = f"F{fix_idx}", "FIX"
            role_rgb = (0.35, 0.22, 0.05)
        elif "leaf" in lname:
            slide_idx += 1
            panel_id, role = f"L{slide_idx}", "FOLD"
            role_rgb = (0.05, 0.30, 0.55)
        elif "door" in lname:
            panel_id, role = "D1", "DOOR"
            role_rgb = (0.05, 0.30, 0.55)
        else:
            slide_idx += 1
            panel_id, role = f"A{max(n_slide - slide_idx + 1, 1)}", sys_role
            role_rgb = (0.05, 0.30, 0.55)
            is_sliding = role == "SLIDING"

        if not is_sliding:
            chip_w, chip_h = 18, 9
            c.setFillColorRGB(1, 1, 1)
            c.setStrokeColorRGB(0.2, 0.2, 0.2)
            c.setLineWidth(0.5)
            c.roundRect(px(cx) - chip_w / 2, py(cy + (y1 - y0) * 0.28) - chip_h / 2, chip_w, chip_h, 1.5, fill=1, stroke=1)
            c.setFillColorRGB(0.05, 0.05, 0.05)
            c.drawCentredString(px(cx), py(cy + (y1 - y0) * 0.28) - 2.2, panel_id)

        c.setFillColorRGB(*role_rgb)
        c.setFont("Helvetica-Bold", 6)
        c.drawCentredString(px(cx), py(cy - (y1 - y0) * 0.30) - 2, role)
        c.setFont("Helvetica-Bold", 7)

        if is_sliding:
            c.setStrokeColorRGB(0.05, 0.30, 0.55)
            c.setFillColorRGB(0.05, 0.30, 0.55)
            c.setLineWidth(0.75)
            ay = cy
            od = float(sp_meta.get("openDir") or 0) if sp_meta else 0.0
            if od == 0:
                od = 1.0 if slide_idx % 2 == 1 else -1.0
            if od > 0:
                ax0, ax1 = cx - (x1 - x0) * 0.24, cx + (x1 - x0) * 0.22
                lx, align = ax0 - (x1 - x0) * 0.02, "right"
            else:
                ax0, ax1 = cx + (x1 - x0) * 0.24, cx - (x1 - x0) * 0.22
                lx, align = ax0 + (x1 - x0) * 0.02, "left"
            c.line(px(ax0), py(ay), px(ax1), py(ay))
            ah = 2.8
            direction = 1 if ax1 > ax0 else -1
            c.line(px(ax1), py(ay), px(ax1) - direction * ah, py(ay) + ah * 0.7)
            c.line(px(ax1), py(ay), px(ax1) - direction * ah, py(ay) - ah * 0.7)
            c.setFont("Helvetica-Bold", 7)
            if align == "right":
                c.drawRightString(px(lx), py(ay) - 8, panel_id)
            else:
                c.drawString(px(lx), py(ay) - 8, panel_id)

    # Dimension helpers in PDF points
    def dim_h(x0: float, x1: float, y_mm: float, text: str, text_dy: float = -9) -> None:
        c.setStrokeColorRGB(*dim)
        c.setFillColorRGB(*dim)
        c.setLineWidth(0.55)
        yy = py(y_mm)
        c.line(px(x0), yy, px(x1), yy)
        c.line(px(x0), yy - 2.2, px(x0), yy + 2.2)
        c.line(px(x1), yy - 2.2, px(x1), yy + 2.2)
        c.setFont("Helvetica", 6.5)
        c.drawCentredString((px(x0) + px(x1)) / 2.0, yy + text_dy, text)

    def dim_v(y0: float, y1: float, x_mm: float, text: str, text_dx: float = -8) -> None:
        c.setStrokeColorRGB(*dim)
        c.setFillColorRGB(*dim)
        c.setLineWidth(0.55)
        xx = px(x_mm)
        c.line(xx, py(y0), xx, py(y1))
        c.line(xx - 2.2, py(y0), xx + 2.2, py(y0))
        c.line(xx - 2.2, py(y1), xx + 2.2, py(y1))
        c.setFont("Helvetica", 6.5)
        c.saveState()
        c.translate(xx + text_dx, (py(y0) + py(y1)) / 2.0)
        c.rotate(90)
        c.drawCentredString(0, 0, text)
        c.restoreState()

    shutters_meta = [s for s in (meta.get("shutters") or []) if isinstance(s, Mapping)]
    glass_meta = [s for s in shutters_meta if s.get("role") == "glass"]
    mesh_meta = [s for s in shutters_meta if s.get("role") == "mesh"]
    mesh = bool(meta.get("mesh"))
    track_count = float(meta.get("track_count") or 2)
    system = str(meta.get("system") or "sliding")

    # Overall H left, overall W bottom
    dim_v(0.0, H, -18.0 / max(scale, 1e-6), f"{H:g}", text_dx=-9)
    dim_h(0.0, W, -28.0 / max(scale, 1e-6), f"{W:g}", text_dy=-9)
    # Per-shutter equal-division widths (nominal shares)
    if glass_meta:
        for s in glass_meta:
            nx0 = float(s.get("nomX0") or s.get("x0") or 0.0)
            nx1 = float(s.get("nomX1") or s.get("x1") or 0.0)
            dim_h(nx0, nx1, -12.0 / max(scale, 1e-6), f"{(nx1 - nx0):g}", text_dy=-8)
    sliding_glasses = [g for g in glasses if "fix" not in (g[0] or "").lower()]
    if sliding_glasses:
        _n, _a, gy0, _b, gy1 = sliding_glasses[0]
        dim_v(gy0, gy1, W + 14.0 / max(scale, 1e-6), f"{(gy1 - gy0):g}", text_dx=8)

    # Section sizes (bifold): top/bottom rail + jamb/leaf stile — printed on the PDF
    sec = meta.get("sectionSizes")
    if isinstance(sec, Mapping):
        c.setFont("Helvetica", 5.5)
        c.setFillColorRGB(*dim)
        bits = [
            f"Top {sec.get('topRail','?')}", f"Bot {sec.get('bottomRail','?')}",
            f"Jamb {sec.get('leftJamb','?')}/{sec.get('rightJamb','?')}", f"Leaf {sec.get('leafStile','?')}",
        ]
        c.drawString(px(0), py(H) + 3, "Sections(mm): " + "  ".join(bits))
    notes = meta.get("notes") or []
    if notes:
        c.setFont("Helvetica-Oblique", 5)
        c.setFillColorRGB(0.55, 0.12, 0.10)
        c.drawString(px(0), y + 0.5, "; ".join(str(n) for n in notes)[:120])

    if include_plan and plan_h > 0:
        py0 = y + 4
        box_ph = plan_h - 4
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.55)
        c.rect(px(0), py0, W * scale, box_ph, fill=0, stroke=1)
        c.setFont("Helvetica", 5)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawCentredString(px(W / 2), py0 + box_ph + 1.5, "PLAN")

        ymid = py0 + box_ph / 2
        band = box_ph * 0.32
        if system == "bifold" and glass_meta:
            # Accordion zigzag across leaf boundaries
            bounds = [float(glass_meta[0].get("nomX0") or 0)] + [float(s.get("nomX1") or 0) for s in glass_meta]
            amp = box_ph * 0.32
            c.setStrokeColorRGB(0.09, 0.23, 0.39)
            c.setLineWidth(0.8)
            prev = None
            for j, bx in enumerate(bounds):
                yy = ymid + (amp if j % 2 == 0 else -amp)
                if prev is not None:
                    c.line(px(prev[0]), prev[1], px(bx), yy)
                prev = (bx, yy)
        elif system in ("casement", "openable", "opening") and glass_meta:
            # Openable plan: sash bar + swing line toward the hinge stile
            for s in glass_meta:
                sx0, sx1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
                c.setStrokeColorRGB(0.09, 0.23, 0.39)
                _hollow_plan_band(c, px(sx0), ymid - band / 2, (sx1 - sx0) * scale, band, lw=0.55)
                hinge = s.get("hingeSide") or "left"
                hx = sx0 if hinge == "left" else sx1
                c.setStrokeColorRGB(0.55, 0.12, 0.10)
                c.setLineWidth(0.5)
                c.line(px(hx), ymid, px((sx0 + sx1) / 2), ymid + band * 1.1)
        elif glass_meta:
            # Sliding: External / Internal offset track indicator (reference Image B)
            depths = sorted({int(s.get("depth") or 1) for s in glass_meta}) or [1]
            dmin = depths[0]
            ext_y = ymid + band * 0.55
            int_y = ymid - band * 0.55
            c.setFont("Helvetica", 4.5)
            c.setFillColorRGB(0.05, 0.24, 0.48)
            left_x = min(float(s.get("x0") or 0) for s in glass_meta)
            c.drawRightString(px(left_x) - 2, ext_y - 1.5, "External")
            c.drawRightString(px(left_x) - 2, int_y - 1.5, "Internal")
            for s in mesh_meta:
                mx0, mx1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
                c.setStrokeColorRGB(0.15, 0.45, 0.30)
                c.setLineWidth(1.0)
                c.line(px(mx0), int_y - band * 0.5, px(mx1), int_y - band * 0.5)
            for pos, s in enumerate(glass_meta):
                sx0, sx1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
                is_front = int(s.get("depth") or 1) == dmin
                yy = int_y if is_front else ext_y
                c.setStrokeColorRGB(0.05, 0.24, 0.48)
                c.setLineWidth(1.0)
                c.line(px(sx0), yy, px(sx1), yy)
                for ex in (sx0, sx1):
                    c.line(px(ex), yy - 2, px(ex), yy + 2)
                cxp = (sx0 + sx1) / 2.0
                num_y = ymid - band * 1.15
                c.setLineWidth(0.8)
                c.circle(px(cxp), num_y, 4.5, fill=0, stroke=1)
                c.setFont("Helvetica", 5)
                c.setFillColorRGB(0.05, 0.24, 0.48)
                c.drawCentredString(px(cxp), num_y - 1.8, str(pos + 1))


def draw_line_model_elevation(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    """Regenerate geometry for a cart line and draw it. Returns False if unavailable."""
    from WEOS.factory.line_kind import is_railing_cart_line, is_shower_cart_line, is_ventilator_cart_line

    # Never regenerate window geometry for designer lines (ReportLab drawers handle them).
    if is_railing_cart_line(line) or is_shower_cart_line(line) or is_ventilator_cart_line(line):
        return False
    w = float(line.get("width") or 0)
    h = float(line.get("height") or 0)
    if w <= 0 or h <= 0:
        return False
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    colour = (opts or {}).get("colour") or line.get("colour") or "white"
    grid = (opts or {}).get("grid") or (opts or {}).get("grille") or line.get("grid")
    product = str(line.get("product") or line.get("productId") or "29mm_sliding")
    # calculate_line replaces glass with a sized list — prefer option string
    glass = (opts or {}).get("glass")
    if not isinstance(glass, str):
        g = line.get("glass")
        glass = g if isinstance(g, str) else None
    handle = (opts or {}).get("handle") or line.get("handle")
    if not isinstance(handle, str):
        handle = None
    from WEOS.factory.layout_options import line_layout_options

    lo = line_layout_options(line)
    try:
        from WEOS.factory.pipeline import generate_job

        # Catalogue/imported (stub) products now carry a synthesised renderable
        # geometry (see product_loader._ensure_renderable), so we draw their
        # elevation in the PDF too.
        job = generate_job(
            w,
            h,
            product,
            glass=glass,
            colour=str(colour) if colour else None,
            handle=handle,
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
        )
        draw_model_elevation(
            c,
            job.drawing,
            x,
            y,
            box_w,
            box_h,
            colour=str(colour),
            grid=grid,
            include_plan=True,
        )
        return True
    except Exception:
        return False
