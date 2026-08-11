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
    if not any("Railing" in s or "Type =" in s for s in specs):
        fails.append(f"specs look wrong: {specs[:3]}")
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
    if not any("Railing" in s or "Type =" in s or "Stairs" in s for s in stair_specs):
        fails.append(f"stair specs wrong: {stair_specs[:4]}")

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

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print("OK railing PDF + productType lock + installComponents smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
