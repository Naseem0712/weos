"""First-class Pergola configuration model — WEOS V2 Batch 8.5 / 9.5.

Canonical ProductConfiguration for PERGOLA on the Universal Canvas.
Geometry (W/D/H/qty) stays independent of materials/finish.
Front / Left / Right / Back are distinct side zones (not one generic side).
Roof and optional floor/deck are separate.
Reuses special_schematics.pergola_svg — does not invent full structural engineering.
"""

from __future__ import annotations

from typing import Any, Mapping

SIDE_KEYS = ("front", "left", "right", "back")
SIDE_LABELS = {
    "front": "Front",
    "left": "Left",
    "right": "Right",
    "back": "Back",
}
TREATMENT_OPTIONS = (
    "open",
    "louvers",
    "glass",
    "solid",
    "rail",
    "polycarbonate",
    "none",
)


def _num(*vals: Any, default: float = 0.0) -> float:
    for v in vals:
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return float(default)


def _int(*vals: Any, default: int = 0) -> int:
    for v in vals:
        if v is None or v == "":
            continue
        try:
            return int(float(v))
        except (TypeError, ValueError):
            continue
    return int(default)


def _str(*vals: Any, default: str = "") -> str:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return default


def _bool(*vals: Any, default: bool = False) -> bool:
    for v in vals:
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "on", "y"):
            return True
        if s in ("0", "false", "no", "off", "n"):
            return False
        # Unrecognized non-empty: skip and try next candidate
        continue
    return default


def _side_zone(raw: Any | None, *, default_treatment: str = "open") -> dict[str, Any]:
    src = raw if isinstance(raw, Mapping) else {}
    treatment = _str(src.get("treatment"), src.get("type"), src.get("fill"), default=default_treatment).lower()
    if treatment not in TREATMENT_OPTIONS:
        treatment = default_treatment
    return {
        "treatment": treatment,
        "notes": _str(src.get("notes"), src.get("note")),
        "material": _str(src.get("material")),
    }


def _default_sides() -> dict[str, dict[str, Any]]:
    return {k: _side_zone(None) for k in SIDE_KEYS}


def extract_pergola_blob(source: Mapping[str, Any] | None) -> dict[str, Any]:
    """Pull nested options.pergola / config.pergola / flat payload into one dict."""
    if not isinstance(source, Mapping):
        return {}
    opts = source.get("options") if isinstance(source.get("options"), Mapping) else {}
    cfg = source.get("configPayload") if isinstance(source.get("configPayload"), Mapping) else {}
    if not cfg and isinstance(source.get("config_payload"), Mapping):
        cfg = source.get("config_payload")  # type: ignore[assignment]
    for nest in (
        source.get("pergola"),
        opts.get("pergola") if isinstance(opts, Mapping) else None,
        cfg.get("pergola") if isinstance(cfg, Mapping) else None,
    ):
        if isinstance(nest, Mapping) and nest:
            merged = dict(nest)
            # Allow top-level overrides for dims/colour commonly set on cart lines.
            for k in ("widthMm", "depthMm", "heightMm", "postHeightMm", "qty", "colour", "powderCoatName"):
                if source.get(k) not in (None, "") and merged.get(k) in (None, ""):
                    merged[k] = source.get(k)
            return merged
    # Flat config already is the pergola payload
    if cfg:
        return dict(cfg)
    return dict(source)


