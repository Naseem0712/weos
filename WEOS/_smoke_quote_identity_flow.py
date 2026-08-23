"""Smoke: quote/customer identity stays locked; branded customer PDF stays detailed."""

from __future__ import annotations

import fitz

from WEOS.factory.pdf_engine import build_customer_pdf_bytes
from WEOS.factory.project_store import empty_project, save_project


def ok(msg: str) -> None:
    print("OK:", msg)


def fail(msg: str) -> None:
    raise SystemExit("FAIL: " + msg)


doc = empty_project(name="Identity Smoke", customer="Aditya ji")
doc["companyGst"] = "36ARWPA9740L1Z3"
doc["customerMobile"] = "+966 50 222 3786"
doc["quotationId"] = "AK-SMOKE/00001/A1"
doc["lines"] = [
    {
        "lineId": "w1",
        "product": "29mm_sliding",
        "displayName": "Sliding Window",
        "width": 1200,
        "height": 1500,
        "qty": 1,
        "options": {"glass": "8 mm", "colour": "Matt Black"},
        "price": {"total": 1000},
    }
]
saved = save_project(doc, action="identity_smoke_create")
ok("created identity-locked quote")

changed = dict(saved)
changed["customer"] = "Komal ji"
changed["customerMobile"] = "9999999999"
try:
    save_project(changed, action="identity_smoke_bad_customer")
except ValueError:
    ok("blocked customer swap on existing quote")
else:
    fail("customer swap was allowed")

payload = {
    "brand": "allkraft",
    "templateId": "marqt_customer",
    "projectId": saved["projectId"],
    "quotationId": saved["quotationId"],
    "customer": saved["customer"],
    "name": saved["name"],
    "lines": [
        {
            "displayName": "Sliding Window",
            "width": 1200,
            "height": 1500,
            "qty": 1,
            "options": {"glass": "8 mm", "colour": "Matt Black"},
            "price": {"total": 1000},
            "selling": {"sellingAmount": 1000, "sellingRate": 1000},
        }
    ],
    "price": {"currency": "INR", "total": 1000, "categoryTotals": {}},
    "combined": {"grandTotal": 1000},
}
pdf = build_customer_pdf_bytes(payload)
text = "\n".join(page.get_text() for page in fitz.open(stream=pdf, filetype="pdf"))
if "DESIGN" not in text or "Terms & Conditions" not in text:
    fail("branded customer PDF lost detailed layout")
if "Customer Quotation" in text:
    fail("branded customer PDF fell back to basic table")
ok("branded customer PDF uses detailed layout")
print("SMOKE_QUOTE_IDENTITY_FLOW_OK")
