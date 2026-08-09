"""Railing product — pricing calculator + 2D designer geometry / SVG.

Balcony-type straight (and simple shaped) railings.  The calculator reproduces
the fabricator's costing model:

* glass is divided into user-selected panels with a **12 mm gap** between panels
  and **12 mm at each wall side** (deducted from the raw length);
* **bottom rail** (and optional **handrail**) are sold per **RFT** or **RMT**
  with a weight per unit;
* **anchor bolts**: a base of *N per RFT* plus per-pillar anchors;
* **pillars/blocks**: 1–4 per glass, each pillar taking 1–2 anchors;
* a **wall connector** cost when both ends meet a wall.

Everything is summed to a **total**, then divided by the actual railing width
(RFT or RMT) to give the **per-unit rate**.  The user can then add extra costs
or override with their own selling rate.

Worked example (reproduced by :func:`compute_railing`):
  length 10 ft, 2 glass panels, 3 blocks/glass, height 2 ft, 2 anchors/pillar,
  glass ₹200/sft, block ₹100/pc, anchor ₹50/pc →
  panels ≈ 59 in each, glass ≈ 20 sft → ₹4000, blocks 6 → ₹600,
  anchors 12 → ₹600.
"""

from __future__ import annotations

import math
from typing import Any, Mapping
from xml.sax.saxutils import escape

MM_PER_FT = 304.8
MM_PER_IN = 25.4
MM_PER_M = 1000.0
SQMM_PER_SQFT = MM_PER_FT * MM_PER_FT
SQMM_PER_SQM = MM_PER_M * MM_PER_M


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _length_mm(cfg: Mapping[str, Any]) -> float:
    if cfg.get("lengthMm") not in (None, ""):
        return _f(cfg.get("lengthMm"))
    if cfg.get("lengthFt") not in (None, ""):
        return _f(cfg.get("lengthFt")) * MM_PER_FT
    if cfg.get("lengthIn") not in (None, ""):
        return _f(cfg.get("lengthIn")) * MM_PER_IN
    if cfg.get("lengthM") not in (None, ""):
        return _f(cfg.get("lengthM")) * MM_PER_M
    return 0.0


def _height_mm(cfg: Mapping[str, Any]) -> float:
    if cfg.get("heightMm") not in (None, ""):
        return _f(cfg.get("heightMm"))
    if cfg.get("heightFt") not in (None, ""):
        return _f(cfg.get("heightFt")) * MM_PER_FT
    if cfg.get("heightIn") not in (None, ""):
        return _f(cfg.get("heightIn")) * MM_PER_IN
    return 0.0


