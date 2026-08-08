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
    out.sort(key=lambda g: (-(g[4] + g[2]) / 2.0, g[1]))  # top→bottom, then left→right
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
        f'stroke="{stroke}" stroke-width="1.6" marker-end="url(#slideArrow)"/>'
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


def _hollow_plan_band(
    parts: list[str],
    *,
    tx,
    ty,
    x0: float,
    x1: float,
    y_bot: float,
    y_top: float,
    stroke: str = "#222",
    stroke_width: float = 0.9,
) -> None:
    """Outline sash section with a light inner parallel pair (aluminium plan look)."""
    w = tx(x1) - tx(x0)
    h = abs(ty(y_bot) - ty(y_top))
    if w < 2 or h < 2:
        return
    parts.append(
        f'<rect x="{tx(x0):.2f}" y="{ty(y_top):.2f}" width="{w:.2f}" height="{h:.2f}" '
        f'fill="none" stroke="{stroke}" stroke-width="{stroke_width:.2f}"/>'
    )
    # Inner parallel rails (hollow section)
    inset_y = max(h * 0.22, 1.2)
    inset_x = min(max(w * 0.012, 1.0), 4.0)
    if h > inset_y * 2.4 and w > inset_x * 2.4:
        parts.append(
            f'<rect x="{tx(x0) + inset_x:.2f}" y="{ty(y_top) + inset_y:.2f}" '
            f'width="{w - 2 * inset_x:.2f}" height="{h - 2 * inset_y:.2f}" '
            f'fill="none" stroke="{stroke}" stroke-width="{stroke_width * 0.75:.2f}"/>'
        )


def _handle_finish_colors(finish: str) -> dict[str, str]:
    """Palette for the lever handle (silver / black) resembling the reference part."""
    if str(finish).lower() in ("black", "black_texture", "matte_black", "dark"):
        return {
            "plate": "#3a3f45", "plate_stroke": "#15181c",
            "lever": "#4c525a", "lever_stroke": "#191c20", "hi": "#6b727b",
        }
    return {
        "plate": "#c9ced4", "plate_stroke": "#7f868e",
        "lever": "#e4e8ec", "lever_stroke": "#9aa1a9", "hi": "#ffffff",
    }


def _draw_lever_handle(
    parts: list[str], *, tx, ty, rect: tuple[float, float, float, float],
    side: str | None, finish: str, k: float,
) -> None:
    """Lever handle with oval escutcheon (reference-style) at the handle-section centre."""
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    pw = (x1 - x0)
    ph = (y1 - y0)
    c = _handle_finish_colors(finish)
    rx = max(pw * 0.62, 5.0 * k)
    ry = max(ph * 0.5, 10.0 * k)
    # Oval escutcheon plate
    parts.append(
        f'<ellipse cx="{tx(cx):.2f}" cy="{ty(cy):.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
        f'fill="{c["plate"]}" stroke="{c["plate_stroke"]}" stroke-width="{1.1 * k:.2f}"/>'
    )
    # Keyhole hint
    parts.append(
        f'<circle cx="{tx(cx):.2f}" cy="{ty(cy) + ry * 0.35:.2f}" r="{max(pw * 0.16, 1.6 * k):.2f}" '
        f'fill="{c["lever_stroke"]}"/>'
    )
    # Lever arm — extends into the leaf (away from the stile)
    direction = -1.0 if side == "right" else 1.0
    arm_len = max(pw * 2.6, 26.0 * k)
    bar_h = max(pw * 0.55, 5.0 * k)
    ax0 = cx if direction > 0 else cx - arm_len
    ax1 = cx + arm_len if direction > 0 else cx
    ly = cy - ry * 0.35
    parts.append(
        f'<rect x="{tx(ax0):.2f}" y="{ty(ly) - bar_h / 2:.2f}" width="{(ax1 - ax0):.2f}" height="{bar_h:.2f}" '
        f'rx="{bar_h / 2:.2f}" fill="{c["lever"]}" stroke="{c["lever_stroke"]}" stroke-width="{1.0 * k:.2f}"/>'
    )
    # Pivot knuckle at the plate
    parts.append(
        f'<circle cx="{tx(cx):.2f}" cy="{ty(ly):.2f}" r="{bar_h * 0.72:.2f}" '
        f'fill="{c["plate"]}" stroke="{c["lever_stroke"]}" stroke-width="{1.0 * k:.2f}"/>'
    )


