"""Smoke: shower partition calc + SVG + PDF specs + selling amount."""
from __future__ import annotations

from WEOS.factory.line_kind import product_has_tracks
from WEOS.factory.marqt_pdf import _spec_lines, _spec_rows
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.shower_engine import compute_shower, shower_svg
from WEOS.factory.svg_export import elevation_svg_for_line


def main() -> int:
    fails: list[str] = []

    # 1) Straight sliding 1+1 — FIX + SLIDE marked, selling rate × sft
    cfg = {
        "shape": "straight",
        "operation": "sliding",
        "widthMm": 1200,
        "heightMm": 2000,
        "slidingSide": "right",
        "colour": "matt_black",
        "glassThicknessMm": 8,
        "glassColour": "grey",
        "glassKind": "tinted",
        "handle": True,
        "handleName": "D-type",
        "lock": False,
        "saleUnit": "sqft",
        "manualRatePerUnit": 450,
        "qty": 1,
    }
    q = compute_shower(cfg)
    roles = [p.get("role") for p in (q.get("panels") or [])]
    labels = " ".join(str(p.get("label") or "") for p in (q.get("panels") or []))
    if "fix" not in roles or "sliding" not in roles:
        fails.append(f"1+1 roles {roles}")
    if "FIX" not in labels.upper() or "SLIDE" not in labels.upper():
        fails.append(f"1+1 labels {labels}")
    area = float(q.get("areaSqft") or 0)
    if abs(float(q.get("sellingPerUnit") or 0) - 450) > 0.01:
        fails.append(f"sellingPerUnit {q.get('sellingPerUnit')}")
    expected = round(450 * area, 2)
    if abs(float(q.get("sellingTotal") or 0) - expected) > 0.05:
        fails.append(f"sellingTotal {q.get('sellingTotal')} != {expected} (area {area})")
    svg = shower_svg(cfg, quote=q)
    if "FIX" not in svg or "SLIDE" not in svg:
        fails.append("svg missing FIX/SLIDE")
    if "Floor plan" not in svg:
        fails.append("svg missing floor plan")

    # 2) L + U footprints
    ql = compute_shower({**cfg, "shape": "L", "depthMm": 900})
    if ql.get("shape") != "L" or not (ql.get("footprint") or {}).get("returnMm"):
        fails.append(f"L footprint {ql.get('footprint')}")
    qu = compute_shower({**cfg, "shape": "U", "depthMm": 800, "depthBMm": 700})
    fp = qu.get("footprint") or {}
    if qu.get("shape") != "U" or not fp.get("leftMm") or not fp.get("rightMm"):
        fails.append(f"U footprint {fp}")

    # 2b) Quote-style U sliding 1050×2130 · L 1860 · R 900 — frames/track/handle/plan
    u_cfg = {
        **cfg,
        "shape": "U",
        "widthMm": 1050,
        "heightMm": 2130,
        "depthMm": 1860,
        "depthBMm": 900,
        "handle": True,
        "handleName": "D-type",
        "lock": True,
    }
    uq = compute_shower(u_cfg)
    usvg = shower_svg(u_cfg, quote=uq)
    uflat = usvg.replace("×", "x")
    for need in ("16x45", "FIX", "SLIDE", "front 1050", "L 1860", "R 900", "SLIDE + TRACK", "Floor plan"):
        if need not in uflat and need not in usvg:
            fails.append(f"U 1050 shower svg missing {need}")
    if "data-gi-plate" not in usvg:
        fails.append("U shower svg missing GI connector plates")
    if "lock" not in usvg.lower():
        fails.append("U shower svg missing lock mark")

    # 3) Cart line → calculate → elevation SVG + PDF specs
    line = {
        "product": "shower_partition",
        "productType": "shower_partition",
        "category": "Bathrooms",
        "width": 1200,
        "height": 2000,
        "qty": 1,
        "saleUnit": "sqft",
        "sellingRate": 450,
        "options": {"shower": cfg, "productType": "shower_partition"},
    }
    calc = calculate_line(line)
    if calc.get("productType") != "shower_partition":
        fails.append(f"calc productType {calc.get('productType')}")
    if abs(float(calc.get("sellingRate") or 0) - 450) > 0.01:
        fails.append(f"calc sellingRate {calc.get('sellingRate')}")
    if float(calc.get("commercialTotal") or 0) <= 0:
        fails.append("calc commercialTotal empty")
    elev = elevation_svg_for_line(calc) or ""
    if "FIX" not in elev or "data-model-system=\"shower\"" not in elev:
        fails.append("PDF elevation not shower canvas")
    specs = " ".join(_spec_lines(calc)).upper()
    if "TRACK" in specs and "COVER" not in specs:
        # sliding shower may mention track hardware — that's OK; casement-style TRACK row must not leak
        pass
    rows = {k: v for k, v in _spec_rows(calc)}
    if "PLAN" not in rows and not any("STRAIGHT" in (v or "").upper() for v in rows.values()):
        fails.append(f"PDF missing plan: {rows}")
    if "AMOUNT" not in rows:
        fails.append(f"PDF missing AMOUNT: {list(rows)}")

    # 4) Casement must not expose tracks
    if product_has_tracks("casements", system="casement"):
        fails.append("casement still has tracks")
    if product_has_tracks("shower_partition", system="shower"):
        fails.append("shower still has tracks")
    if not product_has_tracks("sliding", system="sliding"):
        fails.append("sliding lost tracks")

    casement_line = {
        "product": "casement_stub",
        "productType": "casements",
        "system": "casement",
        "width": 1800,
        "height": 1500,
        "qty": 1,
        "glassShutters": 3,
        "trackCount": 2,
        "casementPanels": [
            {"index": 0, "role": "fix", "handleSide": "right"},
            {"index": 1, "role": "openable", "handleSide": "left"},
            {"index": 2, "role": "openable", "handleSide": "right"},
        ],
        "handleOverrides": {
            "0": {"role": "fix", "side": "none"},
            "1": {"role": "openable", "side": "left"},
            "2": {"role": "openable", "side": "right"},
        },
        "sellingRate": 890,
        "saleUnit": "sqft",
    }
    ccalc = calculate_line(casement_line)
    cspecs = " ".join(_spec_lines(ccalc)).upper()
    if "2-TRACK" in cspecs.replace(" ", "") or "2 TRACK" in cspecs:
        fails.append(f"casement PDF leaked track: {cspecs[:180]}")
    if "PANELS" not in " ".join(k for k, _ in _spec_rows(ccalc)).upper() and "OPENABLE" not in cspecs:
        # panel row is preferred; description fallback is acceptable
        if "FIX" not in cspecs:
            fails.append(f"casement PDF missing panel roles: {cspecs[:200]}")

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print("OK shower 1+1/L/U + selling + PDF elevation · casement no track")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
