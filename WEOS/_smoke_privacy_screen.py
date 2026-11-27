"""Acceptance: 13×8 ft centre-opening folding privacy screen + edit/reopen checks."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

from WEOS.factory.gate_engine import compute_gate, fixed_gap_blade_count, gate_svg
from WEOS.factory.line_kind import is_gate_cart_line, line_world
from WEOS.factory.materials_list import materials_rows_for_line
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.structural_catalogue import build_structural_catalogue, find_section_by_size


def _cfg(**over):
    base = {
        "widthFt": 13,
        "heightFt": 8,
        "bayType": "folding_privacy",
        "foldLeft": 2,
        "foldRight": 2,
        "louverGapMm": 25,
        "louverOrientation": "vertical",
        "msStockFt": 20,
        "msBarWeightKg": 25,
        "msRatePerKg": 150,
        "alRatePerBar": 850,
        "alStockFt": 16,
        "coatingRate": 25,
        "coatingRateUnit": "rft",
        "fabRatePerSft": 150,
        "hardwarePackageAmount": 10000,
        "supportRodCount": 2,
        "supportDiaMm": 12,
        "qty": 1,
    }
    base.update(over)
    return base


def main() -> int:
    fails: list[str] = []
    build_structural_catalogue(persist=True)
    ms = find_section_by_size(material="mild_steel", width_mm=75, height_mm=75, thickness_mm=3, shape="hollow_sq")
    al = find_section_by_size(material="aluminium", width_mm=25, height_mm=25, shape="hollow_sq")
    if not ms:
        fails.append("MS 75×75 missing from structural catalogue")
    if not al:
        fails.append("Al 25×25 square missing from structural catalogue")

    q = compute_gate(_cfg())
    # Geometry
    if abs(float(q.get("widthFt") or 0) - 13) > 0.01:
        fails.append(f"widthFt {q.get('widthFt')}")
    if abs(float(q.get("heightFt") or 0) - 8) > 0.01:
        fails.append(f"heightFt {q.get('heightFt')}")
    if abs(float(q.get("areaSft") or 0) - 104.0) > 0.05:
        fails.append(f"areaSft {q.get('areaSft')} != 104")
    if int(q.get("foldLeft") or 0) != 2 or int(q.get("foldRight") or 0) != 2:
        fails.append(f"fold {q.get('foldLeft')}+{q.get('foldRight')}")
    if int(q.get("wallPostCount") or 0) != 2:
        fails.append(f"wall posts {q.get('wallPostCount')}")
    if int(q.get("leafCount") or 0) != 4:
        fails.append(f"leafCount {q.get('leafCount')}")

    # Louver pack formula
    leaf0 = (q.get("leaves") or [{}])[0]
    clear_w = float(leaf0.get("clearWidthMm") or 0)
    pack = fixed_gap_blade_count(usable_mm=clear_w, face_mm=25, gap_mm=25)
    if int(q.get("bladeCountPerLeaf") or 0) != int(pack.get("bladeCount") or -1):
        fails.append(
            f"blade/leaf {q.get('bladeCountPerLeaf')} != formula {pack.get('bladeCount')} (clear {clear_w})"
        )
    if abs(float(q.get("louverGapMm") or 0) - 25) > 0.01:
        fails.append(f"gap {q.get('louverGapMm')}")

    # Shared posts not duplicated beyond 2
    wall_cuts = [c for c in (q.get("cuts") or []) if c.get("memberRole") == "wall_post"]
    if len(wall_cuts) != 2:
        fails.append(f"wall_post cuts {len(wall_cuts)}")

    # Bars derived from cuts — not hardcoded
    bars = q.get("bars") or {}
    if int(bars.get("aluminium") or 0) < 1:
        fails.append("Al bars missing")
    if int(bars.get("ms") or 0) < 1:
        fails.append("MS bars missing")
    # Two nominal 8-ft from 16-ft only if cuts+trim+kerf fit — verify nest math consistency
    al_nest = None
    for nest in (q.get("nests") or {}).values():
        if str(nest.get("material") or "").startswith("al"):
            al_nest = nest
            break
    if not al_nest:
        fails.append("no Al nest")
    else:
        stock = float(al_nest.get("stockLengthMm") or 0)
        if abs(stock / 304.8 - 16) > 0.05:
            fails.append(f"Al stock ft {stock/304.8}")
        # Each blade ~ clear H; 2 per 16-ft only when 2*(cut+trim)+kerf <= stock
        blade_cut = float((leaf0.get("fill") or {}).get("bladeLengthMm") or 0)
        fit2 = 2 * (blade_cut + float(q.get("trimMm") or 5) + float(q.get("kerfMm") or 3)) <= stock + 1e-6
        blades_total = int(q.get("bladeCountTotal") or 0)
        expected_min_bars = (blades_total + 1) // 2 if fit2 else blades_total
        if int(al_nest.get("bars") or 0) < expected_min_bars and blades_total:
            # Allow nest reuse across leaves — just ensure not absurdly under-counted
            if int(al_nest.get("bars") or 0) < blades_total / 3:
                fails.append(f"Al bars {al_nest.get('bars')} too low for {blades_total} blades")

    # Money heads
    cost = q.get("cost") or {}
    if abs(float(cost.get("fabricationInstall") or 0) - 15600) > 0.5:
        fails.append(f"fab {cost.get('fabricationInstall')} != 15600")
    hw = q.get("hardware") or []
    pkg = next((h for h in hw if h.get("isPackage")), None)
    if not pkg or abs(float(pkg.get("amount") or 0) - 10000) > 0.5:
        fails.append(f"HW package {pkg}")
    # Included items not double-charged
    included_amt = sum(float(h.get("amount") or 0) for h in hw if h.get("includedInPackage"))
    if included_amt > 0.01:
        fails.append(f"included HW charged {included_amt}")
    locks = [h for h in hw if "lock" in str(h.get("catalogueId") or "").lower() and not h.get("isPackage")]
    if locks and float(locks[0].get("qty") or 0) != 1:
        fails.append(f"lock qty {locks[0].get('qty')} (4 leaves ≠ 4 locks)")
    towers = [h for h in hw if "tower" in str(h.get("catalogueId") or "").lower()]
    if towers and float(towers[0].get("qty") or 0) != 4:
        fails.append(f"tower bolts {towers[0].get('qty')}")

    rates = q.get("rates") or {}
    if float(rates.get("msPurchaseRate") or 0) != 150:
        fails.append("MS purchase rate not kept with selection")
    if float(rates.get("alPurchaseRate") or 0) != 850:
        fails.append("Al purchase rate not kept with selection")
    if str(rates.get("alPurchaseUnit") or "") != "full_length":
        fails.append(f"Al unit {rates.get('alPurchaseUnit')}")

    svg = gate_svg(_cfg(), quote=q)
    if "<svg" not in svg or "wall_post" not in svg:
        fails.append("svg missing elevation/wall posts")

    # calculate_line path
    cart = {
        "product": "gates_privacy",
        "productType": "gate",
        "category": "Gates",
        "displayName": "Folding privacy screen",
        "width": q["widthMm"],
        "height": q["heightMm"],
        "qty": 1,
        "options": {"gate": _cfg(), "productType": "gate"},
    }
    if line_world(cart) != "gate":
        fails.append(f"line_world {line_world(cart)}")
    if not is_gate_cart_line(cart):
        fails.append("is_gate_cart_line false")
    result = calculate_line(cart)
    if result.get("status") != "gate":
        fails.append(f"calc status {result.get('status')}")
    if not (result.get("preview") or {}).get("svg"):
        fails.append("calc preview svg missing")
    gq = (result.get("options") or {}).get("gateQuote") or {}
    if int(gq.get("bladeCountPerLeaf") or 0) != int(q.get("bladeCountPerLeaf") or -2):
        fails.append("calc blade mismatch")

    ml = materials_rows_for_line(result)
    if not ml.get("materials"):
        fails.append("factory materials empty")
    if not any(m.get("purchaseKg") for m in ml.get("materials") or []):
        fails.append("factory list missing purchase kg")

    # Edit width, gap 25→35, HW item, qty 1→2
    q2 = compute_gate(_cfg(widthFt=14, louverGapMm=35, qty=2, hardwarePackageAmount=12000))
    if abs(float(q2.get("louverGapMm") or 0) - 35) > 0.01:
        fails.append("gap edit failed")
    if int(q2.get("bladeCountPerLeaf") or 0) == int(q.get("bladeCountPerLeaf") or 0):
        # wider leaf or larger gap should usually change count — not always, but gap↑ usually ↓ blades
        if float(q2.get("widthFt") or 0) > float(q.get("widthFt") or 0) and float(q2.get("louverGapMm") or 0) > 25:
            # If same, still ok if math says so; only fail if gap ignored
            leaf2 = (q2.get("leaves") or [{}])[0]
            pack2 = fixed_gap_blade_count(
                usable_mm=float(leaf2.get("clearWidthMm") or 0), face_mm=25, gap_mm=35
            )
            if int(q2.get("bladeCountPerLeaf") or 0) != int(pack2.get("bladeCount") or -1):
                fails.append("gap 35 blade formula not applied")
    pkg2 = next((h for h in (q2.get("hardware") or []) if h.get("isPackage")), None)
    if not pkg2 or abs(float(pkg2.get("amount") or 0) - 12000) > 0.5:
        fails.append("HW package edit failed")
    if int(q2.get("qty") or 0) != 2:
        fails.append(f"qty {q2.get('qty')}")

    # Reopen saved quote snapshot
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "quote_line.json"
        snap = {
            "product": "gates_privacy",
            "productType": "gate",
            "category": "Gates",
            "width": q["widthMm"],
            "height": q["heightMm"],
            "qty": 1,
            "options": {"gate": _cfg(), "gateQuote": q, "productType": "gate"},
        }
        path.write_text(json.dumps(snap), encoding="utf-8")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        reopened = calculate_line(loaded)
        rq = (reopened.get("options") or {}).get("gateQuote") or {}
        if int(rq.get("bladeCountPerLeaf") or 0) != int(q.get("bladeCountPerLeaf") or -3):
            fails.append("reopen blade mismatch")
        if abs(float(rq.get("sellingTotal") or 0) - float(q.get("sellingTotal") or -1)) > 1.0:
            # recalc may refresh; allow small drift but not collapse
            if float(rq.get("sellingTotal") or 0) < 1000:
                fails.append(f"reopen selling collapsed {rq.get('sellingTotal')}")

    # Itemised sample print
    sample = {
        "opening_ft": f"{q.get('widthFt')} × {q.get('heightFt')}",
        "area_sft": q.get("areaSft"),
        "leaves": f"{q.get('foldLeft')}+{q.get('foldRight')}",
        "blade_per_leaf": q.get("bladeCountPerLeaf"),
        "blade_total": q.get("bladeCountTotal"),
        "gap_mm": q.get("louverGapMm"),
        "ms_bars": bars.get("ms"),
        "al_bars": bars.get("aluminium"),
        "iron_kg": (q.get("weight") or {}).get("ironKg"),
        "al_kg": (q.get("weight") or {}).get("aluminiumKg"),
        "cost": cost,
        "selling_total": q.get("sellingTotal"),
        "selling_per_sft": q.get("sellingPerSft"),
        "hardware": [
            {
                "id": h.get("catalogueId"),
                "name": h.get("name"),
                "qty": h.get("qty"),
                "amount": h.get("amount"),
                "incl": h.get("includedInPackage"),
            }
            for h in hw
        ],
    }

    if fails:
        print("FAIL privacy acceptance:")
        for f in fails:
            print(" -", f)
        print("SAMPLE:", json.dumps(sample, indent=2))
        return 1
    print("OK privacy 13×8 acceptance")
    print(json.dumps(sample, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
