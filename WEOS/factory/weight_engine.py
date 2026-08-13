"""WEOS Universal Material Weight Engine — single source of truth.

Priority (never guess):
  1. Manual / Catalogue weight
  2. Calculated from material + dimensions + density
  3. Unknown

Weight ≠ price. Waste is tracked separately (theoretical vs effective).
Learned weights are NEVER auto-approved for production calc.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from WEOS.factory.formula import eval_formula
from WEOS.factory.job_types import GlassPane, WeightBreakdown

# ── Sources / status (UI chips + agent) ──────────────────────────────────────

WEIGHT_SOURCE_CATALOGUE = "catalogue"
WEIGHT_SOURCE_MANUAL = "manually entered"
WEIGHT_SOURCE_CALCULATED = "calculated"
WEIGHT_SOURCE_LEARNED = "learned"
WEIGHT_SOURCE_UNKNOWN = "unknown"

WEIGHT_STATUS_KNOWN = "known"
WEIGHT_STATUS_MISSING = "missing"
WEIGHT_STATUS_CALCULABLE = "calculable"
WEIGHT_STATUS_NEEDS_CATALOGUE = "needs_catalogue"
WEIGHT_STATUS_PARTIAL = "partial"

WEIGHT_SOURCE_GLASS_UPLIFT = "glass+20%"
WEIGHT_SOURCE_GLASS_ONLY = "glass"

SOURCE_LABELS = {
    WEIGHT_SOURCE_CATALOGUE: "Catalogue",
    WEIGHT_SOURCE_MANUAL: "Manual",
    WEIGHT_SOURCE_CALCULATED: "Calculated",
    WEIGHT_SOURCE_LEARNED: "Learned (pending)",
    WEIGHT_SOURCE_UNKNOWN: "Missing",
    WEIGHT_SOURCE_GLASS_UPLIFT: "Glass + 20% frame/hardware",
    WEIGHT_SOURCE_GLASS_ONLY: "Glass",
}

# Industry defaults — overridable by catalogue / explicit density arg
DENSITY_GLASS = 2500.0
DENSITY_ALUMINIUM = 2700.0
DENSITY_MILD_STEEL = 7850.0
DENSITY_STAINLESS = 8000.0
DENSITY_HPL = 1400.0
DENSITY_POLYCARBONATE = 1200.0
DENSITY_PVB = 1070.0
# ACP effective panel factor (kg/m² per mm thickness); not bulk density
ACP_KG_PER_SQM_PER_MM = 1.4

DEFAULT_DENSITIES: dict[str, float] = {
    "glass": DENSITY_GLASS,
    "aluminium": DENSITY_ALUMINIUM,
    "aluminum": DENSITY_ALUMINIUM,
    "alu": DENSITY_ALUMINIUM,
    "mild_steel": DENSITY_MILD_STEEL,
    "ms": DENSITY_MILD_STEEL,
    "iron": DENSITY_MILD_STEEL,
    "steel": DENSITY_MILD_STEEL,
    "ss": DENSITY_STAINLESS,
    "stainless": DENSITY_STAINLESS,
    "stainless_steel": DENSITY_STAINLESS,
    "hpl": DENSITY_HPL,
    "polycarbonate": DENSITY_POLYCARBONATE,
    "pc": DENSITY_POLYCARBONATE,
    "pvb": DENSITY_PVB,
}

PROFILE_LIBRARY_FIELDS = (
    "id",
    "series",
    "name",
    "dimensions",
    "wallThickness",
    "material",
    "alloy",
    "weightPerMeter",
    "crossSectionArea",
    "density",
    "weightSource",
)

HARDWARE_UNITS = frozenset(
    {"pcs", "pc", "set", "kg", "meter", "m", "rm", "rmt", "rft", "sft", "sqft", "pair", "box"}
)


# ── Result shape ─────────────────────────────────────────────────────────────


@dataclass
class MaterialWeightResult:
    ok: bool
    material: str
    materialKind: str
    quantity: float
    unit: str = "kg"
    weightPerUnit: float | None = None
    totalWeight: float | None = None
    theoreticalWeight: float | None = None
    effectiveWeight: float | None = None
    weightSource: str = WEIGHT_SOURCE_UNKNOWN
    weightStatus: str = WEIGHT_STATUS_MISSING
    confidence: float = 0.0
    formula: str | None = None
    why: dict[str, Any] = field(default_factory=dict)
    missingHints: list[str] = field(default_factory=list)
    densityKgPerM3: float | None = None
    dimensions: dict[str, Any] = field(default_factory=dict)
    wasteFactor: float | None = None
    errors: list[str] = field(default_factory=list)
    sourceLabel: str = "Missing"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sourceLabel"] = SOURCE_LABELS.get(self.weightSource, self.weightSource)
        return d


def _round4(v: float | None) -> float | None:
    if v is None:
        return None
    return round(float(v), 4)


def _num(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _dims(dimensions: Mapping[str, Any] | None) -> dict[str, Any]:
    if not dimensions:
        return {}
    out: dict[str, Any] = {}
    for k, v in dimensions.items():
        n = _num(v)
        out[k] = n if n is not None else v
    return out


def normalize_material_kind(material: str | None) -> str:
    """Map free-text material to a calculation kind."""
    key = (material or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "aluminum": "aluminium",
        "alu": "aluminium",
        "aluminium_sheet": "aluminium_sheet",
        "alu_sheet": "aluminium_sheet",
        "aluminium_profile": "aluminium_profile",
        "aluminium_section": "aluminium_profile",
        "aluminum_section": "aluminium_profile",
        "alu_profile": "aluminium_profile",
        "profile": "aluminium_profile",
        "section": "aluminium_profile",
        "extrusion": "aluminium_profile",
        "aluminium_plate": "aluminium_sheet",
        "plate": "sheet",
        "sheet": "sheet",
        "ms": "mild_steel",
        "mild_steel": "mild_steel",
        "iron": "mild_steel",
        "iron_steel": "mild_steel",
        "steel": "mild_steel",
        "steel_sheet": "mild_steel",
        "ss": "stainless",
        "stainless": "stainless",
        "stainless_steel": "stainless",
        "glass": "glass",
        "clear_glass": "glass",
        "toughened": "glass",
        "tempered": "glass",
        "float_glass": "glass",
        "glass_dgu": "glass_dgu",
        "dgu": "glass_dgu",
        "igu": "glass_dgu",
        "double_glazed": "glass_dgu",
        "insulated": "glass_dgu",
        "glass_laminated": "glass_laminated",
        "laminated": "glass_laminated",
        "lami": "glass_laminated",
        "acp": "acp",
        "acp_sheet": "acp",
        "composite": "acp",
        "hpl": "hpl",
        "polycarbonate": "polycarbonate",
        "pc": "polycarbonate",
        "hardware": "hardware",
        "fitting": "hardware",
        "accessory": "hardware",
    }
    if key in aliases:
        return aliases[key]
    if "glass" in key and ("dgu" in key or "igu" in key or "double" in key):
        return "glass_dgu"
    if "glass" in key and ("lami" in key or "pvb" in key):
        return "glass_laminated"
    if "glass" in key:
        return "glass"
    if "acp" in key:
        return "acp"
    if "hpl" in key:
        return "hpl"
    if "poly" in key or key == "pc":
        return "polycarbonate"
    if "profile" in key or "section" in key or "extrusion" in key:
        return "aluminium_profile"
    if "sheet" in key or "plate" in key:
        if "alu" in key or "alum" in key:
            return "aluminium_sheet"
        if "steel" in key or "iron" in key or "ms" in key:
            return "mild_steel"
        if "ss" in key or "stainless" in key:
            return "stainless"
        return "sheet"
    if key in DEFAULT_DENSITIES:
        return key
    return key or "unknown"


def resolve_density(
    material_kind: str,
    density: float | None = None,
    *,
    catalogue_density: float | None = None,
) -> float | None:
    if density is not None:
        return float(density)
    if catalogue_density is not None:
        return float(catalogue_density)
    # Sheet kinds share metal densities
    if material_kind in ("aluminium_sheet", "aluminium_profile", "aluminium"):
        return DENSITY_ALUMINIUM
    if material_kind in ("mild_steel", "iron", "steel", "sheet") and material_kind != "acp":
        if material_kind == "sheet":
            return None  # generic sheet needs explicit density
        return DENSITY_MILD_STEEL
    if material_kind == "stainless":
        return DENSITY_STAINLESS
    if material_kind in ("glass", "glass_dgu", "glass_laminated"):
        return DENSITY_GLASS
    if material_kind == "hpl":
        return DENSITY_HPL
    if material_kind == "polycarbonate":
        return DENSITY_POLYCARBONATE
    return DEFAULT_DENSITIES.get(material_kind)


def _area_m2(d: Mapping[str, Any]) -> float | None:
    area = _num(d.get("areaM2") or d.get("area_m2") or d.get("area"))
    if area is not None and area > 0:
        return area
    w = _num(d.get("widthMm") or d.get("width") or d.get("W") or d.get("lengthMm"))
    h = _num(d.get("heightMm") or d.get("height") or d.get("H") or d.get("depthMm"))
    # For sheets length×width when height missing
    if w is None:
        w = _num(d.get("lengthMm") or d.get("length"))
    if h is None:
        h = _num(d.get("widthMm") or d.get("width"))
    if w is not None and h is not None and w > 0 and h > 0:
        # Prefer mm pair when both look like mm
        if w > 20 or h > 20:  # treat as mm
            return (w * h) / 1e6
        return w * h  # already m
    return None


def _thickness_m(d: Mapping[str, Any]) -> float | None:
    thk_m = _num(d.get("thicknessM") or d.get("thickness_m"))
    if thk_m is not None and thk_m > 0:
        return thk_m
    thk_mm = _num(
        d.get("thicknessMm")
        or d.get("thickness")
        or d.get("thkMm")
        or d.get("glassThicknessMm")
        or d.get("T")
    )
    if thk_mm is not None and thk_mm > 0:
        return thk_mm / 1000.0
    return None


def _thickness_mm(d: Mapping[str, Any]) -> float | None:
    t = _thickness_m(d)
    return t * 1000.0 if t is not None else None


def _length_m(d: Mapping[str, Any], unit: str | None = None) -> float | None:
    lm = _num(d.get("lengthM") or d.get("cutLengthM") or d.get("runningMeters"))
    if lm is not None and lm > 0:
        return lm
    lmm = _num(d.get("lengthMm") or d.get("cutLengthMm") or d.get("length"))
    if lmm is not None and lmm > 0:
        u = (unit or "").lower()
        if u in ("rft", "ft"):
            return lmm  # already feet? prefer explicit lengthM
        if lmm > 50:  # treat as mm
            return lmm / 1000.0
        return lmm  # already meters-ish
    lrft = _num(d.get("lengthRft") or d.get("runningFeet"))
    if lrft is not None and lrft > 0:
        return lrft * 0.3048
    return None


def _unknown(
    material: str,
    kind: str,
    qty: float,
    *,
    hints: list[str],
    dims: dict[str, Any],
    density: float | None = None,
    calculable: bool = False,
    needs_catalogue: bool = False,
    errors: list[str] | None = None,
) -> MaterialWeightResult:
    if calculable:
        status = WEIGHT_STATUS_CALCULABLE
    elif needs_catalogue:
        status = WEIGHT_STATUS_NEEDS_CATALOGUE
    else:
        status = WEIGHT_STATUS_MISSING
    return MaterialWeightResult(
        ok=False,
        material=material,
        materialKind=kind,
        quantity=qty,
        weightSource=WEIGHT_SOURCE_UNKNOWN,
        weightStatus=status,
        confidence=0.0,
        missingHints=hints,
        densityKgPerM3=density,
        dimensions=dims,
        errors=list(errors or []),
        sourceLabel=SOURCE_LABELS[WEIGHT_SOURCE_UNKNOWN],
        why={"priority": "catalogue → calculated → unknown", "reason": "insufficient data"},
    )


def _known(
    *,
    material: str,
    kind: str,
    qty: float,
    weight_per_unit: float,
    source: str,
    formula: str,
    why: dict[str, Any],
    density: float | None = None,
    dims: dict[str, Any] | None = None,
    waste_factor: float | None = None,
    theoretical: float | None = None,
    confidence: float = 0.95,
) -> MaterialWeightResult:
    total = weight_per_unit * qty
    theo = theoretical if theoretical is not None else weight_per_unit
    effective = total
    if waste_factor is not None and waste_factor > 0 and source == WEIGHT_SOURCE_CALCULATED:
        # waste applied only to effective path; theoretical stays clean
        effective = theo * qty * waste_factor
    return MaterialWeightResult(
        ok=True,
        material=material,
        materialKind=kind,
        quantity=qty,
        weightPerUnit=_round4(weight_per_unit),
        totalWeight=_round4(total if waste_factor is None else (theo * qty)),
        theoreticalWeight=_round4(theo * qty),
        effectiveWeight=_round4(effective),
        weightSource=source,
        weightStatus=WEIGHT_STATUS_KNOWN,
        confidence=confidence,
        formula=formula,
        why=why,
        densityKgPerM3=density,
        dimensions=dims or {},
        wasteFactor=waste_factor,
        sourceLabel=SOURCE_LABELS.get(source, source),
    )


# ── Catalogue / manual first ─────────────────────────────────────────────────


def _try_catalogue_or_manual(
    material: str,
    kind: str,
    qty: float,
    dimensions: Mapping[str, Any],
    *,
    catalogue_weight: float | None,
    weight_per_unit: float | None,
    weight_per_meter: float | None,
    weight_source_hint: str | None,
    unit: str | None,
) -> MaterialWeightResult | None:
    """Use approved catalogue / manually entered weight. Learned is rejected here."""
    hint = (weight_source_hint or "").strip().lower()
    if hint in ("learned", WEIGHT_SOURCE_LEARNED):
        # Learned NEVER auto-applies to production calc
        return None

    source = WEIGHT_SOURCE_CATALOGUE
    if hint in ("manual", "manually entered", "manually_entered", WEIGHT_SOURCE_MANUAL):
        source = WEIGHT_SOURCE_MANUAL
    elif hint in ("catalogue", "catalog", "approved"):
        source = WEIGHT_SOURCE_CATALOGUE

    # Explicit per-unit kg
    wpu = _num(weight_per_unit) if weight_per_unit is not None else _num(catalogue_weight)
    if wpu is None:
        wpu = _num(dimensions.get("weightPerUnit") or dimensions.get("weightKg") or dimensions.get("weightKgPerUnit"))
    if wpu is not None and wpu >= 0:
        if hint not in ("manual", "manually entered", "manually_entered", "catalogue", "catalog", "approved") and not weight_source_hint:
            source = WEIGHT_SOURCE_MANUAL if dimensions.get("weightManual") else WEIGHT_SOURCE_CATALOGUE
        return _known(
            material=material,
            kind=kind,
            qty=qty,
            weight_per_unit=wpu,
            source=source,
            formula="weightPerUnit × quantity",
            why={
                "priority": 1,
                "source": source,
                "inputs": {"weightPerUnit": wpu, "quantity": qty},
                "message": "Using catalogue/manual weight (preferred over calculation).",
            },
            dims=dict(dimensions),
            confidence=0.98 if source == WEIGHT_SOURCE_CATALOGUE else 0.92,
        )

    # Profile kg/m × length
    wpm = _num(weight_per_meter)
    if wpm is None:
        wpm = _num(
            dimensions.get("weightPerMeter")
            or dimensions.get("weightPerMeterKg")
            or dimensions.get("weightKgPerM")
            or dimensions.get("weightKgPerMtr")
        )
    if wpm is not None and wpm >= 0:
        length_m = _length_m(dimensions, unit)
        if length_m is None or length_m <= 0:
            return _unknown(
                material,
                kind,
                qty,
                hints=["cutLengthM or lengthMm required with weightPerMeter"],
                dims=dict(dimensions),
                calculable=False,
                needs_catalogue=False,
            )
        per_unit = wpm * length_m
        return _known(
            material=material,
            kind=kind,
            qty=qty,
            weight_per_unit=per_unit,
            source=source if weight_source_hint else WEIGHT_SOURCE_CATALOGUE,
            formula="weightPerMeter × cutLengthM × quantity",
            why={
                "priority": 1,
                "source": source,
                "inputs": {"weightPerMeter": wpm, "cutLengthM": length_m, "quantity": qty},
                "message": "Catalogue kg/m × cut length (never invent rectangular section).",
            },
            dims={**dict(dimensions), "cutLengthM": length_m, "weightPerMeter": wpm},
            confidence=0.97,
        )

    # Hardware unit == kg → quantity is already weight
    u = (unit or "").strip().lower()
    if kind == "hardware" and u == "kg":
        return _known(
            material=material,
            kind=kind,
            qty=qty,
            weight_per_unit=1.0,
            source=source if weight_source_hint else WEIGHT_SOURCE_MANUAL,
            formula="quantity (unit=kg)",
            why={"priority": 1, "inputs": {"quantityKg": qty}, "message": "Hardware sold by kg."},
            dims=dict(dimensions),
            confidence=0.9,
        )

    return None


# ── Calculated paths ─────────────────────────────────────────────────────────


def _calc_glass(
    material: str,
    kind: str,
    qty: float,
    d: Mapping[str, Any],
    density: float,
) -> MaterialWeightResult:
    area = _area_m2(d)
    if area is None or area <= 0:
        return _unknown(
            material,
            kind,
            qty,
            hints=["widthMm+heightMm or areaM2 required for glass"],
            dims=dict(d),
            density=density,
            calculable=False,
            needs_catalogue=True,
        )

    layers: list[float] = []
    raw_layers = d.get("layersMm") or d.get("glassLayersMm") or d.get("panesMm")
    if isinstance(raw_layers, (list, tuple)):
        layers = [float(x) for x in raw_layers if _num(x) and float(x) > 0]

    makeup = str(d.get("makeup") or d.get("glassMakeup") or "").lower()
    if kind == "glass_dgu" or makeup in ("dgu", "igu", "double", "insulated"):
        if len(layers) < 2:
            g1 = _num(d.get("glass1Mm")) or _thickness_mm(d) or 5.0
            g2 = _num(d.get("glass2Mm")) or g1
            layers = [g1, g2]
        glass_mm = sum(layers)
        # spacer/gas ≈ 0 unless explicit spacer weight provided
        spacer_kg = _num(d.get("spacerWeightKg")) or 0.0
        per = area * (glass_mm / 1000.0) * density + spacer_kg
        return _known(
            material=material,
            kind="glass_dgu",
            qty=qty,
            weight_per_unit=per,
            source=WEIGHT_SOURCE_CALCULATED,
            formula="areaM2 × Σ(paneThicknessM) × density + spacerKg",
            why={
                "priority": 2,
                "inputs": {
                    "areaM2": area,
                    "layersMm": layers,
                    "densityKgPerM3": density,
                    "spacerWeightKg": spacer_kg,
                },
                "message": "DGU/IGU: sum glass panes; gas/air gap ≈ 0 kg unless spacer weight given.",
            },
            density=density,
            dims={**dict(d), "areaM2": area, "layersMm": layers},
            confidence=0.9,
        )

    if kind == "glass_laminated" or makeup in ("laminated", "lami", "pvb"):
        if len(layers) < 2:
            g1 = _num(d.get("glass1Mm")) or _thickness_mm(d) or 5.0
            g2 = _num(d.get("glass2Mm")) or g1
            layers = [g1, g2]
        pvb_mm = _num(d.get("pvbMm") or d.get("interlayerMm")) or 0.76
        pvb_density = _num(d.get("pvbDensityKgPerM3")) or DENSITY_PVB
        glass_part = area * (sum(layers) / 1000.0) * density
        pvb_part = area * (pvb_mm / 1000.0) * pvb_density
        per = glass_part + pvb_part
        return _known(
            material=material,
            kind="glass_laminated",
            qty=qty,
            weight_per_unit=per,
            source=WEIGHT_SOURCE_CALCULATED,
            formula="areaM2 × (Σ glassThicknessM × density + pvbThicknessM × pvbDensity)",
            why={
                "priority": 2,
                "inputs": {
                    "areaM2": area,
                    "layersMm": layers,
                    "pvbMm": pvb_mm,
                    "densityKgPerM3": density,
                    "pvbDensityKgPerM3": pvb_density,
                },
                "message": "Laminated: sum glass layers + PVB interlayer when data exists.",
            },
            density=density,
            dims={**dict(d), "areaM2": area, "layersMm": layers, "pvbMm": pvb_mm},
            confidence=0.9,
        )

    # Multi-layer clear/toughened stack without DGU/lami label
    if len(layers) >= 2:
        per = area * (sum(layers) / 1000.0) * density
        return _known(
            material=material,
            kind="glass",
            qty=qty,
            weight_per_unit=per,
            source=WEIGHT_SOURCE_CALCULATED,
            formula="areaM2 × Σ(layerThicknessM) × density",
            why={
                "priority": 2,
                "inputs": {"areaM2": area, "layersMm": layers, "densityKgPerM3": density},
                "message": "Multi-pane glass: sum layer thicknesses.",
            },
            density=density,
            dims={**dict(d), "areaM2": area},
            confidence=0.88,
        )

    thk_m = _thickness_m(d)
    if thk_m is None or thk_m <= 0:
        return _unknown(
            material,
            kind,
            qty,
            hints=["thicknessMm required (or layersMm) to calculate glass weight"],
            dims={**dict(d), "areaM2": area},
            density=density,
            calculable=True,
            needs_catalogue=False,
        )

    per = area * thk_m * density
    thk_mm = thk_m * 1000.0
    return _known(
        material=material,
        kind="glass",
        qty=qty,
        weight_per_unit=per,
        source=WEIGHT_SOURCE_CALCULATED,
        formula="areaM2 × thicknessM × density × quantity",
        why={
            "priority": 2,
            "inputs": {
                "areaM2": area,
                "thicknessMm": thk_mm,
                "densityKgPerM3": density,
                "quantity": qty,
            },
            "message": f"{thk_mm:g} mm glass @ {density:g} kg/m³.",
        },
        density=density,
        dims={**dict(d), "areaM2": area, "thicknessMm": thk_mm},
        confidence=0.93,
    )


def _calc_sheet(
    material: str,
    kind: str,
    qty: float,
    d: Mapping[str, Any],
    density: float | None,
    *,
    waste_factor: float | None,
) -> MaterialWeightResult:
    # Prefer L×W×T when all present
    length_mm = _num(d.get("lengthMm") or d.get("widthMm") or d.get("W"))
    width_mm = _num(d.get("widthMm") or d.get("heightMm") or d.get("H"))
    # Standard sheet: widthMm × heightMm × thicknessMm
    w = _num(d.get("widthMm") or d.get("width"))
    h = _num(d.get("heightMm") or d.get("height") or d.get("lengthMm") or d.get("length"))
    t = _thickness_mm(d)

    if kind == "acp":
        area = _area_m2(d)
        if area is None or t is None:
            return _unknown(
                material,
                kind,
                qty,
                hints=["area (widthMm×heightMm) and thicknessMm required for ACP"],
                dims=dict(d),
                calculable=bool(area or t),
                needs_catalogue=not (area and t),
            )
        factor = _num(d.get("kgPerSqmPerMm")) or ACP_KG_PER_SQM_PER_MM
        theo = area * t * factor
        wf = waste_factor if waste_factor is not None else None
        res = _known(
            material=material,
            kind="acp",
            qty=qty,
            weight_per_unit=theo,
            source=WEIGHT_SOURCE_CALCULATED,
            formula="areaM2 × thicknessMm × kgPerSqmPerMm",
            why={
                "priority": 2,
                "inputs": {"areaM2": area, "thicknessMm": t, "kgPerSqmPerMm": factor, "wasteFactor": wf},
                "message": "ACP panel factor (not bulk density). Waste tracked separately.",
            },
            density=None,
            dims={**dict(d), "areaM2": area, "thicknessMm": t},
            waste_factor=wf,
            theoretical=theo,
            confidence=0.85,
        )
        return res

    if density is None:
        return _unknown(
            material,
            kind,
            qty,
            hints=["densityKgPerM3 required for generic sheet (or use aluminium/steel/ss/hpl/pc kind)"],
            dims=dict(d),
            needs_catalogue=True,
        )

    if w is not None and h is not None and t is not None and w > 0 and h > 0 and t > 0:
        # L×W×T×density / 1e9
        theo = (w * h * t * density) / 1e9
        wf = waste_factor
        return _known(
            material=material,
            kind=kind,
            qty=qty,
            weight_per_unit=theo,
            source=WEIGHT_SOURCE_CALCULATED,
            formula="widthMm × heightMm × thicknessMm × density / 1e9",
            why={
                "priority": 2,
                "inputs": {
                    "widthMm": w,
                    "heightMm": h,
                    "thicknessMm": t,
                    "densityKgPerM3": density,
                    "wasteFactor": wf,
                    "theoreticalWeight": theo,
                },
                "message": "Sheet theoretical weight; wasteFactor applied only to effectiveWeight.",
            },
            density=density,
            dims={"widthMm": w, "heightMm": h, "thicknessMm": t},
            waste_factor=wf,
            theoretical=theo,
            confidence=0.92,
        )

    area = _area_m2(d)
    thk_m = _thickness_m(d)
    if area is not None and thk_m is not None:
        theo = area * thk_m * density
        return _known(
            material=material,
            kind=kind,
            qty=qty,
            weight_per_unit=theo,
            source=WEIGHT_SOURCE_CALCULATED,
            formula="areaM2 × thicknessM × density",
            why={
                "priority": 2,
                "inputs": {"areaM2": area, "thicknessM": thk_m, "densityKgPerM3": density, "wasteFactor": waste_factor},
            },
            density=density,
            dims={**dict(d), "areaM2": area},
            waste_factor=waste_factor,
            theoretical=theo,
            confidence=0.9,
        )

    hints = []
    if w is None or h is None:
        hints.append("widthMm and heightMm (or areaM2)")
    if t is None:
        hints.append("thicknessMm")
    return _unknown(
        material,
        kind,
        qty,
        hints=hints or ["sheet dimensions incomplete"],
        dims=dict(d),
        density=density,
        calculable=True,
        needs_catalogue=False,
    )


def _calc_profile(
    material: str,
    kind: str,
    qty: float,
    d: Mapping[str, Any],
    density: float | None,
    *,
    waste_factor: float | None,
) -> MaterialWeightResult:
    length_m = _length_m(d)
    # Prefer catalogue kg/m — already handled in _try_catalogue_or_manual.
    # Cross-section path:
    area_mm2 = _num(
        d.get("crossSectionAreaMm2")
        or d.get("crossSectionArea")
        or d.get("areaMm2")
        or d.get("sectionAreaMm2")
    )
    if area_mm2 is not None and area_mm2 > 0 and density is not None and length_m is not None:
        # kg/m = areaMm2 × density / 1e6
        kg_per_m = (area_mm2 * density) / 1e6
        theo = kg_per_m * length_m
        return _known(
            material=material,
            kind=kind,
            qty=qty,
            weight_per_unit=theo,
            source=WEIGHT_SOURCE_CALCULATED,
            formula="(crossSectionAreaMm2 × density / 1e6) × cutLengthM × quantity",
            why={
                "priority": 2,
                "inputs": {
                    "crossSectionAreaMm2": area_mm2,
                    "densityKgPerM3": density,
                    "kgPerM": kg_per_m,
                    "cutLengthM": length_m,
                    "wasteFactor": waste_factor,
                },
                "message": "Profile from cross-section × density (only when catalogue kg/m missing).",
            },
            density=density,
            dims={**dict(d), "cutLengthM": length_m, "kgPerM": kg_per_m},
            waste_factor=waste_factor,
            theoretical=theo,
            confidence=0.88,
        )

    hints: list[str] = []
    needs_cat = False
    calculable = False
    if _num(d.get("weightPerMeter") or d.get("weightKgPerM")) is None and area_mm2 is None:
        hints.append("weightPerMeter (catalogue) OR crossSectionAreaMm2 + density")
        needs_cat = True
        calculable = False
    else:
        if length_m is None:
            hints.append("cutLengthM / lengthMm")
            calculable = True
        if area_mm2 is not None and density is None:
            hints.append("densityKgPerM3")
            calculable = True
        if area_mm2 is None and _num(d.get("weightPerMeter")) is None:
            needs_cat = True
    return _unknown(
        material,
        kind,
        qty,
        hints=hints or ["profile weight data incomplete"],
        dims=dict(d),
        density=density,
        calculable=calculable,
        needs_catalogue=needs_cat,
    )


def _calc_hardware(
    material: str,
    qty: float,
    d: Mapping[str, Any],
    unit: str | None,
) -> MaterialWeightResult:
    # Never invent — only use explicit weights
    wpu = _num(d.get("weightPerUnit") or d.get("weightKg") or d.get("weightKgPerUnit"))
    if wpu is not None:
        return _known(
            material=material,
            kind="hardware",
            qty=qty,
            weight_per_unit=wpu,
            source=WEIGHT_SOURCE_MANUAL if d.get("weightManual") else WEIGHT_SOURCE_CATALOGUE,
            formula="hardware weightPerUnit × quantity",
            why={"priority": 1, "inputs": {"weightPerUnit": wpu, "unit": unit, "quantity": qty}},
            dims=dict(d),
            confidence=0.95,
        )
    u = (unit or "").strip().lower()
    if u in ("meter", "m", "rm", "rmt"):
        wpm = _num(d.get("weightPerMeter") or d.get("weightKgPerM"))
        length_m = _length_m(d, unit) or 1.0
        if wpm is not None:
            return _known(
                material=material,
                kind="hardware",
                qty=qty,
                weight_per_unit=wpm * length_m,
                source=WEIGHT_SOURCE_CATALOGUE,
                formula="weightPerMeter × lengthM × quantity",
                why={"inputs": {"weightPerMeter": wpm, "lengthM": length_m}},
                dims=dict(d),
            )
    return _unknown(
        material,
        "hardware",
        qty,
        hints=["catalogue weightPerUnit (pcs/set) or weightPerMeter — never invent hardware weight"],
        dims=dict(d),
        needs_catalogue=True,
    )


# ── Public API ───────────────────────────────────────────────────────────────


def calculate_material_weight(
    material: str,
    dimensions: Mapping[str, Any] | None = None,
    quantity: float = 1.0,
    density: float | None = None,
    unit: str | None = None,
    *,
    catalogue_weight: float | None = None,
    weight_per_unit: float | None = None,
    weight_per_meter: float | None = None,
    weight_source: str | None = None,
    waste_factor: float | None = None,
    catalogue_density: float | None = None,
    learned_weight: float | None = None,
    learned_approved: bool = False,
) -> dict[str, Any]:
    """Universal weight calculation.

    Returns structured dict with weightPerUnit, totalWeight, weightSource,
    weightStatus, formula/why, missingHints.
    """
    dims = _dims(dimensions)
    qty = float(quantity if quantity is not None else 1.0)
    if qty <= 0:
        qty = 1.0
    kind = normalize_material_kind(material)
    dens = resolve_density(kind, density, catalogue_density=catalogue_density)
    learned_meta: dict[str, Any] = {}

    # Learned only if explicitly approved by admin (then treated as catalogue)
    if learned_weight is not None and learned_approved:
        cat = _try_catalogue_or_manual(
            material,
            kind,
            qty,
            dims,
            catalogue_weight=float(learned_weight),
            weight_per_unit=float(learned_weight),
            weight_per_meter=None,
            weight_source_hint=WEIGHT_SOURCE_CATALOGUE,
            unit=unit,
        )
        if cat is not None and cat.ok:
            cat.why["learnedApproved"] = True
            cat.why["message"] = "Admin-approved learned weight applied as catalogue."
            return cat.as_dict()
    elif learned_weight is not None and not learned_approved:
        # Surface as candidate only — do not use in production calc
        learned_meta = {
            "learnedCandidateKg": float(learned_weight),
            "learnedAutoApply": False,
            "hint": "learned weight exists but is NOT approved — review in Learning → Admin Approval",
        }

    # Priority 1: catalogue / manual
    hit = _try_catalogue_or_manual(
        material,
        kind,
        qty,
        dims,
        catalogue_weight=catalogue_weight,
        weight_per_unit=weight_per_unit,
        weight_per_meter=weight_per_meter,
        weight_source_hint=weight_source,
        unit=unit,
    )
    if hit is not None:
        if hit.ok or hit.missingHints:
            out = hit.as_dict()
            if learned_meta:
                out.setdefault("why", {})
                out["why"].update(learned_meta)
                if learned_meta.get("hint"):
                    out.setdefault("missingHints", [])
                    if learned_meta["hint"] not in out["missingHints"]:
                        out["missingHints"] = list(out.get("missingHints") or []) + [learned_meta["hint"]]
            return out

    # Priority 2: calculated
    wf = _num(waste_factor) if waste_factor is not None else _num(dims.get("wasteFactor"))
    # Normalize waste: accept 1.08 or 8 (%) → factor
    if wf is not None and wf > 1.5:
        wf = 1.0 + wf / 100.0

    result: dict[str, Any]
    if kind in ("glass", "glass_dgu", "glass_laminated"):
        dens = dens or DENSITY_GLASS
        result = _calc_glass(material, kind, qty, dims, dens).as_dict()
    elif kind == "hardware":
        result = _calc_hardware(material, qty, dims, unit).as_dict()
    elif kind == "aluminium_profile" or (
        kind in ("aluminium",) and (_num(dims.get("crossSectionAreaMm2") or dims.get("weightPerMeter")) is not None)
    ):
        result = _calc_profile(
            material, "aluminium_profile", qty, dims, dens or DENSITY_ALUMINIUM, waste_factor=wf
        ).as_dict()
    elif kind in (
        "aluminium_sheet",
        "mild_steel",
        "stainless",
        "acp",
        "hpl",
        "polycarbonate",
        "sheet",
    ):
        if kind == "aluminium_sheet":
            dens = dens or DENSITY_ALUMINIUM
        elif kind == "mild_steel":
            dens = dens or DENSITY_MILD_STEEL
        elif kind == "stainless":
            dens = dens or DENSITY_STAINLESS
        elif kind == "hpl":
            dens = dens or DENSITY_HPL
        elif kind == "polycarbonate":
            dens = dens or DENSITY_POLYCARBONATE
        result = _calc_sheet(material, kind, qty, dims, dens, waste_factor=wf).as_dict()
    elif dens is not None and _area_m2(dims) and _thickness_m(dims):
        result = _calc_sheet(material, kind or "sheet", qty, dims, dens, waste_factor=wf).as_dict()
    else:
        result = _unknown(
            material,
            kind,
            qty,
            hints=[
                "Provide catalogue weightPerUnit, or dimensions+density for calculation",
                f"Unsupported or incomplete material kind: {kind}",
            ],
            dims=dims,
            density=dens,
            needs_catalogue=True,
        ).as_dict()

    if learned_meta:
        result.setdefault("why", {})
        result["why"].update(learned_meta)
        if learned_meta.get("hint"):
            hints = list(result.get("missingHints") or [])
            if learned_meta["hint"] not in hints:
                hints.append(learned_meta["hint"])
            result["missingHints"] = hints
    return result

def enrich_bom_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Attach BOM weight fields to a single item (non-destructive copy)."""
    row = dict(item)
    material = str(
        row.get("material")
        or row.get("materialType")
        or row.get("category")
        or row.get("name")
        or row.get("description")
        or "unknown"
    )
    dims = {
        "widthMm": row.get("widthMm") or row.get("width"),
        "heightMm": row.get("heightMm") or row.get("height"),
        "thicknessMm": row.get("thicknessMm") or row.get("thickness"),
        "lengthMm": row.get("lengthMm") or row.get("length"),
        "lengthM": row.get("lengthM") or row.get("cutLengthM"),
        "areaM2": row.get("areaM2") or row.get("area"),
        "crossSectionAreaMm2": row.get("crossSectionAreaMm2") or row.get("crossSectionArea"),
        "weightPerMeter": row.get("weightPerMeter") or row.get("weightKgPerM"),
        "weightPerUnit": row.get("weightPerUnit") or row.get("weightKg"),
        "layersMm": row.get("layersMm"),
        "makeup": row.get("makeup") or row.get("glassMakeup"),
        "glass1Mm": row.get("glass1Mm"),
        "glass2Mm": row.get("glass2Mm"),
        "pvbMm": row.get("pvbMm"),
        "wasteFactor": row.get("wasteFactor"),
    }
    # Drop Nones
    dims = {k: v for k, v in dims.items() if v is not None}
    qty = _num(row.get("quantity") or row.get("qty")) or 1.0
    unit = str(row.get("unit") or "pcs")
    res = calculate_material_weight(
        material,
        dimensions=dims,
        quantity=qty,
        density=_num(row.get("density") or row.get("densityKgPerM3")),
        unit=unit,
        catalogue_weight=_num(row.get("catalogueWeight") or row.get("weightKgPerUnit")),
        weight_per_unit=_num(row.get("weightPerUnit") or row.get("weightKg")),
        weight_per_meter=_num(row.get("weightPerMeter") or row.get("weightKgPerM") or row.get("weightKgPerMtr")),
        weight_source=str(row.get("weightSource") or "") or None,
        waste_factor=_num(row.get("wasteFactor")),
        learned_weight=_num(row.get("learnedWeight")),
        learned_approved=bool(row.get("learnedApproved")),
    )
    row["item"] = row.get("item") or row.get("name") or row.get("description") or material
    row["weightPerUnit"] = res.get("weightPerUnit")
    row["totalWeight"] = res.get("totalWeight")
    row["theoreticalWeight"] = res.get("theoreticalWeight")
    row["effectiveWeight"] = res.get("effectiveWeight")
    row["weightSource"] = res.get("weightSource")
    row["weightStatus"] = res.get("weightStatus")
    row["weightConfidence"] = res.get("confidence")
    row["weightFormula"] = res.get("formula")
    row["weightWhy"] = res.get("why")
    row["missingHints"] = res.get("missingHints")
    row["sourceLabel"] = res.get("sourceLabel")
    if res.get("dimensions"):
        for k in ("length", "area", "thickness"):
            if k == "length" and res["dimensions"].get("cutLengthM") is not None:
                row.setdefault("length", res["dimensions"]["cutLengthM"])
            if k == "area" and res["dimensions"].get("areaM2") is not None:
                row.setdefault("area", res["dimensions"]["areaM2"])
            if k == "thickness" and res["dimensions"].get("thicknessMm") is not None:
                row.setdefault("thickness", res["dimensions"]["thicknessMm"])
    return row


