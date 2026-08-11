"""Panel fill options — glass replacement with sheet / louvers (optional features).

Base product type still drives the cart world (sliding / fold / railing / …).
Fills are *composable add-ons*: a Fold & Sliding leaf can swap glass for
horizontal or vertical aluminium louvers without changing the product type.

Louvers are parametric (gap + blade profile). 2D canvas/PDF draw the blades and
mark gaps so a fold-door quote prints clearly.
"""

from __future__ import annotations

from typing import Any, Mapping

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


def normalize_panel_fill(raw: Any) -> dict[str, Any]:
    """Clean a panel-fill / louver feature blob."""
    r = raw if isinstance(raw, Mapping) else {}
    fill = normalize_fill_type(r.get("fillType") or r.get("type") or r.get("fill") or "glass")
    orient = str(r.get("orientation") or r.get("louverOrientation") or "horizontal").strip().lower()
    if orient not in ("horizontal", "vertical"):
        orient = "horizontal"

    def _num(key: str, *alts: str, default: float | None = None) -> float | None:
        for k in (key, *alts):
            v = r.get(k)
            if v is None or v == "":
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return default

    out: dict[str, Any] = {
        "fillType": fill,
        "label": FILL_LABELS.get(fill, fill),
    }
    if fill == "louvers":
        # Defaults inspired by shop drawing (depth 70, thk 3) but gap is user-primary.
        out.update({
            "orientation": orient,
            "gapMm": _num("gapMm", "louverGapMm", "gap", default=20.0) or 20.0,
            "bladeWidthMm": _num("bladeWidthMm", "louverWidthMm", "bladeFaceMm", default=50.0) or 50.0,
            "bladeDepthMm": _num("bladeDepthMm", "louverDepthMm", "depthMm", default=70.0) or 70.0,
            "bladeThicknessMm": _num("bladeThicknessMm", "louverThicknessMm", "thicknessMm", default=3.0) or 3.0,
            # Optional flange / overall (shop-drawing inspiration; not required for 2D leaf view)
            "flangeExtraMm": _num("flangeExtraMm", default=89.0),
            "mountHoleDiaMm": _num("mountHoleDiaMm", default=12.0),
            "mountHolePitchMm": _num("mountHolePitchMm", default=150.0),
        })
    elif fill in ("aluminium_sheet", "compact_sheet"):
        out["thicknessMm"] = _num("thicknessMm", "sheetThicknessMm", default=3.0) or 3.0
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
        })
    return normalize_panel_fill({"fillType": "glass"})


def compute_louver_layout(
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    fill: Mapping[str, Any],
) -> dict[str, Any]:
    """Place louver blades inside a leaf glass rect; return drawable geometry + dims."""
    f = normalize_panel_fill(fill)
    orient = str(f.get("orientation") or "horizontal")
    gap = max(float(f.get("gapMm") or 20.0), 0.0)
    blade = max(float(f.get("bladeWidthMm") or 50.0), 1.0)
    depth = float(f.get("bladeDepthMm") or 70.0)
    thk = float(f.get("bladeThicknessMm") or 3.0)
    w = max(float(x1) - float(x0), 0.0)
    h = max(float(y1) - float(y0), 0.0)
    span = h if orient == "horizontal" else w
    pitch = blade + gap
    n = int((span + gap) // pitch) if pitch > 0 else 0
    n = max(n, 1) if span >= blade else 0
    used = n * blade + max(n - 1, 0) * gap
    margin = max((span - used) / 2.0, 0.0)

    blades: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    cursor = (y0 + margin) if orient == "horizontal" else (x0 + margin)
    for i in range(n):
        if orient == "horizontal":
            by0, by1 = cursor, cursor + blade
            blades.append({
                "index": i + 1,
                "x0": x0, "y0": by0, "x1": x1, "y1": by1,
                "orientation": orient,
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
            bx0, bx1 = cursor, cursor + blade
            blades.append({
                "index": i + 1,
                "x0": bx0, "y0": y0, "x1": bx1, "y1": y1,
                "orientation": orient,
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

    return {
        "fillType": "louvers",
        "orientation": orient,
        "gapMm": gap,
        "bladeWidthMm": blade,
        "bladeDepthMm": depth,
        "bladeThicknessMm": thk,
        "bladeCount": n,
        "openingWidthMm": round(w, 1),
        "openingHeightMm": round(h, 1),
        "marginMm": round(margin, 2),
        "blades": blades,
        "gaps": gaps,
        # Shop-drawing inspired overall (optional annotation only)
        "overallWidthMm": round(w + float(f.get("flangeExtraMm") or 89.0), 1) if f.get("flangeExtraMm") else None,
        "overallHeightMm": round(h + float(f.get("flangeExtraMm") or 89.0), 1) if f.get("flangeExtraMm") else None,
    }


def fill_spec_lines(fill: Mapping[str, Any] | None) -> list[str]:
    """Customer-PDF spec lines for the active panel fill."""
    f = normalize_panel_fill(fill or {})
    ft = f.get("fillType") or "glass"
    if ft == "glass":
        return []
    lines = [f"Panel fill = {FILL_LABELS.get(ft, ft)}"]
    if ft == "louvers":
        lines.append(
            f"Louvers = {f.get('orientation')} · gap {f.get('gapMm')} mm"
            f" · blade {f.get('bladeWidthMm')}×{f.get('bladeDepthMm')}×{f.get('bladeThicknessMm')} mm (W×D×Thk)"
        )
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
        # hatch
        parts.append(
            f'<rect x="{tx(x0):.2f}" y="{ty(y1):.2f}" width="{tx(x1)-tx(x0):.2f}" '
            f'height="{ty(y0)-ty(y1):.2f}" fill="{tint}" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
        )
        # diagonal hatch lines
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
    # Background opening
    parts.append(
        f'<rect x="{tx(x0):.2f}" y="{ty(y1):.2f}" width="{tx(x1)-tx(x0):.2f}" '
        f'height="{ty(y0)-ty(y1):.2f}" fill="rgba(230,235,240,0.35)" stroke="#2a4a6a" '
        f'stroke-width="{sw:.2f}"/>'
    )
    for b in layout.get("blades") or []:
        bx0, by0, bx1, by1 = float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"])
        parts.append(
            f'<rect x="{tx(bx0):.2f}" y="{ty(by1):.2f}" width="{tx(bx1)-tx(bx0):.2f}" '
            f'height="{ty(by0)-ty(by1):.2f}" fill="rgba(150,160,170,0.85)" stroke="#222" '
            f'stroke-width="{0.55*k:.2f}"/>'
        )
        # thin edge to suggest blade thickness / depth in 2D
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
    if annotate:
        for g in layout.get("gaps") or []:
            lx, ly = g.get("labelAt") or ((g["x0"] + g["x1"]) / 2.0, (g["y0"] + g["y1"]) / 2.0)
            gap_txt = f"{float(g.get('gapMm') or layout.get('gapMm') or 0):g}"
            parts.append(
                f'<text x="{tx(lx):.2f}" y="{ty(ly) + 4*k:.2f}" text-anchor="middle" '
                f'font-family="Segoe UI, Arial, sans-serif" font-size="{14*k:.0f}" '
                f'fill="#8b1e1a" font-weight="600">{gap_txt}</text>'
            )
        # Profile callout once per leaf (bottom-right)
        call = (
            f"Louvers {layout.get('orientation')} · gap {layout.get('gapMm'):g} · "
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
