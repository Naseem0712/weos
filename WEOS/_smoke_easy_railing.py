"""Smoke: easy railing wizard configs — continuous / block / stairs mounts."""
from __future__ import annotations

from WEOS.factory.marqt_pdf import _spec_lines
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.railing_engine import compute_railing


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
    if abs(float(cont.get("sellingPerUnit") or 0) - 450) > 0.01:
        fails.append(f"manual rate not applied: {cont.get('sellingPerUnit')}")
    if cont.get("wastageEnabled") is not False:
        fails.append("normal should disable wastage")

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
            "installComponents": {
                "bottomRail": False, "block": True, "ssPillar": False,
                "handrail": True, "glass": True,
            },
            "rates": {"glassPerSqft": 200, "studPerPc": 80, "blockPerPc": 100},
        })
        if int(q.get("stairStuds") or 0) != 3 * n:
            fails.append(f"side {n}/glass → studs {q.get('stairStuds')}")

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print("OK easy railing wizard · continuous/block/SS · stairs step/side studs · no series leak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
