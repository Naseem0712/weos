"""
Geometry Engine — sliding layout from named profile geometry rules.

Supports optional fix partitions (top/bottom/left/right) and mesh track count.
Coordinates are never hardcoded; every inset/width comes from profile JSON geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from WEOS.factory.dimensioning import (
    DimStyleParams,
    dim_offset_above,
    dim_offset_below,
    dim_offset_left,
    dim_offset_right,
    horizontal_dim,
    vertical_dim,
)
from WEOS.factory.geometry import (
    frame_miter_segments,
    rect_polyline,
    u_polyline_open_left,
    u_polyline_open_right,
    vertical_segment,
)
from WEOS.factory.layout_options import normalize_partitions, partition_sizes
from WEOS.factory.types import DrawingModel, Point, Rect, Segment


@dataclass(frozen=True, slots=True)
class FixPanel:
    side: str
    size_mm: float
    role: str
    outer: Rect
    glass: Rect


@dataclass(frozen=True, slots=True)
class SlidingLayout:
    W: float
    H: float
    track_width: float
    frame_width: float
    interlock_width: float
    overlap: float
    glass_clip: float
    track: Rect
    interlock_left: float
    interlock_right: float
    shutter_inset: float
    left_shutter: Rect
    right_shutter: Rect
    left_glass: Rect
    right_glass: Rect
    left_clip: Rect
    right_clip: Rect
    fix_panels: tuple[FixPanel, ...] = ()
    mullions: tuple[Rect, ...] = ()
    mesh: bool = False
    track_count: float = 2.0
    sliding_area: Rect | None = None

    @property
    def left_shutter_width(self) -> float:
        return self.left_shutter.width

    @property
    def right_shutter_width(self) -> float:
        return self.right_shutter.width

    @property
    def left_glass_width(self) -> float:
        return self.left_glass.width

    @property
    def right_glass_width(self) -> float:
        return self.right_glass.width

    @property
    def glass_height(self) -> float:
        return self.left_glass.height

    def meta(self) -> dict[str, Any]:
        sliding = self.sliding_area or Rect(
            self.left_shutter.x0,
            self.left_shutter.y0,
            self.right_shutter.x1,
            self.left_shutter.y1,
        )
        return {
            "left_shutter_width": self.left_shutter_width,
            "right_shutter_width": self.right_shutter_width,
            "left_glass_width": self.left_glass_width,
            "right_glass_width": self.right_glass_width,
            "glass_height": self.glass_height,
            "interlock_left": self.interlock_left,
            "interlock_right": self.interlock_right,
            "shutter_inset": self.shutter_inset,
            "clear_opening_left": self.interlock_left - self.track.x0,
            "clear_opening_right": self.track.x1 - self.interlock_right,
            "mesh": self.mesh,
            "track_count": float(self.track_count),
            "sliding_width": sliding.width,
            "sliding_height": sliding.height,
            "sliding_x0": sliding.x0,
            "sliding_y0": sliding.y0,
            "sliding_x1": sliding.x1,
            "sliding_y1": sliding.y1,
            "partitions": [
                {
                    "side": fp.side,
                    "sizeMm": fp.size_mm,
                    "role": fp.role,
                    "widthMm": round(fp.outer.width, 1),
                    "heightMm": round(fp.outer.height, 1),
                    "glassWidthMm": round(fp.glass.width, 1),
                    "glassHeightMm": round(fp.glass.height, 1),
                }
                for fp in self.fix_panels
            ],
        }


def dim_style_from_profile(dimensioning: Mapping[str, Any]) -> DimStyleParams:
    """Dimension presentation — all values from profile JSON dimensioning section."""
    d = dimensioning or {}
    required = ("arrowSize", "textHeight", "offsetOuter", "offsetInner", "offsetDetail", "stackGap")
    missing = [k for k in required if k not in d]
    if missing:
        raise KeyError(f"profile.dimensioning missing keys: {', '.join(missing)}")
    return DimStyleParams(
        arrow_size=float(d["arrowSize"]),
        text_height=float(d["textHeight"]),
        offset_outer=float(d["offsetOuter"]),
        offset_inner=float(d["offsetInner"]),
        offset_detail=float(d["offsetDetail"]),
        stack_gap=float(d["stackGap"]),
    )


def compute_two_track_layout(
    width: float,
    height: float,
    geometry: Mapping[str, Any],
    *,
    partitions: Sequence[Mapping[str, Any]] | None = None,
    mesh: bool = False,
    track_count: float | None = None,
) -> SlidingLayout:
    """Core sliding formulas from profile geometry + optional fix partitions / mesh."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    tw = float(geometry["trackWidth"])
    fw = float(geometry["frameWidth"])
    iw = float(geometry["interlockWidth"])
    ov = float(geometry["overlap"])
    gc = float(geometry["glassClip"])

    if tw <= 0 or fw <= 0 or iw <= 0:
        raise ValueError("profile widths must be positive")
    if ov < 0 or ov >= tw:
        raise ValueError("overlap must be in [0, trackWidth)")
    if gc < 0:
        raise ValueError("glassClip must be >= 0")

    W, H = float(width), float(height)
    shutter_inset = tw - ov
    track = Rect(tw, tw, W - tw, H - tw)

    parts = normalize_partitions(partitions)
    sizes = partition_sizes(parts)
    top_fix = sizes["top"]
    bot_fix = sizes["bottom"]
    left_fix = sizes["left"]
    right_fix = sizes["right"]

    # Sliding band inside outer track, after carving fix panels + mullions
    mullion = fw
    slide_x0 = track.x0 + (left_fix + mullion if left_fix > 0 else 0.0)
    slide_x1 = track.x1 - (right_fix + mullion if right_fix > 0 else 0.0)
    slide_y0 = track.y0 + (bot_fix + mullion if bot_fix > 0 else 0.0)
    slide_y1 = track.y1 - (top_fix + mullion if top_fix > 0 else 0.0)
    if slide_x1 - slide_x0 < fw * 2 or slide_y1 - slide_y0 < fw * 2:
        raise ValueError("partition sizes leave too little room for sliding sashes")

    sliding_area = Rect(slide_x0, slide_y0, slide_x1, slide_y1)
    cx = (slide_x0 + slide_x1) / 2.0
    il = cx - iw / 2.0
    ir = cx + iw / 2.0

    # Shutters sit on the sliding band (inset already applied via track carve)
    left_shutter = Rect(slide_x0, slide_y0, il, slide_y1)
    right_shutter = Rect(il, slide_y0, slide_x1, slide_y1)

    left_glass = Rect(
        left_shutter.x0 + fw,
        left_shutter.y0 + fw,
        left_shutter.x1,
        left_shutter.y1 - fw,
    )
    right_glass = Rect(
        ir,
        right_shutter.y0 + fw,
        right_shutter.x1 - fw,
        right_shutter.y1 - fw,
    )
    left_clip = Rect(
        left_glass.x0 - gc,
        left_glass.y0 - gc,
        left_glass.x1,
        left_glass.y1 + gc,
    )
    right_clip = Rect(
        right_glass.x0,
        right_glass.y0 - gc,
        right_glass.x1 + gc,
        right_glass.y1 + gc,
    )

    fix_panels: list[FixPanel] = []
    mullions: list[Rect] = []

    if top_fix > 0:
        outer = Rect(track.x0, track.y1 - top_fix, track.x1, track.y1)
        glass = outer.inset_uniform(fw * 0.55)
        fix_panels.append(FixPanel("top", top_fix, "fix", outer, glass))
        mullions.append(Rect(track.x0, slide_y1, track.x1, track.y1 - top_fix))
    if bot_fix > 0:
        outer = Rect(track.x0, track.y0, track.x1, track.y0 + bot_fix)
        glass = outer.inset_uniform(fw * 0.55)
        fix_panels.append(FixPanel("bottom", bot_fix, "fix", outer, glass))
        mullions.append(Rect(track.x0, track.y0 + bot_fix, track.x1, slide_y0))
    if left_fix > 0:
        # Left fix spans sliding height (between top/bottom mullions)
        outer = Rect(track.x0, slide_y0, track.x0 + left_fix, slide_y1)
        glass = outer.inset_uniform(fw * 0.55)
        fix_panels.append(FixPanel("left", left_fix, "fix", outer, glass))
        mullions.append(Rect(track.x0 + left_fix, slide_y0, slide_x0, slide_y1))
    if right_fix > 0:
        outer = Rect(track.x1 - right_fix, slide_y0, track.x1, slide_y1)
        glass = outer.inset_uniform(fw * 0.55)
        fix_panels.append(FixPanel("right", right_fix, "fix", outer, glass))
        mullions.append(Rect(slide_x1, slide_y0, track.x1 - right_fix, slide_y1))

    tc = float(track_count) if track_count is not None else float(geometry.get("trackCount") or 2)
    if mesh and tc < 2.5:
        tc = 3.0

    return SlidingLayout(
        W=W,
        H=H,
        track_width=tw,
        frame_width=fw,
        interlock_width=iw,
        overlap=ov,
        glass_clip=gc,
        track=track,
        interlock_left=il,
        interlock_right=ir,
        shutter_inset=shutter_inset,
        left_shutter=left_shutter,
        right_shutter=right_shutter,
        left_glass=left_glass,
        right_glass=right_glass,
        left_clip=left_clip,
        right_clip=right_clip,
        fix_panels=tuple(fix_panels),
        mullions=tuple(mullions),
        mesh=bool(mesh),
        track_count=tc,
        sliding_area=sliding_area,
    )


