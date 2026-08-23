"""Shared SVG schematics for non-window catalogue products."""

from __future__ import annotations

from html import escape
from typing import Any, Mapping


def _num(*values: Any, default: float = 0.0) -> float:
    for val in values:
        if val in (None, ""):
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return float(default)


def _fmt(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return str(val or "")
    return f"{n:g}"


def _opts(line: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(line, Mapping):
        return {}
    opts = line.get("options")
    return opts if isinstance(opts, Mapping) else {}


def _panel_fill(line: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(line, Mapping):
        return {}
    opts = _opts(line)
    fill = line.get("panelFill")
    if not isinstance(fill, Mapping):
        fill = opts.get("panelFill") if isinstance(opts.get("panelFill"), Mapping) else {}
    if not fill and isinstance(line.get("features"), list):
        for feature in line.get("features") or []:
            if isinstance(feature, Mapping) and str(feature.get("type") or "").lower() in ("panel_fill", "louvers"):
                fill = feature
                break
    return fill if isinstance(fill, Mapping) else {}


def louver_svg(line: Mapping[str, Any] | None, *, quote: Mapping[str, Any] | None = None) -> str:
    """Draw a standalone louver product preview/PDF elevation."""
    width = _num(
        (quote or {}).get("widthMm") if isinstance(quote, Mapping) else None,
        (line or {}).get("widthMm") if isinstance(line, Mapping) else None,
        (line or {}).get("width") if isinstance(line, Mapping) else None,
        default=1200,
    )
    height = _num(
        (quote or {}).get("heightMm") if isinstance(quote, Mapping) else None,
        (line or {}).get("heightMm") if isinstance(line, Mapping) else None,
        (line or {}).get("height") if isinstance(line, Mapping) else None,
        default=1500,
    )
    fill = dict(_panel_fill(line))
    fill.setdefault("fillType", "louvers")
    fill.setdefault("orientation", "horizontal")
    fill.setdefault("bladeWidthMm", fill.get("bladeMm") or 80)
    fill.setdefault("gapMm", 20)
    orient = str(fill.get("orientation") or "horizontal").lower()

    vb_w, vb_h = 520.0, 360.0
    pad = 36.0
    title_h = 34.0
    max_w = vb_w - pad * 2
    max_h = vb_h - pad * 2 - title_h
    scale = min(max_w / max(width, 1.0), max_h / max(height, 1.0))
    dw, dh = width * scale, height * scale
    x = (vb_w - dw) / 2.0
    y = title_h + (max_h - dh) / 2.0 + pad / 2.0

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:g} {vb_h:g}" data-model-system="louver" role="img">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{pad:g}" y="24" font-family="Arial" font-size="16" font-weight="700" fill="#1f2937">Louvers</text>',
        f'<text x="{vb_w - pad:g}" y="24" font-family="Arial" font-size="12" text-anchor="end" fill="#475569">{_fmt(width)} x {_fmt(height)} mm</text>',
        f'<rect x="{x:g}" y="{y:g}" width="{dw:g}" height="{dh:g}" fill="#f8fafc" stroke="#111827" stroke-width="2.2"/>',
        f'<rect x="{x + 8:g}" y="{y + 8:g}" width="{max(dw - 16, 1):g}" height="{max(dh - 16, 1):g}" fill="none" stroke="#64748b" stroke-width="1.2"/>',
    ]
    try:
        from WEOS.factory.panel_fills import compute_louver_layout

        layout = compute_louver_layout(x0=0, y0=0, x1=max(width, 1), y1=max(height, 1), fill=fill)
        blades = list((layout or {}).get("blades") or [])
    except Exception:
        blades = []

    if blades:
        for blade in blades[:80]:
            bx0 = x + _num(blade.get("x0")) * scale
            by0 = y + _num(blade.get("y0")) * scale
            bw = max((_num(blade.get("x1")) - _num(blade.get("x0"))) * scale, 1.0)
            bh = max((_num(blade.get("y1")) - _num(blade.get("y0"))) * scale, 1.0)
            parts.append(
                f'<rect x="{bx0:g}" y="{by0:g}" width="{bw:g}" height="{bh:g}" rx="1.5" '
                'fill="#cbd5e1" stroke="#475569" stroke-width="0.75" data-louver="1"/>'
            )
    else:
        blade = max(_num(fill.get("bladeWidthMm"), fill.get("bladeMm"), default=80) * scale, 6)
        gap = max(_num(fill.get("gapMm"), default=20) * scale, 3)
        if orient == "vertical":
            cursor = x + 14
            while cursor + blade <= x + dw - 12:
                parts.append(f'<rect x="{cursor:g}" y="{y + 12:g}" width="{blade:g}" height="{max(dh - 24, 1):g}" fill="#cbd5e1" stroke="#475569" stroke-width="0.75" data-louver="1"/>')
                cursor += blade + gap
        else:
            cursor = y + 14
            while cursor + blade <= y + dh - 12:
                parts.append(f'<rect x="{x + 12:g}" y="{cursor:g}" width="{max(dw - 24, 1):g}" height="{blade:g}" fill="#cbd5e1" stroke="#475569" stroke-width="0.75" data-louver="1"/>')
                cursor += blade + gap

    label = f"{escape(orient.title())} blades - gap {_fmt(fill.get('gapMm') or 20)} mm"
    parts.extend([
        f'<line x1="{x:g}" y1="{y + dh + 12:g}" x2="{x + dw:g}" y2="{y + dh + 12:g}" stroke="#111827" stroke-width="1"/>',
        f'<text x="{x + dw / 2:g}" y="{min(vb_h - 18, y + dh + 30):g}" font-family="Arial" font-size="11" text-anchor="middle" fill="#334155">{label}</text>',
        '</svg>',
    ])
    return "".join(parts)


def pergola_svg(line: Mapping[str, Any] | None, *, quote: Mapping[str, Any] | None = None) -> str:
    """Draw a catalogue-style pergola plan/elevation schematic."""
    opts = _opts(line)
    pergola = opts.get("pergola") if isinstance(opts.get("pergola"), Mapping) else {}
    src: Mapping[str, Any] = pergola if pergola else (line if isinstance(line, Mapping) else {})
    width = _num((quote or {}).get("widthMm") if isinstance(quote, Mapping) else None, src.get("widthMm"), src.get("width"), default=3000)
    depth = _num((quote or {}).get("depthMm") if isinstance(quote, Mapping) else None, src.get("depthMm"), src.get("heightMm"), src.get("height"), default=2400)
    height = _num((quote or {}).get("heightMm") if isinstance(quote, Mapping) else None, src.get("postHeightMm"), src.get("pergolaHeightMm"), default=2700)
    fixing = str(src.get("fixing") or src.get("mount") or src.get("installType") or opts.get("fixing") or "floor / wall / garden").strip()
    cover = str(src.get("cover") or src.get("roofFill") or src.get("material") or "louvers / glass / polycarbonate").strip()
    post = str(src.get("post") or src.get("postSection") or "posts").strip()
    rafter = str(src.get("rafter") or src.get("rafterSection") or "rafters").strip()

    vb_w, vb_h = 640.0, 420.0
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:g} {vb_h:g}" data-model-system="pergola" role="img">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<text x="30" y="28" font-family="Arial" font-size="17" font-weight="700" fill="#111827">Pergola catalogue drawing</text>',
        f'<text x="610" y="28" font-family="Arial" font-size="12" text-anchor="end" fill="#475569">{_fmt(width)} x {_fmt(depth)} mm</text>',
    ]

    px, py, pw, ph = 36.0, 58.0, 355.0, 230.0
    parts.extend([
        f'<text x="{px:g}" y="{py - 12:g}" font-family="Arial" font-size="12" font-weight="700" fill="#334155">Floor plan</text>',
        f'<rect x="{px:g}" y="{py:g}" width="{pw:g}" height="{ph:g}" fill="#f8fafc" stroke="#111827" stroke-width="2"/>',
    ])
    for sx, sy in ((px, py), (px + pw, py), (px, py + ph), (px + pw, py + ph)):
        parts.append(f'<rect x="{sx - 8:g}" y="{sy - 8:g}" width="16" height="16" fill="#e2e8f0" stroke="#0f172a" stroke-width="1.4" data-role="post"/>')
        parts.append(f'<circle cx="{sx:g}" cy="{sy:g}" r="3" fill="#0f766e" data-role="fixing-plate"/>')
    rafter_count = max(4, min(12, int(round(width / 450.0)) if width else 6))
    for i in range(1, rafter_count):
        rx = px + (pw * i / rafter_count)
        parts.append(f'<line x1="{rx:g}" y1="{py:g}" x2="{rx:g}" y2="{py + ph:g}" stroke="#64748b" stroke-width="1.1" data-role="rafter"/>')
    louver_count = max(4, min(16, int(round(depth / 250.0)) if depth else 8))
    for i in range(1, louver_count):
        ly = py + (ph * i / louver_count)
        parts.append(f'<line x1="{px:g}" y1="{ly:g}" x2="{px + pw:g}" y2="{ly:g}" stroke="#cbd5e1" stroke-width="1" data-role="roof-fill"/>')

    ex, ey, ew, eh = 430.0, 78.0, 170.0, 150.0
    roof_y = ey + 16
    floor_y = ey + eh
    parts.extend([
        f'<text x="{ex:g}" y="{ey - 12:g}" font-family="Arial" font-size="12" font-weight="700" fill="#334155">Side elevation</text>',
        f'<line x1="{ex:g}" y1="{floor_y:g}" x2="{ex + ew:g}" y2="{floor_y:g}" stroke="#111827" stroke-width="1.6"/>',
        f'<line x1="{ex + 18:g}" y1="{roof_y:g}" x2="{ex + 18:g}" y2="{floor_y:g}" stroke="#111827" stroke-width="4" data-role="post"/>',
        f'<line x1="{ex + ew - 18:g}" y1="{roof_y:g}" x2="{ex + ew - 18:g}" y2="{floor_y:g}" stroke="#111827" stroke-width="4" data-role="post"/>',
        f'<line x1="{ex + 6:g}" y1="{roof_y:g}" x2="{ex + ew - 6:g}" y2="{roof_y:g}" stroke="#0f172a" stroke-width="5" data-role="beam"/>',
    ])
    for i in range(7):
        lx = ex + 18 + i * ((ew - 36) / 6)
        parts.append(f'<line x1="{lx:g}" y1="{roof_y - 11:g}" x2="{lx + 10:g}" y2="{roof_y:g}" stroke="#64748b" stroke-width="2" data-role="rafter"/>')

    callouts = [
        ("Fixing", fixing),
        ("Posts", post),
        ("Rafters", rafter),
        ("Roof", cover),
        ("Height", f"{_fmt(height)} mm"),
    ]
    cy = 316.0
    for label, value in callouts:
        parts.append(f'<text x="36" y="{cy:g}" font-family="Arial" font-size="11" font-weight="700" fill="#0f172a">{escape(label)}</text>')
        parts.append(f'<text x="104" y="{cy:g}" font-family="Arial" font-size="11" fill="#334155">{escape(value)}</text>')
        cy += 18.0
    parts.append('</svg>')
    return "".join(parts)
