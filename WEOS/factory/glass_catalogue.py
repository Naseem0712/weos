"""Standalone Glass Engine + configurable Glass Library (Part 2).

Users configure glass once (single / DGU / laminated, air gap, PVB, colour,
brand, toughened, rate) and reuse it in Product Library setup + the cart. Each
glass spec computes its own weight (via the preloaded baseline formulas) and,
given a clear opening + profile insertion, its accurate pane size (Part 4). The
full spec prints into the quote / specs.

Library JSON lives under ``knowledge_base/libraries/glass_catalogue/`` so it is
portable and versionable; production product JSON is never modified here.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import knowledge_base_dir

# ── Catalogue of available glass makeups ─────────────────────────────────────
SINGLE_THICKNESSES_MM = [4.0, 5.0, 6.0, 8.0, 10.0, 12.0]

# Commercial leaf rates (₹/sft) — single clear toughened.
CLEAR_TUFF_RATE_PER_SFT: dict[float, float] = {
    5.0: 80.0,
    6.0: 90.0,
    8.0: 120.0,
    10.0: 165.0,
    12.0: 190.0,
}
DGU_CHARGE_PER_SFT = 150.0
ARGON_CHARGE_PER_SFT = 50.0
LAMINATION_CHARGE_PER_SFT = 250.0
DGU_MAX_OVERALL_MM = 28.0
LAMINATED_MAX_OVERALL_MM = 13.52

# DGU overall thickness → default layer makeup (glass / air gap / glass) in mm.
# Keys are overall mm; makeupLabel uses glass+air+glass (e.g. 5+12A+5).
# Window profiles currently admit ≤28 mm overall — thicker keys kept only as legacy.
DGU_MAKEUPS_MM: dict[float, dict[str, float]] = {
    18.0: {"glass1Mm": 5.0, "airGapMm": 8.0, "glass2Mm": 5.0},
    20.0: {"glass1Mm": 6.0, "airGapMm": 8.0, "glass2Mm": 6.0},
    22.0: {"glass1Mm": 5.0, "airGapMm": 12.0, "glass2Mm": 5.0},  # 5+12A+5
    23.0: {"glass1Mm": 5.0, "airGapMm": 12.0, "glass2Mm": 6.0},  # 5+12A+6
    24.0: {"glass1Mm": 6.0, "airGapMm": 12.0, "glass2Mm": 6.0},  # 6+12A+6
    25.0: {"glass1Mm": 5.0, "airGapMm": 12.0, "glass2Mm": 8.0},  # 5+12A+8
    26.0: {"glass1Mm": 6.0, "airGapMm": 12.0, "glass2Mm": 8.0},  # 6+12A+8
    28.0: {"glass1Mm": 8.0, "airGapMm": 12.0, "glass2Mm": 8.0},  # 8+12A+8
}

# Laminated overall thickness → default makeup (glass + PVB + glass) in mm.
# Max 13.52 mm for current window packs.
LAMINATED_MAKEUPS_MM: dict[float, dict[str, float]] = {
    11.52: {"glass1Mm": 5.0, "pvbMm": 1.52, "glass2Mm": 5.0},   # 5+1.52+5
    12.52: {"glass1Mm": 5.0, "pvbMm": 1.52, "glass2Mm": 6.0},   # 5+1.52+6
    13.52: {"glass1Mm": 6.0, "pvbMm": 1.52, "glass2Mm": 6.0},   # 6+1.52+6
}

# Laminated + DGU overall thickness → laminated pane (glass1 + PVB + glass2),
# air gap and the single outer pane (glass3). E.g. 29.52 = 5+1.52+5 / 12A / 6.
LAM_DGU_MAKEUPS_MM: dict[float, dict[str, float]] = {
    28.52: {"glass1Mm": 5.0, "pvbMm": 1.52, "glass2Mm": 5.0, "airGapMm": 12.0, "glass3Mm": 5.0},
    29.52: {"glass1Mm": 5.0, "pvbMm": 1.52, "glass2Mm": 5.0, "airGapMm": 12.0, "glass3Mm": 6.0},
    30.52: {"glass1Mm": 6.0, "pvbMm": 1.52, "glass2Mm": 5.0, "airGapMm": 12.0, "glass3Mm": 6.0},
    31.52: {"glass1Mm": 6.0, "pvbMm": 1.52, "glass2Mm": 6.0, "airGapMm": 12.0, "glass3Mm": 6.0},
    33.52: {"glass1Mm": 6.0, "pvbMm": 1.52, "glass2Mm": 6.0, "airGapMm": 12.0, "glass3Mm": 8.0},
}

LAM_DGU_KINDS = ("lam_dgu", "laminated_dgu", "lamdgu", "lam+dgu", "dgu_laminated")

# Tinted colours commonly offered on single toughened panes (cart + railing).
TINTED_COLOURS = ("clear", "black", "grey", "brown")

# Selectable commercial DGU packs (≤28 mm). Rate = leaf rates + DGU ₹150 (+ Argon ₹50).
COMMERCIAL_DGU_PACKS: tuple[dict[str, Any], ...] = (
    {"g1": 5.0, "gap": 8.0, "g2": 5.0},
    {"g1": 5.0, "gap": 12.0, "g2": 5.0},
    {"g1": 5.0, "gap": 12.0, "g2": 6.0},
    {"g1": 5.0, "gap": 12.0, "g2": 8.0},
    {"g1": 6.0, "gap": 8.0, "g2": 6.0},
    {"g1": 6.0, "gap": 12.0, "g2": 6.0},
    {"g1": 6.0, "gap": 12.0, "g2": 8.0},
    {"g1": 6.0, "gap": 12.0, "g2": 10.0},
    {"g1": 8.0, "gap": 8.0, "g2": 8.0},
    {"g1": 8.0, "gap": 10.0, "g2": 8.0},
    {"g1": 8.0, "gap": 12.0, "g2": 8.0},
    {"g1": 10.0, "gap": 8.0, "g2": 10.0},
)

# Laminated packs within 13.52 mm max (5+1.52+8 = 14.52 excluded).
COMMERCIAL_LAM_PACKS: tuple[dict[str, Any], ...] = (
    {"g1": 5.0, "pvb": 1.52, "g2": 5.0},
    {"g1": 5.0, "pvb": 1.52, "g2": 6.0},
    {"g1": 6.0, "pvb": 1.52, "g2": 5.0},
    {"g1": 6.0, "pvb": 1.52, "g2": 6.0},
)


def clear_tuff_rate(thickness_mm: Any) -> float | None:
    try:
        key = float(thickness_mm)
    except (TypeError, ValueError):
        return None
    if key in CLEAR_TUFF_RATE_PER_SFT:
        return CLEAR_TUFF_RATE_PER_SFT[key]
    # tolerate int-like 5 vs 5.0
    for k, v in CLEAR_TUFF_RATE_PER_SFT.items():
        if abs(k - key) < 1e-6:
            return v
    return None


def dgu_pack_rate(g1: float, g2: float, *, argon: bool = False) -> dict[str, Any]:
    r1 = clear_tuff_rate(g1) or 0.0
    r2 = clear_tuff_rate(g2) or 0.0
    dgu = DGU_CHARGE_PER_SFT
    argon_amt = ARGON_CHARGE_PER_SFT if argon else 0.0
    total = r1 + r2 + dgu + argon_amt
    return {
        "rate": total,
        "rateUnit": "sqft",
        "rateBreakdown": {
            "leaf1Rate": r1,
            "leaf2Rate": r2,
            "dguCharge": dgu,
            "argonCharge": argon_amt,
            "formula": "leaf1 + leaf2 + DGU ₹150" + (" + Argon ₹50" if argon else ""),
        },
    }


def laminated_pack_rate(g1: float, g2: float) -> dict[str, Any]:
    r1 = clear_tuff_rate(g1) or 0.0
    r2 = clear_tuff_rate(g2) or 0.0
    lam = LAMINATION_CHARGE_PER_SFT
    total = r1 + r2 + lam
    return {
        "rate": total,
        "rateUnit": "sqft",
        "rateBreakdown": {
            "leaf1Rate": r1,
            "leaf2Rate": r2,
            "laminationCharge": lam,
            "formula": "leaf1 + leaf2 + lamination ₹250",
        },
    }


def dgu_pack_id(g1: float, gap: float, g2: float, *, argon: bool = False) -> str:
    base = f"dgu_{int(g1)}_{int(gap)}_{int(g2)}"
    return f"{base}_argon" if argon else base


def lam_pack_id(g1: float, pvb: float, g2: float) -> str:
    pvb_key = str(pvb).replace(".", "")
    return f"lam_{int(g1)}_{pvb_key}_{int(g2)}"


def normalize_makeup_kind(makeup: Any) -> str:
    """``single`` / ``dgu`` / ``laminated`` / ``lam_dgu`` from any user/API spelling."""
    kind = str(makeup or "single").strip().lower().replace("-", "_").replace(" ", "_")
    if kind in LAM_DGU_KINDS or ("lam" in kind and "dgu" in kind):
        return "lam_dgu"
    if kind in ("dgu", "double", "insulated", "igu"):
        return "dgu"
    if kind in ("laminated", "lami", "lam"):
        return "laminated"
    return "single"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "glass"


def catalogue_dir() -> Path:
    d = knowledge_base_dir() / "libraries" / "glass_catalogue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def makeup_options() -> dict[str, Any]:
    """Options catalogue for the Glass Library setup UI."""
    return {
        "single": {
            "thicknessesMm": SINGLE_THICKNESSES_MM,
            "label": "Single glass",
        },
        "dgu": {
            "overallMm": sorted(k for k in DGU_MAKEUPS_MM.keys() if k <= DGU_MAX_OVERALL_MM),
            "makeups": {str(k): v for k, v in DGU_MAKEUPS_MM.items() if k <= DGU_MAX_OVERALL_MM},
            "label": "DGU (double glazed unit)",
            "note": (
                f"Selectable packs ≤{DGU_MAX_OVERALL_MM:g} mm. "
                f"Rate = leaf glass + DGU ₹{DGU_CHARGE_PER_SFT:g}/sft (+ Argon ₹{ARGON_CHARGE_PER_SFT:g}/sft optional)."
            ),
            "dguChargePerSft": DGU_CHARGE_PER_SFT,
            "argonChargePerSft": ARGON_CHARGE_PER_SFT,
            "maxOverallMm": DGU_MAX_OVERALL_MM,
        },
        "laminated": {
            "overallMm": sorted(k for k in LAMINATED_MAKEUPS_MM.keys() if k <= LAMINATED_MAX_OVERALL_MM),
            "makeups": {
                str(k): v for k, v in LAMINATED_MAKEUPS_MM.items() if k <= LAMINATED_MAX_OVERALL_MM
            },
            "label": "Laminated (PVB)",
            "note": (
                f"Packs ≤{LAMINATED_MAX_OVERALL_MM:g} mm. "
                f"Rate = leaf glass + lamination ₹{LAMINATION_CHARGE_PER_SFT:g}/sft."
            ),
            "laminationChargePerSft": LAMINATION_CHARGE_PER_SFT,
            "maxOverallMm": LAMINATED_MAX_OVERALL_MM,
        },
        "lam_dgu": {
            "overallMm": sorted(LAM_DGU_MAKEUPS_MM.keys()),
            "makeups": {str(k): v for k, v in LAM_DGU_MAKEUPS_MM.items()},
            "label": "Laminated + DGU",
            "note": "Laminated pane (glass + PVB + glass) + air gap + single glass.",
        },
        "colours": ["clear", "green", "blue", "grey", "bronze", "black", "reflective", "frosted"],
        "toughened": [True, False],
        "rateUnits": ["sqft", "sqm"],
    }


def default_layers_for(makeup: str, overall_mm: float | None) -> dict[str, float]:
    kind = normalize_makeup_kind(makeup)
    try:
        key = float(overall_mm) if overall_mm is not None else None
    except (TypeError, ValueError):
        key = None
    if kind == "dgu" and key in DGU_MAKEUPS_MM:
        return dict(DGU_MAKEUPS_MM[key])
    if kind == "laminated" and key in LAMINATED_MAKEUPS_MM:
        return dict(LAMINATED_MAKEUPS_MM[key])
    if kind == "lam_dgu" and key in LAM_DGU_MAKEUPS_MM:
        return dict(LAM_DGU_MAKEUPS_MM[key])
    return {}


def build_glass_spec(
    *,
    makeup: str = "single",
    thickness_mm: float | None = None,
    overall_mm: float | None = None,
    glass1_mm: float | None = None,
    glass2_mm: float | None = None,
    air_gap_mm: float | None = None,
    pvb_mm: float | None = None,
    glass3_mm: float | None = None,
    colour: str = "clear",
    brand: str = "",
    toughened: bool = False,
    rate: float | None = None,
    rate_unit: str = "sqft",
    density: float = 2500.0,
    name: str | None = None,
    glass_id: str | None = None,
    status: str = "draft",
    argon: bool = False,
    fill_gas: str | None = None,
    rate_breakdown: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize a full glass spec (single / DGU / laminated / laminated+DGU) for reuse + printing."""
    kind = normalize_makeup_kind(makeup)
    # Quick-save sends only ``thicknessMm`` for multi-layer makeups — treat it as the overall.
    if kind != "single" and overall_mm in (None, 0, "") and thickness_mm:
        overall_mm = thickness_mm
    layers = default_layers_for(kind, overall_mm)
    g1 = glass1_mm if glass1_mm is not None else layers.get("glass1Mm")
    g2 = glass2_mm if glass2_mm is not None else layers.get("glass2Mm")
    g3 = glass3_mm if glass3_mm is not None else layers.get("glass3Mm")
    gap = air_gap_mm if air_gap_mm is not None else layers.get("airGapMm")
    pvb = pvb_mm if pvb_mm is not None else layers.get("pvbMm")

    if kind == "dgu":
        thickness_mm = overall_mm or ((g1 or 0) + (gap or 0) + (g2 or 0))
        makeup_label = f"{g1:g}+{gap:g}A+{g2:g}" if g1 and gap and g2 else f"DGU {float(thickness_mm or 0):g}mm"
        layers_mm = [g1 or 0, g2 or 0]
    elif kind == "laminated":
        thickness_mm = overall_mm or ((g1 or 0) + (pvb or 0) + (g2 or 0))
        makeup_label = f"{g1:g}+{pvb:g}PVB+{g2:g}" if g1 and pvb and g2 else f"Laminated {float(thickness_mm or 0):g}mm"
        layers_mm = [g1 or 0, g2 or 0]
    elif kind == "lam_dgu":
        thickness_mm = overall_mm or ((g1 or 0) + (pvb or 0) + (g2 or 0) + (gap or 0) + (g3 or 0))
        if g1 and pvb and g2 and gap and g3:
            makeup_label = f"{g1:g}+{pvb:g}PVB+{g2:g} Lam + {gap:g}A + {g3:g}"
        else:
            makeup_label = f"Laminated + DGU {float(thickness_mm or 0):g}mm"
        layers_mm = [g1 or 0, g2 or 0, g3 or 0]
    else:
        kind = "single"
        thickness_mm = thickness_mm or overall_mm or 5.0
        makeup_label = f"{thickness_mm:g}mm"
        layers_mm = [thickness_mm]

    tuff = "Toughened" if toughened else "Non-toughened"
    if kind == "laminated" and g1 and pvb and g2:
        display_label = f"{g1:g}+{pvb:g}+{g2:g} mm Laminated"
    elif kind == "dgu" and g1 and gap and g2:
        display_label = f"{g1:g}+{gap:g}A+{g2:g} mm DGU"
    elif kind == "lam_dgu" and g1 and pvb and g2 and gap and g3:
        display_label = f"{g1:g}+{pvb:g}+{g2:g} Lam + {gap:g}A + {g3:g} mm DGU"
    elif kind == "lam_dgu":
        display_label = f"{float(thickness_mm or 0):g} mm Laminated + DGU"
    elif kind == "dgu":
        display_label = f"{float(thickness_mm or 0):g} mm DGU"
    elif kind == "laminated":
        display_label = f"{float(thickness_mm or 0):g} mm Laminated"
    else:
        display_label = f"{float(thickness_mm or 0):g} mm"
    # Layered makeups (5+1.52+5 …) print the layer identity only; plain
    # thickness labels keep the Toughened tag as before.
    if toughened and "+" not in display_label and "toughened" not in display_label.lower():
        display_label += " Toughened"
    display = name or (
        f"{makeup_label} {colour.title()} {tuff}"
        + (f" · {brand}" if brand else "")
    ).strip()

    gid = glass_id or f"glass_{_slug(kind)}_{_slug(colour)}_{int(round((thickness_mm or 0) * 100))}"
    fill = str(fill_gas or ("argon" if argon else ("air" if kind == "dgu" else "")) or "").strip().lower()
    out: dict[str, Any] = {
        "id": gid,
        "name": display,
        "makeup": kind,
        "thicknessMm": round(float(thickness_mm or 0), 2),
        "overallMm": round(float(thickness_mm or 0), 2),
        "glass1Mm": g1,
        "glass2Mm": g2,
        "glass3Mm": g3,
        "airGapMm": gap,
        "pvbMm": pvb,
        "layersMm": layers_mm,
        "colour": colour,
        "brand": brand,
        "toughened": bool(toughened),
        "toughenedLabel": tuff,
        "rate": float(rate) if rate is not None else None,
        "rateUnit": rate_unit,
        "densityKgPerM3": float(density),
        "makeupLabel": makeup_label,
        "display_label": display_label,
        "specLine": _spec_line(display, makeup_label, colour, tuff, brand, rate, rate_unit),
        "status": status,
        "updatedAt": _now(),
    }
    if kind == "dgu":
        out["argon"] = bool(argon) or fill == "argon"
        out["fillGas"] = "argon" if out["argon"] else (fill or "air")
    if isinstance(rate_breakdown, Mapping) and rate_breakdown:
        out["rateBreakdown"] = dict(rate_breakdown)
    return out


