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

Everything degrades to sane empty values so callers never crash on a partial
setup.
"""

from __future__ import annotations

from typing import Any, Mapping

# Canonical product types a setup can describe.
SETUP_TYPES = ("sliding", "casement", "telescopic", "style")

# Map a setup type → the cart/geometry "productType" (window system family) so
# the product implies its system when selected.
TYPE_TO_PRODUCT_TYPE = {
    "sliding": "sliding",
    "casement": "casement",
    "telescopic": "telescopic_sliding",
    "style": "style_slide_door",
}

# Type defaults for the standard stock length(s) in mm.
DEFAULT_STANDARD_LENGTHS = {
    "sliding": [5850],
    "casement": [5850],
    "telescopic": [3000],       # imported: 3 mtr only
    "style": [2400, 3000],      # imported: 2.4 & 3 mtr
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
    }

    out["sliding"] = _norm_sliding(s.get("sliding"))
    out["casement"] = _norm_casement(s.get("casement"))
    out["telescopic"] = _norm_telescopic(s.get("telescopic"))
    out["style"] = _norm_style(s.get("style"))

    out["derived"] = {
        "sectionSizes": derive_section_sizes(out),
        "hardware": derive_hardware(out),
        "weights": derive_weights(out),
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
