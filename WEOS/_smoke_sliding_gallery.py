"""Smoke: Sliding Product Gallery schema (tracks · shutters · meeting · mesh · hardware · costing)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_sliding_gal_"))
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
        bom_qty_for_pattern,
        derive_section_sizes,
        derive_sliding_hardware_lines,
        derive_sliding_track_fill,
        normalize_setup,
        rail_count_for_track_option,
    )

    _ok(rail_count_for_track_option(2) == 2, "2 track → 2 rails")
    _ok(rail_count_for_track_option(2.5) == 2, "2.5 track → 2 rails only")
    _ok(rail_count_for_track_option(3) == 3, "3 track → 3 rails")
    _ok(rail_count_for_track_option(4) == 4, "4 track → 4 rails")
    _ok(bom_qty_for_pattern("all_side_4")["all"] == 4, "all side 4 nos")
    _ok(bom_qty_for_pattern("v2_t1_b1")["top"] == 1, "v2 t1 b1")

    raw = {
        "type": "sliding",
        "sliding": {
            "trackMode": "verticals_same_h_diff",
            "bomPattern": "v2_t1_b1",
            "activeTrackOption": "2.5",
            "trackOptions": [
                {
                    "id": "2.5",
                    "sides": {
                        "vertical": {"name": "V track", "wMm": 35, "weightKgPerM": 1.6, "rate": 120, "rateUnit": "rft"},
                        "top": {"name": "Top", "wMm": 35, "weightKgPerM": 1.6, "rate": 120},
                        "bottom": {"name": "Bottom", "wMm": 40, "weightKgPerM": 1.8, "rate": 130},
                    },
                }
            ],
            "shutters": {
                "mode": "split",
                "handleSide": {"name": "Handle", "wMm": 25, "weightKgPerM": 0.8},
                "interlockSlim": {"name": "Slim", "wMm": 20, "weightKgPerM": 0.52},
                "interlockRenf": {"name": "Renf", "wMm": 20, "weightKgPerM": 1.01},
            },
            "meeting": {"enabled": True, "section": {"name": "Meeting", "wMm": 25, "weightKgPerM": 0.22}},
            "mesh": {
                "compatible": True,
                "adapter": {"sameAllSides": True, "section": {"name": "Adapter", "wMm": 18}},
                "meshSection": {"name": "Mesh sash", "wMm": 22, "weightKgPerM": 0.6},
            },
            "hardwarePack": {
                "trackConnectors": {"qty": 4, "rate": 12},
                "shutterConnectors": {"qty": 2, "rate": 10},
                "epdm": {"ratePerM": 35},
                "brush": {"ratePerM": 18},
                "wings": {"rate": 8},
                "lock": {"type": "multipoint", "rate": 450},
                "wheels": {"qtyPerShutter": 2, "rate": 55},
            },
            "costing": {"labourPerSft": 40, "profitPercent": 18, "costEngine": "stub"},
        },
    }
    setup = normalize_setup(raw)
    sl = setup["sliding"]
    _ok(sl["trackMode"] == "verticals_same_h_diff", "track mode round-trip")
    _ok(sl["activeTrackOption"] == "2.5", "active 2.5")
    opt = next(o for o in sl["trackOptions"] if o["id"] == "2.5")
    _ok(opt["railCount"] == 2, f"2.5 railCount={opt['railCount']}")
    _ok(len(sl["trackOptions"]) == 4, "all 2/2.5/3/4 options present")
    _ok(sl["meeting"]["enabled"] is True, "meeting enabled")
    _ok(sl["hardwarePack"]["lock"]["type"] == "multipoint", "lock type")
    _ok(sl["costing"]["costEngine"] == "stub", "cost engine stub")
    _ok(sl["shutters"]["interlockRenf"]["name"] == "Renf", "renf interlock")

    sizes = derive_section_sizes(setup)
    _ok(sizes.get("leftJamb") == 35, f"jamb from vertical {sizes}")
    _ok(sizes.get("trackRailCount") == 2, f"rail count in sizes {sizes}")

    fill = derive_sliding_track_fill(setup, width_mm=1200, height_mm=1400)
    _ok(fill["pattern"] == "v2_t1_b1", f"fill pattern {fill['pattern']}")
    _ok(fill["rails"] == 2, "fill rails")
    _ok(any(ln["role"] == "track_vertical" and ln["qty"] == 2 for ln in fill["lines"]), f"fill lines {fill['lines']}")

    hw = derive_sliding_hardware_lines(setup, width_mm=1200, height_mm=1400, shutter_count=2)
    names = [h["name"] for h in hw]
    _ok(any("EPDM" in n for n in names), f"EPDM line {names}")
    _ok(any("Lock" in n for n in names), f"lock line {names}")
    _ok(any("Wheels" in n for n in names), f"wheels {names}")
    wings = next(h for h in hw if "Wing" in h["name"])
    _ok(wings["qty"] == 8, f"split wings 4×2 shutters = {wings['qty']}")  # qtySplit 4 × 2

    pack = apply_setup_bom(
        setup, width_mm=1200, height_mm=1400, shutter_count=2, system_type="sliding"
    )
    _ok(pack.get("costEngine") == "stub", "BOM cost engine stub")
    _ok(pack.get("trackFill"), "trackFill on BOM pack")
    _ok(len(pack.get("hardware") or []) >= 3, f"hardware from pack {pack.get('hardware')}")

    # all_sides_same wings = 8 per shutter
    raw2 = normalize_setup({
        "type": "sliding",
        "sliding": {
            "trackMode": "all_sides_same",
            "shutters": {"mode": "all_sides_same", "allSides": {"name": "Sash", "wMm": 25}},
            "hardwarePack": {"wings": {"rate": 5}, "wheels": {"qtyPerShutter": 2, "rate": 1}},
        },
    })
    hw2 = derive_sliding_hardware_lines(raw2, width_mm=1000, height_mm=1000, shutter_count=2)
    wings2 = next(h for h in hw2 if "Wing" in h["name"])
    _ok(wings2["qty"] == 16, f"all-side wings 8×2 = {wings2['qty']}")

    print("Sliding Product Gallery smoke passed.")


if __name__ == "__main__":
    main()
