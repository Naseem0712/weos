"""Phase 2 Series Setup: members (wFactor/hFactor) + weight→hardware pick."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_series_p2_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    from WEOS.factory.product_setup import (
        apply_setup_bom,
        normalize_setup,
        pick_hardware_by_weight,
        derive_member_cuts,
    )

    # Empty members / rules → legacy fallback (no crash, empty pack)
    empty = normalize_setup({"type": "sliding"})
    _ok(empty["members"] == [], "empty members default")
    _ok(empty["hardwareWeightRules"] == [], "empty weight rules default")
    pack0 = apply_setup_bom(empty, width_mm=1200, height_mm=1400, glass_kg_total=20, shutter_count=2)
    _ok(not pack0["usedMembers"] and not pack0["usedHardwareWeightRules"], "empty → legacy path")

    setup = normalize_setup({
        "type": "sliding",
        "members": [
            {"name": "Outer track", "role": "outer", "wFactor": 2, "hFactor": 2, "weightKgPerM": 1.1, "ratePerM": 280, "rateUnit": "m"},
            {"name": "Shutter sash", "role": "shutter", "wFactor": 2, "hFactor": 2, "weightKgPerM": 0.9, "ratePerM": 320},
            {"name": "Interlock", "role": "interlock", "wFactor": 0, "hFactor": 2, "weightKgPerM": 0.8, "ratePerM": 300},
            # Door-style: outer height 2 pcs one profile, width 2 pcs different
            {"name": "Door outer H", "role": "outer", "wFactor": 0, "hFactor": 2, "weightKgPerM": 1.4, "ratePerM": 400},
            {"name": "Door outer W", "role": "outer", "wFactor": 2, "hFactor": 0, "weightKgPerM": 1.2, "ratePerM": 380},
        ],
        "hardwareWeightRules": [
            {"kind": "wheel", "systemType": "sliding", "minKg": 0, "maxKg": 30, "name": "Light roller", "rate": 120, "qtyPer": 2, "basis": "shutter"},
            {"kind": "wheel", "systemType": "sliding", "minKg": 30, "maxKg": 60, "name": "Twin roller 60", "rate": 220, "qtyPer": 2, "basis": "shutter", "sku": "TR-60"},
            {"kind": "wheel", "systemType": "sliding", "minKg": 60, "maxKg": 100, "name": "Heavy roller 100", "rate": 380, "qtyPer": 2, "basis": "shutter"},
            {"kind": "hinge", "systemType": "casement", "minKg": 0, "maxKg": 40, "name": "Casement hinge", "rate": 90, "qtyPer": 2, "basis": "leaf"},
            {"kind": "floor_spring", "systemType": "style", "minKg": 0, "maxKg": 80, "name": "FS-80", "rate": 2200, "qtyPer": 1, "basis": "door"},
        ],
    })
    _ok(len(setup["members"]) == 5, f"normalized 5 members got {len(setup['members'])}")
    _ok(setup["members"][0]["wFactor"] == 2 and setup["members"][0]["hFactor"] == 2, "factors round-trip")

    cuts = derive_member_cuts(
        setup, width_mm=2000, height_mm=2100, ctx={"shutterCount": 2}, qty=1
    )
    _ok(len(cuts) >= 4, f"member cuts produced {len(cuts)}")
    outer = next(c for c in cuts if c["name"] == "Outer track")
    # (2*2000 + 2*2100)/1000 * 1 = 8.2 m
    _ok(abs(outer["metres"] - 8.2) < 0.01, f"outer metres {outer['metres']}")
    sash = next(c for c in cuts if c["name"] == "Shutter sash")
    # roleCount=2 shutters → (2*2000+2*2100)/1000*2 = 16.4
    _ok(abs(sash["metres"] - 16.4) < 0.01, f"sash metres {sash['metres']}")

    # Weight pick — WD pattern
    mid = pick_hardware_by_weight(setup["hardwareWeightRules"], 45, kind="wheel", system_type="sliding")
    _ok(mid and mid["name"] == "Twin roller 60", f"45kg → Twin roller 60 got {mid}")
    light = pick_hardware_by_weight(setup["hardwareWeightRules"], 20, kind="wheel", system_type="sliding")
    _ok(light and light["name"] == "Light roller", f"20kg → Light roller got {light}")
    heavy = pick_hardware_by_weight(setup["hardwareWeightRules"], 90, kind="wheel", system_type="sliding")
    _ok(heavy and heavy["name"] == "Heavy roller 100", f"90kg → Heavy got {heavy}")

    # System isolation: casement hinge must not pick for sliding
    bad = pick_hardware_by_weight(setup["hardwareWeightRules"], 20, kind="hinge", system_type="sliding")
    _ok(bad is None, "sliding must not pick casement hinge")
    hinge = pick_hardware_by_weight(setup["hardwareWeightRules"], 20, kind="hinge", system_type="casement")
    _ok(hinge and hinge["name"] == "Casement hinge", f"casement hinge pick got {hinge}")

    pack = apply_setup_bom(
        setup,
        width_mm=2000,
        height_mm=2100,
        ctx={"shutterCount": 2},
        glass_kg_total=40.0,
        shutter_count=2,
        system_type="sliding",
    )
    _ok(pack["usedMembers"] and pack["usedHardwareWeightRules"], "pack uses members+rules")
    _ok(pack["leafWeightKg"] > 0, f"leaf weight {pack['leafWeightKg']}")
    hw_names = [h["name"] for h in pack["hardware"]]
    _ok(any("Twin roller" in n or "Light roller" in n or "Heavy roller" in n for n in hw_names), f"hw lines {hw_names}")
    _ok(all("Casement" not in n and "FS-80" not in n for n in hw_names), f"no foreign system hw {hw_names}")
    twin = next((h for h in pack["hardware"] if "roller" in h["name"].lower()), None)
    _ok(twin and twin["unitRate"] > 0 and twin["qty"] == 4, f"qty 2/shutter×2={twin}")

    # Live generate_job path — inject setup onto loaded product via monkeypatch-free
    # temporary product dict through pipeline internals is hard; instead verify
    # calculate_line still works (legacy) and apply_setup_bom integrates rates.
    from WEOS.factory.project_engine import calculate_line

    calc = calculate_line({
        "product": "29mm_sliding",
        "width": 2000,
        "height": 2100,
        "qty": 1,
        "glass": "10mm_toughened",
        "system": "sliding",
        "trackCount": 2,
        "glassShutters": 2,
        "sellingRate": 800,
        "saleUnit": "sqft",
    })
    _ok(calc.get("status") in ("active", "stub") or calc.get("bom") is not None, "legacy calculate_line ok")
    _ok(isinstance(calc.get("hardware"), list), "hardware list present")
    print("Phase 2 series setup smoke passed.")


if __name__ == "__main__":
    main()
