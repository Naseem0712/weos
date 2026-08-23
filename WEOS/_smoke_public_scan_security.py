"""Smoke: public scan hides raw mobile and uses last-6 verification language."""

from __future__ import annotations

from WEOS.factory.quote_share import (
    _mask_phone,
    render_access_verify_html,
    render_scan_html,
)


def main() -> None:
    raw = "9876543210"
    masked = _mask_phone(raw)
    assert masked == "******3210", masked

    record = {
        "shareToken": "tok123",
        "quoteNumber": "QT-SEC",
        "status": "draft",
        "approved": False,
        "version": 1,
        "versionCount": 1,
        "company": {"name": "Demo Co", "gstNo": "GST"},
        "customer": {"name": "Demo Customer", "phone": masked, "phoneMasked": masked, "verifyDigits": 6},
        "value": {"totalTaxable": 1000, "totalGst": 180, "totalGrand": 1180, "gstPercent": 18},
        "scanner": {"canApprove": True, "canReject": True, "generatedAt": "2026-01-01T00:00:00+00:00"},
        "approval": {},
        "rejection": {},
        "advances": [],
        "products": [],
        "accessGrants": [{"role": "Architect", "name": "Amit", "phoneMasked": "******4444"}],
    }
    html = render_scan_html(record)
    assert raw not in html
    assert masked in html
    assert "Customer mobile last 6 digits" in html
    assert "verifyLast6" in html
    assert "Generate monitor link" in html

    gate = render_access_verify_html(
        record,
        ref="tok123",
        access_token="acc123",
        grant={"role": "Architect", "name": "Amit", "phoneMasked": "******4444"},
    )
    assert "Access for:" in gate
    assert "Amit" in gate and "Architect" in gate and "******4444" in gate
    assert raw not in gate
    print("OK public scan security")


if __name__ == "__main__":
    main()
