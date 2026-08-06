"""SVG preview export — 2D elevation from DrawingModel (same geometry as live canvas / PDF)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from xml.sax.saxutils import escape

from WEOS.factory.types import DrawingModel, Polyline


def _parse_grid(grid: Any) -> tuple[int, int] | None:
    """Return (cols, rows) muntin divisions, or None."""
    if not grid:
        return None
    if isinstance(grid, Mapping):
        cols = int(grid.get("cols") or grid.get("v") or grid.get("columns") or grid.get("vertical") or 0)
        rows = int(grid.get("rows") or grid.get("h") or grid.get("horizontal") or 0)
        if cols <= 0 and rows <= 0:
            return None
        return (max(cols, 1), max(rows, 1))
    if isinstance(grid, (list, tuple)) and len(grid) >= 2:
        cols, rows = int(grid[0] or 0), int(grid[1] or 0)
        if cols <= 0 and rows <= 0:
            return None
        return (max(cols, 1), max(rows, 1))
    text = str(grid).strip().lower().replace("×", "x").replace("*", "x")
    if "x" in text:
        a, _, b = text.partition("x")
        try:
            cols, rows = int(a.strip() or 0), int(b.strip() or 0)
        except ValueError:
            return None
        if cols <= 0 and rows <= 0:
            return None
        return (max(cols, 1), max(rows, 1))
    return None


def _polyline_bbox(pl: Polyline) -> tuple[float, float, float, float] | None:
    if len(pl.points) < 2:
        return None
    xs = [p.x for p in pl.points]
    ys = [p.y for p in pl.points]
    return min(xs), min(ys), max(xs), max(ys)


def _glass_panels(model: DrawingModel) -> list[tuple[str, float, float, float, float]]:
    """Named glass rectangles (minx, miny, maxx, maxy) in model mm."""
    out: list[tuple[str, float, float, float, float]] = []
    for pl in model.polylines:
        if pl.layer != "GLASS":
            continue
        bb = _polyline_bbox(pl)
        if not bb:
            continue
        out.append((pl.name or f"glass_{len(out)+1}", *bb))
    out.sort(key=lambda g: g[1])  # left → right
    return out


def _dim_line_h(
    parts: list[str],
    *,
    tx,
    ty,
    x0: float,
    x1: float,
    y: float,
    text: str,
    text_y: float | None = None,
    stroke: str = "#8b1e1a",
    font: float = 36.0,
) -> None:
    ty_line = text_y if text_y is not None else y
    parts.append(
        f'<line x1="{tx(x0):.2f}" y1="{ty(y):.2f}" x2="{tx(x1):.2f}" y2="{ty(y):.2f}" '
        f'stroke="{stroke}" stroke-width="1.4"/>'
    )
    parts.append(
        f'<line x1="{tx(x0):.2f}" y1="{ty(y) - 8:.2f}" x2="{tx(x0):.2f}" y2="{ty(y) + 8:.2f}" '
        f'stroke="{stroke}" stroke-width="1.4"/>'
    )
    parts.append(
        f'<line x1="{tx(x1):.2f}" y1="{ty(y) - 8:.2f}" x2="{tx(x1):.2f}" y2="{ty(y) + 8:.2f}" '
        f'stroke="{stroke}" stroke-width="1.4"/>'
    )
    mid = (x0 + x1) / 2.0
    parts.append(
        f'<text x="{tx(mid):.2f}" y="{ty(ty_line) + font * 0.35:.2f}" text-anchor="middle" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{font:.0f}" fill="{stroke}">'
        f"{escape(text)}</text>"
    )


def _dim_line_v(
    parts: list[str],
    *,
    tx,
    ty,
    y0: float,
    y1: float,
    x: float,
    text: str,
    text_x: float | None = None,
    stroke: str = "#8b1e1a",
    font: float = 36.0,
) -> None:
    parts.append(
        f'<line x1="{tx(x):.2f}" y1="{ty(y0):.2f}" x2="{tx(x):.2f}" y2="{ty(y1):.2f}" '
        f'stroke="{stroke}" stroke-width="1.4"/>'
    )
    parts.append(
        f'<line x1="{tx(x) - 8:.2f}" y1="{ty(y0):.2f}" x2="{tx(x) + 8:.2f}" y2="{ty(y0):.2f}" '
        f'stroke="{stroke}" stroke-width="1.4"/>'
    )
    parts.append(
        f'<line x1="{tx(x) - 8:.2f}" y1="{ty(y1):.2f}" x2="{tx(x) + 8:.2f}" y2="{ty(y1):.2f}" '
        f'stroke="{stroke}" stroke-width="1.4"/>'
    )
    mid = (y0 + y1) / 2.0
    tx_text = text_x if text_x is not None else x
    parts.append(
        f'<text x="{tx(tx_text) - font * 0.15:.2f}" y="{ty(mid) + font * 0.35:.2f}" text-anchor="middle" '
        f'transform="rotate(-90 {tx(tx_text):.2f} {ty(mid):.2f})" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{font:.0f}" fill="{stroke}">'
        f"{escape(text)}</text>"
    )


def _arrow(
    parts: list[str],
    *,
    tx,
    ty,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    stroke: str = "#1a4a8a",
) -> None:
    parts.append(
        f'<line x1="{tx(x0):.2f}" y1="{ty(y0):.2f}" x2="{tx(x1):.2f}" y2="{ty(y1):.2f}" '
        f'stroke="{stroke}" stroke-width="2.2" marker-end="url(#slideArrow)"/>'
    )


def _draw_grid_in_rect(
    parts: list[str],
    *,
    tx,
    ty,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    cols: int,
    rows: int,
    stroke: str = "#4a6a88",
    stroke_width: float = 1.1,
) -> None:
    w = x1 - x0
    h = y1 - y0
    if w <= 1 or h <= 1:
        return
    for i in range(1, max(cols, 1)):
        x = x0 + w * i / cols
        parts.append(
            f'<line x1="{tx(x):.2f}" y1="{ty(y0):.2f}" x2="{tx(x):.2f}" y2="{ty(y1):.2f}" '
            f'stroke="{stroke}" stroke-width="{stroke_width:.2f}"/>'
        )
    for j in range(1, max(rows, 1)):
        y = y0 + h * j / rows
        parts.append(
            f'<line x1="{tx(x0):.2f}" y1="{ty(y):.2f}" x2="{tx(x1):.2f}" y2="{ty(y):.2f}" '
            f'stroke="{stroke}" stroke-width="{stroke_width:.2f}"/>'
        )


def _draw_plan(
    parts: list[str],
    *,
    tx,
    ty,
    model: DrawingModel,
    plan_y0: float,
    plan_h: float,
    frame_fill: str,
) -> None:
    """Simple top-down track/sash overlap sketch under the elevation."""
    W = model.width
    meta = model.metadata or {}
    inset = float(meta.get("shutter_inset") or 0)
    il = float(meta.get("interlock_left") or W / 2)
    ir = float(meta.get("interlock_right") or W / 2)
    y_mid = plan_y0 + plan_h / 2.0
    band = plan_h * 0.28
    # Outer frame
    parts.append(
        f'<rect x="{tx(0):.2f}" y="{ty(plan_y0 + plan_h):.2f}" width="{tx(W) - tx(0):.2f}" '
        f'height="{ty(plan_y0) - ty(plan_y0 + plan_h):.2f}" fill="none" stroke="#222" stroke-width="1.6"/>'
    )
    # Left sash band
    parts.append(
        f'<rect x="{tx(inset):.2f}" y="{ty(y_mid + band):.2f}" width="{tx(il) - tx(inset):.2f}" '
        f'height="{abs(ty(y_mid - band) - ty(y_mid + band)):.2f}" fill="{frame_fill}" stroke="#222" stroke-width="1.2"/>'
    )
    # Right sash band (slightly lower to show overlap)
    parts.append(
        f'<rect x="{tx(il):.2f}" y="{ty(y_mid + band * 0.55):.2f}" width="{tx(W - inset) - tx(il):.2f}" '
        f'height="{abs(ty(y_mid - band * 1.15) - ty(y_mid + band * 0.55)):.2f}" fill="{frame_fill}" '
        f'stroke="#222" stroke-width="1.2" fill-opacity="0.85"/>'
    )
    # Interlock mark
    parts.append(
        f'<line x1="{tx(il):.2f}" y1="{ty(plan_y0 + 4):.2f}" x2="{tx(ir):.2f}" y2="{ty(plan_y0 + plan_h - 4):.2f}" '
        f'stroke="#444" stroke-width="1.2"/>'
    )
    parts.append(
        f'<text x="{tx(W / 2):.2f}" y="{ty(plan_y0 - 18):.2f}" text-anchor="middle" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="28" fill="#555">PLAN</text>'
    )


def render_svg_string(
    model: DrawingModel,
    *,
    margin: float = 160.0,
    colour: str | None = None,
    annotations: bool = True,
    grid: Any = None,
    include_plan: bool = True,
    style: str = "preview",
) -> str:
    """Return SVG markup string for API preview / quote PDF (same geometry engine).

    style:
      - preview: live cart look
      - pdf: higher-contrast strokes/labels for ReportLab embedding
    """
    pdf = str(style or "preview").lower() == "pdf"
    grid_div = _parse_grid(grid)
    plan_gap = 90.0 if (annotations and include_plan) else 0.0
    plan_h = 70.0 if plan_gap else 0.0
    dim_pad = 110.0 if annotations else 0.0
    # Tighter margin for PDF so geometry fills the design column
    if pdf:
        margin = min(float(margin), 100.0)

    xs: list[float] = [0.0, model.width]
    ys: list[float] = [0.0, model.height]
    for pl in model.polylines:
        for p in pl.points:
            xs.append(p.x)
            ys.append(p.y)
    for seg in model.segments:
        xs.extend([seg.start.x, seg.end.x])
        ys.extend([seg.start.y, seg.end.y])

    min_x = min(xs) - margin - (dim_pad if annotations else 0.0)
    max_x = max(xs) + margin + (40.0 if annotations else 0.0)
    min_y = min(ys) - margin - (dim_pad if annotations else 0.0) - plan_gap - plan_h
    max_y = max(ys) + margin + (dim_pad * 0.35 if annotations else 0.0)
    w = max_x - min_x
    h = max_y - min_y

    def tx(x: float) -> float:
        return x - min_x

    def ty(y: float) -> float:
        return max_y - y

    colour_key = (colour or "white").lower().replace(" ", "_")
    colour_map = {
        "white": "#e8e8e6",
        "black": "#2a2a2a",
        "black_texture": "#2a2a2a",
        "wood_oak": "#8b5a2b",
    }
    frame_fill = colour_map.get(colour_key, "#d0d0ce")
    frame_stroke = "#111" if colour_key.startswith("black") else "#222"
    glass_fill = "rgba(150, 195, 230, 0.45)" if pdf else "rgba(120, 180, 230, 0.38)"
    dim_stroke = "#8b1e1a"
    sw_profile = 2.2 if pdf else 1.6
    sw_seg = 1.6 if pdf else 1.1
    sw_grid = 1.8 if pdf else 1.1
    dim_font = 44.0 if pdf else 36.0
    label_font = 32.0 if pdf else 26.0

    bg = "#ffffff" if pdf else "#f7f6f2"
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}" height="{h:.1f}" '
        f'viewBox="0 0 {w:.1f} {h:.1f}">',
        f"<title>{escape(model.product_type)} {model.width:g}x{model.height:g}</title>",
        f'<rect width="100%" height="100%" fill="{bg}"/>',
        '<defs><marker id="slideArrow" markerWidth="10" markerHeight="10" refX="8" refY="4" orient="auto">'
        '<path d="M0,0 L8,4 L0,8 Z" fill="#0b3d7a"/></marker></defs>',
    ]

    # Profiles + glass
    for pl in model.polylines:
        if len(pl.points) < 2:
            continue
        pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
        if pl.layer == "GLASS":
            parts.append(
                f'<polygon points="{pts}" fill="{glass_fill}" stroke="#1f5fad" stroke-width="{sw_profile * 0.85:.2f}"/>'
            )
        elif pl.closed:
            parts.append(
                f'<polygon points="{pts}" fill="{frame_fill}" stroke="{frame_stroke}" stroke-width="{sw_profile:.2f}"/>'
            )
        else:
            parts.append(
                f'<polyline points="{pts}" fill="none" stroke="{frame_stroke}" stroke-width="{sw_profile * 0.9:.2f}"/>'
            )

    for seg in model.segments:
        stroke = frame_stroke if seg.layer == "PROFILES" else "#666"
        parts.append(
            f'<line x1="{tx(seg.start.x):.2f}" y1="{ty(seg.start.y):.2f}" '
            f'x2="{tx(seg.end.x):.2f}" y2="{ty(seg.end.y):.2f}" '
            f'stroke="{stroke}" stroke-width="{sw_seg:.2f}"/>'
        )

    glasses = _glass_panels(model)
    meta = model.metadata or {}

    # Grids / muntins inside each glass lite
    if grid_div:
        cols, rows = grid_div
        for _name, x0, y0, x1, y1 in glasses:
            _draw_grid_in_rect(
                parts, tx=tx, ty=ty, x0=x0, y0=y0, x1=x1, y1=y1,
                cols=cols, rows=rows, stroke="#2f4f6f", stroke_width=sw_grid,
            )

    if annotations:
        for idx, (name, x0, y0, x1, y1) in enumerate(glasses):
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            panel_id = "S1" if idx == 0 else ("S2" if idx == 1 else f"S{idx + 1}")
            role = "SLIDING"
            lname = (name or "").lower()
            if "fix" in lname:
                panel_id = f"F{idx + 1}"
                role = "FIX"
            elif "door" in lname:
                panel_id = f"D{idx + 1}"
                role = "DOOR"

            chip_y = cy + (y1 - y0) * 0.32
            parts.append(
                f'<rect x="{tx(cx) - 40:.2f}" y="{ty(chip_y) - 18:.2f}" '
                f'width="80" height="36" rx="3" fill="#fff" fill-opacity="0.95" stroke="#222" stroke-width="1.6"/>'
            )
            parts.append(
                f'<text x="{tx(cx):.2f}" y="{ty(chip_y) + 8:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font:.0f}" font-weight="700" fill="#111">'
                f"{escape(panel_id)}</text>"
            )
            parts.append(
                f'<text x="{tx(cx):.2f}" y="{ty(cy - (y1 - y0) * 0.28) + 10:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font * 0.85:.0f}" font-weight="600" fill="#0b3d7a">'
                f"{escape(role)}</text>"
            )

            if role == "SLIDING" and (x1 - x0) > 40:
                ay = cy + (y1 - y0) * 0.05
                if idx == 0:
                    _arrow(parts, tx=tx, ty=ty, x0=cx - (x1 - x0) * 0.28, y0=ay, x1=cx + (x1 - x0) * 0.22, y1=ay)
                else:
                    _arrow(parts, tx=tx, ty=ty, x0=cx + (x1 - x0) * 0.28, y0=ay, x1=cx - (x1 - x0) * 0.22, y1=ay)

        W = float(model.width)
        H = float(model.height)
        left_w = float(meta.get("left_shutter_width") or (W / 2.0))
        right_w = float(meta.get("right_shutter_width") or (W / 2.0))
        inset = float(meta.get("shutter_inset") or 0.0)
        il = float(meta.get("interlock_left") or left_w)
        _dim_line_v(
            parts, tx=tx, ty=ty, y0=0.0, y1=H, x=-55.0, text=f"{H:g}",
            text_x=-82.0, stroke=dim_stroke, font=dim_font,
        )
        _dim_line_h(
            parts, tx=tx, ty=ty, x0=0.0, x1=W, y=-95.0, text=f"{W:g}",
            text_y=-122.0, stroke=dim_stroke, font=dim_font,
        )
        left_x0, left_x1 = inset, il
        right_x0, right_x1 = il, W - inset
        _dim_line_h(
            parts, tx=tx, ty=ty, x0=left_x0, x1=left_x1, y=-42.0,
            text=f"{left_w:g}", text_y=-64.0, stroke=dim_stroke, font=dim_font * 0.9,
        )
        _dim_line_h(
            parts, tx=tx, ty=ty, x0=right_x0, x1=right_x1, y=-42.0,
            text=f"{right_w:g}", text_y=-64.0, stroke=dim_stroke, font=dim_font * 0.9,
        )
        if glasses:
            _n, _a, gy0, _b, gy1 = glasses[0]
            _dim_line_v(
                parts, tx=tx, ty=ty, y0=gy0, y1=gy1, x=W + 48.0,
                text=f"{(gy1 - gy0):g}", text_x=W + 78.0, stroke=dim_stroke, font=dim_font * 0.85,
            )

        if include_plan and plan_h > 0:
            _draw_plan(
                parts,
                tx=tx,
                ty=ty,
                model=model,
                plan_y0=min_y + margin * 0.25,
                plan_h=plan_h,
                frame_fill=frame_fill,
            )

    parts.append("</svg>")
    return "\n".join(parts)


def elevation_svg_for_line(line: Mapping[str, Any], *, style: str = "pdf") -> str | None:
    """Build quote/canvas SVG for a cart line from the same geometry engine as live preview."""
    w = float(line.get("width") or 0)
    h = float(line.get("height") or 0)
    if w <= 0 or h <= 0:
        return None
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    colour = (
        (opts or {}).get("colour")
        or line.get("colour")
        or "white"
    )
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
    try:
        from WEOS.factory.pipeline import generate_job
        from WEOS.factory.product_loader import load_product

        product_meta = load_product(product, strict=False)
        if product_meta.get("_stub") or product_meta.get("status") == "stub":
            return None
        job = generate_job(
            w,
            h,
            product,
            glass=glass,
            colour=str(colour) if colour else None,
            handle=handle,
        )
        return render_svg_string(
            job.drawing,
            colour=str(colour).lower().replace(" ", "_"),
            annotations=True,
            grid=grid,
            include_plan=True,
            style=style,
        )
    except Exception:
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")
        return str(svg) if svg else None


def layout_summary_for_job(*, width: float, height: float, layout_meta: Mapping[str, Any]) -> dict[str, Any]:
    """Serializable panel layout so PDF/quote can reproduce elevation without re-deriving."""
    meta = dict(layout_meta or {})
    inset = float(meta.get("shutter_inset") or 0)
    shutter_h = max(float(height) - 2.0 * inset, 0.0)
    panels = [
        {
            "id": "S1",
            "role": "sliding",
            "side": "left",
            "label": "Sliding",
            "widthMm": round(float(meta.get("left_shutter_width") or 0), 1),
            "heightMm": round(shutter_h, 1),
            "glassWidthMm": round(float(meta.get("left_glass_width") or 0), 1),
            "glassHeightMm": round(float(meta.get("glass_height") or 0), 1),
        },
        {
            "id": "S2",
            "role": "sliding",
            "side": "right",
            "label": "Sliding",
            "widthMm": round(float(meta.get("right_shutter_width") or 0), 1),
            "heightMm": round(shutter_h, 1),
            "glassWidthMm": round(float(meta.get("right_glass_width") or 0), 1),
            "glassHeightMm": round(float(meta.get("glass_height") or 0), 1),
        },
    ]
    return {
        "kind": "two_track_sliding",
        "widthMm": float(width),
        "heightMm": float(height),
        "panels": panels,
        "meta": {k: (round(float(v), 3) if isinstance(v, (int, float)) else v) for k, v in meta.items()},
    }


def export_svg(
    model: DrawingModel,
    path: str | Path,
    *,
    margin: float = 160.0,
    colour: str | None = None,
    annotations: bool = True,
    grid: Any = None,
    include_plan: bool = True,
    style: str = "preview",
) -> Path:
    path = Path(path)
    path.write_text(
        render_svg_string(
            model,
            margin=margin,
            colour=colour,
            annotations=annotations,
            grid=grid,
            include_plan=include_plan,
            style=style,
        ),
        encoding="utf-8",
    )
    return path
