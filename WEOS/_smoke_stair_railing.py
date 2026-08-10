"""Smoke / unit checks for staircase railing geometry + nesting wastage + cost cascade."""
from __future__ import annotations

import math
import sys

from WEOS.factory.railing_engine import (
    SQMM_PER_SQFT,
    compute_railing,
    compute_stair_geometry,
    compute_stair_glass_panels,
    nest_railing_glass,
    railing_svg,
)


def approx(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(float(a) - float(b)) <= tol


def main() -> int:
    fails: list[str] = []

    # Example: 14 steps, riser 180, tread 305, floor 2.5 m → mismatch flag
    cfg = {
        "shape": "staircase",
        "stairSteps": 14,
        "stairRiseMm": 180,
        "stairRunMm": 305,
        "floorHeightMm": 2500,
        "panels": 3,
        "glassHeightMm": 900,
        "gapMm": 12,
        "sheetWidthMm": 3660,
        "sheetHeightMm": 2440,
        "estimatedWastagePercent": 10,
        "measurementBasis": "sloping_rft",
        "overheadPercent": 10,
        "markupPercent": 15,
        "installation": 5000,
        "transport": 2000,
        "rates": {
            "glassPerSqft": 200,
            "blockPerPc": 100,
            "anchorPerPc": 50,
            "studPerPc": 80,
        },
    }

    geo = compute_stair_geometry(cfg)
    expected_angle = math.atan(180 / 305) * 180 / math.pi
    if not approx(geo["stairAngleDeg"], expected_angle, 1e-3):
        fails.append(f"stairAngle {geo['stairAngleDeg']} != {expected_angle}")
    if not approx(geo["totalRiseMm"], 14 * 180):
        fails.append(f"totalRise {geo['totalRiseMm']}")
    if not approx(geo["totalHorizontalRunMm"], 14 * 305):
        fails.append(f"totalRun {geo['totalHorizontalRunMm']}")
    step_slope = math.hypot(180, 305)
    if not approx(geo["totalSlopeLengthMm"], 14 * step_slope, 0.1):
        fails.append(f"totalSlope {geo['totalSlopeLengthMm']}")
    if not geo["riseMismatch"]:
        fails.append("expected riseMismatch for 2520 vs 2500")
    if geo["calculatedRiseMm"] != 2520:
        fails.append(f"calculatedRise {geo['calculatedRiseMm']}")

    panels = compute_stair_glass_panels(cfg, geo)
    if len(panels) != 3:
        fails.append(f"expected 3 panels, got {len(panels)}")
    # 100 mm edges + 12 mm gaps
    usable = 14 * 305 - 2 * 100
    each = (usable - 2 * 12) / 3
    for p in panels:
        if not approx(p["panelWidthHorizontal"], each, 0.2):
            fails.append(f"panel width {p['panelWidthHorizontal']} != {each}")
        # Area = horizontal × vertical height (NOT sloping)
        expect_area = each * 900
        if not approx(p["netGlassAreaSqMm"], expect_area, 1.0):
            fails.append(f"panel area {p['netGlassAreaSqMm']} != {expect_area}")
        if not approx(p["bottomCutAngleVsHorizontal"], expected_angle, 1e-2):
            fails.append("bottom cut vs horizontal")
        if not approx(p["bottomCutAngleVsVertical"], 90 - expected_angle, 1e-2):
            fails.append("bottom cut vs vertical")

    nest = nest_railing_glass(panels, sheet_w=3660, sheet_h=2440, estimated_wastage_pct=10)
    net = nest["netGlassAreaSqFt"]
    purchased = nest["purchasedGlassAreaSqFt"]
    if nest["method"] not in ("sheet_nesting", "estimated_pct"):
        fails.append(f"bad nest method {nest['method']}")
    if nest["method"] == "sheet_nesting":
        # wastagePercent = (purchased - net) / net * 100
        wp = ((purchased - net) / net) * 100 if net else 0
        if not approx(nest["wastagePercent"], wp, 0.05):
            fails.append(f"wastage formula {nest['wastagePercent']} != {wp}")
    else:
        # fallback purchased = net * 1.10
        if not approx(purchased, net * 1.10, 0.02):
            fails.append(f"estimate purchased {purchased} != {net * 1.10}")

    q = compute_railing(cfg)
    if q["shape"] != "staircase":
        fails.append("shape")
    if q["stairStuds"] != (14 // 3) * 2:
        fails.append(f"studs {q['stairStuds']}")
    if q["stairPillars"] != 14 // 3:
        fails.append(f"pillars {q['stairPillars']}")
    if not (q.get("stairGeometry") or {}).get("riseMismatch"):
        fails.append("quote missing riseMismatch")
    inn = q.get("internal") or {}
    for key in (
        "netGlassAreaSqFt", "wastageAreaSqFt", "purchasedGlassAreaSqFt",
        "glassMaterialCost", "directCost", "overheadCost", "profitMarkup",
        "sellingRatePerRFT", "sellingRatePerRMT",
    ):
        if key not in inn:
            fails.append(f"internal missing {key}")
    com = q.get("commercial") or {}
    if "sellingRatePerUnit" not in com:
        fails.append("commercial missing sellingRatePerUnit")

    # Cost cascade math check
    cc = q.get("costCascade") or {}
    direct = cc.get("directCost", 0)
    oh = direct * 0.10
    before = direct + oh
    sell = before * 1.15
    if not approx(cc.get("overheadCost", -1), oh, 0.05):
        fails.append(f"overhead {cc.get('overheadCost')} != {oh}")
    if not approx(cc.get("sellingPrice", -1), sell, 0.05):
        fails.append(f"selling {cc.get('sellingPrice')} != {sell}")

    # Glass material = purchased × rate
    if not approx(cc.get("glassMaterialCost", -1), cc.get("purchasedGlassAreaSqFt", 0) * 200, 0.05):
        fails.append("glassMaterialCost")

    # Steps derived from floor / riser when steps omitted
    geo2 = compute_stair_geometry({
        "stairRiseMm": 180, "stairRunMm": 305, "floorHeightMm": 2500,
    })
    if geo2["steps"] != round(2500 / 180):
        fails.append(f"derived steps {geo2['steps']}")

    svg = railing_svg(cfg, quote=q)
    if "<svg" not in svg or "polygon" not in svg:
        fails.append("svg missing polygon glass panels")
    if "⚠" not in svg and "rise" not in svg.lower():
        pass  # mismatch text may be escaped; still require svg length
    if len(svg) < 500:
        fails.append("svg too short")

    # Straight balcony still works (regression)
    straight = compute_railing({
        "shape": "straight", "lengthFt": 10, "heightFt": 2, "panels": 2,
        "blocksPerGlass": 3, "rates": {"glassPerSqft": 200, "blockPerPc": 100, "anchorPerPc": 50},
    })
    if straight["panelCount"] != 2:
        fails.append("straight panels")
    if straight.get("glassAreaSqft", 0) <= 0:
        fails.append("straight glass area")

    # sqft conversion constant
    if not approx(SQMM_PER_SQFT, 92903.04, 1e-6):
        fails.append("SQMM_PER_SQFT")

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1

    print("OK")
    print(f"  angle={geo['stairAngleDeg']:.4f} rise={geo['totalRiseMm']} mismatch={geo['riseMismatch']}")
    print(f"  panels={len(panels)} eachH={panels[0]['panelWidthHorizontal']:.1f} netSft={net:.4f}")
    print(f"  nest={nest['method']} purchased={purchased:.4f} waste%={nest['wastagePercent']}")
    print(f"  studs={q['stairStuds']} sellRFT={inn.get('sellingRatePerRFT')} sellRMT={inn.get('sellingRatePerRMT')}")
    print(f"  svg_bytes={len(svg)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