def normalize_pergola_config(
    source: Mapping[str, Any] | None,
    *,
    width_mm: float | None = None,
    depth_mm: float | None = None,
    height_mm: float | None = None,
) -> dict[str, Any]:
    """Authoritative ProductConfiguration for PERGOLA (geometry ≠ materials)."""
    raw = extract_pergola_blob(source)
    structure_in = raw.get("structure") if isinstance(raw.get("structure"), Mapping) else {}
    louvers_in = raw.get("louvers") if isinstance(raw.get("louvers"), Mapping) else {}
    roof_in = raw.get("roof") if isinstance(raw.get("roof"), Mapping) else {}
    deck_in = raw.get("deck") if isinstance(raw.get("deck"), Mapping) else {}
    if not deck_in and isinstance(raw.get("floor"), Mapping):
        deck_in = raw.get("floor")  # type: ignore[assignment]
    finish_in = raw.get("finish") if isinstance(raw.get("finish"), Mapping) else {}
    sides_in = raw.get("sides") if isinstance(raw.get("sides"), Mapping) else {}
    if not sides_in and isinstance(raw.get("sideTreatments"), Mapping):
        sides_in = raw.get("sideTreatments")  # type: ignore[assignment]

    width = _num(width_mm, raw.get("widthMm"), raw.get("width"), default=3000)
    depth = _num(
        depth_mm,
        raw.get("depthMm"),
        raw.get("depth"),
        # Legacy cart used height as plan depth when post height lived elsewhere.
        raw.get("planDepthMm"),
        default=2400,
    )
    post_h = _num(
        height_mm,
        raw.get("postHeightMm"),
        raw.get("pergolaHeightMm"),
        raw.get("heightMm") if raw.get("depthMm") is not None else None,
        structure_in.get("postHeightMm"),
        default=2700,
    )
    qty = max(1, _int(raw.get("qty"), raw.get("quantity"), default=1))

    sides = _default_sides()
    for key in SIDE_KEYS:
        # Distinct zones only — refuse a single generic "side" overwrite of all.
        if key in sides_in:
            sides[key] = _side_zone(sides_in.get(key))
        elif key.title() in sides_in:
            sides[key] = _side_zone(sides_in.get(key.title()))
        elif key.upper() in sides_in:
            sides[key] = _side_zone(sides_in.get(key.upper()))

    roof_enabled = _bool(
        roof_in.get("enabled"),
        default=True if roof_in or raw.get("cover") or raw.get("roofFill") else True,
    )
    deck_enabled = _bool(deck_in.get("enabled"), raw.get("deckEnabled"), default=False)

    colour = _str(
        finish_in.get("colour"),
        finish_in.get("powderCoatName"),
        raw.get("colour"),
        raw.get("powderCoatName"),
        raw.get("color"),
    )

    cfg: dict[str, Any] = {
        "productType": "PERGOLA",
        "widthMm": width,
        "depthMm": depth,
        "postHeightMm": post_h,
        "heightMm": post_h,  # alias for callers expecting heightMm as vertical
        "qty": qty,
        "structure": {
            "postCount": max(2, _int(structure_in.get("postCount"), raw.get("postCount"), default=4)),
            "postSection": _str(
                structure_in.get("postSection"),
                structure_in.get("post"),
                raw.get("post"),
                raw.get("postSection"),
                default="posts as specified",
            ),
            "beamSection": _str(
                structure_in.get("beamSection"),
                structure_in.get("beam"),
                raw.get("beam"),
                raw.get("beamSection"),
                default="beams as specified",
            ),
            "rafterCount": max(
                2,
                _int(structure_in.get("rafterCount"), raw.get("rafterCount"), default=6),
            ),
            "rafterSection": _str(
                structure_in.get("rafterSection"),
                structure_in.get("rafter"),
                raw.get("rafter"),
                raw.get("rafterSection"),
                default="rafters as specified",
            ),
            "fixing": _str(
                structure_in.get("fixing"),
                structure_in.get("mount"),
                raw.get("fixing"),
                raw.get("mount"),
                raw.get("installType"),
                default="floor / wall / garden",
            ),
        },
        "louvers": {
            "enabled": _bool(louvers_in.get("enabled"), default=True),
            "orientation": _str(louvers_in.get("orientation"), default="horizontal").lower(),
            "count": max(0, _int(louvers_in.get("count"), louvers_in.get("bladeCount"), default=8)),
            "bladeWidthMm": _num(louvers_in.get("bladeWidthMm"), louvers_in.get("bladeMm"), default=80),
            "gapMm": _num(louvers_in.get("gapMm"), default=20),
            "material": _str(louvers_in.get("material"), default="aluminium"),
        },
        "roof": {
            "enabled": roof_enabled,
            "cover": _str(
                roof_in.get("cover"),
                roof_in.get("roofFill"),
                roof_in.get("type"),
                raw.get("cover"),
                raw.get("roofFill"),
                default="louvers / glass / polycarbonate",
            ),
            "material": _str(roof_in.get("material"), raw.get("roofMaterial")),
            "notes": _str(roof_in.get("notes")),
        },
        "sides": sides,
        "deck": {
            "enabled": deck_enabled,
            "material": _str(deck_in.get("material"), raw.get("deckMaterial"), raw.get("floorMaterial")),
            "notes": _str(deck_in.get("notes"), deck_in.get("note"), raw.get("deckNotes")),
            "type": _str(deck_in.get("type"), deck_in.get("kind"), default="deck" if deck_enabled else ""),
        },
        "finish": {
            "colour": colour,
            "powderCoatName": _str(finish_in.get("powderCoatName"), raw.get("powderCoatName"), colour),
            "notes": _str(finish_in.get("notes")),
        },
        "notes": _str(raw.get("notes"), raw.get("note")),
    }
    cfg["designSummary"] = build_design_summary(cfg)
    return cfg


