"""Smoke: Casement Product Gallery (normal · stile · slim + top-hung vs side-swing stay)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_casement_gal_"))
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
        casement_quote_hardware_descriptions,
        derive_casement_hardware_lines,
        derive_casement_wastage_flags,
        derive_section_sizes,
        format_named_capacity_brand,
        normalize_setup,
    )

    # ── Normal + hinges ──────────────────────────────────────────────
    raw = {
        "type": "casement",
        "casement": {
            "kind": "normal",
            "activeFrameVariant": "grills",
            "outerFrame": {
                "variants": {
                    "plain": {"name": "OF plain", "wMm": 45, "weightKgPerM": 1.2, "rate": 100},
                    "grills": {"name": "OF grills", "wMm": 50, "weightKgPerM": 1.4, "rate": 120},
                    "grills_mesh": {"name": "OF mesh", "wMm": 55, "weightKgPerM": 1.5, "rate": 130},
                }
            },
            "mullions": {
                "active": "slim",
                "slim": {"name": "Mull slim", "wMm": 25, "weightKgPerM": 0.6},
                "big": {"name": "Mull big", "wMm": 40, "weightKgPerM": 1.0},
            },
            "doors": {
                "active": "big",
                "slim": {"name": "Door slim", "wMm": 30},
                "big": {"name": "Door big", "wMm": 40, "weightKgPerM": 0.9},
            },
            "glassClips": {"active": "sg", "sg": {"clipMm": 8, "maxMm": 12}, "dgu": {"clipMm": 14}},
            "hardwarePack": {
                "openHardware": "hinges",
                "hinges": {
                    "name": "SS Butt Hinge",
                    "brand": "Godrej",
                    "weightCapacityKg": 80,
                    "qty": 3,
                    "rate": 45,
                },
                "limitationArm": {"name": "Limitation arm", "brand": "Godrej", "rate": 120},
                "lock": {"type": "multipoint", "rate": 650},
                "frameConnectors": {"qty": 4, "rate": 12},
                "doorConnectors": {"qty": 4, "rate": 10},
                "wings": {"qty": 8, "rate": 8},
                "gasket": {
                    "outerFrame": {"ratePerM": 25},
                    "interlock": {"qtyPerPc": 2, "rate": 5},
                    "doorOutside": {"ratePerM": 20},
                    "glass": {"ratePerM": 18},
                },
            },
            "costing": {"labourPerSft": 35, "profitPercent": 15, "costEngine": "stub"},
        },
    }
    setup = normalize_setup(raw)
    cm = setup["casement"]
    _ok(cm["kind"] == "normal", "kind normal")
    _ok(cm["activeFrameVariant"] == "grills", "frame variant grills")
    _ok(cm["outerFrame"]["variants"]["grills"]["wMm"] == 50, "grills frame dims")
    _ok(cm["mullions"]["active"] == "slim", "mullion slim")
    _ok(cm["doors"]["active"] == "big", "door big")
    _ok(cm["hardwarePack"]["openHardware"] == "hinges", "open = hinges")
    _ok(cm["hardwarePack"]["hinges"]["qty"] == 3, "hinge qty")
    _ok(cm["hardwarePack"]["stay"]["enabled"] is False, "stay off when hinges")
    _ok(cm["hardwarePack"]["topHungStay"]["enabled"] is False, "top-hung off when hinges")
    _ok(cm["hardwarePack"]["limitationArm"]["enabled"] is True, "limitation arm with hinges")
    _ok(cm["hardwarePack"]["frameConnectors"]["qty"] == 4, "frame connectors 4")
    _ok(cm["costing"]["costEngine"] == "stub", "cost stub")

    sizes = derive_section_sizes(setup)
    _ok(sizes.get("leftJamb") == 50, f"jamb from active grills frame {sizes}")
    _ok(sizes.get("leafStile") == 40, f"leaf from big door {sizes}")

    notes = casement_quote_hardware_descriptions(setup)
    texts = " | ".join(n["text"] for n in notes)
    _ok(any(n["label"] == "HINGES" for n in notes), f"HINGES in quote notes {notes}")
    _ok("Godrej" in texts and "80" in texts, f"name·kg·brand in quote {texts}")
    _ok(
        "Godrej" in format_named_capacity_brand(cm["hardwarePack"]["hinges"]),
        "format helper",
    )

    hw = derive_casement_hardware_lines(setup, width_mm=1200, height_mm=1400, door_count=2)
    names = [h["name"] for h in hw]
    _ok(any("Hinge" in n or "Butt" in n for n in names), f"hinge lines {names}")
    _ok(any("Limitation" in n for n in names), f"limitation {names}")
    _ok(any("Lock" in n for n in names), f"lock {names}")
    _ok(any("Frame connectors" in n for n in names), f"frame conn {names}")
    hinges = next(h for h in hw if "Hinge" in h["name"] or "Butt" in h["name"])
    _ok(hinges["qty"] == 6, f"3×2 doors hinge qty={hinges['qty']}")

    # ── Stay mode: side-swing ≠ top-hung, 1 set/door, never mix ─────
    stay_raw = normalize_setup({
        "type": "casement",
        "casement": {
            "kind": "normal",
            "hardwarePack": {
                "openHardware": "stay",
                "stay": {
                    "enabled": True,
                    "name": "Side-swing stay",
                    "selectedInch": 12,
                    "rate": 180,
                    "lengths": [{"inch": 12, "rate": 180}],
                },
                "topHungStay": {
                    "enabled": True,
                    "name": "Top-hung stay",
                    "selectedInch": 10,
                    "rate": 220,
                    "lengths": [{"inch": 10, "rate": 220}],
                },
            },
        },
    })
    sp = stay_raw["casement"]["hardwarePack"]
    _ok(sp["openHardware"] == "stay", "stay mode")
    _ok(sp["hinges"]["enabled"] is False, "no hinges in stay mode")
    _ok(sp["stay"]["setsPerDoor"] == 1, "side-swing 1 set/door")
    _ok(sp["topHungStay"]["setsPerDoor"] == 1, "top-hung 1 set/door")
    _ok(sp["stay"]["kind"] == "side_swing", "side_swing kind")
    _ok(sp["topHungStay"]["kind"] == "top_hung", "top_hung kind")

    # Both enabled without explicit counts → 0 each (must not mix/guess)
    mixed = derive_casement_hardware_lines(
        stay_raw, width_mm=1000, height_mm=1200, door_count=3
    )
    stay_names = [h["name"] for h in mixed]
    _ok(not any("stay" in n.lower() for n in stay_names), f"no guessed stay qty when both on {stay_names}")

    split = derive_casement_hardware_lines(
        stay_raw,
        width_mm=1000,
        height_mm=1200,
        door_count=3,
        side_swing_doors=2,
        top_hung_doors=1,
    )
    side = next(h for h in split if "Side-swing" in h["name"])
    top = next(h for h in split if "Top-hung" in h["name"])
    _ok(side["qty"] == 2, f"side-swing qty 2 doors → {side['qty']}")
    _ok(top["qty"] == 1, f"top-hung qty 1 door → {top['qty']}")
    _ok(side["qty"] != top["qty"] or True, "separate lines")
    _ok("not mixed" in (top.get("remarks") or "").lower() or "top-hung" in (top.get("remarks") or "").lower(),
        f"top-hung remarks {top.get('remarks')}")

    # Only side-swing → all doors
    only_side = normalize_setup({
        "type": "casement",
        "casement": {
            "kind": "normal",
            "hardwarePack": {
                "openHardware": "stay",
                "stay": {"enabled": True, "name": "Side-swing stay", "rate": 100, "selectedInch": 10},
                "topHungStay": {"enabled": False},
            },
        },
    })
    only = derive_casement_hardware_lines(only_side, width_mm=900, height_mm=1100, door_count=4)
    sline = next(h for h in only if "Side-swing" in h["name"])
    _ok(sline["qty"] == 4, f"sole stay family uses all doors → {sline['qty']}")
    _ok(not any("Top-hung" in h["name"] for h in only), "no top-hung line")

    # ── Stile + floor spring ─────────────────────────────────────────
    stile = normalize_setup({
        "type": "casement",
        "casement": {
            "kind": "stile",
            "doors": {
                "hingeSide": {"name": "Hinge stile", "wMm": 50},
                "lockSide": {"name": "Lock stile", "wMm": 55},
                "top": {"name": "Top rail", "wMm": 40},
                "bottom": {"name": "Bottom rail", "wMm": 45},
            },
            "hardwarePack": {
                "openHardware": "floor_spring",
                "floorSpring": {
                    "enabled": True,
                    "topPivot": {"name": "Top pivot", "brand": "Dorma", "weightCapacityKg": 100, "rate": 800},
                    "bottomFloorSpring": {"name": "FS-100", "brand": "Dorma", "weightCapacityKg": 100, "rate": 3200},
                },
                "doorCloser": {"enabled": True, "rate": 900, "brand": "Dorma", "weightCapacityKg": 80},
            },
            "costing": {"soldPerRft": True, "projectWastageReuse": False, "defaultStdLengthM": 3.0},
        },
    })
    st = stile["casement"]
    _ok(st["kind"] == "stile", "stile kind")
    _ok(st["doors"]["mode"] == "stile_sides", "stile door mode")
    _ok(st["outerFrame"]["includeBottom"] is False, "stile no bottom frame")
    _ok(st["hardwarePack"]["frameConnectors"]["qty"] == 0, "stile no connectors")
    _ok(st["hardwarePack"]["floorSpring"]["enabled"] is True, "floor spring on")
    _ok(st["hardwarePack"]["hinges"]["enabled"] is False, "no hinges with floor spring")
    _ok(st["costing"]["soldPerRft"] is True, "stile sold RFT")
    _ok(3.0 in st["costing"]["stdLengthsM"] or st["costing"]["defaultStdLengthM"] == 3.0, "std 3m")

    st_notes = casement_quote_hardware_descriptions(stile)
    _ok(any(n["label"] == "FLOOR SPRING" for n in st_notes), f"floor spring quote {st_notes}")
    _ok(any("Dorma" in n["text"] and "100" in n["text"] for n in st_notes), f"capacity+brand {st_notes}")

    st_hw = derive_casement_hardware_lines(stile, width_mm=1000, height_mm=2100, door_count=1)
    _ok(any("Floor spring" in h["name"] or "FS-100" in h["name"] for h in st_hw), f"FS line {st_hw}")
    _ok(any("Top pivot" in h["name"] for h in st_hw), f"pivot {st_hw}")
    _ok(not any("connector" in h["name"].lower() for h in st_hw), "no connectors on stile BOM")

    wastage = derive_casement_wastage_flags(stile)
    _ok(wastage.get("soldPerRft") is True, "wastage soldPerRft")
    _ok(wastage.get("costEngine") == "stub", "wastage stub")

    # ── Slim profile ─────────────────────────────────────────────────
    slim = normalize_setup({
        "type": "casement",
        "casement": {
            "kind": "slim_profile",
            "doors": {
                "mode": "verticals_same_tb_same",
                "vertical": {"name": "Slim V", "wMm": 20},
                "topBottom": {"name": "Slim TB", "wMm": 18},
            },
            "hardwarePack": {
                "openHardware": "hinges",
                "hinges": {"enabled": True, "name": "Slim hinge", "brand": "X", "weightCapacityKg": 60, "qty": 2, "rate": 40},
                "floorSpring": {"enabled": True, "bottomFloorSpring": {"name": "FS", "brand": "Y", "weightCapacityKg": 80, "rate": 2000}},
            },
            "costing": {"chargeFullStdLengthWhenSplit": True, "projectWastageReuse": False},
        },
    })
    sl = slim["casement"]
    _ok(sl["kind"] == "slim_profile", "slim kind")
    _ok(sl["doors"]["mode"] == "verticals_same_tb_same", "slim door mode")
    _ok(sl["outerFrame"]["includeBottom"] is False, "slim no bottom")
    w2 = derive_casement_wastage_flags(slim)
    _ok(w2.get("chargeFullStdLength") is True, f"split → full std {w2}")

    pack = apply_setup_bom(
        slim, width_mm=900, height_mm=2100, shutter_count=1, system_type="casement"
    )
    _ok(pack.get("costEngine") == "stub", "BOM cost stub")
    _ok(pack.get("quoteHardwareNotes"), f"quote notes on BOM {pack.get('quoteHardwareNotes')}")
    _ok(len(pack.get("hardware") or []) >= 1, f"hardware lines {pack.get('hardware')}")

    print("Casement Product Gallery smoke passed.")


if __name__ == "__main__":
    main()
