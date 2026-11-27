"""Smoke: fixed grill geometry, fold hinges, sliding wheels@300 + track weight."""
from __future__ import annotations


from WEOS.factory.gate_engine import compute_gate, gate_svg
from WEOS.factory.structural_catalogue import build_structural_catalogue


def main() -> int:
    fails: list[str] = []
    build_structural_catalogue(persist=True)

    # Fixed grill — mitred hollow frame + grill bars on canvas
    qg = compute_gate(
        {
            "widthFt": 13,
            "heightFt": 8,
            "bayType": "fixed_grill",
            "foldLeft": 0,
            "foldRight": 0,
            "grillStyle": "straight",
            "msRatePerKg": 215,
            "msBarWeightKg": 25,
            "msStockFt": 20,
            "fabRatePerSft": 150,
            "hardwarePackageAmount": 10000,
        }
    )
    svg_g = gate_svg({}, qg)
    if 'data-mitre="1"' not in svg_g:
        fails.append("fixed grill missing mitre geometry")
    if "grill_bar" not in svg_g and "grill_diagonal" not in svg_g:
        fails.append("fixed grill missing interior grill members")
    if int((qg.get("grill") or {}).get("bladeCount") or 0) < 2:
        fails.append(f"grill bladeCount {qg.get('grill')}")
    if int((qg.get("bars") or {}).get("ms") or 0) < 1:
        fails.append("fixed grill MS bars missing")

    # Fold — hinges wall+interleaf on elevation
    qf = compute_gate(
        {
            "widthFt": 13,
            "heightFt": 8,
            "bayType": "folding_privacy",
            "foldLeft": 2,
            "foldRight": 2,
            "louverGapMm": 25,
        }
    )
    svg_f = gate_svg({}, qf)
    hinge_n = svg_f.count("data-gate-hinge")
    if hinge_n < 6:
        fails.append(f"fold hinges on svg {hinge_n}")
    joints = (qf.get("hinges") or {}).get("joints") or []
    kinds = {j.get("kind") for j in joints if isinstance(j, dict)}
    if "wall_leaf" not in kinds or "leaf_leaf" not in kinds:
        fails.append(f"hinge joint kinds {kinds}")

    # Sliding — wheels @300 mm + track cuts in cost
    qs = compute_gate(
        {
            "widthFt": 13,
            "heightFt": 8,
            "bayType": "sliding_gate",
            "foldLeft": 1,
            "foldRight": 1,
            "louverGapMm": 66,
            "trackBarDiaMm": 20,
            "msRatePerKg": 215,
            "alRatePerBar": 1459,
        }
    )
    svg_s = gate_svg({}, qs)
    if qs.get("leafCount") != 2:
        fails.append(f"sliding leafCount {qs.get('leafCount')}")
    wheel_n = svg_s.count('data-role="wheel"')
    if wheel_n < 4:
        fails.append(f"wheels {wheel_n}")
    if 'data-inset-mm="300"' not in svg_s:
        fails.append("wheel inset 300 missing")
    if "track_c_channel" not in svg_s or "track_round_bar" not in svg_s:
        fails.append("sliding track visuals missing")
    roles = {c.get("memberRole") for c in qs.get("cuts") or []}
    if "track_c_channel" not in roles or "track_round_bar" not in roles:
        fails.append(f"track cuts missing {roles}")
    if float((qs.get("weight") or {}).get("ironKg") or 0) < 50:
        fails.append(f"sliding iron kg too low {qs.get('weight')}")
    if 'data-mitre="1"' not in svg_s:
        fails.append("sliding missing mitres")

    if fails:
        print("FAIL gate workshop:")
        for f in fails:
            print(" -", f)
        return 1
    print(
        "OK gate workshop · "
        f"grill bars={(qg.get('grill') or {}).get('bladeCount')} "
        f"fold hinges={hinge_n} "
        f"slide wheels={wheel_n} "
        f"ironKg={(qs.get('weight') or {}).get('ironKg')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
