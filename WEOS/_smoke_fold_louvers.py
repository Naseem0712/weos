"""Smoke: fold & sliding with louvers fill → canvas SVG + PDF specs (no window track mix)."""
from __future__ import annotations

import sys

from WEOS.factory.marqt_pdf import _spec_lines
from WEOS.factory.panel_fills import (
    compute_louver_layout,
    normalize_panel_fill,
    panel_fill_from_line,
)
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.svg_export import elevation_svg_for_line


def main() -> int:
    fails: list[str] = []
    fill = normalize_panel_fill({
        "fillType": "louvers",
        "orientation": "horizontal",
        "gapMm": 25,
        "bladeWidthMm": 50,
        "bladeDepthMm": 70,
        "bladeThicknessMm": 3,
    })
    layout = compute_louver_layout(x0=0, y0=0, x1=800, y1=2000, fill=fill)
    if layout.get("bladeCount", 0) < 2:
        fails.append(f"expected multiple blades, got {layout.get('bladeCount')}")
    if not layout.get("gaps"):
        fails.append("no gaps marked")
    if abs(float(layout["gaps"][0]["gapMm"]) - 25) > 0.01:
        fails.append("gap not 25")

    cart = {
        "product": "29mm_sliding",
        "productType": "fold",
        "displayName": "Fold & Sliding · louvers",
        "width": 3600,
        "height": 2400,
        "qty": 1,
        "system": "bifold",
        "foldLeft": 3,
        "foldRight": 1,
        "colour": "black_texture",
        "panelFill": fill,
        "options": {"system": "bifold", "foldLeft": 3, "foldRight": 1, "panelFill": fill},
    }
    pf = panel_fill_from_line(cart)
    if pf.get("fillType") != "louvers":
        fails.append(f"fill resolve {pf}")

    result = calculate_line(cart)
    opts = result.get("options") or {}
    if not isinstance(opts.get("panelFill"), dict):
        fails.append("panelFill not persisted on calculate")
    svg = (result.get("preview") or {}).get("svg") or ""
    if "<svg" not in svg:
        fails.append("no preview svg")
    if "Louvers" not in svg and "gap" not in svg.lower():
        fails.append("louver annotations missing from canvas svg")

    elev = elevation_svg_for_line(result, style="pdf") or ""
    if "<svg" not in elev:
        fails.append("pdf elevation empty")
    if "25" not in elev and "gap" not in elev.lower():
        fails.append("gap marks missing on PDF elevation")

    specs = _spec_lines(result)
    if not any("Louver" in s or "Panel fill" in s for s in specs):
        fails.append(f"specs missing louvers: {specs[:6]}")
    # Fold must not print sliding track when bifold
    if any(s.startswith("Track =") or "2-track" in s for s in specs):
        fails.append(f"fold line leaked track specs: {specs}")

    # Vertical louvers path
    vfill = normalize_panel_fill({**fill, "orientation": "vertical", "gapMm": 15})
    vlayout = compute_louver_layout(x0=0, y0=0, x1=1000, y1=1200, fill=vfill)
    if vlayout.get("orientation") != "vertical":
        fails.append("vertical orient")
    if not vlayout.get("gaps"):
        fails.append("vertical gaps empty")

    # Complex pattern: varying gaps + stagger + round
    cfill = normalize_panel_fill({
        "fillType": "louvers",
        "orientation": "vertical",
        "patternMode": "repeat",
        "pattern": [
            {"shape": "round", "sizeMm": 40, "gapAfterMm": 15, "depthOffsetMm": 0},
            {"shape": "rect", "sizeMm": 50, "depthMm": 70, "gapAfterMm": 40, "depthOffsetMm": 25},
        ],
    })
    clayout = compute_louver_layout(x0=0, y0=0, x1=900, y1=1800, fill=cfill)
    if clayout.get("bladeCount", 0) < 2:
        fails.append("complex pattern blade count")
    if not any(b.get("shape") == "round" for b in clayout.get("blades") or []):
        fails.append("round pipe missing")
    gap_vals = {float(g.get("gapMm") or 0) for g in clayout.get("gaps") or []}
    if 15 not in gap_vals or 40 not in gap_vals:
        fails.append(f"varying gaps missing: {gap_vals}")

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print(
        f"OK fold+louvers smoke · blades={layout.get('bladeCount')} "
        f"gaps={len(layout.get('gaps') or [])} pattern={clayout.get('bladeCount')} "
        f"svg={len(svg)} elev={len(elev)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
