"""
Geometry Engine — two-track sliding layout from named profile geometry rules only.

Coordinates are never hardcoded; every inset/width comes from profile JSON geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from cad_engine.dimensioning import (
    DimStyleParams,
    dim_offset_above,
    dim_offset_below,
    dim_offset_left,
    dim_offset_right,
    horizontal_dim,
    vertical_dim,
)
from cad_engine.geometry import (
    frame_miter_segments,
    rect_polyline,
    u_polyline_open_left,
    u_polyline_open_right,
    vertical_segment,
)
from cad_engine.types import DrawingModel, Point, Rect, Segment


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

    def meta(self) -> dict[str, float]:
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


def compute_two_track_layout(width: float, height: float, geometry: Mapping[str, Any]) -> SlidingLayout:
    """Core two-track formulas from profile geometry section."""
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
    cx = W / 2.0
    il = cx - iw / 2.0
    ir = cx + iw / 2.0

    left_shutter = Rect(shutter_inset, shutter_inset, il, H - shutter_inset)
    right_shutter = Rect(il, shutter_inset, W - shutter_inset, H - shutter_inset)

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
    )


def build_drawing(layout: SlidingLayout, *, product_name: str, parameters: dict[str, float], style: DimStyleParams) -> DrawingModel:
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
    model.add_polyline(u_polyline_open_right(L.left_shutter, layer="PROFILES", name="left_shutter_outer"))
    model.add_polyline(u_polyline_open_left(L.right_shutter, layer="PROFILES", name="right_shutter_outer"))
    model.add_segment(
        vertical_segment(L.interlock_left, L.right_shutter.y0, L.right_shutter.y1, layer="PROFILES", name="interlock_left")
    )
    model.add_segment(
        vertical_segment(L.interlock_right, L.right_shutter.y0, L.right_shutter.y1, layer="PROFILES", name="interlock_right")
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
    mid_y = H / 2.0
    cx = W / 2.0
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
        horizontal_dim(L.track.x0, L.interlock_left, mid_y, text_y=mid_y + style.offset_inner, name="left_clear_width", layer="DIMS")
    )
    model.add_dimension(
        horizontal_dim(L.interlock_right, L.track.x1, mid_y, text_y=mid_y + style.offset_inner, name="right_clear_width", layer="DIMS")
    )
    model.add_dimension(
        vertical_dim(L.left_glass.y0, L.left_glass.y1, L.right_shutter.x1, text_x=dim_offset_right(W, style, 0), name="glass_height", layer="DIMS")
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
