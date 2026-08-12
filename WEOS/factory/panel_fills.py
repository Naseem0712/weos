"""Panel fill options — glass replacement with sheet / louvers (optional features).

Base product type still drives the cart world (sliding / fold / railing / …).
Fills are *composable add-ons*: a Fold & Sliding leaf can swap glass for
horizontal or vertical aluminium louvers without changing the product type.

Louvers support:
  - Simple uniform mode (gap + blade W×D×Thk) — backward compatible
  - Repeating pattern slots (varying size / gap / shape / depth offset)
  - Explicit per-blade list for irregular one-off designs
  - Rect or round-pipe blades; optional front/back stagger (depthOffsetMm)
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

FILL_TYPES = ("glass", "aluminium_sheet", "louvers", "compact_sheet")

FILL_LABELS = {
    "glass": "Glass",
    "aluminium_sheet": "Aluminium sheet",
    "louvers": "Louvers",
    "compact_sheet": "Compact sheet",
}

# Nested feature ids that can be composed onto a base product world.
# window_in_pergola is reserved for a future pergola canvas that nests a window job.
COMPOSABLE_FEATURES = (
    "panel_fill",          # glass → sheet / louvers / compact
    "window_in_pergola",   # hook: nest a window line/job inside a pergola bay
)


def normalize_fill_type(raw: Any) -> str:
    t = str(raw or "glass").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "alu_sheet": "aluminium_sheet",
        "aluminum_sheet": "aluminium_sheet",
        "alu": "aluminium_sheet",
        "sheet": "aluminium_sheet",
        "louver": "louvers",
        "louvre": "louvers",
        "louvres": "louvers",
        "compact": "compact_sheet",
        "hpl": "compact_sheet",
        "": "glass",
        "none": "glass",
        "default": "glass",
    }
    t = aliases.get(t, t)
    return t if t in FILL_TYPES else "glass"


def _num(raw: Mapping[str, Any], key: str, *alts: str, default: float | None = None) -> float | None:
    for k in (key, *alts):
        v = raw.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return default


def _normalize_blade_slot(raw: Any, *, defaults: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One blade in a pattern / explicit list."""
    r = raw if isinstance(raw, Mapping) else {}
    d = defaults if isinstance(defaults, Mapping) else {}
    shape = str(r.get("shape") or r.get("bladeShape") or d.get("bladeShape") or "rect").strip().lower()
    if shape in ("round", "pipe", "tube", "circle", "round_pipe"):
        shape = "round"
    else:
        shape = "rect"
    size = (
        _num(r, "sizeMm", "bladeWidthMm", "widthMm", "odMm", "faceMm")
        or _num(d, "bladeWidthMm", default=50.0)
        or 50.0
    )
    depth = (
        _num(r, "depthMm", "bladeDepthMm")
        or (size if shape == "round" else None)
        or _num(d, "bladeDepthMm", default=70.0)
        or 70.0
    )
    thk = _num(r, "thicknessMm", "bladeThicknessMm", "wallMm") or _num(d, "bladeThicknessMm", default=3.0) or 3.0
    gap_after = _num(r, "gapAfterMm", "gapMm", "gap") 
    if gap_after is None:
        gap_after = _num(d, "gapMm", default=20.0) or 20.0
    offset = _num(r, "depthOffsetMm", "offsetMm", "staggerMm", default=0.0) or 0.0
    return {
        "shape": shape,
        "sizeMm": float(size),
        "depthMm": float(depth),
        "thicknessMm": float(thk),
        "gapAfterMm": float(gap_after),
        "depthOffsetMm": float(offset),
    }


