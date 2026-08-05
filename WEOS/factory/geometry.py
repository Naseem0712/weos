"""Pure geometry helpers used by all product generators."""

from __future__ import annotations

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