def _spec_line(
    display: str, makeup_label: str, colour: str, tuff: str, brand: str, rate: float | None, rate_unit: str
) -> str:
    bits = [makeup_label, colour.title(), tuff]
    if brand:
        bits.append(brand)
    if rate is not None:
        bits.append(f"@ ₹{rate:g}/{rate_unit}")
    return " · ".join(bits)


def glass_weight(spec: Mapping[str, Any], *, width_mm: float, height_mm: float, qty: float = 1.0) -> dict[str, Any]:
    """Weight for a configured glass spec at a given pane size (baseline formulas)."""
    from WEOS.learning.material_formulas import compute_glass_makeup_weight

    return compute_glass_makeup_weight(
        makeup=str(spec.get("makeup") or "single"),
        width_mm=width_mm,
        height_mm=height_mm,
        layers_mm=list(spec.get("layersMm") or []),
        pvb_mm=float(spec.get("pvbMm") or 0.76),
        thickness_mm=float(spec.get("thicknessMm") or 0) or None,
        density=float(spec.get("densityKgPerM3") or 2500.0),
        qty=qty,
    )


def price_glass(spec: Mapping[str, Any], *, area_m2: float, qty: float = 1.0) -> dict[str, Any]:
    rate = spec.get("rate")
    unit = str(spec.get("rateUnit") or "sqft")
    if rate is None:
        return {"rate": None, "unit": unit, "billableQty": None, "amount": None}
    if unit == "sqm":
        billable = area_m2 * qty
    else:  # sqft
        billable = area_m2 * 10.7639 * qty
    return {"rate": float(rate), "unit": unit, "billableQty": round(billable, 4), "amount": round(float(rate) * billable, 2)}