def normalize_panel_fill(raw: Any) -> dict[str, Any]:
    """Clean a panel-fill / louver feature blob."""
    r = raw if isinstance(raw, Mapping) else {}
    fill = normalize_fill_type(r.get("fillType") or r.get("type") or r.get("fill") or "glass")
    orient = str(r.get("orientation") or r.get("louverOrientation") or "horizontal").strip().lower()
    if orient not in ("horizontal", "vertical"):
        orient = "horizontal"

    out: dict[str, Any] = {
        "fillType": fill,
        "label": FILL_LABELS.get(fill, fill),
    }
    if fill == "louvers":
        shape = str(r.get("bladeShape") or r.get("shape") or "rect").strip().lower()
        if shape in ("round", "pipe", "tube", "circle", "round_pipe"):
            shape = "round"
        else:
            shape = "rect"
        mode = str(r.get("patternMode") or r.get("mode") or "").strip().lower()
        pattern_raw = r.get("pattern") or r.get("bladePattern") or []
        blades_raw = r.get("blades") or r.get("bladeList") or r.get("slots") or []
        if not mode:
            if isinstance(blades_raw, (list, tuple)) and blades_raw:
                mode = "explicit"
            elif isinstance(pattern_raw, (list, tuple)) and pattern_raw:
                mode = "repeat"
            else:
                mode = "uniform"

        defaults = {
            "gapMm": _num(r, "gapMm", "louverGapMm", "gap", default=20.0) or 20.0,
            "bladeWidthMm": _num(r, "bladeWidthMm", "louverWidthMm", "bladeFaceMm", default=50.0) or 50.0,
            "bladeDepthMm": _num(r, "bladeDepthMm", "louverDepthMm", "depthMm", default=70.0) or 70.0,
            "bladeThicknessMm": _num(r, "bladeThicknessMm", "louverThicknessMm", "thicknessMm", default=3.0) or 3.0,
            "bladeShape": shape,
        }
        out.update({
            "orientation": orient,
            "gapMm": defaults["gapMm"],
            "bladeWidthMm": defaults["bladeWidthMm"],
            "bladeDepthMm": defaults["bladeDepthMm"],
            "bladeThicknessMm": defaults["bladeThicknessMm"],
            "bladeShape": shape,
            "patternMode": mode if mode in ("uniform", "repeat", "explicit") else "uniform",
            "flangeExtraMm": _num(r, "flangeExtraMm", default=89.0),
            "mountHoleDiaMm": _num(r, "mountHoleDiaMm", default=12.0),
            "mountHolePitchMm": _num(r, "mountHolePitchMm", default=150.0),
        })
        if isinstance(pattern_raw, (list, tuple)) and pattern_raw:
            out["pattern"] = [_normalize_blade_slot(s, defaults=defaults) for s in pattern_raw]
        else:
            out["pattern"] = []
        if isinstance(blades_raw, (list, tuple)) and blades_raw and mode == "explicit":
            out["blades"] = [_normalize_blade_slot(s, defaults=defaults) for s in blades_raw]
        else:
            out["blades"] = []
    elif fill in ("aluminium_sheet", "compact_sheet"):
        out["thicknessMm"] = _num(r, "thicknessMm", "sheetThicknessMm", default=3.0) or 3.0
        out["orientation"] = orient  # unused but kept for UI round-trip
    return out


