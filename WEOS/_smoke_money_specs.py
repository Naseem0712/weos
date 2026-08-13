"""Quick verify: money aggregates + tabular specs for window + railing."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_money_specs_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    fails: list[str] = []
    from WEOS.db.engine import init_db
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.customer_store import save_customer_profile
    from WEOS.factory.ledger_store import build_ledger, quote_money_parts
    from WEOS.factory.marqt_pdf import _spec_lines, _spec_rows, render_marqt_pdf
    from WEOS.factory.project_store import empty_project, save_project

    init_db()
    parts = quote_money_parts(100000)
    if parts["totalTaxable"] != 100000 or parts["totalGrand"] != 118000 or parts["totalGst"] != 18000:
        fails.append(f"quote_money_parts bad: {parts}")

    gst = "27CCCCC0000C1Z5"
    cust = "Money Specs Customer"
    open_workspace(gst, profile={"companyName": "Money Specs Co"})
    save_customer_profile(cust, {"name": cust, "companyGst": gst})
    p = empty_project(name="Live Quote", customer=cust)
    p["companyGst"] = gst
    p["quotationId"] = "QT-MONEY-1"
    p["lastCalculation"] = {"price": {"total": 100000.0}}
    save_project(p, action="smoke")

    led = build_ledger(cust, company_gst=gst)
    t = led["totals"]
    ws = open_workspace(gst)
    dash = ws["dashboard"]
    if abs(float(t["totalTaxable"]) - 100000) > 0.01:
        fails.append(f"ledger taxable {t}")
    if abs(float(t["totalGrand"]) - 118000) > 0.01:
        fails.append(f"ledger grand {t}")
    if abs(float(dash["totalTaxable"]) - float(t["totalTaxable"])) > 0.01:
        fails.append("hub taxable != ledger")
    if abs(float(dash["totalGrand"]) - float(t["totalGrand"])) > 0.01:
        fails.append("hub grand != ledger")

    # Sliding window-ish specs
    win = {
        "product": "35mm_sliding",
        "displayName": "35mm Sliding Window",
        "width": 2760,
        "height": 2380,
        "layout": {"widthMm": 2760, "heightMm": 2380, "glassCount": 2, "trackCount": 2},
        "options": {"colour": "bronze", "handleName": "C Handle", "glass": "10mm_clear_toughened"},
        "glass": [{"thicknessMm": 10, "name": "Clear Toughened"}],
        "hardware": [{"name": "AAA"}, {"name": "BBB", "colour": "SS"}],
        "sectionSpecs": {"seriesTitle": "35mm Sliding", "track": "Outer track", "sash": "Shutter"},
    }
    rows = _spec_rows(win)
    labels = [r[0] for r in rows if r[0]]
    blob = " | ".join(f"{a}: {b}" for a, b in rows)
    for need in ("SIZE", "GLASS", "HARDWARE", "COLOUR", "HANDLE", "TRACK", "SERIES", "MESH"):
        if need not in labels:
            fails.append(f"window missing {need} in {labels}")
    if "SIZE: 2760" not in blob.replace("×", "x") and "2760" not in blob:
        fails.append(f"window size missing: {blob}")
    lines = _spec_lines(win)
    if any("=" in s.split(":")[0] for s in lines if ":" in s):
        fails.append("window still using = delimiters in labels")

    win_dump = {
        **win,
        "layout": {
            **(win.get("layout") or {}),
            "panels": [
                {"id": "S1", "label": "Sliding", "role": "sliding", "widthMm": 1348.8, "heightMm": 2317.6},
            ],
        },
    }
    dump_blob = " ".join(f"{a}: {b}" for a, b in _spec_rows(win_dump)).upper()
    if "PANELS:" in dump_blob and "1348" in dump_blob:
        fails.append("window specs still dump PANELS mm sizes")

    # Railing specs
    rail = {
        "product": "glass_railing",
        "category": "Railings",
        "width": 3000,
        "height": 1100,
        "options": {
            "railing": {
                "shape": "straight",
                "mountType": "side_mount",
                "glassThicknessMm": 12,
                "glassType": "Clear Toughened",
                "systemColor": "SS 304",
            }
        },
        "railingQuote": {
            "shape": "straight",
            "lengthMm": 3000,
            "heightMm": 1100,
            "panelCount": 3,
            "gapMm": 12,
            "glassThicknessMm": 12,
            "glassType": "Clear Toughened",
            "lengthRft": 10,
            "pillarCount": 4,
            "anchorCount": 8,
            "bomDetails": [],
        },
    }
    rrows = _spec_rows(rail)
    rlabels = [r[0] for r in rrows if r[0]]
    for need in ("SIZE", "GLASS", "TYPE", "HARDWARE", "MOUNT"):
        if need not in rlabels:
            fails.append(f"railing missing {need} in {rlabels}")
    rblob = " ".join(f"{a}: {b}" for a, b in rrows)
    if " @ " in rblob:
        fails.append(f"customer railing specs leaked rates: {rblob}")

    from WEOS.factory.design_photo import save_design_photo, design_photo_bytes_by_key
    from WEOS.factory.marqt_pdf import _line_design_photo_bytes
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    info = save_design_photo("smoke_p", "smoke_l", png, filename="design.png", content_type="image/png")
    raw, _ct = design_photo_bytes_by_key(info["key"])
    if not raw:
        fails.append("design photo durable blob round-trip failed")
    photo_line = {**win, "designPhoto": {"key": info["key"], "filename": "design.png"}}
    got, _ = _line_design_photo_bytes(photo_line)
    if not got:
        fails.append("PDF photo lookup failed")

    pdf = render_marqt_pdf(
        {"branding": {"companyName": "TEST CO", "primaryColor": [0.1, 0.2, 0.3]}},
        {
            "quotationId": "AK-26/TEST/A1",
            "customer": cust,
            "lines": [win, rail],
            "price": {"total": 100000},
        },
    )
    if not pdf.startswith(b"%PDF"):
        fails.append("PDF not generated")
    out = _tmp / "specs.pdf"
    out.write_bytes(pdf)
    print("PDF", out, "bytes", len(pdf))

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("OK money + specs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
