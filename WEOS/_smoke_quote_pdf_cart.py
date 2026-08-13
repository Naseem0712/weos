"""Immediate cart PDF + short window specs + SG/DG + weight + visual scale."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_pdf_cart_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

from WEOS.factory.marqt_pdf import _spec_rows, render_marqt_pdf
from WEOS.factory.pipeline import generate_job
from WEOS.factory.project_engine import calculate_line, calculate_project
from WEOS.factory.project_store import empty_project
from WEOS.factory.svg_export import render_svg_string
from WEOS.factory.window_specs import glass_family_from_line, human_glass_label, is_internal_glass_name
from WEOS.factory.section_catalogue import clean_profile_print_name, specs_summary_for_series


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    _ok(is_internal_glass_name("shutter_0_glass"), "detect shutter_0_glass")
    _ok(not is_internal_glass_name("Clear Toughened"), "human glass name ok")
    _ok(clean_profile_print_name("Slim interlock sg, dg") == "Slim interlock", "strip sg,dg")
    _ok("sg" not in clean_profile_print_name("renf. Int. Sg, dg").lower(), "strip Sg, dg")

    sg_sum = specs_summary_for_series("25mm_eco_gulf", glass_family="single", track_count=2, clean_names=True)
    dg_sum = specs_summary_for_series("25mm_eco_gulf", glass_family="dgu", track_count=2, clean_names=True)
    for label, summary in (("SG", sg_sum), ("DG", dg_sum)):
        blob = " ".join(str(summary.get(k) or "") for k in ("track", "sash", "interlock")).lower()
        _ok("sg" not in blob.split() or "dg" not in blob.split(), f"{label} print has no dual sg,dg: {blob}")
        _ok(summary.get("sash") or summary.get("sashPrint"), f"{label} has sash dim")

    win_sg = {
        "product": "29mm_sliding",
        "displayName": "Sliding Window",
        "width": 2050,
        "height": 1970,
        "qty": 1,
        "glass": "10mm_toughened",
        "colour": "black_texture",
        "handle": "premium",
        "handleName": "C Handle",
        "handleFinish": "black",
        "hardwareBrand": "Ozone",
        "sectionSeries": "25mm_eco_gulf",
        "trackCount": 2,
        "glassShutters": 2,
        "system": "sliding",
        "sellingRate": 890,
        "saleUnit": "sqft",
        "locationName": "Master Bedroom",
    }
    calc_sg = calculate_line(win_sg)
    fam = glass_family_from_line(calc_sg)
    _ok(fam == "single", f"10mm toughened is SG got {fam}")
    gtxt = human_glass_label(calc_sg)
    _ok("shutter_0" not in gtxt.lower() and "_glass" not in gtxt.lower(), f"glass label {gtxt}")
    rows = _spec_rows(calc_sg, audience="customer")
    labels = [r[0] for r in rows if r[0]]
    blob = " | ".join(f"{a}: {b}" for a, b in rows)
    for need in ("SIZE", "AREA", "SHUTTER", "TRACK", "SASH", "GLASS", "HANDLE", "COLOUR", "MESH"):
        _ok(need in labels, f"customer has {need} in {labels}")
    for ban in ("SERIES", "ALUMINIUM", "JOINT", "INTERLOCK", "SECTION"):
        _ok(ban not in labels, f"customer must not dump {ban}: {labels}")
    _ok("shutter_0_glass" not in blob.lower(), f"no internal glass id: {blob}")
    _ok("sg, dg" not in blob.lower() and "sg,dg" not in blob.lower().replace(" ", ""), f"no dual sg,dg: {blob}")
    wt = calc_sg.get("weight") or {}
    _ok(float(wt.get("glassKg") or 0) > 0, f"glass kg {wt}")
    _ok(wt.get("weightSource") in ("glass+20%", "catalogue", "glass"), f"weightSource {wt.get('weightSource')}")
    if wt.get("weightSource") == "glass+20%":
        _ok(abs(float(wt["aluminiumKg"]) - 0.20 * float(wt["glassKg"])) < 0.05, f"20% uplift {wt}")

    win_dg = {
        **win_sg,
        "glass": "dgu_6_12_6",
        "glassMakeup": "dgu",
        "locationName": "Kitchen",
    }
    calc_dg = calculate_line(win_dg)
    _ok(glass_family_from_line(calc_dg) == "dgu", f"DGU family got {glass_family_from_line(calc_dg)}")
    dblob = " ".join(v for _, v in _spec_rows(calc_dg, audience="customer")).lower()
    _ok("sg, dg" not in dblob and "sg,dg" not in dblob.replace(" ", ""), f"DGU no dual tag: {dblob}")

    win_upvc = {**win_sg, "frameMaterial": "upvc", "colour": "white", "reinforcement": True, "reinforcementMaterial": "gi"}
    calc_u = calculate_line(win_upvc)
    urows = _spec_rows(calc_u, audience="customer")
    ulabels = [r[0] for r in urows if r[0]]
    ublob = " ".join(v for _, v in urows).lower()
    _ok("MATERIAL" in ulabels, f"UPVC material row {ulabels}")
    _ok("upvc" in ublob, f"UPVC text {ublob}")
    _ok("alloy" not in ulabels and "aluminium" not in ulabels, f"no alloy/alu dump {ulabels}")
    _ok("REINFORCEMENT" in ulabels and "gi" in ublob, f"GI reinforcement {urows}")
    _ok((calc_u.get("weight") or {}).get("weightSource") in ("glass", "catalogue", "glass+hardware"), f"UPVC weight src {calc_u.get('weight')}")

    job_small = generate_job(750, 970, "29mm_sliding", glass="5mm_clear", system="sliding")
    job_large = generate_job(2750, 1970, "29mm_sliding", glass="5mm_clear", system="sliding")
    job_cas = generate_job(2050, 1970, "29mm_sliding", glass="8mm_toughened", system="casement", glass_count=2)
    svg_s = render_svg_string(job_small.drawing, annotations=True, include_plan=True, style="pdf")
    svg_l = render_svg_string(job_large.drawing, annotations=True, include_plan=True, style="pdf")
    svg_c = render_svg_string(job_cas.drawing, annotations=True, include_plan=True, style="pdf")
    _ok('data-visual-series="sliding35"' in svg_s and 'data-visual-series="sliding35"' in svg_l, "sliding visual 35")
    _ok('data-visual-series="casement50"' in svg_c, "casement visual 50")
    _ok("stroke-width=" in svg_l, "large window has strokes")

    # Immediate PDF from 8+ mixed in-memory lines (no wait / stale snapshot)
    lines = [
        calculate_line({**win_sg, "qty": 1, "locationName": "MB"}),
        calculate_line({**win_dg, "width": 1440, "height": 1800, "locationName": "Kit"}),
        calculate_line({
            "product": "29mm_sliding", "system": "casement", "width": 1200, "height": 2100, "qty": 1,
            "glass": "8mm_toughened", "glassShutters": 2, "sellingRate": 950, "sectionSeries": "25mm_eco_gulf",
        }),
        calculate_line({
            "product": "shower_partition", "productType": "shower_partition", "width": 1200, "height": 2000, "qty": 1,
            "sellingRate": 1100,
            "options": {"shower": {"widthMm": 1200, "heightMm": 2000, "sellingRate": 1100}, "productType": "shower_partition"},
        }),
        calculate_line({
            "product": "railing", "productType": "railing", "width": 2400, "height": 1100, "qty": 1,
            "sellingRate": 850,
            "options": {"railing": {"shape": "straight", "lengthMm": 2400, "heightMm": 1100, "sellingRate": 850}},
        }),
        calculate_line({**win_upvc, "width": 900, "height": 1200, "locationName": "Toilet"}),
        calculate_line({
            "product": "bathroom_ventilator", "productType": "bathroom_ventilator", "width": 600, "height": 450, "qty": 2,
            "sellingRate": 420,
            "options": {"ventilator": {"widthMm": 600, "heightMm": 450, "sellingRate": 420}, "productType": "bathroom_ventilator"},
        }),
        calculate_line({**win_sg, "width": 1800, "height": 1500, "qty": 2, "locationName": "Hall"}),
    ]
    _ok(len(lines) >= 8, f"8+ lines got {len(lines)}")
    pdf = render_marqt_pdf(
        {"branding": {"companyName": "TEST CO", "primaryColor": [0.1, 0.2, 0.3]}},
        {"quotationId": "QT-CART-8", "customer": "Cart Test", "lines": lines, "price": {"total": 1}},
    )
    _ok(pdf.startswith(b"%PDF"), "PDF bytes")
    _ok(b"shutter_0_glass" not in pdf, "PDF has no shutter_0_glass")

    # Overlay calculate_project uses in-memory lines even if saved project is empty-ish
    doc = empty_project(name="Live Cart", customer="Cart Test")
    doc["lines"] = [
        {"product": "29mm_sliding", "width": 1000, "height": 1200, "qty": 1, "glass": "5mm_clear", "sellingRate": 800},
        {"product": "29mm_sliding", "width": 1100, "height": 1300, "qty": 1, "glass": "8mm_toughened", "sellingRate": 800},
        {"product": "29mm_sliding", "width": 1200, "height": 1400, "qty": 1, "glass": "10mm_toughened", "sellingRate": 800},
        {"product": "shower_partition", "productType": "shower_partition", "width": 1400, "height": 2000, "qty": 1,
         "sellingRate": 900, "options": {"shower": {"widthMm": 1400, "heightMm": 2000, "sellingRate": 900}, "productType": "shower_partition"}},
        {"product": "railing", "productType": "railing", "width": 3000, "height": 1100, "qty": 1, "sellingRate": 700,
         "options": {"railing": {"shape": "straight", "lengthMm": 3000, "heightMm": 1100}}},
        {"product": "bathroom_ventilator", "productType": "bathroom_ventilator", "width": 500, "height": 400, "qty": 1,
         "sellingRate": 400, "options": {"ventilator": {"widthMm": 500, "heightMm": 400, "sellingRate": 400}, "productType": "bathroom_ventilator"}},
        {"product": "29mm_sliding", "system": "casement", "width": 900, "height": 2100, "qty": 1, "glass": "5mm_clear",
         "glassShutters": 1, "sellingRate": 850},
        {"product": "29mm_sliding", "width": 1600, "height": 1600, "qty": 1, "glass": "5mm_clear", "frameMaterial": "upvc",
         "sellingRate": 800},
    ]
    result = calculate_project(doc, optimize=False)
    _ok(len(result.get("lines") or []) == 8, f"calculate_project 8 lines got {len(result.get('lines') or [])}")
    print("SMOKE_QUOTE_PDF_CART_OK")


if __name__ == "__main__":
    main()