def size_and_price(
    spec: Mapping[str, Any],
    *,
    clear_width_mm: float,
    clear_height_mm: float,
    glass_rules: Mapping[str, Any] | None = None,
    qty: float = 1.0,
    interlock_left: bool = False,
    interlock_right: bool = False,
) -> dict[str, Any]:
    """Full standalone Glass Engine compute: accurate size → weight → price → spec.

    Ties Part 2 (glass library spec) and Part 4 (insertion-based sizing) together.
    """
    from WEOS.factory.glass_sizing import preview_from_profile

    sizing = preview_from_profile(
        glass_rules,
        clear_width_mm=clear_width_mm,
        clear_height_mm=clear_height_mm,
        interlock_left=interlock_left,
        interlock_right=interlock_right,
        label=str(spec.get("name") or "glass"),
    )
    weight = glass_weight(spec, width_mm=sizing["glassWidthMm"], height_mm=sizing["glassHeightMm"], qty=qty)
    price = price_glass(spec, area_m2=sizing["areaM2"], qty=qty)
    return {
        "spec": dict(spec),
        "size": sizing,
        "weight": weight,
        "price": price,
        "print": {
            "glass": spec.get("specLine") or spec.get("name"),
            "sizeMm": f"{sizing['glassWidthMm']:g} × {sizing['glassHeightMm']:g}",
            "areaSqft": sizing.get("areaSqft"),
            "weightKg": weight.get("weightKg") if isinstance(weight, dict) else None,
        },
    }


