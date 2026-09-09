"""Batch A — PDF reliability: completeness, drawings, terms, determinism."""
from __future__ import annotations

import io
import os
import tempfile
from copy import deepcopy
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_pdf_rel_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

from WEOS.factory.marqt_pdf import render_marqt_pdf
from WEOS.factory.pdf_engine import build_customer_pdf_bytes, _minimal_text_pdf
from WEOS.factory.pdf_preflight import (
    PdfCompletenessError,
    assert_not_minimal_pdf,
    commercial_text_fingerprint,
    preflight_customer_pdf,
)
from WEOS.factory.project_engine import calculate_line
from WEOS.api.server import _coerce_cart_lines, _merge_calc_lines


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def _pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _tmpl(**branding_extra):
    branding = {
        "companyName": "RELIABILITY CO",
        "primaryColor": [0.1, 0.2, 0.3],
        "terms": "Company default: payment as agreed.",
    }
    branding.update(branding_extra)
    return {"branding": branding}


def _sliding(i: int = 1, **kw):
    base = {
        "lineId": f"SL-{i:03d}",
        "product": "29mm_sliding",
        "displayName": f"Sliding Window {i}",
        "width": 1200 + i * 10,
        "height": 1400,
        "qty": 1,
        "glass": "10mm_toughened",
        "colour": "black_texture",
        "handle": "premium",
        "sectionSeries": "25mm_eco_gulf",
        "trackCount": 2,
        "glassShutters": 2,
        "system": "sliding",
        "sellingRate": 890,
        "saleUnit": "sqft",
        "locationName": f"Room {i}",
        "description": f"Sliding desc {i}",
    }
    base.update(kw)
    return calculate_line(base)


def _casement(i: int = 1, **kw):
    base = {
        "lineId": f"CS-{i:03d}",
        "product": "29mm_sliding",
        "displayName": f"Casement {i}",
        "system": "casement",
        "width": 1100,
        "height": 2000,
        "qty": 1,
        "glass": "8mm_toughened",
        "glassShutters": 2,
        "sellingRate": 950,
        "sectionSeries": "25mm_eco_gulf",
        "saleUnit": "sqft",
        "locationName": f"Case {i}",
    }
    base.update(kw)
    return calculate_line(base)


def _ventilator(i: int = 1, **kw):
    base = {
        "lineId": f"VT-{i:03d}",
        "product": "bathroom_ventilator",
        "productType": "bathroom_ventilator",
        "displayName": f"Ventilator {i}",
        "width": 600,
        "height": 450,
        "qty": 1,
        "sellingRate": 420,
        "saleUnit": "nos",
        "options": {
            "ventilator": {"widthMm": 600, "heightMm": 450, "sellingRate": 420},
            "productType": "bathroom_ventilator",
        },
    }
    base.update(kw)
    return calculate_line(base)


def _railing(i: int = 1, **kw):
    base = {
        "lineId": f"RL-{i:03d}",
        "product": "railing",
        "productType": "railing",
        "displayName": f"Railing {i}",
        "width": 2400,
        "height": 1100,
        "qty": 1,
        "sellingRate": 850,
        "saleUnit": "rft",
        "options": {
            "railing": {
                "shape": "straight",
                "lengthMm": 2400,
                "heightMm": 1100,
                "sellingRate": 850,
            }
        },
    }
    base.update(kw)
    return calculate_line(base)


def _manual(i: int = 1, **kw):
    line = {
        "lineId": f"MN-{i:03d}",
        "itemKind": "MANUAL",
        "manualProduct": True,
        "product": "manual_custom",
        "productType": "manual",
        "displayName": f"Manual Product {i}",
        "description": f"Manual description {i}",
        "width": 900,
        "height": 1200,
        "qty": 2,
        "sellingRate": 1500,
        "saleUnit": "nos",
        "commercialTotal": 3000,
        "selling": {"sellingRate": 1500, "saleUnit": "nos", "sellingAmount": 3000},
        "options": {"itemKind": "MANUAL", "specs": "Powder coated mild steel"},
    }
    line.update(kw)
    return line