def panel_fill_from_line(line: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve the active fill feature from a cart line / options / features list."""
    line = line if isinstance(line, Mapping) else {}
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    # Explicit panelFill blob
    for src in (line.get("panelFill"), (opts or {}).get("panelFill"), line.get("fill")):
        if isinstance(src, Mapping) and src:
            return normalize_panel_fill(src)
    # features: [{type:'panel_fill', ...}] or {panel_fill: {...}}
    feats = line.get("features") or (opts or {}).get("features")
    if isinstance(feats, Mapping) and isinstance(feats.get("panel_fill"), Mapping):
        return normalize_panel_fill(feats.get("panel_fill"))
    if isinstance(feats, (list, tuple)):
        for f in feats:
            if not isinstance(f, Mapping):
                continue
            kind = str(f.get("type") or f.get("feature") or "").lower()
            if kind in ("panel_fill", "fill", "louvers", "glass_replace"):
                return normalize_panel_fill(f)
            if normalize_fill_type(f.get("fillType")) != "glass" or f.get("orientation"):
                return normalize_panel_fill(f)
    # Shorthand: options.fillType = louvers
    if (opts or {}).get("fillType") or line.get("fillType"):
        return normalize_panel_fill({
            "fillType": (opts or {}).get("fillType") or line.get("fillType"),
            "orientation": (opts or {}).get("louverOrientation") or line.get("louverOrientation"),
            "gapMm": (opts or {}).get("louverGapMm") or line.get("louverGapMm"),
            "bladeWidthMm": (opts or {}).get("louverBladeWidthMm") or line.get("louverBladeWidthMm"),
            "bladeDepthMm": (opts or {}).get("louverBladeDepthMm") or line.get("louverBladeDepthMm"),
            "bladeThicknessMm": (opts or {}).get("louverBladeThicknessMm") or line.get("louverBladeThicknessMm"),
            "bladeShape": (opts or {}).get("louverBladeShape") or line.get("louverBladeShape"),
            "patternMode": (opts or {}).get("louverPatternMode") or line.get("louverPatternMode"),
            "pattern": (opts or {}).get("louverPattern") or line.get("louverPattern"),
            "blades": (opts or {}).get("louverBlades") or line.get("louverBlades"),
        })
    return normalize_panel_fill({"fillType": "glass"})


def _slot_sequence(fill: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand pattern / explicit / uniform into an ordered list of blade slots to try."""
    f = fill
    mode = str(f.get("patternMode") or "uniform")
    if mode == "explicit" and f.get("blades"):
        return list(f["blades"])
    if mode == "repeat" and f.get("pattern"):
        # Return the repeating unit; caller tiles it
        return list(f["pattern"])
    # Uniform single-slot pattern
    return [_normalize_blade_slot({
        "shape": f.get("bladeShape") or "rect",
        "sizeMm": f.get("bladeWidthMm"),
        "depthMm": f.get("bladeDepthMm"),
        "thicknessMm": f.get("bladeThicknessMm"),
        "gapAfterMm": f.get("gapMm"),
        "depthOffsetMm": 0,
    }, defaults=f)]


def compute_louver_layout(
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    fill: Mapping[str, Any],
) -> dict[str, Any]:
    """Place louver blades inside a leaf glass rect; return drawable geometry + dims.

    Gaps do not add material. Blade length = opening width (horizontal louvers)
    or opening height (vertical louvers).
    """
    f = normalize_panel_fill(fill)
    orient = str(f.get("orientation") or "horizontal")
    mode = str(f.get("patternMode") or "uniform")
    w = max(float(x1) - float(x0), 0.0)
    h = max(float(y1) - float(y0), 0.0)
    span = h if orient == "horizontal" else w

    unit = _slot_sequence(f)
    if not unit:
        unit = [_normalize_blade_slot({}, defaults=f)]

    # Build concrete blade list that fits the span
    planned: list[dict[str, Any]] = []
    if mode == "explicit":
        planned = [dict(s) for s in unit]
    else:
        # Tile the repeating unit until the next blade would not fit
        used = 0.0
        i = 0
        safety = 500
        while safety > 0:
            safety -= 1
            slot = dict(unit[i % len(unit)])
            size = max(float(slot.get("sizeMm") or 1.0), 1.0)
            gap = max(float(slot.get("gapAfterMm") or 0.0), 0.0)
            if used + size > span + 1e-6:
                break
            planned.append(slot)
            used += size
            # Trailing gap after last blade is not required to fit
            nxt_size = max(float(unit[(i + 1) % len(unit)].get("sizeMm") or 1.0), 1.0)
            if used + gap + nxt_size > span + 1e-6:
                break
            used += gap
            i += 1

    n = len(planned)
    if n == 0 and span >= 1:
        # At least one blade if opening is non-trivial
        planned = [dict(unit[0])]
        n = 1

    used_span = 0.0
    for i, slot in enumerate(planned):
        used_span += max(float(slot.get("sizeMm") or 1.0), 1.0)
        if i < n - 1:
            used_span += max(float(slot.get("gapAfterMm") or 0.0), 0.0)
    margin = max((span - used_span) / 2.0, 0.0)

    blades: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    cursor = (y0 + margin) if orient == "horizontal" else (x0 + margin)

    for i, slot in enumerate(planned):
        size = max(float(slot.get("sizeMm") or 1.0), 1.0)
        gap = max(float(slot.get("gapAfterMm") or 0.0), 0.0)
        offset = float(slot.get("depthOffsetMm") or 0.0)
        shape = str(slot.get("shape") or "rect")
        depth = float(slot.get("depthMm") or f.get("bladeDepthMm") or 70.0)
        thk = float(slot.get("thicknessMm") or f.get("bladeThicknessMm") or 3.0)

        if orient == "horizontal":
            by0, by1 = cursor, cursor + size
            # Stagger: shift along depth axis visualized as X inset
            ox = offset
            blades.append({
                "index": i + 1,
                "x0": x0 + max(ox, 0.0), "y0": by0,
                "x1": x1 + min(ox, 0.0), "y1": by1,
                "orientation": orient,
                "shape": shape,
                "sizeMm": size,
                "depthMm": depth,
                "thicknessMm": thk,
                "depthOffsetMm": offset,
                "lengthMm": round(w, 1),
            })
            if i < n - 1:
                gy0, gy1 = by1, by1 + gap
                gaps.append({
                    "index": i + 1,
                    "x0": x0, "y0": gy0, "x1": x1, "y1": gy1,
                    "gapMm": gap,
                    "labelAt": ((x0 + x1) / 2.0, (gy0 + gy1) / 2.0),
                })
            cursor = by1 + gap
        else:
            bx0, bx1 = cursor, cursor + size
            oy = offset
            blades.append({
                "index": i + 1,
                "x0": bx0, "y0": y0 + max(oy, 0.0),
                "x1": bx1, "y1": y1 + min(oy, 0.0),
                "orientation": orient,
                "shape": shape,
                "sizeMm": size,
                "depthMm": depth,
                "thicknessMm": thk,
                "depthOffsetMm": offset,
                "lengthMm": round(h, 1),
            })
            if i < n - 1:
                gx0, gx1 = bx1, bx1 + gap
                gaps.append({
                    "index": i + 1,
                    "x0": gx0, "y0": y0, "x1": gx1, "y1": y1,
                    "gapMm": gap,
                    "labelAt": ((gx0 + gx1) / 2.0, (y0 + y1) / 2.0),
                })
            cursor = bx1 + gap

    primary_gap = float(f.get("gapMm") or 20.0)
    if gaps:
        primary_gap = float(gaps[0].get("gapMm") or primary_gap)

    return {
        "fillType": "louvers",
        "orientation": orient,
        "patternMode": mode,
        "gapMm": primary_gap,
        "bladeWidthMm": float(f.get("bladeWidthMm") or 50.0),
        "bladeDepthMm": float(f.get("bladeDepthMm") or 70.0),
        "bladeThicknessMm": float(f.get("bladeThicknessMm") or 3.0),
        "bladeShape": f.get("bladeShape") or "rect",
        "bladeCount": n,
        "openingWidthMm": round(w, 1),
        "openingHeightMm": round(h, 1),
        "marginMm": round(margin, 2),
        "blades": blades,
        "gaps": gaps,
        "bom": louver_bom_from_layout({
            "orientation": orient,
            "blades": blades,
            "openingWidthMm": w,
            "openingHeightMm": h,
        }),
        "overallWidthMm": round(w + float(f.get("flangeExtraMm") or 89.0), 1) if f.get("flangeExtraMm") else None,
        "overallHeightMm": round(h + float(f.get("flangeExtraMm") or 89.0), 1) if f.get("flangeExtraMm") else None,
    }


def louver_bom_from_layout(layout: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Cut lengths for blades — gaps add no material."""
    lines: list[dict[str, Any]] = []
    for b in layout.get("blades") or []:
        length = float(b.get("lengthMm") or 0)
        if length <= 0:
            if str(layout.get("orientation")) == "horizontal":
                length = float(layout.get("openingWidthMm") or 0)
            else:
                length = float(layout.get("openingHeightMm") or 0)
        lines.append({
            "index": b.get("index"),
            "shape": b.get("shape") or "rect",
            "sizeMm": b.get("sizeMm"),
            "depthMm": b.get("depthMm"),
            "thicknessMm": b.get("thicknessMm"),
            "depthOffsetMm": b.get("depthOffsetMm") or 0,
            "lengthMm": round(length, 1),
            "qty": 1,
        })
    return lines


def compute_louver_weight(
    fill: Mapping[str, Any],
    *,
    opening_width_mm: float,
    opening_height_mm: float,
    qty: float = 1.0,
) -> dict[str, Any]:
    """Aluminium blade weight for a louver fill (additive; does not replace frame weight)."""
    f = normalize_panel_fill(fill)
    if (f.get("fillType") or "glass") != "louvers":
        return {"ok": True, "weightKg": 0.0, "bladeCount": 0, "details": []}
    layout = compute_louver_layout(
        x0=0, y0=0,
        x1=float(opening_width_mm), y1=float(opening_height_mm),
        fill=f,
    )
    details: list[dict[str, Any]] = []
    total = 0.0
    try:
        from WEOS.factory.weight_engine import calculate_material_weight
    except Exception:
        calculate_material_weight = None  # type: ignore

    for b in layout.get("blades") or []:
        length = float(b.get("lengthMm") or 0)
        size = float(b.get("sizeMm") or 50)
        depth = float(b.get("depthMm") or 70)
        thk = float(b.get("thicknessMm") or 3)
        shape = str(b.get("shape") or "rect")
        kg = 0.0
        why = ""
        if calculate_material_weight:
            if shape == "round":
                # Approx hollow pipe: π/4 * (OD² − ID²) * length * density
                od = size
                wall = max(min(thk, od / 2.0 - 0.1), 0.5)
                id_ = max(od - 2.0 * wall, 0.0)
                area = math.pi / 4.0 * (od * od - id_ * id_)
                res = calculate_material_weight(
                    "aluminium_profile",
                    dimensions={"lengthMm": length, "crossSectionAreaMm2": area},
                    quantity=1.0,
                )
            else:
                # Flat / box face: treat as sheet strip size × thickness × length
                res = calculate_material_weight(
                    "aluminium_sheet",
                    dimensions={
                        "widthMm": size,
                        "heightMm": length,
                        "thicknessMm": thk,
                    },
                    quantity=1.0,
                )
            if isinstance(res, Mapping) and res.get("ok"):
                kg = float(res.get("totalWeight") or res.get("weightKg") or 0.0)
                why = str(res.get("formula") or res.get("sourceLabel") or "")
            else:
                # Fallback density calc
                dens = 2700.0
                if shape == "round":
                    od = size
                    wall = max(min(thk, od / 2.0 - 0.1), 0.5)
                    id_ = max(od - 2.0 * wall, 0.0)
                    area_m2 = (math.pi / 4.0 * (od * od - id_ * id_)) * 1e-6
                    kg = area_m2 * (length / 1000.0) * dens
                else:
                    kg = (size / 1000.0) * (length / 1000.0) * (thk / 1000.0) * dens
                why = "density fallback"
        else:
            dens = 2700.0
            kg = (size / 1000.0) * (length / 1000.0) * (thk / 1000.0) * dens
            why = "density fallback"
        total += kg
        details.append({
            "index": b.get("index"),
            "shape": shape,
            "lengthMm": length,
            "weightKg": round(kg, 3),
            "why": why,
        })
    total *= float(qty or 1.0)
    return {
        "ok": True,
        "weightKg": round(total, 3),
        "bladeCount": layout.get("bladeCount") or 0,
        "details": details,
        "bom": layout.get("bom") or [],
    }


def fill_spec_lines(fill: Mapping[str, Any] | None) -> list[str]:
    """Customer-PDF spec lines for the active panel fill."""
    f = normalize_panel_fill(fill or {})
    ft = f.get("fillType") or "glass"
    if ft == "glass":
        return []
    lines = [f"Panel fill = {FILL_LABELS.get(ft, ft)}"]
    if ft == "louvers":
        mode = f.get("patternMode") or "uniform"
        shape = f.get("bladeShape") or "rect"
        base = (
            f"Louvers = {f.get('orientation')} · {mode}"
            f" · shape {shape}"
        )
        if mode == "uniform":
            base += (
                f" · gap {f.get('gapMm')} mm"
                f" · blade {f.get('bladeWidthMm')}×{f.get('bladeDepthMm')}×{f.get('bladeThicknessMm')} mm (W×D×Thk)"
            )
        elif mode == "repeat" and f.get("pattern"):
            bits = []
            for s in f["pattern"]:
                bits.append(
                    f"{s.get('shape')} {s.get('sizeMm'):g}"
                    f"+gap{s.get('gapAfterMm'):g}"
                    + (f"@{s.get('depthOffsetMm'):g}off" if s.get("depthOffsetMm") else "")
                )
            base += " · pattern " + " → ".join(bits)
        elif mode == "explicit" and f.get("blades"):
            base += f" · {len(f['blades'])} explicit blades"
        lines.append(base)
    elif ft in ("aluminium_sheet", "compact_sheet"):
        lines.append(f"Sheet thickness = {f.get('thicknessMm') or 3} mm")
    return lines


def svg_fill_for_rect(
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    fill: Mapping[str, Any],
    tx,
    ty,
    k: float = 1.0,
    annotate: bool = True,
) -> list[str]:
    """SVG fragments for one glass rect replaced by the chosen fill."""
    f = normalize_panel_fill(fill)
    ft = f.get("fillType") or "glass"
    parts: list[str] = []
    sw = 0.7 * k
    if ft == "glass":
        return parts
    if ft in ("aluminium_sheet", "compact_sheet"):
        tint = "rgba(180, 185, 190, 0.55)" if ft == "aluminium_sheet" else "rgba(210, 190, 160, 0.55)"
        stroke = "#555" if ft == "aluminium_sheet" else "#6a4a28"
        parts.append(
            f'<rect x="{tx(x0):.2f}" y="{ty(y1):.2f}" width="{tx(x1)-tx(x0):.2f}" '
            f'height="{ty(y0)-ty(y1):.2f}" fill="{tint}" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
        )
        step = 28 * k
        x = x0
        while x < x1:
            parts.append(
                f'<line x1="{tx(x):.2f}" y1="{ty(y0):.2f}" x2="{tx(min(x + (y1-y0), x1)):.2f}" '
                f'y2="{ty(y1):.2f}" stroke="{stroke}" stroke-width="{0.45*k:.2f}" opacity="0.55"/>'
            )
            x += step
        if annotate:
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            lab = "ALU SHEET" if ft == "aluminium_sheet" else "COMPACT"
            parts.append(
                f'<text x="{tx(cx):.2f}" y="{ty(cy):.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{18*k:.0f}" '
                f'font-weight="700" fill="#333">{lab}</text>'
            )
        return parts

    # Louvers
    layout = compute_louver_layout(x0=x0, y0=y0, x1=x1, y1=y1, fill=f)
    parts.append(
        f'<rect x="{tx(x0):.2f}" y="{ty(y1):.2f}" width="{tx(x1)-tx(x0):.2f}" '
        f'height="{ty(y0)-ty(y1):.2f}" fill="rgba(230,235,240,0.35)" stroke="#2a4a6a" '
        f'stroke-width="{sw:.2f}"/>'
    )
    for b in layout.get("blades") or []:
        bx0, by0, bx1, by1 = float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"])
        shape = str(b.get("shape") or "rect")
        offset = float(b.get("depthOffsetMm") or 0)
        # Slightly different tint for staggered blades
        alpha = 0.85 if abs(offset) < 1 else (0.55 if offset > 0 else 0.7)
        fill_c = f"rgba(150,160,170,{alpha:.2f})"
        if shape == "round":
            cx = (bx0 + bx1) / 2.0
            cy = (by0 + by1) / 2.0
            if layout.get("orientation") == "vertical":
                rx = max((bx1 - bx0) / 2.0, 1.0)
                ry = min(rx * 0.85, (by1 - by0) / 2.0)
            else:
                ry = max((by1 - by0) / 2.0, 1.0)
                rx = min(ry * 0.85, (bx1 - bx0) / 2.0)
            parts.append(
                f'<ellipse cx="{tx(cx):.2f}" cy="{ty(cy):.2f}" rx="{abs(tx(cx+rx)-tx(cx)):.2f}" '
                f'ry="{abs(ty(cy)-ty(cy+ry)):.2f}" fill="{fill_c}" stroke="#222" '
                f'stroke-width="{0.55*k:.2f}"/>'
            )
        else:
            parts.append(
                f'<rect x="{tx(bx0):.2f}" y="{ty(by1):.2f}" width="{tx(bx1)-tx(bx0):.2f}" '
                f'height="{ty(by0)-ty(by1):.2f}" fill="{fill_c}" stroke="#222" '
                f'stroke-width="{0.55*k:.2f}"/>'
            )
            if layout.get("orientation") == "horizontal":
                mid = (by0 + by1) / 2.0
                parts.append(
                    f'<line x1="{tx(bx0):.2f}" y1="{ty(mid):.2f}" x2="{tx(bx1):.2f}" y2="{ty(mid):.2f}" '
                    f'stroke="#111" stroke-width="{0.35*k:.2f}" opacity="0.4"/>'
                )
            else:
                mid = (bx0 + bx1) / 2.0
                parts.append(
                    f'<line x1="{tx(mid):.2f}" y1="{ty(by0):.2f}" x2="{tx(mid):.2f}" y2="{ty(by1):.2f}" '
                    f'stroke="#111" stroke-width="{0.35*k:.2f}" opacity="0.4"/>'
                )
        if annotate and abs(offset) >= 1:
            lx = (bx0 + bx1) / 2.0
            ly = (by0 + by1) / 2.0
            parts.append(
                f'<text x="{tx(lx):.2f}" y="{ty(ly):.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{11*k:.0f}" '
                f'fill="#1a4a7a">Δ{offset:g}</text>'
            )
    if annotate:
        for g in layout.get("gaps") or []:
            lx, ly = g.get("labelAt") or ((g["x0"] + g["x1"]) / 2.0, (g["y0"] + g["y1"]) / 2.0)
            gap_txt = f"{float(g.get('gapMm') or layout.get('gapMm') or 0):g}"
            parts.append(
                f'<text x="{tx(lx):.2f}" y="{ty(ly) + 4*k:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{14*k:.0f}" '
                f'fill="#8b1e1a" font-weight="600">{gap_txt}</text>'
            )
        call = (
            f"Louvers {layout.get('orientation')} · {layout.get('patternMode')} · "
            f"n={layout.get('bladeCount')} · "
            f"blade {layout.get('bladeWidthMm'):g}×{layout.get('bladeDepthMm'):g}×{layout.get('bladeThicknessMm'):g}"
        )
        parts.append(
            f'<text x="{tx(x0) + 4*k:.2f}" y="{ty(y0) - 6*k:.2f}" text-anchor="start" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="{13*k:.0f}" fill="#333">{call}</text>'
        )
    return parts


def attach_fill_to_drawing(drawing: Any, fill: Mapping[str, Any] | None) -> Any:
    """Stamp panel_fill onto drawing.metadata so SVG/PDF render the replacement."""
    if drawing is None or not isinstance(fill, Mapping):
        return drawing
    f = normalize_panel_fill(fill)
    if (f.get("fillType") or "glass") == "glass":
        return drawing
    meta = dict(getattr(drawing, "metadata", None) or {})
    meta["panel_fill"] = f
    meta["panelFill"] = f
    drawing.metadata = meta
    return drawing
