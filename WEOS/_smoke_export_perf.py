"""10-line quote PDF + Excel should finish in a few seconds locally."""
from __future__ import annotations

import time

from WEOS.factory.export_xlsx import export_quote_xlsx
from WEOS.factory.marqt_pdf import render_marqt_pdf
from WEOS.factory.project_engine import calculate_line


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def _win(i: int) -> dict:
    w = 1200 + (i % 5) * 80
    h = 1400 + (i % 4) * 60
    return calculate_line({
        "product": "29mm_sliding",
        "displayName": f"Sliding {i+1}",
        "width": w,
        "height": h,
        "qty": 1,
        "glass": "5mm_clear" if i % 2 == 0 else "10mm_toughened",
        "colour": "white",
        "sellingRate": 850,
        "saleUnit": "sqft",
        "locationName": f"Room {i+1}",
        "system": "sliding",
        "trackCount": 2,
        "glassShutters": 2,
    }, include_preview=False)


def _rail(length: int, rate: float) -> dict:
    return calculate_line({
        "product": "railing",
        "productType": "railing",
        "width": length,
        "height": 1000,
        "qty": 1,
        "sellingRate": rate,
        "saleUnit": "rft",
        "options": {
            "railing": {
                "shape": "straight",
                "lengthMm": length,
                "heightMm": 1000,
                "panels": 3,
                "bottomKind": "continuous",
                "bottomSize": "100×45",
                "handrailSize": "25×25",
                "continuousRail": True,
                "handrail": True,
                "anchorSpacingFt": 2,
                "installComponents": {
                    "bottomRail": True, "block": False, "ssPillar": False,
                    "handrail": True, "glass": True,
                },
                "manualRatePerUnit": rate,
            },
        },
    }, include_preview=False)


def _shower(w: int, h: int, shape: str = "straight", op: str = "sliding") -> dict:
    return calculate_line({
        "product": "shower_partition",
        "productType": "shower_partition",
        "width": w,
        "height": h,
        "qty": 1,
        "sellingRate": 900,
        "saleUnit": "sqft",
        "options": {
            "shower": {
                "shape": shape,
                "operation": op,
                "widthMm": w,
                "heightMm": h,
                "depthMm": 900 if shape == "L" else 0,
                "manualRatePerUnit": 900,
                "saleUnit": "sqft",
                "handle": True,
            },
        },
    }, include_preview=False)


def main() -> None:
    lines = [_win(i) for i in range(11)]
    lines.append(_rail(2050, 2550))
    lines.append(_rail(3000, 520))
    lines.append(_shower(1750, 2130, "L", "hinged"))
    lines.append(_shower(1200, 2000, "straight", "sliding"))
    _ok(len(lines) == 15, f"15 lines got {len(lines)}")

    # Use already-calculated lines (don't re-run calculate_project — glass lists break generate_job).
    t0 = time.perf_counter()
    pdf = render_marqt_pdf(
        {"branding": {"companyName": "PERF CO", "primaryColor": [0.1, 0.2, 0.3]}},
        {"quotationId": "QT-PERF-10", "customer": "Perf", "lines": lines, "price": {"total": 1}},
    )
    pdf_s = time.perf_counter() - t0
    _ok(pdf.startswith(b"%PDF"), "PDF bytes")
    _ok(b"50" in pdf or b"100" in pdf, "PDF contains railing sizes")

    t2 = time.perf_counter()
    xlsx = export_quote_xlsx(
        {"quotationId": "QT-PERF-10", "customer": "Perf", "lines": lines, "price": {"total": 1}},
        {"companyName": "PERF CO"},
        embed_drawings="thumb",
    )
    xls_s = time.perf_counter() - t2
    _ok(len(xlsx) > 2000, f"xlsx bytes {len(xlsx)}")

    # Local target: a few seconds. ReportLab elevations — no multi-megapixel Cairo.
    _ok(pdf_s < 8.0, f"PDF {pdf_s:.2f}s")
    _ok(xls_s < 25.0, f"Excel {xls_s:.2f}s")
    _ok(b"Railing design" not in pdf, "no railing placeholder")
    print(f"OK export perf · pdf {pdf_s:.2f}s · xlsx {xls_s:.2f}s")


if __name__ == "__main__":
    main()
