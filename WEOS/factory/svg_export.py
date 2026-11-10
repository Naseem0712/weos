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


def _partition_split_sizes(meta: Mapping[str, Any] | None) -> dict[str, float]:
    """Nominal fix sizes per side from layout meta partitions (mm)."""
    out = {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0}
    parts = (meta or {}).get("partitions")
    if not isinstance(parts, list):
        return out
    for p in parts:
        if not isinstance(p, Mapping):
            continue
        side = str(p.get("side") or "").lower()
        if side not in out:
            continue
        try:
            size = float(p.get("sizeMm") or (p.get("heightMm") if side in ("top", "bottom") else p.get("widthMm")) or 0)
        except (TypeError, ValueError):
            size = 0.0
        if size > 0:
            out[side] += size
    return out


def _vertical_split_chain(H: float, top_fix: float, bot_fix: float) -> list[tuple[float, float, str]]:
    """``[(y0, y1, label)]`` bottom→top: FIX n / remaining door-shutter share / FIX n.

    The pieces add up to the overall height so the print reads
    "600 fix applied, 2874 left" next to the overall 3474.
    """
    rows: list[tuple[float, float, str]] = []
    y = 0.0
    if bot_fix > 0:
        rows.append((y, min(y + bot_fix, H), f"FIX {mm_n(bot_fix)}"))
        y += bot_fix
    rest_top = H - (top_fix if top_fix > 0 else 0.0)
    if rest_top > y:
        rows.append((y, rest_top, f"{mm_n(rest_top - y)}"))
    if top_fix > 0:
        rows.append((max(rest_top, 0.0), H, f"FIX {mm_n(top_fix)}"))
    return rows


def _horizontal_split_chain(W: float, left_fix: float, right_fix: float) -> list[tuple[float, float, str]]:
    rows: list[tuple[float, float, str]] = []
    x = 0.0
    if left_fix > 0:
        rows.append((x, min(x + left_fix, W), f"FIX {mm_n(left_fix)}"))
        x += left_fix
    rest = W - (right_fix if right_fix > 0 else 0.0)
    if rest > x:
        rows.append((x, rest, f"{mm_n(rest - x)}"))
    if right_fix > 0:
        rows.append((max(rest, 0.0), W, f"FIX {mm_n(right_fix)}"))
    return rows


def _panel_width_dim_spans(
    meta: Mapping[str, Any] | None,
    W: float,
) -> list[tuple[float, float]]:
    """Per-panel width dim spans along the elevation bottom (outer bay shares).

    Sliding / bifold: nominal shutter shares (already tile 0..W).
    Casement / openable: continuous bay chain across overall W using mullion
    mid-points so FIX and openable panels each get a divided size label.
    Glass / daylight (sash-inner) widths are never returned.
    """
    system = str((meta or {}).get("system") or "sliding").lower()
    glass = [
        s
        for s in ((meta or {}).get("shutters") or [])
        if isinstance(s, Mapping) and s.get("role") == "glass"
    ]
    if len(glass) < 1:
        return []
    glass = sorted(
        glass,
        key=lambda s: float(s.get("nomX0") or s.get("x0") or 0.0),
    )
    if system in ("casement", "openable", "opening"):
        if len(glass) == 1:
            return [(0.0, float(W))]
        bounds: list[float] = [0.0]
        for i in range(len(glass) - 1):
            a = float(glass[i].get("x1") or glass[i].get("nomX1") or 0.0)
            b = float(glass[i + 1].get("x0") or glass[i + 1].get("nomX0") or 0.0)
            bounds.append((a + b) / 2.0)
        bounds.append(float(W))
        return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i + 1] > bounds[i] + 0.5]
    # Sliding / bifold — nominal equal-division shares
    spans: list[tuple[float, float]] = []
    for s in glass:
        nx0 = float(s.get("nomX0") or s.get("x0") or 0.0)
        nx1 = float(s.get("nomX1") or s.get("x1") or 0.0)
        if nx1 > nx0 + 0.5:
            spans.append((nx0, nx1))
    return spans


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


