"""Comprehensive tests for WEOS Universal Material Weight Engine.

Run:  python -m WEOS._test_weight_engine
"""

from __future__ import annotations

import sys
import traceback

_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        _RESULTS.append((name, True, str(detail)))
        line = f"PASS  {name}: {detail}"
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode("ascii"))
    except Exception as exc:  # noqa: BLE001
        _RESULTS.append((name, False, f"{exc}"))
        try:
            print(f"FAIL  {name}: {exc}")
        except UnicodeEncodeError:
            print(f"FAIL  {name}: {exc!r}")
        traceback.print_exc()


def _glass(thk: float):
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "glass",
        dimensions={"widthMm": 1000, "heightMm": 1000, "thicknessMm": thk},
        quantity=1,
    )
    assert r["ok"], r
    assert r["weightSource"] == "calculated", r
    expected = 1.0 * (thk / 1000.0) * 2500.0
    assert abs(r["totalWeight"] - expected) < 0.01, (r["totalWeight"], expected)
    assert "areaM2" in (r.get("formula") or "") or "density" in (r.get("formula") or "")
    return f"{thk}mm = {r['totalWeight']} kg [{r['sourceLabel']}]"


def t_glass_5():
    return _glass(5)


def t_glass_8():
    return _glass(8)


def t_glass_10():
    return _glass(10)


def t_dgu():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "glass_dgu",
        dimensions={"widthMm": 1000, "heightMm": 1000, "layersMm": [6, 6]},
        quantity=1,
    )
    assert r["ok"], r
    # 12mm glass total → 30 kg
    assert 29.5 <= r["totalWeight"] <= 30.5, r
    assert r["weightSource"] == "calculated"
    return f"DGU 6+6 = {r['totalWeight']} kg"


def t_laminated():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "glass_laminated",
        dimensions={"widthMm": 1000, "heightMm": 1000, "layersMm": [5, 5], "pvbMm": 1.52},
        quantity=1,
    )
    assert r["ok"], r
    # 10mm glass = 25 + PVB 1.52mm * 1070 ≈ 1.626 → ~26.63
    assert 25.5 <= r["totalWeight"] <= 27.5, r
    assert "pvb" in (r.get("formula") or "").lower() or "PVB" in str(r.get("why"))
    return f"laminated 5+1.52+5 = {r['totalWeight']} kg"


def t_al_sheet():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "aluminium_sheet",
        dimensions={"widthMm": 1000, "heightMm": 1000, "thicknessMm": 2},
        quantity=1,
        waste_factor=1.05,
    )
    assert r["ok"], r
    # 2mm * 1m² * 2700 = 5.4 kg theoretical
    assert abs(r["theoreticalWeight"] - 5.4) < 0.01, r
    assert abs(r["totalWeight"] - 5.4) < 0.01, r  # theoretical not mixed with waste
    assert abs(r["effectiveWeight"] - 5.4 * 1.05) < 0.01, r
    assert r["weightSource"] == "calculated"
    return f"Al sheet 2mm = theo {r['theoreticalWeight']} / eff {r['effectiveWeight']}"


def t_steel_sheet():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "mild_steel",
        dimensions={"widthMm": 1000, "heightMm": 1000, "thicknessMm": 1},
        quantity=1,
        waste_factor=None,
    )
    assert r["ok"], r
    assert abs(r["totalWeight"] - 7.85) < 0.01, r
    return f"1mm MS = {r['totalWeight']} kg"


def t_profile_kg_m():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "aluminium_profile",
        dimensions={"lengthMm": 2000},
        quantity=3,
        weight_per_meter=1.25,
        weight_source="catalogue",
    )
    assert r["ok"], r
    # 1.25 kg/m × 2m × 3 = 7.5
    assert abs(r["totalWeight"] - 7.5) < 0.01, r
    assert r["weightSource"] == "catalogue"
    assert "weightPerMeter" in (r.get("formula") or "")
    return f"profile kg/m = {r['totalWeight']} kg [{r['sourceLabel']}]"


def t_profile_cross_section():
    from WEOS.factory.weight_engine import calculate_material_weight

    # 500 mm² × 2700 / 1e6 = 1.35 kg/m × 1m = 1.35
    r = calculate_material_weight(
        "aluminium_profile",
        dimensions={"lengthMm": 1000, "crossSectionAreaMm2": 500},
        quantity=1,
        density=2700,
    )
    assert r["ok"], r
    assert abs(r["totalWeight"] - 1.35) < 0.01, r
    assert r["weightSource"] == "calculated"
    return f"profile from CSA = {r['totalWeight']} kg"


def t_hardware_pcs():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "hardware",
        dimensions={"weightPerUnit": 0.35},
        quantity=4,
        unit="pcs",
        weight_source="catalogue",
    )
    assert r["ok"], r
    assert abs(r["totalWeight"] - 1.4) < 0.01, r
    return f"hardware 4pcs = {r['totalWeight']} kg"


def t_hardware_kg_unit():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight("hardware", quantity=2.5, unit="kg", weight_source="manual")
    assert r["ok"], r
    assert abs(r["totalWeight"] - 2.5) < 0.01, r
    return f"hardware unit=kg qty=2.5 = {r['totalWeight']}"


