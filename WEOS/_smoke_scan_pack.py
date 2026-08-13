"""Smoke: scan amounts/locations, card ledger, quote sheet branding, post-approval pack."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_scan_pack_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)


def _ok(cond: bool, msg: str, fails: list[str]) -> None:
    if not cond:
        fails.append(msg)
        print("FAIL:", msg)
    else:
        print("OK:", msg)


def _pdf_plain_text(raw: bytes) -> str:
    import base64
    import re
    import zlib

    def _decode_stream(data: bytes) -> bytes:
        data = data.strip()
        if data.startswith(b"\r\n"):
            data = data[2:]
        elif data.startswith(b"\n"):
            data = data[1:]
        if b"~>" in data:
            try:
                decoded = base64.a85decode(data, adobe=True)
                try:
                    return zlib.decompress(decoded)
                except Exception:
                    return decoded
            except Exception:
                pass
        try:
            return zlib.decompress(data)
        except Exception:
            return data

    chunks: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        try:
            payload = _decode_stream(m.group(1))
            chunks.append(payload.decode("latin-1", errors="ignore"))
        except Exception:
            continue
    chunks.append(raw.decode("latin-1", errors="ignore"))
    return "\n".join(chunks)


def main() -> int:
    fails: list[str] = []
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from WEOS.db.engine import init_db
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.customer_line_view import customer_line_amount, customer_type_label, public_product_row
    from WEOS.factory.customer_quote_pdf import render_customer_quote_sheet
    from WEOS.factory.customer_store import save_customer_profile
    from WEOS.factory.ledger_pdf import render_ledger_html, render_ledger_pdf
    from WEOS.factory.ledger_store import build_ledger
    from WEOS.factory.project_pack import add_file, add_update
    from WEOS.factory.project_store import empty_project, save_project, set_project_status
    from WEOS.factory.quote_share import build_public_quote_record, render_scan_html
    from WEOS.factory.scan_all_pdf import render_scan_all_pdf

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}", fails)

    eco = {
        "product": "25mm_eco_gulf",
        "productType": "sliding",
        "width": 1500,
        "height": 1200,
        "qty": 2,
        "sellingRate": 450,
        "saleUnit": "sqft",
        "locationName": "Hall",
        "positionName": "Hall",
        "glass": "8mm_toughened",
        "colour": "white",
    }
    row = public_product_row(0, eco)
    _ok(row["serial"] == "W1", f"serial W1 got {row['serial']}", fails)
    _ok(row["location"] == "Hall", f"location Hall got {row['location']}", fails)
    _ok("Sliding" in str(row["type"]), f"type sliding got {row['type']}", fails)
    _ok(float(row["amount"] or 0) > 0, f"eco amount recomputed {row['amount']}", fails)
    _ok("8" in str(row["glass"]) or "tough" in str(row["glass"]).lower(), f"glass human {row['glass']}", fails)
    _ok(float(customer_line_amount(eco) or 0) > 0, "customer_line_amount eco", fails)

    cas = {
        "product": "casement_stub",
        "displayName": "Fixed Light (coming soon)",
        "productType": "casements",
        "width": 1000,
        "height": 1200,
        "qty": 1,
        "sellingRate": 800,
    }
    _ok(customer_type_label(cas) == "Casement", f"casement label {customer_type_label(cas)}", fails)
    _ok("coming soon" not in customer_type_label(cas).lower(), "no coming soon", fails)
    _ok("stub" not in customer_type_label(cas).lower(), "no stub id", fails)

    gst = "27AAAAA0000A1Z5"
    open_workspace(gst, profile={"companyName": "ALLUKRAFT", "phone": "9000000001"})
    save_customer_profile("Scan Cust", {"name": "Scan Cust", "phone": "9876500099", "companyGst": gst})

    doc = empty_project(name="Scan quote", customer="Scan Cust")
    doc["companyGst"] = gst
    doc["quotationId"] = "AK-26/00001/A1"
    doc["status"] = "draft"
    doc["lines"] = [eco, cas]
    doc["lastCalculation"] = {"price": {"total": 0}}
    doc = save_project(doc, action="smoke")
    rec = build_public_quote_record(str(doc.get("shareToken") or doc["projectId"])) or {}
    _ok(not rec.get("approved"), "unapproved", fails)
    _ok(not (rec.get("pack") or {}).get("available"), "pack hidden while draft", fails)
    html = render_scan_html(rec).lower()
    _ok("available after approval" in html, "draft copy", fails)
    prods = rec.get("products") or []
    _ok(all(float(p.get("amount") or 0) > 0 for p in prods), f"all scan amounts >0 {prods}", fails)
    _ok(any("Hall" in str(p.get("location") or "") for p in prods), "scan location passed", fails)

    try:
        add_update(doc["projectId"], "too early")
        fails.append("update before approval must fail")
    except (PermissionError, ValueError):
        print("OK: update blocked")

    set_project_status(doc["projectId"], "approved")
    add_update(doc["projectId"], "Glass fixed", date="2026-08-13")
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05"
        b"\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    add_file(doc["projectId"], kind="photo", raw=png, filename="p.png", content_type="image/png")
    add_file(doc["projectId"], kind="challan", raw=b"%PDF-1.4 x", filename="c.pdf", content_type="application/pdf", note="DC")

    rec2 = build_public_quote_record(str(doc.get("shareToken") or doc["projectId"])) or {}
    _ok(rec2.get("approved"), "approved flag", fails)
    pack = rec2.get("pack") or {}
    _ok(pack.get("available"), "pack available", fails)
    _ok(len(pack.get("updates") or []) == 1, "1 update", fails)
    _ok(len(pack.get("photos") or []) == 1, "1 photo", fails)
    _ok(len(pack.get("documents") or []) == 1, "1 challan", fails)
    html2 = render_scan_html(rec2).lower()
    _ok("glass fixed" in html2 and "process updates" in html2, "scan shows timeline", fails)
    _ok("download all" in html2, "download all button", fails)
    _ok("available after approval" not in html2, "no pending copy after approve", fails)
    _ok(render_scan_all_pdf(rec2).startswith(b"%PDF"), "all.pdf", fails)

    sheet = render_customer_quote_sheet(
        {
            "company": {"companyName": "ALLUKRAFT", "gstNo": gst},
            "customer": "Scan Cust",
            "quotationId": "AK-26/00001/A1",
            "lines": [eco, cas],
        }
    )
    _ok(sheet.startswith(b"%PDF"), "quote sheet pdf", fails)
    sheet_txt = _pdf_plain_text(sheet).upper()
    _ok("WOODENMAX" not in sheet_txt, "not woodenmax", fails)
    _ok("ALLUKRAFT" in sheet_txt, "allukraft branding", fails)
    _ok("COMING SOON" not in sheet_txt, "no coming soon in sheet", fails)
    _ok("HALL" in sheet_txt, "location in sheet", fails)

    led = build_ledger("Scan Cust")
    pdf = render_ledger_pdf(led, {"companyName": "ALLUKRAFT", "gstNo": gst})
    _ok(pdf.startswith(b"%PDF"), "ledger pdf", fails)
    led_txt = _pdf_plain_text(pdf).upper()
    _ok("CUSTOMER ACCOUNT LEDGER" in led_txt, "ledger title", fails)
    _ok("WOODENMAX" not in led_txt, "ledger not woodenmax", fails)
    page = render_ledger_html(led, {"companyName": "ALLUKRAFT", "gstNo": gst}).lower()
    _ok("customer account ledger" in page and "taxable" in page, "ledger html cards", fails)

    if fails:
        print("FAIL scan/pack smoke")
        for f in fails:
            print(" -", f)
        return 1
    print("OK scan amounts + ledger cards + quote branding + project pack")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
