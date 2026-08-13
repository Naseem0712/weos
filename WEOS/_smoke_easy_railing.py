"""Smoke: easy railing wizard configs — continuous / block / stairs mounts."""
from __future__ import annotations

from WEOS.factory.marqt_pdf import _spec_lines
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.railing_engine import (
    PILLAR_EDGE_MM,
    _pillar_positions_along,
    compute_railing,
    railing_svg,
)


def main() -> int:
    fails: list[str] = []

    # 1) Normal continuous rail — size+rate feed BOM
    cont = compute_railing({
        "shape": "straight",
        "lengthMm": 3000,
        "heightMm": 1000,
        "panels": 2,
        "bottomKind": "continuous",
        "bottomSize": "50x10",
        "handrailSize": "Ø38",
        "continuousRail": True,
        "handrail": True,
        "installComponents": {
            "bottomRail": True, "block": False, "ssPillar": False,
            "handrail": True, "glass": True,
        },
        "rates": {
            "glassPerSqft": 200, "bottomRailPerUnit": 80, "handrailPerUnit": 120,
        },
        "manualRatePerUnit": 450,
    })
    keys = {it["key"] for it in cont.get("items") or []}
    if "bottomRail" not in keys:
        fails.append("continuous missing bottomRail BOM")
    if "blocks" in keys:
        fails.append("continuous should not BOM blocks")
    if "studs" in keys:
        fails.append("continuous should not BOM studs")
    if "anchors" not in keys:
        fails.append("continuous should BOM spaced anchors (1/2 ft + 100 mm inset)")
    # 3000 mm · default 2 ft spacing → 1 + floor((3000-200)/609.6) = 5
    if int(cont.get("anchorCount") or 0) != 5:
        fails.append(f"continuous default 2ft anchors {cont.get('anchorCount')} != 5")
    if int(cont.get("pillarCount") or 0) != 0:
        fails.append(f"continuous pillarCount {cont.get('pillarCount')}")
    br = next((it for it in (cont.get("items") or []) if it.get("key") == "bottomRail"), {})
    hr = next((it for it in (cont.get("items") or []) if it.get("key") == "handrail"), {})
    if abs(float(br.get("qty") or 0) - float(hr.get("qty") or 0)) > 0.011:
        fails.append(f"continuous handrail qty {hr.get('qty')} != bottom rail {br.get('qty')}")
    if str(br.get("unit") or "").lower() != "rft" or str(hr.get("unit") or "").lower() != "rft":
        fails.append(f"continuous rail units br={br.get('unit')} hr={hr.get('unit')}")
    if abs(float(br.get("lengthMm") or 0) - float(hr.get("lengthMm") or 0)) > 0.5:
        fails.append(f"continuous lengthMm br={br.get('lengthMm')} hr={hr.get('lengthMm')}")
    if "50x10" not in str(br.get("sizeMm") or br.get("label") or "").replace("×", "x"):
        fails.append(f"continuous missing bottom size on BOM {br}")
    if "38" not in str(hr.get("sizeMm") or hr.get("label") or ""):
        fails.append(f"continuous missing handrail size on BOM {hr}")
    csvg = None
    try:
        from WEOS.factory.railing_engine import railing_svg
        csvg = railing_svg({
            "shape": "straight", "lengthMm": 3000, "heightMm": 1000, "panels": 2,
            "bottomKind": "continuous", "bottomSize": "50x10", "handrailSize": "Ø38",
            "continuousRail": True, "handrail": True,
            "installComponents": {"bottomRail": True, "block": False, "ssPillar": False, "handrail": True, "glass": True},
        }, quote=cont)
    except Exception as exc:
        fails.append(f"continuous svg {exc}")
    if csvg:
        if "50x10" not in csvg.replace("×", "x") and "50×10" not in csvg:
            fails.append("continuous svg missing bottom rail size")
        if "Ø38" not in csvg and "38" not in csvg:
            fails.append("continuous svg missing handrail size")
        if "RFT" not in csvg.upper() and "rft" not in csvg.lower():
            fails.append("continuous svg missing RFT length")
    if abs(float(cont.get("sellingPerUnit") or 0) - 450) > 0.01:
        fails.append(f"manual rate not applied: {cont.get('sellingPerUnit')}")
    if cont.get("wastageEnabled") is not False:
        fails.append("normal should disable wastage")
    pos3 = [round(x) for x in _pillar_positions_along(1000.0, 3, edge_mm=PILLAR_EDGE_MM)]
    if pos3 != [100, 500, 900]:
        fails.append(f"3 pillar spacing {pos3} != [100, 500, 900]")
    pos2 = [round(x) for x in _pillar_positions_along(1000.0, 2, edge_mm=PILLAR_EDGE_MM)]
    if pos2 != [100, 900]:
        fails.append(f"2 pillar spacing {pos2} != [100, 900]")
    if csvg and 'data-spigot="1"' in csvg:
        fails.append("continuous svg still draws pillars/spigots")

    # 2) Normal aluminium block
    blk = compute_railing({
        "shape": "straight",
        "lengthMm": 3000,
        "heightMm": 1000,
        "panels": 3,
        "bottomKind": "block",
        "blocksPerGlass": 2,
        "continuousRail": False,
        "installComponents": {
            "bottomRail": False, "block": True, "ssPillar": False,
            "handrail": True, "glass": True,
        },
        "rates": {"glassPerSqft": 200, "blockPerPc": 150, "handrailPerUnit": 100, "anchorPerPc": 40},
        "anchorsPerPillar": 2,
    })
    bk = {it["key"] for it in blk.get("items") or []}
    if "blocks" not in bk:
        fails.append("block path missing blocks BOM")
    if "bottomRail" in bk:
        fails.append("block path should not BOM continuous bottom")
    if int(blk.get("pillarCount") or 0) < 1:
        fails.append(f"block pillarCount {blk.get('pillarCount')}")
    bsvg = railing_svg({
        "shape": "straight", "lengthMm": 3000, "heightMm": 1000, "panels": 3,
        "bottomKind": "block", "blocksPerGlass": 2, "continuousRail": False,
        "handrail": True,
        "installComponents": {
            "bottomRail": False, "block": True, "ssPillar": False,
            "handrail": True, "glass": True,
        },
    }, quote=blk)
    n_spigot = bsvg.count('data-spigot="1"')
    n_bolt = bsvg.count('data-spigot-bolt="1"')
    if n_spigot != 6:
        fails.append(f"block 2/glass x 3 panels spigots {n_spigot} != 6")
    if n_bolt != 24:
        fails.append(f"block spigot 4-hole plates {n_bolt} != 24")
    if 'data-handrail="1"' not in bsvg:
        fails.append("block svg missing solid black handrail")
    if 'data-side-stud="1"' in bsvg:
        fails.append("block svg used studs placement")
    if 'data-bottom-rail="1"' in bsvg:
        fails.append("block svg still draws continuous bottom rail")

    # 3) Normal SS pillar
    ss = compute_railing({
        "shape": "L",
        "legAMm": 2000,
        "legBMm": 1500,
        "heightMm": 1000,
        "panels": 4,
        "bottomKind": "ss_pillar",
        "blocksPerGlass": 2,
        "pillarType": "ss",
        "continuousRail": False,
        "installComponents": {
            "bottomRail": False, "block": False, "ssPillar": True,
            "handrail": True, "glass": True,
        },
        "rates": {"glassPerSqft": 200, "blockPerPc": 220, "handrailPerUnit": 110},
    })
    if ss.get("shape") != "L":
        fails.append("L shape lost")
    if "blocks" not in {it["key"] for it in ss.get("items") or []}:
        fails.append("SS pillar missing blocks BOM")

    # 4) Stairs step-mount · 3 studs/glass
    stair_step = compute_railing({
        "shape": "staircase",
        "floorHeightMm": 2520,
        "stairRiseMm": 180,
        "stairRunMm": 300,
        "glassHeightMm": 900,
        "panels": 4,
        "stairMountType": "step",
        "stairBottomType": "block",
        "studsPerGlass": 3,
        "handrail": True,
        "installComponents": {
            "bottomRail": False, "block": True, "ssPillar": False,
            "handrail": True, "glass": True,
        },
        "rates": {"glassPerSqft": 220, "blockPerPc": 100, "studPerPc": 85, "handrailPerUnit": 130},
        "estimatedWastagePercent": 10,
    })
    if stair_step.get("shape") != "staircase":
        fails.append("stair step shape")
    if int(stair_step.get("studsPerGlass") or 0) != 3:
        fails.append(f"studsPerGlass {stair_step.get('studsPerGlass')}")
    expected_studs = 4 * 3
    if int(stair_step.get("stairStuds") or 0) != expected_studs:
        fails.append(f"step studs {stair_step.get('stairStuds')} != {expected_studs}")
    if not stair_step.get("wastageEnabled"):
        fails.append("stairs should enable wastage")
    if float(stair_step.get("purchasedGlassAreaSqFt") or 0) < float(stair_step.get("netGlassAreaSqFt") or 0) - 0.01:
        fails.append("purchased < net on stairs")

    # 5) Stairs side-mount · 50mm · 4 studs/glass · topiller
    stair_side = compute_railing({
        "shape": "staircase",
        "floorHeightMm": 3350,  # ~11 ft
        "stairRiseMm": 180,
        "stairRunMm": 280,
        "glassHeightMm": 900,
        "panels": 4,
        "stairMountType": "side",
        "stairBottomType": "topiller",
        "studSizeMm": 50,
        "studsPerGlass": 4,
        "handrail": True,
        "installComponents": {
            "bottomRail": False, "block": True, "ssPillar": True,
            "handrail": True, "glass": True,
        },
        "rates": {"glassPerSqft": 250, "blockPerPc": 180, "studPerPc": 95, "handrailPerUnit": 140},
    })
    if int(stair_side.get("studSizeMm") or 0) != 50:
        fails.append(f"stud size {stair_side.get('studSizeMm')}")
    if int(stair_side.get("stairStuds") or 0) != 16:
        fails.append(f"side studs {stair_side.get('stairStuds')} != 16")
    if stair_side.get("stairMountType") != "side":
        fails.append(f"mount {stair_side.get('stairMountType')}")

    # 6) Contaminated cart must not leak window series into PDF specs
    dirty = calculate_line({
        "product": "railing",
        "productType": "staircase_railing",
        "width": 4000,
        "height": 900,
        "qty": 1,
        "sectionSeries": "25mm_eco_gulf",
        "specifications": {"profileSeries": "25mm eco gulf system", "track": "2 track"},
        "options": {
            "railing": {
                "shape": "staircase",
                "floorHeightMm": 2520,
                "stairRiseMm": 180,
                "stairRunMm": 300,
                "glassHeightMm": 900,
                "panels": 4,
                "stairMountType": "step",
                "studsPerGlass": 2,
                "stairBottomType": "block",
                "rates": {"glassPerSqft": 200, "studPerPc": 70, "blockPerPc": 90},
            },
            "productType": "staircase_railing",
        },
    })
    specs = " ".join(_spec_lines(dirty)).lower()
    if "eco gulf" in specs or "2 track" in specs or "profileseries" in specs.replace(" ", ""):
        fails.append(f"series leak in specs: {specs[:200]}")
    if dirty.get("productType") != "staircase_railing":
        fails.append(f"productType {dirty.get('productType')}")
    if dirty.get("sectionSpecs"):
        fails.append("sectionSpecs present on railing")

    # 6b) Normal SS studs bottom — exclusive of block/continuous
    studs = compute_railing({
        "shape": "straight",
        "lengthMm": 3000,
        "heightMm": 1000,
        "panels": 3,
        "bottomKind": "studs",
        "studsPerGlass": 2,
        "continuousRail": False,
        "installComponents": {
            "bottomRail": False, "block": False, "ssPillar": False, "studs": True,
            "handrail": True, "glass": True,
        },
        "rates": {"glassPerSqft": 200, "studPerPc": 90, "handrailPerUnit": 110, "anchorPerPc": 40},
        "manualRatePerUnit": 500,
    })
    sk = {it["key"] for it in studs.get("items") or []}
    if "studs" not in sk:
        fails.append("normal studs missing studs BOM")
    if "bottomRail" in sk:
        fails.append("normal studs should not BOM continuous bottom")
    if "blocks" in sk:
        fails.append("normal studs should not BOM aluminium blocks")
    if abs(float(studs.get("sellingPerUnit") or 0) - 500) > 0.01:
        fails.append(f"studs manual rate {studs.get('sellingPerUnit')}")
    if str(studs.get("bottomKind") or "") != "studs":
        fails.append(f"bottomKind {studs.get('bottomKind')}")
    if studs.get("mountType") != "side_mount":
        fails.append(f"studs mount {studs.get('mountType')} != side_mount")
    if float(studs.get("beamOverlapMm") or 0) < 150:
        fails.append(f"studs overlap {studs.get('beamOverlapMm')}")
    studs_svg = ""
    try:
        from WEOS.factory.railing_engine import railing_svg as _rsvg_easy
        studs_svg = _rsvg_easy({**{
            "shape": "straight", "lengthMm": 3000, "heightMm": 1000, "panels": 3,
            "bottomKind": "studs", "studsPerGlass": 2, "continuousRail": False,
            "installComponents": {
                "bottomRail": False, "block": False, "ssPillar": False, "studs": True,
                "handrail": True, "glass": True,
            },
            "beamOverlapMm": 200,
        }}, quote=studs)
    except Exception as exc:
        fails.append(f"studs svg {exc}")
    if "overlap" not in studs_svg.lower():
        fails.append("studs svg missing overlap label")
    n_drawn = studs_svg.count('data-side-stud="1"')
    if n_drawn != 3 * 2:
        fails.append(f"straight 2pc/glass stud count {n_drawn} != 6")
    if "#e7f3ee" in studs_svg:
        fails.append("straight still draws green bullet studs")
    if cont.get("mountType") != "top_mount":
        fails.append(f"continuous mount {cont.get('mountType')} != top_mount")
    if blk.get("mountType") != "top_mount":
        fails.append(f"block mount {blk.get('mountType')} != top_mount")
    if ss.get("mountType") != "top_mount":
        fails.append(f"ss pillar mount {ss.get('mountType')} != top_mount")
    if stair_step.get("mountType") != "step_mount":
        fails.append(f"stair step mount {stair_step.get('mountType')}")
    if stair_step.get("beamOverlapMm"):
        fails.append("step-mount stairs should not carry beam overlap")
    if stair_side.get("mountType") != "side_mount":
        fails.append(f"stair side mount {stair_side.get('mountType')}")
    if float(stair_side.get("beamOverlapMm") or 0) < 150:
        fails.append(f"stair side overlap {stair_side.get('beamOverlapMm')}")

    # 7) Side mount 2/4/6/8 enumeration
    for n in (2, 4, 6, 8):
        q = compute_railing({
            "shape": "staircase",
            "floorHeightMm": 2520,
            "stairRiseMm": 180,
            "stairRunMm": 300,
            "glassHeightMm": 900,
            "panels": 3,
            "stairMountType": "side",
            "studSizeMm": 38,
            "studsPerGlass": n,
            "stairBottomType": "block",
            "beamOverlapMm": 150,
            "installComponents": {
                "bottomRail": False, "block": True, "ssPillar": False,
                "handrail": True, "glass": True,
            },
            "rates": {"glassPerSqft": 200, "studPerPc": 80, "blockPerPc": 100},
        })
        if int(q.get("stairStuds") or 0) != 3 * n:
            fails.append(f"side {n}/glass → studs {q.get('stairStuds')}")
        svg_n = ""
        try:
            from WEOS.factory.railing_engine import railing_svg as _rsvg_side
            svg_n = _rsvg_side({
                "shape": "staircase",
                "floorHeightMm": 2520,
                "stairRiseMm": 180,
                "stairRunMm": 300,
                "glassHeightMm": 900,
                "panels": 3,
                "stairMountType": "side",
                "studSizeMm": 38,
                "studsPerGlass": n,
                "stairBottomType": "block",
                "beamOverlapMm": 150,
                "installComponents": {
                    "bottomRail": False, "block": True, "ssPillar": False,
                    "handrail": True, "glass": True,
                },
            }, quote=q)
        except Exception as exc:
            fails.append(f"side {n} svg {exc}")
            continue
        mark = 'data-side-stud="1"'
        got = svg_n.count(mark)
        if got != 3 * n:
            fails.append(f"side {n}/glass svg studs {got} != {3 * n}")
        if "<line" in svg_n and 'stroke="#14181c" stroke-width="' in svg_n:
            # Stair nosing polyline is OK; a full-height pole at a stud x is not.
            if "×2</text>" in svg_n or "#e7f3ee" in svg_n:
                fails.append(f"side {n} still draws pole/bullet studs")
        if n == 4 and "overlap 150" not in svg_n.lower() and "overlap 150 mm" not in svg_n.lower():
            if "overlap" not in svg_n.lower():
                fails.append("side 4pc svg missing overlap dim")

    # Gallery sizes + 2 ft anchors + 16 ft bars + EPDM + 180° on handrail only
    from WEOS.factory.railing_engine import continuous_rail_anchor_count, _handrail_connectors, FT_16_MM

    gal = compute_railing({
        "shape": "straight",
        "lengthMm": 5000,
        "heightMm": 1100,
        "panels": 3,
        "bottomKind": "continuous",
        "bottomSize": "100×45",
        "handrailSize": "50×50",
        "continuousRail": True,
        "handrail": True,
        "handrailBarLengthFt": 16,
        "anchorSpacingFt": 2,
        "installComponents": {
            "bottomRail": True, "block": False, "ssPillar": False,
            "handrail": True, "glass": True,
        },
        "rates": {
            "glassPerSqft": 200, "bottomRailPerUnit": 90, "handrailPerUnit": 140,
            "anchorPerPc": 40, "connector180PerPc": 80,
            "epdmHandrailPerUnit": 18, "epdmBottomPerUnit": 18,
            "handrailWeightPerUnit": 1.25, "bottomRailWeightPerUnit": 2.4,
        },
        "manualRatePerUnit": 520,
    })
    expect_anc = continuous_rail_anchor_count(5000, 2 * 304.8)
    expect_180 = _handrail_connectors(5000, FT_16_MM)
    if int(gal.get("anchorCount") or 0) != expect_anc:
        fails.append(f"gallery anchors {gal.get('anchorCount')} != {expect_anc}")
    if int(gal.get("connector180Count") or 0) != expect_180:
        fails.append(f"gallery 180° {gal.get('connector180Count')} != {expect_180}")
    gk = {it["key"] for it in gal.get("items") or []}
    if "connector180" not in gk and expect_180:
        fails.append("180° missing from handrail BOM")
    if any("bottom" in str(it.get("label") or "").lower() and "180" in str(it.get("label") or "") for it in (gal.get("items") or [])):
        fails.append("180° must not appear on bottom rail")
    if "epdmHandrail" not in gk or "epdmBottom" not in gk:
        fails.append(f"EPDM missing keys {gk}")
    hr = next((it for it in (gal.get("items") or []) if it.get("key") == "handrail"), {})
    br = next((it for it in (gal.get("items") or []) if it.get("key") == "bottomRail"), {})
    if "50×50" not in str(hr.get("sizeMm") or hr.get("label") or "").replace("x", "×") and "50x50" not in str(hr.get("sizeMm") or "").lower().replace("×", "x"):
        fails.append(f"handrail size not 50×50: {hr}")
    if "100×45" not in str(br.get("sizeMm") or br.get("label") or "").replace("x", "×") and "100x45" not in str(br.get("sizeMm") or "").lower().replace("×", "x"):
        fails.append(f"bottom size not 100×45: {br}")
    if abs(float(hr.get("qty") or 0) - float(br.get("qty") or 0)) > 0.02:
        fails.append(f"handrail RFT {hr.get('qty')} != bottom {br.get('qty')}")
    if float(hr.get("weightKg") or 0) <= 0 or float(br.get("weightKg") or 0) <= 0:
        fails.append(f"weight input not applied hr={hr.get('weightKg')} br={br.get('weightKg')}")
    specs = " ".join(_spec_lines({
        "product": "railing", "productType": "railing",
        "width": 5000, "height": 1100, "qty": 1, "sellingRate": 520,
        "options": {"railing": {
            "shape": "straight", "lengthMm": 5000, "heightMm": 1100,
            "bottomKind": "continuous", "bottomSize": "100×45", "handrailSize": "50×50",
            "handrailBarLengthFt": 16, "anchorSpacingFt": 2, "handrail": True,
        }, "railingQuote": gal},
    })).lower()
    if "100" not in specs.replace("×", "x") or "45" not in specs:
        fails.append(f"PDF specs missing bottom 100×45: {specs[:240]}")
    if "50" not in specs or "handrail" not in specs:
        fails.append(f"PDF specs missing handrail 50×50: {specs[:240]}")
    if "epdm" not in specs:
        fails.append(f"PDF specs missing EPDM: {specs[:240]}")
    if "180" not in specs:
        fails.append(f"PDF specs missing 180°: {specs[:240]}")

    # Custom bottom size + weight / RFT
    custom = compute_railing({
        "shape": "straight",
        "lengthMm": 2400,
        "heightMm": 1000,
        "panels": 2,
        "bottomKind": "continuous",
        "bottomSize": "95×42 custom",
        "handrailSize": "Ø35",
        "continuousRail": True,
        "handrail": True,
        "handrailBarLengthFt": 12,
        "anchorSpacingFt": 1,
        "installComponents": {
            "bottomRail": True, "block": False, "ssPillar": False,
            "handrail": True, "glass": True,
        },
        "rates": {
            "glassPerSqft": 180, "bottomRailPerUnit": 70, "handrailPerUnit": 110,
            "anchorPerPc": 35, "bottomRailWeightPerUnit": 1.8, "handrailWeightPerUnit": 0.9,
        },
    })
    cbr = next((it for it in (custom.get("items") or []) if it.get("key") == "bottomRail"), {})
    if "95" not in str(cbr.get("sizeMm") or cbr.get("label") or ""):
        fails.append(f"custom bottom size missing: {cbr}")
    if float(cbr.get("weightKg") or 0) <= 0:
        fails.append("custom bottom weight not applied")
    expect_1ft = continuous_rail_anchor_count(2400, 304.8)
    if int(custom.get("anchorCount") or 0) != expect_1ft:
        fails.append(f"1ft anchors {custom.get('anchorCount')} != {expect_1ft}")
    if int(custom.get("connector180Count") or 0) != 0:
        fails.append(f"12ft bar on 2400mm should be 0 connectors, got {custom.get('connector180Count')}")
    if int(custom.get("pillarCount") or 0) != 0:
        fails.append("custom continuous still has pillars")

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print("OK easy railing wizard · continuous/block/SS · stairs step/side studs · no series leak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