def _plan_hinge_ticks(
    parts: list[str],
    *,
    tx,
    ty,
    x0: float,
    x1: float,
    y_mid: float,
    band: float,
    hinge: str,
    stroke_scale: float,
) -> None:
    """Hinge marks on the real hinge edge. No stroke across the leaf."""
    sw = max(0.7 * stroke_scale, 0.45)
    span = max(float(x1) - float(x0), 1.0)
    if hinge == "top":
        yb = y_mid + band * 0.5
        for frac in (0.22, 0.78):
            hx = x0 + span * frac
            parts.append(
                f'<line x1="{tx(hx):.2f}" y1="{ty(yb):.2f}" x2="{tx(hx):.2f}" '
                f'y2="{ty(yb - band * 0.55):.2f}" stroke="#8b1e1a" stroke-width="{sw:.2f}" '
                f'data-plan-hinge="top"/>'
            )
        return
    side = "left" if hinge == "left" else "right"
    hx = x0 if side == "left" else x1
    stub = min(span * 0.045, max(band * 0.8, 8.0))
    direction = 1.0 if side == "left" else -1.0
    for frac in (0.22, 0.78):
        yy = (y_mid - band * 0.5) + band * frac
        parts.append(
            f'<line x1="{tx(hx):.2f}" y1="{ty(yy):.2f}" '
            f'x2="{tx(hx + direction * stub):.2f}" y2="{ty(yy):.2f}" '
            f'stroke="#8b1e1a" stroke-width="{sw:.2f}" data-plan-hinge="{side}"/>'
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
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font*0.55:.0f}" fill="#444">{mm_n(cell.get("wmm"))}×{mm_n(cell.get("hmm"))}</text>'
            )

    if annotations:
        colX = grid.get("colX") or [0, W]
        rowTop = grid.get("rowTop") or [H, 0]
        # Overall dims (whole mm labels only)
        _dim_line_v(parts, tx=tx, ty=ty, y0=0.0, y1=H, x=-55.0 * k, text=str(mm_n(H)), text_x=-82.0 * k, stroke=dim_stroke, font=dim_font)
        _dim_line_h(parts, tx=tx, ty=ty, x0=0.0, x1=W, y=-95.0 * k, text=str(mm_n(W)), text_y=-122.0 * k, stroke=dim_stroke, font=dim_font)
        # Column widths (top)
        for i in range(len(colX) - 1):
            _dim_line_h(parts, tx=tx, ty=ty, x0=float(colX[i]), x1=float(colX[i + 1]), y=-42.0 * k, text=str(mm_n(float(colX[i + 1]) - float(colX[i]))), text_y=-64.0 * k, stroke=dim_stroke, font=dim_font * 0.8)
        # Row heights (right)
        for i in range(len(rowTop) - 1):
            _dim_line_v(parts, tx=tx, ty=ty, y0=float(rowTop[i + 1]), y1=float(rowTop[i]), x=W + 48.0 * k, text=str(mm_n(float(rowTop[i]) - float(rowTop[i + 1]))), text_x=W + 74.0 * k, stroke=dim_stroke, font=dim_font * 0.8)


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
        # Openable plan. A single leaf (or a top-hung vent) must not stroke a
        # line to the centre of the sash — that reads as a false mid rail.
        operable_glass = [s for s in glass if bool(s.get("operable", True))]
        single = len(operable_glass) == 1
        for s in glass:
            x0, x1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
            _hollow_plan_band(parts, tx=tx, ty=ty, x0=x0, x1=x1, y_bot=y_mid - band * 0.5, y_top=y_mid + band * 0.5, stroke="#173a63", stroke_width=sw)
            # Fixed panels are glazing only — no hinge, no door swing in plan.
            if not bool(s.get("operable", True)):
                continue
            hinge = str(s.get("hingeSide") or "").lower()
            if not hinge:
                hinge = "left" if float(s.get("openDir") or 1) >= 0 else "right"
            top_hung = hinge == "top" or str(s.get("pack") or "") == "top_hung"
            if top_hung or single:
                _plan_hinge_ticks(
                    parts, tx=tx, ty=ty, x0=x0, x1=x1, y_mid=y_mid, band=band,
                    hinge="top" if top_hung else hinge, stroke_scale=stroke_scale,
                )
            else:
                hx = x0 if hinge == "left" else x1
                parts.append(
                    f'<line x1="{tx(hx):.2f}" y1="{ty(y_mid):.2f}" x2="{tx((x0 + x1) / 2):.2f}" '
                    f'y2="{ty(y_mid + band * 1.3):.2f}" stroke="#8b1e1a" stroke-width="{0.8 * stroke_scale:.2f}"/>'
                )
        plan_lbl = "OPENABLE · hinge side" if operable_glass else "FIXED PANELS"
        parts.append(
            f'<text x="{tx(W / 2):.2f}" y="{ty(y_mid - band * 1.4):.2f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="{14 * stroke_scale:.0f}" fill="#173a63">{plan_lbl}</text>'
        )
        return

    # --- Sliding: External / Internal track indicator (reference Image B) ---
    # One plan line per glass track (depth level): 2-track → 2 lines, 3-track
    # telescopic → 3 lines, 4-track → 4 lines. Mesh rides its own front line.
    depths = sorted({int(s.get("depth") or 1) for s in glass})
    dmin = depths[0] if depths else 1
    n_levels = max(len(depths), 1)
    try:
        n_levels = max(n_levels, int(track_count) - (1 if (mesh or meshes) else 0))
    except (TypeError, ValueError):
        pass
    n_levels = max(min(n_levels, 6), 1)
    ext_y = y_mid + band * 0.55   # external (back) track — drawn higher
    int_y = y_mid - band * 0.55   # internal (front) track — drawn lower
    if n_levels > 2:
        ext_y = y_mid + band * 0.75
        int_y = y_mid - band * 0.75

    def _level_y(depth: int) -> float:
        if n_levels <= 1:
            return int_y
        rank = depths.index(depth) if depth in depths else 0
        return int_y + (ext_y - int_y) * (rank / float(n_levels - 1))

    left_x = min(float(s.get("x0") or 0) for s in glass)
    if n_levels > 2:
        # faint guide line for every track so empty tracks still read
        for lv in range(n_levels):
            yy = int_y + (ext_y - int_y) * (lv / float(n_levels - 1))
            parts.append(
                f'<line x1="{tx(left_x):.2f}" y1="{ty(yy):.2f}" x2="{tx(W - left_x):.2f}" y2="{ty(yy):.2f}" '
                f'stroke="#c3d0dd" {_solid_sw(0.5 * stroke_scale)}/>'
            )

    # External / Internal labels at the far left
    parts.append(
        f'<text x="{tx(left_x) - 6 * stroke_scale:.2f}" y="{ty(ext_y) + 4 * stroke_scale:.2f}" text-anchor="end" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{12 * stroke_scale:.0f}" fill="#0b3d7a">External</text>'
    )
    parts.append(
        f'<text x="{tx(left_x) - 6 * stroke_scale:.2f}" y="{ty(int_y) + 4 * stroke_scale:.2f}" text-anchor="end" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{12 * stroke_scale:.0f}" fill="#0b3d7a">Internal</text>'
    )

    # Mesh sash (frontmost/internal) — dark wire line on its own mesh track
    mesh_y = int_y - band * (0.5 if n_levels <= 2 else 0.4)
    for s in meshes:
        x0, x1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
        parts.append(
            f'<line x1="{tx(x0):.2f}" y1="{ty(mesh_y):.2f}" x2="{tx(x1):.2f}" y2="{ty(mesh_y):.2f}" '
            f'stroke="#1a1a1a" {_solid_sw(2.0 * stroke_scale)}/>'
        )
        parts.append(
            f'<text x="{tx((x0 + x1) / 2):.2f}" y="{ty(mesh_y) - 3 * stroke_scale:.2f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="{9 * stroke_scale:.0f}" fill="#1a1a1a">MESH</text>'
        )

    # One offset track bar per glass sash: one line per track level
    for pos, s in enumerate(glass):
        x0, x1 = float(s.get("x0") or 0), float(s.get("x1") or 0)
        depth = int(s.get("depth") or 1)
        is_front = depth == dmin
        yy = _level_y(depth) if n_levels > 2 else (int_y if is_front else ext_y)
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
    """Accordion plan for Fold & Sliding - separate leaves with hinge/handle marks."""
    glass = [s for s in shutters if s.get("role") == "glass"]
    if not glass:
        return
    glass.sort(key=lambda s: float(s.get("nomX0") or 0))
    amp = plan_h * 0.30
    bounds = [float(glass[0].get("nomX0") or 0)] + [float(s.get("nomX1") or 0) for s in glass]
    pts = [(bounds[j], y_mid + (amp if j % 2 == 0 else -amp)) for j in range(len(bounds))]
    sw = max(0.95, 1.05 * stroke_scale)

    def _line_segment(a: tuple[float, float], b: tuple[float, float], gap_px: float = 3.0) -> tuple[float, float, float, float]:
        ax, ay = tx(a[0]), ty(a[1])
        bx, by = tx(b[0]), ty(b[1])
        dx, dy = bx - ax, by - ay
        ln = max((dx * dx + dy * dy) ** 0.5, 1.0)
        g = min(gap_px * stroke_scale, ln * 0.20)
        return ax + dx / ln * g, ay + dy / ln * g, bx - dx / ln * g, by - dy / ln * g

    # Draw every folded leaf as its own slim segment. Small gaps make the opening
    # points read as separate door leaves instead of one heavy joined polyline.
    for i, leaf in enumerate(glass):
        x1, y1, x2, y2 = _line_segment(pts[i], pts[i + 1])
        pack = str(leaf.get("pack") or "").upper()
        parts.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="#173a63" stroke-width="{sw:.2f}" stroke-linecap="round" data-role="fold-plan-leaf"/>'
        )
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        parts.append(
            f'<text x="{mx:.2f}" y="{my - 4 * stroke_scale:.2f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="{8 * stroke_scale:.0f}" fill="#0b3d7a">{pack}{i + 1}</text>'
        )

    # Hinge dots at real hinge vertices: inside a pack and at each outer pivot.
    for j, (x, y) in enumerate(pts):
        left = glass[j - 1] if 0 <= j - 1 < len(glass) else None
        right = glass[j] if 0 <= j < len(glass) else None
        left_pack = str((left or {}).get("pack") or "")
        right_pack = str((right or {}).get("pack") or "")
        is_outer = j == 0 or j == len(pts) - 1
        is_hinge = is_outer or (left_pack and left_pack == right_pack)
        if not is_hinge:
            continue
        parts.append(
            f'<circle cx="{tx(x):.2f}" cy="{ty(y):.2f}" r="{2.0 * stroke_scale:.2f}" fill="#ffffff" '
            f'stroke="#8b1e1a" stroke-width="{0.85 * stroke_scale:.2f}" data-role="fold-plan-hinge"/>'
        )

    # Handles at lead/meeting leaves. If a one-side folding pack is used, this
    # marks the pull stile on the end leaf.
    for i, leaf in enumerate(glass):
        side = str(leaf.get("handleSide") or "").lower()
        if side not in ("left", "right"):
            continue
        j = i if side == "left" else i + 1
        if not (0 <= j < len(pts)):
            continue
        x, y = pts[j]
        sx, sy = tx(x), ty(y)
        parts.append(
            f'<rect x="{sx - 3.2 * stroke_scale:.2f}" y="{sy - 9 * stroke_scale:.2f}" '
            f'width="{6.4 * stroke_scale:.2f}" height="{18 * stroke_scale:.2f}" rx="{2 * stroke_scale:.2f}" '
            f'fill="#ffffff" stroke="#111827" stroke-width="{0.95 * stroke_scale:.2f}" data-role="fold-plan-handle"/>'
        )
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy + 4.5 * stroke_scale:.2f}" r="{1.7 * stroke_scale:.2f}" '
            f'fill="none" stroke="#111827" stroke-width="{0.75 * stroke_scale:.2f}"/>'
        )

    # Fold-direction arrows per pack.
    fl = sum(1 for s in glass if str(s.get("pack") or "").upper() == "L")
    if fl > 0:
        lx = float(glass[0].get("nomX0") or 0)
        parts.append(
            f'<line x1="{tx(lx) + 26 * stroke_scale:.2f}" y1="{ty(y_mid):.2f}" x2="{tx(lx) + 2:.2f}" '
            f'y2="{ty(y_mid):.2f}" stroke="#0b3d7a" stroke-width="{1.05 * stroke_scale:.2f}" marker-end="url(#slideArrow)"/>'
        )
    if fl < len(glass):
        rx = float(glass[-1].get("nomX1") or W)
        parts.append(
            f'<line x1="{tx(rx) - 26 * stroke_scale:.2f}" y1="{ty(y_mid):.2f}" x2="{tx(rx) - 2:.2f}" '
            f'y2="{ty(y_mid):.2f}" stroke="#0b3d7a" stroke-width="{1.05 * stroke_scale:.2f}" marker-end="url(#slideArrow)"/>'
        )


