"""ReportLab elevation drawer — same geometry engine as live canvas, sized for PDF columns."""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory.svg_export import _parse_grid
from WEOS.factory.types import DrawingModel, Polyline


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
    del colour  # outline drafting — colour stays in the text specs, not as solid fills
    meta = model.metadata or {}
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

    stroke = (0.08, 0.08, 0.10)
    dim = (0.55, 0.12, 0.10)
    glass_stroke = (0.18, 0.42, 0.68)

    # White plate behind drawing
    c.setFillColorRGB(1, 1, 1)
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.35)
    c.rect(x, y, box_w, box_h, fill=1, stroke=1)

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
        if len(pl.points) < 2 or pl.layer == "GLASS" or not pl.closed:
            continue
        path = c.beginPath()
        path.moveTo(px(pl.points[0].x), py(pl.points[0].y))
        for p in pl.points[1:]:
            path.lineTo(px(p.x), py(p.y))
        path.close()
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.85)
        c.drawPath(path, fill=0, stroke=1)

    for pl in model.polylines:
        if pl.closed or pl.layer == "GLASS" or len(pl.points) < 2:
            continue
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.7)
        for a, b in zip(pl.points, pl.points[1:]):
            c.line(px(a.x), py(a.y), px(b.x), py(b.y))

    for seg in model.segments:
        lname = (seg.name or "").lower()
        is_il = "interlock" in lname or "meeting" in lname
        if is_il:
            c.setStrokeColorRGB(0.05, 0.28, 0.55)
            c.setLineWidth(1.05)
        else:
            c.setStrokeColorRGB(*stroke if seg.layer == "PROFILES" else (0.45, 0.45, 0.45))
            c.setLineWidth(0.6)
        c.line(px(seg.start.x), py(seg.start.y), px(seg.end.x), py(seg.end.y))

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
    c.setFont("Helvetica-Bold", 7)
    slide_idx = 0
    fix_idx = 0
    for name, x0, y0, x1, y1 in glasses:
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        lname = (name or "").lower()
        if "fix" in lname:
            fix_idx += 1
            panel_id, role = f"F{fix_idx}", "FIX"
            role_rgb = (0.35, 0.22, 0.05)
        elif "door" in lname:
            panel_id, role = "D1", "DOOR"
            role_rgb = (0.05, 0.30, 0.55)
        else:
            slide_idx += 1
            panel_id, role = f"S{slide_idx}", "SLIDING"
            role_rgb = (0.05, 0.30, 0.55)

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

        if role == "SLIDING":
            c.setStrokeColorRGB(0.05, 0.30, 0.55)
            c.setFillColorRGB(0.05, 0.30, 0.55)
            c.setLineWidth(0.75)
            ay = cy
            if slide_idx == 1:
                ax0, ax1 = cx - (x1 - x0) * 0.28, cx + (x1 - x0) * 0.20
            else:
                ax0, ax1 = cx + (x1 - x0) * 0.28, cx - (x1 - x0) * 0.20
            c.line(px(ax0), py(ay), px(ax1), py(ay))
            ah = 2.8
            direction = 1 if ax1 > ax0 else -1
            c.line(px(ax1), py(ay), px(ax1) - direction * ah, py(ay) + ah * 0.7)
            c.line(px(ax1), py(ay), px(ax1) - direction * ah, py(ay) - ah * 0.7)

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

    left_w = float(meta.get("left_shutter_width") or W / 2)
    right_w = float(meta.get("right_shutter_width") or W / 2)
    slide_x0 = float(meta.get("sliding_x0") or meta.get("shutter_inset") or 0)
    slide_x1 = float(meta.get("sliding_x1") or (W - float(meta.get("shutter_inset") or 0)))
    il = float(meta.get("interlock_left") or (slide_x0 + left_w))
    mesh = bool(meta.get("mesh"))
    track_count = float(meta.get("track_count") or 2)

    # Overall H left, overall W bottom, panel widths, glass H
    dim_v(0.0, H, -18.0 / max(scale, 1e-6), f"{H:g}", text_dx=-9)
    dim_h(0.0, W, -28.0 / max(scale, 1e-6), f"{W:g}", text_dy=-9)
    dim_h(slide_x0, il, -12.0 / max(scale, 1e-6), f"{left_w:g}", text_dy=-8)
    dim_h(il, slide_x1, -12.0 / max(scale, 1e-6), f"{right_w:g}", text_dy=-8)
    sliding_glasses = [g for g in glasses if "fix" not in (g[0] or "").lower()]
    if sliding_glasses:
        _n, _a, gy0, _b, gy1 = sliding_glasses[0]
        dim_v(gy0, gy1, W + 14.0 / max(scale, 1e-6), f"{(gy1 - gy0):g}", text_dx=8)

    if include_plan and plan_h > 0:
        py0 = y + 4
        box_ph = plan_h - 4
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(0.7)
        c.rect(px(0), py0, W * scale, box_ph, fill=0, stroke=1)
        # Track guides (2 / 3 for mesh)
        c.setStrokeColorRGB(0.55, 0.55, 0.55)
        c.setLineWidth(0.35)
        n_guides = 3 if (mesh or track_count >= 2.5) else 2
        for i in range(n_guides):
            t = i / max(n_guides - 1, 1)
            gy = py0 + box_ph * (0.22 + 0.56 * t)
            c.line(px(slide_x0), gy, px(slide_x1), gy)
        # Hollow sash bands
        c.setStrokeColorRGB(*stroke)
        band = box_ph * 0.20
        _hollow_plan_band(
            c, px(slide_x0), py0 + box_ph / 2 - band / 2,
            (il - slide_x0) * scale, band, lw=0.55,
        )
        _hollow_plan_band(
            c, px(il), py0 + box_ph / 2 - band * 0.85,
            (slide_x1 - il) * scale, band, lw=0.55,
        )
        if mesh or track_count >= 2.5:
            c.setStrokeColorRGB(0.15, 0.45, 0.30)
            c.setDash(2, 1.5)
            c.setLineWidth(0.55)
            my = py0 + box_ph * 0.12
            c.rect(px(slide_x0), my, (slide_x1 - slide_x0) * scale, band * 0.7, fill=0, stroke=1)
            c.setDash()
            c.setFont("Helvetica", 4.5)
            c.setFillColorRGB(0.15, 0.45, 0.30)
            c.drawCentredString(px(W / 2), my + band * 0.85, "MESH")
        c.setFont("Helvetica", 5)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawCentredString(px(W / 2), py0 + box_ph + 1.5, "PLAN")


def draw_line_model_elevation(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    """Regenerate geometry for a cart line and draw it. Returns False if unavailable."""
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
        from WEOS.factory.product_loader import load_product

        meta = load_product(product, strict=False)
        if meta.get("_stub") or meta.get("status") == "stub":
            return False
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
