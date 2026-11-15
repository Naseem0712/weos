"""Product Library — per-type *series setup* schema, normalisation and derivations.

A "setup" is the structured, editable definition a fabricator fills in when they
register a series in the Product Library (Admin · Product Library → *Series
Setup* / Sliding Product Gallery).  It captures, per product **type**:

* the aluminium **sections** (outer track / frame, shutters, mesh, verticals,
  rails …) with dimensions, **weight (kg/m|ft)**, **standard length (rft/rmt)**,
  **rate** and **coating**, with per-side variants when sides differ; and
* the **hardware** items (rollers, connectors, hinges, locks, handles, friction
  stays, door closers …) with **brand**, **unit**, **rate** and **quantity per
  shutter / leaf / config**.

Sliding Product Gallery (series under Sliding selection):

* **trackMode** — all sides same / verticals same + H different / all different
* **trackOptions** — 2 / 2.5 / 3 / 4 (own weight/rate; rail count auto; shutters shared)
* **bomPattern** — v2_tb2 / v2_t1_b1 / all_side_4
* shutters (all-sides or split + slim/renf), meeting, mesh adapter, hardwarePack, costing stub

Phase 2 also ports WD-series concepts:

* **members** — editable qty-master rows with ``wFactor`` / ``hFactor`` (width /
  height piece counts), kg/m and ₹/m|rft for accurate cut metres;
* **hardwareWeightRules** — min/max kg → SKU/name/rate, isolated by system type
  (sliding wheels ≠ casement hinges ≠ style floorspring). Empty members / rules
  fall back to the legacy section cards + ``#admin-rules`` formulas.

The setup blob lives inside ``product.json`` (key ``setup``) so the durable
Postgres product store mirrors it automatically and it round-trips through the
Admin editor.  This module keeps the *shape* stable and provides small pure
helpers that turn a setup into engine-friendly artefacts:

* :func:`normalize_setup`      – coerce/clean a raw setup dict
* :func:`derive_section_sizes` – ``{topRail, bottomRail, leftJamb, rightJamb,
  leafStile}`` (mm) for the geometry engine
* :func:`derive_hardware`      – a flat hardware BOM list (optionally for one
  telescopic ``config`` such as ``"1+3"``) for cut-list / BOM / pricing
* :func:`derive_weights`       – section weight (kg/m) map for weight calc
* :func:`derive_member_cuts`   – cut metres from member wFactor/hFactor
* :func:`pick_hardware_by_weight` – WD-style capacity pick for wheels/closers/…

Everything degrades to sane empty values so callers never crash on a partial
setup.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# Canonical product types a setup can describe.
SETUP_TYPES = ("sliding", "casement", "telescopic", "style")

# Map a setup type → the cart/geometry "productType" (window system family) so
# the product implies its system when selected.
TYPE_TO_PRODUCT_TYPE = {
    "sliding": "sliding",
    "casement": "casements",
    "telescopic": "telescopic",
    "style": "style",
    "fold": "fold",
    "synchron": "synchron",
}

# Type defaults for the standard stock length(s) in mm.
DEFAULT_STANDARD_LENGTHS = {
    "sliding": [5850],
    "casement": [5850],
    "telescopic": [3000],       # imported: 3 mtr only
    "style": [2400, 3000],      # imported: 2.4 & 3 mtr
}

MEMBER_ROLES = (
    "outer",
    "track",
    "shutter",
    "interlock",
    "mesh",
    "mullion",
    "bead",
    "other",
)

HARDWARE_WEIGHT_KINDS = (
    "wheel",
    "roller",
    "door_closer",
    "floor_spring",
    "hinge",
)

# System-type isolation — sliding hardware must never auto-pick for casement, etc.
SYSTEM_TYPES = (
    "sliding",
    "casement",
    "tilt_turn",
    "style",
    "telescopic",
    "fold",
    "synchron",
)

# Map setup.type / layout.system aliases → hardware isolation key.
_SYSTEM_ALIASES = {
    "sliding": "sliding",
    "slider": "sliding",
    "casement": "casement",
    "casements": "casement",
    "openable": "casement",
    "opening": "casement",
    "tilt_turn": "tilt_turn",
    "tilt-turn": "tilt_turn",
    "tiltturn": "tilt_turn",
    "style": "style",
    "style_slide_door": "style",
    "door": "style",
    "telescopic": "telescopic",
    "telescopic_sliding": "telescopic",
    "fold": "fold",
    "bifold": "fold",
    "fold_sliding": "fold",
    "synchron": "synchron",
    "synchro": "synchron",
}


# ── coercion helpers ────────────────────────────────────────────────────────

def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# Sliding Product Gallery — track side modes & BOM fill patterns.
TRACK_MODES = (
    "all_sides_same",           # one track type on all sides
    "verticals_same_h_diff",    # both verticals same; top/bottom different
    "all_different",            # left/right verticals + horizontals different
)
TRACK_OPTION_IDS = ("2", "2.5", "3", "4")
BOM_PATTERNS = (
    "v2_tb2",       # vertical 2 nos, top+bottom track 2 nos
    "v2_t1_b1",     # vertical 2, top 1, bottom 1
    "all_side_4",   # track all side 4 nos (= vertical 2 + horizontal 2)
)
SHUTTER_MODES = ("all_sides_same", "split")
LOCK_TYPES = ("single_point", "multipoint", "mortice")
WEIGHT_UNITS = ("m", "ft")
LENGTH_UNITS = ("rft", "rmt")
RATE_UNITS = ("rft", "rmt", "kg")
COATING_UNITS = ("rft", "rmt")


def rail_count_for_track_option(track_id: Any) -> int:
    """2 / 2.5 → 2 rails; 3 → 3; 4 → 4."""
    try:
        v = float(track_id)
    except (TypeError, ValueError):
        return 2
    if v >= 4:
        return 4
    if v >= 3:
        return 3
    return 2  # 2 and 2.5 track → 2 rails only


def default_bom_pattern(track_mode: str) -> str:
    """Match fill/BOM pattern to the track mode the fabricator picked."""
    mode = _str(track_mode).lower()
    if mode == "all_sides_same":
        return "all_side_4"
    if mode == "verticals_same_h_diff":
        return "v2_t1_b1"
    if mode == "all_different":
        return "v2_tb2"
    return "all_side_4"


def normalize_section(raw: Any) -> dict[str, Any]:
    """A single aluminium section row (dims · weight · stock · rate · coating)."""
    r = raw if isinstance(raw, Mapping) else {}
    weight_unit = _str(r.get("weightUnit") or "m").lower()
    if weight_unit not in WEIGHT_UNITS:
        weight_unit = "m"
    std_unit = _str(r.get("stdLengthUnit") or r.get("standardLengthUnit") or "").lower()
    if std_unit in ("rm", "m", "mt", "meter", "metre"):
        std_unit = "rmt"
    if std_unit in ("ft", "feet", "foot"):
        std_unit = "rft"
    if std_unit not in LENGTH_UNITS:
        # Prefer explicit mm stock when only stdLengthMm is present.
        std_unit = "rft" if (r.get("stdLength") or r.get("standardLength")) else (
            "rmt" if r.get("stdLengthMm") or r.get("standardLengthMm") else "rft"
        )
    rate_unit = _str(r.get("rateUnit") or "rft").lower()
    if rate_unit in ("rm", "m", "mt"):
        rate_unit = "rmt"
    if rate_unit in ("ft", "feet"):
        rate_unit = "rft"
    if rate_unit not in RATE_UNITS:
        rate_unit = "rft"
    coating_unit = _str(r.get("coatingUnit") or "rft").lower()
    if coating_unit in ("rm", "m", "mt"):
        coating_unit = "rmt"
    if coating_unit in ("ft", "feet"):
        coating_unit = "rft"
    if coating_unit not in COATING_UNITS:
        coating_unit = "rft"
    std_len = r.get("stdLength")
    if std_len is None:
        std_len = r.get("standardLength")
    # Keep numeric mm when that is all we have (legacy Series Setup).
    std_length_mm = _num(r.get("stdLengthMm") or r.get("standardLengthMm"))
    if std_len is None and std_length_mm is not None:
        std_len = std_length_mm
    return {
        "name": _str(r.get("name")),
        "use": _str(r.get("use") or r.get("position")),
        "wMm": _num(r.get("wMm") or r.get("widthMm")),
        "hMm": _num(r.get("hMm") or r.get("heightMm") or r.get("depthMm")),
        "wallMm": _num(r.get("wallMm") or r.get("thicknessMm")),
        "weightKgPerM": _num(r.get("weightKgPerM") or r.get("weightKgPerMtr")),
        "weightUnit": weight_unit,
        "stdLengthMm": std_length_mm,
        "stdLength": std_len if isinstance(std_len, (int, float)) else _str(std_len) or None,
        "stdLengthUnit": std_unit,
        "rate": _num(r.get("rate") or r.get("ratePerUnit") or r.get("unitRate")) or 0.0,
        "rateUnit": rate_unit,
        "coatingCost": _num(r.get("coatingCost") or r.get("coatingRate")) or 0.0,
        "coatingUnit": coating_unit,
        "side": _str(r.get("side")),
        "glassType": _str(r.get("glassType")),  # '', 'sg' or 'dg'
        "notes": _str(r.get("notes")),
    }


def normalize_hardware(raw: Any) -> dict[str, Any]:
    """A single hardware/BOM row with brand, rate and qty-per rule."""
    r = raw if isinstance(raw, Mapping) else {}
    basis = _str(r.get("basis") or "shutter").lower()
    if basis not in ("shutter", "leaf", "window", "config", "pair", "door", "meter"):
        basis = "shutter"
    return {
        "name": _str(r.get("name")),
        "brand": _str(r.get("brand")),
        "unit": _str(r.get("unit") or "PC").upper(),
        "rate": _num(r.get("rate")) or 0.0,
        "qtyPer": _num(r.get("qtyPer") if r.get("qtyPer") is not None else r.get("qty")) or 0.0,
        "basis": basis,
        "sizes": [s for s in (r.get("sizes") or []) if _str(s)] if isinstance(r.get("sizes"), (list, tuple)) else _list_from_csv(r.get("sizes")),
        "config": _str(r.get("config")),
        "notes": _str(r.get("notes")),
    }


def normalize_member(raw: Any) -> dict[str, Any]:
    """WD-style ProfileMember: name/role + wFactor/hFactor + kg/m + rate."""
    r = raw if isinstance(raw, Mapping) else {}
    role = _str(r.get("role") or r.get("memberClass") or "other").lower().replace(" ", "_")
    # Accept WD memberClass labels → WEOS roles
    role_aliases = {
        "window": "outer",
        "outer_frame": "outer",
        "frame": "outer",
        "2-track": "track",
        "2.5-track": "track",
        "3-track": "track",
        "meeting": "interlock",
        "openable_panel": "shutter",
        "openable": "shutter",
        "panel": "shutter",
        "door_leaf": "shutter",
        "sash": "shutter",
        "mesh_panel": "mesh",
        "glazing_bead": "bead",
        "bead": "bead",
    }
    role = role_aliases.get(role, role)
    if role not in MEMBER_ROLES:
        role = "other"
    rate_unit = _str(r.get("rateUnit") or "m").lower()
    if rate_unit not in ("m", "rm", "rft", "ft"):
        rate_unit = "m"
    if rate_unit in ("rm",):
        rate_unit = "m"
    if rate_unit in ("ft",):
        rate_unit = "rft"
    mid = _str(r.get("id"))
    return {
        "id": mid,
        "name": _str(r.get("name")),
        "role": role,
        "wFactor": _num(r.get("wFactor")) if r.get("wFactor") is not None else 0.0,
        "hFactor": _num(r.get("hFactor")) if r.get("hFactor") is not None else 0.0,
        "weightKgPerM": _num(r.get("weightKgPerM") or r.get("kgPerM") or r.get("weightPerMeter")),
        "ratePerM": _num(r.get("ratePerM") or r.get("rate")) or 0.0,
        "rateUnit": rate_unit,
        "sku": _str(r.get("sku") or r.get("profileSkuId") or r.get("partNumber")),
        "notes": _str(r.get("notes")),
    }


def normalize_hardware_weight_rule(raw: Any) -> dict[str, Any]:
    """min/max kg → SKU/name/rate, scoped by hardware kind + system type."""
    r = raw if isinstance(raw, Mapping) else {}
    kind = _str(r.get("kind") or r.get("category") or "wheel").lower().replace(" ", "_").replace("-", "_")
    if kind == "wheels":
        kind = "wheel"
    if kind == "rollers":
        kind = "roller"
    if kind in ("closer", "doorcloser"):
        kind = "door_closer"
    if kind in ("floorspring", "floor"):
        kind = "floor_spring"
    if kind in ("hinges",):
        kind = "hinge"
    if kind not in HARDWARE_WEIGHT_KINDS:
        kind = "wheel"
    system = normalize_system_type(r.get("systemType") or r.get("system") or "")
    basis = _str(r.get("basis") or "shutter").lower()
    if basis not in ("shutter", "leaf", "door", "window", "opening", "pair"):
        basis = "shutter"
    min_kg = _num(r.get("minKg"))
    max_kg = _num(r.get("maxKg") or r.get("weightCapacityKg"))
    return {
        "kind": kind,
        "systemType": system,
        "minKg": float(min_kg) if min_kg is not None else 0.0,
        "maxKg": float(max_kg) if max_kg is not None else 0.0,
        "name": _str(r.get("name")),
        "sku": _str(r.get("sku") or r.get("partNumber") or r.get("hardwareId")),
        "brand": _str(r.get("brand")),
        "rate": _num(r.get("rate") or r.get("unitRate")) or 0.0,
        "unit": _str(r.get("unit") or "PC").upper(),
        "qtyPer": _num(r.get("qtyPer") if r.get("qtyPer") is not None else r.get("qty")) or 1.0,
        "basis": basis,
        "notes": _str(r.get("notes")),
    }


def normalize_system_type(value: Any) -> str:
    key = _str(value).lower().replace(" ", "_")
    if not key:
        return ""
    return _SYSTEM_ALIASES.get(key, key if key in SYSTEM_TYPES else "")


def _list_from_csv(value: Any) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in str(value).replace(";", ",").split(",") if p.strip()]


def _sections(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
    return [normalize_section(x) for x in items]


def _hardware(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
    return [normalize_hardware(x) for x in items]


def _members(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
    out = [normalize_member(x) for x in items]
    return [m for m in out if m.get("name") or (m.get("wFactor") or m.get("hFactor"))]


def _hardware_weight_rules(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
    out = [normalize_hardware_weight_rule(x) for x in items]
    return [r for r in out if r.get("name") or r.get("sku") or r.get("maxKg")]


# ── normalisation ───────────────────────────────────────────────────────────

def normalize_setup(raw: Any) -> dict[str, Any]:
    """Return a cleaned setup dict keyed by its ``type``.

    Only the block matching ``type`` is guaranteed populated; other blocks are
    preserved as-is (cleaned) so switching type in the UI never loses data.
    """
    s = dict(raw) if isinstance(raw, Mapping) else {}
    stype = _str(s.get("type")).lower()
    if stype not in SETUP_TYPES:
        stype = "sliding"

    std_lengths = s.get("standardLengths")
    if isinstance(std_lengths, (list, tuple)):
        std_lengths = [n for n in (_num(x) for x in std_lengths) if n]
    else:
        std_lengths = []
    if not std_lengths:
        std_lengths = list(DEFAULT_STANDARD_LENGTHS.get(stype, [5850]))

    out: dict[str, Any] = {
        "type": stype,
        "imported": _bool(s.get("imported"), stype in ("telescopic", "style")),
        "standardLengths": std_lengths,
        "notes": _str(s.get("notes")),
        # Phase 2 — WD members + weight→hardware (empty → legacy path)
        "members": _members(s.get("members")),
        "hardwareWeightRules": _hardware_weight_rules(
            s.get("hardwareWeightRules") or s.get("weightHardwareRules")
        ),
    }

    out["sliding"] = _norm_sliding(s.get("sliding"))
    out["casement"] = _norm_casement(s.get("casement"))
    out["telescopic"] = _norm_telescopic(s.get("telescopic"))
    out["style"] = _norm_style(s.get("style"))

    derived: dict[str, Any] = {
        "sectionSizes": derive_section_sizes(out),
        "hardware": derive_hardware(out),
        "weights": derive_weights(out),
        "memberCount": len(out["members"]),
        "hardwareWeightRuleCount": len(out["hardwareWeightRules"]),
    }
    if stype == "sliding":
        derived["trackFill"] = derive_sliding_track_fill(out)
        derived["activeTrackOption"] = (out.get("sliding") or {}).get("activeTrackOption")
        derived["railCount"] = (derived["trackFill"] or {}).get("rails")
        derived["costEngine"] = ((out.get("sliding") or {}).get("costing") or {}).get("costEngine", "stub")
    out["derived"] = derived
    return out


def _norm_track_mode(value: Any) -> str:
    mode = _str(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "all": "all_sides_same",
        "same": "all_sides_same",
        "all_sides": "all_sides_same",
        "same_all_sides": "all_sides_same",
        "vertical_same": "verticals_same_h_diff",
        "verticals_same": "verticals_same_h_diff",
        "vh_diff": "verticals_same_h_diff",
        "split_h": "verticals_same_h_diff",
        "different": "all_different",
        "all_diff": "all_different",
        "full_split": "all_different",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in TRACK_MODES else "all_sides_same"


def _norm_bom_pattern(value: Any, track_mode: str = "all_sides_same") -> str:
    pat = _str(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "vertical_2_top_bottom_2": "v2_tb2",
        "v2_topbottom_2": "v2_tb2",
        "vertical_2_top_1_bottom_1": "v2_t1_b1",
        "v2_t1b1": "v2_t1_b1",
        "all_side": "all_side_4",
        "all_sides_4": "all_side_4",
        "track_all_side_4": "all_side_4",
        "4_nos": "all_side_4",
    }
    pat = aliases.get(pat, pat)
    if pat in BOM_PATTERNS:
        return pat
    return default_bom_pattern(track_mode)


def _blank_track_sides() -> dict[str, Any]:
    return {
        "all": normalize_section({"use": "track"}),
        "vertical": normalize_section({"use": "track_vertical"}),
        "top": normalize_section({"use": "track_top"}),
        "bottom": normalize_section({"use": "track_bottom"}),
        "leftVertical": normalize_section({"use": "track_left"}),
        "rightVertical": normalize_section({"use": "track_right"}),
    }


def normalize_track_option(raw: Any) -> dict[str, Any]:
    """One track option (2 / 2.5 / 3 / 4) under the same series — shutters unchanged."""
    r = raw if isinstance(raw, Mapping) else {}
    tid = _str(r.get("id") or r.get("trackCount") or r.get("count") or "2")
    # Normalise "2 track" / 2.5 → canonical id
    cleaned = tid.lower().replace("track", "").replace(" ", "").strip()
    if cleaned in TRACK_OPTION_IDS:
        tid = cleaned
    else:
        try:
            f = float(cleaned)
            tid = "2.5" if abs(f - 2.5) < 0.01 else str(int(f)) if f == int(f) else str(f)
        except (TypeError, ValueError):
            tid = "2"
    if tid not in TRACK_OPTION_IDS:
        tid = "2"
    sides = r.get("sides") if isinstance(r.get("sides"), Mapping) else {}
    # Accept flat legacy keys on the option itself
    base = _blank_track_sides()
    for key in base:
        src = sides.get(key) if key in sides else r.get(key)
        if src is not None:
            base[key] = normalize_section(src)
    # If only a single section blob was stored, treat it as "all"
    if isinstance(r.get("section"), Mapping):
        base["all"] = normalize_section(r.get("section"))
    label = _str(r.get("label") or r.get("name")) or f"{tid} track"
    try:
        track_count = float(tid)
    except ValueError:
        track_count = 2.0
    return {
        "id": tid,
        "label": label,
        "trackCount": track_count,
        "railCount": int(r.get("railCount") or rail_count_for_track_option(tid)),
        "meshCapable": _bool(r.get("meshCapable"), float(tid) >= 2.5),
        "sides": base,
        "notes": _str(r.get("notes")),
    }


def default_track_options() -> list[dict[str, Any]]:
    return [normalize_track_option({"id": x}) for x in TRACK_OPTION_IDS]


def _norm_sliding_hardware_pack(raw: Any) -> dict[str, Any]:
    """Structured per-shutter hardware (connectors, EPDM, wings, brush, lock, wheels)."""
    r = raw if isinstance(raw, Mapping) else {}

    def qty_rate(key: str, default_qty: float = 0.0, max_qty: float | None = None) -> dict[str, Any]:
        block = r.get(key) if isinstance(r.get(key), Mapping) else {}
        qty = _num(block.get("qty") if block.get("qty") is not None else default_qty)
        if qty is None:
            qty = default_qty
        if max_qty is not None:
            qty = max(0.0, min(float(qty), float(max_qty)))
        return {
            "qty": float(qty),
            "rate": _num(block.get("rate")) or 0.0,
            "unit": _str(block.get("unit") or "PC").upper(),
            "notes": _str(block.get("notes")),
        }

    epdm = r.get("epdm") if isinstance(r.get("epdm"), Mapping) else {}
    brush = r.get("brush") if isinstance(r.get("brush"), Mapping) else {}
    wings = r.get("wings") if isinstance(r.get("wings"), Mapping) else {}
    lock = r.get("lock") if isinstance(r.get("lock"), Mapping) else {}
    wheels = r.get("wheels") if isinstance(r.get("wheels"), Mapping) else {}
    lock_type = _str(lock.get("type") or "single_point").lower().replace("-", "_").replace(" ", "_")
    if lock_type in ("single", "sp"):
        lock_type = "single_point"
    if lock_type in ("multi", "mp"):
        lock_type = "multipoint"
    if lock_type not in LOCK_TYPES:
        lock_type = "single_point"
    return {
        "trackConnectors": qty_rate("trackConnectors", 0, 8),
        "shutterConnectors": qty_rate("shutterConnectors", 0, 4),
        "epdm": {
            "ratePerM": _num(epdm.get("ratePerM") or epdm.get("rate")) or 0.0,
            # height×4 + width×4 (m) — computed at quote time
            "formula": _str(epdm.get("formula") or "height_m*4 + width_m*4"),
            "notes": _str(epdm.get("notes")),
        },
        "brush": {
            "ratePerM": _num(brush.get("ratePerM") or brush.get("rate")) or 0.0,
            "formula": _str(brush.get("formula") or "height_m*4 + width_m*4"),
            "notes": _str(brush.get("notes")),
        },
        "wings": {
            # 4/shutter if slim or renf interlock; 8 if all-side same section
            "rate": _num(wings.get("rate")) or 0.0,
            "qtyAllSidesSame": int(_num(wings.get("qtyAllSidesSame")) or 8),
            "qtySplit": int(_num(wings.get("qtySplit")) or 4),
            "notes": _str(wings.get("notes")),
        },
        "lock": {
            "type": lock_type,
            "rate": _num(lock.get("rate")) or 0.0,
            "unit": _str(lock.get("unit") or "SET").upper(),
            "notes": _str(lock.get("notes")),
        },
        "wheels": {
            "qtyPerShutter": _num(wheels.get("qtyPerShutter") if wheels.get("qtyPerShutter") is not None else 2) or 2.0,
            "rate": _num(wheels.get("rate")) or 0.0,
            "unit": _str(wheels.get("unit") or "PC").upper(),
            "notes": _str(wheels.get("notes")),
        },
    }


def _norm_sliding_costing(raw: Any) -> dict[str, Any]:
    """Labour / profit / wastage hooks — full project cost may stub until all products quoted."""
    r = raw if isinstance(raw, Mapping) else {}
    return {
        "labourPerSft": _num(r.get("labourPerSft") or r.get("labourRate")),
        "profitPercent": _num(r.get("profitPercent") or r.get("profit")),
        "cutFromOwnStock": _bool(r.get("cutFromOwnStock"), True),
        "allSideSameLowWastage": _bool(r.get("allSideSameLowWastage"), True),
        "projectWastageReuse": _bool(r.get("projectWastageReuse"), True),
        "costEngine": _str(r.get("costEngine") or "stub"),  # stub | live
        "notes": _str(r.get("notes") or "Full project cost runs when all products are on the quote."),
    }


def bom_qty_for_pattern(pattern: str) -> dict[str, int]:
    """Piece counts for track fill patterns (per opening)."""
    p = _norm_bom_pattern(pattern)
    if p == "v2_tb2":
        return {"vertical": 2, "top": 2, "bottom": 2, "horizontal": 0, "all": 0}
    if p == "v2_t1_b1":
        return {"vertical": 2, "top": 1, "bottom": 1, "horizontal": 0, "all": 0}
    # all_side_4
    return {"vertical": 2, "top": 0, "bottom": 0, "horizontal": 2, "all": 4}


def _norm_sliding(raw: Any) -> dict[str, Any]:
    r = raw if isinstance(raw, Mapping) else {}
    ot = r.get("outerTrack") if isinstance(r.get("outerTrack"), Mapping) else {}
    sh = r.get("shutters") if isinstance(r.get("shutters"), Mapping) else {}
    mesh = r.get("mesh") if isinstance(r.get("mesh"), Mapping) else {}
    meeting = r.get("meeting") if isinstance(r.get("meeting"), Mapping) else {}
    track_mode = _norm_track_mode(
        r.get("trackMode") or ot.get("trackMode")
        or ("all_sides_same" if _bool(ot.get("sameAllSides"), True) else "verticals_same_h_diff")
    )
    bom_pattern = _norm_bom_pattern(r.get("bomPattern") or ot.get("bomPattern"), track_mode)

    # Track options — prefer explicit list; else seed 2/2.5/3/4
    opts_raw = r.get("trackOptions")
    if isinstance(opts_raw, (list, tuple)) and opts_raw:
        track_options = [normalize_track_option(x) for x in opts_raw]
        # Ensure unique ids, keep order
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for opt in track_options:
            if opt["id"] in seen:
                continue
            seen.add(opt["id"])
            uniq.append(opt)
        for tid in TRACK_OPTION_IDS:
            if tid not in seen:
                uniq.append(normalize_track_option({"id": tid}))
        track_options = uniq
    else:
        track_options = default_track_options()
        # Migrate legacy outerTrack section cards into the active option "all"/sides
        active0 = track_options[0]
        sides = active0["sides"]
        if ot.get("top") or ot.get("bottom") or ot.get("verticals"):
            sides["top"] = normalize_section(ot.get("top"))
            sides["bottom"] = normalize_section(ot.get("bottom"))
            sides["vertical"] = normalize_section(ot.get("verticals"))
            if _bool(ot.get("sameAllSides"), True):
                sides["all"] = normalize_section(ot.get("verticals") or ot.get("top") or ot.get("bottom"))

    active = _str(r.get("activeTrackOption") or r.get("trackCount") or "2")
    if active not in TRACK_OPTION_IDS:
        try:
            f = float(active)
            active = "2.5" if abs(f - 2.5) < 0.01 else str(int(f))
        except (TypeError, ValueError):
            active = "2"
    if active not in {o["id"] for o in track_options}:
        active = track_options[0]["id"]

    shutter_mode = _str(sh.get("mode") or "").lower()
    if shutter_mode not in SHUTTER_MODES:
        shutter_mode = "all_sides_same" if _bool(sh.get("sameAllSides"), True) else "split"

    # Freeform hardware list (legacy) + structured pack
    hw_list = r.get("hardware")
    hw_pack_raw = r.get("hardwarePack") if isinstance(r.get("hardwarePack"), Mapping) else None
    if isinstance(hw_list, Mapping) and not hw_pack_raw:
        # New UI may store structured pack under "hardware" as object
        hw_pack_raw = hw_list
        hw_list = hw_list.get("items") if isinstance(hw_list.get("items"), (list, tuple)) else []

    adapter = mesh.get("adapter") if isinstance(mesh.get("adapter"), Mapping) else {}
    mesh_section = mesh.get("meshSection") if isinstance(mesh.get("meshSection"), Mapping) else mesh.get("section")

    return {
        "trackMode": track_mode,
        "bomPattern": bom_pattern,
        "activeTrackOption": active,
        "trackOptions": track_options,
        "outerTrack": {
            # Legacy mirror for older UI / derive_section_sizes
            "sameAllSides": track_mode == "all_sides_same",
            "trackMode": track_mode,
            "bomPattern": bom_pattern,
            "top": normalize_section(ot.get("top")),
            "bottom": normalize_section(ot.get("bottom")),
            "verticals": normalize_section(ot.get("verticals")),
            "bottomRails": normalize_section(ot.get("bottomRails")),
            "leftVertical": normalize_section(ot.get("leftVertical")),
            "rightVertical": normalize_section(ot.get("rightVertical")),
        },
        "shutters": {
            "mode": shutter_mode,
            "sameAllSides": shutter_mode == "all_sides_same",
            "allSides": normalize_section(sh.get("allSides") or (sh.get("top") if shutter_mode == "all_sides_same" else None)),
            "top": normalize_section(sh.get("top")),
            "bottom": normalize_section(sh.get("bottom")),
            "handleSide": normalize_section(sh.get("handleSide")),
            "interlockSide": normalize_section(sh.get("interlockSide")),  # slim (1st shutter)
            "interlockSlim": normalize_section(sh.get("interlockSlim") or sh.get("interlockSide")),
            "interlockRenf": normalize_section(sh.get("interlockRenf") or sh.get("reinforcement")),
            "notes": _str(sh.get("notes")),
        },
        "meeting": {
            "enabled": _bool(meeting.get("enabled"), False),
            "section": normalize_section(meeting.get("section") or meeting),
            "notes": _str(meeting.get("notes") or "Used when 4 glass shutters (center opening)."),
        },
        "mesh": {
            "compatible": _bool(mesh.get("compatible"), False),
            "sameAsShutter": _bool(mesh.get("sameAsShutter"), True),
            "adapter": {
                "sameAllSides": _bool(adapter.get("sameAllSides"), True),
                "section": normalize_section(adapter.get("section") or adapter),
            },
            "meshSection": normalize_section(mesh_section),
            "sections": _sections(mesh.get("sections")),
        },
        "hardware": _hardware(hw_list if isinstance(hw_list, (list, tuple)) else []),
        "hardwarePack": _norm_sliding_hardware_pack(hw_pack_raw or {}),
        "costing": _norm_sliding_costing(r.get("costing")),
    }


def _norm_casement(raw: Any) -> dict[str, Any]:
    r = raw if isinstance(raw, Mapping) else {}
    glass = r.get("glass") if isinstance(r.get("glass"), Mapping) else {}
    return {
        "outerFrame": normalize_section(r.get("outerFrame")),
        "shutter": normalize_section(r.get("shutter")),
        "glass": {"sgClip": _num(glass.get("sgClip")), "dgClip": _num(glass.get("dgClip"))},
        "hardware": _hardware(r.get("hardware")),
    }


def _norm_telescopic(raw: Any) -> dict[str, Any]:
    r = raw if isinstance(raw, Mapping) else {}
    sets_raw = r.get("hardwareSets") if isinstance(r.get("hardwareSets"), Mapping) else {}
    hardware_sets = {cfg: _hardware(sets_raw.get(cfg)) for cfg in ("1+1", "1+2", "1+3", "1+4", "1+5")}
    return {
        "vertical": normalize_section(r.get("vertical")),
        "verticalTop": normalize_section(r.get("verticalTop")),
        "verticalBottom": normalize_section(r.get("verticalBottom")),
        "commonSize": _str(r.get("commonSize") or "16x45"),
        "jointConnectorGI": normalize_hardware(r.get("jointConnectorGI")),
        "topTrack": normalize_section(r.get("topTrack")),
        "hardwareSets": hardware_sets,
        "overlapAdjacent": _bool(r.get("overlapAdjacent"), True),
        "synchro2plus2": _bool(r.get("synchro2plus2"), False),
        "maxConfig": _str(r.get("maxConfig") or "1+1"),
    }


def _norm_style(raw: Any) -> dict[str, Any]:
    r = raw if isinstance(raw, Mapping) else {}
    return {
        "outerFrame": normalize_section(r.get("outerFrame")),
        "innerDoorVertical": normalize_section(r.get("innerDoorVertical")),
        "top": normalize_section(r.get("top")),
        "bottom": normalize_section(r.get("bottom")),
        "usesCasementHardware": _bool(r.get("usesCasementHardware"), True),
        "floorSpring": normalize_hardware(r.get("floorSpring")),
        "pivotDoor": normalize_hardware(r.get("pivotDoor")),
        "hardware": _hardware(r.get("hardware")),
    }


# ── derivations (engine-friendly) ────────────────────────────────────────────

def _face(section: Mapping[str, Any] | None) -> float | None:
    """Visible frame face width (mm) of a section — used as the geometry
    frame-width contribution. Prefer wMm (face), fall back to wallMm."""
    if not isinstance(section, Mapping):
        return None
    return _num(section.get("wMm")) or _num(section.get("wallMm"))


def derive_section_sizes(setup: Mapping[str, Any]) -> dict[str, float]:
    """Return ``{topRail, bottomRail, leftJamb, rightJamb, leafStile}`` (mm).

    Empty when the relevant sections are not filled in. These feed the geometry
    engine's ``section_sizes`` so the elevation frame widths match the series.
    """
    stype = _str(setup.get("type")).lower()
    out: dict[str, float] = {}

    def put(key: str, val: float | None) -> None:
        if val:
            out[key] = float(val)

    if stype == "sliding":
        sl = setup.get("sliding") or {}
        ot = sl.get("outerTrack") or {}
        sh = sl.get("shutters") or {}
        # Prefer active track option sides when filled
        active = _str(sl.get("activeTrackOption") or "2")
        opt = next(
            (o for o in (sl.get("trackOptions") or []) if isinstance(o, Mapping) and _str(o.get("id")) == active),
            None,
        )
        sides = (opt or {}).get("sides") if isinstance(opt, Mapping) else None
        mode = _str(sl.get("trackMode") or ot.get("trackMode") or "all_sides_same")
        if isinstance(sides, Mapping):
            if mode == "all_sides_same":
                face = _face(sides.get("all")) or _face(sides.get("vertical")) or _face(sides.get("top"))
                put("topRail", face)
                put("bottomRail", face)
                put("leftJamb", face)
                put("rightJamb", face)
            elif mode == "verticals_same_h_diff":
                put("topRail", _face(sides.get("top")))
                put("bottomRail", _face(sides.get("bottom")))
                put("leftJamb", _face(sides.get("vertical")))
                put("rightJamb", _face(sides.get("vertical")))
            else:
                put("topRail", _face(sides.get("top")))
                put("bottomRail", _face(sides.get("bottom")))
                put("leftJamb", _face(sides.get("leftVertical")))
                put("rightJamb", _face(sides.get("rightVertical")))
        if "topRail" not in out:
            put("topRail", _face(ot.get("top")))
            put("bottomRail", _face(ot.get("bottom")))
            put("leftJamb", _face(ot.get("leftVertical")) or _face(ot.get("verticals")))
            put("rightJamb", _face(ot.get("rightVertical")) or _face(ot.get("verticals")))
        put(
            "leafStile",
            _face(sh.get("interlockSlim"))
            or _face(sh.get("interlockSide"))
            or _face(sh.get("handleSide"))
            or _face(sh.get("allSides"))
            or _face(sh.get("top")),
        )
        if isinstance(opt, Mapping) and opt.get("railCount"):
            out["trackRailCount"] = float(opt["railCount"])
            out["trackCount"] = float(opt.get("trackCount") or active or 2)
    elif stype == "casement":
        c = setup.get("casement") or {}
        fw = _face(c.get("outerFrame"))
        put("topRail", fw)
        put("bottomRail", fw)
        put("leftJamb", fw)
        put("rightJamb", fw)
        put("leafStile", _face(c.get("shutter")) or fw)
    elif stype == "telescopic":
        t = setup.get("telescopic") or {}
        put("topRail", _face(t.get("verticalTop")) or _face(t.get("topTrack")))
        put("bottomRail", _face(t.get("verticalBottom")))
        put("leftJamb", _face(t.get("vertical")))
        put("rightJamb", _face(t.get("vertical")))
        put("leafStile", _face(t.get("vertical")))
    elif stype == "style":
        st = setup.get("style") or {}
        put("topRail", _face(st.get("top")))
        put("bottomRail", _face(st.get("bottom")))
        put("leftJamb", _face(st.get("outerFrame")))
        put("rightJamb", _face(st.get("outerFrame")))
        put("leafStile", _face(st.get("innerDoorVertical")))
    return out


def derive_hardware(setup: Mapping[str, Any], *, config: str | None = None) -> list[dict[str, Any]]:
    """Flat hardware BOM list for the setup type.

    ``config`` selects a telescopic hardware set (e.g. ``"1+3"``). For other
    types it is ignored. Rows are already normalised (name/brand/unit/rate/
    qtyPer/basis) so cut-list / BOM / pricing can consume them directly.
    """
    stype = _str(setup.get("type")).lower()
    rows: list[dict[str, Any]] = []
    if stype == "sliding":
        rows = list((setup.get("sliding") or {}).get("hardware") or [])
    elif stype == "casement":
        rows = list((setup.get("casement") or {}).get("hardware") or [])
    elif stype == "telescopic":
        sets = (setup.get("telescopic") or {}).get("hardwareSets") or {}
        if config and config in sets:
            rows = list(sets.get(config) or [])
        else:
            # union of all configured sets (deduped by name+config)
            seen: set[tuple[str, str]] = set()
            for cfg, items in sets.items():
                for it in items or []:
                    key = (str(it.get("name")), cfg)
                    if key in seen:
                        continue
                    seen.add(key)
                    row = dict(it)
                    row.setdefault("config", cfg)
                    if not row.get("config"):
                        row["config"] = cfg
                    rows.append(row)
        jc = (setup.get("telescopic") or {}).get("jointConnectorGI")
        if isinstance(jc, Mapping) and jc.get("name"):
            rows.append(dict(jc))
    elif stype == "style":
        st = setup.get("style") or {}
        rows = list(st.get("hardware") or [])
        for extra in ("floorSpring", "pivotDoor"):
            it = st.get(extra)
            if isinstance(it, Mapping) and it.get("name"):
                rows.append(dict(it))
    return [normalize_hardware(r) for r in rows if _str((r or {}).get("name"))]


def derive_weights(setup: Mapping[str, Any]) -> dict[str, float]:
    """Return ``{sectionName: weightKgPerM}`` for every section that carries a
    weight — feeds the weight calculator / factory sheet."""
    out: dict[str, float] = {}

    def add(sec: Any) -> None:
        if isinstance(sec, Mapping):
            w = _num(sec.get("weightKgPerM"))
            nm = _str(sec.get("name")) or _str(sec.get("use"))
            if w and nm:
                out[nm] = float(w)

    stype = _str(setup.get("type")).lower()
    block = setup.get(stype) or {}
    # Walk one level: section objects and lists of sections.
    for val in block.values() if isinstance(block, Mapping) else []:
        if isinstance(val, Mapping):
            if "weightKgPerM" in val:
                add(val)
            else:
                for sub in val.values():
                    if isinstance(sub, Mapping):
                        add(sub)
                    elif isinstance(sub, (list, tuple)):
                        for x in sub:
                            add(x)
        elif isinstance(val, (list, tuple)):
            for x in val:
                add(x)
    return out


def flatten_setup_sections(setup: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Flat list of named section rows from a Series Setup blob (for quote specs)."""
    if not isinstance(setup, Mapping):
        return []
    stype = _str(setup.get("type")).lower()
    block = setup.get(stype) if stype else None
    if not isinstance(block, Mapping):
        block = {}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def add(sec: Any, *, use_hint: str = "") -> None:
        if not isinstance(sec, Mapping):
            return
        row = normalize_section(sec)
        if use_hint and not row.get("use"):
            row["use"] = use_hint
        if not row.get("name") and not (row.get("wMm") or row.get("hMm")):
            return
        key = (row.get("name"), row.get("use"), row.get("wMm"), row.get("hMm"), row.get("side"))
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    def walk(node: Any, use_hint: str = "") -> None:
        if isinstance(node, Mapping):
            if any(k in node for k in ("name", "wMm", "widthMm", "weightKgPerM")):
                add(node, use_hint=use_hint)
                return
            for k, v in node.items():
                walk(v, use_hint=str(k))
        elif isinstance(node, (list, tuple)):
            for it in node:
                walk(it, use_hint=use_hint)

    walk(block)
    return rows


