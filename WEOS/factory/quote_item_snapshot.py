"""Immutable Quote Item Snapshot — identity frozen at add time.

Saved quote items are never re-resolved from the live Product Library.
Refresh / calculate / PDF consume this object only. Missing product → error,
never a silent substitute (no “first window”, no random glass).
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping

CONFIGURATION_VERSION = 1
PRODUCT_UNAVAILABLE = "Product configuration unavailable. Quote item was not changed."

SNAPSHOT_KEYS = (
    "quote_item_id",
    "product_id",
    "product_name_snapshot",
    "category_snapshot",
    "series_id",
    "series_name_snapshot",
    "width",
    "height",
    "quantity",
    "selected_options",
    "profile_snapshot",
    "hardware_snapshot",
    "glass_snapshot",
    "calculation_snapshot",
    "preview_snapshot",
    "created_at",
    "updated_at",
    "configuration_version",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _int(val: Any, default: int = 1) -> int:
    try:
        if val is None or val == "":
            return default
        return int(round(float(val)))
    except (TypeError, ValueError):
        return default


def _as_map(val: Any) -> dict[str, Any]:
    return dict(val) if isinstance(val, Mapping) else {}


def _line_id(line: Mapping[str, Any] | None) -> str:
    if not isinstance(line, Mapping):
        return ""
    return str(line.get("lineId") or line.get("id") or line.get("quote_item_id") or "").strip()


def product_id_of(line: Mapping[str, Any] | None) -> str:
    """Stable product_id only — never inferred from name, index, or category order."""
    snap = get_item_snapshot(line) if line else {}
    pid = str(snap.get("product_id") or "").strip()
    if pid:
        return pid
    if not isinstance(line, Mapping):
        return ""
    return str(line.get("product") or line.get("productId") or "").strip()


def get_item_snapshot(line: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(line, Mapping):
        return {}
    for key in ("itemSnapshot", "item_snapshot"):
        raw = line.get(key)
        if isinstance(raw, Mapping) and (raw.get("product_id") or raw.get("quote_item_id")):
            return dict(raw)
    return {}


def get_glass_snapshot(line: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(line, Mapping):
        return {}
    for key in ("glass_snapshot", "glassSnapshot"):
        raw = line.get(key)
        if isinstance(raw, Mapping) and (raw.get("glass_id") or raw.get("display_label") or raw.get("layers")):
            return dict(raw)
    snap = get_item_snapshot(line)
    gs = snap.get("glass_snapshot")
    if isinstance(gs, Mapping):
        return dict(gs)
    return {}


def glass_display_label(spec: Mapping[str, Any] | None) -> str:
    """Canonical printable glass identity.

    Laminated 6+1.52+5 → ``6+1.52+5 mm Laminated`` (never 8/10/12/15mm).
    DGU 6+12A+6 → ``6+12A+6 mm DGU`` (air gap is not pane thickness).
    """
    if not isinstance(spec, Mapping) or not spec:
        return ""
    existing = str(spec.get("display_label") or spec.get("displayLabel") or "").strip()
    if existing and "+" in existing:
        return existing
    kind = str(
        spec.get("glass_construction")
        or spec.get("glass_type")
        or spec.get("makeup")
        or spec.get("kind")
        or ""
    ).strip().lower()
    layers = spec.get("layers") if isinstance(spec.get("layers"), Mapping) else {}
    g1 = spec.get("glass1Mm") if spec.get("glass1Mm") is not None else layers.get("glass1Mm")
    g2 = spec.get("glass2Mm") if spec.get("glass2Mm") is not None else layers.get("glass2Mm")
    pvb = spec.get("pvbMm") if spec.get("pvbMm") is not None else layers.get("pvbMm")
    gap = (
        spec.get("air_gap_mm")
        if spec.get("air_gap_mm") is not None
        else (spec.get("airGapMm") if spec.get("airGapMm") is not None else layers.get("airGapMm"))
    )
    laminated = bool(spec.get("laminated")) or kind in ("laminated", "lami")
    dgu = bool(spec.get("dgu")) or kind in ("dgu", "igu", "double", "insulated")
    toughened = bool(spec.get("toughened"))
    colour = str(spec.get("colour") or spec.get("color") or "").strip()
    finish = str(spec.get("finish") or "").strip()

    if laminated and g1 and pvb and g2:
        label = f"{_fmt_mm(g1)}+{_fmt_mm(pvb)}+{_fmt_mm(g2)} mm Laminated"
    elif dgu and g1 and gap and g2:
        label = f"{_fmt_mm(g1)}+{_fmt_mm(gap)}A+{_fmt_mm(g2)} mm DGU"
    else:
        thk = spec.get("total_thickness_mm") or spec.get("thicknessMm") or spec.get("overallMm")
        if thk in (None, ""):
            label = str(spec.get("makeupLabel") or spec.get("name") or spec.get("label") or "").strip()
        else:
            bits = [f"{_fmt_mm(thk)} mm"]
            if toughened:
                bits.append("Toughened")
            label = " ".join(bits)
    extra: list[str] = []
    if colour and colour.lower() not in ("clear",) and colour.lower() not in label.lower():
        extra.append(colour.replace("_", " "))
    fin = finish.lower().replace("_", " ")
    if finish and fin not in label.lower() and fin not in ("non-toughened", "nontoughened", "non toughened"):
        extra.append(finish.replace("_", " "))
    if extra:
        label = f"{label} · " + " · ".join(extra) if label else " · ".join(extra)
    return label


def _fmt_mm(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return str(val)
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n))}"
    s = f"{n:.2f}".rstrip("0").rstrip(".")
    return s


def _parse_layers_from_id(glass_id: str) -> dict[str, Any]:
    """Exact makeup from known ids (lam_6_152_5, dgu_6_12_6). Never nearest-match."""
    gid = str(glass_id or "").strip().lower()
    m = re.fullmatch(r"lam_(\d+)_(\d+)_(\d+)", gid)
    if m:
        g1, pvb_raw, g2 = int(m.group(1)), m.group(2), int(m.group(3))
        pvb = float(pvb_raw) / 100.0 if len(pvb_raw) >= 3 else float(pvb_raw)
        return {
            "makeup": "laminated",
            "glass1Mm": float(g1),
            "pvbMm": pvb,
            "glass2Mm": float(g2),
            "overallMm": float(g1) + pvb + float(g2),
        }
    m = re.fullmatch(r"dgu_(\d+)_(\d+)_(\d+)", gid)
    if m:
        g1, gap, g2 = float(m.group(1)), float(m.group(2)), float(m.group(3))
        return {
            "makeup": "dgu",
            "glass1Mm": g1,
            "airGapMm": gap,
            "glass2Mm": g2,
            "overallMm": g1 + gap + g2,
        }
    m = re.match(r"^(\d+(?:\.\d+)?)\s*mm", gid.replace("_", " "))
    if m:
        thk = float(m.group(1))
        tough = any(k in gid for k in ("tough", "tuff", "tempered"))
        colour = "clear"
        for c in ("black", "grey", "gray", "brown", "green", "blue", "bronze"):
            if c in gid:
                colour = "grey" if c == "gray" else c
                break
        return {
            "makeup": "single",
            "thicknessMm": thk,
            "overallMm": thk,
            "toughened": tough,
            "colour": colour,
        }
    return {}


def _lookup_glass_option(glass_id: str) -> dict[str, Any]:
    """Exact id match in the glass catalogue — never first / random option."""
    gid = str(glass_id or "").strip()
    if not gid:
        return {}
    try:
        from WEOS.factory.glass_catalogue import cart_glass_options, get_glass

        try:
            spec = get_glass(gid.split("@")[0].strip())
            if isinstance(spec, Mapping) and spec.get("id"):
                return dict(spec)
        except Exception:
            spec = {}
        for opt in cart_glass_options(merge_library=True) or []:
            if not isinstance(opt, Mapping):
                continue
            if str(opt.get("id") or "").strip() == gid:
                return dict(opt)
    except Exception:
        pass
    return _parse_layers_from_id(gid)


def build_glass_snapshot(
    line: Mapping[str, Any] | None = None,
    *,
    option: Mapping[str, Any] | None = None,
    railing: bool = False,
) -> dict[str, Any]:
    """Serialize the selected glass configuration (full structured identity)."""
    existing = get_glass_snapshot(line) if line else {}
    if existing.get("display_label") and existing.get("glass_id"):
        return existing

    src = dict(option or {})
    opts = _as_map(line.get("options") if isinstance(line, Mapping) else None)
    rail_cfg = _as_map(opts.get("railing"))
    rail_q = _as_map(opts.get("railingQuote"))
    if railing or rail_cfg or rail_q:
        thk = (
            src.get("thicknessMm")
            or rail_q.get("glassThicknessMm")
            or rail_cfg.get("glassThicknessMm")
            or (line or {}).get("glassThicknessMm")
        )
        gtype = str(
            src.get("glassType")
            or rail_cfg.get("glassType")
            or rail_q.get("glassType")
            or ""
        ).strip()
        gcol = str(
            src.get("colour")
            or rail_cfg.get("glassColour")
            or rail_q.get("glassColour")
            or ""
        ).strip()
        tough = bool(src.get("toughened")) or any(
            k in gtype.lower() for k in ("tough", "tuff", "temper")
        )
        laminated = "lam" in gtype.lower()
        dgu = "dgu" in gtype.lower() or "igu" in gtype.lower()
        gid = str(src.get("id") or (line or {}).get("glass") or "").strip()
        parsed = _parse_layers_from_id(gid) if gid else {}
        if laminated and not parsed:
            parsed = _parse_layers_from_id(gtype)
        layers = {}
        if parsed.get("makeup") == "laminated":
            layers = {
                "glass1Mm": parsed.get("glass1Mm"),
                "pvbMm": parsed.get("pvbMm"),
                "glass2Mm": parsed.get("glass2Mm"),
            }
            laminated = True
        elif parsed.get("makeup") == "dgu":
            layers = {
                "glass1Mm": parsed.get("glass1Mm"),
                "airGapMm": parsed.get("airGapMm"),
                "glass2Mm": parsed.get("glass2Mm"),
            }
            dgu = True
        construction = "laminated" if laminated else ("dgu" if dgu else "single")
        total = parsed.get("overallMm") or thk
        snap = {
            "glass_id": gid or f"railing_{_fmt_mm(total or 12)}mm",
            "glass_type": gtype or construction,
            "glass_construction": construction,
            "layers": layers,
            "total_thickness_mm": _num(total, 12.0) if total not in (None, "") else 12.0,
            "colour": gcol or str(parsed.get("colour") or "clear"),
            "finish": str(src.get("finish") or ""),
            "toughened": tough,
            "laminated": laminated,
            "dgu": dgu,
            "air_gap_mm": parsed.get("airGapMm"),
            "rate": src.get("rate") or rail_q.get("glassRate"),
            "weight": src.get("weight") or rail_q.get("glassKg"),
            "glass1Mm": parsed.get("glass1Mm") or layers.get("glass1Mm"),
            "glass2Mm": parsed.get("glass2Mm") or layers.get("glass2Mm"),
            "pvbMm": parsed.get("pvbMm") or layers.get("pvbMm"),
            "airGapMm": parsed.get("airGapMm") or layers.get("airGapMm"),
            "source": "railing",
        }
        snap["display_label"] = glass_display_label(snap)
        return snap

    gid = str(
        src.get("id")
        or src.get("glass_id")
        or (line.get("glass") if isinstance(line, Mapping) and isinstance(line.get("glass"), str) else "")
        or (line.get("glassId") if isinstance(line, Mapping) else "")
        or opts.get("glassId")
        or ""
    ).split("@")[0].strip()
    if isinstance(line, Mapping) and isinstance(line.get("glass"), Mapping):
        src = {**dict(line.get("glass") or {}), **src}
        gid = str(src.get("id") or gid).strip()
    if isinstance(line, Mapping) and isinstance(line.get("glassSpec"), Mapping):
        src = {**dict(line.get("glassSpec") or {}), **src}

    looked = _lookup_glass_option(gid) if gid else {}
    merged = {**looked, **src}
    makeup = str(merged.get("makeup") or merged.get("kind") or looked.get("makeup") or "").lower()
    parsed = _parse_layers_from_id(gid) if gid else {}
    if not makeup:
        makeup = str(parsed.get("makeup") or "single")
    g1 = merged.get("glass1Mm") if merged.get("glass1Mm") is not None else parsed.get("glass1Mm")
    g2 = merged.get("glass2Mm") if merged.get("glass2Mm") is not None else parsed.get("glass2Mm")
    pvb = merged.get("pvbMm") if merged.get("pvbMm") is not None else parsed.get("pvbMm")
    gap = merged.get("airGapMm") if merged.get("airGapMm") is not None else parsed.get("airGapMm")
    laminated = makeup in ("laminated", "lami") or bool(pvb)
    dgu = makeup in ("dgu", "igu", "double", "insulated") or bool(gap and not pvb)
    construction = "laminated" if laminated else ("dgu" if dgu else "single")
    layers: dict[str, Any] = {}
    if laminated:
        layers = {"glass1Mm": g1, "pvbMm": pvb, "glass2Mm": g2}
        total = merged.get("overallMm") or merged.get("thicknessMm")
        if total in (None, "") and g1 and pvb and g2:
            total = float(g1) + float(pvb) + float(g2)
    elif dgu:
        layers = {"glass1Mm": g1, "airGapMm": gap, "glass2Mm": g2}
        total = merged.get("overallMm") or merged.get("thicknessMm")
        if total in (None, "") and g1 and gap and g2:
            total = float(g1) + float(gap) + float(g2)
    else:
        total = merged.get("thicknessMm") or merged.get("overallMm") or parsed.get("thicknessMm")
        if total is not None:
            layers = {"glass1Mm": total}
    tough = merged.get("toughened")
    if tough is None:
        tough = bool(parsed.get("toughened"))
    snap = {
        "glass_id": gid or str(merged.get("id") or ""),
        "glass_type": makeup or construction,
        "glass_construction": construction,
        "layers": layers,
        "total_thickness_mm": _num(total) if total not in (None, "") else None,
        "colour": str(merged.get("colour") or parsed.get("colour") or "clear"),
        "finish": str(merged.get("finish") or ""),
        "toughened": bool(tough),
        "laminated": laminated,
        "dgu": dgu,
        "air_gap_mm": gap,
        "rate": merged.get("rate"),
        "weight": merged.get("weightKg") or merged.get("weight"),
        "glass1Mm": g1,
        "glass2Mm": g2,
        "pvbMm": pvb,
        "airGapMm": gap,
        "makeup": construction,
        "thicknessMm": _num(total) if total not in (None, "") else None,
        "overallMm": _num(total) if total not in (None, "") else None,
        "source": "selected",
    }
    snap["display_label"] = glass_display_label(snap)
    return snap


def _series_name(series_id: str) -> str:
    sid = str(series_id or "").strip()
    if not sid:
        return ""
    try:
        from WEOS.factory.section_catalogue import specs_summary_for_series

        summary = specs_summary_for_series(sid) or {}
        return str(summary.get("displayName") or summary.get("title") or sid)
    except Exception:
        return sid


def _load_named_product(product_id: str) -> dict[str, Any] | None:
    """Load this exact product_id. Never fall back to another catalogue row."""
    pid = str(product_id or "").strip()
    if not pid:
        return None
    try:
        from WEOS.factory.product_loader import load_product, product_dir

        product_dir(pid)  # raises if missing — do not substitute
        return load_product(pid, strict=False)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def freeze_item_snapshot(
    line: Mapping[str, Any] | None,
    *,
    overwrite_identity: bool = False,
    calculation: Mapping[str, Any] | None = None,
    preview: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Complete snapshot at add time. Identity is immutable unless explicitly overwritten."""
    src = dict(line) if isinstance(line, Mapping) else {}
    existing = get_item_snapshot(src)
    now = _now()
    if existing and not overwrite_identity:
        snap = dict(existing)
        snap["width"] = _num(src.get("width") if src.get("width") not in (None, "") else snap.get("width"))
        snap["height"] = _num(src.get("height") if src.get("height") not in (None, "") else snap.get("height"))
        snap["quantity"] = _int(src.get("qty") if src.get("qty") not in (None, "") else src.get("quantity", snap.get("quantity")))
        if src.get("lineId") and not snap.get("quote_item_id"):
            snap["quote_item_id"] = str(src.get("lineId"))
        if isinstance(src.get("options"), Mapping):
            snap["selected_options"] = copy.deepcopy(dict(src.get("options") or {}))
        if calculation is not None:
            snap["calculation_snapshot"] = _strip_preview_svg(calculation)
        if preview is not None:
            snap["preview_snapshot"] = _preview_blob(preview)
        elif isinstance(src.get("preview"), Mapping) and not snap.get("preview_snapshot"):
            snap["preview_snapshot"] = _preview_blob(src.get("preview"))
        snap["updated_at"] = now
        snap["configuration_version"] = int(snap.get("configuration_version") or CONFIGURATION_VERSION)
        if not snap.get("glass_snapshot"):
            from WEOS.factory.line_kind import is_railing_cart_line

            snap["glass_snapshot"] = build_glass_snapshot(src, railing=is_railing_cart_line(src))
        return snap

    from WEOS.factory.line_kind import is_railing_cart_line, line_world

    pid = product_id_of(src)
    product = _load_named_product(pid) if pid else None
    world = line_world(src, product=product)
    opts = _as_map(src.get("options"))
    series_id = str(src.get("sectionSeries") or opts.get("sectionSeries") or "").strip()
    display = str(
        src.get("displayName")
        or (product or {}).get("displayName")
        or src.get("description")
        or pid
        or ""
    ).strip()
    category = str(
        src.get("category")
        or (product or {}).get("category")
        or ""
    ).strip()
    if world == "louver" and (not category or category.lower() in ("windows", "window")):
        category = "Louvers"
    if world in ("railing", "staircase_railing") and (not category or category.lower() in ("windows", "window")):
        category = "Railings"

    glass_snap = build_glass_snapshot(src, railing=is_railing_cart_line(src) or world in ("railing", "staircase_railing"))
    hw = src.get("hardware")
    if not isinstance(hw, list):
        hw = opts.get("hardware") if isinstance(opts.get("hardware"), list) else []
    profile = {
        "productType": src.get("productType") or opts.get("productType") or (product or {}).get("productType"),
        "system": src.get("system") or opts.get("system"),
        "sectionSeries": series_id or None,
        "world": world,
    }
    snap = {
        "quote_item_id": _line_id(src),
        "product_id": pid,
        "product_name_snapshot": display,
        "category_snapshot": category,
        "series_id": series_id or None,
        "series_name_snapshot": _series_name(series_id) if series_id else None,
        "width": _num(src.get("width")),
        "height": _num(src.get("height")),
        "quantity": _int(src.get("qty") if src.get("qty") not in (None, "") else src.get("quantity")),
        "selected_options": copy.deepcopy(opts),
        "profile_snapshot": profile,
        "hardware_snapshot": copy.deepcopy(hw) if hw else [],
        "glass_snapshot": glass_snap,
        "calculation_snapshot": _strip_preview_svg(calculation) if calculation is not None else None,
        "preview_snapshot": _preview_blob(preview if preview is not None else src.get("preview")),
        "created_at": str(existing.get("created_at") or src.get("createdAt") or now),
        "updated_at": now,
        "configuration_version": CONFIGURATION_VERSION,
        "product_unavailable": bool(pid) and product is None,
    }
    if pid in ("railing",):
        snap["product_unavailable"] = False
        snap.pop("error", None)
    if snap["product_unavailable"]:
        snap["error"] = PRODUCT_UNAVAILABLE
    return snap


