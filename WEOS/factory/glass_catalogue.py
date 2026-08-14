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
# Keys are overall mm; makeupLabel uses glass+air+glass (e.g. 5+12A+5).
DGU_MAKEUPS_MM: dict[float, dict[str, float]] = {
    18.0: {"glass1Mm": 5.0, "airGapMm": 8.0, "glass2Mm": 5.0},
    20.0: {"glass1Mm": 6.0, "airGapMm": 8.0, "glass2Mm": 6.0},
    22.0: {"glass1Mm": 5.0, "airGapMm": 12.0, "glass2Mm": 5.0},  # 5+12A+5
    24.0: {"glass1Mm": 6.0, "airGapMm": 12.0, "glass2Mm": 6.0},  # 6+12A+6
    26.0: {"glass1Mm": 6.0, "airGapMm": 14.0, "glass2Mm": 6.0},
    28.0: {"glass1Mm": 8.0, "airGapMm": 12.0, "glass2Mm": 8.0},  # 8+12A+8
    30.0: {"glass1Mm": 8.0, "airGapMm": 14.0, "glass2Mm": 8.0},
    32.0: {"glass1Mm": 10.0, "airGapMm": 12.0, "glass2Mm": 10.0},  # 10+12A+10
}

# Laminated overall thickness → default makeup (glass + PVB + glass) in mm.
LAMINATED_MAKEUPS_MM: dict[float, dict[str, float]] = {
    11.52: {"glass1Mm": 5.0, "pvbMm": 1.52, "glass2Mm": 5.0},   # 5+1.52+5
    12.52: {"glass1Mm": 6.0, "pvbMm": 1.52, "glass2Mm": 5.0},   # 6+1.52+5
    13.52: {"glass1Mm": 6.0, "pvbMm": 1.52, "glass2Mm": 6.0},   # 6+1.52+6
    15.52: {"glass1Mm": 8.0, "pvbMm": 1.52, "glass2Mm": 6.0},   # 8+1.52+6
    17.52: {"glass1Mm": 8.0, "pvbMm": 1.52, "glass2Mm": 8.0},   # 8+1.52+8
}

# Tinted colours commonly offered on single toughened panes (cart + railing).
TINTED_COLOURS = ("clear", "black", "grey", "brown")


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
    if kind in ("laminated", "lami") and g1 and pvb and g2:
        display_label = f"{g1:g}+{pvb:g}+{g2:g} mm Laminated"
    elif kind in ("dgu", "double", "insulated") and g1 and gap and g2:
        display_label = f"{g1:g}+{gap:g}A+{g2:g} mm DGU"
    else:
        display_label = f"{float(thickness_mm or 0):g} mm"
        if toughened:
            display_label += " Toughened"
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
        "display_label": display_label,
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


