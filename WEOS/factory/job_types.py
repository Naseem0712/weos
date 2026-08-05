"""Manufacturing job result types (BOM, cut list, glass, quotation, …)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from WEOS.factory.types import DrawingModel


@dataclass
class LineItem:
    category: str
    description: str
    quantity: float
    unit: str = "pcs"
    length_mm: float = 0.0
    remarks: str = ""
    unit_rate: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GlassPane:
    name: str
    width_mm: float
    height_mm: float
    thickness_mm: float
    area_m2: float
    weight_kg: float
    quantity: int = 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CutListItem:
    profile: str
    length_mm: float
    quantity: int
    cut_angle: str = "90"
    machine_notes: str = ""
    total_length_mm: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_length_mm"] = self.length_mm * self.quantity
        return d


@dataclass
class WeightBreakdown:
    aluminium_kg: float
    glass_kg: float
    hardware_kg: float
    total_kg: float
    details: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QuotationResult:
    currency: str
    lines: list[dict[str, Any]]
    subtotal: float
    markup_percent: float
    total: float
    markup_amount: float = 0.0
    after_markup: float = 0.0
    gst_percent: float = 0.0
    gst_amount: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobResult:
    """Full manufacturing package for one opening."""

    profile_id: str
    display_name: str
    width: float
    height: float
    geometry_params: dict[str, float]
    layout_meta: dict[str, float]
    drawing: DrawingModel
    glass: list[GlassPane] = field(default_factory=list)
    hardware: list[LineItem] = field(default_factory=list)
    brush: list[LineItem] = field(default_factory=list)
    track_rail: list[LineItem] = field(default_factory=list)
    cut_list: list[CutListItem] = field(default_factory=list)
    bom: list[LineItem] = field(default_factory=list)
    weight: WeightBreakdown | None = None
    quotation: QuotationResult | None = None
    profile_path: str = ""

    def manufacturing_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "profile_path": self.profile_path,
            "width": self.width,
            "height": self.height,
            "geometry": self.geometry_params,
            "layout": self.layout_meta,
            "glass": [g.as_dict() for g in self.glass],
            "hardware": [h.as_dict() for h in self.hardware],
            "brush": [b.as_dict() for b in self.brush],
            "track_rail": [t.as_dict() for t in self.track_rail],
            "cut_list": [c.as_dict() for c in self.cut_list],
            "bom": [b.as_dict() for b in self.bom],
            "weight": self.weight.as_dict() if self.weight else None,
            "quotation": self.quotation.as_dict() if self.quotation else None,
        }