def _preview_blob(preview: Any) -> dict[str, Any] | None:
    if not isinstance(preview, Mapping):
        return None
    out = {k: v for k, v in preview.items() if k not in ("svg", "pdfSvg")}
    svg = str(preview.get("svg") or preview.get("pdfSvg") or "").strip()
    if svg and "<svg" in svg.lower():
        out["svg"] = svg
    return out or None


def _strip_preview_svg(calc: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(calc))
    prev = out.get("preview")
    if isinstance(prev, Mapping):
        slim = {k: v for k, v in prev.items() if k not in ("svg", "pdfSvg")}
        svg = str(prev.get("svg") or prev.get("pdfSvg") or "").strip()
        if svg and "<svg" in svg.lower():
            slim["svg"] = svg
        out["preview"] = slim
    return out


def attach_snapshot(
    line: MutableMapping[str, Any] | Mapping[str, Any],
    *,
    overwrite_identity: bool = False,
    calculation: Mapping[str, Any] | None = None,
    preview: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp snapshot onto a cart line (mutates dicts). Returns the line dict."""
    out = dict(line) if isinstance(line, Mapping) else {}
    snap = freeze_item_snapshot(
        out, overwrite_identity=overwrite_identity, calculation=calculation, preview=preview
    )
    out["itemSnapshot"] = snap
    out["item_snapshot"] = snap
    out["glass_snapshot"] = snap.get("glass_snapshot")
    out["glassSnapshot"] = snap.get("glass_snapshot")
    out["configuration_version"] = snap.get("configuration_version") or CONFIGURATION_VERSION
    if snap.get("product_id"):
        if not out.get("product"):
            out["product"] = snap["product_id"]
        if not out.get("productId"):
            out["productId"] = snap["product_id"]
    if snap.get("product_name_snapshot") and not out.get("displayName"):
        out["displayName"] = snap["product_name_snapshot"]
    if snap.get("category_snapshot") and not out.get("category"):
        out["category"] = snap["category_snapshot"]
    if isinstance(line, dict):
        line.clear()
        line.update(out)
        return line
    return out


def freeze_project_lines(lines: Any, *, overwrite_identity: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ln in lines or []:
        if not isinstance(ln, Mapping):
            continue
        out.append(attach_snapshot(dict(ln), overwrite_identity=overwrite_identity))
    return out


def resolved_config(line: Mapping[str, Any] | None) -> dict[str, Any]:
    """Single resolved product configuration for Preview, BOM, PDF, Pricing."""
    src = dict(line) if isinstance(line, Mapping) else {}
    snap = freeze_item_snapshot(src)
    pid = str(snap.get("product_id") or "").strip()
    unavailable = bool(snap.get("product_unavailable")) or (bool(pid) and _load_named_product(pid) is None and pid not in ("railing",))
    # Designer-only ids (railing) are valid without a product folder.
    if pid in ("railing", "shower_partition", "bathroom_ventilator"):
        unavailable = False
    glass = snap.get("glass_snapshot") if isinstance(snap.get("glass_snapshot"), Mapping) else {}
    cfg = {
        "quote_item_id": snap.get("quote_item_id") or _line_id(src),
        "product_id": pid,
        "product_name": snap.get("product_name_snapshot") or src.get("displayName") or pid,
        "category": snap.get("category_snapshot") or src.get("category") or "",
        "series_id": snap.get("series_id"),
        "series_name": snap.get("series_name_snapshot"),
        "width": snap.get("width"),
        "height": snap.get("height"),
        "quantity": snap.get("quantity"),
        "selected_options": snap.get("selected_options") or _as_map(src.get("options")),
        "profile": snap.get("profile_snapshot") or {},
        "hardware": snap.get("hardware_snapshot") or [],
        "glass": glass,
        "glass_display_label": glass_display_label(glass) if glass else "",
        "calculation": snap.get("calculation_snapshot"),
        "preview": snap.get("preview_snapshot") or src.get("preview"),
        "configuration_version": snap.get("configuration_version") or CONFIGURATION_VERSION,
        "world": (snap.get("profile_snapshot") or {}).get("world"),
        "error": PRODUCT_UNAVAILABLE if unavailable and pid else (snap.get("error") or None),
        "snapshot": snap,
    }
    return cfg


def apply_snapshot_to_result(result: MutableMapping[str, Any], line: Mapping[str, Any] | None) -> dict[str, Any]:
    """Force calc/PDF output to consume snapshot identity — never library names."""
    cfg = resolved_config(line)
    snap = cfg.get("snapshot") or {}
    result["itemSnapshot"] = snap
    result["item_snapshot"] = snap
    result["glass_snapshot"] = cfg.get("glass") or result.get("glass_snapshot")
    result["glassSnapshot"] = result.get("glass_snapshot")
    if cfg.get("product_id"):
        result["product"] = cfg["product_id"]
        result["productId"] = cfg["product_id"]
    if cfg.get("product_name"):
        result["displayName"] = cfg["product_name"]
    if cfg.get("category"):
        result["category"] = cfg["category"]
    if cfg.get("series_id") and not result.get("sectionSeries"):
        result["sectionSeries"] = cfg["series_id"]
    if cfg.get("error"):
        result["error"] = cfg["error"]
        result["productUnavailable"] = True
    result["configuration_version"] = cfg.get("configuration_version")
    return result if isinstance(result, dict) else dict(result)


class ProductUnavailable(RuntimeError):
    def __init__(self, message: str = PRODUCT_UNAVAILABLE) -> None:
        super().__init__(message)