def build_drawing(
    layout: SlidingLayout,
    *,
    product_name: str,
    parameters: dict[str, float],
    style: DimStyleParams,
) -> DrawingModel:
    """Geometry + Dimension engines → DrawingModel."""
    L = layout
    model = DrawingModel(
        product_type=product_name,
        width=L.W,
        height=L.H,
        parameters=parameters,
        metadata=L.meta(),
    )
    _build_profiles(model, L)
    _build_dimensions(model, L, style)
    return model


def _build_profiles(model: DrawingModel, L: SlidingLayout) -> None:
    outer = Rect(0.0, 0.0, L.W, L.H)
    model.add_polyline(rect_polyline(outer, closed=True, layer="PROFILES", name="outer_frame"))
    model.add_polyline(rect_polyline(L.track, closed=True, layer="Defpoints", name="track_inner"))

    # Fix panels + mullions (clear linework, no fills)
    for i, fp in enumerate(L.fix_panels):
        model.add_polyline(rect_polyline(fp.outer, closed=True, layer="PROFILES", name=f"fix_{fp.side}_outer"))
        model.add_polyline(rect_polyline(fp.glass, closed=True, layer="GLASS", name=f"fix_{fp.side}_glass"))
        # Corner ticks so fix reads as framed lite
        g, o = fp.glass, fp.outer
        for name, p0, p1 in (
            (f"fix_{fp.side}_miter_bl", Point(o.x0, o.y0), Point(g.x0, g.y0)),
            (f"fix_{fp.side}_miter_br", Point(o.x1, o.y0), Point(g.x1, g.y0)),
            (f"fix_{fp.side}_miter_tr", Point(o.x1, o.y1), Point(g.x1, g.y1)),
            (f"fix_{fp.side}_miter_tl", Point(o.x0, o.y1), Point(g.x0, g.y1)),
        ):
            model.add_segment(Segment(p0, p1, layer="PROFILES", name=name))

    for i, m in enumerate(L.mullions):
        model.add_polyline(rect_polyline(m, closed=True, layer="PROFILES", name=f"mullion_{i+1}"))

    model.add_polyline(u_polyline_open_right(L.left_shutter, layer="PROFILES", name="left_shutter_outer"))
    model.add_polyline(u_polyline_open_left(L.right_shutter, layer="PROFILES", name="right_shutter_outer"))
    model.add_segment(
        vertical_segment(L.interlock_left, L.right_shutter.y0, L.right_shutter.y1, layer="PROFILES", name="interlock_left")
    )
    model.add_segment(
        vertical_segment(L.interlock_right, L.right_shutter.y0, L.right_shutter.y1, layer="PROFILES", name="interlock_right")
    )
    # Meeting highlight — second pass so interlock reads clearly
    model.add_segment(
        Segment(
            Point((L.interlock_left + L.interlock_right) / 2.0, L.left_shutter.y0),
            Point((L.interlock_left + L.interlock_right) / 2.0, L.left_shutter.y1),
            layer="PROFILES",
            name="interlock_center",
        )
    )
    model.add_polyline(rect_polyline(L.left_glass, closed=True, layer="GLASS", name="left_glass"))
    model.add_polyline(rect_polyline(L.right_glass, closed=True, layer="GLASS", name="right_glass"))
    model.add_polyline(rect_polyline(L.left_clip, closed=False, layer="PROFILES", name="left_clip"))
    model.add_polyline(rect_polyline(L.right_clip, closed=False, layer="PROFILES", name="right_clip"))
    model.extend_segments(frame_miter_segments(outer, L.track, layer="PROFILES", name_prefix="track_miter"))
    for name, p0, p1 in (
        ("left_miter_bl", Point(L.left_shutter.x0, L.left_shutter.y0), Point(L.left_glass.x0, L.left_glass.y0)),
        ("left_miter_tl", Point(L.left_shutter.x0, L.left_shutter.y1), Point(L.left_glass.x0, L.left_glass.y1)),
        ("right_miter_br", Point(L.right_shutter.x1, L.right_shutter.y0), Point(L.right_glass.x1, L.right_glass.y0)),
        ("right_miter_tr", Point(L.right_shutter.x1, L.right_shutter.y1), Point(L.right_glass.x1, L.right_glass.y1)),
        ("right_clip_miter_tr", Point(L.track.x1, L.track.y1), Point(L.right_clip.x1, L.right_clip.y1)),
    ):
        model.add_segment(Segment(p0, p1, layer="PROFILES", name=name))

    tick = L.glass_clip
    for x, y, name in (
        (L.interlock_right, L.right_clip.y0, "tick_br_bot"),
        (L.interlock_right, L.right_clip.y1 - tick, "tick_br_top"),
        (L.right_glass.x1, L.right_clip.y0, "tick_rr_bot"),
        (L.right_glass.x1, L.right_clip.y1 - tick, "tick_rr_top"),
    ):
        model.add_segment(Segment(Point(x, y), Point(x, y + tick), layer="PROFILES", name=name))