def _draw_hardware(parts: list[str], *, tx, ty, model: DrawingModel, finish: str, k: float) -> None:
    """Draw handles (from shutter meta, oriented) and bifold hinge knuckles."""
    meta = model.metadata or {}
    c = _handle_finish_colors(finish)
    # Hinge knuckles
    for h in meta.get("hinges") or []:
        if not isinstance(h, Mapping):
            continue
        x0, y0, x1, y1 = float(h["x0"]), float(h["y0"]), float(h["x1"]), float(h["y1"])
        parts.append(
            f'<rect x="{tx(x0):.2f}" y="{ty(y1):.2f}" width="{(x1 - x0):.2f}" height="{(y1 - y0):.2f}" '
            f'rx="{(x1 - x0) * 0.35:.2f}" fill="{c["plate"]}" stroke="{c["plate_stroke"]}" stroke-width="{0.9 * k:.2f}"/>'
        )
    # Handles
    for sp in meta.get("shutters") or []:
        if not isinstance(sp, Mapping):
            continue
        hd = sp.get("handle")
        if not isinstance(hd, Mapping):
            continue
        _draw_lever_handle(
            parts, tx=tx, ty=ty,
            rect=(float(hd["x0"]), float(hd["y0"]), float(hd["x1"]), float(hd["y1"])),
            side=sp.get("handleSide"), finish=finish, k=k,
        )


def _draw_plan(
    parts: list[str],
    *,
    tx,
    ty,
    model: DrawingModel,
    plan_y0: float,
    plan_h: float,
    stroke_scale: float = 1.0,
) -> None:
    """Top-down track/sash sketch — front/back stagger from per-sash depth."""
    W = model.width
    meta = model.metadata or {}
    system = str(meta.get("system") or "sliding")
    track_count = float(meta.get("track_count") or 2)
    mesh = bool(meta.get("mesh"))
    shutters = [s for s in (meta.get("shutters") or []) if isinstance(s, Mapping)]
    y_mid = plan_y0 + plan_h / 2.0
    band = plan_h * 0.30
    sw = 0.95 * stroke_scale

    # Outer frame / track box
    parts.append(
        f'<rect x="{tx(0):.2f}" y="{ty(plan_y0 + plan_h):.2f}" width="{tx(W) - tx(0):.2f}" '
        f'height="{ty(plan_y0) - ty(plan_y0 + plan_h):.2f}" fill="none" stroke="#222" '
        f'stroke-width="{1.15 * stroke_scale:.2f}"/>'
    )
    parts.append(
        f'<text x="{tx(W / 2):.2f}" y="{ty(plan_y0 - 14 * stroke_scale):.2f}" text-anchor="middle" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{24 * stroke_scale:.0f}" fill="#666">PLAN</text>'
    )

    if not shutters:
        return

    if system == "bifold":
        _draw_plan_bifold(parts, tx=tx, ty=ty, shutters=shutters, W=W, y_mid=y_mid, plan_h=plan_h, stroke_scale=stroke_scale)
        return

    glass = [s for s in shutters if s.get("role") == "glass"]
    meshes = [s for s in shutters if s.get("role") == "mesh"]
    depths = sorted({int(s.get("depth") or 1) for s in glass}) or [1]
    dmin, dmax = min(depths), max(depths)
    spread = plan_h * 0.26

    def y_for(depth: int) -> float:
        if dmax == dmin:
            return y_mid
        t = (depth - dmin) / (dmax - dmin)  # 0 = front, 1 = back
        return y_mid - spread * (0.5 - t)   # front sits lower (toward viewer)

    # Track guide lines
    inset = float(meta.get("shutter_inset") or 0)
    n_guides = max(len(depths) + (1 if meshes else 0), 2)
    gspan = band * 1.9
    for i in range(n_guides):
        t = i / max(n_guides - 1, 1)
        dy = -gspan + 2 * gspan * t
        parts.append(
            f'<line x1="{tx(inset):.2f}" y1="{ty(y_mid + dy):.2f}" x2="{tx(W - inset):.2f}" '
            f'y2="{ty(y_mid + dy):.2f}" stroke="#bbb" stroke-width="{0.5 * stroke_scale:.2f}"/>'
        )

    # Mesh sashes — frontmost (dashed green)
    for s in meshes:
        my = y_for(dmin) - band * 0.9
        x0, x1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
        parts.append(
            f'<rect x="{tx(x0):.2f}" y="{ty(my + band * 0.5):.2f}" width="{(x1 - x0):.2f}" '
            f'height="{band * 0.5:.2f}" fill="none" stroke="#2a6a4a" '
            f'stroke-width="{0.85 * stroke_scale:.2f}" stroke-dasharray="{4 * stroke_scale:.1f},{3 * stroke_scale:.1f}"/>'
        )
    if meshes:
        parts.append(
            f'<text x="{tx(W / 2):.2f}" y="{ty(y_for(dmin) - band * 1.5):.2f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="{16 * stroke_scale:.0f}" fill="#2a6a4a">MESH</text>'
        )

    # Glass sashes — draw back (deeper) first so front laps over
    for s in sorted(glass, key=lambda p: -int(p.get("depth") or 1)):
        depth = int(s.get("depth") or 1)
        yy = y_for(depth)
        x0, x1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
        is_front = depth == dmin
        stroke = "#173a63" if is_front else "#555"
        _hollow_plan_band(
            parts, tx=tx, ty=ty, x0=x0, x1=x1,
            y_bot=yy - band * 0.5, y_top=yy + band * 0.5, stroke=stroke, stroke_width=sw,
        )
    # Front/back legend
    parts.append(
        f'<text x="{tx(inset):.2f}" y="{ty(y_for(dmin) - band * 0.85):.2f}" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{14 * stroke_scale:.0f}" fill="#173a63">front</text>'
    )
    if dmax != dmin:
        parts.append(
            f'<text x="{tx(inset):.2f}" y="{ty(y_for(dmax) + band * 0.95):.2f}" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="{14 * stroke_scale:.0f}" fill="#555">back</text>'
        )