def enrich_bom_with_weights(items: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    return [enrich_bom_item(it) for it in (items or [])]


def sum_product_weights(
    items: Sequence[Mapping[str, Any]] | None,
    *,
    critical_unknown_blocks_total: bool = True,
) -> dict[str, Any]:
    """Sum BOM component weights. Never fake product total if critical unknowns."""
    enriched = enrich_bom_with_weights(items)
    known_total = 0.0
    effective_total = 0.0
    unknowns: list[dict[str, Any]] = []
    known_items: list[dict[str, Any]] = []
    for row in enriched:
        if row.get("weightStatus") == WEIGHT_STATUS_KNOWN and row.get("totalWeight") is not None:
            known_total += float(row["totalWeight"])
            effective_total += float(row.get("effectiveWeight") if row.get("effectiveWeight") is not None else row["totalWeight"])
            known_items.append(row)
        else:
            unknowns.append(row)

    critical = [
        u
        for u in unknowns
        if str(u.get("category") or u.get("materialKind") or "").lower()
        in ("glass", "profile", "aluminium", "aluminium_profile", "structure", "frame")
        or u.get("weightStatus") == WEIGHT_STATUS_NEEDS_CATALOGUE
    ]
    blocked = bool(critical_unknown_blocks_total and critical)
    return {
        "ok": not blocked,
        "totalWeight": None if blocked else _round4(known_total),
        "knownWeightKg": _round4(known_total),
        "effectiveWeightKg": None if blocked else _round4(effective_total),
        "unknownCount": len(unknowns),
        "knownCount": len(known_items),
        "unknowns": [
            {
                "item": u.get("item") or u.get("name"),
                "weightSource": u.get("weightSource"),
                "weightStatus": u.get("weightStatus"),
                "missingHints": u.get("missingHints"),
                "sourceLabel": u.get("sourceLabel"),
            }
            for u in unknowns
        ],
        "items": enriched,
        "message": (
            "Product total withheld — critical weight data missing."
            if blocked
            else f"Product total {known_total:.3f} kg from {len(known_items)} known BOM lines"
            + (f" ({len(unknowns)} unknown omitted)" if unknowns else "")
        ),
    }


def analyze_missing_weights(items: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Agent helper: N missing, M calculable from dims, K need catalogue."""
    enriched = enrich_bom_with_weights(items)
    missing = [r for r in enriched if r.get("weightStatus") != WEIGHT_STATUS_KNOWN]
    calculable = [r for r in missing if r.get("weightStatus") == WEIGHT_STATUS_CALCULABLE]
    needs_cat = [r for r in missing if r.get("weightStatus") == WEIGHT_STATUS_NEEDS_CATALOGUE]
    other = [r for r in missing if r not in calculable and r not in needs_cat]
    n, m, k = len(missing), len(calculable), len(needs_cat)
    summary = format_missing_weight_message(n, m, k)
    return {
        "missingCount": n,
        "calculableCount": m,
        "needsCatalogueCount": k,
        "otherMissingCount": len(other),
        "summary": summary,
        "offerCalculateNow": m > 0,
        "calculatePrompt": "Calculate now?" if m > 0 else None,
        "items": enriched,
        "missing": missing,
        "calculable": calculable,
        "needsCatalogue": needs_cat,
    }


def format_missing_weight_message(n: int, m: int, k: int) -> str:
    """Hindi-emphasis style agent banner (Weight Source always explicit)."""
    if n <= 0:
        return "All BOM items have weight data (Catalogue / Manual / Calculated)."
    return (
        f"⚠️ {n} items have no weight data. "
        f"{m} can be calculated from available dimensions. "
        f"{k} requires catalogue weight."
    )


def propose_learned_weight_candidate(
    *,
    material: str,
    weight_kg: float,
    evidence: Mapping[str, Any] | None = None,
    source_doc: str | None = None,
    unit: str = "kg",
) -> dict[str, Any]:
    """Extracted weight → Candidate → Review → Admin Approval. Never auto-apply."""
    return {
        "status": "candidate",
        "weightSource": WEIGHT_SOURCE_LEARNED,
        "autoApproved": False,
        "material": material,
        "weightKg": float(weight_kg),
        "unit": unit,
        "evidence": dict(evidence or {}),
        "sourceDoc": source_doc,
        "workflow": ["candidate", "review", "admin_approval", "approved_catalogue"],
        "message": "Learned weight queued as candidate — not used in production until admin approval.",
        "safety": "learned NEVER auto-approved",
    }


def profile_entry(
    *,
    id: str,
    series: str = "",
    name: str = "",
    dimensions: str | Mapping[str, Any] | None = None,
    wall_thickness: float | None = None,
    material: str = "aluminium",
    alloy: str = "",
    weight_per_meter: float | None = None,
    cross_section_area: float | None = None,
    density: float | None = None,
    weight_source: str = WEIGHT_SOURCE_UNKNOWN,
) -> dict[str, Any]:
    """Canonical profile library fields."""
    src = weight_source if weight_source in SOURCE_LABELS else WEIGHT_SOURCE_UNKNOWN
    if src == WEIGHT_SOURCE_LEARNED:
        # learned never auto-approved — keep as unknown for calc until admin sets catalogue
        pass
    return {
        "id": id,
        "series": series,
        "name": name or id,
        "dimensions": dimensions,
        "wallThickness": wall_thickness,
        "material": material,
        "alloy": alloy,
        "weightPerMeter": weight_per_meter,
        "crossSectionArea": cross_section_area,
        "density": density if density is not None else resolve_density(normalize_material_kind(material)),
        "weightSource": src,
        "sourceLabel": SOURCE_LABELS.get(src, src),
        "learnedAutoApproved": False,
    }


# ── Legacy pipeline API (aluminium profile sections + glass panes) ────────────


def _pane_glass_kg(pane: GlassPane, glass_rules: Mapping[str, Any] | None) -> float:
    """Universal engine glass kg (dims × thickness × density × qty; laminated/DGU sum layers)."""
    rules = dict(glass_rules or {})
    makeup = str(rules.get("makeup") or rules.get("kind") or "").lower()
    thk = float(pane.thickness_mm or rules.get("thicknessMm") or rules.get("overallMm") or 0)
    dims: dict[str, Any] = {
        "widthMm": float(pane.width_mm or 0),
        "heightMm": float(pane.height_mm or 0),
        "thicknessMm": thk or None,
        "makeup": makeup,
    }
    kind = "glass"
    if makeup in ("dgu", "igu", "double", "insulated") or str(rules.get("airGapMm") or ""):
        kind = "glass_dgu"
        layers = list(rules.get("layersMm") or [])
        if rules.get("glass1Mm") and rules.get("glass2Mm"):
            layers = [float(rules["glass1Mm"]), float(rules["glass2Mm"])]
        if layers:
            dims["layersMm"] = layers
        if rules.get("airGapMm") is not None:
            dims["airGapMm"] = rules.get("airGapMm")
        if rules.get("glass1Mm") is not None:
            dims["glass1Mm"] = rules.get("glass1Mm")
        if rules.get("glass2Mm") is not None:
            dims["glass2Mm"] = rules.get("glass2Mm")
    elif makeup in ("laminated", "lami", "pvb"):
        kind = "glass_laminated"
        layers = list(rules.get("layersMm") or [])
        if rules.get("glass1Mm") and rules.get("glass2Mm"):
            layers = [float(rules["glass1Mm"]), float(rules["glass2Mm"])]
        if layers:
            dims["layersMm"] = layers
        if rules.get("pvbMm") is not None:
            dims["pvbMm"] = rules.get("pvbMm")
    try:
        res = calculate_material_weight(
            kind,
            dimensions=dims,
            quantity=float(pane.quantity or 1),
            density=_num(rules.get("densityKgPerM3")),
        )
        kg = float(res.get("totalWeight") or 0)
        if kg > 0:
            return kg
    except Exception:
        pass
    return float(pane.weight_kg or 0) * float(pane.quantity or 1)


def compute_weight(
    weight_rules: Mapping[str, Any],
    glass: Sequence[GlassPane],
    ctx: Mapping[str, float],
    *,
    glass_rules: Mapping[str, Any] | None = None,
    hardware: Sequence[Any] | None = None,
    frame_material: str | None = None,
) -> WeightBreakdown:
    """Window/door weight: glass from universal engine, then actual kg/m or 20% uplift.

    Aluminium (and casement/vent unless UPVC):
      1. Glass kg from dims × thickness × density × qty (laminated/DGU sum layers).
      2. Frame + hardware = catalogue kg/m × cut lengths (+ hardware pcs kg) when
         ``weightPerMeter`` / hardware kg exist; else **20% of glass weight**.
    UPVC: glass only (+ actual hardware kg if present). Never invent hardware kg.
    """
    if "aluminiumDensityKgPerM3" not in (weight_rules or {}):
        raise KeyError("profile.weight.aluminiumDensityKgPerM3 is required (no Python default)")
    waste = float((weight_rules or {}).get("wasteFactor", 1.0) or 1.0)
    details: dict[str, float] = {}
    glass_kg = 0.0
    for g in glass or []:
        kg = _pane_glass_kg(g, glass_rules)
        details[str(getattr(g, "name", None) or "glass")] = kg
        glass_kg += kg
    details["glass"] = glass_kg

    upvc = str(frame_material or "").strip().lower().replace("-", "").replace(" ", "") in (
        "upvc",
        "upv",
        "pvc",
    )

    alu = 0.0
    has_catalogue_kg_m = False
    for sec in (weight_rules or {}).get("profileSections") or []:
        wpm = sec.get("weightPerMeter") or sec.get("weightKgPerM") or sec.get("weightKgPerMtr")
        if wpm is None:
            continue
        has_catalogue_kg_m = True
        length_mm = eval_formula(sec.get("lengthFormula", 0), ctx)
        res = calculate_material_weight(
            "aluminium_profile",
            dimensions={"lengthMm": length_mm, "weightPerMeter": float(wpm)},
            quantity=1.0,
            weight_per_meter=float(wpm),
            weight_source=WEIGHT_SOURCE_CATALOGUE,
        )
        kg = float(res.get("totalWeight") or 0.0) * waste
        details[str(sec.get("name", "section"))] = kg
        alu += kg

    hw_kg = 0.0
    for h in hardware or []:
        qty = 1.0
        piece = None
        if isinstance(h, Mapping):
            piece = h.get("weightKg") or h.get("weightPerUnit") or h.get("unitWeightKg")
            qty = float(h.get("qty") or h.get("quantity") or 1) or 1.0
        else:
            piece = getattr(h, "weight_kg", None) or getattr(h, "weightKg", None)
            qty = float(getattr(h, "quantity", None) or getattr(h, "qty", None) or 1) or 1.0
        if piece in (None, ""):
            continue
        try:
            hw_kg += float(piece) * qty
        except (TypeError, ValueError):
            continue
    if hw_kg:
        details["hardware"] = hw_kg

    if upvc:
        src = WEIGHT_SOURCE_GLASS_ONLY if not hw_kg else WEIGHT_SOURCE_CATALOGUE
        total = glass_kg + hw_kg
        return WeightBreakdown(
            aluminium_kg=0.0,
            glass_kg=glass_kg,
            hardware_kg=hw_kg,
            total_kg=total,
            details=details,
            weight_source=src,
        )

    if has_catalogue_kg_m:
        total = alu + glass_kg + hw_kg
        return WeightBreakdown(
            aluminium_kg=alu,
            glass_kg=glass_kg,
            hardware_kg=hw_kg,
            total_kg=total,
            details=details,
            weight_source=WEIGHT_SOURCE_CATALOGUE,
        )

    # Default: aluminium + hardware = 20% of glass. Do not invent hardware kg.
    uplift = round(0.20 * glass_kg, 6)
    details["frame_hardware_uplift"] = uplift
    return WeightBreakdown(
        aluminium_kg=uplift,
        glass_kg=glass_kg,
        hardware_kg=0.0,
        total_kg=glass_kg + uplift,
        details=details,
        weight_source=WEIGHT_SOURCE_GLASS_UPLIFT,
    )