def attach_top_shape_to_drawing(
    drawing: Any,
    *,
    top_shape: Any = None,
    curve_rise_mm: Any = None,
) -> None:
    """Stamp curved/flat top metadata onto a drawing for SVG elevation render."""
    if drawing is None:
        return
    meta = dict(getattr(drawing, "metadata", None) or {})
    shape = str(top_shape if top_shape is not None else meta.get("topShape") or "flat").strip().lower()
    if shape in ("curved", "curve", "arch", "arched", "bow"):
        meta["topShape"] = "curved"
        try:
            rise = float(curve_rise_mm if curve_rise_mm is not None else meta.get("curveRiseMm") or 0)
        except (TypeError, ValueError):
            rise = 0.0
        if rise <= 0:
            try:
                rise = max(80.0, float(getattr(drawing, "width", 0) or 0) * 0.12)
            except (TypeError, ValueError):
                rise = 120.0
        meta["curveRiseMm"] = round(rise, 1)
    else:
        meta["topShape"] = "flat"
        meta.pop("curveRiseMm", None)
    drawing.metadata = meta


def _curve_rise_from_meta(meta: Mapping[str, Any] | None, *, width: float) -> float:
    m = meta or {}
    shape = str(m.get("topShape") or "").strip().lower()
    if shape not in ("curved", "curve", "arch", "arched", "bow"):
        return 0.0
    try:
        rise = float(m.get("curveRiseMm") or 0)
    except (TypeError, ValueError):
        rise = 0.0
    if rise <= 0:
        rise = max(80.0, float(width or 0) * 0.12)
    return float(rise)


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

    curve_rise = _curve_rise_from_meta(model.metadata, width=float(model.width or 0))

    xs: list[float] = [0.0, model.width]
    ys: list[float] = [0.0, model.height]
    if curve_rise > 0:
        ys.append(float(model.height) + curve_rise)
    for pl in model.polylines:
        for p in pl.points:
            xs.append(p.x)
            ys.append(p.y)
    for seg in model.segments:
        xs.extend([seg.start.x, seg.end.x])
        ys.extend([seg.start.y, seg.end.y])

    _fix_pad = 0.0
    if annotations:
        _fs = _partition_split_sizes(model.metadata or {})
        if _fs["top"] > 0 or _fs["bottom"] > 0:
            _fix_pad = 75.0 * k  # room for the FIX / remaining split chain
    min_x = min(xs) - margin - (dim_pad if annotations else 0.0)
    max_x = max(xs) + margin + (40.0 * k if annotations else 0.0) + _fix_pad
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
    _style_meta = model.metadata or {}
    _style_system = str(_style_meta.get("system") or "").lower()
    if _style_system == "bifold":
        sw_outer = max(1.25, min(ref * 0.00145, 2.05))
        sw_inner = max(0.95, sw_outer * 0.68)
    else:
        sw_outer = max(2.00, min(ref * 0.0024, 3.40))
        sw_inner = max(1.55, sw_outer * 0.82)
    sw_profile = sw_inner
    sw_seg = sw_inner
    sw_grid = max(1.15, sw_inner * 0.72)
    sw_interlock = max(1.10, sw_outer * (0.72 if _style_system == "bifold" else 0.90))
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
    _title_bits = [f"{mm_n(model.width)}×{mm_n(model.height)}"]
    try:
        _tc0 = _meta0.get("track_count")
        if _sys0 == "sliding" and _tc0 not in (None, ""):
            _title_bits.append(f"{float(_tc0):g}-track")
    except (TypeError, ValueError):
        pass
    _op0 = str(_meta0.get("opening") or "").lower()
    if _sys0 == "sliding" and _op0:
        _title_bits.append("center opening" if _op0 in ("center", "centre") else "side opening")
    # Wider checks + slimmer stroke so wire mesh reads light, not a dark block.
    _mesh_cell = 24.0 * k
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
        '<path d="M0,0 L8,4 L0,8 Z" fill="#0b3d7a"/></marker>'
        # Wire mesh: open dark-grey cross-hatch (print-safe). Wider spacing + thin
        # stroke keeps the pane readable instead of a filled charcoal block.
        f'<pattern id="meshWire" patternUnits="userSpaceOnUse" width="{_mesh_cell:.2f}" height="{_mesh_cell:.2f}">'
        f'<path d="M0,0 L{_mesh_cell:.2f},{_mesh_cell:.2f} M{_mesh_cell:.2f},0 L0,{_mesh_cell:.2f}" '
        f'stroke="#2a2a2a" stroke-width="{max(0.28, 0.32 * k):.2f}" stroke-opacity="0.55"/></pattern>'
        # Pleated / rolling mesh add-on: fine dot grid (lighter than the wire
        # sash). Filled dots, not a dashed stroke — RIP/svglib stipple-safe.
        f'<pattern id="meshPleat" patternUnits="userSpaceOnUse" width="{_mesh_cell * 1.6:.2f}" height="{_mesh_cell * 1.6:.2f}">'
        f'<circle cx="{_mesh_cell * 0.8:.2f}" cy="{_mesh_cell * 0.8:.2f}" r="{max(0.6, 0.7 * k):.2f}" fill="#2b2b2b" fill-opacity="0.7"/>'
        f'<circle cx="0" cy="0" r="{max(0.6, 0.7 * k):.2f}" fill="#2b2b2b" fill-opacity="0.7"/></pattern>'
        "</defs>",
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

    # Glass lites fully under a mesh sash are omitted here — mesh plate + hatch
    # own that bay (avoids glass edge/mitre stubs showing through mesh corners).
    _mesh_cover: list[tuple[float, float, float, float]] = []
    for pl in model.polylines:
        nm = (pl.name or "").lower()
        if not (nm.startswith("mesh_") and nm.endswith("_outer")):
            continue
        bb = _polyline_bbox(pl)
        if bb:
            _mesh_cover.append(bb)

    def _glass_under_mesh(gx0: float, gy0: float, gx1: float, gy1: float, *, eps: float = 1.0) -> bool:
        for mx0, my0, mx1, my1 in _mesh_cover:
            if gx0 >= mx0 - eps and gx1 <= mx1 + eps and gy0 >= my0 - eps and gy1 <= my1 + eps:
                return True
        return False

    glasses_early = _glass_panels(model)
    if panel_fill:
        for _name, gx0, gy0, gx1, gy1 in glasses_early:
            if _glass_under_mesh(gx0, gy0, gx1, gy1):
                continue
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
            bb = _polyline_bbox(pl)
            if bb and _glass_under_mesh(*bb):
                continue
            pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
            parts.append(
                f'<polygon points="{pts}" fill="{glass_fill}" stroke="{glass_stroke}" '
                f'{_solid_sw(sw_profile * 0.85)}/>'
            )

    def _is_mesh_frame(name: str) -> bool:
        nm = (name or "").lower()
        return nm.startswith("mesh_") and "net" not in nm

    for pl in model.polylines:
        if pl.layer in ("GLASS", "HARDWARE", "MESH") or len(pl.points) < 2:
            continue
        # Mesh sash frame is stroked after the clipped hatch so the profile
        # outline sits cleanly on top (same as glass: fill inside, frame above).
        if _is_mesh_frame(pl.name or ""):
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

    # Curved / arched top: lunette glass + outer/inner arcs above the rectangular head.
    if curve_rise > 0:
        W = float(model.width or 0)
        H = float(model.height or 0)
        # Quadratic peak = H+rise ⇒ control point at H + 2*rise
        ctrl_y = H + (2.0 * curve_rise)
        parts.append(
            f'<path d="M {tx(0):.2f},{ty(H):.2f} Q {tx(W * 0.5):.2f},{ty(ctrl_y):.2f} '
            f'{tx(W):.2f},{ty(H):.2f} Z" fill="{glass_fill}" stroke="none"/>'
        )
        parts.append(
            f'<path d="M {tx(0):.2f},{ty(H):.2f} Q {tx(W * 0.5):.2f},{ty(ctrl_y):.2f} '
            f'{tx(W):.2f},{ty(H):.2f}" fill="none" stroke="{frame_stroke}" {_solid_sw(sw_outer)}/>'
        )
        inset = max(18.0 * k, sw_outer * 4.0)
        rise_inner = max(curve_rise - inset * 0.55, curve_rise * 0.72)
        ctrl_inner = H + (2.0 * rise_inner)
        parts.append(
            f'<path d="M {tx(inset):.2f},{ty(H):.2f} Q {tx(W * 0.5):.2f},{ty(ctrl_inner):.2f} '
            f'{tx(W - inset):.2f},{ty(H):.2f}" fill="none" stroke="{frame_stroke}" {_solid_sw(sw_inner)}/>'
        )

    for seg in model.segments:
        lname = (seg.name or "").lower()
        if lname.startswith("mesh_"):
            continue  # mesh miters redrawn on top of the hatch
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

    # Wire mesh sashes — opaque plate + hatch + outer/inner/45° miters on top so
    # rear glass corners cannot show through (XX / inverted cut / inner stubs).
    mesh_nets: list[tuple[str, float, float, float, float]] = []
    mesh_net_pls: list[Polyline] = []
    for pl in model.polylines:
        if pl.layer != "MESH" or len(pl.points) < 2:
            continue
        bb = _polyline_bbox(pl)
        if not bb:
            continue
        mesh_nets.append((pl.name or f"mesh_{len(mesh_nets)+1}", *bb))
        mesh_net_pls.append(pl)
    if mesh_net_pls:
        # Opaque sash plate (covers any glass outer/inner still under the mesh bay).
        for pl in model.polylines:
            nm = (pl.name or "").lower()
            if not (nm.startswith("mesh_") and nm.endswith("_outer")) or len(pl.points) < 2:
                continue
            pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
            parts.append(
                f'<polygon points="{pts}" fill="{bg}" stroke="none" data-mesh-plate="1"/>'
            )
        parts.append("<defs>")
        for i, pl in enumerate(mesh_net_pls):
            pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
            parts.append(f'<clipPath id="meshClip{i}"><polygon points="{pts}"/></clipPath>')
        parts.append("</defs>")
        for i, pl in enumerate(mesh_net_pls):
            # Slight inset so hatch wires do not collide with the 45° mitre tip
            # (avoids an "inverted diagonal" look at the inner corner).
            bb = _polyline_bbox(pl)
            if bb:
                hx0, hy0, hx1, hy1 = bb
                inset = min(1.5, max(0.0, (hx1 - hx0) * 0.01), max(0.0, (hy1 - hy0) * 0.01))
                hx0, hy0, hx1, hy1 = hx0 + inset, hy0 + inset, hx1 - inset, hy1 - inset
                pts = (
                    f"{tx(hx0):.2f},{ty(hy0):.2f} {tx(hx1):.2f},{ty(hy0):.2f} "
                    f"{tx(hx1):.2f},{ty(hy1):.2f} {tx(hx0):.2f},{ty(hy1):.2f}"
                )
            else:
                pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
            parts.append(
                f'<g clip-path="url(#meshClip{i})">'
                f'<polygon points="{pts}" fill="url(#meshWire)" stroke="none" data-mesh="wire"/>'
                f"</g>"
            )
        # Outer then inner profile (glass-identical), then 45° miters.
        for pl in model.polylines:
            if not _is_mesh_frame(pl.name or "") or len(pl.points) < 2:
                continue
            pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
            if pl.closed:
                parts.append(
                    f'<polygon points="{pts}" fill="none" stroke="{frame_stroke}" {_solid_sw(sw_inner)}/>'
                )
            else:
                parts.append(
                    f'<polyline points="{pts}" fill="none" stroke="{frame_stroke}" {_solid_sw(sw_inner * 0.9)}/>'
                )
        for seg in model.segments:
            if not (seg.name or "").lower().startswith("mesh_"):
                continue
            parts.append(
                f'<line x1="{tx(seg.start.x):.2f}" y1="{ty(seg.start.y):.2f}" '
                f'x2="{tx(seg.end.x):.2f}" y2="{ty(seg.end.y):.2f}" '
                f'stroke="{frame_stroke}" {_solid_sw(sw_seg)}/>'
            )

    # Pleated / rolling mesh add-on — dotted grid over the chosen placement.
    _addon = meta.get("mesh_addon") if isinstance(meta.get("mesh_addon"), Mapping) else None
    if _addon:
        try:
            ax0, ay0, ax1, ay1 = (float(_addon["x0"]), float(_addon["y0"]), float(_addon["x1"]), float(_addon["y1"]))
        except (KeyError, TypeError, ValueError):
            ax0 = ay0 = ax1 = ay1 = 0.0
        if ax1 > ax0 and ay1 > ay0:
            parts.append(
                f'<rect x="{tx(ax0):.2f}" y="{ty(ay1):.2f}" width="{tx(ax1) - tx(ax0):.2f}" height="{ty(ay0) - ty(ay1):.2f}" '
                f'fill="url(#meshPleat)" stroke="#2b2b2b" stroke-dasharray="{6 * k:.1f} {4 * k:.1f}" '
                f'{_solid_sw(max(0.9, sw_inner * 0.6))} data-mesh="{escape(str(_addon.get("type") or "addon"))}"/>'
            )
            if annotations:
                _lab = f"{str(_addon.get('type') or 'MESH').upper()} MESH {mm_n(_addon.get('widthMm') or 0)}×{mm_n(_addon.get('heightMm') or 0)}"
                parts.append(
                    f'<text x="{tx((ax0 + ax1) / 2):.2f}" y="{ty(ay1) + 30 * k:.2f}" text-anchor="middle" '
                    f'font-family="Segoe UI, Arial, sans-serif" font-size="{22 * k:.0f}" font-weight="700" fill="#1f1f1f">'
                    f"{escape(_lab)}</text>"
                )

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

        # Mesh sash labels (M1, M2 …) — wire mesh on the front track
        for mi, (_mn, mx0, my0, mx1, my1) in enumerate(mesh_nets):
            mcx = (mx0 + mx1) / 2.0
            mcy = my0 + (my1 - my0) * 0.12
            chip_w, chip_h = 110 * k, 36 * k
            parts.append(
                f'<rect x="{tx(mcx) - chip_w / 2:.2f}" y="{ty(mcy) - chip_h / 2:.2f}" '
                f'width="{chip_w:.2f}" height="{chip_h:.2f}" rx="{3 * k:.1f}" fill="#fff" fill-opacity="0.95" '
                f'stroke="#333" stroke-width="{max(0.55, min(0.40 * k, 0.90)):.2f}"/>'
            )
            parts.append(
                f'<text x="{tx(mcx):.2f}" y="{ty(mcy) + label_font * 0.32:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{label_font * 0.85:.0f}" font-weight="700" fill="#111">'
                f"M{mi + 1} MESH</text>"
            )

        W = float(model.width)
        H = float(model.height)
        _dim_line_v(
            parts, tx=tx, ty=ty, y0=0.0, y1=H, x=-55.0 * k, text=str(mm_n(H)),
            text_x=-82.0 * k, stroke=dim_stroke, font=dim_font,
        )
        _dim_line_h(
            parts, tx=tx, ty=ty, x0=0.0, x1=W, y=-95.0 * k, text=str(mm_n(W)),
            text_y=-122.0 * k, stroke=dim_stroke, font=dim_font,
        )
        # Per-panel / per-shutter divided widths along the bottom (whole mm).
        # Sliding: nominal shutter shares. Casement: bay chain for FIX + openable.
        # Glass / daylight (sash-inner) sizes stay omitted.
        for nx0, nx1 in _panel_width_dim_spans(meta, W):
            _dim_line_h(
                parts, tx=tx, ty=ty, x0=nx0, x1=nx1, y=-42.0 * k,
                text=str(mm_n(nx1 - nx0)), text_y=-64.0 * k, stroke=dim_stroke, font=dim_font * 0.82,
            )
        # Fix partition dims — "how much fix, how much left": a split chain that
        # adds up to the overall size (FIX n + remaining shutter / door share).
        # Glass / daylight (sash-inner) width & height are intentionally omitted.
        _fix_sizes = _partition_split_sizes(meta)
        _has_v_fix = (_fix_sizes["top"] > 0 or _fix_sizes["bottom"] > 0)
        if _has_v_fix:
            _xv = W + 48.0 * k
            _xt = _xv + 30.0 * k
            for (ya, yb, txt) in _vertical_split_chain(H, _fix_sizes["top"], _fix_sizes["bottom"]):
                _dim_line_v(
                    parts, tx=tx, ty=ty, y0=ya, y1=yb, x=_xv, text=txt, text_x=_xt,
                    stroke=dim_stroke, font=dim_font * 0.75,
                )
        if _fix_sizes["left"] > 0 or _fix_sizes["right"] > 0:
            _yh = H + 40.0 * k
            for (xa, xb, txt) in _horizontal_split_chain(W, _fix_sizes["left"], _fix_sizes["right"]):
                _dim_line_h(
                    parts, tx=tx, ty=ty, x0=xa, x1=xb, y=_yh, text=txt, text_y=_yh + 28.0 * k,
                    stroke=dim_stroke, font=dim_font * 0.75,
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
        from WEOS.factory.svg_export import attach_top_shape_to_drawing

        attach_top_shape_to_drawing(
            job.drawing,
            top_shape=lo.get("topShape") or line.get("topShape"),
            curve_rise_mm=lo.get("curveRiseMm") or line.get("curveRiseMm"),
        )
        try:
            from WEOS.factory.mesh_addon import attach_mesh_addon_to_drawing, mesh_addon_for_line

            attach_mesh_addon_to_drawing(job.drawing, mesh_addon_for_line(line))
        except Exception:
            pass
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
                "label": f"Fix ({side})" if side else "Fix",
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
                pack = str(s.get("pack") or "").strip().lower()
                hs_top = str(s.get("hingeSide") or "").lower() == "top" or hs == "bottom" or pack == "top_hung"
                if pack == "sliding" or (fixed and pack == "sliding"):
                    role, label, pid = "fix", "Sliding (fixed lite)", f"S{s_idx}"
                elif fixed:
                    role, label, pid = "fix", "Fix", f"S{s_idx}"
                elif hs_top:
                    role, label, pid = "openable", "Top hung · handle bottom", f"S{s_idx}"
                elif pack == "door":
                    side_lbl = "L" if hs == "left" else ("R" if hs == "right" else "—")
                    role, label, pid = "openable", f"Door · handle {side_lbl}", f"S{s_idx}"
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
