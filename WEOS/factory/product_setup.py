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

from typing import Any, Mapping, MutableMapping, Sequence

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


def _as_clip_section(raw: Any) -> dict[str, Any] | None:
    """Glass/mullion clip row: full section when present, else None."""
    if not isinstance(raw, Mapping):
        return None
    # Nested ``section`` under glassClips.sg / .dgu
    nested = raw.get("section") if isinstance(raw.get("section"), Mapping) else None
    src = nested if nested is not None else raw
    if not (
        _str(src.get("name"))
        or src.get("weightKgPerM") is not None
        or src.get("weightKgPerMtr") is not None
        or src.get("rate") is not None
        or src.get("wMm") is not None
        or src.get("widthMm") is not None
    ):
        return None
    sec = normalize_section(src)
    if _str(sec.get("name")) or (_num(sec.get("weightKgPerM")) or 0) > 0 or (_num(sec.get("rate")) or 0) > 0:
        return sec
    return None


def _clip_mm_from(raw: Any, *, fallback: Any = None) -> float | None:
    if isinstance(raw, Mapping):
        return _num(raw.get("clipMm") or raw.get("wMm") or raw.get("widthMm") or fallback)
    return _num(raw if raw not in (None, "") else fallback)


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
    # Excel / Series Setup aluminium rates are ₹/kg by default (not ₹/rft).
    rate_unit = _str(r.get("rateUnit") or "kg").lower()
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
    # Excel coating column is always ₹/RFT — keep rft unless explicitly rmt
    if coating_unit not in COATING_UNITS:
        coating_unit = "rft"
    std_len = r.get("stdLength")
    if std_len is None:
        std_len = r.get("standardLength")
    # Keep numeric mm when that is all we have (legacy Series Setup).
    std_length_mm = _num(r.get("stdLengthMm") or r.get("standardLengthMm"))
    if std_len is None and std_length_mm is not None:
        std_len = std_length_mm
    use_txt = _str(r.get("use") or r.get("position"))
    pcs_v = r.get("pcsVertical")
    pcs_h = r.get("pcsHorizontal")
    all_same = r.get("allSidesSame")
    bom_hint = _str(r.get("bomHint"))
    if pcs_v is None or pcs_h is None or all_same is None:
        try:
            from WEOS.factory.profile_hardware_import import parse_use_bom_counts

            parsed = parse_use_bom_counts(use_txt, section_name=_str(r.get("name")))
            if pcs_v is None:
                pcs_v = parsed.get("pcsVertical")
            if pcs_h is None:
                pcs_h = parsed.get("pcsHorizontal")
            if all_same is None:
                all_same = parsed.get("allSidesSame")
            if not bom_hint:
                bom_hint = _str(parsed.get("bomHint"))
        except Exception:
            pass
    return {
        "name": _str(r.get("name")),
        "use": use_txt,
        # FACE×DEPTH: wMm = face (elevation), hMm = depth (BOM/3D only)
        "wMm": _num(r.get("wMm") or r.get("widthMm") or r.get("faceMm")),
        "hMm": _num(r.get("hMm") or r.get("heightMm") or r.get("depthMm") or r.get("sectionDepthMm")),
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
        "pcsVertical": int(pcs_v) if pcs_v is not None else None,
        "pcsHorizontal": int(pcs_h) if pcs_h is not None else None,
        "allSidesSame": bool(all_same) if all_same is not None else None,
        "bomHint": bom_hint or None,
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


def canonical_track_id(value: Any) -> str:
    """Normalize 2 / 2.5 / 3 / 4 track labels to a TRACK_OPTION_IDS id."""
    tid = _str(value or "2")
    cleaned = tid.lower().replace("track", "").replace(" ", "").strip()
    if cleaned in TRACK_OPTION_IDS:
        return cleaned
    try:
        f = float(cleaned)
        return "2.5" if abs(f - 2.5) < 0.01 else str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return "2"


def section_has_profile_rates(sec: Any) -> bool:
    """True when a section can produce non-zero Al or coating ₹/m."""
    if not isinstance(sec, Mapping):
        return False
    s = normalize_section(sec)
    if _str(s.get("name")) and (_num(s.get("weightKgPerM")) or 0) > 0:
        return True
    rate = _num(s.get("rate")) or 0.0
    if rate <= 0:
        return bool((_num(s.get("coatingCost")) or 0) > 0 and _str(s.get("name")))
    unit = _str(s.get("rateUnit") or "kg").lower()
    if unit in ("kg", "per_kg", "kgm"):
        return (_num(s.get("weightKgPerM")) or 0) > 0
    return True


def track_option_is_defined(opt: Any) -> bool:
    """Track option exists on Series Setup / Excel when any side has name+weight/rate."""
    if not isinstance(opt, Mapping):
        return False
    sides = opt.get("sides") if isinstance(opt.get("sides"), Mapping) else {}
    if not sides and isinstance(opt.get("section"), Mapping):
        return section_has_profile_rates(opt.get("section"))
    for side in sides.values():
        if section_has_profile_rates(side):
            return True
    # Flat option fields (import shorthand)
    if section_has_profile_rates(opt):
        return True
    return bool((_num(opt.get("weightKgPerM")) or 0) > 0 and (_num(opt.get("rate")) or 0) > 0)


def normalize_track_option(raw: Any) -> dict[str, Any]:
    """One track option (2 / 2.5 / 3 / 4) under the same series — shutters unchanged."""
    r = raw if isinstance(raw, Mapping) else {}
    tid = canonical_track_id(r.get("id") or r.get("trackCount") or r.get("count") or "2")
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
    out = {
        "id": tid,
        "label": label,
        "trackCount": track_count,
        "railCount": int(r.get("railCount") or rail_count_for_track_option(tid)),
        "meshCapable": _bool(r.get("meshCapable"), float(tid) >= 2.5),
        "sides": base,
        "notes": _str(r.get("notes")),
    }
    out["defined"] = track_option_is_defined(out)
    return out


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
    mesh_wheels = (
        r.get("meshWheels")
        if isinstance(r.get("meshWheels"), Mapping)
        else (r.get("mesh_wheels") if isinstance(r.get("mesh_wheels"), Mapping) else {})
    )
    lock_type = _str(lock.get("type") or "single_point").lower().replace("-", "_").replace(" ", "_")
    if lock_type in ("single", "sp"):
        lock_type = "single_point"
    if lock_type in ("multi", "mp"):
        lock_type = "multipoint"
    if lock_type not in LOCK_TYPES:
        lock_type = "single_point"

    def _wheel_block(block: Mapping[str, Any], *, default_name: str, default_cap: float | None = None) -> dict[str, Any]:
        return {
            "qtyPerShutter": _num(block.get("qtyPerShutter") if block.get("qtyPerShutter") is not None else 2) or 2.0,
            "rate": _num(block.get("rate")) or 0.0,
            "unit": _str(block.get("unit") or "PC").upper(),
            "brand": _brand(block, name=_str(block.get("name") or default_name)),
            "origin": _str(block.get("origin") or "indian"),
            "name": _str(block.get("name") or default_name),
            "id": _str(block.get("id") or block.get("hardwareId")),
            "weightCapacityKg": _num(block.get("weightCapacityKg") or block.get("capacityKg") or default_cap),
            "notes": _str(block.get("notes")),
        }

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
        # Glass shutter wheels — capacity should cover shutter glass weight
        "wheels": _wheel_block(wheels, default_name="Wheels"),
        # Mesh shutters use regular/light mesh wheels (not heavy glass wheels)
        "meshWheels": _wheel_block(
            mesh_wheels or {"name": "Mesh wheel", "rate": _num(wheels.get("rate")) or 70.0, "weightCapacityKg": 40.0},
            default_name="Mesh wheel",
            default_cap=40.0,
        ),
    }