def _build_dimensions(model: DrawingModel, L: SlidingLayout, style: DimStyleParams) -> None:
    W, H = L.W, L.H
    mid_y = (L.left_shutter.y0 + L.left_shutter.y1) / 2.0
    cx = (L.left_shutter.x0 + L.right_shutter.x1) / 2.0
    top_y = L.left_shutter.y1

    model.add_dimension(horizontal_dim(0.0, W, 0.0, text_y=dim_offset_below(0.0, style, 0), name="overall_width", layer="DIMS"))
    model.add_dimension(vertical_dim(0.0, H, 0.0, text_x=dim_offset_left(0.0, style, 0), name="overall_height", layer="DIMS"))
    model.add_dimension(
        horizontal_dim(L.left_shutter.x0, cx, top_y, text_y=dim_offset_above(H, style, 0), name="left_shutter_to_center", layer="DIMS")
    )
    model.add_dimension(
        horizontal_dim(cx, L.right_shutter.x1, top_y, text_y=dim_offset_above(H, style, 0), name="right_shutter_to_center", layer="DIMS")
    )
    model.add_dimension(
        horizontal_dim(L.left_shutter.x0, L.interlock_left, mid_y, text_y=mid_y + style.offset_inner, name="left_clear_width", layer="DIMS")
    )
    model.add_dimension(
        horizontal_dim(L.interlock_right, L.right_shutter.x1, mid_y, text_y=mid_y + style.offset_inner, name="right_clear_width", layer="DIMS")
    )
    model.add_dimension(
        vertical_dim(L.left_glass.y0, L.left_glass.y1, L.right_shutter.x1, text_x=dim_offset_right(W, style, 0), name="glass_height", layer="DIMS")
    )
    # Fix partition height/width callouts
    for fp in L.fix_panels:
        if fp.side in ("top", "bottom"):
            model.add_dimension(
                vertical_dim(
                    fp.outer.y0, fp.outer.y1, W,
                    text_x=dim_offset_right(W, style, 1),
                    name=f"fix_{fp.side}_height",
                    layer="DIMS",
                )
            )
        else:
            model.add_dimension(
                horizontal_dim(
                    fp.outer.x0, fp.outer.x1, fp.outer.y0,
                    text_y=dim_offset_below(fp.outer.y0, style, 0),
                    name=f"fix_{fp.side}_width",
                    layer="DIMS",
                )
            )
    model.add_dimension(
        horizontal_dim(
            L.left_glass.x0, L.left_glass.x1, L.left_glass.y0,
            text_y=dim_offset_below(L.left_glass.y0, style, 0), name="left_glass_width", layer="DIMS",
        )
    )
    detail_y = dim_offset_below(0.0, style, 1)
    model.add_dimension(horizontal_dim(0.0, L.track_width, 0.0, text_y=detail_y, name="track_width", layer="DIMS"))
    model.add_dimension(
        horizontal_dim(L.left_shutter.x0, L.track.x0, 0.0, text_y=dim_offset_below(0.0, style, 2), name="overlap", layer="DIMS")
    )
    model.add_dimension(
        horizontal_dim(L.interlock_left, L.interlock_right, mid_y, text_y=mid_y - style.offset_detail, name="interlock_width", layer="DIMS")
    )
    model.add_dimension(
        horizontal_dim(
            L.left_shutter.x0, L.left_glass.x0, L.left_glass.y0,
            text_y=L.left_glass.y0 - style.offset_detail, name="shutter_frame_width", layer="DIMS",
        )
    )
    model.add_dimension(horizontal_dim(L.track.x1, W, 0.0, text_y=detail_y, name="outer_frame_width", layer="DIMS"))
