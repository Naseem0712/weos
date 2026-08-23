"""SVG preview export — 2D elevation from DrawingModel (same geometry as live canvas / PDF)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from xml.sax.saxutils import escape

from WEOS.factory.fmt import mm_n
from WEOS.factory.geometry import casement_hinge_svg
from WEOS.factory.types import DrawingModel, Polyline


def _solid_sw(sw: float) -> str:
    """Print-safe solid stroke — no dasharray (RIP/svglib hairlines look dotted)."""
    return (
        f'stroke-width="{float(sw):.2f}" stroke-dasharray="none" '
        f'stroke-linecap="square" stroke-linejoin="miter"'
    )


def _parse_grid(grid: Any) -> tuple[int, int] | None:
    """Return (cols, rows) muntin divisions, or None.

    IMPORTANT: this parses a *muntin* grid (small internal glazing bars), e.g.
    ``{"cols": 3, "rows": 2}`` or ``"3x2"``. It is NOT the partition/grid-designer
    spec (``{"cols": [..], "rows": [..], "cells": [..]}``) — that one has LIST
    cols/rows and a ``cells`` array and is rendered separately by
    ``_draw_grid_svg``. Passing that spec here previously raised ``TypeError`` via
    ``int([...])`` and blanked the whole export, so we defensively ignore it.
    """
    if not grid:
        return None
    if isinstance(grid, Mapping):
        # Partition/grid-designer spec → not a muntin grid; ignore here.
        if grid.get("cells") is not None:
            return None
        raw_cols = grid.get("cols") or grid.get("v") or grid.get("columns") or grid.get("vertical") or 0
        raw_rows = grid.get("rows") or grid.get("h") or grid.get("horizontal") or 0
        if isinstance(raw_cols, (list, tuple)) or isinstance(raw_rows, (list, tuple)):
            return None
        try:
            cols = int(raw_cols)
            rows = int(raw_rows)
        except (TypeError, ValueError):
            return None
        if cols <= 0 and rows <= 0:
            return None
        return (max(cols, 1), max(rows, 1))
    if isinstance(grid, (list, tuple)) and len(grid) >= 2:
        # A list-of-lists is a partition spec, not a muntin (cols, rows) pair.
        if isinstance(grid[0], (list, tuple)) or isinstance(grid[1], (list, tuple)):
            return None
        try:
            cols, rows = int(grid[0] or 0), int(grid[1] or 0)
        except (TypeError, ValueError):
            return None
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
        f'stroke="{stroke}" stroke-width="0.7"/>'
    )
    parts.append(
        f'<line x1="{tx(x0):.2f}" y1="{ty(y) - 8:.2f}" x2="{tx(x0):.2f}" y2="{ty(y) + 8:.2f}" '
        f'stroke="{stroke}" stroke-width="0.7"/>'
    )
    parts.append(
        f'<line x1="{tx(x1):.2f}" y1="{ty(y) - 8:.2f}" x2="{tx(x1):.2f}" y2="{ty(y) + 8:.2f}" '
        f'stroke="{stroke}" stroke-width="0.7"/>'
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
        f'stroke="{stroke}" stroke-width="0.7"/>'
    )
    parts.append(
        f'<line x1="{tx(x) - 8:.2f}" y1="{ty(y0):.2f}" x2="{tx(x) + 8:.2f}" y2="{ty(y0):.2f}" '
        f'stroke="{stroke}" stroke-width="0.7"/>'
    )
    parts.append(
        f'<line x1="{tx(x) - 8:.2f}" y1="{ty(y1):.2f}" x2="{tx(x) + 8:.2f}" y2="{ty(y1):.2f}" '
        f'stroke="{stroke}" stroke-width="0.7"/>'
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
        f'stroke="{stroke}" stroke-width="1.05" marker-end="url(#slideArrow)"/>'
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
    """2D outline handle palette — line colour only (no solid fill)."""
    if str(finish).lower() in ("black", "black_texture", "matte_black", "dark"):
        return {"stroke": "#1c1f24"}
    return {"stroke": "#6b7178"}


def _draw_lever_handle(
    parts: list[str], *, tx, ty, rect: tuple[float, float, float, float],
    side: str | None, finish: str, k: float, panel_index: Any = None,
) -> None:
    """Clean 2D outline lever handle: oval escutcheon + lever arm (no solid fill).

    Draws a draggable-friendly group tagged with ``data-handle`` so the live
    preview can attach touch/mouse drag to reposition it.
    """
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    pw = (x1 - x0)
    ph = (y1 - y0)
    c = _handle_finish_colors(finish)
    sw = max(0.70, min(0.50 * k, 1.10))
    rx = max(pw * 0.60, 5.0 * k)
    ry = max(ph * 0.5, 10.0 * k)
    tag = "" if panel_index is None else f' data-handle="{panel_index}"'
    group = [f'<g class="weos-handle"{tag} style="cursor:grab">']
    # Oval escutcheon plate (outline)
    group.append(
        f'<ellipse cx="{tx(cx):.2f}" cy="{ty(cy):.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
        f'fill="#ffffff" fill-opacity="0.35" stroke="{c["stroke"]}" stroke-width="{sw:.2f}"/>'
    )
    # Keyhole hint (outline circle)
    group.append(
        f'<circle cx="{tx(cx):.2f}" cy="{ty(cy) + ry * 0.32:.2f}" r="{max(pw * 0.16, 1.8 * k):.2f}" '
        f'fill="none" stroke="{c["stroke"]}" stroke-width="{sw * 0.8:.2f}"/>'
    )
    # Lever arm — extends into the leaf (away from the stile), outline only
    direction = -1.0 if side == "right" else 1.0
    arm_len = max(pw * 2.4, 24.0 * k)
    bar_h = max(pw * 0.52, 5.0 * k)
    ax0 = cx if direction > 0 else cx - arm_len
    ax1 = cx + arm_len if direction > 0 else cx
    ly = cy - ry * 0.35
    group.append(
        f'<rect x="{tx(ax0):.2f}" y="{ty(ly) - bar_h / 2:.2f}" width="{(ax1 - ax0):.2f}" height="{bar_h:.2f}" '
        f'rx="{bar_h / 2:.2f}" fill="none" stroke="{c["stroke"]}" stroke-width="{sw:.2f}"/>'
    )
    # Pivot knuckle (outline)
    group.append(
        f'<circle cx="{tx(cx):.2f}" cy="{ty(ly):.2f}" r="{bar_h * 0.7:.2f}" '
        f'fill="#ffffff" fill-opacity="0.35" stroke="{c["stroke"]}" stroke-width="{sw:.2f}"/>'
    )
    group.append("</g>")
    parts.append("".join(group))


def _draw_casement_hinge_svg(
    parts: list[str],
    *,
    tx,
    ty,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    stroke: str,
    stroke_width: float,
    extra_attrs: str = "",
) -> None:
    """Same stadium hinge glyph as shower / ventilator / PDF (horizontal barrel split)."""
    w = abs(float(x1) - float(x0))
    h = abs(float(y1) - float(y0))
    cx = (float(x0) + float(x1)) / 2.0
    cy = (float(y0) + float(y1)) / 2.0
    parts.append(
        casement_hinge_svg(
            tx(cx),
            ty(cy),
            w=w,
            h=h,
            stroke=stroke,
            stroke_width=stroke_width,
            extra_attrs=extra_attrs,
        )
    )


def _draw_hardware(parts: list[str], *, tx, ty, model: DrawingModel, finish: str, k: float) -> None:
    """Draw handles (from shutter meta, oriented) and casement hinge capsules."""
    meta = model.metadata or {}
    c = _handle_finish_colors(finish)
    # Hinge capsules (light fill + horizontal barrel split), centred on stile gap.
    for h in meta.get("hinges") or []:
        if not isinstance(h, Mapping):
            continue
        x0, y0, x1, y1 = float(h["x0"]), float(h["y0"]), float(h["x1"]), float(h["y1"])
        _draw_casement_hinge_svg(
            parts, tx=tx, ty=ty, x0=x0, y0=y0, x1=x1, y1=y1,
            stroke=c["stroke"], stroke_width=max(0.50, min(0.38 * k, 0.85)),
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
            side=sp.get("handleSide"), finish=finish, k=k, panel_index=sp.get("index"),
        )


def _draw_grid_svg(
    parts: list[str], *, tx, ty, meta: Mapping[str, Any], k: float, W: float, H: float,
    glass_fill: str, glass_stroke: str, frame_stroke: str, dim_stroke: str,
    dim_font: float, label_font: float, finish: str, annotations: bool, sw: float,
) -> None:
    """Clean 2D partition-grid: framed cells, per-cell role + hardware, full dims."""
    grid = meta.get("grid") or {}
    cells = grid.get("cells") or []
    role_color = {"fix": "#5a3a10", "sliding": "#0b3d7a", "openable": "#0b6a3d", "top_hung": "#0b6a3d"}
    role_text = {"fix": "FIX", "sliding": "SLIDING", "openable": "OPENABLE", "top_hung": "TOP HUNG"}

    # Outer frame
    parts.append(
        f'<rect x="{tx(0):.2f}" y="{ty(H):.2f}" width="{tx(W)-tx(0):.2f}" height="{ty(0)-ty(H):.2f}" '
        f'fill="none" stroke="{frame_stroke}" {_solid_sw(sw)}/>'
    )

    for cell in cells:
        x0, y0, x1, y1 = float(cell["x0"]), float(cell["y0"]), float(cell["x1"]), float(cell["y1"])
        role = cell.get("role") or "fix"
        rc = role_color.get(role, "#0b3d7a")
        # Cell frame (mullion)
        parts.append(
            f'<rect x="{tx(x0):.2f}" y="{ty(y1):.2f}" width="{tx(x1)-tx(x0):.2f}" height="{ty(y0)-ty(y1):.2f}" '
            f'fill="none" stroke="{frame_stroke}" {_solid_sw(sw)}/>'
        )
        # Glass lites
        for g in cell.get("glass") or []:
            gx0, gy0, gx1, gy1 = float(g["x0"]), float(g["y0"]), float(g["x1"]), float(g["y1"])
            parts.append(
                f'<rect x="{tx(gx0):.2f}" y="{ty(gy1):.2f}" width="{tx(gx1)-tx(gx0):.2f}" height="{ty(gy0)-ty(gy1):.2f}" '
                f'fill="{glass_fill}" stroke="{glass_stroke}" {_solid_sw(sw*0.7)}/>'
            )
        # Sash division lines (sliding)
        for sx in cell.get("sashLines") or []:
            parts.append(
                f'<line x1="{tx(float(sx)):.2f}" y1="{ty(y0):.2f}" x2="{tx(float(sx)):.2f}" y2="{ty(y1):.2f}" '
                f'stroke="{frame_stroke}" {_solid_sw(sw*0.9)}/>'
            )
        # Mesh (one sliding-panel width) — solid green, never dashed in print
        m = cell.get("mesh")
        if isinstance(m, Mapping):
            parts.append(
                f'<rect x="{tx(float(m["x0"])):.2f}" y="{ty(float(m["y1"])):.2f}" '
                f'width="{tx(float(m["x1"]))-tx(float(m["x0"])):.2f}" height="{ty(float(m["y0"]))-ty(float(m["y1"])):.2f}" '
                f'fill="none" stroke="#2a6a4a" {_solid_sw(sw*0.7)}/>'
            )
        # Openable diagonals — solid (print RIP stipples dashes)
        for d in cell.get("diagonals") or []:
            parts.append(
                f'<line x1="{tx(float(d[0])):.2f}" y1="{ty(float(d[1])):.2f}" x2="{tx(float(d[2])):.2f}" y2="{ty(float(d[3])):.2f}" '
                f'stroke="{rc}" {_solid_sw(sw*0.6)}/>'
            )
        # Arrows (sliding)
        for a in cell.get("arrows") or []:
            _arrow(parts, tx=tx, ty=ty, x0=float(a["x0"]), y0=float(a["y0"]), x1=float(a["x1"]), y1=float(a["y1"]))
        # Hinges (openable) — stadium + horizontal barrel split
        hc = _handle_finish_colors(finish)
        for hg in cell.get("hinges") or []:
            _draw_casement_hinge_svg(
                parts, tx=tx, ty=ty,
                x0=float(hg["x0"]), y0=float(hg["y0"]), x1=float(hg["x1"]), y1=float(hg["y1"]),
                stroke=hc["stroke"], stroke_width=max(0.50, min(0.38 * k, 0.85)),
            )
        # Handles — 2D lever outline
        for hd in cell.get("handles") or []:
            _draw_lever_handle(parts, tx=tx, ty=ty, rect=(float(hd["x0"]), float(hd["y0"]), float(hd["x1"]), float(hd["y1"])), side=hd.get("side"), finish=finish, k=k)

        if annotations:
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            chip_w, chip_h = 70 * k, 30 * k
            parts.append(
                f'<rect x="{tx(cx)-chip_w/2:.2f}" y="{ty(cy)-chip_h/2:.2f}" width="{chip_w:.2f}" height="{chip_h:.2f}" '
                f'rx="{3*k:.1f}" fill="#fff" fill-opacity="0.92" stroke="#333" stroke-width="{max(0.55, min(0.40 * k, 0.90)):.2f}"/>'
            )
            parts.append(
                f'<text x="{tx(cx):.2f}" y="{ty(cy)+label_font*0.3:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font*0.8:.0f}" font-weight="700" fill="#111">{escape(cell.get("label") or "")}</text>'
            )
            parts.append(
                f'<text x="{tx(cx):.2f}" y="{ty(cy)-chip_h*0.9:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font*0.62:.0f}" font-weight="600" fill="{rc}">{role_text.get(role, role.upper())}</text>'
            )
            # Cell size (w × h) under the label
            parts.append(
                f'<text x="{tx(cx):.2f}" y="{ty(cy)+chip_h*1.15:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font*0.55:.0f}" fill="#444">{cell.get("wmm")}×{cell.get("hmm")}</text>'
            )

    if annotations:
        colX = grid.get("colX") or [0, W]
        rowTop = grid.get("rowTop") or [H, 0]
        # Overall dims
        _dim_line_v(parts, tx=tx, ty=ty, y0=0.0, y1=H, x=-55.0 * k, text=f"{H:g}", text_x=-82.0 * k, stroke=dim_stroke, font=dim_font)
        _dim_line_h(parts, tx=tx, ty=ty, x0=0.0, x1=W, y=-95.0 * k, text=f"{W:g}", text_y=-122.0 * k, stroke=dim_stroke, font=dim_font)
        # Column widths (top)
        for i in range(len(colX) - 1):
            _dim_line_h(parts, tx=tx, ty=ty, x0=float(colX[i]), x1=float(colX[i + 1]), y=-42.0 * k, text=f"{float(colX[i+1])-float(colX[i]):g}", text_y=-64.0 * k, stroke=dim_stroke, font=dim_font * 0.8)
        # Row heights (right)
        for i in range(len(rowTop) - 1):
            _dim_line_v(parts, tx=tx, ty=ty, y0=float(rowTop[i + 1]), y1=float(rowTop[i]), x=W + 48.0 * k, text=f"{float(rowTop[i])-float(rowTop[i+1]):g}", text_x=W + 74.0 * k, stroke=dim_stroke, font=dim_font * 0.8)


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
    sw = 0.6 * stroke_scale

    # Outer frame / track box
    parts.append(
        f'<rect x="{tx(0):.2f}" y="{ty(plan_y0 + plan_h):.2f}" width="{tx(W) - tx(0):.2f}" '
        f'height="{ty(plan_y0) - ty(plan_y0 + plan_h):.2f}" fill="none" stroke="#222" '
        f'stroke-width="{0.8 * stroke_scale:.2f}"/>'
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
    if not glass:
        return

    if system in ("casement", "openable", "opening"):
        # Openable plan: sash + swing arc toward the hinge stile
        for s in glass:
            x0, x1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
            hinge = s.get("hingeSide") or ("left" if float(s.get("openDir") or 1) >= 0 else "right")
            _hollow_plan_band(parts, tx=tx, ty=ty, x0=x0, x1=x1, y_bot=y_mid - band * 0.5, y_top=y_mid + band * 0.5, stroke="#173a63", stroke_width=sw)
            hx = x0 if hinge == "left" else x1
            parts.append(
                f'<line x1="{tx(hx):.2f}" y1="{ty(y_mid):.2f}" x2="{tx((x0 + x1) / 2):.2f}" '
                f'y2="{ty(y_mid + band * 1.3):.2f}" stroke="#8b1e1a" stroke-width="{0.8 * stroke_scale:.2f}"/>'
            )
        parts.append(
            f'<text x="{tx(W / 2):.2f}" y="{ty(y_mid - band * 1.4):.2f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="{14 * stroke_scale:.0f}" fill="#173a63">OPENABLE · hinge side</text>'
        )
        return

    # --- Sliding: External / Internal track indicator (reference Image B) ---
    depths = sorted({int(s.get("depth") or 1) for s in glass})
    dmin = depths[0] if depths else 1
    ext_y = y_mid + band * 0.55   # external (back) track — drawn higher
    int_y = y_mid - band * 0.55   # internal (front) track — drawn lower
    left_x = min(float(s.get("x0") or 0) for s in glass)

    # External / Internal labels at the far left
    parts.append(
        f'<text x="{tx(left_x) - 6 * stroke_scale:.2f}" y="{ty(ext_y) + 4 * stroke_scale:.2f}" text-anchor="end" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{12 * stroke_scale:.0f}" fill="#0b3d7a">External</text>'
    )
    parts.append(
        f'<text x="{tx(left_x) - 6 * stroke_scale:.2f}" y="{ty(int_y) + 4 * stroke_scale:.2f}" text-anchor="end" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{12 * stroke_scale:.0f}" fill="#0b3d7a">Internal</text>'
    )

    # Mesh sash (frontmost/internal) — solid green (print must not stipple)
    for s in meshes:
        x0, x1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
        parts.append(
            f'<line x1="{tx(x0):.2f}" y1="{ty(int_y - band * 0.5):.2f}" x2="{tx(x1):.2f}" y2="{ty(int_y - band * 0.5):.2f}" '
            f'stroke="#2a6a4a" {_solid_sw(2.0 * stroke_scale)}/>'
        )

    # One offset track bar per glass sash: internal + external both solid
    for pos, s in enumerate(glass):
        x0, x1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
        depth = int(s.get("depth") or 1)
        is_front = depth == dmin
        yy = int_y if is_front else ext_y
        parts.append(
            f'<line x1="{tx(x0):.2f}" y1="{ty(yy):.2f}" x2="{tx(x1):.2f}" y2="{ty(yy):.2f}" '
            f'stroke="#0b3d7a" {_solid_sw(1.8 * stroke_scale)}/>'
        )
        # End ticks
        for ex in (x0, x1):
            parts.append(
                f'<line x1="{tx(ex):.2f}" y1="{ty(yy) - 4 * stroke_scale:.2f}" x2="{tx(ex):.2f}" '
                f'y2="{ty(yy) + 4 * stroke_scale:.2f}" stroke="#0b3d7a" stroke-width="{1.4 * stroke_scale:.2f}"/>'
            )
        # Circled panel number below
        cxp = (x0 + x1) / 2.0
        num_y = y_mid - band * 1.35
        parts.append(
            f'<circle cx="{tx(cxp):.2f}" cy="{ty(num_y):.2f}" r="{9 * stroke_scale:.2f}" fill="none" '
            f'stroke="#0b3d7a" stroke-width="{1.3 * stroke_scale:.2f}"/>'
        )
        parts.append(
            f'<text x="{tx(cxp):.2f}" y="{ty(num_y) + 4 * stroke_scale:.2f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="{12 * stroke_scale:.0f}" fill="#0b3d7a">{pos + 1}</text>'
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
      - pdf: same slim strokes as canvas (tighter margin only for the PDF column)
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

    # Drafting style: profile outlines only (never solid dark fills).
    # Strokes are in model-mm so they stay readable when the SVG is fit into
    # the live preview (~420px) or the quote PDF column.
    _ = colour  # kept for API / quote colour label; frames stay stroke-only
    frame_stroke = "#111111"
    # Very light glass tint — clear 2D, not solid dark. Same fill for canvas + PDF
    # so Quote/Print match the live slim drawing (no PDF-only darkening).
    glass_fill = "rgba(186, 214, 235, 0.28)"
    glass_stroke = "#111111"  # solid black glass edge (print-safe, not blue dash)
    dim_stroke = "#8b1e1a"
    # Slim 2D CAD strokes in model-mm. Dark + solid. Floor is ~1.45× Cairo PNG
    # into a ~200 pt PDF cell — hairlines (~1 mm) RIP as dotted. Keep slim
    # (old fat contrast was ~11 mm) but above print-safe minimum.
    sw_outer = max(2.00, min(ref * 0.0024, 3.40))
    sw_inner = max(1.55, sw_outer * 0.82)
    sw_profile = sw_inner
    sw_seg = sw_inner
    sw_grid = max(1.15, sw_inner * 0.72)
    sw_interlock = max(1.70, sw_outer * 0.90)
    dim_font = 36.0 * k
    label_font = 26.0 * k

    bg = "#ffffff"
    # Compact sash box table for interactive handle drag: "i;x0;x1;y0;y1;nx0;nx1|..."
    _sh_rows = []
    for _sp in (model.metadata or {}).get("shutters") or []:
        if not isinstance(_sp, Mapping) or _sp.get("role") != "glass":
            continue
        _sh_rows.append(
            "{i};{x0:.1f};{x1:.1f};{y0:.1f};{y1:.1f};{nx0:.1f};{nx1:.1f}".format(
                i=_sp.get("index"), x0=float(_sp.get("x0") or 0), x1=float(_sp.get("x1") or 0),
                y0=float(_sp.get("y0") or 0), y1=float(_sp.get("y1") or 0),
                nx0=float(_sp.get("nomX0") or _sp.get("x0") or 0), nx1=float(_sp.get("nomX1") or _sp.get("x1") or 0),
            )
        )
    _sh_data = "|".join(_sh_rows)
    _meta0 = model.metadata or {}
    _sys0 = str(_meta0.get("system") or "sliding").lower()
    _title_bits = [f"{model.width:g}×{model.height:g}"]
    try:
        _tc0 = _meta0.get("track_count")
        if _sys0 == "sliding" and _tc0 not in (None, ""):
            _title_bits.append(f"{float(_tc0):g}-track")
    except (TypeError, ValueError):
        pass
    _op0 = str(_meta0.get("opening") or "").lower()
    if _sys0 == "sliding" and _op0:
        _title_bits.append("center opening" if _op0 in ("center", "centre") else "side opening")
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}" height="{h:.1f}" '
        f'viewBox="0 0 {w:.1f} {h:.1f}" data-model-minx="{min_x:.3f}" data-model-maxy="{max_y:.3f}" '
        f'data-model-system="{escape(str((model.metadata or {}).get("system") or "sliding"))}" '
        f'data-visual-profile-mm="{escape(str((model.metadata or {}).get("visualProfileMm") or ""))}" '
        f'data-visual-series="{escape(str((model.metadata or {}).get("visualSeries") or ""))}" '
        f'data-shutters="{escape(_sh_data)}">',
        f"<title>{escape(' · '.join(_title_bits))}</title>",
        f'<rect width="100%" height="100%" fill="{bg}"/>',
        '<defs><marker id="slideArrow" markerWidth="10" markerHeight="10" refX="8" refY="4" orient="auto">'
        '<path d="M0,0 L8,4 L0,8 Z" fill="#0b3d7a"/></marker></defs>',
    ]

    # Grid / partition designer — dedicated clean-2D rendering from metadata
    if str((model.metadata or {}).get("system") or "") == "grid":
        _meta = model.metadata or {}
        _finish = str(_meta.get("handle_finish") or "silver")
        _draw_grid_svg(
            parts, tx=tx, ty=ty, meta=_meta, k=k, W=float(model.width), H=float(model.height),
            glass_fill=glass_fill, glass_stroke=glass_stroke, frame_stroke=frame_stroke,
            dim_stroke=dim_stroke, dim_font=36.0 * k,
            label_font=26.0 * k, finish=_finish, annotations=annotations, sw=sw_profile,
        )
        parts.append("</svg>")
        return "\n".join(parts)

    # Glass first (filled), then profile outlines on top
    panel_fill = None
    try:
        from WEOS.factory.panel_fills import normalize_panel_fill, svg_fill_for_rect

        raw_fill = (model.metadata or {}).get("panel_fill") or (model.metadata or {}).get("panelFill")
        if isinstance(raw_fill, Mapping) and str(raw_fill.get("fillType") or "glass") != "glass":
            panel_fill = normalize_panel_fill(raw_fill)
    except Exception:
        panel_fill = None

    glasses_early = _glass_panels(model)
    if panel_fill:
        for _name, gx0, gy0, gx1, gy1 in glasses_early:
            parts.extend(
                svg_fill_for_rect(
                    x0=gx0, y0=gy0, x1=gx1, y1=gy1,
                    fill=panel_fill, tx=tx, ty=ty, k=k, annotate=annotations or pdf,
                )
            )
    else:
        for pl in model.polylines:
            if pl.layer != "GLASS" or len(pl.points) < 2:
                continue
            pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
            parts.append(
                f'<polygon points="{pts}" fill="{glass_fill}" stroke="{glass_stroke}" '
                f'{_solid_sw(sw_profile * 0.85)}/>'
            )

    for pl in model.polylines:
        if pl.layer in ("GLASS", "HARDWARE") or len(pl.points) < 2:
            continue
        pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
        nm = str(pl.name or "").lower()
        is_outer = "outer" in nm or nm in ("outer_frame", "frame_outer", "track_outer")
        sw_pl = sw_outer if is_outer else sw_inner
        if pl.closed:
            parts.append(
                f'<polygon points="{pts}" fill="none" stroke="{frame_stroke}" {_solid_sw(sw_pl)}/>'
            )
        else:
            parts.append(
                f'<polyline points="{pts}" fill="none" stroke="{frame_stroke}" {_solid_sw(sw_pl * 0.9)}/>'
            )

    for seg in model.segments:
        lname = (seg.name or "").lower()
        is_il = "interlock" in lname or "meeting" in lname
        stroke = "#052c54" if is_il else (frame_stroke if seg.layer == "PROFILES" else "#333")
        lw = sw_interlock if is_il else sw_seg
        parts.append(
            f'<line x1="{tx(seg.start.x):.2f}" y1="{ty(seg.start.y):.2f}" '
            f'x2="{tx(seg.end.x):.2f}" y2="{ty(seg.end.y):.2f}" '
            f'stroke="{stroke}" {_solid_sw(lw)}/>'
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
        import re as _re
        system = str(meta.get("system") or "sliding")
        sys_role = {"casement": "OPENABLE", "openable": "OPENABLE", "bifold": "FOLD"}.get(system, "SLIDING")
        shutters_by_idx = {
            int(s["index"]): s
            for s in (meta.get("shutters") or [])
            if isinstance(s, Mapping) and s.get("index") is not None
        }
        slide_idx = 0
        fix_idx = 0
        # Sliding sashes are labelled A1, A2 … counted from the RIGHT (reference: the
        # right-hand sash is A1, the left is A2), so pre-count the sliding lites.
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
                # A-number from the right → rightmost sliding sash = A1
                panel_id = f"A{max(n_slide - slide_idx + 1, 1)}"
                role = sys_role
                role_color = "#0b3d7a"
                is_sliding = role == "SLIDING"

            # Sliding sashes read like the reference: clean arrow + A-label, no chip.
            if not is_sliding:
                chip_w, chip_h = 80 * k, 36 * k
                chip_y = cy + (y1 - y0) * 0.32
                parts.append(
                    f'<rect x="{tx(cx) - chip_w / 2:.2f}" y="{ty(chip_y) - chip_h / 2:.2f}" '
                    f'width="{chip_w:.2f}" height="{chip_h:.2f}" rx="{3 * k:.1f}" fill="#fff" fill-opacity="0.95" '
                    f'stroke="#333" stroke-width="{max(0.55, min(0.40 * k, 0.90)):.2f}"/>'
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

            # Slide-direction arrow (sliding only) — direction from the sash openDir
            if is_sliding and (x1 - x0) > 40:
                ay = cy
                od = float(sp_meta.get("openDir") or 0) if sp_meta else 0.0
                if od == 0:
                    od = 1.0 if slide_idx % 2 == 1 else -1.0
                halfw = (x1 - x0)
                if od > 0:
                    ax0, ax1 = cx - halfw * 0.24, cx + halfw * 0.22
                    lx = ax0 - halfw * 0.02
                    anchor = "end"
                else:
                    ax0, ax1 = cx + halfw * 0.24, cx - halfw * 0.22
                    lx = ax0 + halfw * 0.02
                    anchor = "start"
                _arrow(parts, tx=tx, ty=ty, x0=ax0, y0=ay, x1=ax1, y1=ay)
                # Label sits beside the arrow tail (like "A2 →" / "← A1")
                parts.append(
                    f'<text x="{tx(lx):.2f}" y="{ty(ay) + label_font * 1.05:.2f}" text-anchor="{anchor}" '
                    f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font * 0.85:.0f}" '
                    f'font-weight="700" fill="#0b3d7a">{escape(panel_id)}</text>'
                )

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
                stroke_scale=max(0.55, min(k * 0.45, 1.05)),
            )

    parts.append("</svg>")
    return "\n".join(parts)


def preview_svgs_for_drawing(
    drawing,
    *,
    colour: str | None = None,
    grid: Any = None,
    include_plan: bool = True,
) -> dict[str, str]:
    """Render live-preview SVG once — PDF/Print reuse the same slim strokes."""
    kwargs = dict(colour=colour, annotations=True, grid=grid, include_plan=include_plan)
    svg = render_svg_string(drawing, style="preview", **kwargs)
    return {"svg": svg, "pdfSvg": svg}


def elevation_svg_for_line(line: Mapping[str, Any], *, style: str = "pdf") -> str | None:
    """Build quote/canvas SVG for a cart line from the same geometry engine as live preview."""
    from WEOS.factory.line_kind import (
        is_pergola_cart_line,
        is_railing_cart_line,
        is_shower_cart_line,
        is_surface_cart_line,
        is_ventilator_cart_line,
    )

    prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
    live_svg = str((prev or {}).get("svg") or (prev or {}).get("pdfSvg") or "").strip()
    # Always prefer the live-canvas SVG (slim strokes). Never a thickened pdfSvg.
    if live_svg and "<svg" in live_svg.lower():
        return live_svg

    if is_ventilator_cart_line(line):
        opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        cfg = opts.get("ventilator") if isinstance(opts, Mapping) else None
        cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
        if not cfg and isinstance(line.get("ventilator"), Mapping):
            cfg = dict(line.get("ventilator") or {})
        try:
            from WEOS.factory.ventilator_engine import (
                compute_ventilator,
                ensure_ventilator_dims,
                ventilator_svg,
            )

            cfg = ensure_ventilator_dims(
                cfg,
                width=float(line.get("width") or 0) or None,
                height=float(line.get("height") or 0) or None,
            )
            q = opts.get("ventilatorQuote") if isinstance(opts, Mapping) else None
            if not isinstance(q, Mapping):
                q = line.get("ventilator") if isinstance(line.get("ventilator"), Mapping) else None
            if not isinstance(q, Mapping) or not q.get("widthMm"):
                q = compute_ventilator(cfg)
            svg = ventilator_svg(cfg, quote=q if isinstance(q, Mapping) else None)
            if svg:
                return str(svg)
        except Exception:
            pass
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")
        return str(svg) if svg else None

    if is_shower_cart_line(line):
        opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        cfg = opts.get("shower") if isinstance(opts, Mapping) else None
        cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
        if not cfg and isinstance(line.get("shower"), Mapping):
            cfg = dict(line.get("shower") or {})
        try:
            from WEOS.factory.shower_engine import compute_shower, ensure_shower_dims, shower_svg

            cfg = ensure_shower_dims(
                cfg,
                width=float(line.get("width") or 0) or None,
                height=float(line.get("height") or 0) or None,
            )
            q = opts.get("showerQuote") if isinstance(opts, Mapping) else None
            if not isinstance(q, Mapping):
                q = line.get("shower") if isinstance(line.get("shower"), Mapping) else None
            if not isinstance(q, Mapping) or not q.get("panels"):
                q = compute_shower(cfg)
            svg = shower_svg(cfg, quote=q if isinstance(q, Mapping) else None)
            if svg:
                return str(svg)
        except Exception:
            pass
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")
        return str(svg) if svg else None

    # Railing lines must NEVER call window generate_job (that printed windows on quotes).
    if is_railing_cart_line(line):
        opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        cfg = opts.get("railing") if isinstance(opts, Mapping) else None
        cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
        try:
            from WEOS.factory.railing_engine import (
                compute_railing,
                ensure_railing_dims,
                railing_quote_matches_cfg,
                railing_svg,
            )

            cfg = ensure_railing_dims(
                cfg,
                width=float(line.get("width") or 0) or None,
                height=float(line.get("height") or 0) or None,
            )
            q = opts.get("railingQuote") if isinstance(opts, Mapping) else None
            if not isinstance(q, Mapping):
                q = line.get("railing") if isinstance(line.get("railing"), Mapping) else None
            if (
                not isinstance(q, Mapping)
                or float((q or {}).get("lengthMm") or 0) <= 1.0
                or not railing_quote_matches_cfg(q, cfg)
            ) and cfg:
                q = compute_railing(cfg)
            svg = railing_svg(cfg or {}, quote=q if isinstance(q, Mapping) else None)
            if svg:
                return str(svg)
        except Exception:
            pass
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")
        return str(svg) if svg else None

    from WEOS.factory.line_kind import is_louver_cart_line

    if is_louver_cart_line(line):
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")
        if svg:
            return str(svg)
        try:
            from WEOS.factory.special_schematics import louver_svg

            return str(louver_svg(line))
        except Exception:
            return None

    if is_pergola_cart_line(line):
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")
        if svg:
            return str(svg)
        try:
            from WEOS.factory.special_schematics import pergola_svg

            return str(pergola_svg(line))
        except Exception:
            return None

    if is_surface_cart_line(line):
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")
        if svg:
            return str(svg)
        try:
            from WEOS.factory.special_schematics import surface_svg

            return str(surface_svg(line))
        except Exception:
            return None

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
    product = str(line.get("product") or line.get("productId") or "")
    if not product:
        return None
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
        # geometry (see product_loader._ensure_renderable), so we draw them too
        # instead of returning None.
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
            frame_material=lo.get("frameMaterial") or line.get("frameMaterial"),
        )
        if lo.get("panelFill"):
            from WEOS.factory.panel_fills import attach_fill_to_drawing

            attach_fill_to_drawing(job.drawing, lo.get("panelFill"))
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
                "widthMm": mm_n(part.get("widthMm")),
                "heightMm": mm_n(part.get("heightMm") or part.get("sizeMm")),
                "glassWidthMm": mm_n(part.get("glassWidthMm")),
                "glassHeightMm": mm_n(part.get("glassHeightMm")),
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
                        "widthMm": mm_n(s.get("widthMm")), "heightMm": mm_n(shutter_h),
                    }
                )
                continue
            s_idx += 1
            fixed = not bool(s.get("operable", True))
            hs = str(s.get("handleSide") or s.get("handle_side") or "").lower()
            if is_bifold:
                pack = str(s.get("pack") or "").strip().lower()
                if pack.startswith("r"):
                    n = sum(1 for p in panels if str(p.get("id") or "").startswith("R")) + 1
                    role, label, pid = "leaf", "Fold (R)", f"R{n}"
                else:
                    n = sum(1 for p in panels if str(p.get("id") or "").startswith("L")) + 1
                    role, label, pid = "leaf", "Fold (L)", f"L{n}"
            elif system == "casement":
                hs_top = str(s.get("hingeSide") or "").lower() == "top" or hs == "bottom" or str(s.get("pack") or "") == "top_hung"
                if fixed:
                    role, label, pid = "fix", "Fix", f"S{s_idx}"
                elif hs_top:
                    role, label, pid = "openable", "Top hung · handle bottom", f"S{s_idx}"
                else:
                    side_lbl = "L" if hs == "left" else ("R" if hs == "right" else "—")
                    role, label, pid = "openable", f"Openable · handle {side_lbl}", f"S{s_idx}"
            elif fixed:
                role, label, pid = "fix", "Fix (locked sash)", f"S{s_idx}"
            else:
                role, label, pid = "sliding", "Sliding", f"S{s_idx}"
            panels.append(
                {
                    "id": pid, "role": role, "side": s.get("track") or s.get("pack") or hs or None,
                    "label": label,
                    "track": s.get("track"), "depth": s.get("depth"), "pack": s.get("pack"),
                    "widthMm": mm_n(s.get("widthMm")), "heightMm": mm_n(shutter_h),
                    "glassWidthMm": mm_n(s.get("glassWidthMm")),
                    "glassHeightMm": mm_n(s.get("glassHeightMm")),
                    "handle": bool(s.get("handle")),
                    "handleSide": hs or None,
                    "operable": not fixed,
                }
            )
    else:
        panels.extend(
            [
                {"id": "S1", "role": "sliding", "side": "left", "label": "Sliding",
                 "widthMm": mm_n(meta.get("left_shutter_width")), "heightMm": mm_n(shutter_h),
                 "glassWidthMm": mm_n(meta.get("left_glass_width")),
                 "glassHeightMm": mm_n(meta.get("glass_height"))},
                {"id": "S2", "role": "sliding", "side": "right", "label": "Sliding",
                 "widthMm": mm_n(meta.get("right_shutter_width")), "heightMm": mm_n(shutter_h),
                 "glassWidthMm": mm_n(meta.get("right_glass_width")),
                 "glassHeightMm": mm_n(meta.get("glass_height"))},
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
    elif system == "casement":
        kind = "casement"
    elif meta.get("partitions"):
        kind = "sliding_with_partitions"
    else:
        kind = "two_track_sliding"
    tc_raw = meta.get("track_count")
    try:
        tc_val = float(tc_raw) if tc_raw is not None else None
    except (TypeError, ValueError):
        tc_val = None
    if is_bifold or system == "casement":
        tc_val = None
    elif tc_val is None:
        tc_val = 2.0
    return {
        "kind": kind,
        "system": system,
        "widthMm": float(width),
        "heightMm": float(height),
        "trackCount": tc_val,
        "mesh": bool(meta.get("mesh")),
        "glassCount": int(meta.get("glass_count") or 0),
        "meshCount": int(meta.get("mesh_count") or 0),
        "opening": meta.get("opening"),
        "openingSide": meta.get("opening_side") or meta.get("openingSide"),
        "openingLabel": (
            "center opening"
            if str(meta.get("opening") or "").lower() in ("center", "centre")
            else ("side opening" if str(meta.get("opening") or "") else None)
        ) if system == "sliding" else None,
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