def _norm_sliding_costing(raw: Any) -> dict[str, Any]:
    """Labour / profit / wastage hooks — full project cost may stub until all products quoted."""
    r = raw if isinstance(raw, Mapping) else {}
    try:
        from WEOS.factory.commercial_defaults import installation_per_sft, labour_per_sft

        labour = labour_per_sft(r.get("labourPerSft") or r.get("labourRate"))
        install = installation_per_sft(r.get("installationPerSft") or r.get("installPerSft"))
    except Exception:
        labour = _num(r.get("labourPerSft") or r.get("labourRate"))
        install = _num(r.get("installationPerSft") or r.get("installPerSft"))
    return {
        "labourPerSft": labour,
        "installationPerSft": install,
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
            # 1 pc per interlock (glass + mesh) — length = shutter height
            "glassReducer": normalize_section(
                sh.get("glassReducer") or sh.get("glass_reducer") or sh.get("reducer")
            ),
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
        side_stay["enabled"] = True
        # topHungStay catalogue stays enabled for top-hung doors (stay-only path)
    else:
        # Side-swing hinges / floor spring → no side-swing stay.
        # Top-hung stay remains available whenever top-hung doors appear on quote.
        if open_hw != "stay":
            side_stay["enabled"] = False
        if open_hw == "floor_spring":
            # Floor spring mode does not use side stay; top-hung stay still OK on mixed layouts
            pass

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
    try:
        from WEOS.factory.commercial_defaults import installation_per_sft, labour_per_sft

        labour = labour_per_sft(r.get("labourPerSft") or r.get("labourRate"))
        install = installation_per_sft(r.get("installationPerSft") or r.get("installPerSft"))
    except Exception:
        labour = _num(r.get("labourPerSft") or r.get("labourRate"))
        install = _num(r.get("installationPerSft") or r.get("installPerSft"))
    return {
        "labourPerSft": labour,
        "installationPerSft": install,
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
            "sgClip": _as_clip_section(glass.get("sgClip"))
            or _as_clip_section(glass_clips.get("sg"))
            or _num(glass.get("sgClip") if not isinstance(glass.get("sgClip"), Mapping) else None),
            "dgClip": _as_clip_section(glass.get("dgClip"))
            or _as_clip_section(glass_clips.get("dgu") or glass_clips.get("dg"))
            or _num(glass.get("dgClip") if not isinstance(glass.get("dgClip"), Mapping) else None),
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
                "clipMm": _clip_mm_from(
                    glass_clips.get("sg") if isinstance(glass_clips.get("sg"), Mapping) else None,
                    fallback=glass.get("sgClip") if not isinstance(glass.get("sgClip"), Mapping) else None,
                ),
                "section": _as_clip_section(glass.get("sgClip"))
                or _as_clip_section(glass_clips.get("sg"))
                or {},
                "notes": "Single glass up to 12mm",
            },
            "dgu": {
                "clipMm": _clip_mm_from(
                    glass_clips.get("dgu") if isinstance(glass_clips.get("dgu"), Mapping) else None,
                    fallback=glass.get("dgClip") if not isinstance(glass.get("dgClip"), Mapping) else None,
                ),
                "section": _as_clip_section(glass.get("dgClip"))
                or _as_clip_section(glass_clips.get("dgu") or glass_clips.get("dg"))
                or {},
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
    # Explicit layout counts of 0 operable must stay 0 (fixed+mullion only).
    # Legacy callers that omit counts still default to 1 door.
    if side_swing_doors is not None or top_hung_doors is not None:
        doors = max(float(side_swing_doors or 0) + float(top_hung_doors or 0), 0.0)
    else:
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
        if qty <= 0:
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

    # Side-swing: stay XOR hinge (mutually exclusive). Top hung: stay only (never hinge).
    open_hw = _str(pack.get("openHardware") or "hinges")
    side = pack.get("stay") if isinstance(pack.get("stay"), Mapping) else {}
    top = pack.get("topHungStay") if isinstance(pack.get("topHungStay"), Mapping) else {}
    side_flag = bool(side.get("enabled"))
    top_flag = bool(top.get("enabled"))

    if side_swing_doors is not None or top_hung_doors is not None:
        side_n_doors = float(side_swing_doors) if side_swing_doors is not None else max(
            doors - float(top_hung_doors or 0), 0.0
        )
        top_n_doors = float(top_hung_doors) if top_hung_doors is not None else max(
            doors - side_n_doors, 0.0
        )
    else:
        # No layout counts: never guess when both stay families are enabled
        if open_hw == "stay" and side_flag and top_flag:
            side_n_doors = 0.0
            top_n_doors = 0.0
        elif open_hw == "stay" and top_flag and not side_flag:
            side_n_doors = 0.0
            top_n_doors = doors
        else:
            # Hinges path, or sole side-stay family → all doors are side-swing
            side_n_doors = doors
            top_n_doors = 0.0

    hinges = pack.get("hinges") or {}
    side_uses_hinge = open_hw == "hinges" and side_n_doors > 0 and (hinges.get("enabled") is not False)
    side_uses_stay = open_hw == "stay" and side_n_doors > 0 and (side_flag or not top_flag)
    # Top hung always uses stay when layout counts say so (never hinge), even if
    # series openHardware is hinges. Without counts, only when top_flag is on.
    top_uses_stay = top_n_doors > 0 and (
        top_flag or side_swing_doors is not None or top_hung_doors is not None
    )

    if side_uses_hinge:
        hq = float(hinges.get("qty") or 3)
        add(
            _str(hinges.get("name") or "Hinge"),
            hq * side_n_doors,
            float(hinges.get("rate") or 0),
            hinges.get("unit") or "PC",
            f"{hq:g}/door × {side_n_doors:g} side-swing door(s) (editable {CASEMENT_HINGE_QTY_MIN}–{CASEMENT_HINGE_QTY_MAX})",
            brand=_str(hinges.get("brand")),
            capacity=_num(hinges.get("weightCapacityKg")),
        )
        lim = pack.get("limitationArm") or {}
        if lim.get("enabled") is not False:
            add(
                _str(lim.get("name") or "Limitation arm"),
                float(lim.get("qty") or 1) * side_n_doors,
                float(lim.get("rate") or 0),
                lim.get("unit") or "PC",
                "with side-swing hinges — no stay",
                brand=_str(lim.get("brand")),
                capacity=_num(lim.get("weightCapacityKg")),
            )

    if side_uses_stay and not side_uses_hinge:
        inch = side.get("selectedInch")
        label = _str(side.get("name") or "Side-swing stay")
        if inch:
            label = f'{label} ({inch:g}")'
        add(
            label,
            side_n_doors * float(side.get("setsPerDoor") or 1),
            float(side.get("rate") or 0),
            side.get("unit") or "SET",
            f"1 set/door · side-swing only · {side_n_doors:g} door(s)",
            brand=_str(side.get("brand")),
            source="casement.hardwarePack.stay",
        )
    if top_uses_stay:
        inch = top.get("selectedInch")
        label = _str(top.get("name") or "Top-hung stay")
        if inch:
            label = f'{label} ({inch:g}")'
        add(
            label,
            top_n_doors * float(top.get("setsPerDoor") or 1),
            float(top.get("rate") or 0),
            top.get("unit") or "SET",
            f"1 set/door · top-hung stay only (no hinge) · {top_n_doors:g} door(s)",
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
    """Visible elevation face (mm) — geometry frame thickness on 2D preview.

    Written size is FACE×DEPTH: ``wMm`` / ``widthMm`` = face (before X);
    ``hMm`` / ``sectionDepthMm`` = depth into the opening and must NOT be used
    as elevation member width. Prefer face fields; never fall back to hMm.
    """
    if not isinstance(section, Mapping):
        return None
    return (
        _num(section.get("wMm"))
        or _num(section.get("widthMm"))
        or _num(section.get("faceMm"))
        or _num(section.get("wallMm"))
    )


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


def defined_track_options(setup: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Track options that exist on this series (Excel / Series Setup), not empty placeholders."""
    if not isinstance(setup, Mapping):
        return []
    sl = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else None
    if not isinstance(sl, Mapping) and _str(setup.get("type")).lower() == "sliding":
        sl = setup
    if not isinstance(sl, Mapping):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in sl.get("trackOptions") or []:
        opt = normalize_track_option(raw)
        if not opt.get("defined"):
            continue
        if opt["id"] in seen:
            continue
        seen.add(opt["id"])
        out.append(opt)
    return out


def select_track_option(
    setup: Mapping[str, Any] | None,
    track_count: Any = None,
) -> dict[str, Any] | None:
    """Pick track option for BOM/cost: prefer cart trackCount, else active, else first defined.

    Never returns an empty placeholder when a defined track exists on the series.
    """
    if not isinstance(setup, Mapping):
        return None
    sl = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else None
    if not isinstance(sl, Mapping) and _str(setup.get("type")).lower() == "sliding":
        sl = setup
    if not isinstance(sl, Mapping):
        return None
    opts_all = [normalize_track_option(o) for o in (sl.get("trackOptions") or []) if isinstance(o, Mapping)]
    defined = [o for o in opts_all if o.get("defined")]
    pool = defined or opts_all
    if not pool:
        return None

    wanted = None
    if track_count not in (None, ""):
        wanted = canonical_track_id(track_count)
    if not wanted:
        wanted = canonical_track_id(sl.get("activeTrackOption") or pool[0]["id"])

    by_id = {o["id"]: o for o in pool}
    if wanted in by_id:
        return by_id[wanted]
    # Nearest defined track by count
    try:
        w = float(wanted)
        ranked = sorted(pool, key=lambda o: abs(float(o.get("trackCount") or o["id"]) - w))
        return ranked[0]
    except (TypeError, ValueError):
        return pool[0]


def setup_has_profile_rates(setup: Mapping[str, Any] | None) -> bool:
    """True when sliding/casement setup has at least one section with billable Al/coat."""
    if not isinstance(setup, Mapping):
        return False
    try:
        norm = normalize_setup(setup)
    except Exception:
        norm = setup
    if not isinstance(norm, Mapping):
        return False
    if defined_track_options(norm):
        return True
    sl = norm.get("sliding") if isinstance(norm.get("sliding"), Mapping) else {}
    shut = sl.get("shutters") if isinstance(sl.get("shutters"), Mapping) else {}
    for key in ("allSides", "handleSide", "top", "bottom", "interlockSlim", "interlockRenf", "glassReducer"):
        if section_has_profile_rates(shut.get(key)):
            return True
    cm = norm.get("casement") if isinstance(norm.get("casement"), Mapping) else {}

    def _walk_sections(node: Any, depth: int = 0) -> bool:
        if depth > 5 or node is None:
            return False
        if isinstance(node, Mapping):
            if section_has_profile_rates(node):
                return True
            return any(_walk_sections(v, depth + 1) for v in node.values())
        if isinstance(node, (list, tuple)):
            return any(_walk_sections(v, depth + 1) for v in node)
        return False

    for key in (
        "outerFrame",
        "outer",
        "mullions",
        "mullion",
        "doors",
        "door",
        "shutter",
        "leaf",
        "sash",
        "frame",
        "glassClips",
    ):
        if _walk_sections(cm.get(key)):
            return True
    return False


def with_active_track(setup: Mapping[str, Any] | None, track_count: Any = None) -> dict[str, Any]:
    """Copy setup with ``activeTrackOption`` synced to cart trackCount (defined tracks only)."""
    import copy

    if not isinstance(setup, Mapping):
        return {}
    out = copy.deepcopy(dict(setup))
    norm = normalize_setup(out)
    opt = select_track_option(norm, track_count=track_count)
    if opt and isinstance(norm.get("sliding"), dict):
        norm["sliding"]["activeTrackOption"] = opt["id"]
        # Drop undefined placeholders from the working copy used for BOM/cost
        defined = defined_track_options(norm)
        if defined:
            # Keep undefined slots out of costing selection, but preserve defined list order
            by_id = {o["id"]: o for o in (norm["sliding"].get("trackOptions") or []) if isinstance(o, Mapping)}
            norm["sliding"]["trackOptions"] = [by_id.get(o["id"], o) for o in defined]
    return norm


def active_track_option(setup: Mapping[str, Any] | None, track_count: Any = None) -> dict[str, Any] | None:
    """Return the normalised active track option from a sliding setup."""
    return select_track_option(setup, track_count=track_count)


def assign_sliding_interlocks(
    *,
    glass_count: float | int = 2,
    mesh_count: float | int = 0,
    opening: str | None = None,
    track_count: float | int | None = None,
    series_has_slim: bool = True,
) -> dict[str, Any]:
    """Clear sliding interlock mix — glass shutters + mesh (slim only).

    Glass:
      - 2 shutters → 1 slim + 1 reinforcement
      - 4 + center opening → 2 slim + 2 reinforcement
      - 3 shutters → 2 reinforcement + 1 slim
      - 4 + 4-track + side opening → 1 slim + 3 reinforcement
    Mesh: always slim only when series has slim interlock (never renf on mesh).
    Glass reducer: 1 pc per interlock (glass + mesh).
    """
    g = max(int(round(float(glass_count or 0))), 0)
    m = max(int(round(float(mesh_count or 0))), 0)
    op = _str(opening).lower().replace("-", "_").replace(" ", "_")
    if op in ("centre", "center_opening", "centre_opening"):
        op = "center"
    if op in ("side", "side_opening", "telescopic", "end"):
        op = "side"
    if not op:
        op = "center" if g == 4 else "side"
    tc = float(track_count or 0)

    slim = 0
    renf = 0
    rule = "none"
    if g <= 0:
        rule = "no_glass"
    elif g == 2:
        slim, renf, rule = 1, 1, "2_glass_1slim_1renf"
    elif g == 3:
        slim, renf, rule = 1, 2, "3_glass_1slim_2renf"
    elif g == 4 and op == "side" and tc >= 3.99:
        slim, renf, rule = 1, 3, "4_glass_4track_side_1slim_3renf"
    elif g == 4:
        slim, renf, rule = 2, 2, "4_glass_center_2slim_2renf"
    else:
        if op == "center":
            slim = max(g // 2, 1)
            renf = max(g - slim, 0)
            rule = f"{g}_glass_center_split"
        else:
            slim, renf = 1, max(g - 1, 0)
            rule = f"{g}_glass_side_1slim_rest_renf"

    mesh_slim = m if m > 0 else 0
    if m > 0 and not series_has_slim:
        mesh_slim = m  # still slim-equivalent pcs; never renf on mesh

    total_interlocks = slim + renf + mesh_slim
    return {
        "glassCount": g,
        "meshCount": m,
        "opening": op,
        "trackCount": tc if tc > 0 else None,
        "slim": slim,
        "renf": renf,
        "meshSlim": mesh_slim,
        "glassReducerPcs": total_interlocks,
        "totalInterlocks": total_interlocks,
        "rule": rule,
        "meshRule": "mesh_slim_only",
        "seriesHasSlim": bool(series_has_slim),
        "notes": (
            "Mesh uses slim interlock only. "
            "Glass reducer = 1 pc per interlock (glass + mesh)."
        ),
    }


def derive_sliding_shutter_frame_cuts(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float,
    height_mm: float,
    glass_count: float = 2.0,
    colour: str | None = None,
) -> dict[str, Any]:
    """Shutter frame cuts from Excel V/H / V2 H2 on shutter sections.

    - all-sides (V2 H2): 2 vertical @ H + 2 horizontal @ leaf-width, × glass shutters
    - split: handleSide V @ H; top/bottom H @ leaf-width, × glass shutters
    Interlocks are handled separately by ``derive_sliding_interlock_cuts``.
    """
    if not isinstance(setup, Mapping):
        return {"lines": [], "cutSpecs": []}
    sl = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else {}
    sh = sl.get("shutters") if isinstance(sl.get("shutters"), Mapping) else {}
    g = max(int(round(float(glass_count or 1))), 1)
    h_m = max(float(height_mm or 0), 0.0) / 1000.0
    leaf_w_m = max(float(width_mm or 0), 0.0) / 1000.0 / g
    mode = _str(sh.get("mode") or ("all_sides_same" if sh.get("sameAllSides") else "split"))
    lines: list[dict[str, Any]] = []
    cut_specs: list[dict[str, Any]] = []

    def _add(sec: Any, qty: float, length_m: float, *, use: str, label: str) -> None:
        if qty <= 0 or length_m <= 0:
            return
        s = normalize_section(sec) if isinstance(sec, Mapping) else normalize_section({})
        display = _str(s.get("name")) or label
        q = float(qty)
        lines.append({
            "category": "profile",
            "name": display,
            "catalogueName": display,
            "use": use,
            "qty": q,
            "pcs": int(round(q)) if abs(q - round(q)) < 1e-6 else round(q, 4),
            "lengthM": round(length_m, 4),
            "metres": round(length_m * q, 4),
            "unit": "RM",
            "section": s,
            "colour": _str(colour),
            "remarks": f"{label} ×{int(round(q))}",
            "sides": use.replace("_", " "),
        })
        for _ in range(max(int(round(q)), 0)):
            cut_specs.append({
                "lengthM": length_m,
                "section": s,
                "use": use,
                "sectionName": display,
                "colour": _str(colour),
            })

    if mode == "all_sides_same":
        sec = sh.get("allSides") or sh.get("handleSide") or {}
        ns = normalize_section(sec if isinstance(sec, Mapping) else {})
        v = int(ns.get("pcsVertical") or 2)
        h = int(ns.get("pcsHorizontal") or 2)
        _add(sec, v * g, h_m, use="shutter_vertical", label="Shutter vertical")
        _add(sec, h * g, leaf_w_m, use="shutter_horizontal", label="Shutter top/bottom")
    else:
        handle = sh.get("handleSide") or {}
        top = sh.get("top") or {}
        bot = sh.get("bottom") or {}
        hn = normalize_section(handle if isinstance(handle, Mapping) else {})
        tn = normalize_section(top if isinstance(top, Mapping) else {})
        bn = normalize_section(bot if isinstance(bot, Mapping) else {})
        v_pcs = int(hn.get("pcsVertical") or 1)
        # handle side top,bottom row often has V=1 H=2 on one combined section
        if _str(hn.get("name")) and ("top" in _str(hn.get("name")).lower() or "bottom" in _str(hn.get("name")).lower()):
            h_pcs = int(hn.get("pcsHorizontal") or 2)
            _add(handle, v_pcs * g, h_m, use="shutter_handle", label="Handle-side vertical")
            _add(handle, h_pcs * g, leaf_w_m, use="shutter_top_bottom", label="Shutter top/bottom")
        else:
            _add(handle, v_pcs * g, h_m, use="shutter_handle", label="Handle-side vertical")
            t_pcs = int(tn.get("pcsHorizontal") or tn.get("pcsVertical") or (1 if _str(tn.get("name")) else 0))
            b_pcs = int(bn.get("pcsHorizontal") or bn.get("pcsVertical") or (1 if _str(bn.get("name")) else 0))
            if t_pcs:
                _add(top, t_pcs * g, leaf_w_m, use="shutter_top", label="Shutter top")
            if b_pcs:
                _add(bot, b_pcs * g, leaf_w_m, use="shutter_bottom", label="Shutter bottom")
            # Combined "handle side, top, bottom" with H=2 already covered above
            if not t_pcs and not b_pcs and int(hn.get("pcsHorizontal") or 0) > 0:
                _add(handle, int(hn.get("pcsHorizontal") or 0) * g, leaf_w_m, use="shutter_top_bottom", label="Shutter top/bottom")

    return {"lines": lines, "cutSpecs": cut_specs, "mode": mode, "glassCount": g}


def derive_sliding_interlock_cuts(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float,
    height_mm: float,
    glass_count: float = 2.0,
    mesh_count: float = 0.0,
    opening: str | None = None,
    track_count: float | None = None,
    colour: str | None = None,
) -> dict[str, Any]:
    """Profile cut lines for slim/renf/mesh interlocks + glass reducer (1/interlock)."""
    if not isinstance(setup, Mapping):
        return {"assignment": {}, "lines": [], "cutSpecs": []}
    sl = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else {}
    sh = sl.get("shutters") if isinstance(sl.get("shutters"), Mapping) else {}
    slim_sec = normalize_section(sh.get("interlockSlim") or sh.get("interlockSide") or {})
    renf_sec = normalize_section(sh.get("interlockRenf") or {})
    reducer_sec = normalize_section(sh.get("glassReducer") or {})
    series_has_slim = bool(
        _str(slim_sec.get("name"))
        or _num(slim_sec.get("rate"))
        or _num(slim_sec.get("weightKgPerM"))
    )
    assign = assign_sliding_interlocks(
        glass_count=glass_count,
        mesh_count=mesh_count,
        opening=opening,
        track_count=track_count,
        series_has_slim=series_has_slim,
    )
    h_m = max(float(height_mm or 0), 0.0) / 1000.0
    lines: list[dict[str, Any]] = []
    cut_specs: list[dict[str, Any]] = []

    def _add(sec: Mapping[str, Any], qty: float, *, use: str, label: str) -> None:
        if qty <= 0 or h_m <= 0:
            return
        s = normalize_section(sec) if isinstance(sec, Mapping) else {}
        display = _str(s.get("name")) or label
        q = float(qty)
        lines.append({
            "category": "profile",
            "name": display,
            "catalogueName": display,
            "use": use,
            "qty": q,
            "pcs": int(round(q)) if abs(q - round(q)) < 1e-6 else round(q, 4),
            "lengthM": round(h_m, 4),
            "metres": round(h_m * q, 4),
            "unit": "RM",
            "section": s,
            "colour": _str(colour),
            "remarks": f"{label} ×{int(round(q))} @ H",
            "sides": use.replace("_", " "),
        })
        for _ in range(max(int(round(q)), 0)):
            cut_specs.append({
                "lengthM": h_m,
                "section": s,
                "use": use,
                "sectionName": display,
                "colour": _str(colour),
            })

    _add(slim_sec, assign["slim"], use="interlock_slim", label="Slim interlock")
    _add(renf_sec or slim_sec, assign["renf"], use="interlock_renf", label="Reinforcement interlock")
    if assign["meshSlim"] > 0:
        _add(slim_sec, assign["meshSlim"], use="interlock_mesh_slim", label="Mesh slim interlock")

    reducer_pcs = float(assign.get("glassReducerPcs") or 0)
    if reducer_pcs > 0:
        if not _str(reducer_sec.get("name")) and not _num(reducer_sec.get("rate")):
            try:
                for sec in flatten_setup_sections(setup):
                    if "reducer" in _str(sec.get("name")).lower():
                        reducer_sec = normalize_section(sec)
                        break
            except Exception:
                pass
        _add(reducer_sec, reducer_pcs, use="glass_reducer", label="Glass reducer")

    return {
        "assignment": assign,
        "lines": lines,
        "cutSpecs": cut_specs,
        "heightM": round(h_m, 4),
    }


def derive_sliding_track_fill(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float = 0.0,
    height_mm: float = 0.0,
    track_count: Any = None,
) -> dict[str, Any]:
    """BOM fill sketch for the active track option (qty + section refs).

    ``track_count`` from the cart overrides saved ``activeTrackOption`` so 3/4-track
    live cost uses that series' defined track sections (not an empty placeholder).
    """
    if not isinstance(setup, Mapping):
        return {"pattern": "all_side_4", "rails": 2, "pieces": {}, "lines": []}
    sl = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else setup
    if not isinstance(sl, Mapping):
        return {"pattern": "all_side_4", "rails": 2, "pieces": {}, "lines": []}
    pattern = _norm_bom_pattern(sl.get("bomPattern"), _str(sl.get("trackMode")))
    pieces = bom_qty_for_pattern(pattern)
    blob = setup if setup.get("sliding") else {"sliding": sl, "type": "sliding"}
    opt = select_track_option(blob, track_count=track_count)
    if opt is None and isinstance(setup.get("sliding"), Mapping):
        opt = select_track_option(setup, track_count=track_count)
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
        ns = normalize_section(sec) if sec is not None else normalize_section({})
        # Excel V2/H2 → 2 vertical @ H + 2 horizontal @ W (one section, all sides)
        v_pcs = ns.get("pcsVertical")
        h_pcs = ns.get("pcsHorizontal")
        if ns.get("allSidesSame") or (v_pcs and h_pcs) or _str(ns.get("bomHint")) == "all_sides_same_v2h2":
            add_line("track_vertical", int(v_pcs or 2), sec, h)
            add_line("track_horizontal", int(h_pcs or 2), sec, w)
        else:
            add_line("track_all", pieces.get("all") or 4, sec, 0)
    elif mode == "verticals_same_h_diff":
        vsec = normalize_section(sides.get("vertical") or {})
        tsec = normalize_section(sides.get("top") or {})
        bsec = normalize_section(sides.get("bottom") or {})
        v_q = vsec.get("pcsVertical") or pieces.get("vertical") or 2
        # Top/bottom may carry pcsHorizontal (or inverted Excel V count → already corrected)
        t_q = tsec.get("pcsHorizontal") or pieces.get("top") or 1
        b_q = bsec.get("pcsHorizontal") or pieces.get("bottom") or 1
        add_line("track_vertical", int(v_q), sides.get("vertical"), h)
        add_line("track_top", int(t_q), sides.get("top"), w)
        add_line("track_bottom", int(b_q), sides.get("bottom"), w)
    else:
        lv = normalize_section(sides.get("leftVertical") or {})
        rv = normalize_section(sides.get("rightVertical") or {})
        tsec = normalize_section(sides.get("top") or {})
        bsec = normalize_section(sides.get("bottom") or {})
        add_line("track_left", int(lv.get("pcsVertical") or 1), sides.get("leftVertical"), h)
        add_line("track_right", int(rv.get("pcsVertical") or 1), sides.get("rightVertical"), h)
        top_q = tsec.get("pcsHorizontal") or pieces.get("top") or 1
        bot_q = bsec.get("pcsHorizontal") or pieces.get("bottom") or 1
        add_line("track_top", int(top_q), sides.get("top"), w)
        add_line("track_bottom", int(bot_q), sides.get("bottom"), w)

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
    mesh_count: float = 0.0,
) -> list[dict[str, Any]]:
    """Expand structured hardwarePack into priced BOM lines (per opening).

    Glass wheels are charged per glass shutter; mesh wheels are charged per
    mesh shutter (regular/light mesh wheels — never the heavy glass pick).
    Other pack items stay per glass shutter unless noted.
    """
    if not isinstance(setup, Mapping):
        return []
    sl = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else None
    if not isinstance(sl, Mapping):
        return []
    pack = sl.get("hardwarePack") if isinstance(sl.get("hardwarePack"), Mapping) else {}
    if not pack:
        return []

    def _pack_configured(p: Mapping[str, Any]) -> bool:
        for key in ("trackConnectors", "shutterConnectors", "wheels", "meshWheels", "lock", "wings"):
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
    mesh_n = max(float(mesh_count or 0), 0.0)
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
        source: str = "sliding.hardwarePack",
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
            "source": source,
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
        "per glass shutter",
        brand=_str(sc.get("brand")),
        origin=_str(sc.get("origin") or "indian"),
    )
    epdm = pack.get("epdm") or {}
    add(
        "EPDM dual-side",
        perimeter * shutters,
        float(epdm.get("ratePerM") or 0),
        "RM",
        "height×4 + width×4 × glass shutters",
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
        "4 split / 8 all-sides per glass shutter",
        brand=_str(wings.get("brand")),
        origin=_str(wings.get("origin") or "indian"),
    )
    lock = pack.get("lock") or {}
    add(
        f"Lock ({lock.get('type') or 'single_point'})",
        1.0,
        float(lock.get("rate") or 0),
        lock.get("unit") or "SET",
        "per opening",
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
        f"per glass shutter · {shutters:g} shutter(s)",
        brand=_str(wheels.get("brand")),
        origin=_str(wheels.get("origin") or "indian"),
        capacity=_num(wheels.get("weightCapacityKg")),
        source="sliding.hardwarePack.wheels",
    )
    if mesh_n > 0:
        mw = pack.get("meshWheels") if isinstance(pack.get("meshWheels"), Mapping) else {}
        if not mw:
            mw = {
                "name": "Mesh wheel",
                "qtyPerShutter": float(wheels.get("qtyPerShutter") or 2),
                "rate": min(float(wheels.get("rate") or 70), 70.0),
                "unit": "PC",
                "brand": _str(wheels.get("brand")),
                "origin": _str(wheels.get("origin") or "indian"),
                "weightCapacityKg": 40.0,
            }
        add(
            _str(mw.get("name") or "Mesh wheel"),
            float(mw.get("qtyPerShutter") or 2) * mesh_n,
            float(mw.get("rate") or 0),
            mw.get("unit") or "PC",
            f"regular mesh wheels · per mesh shutter · {mesh_n:g} shutter(s)",
            brand=_str(mw.get("brand")),
            origin=_str(mw.get("origin") or "indian"),
            capacity=_num(mw.get("weightCapacityKg") or 40),
            source="sliding.hardwarePack.meshWheels",
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


def shutter_glass_weight_kg(
    glass_id: str | None,
    *,
    width_mm: float,
    height_mm: float,
    shutter_count: float = 1.0,
) -> dict[str, Any]:
    """Glass weight for one shutter from selected glass pack / thickness.

    Pane approx = (opening width ÷ shutter count) × height. Uses catalogue
    density / makeup via :func:`WEOS.factory.glass_catalogue.glass_weight`.
    """
    shutters = max(float(shutter_count or 1), 1.0)
    pane_w = max(float(width_mm or 0), 0.0) / shutters
    pane_h = max(float(height_mm or 0), 0.0)
    gid = _str(glass_id)
    out: dict[str, Any] = {
        "glassId": gid or None,
        "paneWidthMm": round(pane_w, 1),
        "paneHeightMm": round(pane_h, 1),
        "shutterCount": shutters,
        "weightKg": 0.0,
        "totalGlassKg": 0.0,
    }
    if not gid or pane_w <= 0 or pane_h <= 0:
        return out
    try:
        from WEOS.factory.glass_catalogue import get_glass, glass_weight

        spec = get_glass(gid)
        if not isinstance(spec, Mapping):
            return out
        wt = glass_weight(spec, width_mm=pane_w, height_mm=pane_h, qty=1.0)
        each = float(wt.get("weightKg") or 0)
        out["weightKg"] = round(each, 3)
        out["totalGlassKg"] = round(each * shutters, 3)
        out["thicknessMm"] = spec.get("thicknessMm") or spec.get("overallMm")
        out["glassName"] = _str(spec.get("name") or spec.get("label") or gid)
        out["densityKgPerM3"] = float(spec.get("densityKgPerM3") or 2500.0)
    except Exception:
        pass
    return out


def list_wheel_options_for_weight(
    required_kg: float = 0.0,
    *,
    for_mesh: bool = False,
    max_mesh_kg: float = 80.0,
) -> list[dict[str, Any]]:
    """Catalogue wheels/rollers filtered for shutter weight (or regular mesh).

    Glass shutters: prefer capacity ≥ required kg (still list heavier options).
    Mesh shutters: only regular/light wheels (capacity ≤ ``max_mesh_kg``).
    """
    try:
        from WEOS.factory.hardware_catalogue import list_hardware
        items = list_hardware()
    except Exception:
        items = []
    req = max(float(required_kg or 0), 0.0)
    rows: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, Mapping):
            continue
        cat = _str(it.get("category")).lower()
        if cat not in ("wheel", "roller"):
            continue
        cap = _num(it.get("weightCapacityKg") or it.get("capacityKg") or it.get("maxKg"))
        if cap is None:
            continue
        if for_mesh and float(cap) > float(max_mesh_kg):
            continue
        fit = float(cap) >= req
        rows.append({
            "id": _str(it.get("id")),
            "name": _str(it.get("name") or "Wheel"),
            "brand": _str(it.get("brand")),
            "origin": _str(it.get("origin") or "indian"),
            "rate": float(it.get("rate") or 0),
            "unit": _str(it.get("unit") or "PC").upper(),
            "qtyPerShutter": float(it.get("qtyPer") or 2) or 2.0,
            "weightCapacityKg": float(cap),
            "fits": fit if not for_mesh else True,
            "forMesh": for_mesh,
            "systemGroup": _str(it.get("systemGroup")),
        })
    rows.sort(key=lambda r: (0 if r.get("fits") else 1, float(r.get("weightCapacityKg") or 0), float(r.get("rate") or 0)))
    return rows


def suggest_wheel_for_weight(
    required_kg: float,
    *,
    for_mesh: bool = False,
    selected_id: str | None = None,
) -> dict[str, Any] | None:
    """Pick catalogue wheel: honor ``selected_id`` if valid, else smallest capacity ≥ weight."""
    opts = list_wheel_options_for_weight(required_kg, for_mesh=for_mesh)
    if not opts:
        return None
    sid = _str(selected_id)
    if sid:
        hit = next((o for o in opts if o.get("id") == sid), None)
        if hit:
            return hit
    if for_mesh:
        return opts[0]
    covering = [o for o in opts if o.get("fits")]
    return covering[0] if covering else opts[-1]


def wheel_block_from_option(opt: Mapping[str, Any] | None, *, default_name: str = "Wheels") -> dict[str, Any]:
    """Map a catalogue wheel option into hardwarePack.wheels / meshWheels shape."""
    if not isinstance(opt, Mapping):
        return {
            "qtyPerShutter": 2.0,
            "rate": 0.0,
            "unit": "PC",
            "brand": "",
            "origin": "indian",
            "name": default_name,
            "id": "",
            "weightCapacityKg": None,
            "notes": "",
        }
    return {
        "qtyPerShutter": float(opt.get("qtyPerShutter") or opt.get("qtyPer") or 2) or 2.0,
        "rate": float(opt.get("rate") or 0),
        "unit": _str(opt.get("unit") or "PC").upper(),
        "brand": _str(opt.get("brand")),
        "origin": _str(opt.get("origin") or "indian"),
        "name": _str(opt.get("name") or default_name),
        "id": _str(opt.get("id")),
        "weightCapacityKg": _num(opt.get("weightCapacityKg") or opt.get("capacityKg")),
        "notes": _str(opt.get("notes") or ("regular mesh wheel" if "mesh" in default_name.lower() else "")),
    }


def apply_stay_size_rate(stay: MutableMapping[str, Any] | Mapping[str, Any], inch: float | None) -> dict[str, Any]:
    """Set selectedInch on a stay block and sync rate from lengths catalogue."""
    block = dict(stay) if isinstance(stay, Mapping) else {}
    lengths = block.get("lengths") if isinstance(block.get("lengths"), list) else []
    if inch is not None:
        block["selectedInch"] = float(inch)
    selected = _num(block.get("selectedInch") or inch)
    if selected is not None and lengths:
        match = next((x for x in lengths if isinstance(x, Mapping) and _num(x.get("inch")) == selected), None)
        if match is not None:
            block["rate"] = float(match.get("rate") or block.get("rate") or 0)
    return block


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
    interlock_pack: dict[str, Any] = {}
    shutter_frames: dict[str, Any] = {}
    if stype == "sliding":
        mesh_n = float(
            context.get("meshCount")
            or context.get("meshShutters")
            or context.get("mesh_count")
            or 0
        )
        opening = context.get("opening") or context.get("openingType") or context.get("shutterOpening")
        track_c = context.get("trackCount") or context.get("track_count")
        track_fill = derive_sliding_track_fill(
            setup,
            width_mm=width_mm,
            height_mm=height_mm,
            track_count=track_c,
        )
        colour_ctx = _str(context.get("colour") or context.get("color") or "")
        shutter_frames = derive_sliding_shutter_frame_cuts(
            setup,
            width_mm=width_mm,
            height_mm=height_mm,
            glass_count=shutters,
            colour=colour_ctx,
        )
        interlock_pack = derive_sliding_interlock_cuts(
            setup,
            width_mm=width_mm,
            height_mm=height_mm,
            glass_count=shutters,
            mesh_count=mesh_n,
            opening=_str(opening) or None,
            track_count=float(track_c) if track_c not in (None, "") else None,
            colour=colour_ctx,
        )
        pack_hw = derive_sliding_hardware_lines(
            setup,
            width_mm=width_mm,
            height_mm=height_mm,
            shutter_count=shutters,
            mesh_count=mesh_n,
        )
        # Prefer weight-picked glass wheels when both exist; always keep mesh wheels from pack
        if hw:
            pack_hw = [
                ln for ln in pack_hw
                if "meshWheels" in str(ln.get("source") or "")
                or "wheel" not in str(ln.get("name") or "").lower()
            ]
        hw = list(hw) + list(pack_hw)
    elif stype == "casement":
        # Use `is not None` — 0 operable (fixed+mullion) must not fall through to defaults.
        side_n = context.get("sideSwingDoors")
        if side_n is None:
            side_n = context.get("side_swing_doors")
        top_n = context.get("topHungDoors")
        if top_n is None:
            top_n = context.get("top_hung_doors")
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
        "shutterFrames": shutter_frames,
        "interlocks": interlock_pack,
        "hardwarePackLines": pack_hw,
        "quoteHardwareNotes": quote_hw_notes,
        "wastage": wastage,
        "costing": costing if isinstance(costing, Mapping) else {},
        "costEngine": (costing.get("costEngine") if isinstance(costing, Mapping) else None) or "stub",
    }