def main() -> None:
    # --- coerce strict ---
    existing = [{"lineId": "A1", "product": "29mm_sliding", "width": 1000, "height": 1200}]
    got = _coerce_cart_lines(["A1"], existing=existing, strict=True)
    _ok(len(got) == 1 and got[0]["lineId"] == "A1", "strict coerce resolves known id")
    try:
        _coerce_cart_lines(["MISSING-ID"], existing=existing, strict=True)
        raise SystemExit("FAIL: strict coerce should raise on missing id")
    except PdfCompletenessError as exc:
        _ok("MISSING-ID" in exc.missing_ids, f"missing id reported: {exc.missing_ids}")

    soft = _coerce_cart_lines(["MISSING-ID"], existing=existing, strict=False)
    _ok(soft == [], "non-strict still drops unknown id")

    # --- merge preserves durable SVG ---
    cart = [
        {
            "lineId": "P1",
            "product": "29mm_sliding",
            "width": 1000,
            "height": 1200,
            "preview": {"svg": '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', "key": "k1"},
            "designPhoto": {"key": "photo-1"},
        }
    ]
    calc = [
        {
            "lineId": "P1",
            "product": "29mm_sliding",
            "width": 1000,
            "height": 1200,
            "preview": {"svg": None},
            "price": {"total": 100},
        }
    ]
    merged = _merge_calc_lines(cart, calc)
    _ok(
        merged
        and "<svg" in str((merged[0].get("preview") or {}).get("svg") or ""),
        "merge keeps cart preview.svg when calc null",
    )
    _ok(merged[0].get("designPhoto", {}).get("key") == "photo-1", "merge keeps designPhoto")

    # --- mixed Sliding + Casement + Ventilator + Railing + Manual ---
    lines = [
        _sliding(1),
        _casement(1),
        _ventilator(1),
        _railing(1),
        _manual(1),
    ]
    ids = [ln["lineId"] for ln in lines]
    terms = "1. Payment 50% advance.\n2. Balance before dispatch.\n3. Validity 15 days."
    desc = "PROJECT SCOPE: Mixed aluminium package for reliability test."
    payload = {
        "quotationId": "QT-REL-1",
        "customer": "Reliability Customer",
        "createdOn": "01-01-2026",
        "quoteDate": "01-01-2026",
        "shareToken": "fixed-share-token",
        "description": desc,
        "terms": terms,
        "lines": lines,
        "price": {"total": 1},
        "pdfFailClosed": True,
        "pdfExpectedLineIds": ids,
        "branding": {"companyName": "RELIABILITY CO", "terms": "Company fallback terms"},
    }
    report = preflight_customer_pdf(
        payload,
        expected_line_ids=ids,
        allow_builtin_terms=False,
        strict_drawings=True,
    )
    _ok(report["status"] == "READY", f"preflight READY {report}")

    pdf = render_marqt_pdf(_tmpl(), payload)
    _ok(pdf.startswith(b"%PDF"), "mixed PDF bytes")
    assert_not_minimal_pdf(pdf)
    text = _pdf_text(pdf)
    # Titles come from product formatters (e.g. bathroom vent uses
    # "Bathroom ventilator · …", not the cart displayName alone).
    text_l = text.lower()
    for needle in ("Sliding", "Casement", "Bathroom ventilator", "Railing", "Manual Product"):
        _ok(needle.lower() in text_l, f"item family present in PDF text: {needle}")
    for ln in lines:
        label = str(ln.get("displayName") or ln.get("product") or "")
        token = label.split()[0] if label.split() else ""
        # Ventilator displayName may be replaced by bathroom-vent title in PDF.
        if "ventilator" in label.lower() or str(ln.get("productType") or "").lower().endswith("ventilator"):
            _ok("bathroom ventilator" in text_l, f"line label in PDF: {label!r}")
            continue
        _ok(not token or token in text or label in text, f"line label in PDF: {label!r}")
    _ok("Payment 50% advance" in text or "50% advance" in text, "terms rendered")
    _ok("PROJECT SCOPE" in text or "Mixed aluminium" in text, "description rendered")
    _ok("demo terms" not in text.lower(), "no demo terms substitute")

    # --- drawing unavailable must fail (not silent omit) ---
    bad = deepcopy(payload)
    bad["lines"] = [
        {
            "lineId": "BAD-01",
            "product": "",
            "displayName": "Broken Engineered",
            "width": 0,
            "height": 0,
            "qty": 1,
            "sellingRate": 10,
            "saleUnit": "nos",
        }
    ]
    bad["pdfExpectedLineIds"] = ["BAD-01"]
    try:
        preflight_customer_pdf(
            bad,
            expected_line_ids=["BAD-01"],
            allow_builtin_terms=False,
            strict_drawings=True,
        )
        raise SystemExit("FAIL: preflight should reject undrawable engineered line")
    except PdfCompletenessError as exc:
        _ok("BAD-01" in exc.missing_ids or any("drawing" in e.lower() for e in exc.errors), f"drawing fail {exc}")

    # Manual without drawing is OK
    man_only = deepcopy(payload)
    man_only["lines"] = [_manual(9)]
    man_only["pdfExpectedLineIds"] = ["MN-009"]
    preflight_customer_pdf(
        man_only,
        expected_line_ids=["MN-009"],
        allow_builtin_terms=False,
        strict_drawings=True,
    )
    _ok(True, "manual product preflight without drawing READY")
    man_pdf = render_marqt_pdf(_tmpl(), man_only)
    _ok("Manual Product 9" in _pdf_text(man_pdf), "manual product renders name")

    # --- expected items must equal rendered ---
    short = deepcopy(payload)
    short["lines"] = lines[:2]
    short["pdfExpectedLineIds"] = ids  # still expect all 5
    try:
        preflight_customer_pdf(
            short,
            expected_line_ids=ids,
            allow_builtin_terms=False,
            strict_drawings=True,
        )
        raise SystemExit("FAIL: count mismatch should fail preflight")
    except PdfCompletenessError as exc:
        _ok(len(exc.missing_ids) >= 3, f"missing ids reported on omit: {exc.missing_ids}")

    # --- terms exist must not be replaced by demo ---
    try:
        preflight_customer_pdf(
            {**payload, "terms": "Warranty: 1 year manufacturing defects (demo terms)."},
            expected_line_ids=ids,
            allow_builtin_terms=False,
        )
        raise SystemExit("FAIL: demo terms should be rejected")
    except PdfCompletenessError:
        _ok(True, "demo terms rejected by preflight")

    # failClosed render must not inject builtin when terms empty
    empty_terms = deepcopy(payload)
    empty_terms["terms"] = ""
    empty_terms["branding"] = {"companyName": "RELIABILITY CO"}
    pdf_et = render_marqt_pdf(_tmpl(terms=""), empty_terms)
    et = _pdf_text(pdf_et).lower()
    _ok("demo terms" not in et, "empty terms: no demo substitute")
    _ok("no terms supplied" in et or "terms & conditions" in et, "empty terms page explicit")

    # --- 3× deterministic commercial fingerprint ---
    fps = []
    for _ in range(3):
        p = deepcopy(payload)
        p["shareToken"] = "fixed-share-token"
        p["createdOn"] = "01-01-2026"
        p["quoteDate"] = "01-01-2026"
        out = render_marqt_pdf(_tmpl(), p)
        fps.append(commercial_text_fingerprint(out))
    _ok(fps[0] == fps[1] == fps[2], f"3× deterministic fingerprints {fps}")

    # --- large quote ---
    big_lines = []
    for i in range(1, 25):
        if i % 5 == 0:
            big_lines.append(_manual(i))
        elif i % 4 == 0:
            big_lines.append(_railing(i))
        elif i % 3 == 0:
            big_lines.append(_ventilator(i))
        elif i % 2 == 0:
            big_lines.append(_casement(i))
        else:
            big_lines.append(_sliding(i))
    big_ids = [ln["lineId"] for ln in big_lines]
    big_payload = {
        **payload,
        "quotationId": "QT-REL-BIG",
        "lines": big_lines,
        "pdfExpectedLineIds": big_ids,
    }
    preflight_customer_pdf(
        big_payload,
        expected_line_ids=big_ids,
        allow_builtin_terms=False,
        strict_drawings=True,
    )
    big_pdf = render_marqt_pdf(_tmpl(), big_payload)
    _ok(big_pdf.startswith(b"%PDF") and len(big_pdf) > 20000, f"large quote PDF {len(big_pdf)}")
    big_text = _pdf_text(big_pdf)
    big_l = big_text.lower()
    missing_names = []
    vent_needed = 0
    for ln in big_lines:
        label = str(ln.get("displayName") or ln.get("product") or "")
        token = (label.split()[0] if label.split() else "")
        ptype = str(ln.get("productType") or ln.get("product") or "").lower()
        # Bathroom vent PDF title omits cart displayName ("Ventilator N").
        if "ventilator" in ptype:
            vent_needed += 1
            continue
        if label and label not in big_text and token and token not in big_text:
            missing_names.append(label)
    vent_hits = big_l.count("bathroom ventilator")
    _ok(
        vent_hits >= vent_needed,
        f"large-quote ventilators present ({vent_hits}/{vent_needed})",
    )
    _ok(len(missing_names) <= 2, f"large-quote names mostly present (missing {missing_names[:5]})")
    _ok(len(big_ids) == 24, f"large quote line count {len(big_ids)}")

    # --- build_customer_pdf_bytes fail-closed refuses minimal ---
    try:
        assert_not_minimal_pdf(_minimal_text_pdf("WEOS Customer Quotation", {"projectId": "x"}))
        raise SystemExit("FAIL: minimal PDF should be refused")
    except PdfCompletenessError:
        _ok(True, "minimal PDF refused")

    fc_payload = deepcopy(payload)
    fc_pdf = build_customer_pdf_bytes(fc_payload)
    _ok(fc_pdf.startswith(b"%PDF"), "build_customer_pdf_bytes fail-closed works")
    assert_not_minimal_pdf(fc_pdf)

    # --- revision-ish content: updatedOn + same lines ---
    rev = deepcopy(payload)
    rev["quotationId"] = "QT-REL-1-R1"
    rev["updatedOn"] = "15-02-2026"
    rev_pdf = render_marqt_pdf(_tmpl(), rev)
    rev_text = _pdf_text(rev_pdf)
    _ok("Sliding Window 1" in rev_text and "15-02-2026" in rev_text, "revision date + content")

    print("ALL PDF RELIABILITY CHECKS PASSED")


if __name__ == "__main__":
    main()