def empty_setup(stype: str = "sliding") -> dict[str, Any]:
    """A blank, normalised setup for a given type (used to seed the editor)."""
    return normalize_setup({"type": stype})


def active_track_option(setup: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the normalised active track option from a sliding setup."""
    if not isinstance(setup, Mapping):
        return None
    sl = setup.get("sliding") if _str(setup.get("type")).lower() == "sliding" else setup
    if not isinstance(sl, Mapping):
        return None
    if "trackOptions" not in sl and isinstance(setup.get("sliding"), Mapping):
        sl = setup["sliding"]
    active = _str(sl.get("activeTrackOption") or "2")
    for opt in sl.get("trackOptions") or []:
        if isinstance(opt, Mapping) and _str(opt.get("id")) == active:
            return normalize_track_option(opt)
    opts = sl.get("trackOptions") or []
    return normalize_track_option(opts[0]) if opts else None


def derive_sliding_track_fill(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float = 0.0,
    height_mm: float = 0.0,
) -> dict[str, Any]:
    """BOM fill sketch for the active track option (qty + section refs).

    Cost engine may stub pricing; this always returns structure for the UI/BOM.
    """
    if not isinstance(setup, Mapping):
        return {"pattern": "all_side_4", "rails": 2, "pieces": {}, "lines": []}
    sl = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else setup
    if not isinstance(sl, Mapping):
        return {"pattern": "all_side_4", "rails": 2, "pieces": {}, "lines": []}
    pattern = _norm_bom_pattern(sl.get("bomPattern"), _str(sl.get("trackMode")))
    pieces = bom_qty_for_pattern(pattern)
    opt = active_track_option(setup if setup.get("sliding") else {"sliding": sl, "type": "sliding"})
    if opt is None and isinstance(setup.get("sliding"), Mapping):
        opt = active_track_option(setup)
    sides = (opt or {}).get("sides") or {}
    mode = _str(sl.get("trackMode") or "all_sides_same")
    w = max(float(width_mm or 0), 0.0)
    h = max(float(height_mm or 0), 0.0)
    lines: list[dict[str, Any]] = []

    def add_line(role: str, qty: int, sec: Any, length_mm: float) -> None:
        if qty <= 0:
            return
        section = normalize_section(sec) if sec is not None else normalize_section({})
        lines.append({
            "role": role,
            "qty": qty,
            "lengthMm": length_mm or None,
            "section": section,
            "trackOption": (opt or {}).get("id"),
            "railCount": (opt or {}).get("railCount"),
        })

    if mode == "all_sides_same":
        sec = sides.get("all") or sides.get("vertical")
        add_line("track_all", pieces.get("all") or 4, sec, 0)
    elif mode == "verticals_same_h_diff":
        add_line("track_vertical", pieces.get("vertical") or 2, sides.get("vertical"), h)
        add_line("track_top", pieces.get("top") or 1, sides.get("top"), w)
        add_line("track_bottom", pieces.get("bottom") or 1, sides.get("bottom"), w)
    else:
        add_line("track_left", 1, sides.get("leftVertical"), h)
        add_line("track_right", 1, sides.get("rightVertical"), h)
        top_q = pieces.get("top") or 1
        bot_q = pieces.get("bottom") or 1
        add_line("track_top", top_q, sides.get("top"), w)
        add_line("track_bottom", bot_q, sides.get("bottom"), w)

    return {
        "pattern": pattern,
        "trackMode": mode,
        "rails": int((opt or {}).get("railCount") or rail_count_for_track_option((opt or {}).get("id"))),
        "trackOption": (opt or {}).get("id"),
        "pieces": pieces,
        "lines": lines,
        "costEngine": ((sl.get("costing") or {}) if isinstance(sl.get("costing"), Mapping) else {}).get("costEngine", "stub"),
    }


def derive_sliding_hardware_lines(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float,
    height_mm: float,
    shutter_count: float = 2.0,
) -> list[dict[str, Any]]:
    """Expand structured hardwarePack into priced BOM lines (per opening)."""
    if not isinstance(setup, Mapping):
        return []
    sl = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else None
    if not isinstance(sl, Mapping):
        return []
    pack = sl.get("hardwarePack") if isinstance(sl.get("hardwarePack"), Mapping) else {}
    if not pack:
        return []

    def _pack_configured(p: Mapping[str, Any]) -> bool:
        for key in ("trackConnectors", "shutterConnectors", "wheels", "lock", "wings"):
            block = p.get(key) if isinstance(p.get(key), Mapping) else {}
            if float(block.get("rate") or 0) > 0:
                return True
            if key in ("trackConnectors", "shutterConnectors") and float(block.get("qty") or 0) > 0:
                return True
        for key in ("epdm", "brush"):
            block = p.get(key) if isinstance(p.get(key), Mapping) else {}
            if float(block.get("ratePerM") or block.get("rate") or 0) > 0:
                return True
        return False

    if not _pack_configured(pack):
        return []
    shutters = max(float(shutter_count or 1), 1.0)
    w_m = max(float(width_mm or 0), 0.0) / 1000.0
    h_m = max(float(height_mm or 0), 0.0) / 1000.0
    perimeter = (h_m * 4.0) + (w_m * 4.0)  # EPDM / brush rule
    same_shutter = _str((sl.get("shutters") or {}).get("mode")) == "all_sides_same"
    lines: list[dict[str, Any]] = []

    def add(name: str, qty: float, rate: float, unit: str = "PC", remarks: str = "") -> None:
        if qty <= 0 and rate <= 0:
            return
        lines.append({
            "category": "hardware",
            "name": name,
            "qty": round(qty, 4),
            "unit": unit,
            "unitRate": float(rate or 0),
            "remarks": remarks,
            "source": "sliding.hardwarePack",
        })

    tc = pack.get("trackConnectors") or {}
    add("Track connectors", float(tc.get("qty") or 0), float(tc.get("rate") or 0), tc.get("unit") or "PC")
    sc = pack.get("shutterConnectors") or {}
    add(
        "Shutter connectors",
        float(sc.get("qty") or 0) * shutters,
        float(sc.get("rate") or 0),
        sc.get("unit") or "PC",
        "per shutter",
    )
    epdm = pack.get("epdm") or {}
    add("EPDM dual-side", perimeter * shutters, float(epdm.get("ratePerM") or 0), "RM", "height×4 + width×4 × shutters")
    brush = pack.get("brush") or {}
    add("Brush", perimeter * shutters, float(brush.get("ratePerM") or 0), "RM", "same as EPDM")
    wings = pack.get("wings") or {}
    wqty = float(wings.get("qtyAllSidesSame") or 8) if same_shutter else float(wings.get("qtySplit") or 4)
    add("Wings / angle", wqty * shutters, float(wings.get("rate") or 0), "PC", "4 split / 8 all-sides per shutter")
    lock = pack.get("lock") or {}
    add(f"Lock ({lock.get('type') or 'single_point'})", 1.0, float(lock.get("rate") or 0), lock.get("unit") or "SET")
    wheels = pack.get("wheels") or {}
    add(
        "Wheels",
        float(wheels.get("qtyPerShutter") or 2) * shutters,
        float(wheels.get("rate") or 0),
        wheels.get("unit") or "PC",
        "per shutter",
    )
    return [ln for ln in lines if ln["qty"] > 0 or ln["unitRate"] > 0]


# ── Phase 2: member factors + weight→hardware ───────────────────────────────

def _role_count(role: str, ctx: Mapping[str, Any]) -> float:
    """How many times a member row repeats for this opening."""
    shutters = float(ctx.get("shutterCount") or ctx.get("glassCount") or ctx.get("leafCount") or 1) or 1.0
    mesh = float(ctx.get("meshCount") or 0) or 0.0
    mullions = float(ctx.get("mullionCount") or ctx.get("mullions") or 0) or 0.0
    if role in ("outer", "track", "other", "bead"):
        return 1.0
    if role == "shutter":
        return max(shutters, 1.0)
    if role == "interlock":
        # Meeting stiles roughly one fewer than shutters; never below 1 when shutters≥2
        return max(shutters - 1.0, 1.0) if shutters >= 2 else 0.0
    if role == "mesh":
        return max(mesh, 0.0)
    if role == "mullion":
        return max(mullions, 0.0)
    return 1.0


def _basis_multiplier(basis: str, ctx: Mapping[str, Any]) -> float:
    b = (basis or "shutter").lower()
    if b in ("shutter", "leaf"):
        return float(ctx.get("shutterCount") or ctx.get("leafCount") or ctx.get("glassCount") or 1) or 1.0
    if b == "door":
        return float(ctx.get("doorCount") or ctx.get("leafCount") or 1) or 1.0
    if b in ("window", "opening"):
        return 1.0
    if b == "pair":
        return 1.0
    return 1.0


def derive_member_cuts(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float,
    height_mm: float,
    ctx: Mapping[str, Any] | None = None,
    qty: float = 1.0,
) -> list[dict[str, Any]]:
    """Cut metres from member wFactor/hFactor.

    Empty ``members`` → ``[]`` (caller keeps legacy cut-list / formulas).
    Metres = ((wFactor × W) + (hFactor × H)) / 1000 × roleCount × qty.
    When rateUnit is rft, metres are converted to running feet for billing qty.
    """
    if not isinstance(setup, Mapping):
        return []
    members = setup.get("members") or []
    if not members:
        return []
    context = dict(ctx or {})
    w = max(float(width_mm or 0), 0.0)
    h = max(float(height_mm or 0), 0.0)
    q = max(float(qty or 1), 0.0)
    lines: list[dict[str, Any]] = []
    for raw in members:
        m = normalize_member(raw)
        if not m.get("name") and not (m.get("wFactor") or m.get("hFactor")):
            continue
        wf = float(m.get("wFactor") or 0)
        hf = float(m.get("hFactor") or 0)
        if wf <= 0 and hf <= 0:
            continue
        count = _role_count(str(m.get("role") or "other"), context)
        if count <= 0:
            continue
        metres = ((wf * w + hf * h) / 1000.0) * count * q
        if metres <= 0:
            continue
        rate_unit = str(m.get("rateUnit") or "m")
        bill_qty = metres * (1.0 / 0.3048) if rate_unit == "rft" else metres
        bill_unit = "RFT" if rate_unit == "rft" else "RM"
        # Piece counts (integer factors → discrete pieces for cut sheet)
        pieces_h = int(round(wf * count * q)) if wf and float(wf).is_integer() else None
        pieces_v = int(round(hf * count * q)) if hf and float(hf).is_integer() else None
        lines.append({
            "category": "profile",
            "name": m.get("name") or m.get("role") or "member",
            "role": m.get("role"),
            "sku": m.get("sku") or "",
            "wFactor": wf,
            "hFactor": hf,
            "roleCount": count,
            "metres": round(metres, 4),
            "qty": round(bill_qty, 4),
            "unit": bill_unit,
            "unitRate": float(m.get("ratePerM") or 0),
            "weightKgPerM": m.get("weightKgPerM"),
            "weightKg": round(metres * float(m["weightKgPerM"]), 4) if m.get("weightKgPerM") else None,
            "piecesH": pieces_h,
            "piecesV": pieces_v,
            "cutWidthMm": w if wf else None,
            "cutHeightMm": h if hf else None,
            "remarks": m.get("notes") or f"wFactor={wf} hFactor={hf}",
        })
    return lines


def estimate_leaf_weight_kg(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float,
    height_mm: float,
    glass_kg_total: float = 0.0,
    shutter_count: float = 1.0,
    ctx: Mapping[str, Any] | None = None,
) -> float:
    """Approx one leaf/shutter weight for hardware capacity pick.

    Uses shutter-role member kg/m × perimeter share, plus glass/shutter_count.
    Falls back to glass-only / shutter_count when members lack weights.
    """
    shutters = max(float(shutter_count or 1), 1.0)
    glass_each = max(float(glass_kg_total or 0), 0.0) / shutters
    context = dict(ctx or {})
    context.setdefault("shutterCount", shutters)
    section_kg = 0.0
    for line in derive_member_cuts(
        setup, width_mm=width_mm, height_mm=height_mm, ctx=context, qty=1.0
    ):
        role = str(line.get("role") or "")
        if role not in ("shutter", "interlock", "bead"):
            continue
        wkg = line.get("weightKg")
        if wkg is None:
            continue
        # Member lines already multiply by roleCount (all shutters); per-leaf share
        section_kg += float(wkg) / shutters
    return round(glass_each + section_kg, 3)


def pick_hardware_by_weight(
    rules: Sequence[Mapping[str, Any]] | None,
    required_kg: float,
    *,
    kind: str,
    system_type: str = "",
) -> dict[str, Any] | None:
    """WD ``pickWheelByWeight`` generalised: prefer capacity ≥ required; else heaviest.

    Rules are filtered by ``kind`` and ``systemType`` (empty system on a rule
    matches any; a typed rule never crosses systems).
    """
    want_kind = _str(kind).lower().replace("-", "_")
    if want_kind == "rollers":
        want_kind = "roller"
    if want_kind == "wheels":
        want_kind = "wheel"
    # roller and wheel are interchangeable for sliding
    kind_aliases = {want_kind}
    if want_kind in ("wheel", "roller"):
        kind_aliases = {"wheel", "roller"}
    sys = normalize_system_type(system_type)
    candidates: list[dict[str, Any]] = []
    for raw in rules or []:
        rule = normalize_hardware_weight_rule(raw)
        if rule["kind"] not in kind_aliases:
            continue
        rule_sys = rule.get("systemType") or ""
        if rule_sys and sys and rule_sys != sys:
            continue
        if rule_sys and not sys:
            # setup type unknown — only accept untyped or matching later
            pass
        if not rule.get("name") and not rule.get("sku"):
            continue
        if float(rule.get("maxKg") or 0) <= 0 and float(rule.get("minKg") or 0) <= 0:
            continue
        candidates.append(rule)
    if not candidates:
        return None
    req = max(float(required_kg or 0), 0.0)
    # Prefer rules whose [minKg, maxKg] covers req; among those smallest maxKg.
    covering = [
        c for c in candidates
        if float(c.get("minKg") or 0) <= req <= (float(c.get("maxKg") or 1e9) or 1e9)
    ]
    if covering:
        covering.sort(key=lambda c: float(c.get("maxKg") or 1e9))
        return covering[0]
    # Else prefer capacity ≥ required (WD), else heaviest listed
    ordered = sorted(candidates, key=lambda c: float(c.get("maxKg") or 0))
    fit = next((c for c in ordered if float(c.get("maxKg") or 0) >= req), None)
    return fit or ordered[-1]


def apply_hardware_weight_rules(
    setup: Mapping[str, Any] | None,
    *,
    leaf_weight_kg: float,
    ctx: Mapping[str, Any] | None = None,
    system_type: str | None = None,
) -> list[dict[str, Any]]:
    """Emit priced hardware lines for each kind present in the setup rules."""
    if not isinstance(setup, Mapping):
        return []
    rules = setup.get("hardwareWeightRules") or []
    if not rules:
        return []
    context = dict(ctx or {})
    sys = normalize_system_type(
        system_type
        or setup.get("type")
        or context.get("system")
        or context.get("systemType")
        or ""
    )
    # Unique kinds in rules that match this system (or untyped)
    kinds: list[str] = []
    for raw in rules:
        rule = normalize_hardware_weight_rule(raw)
        rule_sys = rule.get("systemType") or ""
        if rule_sys and sys and rule_sys != sys:
            continue
        k = rule["kind"]
        # collapse wheel/roller
        key = "wheel" if k in ("wheel", "roller") else k
        if key not in kinds:
            kinds.append(key)
    lines: list[dict[str, Any]] = []
    for kind in kinds:
        picked = pick_hardware_by_weight(rules, leaf_weight_kg, kind=kind, system_type=sys)
        if not picked:
            continue
        qty_each = float(picked.get("qtyPer") or 1) or 1.0
        basis = str(picked.get("basis") or "shutter")
        qty = qty_each * _basis_multiplier(basis, context)
        if qty <= 0:
            continue
        cap = picked.get("maxKg")
        name = picked.get("name") or f"{kind} (auto)"
        if cap:
            name = f"{name} (≤{cap:g} kg)"
        lines.append({
            "category": "hardware",
            "name": name,
            "kind": picked.get("kind"),
            "sku": picked.get("sku") or "",
            "brand": picked.get("brand") or "",
            "qty": round(qty, 4),
            "unit": picked.get("unit") or "PC",
            "unitRate": float(picked.get("rate") or 0),
            "remarks": (
                f"weight-pick {leaf_weight_kg:g}kg · {picked.get('systemType') or sys or 'any'}"
                + (f" · {picked.get('notes')}" if picked.get("notes") else "")
            ),
            "selectBy": "weight",
            "leafWeightKg": leaf_weight_kg,
        })
    return lines


def apply_setup_bom(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float,
    height_mm: float,
    ctx: Mapping[str, Any] | None = None,
    glass_kg_total: float = 0.0,
    shutter_count: float | None = None,
    system_type: str | None = None,
    qty: float = 1.0,
) -> dict[str, Any]:
    """Combine member cuts + weight-picked hardware for the calculate pipeline.

    Returns empty lists when setup has no members/rules so legacy behaviour wins.
    """
    context = dict(ctx or {})
    shutters = float(
        shutter_count
        if shutter_count is not None
        else (context.get("shutterCount") or context.get("glassCount") or 1)
    ) or 1.0
    context.setdefault("shutterCount", shutters)
    members = derive_member_cuts(
        setup, width_mm=width_mm, height_mm=height_mm, ctx=context, qty=qty
    )
    leaf_kg = estimate_leaf_weight_kg(
        setup,
        width_mm=width_mm,
        height_mm=height_mm,
        glass_kg_total=glass_kg_total,
        shutter_count=shutters,
        ctx=context,
    )
    # If members gave no section weight, still allow glass-only leaf weight for pick
    if leaf_kg <= 0 and glass_kg_total > 0:
        leaf_kg = round(float(glass_kg_total) / shutters, 3)
    hw = apply_hardware_weight_rules(
        setup,
        leaf_weight_kg=leaf_kg,
        ctx=context,
        system_type=system_type,
    )
    # Sliding Product Gallery — structured hardwarePack + track fill sketch
    track_fill: dict[str, Any] = {}
    pack_hw: list[dict[str, Any]] = []
    if _str(setup.get("type")).lower() == "sliding" or isinstance(setup.get("sliding"), Mapping):
        track_fill = derive_sliding_track_fill(
            setup, width_mm=width_mm, height_mm=height_mm
        )
        pack_hw = derive_sliding_hardware_lines(
            setup,
            width_mm=width_mm,
            height_mm=height_mm,
            shutter_count=shutters,
        )
        # Prefer weight-picked wheels when both exist; keep pack lines for the rest
        if hw:
            pack_hw = [ln for ln in pack_hw if "wheel" not in str(ln.get("name") or "").lower()]
        hw = list(hw) + list(pack_hw)
    alu_kg = sum(float(m["weightKg"]) for m in members if m.get("weightKg") is not None)
    costing = {}
    if isinstance(setup.get("sliding"), Mapping):
        costing = (setup.get("sliding") or {}).get("costing") or {}
    return {
        "members": members,
        "hardware": hw,
        "leafWeightKg": leaf_kg,
        "aluminiumKgFromMembers": round(alu_kg, 4),
        "usedMembers": bool(members),
        "usedHardwareWeightRules": bool(hw),
        "trackFill": track_fill,
        "hardwarePackLines": pack_hw,
        "costing": costing if isinstance(costing, Mapping) else {},
        "costEngine": (costing.get("costEngine") if isinstance(costing, Mapping) else None) or "stub",
    }
