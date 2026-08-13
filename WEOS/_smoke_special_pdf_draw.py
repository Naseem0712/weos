"""W14 railing + W13 shower ReportLab PDF, live amounts, mixed-quote speed."""
from __future__ import annotations

import io
import time

from reportlab.pdfgen import canvas as rl_canvas

from WEOS.factory.customer_line_view import customer_line_amount, public_product_row
from WEOS.factory.marqt_pdf import draw_line_elevation, render_marqt_pdf
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.railing_engine import compute_railing
from WEOS.factory.shower_engine import compute_shower
from WEOS.factory.svg_export import elevation_svg_for_line


def _ok(cond: bool, msg: str, fails: list[str]) -> None:
    if not cond:
        fails.append(msg)
        print("FAIL:", msg)
    else:
        print("OK:", msg)


def _rail_cfg() -> dict:
    return {
        "shape": "straight",
        "lengthMm": 2050,
        "heightMm": 1000,
        "panels": 3,
        "bottomKind": "continuous",
        "bottomSize": "100×45",
        "handrail": True,
        "handrailSize": "25×25",
        "continuousRail": True,
        "anchorSpacingFt": 2,
        "glassThicknessMm": 12,
        "glassType": "laminated",
        "wallStart": True,
        "wallEnd": True,
        "installComponents": {
            "bottomRail": True, "block": False, "ssPillar": False,
            "handrail": True, "glass": True,
        },
        "manualRatePerUnit": 2550,
        "saleUnit": "rft",
    }


def _shower_cfg() -> dict:
    return {
        "shape": "L",
        "operation": "hinged",
        "widthMm": 1750,
        "heightMm": 2130,
        "depthMm": 900,
        "doorSide": "right",
        "handle": True,
        "hingeCount": 3,
        "frameKind": "profile",
        "glassThicknessMm": 8,
        "saleUnit": "sqft",
        "manualRatePerUnit": 950,
        "qty": 1,
    }


def _win(i: int) -> dict:
    return calculate_line({
        "product": "29mm_sliding",
        "displayName": f"Sliding {i+1}",
        "width": 1200 + (i % 5) * 80,
        "height": 1400 + (i % 3) * 50,
        "qty": 1,
        "glass": "5mm_clear",
        "colour": "white",
        "sellingRate": 850,
        "saleUnit": "sqft",
        "system": "sliding",
        "trackCount": 2,
        "glassShutters": 2,
        "locationName": f"Room {i+1}",
    }, include_preview=False)