# ── Glass Library persistence (configure once, reuse) ────────────────────────

def list_glass() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(catalogue_dir().glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items


def get_glass(glass_id: str) -> dict[str, Any]:
    path = catalogue_dir() / f"{glass_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Glass '{glass_id}' not found in library")
    return json.loads(path.read_text(encoding="utf-8"))


def save_glass(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Persist a glass spec to the library (normalizes via build_glass_spec)."""
    argon = bool(spec.get("argon") or str(spec.get("fillGas") or "").lower() == "argon")
    breakdown = spec.get("rateBreakdown") if isinstance(spec.get("rateBreakdown"), Mapping) else None
    normalized = build_glass_spec(
        makeup=str(spec.get("makeup") or "single"),
        thickness_mm=spec.get("thicknessMm"),
        overall_mm=spec.get("overallMm"),
        glass1_mm=spec.get("glass1Mm"),
        glass2_mm=spec.get("glass2Mm"),
        air_gap_mm=spec.get("airGapMm"),
        pvb_mm=spec.get("pvbMm"),
        glass3_mm=spec.get("glass3Mm"),
        colour=str(spec.get("colour") or "clear"),
        brand=str(spec.get("brand") or ""),
        toughened=bool(spec.get("toughened")),
        rate=spec.get("rate"),
        rate_unit=str(spec.get("rateUnit") or "sqft"),
        density=float(spec.get("densityKgPerM3") or 2500.0),
        name=(str(spec.get("name") or "").strip() or None),
        glass_id=spec.get("id") or f"glass_{uuid.uuid4().hex[:8]}",
        status=str(spec.get("status") or "active"),
        argon=argon,
        fill_gas=str(spec.get("fillGas") or ("argon" if argon else "")),
        rate_breakdown=breakdown,
    )
    path = catalogue_dir() / f"{normalized['id']}.json"
    path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    return normalized


def delete_glass(glass_id: str) -> dict[str, Any]:
    path = catalogue_dir() / f"{glass_id}.json"
    if path.is_file():
        path.unlink()
        return {"ok": True, "deleted": glass_id}
    raise FileNotFoundError(f"Glass '{glass_id}' not found")


def _starter_glass_specs() -> list[dict[str, Any]]:
    """Full default catalogue: single clear/tinted, laminated safety, DGU/IGU.

    Commercial rates (₹/sft): clear tuff leaves from ``CLEAR_TUFF_RATE_PER_SFT``;
    DGU = leaves + ₹150 (+ Argon ₹50); laminated = leaves + ₹250.
    """
    starters: list[dict[str, Any]] = []
    # Single clear (annealed 5) + toughened clear at common thicknesses
    starters.append({
        "makeup": "single", "thicknessMm": 5.0, "colour": "clear", "toughened": False,
        "name": "5mm Clear", "id": "5mm_clear",
    })
    for thk in (5.0, 6.0, 8.0, 10.0, 12.0):
        rate = clear_tuff_rate(thk)
        starters.append({
            "makeup": "single", "thicknessMm": thk, "colour": "clear", "toughened": True,
            "name": f"{thk:g}mm Clear Toughened",
            "id": f"{int(thk)}mm_toughened" if thk != 5 else "5mm_clear_toughened",
            "rate": rate, "rateUnit": "sqft",
            "rateBreakdown": {"leafRate": rate, "formula": "clear tuff leaf ₹/sft"},
        })
    # Single tinted toughened (black / grey / brown) at 5–12 mm — same leaf rates
    for colour in ("black", "grey", "brown"):
        for thk in (5.0, 6.0, 8.0, 10.0, 12.0):
            rate = clear_tuff_rate(thk)
            starters.append({
                "makeup": "single", "thicknessMm": thk, "colour": colour, "toughened": True,
                "name": f"{thk:g}mm {colour.title()} Toughened",
                "id": f"{int(thk)}mm_{colour}_toughened",
                "rate": rate, "rateUnit": "sqft",
            })
    # Fluted toughened (shower + custom)
    for colour in ("clear", "grey", "brown"):
        for thk in (5.0, 8.0):
            rate = clear_tuff_rate(thk)
            starters.append({
                "makeup": "single", "thicknessMm": thk, "colour": colour, "toughened": True,
                "name": f"{thk:g}mm Fluted {colour.title()} Toughened",
                "id": f"fluted_{int(thk)}_{colour}_tuff",
                "rate": rate, "rateUnit": "sqft",
            })
    # Laminated safety packs ≤13.52 mm
    for pack in COMMERCIAL_LAM_PACKS:
        g1, pvb, g2 = float(pack["g1"]), float(pack["pvb"]), float(pack["g2"])
        overall = round(g1 + pvb + g2, 2)
        if overall > LAMINATED_MAX_OVERALL_MM + 1e-6:
            continue
        priced = laminated_pack_rate(g1, g2)
        oid = lam_pack_id(g1, pvb, g2)
        starters.append({
            "makeup": "laminated", "overallMm": overall,
            "glass1Mm": g1, "pvbMm": pvb, "glass2Mm": g2,
            "colour": "clear", "toughened": True,
            "name": f"Laminated {g1:g}+{pvb:g}+{g2:g} Clear Tuff",
            "id": oid,
            "rate": priced["rate"], "rateUnit": "sqft",
            "rateBreakdown": priced["rateBreakdown"],
        })
    # DGU packs ≤28 mm (air + argon variants for each)
    for pack in COMMERCIAL_DGU_PACKS:
        g1, gap, g2 = float(pack["g1"]), float(pack["gap"]), float(pack["g2"])
        overall = round(g1 + gap + g2, 2)
        if overall > DGU_MAX_OVERALL_MM + 1e-6:
            continue
        if clear_tuff_rate(g1) is None or clear_tuff_rate(g2) is None:
            continue
        for argon in (False, True):
            priced = dgu_pack_rate(g1, g2, argon=argon)
            fill = "Argon" if argon else "Air"
            oid = dgu_pack_id(g1, gap, g2, argon=argon)
            starters.append({
                "makeup": "dgu", "overallMm": overall,
                "glass1Mm": g1, "airGapMm": gap, "glass2Mm": g2,
                "colour": "clear", "toughened": True,
                "name": f"DGU {g1:g}+{gap:g}A+{g2:g} Clear Tuff · {fill}",
                "id": oid,
                "argon": argon, "fillGas": "argon" if argon else "air",
                "rate": priced["rate"], "rateUnit": "sqft",
                "rateBreakdown": priced["rateBreakdown"],
            })
    return starters


def default_product_glass_options() -> list[dict[str, Any]]:
    """Cart / product ``rules/glass.json`` options — shared across window products.

    Includes legacy ids (``5mm_clear``, ``8mm_toughened``, ``10mm_toughened``) so
    existing quotes keep resolving, plus commercial single / laminated / DGU packs
    with absolute ₹/sft rates.
    """
    options: list[dict[str, Any]] = []
    # Legacy-compatible singles first
    options.append({
        "id": "5mm_clear", "label": "5mm Clear", "thicknessMm": 5,
        "makeup": "single", "colour": "clear", "toughened": False, "rateMultiplier": 1.0,
    })
    for thk in (5.0, 6.0, 8.0, 10.0, 12.0):
        oid = f"{int(thk)}mm_toughened" if thk != 5 else "5mm_clear_toughened"
        if thk == 8:
            oid = "8mm_toughened"
        elif thk == 10:
            oid = "10mm_toughened"
        rate = clear_tuff_rate(thk)
        options.append({
            "id": oid, "label": f"{thk:g}mm Clear Toughened", "thicknessMm": thk,
            "makeup": "single", "colour": "clear", "toughened": True,
            "rate": rate, "rateUnit": "sqft", "rateMultiplier": 1.0,
            "densityKgPerM3": 2500,
        })
    for colour in ("black", "grey", "brown"):
        for thk in (5.0, 6.0, 8.0, 10.0, 12.0):
            rate = clear_tuff_rate(thk)
            options.append({
                "id": f"{int(thk)}mm_{colour}_toughened",
                "label": f"{thk:g}mm {colour.title()} Toughened",
                "thicknessMm": thk, "makeup": "single", "colour": colour,
                "toughened": True, "rate": rate, "rateUnit": "sqft",
                "rateMultiplier": 1.0, "densityKgPerM3": 2500,
            })
    for pack in COMMERCIAL_LAM_PACKS:
        g1, pvb, g2 = float(pack["g1"]), float(pack["pvb"]), float(pack["g2"])
        overall = round(g1 + pvb + g2, 2)
        if overall > LAMINATED_MAX_OVERALL_MM + 1e-6:
            continue
        priced = laminated_pack_rate(g1, g2)
        oid = lam_pack_id(g1, pvb, g2)
        options.append({
            "id": oid,
            "label": f"Laminated {g1:g}+{pvb:g}+{g2:g} Clear Tuff",
            "thicknessMm": overall, "overallMm": overall,
            "makeup": "laminated", "glass1Mm": g1, "pvbMm": pvb, "glass2Mm": g2,
            "colour": "clear", "toughened": True,
            "rate": priced["rate"], "rateUnit": "sqft",
            "rateBreakdown": priced["rateBreakdown"],
            "rateMultiplier": 1.0, "densityKgPerM3": 2500,
        })
    for pack in COMMERCIAL_DGU_PACKS:
        g1, gap, g2 = float(pack["g1"]), float(pack["gap"]), float(pack["g2"])
        overall = round(g1 + gap + g2, 2)
        if overall > DGU_MAX_OVERALL_MM + 1e-6:
            continue
        if clear_tuff_rate(g1) is None or clear_tuff_rate(g2) is None:
            continue
        for argon in (False, True):
            priced = dgu_pack_rate(g1, g2, argon=argon)
            fill = "Argon" if argon else "Air"
            oid = dgu_pack_id(g1, gap, g2, argon=argon)
            options.append({
                "id": oid,
                "label": f"DGU {g1:g}+{gap:g}A+{g2:g} Clear Tuff · {fill}",
                "thicknessMm": overall, "overallMm": overall, "makeup": "dgu",
                "glass1Mm": g1, "airGapMm": gap, "glass2Mm": g2,
                "colour": "clear", "toughened": True,
                "argon": argon, "fillGas": "argon" if argon else "air",
                "rate": priced["rate"], "rateUnit": "sqft",
                "rateBreakdown": priced["rateBreakdown"],
                "rateMultiplier": 1.0, "densityKgPerM3": 2500,
            })
    return options


def library_as_cart_options() -> list[dict[str, Any]]:
    """Map Glass Library specs into cart-select options (id + label + makeup fields)."""
    out: list[dict[str, Any]] = []
    for g in list_glass():
        if not isinstance(g, Mapping):
            continue
        gid = str(g.get("id") or "").strip()
        if not gid:
            continue
        out.append({
            "id": gid,
            "label": g.get("name") or g.get("specLine") or gid,
            "name": g.get("name"),
            "display_label": g.get("display_label"),
            "thicknessMm": g.get("thicknessMm") or g.get("overallMm"),
            "overallMm": g.get("overallMm"),
            "makeup": g.get("makeup") or "single",
            "glass1Mm": g.get("glass1Mm"),
            "glass2Mm": g.get("glass2Mm"),
            "glass3Mm": g.get("glass3Mm"),
            "airGapMm": g.get("airGapMm"),
            "pvbMm": g.get("pvbMm"),
            "colour": g.get("colour") or "clear",
            "toughened": bool(g.get("toughened")),
            "brand": g.get("brand") or "",
            "argon": bool(g.get("argon")),
            "fillGas": g.get("fillGas") or "",
            "rate": g.get("rate"),
            "rateUnit": g.get("rateUnit") or "sqft",
            "rateBreakdown": g.get("rateBreakdown"),
            "densityKgPerM3": g.get("densityKgPerM3") or 2500,
            "rateMultiplier": 1.0,
        })
    return out


def cart_glass_options(*, merge_library: bool = True) -> list[dict[str, Any]]:
    """Canonical cart list: product defaults, then any extra Glass Library entries."""
    by_id: dict[str, dict[str, Any]] = {}
    for opt in default_product_glass_options():
        by_id[str(opt["id"])] = opt
    if merge_library:
        for opt in library_as_cart_options():
            oid = str(opt["id"])
            if oid not in by_id:
                by_id[oid] = opt
            else:
                # Library rate / brand / pack metadata wins when present
                merged = dict(by_id[oid])
                for k in (
                    "rate", "rateUnit", "brand", "label", "name", "rateBreakdown",
                    "argon", "fillGas", "glass1Mm", "glass2Mm", "airGapMm", "pvbMm",
                    "overallMm", "thicknessMm", "makeup", "toughened",
                ):
                    if opt.get(k) not in (None, ""):
                        merged[k if k != "name" else "label"] = opt[k]
                by_id[oid] = merged
    return list(by_id.values())


def sync_glass_options_to_products(
    *,
    product_ids: list[str] | None = None,
    merge_library: bool = True,
) -> dict[str, Any]:
    """Write the shared glass options list into each window product's ``rules/glass.json``.

    Stub / window catalogue products without a glass file get a new one (options only).
    Existing glass.json keeps engineering overlaps/density and only replaces ``options``.
    Railing / facade stubs that do not use window glass are skipped.
    """
    from WEOS.paths import products_dir

    skip_types = {
        "railing", "staircase_railing", "railings_stub", "pergolas", "pergola_stub",
        "acp_stub", "fluted_stub", "perforated_stub", "louvers_stub",
    }
    options = cart_glass_options(merge_library=merge_library)
    root = products_dir()
    updated: list[str] = []
    skipped: list[str] = []
    targets = product_ids
    if not targets:
        targets = [p.name for p in root.iterdir() if p.is_dir() and (p / "product.json").is_file()]
    for pid in targets:
        pdir = root / pid
        meta_path = pdir / "product.json"
        if not meta_path.is_file():
            skipped.append(pid)
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            skipped.append(pid)
            continue
        ptype = str(meta.get("productType") or pid).lower()
        cat = str(meta.get("category") or "").lower()
        # Sync window/door glass products; skip railing / facade / pergola worlds.
        if ptype in skip_types or cat in ("railings", "facades", "pergolas"):
            skipped.append(pid)
            continue
        rules_dir = pdir / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        glass_path = rules_dir / "glass.json"
        if glass_path.is_file():
            try:
                glass_doc = json.loads(glass_path.read_text(encoding="utf-8-sig"))
            except Exception:
                glass_doc = {}
            if not isinstance(glass_doc, dict):
                glass_doc = {}
        else:
            glass_doc = {
                "thicknessMm": 5,
                "densityKgPerM3": 2500,
                "quantityFormula": "shutterCount",
            }
        glass_doc["options"] = options
        glass_path.write_text(json.dumps(glass_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        updated.append(pid)
    return {
        "ok": True,
        "updated": updated,
        "skipped": skipped,
        "optionCount": len(options),
    }


def seed_default_glass(*, force: bool = False, sync_products: bool = True) -> dict[str, Any]:
    """Preload the full glass catalogue into the library (and sync product options).

    When the library was previously seeded with a small starter set, missing
    entries are still added. Commercial rates / pack metadata are always
    refreshed on matching starter ids (unless the user cleared the rate and
    ``force`` is False — then only blank rates get filled). Pass ``force=True``
    to rewrite every starter id.
    """
    existing_by_id = {str(g.get("id")): g for g in list_glass() if g.get("id")}
    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    for s in _starter_glass_specs():
        sid = str(s.get("id") or "")
        if not sid:
            continue
        existing = existing_by_id.get(sid)
        if existing is not None and not force:
            # Refresh commercial rate / pack fields; keep user name if customised.
            merged = dict(existing)
            for k in (
                "rate", "rateUnit", "rateBreakdown", "argon", "fillGas",
                "glass1Mm", "glass2Mm", "glass3Mm", "airGapMm", "pvbMm",
                "overallMm", "thicknessMm", "makeup", "toughened", "colour",
            ):
                if s.get(k) is not None:
                    # Don't overwrite a user-edited rate unless force
                    if k == "rate" and existing.get("rate") not in (None, "") and not force:
                        # Still upgrade when prior seed left rate null
                        if existing.get("rate") is not None:
                            continue
                    merged[k] = s[k]
            if s.get("name") and (
                not existing.get("name")
                or str(existing.get("name")).startswith(("DGU ", "Laminated ", f"{int(float(s.get('thicknessMm') or 0))}mm"))
            ):
                merged["name"] = s["name"]
            # Always apply computed commercial rate when seed has one and existing is blank
            if s.get("rate") is not None and (force or existing.get("rate") in (None, "")):
                merged["rate"] = s["rate"]
                merged["rateUnit"] = s.get("rateUnit") or "sqft"
                if s.get("rateBreakdown"):
                    merged["rateBreakdown"] = s["rateBreakdown"]
            # Also apply when force or when rates look like pre-commercial (null)
            if force or existing.get("rate") in (None, ""):
                try:
                    updated.append(save_glass(merged)["id"])
                except Exception:
                    skipped.append(sid)
            else:
                # Even with an existing rate, refresh pack metadata + commercial formula rates
                merged["rate"] = s.get("rate", existing.get("rate"))
                if s.get("rateBreakdown"):
                    merged["rateBreakdown"] = s["rateBreakdown"]
                if s.get("argon") is not None:
                    merged["argon"] = s["argon"]
                if s.get("fillGas"):
                    merged["fillGas"] = s["fillGas"]
                try:
                    updated.append(save_glass(merged)["id"])
                except Exception:
                    skipped.append(sid)
            continue
        try:
            created.append(save_glass(s)["id"])
        except Exception:
            continue
    result: dict[str, Any] = {
        "ok": True,
        "seeded": created,
        "updated": updated,
        "skipped": skipped,
        "count": len(created),
        "libraryCount": len(list_glass()),
        "commercial": {
            "clearTuffRates": CLEAR_TUFF_RATE_PER_SFT,
            "dguChargePerSft": DGU_CHARGE_PER_SFT,
            "argonChargePerSft": ARGON_CHARGE_PER_SFT,
            "laminationChargePerSft": LAMINATION_CHARGE_PER_SFT,
            "dguMaxMm": DGU_MAX_OVERALL_MM,
            "laminatedMaxMm": LAMINATED_MAX_OVERALL_MM,
        },
    }
    if sync_products:
        result["productSync"] = sync_glass_options_to_products(merge_library=True)
    try:
        sentinel = catalogue_dir() / "_seeded.json"
        sentinel.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result


def apply_commercial_glass_defaults(*, sync_products: bool = True) -> dict[str, Any]:
    """Force-write commercial single / DGU / laminated pack rates into the library."""
    return seed_default_glass(force=True, sync_products=sync_products)