def t_hardware_meter():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "hardware",
        dimensions={"lengthM": 3, "weightPerMeter": 0.2},
        quantity=2,
        unit="meter",
    )
    assert r["ok"], r
    assert abs(r["totalWeight"] - 1.2) < 0.01, r
    return f"hardware meter = {r['totalWeight']} kg"


def t_hardware_missing():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight("hardware", quantity=2, unit="pcs")
    assert not r["ok"], r
    assert r["weightSource"] == "unknown"
    assert r["weightStatus"] == "needs_catalogue"
    return "hardware without weight = Missing / needs_catalogue"


def t_missing_glass_no_thk():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "glass",
        dimensions={"widthMm": 1000, "heightMm": 1000},
        quantity=1,
    )
    assert not r["ok"], r
    assert r["weightStatus"] == "calculable"
    assert r["missingHints"]
    return f"glass no thickness = {r['weightStatus']}"


def t_catalogue_beats_calc():
    from WEOS.factory.weight_engine import calculate_material_weight

    r = calculate_material_weight(
        "glass",
        dimensions={"widthMm": 1000, "heightMm": 1000, "thicknessMm": 5},
        quantity=1,
        weight_per_unit=99.0,
        weight_source="catalogue",
    )
    assert r["ok"] and abs(r["totalWeight"] - 99.0) < 0.01, r
    assert r["weightSource"] == "catalogue"
    return "catalogue priority over calculated dims"


def t_learned_not_auto():
    from WEOS.factory.weight_engine import calculate_material_weight, propose_learned_weight_candidate

    r = calculate_material_weight(
        "hardware",
        quantity=1,
        unit="pcs",
        learned_weight=0.5,
        learned_approved=False,
    )
    assert not r["ok"], r
    assert r["why"].get("learnedCandidateKg") == 0.5 or any(
        "learned" in h.lower() for h in (r.get("missingHints") or [])
    )
    cand = propose_learned_weight_candidate(material="roller", weight_kg=0.5, source_doc="quote.pdf")
    assert cand["autoApproved"] is False
    assert cand["status"] == "candidate"
    return "learned never auto-approved"


def t_mixed_bom_and_product_total():
    from WEOS.factory.weight_engine import analyze_missing_weights, sum_product_weights

    bom = [
        {
            "name": "Glass 8mm",
            "material": "glass",
            "category": "glass",
            "widthMm": 1000,
            "heightMm": 1000,
            "thicknessMm": 8,
            "quantity": 1,
        },
        {
            "name": "Outer",
            "material": "aluminium_profile",
            "category": "profile",
            "lengthMm": 1000,
            "weightPerMeter": 1.0,
            "weightSource": "catalogue",
            "quantity": 1,
        },
        {"name": "Handle", "material": "hardware", "category": "hardware", "quantity": 2, "unit": "pcs"},
    ]
    product = sum_product_weights(bom, critical_unknown_blocks_total=False)
    assert product["knownCount"] == 2, product
    assert product["unknownCount"] == 1, product
    # 20 + 1 = 21
    assert abs(product["knownWeightKg"] - 21.0) < 0.05, product

    report = analyze_missing_weights(bom)
    assert report["missingCount"] == 1
    assert report["needsCatalogueCount"] >= 1
    assert "⚠️" in report["summary"]
    assert "catalogue" in report["summary"].lower()
    return f"mixed BOM known={product['knownWeightKg']}kg; {report['summary']}"


def t_product_total_blocked():
    from WEOS.factory.weight_engine import sum_product_weights

    bom = [
        {"name": "Frame", "material": "aluminium_profile", "category": "profile", "quantity": 1},
        {
            "name": "Glass",
            "material": "glass",
            "category": "glass",
            "widthMm": 500,
            "heightMm": 500,
            "thicknessMm": 5,
            "quantity": 1,
        },
    ]
    product = sum_product_weights(bom, critical_unknown_blocks_total=True)
    assert product["totalWeight"] is None, product
    assert product["ok"] is False
    return "critical unknown blocks product total"


def t_ss_acp_hpl_pc():
    from WEOS.factory.weight_engine import calculate_material_weight

    ss = calculate_material_weight(
        "stainless",
        dimensions={"widthMm": 1000, "heightMm": 1000, "thicknessMm": 1},
    )
    assert ss["ok"] and abs(ss["totalWeight"] - 8.0) < 0.05, ss

    acp = calculate_material_weight(
        "acp",
        dimensions={"widthMm": 1000, "heightMm": 1000, "thicknessMm": 4},
    )
    assert acp["ok"] and 5.0 <= acp["totalWeight"] <= 6.5, acp

    hpl = calculate_material_weight(
        "hpl",
        dimensions={"widthMm": 1000, "heightMm": 1000, "thicknessMm": 6},
    )
    assert hpl["ok"] and abs(hpl["totalWeight"] - 8.4) < 0.05, hpl  # 1*0.006*1400

    pc = calculate_material_weight(
        "polycarbonate",
        dimensions={"widthMm": 1000, "heightMm": 1000, "thicknessMm": 5},
    )
    assert pc["ok"] and abs(pc["totalWeight"] - 6.0) < 0.05, pc  # 1*0.005*1200

    # thickness missing → unknown (no guessing)
    bare = calculate_material_weight("ss", dimensions={"widthMm": 1000, "heightMm": 1000})
    assert not bare["ok"], bare
    return f"SS={ss['totalWeight']} ACP={acp['totalWeight']} HPL={hpl['totalWeight']} PC={pc['totalWeight']}"


