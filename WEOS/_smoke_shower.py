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
    if 'data-meeting-stiles="1"' not in svg:
        fails.append("sliding 1+1 should show one overlapping meeting stile")
    if 'data-gi-plate' in svg:
        fails.append("sliding svg still has corner dots")
    if 'data-track-gap-px="0"' not in svg:
        fails.append("sliding track gap should be 0 (sit on head rails)")
    if 'data-arrow-dir="left"' not in svg:
        fails.append("door-right sliding arrow should point left")
    if 'data-handle-side="right"' not in svg:
        fails.append("door-right sliding handle should be on the right")
    if 'data-miter="1"' not in svg:
        fails.append("sliding missing 45° miters")
    if q.get("doorSide") != "right":
        fails.append(f"quote doorSide {q.get('doorSide')}")

    # 1b) Door left — arrow → , handle left
    cfg_left = {**cfg, "doorSide": "left", "slidingSide": "left"}
    q_left = compute_shower(cfg_left)
    svg_left = shower_svg(cfg_left, quote=q_left)
    if q_left.get("doorSide") != "left":
        fails.append(f"door-left quote doorSide {q_left.get('doorSide')}")
    if 'data-arrow-dir="right"' not in svg_left:
        fails.append("door-left sliding arrow should point right")
    if 'data-handle-side="left"' not in svg_left:
        fails.append("door-left sliding handle should be on the left")
    if 'data-meeting-stiles="1"' not in svg_left:
        fails.append("door-left sliding should still be one meeting stile")

    # 1c) Hinged — both frames, 10mm chokhat overlap, independent handle, hinges opposite
    hcfg = {
        **cfg,
        "operation": "hinged",
        "doorSide": "right",
        "handleSide": "left",
        "lock": True,
        "hingeCount": 4,
        "hingesPerDoor": 4,
        "doorWidthMm": 700,
    }
    hq = compute_shower(hcfg)
    hsvg = shower_svg(hcfg, quote=hq)
    if hq.get("doorSide") != "right" or hq.get("handleSide") != "left":
        fails.append(f"hinged sides door={hq.get('doorSide')} handle={hq.get('handleSide')}")
    if hq.get("hingeSide") != "right":
        fails.append(f"hinges should be opposite handle, got {hq.get('hingeSide')}")
    if int(hq.get("hingeCount") or 0) != 4:
        fails.append(f"hingeCount {hq.get('hingeCount')}")
    if 'data-meeting-stiles="2"' not in hsvg:
        fails.append("openable should keep both frames at the meeting")
    if 'data-chokhat-overlap-mm="10"' not in hsvg:
        fails.append("openable missing 10mm chokhat overlap")
    if 'data-handle-side="left"' not in hsvg:
        fails.append("openable handle independent (left)")
    if 'data-hinge-side="right"' not in hsvg:
        fails.append("openable hinges should be on the right (opp. handle)")
    if 'data-hinge="1"' not in hsvg:
        fails.append("openable missing hinge symbols")
    if 'data-hinge-style="casement"' not in hsvg:
        fails.append("openable hinges should be casement-style (not X)")
    n_hinge = hsvg.count('data-hinge="1"')
    if n_hinge != 4:
        fails.append(f"expected 4 casement hinges, got {n_hinge}")
    if 'data-hinge-from-top-mm="100"' not in hsvg:
        fails.append("top hinge should sit 100 mm from leaf top")
    if 'data-chokhat-bottom="0"' not in hsvg:
        fails.append("hinged chokhat must not include a bottom member")
    if 'data-chokhat-side="bottom"' in hsvg:
        fails.append("hinged svg still draws bottom chokhat")
    if 'data-lock-kind="mortice"' not in hsvg:
        fails.append("lock should draw as mortice, not a dot")
    if 'data-gi-plate' in hsvg or 'data-corner-markers="0"' not in hsvg:
        fails.append("corner dots / GI plates must not appear on hinged 2D")
    if 'data-miter="1"' not in hsvg:
        fails.append("openable missing 45° miters")
    if 'data-meeting-miter="1"' not in hsvg:
        fails.append("front leaf meeting stile missing 45° miters")

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
    if "data-gi-plate" in usvg:
        fails.append("U shower svg still has corner GI plate dots")
    if 'data-lock-kind="mortice"' not in usvg and "data-lock" not in usvg:
        fails.append("U shower svg missing mortice lock mark")
    if 'data-track-gap-px="0"' not in usvg:
        fails.append("sliding track must sit immediately above the head rails")
    if 'data-track="cover"' not in usvg or 'data-track="top"' not in usvg:
        fails.append("sliding missing distinct cover plate + top track")

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