def _starter_glass_specs() -> list[dict[str, Any]]:
    """Full default catalogue: single clear/tinted, laminated safety, DGU/IGU."""
    starters: list[dict[str, Any]] = []
    # Single clear (annealed 5) + toughened clear at common thicknesses
    starters.append({
        "makeup": "single", "thicknessMm": 5.0, "colour": "clear", "toughened": False,
        "name": "5mm Clear", "id": "5mm_clear",
    })
    for thk in (5.0, 6.0, 8.0, 10.0, 12.0):
        starters.append({
            "makeup": "single", "thicknessMm": thk, "colour": "clear", "toughened": True,
            "name": f"{thk:g}mm Clear Toughened",
            "id": f"{int(thk)}mm_toughened" if thk != 5 else "5mm_clear_toughened",
        })
    # Single tinted toughened (black / grey / brown) at 5–12 mm
    for colour in ("black", "grey", "brown"):
        for thk in (5.0, 6.0, 8.0, 10.0, 12.0):
            starters.append({
                "makeup": "single", "thicknessMm": thk, "colour": colour, "toughened": True,
                "name": f"{thk:g}mm {colour.title()} Toughened",
                "id": f"{int(thk)}mm_{colour}_toughened",
            })
    # Fluted toughened (shower + custom)
    for colour in ("clear", "grey", "brown"):
        for thk in (5.0, 8.0):
            starters.append({
                "makeup": "single", "thicknessMm": thk, "colour": colour, "toughened": True,
                "name": f"{thk:g}mm Fluted {colour.title()} Toughened",
                "id": f"fluted_{int(thk)}_{colour}_tuff",
            })
    # Laminated safety
    for overall, g1, pvb, g2, oid, label in (
        (11.52, 5.0, 1.52, 5.0, "lam_5_152_5", "Laminated 5+1.52+5"),
        (12.52, 6.0, 1.52, 5.0, "lam_6_152_5", "Laminated 6+1.52+5"),
        (13.52, 6.0, 1.52, 6.0, "lam_6_152_6", "Laminated 6+1.52+6"),
        (15.52, 8.0, 1.52, 6.0, "lam_8_152_6", "Laminated 8+1.52+6"),
        (17.52, 8.0, 1.52, 8.0, "lam_8_152_8", "Laminated 8+1.52+8"),
    ):
        starters.append({
            "makeup": "laminated", "overallMm": overall,
            "glass1Mm": g1, "pvbMm": pvb, "glass2Mm": g2,
            "colour": "clear", "toughened": False,
            "name": label, "id": oid,
        })
    # DGU / IGU typical build-ups
    for overall, g1, gap, g2, oid, label in (
        (22.0, 5.0, 12.0, 5.0, "dgu_5_12_5", "DGU 5+12A+5"),
        (24.0, 6.0, 12.0, 6.0, "dgu_6_12_6", "DGU 6+12A+6"),
        (28.0, 8.0, 12.0, 8.0, "dgu_8_12_8", "DGU 8+12A+8"),
        (32.0, 10.0, 12.0, 10.0, "dgu_10_12_10", "DGU 10+12A+10"),
        (18.0, 5.0, 8.0, 5.0, "dgu_5_8_5", "DGU 5+8A+5"),
    ):
        starters.append({
            "makeup": "dgu", "overallMm": overall,
            "glass1Mm": g1, "airGapMm": gap, "glass2Mm": g2,
            "colour": "clear", "toughened": True,
            "name": f"{label} Clear Toughened", "id": oid,
        })
    return starters


