"""Formula-based dimension placement helpers (style matched to reference DXF)."""

from __future__ import annotations

from dataclasses import dataclass

from cad_engine.types import AlignedDim, Point


@dataclass(frozen=True, slots=True)
class DimStyleParams:
    """
    Dimension presentation parameters reverse-engineered from the master DXF header:
      $DIMASZ = 30, $DIMTXT = 50, arrow/text scale for mm drawings.
    Offsets below are chosen to match reference text placement spacing.
    """

    arrow_size: float = 30.0
    text_height: float = 50.0
    # Distance from measured geometry to dimension line (approx reference ~70–90 mm)
    offset_outer: float = 72.0
    offset_inner: float = 70.0
    offset_detail: float = 55.0
    # Extra stack gap when stacking multiple parallel dims
    stack_gap: float = 90.0


def horizontal_dim(
    x0: float,
    x1: float,
    y: float,
    *,
    text_y: float,
    name: str = "",
    layer: str = "0",
) -> AlignedDim:
    mid_x = (x0 + x1) / 2.0
    return AlignedDim(
        p1=Point(x0, y),
        p2=Point(x1, y),
        text_pos=Point(mid_x, text_y),
        angle_deg=0.0,
        layer=layer,
        name=name,
    )


def vertical_dim(
    y0: float,
    y1: float,
    x: float,
    *,
    text_x: float,
    name: str = "",
    layer: str = "0",
) -> AlignedDim:
    mid_y = (y0 + y1) / 2.0
    return AlignedDim(
        p1=Point(x, y0),
        p2=Point(x, y1),
        text_pos=Point(text_x, mid_y),
        angle_deg=90.0,
        layer=layer,
        name=name,
    )


def dim_offset_below(y: float, style: DimStyleParams, stack: int = 0) -> float:
    return y - style.offset_outer - stack * style.stack_gap


def dim_offset_above(y: float, style: DimStyleParams, stack: int = 0) -> float:
    return y + style.offset_outer + stack * style.stack_gap


def dim_offset_left(x: float, style: DimStyleParams, stack: int = 0) -> float:
    return x - style.offset_outer - stack * style.stack_gap


def dim_offset_right(x: float, style: DimStyleParams, stack: int = 0) -> float:
    return x + style.offset_outer + stack * style.stack_gap