def compute_railing(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Compute glass sizing (12 mm gaps + wall deductions), quantities, per-item
    costs, the total and the per-RFT/RMT rate. Pure function; never raises on
    partial input."""
    cfg = dict(cfg or {})
    length_mm = _length_mm(cfg)
    height_mm = _height_mm(cfg)
    gap = _f(cfg.get("gapMm"), 12.0)
    wall_gap = _f(cfg.get("wallGapMm"), 12.0)
    wall_left = bool(cfg.get("wallLeft", True))
    wall_right = bool(cfg.get("wallRight", True))
    sale_unit = str(cfg.get("saleUnit") or "rft").lower()
    if sale_unit not in ("rft", "rmt"):
        sale_unit = "rft"

    rates = dict(cfg.get("rates") or {})
    r_glass = _f(rates.get("glassPerSqft"), 200.0)
    r_block = _f(rates.get("blockPerPc"), 100.0)
    r_anchor = _f(rates.get("anchorPerPc"), 50.0)
    r_brail = _f(rates.get("bottomRailPerUnit"))
    w_brail = _f(rates.get("bottomRailWeightPerUnit"))
    r_hrail = _f(rates.get("handrailPerUnit"))
    w_hrail = _f(rates.get("handrailWeightPerUnit"))
    r_wall = _f(rates.get("wallConnectorPerPc"))

    # ── glass panels + 12mm gaps + wall deductions ──────────────────────────
    explicit = cfg.get("panelSizesMm")
    if isinstance(explicit, (list, tuple)) and explicit:
        panel_widths = [max(_f(x), 0.0) for x in explicit if _f(x) > 0]
        panel_count = len(panel_widths)
    else:
        panel_count = max(_i(cfg.get("panels"), 1), 1)
        gaps_total = (wall_gap if wall_left else 0.0) + (wall_gap if wall_right else 0.0) + gap * max(panel_count - 1, 0)
        glass_total = max(length_mm - gaps_total, 0.0)
        each = glass_total / panel_count if panel_count else 0.0
        panel_widths = [each] * panel_count

    panel_widths_in = [round(w / MM_PER_IN, 2) for w in panel_widths]

    glass_area_sqmm = sum(w * height_mm for w in panel_widths)
    glass_area_sqft = glass_area_sqmm / SQMM_PER_SQFT
    glass_area_sqm = glass_area_sqmm / SQMM_PER_SQM

    # ── pillars / blocks + anchors ──────────────────────────────────────────
    blocks_per_glass = max(_i(cfg.get("blocksPerGlass"), 0), 0)
    pillar_count = blocks_per_glass * panel_count
    anchors_per_pillar = min(max(_i(cfg.get("anchorsPerPillar"), 1), 1), 2) if pillar_count else 0
    pillar_anchors = pillar_count * anchors_per_pillar

    length_rft = length_mm / MM_PER_FT if length_mm else 0.0
    length_rmt = length_mm / MM_PER_M if length_mm else 0.0
    width_unit = length_rft if sale_unit == "rft" else length_rmt

    anchors_per_rft = _f(cfg.get("anchorsPerRft"), 0.0)
    include_base = bool(cfg.get("includeBaseAnchors", False))
    base_anchors = math.ceil(length_rft * anchors_per_rft) if (include_base and anchors_per_rft) else 0
    # Faithful to the worked example: when pillars exist they carry the anchoring
    # (base anchors are only added when the user explicitly opts in).
    anchor_count = pillar_anchors + base_anchors
    if anchor_count == 0 and not pillar_count:
        # No pillars → fall back to the "1 anchor per RFT" base rule.
        anchor_count = math.ceil(length_rft * (anchors_per_rft or 1.0))

    # ── rails ────────────────────────────────────────────────────────────────
    rail_unit_len = width_unit  # rail runs the full width in the sale unit
    handrail_on = bool(cfg.get("handrail"))
    wall_connectors = 2 if (wall_left and wall_right) else 0

    items: list[dict[str, Any]] = []

    def add(key: str, label: str, qty: float, unit: str, rate: float, weight: float | None = None) -> None:
        amount = round(qty * rate, 2)
        row = {"key": key, "label": label, "qty": round(qty, 3), "unit": unit, "rate": round(rate, 3), "amount": amount}
        if weight is not None:
            row["weightKg"] = round(weight, 3)
        items.append(row)

    add("glass", "Glass", round(glass_area_sqft, 3), "sqft", r_glass)
    if pillar_count:
        add("blocks", f"Blocks / pillars ({cfg.get('pillarType') or 'block'})", pillar_count, "pc", r_block)
    if anchor_count:
        add("anchors", "Anchor bolts", anchor_count, "pc", r_anchor)
    if r_brail:
        add("bottomRail", "Bottom rail", round(rail_unit_len, 3), sale_unit, r_brail,
            weight=rail_unit_len * w_brail if w_brail else None)
    if handrail_on and r_hrail:
        add("handrail", "Handrail", round(rail_unit_len, 3), sale_unit, r_hrail,
            weight=rail_unit_len * w_hrail if w_hrail else None)
    if wall_connectors and r_wall:
        add("wallConnector", "Wall connector", wall_connectors, "pc", r_wall)

    extras_in = cfg.get("extras") if isinstance(cfg.get("extras"), (list, tuple)) else []
    extras: list[dict[str, Any]] = []
    extras_total = 0.0
    for ex in extras_in:
        if not isinstance(ex, Mapping):
            continue
        amt = _f(ex.get("amount"))
        nm = str(ex.get("name") or "Extra")
        extras.append({"name": nm, "amount": round(amt, 2)})
        extras_total += amt

    items_total = sum(float(it["amount"]) for it in items)
    total = round(items_total + extras_total, 2)
    per_unit_rate = round(total / width_unit, 2) if width_unit else 0.0

    manual = cfg.get("manualRatePerUnit")
    manual_rate = _f(manual) if manual not in (None, "") else None
    selling_per_unit = manual_rate if manual_rate is not None else per_unit_rate
    selling_total = round(selling_per_unit * width_unit, 2) if width_unit else round(total, 2)

    geometry = _railing_geometry(
        length_mm=length_mm, height_mm=height_mm, panel_widths=panel_widths,
        gap=gap, wall_gap=wall_gap, wall_left=wall_left, wall_right=wall_right,
        blocks_per_glass=blocks_per_glass, handrail=handrail_on,
        shape=str(cfg.get("shape") or "straight"),
    )

    return {
        "lengthMm": round(length_mm, 2), "heightMm": round(height_mm, 2),
        "lengthRft": round(length_rft, 3), "lengthRmt": round(length_rmt, 3),
        "saleUnit": sale_unit, "widthUnit": round(width_unit, 3),
        "panelCount": panel_count, "gapMm": gap, "wallGapMm": wall_gap,
        "panelWidthsMm": [round(w, 1) for w in panel_widths],
        "panelWidthsIn": panel_widths_in,
        "glassAreaSqft": round(glass_area_sqft, 3), "glassAreaSqm": round(glass_area_sqm, 4),
        "pillarCount": pillar_count, "anchorsPerPillar": anchors_per_pillar,
        "anchorCount": anchor_count, "baseAnchorCount": base_anchors,
        "handrail": handrail_on, "wallConnectors": wall_connectors,
        "items": items, "extras": extras, "extrasTotal": round(extras_total, 2),
        "total": total, "perUnitRate": per_unit_rate,
        "manualRatePerUnit": manual_rate,
        "sellingPerUnit": round(selling_per_unit, 2), "sellingTotal": selling_total,
        "geometry": geometry,
    }


# ── 2D designer geometry + SVG ───────────────────────────────────────────────

def _railing_geometry(
    *, length_mm: float, height_mm: float, panel_widths: list[float],
    gap: float, wall_gap: float, wall_left: bool, wall_right: bool,
    blocks_per_glass: int, handrail: bool, shape: str,
) -> dict[str, Any]:
    """Neutral geometry (mm, origin bottom-left) for the 2D railing elevation."""
    rail_h = max(min(height_mm * 0.06, 60.0), 25.0)  # bottom rail band height
    hand_h = rail_h if handrail else 0.0
    post_w = max(min(length_mm * 0.01, 40.0), 18.0)

    panels: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    x = wall_gap if wall_left else 0.0
    glass_y0 = rail_h
    glass_y1 = height_mm - hand_h
    for i, w in enumerate(panel_widths):
        gx0, gx1 = x, x + w
        panels.append({"index": i, "x0": round(gx0, 1), "y0": round(glass_y0, 1),
                       "x1": round(gx1, 1), "y1": round(glass_y1, 1), "wMm": round(w, 1)})
        if blocks_per_glass > 0:
            for b in range(blocks_per_glass):
                bx = gx0 + (w * (b + 1) / (blocks_per_glass + 1))
                bw = post_w
                blocks.append({"x0": round(bx - bw / 2, 1), "y0": 0.0,
                               "x1": round(bx + bw / 2, 1), "y1": round(rail_h * 1.4, 1)})
        x = gx1 + gap
    return {
        "lengthMm": round(length_mm, 1), "heightMm": round(height_mm, 1),
        "railH": round(rail_h, 1), "handH": round(hand_h, 1), "postW": round(post_w, 1),
        "handrail": handrail, "shape": shape,
        "wallLeft": wall_left, "wallRight": wall_right, "gap": gap, "wallGap": wall_gap,
        "panels": panels, "blocks": blocks,
    }


def railing_svg(cfg: Mapping[str, Any], *, quote: Mapping[str, Any] | None = None) -> str:
    """Clean 2D railing elevation SVG (sleek strokes, dimensions marked).

    Consistent with the rest of WEOS: thin outlines, light glass tint, red
    dimension lines. Embeddable as vector in the PDF (svglib) and shown live.
    """
    q = quote if isinstance(quote, Mapping) else compute_railing(cfg)
    g = q.get("geometry") or {}
    L = _f(g.get("lengthMm")) or 1.0
    Hgt = _f(g.get("heightMm")) or 1.0
    rail_h = _f(g.get("railH"))
    hand_h = _f(g.get("handH"))
    post_w = _f(g.get("postW"))
    panels = g.get("panels") or []
    blocks = g.get("blocks") or []

    pad = max(L, Hgt) * 0.16 + 120.0
    vb_w = L + pad * 2
    vb_h = Hgt + pad * 2
    ox, oy = pad, pad

    def X(mx: float) -> float:
        return ox + mx

    def Y(my: float) -> float:  # flip Y (mm origin bottom-left → svg top-left)
        return oy + (Hgt - my)

    sw = max(L, Hgt) / 500.0
    stroke = "#14181c"
    glass = "#e6eef6"
    glass_stroke = "#2f6db0"
    dim = "#8c1f18"
    fs = max(vb_w, vb_h) * 0.018

    p: list[str] = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.1f} {vb_h:.1f}" font-family="Segoe UI, Arial, sans-serif">')
    p.append(f'<rect x="0" y="0" width="{vb_w:.1f}" height="{vb_h:.1f}" fill="#ffffff"/>')

    # Bottom rail band
    p.append(f'<rect x="{X(0):.1f}" y="{Y(rail_h):.1f}" width="{L:.1f}" height="{rail_h:.1f}" '
             f'fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>')
    # Handrail band
    if hand_h > 0:
        p.append(f'<rect x="{X(0):.1f}" y="{Y(Hgt):.1f}" width="{L:.1f}" height="{hand_h:.1f}" '
                 f'fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>')
    # End posts
    for px in (0.0, L - post_w):
        p.append(f'<rect x="{X(px):.1f}" y="{Y(Hgt):.1f}" width="{post_w:.1f}" height="{Hgt:.1f}" '
                 f'fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>')

    # Glass panels
    for pl in panels:
        gx0, gy0, gx1, gy1 = _f(pl.get("x0")), _f(pl.get("y0")), _f(pl.get("x1")), _f(pl.get("y1"))
        p.append(f'<rect x="{X(gx0):.1f}" y="{Y(gy1):.1f}" width="{(gx1-gx0):.1f}" height="{(gy1-gy0):.1f}" '
                 f'fill="{glass}" stroke="{glass_stroke}" stroke-width="{sw*0.8:.2f}"/>')
        cx = (gx0 + gx1) / 2
        cy = (gy0 + gy1) / 2
        p.append(f'<text x="{X(cx):.1f}" y="{Y(cy):.1f}" text-anchor="middle" font-size="{fs:.1f}" fill="#173a63">'
                 f'G{int(pl.get("index",0))+1}</text>')
        # panel width dimension (below panel)
        _dim_h(p, X(gx0), X(gx1), Y(0) + fs * 1.6, f'{(gx1-gx0):.0f}', dim, sw, fs)

    # Blocks / pillars
    for b in blocks:
        bx0, by0, bx1, by1 = _f(b.get("x0")), _f(b.get("y0")), _f(b.get("x1")), _f(b.get("y1"))
        p.append(f'<rect x="{X(bx0):.1f}" y="{Y(by1):.1f}" width="{(bx1-bx0):.1f}" height="{(by1-by0):.1f}" '
                 f'fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>')

    # Overall dimensions
    _dim_h(p, X(0), X(L), Y(0) + fs * 3.4, f'{L:.0f} mm  ·  {q.get("lengthRft")} RFT', dim, sw, fs)
    _dim_v(p, Y(0), Y(Hgt), X(0) - fs * 1.6, f'{Hgt:.0f}', dim, sw, fs)

    # Title / summary
    summ = f'Railing · {q.get("panelCount")} panels · gap {int(_f(g.get("gap")))}mm · {q.get("glassAreaSqft")} sft'
    p.append(f'<text x="{X(0):.1f}" y="{oy - fs*0.6:.1f}" font-size="{fs*1.05:.1f}" fill="#111">{escape(summ)}</text>')
    p.append('</svg>')
    return "".join(p)


def _dim_h(p: list[str], x0: float, x1: float, y: float, text: str, dim: str, sw: float, fs: float) -> None:
    p.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" stroke="{dim}" stroke-width="{sw*0.7:.2f}"/>')
    for xx in (x0, x1):
        p.append(f'<line x1="{xx:.1f}" y1="{y-fs*0.4:.1f}" x2="{xx:.1f}" y2="{y+fs*0.4:.1f}" stroke="{dim}" stroke-width="{sw*0.7:.2f}"/>')
    p.append(f'<text x="{(x0+x1)/2:.1f}" y="{y-fs*0.5:.1f}" text-anchor="middle" font-size="{fs:.1f}" fill="{dim}">{escape(text)}</text>')


def _dim_v(p: list[str], y0: float, y1: float, x: float, text: str, dim: str, sw: float, fs: float) -> None:
    ylo, yhi = min(y0, y1), max(y0, y1)
    p.append(f'<line x1="{x:.1f}" y1="{ylo:.1f}" x2="{x:.1f}" y2="{yhi:.1f}" stroke="{dim}" stroke-width="{sw*0.7:.2f}"/>')
    for yy in (ylo, yhi):
        p.append(f'<line x1="{x-fs*0.4:.1f}" y1="{yy:.1f}" x2="{x+fs*0.4:.1f}" y2="{yy:.1f}" stroke="{dim}" stroke-width="{sw*0.7:.2f}"/>')
    cy = (ylo + yhi) / 2
    p.append(f'<text x="{x:.1f}" y="{cy:.1f}" text-anchor="middle" font-size="{fs:.1f}" fill="{dim}" '
             f'transform="rotate(-90 {x:.1f} {cy:.1f})">{escape(text)}</text>')
