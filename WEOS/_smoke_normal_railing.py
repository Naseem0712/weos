"""Smoke checks: normal (non-stair) railing — zero wastage, multi-span L/U BOM, cascade."""
from __future__ import annotations

import sys

from WEOS.factory.railing_engine import compute_railing, railing_svg
from WEOS.factory.railing_materials import seed_default_materials, rates_from_selections


def approx(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(float(a) - float(b)) <= tol


def main() -> int:
    fails: list[str] = []
    seed_default_materials(force=False)

    # U-shape with per-span panels — no wastage
    cfg = {
        "shape": "U",
        "legAMm": 2500,
        "legBMm": 4000,
        "legCMm": 2500,
        "heightMm": 1000,
        "gapMm": 12,
        "wallStart": True,
        "wallEnd": True,
        "handrail": True,
        "blocksPerGlass": 2,
        "anchorsPerPillar": 2,
        "mountType": "side_mount",
        "measurementBasis": "horizontal_rft",
        "overheadPercent": 10,
        "markupPercent": 15,
        "installation": 3000,
        "transport": 1500,
        "spans": [
            {"panels": 4, "blocksPerGlass": 2, "label": "Span A", "lengthMm": 2500},
            {"panels": 3, "blocksPerGlass": 2, "label": "Span B", "lengthMm": 4000},
            {"panels": 4, "blocksPerGlass": 2, "label": "Span C", "lengthMm": 2500},
        ],
        "materialSelections": {
            "bottom_rail": "rm_bottom_rail_50x10_316_black",
            "handrail": "rm_handrail_38_round_316_4753",
            "block": "rm_block_side_50_316",
            "anchor": "rm_anchor_m10",
            "bend": "rm_bend_90_38_316",
            "end_cap": "rm_end_cap_38_316",
            "wall_connector": "rm_wall_conn_38_316",
        },
        "rates": {"glassPerSqft": 200},
    }

    q = compute_railing(cfg)
    if q["shape"] != "U":
        fails.append(f"shape {q['shape']}")
    if q["panelCount"] != 11:
        fails.append(f"panels {q['panelCount']} != 11")
    if q.get("wastagePercent") not in (0, 0.0):
        fails.append(f"wastage {q.get('wastagePercent')} != 0")
    if q.get("wastageEnabled") is not False:
        fails.append("wastageEnabled should be False for normal")
    if not approx(q["netGlassAreaSqFt"], q["purchasedGlassAreaSqFt"], 1e-6):
        fails.append("purchased != net for normal railing")
    nest = q.get("glassNesting") or {}
    if nest.get("method") != "no_wastage":
        fails.append(f"nest method {nest.get('method')}")
    if not nest.get("nestingSkipped"):
        fails.append("nesting should be skipped")

    # Pillars = blocksPerGlass × panels
    if q["pillarCount"] != 2 * 11:
        fails.append(f"pillars {q['pillarCount']} != 22")
    # U has 2 bends
    if q["bendCount"] != 2:
        fails.append(f"bends {q['bendCount']}")
    # Wall both ends → 2 wall connectors, 0 end caps
    if q["wallConnectors"] != 2:
        fails.append(f"wallConnectors {q['wallConnectors']}")
    if q["endCapCount"] != 0:
        fails.append(f"endCaps {q['endCapCount']}")

    segs = q.get("segments") or []
    if len(segs) != 3:
        fails.append(f"segments {len(segs)}")
    else:
        if segs[0].get("panelStartIndex") != 1:
            fails.append("span A panel start")
        if segs[1].get("panelStartIndex") != 5:
            fails.append(f"span B start {segs[1].get('panelStartIndex')}")
        if segs[2].get("panelStartIndex") != 8:
            fails.append(f"span C start {segs[2].get('panelStartIndex')}")

    keys = {it["key"] for it in q.get("items") or []}
    for need in ("glass", "blocks", "anchors", "handrail", "modularBend", "wallConnector"):
        if need not in keys:
            fails.append(f"BOM missing {need}")

    bom = q.get("bomDetails") or []
    if not bom:
        fails.append("bomDetails empty")
    else:
        block_row = next((b for b in bom if b.get("key") == "blocks"), None)
        if not block_row or not block_row.get("color"):
            fails.append("block BOM missing color/grade meta")

    inn = q.get("internal") or {}
    if inn.get("nestingSkipped") is not True:
        fails.append("internal nestingSkipped")
    cc = q.get("costCascade") or {}
    if not approx(cc.get("glassMaterialCost", -1), cc.get("purchasedGlassAreaSqFt", 0) * 200, 0.05):
        fails.append("glassMaterialCost cascade")
    direct = cc.get("directCost", 0)
    oh = direct * 0.10
    sell = (direct + oh) * 1.15
    if not approx(cc.get("overheadCost", -1), oh, 0.1):
        fails.append(f"overhead {cc.get('overheadCost')}")
    if not approx(cc.get("sellingPrice", -1), sell, 0.1):
        fails.append(f"selling {cc.get('sellingPrice')}")

    com = q.get("commercial") or {}
    if "sellingRatePerUnit" not in com:
        fails.append("commercial rate missing")

    # Gallery rates applied
    rates = rates_from_selections(cfg["materialSelections"])
    if rates.get("bottomRailPerUnit") != 180:
        fails.append("gallery bottom rail rate")
    if rates.get("handrailPerUnit") != 320:
        fails.append("gallery handrail rate")

    svg = railing_svg(cfg, quote=q)
    if "<svg" not in svg:
        fails.append("svg missing")
    if "Panel #" not in svg and "Panel #" not in svg.lower():
        # shop drawing elevations use Panel #
        if "Span" not in svg:
            fails.append("shop drawing missing span/panel labels")
    if "shop drawing" not in svg.lower() and "Span" not in svg:
        fails.append("expected multi-span shop drawing")
    if len(svg) < 800:
        fails.append("svg too short")

    # L-shape regression
    lq = compute_railing({
        "shape": "L",
        "legAMm": 3000,
        "legBMm": 2000,
        "heightMm": 900,
        "spans": [{"panels": 3}, {"panels": 2}],
        "blocksPerGlass": 2,
        "handrail": True,
        "wallStart": True,
        "wallEnd": False,
        "rates": {"glassPerSqft": 180, "blockPerPc": 90, "endCapPerPc": 40, "modularBendPerPc": 100},
        "overheadPercent": 5,
        "markupPercent": 10,
    })
    if lq["panelCount"] != 5:
        fails.append(f"L panels {lq['panelCount']}")
    if lq["bendCount"] != 1:
        fails.append("L bends")
    if lq["endCapCount"] != 1:
        fails.append("L end caps (open end)")
    if lq.get("wastagePercent") not in (0, 0.0):
        fails.append("L wastage")

    # Straight balcony still zero wastage; stairs still nest
    st = compute_railing({
        "shape": "straight", "lengthMm": 3048, "heightMm": 900,
        "panels": 2, "blocksPerGlass": 2,
        "rates": {"glassPerSqft": 200, "blockPerPc": 100, "anchorPerPc": 50},
        "overheadPercent": 10, "markupPercent": 15,
    })
    if not approx(st["netGlassAreaSqFt"], st["purchasedGlassAreaSqFt"]):
        fails.append("straight purchased!=net")
    if st.get("glassNesting", {}).get("method") != "no_wastage":
        fails.append("straight should skip nesting")

    stair = compute_railing({
        "shape": "staircase",
        "stairSteps": 12,
        "stairRiseMm": 180,
        "stairRunMm": 305,
        "panels": 3,
        "glassHeightMm": 900,
        "estimatedWastagePercent": 10,
        "rates": {"glassPerSqft": 200, "blockPerPc": 100, "anchorPerPc": 50, "studPerPc": 80},
        "overheadPercent": 10,
        "markupPercent": 15,
    })
    if stair.get("wastageEnabled") is not True:
        fails.append("stairs must keep wastage path")
    if stair.get("glassNesting", {}).get("method") not in ("sheet_nesting", "estimated_pct"):
        fails.append(f"stair nest method {stair.get('glassNesting', {}).get('method')}")

    jog = compute_railing({
        "runs": [
            {"lengthMm": 2000, "panels": 2, "turn": "left", "turnDeg": 90, "glassHeightMm": 1000},
            {"lengthMm": 1500, "panels": 2, "turn": "right", "turnDeg": 90, "glassHeightMm": 1000},
            {"lengthMm": 1800, "panels": 2, "glassHeightMm": 1000},
        ],
        "heightMm": 1000,
        "handrail": True,
        "bottomKind": "continuous",
        "rates": {
            "glassPerSqft": 200, "bottomRailPerUnit": 80, "handrailPerUnit": 120,
            "modularBendPerPc": 50,
        },
    })
    if jog.get("shape") not in ("polyline", "straight"):
        fails.append(f"jog shape {jog.get('shape')}")
    if int(jog.get("bendCount") or 0) != 2:
        fails.append(f"jog 90° bands {jog.get('bendCount')}")
    if int(jog.get("panelCount") or 0) != 6:
        fails.append(f"jog panels {jog.get('panelCount')}")
    keys = {it["key"] for it in (jog.get("items") or [])}
    if "modularBend" not in keys:
        fails.append("jog missing Modular band")
    jsvg = railing_svg({"runs": jog.get("runs"), "heightMm": 1000}, quote=jog)
    if "90° L" not in jsvg and "90°" not in jsvg:
        fails.append("jog svg missing 90° L/R labels")

    back = compute_railing({
        "runs": [
            {"lengthMm": 3000, "panels": 2, "turn": "left", "turnDeg": 180, "glassHeightMm": 1000},
            {"lengthMm": 3000, "panels": 2, "glassHeightMm": 1000},
        ],
        "heightMm": 1000,
        "handrail": True,
        "bottomKind": "continuous",
        "rates": {"glassPerSqft": 200, "bottomRailPerUnit": 80, "handrailPerUnit": 120},
    })
    if int(back.get("bendCount") or 0) != 0:
        fails.append(f"180° should not count as modular band {back.get('bendCount')}")
    if int(back.get("connector180Count") or 0) < 1:
        fails.append("180° band qty")

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1

    print("OK")
    print(f"  U panels={q['panelCount']} pillars={q['pillarCount']} bends={q['bendCount']}")
    print(f"  net={q['netGlassAreaSqFt']} purchased={q['purchasedGlassAreaSqFt']} waste%={q['wastagePercent']}")
    print(f"  sellRFT={inn.get('sellingRatePerRFT')} commercial={com.get('sellingRatePerUnit')}/{com.get('saleUnit')}")
    print(f"  bom_lines={len(bom)} svg_bytes={len(svg)}")
    print(f"  stair_nest={stair.get('glassNesting', {}).get('method')} stair_waste%={stair.get('wastagePercent')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
