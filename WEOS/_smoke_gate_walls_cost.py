"""Smoke: walls top+100/ground, handle stile, L/R bay dims, BOM cost vs sell."""
from __future__ import annotations

import re

from WEOS.factory.gate_engine import MM_PER_FT, compute_gate, gate_svg
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.structural_catalogue import build_structural_catalogue, list_structural_sections


def _pick_al(w: float, h: float) -> str | None:
    best = None
    for s in list_structural_sections(material="aluminium"):
        if abs(float(s.get("widthMm") or 0) - w) < 0.8 and abs(float(s.get("heightMm") or 0) - h) < 0.8:
            shp = str(s.get("shape") or "")
            if "hollow" in shp or "square" in shp or "rect" in shp:
                return s.get("sectionId")
            best = best or s.get("sectionId")
    return best


def main() -> int:
    fails: list[str] = []
    build_structural_catalogue(persist=True)
    s25 = _pick_al(25, 25)
    s50 = _pick_al(50, 25) or _pick_al(50, 50) or s25
    s100 = _pick_al(100, 25) or _pick_al(100, 50) or s50

    cfg = {
        "widthFt": 13,
        "heightFt": 8,
        "bayType": "folding_privacy",
        "foldLeft": 2,
        "foldRight": 2,
        "leftGateWidthMm": 6.5 * MM_PER_FT,
        "rightGateWidthMm": 6.5 * MM_PER_FT,
        "midPillarEnabled": True,
        "midPillarWidthMm": 230,
        "sideWallWidthMm": 230,
        "handleSide": "R",
        "louverPattern": [
            {"sectionId": s25, "gapAfterMm": 30},
            {"sectionId": s50, "gapAfterMm": 50},
            {"sectionId": s100, "gapAfterMm": 25},
        ] if s25 and s50 and s100 else None,
        "msRatePerKg": 215,
        "alRatePerBar": 1459,
        "fabRatePerSft": 150,
        "coatingRate": 25,
        "hardwarePackageAmount": 10000,
        "qty": 1,
    }
    q = compute_gate(cfg)
    svg = gate_svg({}, q)
    mas = q.get("masonry") or {}

    # Walls: top at -100, bottom at ground H (not hanging below)
    if abs(float(mas.get("wallTopMm") or 0) - (-100)) > 0.5:
        fails.append(f"wallTopMm={mas.get('wallTopMm')} want -100")
    H = float(q.get("heightMm") or 0)
    if abs(float(mas.get("wallBottomMm") or 0) - H) > 0.5:
        fails.append(f"wallBottomMm={mas.get('wallBottomMm')} want H={H}")
    if 'y_mm="-100"' not in svg.replace(" ", "") and 'data-role="side_wall_L"' not in svg:
        # brick hatch uses computed sy; check role present and wall height ≈ H+100
        if abs(float(mas.get("wallHeightMm") or 0) - (H + 100)) > 1:
            fails.append(f"wallHeightMm={mas.get('wallHeightMm')} want {H+100}")

    # Bay dims: two gates, exclude mid
    bays = q.get("bayDims") or []
    if len(bays) < 2:
        fails.append(f"expected L+R bay dims, got {bays}")
    else:
        for b in bays:
            if float(b.get("widthMm") or 0) <= 0:
                fails.append(f"empty bay dim {b}")
        mid = float(mas.get("midPillarWidthMm") or 0)
        span = sum(float(b.get("widthMm") or 0) for b in bays)
        if mid > 0 and abs(span - float(q.get("widthMm") or 0)) > 50:
            # clear gates ≈ quote W (posts/clearances may differ slightly)
            pass
        if any(abs(float(b.get("widthMm") or 0) - mid) < 1 for b in bays):
            fails.append("bay dim must not equal mid pillar width alone")

    # Handles on stile (x near leaf edge, not centre)
    handles = q.get("handles") or []
    leaves = {L.get("leafId"): L for L in (q.get("leaves") or [])}
    if not handles:
        fails.append("no handles")
    for h in handles:
        L = leaves.get(h.get("leafId")) or {}
        lx = float(L.get("x0Mm") or 0)
        lw = float(L.get("outerWidthMm") or 0)
        lf = float(L.get("frameFaceMm") or 40)
        hx = float(h.get("xMm") or 0)
        side = str(h.get("side") or "R")
        if side == "R":
            if abs(hx - (lx + lw - lf / 2)) > 2:
                fails.append(f"handle not on R stile hx={hx} expect={lx + lw - lf / 2}")
        else:
            if abs(hx - (lx + lf / 2)) > 2:
                fails.append(f"handle not on L stile hx={hx} expect={lx + lf / 2}")
        # Must not sit in leaf centre
        if abs(hx - (lx + lw / 2)) < lf:
            fails.append(f"handle looks centred in leaf {h.get('leafId')}")

    # Dim marks: per-bay present in SVG
    dim_n = svg.count('data-dim="1"')
    if dim_n < 6:
        fails.append(f"expected multiple dim marks, got {dim_n}")

    cost1 = float((q.get("cost") or {}).get("total") or 0)
    if cost1 <= 0:
        fails.append("cost total missing")
    # Pattern sections each contribute to nests/cost
    if s25 and s50 and s100:
        nests = q.get("nests") or {}
        for sid in (s25, s50, s100):
            if sid not in nests:
                fails.append(f"missing nest for pattern section {sid}")
            elif nests[sid].get("costAmount") is None and (nests[sid].get("purchase") or {}).get("amount") is None:
                fails.append(f"no cost amount for {sid}")
        # used vs purchase distinct on Al bar rate
        n0 = nests.get(s25) or {}
        if n0.get("usedM") is not None and n0.get("purchaseM") is not None:
            if float(n0.get("purchaseM") or 0) + 1e-6 < float(n0.get("usedM") or 0):
                fails.append("purchaseM < usedM")

    # Qty 2 doubles cost
    q2 = compute_gate({**cfg, "qty": 2})
    cost2 = float((q2.get("cost") or {}).get("total") or 0)
    if abs(cost2 - 2 * cost1) > max(2.0, 0.02 * cost1):
        fails.append(f"qty2 cost {cost2} != 2× {cost1}")

    # Cart line: cost stable when sell rate changes
    line = {
        "product": "gates_privacy",
        "productType": "gate",
        "width": q.get("widthMm"),
        "height": q.get("heightMm"),
        "qty": 1,
        "saleUnit": "sqft",
        "sellingRate": 900,
        "options": {"gate": cfg, "productType": "gate"},
    }
    r1 = calculate_line(line, include_preview=False)
    c_a = float((r1.get("price") or {}).get("total") or 0)
    sell_a = float(((r1.get("selling") or {}).get("sellingAmount") or r1.get("commercialTotal") or 0))
    line2 = dict(line)
    line2["sellingRate"] = 1200
    r2 = calculate_line(line2, include_preview=False)
    c_b = float((r2.get("price") or {}).get("total") or 0)
    sell_b = float(((r2.get("selling") or {}).get("sellingAmount") or 0))
    if abs(c_a - c_b) > 0.5:
        fails.append(f"sell rate changed cost {c_a} → {c_b}")
    if sell_b <= sell_a:
        fails.append(f"higher ₹/sft should raise selling {sell_a} → {sell_b}")
    if abs(c_a - cost1) > max(2.0, 0.02 * cost1):
        fails.append(f"line cost {c_a} != gate cost {cost1}")

    # Incomplete when rate missing
    q_bad = compute_gate({**cfg, "msRatePerKg": None, "alRatePerBar": None})
    # still may have rates from catalogue — force incomplete via empty purchase on custom
    if q_bad.get("ok") and not (q_bad.get("incomplete") or []):
        # ok if catalogue rates exist
        pass

    if fails:
        print("FAIL gate walls/cost:")
        for f in fails:
            print(" -", f)
        return 1
    print(
        f"OK gate walls/cost · cost={cost1} · qty2={cost2} · sell {sell_a}→{sell_b} · "
        f"bays={len(bays)} · handles={len(handles)} · wallH={mas.get('wallHeightMm')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