def _draw_plan_bifold(parts: list[str], *, tx, ty, shutters, W: float, y_mid: float, plan_h: float, stroke_scale: float) -> None:
    """Accordion plan for Fold & Sliding — zigzag of folded leaves per pack."""
    glass = [s for s in shutters if s.get("role") == "glass"]
    if not glass:
        return
    amp = plan_h * 0.30
    bounds = [float(glass[0].get("nomX0") or 0)] + [float(s.get("nomX1") or 0) for s in glass]
    pts = [(bounds[j], y_mid + (amp if j % 2 == 0 else -amp)) for j in range(len(bounds))]
    d = " ".join(f"{tx(x):.2f},{ty(y):.2f}" for x, y in pts)
    parts.append(
        f'<polyline points="{d}" fill="none" stroke="#173a63" stroke-width="{1.4 * stroke_scale:.2f}" '
        f'stroke-linejoin="round"/>'
    )
    # Hinge dots at internal vertices
    for j in range(1, len(pts) - 1):
        x, y = pts[j]
        parts.append(
            f'<circle cx="{tx(x):.2f}" cy="{ty(y):.2f}" r="{2.2 * stroke_scale:.2f}" fill="#8b1e1a"/>'
        )
    # Fold-direction arrows per pack
    fl = sum(1 for s in glass if s.get("pack") == "L")
    if fl > 0:
        lx = float(glass[0].get("nomX0") or 0)
        parts.append(
            f'<line x1="{tx(lx) + 26 * stroke_scale:.2f}" y1="{ty(y_mid):.2f}" x2="{tx(lx) + 2:.2f}" '
            f'y2="{ty(y_mid):.2f}" stroke="#0b3d7a" stroke-width="{1.4 * stroke_scale:.2f}" marker-end="url(#slideArrow)"/>'
        )
    if fl < len(glass):
        rx = float(glass[-1].get("nomX1") or W)
        parts.append(
            f'<line x1="{tx(rx) - 26 * stroke_scale:.2f}" y1="{ty(y_mid):.2f}" x2="{tx(rx) - 2:.2f}" '
            f'y2="{ty(y_mid):.2f}" stroke="#0b3d7a" stroke-width="{1.4 * stroke_scale:.2f}" marker-end="url(#slideArrow)"/>'
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

    # Size-independent drafting: stroke/font scale with model so small & large
    # openings look the same when the SVG is fit into a preview/PDF box.
    ref = max(float(model.width), float(model.height), 1.0)
    k = ref / 1000.0  # 1.0 at ~1000 mm reference
    k = max(0.55, min(k, 4.0))

    plan_gap = (90.0 * k) if (annotations and include_plan) else 0.0
    plan_h = (70.0 * k) if plan_gap else 0.0
    dim_pad = (110.0 * k) if annotations else 0.0
    margin = float(margin) * k
    # Tighter margin for PDF so geometry fills the design column
    if pdf:
        margin = min(margin, 100.0 * k)

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
    max_x = max(xs) + margin + (40.0 * k if annotations else 0.0)
    min_y = min(ys) - margin - (dim_pad if annotations else 0.0) - plan_gap - plan_h
    max_y = max(ys) + margin + (dim_pad * 0.35 if annotations else 0.0)
    w = max_x - min_x
    h = max_y - min_y

    def tx(x: float) -> float:
        return x - min_x

    def ty(y: float) -> float:
        return max_y - y

    # Drafting style: profile outlines only (never solid dark fills)
    _ = colour  # kept for API / quote colour label; frames stay stroke-only
    frame_stroke = "#1a1a1a"
    # Very light glass tint — clear 2D, not solid dark
    glass_fill = "rgba(170, 205, 230, 0.22)" if pdf else "rgba(160, 200, 230, 0.18)"
    glass_stroke = "#2a6fad"
    dim_stroke = "#8b1e1a"
    sw_profile = (1.45 if pdf else 1.25) * k
    sw_seg = (1.1 if pdf else 0.95) * k
    sw_grid = (1.15 if pdf else 0.95) * k
    sw_interlock = (1.55 if pdf else 1.35) * k
    dim_font = (44.0 if pdf else 36.0) * k
    label_font = (32.0 if pdf else 26.0) * k

    bg = "#ffffff" if pdf else "#f7f6f2"
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}" height="{h:.1f}" '
        f'viewBox="0 0 {w:.1f} {h:.1f}">',
        f"<title>{escape(model.product_type)} {model.width:g}x{model.height:g}</title>",
        f'<rect width="100%" height="100%" fill="{bg}"/>',
        '<defs><marker id="slideArrow" markerWidth="10" markerHeight="10" refX="8" refY="4" orient="auto">'
        '<path d="M0,0 L8,4 L0,8 Z" fill="#0b3d7a"/></marker></defs>',
    ]

    # Glass first (filled), then profile outlines on top
    for pl in model.polylines:
        if pl.layer != "GLASS" or len(pl.points) < 2:
            continue
        pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
        parts.append(
            f'<polygon points="{pts}" fill="{glass_fill}" stroke="{glass_stroke}" '
            f'stroke-width="{sw_profile * 0.75:.2f}"/>'
        )

    for pl in model.polylines:
        if pl.layer in ("GLASS", "HARDWARE") or len(pl.points) < 2:
            continue
        pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
        if pl.closed:
            parts.append(
                f'<polygon points="{pts}" fill="none" stroke="{frame_stroke}" stroke-width="{sw_profile:.2f}"/>'
            )
        else:
            parts.append(
                f'<polyline points="{pts}" fill="none" stroke="{frame_stroke}" stroke-width="{sw_profile * 0.9:.2f}"/>'
            )

    for seg in model.segments:
        lname = (seg.name or "").lower()
        is_il = "interlock" in lname or "meeting" in lname
        stroke = "#0d3a6e" if is_il else (frame_stroke if seg.layer == "PROFILES" else "#777")
        lw = sw_interlock if is_il else sw_seg
        parts.append(
            f'<line x1="{tx(seg.start.x):.2f}" y1="{ty(seg.start.y):.2f}" '
            f'x2="{tx(seg.end.x):.2f}" y2="{ty(seg.end.y):.2f}" '
            f'stroke="{stroke}" stroke-width="{lw:.2f}"/>'
        )

    glasses = _glass_panels(model)
    meta = model.metadata or {}

    # Hardware — lever handles + bifold hinges (drawn above glass & frames)
    finish = str(meta.get("handle_finish") or "")
    if not finish:
        cl = str(colour or "").lower()
        finish = "black" if ("black" in cl or "dark" in cl) else "silver"
    _draw_hardware(parts, tx=tx, ty=ty, model=model, finish=finish, k=k)

    # Grids / muntins inside each glass lite
    if grid_div:
        cols, rows = grid_div
        for _name, x0, y0, x1, y1 in glasses:
            _draw_grid_in_rect(
                parts, tx=tx, ty=ty, x0=x0, y0=y0, x1=x1, y1=y1,
                cols=cols, rows=rows, stroke="#4a6a88", stroke_width=sw_grid,
            )

    if annotations:
        slide_idx = 0
        fix_idx = 0
        for name, x0, y0, x1, y1 in glasses:
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            lname = (name or "").lower()
            if "fix" in lname:
                fix_idx += 1
                panel_id = f"F{fix_idx}"
                role = "FIX"
                role_color = "#5a3a10"
            elif "leaf" in lname:
                slide_idx += 1
                panel_id = f"L{slide_idx}"
                role = "FOLD"
                role_color = "#0b3d7a"
            elif "door" in lname:
                panel_id = "D1"
                role = "DOOR"
                role_color = "#0b3d7a"
            else:
                slide_idx += 1
                panel_id = f"S{slide_idx}"
                role = "SLIDING"
                role_color = "#0b3d7a"

            chip_w, chip_h = 80 * k, 36 * k
            chip_y = cy + (y1 - y0) * 0.32
            parts.append(
                f'<rect x="{tx(cx) - chip_w / 2:.2f}" y="{ty(chip_y) - chip_h / 2:.2f}" '
                f'width="{chip_w:.2f}" height="{chip_h:.2f}" rx="{3 * k:.1f}" fill="#fff" fill-opacity="0.95" '
                f'stroke="#333" stroke-width="{1.15 * k:.2f}"/>'
            )
            parts.append(
                f'<text x="{tx(cx):.2f}" y="{ty(chip_y) + label_font * 0.32:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font:.0f}" font-weight="700" fill="#111">'
                f"{escape(panel_id)}</text>"
            )
            parts.append(
                f'<text x="{tx(cx):.2f}" y="{ty(cy - (y1 - y0) * 0.28) + label_font * 0.35:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font * 0.85:.0f}" font-weight="600" fill="{role_color}">'
                f"{escape(role)}</text>"
            )

            if role == "SLIDING" and (x1 - x0) > 40:
                ay = cy + (y1 - y0) * 0.05
                if slide_idx == 1:
                    _arrow(parts, tx=tx, ty=ty, x0=cx - (x1 - x0) * 0.28, y0=ay, x1=cx + (x1 - x0) * 0.22, y1=ay)
                else:
                    _arrow(parts, tx=tx, ty=ty, x0=cx + (x1 - x0) * 0.28, y0=ay, x1=cx - (x1 - x0) * 0.22, y1=ay)

        W = float(model.width)
        H = float(model.height)
        _dim_line_v(
            parts, tx=tx, ty=ty, y0=0.0, y1=H, x=-55.0 * k, text=f"{H:g}",
            text_x=-82.0 * k, stroke=dim_stroke, font=dim_font,
        )
        _dim_line_h(
            parts, tx=tx, ty=ty, x0=0.0, x1=W, y=-95.0 * k, text=f"{W:g}",
            text_y=-122.0 * k, stroke=dim_stroke, font=dim_font,
        )
        # Per-shutter equal-division widths (nominal shares) along the top
        glass_meta = [s for s in (meta.get("shutters") or []) if isinstance(s, Mapping) and s.get("role") == "glass"]
        if glass_meta:
            for s in glass_meta:
                nx0 = float(s.get("nomX0") or s.get("x0") or 0.0)
                nx1 = float(s.get("nomX1") or s.get("x1") or 0.0)
                _dim_line_h(
                    parts, tx=tx, ty=ty, x0=nx0, x1=nx1, y=-42.0 * k,
                    text=f"{(nx1 - nx0):g}", text_y=-64.0 * k, stroke=dim_stroke, font=dim_font * 0.82,
                )
        else:
            slide_x0 = float(meta.get("sliding_x0") or meta.get("shutter_inset") or 0.0)
            slide_x1 = float(meta.get("sliding_x1") or (W - float(meta.get("shutter_inset") or 0.0)))
            il = float(meta.get("interlock_left") or ((slide_x0 + slide_x1) / 2.0))
            _dim_line_h(
                parts, tx=tx, ty=ty, x0=slide_x0, x1=il, y=-42.0 * k,
                text=f"{(il - slide_x0):g}", text_y=-64.0 * k, stroke=dim_stroke, font=dim_font * 0.9,
            )
            _dim_line_h(
                parts, tx=tx, ty=ty, x0=il, x1=slide_x1, y=-42.0 * k,
                text=f"{(slide_x1 - il):g}", text_y=-64.0 * k, stroke=dim_stroke, font=dim_font * 0.9,
            )
        # Fix partition dims
        for part in (meta.get("partitions") or []) if isinstance(meta.get("partitions"), list) else []:
            side = str(part.get("side") or "")
            if side == "top":
                ph = float(part.get("heightMm") or part.get("sizeMm") or 0)
                if ph > 0:
                    _dim_line_v(
                        parts, tx=tx, ty=ty, y0=H - float(meta.get("shutter_inset") or 0) - ph,
                        y1=H - float(meta.get("shutter_inset") or 0),
                        x=W + 48.0 * k, text=f"FIX {ph:g}", text_x=W + 90.0 * k,
                        stroke=dim_stroke, font=dim_font * 0.75,
                    )
            elif side == "bottom":
                ph = float(part.get("heightMm") or part.get("sizeMm") or 0)
                if ph > 0:
                    _dim_line_v(
                        parts, tx=tx, ty=ty, y0=float(meta.get("shutter_inset") or 0),
                        y1=float(meta.get("shutter_inset") or 0) + ph,
                        x=W + 48.0 * k, text=f"FIX {ph:g}", text_x=W + 90.0 * k,
                        stroke=dim_stroke, font=dim_font * 0.75,
                    )
        sliding_glasses = [g for g in glasses if "fix" not in (g[0] or "").lower()]
        if sliding_glasses:
            _n, _a, gy0, _b, gy1 = sliding_glasses[0]
            _dim_line_v(
                parts, tx=tx, ty=ty, y0=gy0, y1=gy1, x=W + 48.0 * k,
                text=f"{(gy1 - gy0):g}", text_x=W + 78.0 * k, stroke=dim_stroke, font=dim_font * 0.85,
            )

        if include_plan and plan_h > 0:
            _draw_plan(
                parts,
                tx=tx,
                ty=ty,
                model=model,
                plan_y0=min_y + margin * 0.25,
                plan_h=plan_h,
                stroke_scale=k,
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
    from WEOS.factory.layout_options import line_layout_options

    lo = line_layout_options(line)
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
            partitions=lo.get("partitions"),
            mesh=bool(lo.get("mesh")),
            track_count=lo.get("trackCount"),
            section_series=lo.get("sectionSeries") or line.get("sectionSeries"),
            glass_count=lo.get("glassCount"),
            mesh_count=lo.get("meshCount"),
            opening=lo.get("opening"),
            fixed_shutters=lo.get("fixedShutters"),
            system=lo.get("system"),
            fold_left=lo.get("foldLeft"),
            fold_right=lo.get("foldRight"),
            section_sizes=lo.get("sectionSizes"),
            handle_finish=lo.get("handleFinish"),
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
    shutter_h = float(meta.get("sliding_height") or 0)
    if shutter_h <= 0:
        inset = float(meta.get("shutter_inset") or 0)
        shutter_h = max(float(height) - 2.0 * inset, 0.0)
    panels: list[dict[str, Any]] = []
    system = str(meta.get("system") or "sliding")
    is_bifold = system == "bifold"
    # Fix panels first (top→bottom, left→right)
    for i, part in enumerate(meta.get("partitions") or [] if isinstance(meta.get("partitions"), list) else []):
        side = str(part.get("side") or "")
        panels.append(
            {
                "id": f"F{i + 1}",
                "role": "fix",
                "side": side,
                "label": "Fix",
                "widthMm": round(float(part.get("widthMm") or 0), 1),
                "heightMm": round(float(part.get("heightMm") or part.get("sizeMm") or 0), 1),
                "glassWidthMm": round(float(part.get("glassWidthMm") or 0), 1),
                "glassHeightMm": round(float(part.get("glassHeightMm") or 0), 1),
            }
        )
    shutters = [s for s in (meta.get("shutters") or []) if isinstance(s, dict)]
    if shutters:
        s_idx = 0
        m_idx = 0
        for s in shutters:
            if s.get("role") == "mesh":
                m_idx += 1
                panels.append(
                    {
                        "id": f"M{m_idx}", "role": "mesh", "side": "mesh", "label": "Mesh",
                        "widthMm": round(float(s.get("widthMm") or 0), 1), "heightMm": round(shutter_h, 1),
                    }
                )
                continue
            s_idx += 1
            fixed = not bool(s.get("operable", True))
            if is_bifold:
                role, label, pid = "leaf", f"Fold ({s.get('pack','')})", f"L{s_idx}"
            elif fixed:
                role, label, pid = "fix", "Fix (locked sash)", f"S{s_idx}"
            else:
                role, label, pid = "sliding", "Sliding", f"S{s_idx}"
            panels.append(
                {
                    "id": pid, "role": role, "side": s.get("track"), "label": label,
                    "track": s.get("track"), "depth": s.get("depth"),
                    "widthMm": round(float(s.get("widthMm") or 0), 1), "heightMm": round(shutter_h, 1),
                    "glassWidthMm": round(float(s.get("glassWidthMm") or 0), 1),
                    "glassHeightMm": round(float(s.get("glassHeightMm") or 0), 1),
                    "handle": bool(s.get("handle")),
                }
            )
    else:
        panels.extend(
            [
                {"id": "S1", "role": "sliding", "side": "left", "label": "Sliding",
                 "widthMm": round(float(meta.get("left_shutter_width") or 0), 1), "heightMm": round(shutter_h, 1),
                 "glassWidthMm": round(float(meta.get("left_glass_width") or 0), 1),
                 "glassHeightMm": round(float(meta.get("glass_height") or 0), 1)},
                {"id": "S2", "role": "sliding", "side": "right", "label": "Sliding",
                 "widthMm": round(float(meta.get("right_shutter_width") or 0), 1), "heightMm": round(shutter_h, 1),
                 "glassWidthMm": round(float(meta.get("right_glass_width") or 0), 1),
                 "glassHeightMm": round(float(meta.get("glass_height") or 0), 1)},
            ]
        )
    clean_meta: dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            clean_meta[k] = round(float(v), 3)
        elif isinstance(v, (str, bool, list, dict)) or v is None:
            clean_meta[k] = v
    if is_bifold:
        kind = "fold_and_sliding"
    elif meta.get("partitions"):
        kind = "sliding_with_partitions"
    else:
        kind = "two_track_sliding"
    return {
        "kind": kind,
        "system": system,
        "widthMm": float(width),
        "heightMm": float(height),
        "trackCount": float(meta.get("track_count") or 2),
        "mesh": bool(meta.get("mesh")),
        "glassCount": int(meta.get("glass_count") or 0),
        "meshCount": int(meta.get("mesh_count") or 0),
        "foldLeft": int(meta.get("fold_left") or 0),
        "foldRight": int(meta.get("fold_right") or 0),
        "sectionSizes": meta.get("sectionSizes"),
        "notes": meta.get("notes") or [],
        "panels": panels,
        "meta": clean_meta,
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
