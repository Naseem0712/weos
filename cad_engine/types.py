"""Core geometric primitives for the CAD engine (formula-driven, unit-agnostic mm)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def offset(self, dx: float = 0.0, dy: float = 0.0) -> Point:
        return Point(self.x + dx, self.y + dy)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True, slots=True)
class Rect:
    """Axis-aligned rectangle defined by min/max corners."""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError(f"Invalid rect: ({self.x0},{self.y0})-({self.x1},{self.y1})")

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    def inset(self, left: float, bottom: float, right: float, top: float) -> Rect:
        return Rect(self.x0 + left, self.y0 + bottom, self.x1 - right, self.y1 - top)

    def inset_uniform(self, d: float) -> Rect:
        return self.inset(d, d, d, d)


@dataclass(frozen=True, slots=True)
class Segment:
    start: Point
    end: Point
    layer: str = "0"
    name: str = ""


@dataclass(frozen=True, slots=True)
class Polyline:
    points: tuple[Point, ...]
    closed: bool = False
    layer: str = "0"
    name: str = ""

    @staticmethod
    def from_xy(points: Sequence[tuple[float, float]], *, closed: bool = False, layer: str = "0", name: str = "") -> Polyline:
        return Polyline(tuple(Point(x, y) for x, y in points), closed=closed, layer=layer, name=name)


@dataclass(frozen=True, slots=True)
class AlignedDim:
    """Aligned/rotated dimension defined by two measurement points and text placement."""

    p1: Point
    p2: Point
    text_pos: Point
    angle_deg: float = 0.0  # 0 = horizontal dim measuring along X; 90 = vertical along Y
    layer: str = "0"
    name: str = ""
    override_text: str | None = None


@dataclass
class DrawingModel:
    """Neutral drawing representation produced by product generators."""

    product_type: str
    width: float
    height: float
    parameters: dict[str, float] = field(default_factory=dict)
    polylines: list[Polyline] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    dimensions: list[AlignedDim] = field(default_factory=list)
    metadata: dict[str, float | str] = field(default_factory=dict)

    def add_polyline(self, pl: Polyline) -> None:
        self.polylines.append(pl)

    def add_segment(self, seg: Segment) -> None:
        self.segments.append(seg)

    def add_dimension(self, dim: AlignedDim) -> None:
        self.dimensions.append(dim)

    def extend_segments(self, segs: Iterable[Segment]) -> None:
        self.segments.extend(segs)
