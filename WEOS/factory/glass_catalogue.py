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

# DGU overall thickness → default layer makeup (glass / air gap / glass) in mm.
DGU_MAKEUPS_MM: dict[float, dict[str, float]] = {
    18.0: {"glass1Mm": 5.0, "airGapMm": 8.0, "glass2Mm": 5.0},
    20.0: {"glass1Mm": 6.0, "airGapMm": 8.0, "glass2Mm": 6.0},
    22.0: {"glass1Mm": 6.0, "airGapMm": 10.0, "glass2Mm": 6.0},
    24.0: {"glass1Mm": 6.0, "airGapMm": 12.0, "glass2Mm": 6.0},
    28.0: {"glass1Mm": 8.0, "airGapMm": 12.0, "glass2Mm": 8.0},
    30.0: {"glass1Mm": 8.0, "airGapMm": 14.0, "glass2Mm": 8.0},
}

# Laminated overall thickness → default makeup (glass + PVB + glass) in mm.
LAMINATED_MAKEUPS_MM: dict[float, dict[str, float]] = {
    11.52: {"glass1Mm": 5.0, "pvbMm": 1.52, "glass2Mm": 5.0},
    13.52: {"glass1Mm": 6.0, "pvbMm": 1.52, "glass2Mm": 6.0},
}


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
            "overallMm": sorted(DGU_MAKEUPS_MM.keys()),
            "makeups": {str(k): v for k, v in DGU_MAKEUPS_MM.items()},
            "label": "DGU (double glazed unit)",
            "note": "Choose which glass on each side + air gap; layers configurable.",
        },
        "laminated": {
            "overallMm": sorted(LAMINATED_MAKEUPS_MM.keys()),
            "makeups": {str(k): v for k, v in LAMINATED_MAKEUPS_MM.items()},
            "label": "Laminated (PVB)",
            "note": "Two glass leaves + PVB interlayer thickness.",
        },
        "colours": ["clear", "green", "blue", "grey", "bronze", "black", "reflective", "frosted"],
        "toughened": [True, False],
        "rateUnits": ["sqft", "sqm"],
    }


def default_layers_for(makeup: str, overall_mm: float | None) -> dict[str, float]:
    kind = (makeup or "single").strip().lower()
    if kind in ("dgu", "double", "insulated") and overall_mm in DGU_MAKEUPS_MM:
        return dict(DGU_MAKEUPS_MM[overall_mm])
    if kind in ("laminated", "lami") and overall_mm in LAMINATED_MAKEUPS_MM:
        return dict(LAMINATED_MAKEUPS_MM[overall_mm])
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
    colour: str = "clear",
    brand: str = "",
    toughened: bool = False,
    rate: float | None = None,
    rate_unit: str = "sqft",
    density: float = 2500.0,
    name: str | None = None,
    glass_id: str | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    """Normalize a full glass spec (single / DGU / laminated) for reuse + printing."""
    kind = (makeup or "single").strip().lower()
    layers = default_layers_for(kind, overall_mm)
    g1 = glass1_mm if glass1_mm is not None else layers.get("glass1Mm")
    g2 = glass2_mm if glass2_mm is not None else layers.get("glass2Mm")
    gap = air_gap_mm if air_gap_mm is not None else layers.get("airGapMm")
    pvb = pvb_mm if pvb_mm is not None else layers.get("pvbMm")

    if kind in ("dgu", "double", "insulated"):
        thickness_mm = overall_mm or ((g1 or 0) + (gap or 0) + (g2 or 0))
        makeup_label = f"{g1:g}+{gap:g}A+{g2:g}" if g1 and gap and g2 else f"DGU {thickness_mm:g}mm"
        layers_mm = [g1 or 0, g2 or 0]
    elif kind in ("laminated", "lami"):
        thickness_mm = overall_mm or ((g1 or 0) + (pvb or 0) + (g2 or 0))
        makeup_label = f"{g1:g}+{pvb:g}PVB+{g2:g}" if g1 and pvb and g2 else f"Laminated {thickness_mm:g}mm"
        layers_mm = [g1 or 0, g2 or 0]
    else:
        kind = "single"
        thickness_mm = thickness_mm or overall_mm or 5.0
        makeup_label = f"{thickness_mm:g}mm"
        layers_mm = [thickness_mm]

    tuff = "Toughened" if toughened else "Non-toughened"
    display = name or (
        f"{makeup_label} {colour.title()} {tuff}"
        + (f" · {brand}" if brand else "")
    ).strip()

    gid = glass_id or f"glass_{_slug(kind)}_{_slug(colour)}_{int(round((thickness_mm or 0) * 100))}"
    return {
        "id": gid,
        "name": display,
        "makeup": kind,
        "thicknessMm": round(float(thickness_mm or 0), 2),
        "overallMm": round(float(thickness_mm or 0), 2),
        "glass1Mm": g1,
        "glass2Mm": g2,
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
        "specLine": _spec_line(display, makeup_label, colour, tuff, brand, rate, rate_unit),
        "status": status,
        "updatedAt": _now(),
    }


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
    normalized = build_glass_spec(
        makeup=str(spec.get("makeup") or "single"),
        thickness_mm=spec.get("thicknessMm"),
        overall_mm=spec.get("overallMm"),
        glass1_mm=spec.get("glass1Mm"),
        glass2_mm=spec.get("glass2Mm"),
        air_gap_mm=spec.get("airGapMm"),
        pvb_mm=spec.get("pvbMm"),
        colour=str(spec.get("colour") or "clear"),
        brand=str(spec.get("brand") or ""),
        toughened=bool(spec.get("toughened")),
        rate=spec.get("rate"),
        rate_unit=str(spec.get("rateUnit") or "sqft"),
        density=float(spec.get("densityKgPerM3") or 2500.0),
        name=spec.get("name"),
        glass_id=spec.get("id") or f"glass_{uuid.uuid4().hex[:8]}",
        status=str(spec.get("status") or "active"),
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


def seed_default_glass(*, force: bool = False) -> dict[str, Any]:
    """Preload a starter set of common glass options into the library."""
    sentinel = catalogue_dir() / "_seeded.json"
    if sentinel.is_file() and not force:
        try:
            return json.loads(sentinel.read_text(encoding="utf-8"))
        except Exception:
            pass
    created: list[str] = []
    starters = [
        {"makeup": "single", "thicknessMm": 5.0, "colour": "clear", "toughened": False},
        {"makeup": "single", "thicknessMm": 8.0, "colour": "clear", "toughened": True},
        {"makeup": "dgu", "overallMm": 24.0, "colour": "clear", "toughened": True},
        {"makeup": "laminated", "overallMm": 11.52, "colour": "clear", "toughened": False},
    ]
    for s in starters:
        try:
            created.append(save_glass(s)["id"])
        except Exception:
            continue
    result = {"ok": True, "seeded": created, "count": len(created)}
    try:
        sentinel.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result