def build_design_summary(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Stable summary for quote / print / PDF (dims, colour, roof, sides, deck)."""
    structure = cfg.get("structure") if isinstance(cfg.get("structure"), Mapping) else {}
    louvers = cfg.get("louvers") if isinstance(cfg.get("louvers"), Mapping) else {}
    roof = cfg.get("roof") if isinstance(cfg.get("roof"), Mapping) else {}
    deck = cfg.get("deck") if isinstance(cfg.get("deck"), Mapping) else {}
    finish = cfg.get("finish") if isinstance(cfg.get("finish"), Mapping) else {}
    sides = cfg.get("sides") if isinstance(cfg.get("sides"), Mapping) else {}

    side_txt = []
    for key in SIDE_KEYS:
        zone = sides.get(key) if isinstance(sides.get(key), Mapping) else {}
        treat = _str((zone or {}).get("treatment"), default="open")
        side_txt.append(f"{SIDE_LABELS[key]}: {treat}")

    colour = _str(finish.get("colour"), finish.get("powderCoatName"), cfg.get("colour"))
    roof_txt = "none"
    if _bool(roof.get("enabled"), default=True):
        roof_txt = _str(roof.get("cover"), roof.get("material"), default="as specified")
    deck_txt = "none"
    if _bool(deck.get("enabled"), default=False):
        deck_txt = _str(deck.get("material"), deck.get("type"), default="deck as specified")

    w = _num(cfg.get("widthMm"))
    d = _num(cfg.get("depthMm"))
    h = _num(cfg.get("postHeightMm"), cfg.get("heightMm"))
    qty = max(1, _int(cfg.get("qty"), default=1))

    lines = [
        f"Size: {_fmt_mm(w)} × {_fmt_mm(d)} × {_fmt_mm(h)} mm",
        f"Qty: {qty}",
        f"Posts: {structure.get('postCount')} · {structure.get('postSection')}",
        f"Beams: {structure.get('beamSection')}",
        f"Rafters: {structure.get('rafterCount')} · {structure.get('rafterSection')}",
        f"Louvers: {'yes' if louvers.get('enabled') else 'no'}"
        + (f" ({louvers.get('count')} / {louvers.get('orientation')})" if louvers.get("enabled") else ""),
        f"Roof: {roof_txt}",
        f"Sides — {'; '.join(side_txt)}",
        f"Floor/Deck: {deck_txt}",
        f"Colour: {colour or 'as specified'}",
        f"Fixing: {structure.get('fixing')}",
    ]
    return {
        "title": "Pergola design summary",
        "widthMm": w,
        "depthMm": d,
        "heightMm": h,
        "qty": qty,
        "colour": colour,
        "roof": roof_txt,
        "sides": {k: (sides.get(k) or {}) for k in SIDE_KEYS},
        "sidesText": "; ".join(side_txt),
        "deck": deck_txt,
        "deckEnabled": _bool(deck.get("enabled"), default=False),
        "structure": {
            "posts": structure.get("postSection"),
            "postCount": structure.get("postCount"),
            "beams": structure.get("beamSection"),
            "rafters": structure.get("rafterSection"),
            "rafterCount": structure.get("rafterCount"),
            "fixing": structure.get("fixing"),
        },
        "lines": lines,
        "text": " | ".join(lines),
    }


def _fmt_mm(v: float) -> str:
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return f"{v:g}"


def design_summary_spec_rows(cfg_or_line: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """Spec rows for quote/PDF — design summary block."""
    cfg = normalize_pergola_config(cfg_or_line)
    summary = cfg.get("designSummary") if isinstance(cfg.get("designSummary"), Mapping) else build_design_summary(cfg)
    rows: list[tuple[str, str]] = [
        ("", "Pergola"),
        ("SIZE", f"{_fmt_mm(summary.get('widthMm') or 0)} x {_fmt_mm(summary.get('depthMm') or 0)} x {_fmt_mm(summary.get('heightMm') or 0)} mm"),
        ("QTY", str(summary.get("qty") or 1)),
        ("TYPE", "Pergola catalogue design"),
    ]
    structure = summary.get("structure") if isinstance(summary.get("structure"), Mapping) else {}
    rows.append(("FIXING", str(structure.get("fixing") or "as specified")))
    rows.append(("POSTS", f"{structure.get('postCount')} · {structure.get('posts')}"))
    rows.append(("BEAMS", str(structure.get("beams") or "as specified")))
    rows.append(("RAFTERS", f"{structure.get('rafterCount')} · {structure.get('rafters')}"))
    rows.append(("ROOF", str(summary.get("roof") or "as specified")))
    rows.append(("SIDES", str(summary.get("sidesText") or "")))
    rows.append(("DECK", str(summary.get("deck") or "none")))
    colour = str(summary.get("colour") or "").strip()
    if colour:
        rows.append(("COLOUR", colour.replace("_", " ").title()))
    rows.append(("SUMMARY", str(summary.get("text") or "")[:500]))
    return rows


def property_schema() -> dict[str, Any]:
    """Contextual property panel groups for PERGOLA."""
    side_fields = []
    for key in SIDE_KEYS:
        side_fields.append(
            {
                "key": f"sides.{key}.treatment",
                "label": f"{SIDE_LABELS[key]} treatment",
                "type": "enum",
                "options": list(TREATMENT_OPTIONS),
                "domain": "config",
            }
        )
        side_fields.append(
            {
                "key": f"sides.{key}.notes",
                "label": f"{SIDE_LABELS[key]} notes",
                "type": "string",
                "domain": "config",
            }
        )
    return {
        "version": 1,
        "groups": [
            {
                "id": "geometry",
                "label": "Geometry",
                "domain": "geometry",
                "fields": [
                    {"key": "widthMm", "label": "Width (mm)", "type": "number", "domain": "geometry"},
                    {"key": "depthMm", "label": "Depth (mm)", "type": "number", "domain": "geometry"},
                    {"key": "postHeightMm", "label": "Height (mm)", "type": "number", "domain": "config"},
                    {"key": "qty", "label": "Qty", "type": "number", "domain": "config"},
                    {"key": "xMm", "label": "X (mm)", "type": "number", "domain": "geometry"},
                    {"key": "yMm", "label": "Y (mm)", "type": "number", "domain": "geometry"},
                ],
            },
            {
                "id": "structure",
                "label": "Structure",
                "domain": "config",
                "fields": [
                    {"key": "structure.postCount", "label": "Post count", "type": "number", "domain": "config"},
                    {"key": "structure.postSection", "label": "Posts", "type": "string", "domain": "config"},
                    {"key": "structure.beamSection", "label": "Beams", "type": "string", "domain": "config"},
                    {"key": "structure.rafterCount", "label": "Rafter count", "type": "number", "domain": "config"},
                    {"key": "structure.rafterSection", "label": "Rafters", "type": "string", "domain": "config"},
                    {"key": "structure.fixing", "label": "Fixing / mount", "type": "string", "domain": "config"},
                ],
            },
            {
                "id": "louvers",
                "label": "Louvers",
                "domain": "config",
                "fields": [
                    {"key": "louvers.enabled", "label": "Louvers enabled", "type": "boolean", "domain": "config"},
                    {"key": "louvers.orientation", "label": "Orientation", "type": "string", "domain": "config"},
                    {"key": "louvers.count", "label": "Louver count", "type": "number", "domain": "config"},
                    {"key": "louvers.bladeWidthMm", "label": "Blade width (mm)", "type": "number", "domain": "config"},
                    {"key": "louvers.gapMm", "label": "Gap (mm)", "type": "number", "domain": "config"},
                    {"key": "louvers.material", "label": "Louver material", "type": "string", "domain": "config"},
                ],
            },
            {
                "id": "roof",
                "label": "Roof",
                "domain": "config",
                "fields": [
                    {"key": "roof.enabled", "label": "Roof enabled", "type": "boolean", "domain": "config"},
                    {"key": "roof.cover", "label": "Roof cover", "type": "string", "domain": "config"},
                    {"key": "roof.material", "label": "Roof material", "type": "string", "domain": "config"},
                    {"key": "roof.notes", "label": "Roof notes", "type": "string", "domain": "config"},
                ],
            },
            {
                "id": "side_treatments",
                "label": "Side Treatments",
                "domain": "config",
                "fields": side_fields,
            },
            {
                "id": "floor_deck",
                "label": "Floor/Deck",
                "domain": "config",
                "fields": [
                    {"key": "deck.enabled", "label": "Deck enabled", "type": "boolean", "domain": "config"},
                    {"key": "deck.material", "label": "Deck material", "type": "string", "domain": "config"},
                    {"key": "deck.type", "label": "Deck type", "type": "string", "domain": "config"},
                    {"key": "deck.notes", "label": "Deck notes", "type": "string", "domain": "config"},
                ],
            },
            {
                "id": "finish",
                "label": "Finish",
                "domain": "config",
                "fields": [
                    {"key": "finish.colour", "label": "Colour", "type": "string", "domain": "config"},
                    {"key": "finish.powderCoatName", "label": "Powder coat", "type": "string", "domain": "config"},
                    {"key": "finish.notes", "label": "Finish notes", "type": "string", "domain": "config"},
                    {"key": "notes", "label": "Notes", "type": "string", "domain": "config"},
                ],
            },
            {
                "id": "summary",
                "label": "Summary",
                "domain": "readonly",
                "fields": [
                    {"key": "designSummary.text", "label": "Design summary", "type": "readonly", "domain": "readonly"},
                ],
            },
        ],
    }


def _set_path(root: dict[str, Any], dotted: str, value: Any) -> None:
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return
    cur: dict[str, Any] = root
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def apply_pergola_patch(base: Mapping[str, Any] | None, patch: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge flat or dotted panel patches into normalized pergola config."""
    cfg = normalize_pergola_config(base)
    patch = dict(patch or {})
    # Geometry keys that belong on element are ignored here except depth/postHeight/qty.
    for k in ("widthMm", "xMm", "yMm", "elementId", "assemblyId", "connectionId", "productType", "kind"):
        patch.pop(k, None)

    # depthMm stays in config (and caller may sync to element heightMm).
    for key, val in list(patch.items()):
        if "." in key:
            _set_path(cfg, key, val)
            patch.pop(key, None)

    # Nested dict merges
    for nest in ("structure", "louvers", "roof", "deck", "finish", "sides"):
        if nest in patch and isinstance(patch[nest], Mapping):
            existing = cfg.get(nest) if isinstance(cfg.get(nest), Mapping) else {}
            merged = dict(existing)
            if nest == "sides":
                for sk in SIDE_KEYS:
                    if sk in patch[nest]:
                        merged[sk] = _side_zone(patch[nest].get(sk), default_treatment=(existing.get(sk) or {}).get("treatment", "open"))
            else:
                merged.update(dict(patch[nest]))
            cfg[nest] = merged
            patch.pop(nest, None)

    for k, v in patch.items():
        if k in ("widthMm", "heightMm", "xMm", "yMm"):
            continue
        if k == "depthMm":
            cfg["depthMm"] = _num(v, default=cfg.get("depthMm") or 2400)
        elif k in ("postHeightMm", "pergolaHeightMm"):
            cfg["postHeightMm"] = _num(v, default=cfg.get("postHeightMm") or 2700)
            cfg["heightMm"] = cfg["postHeightMm"]
        elif k == "qty":
            cfg["qty"] = max(1, _int(v, default=1))
        elif k == "colour":
            finish = dict(cfg.get("finish") or {})
            finish["colour"] = _str(v)
            cfg["finish"] = finish
        elif k == "notes":
            cfg["notes"] = _str(v)
        else:
            cfg[k] = v

    return normalize_pergola_config(cfg)


def panel_values(element: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Flatten nested config for property panel form binding."""
    c = normalize_pergola_config(
        cfg or element,
        width_mm=_num(element.get("widthMm"), element.get("width_mm")),
        depth_mm=_num(
            (cfg or {}).get("depthMm") if isinstance(cfg, Mapping) else None,
            element.get("heightMm"),
            element.get("height_mm"),
        ),
    )
    # Prefer element footprint for depth when present
    if _num(element.get("heightMm"), element.get("height_mm")) > 0 and not (
        isinstance(cfg, Mapping) and cfg.get("depthMm") not in (None, "")
    ):
        c["depthMm"] = _num(element.get("heightMm"), element.get("height_mm"), default=c["depthMm"])

    values: dict[str, Any] = {
        "widthMm": _num(element.get("widthMm"), element.get("width_mm"), c.get("widthMm")),
        "depthMm": c.get("depthMm"),
        "postHeightMm": c.get("postHeightMm"),
        "qty": c.get("qty"),
        "xMm": element.get("xMm"),
        "yMm": element.get("yMm"),
        "notes": c.get("notes"),
        "designSummary.text": (c.get("designSummary") or {}).get("text")
        if isinstance(c.get("designSummary"), Mapping)
        else "",
    }
    for nest in ("structure", "louvers", "roof", "deck", "finish"):
        blob = c.get(nest) if isinstance(c.get(nest), Mapping) else {}
        for fk, fv in blob.items():
            values[f"{nest}.{fk}"] = fv
    sides = c.get("sides") if isinstance(c.get("sides"), Mapping) else {}
    for sk in SIDE_KEYS:
        zone = sides.get(sk) if isinstance(sides.get(sk), Mapping) else {}
        values[f"sides.{sk}.treatment"] = (zone or {}).get("treatment")
        values[f"sides.{sk}.notes"] = (zone or {}).get("notes")
        values[f"sides.{sk}.material"] = (zone or {}).get("material")
    return values


def svg_line_payload(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Shape accepted by special_schematics.pergola_svg."""
    c = normalize_pergola_config(cfg)
    structure = c.get("structure") or {}
    roof = c.get("roof") or {}
    louvers = c.get("louvers") or {}
    return {
        "widthMm": c.get("widthMm"),
        "depthMm": c.get("depthMm"),
        "heightMm": c.get("depthMm"),  # plan depth alias used by legacy svg path
        "postHeightMm": c.get("postHeightMm"),
        "pergolaHeightMm": c.get("postHeightMm"),
        "qty": c.get("qty"),
        "colour": (c.get("finish") or {}).get("colour"),
        "options": {
            "pergola": {
                **c,
                "post": structure.get("postSection"),
                "postSection": structure.get("postSection"),
                "postCount": structure.get("postCount"),
                "rafter": structure.get("rafterSection"),
                "rafterSection": structure.get("rafterSection"),
                "rafterCount": structure.get("rafterCount"),
                "beam": structure.get("beamSection"),
                "beamSection": structure.get("beamSection"),
                "fixing": structure.get("fixing"),
                "cover": roof.get("cover"),
                "roofFill": roof.get("cover"),
                "louverCount": louvers.get("count"),
                "louversEnabled": louvers.get("enabled"),
            }
        },
    }