def main() -> int:
    fails: list[str] = []

    # 1) Live amount before calculate (eco gulf + railing rate×RFT)
    eco = {
        "product": "25mm_eco_gulf",
        "productType": "sliding",
        "width": 1500,
        "height": 1200,
        "qty": 2,
        "sellingRate": 450,
        "saleUnit": "sqft",
    }
    eco_amt = customer_line_amount(eco) or 0
    expected_eco = round((1500 * 1200 / 1_000_000.0) * 10.7639 * 2 * 450, 2)
    _ok(eco_amt > 0, f"eco live amount {eco_amt}", fails)
    _ok(abs(eco_amt - expected_eco) < 2.0, f"eco amount ~{expected_eco} got {eco_amt}", fails)
    row = public_product_row(0, eco)
    _ok(float(row.get("amount") or 0) > 0, f"scan row amount {row.get('amount')}", fails)

    cfg = _rail_cfg()
    q = compute_railing(cfg)
    rft = float(q.get("lengthRft") or (2050 / 304.8))
    rail_line = {
        "product": "railing",
        "productType": "railing",
        "width": 2050,
        "height": 1000,
        "qty": 1,
        "sellingRate": 2550,
        "saleUnit": "rft",
        "options": {"railing": cfg, "railingQuote": q},
    }
    rail_amt = customer_line_amount(rail_line) or 0
    expected_rail = round(rft * 2550, 2)
    _ok(rail_amt > 0, f"railing live amount {rail_amt}", fails)
    _ok(abs(rail_amt - expected_rail) < 30.0, f"railing ~{expected_rail} (rft {rft:.3f}) got {rail_amt}", fails)
    _ok(abs(rail_amt - 17161.5) < 80.0, f"W14-like ~17161.5 got {rail_amt}", fails)

    # Uncalculated railing (rate only, no quote) still uses length/304.8 not perimeter
    bare_rail = {
        "product": "railing", "productType": "railing",
        "width": 2050, "height": 1000, "qty": 1,
        "sellingRate": 2550, "saleUnit": "rft",
        "options": {"railing": {"shape": "straight", "lengthMm": 2050, "heightMm": 1000, "bottomKind": "continuous"}},
    }
    bare_amt = customer_line_amount(bare_rail) or 0
    peri_wrong = round((2 * (2050 + 1000) / 304.8) * 2550, 2)
    _ok(bare_amt > 0 and abs(bare_amt - peri_wrong) > 1000, f"railing not window-perimeter {bare_amt} vs wrong {peri_wrong}", fails)

    # 2) ReportLab railing cell — no grey placeholder
    calc_rail = calculate_line(rail_line, include_preview=False)
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(400, 500))
    ok_draw = draw_line_elevation(c, calc_rail, 20, 80, 200, 210)
    c.save()
    pdf_cell = buf.getvalue()
    rail_svg = elevation_svg_for_line(calc_rail) or ""
    _ok("<svg" in rail_svg.lower(), "railing canvas SVG", fails)
    _ok(ok_draw, "railing draw_line_elevation returned True", fails)
    _ok(b"Railing design" not in pdf_cell, "no grey placeholder text in railing cell", fails)
    _ok(b"/Image" in pdf_cell or b"IDAT" in pdf_cell, "railing cell embeds canvas PNG", fails)
    _ok(pdf_cell.startswith(b"%PDF") or b"PDF" in pdf_cell[:20] or len(pdf_cell) > 200, f"cell pdf bytes {len(pdf_cell)}", fails)

    # 3) Shower L hinged draw
    sh_cfg = _shower_cfg()
    sh_q = compute_shower(sh_cfg)
    sh_line = {
        "product": "shower_partition",
        "productType": "shower_partition",
        "width": 1750,
        "height": 2130,
        "qty": 1,
        "sellingRate": 950,
        "saleUnit": "sqft",
        "options": {"shower": sh_cfg, "showerQuote": sh_q},
    }
    calc_sh = calculate_line(sh_line, include_preview=False)
    sh_svg = elevation_svg_for_line(calc_sh) or ""
    _ok('data-model-system="shower"' in sh_svg, "shower canvas SVG", fails)
    _ok("data-corner-markers=\"0\"" in sh_svg or "data-corner-markers='0'" in sh_svg, "shower no stray corner markers", fails)
    buf2 = io.BytesIO()
    c2 = rl_canvas.Canvas(buf2, pagesize=(400, 500))
    ok_sh = draw_line_elevation(c2, calc_sh, 20, 80, 200, 210)
    c2.save()
    pdf_sh = buf2.getvalue()
    _ok(ok_sh, "shower draw_line_elevation returned True", fails)
    _ok(b"/Image" in pdf_sh or b"IDAT" in pdf_sh, "shower cell embeds canvas PNG", fails)
    sh_amt = customer_line_amount(sh_line) or customer_line_amount(calc_sh) or 0
    _ok(sh_amt > 0, f"shower live amount {sh_amt}", fails)

    # Straight sliding shower — the screenshot stub (triangles / messy join)
    slide_cfg = {
        "shape": "straight", "operation": "sliding", "widthMm": 1200, "heightMm": 2000,
        "doorSide": "right", "frameKind": "profile", "glassThicknessMm": 8,
        "saleUnit": "sqft", "manualRatePerUnit": 800,
    }
    slide_line = calculate_line({
        "product": "shower_partition", "productType": "shower_partition",
        "width": 1200, "height": 2000, "qty": 1, "sellingRate": 800, "saleUnit": "sqft",
        "options": {"shower": slide_cfg, "showerQuote": compute_shower(slide_cfg)},
    }, include_preview=False)
    slide_svg = elevation_svg_for_line(slide_line) or ""
    _ok('data-model-system="shower"' in slide_svg, "straight sliding canvas SVG", fails)
    _ok("TOP TRACK" in slide_svg or 'data-track="top"' in slide_svg, "sliding has canvas track", fails)
    _ok("COVER PLATE" in slide_svg or 'data-track="cover"' in slide_svg, "sliding has canvas cover", fails)
    buf3 = io.BytesIO()
    c3 = rl_canvas.Canvas(buf3, pagesize=(400, 500))
    ok_slide = draw_line_elevation(c3, slide_line, 20, 80, 200, 210)
    c3.save()
    _ok(ok_slide, "straight sliding shower PDF cell drew", fails)
    _ok(b"/Image" in buf3.getvalue() or b"IDAT" in buf3.getvalue(), "sliding shower PNG not schematic", fails)

    # 4) 15-line mixed quote PDF speed
    lines = [_win(i) for i in range(11)]
    lines.append(calc_rail)
    lines.append(calculate_line({
        **rail_line,
        "width": 3000,
        "options": {"railing": {**cfg, "lengthMm": 3000, "panels": 4},
                    "railingQuote": compute_railing({**cfg, "lengthMm": 3000, "panels": 4})},
    }, include_preview=False))
    lines.append(calc_sh)
    lines.append(calculate_line({
        "product": "shower_partition",
        "productType": "shower_partition",
        "width": 1200,
        "height": 2000,
        "qty": 1,
        "sellingRate": 800,
        "saleUnit": "sqft",
        "options": {
            "shower": {"shape": "straight", "operation": "sliding", "widthMm": 1200, "heightMm": 2000,
                       "manualRatePerUnit": 800, "saleUnit": "sqft"},
        },
    }, include_preview=False))
    _ok(len(lines) == 15, f"15 lines got {len(lines)}", fails)

    t0 = time.perf_counter()
    pdf = render_marqt_pdf(
        {"branding": {"companyName": "SMOKE CO", "primaryColor": [0.1, 0.2, 0.3]}},
        {"quotationId": "QT-MIX-15", "customer": "Mix", "lines": lines, "price": {"total": 1}},
    )
    pdf_s = time.perf_counter() - t0
    _ok(pdf.startswith(b"%PDF"), "mixed PDF bytes", fails)
    _ok(b"Railing design" not in pdf, "full quote has no railing placeholder", fails)
    _ok(pdf_s < 8.0, f"15-line PDF {pdf_s:.2f}s (target <8s)", fails)
    print(f"OK mixed quote PDF {pdf_s:.2f}s · {len(pdf)} bytes")

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print("OK special pdf draw + live amounts + mixed speed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
