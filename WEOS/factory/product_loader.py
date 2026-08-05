"""Product rule loader — merges products/<id>/rules/*.json into one engineering doc.

Engineering knowledge lives ONLY in product JSON rules — never in Python.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import PACKAGE_ROOT, products_dir

WEOS_ROOT = PACKAGE_ROOT
PRODUCTS_DIR = products_dir()
DEFAULT_PRODUCT_ID = "29mm_sliding"

RULE_FILES = {
    "geometry": "geometry",
    "glass": "glass",
    "hardware": "hardware",
    "brush": "brush",
    "track_rail": "trackRail",
    "cutlist": "cutList",
    "weight": "weight",
    "quotation": "quotation",
    "dimensioning": "dimensioning",
    "bom_extras": "bomExtras",
    "pricing": "pricing",
    "provenance": "_provenance",
}

REQUIRED_SECTIONS = (
    "geometry",
    "glass",
    "hardware",
    "brush",
    "trackRail",
    "cutList",
    "weight",
    "quotation",
    "dimensioning",
    "bomExtras",
)

# Aliases for engines that still say "profile"
PROFILES_DIR = PRODUCTS_DIR
DEFAULT_PROFILE_ID = DEFAULT_PRODUCT_ID

_OVERRIDE_MAP: dict[str, tuple[str, str]] = {
    "trackWidth": ("geometry", "trackWidth"),
    "track_width": ("geometry", "trackWidth"),
    "frameWidth": ("geometry", "frameWidth"),
    "frame_width": ("geometry", "frameWidth"),
    "shutter_frame": ("geometry", "frameWidth"),
    "shutterFrame": ("geometry", "frameWidth"),
    "interlockWidth": ("geometry", "interlockWidth"),
    "interlock_width": ("geometry", "interlockWidth"),
    "overlap": ("geometry", "overlap"),
    "glassClip": ("geometry", "glassClip"),
    "glass_clip": ("geometry", "glassClip"),
    "trackCount": ("geometry", "trackCount"),
    "track_count": ("geometry", "trackCount"),
    "shutterCount": ("geometry", "shutterCount"),
    "shutter_count": ("geometry", "shutterCount"),
    "meetingGap": ("geometry", "meetingGap"),
    "meeting_gap": ("geometry", "meetingGap"),
    "handleSideOverlap": ("glass", "handleSideOverlap"),
    "interlockSideOverlap": ("glass", "interlockSideOverlap"),
    "topOverlap": ("glass", "topOverlap"),
    "bottomOverlap": ("glass", "bottomOverlap"),
    "thicknessMm": ("glass", "thicknessMm"),
    "densityKgPerM3": ("glass", "densityKgPerM3"),
    "arrowSize": ("dimensioning", "arrowSize"),
    "arrow_size": ("dimensioning", "arrowSize"),
    "textHeight": ("dimensioning", "textHeight"),
    "text_height": ("dimensioning", "textHeight"),
    "offsetOuter": ("dimensioning", "offsetOuter"),
    "offset_outer": ("dimensioning", "offsetOuter"),
    "offsetInner": ("dimensioning", "offsetInner"),
    "offset_inner": ("dimensioning", "offsetInner"),
    "offsetDetail": ("dimensioning", "offsetDetail"),
    "offset_detail": ("dimensioning", "offsetDetail"),
    "stackGap": ("dimensioning", "stackGap"),
    "stack_gap": ("dimensioning", "stackGap"),
}


def product_dir(product_id: str) -> Path:
    d = PRODUCTS_DIR / product_id.replace(".json", "")
    if not d.is_dir():
        known = sorted(p.name for p in PRODUCTS_DIR.iterdir() if p.is_dir()) if PRODUCTS_DIR.is_dir() else []
        raise FileNotFoundError(f"Product '{product_id}' not found. Known: {', '.join(known) or '(none)'}")
    return d


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def list_products() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not PRODUCTS_DIR.is_dir():
        return out
    for d in sorted(PRODUCTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "product.json"
        if meta_path.is_file():
            meta = _read_json(meta_path)
            out.append((meta.get("id", d.name), meta.get("displayName", d.name)))
        else:
            out.append((d.name, d.name))
    return out


def list_profiles() -> list[tuple[str, str]]:
    return list_products()


def profile_path(profile_id: str) -> Path:
    return product_dir(profile_id)


def validate_profile_sections(data: Mapping[str, Any], *, path: str | Path = "") -> list[str]:
    issues = [s for s in REQUIRED_SECTIONS if s not in data]
    if "quotation" in data:
        rates = (data.get("quotation") or {}).get("rates") or {}
        if "hardwareLumpSum" in rates:
            issues.append("quotation.rates must NOT contain hardwareLumpSum")
    return issues


def load_product(product_id: str | Path | None = None, *, strict: bool = True) -> dict[str, Any]:
    """Load and merge product.json + rules/*.json into a single engineering document."""
    if isinstance(product_id, Path):
        data = json.loads(product_id.read_text(encoding="utf-8"))
        data["_path"] = str(product_id)
        return copy.deepcopy(data)

    pid = DEFAULT_PRODUCT_ID if product_id is None else str(product_id).replace(".json", "")
    pdir = product_dir(pid)
    meta_path = pdir / "product.json"
    doc: dict[str, Any] = {}
    if meta_path.is_file():
        doc.update(_read_json(meta_path))
    else:
        doc["id"] = pid

    rules_dir = pdir / "rules"
    if rules_dir.is_dir():
        for stem, section in RULE_FILES.items():
            path = rules_dir / f"{stem}.json"
            if path.is_file():
                doc[section] = _read_json(path)

    is_stub = str(doc.get("status", "")).lower() == "stub" or bool((doc.get("quotation") or {}).get("stub"))
    if strict and not is_stub:
        missing = validate_profile_sections(doc)
        if missing:
            raise ValueError(f"Product {pid} missing/invalid sections: {', '.join(missing)}")
    doc["_stub"] = is_stub

    doc["_path"] = str(pdir)
    doc["_product_dir"] = str(pdir)
    return copy.deepcopy(doc)


def load_profile(profile_id: str | Path | None = None, *, strict: bool = True) -> dict[str, Any]:
    return load_product(profile_id, strict=strict)


def apply_geometry_overrides(profile: dict[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    doc = copy.deepcopy(profile)
    if not overrides:
        return doc
    for raw_key, value in overrides.items():
        if value is None:
            continue
        key = str(raw_key).strip()
        section: str | None = None
        leaf: str | None = None
        if "." in key:
            section, leaf = key.split(".", 1)
            section = {"geom": "geometry", "dim": "dimensioning"}.get(section, section)
            mapped = _OVERRIDE_MAP.get(leaf)
            if mapped:
                section, leaf = mapped
        elif key in _OVERRIDE_MAP:
            section, leaf = _OVERRIDE_MAP[key]
        if not section or not leaf:
            continue
        block = dict(doc.get(section) or {})
        block[leaf] = float(value)
        doc[section] = block
    return doc


def geometry_as_engine_dict(profile: Mapping[str, Any]) -> dict[str, float]:
    g = profile.get("geometry") or {}
    required = ("trackWidth", "frameWidth", "interlockWidth", "overlap", "glassClip", "trackCount", "shutterCount")
    missing = [k for k in required if k not in g]
    if missing:
        raise KeyError(f"geometry missing keys: {', '.join(missing)}")
    return {
        "track_width": float(g["trackWidth"]),
        "shutter_frame": float(g["frameWidth"]),
        "interlock_width": float(g["interlockWidth"]),
        "overlap": float(g["overlap"]),
        "glass_clip": float(g["glassClip"]),
        "track_count": float(g["trackCount"]),
        "shutter_count": float(g["shutterCount"]),
        "meeting_gap": float(g.get("meetingGap", 0)),
    }


def apply_customer_options(
    product: dict[str, Any],
    *,
    glass: str | None = None,
    colour: str | None = None,
    handle: str | None = None,
) -> dict[str, Any]:
    """Apply website options (glass type, colour, handle) onto engineering + commercial rules."""
    doc = copy.deepcopy(product)
    glass_rules = dict(doc.get("glass") or {})
    options = list(glass_rules.pop("options", None) or [])
    if glass:
        match = next((o for o in options if o.get("id") == glass or o.get("label") == glass), None)
        if not match:
            # fuzzy: "8mm Toughened" → 8mm_toughened
            gnorm = glass.lower().replace(" ", "_")
            match = next((o for o in options if o.get("id") == gnorm), None)
        if match:
            if "thicknessMm" in match:
                glass_rules["thicknessMm"] = match["thicknessMm"]
            if "densityKgPerM3" in match:
                glass_rules["densityKgPerM3"] = match["densityKgPerM3"]
            glass_rules["_selectedOption"] = match.get("id", glass)
            glass_rules["_rateMultiplier"] = float(match.get("rateMultiplier", 1.0))
    # keep options list for API meta (not used by glass_engine numeric keys)
    glass_rules["options"] = options
    doc["glass"] = glass_rules

    hw = copy.deepcopy(doc.get("hardware") or [])
    handle_id = (handle or "standard").lower().replace(" ", "_")
    for item in hw:
        if item.get("optionKey") == "handle" and isinstance(item.get("variants"), dict):
            variant = item["variants"].get(handle_id) or item["variants"].get("standard")
            if variant:
                item["unitRate"] = float(variant.get("unitRate", item.get("unitRate", 0)))
                item["remarks"] = f"Handle: {variant.get('label', handle_id)}"
    doc["hardware"] = hw

    quote = dict(doc.get("quotation") or {})
    pricing = doc.get("pricing") or {}
    surcharges = pricing.get("colourSurchargePercent") or quote.get("colourSurchargePercent") or {}
    colour_id = (colour or "white").lower().replace(" ", "_")
    quote["_colour"] = colour_id
    quote["_colourSurchargePercent"] = float(surcharges.get(colour_id, 0))
    mult = float(glass_rules.get("_rateMultiplier", 1.0))
    rates = dict(quote.get("rates") or {})
    if "glassPerM2" in rates:
        rates["glassPerM2"] = float(rates["glassPerM2"]) * mult
    quote["rates"] = rates
    # merge colour surcharge into quotation file if present in pricing
    if "colourSurchargePercent" in pricing:
        quote["colourSurchargePercent"] = pricing["colourSurchargePercent"]
    doc["quotation"] = quote
    doc["_options"] = {"glass": glass, "colour": colour_id, "handle": handle_id}
    return doc
