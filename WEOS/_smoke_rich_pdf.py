"""Smoke test: rich text (bold) in quote PDF description & terms."""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_rich_pdf_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

from WEOS.factory.marqt_pdf import render_marqt_pdf
from WEOS.factory.pdf_rich_text import _parse_spans, has_rich_markers, html_paste_to_markdown


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    md = html_paste_to_markdown("<p><strong>PRODUCT SPECIFICATIONS</strong></p><p>Plain line here.</p>")
    _ok("**PRODUCT SPECIFICATIONS**" in md, f"html paste to markdown: {md!r}")
    _ok(has_rich_markers("**Bold** and plain"), "detects markdown bold")
    _ok(not has_rich_markers("Plain text only"), "plain text has no rich markers")

    spans = _parse_spans("Before **Bold bit** after")
    _ok(any(b for _, b in spans), "parse spans finds bold")
    _ok("Bold bit" in "".join(t for t, _ in spans), f"bold text preserved: {spans}")

    tmpl = {"branding": {"companyName": "RICH TEST CO", "primaryColor": [0.1, 0.2, 0.3]}}
    payload = {
        "quotationId": "QT-RICH-1",
        "customer": "Rich Text Test",
        "lines": [],
        "price": {"total": 0},
        "description": "SYSTEM WINDOWS\n\n**PRODUCT SPECIFICATIONS**\n\nSystem Type: Premium window.\nPlain paragraph continues.",
        "terms": "**PAYMENT TERMS**\n\n50% Advance against PO.\n\n**WARRANTY TERMS**\n\n10 years powder coating.",
    }
    pdf = render_marqt_pdf(tmpl, payload)
    _ok(pdf.startswith(b"%PDF"), "PDF bytes")
    _ok(len(pdf) > 4000, f"PDF size {len(pdf)}")

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        _ok("PRODUCT SPECIFICATIONS" in text, "description text present")
        _ok("PAYMENT TERMS" in text, "terms text present")
        _ok("Plain paragraph" in text, "plain text preserved")

        fonts = set()
        for page in reader.pages:
            res = page.get("/Resources")
            if not res:
                continue
            font_ref = res.get("/Font")
            if not font_ref:
                continue
            for name in font_ref:
                try:
                    fobj = font_ref[name].get_object()
                    base = fobj.get("/BaseFont") or fobj.get("/Name")
                    if base:
                        fonts.add(str(base))
                except Exception:
                    pass
        boldish = [f for f in fonts if "bold" in f.lower() or "-bd" in f.lower()]
        _ok(boldish, f"PDF uses bold font variant: {sorted(fonts)}")
    except ImportError:
        _ok(b"**" not in pdf, "binary PDF does not contain literal ** markers")

    plain_pdf = render_marqt_pdf(
        tmpl,
        {**payload, "description": "Plain description without any markers.", "terms": "1. Plain term.\n2. Another term."},
    )
    _ok(plain_pdf.startswith(b"%PDF") and len(plain_pdf) > 4000, "plain-text PDF still generates")

    print("ALL RICH PDF CHECKS PASSED")


if __name__ == "__main__":
    main()
