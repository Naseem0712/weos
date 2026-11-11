"""Product Library — per-type *series setup* schema, normalisation and derivations.

A "setup" is the structured, editable definition a fabricator fills in when they
register a series in the Product Library (Admin · Product Library → *Series
Setup*).  It captures, per product **type**:

* the aluminium **sections** (outer track / frame, shutters, mesh, verticals,
  rails …) with dimensions, **weight (kg/m)** and **standard length (mm)**, with
  per-side variants when sides differ; and
* the **hardware** items (rollers, connectors, hinges, locks, handles, friction
  stays, door closers …) with **brand**, **unit**, **rate** and **quantity per
  shutter / leaf / config**.

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


def normalize_section(raw: Any) -> dict[str, Any]:
    """A single aluminium section row."""
    r = raw if isinstance(raw, Mapping) else {}
    return {
        "name": _str(r.get("name")),
        "use": _str(r.get("use") or r.get("position")),
        "wMm": _num(r.get("wMm") or r.get("widthMm")),
        "hMm": _num(r.get("hMm") or r.get("heightMm") or r.get("depthMm")),
        "wallMm": _num(r.get("wallMm") or r.get("thicknessMm")),
        "weightKgPerM": _num(r.get("weightKgPerM") or r.get("weightKgPerMtr")),
        "stdLengthMm": _num(r.get("stdLengthMm") or r.get("standardLengthMm")),
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

    out["derived"] = {
        "sectionSizes": derive_section_sizes(out),
        "hardware": derive_hardware(out),
        "weights": derive_weights(out),
        "memberCount": len(out["members"]),
        "hardwareWeightRuleCount": len(out["hardwareWeightRules"]),
    }
    return out


def _norm_sliding(raw: Any) -> dict[str, Any]:
    r = raw if isinstance(raw, Mapping) else {}
    ot = r.get("outerTrack") if isinstance(r.get("outerTrack"), Mapping) else {}
    sh = r.get("shutters") if isinstance(r.get("shutters"), Mapping) else {}
    mesh = r.get("mesh") if isinstance(r.get("mesh"), Mapping) else {}
    return {
        "outerTrack": {
            "sameAllSides": _bool(ot.get("sameAllSides"), True),
            "top": normalize_section(ot.get("top")),
            "bottom": normalize_section(ot.get("bottom")),
            "verticals": normalize_section(ot.get("verticals")),
            "bottomRails": normalize_section(ot.get("bottomRails")),
        },
        "shutters": {
            "sameAllSides": _bool(sh.get("sameAllSides"), True),
            "top": normalize_section(sh.get("top")),
            "bottom": normalize_section(sh.get("bottom")),
            "handleSide": normalize_section(sh.get("handleSide")),
            "interlockSide": normalize_section(sh.get("interlockSide")),
        },
        "mesh": {
            "compatible": _bool(mesh.get("compatible"), False),
            "sameAsShutter": _bool(mesh.get("sameAsShutter"), True),
            "sections": _sections(mesh.get("sections")),
        },
        "hardware": _hardware(r.get("hardware")),
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
        ot = (setup.get("sliding") or {}).get("outerTrack") or {}
        sh = (setup.get("sliding") or {}).get("shutters") or {}
        put("topRail", _face(ot.get("top")))
        put("bottomRail", _face(ot.get("bottom")))
        put("leftJamb", _face(ot.get("verticals")))
        put("rightJamb", _face(ot.get("verticals")))
        put("leafStile", _face(sh.get("interlockSide")) or _face(sh.get("handleSide")) or _face(sh.get("top")))
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
    alu_kg = sum(float(m["weightKg"]) for m in members if m.get("weightKg") is not None)
    return {
        "members": members,
        "hardware": hw,
        "leafWeightKg": leaf_kg,
        "aluminiumKgFromMembers": round(alu_kg, 4),
        "usedMembers": bool(members),
        "usedHardwareWeightRules": bool(hw),
    }