def default_product_glass_options() -> list[dict[str, Any]]:
    """Cart / product ``rules/glass.json`` options — shared across window products.

    Includes legacy ids (``5mm_clear``, ``8mm_toughened``, ``10mm_toughened``) so
    existing quotes keep resolving, plus the expanded single / laminated / DGU set.
    """
    options: list[dict[str, Any]] = []
    # Legacy-compatible singles first
    options.append({
        "id": "5mm_clear", "label": "5mm Clear", "thicknessMm": 5,
        "makeup": "single", "colour": "clear", "toughened": False, "rateMultiplier": 1.0,
    })
    for thk, mult in ((5, 1.15), (6, 1.25), (8, 1.45), (10, 1.75), (12, 2.1)):
        oid = f"{thk}mm_toughened" if thk != 5 else "5mm_clear_toughened"
        # Keep classic 8mm_toughened / 10mm_toughened ids
        if thk == 8:
            oid = "8mm_toughened"
        elif thk == 10:
            oid = "10mm_toughened"
        options.append({
            "id": oid, "label": f"{thk}mm Clear Toughened", "thicknessMm": thk,
            "makeup": "single", "colour": "clear", "toughened": True,
            "rateMultiplier": mult, "densityKgPerM3": 2500,
        })
    for colour, base in (("black", 1.2), ("grey", 1.18), ("brown", 1.18)):
        for thk, bump in ((5, 0.0), (6, 0.1), (8, 0.3), (10, 0.55), (12, 0.9)):
            options.append({
                "id": f"{thk}mm_{colour}_toughened",
                "label": f"{thk}mm {colour.title()} Toughened",
                "thicknessMm": thk, "makeup": "single", "colour": colour,
                "toughened": True, "rateMultiplier": round(base + bump, 2),
                "densityKgPerM3": 2500,
            })
    for oid, label, g1, pvb, g2, overall, mult in (
        ("lam_5_152_5", "Laminated 5+1.52+5", 5, 1.52, 5, 11.52, 2.2),
        ("lam_6_152_5", "Laminated 6+1.52+5", 6, 1.52, 5, 12.52, 2.4),
        ("lam_6_152_6", "Laminated 6+1.52+6", 6, 1.52, 6, 13.52, 2.55),
        ("lam_8_152_6", "Laminated 8+1.52+6", 8, 1.52, 6, 15.52, 2.8),
        ("lam_8_152_8", "Laminated 8+1.52+8", 8, 1.52, 8, 17.52, 3.0),
    ):
        options.append({
            "id": oid, "label": label, "thicknessMm": overall, "overallMm": overall,
            "makeup": "laminated", "glass1Mm": g1, "pvbMm": pvb, "glass2Mm": g2,
            "colour": "clear", "toughened": False, "rateMultiplier": mult,
            "densityKgPerM3": 2500,
        })
    for oid, label, g1, gap, g2, overall, mult in (
        ("dgu_5_12_5", "DGU 5+12A+5", 5, 12, 5, 22, 2.6),
        ("dgu_6_12_6", "DGU 6+12A+6", 6, 12, 6, 24, 2.9),
        ("dgu_8_12_8", "DGU 8+12A+8", 8, 12, 8, 28, 3.4),
        ("dgu_10_12_10", "DGU 10+12A+10", 10, 12, 10, 32, 3.9),
        ("dgu_5_8_5", "DGU 5+8A+5", 5, 8, 5, 18, 2.35),
    ):
        options.append({
            "id": oid, "label": f"{label} Clear Toughened", "thicknessMm": overall,
            "overallMm": overall, "makeup": "dgu",
            "glass1Mm": g1, "airGapMm": gap, "glass2Mm": g2,
            "colour": "clear", "toughened": True, "rateMultiplier": mult,
            "densityKgPerM3": 2500,
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
            "thicknessMm": g.get("thicknessMm") or g.get("overallMm"),
            "overallMm": g.get("overallMm"),
            "makeup": g.get("makeup") or "single",
            "glass1Mm": g.get("glass1Mm"),
            "glass2Mm": g.get("glass2Mm"),
            "airGapMm": g.get("airGapMm"),
            "pvbMm": g.get("pvbMm"),
            "colour": g.get("colour") or "clear",
            "toughened": bool(g.get("toughened")),
            "brand": g.get("brand") or "",
            "rate": g.get("rate"),
            "rateUnit": g.get("rateUnit") or "sqft",
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
                # Library rate / brand wins when present
                merged = dict(by_id[oid])
                for k in ("rate", "rateUnit", "brand", "label", "name"):
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
    entries are still added (unless ``force`` rewrites every starter id).
    """
    existing_ids = {str(g.get("id")) for g in list_glass()}
    created: list[str] = []
    skipped: list[str] = []
    for s in _starter_glass_specs():
        sid = str(s.get("id") or "")
        if sid and sid in existing_ids and not force:
            skipped.append(sid)
            continue
        try:
            created.append(save_glass(s)["id"])
        except Exception:
            continue
    result: dict[str, Any] = {
        "ok": True,
        "seeded": created,
        "skipped": skipped,
        "count": len(created),
        "libraryCount": len(list_glass()),
    }
    if sync_products:
        result["productSync"] = sync_glass_options_to_products(merge_library=True)
    try:
        sentinel = catalogue_dir() / "_seeded.json"
        sentinel.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result
