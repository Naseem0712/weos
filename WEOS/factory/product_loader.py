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
    # Data folders (sections/, etc.) are not selectable products — only dirs with product.json.
    for d in sorted(PRODUCTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "product.json"
        if not meta_path.is_file():
            continue
        meta = _read_json(meta_path)
        out.append((meta.get("id", d.name), meta.get("displayName", d.name)))
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

    # Catalogue / imported products carry no engineering rules, so the geometry
    # engine cannot draw them and the UI falls back to a "Catalogue placeholder".
    # Give them a RENDERABLE definition: borrow the default product's engineering
    # rules and override the frame/interlock/track widths with the imported section
    # sizes. Pricing stays manual (``_stub`` remains True) — this only enables the
    # elevation drawing + glass resolution.
    if pid != DEFAULT_PRODUCT_ID:
        _ensure_renderable(doc)

    doc["_path"] = str(pdir)
    doc["_product_dir"] = str(pdir)
    return copy.deepcopy(doc)


_GEOM_KEYS = ("trackWidth", "frameWidth", "interlockWidth", "overlap", "glassClip", "trackCount", "shutterCount")


def _has_renderable_geometry(doc: Mapping[str, Any]) -> bool:
    g = doc.get("geometry")
    return isinstance(g, Mapping) and all(k in g for k in _GEOM_KEYS)


def _catalogue_width(profiles: Any, usages: tuple[str, ...]) -> float | None:
    """First profile whose usage matches → its face width (or section depth)."""
    if not isinstance(profiles, (list, tuple)):
        return None
    for p in profiles:
        if not isinstance(p, Mapping):
            continue
        u = str(p.get("usage") or "").lower()
        if any(k in u for k in usages):
            for key in ("widthMm", "sectionDepthMm"):
                try:
                    v = float(p.get(key))
                except (TypeError, ValueError):
                    v = 0.0
                if v > 0:
                    return v
    return None


def _catalogue_track_count(cat: Mapping[str, Any] | None, profiles: Any) -> float | None:
    """Prefer explicit catalogue trackCount; else parse from first track profile name."""
    if isinstance(cat, Mapping):
        raw = cat.get("trackCount")
        if raw is not None and str(raw).strip() != "":
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
        opts = cat.get("trackOptions")
        if isinstance(opts, (list, tuple)) and opts:
            try:
                return float(opts[0])
            except (TypeError, ValueError):
                pass
    if not isinstance(profiles, (list, tuple)):
        return None
    try:
        from WEOS.factory.section_catalogue import parse_track_count
    except Exception:
        parse_track_count = None  # type: ignore[assignment]
    for p in profiles:
        if not isinstance(p, Mapping):
            continue
        u = str(p.get("usage") or "").lower()
        if u and not any(k in u for k in ("track", "frame")):
            continue
        tc = p.get("trackCount")
        if tc is None and parse_track_count:
            tc = parse_track_count(p.get("name"))
        if tc is not None:
            try:
                return float(tc)
            except (TypeError, ValueError):
                continue
    return None


def resolve_engine_product_id(doc: Mapping[str, Any] | None, product_id: str | None = None) -> str:
    """Map a catalogue/stub product to a manufacturing engine id when needed."""
    pid = str(product_id or (doc or {}).get("id") or DEFAULT_PRODUCT_ID).replace(".json", "")
    if not isinstance(doc, Mapping):
        return pid
    is_stub = bool(doc.get("_stub") or str(doc.get("status") or "").lower() == "stub")
    if not is_stub and _has_renderable_geometry(doc):
        return pid
    linked = doc.get("linkedProductId") or (doc.get("catalogue") or {}).get("productId")
    if linked:
        return str(linked).replace(".json", "")
    try:
        from WEOS.factory.section_catalogue import SERIES_PRODUCT_MAP

        mapped = SERIES_PRODUCT_MAP.get(pid)
        if mapped:
            return str(mapped)
    except Exception:
        pass
    return pid


_REQUIRED_GLASS_KEYS = (
    "handleSideOverlap",
    "interlockSideOverlap",
    "topOverlap",
    "bottomOverlap",
    "thicknessMm",
    "densityKgPerM3",
)


def _glass_rules_complete(glass: Mapping[str, Any] | None) -> bool:
    if not isinstance(glass, Mapping) or not glass:
        return False
    return all(k in glass for k in _REQUIRED_GLASS_KEYS)


def _ensure_renderable(doc: dict[str, Any]) -> None:
    """Fill missing engineering sections so the geometry engine can draw a
    catalogue/imported product. Mutates ``doc`` in place. Best-effort/no-raise."""
    if _has_renderable_geometry(doc) and _glass_rules_complete(doc.get("glass") if isinstance(doc.get("glass"), Mapping) else None):
        return
    base_id = DEFAULT_PRODUCT_ID
    linked = doc.get("linkedProductId")
    if linked and str(linked) != str(doc.get("id") or ""):
        base_id = str(linked).replace(".json", "")
    try:
        base = load_product(base_id, strict=False)
    except Exception:
        base = {}
    # Linked catalogue stubs often ship incomplete glass (options only). Fall back
    # to the default manufacturing product so elevation/PDF never lose overlaps.
    if (not _has_renderable_geometry(base) or not _glass_rules_complete(base.get("glass") if isinstance(base.get("glass"), Mapping) else None)) and base_id != DEFAULT_PRODUCT_ID:
        try:
            base = load_product(DEFAULT_PRODUCT_ID, strict=False)
            base_id = DEFAULT_PRODUCT_ID
        except Exception:
            if not base:
                return
    if not base:
        return
    # Borrow any engineering section the catalogue product lacks (keep its own
    # identity, catalogue block, specifications and stub quotation).
    for sec in ("glass", "dimensioning", "weight", "hardware", "brush", "trackRail", "cutList", "bomExtras"):
        if not doc.get(sec):
            doc[sec] = copy.deepcopy(base.get(sec))
    # Merge required glass overlap keys even when a partial glass.json exists
    # (e.g. 35mm_sliding has thickness/options but no handleSideOverlap).
    glass = dict(doc.get("glass") or {})
    base_glass = dict(base.get("glass") or {})
    for key in _REQUIRED_GLASS_KEYS:
        if key not in glass and key in base_glass:
            glass[key] = base_glass[key]
    if glass:
        doc["glass"] = glass
    if not _has_renderable_geometry(doc):
        base_geom = dict(base.get("geometry") or {})
        cat = doc.get("catalogue") if isinstance(doc.get("catalogue"), Mapping) else {}
        profiles = cat.get("profiles") if isinstance(cat, Mapping) else None
        geom = dict(base_geom)
        fw = _catalogue_width(profiles, ("sash", "shutter"))
        iw = _catalogue_width(profiles, ("interlock", "meeting"))
        tw = _catalogue_width(profiles, ("track", "frame"))
        if fw:
            geom["frameWidth"] = fw
        if iw:
            geom["interlockWidth"] = iw
        if tw:
            geom["trackWidth"] = tw
        # Track count from the product/catalogue if present (name-parse when Excel
        # fields were never written onto stale section JSON).
        tc = _catalogue_track_count(cat if isinstance(cat, Mapping) else None, profiles)
        try:
            geom["trackCount"] = float(tc if tc is not None else geom.get("trackCount") or 2)
        except (TypeError, ValueError):
            geom["trackCount"] = float(base_geom.get("trackCount") or 2)
        # Sanitise so geometry_engine invariants hold (0 <= overlap < trackWidth, etc.).
        try:
            tw_v = float(geom.get("trackWidth") or base_geom.get("trackWidth") or 40)
            ov_v = float(geom.get("overlap") or base_geom.get("overlap") or 18)
            geom["overlap"] = max(0.0, min(ov_v, tw_v * 0.9))
            geom.setdefault("glassClip", float(base_geom.get("glassClip") or 6))
            geom.setdefault("shutterCount", float(base_geom.get("shutterCount") or 2))
        except (TypeError, ValueError):
            pass
        doc["geometry"] = geom
        doc["_synthesizedGeometry"] = True
    doc["_engineProductId"] = base_id


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
            if match.get("thicknessMm") is not None:
                glass_rules["thicknessMm"] = match["thicknessMm"]
            elif match.get("overallMm") is not None:
                glass_rules["thicknessMm"] = match["overallMm"]
            if "densityKgPerM3" in match:
                glass_rules["densityKgPerM3"] = match["densityKgPerM3"]
            for k in (
                "makeup", "overallMm", "glass1Mm", "glass2Mm", "airGapMm", "pvbMm",
                "layersMm", "colour", "toughened", "brand",
            ):
                if match.get(k) is not None:
                    glass_rules[k] = match[k]
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
