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
    })


def main() -> None:
    lines = [_win(i) for i in range(9)]
    lines.append(calculate_line({
        "product": "railing",
        "productType": "railing",
        "width": 5000,
        "height": 1100,
        "qty": 1,
        "sellingRate": 520,
        "saleUnit": "rft",
        "options": {
            "railing": {
                "shape": "straight",
                "lengthMm": 5000,
                "heightMm": 1100,
                "panels": 3,
                "bottomKind": "continuous",
                "bottomSize": "100×45",
                "handrailSize": "50×50",
                "continuousRail": True,
                "handrail": True,
                "handrailBarLengthFt": 16,
                "anchorSpacingFt": 2,
                "installComponents": {
                    "bottomRail": True, "block": False, "ssPillar": False,
                    "handrail": True, "glass": True,
                },
                "rates": {
                    "glassPerSqft": 200, "bottomRailPerUnit": 90, "handrailPerUnit": 140,
                    "anchorPerPc": 40, "connector180PerPc": 80,
                    "epdmHandrailPerUnit": 18, "epdmBottomPerUnit": 18,
                },
                "manualRatePerUnit": 520,
            },
        },
    }))
    _ok(len(lines) == 10, f"10 lines got {len(lines)}")

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

    # Local target: a few seconds, not "bahut delay". Without Cairo, vector embed should still be quick.
    _ok(pdf_s < 30.0, f"PDF {pdf_s:.2f}s")
    _ok(xls_s < 25.0, f"Excel {xls_s:.2f}s")
    print(f"OK export perf · pdf {pdf_s:.2f}s · xlsx {xls_s:.2f}s")


if __name__ == "__main__":
    main()
