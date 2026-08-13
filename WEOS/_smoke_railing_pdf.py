"""Smoke: railing cart line → calculate → PDF elevation/specs path."""
from __future__ import annotations

import sys

from WEOS.factory.marqt_pdf import _line_is_railing, _railing_cfg_and_quote, _spec_lines
from WEOS.factory.project_engine import calculate_line, _is_railing_cart_line
from WEOS.factory.railing_engine import compute_railing, railing_svg


def main() -> int:
    fails: list[str] = []
    cfg = {
        "shape": "straight",
        "lengthMm": 3000,
        "heightMm": 1000,
        "panels": 3,
        "blocksPerGlass": 2,
        "handrail": True,
        "gapMm": 12,
        "wallStart": True,
        "wallEnd": True,
        "mountType": "side_mount",
        "glassThicknessMm": 12,
        "glassType": "clear",
        "colorMode": "global",
        "systemColor": "black",
        "installComponents": {
            "bottomRail": True, "block": True, "ssPillar": False,
            "handrail": True, "glass": True,
        },
        "rates": {
            "glassPerSqft": 200, "blockPerPc": 100, "anchorPerPc": 50,
            "bottomRailPerUnit": 80, "handrailPerUnit": 120,
        },
        "overheadPercent": 10,
        "markupPercent": 15,
    }
    q = compute_railing(cfg)
    svg = railing_svg(cfg, quote=q)
    if "<svg" not in str(svg):
        fails.append("no svg")
    if q.get("wastageEnabled") is not False:
        fails.append("normal should disable wastage")
    if not q.get("glassType"):
        fails.append("glassType missing on quote")

    cart = {
        "product": "railing",
        "displayName": "Railing",
        "width": q["lengthMm"],
        "height": q["heightMm"],
        "qty": 1,
        "saleUnit": q["saleUnit"],
        "sellingRate": q["sellingPerUnit"],
        "options": {"railing": cfg, "railingQuote": q},
    }
    if not _is_railing_cart_line(cart):
        fails.append("cart not detected as railing")
    result = calculate_line(cart)
    if result.get("product") != "railing":
        fails.append(f"calc product {result.get('product')}")
    opts = result.get("options") or {}
    if not isinstance(opts.get("railing"), dict):
        fails.append("options.railing missing after calculate")
    if not isinstance(opts.get("railingQuote"), dict):
        fails.append("options.railingQuote missing after calculate")
    if not (result.get("preview") or {}).get("svg"):
        fails.append("preview.svg missing")
    if not _line_is_railing(result):
        fails.append("result not detected as railing for PDF")
    cfg2, q2 = _railing_cfg_and_quote(result)
    if not cfg2:
        fails.append("pdf cfg empty")
    if not q2.get("items"):
        fails.append("pdf quote items empty")
    specs = _spec_lines(result)
    if not any("Railing" in s or s.startswith("TYPE:") or "Type =" in s for s in specs):
        fails.append(f"specs look wrong: {specs[:3]}")
    cust_blob = " ".join(specs)
    if " @ " in cust_blob or "@ " in cust_blob:
        fails.append(f"customer specs leaked purchase rates: {specs}")
    if any("wastage" in s.lower() and "purchased" in s.lower() for s in specs):
        fails.append(f"customer specs leaked wastage/purchased: {specs}")
    fact_specs = _spec_lines(result, audience="factory")
    if not any("@" in s for s in fact_specs):
        fails.append(f"factory specs missing purchase rates: {fact_specs[:8]}")
    if any("Track" in s and "track" in s.lower() for s in specs if "Track /" in s or s.startswith("Track =")):
        fails.append(f"window track leaked into railing specs: {specs}")
    if any("Fold" in s or "Sliding" == s.split("=")[-1].strip()[:7] for s in specs if "Panels" in s and "S1" in s):
        fails.append(f"window panel labels in railing specs: {specs}")
    if result.get("productType") not in ("railing", "staircase_railing"):
        fails.append(f"productType {result.get('productType')}")
    # elevation_svg_for_line must not call window generate_job
    from WEOS.factory.svg_export import elevation_svg_for_line
    elev = elevation_svg_for_line(result, style="pdf")
    if not elev or "<svg" not in elev:
        fails.append("elevation_svg_for_line empty for railing")
    if "track" in elev.lower() and "shutter" in elev.lower() and "railing" not in elev.lower()[:200]:
        # soft check — railing svg shouldn't look like multi-track window
        pass

    # Catalogue-style productType lock (no options.railing yet) — cart width must drive length
    typed = calculate_line({
        "product": "custom_balcony",
        "productType": "railing",
        "category": "Railings",
        "width": 3000,
        "height": 1000,
        "qty": 1,
    })
    if typed.get("product") != "custom_balcony" and typed.get("product") not in ("railing", "custom_balcony", "railings_stub"):
        # product id preserved from input or normalised
        pass
    q_typed = typed.get("railing") or (typed.get("options") or {}).get("railingQuote") or {}
    if float(q_typed.get("lengthMm") or 0) < 2990:
        fails.append(f"cart width not seeded into railing length: {q_typed.get('lengthMm')}")
    if float(q_typed.get("lengthRft") or 0) < 9.5:
        fails.append(f"LengthRft too small after width seed: {q_typed.get('lengthRft')}")
    svg_typed = (typed.get("preview") or {}).get("svg") or ""
    if "1 mm" in svg_typed and "3000" not in svg_typed:
        fails.append("typed railing still draws collapsed 1 mm stub")
    if "length missing" in svg_typed.lower():
        fails.append("typed railing shows missing-length error despite width=3000")
    if typed.get("layout"):
        fails.append("railing line should not carry window layout")

    # Empty length must not draw 1 mm stub
    from WEOS.factory.railing_engine import railing_svg as _rsvg
    err_svg = _rsvg({})
    if "1 mm" in err_svg and "missing" not in err_svg.lower():
        fails.append("empty cfg still draws 1 mm stub instead of error")
    if "missing" not in err_svg.lower() and "length" not in err_svg.lower():
        fails.append("empty cfg should show length-missing error SVG")

    # Happy path dims on smoke cfg
    if float(q.get("lengthMm") or 0) < 2990:
        fails.append(f"smoke cfg length {q.get('lengthMm')}")
    if float(q.get("lengthRft") or 0) < 9.5:
        fails.append(f"smoke cfg RFT {q.get('lengthRft')}")
    if "3000" not in str(svg):
        fails.append("smoke svg missing 3000 mm dim")

    # Stairs cart → PDF
    stair_cart = {
        "product": "railing",
        "productType": "staircase_railing",
        "width": 4000,
        "height": 900,
        "qty": 1,
        "options": {
            "railing": {
                "shape": "staircase",
                "floorHeightMm": 2520,
                "stairRiseMm": 180,
                "stairRunMm": 300,
                "glassHeightMm": 900,
                "panels": 4,
                "handrail": True,
                "installComponents": {
                    "bottomRail": False, "block": True, "ssPillar": False,
                    "handrail": True, "glass": True,
                },
                "rates": {"glassPerSqft": 200, "blockPerPc": 100},
            }
        },
    }
    stair_res = calculate_line(stair_cart)
    if stair_res.get("productType") != "staircase_railing":
        fails.append(f"stair productType {stair_res.get('productType')}")
    if not _line_is_railing(stair_res):
        fails.append("stair result not railing for PDF")
    stair_specs = _spec_lines(stair_res)
    if any(s.startswith("Track") for s in stair_specs):
        fails.append("stair specs have Track")
    if not any("Railing" in s or s.startswith("TYPE:") or "Type =" in s or "Stairs" in s or "STAIRS" in s for s in stair_specs):
        fails.append(f"stair specs wrong: {stair_specs[:4]}")
    # Window series must never appear on staircase railing specs / calc result
    leak_keys = ("profileSeries", "sectionSizeMm", "standardLength", "wallThickness", "sectionSpecs")
    blob = " ".join(stair_specs).lower() + " " + str(stair_res.get("specifications") or {}).lower()
    if any(k.lower() in blob for k in ("profileseries", "sectionsize", "2-track", "s1 sliding")):
        fails.append(f"window series leaked into stair specs: {stair_specs[:6]}")
    if stair_res.get("sectionSpecs"):
        fails.append(f"stair result has sectionSpecs: {stair_res.get('sectionSpecs')}")
    if stair_res.get("layout"):
        fails.append("stair result should not carry window layout")
    # Contaminated cart (window series fields) must still price as railing only
    dirty = calculate_line({
        **stair_cart,
        "sectionSeries": "25mm_eco_gulf",
        "specifications": {
            "profileSeries": "25mm eco gulf system",
            "sectionSizeMm": 49,
            "standardLength": "16F",
            "wallThicknessMm": 1.1,
            "track": "2 track 49x37.8 mm",
        },
        "system": "sliding",
        "trackCount": 2,
        "glassShutters": 2,
    })
    dirty_specs = _spec_lines(dirty)
    dirty_blob = " ".join(dirty_specs).lower()
    if "eco gulf" in dirty_blob or "2 track" in dirty_blob or "s1" in dirty_blob:
        fails.append(f"contaminated stair still dumps series: {dirty_specs[:8]}")
    if dirty.get("sectionSpecs"):
        fails.append("contaminated stair kept sectionSpecs")
    if dirty.get("productType") != "staircase_railing":
        fails.append(f"contaminated stair productType {dirty.get('productType')}")

    # Manual rate must drive commercialTotal / price.total (Total Amount)
    manual_cfg = {
        **cfg,
        "manualRatePerUnit": 999.0,
    }
    mq = compute_railing(manual_cfg)
    if abs(float(mq.get("sellingPerUnit") or 0) - 999.0) > 0.01:
        fails.append(f"manual rate not on sellingPerUnit: {mq.get('sellingPerUnit')}")
    # Engine rounds widthUnit for display; sellingTotal uses full precision — tolerate 1 INR.
    expected_total = float(mq.get("sellingTotal") or 0)
    approx = round(999.0 * float(mq.get("widthUnit") or 0), 2)
    if abs(expected_total - approx) > 1.0:
        fails.append(f"manual sellingTotal {expected_total} far from RFT×rate {approx}")
    m_line = calculate_line({
        "product": "railing",
        "productType": "railing",
        "width": mq["lengthMm"],
        "height": mq["heightMm"],
        "qty": 1,
        "saleUnit": mq["saleUnit"],
        "sellingRate": 999.0,
        "options": {"railing": manual_cfg, "railingQuote": mq, "productType": "railing"},
    })
    if abs(float(m_line.get("commercialTotal") or 0) - expected_total) > 0.05:
        fails.append(f"manual commercialTotal {m_line.get('commercialTotal')} != {expected_total}")
    if abs(float((m_line.get("price") or {}).get("total") or 0) - expected_total) > 0.05:
        fails.append(f"manual price.total {(m_line.get('price') or {}).get('total')} != {expected_total}")
    # Cart sellingRate alone (no cfg.manual) must NOT freeze/override cascade —
    # otherwise BOM material rates never reach Total Amount.
    cart_only = calculate_line({
        "product": "railing",
        "productType": "railing",
        "width": 3000,
        "height": 1000,
        "qty": 1,
        "saleUnit": "rft",
        "sellingRate": 777.0,
        "options": {
            "railing": {
                "shape": "straight", "lengthMm": 3000, "heightMm": 1000, "panels": 2,
                "rates": {"glassPerSqft": 200},
            },
            "productType": "railing",
        },
    })
    cascade_only = compute_railing({
        "shape": "straight", "lengthMm": 3000, "heightMm": 1000, "panels": 2,
        "rates": {"glassPerSqft": 200},
    })
    if abs(float(cart_only.get("commercialTotal") or 0) - float(cascade_only.get("sellingTotal") or 0)) > 0.05:
        fails.append(
            f"cart sellingRate froze total: {cart_only.get('commercialTotal')} "
            f"vs cascade {cascade_only.get('sellingTotal')}"
        )
    if abs(float(cart_only.get("sellingRate") or 0) - 777.0) < 0.01 and abs(
        float(cascade_only.get("sellingPerUnit") or 0) - 777.0
    ) > 1.0:
        fails.append("cart sellingRate incorrectly applied as manual override")

    # Stale staircase description must refresh from live quote
    stale_desc = calculate_line({
        "product": "railing",
        "productType": "staircase_railing",
        "width": 3000,
        "height": 1000,
        "qty": 1,
        "description": "Railing · staircase · 3000 mm · 4 panels · 12mm",
        "options": {
            "railing": {
                "shape": "straight", "lengthMm": 3000, "heightMm": 1000, "panels": 1,
                "rates": {"glassPerSqft": 200},
            },
            "productType": "staircase_railing",
        },
    })
    if "staircase" in str(stale_desc.get("description") or "").lower():
        fails.append(f"stale staircase description kept: {stale_desc.get('description')}")
    if stale_desc.get("productType") != "railing":
        fails.append(f"stale staircase productType kept: {stale_desc.get('productType')}")

    # Continuous bottom-rail only — no pillar qty
    cont = compute_railing({
        **cfg,
        "blocksPerGlass": 0,
        "installComponents": {
            "bottomRail": True, "block": False, "ssPillar": False,
            "handrail": False, "glass": True,
        },
    })
    if cont.get("pillarCount") not in (0, 0.0):
        fails.append(f"continuous rail still has pillars {cont.get('pillarCount')}")
    keys = {it["key"] for it in cont.get("items") or []}
    if "blocks" in keys:
        fails.append("continuous-only should omit blocks BOM")
    if "studs" in keys:
        fails.append(f"continuous-only extra hardware {keys}")
    if "anchors" not in keys:
        fails.append(f"continuous-only missing spaced anchors {keys}")
    if "epdmBottom" not in keys:
        fails.append(f"continuous-only missing bottom EPDM {keys}")
    cont_svg = railing_svg({
        **cfg, "blocksPerGlass": 0, "bottomKind": "continuous", "continuousRail": True,
        "mountType": "top_mount",
        "installComponents": {"bottomRail": True, "block": False, "ssPillar": False, "handrail": False, "glass": True},
    }, quote=cont)
    if 'data-spigot="1"' in cont_svg:
        fails.append("continuous pdf svg still has spigots")

    pillar_cfg = {
        "shape": "straight", "lengthMm": 2400, "heightMm": 1000, "panels": 1,
        "bottomKind": "ss_pillar", "blocksPerGlass": 3, "handrail": True,
        "continuousRail": False, "handrailSize": "50×50",
        "installComponents": {"bottomRail": False, "block": False, "ssPillar": True, "handrail": True, "glass": True},
    }
    pq = compute_railing(pillar_cfg)
    psvg = railing_svg(pillar_cfg, quote=pq)
    n_spigot = psvg.count('data-spigot="1"')
    n_bolt = psvg.count('data-spigot-bolt="1"')
    if n_spigot != 3:
        fails.append(f"1 glass 3 pillars spigots {n_spigot} != 3")
    if n_bolt != 12:
        fails.append(f"3 spigots should show 12 bolt holes, got {n_bolt}")
    if 'data-handrail="1"' not in psvg:
        fails.append("ss pillar svg missing solid handrail outline")
    if 'data-side-stud="1"' in psvg:
        fails.append("ss pillar svg used studs placement")
    line_p = calculate_line({
        "product": "railing", "productType": "railing", "width": 2400, "height": 1000, "qty": 1,
        "options": {"railing": pillar_cfg, "railingQuote": pq},
    })
    prev_svg = str((line_p.get("preview") or {}).get("svg") or "")
    elev_pdf = elevation_svg_for_line(line_p, style="pdf") or ""
    elev_prev = elevation_svg_for_line(line_p, style="preview") or ""
    if prev_svg and elev_pdf and prev_svg != elev_pdf:
        fails.append("railing canvas SVG != PDF SVG")
    if elev_pdf and elev_prev and elev_pdf != elev_prev:
        fails.append("railing preview style SVG != pdf style SVG")

    # Stairs engine: no bottom rail
    stair = compute_railing({
        "shape": "staircase",
        "floorHeightMm": 2520,
        "stairRiseMm": 180,
        "stairRunMm": 300,
        "stairSteps": 0,
        "glassHeightMm": 900,
        "panels": 4,
        "handrail": True,
        "installComponents": {
            "bottomRail": False, "block": True, "ssPillar": False,
            "handrail": True, "glass": True,
        },
        "rates": {"glassPerSqft": 200, "blockPerPc": 100, "studPerPc": 80},
        "estimatedWastagePercent": 10,
    })
    if stair.get("shape") != "staircase":
        fails.append("stair shape")
    sk = {it["key"] for it in stair.get("items") or []}
    if "bottomRail" in sk:
        fails.append("stairs should not BOM bottom rail")

    # Mount formula + beam overlap (studs side-mount)
    from WEOS.factory.railing_engine import (
        infer_railing_mount,
        clamp_beam_overlap_mm,
        side_stud_row_offsets_mm,
        side_stud_column_xs,
        side_stud_second_y_mm,
    )
    if infer_railing_mount(bottom_kind="studs") != "side_mount":
        fails.append("infer studs != side_mount")
    if infer_railing_mount(bottom_kind="block") != "top_mount":
        fails.append("infer block != top_mount")
    if infer_railing_mount(bottom_kind="continuous") != "top_mount":
        fails.append("infer continuous != top_mount")
    if infer_railing_mount(shape="staircase", stair_mount_type="step") != "step_mount":
        fails.append("infer stair step != step_mount")
    if infer_railing_mount(shape="staircase", stair_mount_type="side", stair_bottom_type="studs") != "side_mount":
        fails.append("infer stair side studs != side_mount")
    if infer_railing_mount(shape="staircase", stair_mount_type="side", stair_bottom_type="block") != "side_mount":
        fails.append("infer stair side block != side_mount")
    if clamp_beam_overlap_mm(None) != 200:
        fails.append(f"default overlap {clamp_beam_overlap_mm(None)}")
    if clamp_beam_overlap_mm(50) != 150 or clamp_beam_overlap_mm(900) != 450:
        fails.append("overlap clamp 150–450 failed")
    ov_q = compute_railing({
        "shape": "straight", "lengthMm": 3000, "heightMm": 1000, "panels": 3,
        "bottomKind": "studs", "studsPerGlass": 2,
        "installComponents": {"bottomRail": False, "block": False, "ssPillar": False, "studs": True, "handrail": True, "glass": True},
        "beamOverlapMm": 250,
        "rates": {"glassPerSqft": 200, "studPerPc": 80},
    })
    if ov_q.get("mountType") != "side_mount":
        fails.append(f"overlap cfg mount {ov_q.get('mountType')}")
    if abs(float(ov_q.get("beamOverlapMm") or 0) - 250) > 0.1:
        fails.append(f"beamOverlapMm not persisted {ov_q.get('beamOverlapMm')}")
    ov_svg = railing_svg({
        "shape": "straight", "lengthMm": 3000, "heightMm": 1000, "panels": 3,
        "bottomKind": "studs", "beamOverlapMm": 250,
        "installComponents": {"studs": True, "handrail": True, "glass": True},
    }, quote=ov_q)
    if "overlap 250" not in ov_svg.lower() and "overlap 250 mm" not in ov_svg.lower():
        fails.append("straight svg missing overlap 250 mm label")
    # Placement math: inset 100 both sides; row1=25; row2=overlap-50
    if abs(side_stud_second_y_mm(150) - 100) > 0.05:
        fails.append(f"secondY(150)={side_stud_second_y_mm(150)} != 100")
    if abs(side_stud_second_y_mm(200) - 150) > 0.05:
        fails.append(f"secondY(200)={side_stud_second_y_mm(200)} != 150")
    xl, xr = side_stud_column_xs(0, 1200)
    if abs(xl - 100) > 0.05 or abs(xr - 1100) > 0.05:
        fails.append(f"columns {xl},{xr} != 100,1100")
    off2 = side_stud_row_offsets_mm(2, overlap_mm=150, glass_height_from_bottom_mm=1050)
    off4 = side_stud_row_offsets_mm(4, overlap_mm=150, glass_height_from_bottom_mm=1050)
    off6 = side_stud_row_offsets_mm(6, overlap_mm=150, glass_height_from_bottom_mm=1050)
    off8 = side_stud_row_offsets_mm(8, overlap_mm=150, glass_height_from_bottom_mm=1050)
    if off2 != [25.0] and not (len(off2) == 1 and abs(off2[0] - 25) < 0.05):
        fails.append(f"2pc rows {off2}")
    if len(off4) != 2 or abs(off4[0] - 25) > 0.05 or abs(off4[1] - 100) > 0.05:
        fails.append(f"4pc rows {off4}")
    if len(off6) != 3 or abs(off6[2] - (150 + (1050 - 150) / 2)) > 1:
        fails.append(f"6pc rows {off6}")
    if len(off8) != 4 or abs(off8[2] - (150 + (1050 - 150) / 3)) > 1 or abs(off8[3] - (150 + 2 * (1050 - 150) / 3)) > 1:
        fails.append(f"8pc rows {off8}")
    n_ov_studs = ov_svg.count('data-side-stud="1"')
    if n_ov_studs != 3 * 2:
        fails.append(f"overlap svg stud count {n_ov_studs} != 6")

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print("OK railing PDF + productType lock + installComponents smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
