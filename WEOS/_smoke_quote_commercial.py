"""Smoke: line add-ons, soft-cancel, commercial buckets, markdown bold."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_quote_commercial_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

from WEOS.factory.line_addons import is_line_cancelled, line_addons_total, normalize_addon
from WEOS.factory.pdf_rich_text import markdown_emphasis_to_html
from WEOS.factory.quote_commercial import quote_commercial_breakdown
from WEOS.factory.quote_share import render_scan_html


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    ad = normalize_addon({"name": "Automatic system", "note": "per door", "qty": 2, "rate": 1500})
    _ok(ad and ad["amount"] == 3000, f"addon amount {ad}")

    sliding1 = {
        "product": "29mm_sliding",
        "productType": "sliding",
        "system": "sliding",
        "width": 1200,
        "height": 1500,
        "qty": 2,
        "sellingRate": 800,
        "saleUnit": "sqft",
        "displayName": "Sliding A",
    }
    sliding2 = {
        **sliding1,
        "qty": 1,
        "displayName": "Sliding B cancelled",
        "cancelled": True,
        "addons": [{"name": "Should not count", "qty": 1, "rate": 9999}],
    }
    casement = {
        "product": "casement_stub",
        "productType": "casements",
        "system": "casement",
        "width": 1000,
        "height": 1200,
        "qty": 1,
        "sellingRate": 900,
        "saleUnit": "sqft",
        "displayName": "Casement",
        "addons": [{"name": "Automatic system", "note": "per door", "qty": 2, "rate": 1500}],
    }
    _ok(is_line_cancelled(sliding2), "cancelled detected")
    _ok(line_addons_total(casement) == 3000, f"casement addons {line_addons_total(casement)}")
    _ok(line_addons_total(sliding2) == 0, "cancelled addons excluded from money total")

    br = quote_commercial_breakdown(
        [sliding1, sliding2, casement],
        discount={"mode": "percent", "percent": 10},
    )
    _ok(br["sliding"]["qty"] == 2, f"sliding qty 2 got {br['sliding']['qty']}")
    _ok(br["casement"]["qty"] == 1, f"casement qty 1 got {br['casement']['qty']}")
    _ok(br["addServices"] == 3000, f"add services 3000 got {br['addServices']}")
    _ok(br["sliding"]["amount"] > 0 and br["casement"]["amount"] > 0, "product buckets have amounts")
    _ok(br["beforeGst"] == round(br["productsTotal"] + br["addServices"], 2), "before GST = products + services")
    _ok(abs(br["discountPercent"] - 10) < 0.01, f"discount % {br['discountPercent']}")
    _ok(br["grandTotal"] == round(br["afterDiscount"] + br["gstAmount"], 2), "grand = after disc + GST")
    _ok(br["sliding"]["avgRate"] is not None, "sliding avg rate")
    _ok(br["casement"]["avgRate"] is not None, "casement avg rate")

    html = markdown_emphasis_to_html("Install **Automatic door** today")
    _ok("<strong>Automatic door</strong>" in html, f"html bold {html}")
    _ok("**" not in html, f"no stars left {html}")
    _ok("&lt;" in markdown_emphasis_to_html("<script>**x**</script>") or "<strong>" in markdown_emphasis_to_html("a **b** c"), "escape or bold ok")
    esc_html = markdown_emphasis_to_html("See <script>alert(1)</script> and **safe**")
    _ok("<script>" not in esc_html and "<strong>safe</strong>" in esc_html, f"xss-safe {esc_html}")

    scan = render_scan_html(
        {
            "quoteNumber": "QT-BOLD-1",
            "status": "draft",
            "company": {"name": "Bold Co"},
            "customer": {"name": "Cust"},
            "value": {"totalTaxable": 1000, "totalGst": 180, "totalGrand": 1180, "gstPercent": 18},
            "description": "Includes **Automatic door** hardware",
            "terms": "Warranty on __frames__ only",
            "products": [
                {
                    "serial": "W1",
                    "location": "Hall",
                    "type": "Sliding",
                    "size": "1200×1500",
                    "qty": 1,
                    "amount": 1000,
                    "addons": [{"name": "Automatic system", "qty": 2, "rate": 1500, "amount": 3000}],
                    "addonLabels": ["Automatic system · 2 × ₹1,500.00 · ₹3,000.00"],
                },
                {
                    "serial": "W2",
                    "location": "Bed",
                    "type": "Sliding",
                    "size": "1200×1500",
                    "qty": 1,
                    "amount": 800,
                    "cancelled": True,
                },
            ],
            "typeTotals": [],
            "advances": [],
            "pack": {},
            "permissions": {"showDesign": True, "showRate": True, "showAmount": True, "showAdvances": True},
        }
    )
    _ok("<strong>Automatic door</strong>" in scan, "scan HTML has real bold")
    _ok("**Automatic door**" not in scan, "scan HTML has no raw ** markers for that phrase")
    _ok("CANCELLED" in scan, "scan shows CANCELLED")
    _ok("Automatic system" in scan, "scan shows under-window addon")

    # PDF bytes for marqt with addons + cancelled
    from WEOS.factory.marqt_pdf import render_marqt_pdf
    from WEOS.factory.project_engine import calculate_line

    calc_s = calculate_line(dict(sliding1))
    calc_c = calculate_line(dict(casement))
    calc_x = calculate_line(dict(sliding2))
    pdf = render_marqt_pdf(
        {"branding": {"companyName": "Smoke Co", "primaryColor": (0.12, 0.22, 0.38), "accentColor": (0.72, 0.12, 0.12)}},
        {
            "quotationId": "QT-COMM-1",
            "customer": "Smoke",
            "lines": [calc_s, calc_c, calc_x],
            "quoteDiscount": {"mode": "percent", "percent": 10},
            "description": "Note **Automatic door**",
            "terms": "Pay in **7 days**",
        },
    )
    _ok(isinstance(pdf, (bytes, bytearray)) and pdf[:4] == b"%PDF", f"marqt pdf {len(pdf)}")
    from io import BytesIO

    from pypdf import PdfReader

    def _pdf_text(raw: bytes) -> str:
        reader = PdfReader(BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    text = _pdf_text(pdf)
    _ok("CANCELLED" in text, f"pdf marks cancelled: {text[:400]!r}")
    _ok("Automatic" in text, f"pdf has addon name under window: {text[:500]!r}")
    _ok("**Automatic" not in text, "marqt description bold has no raw **Automatic")

    from WEOS.factory.scan_all_pdf import render_scan_all_pdf

    spdf = render_scan_all_pdf(
        {
            "quoteNumber": "QT-SCAN-BOLD",
            "company": {"name": "Bold Co"},
            "customer": {"name": "Cust"},
            "value": {"totalTaxable": 1000, "totalGst": 180, "totalGrand": 1180, "gstPercent": 18},
            "description": "Pack **Automatic door**",
            "terms": "See __terms__",
            "products": [],
            "advances": [],
            "pack": {},
        }
    )
    _ok(spdf[:4] == b"%PDF", "scan-all pdf")
    stext = _pdf_text(spdf)
    # ReportLab bold runs often extract as separate tokens; require both words and no markers.
    _ok("Automatic" in stext and "door" in stext, f"scan pdf draws bold text: {stext!r}")
    _ok("**" not in stext, "scan pdf no raw ** markers")
    _ok("terms" in stext.lower(), "scan pdf draws __terms__ as terms")

    print("SMOKE_QUOTE_COMMERCIAL_OK")


if __name__ == "__main__":
    main()
