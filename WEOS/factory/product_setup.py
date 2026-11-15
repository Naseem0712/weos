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

Casement Product Gallery (``setup.casement``, Series Setup · Casement series):

* **kind** — normal | stile | slim_profile
* **normal** — outer frame all-sides same (plain / grills / grills+mesh variants);
  mullions slim|big; doors slim|big; glass clips SG|DGU; hinges↔stay exclusive
  (hinges → limitation arm); gasket (no brush); connectors 4+4; wings 8
* **Stays** — side-swing stay ≠ top-hung stay (separate catalogue rows); quote qty
  never mixed; **1 set per door** for each kind
* **stile** — no connectors; gasket top+verticals (no bottom); door sections
  hinge/top/bottom/lock; door closer 1/door; floor spring set by weight when no hinges
* **slim_profile** — outer frame all sides except bottom; door all-sides or
  verticals+top/bottom; floor spring and/or hinges
* Quote print: hinges / floor spring → name · weight capacity · brand
* Costing stub: RFT sale for stile/slim (std 2.4/2.8/3 m), wastageReuse flags

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

# Casement Product Gallery
CASEMENT_KINDS = ("normal", "stile", "slim_profile")
CASEMENT_FRAME_VARIANTS = ("plain", "grills", "grills_mesh")
CASEMENT_SECTION_SIZES = ("slim", "big")
CASEMENT_DOOR_MODES = (
    "all_sides_same",           # normal slim/big all-side · slim profile option
    "verticals_same_tb_same",   # slim profile: verticals same + top/bottom same
    "stile_sides",              # stile: hinge | top | bottom | lock
)
CASEMENT_OPEN_HW = ("hinges", "stay", "floor_spring")  # normal: hinges↔stay; stile: hinges↔floor_spring
CASEMENT_STAY_KINDS = ("side_swing", "top_hung")  # never mix qty on quote
CASEMENT_STAY_INCHES = (6, 8, 10, 12, 14, 16)
CASEMENT_STD_LENGTHS_M = (2.4, 2.8, 3.0)
CASEMENT_HINGE_QTY_MIN = 2
CASEMENT_HINGE_QTY_MAX = 8


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
    elif stype == "casement":
        cm = out.get("casement") or {}
        derived["casementKind"] = cm.get("kind")
        derived["costEngine"] = ((cm.get("costing") or {}) if isinstance(cm.get("costing"), Mapping) else {}).get(
            "costEngine", "stub"
        )
        derived["quoteHardwareNotes"] = casement_quote_hardware_descriptions(out)
        derived["wastage"] = derive_casement_wastage_flags(out)
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

    def _brand(block: Mapping[str, Any], *, name: str = "", default_origin: str = "indian") -> str:
        try:
            from WEOS.factory.hardware_brands import resolve_hardware_brand

            return resolve_hardware_brand(
                block,
                brand=block.get("brand"),
                origin=block.get("origin"),
                name=name or block.get("name"),
                default_origin=default_origin,
            )
        except Exception:
            return _str(block.get("brand")) or "HIVIC"

    def qty_rate(key: str, default_qty: float = 0.0, max_qty: float | None = None, *, name: str = "") -> dict[str, Any]:
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
            "brand": _brand(block, name=name),
            "origin": _str(block.get("origin") or "indian"),
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
        "trackConnectors": qty_rate("trackConnectors", 0, 8, name="Track connectors"),
        "shutterConnectors": qty_rate("shutterConnectors", 0, 4, name="Shutter connectors"),
        "epdm": {
            "ratePerM": _num(epdm.get("ratePerM") or epdm.get("rate")) or 0.0,
            # height×4 + width×4 (m) — computed at quote time
            "formula": _str(epdm.get("formula") or "height_m*4 + width_m*4"),
            "brand": _brand(epdm, name="EPDM"),
            "origin": _str(epdm.get("origin") or "indian"),
            "notes": _str(epdm.get("notes")),
        },
        "brush": {
            "ratePerM": _num(brush.get("ratePerM") or brush.get("rate")) or 0.0,
            "formula": _str(brush.get("formula") or "height_m*4 + width_m*4"),
            "brand": _brand(brush, name="Brush"),
            "origin": _str(brush.get("origin") or "indian"),
            "notes": _str(brush.get("notes")),
        },
        "wings": {
            # 4/shutter if slim or renf interlock; 8 if all-side same section
            "rate": _num(wings.get("rate")) or 0.0,
            "qtyAllSidesSame": int(_num(wings.get("qtyAllSidesSame")) or 8),
            "qtySplit": int(_num(wings.get("qtySplit")) or 4),
            "brand": _brand(wings, name="Wings"),
            "origin": _str(wings.get("origin") or "indian"),
            "notes": _str(wings.get("notes")),
        },
        "lock": {
            "type": lock_type,
            "rate": _num(lock.get("rate")) or 0.0,
            "unit": _str(lock.get("unit") or "SET").upper(),
            "brand": _brand(lock, name="Lock"),
            "origin": _str(lock.get("origin") or "indian"),
            "notes": _str(lock.get("notes")),
        },
        "wheels": {
            "qtyPerShutter": _num(wheels.get("qtyPerShutter") if wheels.get("qtyPerShutter") is not None else 2) or 2.0,
            "rate": _num(wheels.get("rate")) or 0.0,
            "unit": _str(wheels.get("unit") or "PC").upper(),
            "brand": _brand(wheels, name=_str(wheels.get("name") or "Wheels")),
            "origin": _str(wheels.get("origin") or "indian"),
            "name": _str(wheels.get("name")),
            "weightCapacityKg": _num(wheels.get("weightCapacityKg") or wheels.get("capacityKg")),
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


def _norm_casement_kind(value: Any) -> str:
    k = _str(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "normal_casement": "normal",
        "standard": "normal",
        "casement": "normal",
        "stile_door": "stile",
        "stile_doors": "stile",
        "slim": "slim_profile",
        "slim_profiles": "slim_profile",
        "slim_door": "slim_profile",
        "slim_doors": "slim_profile",
    }
    k = aliases.get(k, k)
    return k if k in CASEMENT_KINDS else "normal"


def _norm_frame_variant(value: Any) -> str:
    v = _str(value).lower().replace("-", "_").replace(" ", "_").replace("+", "_")
    aliases = {
        "none": "plain",
        "no_grill": "plain",
        "grill": "grills",
        "with_grills": "grills",
        "grills_and_mesh": "grills_mesh",
        "grill_mesh": "grills_mesh",
        "mesh": "grills_mesh",
    }
    v = aliases.get(v, v)
    return v if v in CASEMENT_FRAME_VARIANTS else "plain"


def _norm_size_pick(value: Any, default: str = "slim") -> str:
    v = _str(value).lower()
    if v in ("renf", "reinforced", "heavy", "large"):
        return "big"
    if v in CASEMENT_SECTION_SIZES:
        return v
    return default if default in CASEMENT_SECTION_SIZES else "slim"


def _qty_rate_block(
    raw: Any,
    *,
    default_qty: float = 0.0,
    min_qty: float | None = None,
    max_qty: float | None = None,
    default_unit: str = "PC",
) -> dict[str, Any]:
    r = raw if isinstance(raw, Mapping) else {}
    qty = _num(r.get("qty") if r.get("qty") is not None else default_qty)
    if qty is None:
        qty = default_qty
    if min_qty is not None:
        qty = max(float(min_qty), float(qty))
    if max_qty is not None:
        qty = min(float(max_qty), float(qty))
    return {
        "qty": float(qty),
        "rate": _num(r.get("rate")) or 0.0,
        "unit": _str(r.get("unit") or default_unit).upper(),
        "notes": _str(r.get("notes")),
    }


def _named_capacity_hw(raw: Any, *, default_name: str = "", default_qty: float = 1.0) -> dict[str, Any]:
    """Hardware row that must print name · weight capacity · brand on quotes."""
    r = raw if isinstance(raw, Mapping) else {}
    qty = _num(r.get("qty") if r.get("qty") is not None else default_qty)
    if qty is None:
        qty = default_qty
    return {
        "name": _str(r.get("name") or default_name),
        "brand": _str(r.get("brand")),
        "weightCapacityKg": _num(r.get("weightCapacityKg") or r.get("capacityKg") or r.get("maxKg")),
        "qty": float(qty),
        "rate": _num(r.get("rate")) or 0.0,
        "unit": _str(r.get("unit") or "PC").upper(),
        "sku": _str(r.get("sku")),
        "notes": _str(r.get("notes")),
        "enabled": _bool(r.get("enabled"), bool(_str(r.get("name") or default_name) or (_num(r.get("rate")) or 0) > 0)),
    }


def _norm_stay_lengths(raw: Any) -> list[dict[str, Any]]:
    """Stay catalogue by inch size (+ larger custom)."""
    rows: list[dict[str, Any]] = []
    if isinstance(raw, (list, tuple)):
        for it in raw:
            if isinstance(it, Mapping):
                inch = _num(it.get("inch") or it.get("sizeInch") or it.get("size"))
                rows.append({
                    "inch": inch,
                    "rate": _num(it.get("rate")) or 0.0,
                    "label": _str(it.get("label") or (f"{inch:g}\"" if inch else "")),
                    "notes": _str(it.get("notes")),
                })
            else:
                inch = _num(it)
                if inch:
                    rows.append({"inch": inch, "rate": 0.0, "label": f'{inch:g}"', "notes": ""})
    # Seed standard sizes when empty
    if not rows:
        rows = [{"inch": float(i), "rate": 0.0, "label": f'{i}"', "notes": ""} for i in CASEMENT_STAY_INCHES]
    else:
        have = {r["inch"] for r in rows if r.get("inch") is not None}
        for i in CASEMENT_STAY_INCHES:
            if float(i) not in have:
                rows.append({"inch": float(i), "rate": 0.0, "label": f'{i}"', "notes": ""})
    rows.sort(key=lambda x: (x["inch"] is None, x["inch"] or 0))
    return rows


def _norm_casement_stay_block(raw: Any, *, kind: str, default_name: str) -> dict[str, Any]:
    """One stay family — side-swing OR top-hung (never mixed on quote).

    Qty rule: **1 set per door** of that opening kind.
    """
    r = raw if isinstance(raw, Mapping) else {}
    sk = _str(kind).lower().replace("-", "_")
    if sk not in CASEMENT_STAY_KINDS:
        sk = "side_swing"
    lengths = _norm_stay_lengths(r.get("lengths") or r.get("sizes"))
    selected = _num(r.get("selectedInch") or r.get("inch") or r.get("sizeInch"))
    if selected is None and lengths:
        selected = lengths[0].get("inch")
    rate = _num(r.get("rate"))
    if rate is None or rate == 0:
        match = next((x for x in lengths if x.get("inch") == selected), None)
        rate = float((match or {}).get("rate") or 0)
    return {
        "kind": sk,
        "enabled": _bool(r.get("enabled"), False),
        "name": _str(r.get("name") or default_name),
        "brand": _str(r.get("brand")),
        "selectedInch": selected,
        "lengths": lengths,
        "rate": float(rate or 0),
        "unit": _str(r.get("unit") or "SET").upper(),
        "setsPerDoor": 1,  # always 1 set per door
        "notes": _str(r.get("notes") or "1 set per door — do not mix with the other stay kind."),
    }


def _norm_casement_gasket(raw: Any, *, kind: str) -> dict[str, Any]:
    r = raw if isinstance(raw, Mapping) else {}
    outer = r.get("outerFrame") if isinstance(r.get("outerFrame"), Mapping) else {}
    interlock = r.get("interlock") if isinstance(r.get("interlock"), Mapping) else {}
    door = r.get("doorOutside") if isinstance(r.get("doorOutside"), Mapping) else {}
    glass = r.get("glass") if isinstance(r.get("glass"), Mapping) else {}
    # Defaults by casement kind
    if kind == "stile":
        outer_formula = "height_m*2 + width_m*0"  # top + vertical×2 → encoded as H×2 (verticals) + top handled via notes
        # Prefer explicit: top (W×1) + verticals (H×2); no bottom
        outer_formula = _str(outer.get("formula") or "width_m*1 + height_m*2")
        include_bottom = False
    elif kind == "slim_profile":
        outer_formula = _str(outer.get("formula") or "width_m*1 + height_m*2")  # no bottom
        include_bottom = False
    else:
        outer_formula = _str(outer.get("formula") or "height_m*2 + width_m*2")
        include_bottom = True
    return {
        "outerFrame": {
            "ratePerM": _num(outer.get("ratePerM") or outer.get("rate")) or 0.0,
            "formula": outer_formula,
            "includeBottom": _bool(outer.get("includeBottom"), include_bottom),
            "notes": _str(outer.get("notes")),
        },
        "interlock": {
            "qtyPerPc": _num(interlock.get("qtyPerPc") if interlock.get("qtyPerPc") is not None else 2) or 2.0,
            "rate": _num(interlock.get("rate")) or 0.0,
            "unit": _str(interlock.get("unit") or "PC").upper(),
            "notes": _str(interlock.get("notes") or "2 nos per pc"),
        },
        "doorOutside": {
            "ratePerM": _num(door.get("ratePerM") or door.get("rate")) or 0.0,
            "formula": _str(door.get("formula") or "height_m*2 + width_m*2"),
            "notes": _str(door.get("notes")),
        },
        "glass": {
            "ratePerM": _num(glass.get("ratePerM") or glass.get("rate")) or 0.0,
            "formula": _str(glass.get("formula") or "height_m*4 + width_m*4"),
            "notes": _str(glass.get("notes") or "H×4 + W×4 per door"),
        },
    }


def _norm_casement_hardware_pack(raw: Any, *, kind: str) -> dict[str, Any]:
    r = raw if isinstance(raw, Mapping) else {}
    open_hw = _str(r.get("openHardware") or r.get("openHw") or "hinges").lower().replace("-", "_")
    if open_hw in ("friction_stay", "friction", "stays"):
        open_hw = "stay"
    if open_hw in ("floorspring", "floor", "pivot"):
        open_hw = "floor_spring"
    # Stile: stay not used — map stray "stay" to floor_spring
    if kind == "stile" and open_hw == "stay":
        open_hw = "floor_spring"
    if open_hw not in CASEMENT_OPEN_HW:
        open_hw = "hinges"

    hinges = r.get("hinges") if isinstance(r.get("hinges"), Mapping) else {}
    hinge_qty = _num(hinges.get("qty") if hinges.get("qty") is not None else 3)
    if hinge_qty is None:
        hinge_qty = 3.0
    hinge_qty = max(float(CASEMENT_HINGE_QTY_MIN), min(float(CASEMENT_HINGE_QTY_MAX), float(hinge_qty)))
    use_hinges = open_hw == "hinges" or (
        kind == "slim_profile" and _bool(hinges.get("enabled"), open_hw == "hinges")
    )
    hinge_block = _named_capacity_hw(
        {**hinges, "qty": hinge_qty, "enabled": use_hinges},
        default_name="Hinge",
        default_qty=hinge_qty,
    )
    hinge_block["qty"] = hinge_qty
    hinge_block["qtyEditable"] = True
    hinge_block["qtyMin"] = CASEMENT_HINGE_QTY_MIN
    hinge_block["qtyMax"] = CASEMENT_HINGE_QTY_MAX
    hinge_block["enabled"] = bool(use_hinges)

    lim = r.get("limitationArm") if isinstance(r.get("limitationArm"), Mapping) else {}
    limitation = _named_capacity_hw(lim, default_name="Limitation arm", default_qty=1.0)
    # Hinges use limitation arm; stay / floor-spring mode disables it
    limitation["enabled"] = bool(use_hinges) and _bool(lim.get("enabled"), True)

    # Side-swing stay ≠ top-hung stay — separate catalogue + quote qty (normal only)
    side_stay = _norm_casement_stay_block(
        r.get("stay") or r.get("sideSwingStay") or r.get("frictionStay"),
        kind="side_swing",
        default_name="Side-swing stay",
    )
    top_stay = _norm_casement_stay_block(
        r.get("topHungStay") or r.get("top_hung_stay") or r.get("topHung"),
        kind="top_hung",
        default_name="Top-hung stay",
    )
    if open_hw == "stay" and kind == "normal":
        hinge_block["enabled"] = False
        limitation["enabled"] = False
        if not side_stay["enabled"] and not top_stay["enabled"]:
            side_stay["enabled"] = True
    else:
        # Hinges / floor spring → no stay (unless slim explicitly keeps stays off)
        side_stay["enabled"] = False if open_hw != "stay" else side_stay["enabled"]
        top_stay["enabled"] = False if open_hw != "stay" else top_stay["enabled"]
        if open_hw != "stay":
            side_stay["enabled"] = False
            top_stay["enabled"] = False

    lock = r.get("lock") if isinstance(r.get("lock"), Mapping) else {}
    lock_type = _str(lock.get("type") or "single_point").lower().replace("-", "_").replace(" ", "_")
    if lock_type in ("single", "sp"):
        lock_type = "single_point"
    if lock_type in ("multi", "mp"):
        lock_type = "multipoint"
    if lock_type not in LOCK_TYPES:
        lock_type = "single_point"

    # Connectors: normal only (stile/slim → none)
    use_connectors = kind == "normal"
    frame_conn = _qty_rate_block(
        r.get("frameConnectors"), default_qty=4.0 if use_connectors else 0.0, max_qty=8, default_unit="PC"
    )
    door_conn = _qty_rate_block(
        r.get("doorConnectors"), default_qty=4.0 if use_connectors else 0.0, max_qty=8, default_unit="PC"
    )
    if not use_connectors:
        frame_conn["qty"] = 0.0
        door_conn["qty"] = 0.0
        frame_conn["notes"] = _str(frame_conn.get("notes") or "Not used on stile / slim profiles")
        door_conn["notes"] = _str(door_conn.get("notes") or "Not used on stile / slim profiles")

    wings = r.get("wings") if isinstance(r.get("wings"), Mapping) else {}
    wings_out = {
        "qty": int(_num(wings.get("qty")) or (8 if kind == "normal" else 0)),
        "rate": _num(wings.get("rate")) or 0.0,
        "unit": _str(wings.get("unit") or "PC").upper(),
        "notes": _str(wings.get("notes") or ("8 nos" if kind == "normal" else "")),
    }

    handles = r.get("handles") if isinstance(r.get("handles"), Mapping) else {}
    closer = r.get("doorCloser") if isinstance(r.get("doorCloser"), Mapping) else {}
    floor = r.get("floorSpring") if isinstance(r.get("floorSpring"), Mapping) else {}
    top_pivot = floor.get("topPivot") if isinstance(floor.get("topPivot"), Mapping) else floor.get("top")
    bottom_fs = (
        floor.get("bottomFloorSpring")
        if isinstance(floor.get("bottomFloorSpring"), Mapping)
        else (floor.get("bottom") if isinstance(floor.get("bottom"), Mapping) else floor)
    )
    # Stile: no hinges → floor spring. Slim: floor spring and/or hinges.
    if kind == "stile":
        use_floor = open_hw == "floor_spring" or (not hinge_block["enabled"])
        use_floor = _bool(floor.get("enabled"), use_floor)
        if hinge_block["enabled"]:
            use_floor = False
    elif kind == "slim_profile":
        use_floor = _bool(floor.get("enabled"), open_hw == "floor_spring")
    else:
        use_floor = False

    return {
        "openHardware": open_hw,
        "hinges": hinge_block,
        "limitationArm": limitation,
        "stay": side_stay,  # side-swing friction stay
        "topHungStay": top_stay,  # perfectly separate from side-swing
        "lock": {
            "type": lock_type,
            "rate": _num(lock.get("rate")) or 0.0,
            "unit": _str(lock.get("unit") or "SET").upper(),
            "name": _str(lock.get("name") or f"Lock ({lock_type})"),
            "brand": _str(lock.get("brand")),
            "notes": _str(lock.get("notes")),
        },
        "frameConnectors": frame_conn,
        "doorConnectors": door_conn,
        "wings": wings_out,
        "gasket": _norm_casement_gasket(r.get("gasket"), kind=kind),
        "handles": {
            "enabled": _bool(handles.get("enabled"), False),
            "name": _str(handles.get("name") or "Handle"),
            "brand": _str(handles.get("brand")),
            "qty": _num(handles.get("qty") if handles.get("qty") is not None else 1) or 1.0,
            "rate": _num(handles.get("rate")) or 0.0,
            "unit": _str(handles.get("unit") or "SET").upper(),
            "notes": _str(handles.get("notes")),
        },
        "doorCloser": {
            "enabled": _bool(closer.get("enabled"), kind == "stile"),
            "name": _str(closer.get("name") or "Door closer"),
            "brand": _str(closer.get("brand")),
            "weightCapacityKg": _num(closer.get("weightCapacityKg") or closer.get("capacityKg")),
            "qtyPerDoor": 1.0,
            "rate": _num(closer.get("rate")) or 0.0,
            "unit": _str(closer.get("unit") or "PC").upper(),
            "notes": _str(closer.get("notes") or "1 per door"),
        },
        "floorSpring": {
            "enabled": use_floor,
            "topPivot": _named_capacity_hw(
                top_pivot if isinstance(top_pivot, Mapping) else {},
                default_name="Top pivot",
                default_qty=1.0,
            ),
            "bottomFloorSpring": _named_capacity_hw(
                bottom_fs if isinstance(bottom_fs, Mapping) else {},
                default_name="Floor spring",
                default_qty=1.0,
            ),
            "notes": _str(floor.get("notes") or "By weight capacity — separate rates for pivot + spring"),
        },
    }


def _norm_casement_costing(raw: Any, *, kind: str) -> dict[str, Any]:
    r = raw if isinstance(raw, Mapping) else {}
    sold_rft = _bool(r.get("soldPerRft"), kind in ("stile", "slim_profile"))
    std_raw = r.get("stdLengthsM") or r.get("standardLengthsM")
    std_m: list[float] = []
    if isinstance(std_raw, (list, tuple)):
        std_m = [float(n) for n in (_num(x) for x in std_raw) if n]
    if not std_m:
        std_m = list(CASEMENT_STD_LENGTHS_M)
    default_m = _num(r.get("defaultStdLengthM") or r.get("defaultStdLength")) or 3.0
    if default_m not in std_m:
        std_m = sorted(set(std_m + [float(default_m)]))
    # Wastage: often off for stile/slim; all-side same may reuse
    reuse_default = False if kind in ("stile", "slim_profile") else True
    return {
        "labourPerSft": _num(r.get("labourPerSft") or r.get("labourRate")),
        "profitPercent": _num(r.get("profitPercent") or r.get("profit")),
        "soldPerRft": sold_rft,
        "coatedDefault": _bool(r.get("coatedDefault"), True),
        "colorRate": _num(r.get("colorRate") or r.get("coatingRate")),
        "stdLengthsM": std_m,
        "defaultStdLengthM": float(default_m),
        "projectWastageReuse": _bool(r.get("projectWastageReuse"), reuse_default),
        "allSideSameReuse": _bool(r.get("allSideSameReuse"), True),
        "chargeFullStdLengthWhenSplit": _bool(r.get("chargeFullStdLengthWhenSplit"), True),
        "verticalPcsPerDoor": int(_num(r.get("verticalPcsPerDoor")) or 2),
        "topBottomPcsPerDoor": int(_num(r.get("topBottomPcsPerDoor")) or 1),
        # "live" when fabricator has filled rates; design_cost flips to live at quote time
        # even if this flag remains stub — prefer real calc over perpetual stub.
        "costEngine": _str(r.get("costEngine") or "live"),
        "notes": _str(
            r.get("notes")
            or (
                "Stile/slim usually per RFT coated; wastage reuse often off. "
                "If top/bottom ≠ vertical → charge full std length (e.g. 2 pcs std/door verticals). "
                "Design cost charges only profiles used on the canvas."
            )
        ),
    }


def _norm_casement(raw: Any) -> dict[str, Any]:
    """Casement Product Gallery — normal | stile | slim_profile under setup.casement."""
    r = raw if isinstance(raw, Mapping) else {}
    kind = _norm_casement_kind(r.get("kind") or r.get("casementType") or r.get("variant"))
    glass = r.get("glass") if isinstance(r.get("glass"), Mapping) else {}
    glass_clips = r.get("glassClips") if isinstance(r.get("glassClips"), Mapping) else glass
    active_clip = _str(glass_clips.get("active") or glass_clips.get("type") or "sg").lower()
    if active_clip in ("dg", "dgu", "double"):
        active_clip = "dgu"
    if active_clip not in ("sg", "dgu"):
        active_clip = "sg"

    # Outer frame — always all-sides same for normal/stile; slim excludes bottom
    of = r.get("outerFrame") if isinstance(r.get("outerFrame"), Mapping) else {}
    variants_raw = of.get("variants") if isinstance(of.get("variants"), Mapping) else {}
    variants: dict[str, Any] = {}
    for vid in CASEMENT_FRAME_VARIANTS:
        src = variants_raw.get(vid) or (of if vid == "plain" and not variants_raw else None)
        # Legacy: single outerFrame section → plain
        if src is None and vid == "plain":
            src = r.get("outerFrame") if not isinstance(of.get("variants"), Mapping) else of.get("allSides")
        variants[vid] = normalize_section(src if isinstance(src, Mapping) else {})
        if not variants[vid].get("use"):
            variants[vid]["use"] = f"outer_frame_{vid}"
    active_variant = _norm_frame_variant(
        of.get("activeVariant") or r.get("activeFrameVariant") or r.get("frameVariant") or "plain"
    )
    include_bottom = kind != "slim_profile" and kind != "stile"  # stile: bottom no frame
    if kind == "stile":
        include_bottom = False
    include_bottom = _bool(of.get("includeBottom"), include_bottom)

    mull = r.get("mullions") if isinstance(r.get("mullions"), Mapping) else {}
    doors = r.get("doors") if isinstance(r.get("doors"), Mapping) else {}
    # Legacy shutter → doors.slim / allSides
    legacy_shutter = r.get("shutter") if isinstance(r.get("shutter"), Mapping) else None

    door_mode = _str(doors.get("mode") or "").lower().replace("-", "_").replace(" ", "_")
    if kind == "stile":
        door_mode = "stile_sides"
    elif kind == "slim_profile":
        if door_mode not in ("all_sides_same", "verticals_same_tb_same"):
            door_mode = "all_sides_same" if _bool(doors.get("sameAllSides"), True) else "verticals_same_tb_same"
    else:
        door_mode = "all_sides_same"

    active_door = _norm_size_pick(doors.get("active") or doors.get("size") or "slim")
    active_mullion = _norm_size_pick(mull.get("active") or mull.get("size") or "slim")

    hw_list = r.get("hardware")
    hw_pack_raw = r.get("hardwarePack") if isinstance(r.get("hardwarePack"), Mapping) else None
    if isinstance(hw_list, Mapping) and not hw_pack_raw:
        hw_pack_raw = hw_list
        hw_list = hw_list.get("items") if isinstance(hw_list.get("items"), (list, tuple)) else []

    return {
        "kind": kind,
        "activeFrameVariant": active_variant,
        "outerFrame": {
            "allSidesSame": True,  # always — variants change section, not side split
            "includeBottom": include_bottom,
            "activeVariant": active_variant,
            "variants": variants,
            # Legacy single card mirror (active variant)
            "allSides": normalize_section(
                of.get("allSides") or variants.get(active_variant) or r.get("outerFrame")
            ),
            "notes": _str(of.get("notes") or "Outer frame all sides same (variant changes section)."),
        },
        "mullions": {
            "active": active_mullion,
            "slim": normalize_section(mull.get("slim") or {"use": "mullion_slim"}),
            "big": normalize_section(mull.get("big") or {"use": "mullion_big"}),
            "notes": _str(mull.get("notes")),
        },
        "doors": {
            "mode": door_mode,
            "active": active_door,
            "slim": normalize_section(doors.get("slim") or legacy_shutter or {"use": "door_slim"}),
            "big": normalize_section(doors.get("big") or {"use": "door_big"}),
            "allSides": normalize_section(
                doors.get("allSides") or doors.get("slim") or legacy_shutter or {"use": "door"}
            ),
            "vertical": normalize_section(doors.get("vertical") or {"use": "door_vertical"}),
            "top": normalize_section(doors.get("top") or {"use": "door_top"}),
            "bottom": normalize_section(doors.get("bottom") or {"use": "door_bottom"}),
            "topBottom": normalize_section(
                doors.get("topBottom") or doors.get("top") or {"use": "door_tb"}
            ),
            # Stile split sections
            "hingeSide": normalize_section(doors.get("hingeSide") or {"use": "door_hinge"}),
            "lockSide": normalize_section(doors.get("lockSide") or {"use": "door_lock"}),
            "notes": _str(doors.get("notes")),
        },
        # Legacy mirrors for older UI / derive_section_sizes
        "shutter": normalize_section(
            legacy_shutter or doors.get("slim") or doors.get("allSides") or doors.get("hingeSide")
        ),
        "glass": {
            "sgClip": _num(glass.get("sgClip") or glass_clips.get("sgClip") or glass_clips.get("sg")),
            "dgClip": _num(glass.get("dgClip") or glass_clips.get("dgClip") or glass_clips.get("dgu")),
        },
        "glassClips": {
            "active": active_clip,
            "sg": {
                "maxMm": (
                    _num(
                        (glass_clips.get("sg") or {}).get("maxMm")
                        if isinstance(glass_clips.get("sg"), Mapping)
                        else glass_clips.get("sgMaxMm")
                    )
                    or 12.0
                ),
                "clipMm": _num(
                    glass.get("sgClip")
                    or (
                        (glass_clips.get("sg") or {}).get("clipMm")
                        if isinstance(glass_clips.get("sg"), Mapping)
                        else glass_clips.get("sgClip")
                    )
                ),
                "notes": "Single glass up to 12mm",
            },
            "dgu": {
                "clipMm": _num(
                    glass.get("dgClip")
                    or (
                        (glass_clips.get("dgu") or {}).get("clipMm")
                        if isinstance(glass_clips.get("dgu"), Mapping)
                        else glass_clips.get("dgClip")
                    )
                ),
                "notes": "Series-dependent DGU clip",
            },
        },
        "hardware": _hardware(hw_list if isinstance(hw_list, (list, tuple)) else []),
        "hardwarePack": _norm_casement_hardware_pack(hw_pack_raw or {}, kind=kind),
        "costing": _norm_casement_costing(r.get("costing"), kind=kind),
    }


def format_named_capacity_brand(item: Mapping[str, Any] | None) -> str:
    """Quote print: name, weight capacity, brand."""
    if not isinstance(item, Mapping):
        return ""
    name = _str(item.get("name")) or "Hardware"
    try:
        from WEOS.factory.hardware_brands import resolve_hardware_brand

        brand = resolve_hardware_brand(
            item,
            brand=item.get("brand"),
            origin=item.get("origin"),
            name=name,
        )
    except Exception:
        brand = _str(item.get("brand"))
    cap = _num(item.get("weightCapacityKg") or item.get("capacityKg") or item.get("maxKg"))
    bits = [name]
    if cap:
        bits.append(f"{cap:g} kg")
    if brand:
        bits.append(brand)
    return " · ".join(bits)


def casement_quote_hardware_descriptions(setup: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """Rows for quote product description when hinges / floor spring selected."""
    if not isinstance(setup, Mapping):
        return []
    cm = setup.get("casement") if isinstance(setup.get("casement"), Mapping) else setup
    if not isinstance(cm, Mapping):
        return []
    pack = cm.get("hardwarePack") if isinstance(cm.get("hardwarePack"), Mapping) else {}
    out: list[dict[str, str]] = []
    hinges = pack.get("hinges") if isinstance(pack.get("hinges"), Mapping) else {}
    if hinges.get("enabled") or (_str(pack.get("openHardware")) == "hinges" and hinges.get("name")):
        text = format_named_capacity_brand(hinges)
        if text:
            out.append({"label": "HINGES", "text": text})
        lim = pack.get("limitationArm") if isinstance(pack.get("limitationArm"), Mapping) else {}
        if lim.get("enabled") or lim.get("name") or lim.get("rate"):
            lt = format_named_capacity_brand(lim) or _str(lim.get("name") or "Limitation arm")
            if lt:
                out.append({"label": "LIMITATION ARM", "text": lt})
    fs = pack.get("floorSpring") if isinstance(pack.get("floorSpring"), Mapping) else {}
    if fs.get("enabled"):
        top = fs.get("topPivot") if isinstance(fs.get("topPivot"), Mapping) else {}
        bot = fs.get("bottomFloorSpring") if isinstance(fs.get("bottomFloorSpring"), Mapping) else {}
        if top.get("name") or top.get("rate") or top.get("weightCapacityKg"):
            out.append({"label": "TOP PIVOT", "text": format_named_capacity_brand(top)})
        if bot.get("name") or bot.get("rate") or bot.get("weightCapacityKg"):
            out.append({"label": "FLOOR SPRING", "text": format_named_capacity_brand(bot)})
    closer = pack.get("doorCloser") if isinstance(pack.get("doorCloser"), Mapping) else {}
    if closer.get("enabled") and (closer.get("name") or closer.get("rate")):
        out.append({"label": "DOOR CLOSER", "text": format_named_capacity_brand(closer)})
    return [row for row in out if row.get("text")]


def derive_casement_wastage_flags(setup: Mapping[str, Any] | None) -> dict[str, Any]:
    """Cost-engine stub flags for RFT / full-std-length charging."""
    if not isinstance(setup, Mapping):
        return {"costEngine": "stub"}
    cm = setup.get("casement") if isinstance(setup.get("casement"), Mapping) else setup
    if not isinstance(cm, Mapping):
        return {"costEngine": "stub"}
    kind = _str(cm.get("kind") or "normal")
    doors = cm.get("doors") if isinstance(cm.get("doors"), Mapping) else {}
    costing = cm.get("costing") if isinstance(cm.get("costing"), Mapping) else {}
    mode = _str(doors.get("mode") or "all_sides_same")
    all_same = mode == "all_sides_same"
    reuse = bool(costing.get("projectWastageReuse"))
    if all_same and costing.get("allSideSameReuse"):
        reuse = True
    if not all_same and costing.get("chargeFullStdLengthWhenSplit"):
        reuse = False
    return {
        "costEngine": costing.get("costEngine") or "stub",
        "kind": kind,
        "doorMode": mode,
        "soldPerRft": bool(costing.get("soldPerRft")),
        "projectWastageReuse": reuse,
        "chargeFullStdLength": (not all_same) and bool(costing.get("chargeFullStdLengthWhenSplit")),
        "verticalPcsPerDoor": int(costing.get("verticalPcsPerDoor") or 2),
        "topBottomPcsPerDoor": int(costing.get("topBottomPcsPerDoor") or 1),
        "defaultStdLengthM": costing.get("defaultStdLengthM") or 3.0,
        "stdLengthsM": list(costing.get("stdLengthsM") or CASEMENT_STD_LENGTHS_M),
        "notes": (
            "All-side same may reuse offcuts; split top/bottom≠vertical → typically "
            "2× std length verticals per door + top/bottom as sized."
        ),
    }


def derive_casement_hardware_lines(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float = 0.0,
    height_mm: float = 0.0,
    door_count: float = 1.0,
    side_swing_doors: float | None = None,
    top_hung_doors: float | None = None,
) -> list[dict[str, Any]]:
    """Expand casement hardwarePack into BOM lines.

    Stay qty: **1 set per door**, with side-swing and top-hung counted separately
    (never mixed). Pass ``side_swing_doors`` / ``top_hung_doors`` from the quote
    layout; when omitted, enabled stay families use ``door_count`` each only if
    that family is the sole enabled stay — otherwise 0 until counts are provided.
    """
    if not isinstance(setup, Mapping):
        return []
    cm = setup.get("casement") if isinstance(setup.get("casement"), Mapping) else None
    if not isinstance(cm, Mapping):
        return []
    pack = cm.get("hardwarePack") if isinstance(cm.get("hardwarePack"), Mapping) else {}
    if not pack:
        return []
    doors = max(float(door_count or 1), 1.0)
    w_m = max(float(width_mm or 0), 0.0) / 1000.0
    h_m = max(float(height_mm or 0), 0.0) / 1000.0
    kind = _str(cm.get("kind") or "normal")
    lines: list[dict[str, Any]] = []

    def add(
        name: str,
        qty: float,
        rate: float,
        unit: str = "PC",
        remarks: str = "",
        *,
        brand: str = "",
        capacity: float | None = None,
        source: str = "casement.hardwarePack",
    ) -> None:
        if qty <= 0 and rate <= 0:
            return
        display = name
        if capacity or brand:
            display = format_named_capacity_brand(
                {"name": name, "brand": brand, "weightCapacityKg": capacity}
            ) or name
        lines.append({
            "category": "hardware",
            "name": display,
            "qty": round(qty, 4),
            "unit": unit,
            "unitRate": float(rate or 0),
            "brand": brand,
            "weightCapacityKg": capacity,
            "remarks": remarks,
            "source": source,
        })

    open_hw = _str(pack.get("openHardware") or "hinges")
    hinges = pack.get("hinges") or {}
    if open_hw == "hinges" and (hinges.get("enabled") is not False):
        hq = float(hinges.get("qty") or 3)
        add(
            _str(hinges.get("name") or "Hinge"),
            hq * doors,
            float(hinges.get("rate") or 0),
            hinges.get("unit") or "PC",
            f"{hq:g}/door × {doors:g} doors (editable {CASEMENT_HINGE_QTY_MIN}–{CASEMENT_HINGE_QTY_MAX})",
            brand=_str(hinges.get("brand")),
            capacity=_num(hinges.get("weightCapacityKg")),
        )
        lim = pack.get("limitationArm") or {}
        if lim.get("enabled") is not False:
            add(
                _str(lim.get("name") or "Limitation arm"),
                float(lim.get("qty") or 1) * doors,
                float(lim.get("rate") or 0),
                lim.get("unit") or "PC",
                "with hinges — no stay",
                brand=_str(lim.get("brand")),
                capacity=_num(lim.get("weightCapacityKg")),
            )

    # Stays — side-swing ≠ top-hung; 1 set per door of that kind
    side = pack.get("stay") if isinstance(pack.get("stay"), Mapping) else {}
    top = pack.get("topHungStay") if isinstance(pack.get("topHungStay"), Mapping) else {}
    side_on = bool(side.get("enabled")) and open_hw == "stay"
    top_on = bool(top.get("enabled")) and open_hw == "stay"

    def _stay_door_qty(family_on: bool, explicit: float | None, other_on: bool) -> float:
        if not family_on:
            return 0.0
        if explicit is not None:
            return max(float(explicit), 0.0)
        # If only one stay family enabled, assume all doors use it; if both on, require explicit counts
        if other_on:
            return 0.0
        return doors

    side_n = _stay_door_qty(side_on, side_swing_doors, top_on)
    top_n = _stay_door_qty(top_on, top_hung_doors, side_on)

    if side_on and side_n > 0:
        inch = side.get("selectedInch")
        label = _str(side.get("name") or "Side-swing stay")
        if inch:
            label = f'{label} ({inch:g}")'
        add(
            label,
            side_n * float(side.get("setsPerDoor") or 1),  # 1 set per door
            float(side.get("rate") or 0),
            side.get("unit") or "SET",
            f"1 set/door · side-swing only · {side_n:g} door(s)",
            brand=_str(side.get("brand")),
            source="casement.hardwarePack.stay",
        )
    if top_on and top_n > 0:
        inch = top.get("selectedInch")
        label = _str(top.get("name") or "Top-hung stay")
        if inch:
            label = f'{label} ({inch:g}")'
        add(
            label,
            top_n * float(top.get("setsPerDoor") or 1),
            float(top.get("rate") or 0),
            top.get("unit") or "SET",
            f"1 set/door · top-hung only · {top_n:g} door(s) — not mixed with side-swing",
            brand=_str(top.get("brand")),
            source="casement.hardwarePack.topHungStay",
        )

    lock = pack.get("lock") or {}
    add(
        _str(lock.get("name") or f"Lock ({lock.get('type') or 'single_point'})"),
        doors,
        float(lock.get("rate") or 0),
        lock.get("unit") or "SET",
        "per door",
        brand=_str(lock.get("brand")),
    )

    if kind == "normal":
        fc = pack.get("frameConnectors") or {}
        add("Frame connectors", float(fc.get("qty") or 4), float(fc.get("rate") or 0), fc.get("unit") or "PC", "4 nos")
        dc = pack.get("doorConnectors") or {}
        add(
            "Door connectors",
            float(dc.get("qty") or 4) * doors,
            float(dc.get("rate") or 0),
            dc.get("unit") or "PC",
            "4 nos per door",
        )
        wings = pack.get("wings") or {}
        add(
            "Wings / angle",
            float(wings.get("qty") or 8) * doors,
            float(wings.get("rate") or 0),
            wings.get("unit") or "PC",
            "8 nos per door",
        )

    gasket = pack.get("gasket") if isinstance(pack.get("gasket"), Mapping) else {}
    outer_g = gasket.get("outerFrame") or {}
    if kind == "stile" or not outer_g.get("includeBottom", True):
        outer_m = w_m * 1.0 + h_m * 2.0  # top + vertical×2
        outer_note = "top + vertical×2 (no bottom)"
    else:
        outer_m = h_m * 2.0 + w_m * 2.0
        outer_note = "H×2 + W×2"
    add("Gasket — outer frame", outer_m, float(outer_g.get("ratePerM") or 0), "RM", outer_note)
    inter = gasket.get("interlock") or {}
    add(
        "Gasket — interlock",
        float(inter.get("qtyPerPc") or 2) * doors,
        float(inter.get("rate") or 0),
        inter.get("unit") or "PC",
        "2 nos per pc",
    )
    door_g = gasket.get("doorOutside") or {}
    add(
        "Gasket — door outside",
        (h_m * 2.0 + w_m * 2.0) * doors,
        float(door_g.get("ratePerM") or 0),
        "RM",
        "H×2 + W×2 per door",
    )
    glass_g = gasket.get("glass") or {}
    add(
        "Gasket — glass",
        (h_m * 4.0 + w_m * 4.0) * doors,
        float(glass_g.get("ratePerM") or 0),
        "RM",
        "H×4 + W×4 per door",
    )

    handles = pack.get("handles") or {}
    if handles.get("enabled"):
        add(
            _str(handles.get("name") or "Handle"),
            float(handles.get("qty") or 1) * doors,
            float(handles.get("rate") or 0),
            handles.get("unit") or "SET",
            "optional",
            brand=_str(handles.get("brand")),
        )
    closer = pack.get("doorCloser") or {}
    if closer.get("enabled"):
        add(
            _str(closer.get("name") or "Door closer"),
            float(closer.get("qtyPerDoor") or 1) * doors,
            float(closer.get("rate") or 0),
            closer.get("unit") or "PC",
            "1 per door",
            brand=_str(closer.get("brand")),
            capacity=_num(closer.get("weightCapacityKg")),
        )
    fs = pack.get("floorSpring") if isinstance(pack.get("floorSpring"), Mapping) else {}
    if fs.get("enabled"):
        top_p = fs.get("topPivot") or {}
        bot = fs.get("bottomFloorSpring") or {}
        add(
            _str(top_p.get("name") or "Top pivot"),
            float(top_p.get("qty") or 1) * doors,
            float(top_p.get("rate") or 0),
            top_p.get("unit") or "SET",
            "floor spring set",
            brand=_str(top_p.get("brand")),
            capacity=_num(top_p.get("weightCapacityKg")),
        )
        add(
            _str(bot.get("name") or "Floor spring"),
            float(bot.get("qty") or 1) * doors,
            float(bot.get("rate") or 0),
            bot.get("unit") or "SET",
            "by weight capacity",
            brand=_str(bot.get("brand")),
            capacity=_num(bot.get("weightCapacityKg")),
        )

    return [ln for ln in lines if ln["qty"] > 0 or ln["unitRate"] > 0]


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
        of = c.get("outerFrame") if isinstance(c.get("outerFrame"), Mapping) else {}
        variants = of.get("variants") if isinstance(of.get("variants"), Mapping) else {}
        active_v = _str(of.get("activeVariant") or c.get("activeFrameVariant") or "plain")
        frame_sec = (
            variants.get(active_v)
            or of.get("allSides")
            or c.get("outerFrame")
        )
        fw = _face(frame_sec if isinstance(frame_sec, Mapping) else None)
        put("topRail", fw)
        put("leftJamb", fw)
        put("rightJamb", fw)
        if of.get("includeBottom", True):
            put("bottomRail", fw)
        doors = c.get("doors") if isinstance(c.get("doors"), Mapping) else {}
        active_door = _str(doors.get("active") or "slim")
        put(
            "leafStile",
            _face(doors.get(active_door))
            or _face(doors.get("allSides"))
            or _face(doors.get("hingeSide"))
            or _face(doors.get("vertical"))
            or _face(c.get("shutter"))
            or fw,
        )
        mull = c.get("mullions") if isinstance(c.get("mullions"), Mapping) else {}
        put("mullion", _face(mull.get(mull.get("active") or "slim")) or _face(mull.get("slim")))
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

    def add(
        name: str,
        qty: float,
        rate: float,
        unit: str = "PC",
        remarks: str = "",
        *,
        brand: str = "",
        origin: str = "indian",
        capacity: float | None = None,
    ) -> None:
        if qty <= 0 and rate <= 0:
            return
        try:
            from WEOS.factory.hardware_brands import resolve_hardware_brand

            brand_r = resolve_hardware_brand(
                {"name": name, "brand": brand, "origin": origin},
                brand=brand,
                origin=origin,
                name=name,
            )
        except Exception:
            brand_r = brand or "HIVIC"
        display = name
        if brand_r and brand_r.lower() not in name.lower():
            display = f"{brand_r} {name}"
        if capacity is not None:
            display = f"{display} · {float(capacity):g} kg"
        lines.append({
            "category": "hardware",
            "name": display,
            "qty": round(qty, 4),
            "unit": unit,
            "unitRate": float(rate or 0),
            "brand": brand_r,
            "origin": origin,
            "remarks": remarks,
            "source": "sliding.hardwarePack",
        })

    tc = pack.get("trackConnectors") or {}
    add(
        "Track connectors",
        float(tc.get("qty") or 0),
        float(tc.get("rate") or 0),
        tc.get("unit") or "PC",
        brand=_str(tc.get("brand")),
        origin=_str(tc.get("origin") or "indian"),
    )
    sc = pack.get("shutterConnectors") or {}
    add(
        "Shutter connectors",
        float(sc.get("qty") or 0) * shutters,
        float(sc.get("rate") or 0),
        sc.get("unit") or "PC",
        "per shutter",
        brand=_str(sc.get("brand")),
        origin=_str(sc.get("origin") or "indian"),
    )
    epdm = pack.get("epdm") or {}
    add(
        "EPDM dual-side",
        perimeter * shutters,
        float(epdm.get("ratePerM") or 0),
        "RM",
        "height×4 + width×4 × shutters",
        brand=_str(epdm.get("brand")),
        origin=_str(epdm.get("origin") or "indian"),
    )
    brush = pack.get("brush") or {}
    add(
        "Brush",
        perimeter * shutters,
        float(brush.get("ratePerM") or 0),
        "RM",
        "same as EPDM",
        brand=_str(brush.get("brand")),
        origin=_str(brush.get("origin") or "indian"),
    )
    wings = pack.get("wings") or {}
    wqty = float(wings.get("qtyAllSidesSame") or 8) if same_shutter else float(wings.get("qtySplit") or 4)
    add(
        "Wings / angle",
        wqty * shutters,
        float(wings.get("rate") or 0),
        "PC",
        "4 split / 8 all-sides per shutter",
        brand=_str(wings.get("brand")),
        origin=_str(wings.get("origin") or "indian"),
    )
    lock = pack.get("lock") or {}
    add(
        f"Lock ({lock.get('type') or 'single_point'})",
        1.0,
        float(lock.get("rate") or 0),
        lock.get("unit") or "SET",
        brand=_str(lock.get("brand")),
        origin=_str(lock.get("origin") or "indian"),
    )
    wheels = pack.get("wheels") or {}
    wname = _str(wheels.get("name") or "Wheels")
    add(
        wname,
        float(wheels.get("qtyPerShutter") or 2) * shutters,
        float(wheels.get("rate") or 0),
        wheels.get("unit") or "PC",
        "per shutter",
        brand=_str(wheels.get("brand")),
        origin=_str(wheels.get("origin") or "indian"),
        capacity=_num(wheels.get("weightCapacityKg")),
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
    # Sliding / Casement Product Gallery — structured hardwarePack
    track_fill: dict[str, Any] = {}
    pack_hw: list[dict[str, Any]] = []
    quote_hw_notes: list[dict[str, str]] = []
    wastage: dict[str, Any] = {}
    stype = _str(setup.get("type")).lower()
    if stype == "sliding":
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
    elif stype == "casement":
        side_n = context.get("sideSwingDoors") or context.get("side_swing_doors")
        top_n = context.get("topHungDoors") or context.get("top_hung_doors")
        pack_hw = derive_casement_hardware_lines(
            setup,
            width_mm=width_mm,
            height_mm=height_mm,
            door_count=shutters,
            side_swing_doors=float(side_n) if side_n is not None else None,
            top_hung_doors=float(top_n) if top_n is not None else None,
        )
        if hw:
            # Prefer weight-picked hinges/floor springs when both exist
            pack_hw = [
                ln for ln in pack_hw
                if not any(
                    k in str(ln.get("name") or "").lower()
                    for k in ("hinge", "floor spring", "top pivot")
                )
            ]
        hw = list(hw) + list(pack_hw)
        quote_hw_notes = casement_quote_hardware_descriptions(setup)
        wastage = derive_casement_wastage_flags(setup)
    alu_kg = sum(float(m["weightKg"]) for m in members if m.get("weightKg") is not None)
    costing = {}
    if stype == "sliding" and isinstance(setup.get("sliding"), Mapping):
        costing = (setup.get("sliding") or {}).get("costing") or {}
    elif stype == "casement" and isinstance(setup.get("casement"), Mapping):
        costing = (setup.get("casement") or {}).get("costing") or {}
    elif isinstance(setup.get("sliding"), Mapping):
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
        "quoteHardwareNotes": quote_hw_notes,
        "wastage": wastage,
        "costing": costing if isinstance(costing, Mapping) else {},
        "costEngine": (costing.get("costEngine") if isinstance(costing, Mapping) else None) or "stub",
    }
