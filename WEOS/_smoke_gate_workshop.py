"""Smoke: grill, fold hinges+handle, walls brick+100, mid pillar, sliding split+track 2W+1ft."""
from __future__ import annotations

from WEOS.factory.gate_engine import MM_PER_FT, compute_gate, gate_svg
from WEOS.factory.structural_catalogue import build_structural_catalogue


def main() -> int:
    fails: list[str] = []
    build_structural_catalogue(persist=True)

    # Fixed grill — mitred hollow frame + grill + both side walls
    qg = compute_gate(
        {
            "widthFt": 13,
            "heightFt": 8,
            "bayType": "fixed_grill",
            "foldLeft": 0,
            "foldRight": 0,
            "grillStyle": "straight",
            "sideWallWidthMm": 230,
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
    if "side_wall_L" not in svg_g or "side_wall_R" not in svg_g:
        fails.append("fixed grill missing side walls")
    if "brick_bed" not in svg_g or "brick_head" not in svg_g:
        fails.append("fixed grill missing running-bond brick hatch")
    wh = float((qg.get("masonry") or {}).get("wallHeightMm") or 0)
    if abs(wh - (qg["heightMm"] + 100)) > 0.6:
        fails.append(f"wall height not H+100: {wh}")

    # Fold — hinges + handles opposite hinge + mid pillar option
    qf = compute_gate(
        {
            "widthFt": 13,
            "heightFt": 8,
            "bayType": "folding_privacy",
            "foldLeft": 2,
            "foldRight": 2,
            "louverGapMm": 25,
            "midPillarEnabled": True,
            "midPillarWidthMm": 300,
            "sideWallWidthMm": 230,
        }
    )
    svg_f = gate_svg({}, qf)
    hinge_n = svg_f.count("data-gate-hinge")
    if hinge_n < 6:
        fails.append(f"fold hinges on svg {hinge_n}")
    if 'data-role="handle"' not in svg_f:
        fails.append("fold missing handle drawing")
    if "mid_pillar" not in svg_f:
        fails.append("fold mid pillar missing on svg")
    if not (qf.get("handles") or []):
        fails.append("fold handles meta empty")
    else:
        h0 = qf["handles"][0]
        if float(h0.get("heightMm") or 0) < float(qf["heightMm"]) * 0.49:
            fails.append(f"handle height too short {h0.get('heightMm')}")
    roles = {c.get("memberRole") for c in qf.get("cuts") or []}
    if "handle" not in roles:
        fails.append("handle not in BOM cuts")

    # Sliding — user split + track 2W+1ft on anti-handle side + wheels@300
    W = 13 * MM_PER_FT
    expect_track = 2 * W + MM_PER_FT
    qs = compute_gate(
        {
            "widthFt": 13,
            "heightFt": 8,
            "bayType": "sliding_gate",
            "foldLeft": 1,
            "foldRight": 1,
            "louverGapMm": 66,
            "trackBarDiaMm": 20,
            "slidingMainWidthMm": 2800,
            "swingLeafWidthMm": 900,
            "handleSide": "R",
            "sideWallWidthMm": 230,
            "msRatePerKg": 215,
            "alRatePerBar": 1459,
        }
    )
    svg_s = gate_svg({}, qs)
    leaves = qs.get("leaves") or []
    if len(leaves) < 2:
        fails.append(f"sliding leafCount {len(leaves)}")
    widths = [float(L.get("outerWidthMm") or 0) for L in leaves]
    if abs(widths[-1] - 900) > 80 and abs(min(widths) - 900) > 80:
        # swing should be near 900 after scale-to-span; allow mid-pillar-less scale
        if not any(abs(w - 900) / 900 < 0.25 for w in widths):
            fails.append(f"swing width not honoured {widths}")
    roles_leaf = {L.get("role") for L in leaves}
    if "swing" not in roles_leaf or "sliding" not in roles_leaf:
        fails.append(f"sliding roles {roles_leaf}")
    track = qs.get("track") or {}
    tlen = float(track.get("lengthMm") or 0)
    if abs(tlen - expect_track) > 1.0:
        fails.append(f"track len {tlen} != 2W+1ft {expect_track}")
    if track.get("pocketSide") != "L" or track.get("handleSide") != "R":
        fails.append(f"track sides {track.get('pocketSide')} / {track.get('handleSide')}")
    if float(track.get("x0Mm") or 0) > -100:
        fails.append(f"track should extend left of opening x0={track.get('x0Mm')}")
    if 'data-inset-mm="300"' not in svg_s:
        fails.append("wheel inset 300 missing")
    if "track_c_channel" not in svg_s or "track_round_bar" not in svg_s:
        fails.append("sliding track visuals missing")
    if "side_wall_L" not in svg_s or "side_wall_R" not in svg_s:
        fails.append("sliding missing side walls")
    if 'data-role="handle"' not in svg_s:
        fails.append("sliding missing handle")
    cut_roles = {c.get("memberRole") for c in qs.get("cuts") or []}
    if "track_c_channel" not in cut_roles or "track_round_bar" not in cut_roles:
        fails.append(f"track cuts missing {cut_roles}")
    if float((qs.get("weight") or {}).get("ironKg") or 0) < 50:
        fails.append(f"sliding iron kg too low {qs.get('weight')}")

    if fails:
        print("FAIL gate workshop:")
        for f in fails:
            print(" -", f)
        return 1
    print(
        "OK gate workshop · "
        f"walls H+100={wh:g} · fold hinges={hinge_n} handles={len(qf.get('handles') or [])} · "
        f"slide track={tlen:g} pocket={track.get('pocketSide')} widths={[round(w) for w in widths]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
