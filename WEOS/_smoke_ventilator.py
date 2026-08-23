"""Bathroom ventilator: gallery type, 2D SVG (canvas===PDF), customer specs, no corner dots."""
from __future__ import annotations

from WEOS.factory.line_kind import (
    is_ventilator_cart_line,
    normalize_product_type,
    product_world,
)
from WEOS.factory.marqt_pdf import _spec_rows
from WEOS.factory.product_loader import load_product
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.svg_export import elevation_svg_for_line
from WEOS.factory.ventilator_engine import (
    compute_ventilator,
    format_ventilator_description,
    ventilator_svg,
)


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    _ok(normalize_product_type("ventilator") == "bathroom_ventilator", "alias ventilator")
    _ok(product_world("bathroom_ventilator") == "ventilator", "world ventilator")
    prod = load_product("bathroom_ventilator", strict=False)
    _ok(prod.get("productType") == "bathroom_ventilator", f"gallery productType {prod.get('productType')}")
    _ok(prod.get("category") == "Bathrooms", "gallery category Bathrooms")

    split_cfg = {
        "widthMm": 600,
        "heightMm": 450,
        "mode": "split",
        "louversSide": "left",
        "louversFill": "louvers",
        "remainFill": "top_hung",
        "exhaust": True,
        "exhaustSide": "left",
        "fanDiameterMm": 180,
        "hingesPerDoor": 2,
        "colour": "matt_black",
        "sellingRate": 420,
        "qty": 1,
    }
    q = compute_ventilator(split_cfg)
    _ok(q["productType"] == "bathroom_ventilator", "compute productType")
    _ok(q["glassColour"] == "frosted", f"default glass frosted got {q.get('glassColour')}")
    _ok(q["remainFill"] == "top_hung", "remain top-hung")
    _ok(q["louversFill"] == "louvers", "left louvers")
    _ok(q["handlePosition"] == "bottom", "handle at bottom")
    _ok(q["hingePosition"] == "top", "hinges at top")
    svg = ventilator_svg(split_cfg, quote=q)
    _ok('data-model-system="ventilator"' in svg, "svg system ventilator")
    _ok('data-miter="1"' in svg and 'data-outer-miter="45"' in svg, "outer 45° miters")
    _ok('data-mullion-joint="90"' in svg, "mullion 90°")
    _ok('data-corner-markers="0"' in svg, "no corner dots flag")
    _ok("data-gi" not in svg.lower() and "corner-dot" not in svg, "no GI/corner dots")
    _ok('data-hinge="1"' in svg and 'data-hinge-pos="top"' in svg, "top casement hinges")
    _ok('data-handle-pos="bottom"' in svg, "handle at bottom")
    _ok('data-louver="1"' in svg, "horizontal louvers drawn")
    _ok('data-fan="1"' in svg, "exhaust fan opening")
    hinge_n = svg.count('data-hinge="1"')
    _ok(hinge_n == 2, f"2 top hinges got {hinge_n}")

    cut_cfg = {
        "widthMm": 500,
        "heightMm": 500,
        "mode": "full_cutout",
        "fanDiameterMm": 200,
        "sellingRate": 390,
    }
    qc = compute_ventilator(cut_cfg)
    svgc = ventilator_svg(cut_cfg, quote=qc)
    _ok(qc["mode"] == "full_cutout", "full cutout mode")
    _ok('data-fan-cut="1"' in svgc, "round cut in glass")
    _ok('data-fan="1"' in svgc, "fan circle")
    _ok("data-miter" in svgc, "outer frame miters on cutout mode")

    line = {
        "product": "bathroom_ventilator",
        "productType": "bathroom_ventilator",
        "category": "Bathrooms",
        "width": 600,
        "height": 450,
        "qty": 2,
        "sellingRate": 420,
        "options": {"ventilator": split_cfg, "productType": "bathroom_ventilator"},
    }
    _ok(is_ventilator_cart_line(line), "cart line detector")
    calc = calculate_line(line)
    _ok(calc.get("productType") == "bathroom_ventilator", f"calc type {calc.get('productType')}")
    _ok(float(calc.get("sellingRate") or 0) == 420, f"selling rate 420 got {calc.get('sellingRate')}")
    _ok(round(float(calc.get("commercialTotal") or 0), 2) > 0, "commercial total > 0")
    elev = elevation_svg_for_line(line)
    _ok(elev and 'data-model-system="ventilator"' in elev, "elevation_svg same engine")
    _ok(elev == ventilator_svg(split_cfg, quote=compute_ventilator(split_cfg)) or "data-fan" in (elev or ""),
        "canvas/PDF same family SVG")

    cust = _spec_rows(calc, audience="customer")
    labels = [r[0] for r in cust]
    blob = " ".join(v for _, v in cust).lower()
    _ok("BOM" not in labels, f"customer has no BOM labels {labels}")
    _ok("bom" not in blob, "customer text has no bom")
    for need in ("PROFILE", "GLASS", "COLOUR", "HARDWARE", "LAYOUT", "AREA"):
        _ok(need in labels, f"customer spec {need}")
    for dup in ("RATE", "AMOUNT", "QTY"):
        _ok(dup not in labels, f"customer spec must not duplicate table column {dup}")
    desc = format_ventilator_description(q, split_cfg)
    _ok("Bathroom ventilator" in desc, f"desc {desc}")
    _ok("frosted" in (q.get("glassLabel") or "").lower() or q.get("glassColour") == "frosted", "frosted default")
    print("SMOKE_VENTILATOR_OK")


if __name__ == "__main__":
    main()
