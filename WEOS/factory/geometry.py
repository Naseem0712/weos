"""Pure geometry helpers used by all product generators."""

from __future__ import annotations

from typing import Sequence

from WEOS.factory.types import Point, Polyline, Rect, Segment


def rect_polyline(rect: Rect, *, closed: bool = True, layer: str = "0", name: str = "") -> Polyline:
    return Polyline(
        (
            Point(rect.x0, rect.y0),
            Point(rect.x1, rect.y0),
            Point(rect.x1, rect.y1),
            Point(rect.x0, rect.y1),
        ),
        closed=closed,
        layer=layer,
        name=name,
    )


def inset_rect(rect: Rect, left: float, bottom: float, right: float, top: float) -> Rect:
    return rect.inset(left, bottom, right, top)


def frame_miter_segments(
    outer: Rect,
    inner: Rect,
    *,
    layer: str = "0",
    name_prefix: str = "miter",
) -> list[Segment]:
    """
    Draw 45° miters at the four corners between an outer and inner frame rectangle.
    Each miter connects the corresponding outer/inner corner.
    """
    corners = [
        (Point(outer.x0, outer.y0), Point(inner.x0, inner.y0), "bl"),
        (Point(outer.x1, outer.y0), Point(inner.x1, inner.y0), "br"),
        (Point(outer.x1, outer.y1), Point(inner.x1, inner.y1), "tr"),
        (Point(outer.x0, outer.y1), Point(inner.x0, inner.y1), "tl"),
    ]
    return [
        Segment(o, i, layer=layer, name=f"{name_prefix}_{tag}")
        for o, i, tag in corners
    ]


def u_polyline_open_right(rect: Rect, *, layer: str = "0", name: str = "") -> Polyline:
    """Open polyline along top-left-bottom (open on the right) — useful for meeting stiles."""
    return Polyline(
        (
            Point(rect.x1, rect.y1),
            Point(rect.x0, rect.y1),
            Point(rect.x0, rect.y0),
            Point(rect.x1, rect.y0),
        ),
        closed=False,
        layer=layer,
        name=name,
    )


def u_polyline_open_left(rect: Rect, *, layer: str = "0", name: str = "") -> Polyline:
    """Open polyline along bottom-right-top (open on the left)."""
    return Polyline(
        (
            Point(rect.x0, rect.y0),
            Point(rect.x1, rect.y0),
            Point(rect.x1, rect.y1),
            Point(rect.x0, rect.y1),
        ),
        closed=False,
        layer=layer,
        name=name,
    )


def vertical_segment(x: float, y0: float, y1: float, *, layer: str = "0", name: str = "") -> Segment:
    return Segment(Point(x, y0), Point(x, y1), layer=layer, name=name)


def horizontal_segment(y: float, x0: float, x1: float, *, layer: str = "0", name: str = "") -> Segment:
    return Segment(Point(x0, y), Point(x1, y), layer=layer, name=name)


def subtract_intervals(
    start: float,
    end: float,
    cuts: Sequence[tuple[float, float]],
    *,
    min_len: float = 0.6,
) -> list[tuple[float, float]]:
    """Keep [start, end] minus each cut interval — used to hide back edges under overlap."""
    if end <= start:
        return []
    segs: list[tuple[float, float]] = [(float(start), float(end))]
    for raw0, raw1 in cuts or ():
        a, b = (float(raw0), float(raw1)) if raw0 <= raw1 else (float(raw1), float(raw0))
        nxt: list[tuple[float, float]] = []
        for s0, s1 in segs:
            if b <= s0 or a >= s1:
                nxt.append((s0, s1))
                continue
            if a > s0:
                nxt.append((s0, min(a, s1)))
            if b < s1:
                nxt.append((max(b, s0), s1))
        segs = nxt
    return [(a, b) for a, b in segs if (b - a) >= min_len]


def hinge_centers_mm(leaf_h_mm: float, count: int = 3) -> list[float]:
    """Casement hinge cy from top of leaf (mm): 100 from top/bottom; extras stacked then mid-span."""
    count = min(max(int(count), 2), 6)
    h = max(float(leaf_h_mm), 240.0)
    top = 100.0 if h >= 280.0 else min(100.0, h * 0.16)
    bot = (h - 100.0) if h >= 280.0 else max(h - 100.0, h * 0.84)
    if bot <= top + 30.0:
        top, bot = h * 0.18, h * 0.82
    if count == 2:
        return [top, bot]
    if count == 3:
        return [top, (top + bot) / 2.0, bot]
    stack = min(48.0, max(28.0, (bot - top) * 0.08))
    top_b = top + stack
    extra = count - 3
    mids = [top_b + (bot - top_b) * i / (extra + 1) for i in range(1, extra + 1)]
    return [top, top_b, *mids, bot]


# Sleek 2D casement hinge — light capsule + slight diagonal (two leaves).
HINGE_FILL = "#f3f2ee"
HINGE_FILL_RGB = (0.953, 0.949, 0.933)
HINGE_STROKE = "#1a1a1a"


def casement_hinge_svg(
    cx: float,
    cy: float,
    *,
    w: float,
    h: float,
    stroke: str = HINGE_STROKE,
    stroke_width: float = 0.75,
    extra_attrs: str = "",
) -> str:
    """Tall/wide rounded capsule with a thin outline and a slight mid diagonal.

    ``(cx, cy)`` is the hinge centre in the same SVG space as ``w`` / ``h``.
    Place that centre on the outer-frame | sash gap so the split reads as two leaves.
    """
    ww = max(float(w), 0.8)
    hh = max(float(h), 0.8)
    x = float(cx) - ww / 2.0
    y = float(cy) - hh / 2.0
    rx = min(ww, hh) * 0.49
    dx = ww * 0.28
    dy = hh * 0.20
    extra = f" {extra_attrs.strip()}" if extra_attrs and extra_attrs.strip() else ""
    sw = max(float(stroke_width), 0.35)
    return (
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{ww:.2f}" height="{hh:.2f}" '
        f'rx="{rx:.2f}" fill="{HINGE_FILL}" stroke="{stroke}" stroke-width="{sw:.2f}" '
        f'data-hinge="1"{extra}/>'
        f'<line x1="{float(cx) - dx:.2f}" y1="{float(cy) - dy:.2f}" '
        f'x2="{float(cx) + dx:.2f}" y2="{float(cy) + dy:.2f}" '
        f'stroke="{stroke}" stroke-width="{max(sw * 0.65, 0.35):.2f}"/>'
    )