def t_legacy_compute_weight():
    from WEOS.factory.job_types import GlassPane
    from WEOS.factory.weight_engine import WEIGHT_SOURCE_GLASS_UPLIFT, compute_weight

    glass = [GlassPane(name="g", width_mm=1000, height_mm=1000, thickness_mm=5, area_m2=1.0, weight_kg=12.5, quantity=1)]
    rules = {
        "aluminiumDensityKgPerM3": 2700,
        "wasteFactor": 1.0,
        "hardwareAllowanceKg": 0.5,
        "profileSections": [
            {"name": "outer", "crossSectionAreaMm2": 500, "lengthFormula": "1000"},
        ],
    }
    wb = compute_weight(rules, glass, {})
    # No catalogue kg/m → glass + 20% frame/hw (do not invent hardwareAllowanceKg)
    assert abs(wb.glass_kg - 12.5) < 0.05, wb
    assert abs(wb.aluminium_kg - 2.5) < 0.05, wb
    assert abs(wb.hardware_kg - 0.0) < 0.01, wb
    assert abs(wb.total_kg - 15.0) < 0.08, wb
    assert wb.weight_source == WEIGHT_SOURCE_GLASS_UPLIFT, wb
    return f"uplift compute_weight total={wb.total_kg} src={wb.weight_source}"


def t_catalogue_kg_m_weight():
    from WEOS.factory.job_types import GlassPane
    from WEOS.factory.weight_engine import WEIGHT_SOURCE_CATALOGUE, compute_weight

    glass = [GlassPane(name="g", width_mm=1000, height_mm=1000, thickness_mm=5, area_m2=1.0, weight_kg=12.5, quantity=1)]
    rules = {
        "aluminiumDensityKgPerM3": 2700,
        "wasteFactor": 1.0,
        "profileSections": [
            {"name": "outer", "weightPerMeter": 0.8, "lengthFormula": "2000"},
        ],
    }
    wb = compute_weight(rules, glass, {})
    assert wb.weight_source == WEIGHT_SOURCE_CATALOGUE, wb
    assert abs(wb.aluminium_kg - 1.6) < 0.05, wb  # 2.0 m × 0.8 kg/m
    assert abs(wb.glass_kg - 12.5) < 0.05, wb
    return f"catalogue kg/m alu={wb.aluminium_kg}"


def t_upvc_no_uplift():
    from WEOS.factory.job_types import GlassPane
    from WEOS.factory.weight_engine import WEIGHT_SOURCE_GLASS_ONLY, compute_weight

    glass = [GlassPane(name="g", width_mm=1000, height_mm=1000, thickness_mm=5, area_m2=1.0, weight_kg=12.5, quantity=1)]
    rules = {"aluminiumDensityKgPerM3": 2700, "profileSections": []}
    wb = compute_weight(rules, glass, {}, frame_material="upvc")
    assert abs(wb.aluminium_kg) < 0.01, wb
    assert abs(wb.glass_kg - 12.5) < 0.05, wb
    assert wb.weight_source == WEIGHT_SOURCE_GLASS_ONLY, wb
    return f"upvc glass-only {wb.total_kg}"


def main() -> int:
    for name, fn in [
        ("Glass 5mm", t_glass_5),
        ("Glass 8mm", t_glass_8),
        ("Glass 10mm", t_glass_10),
        ("DGU 6+6", t_dgu),
        ("Laminated", t_laminated),
        ("Al sheet + waste split", t_al_sheet),
        ("Steel sheet", t_steel_sheet),
        ("Profile kg/m catalogue", t_profile_kg_m),
        ("Profile cross-section", t_profile_cross_section),
        ("Hardware pcs", t_hardware_pcs),
        ("Hardware kg unit", t_hardware_kg_unit),
        ("Hardware meter", t_hardware_meter),
        ("Hardware missing", t_hardware_missing),
        ("Missing glass thickness", t_missing_glass_no_thk),
        ("Catalogue priority", t_catalogue_beats_calc),
        ("Learned not auto-applied", t_learned_not_auto),
        ("Mixed BOM + agent summary", t_mixed_bom_and_product_total),
        ("Product total blocked", t_product_total_blocked),
        ("SS/ACP/HPL/PC", t_ss_acp_hpl_pc),
        ("Legacy compute_weight", t_legacy_compute_weight),
        ("Catalogue kg/m weight", t_catalogue_kg_m_weight),
        ("UPVC no 20% uplift", t_upvc_no_uplift),
    ]:
        check(name, fn)

    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    print(f"\n{'='*60}\nWEIGHT ENGINE: {passed}/{total} passed")
    failed = [n for n, ok, _ in _RESULTS if not ok]
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
