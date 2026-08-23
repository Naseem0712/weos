"""Advance Receipt / Payment Slip PDF — letterhead + amount + stamp/sign."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Mapping


def _inr(n: Any) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    neg = v < 0
    v = abs(v)
    return ("-Rs." if neg else "Rs.") + f"{v:,.2f}"


def _txt(v: Any) -> str:
    return str(v or "").strip()


def render_advance_slip_pdf(
    advance: Mapping[str, Any],
    *,
    company: Mapping[str, Any] | None = None,
    ledger: Mapping[str, Any] | None = None,
    customer: str | None = None,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from WEOS.factory.media_assets import draw_stamp_signature_block, resolve_doc_images

    company = company or {}
    ledger = ledger or {}
    profile = (ledger.get("profile") if isinstance(ledger, Mapping) else None) or {}
    totals = (ledger.get("totals") if isinstance(ledger, Mapping) else None) or {}
    cust = _txt(customer or advance.get("customerName") or ledger.get("customer") or profile.get("name"))

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    M = 40
    primary = (0.12, 0.22, 0.38)

    # ── Letterhead (tight logo gap) ──────────────────────────────────────────
    y = H - M
    logo_path = company.get("logoPath")
    logo_w = 0.0
    logo_h = 0.0
    if logo_path:
        try:
            from pathlib import Path

            lp = Path(str(logo_path))
            if lp.is_file():
                img = ImageReader(str(lp))
                iw, ih = img.getSize()
                if iw > 0 and ih > 0:
                    scale = min(110 / float(iw), 56 / float(ih))
                    logo_w, logo_h = iw * scale, ih * scale
                    c.drawImage(img, M, y - logo_h, width=logo_w, height=logo_h, mask="auto")
        except Exception:
            logo_w = logo_h = 0.0

    text_x = M + ((logo_w + 10) if logo_h else 0)
    co_name = (_txt(company.get("companyName")) or "WEOS").upper()
    c.setFillColorRGB(*primary)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(text_x, y - 16, co_name[:70])
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.setFont("Helvetica", 8)
    ty = y - 30
    for bit in (
        _txt(company.get("tagline")),
        _txt(company.get("address")),
        " · ".join(
            x
            for x in (_txt(company.get("phone")), _txt(company.get("email")), _txt(company.get("website")))
            if x
        ),
        f"GSTIN: {_txt(company.get('gstNo'))}" if _txt(company.get("gstNo")) else "",
    ):
        if bit:
            c.drawString(text_x, ty, bit[:95])
            ty -= 11
    header_bottom = min(y - max(logo_h, 52) - 8, ty - 4)
    c.setStrokeColorRGB(*primary)
    c.setLineWidth(1.1)
    c.line(M, header_bottom, W - M, header_bottom)

    y = header_bottom - 28
    c.setFillColorRGB(*primary)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(W / 2, y, "ADVANCE RECEIPT / PAYMENT SLIP")
    y -= 22

    slip_no = _txt(advance.get("slipNo") or advance.get("id") or advance.get("advanceId")) or "—"
    paid = _txt(advance.get("paidAt") or advance.get("date"))[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 10)
    c.drawString(M, y, f"Slip No: {slip_no}")
    c.drawRightString(W - M, y, f"Date: {paid}")
    y -= 18

    c.setFont("Helvetica-Bold", 10)
    c.drawString(M, y, "Received from")
    y -= 14
    c.setFont("Helvetica", 10)
    c.drawString(M + 8, y, cust.upper() if cust else "—")
    y -= 13
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    for bit in (
        _txt(profile.get("address")),
        " · ".join(x for x in (_txt(profile.get("phone")), _txt(profile.get("email"))) if x),
        f"GSTIN: {_txt(profile.get('gstNo'))}" if _txt(profile.get("gstNo")) else "",
    ):
        if bit:
            c.drawString(M + 8, y, bit[:100])
            y -= 11
    c.setFillColorRGB(0, 0, 0)
    y -= 6

    linked = advance.get("linkedQuote") if isinstance(advance.get("linkedQuote"), Mapping) else {}
    project = _txt(advance.get("projectName") or linked.get("name") or advance.get("projectId") or "")
    quote_ref = _txt(
        advance.get("quoteId")
        or linked.get("quotationId")
        or advance.get("quotationId")
        or ""
    )
    c.setFont("Helvetica", 10)
    if project:
        c.drawString(M, y, f"Project: {project}")
        y -= 14
    if quote_ref:
        c.drawString(M, y, f"Quote Ref: {quote_ref}")
        y -= 14

    # Amount box (+ QR on the right so the customer can scan their account)
    y -= 8
    qr_size = 64.0
    qr_gap = 16.0
    has_qr = bool(
        _txt(advance.get("shareToken") or advance.get("quoteShareToken") or advance.get("quoteRef"))
    )
    box_w = W - 2 * M - ((qr_size + qr_gap) if has_qr else 0)
    c.setStrokeColorRGB(*primary)
    c.setFillColorRGB(0.96, 0.97, 0.99)
    c.roundRect(M, y - 70, box_w, 78, 6, stroke=1, fill=1)
    if has_qr:
        try:
            from WEOS.factory.pdf_qr import draw_quote_qr

            draw_quote_qr(
                c,
                advance,
                x=W - M - qr_size,
                y=y - 64,
                size=qr_size,
                label="Scan your account",
            )
        except Exception:
            pass
    c.setFillColorRGB(*primary)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(M + 14, y - 18, "Advance amount")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(M + 14, y - 42, _inr(advance.get("amount")))
    mode = (_txt(advance.get("paymentMode")) or "cash").upper()
    ref = _txt(advance.get("reference") or advance.get("note"))
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.drawString(M + 14, y - 60, f"Payment mode: {mode}" + (f"   Ref: {ref}" if ref else ""))
    y -= 96

    # Running balance — scoped to this project / quote when recorded that way
    bal = totals.get("balance")
    adv_tot = totals.get("advances")
    billed = totals.get("value", totals.get("billed"))
    scope = ledger.get("scope") if isinstance(ledger.get("scope"), Mapping) else {}
    scoped = bool(scope.get("projectId") or scope.get("quoteId"))
    c.setFont("Helvetica-Bold", 10)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(M, y, "Account summary (this project / quote)" if scoped else "Account summary (after this advance)")
    y -= 14
    c.setFont("Helvetica", 9)
    if billed is not None:
        c.drawString(M + 8, y, f"Total value:  {_inr(billed)}")
        y -= 12
    if adv_tot is not None:
        c.drawString(M + 8, y, f"Total advances:  {_inr(adv_tot)}")
        y -= 12
    if bal is not None:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(M + 8, y, f"Balance outstanding:  {_inr(bal)}")
        y -= 16
    if _txt(advance.get("shareToken") or advance.get("quoteShareToken")):
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(M, y, "Scan the QR to see project value, advances paid, and balance on your phone.")
        c.setFillColorRGB(0, 0, 0)
        y -= 16

    note = _txt(advance.get("note"))
    if note and note != ref:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(M, y, f"Note: {note[:110]}")
        y -= 14

    # Stamp / signature — keep clear of totals
    imgs = resolve_doc_images(customer=cust)
    company_auth_image = imgs.get("companySignature") or imgs.get("companyStamp")
    customer_recv_image = imgs.get("customerSignature") or imgs.get("customerStamp")
    block_top = min(y - 10, 160)
    draw_stamp_signature_block(
        c,
        x=M,
        y=block_top,
        width=W - 2 * M,
        company_name=co_name,
        customer_name=cust,
        stamp_path=company_auth_image,
        signature_path=customer_recv_image,
        left_label="Authorized Signatory",
        right_label="Received by / Customer",
    )

    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(M, M / 2 + 6, "This is a computer generated document - powered by WEOS - advance receipt")
    c.showPage()
    c.save()
    return buf.getvalue()


def advance_slip_filename(customer: str, advance: Mapping[str, Any]) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (customer or "customer").strip()).strip("_") or "customer"
    sid = _txt(advance.get("slipNo") or advance.get("id") or advance.get("advanceId") or "slip")
    sid = re.sub(r"[^A-Za-z0-9._-]+", "-", sid)
    return f"{slug}_advance_{sid}.pdf"
