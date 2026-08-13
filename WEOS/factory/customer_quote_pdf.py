"""Clean A4 customer quotation sheet — GST company branding + live line totals.

Replaces the old WoodenMax/AllKraft block template (dummy “Product” box, 0.00
amounts, stub ids, coming soon) with the same details as the live scan page.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Mapping

from WEOS.factory.customer_line_view import (
    customer_line_amount,
    public_products_from_doc,
    totals_by_type,
)
from WEOS.factory.ledger_store import quote_money_parts


def _txt(v: Any) -> str:
    return str(v or "").strip()


def _inr(n: Any) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    neg = v < 0
    v = abs(v)
    return ("-Rs." if neg else "Rs.") + f"{v:,.2f}"


def _company_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    co = dict(payload.get("company") or {})
    branding = dict(payload.get("branding") or {})
    gst = _txt(payload.get("companyGst") or co.get("gstNo") or branding.get("gstNo"))
    try:
        from WEOS.factory.company_store import company_branding, load_company, load_company_by_gst

        if gst:
            by = load_company_by_gst(gst) or {}
            if by:
                co = {**co, **{k: v for k, v in by.items() if v}}
        overlay = company_branding(gst=gst or None)
        for k, v in overlay.items():
            if v and not co.get(k):
                co[k] = v
        if not co.get("companyName"):
            active = load_company() or {}
            co.setdefault("companyName", active.get("companyName") or "")
            co.setdefault("gstNo", active.get("gstNo") or gst)
            co.setdefault("address", active.get("address") or "")
            co.setdefault("phone", active.get("phone") or "")
            co.setdefault("email", active.get("email") or "")
    except Exception:
        pass
    if branding.get("companyName") and not co.get("companyName"):
        co["companyName"] = branding["companyName"]
    if gst and not co.get("gstNo"):
        co["gstNo"] = gst
    if branding.get("logoPath") and not co.get("logoPath"):
        co["logoPath"] = branding["logoPath"]
    return co


def render_customer_quote_sheet(
    payload: Mapping[str, Any],
    branding: Mapping[str, Any] | None = None,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    payload = dict(payload or {})
    if branding:
        payload.setdefault("branding", dict(branding))
    co = _company_from_payload(payload)
    cust_name = _txt(payload.get("customer") or (payload.get("customerProfile") or {}).get("name"))
    profile = dict(payload.get("customerProfile") or {})
    products = list(payload.get("scanProducts") or [])
    if not products:
        products = public_products_from_doc(payload)
    type_totals = list(payload.get("typeTotals") or totals_by_type(list(payload.get("lines") or [])))
    if not type_totals and products:
        buckets: dict[str, dict[str, Any]] = {}
        for p in products:
            lab = _txt(p.get("type") or "Other") or "Other"
            row = buckets.setdefault(lab, {"type": lab, "qty": 0, "amount": 0.0})
            try:
                row["qty"] += int(round(float(p.get("qty") or 1)))
            except (TypeError, ValueError):
                row["qty"] += 1
            try:
                row["amount"] = round(row["amount"] + float(p.get("amount") or 0), 2)
            except (TypeError, ValueError):
                pass
        type_totals = list(buckets.values())

    commercial = 0.0
    for p in products:
        try:
            commercial += float(p.get("amount") or 0)
        except (TypeError, ValueError):
            pass
    if commercial <= 0:
        for ln in payload.get("lines") or []:
            if isinstance(ln, dict):
                commercial += float(customer_line_amount(ln) or 0)
    if commercial <= 0:
        commercial = float((payload.get("price") or {}).get("total") or (payload.get("combined") or {}).get("grandTotal") or 0)
    money = quote_money_parts(commercial)

    green = (0.039, 0.353, 0.282)
    ink = (0.08, 0.08, 0.06)
    muted = (0.36, 0.35, 0.31)
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    M = 36
    y = H - M

    def ensure(need: float = 70) -> None:
        nonlocal y
        if y < need:
            c.showPage()
            y = H - M

    def card(h: float) -> None:
        nonlocal y
        ensure(h + 16)
        c.setFillColorRGB(0.998, 0.992, 0.976)
        c.setStrokeColorRGB(0.82, 0.80, 0.74)
        c.setLineWidth(0.7)
        c.roundRect(M, y - h, W - 2 * M, h, 8, fill=1, stroke=1)
        c.setFillColorRGB(*ink)

    # Letterhead
    logo_h = 0.0
    logo_w = 0.0
    logo_path = co.get("logoPath")
    if logo_path:
        try:
            from pathlib import Path

            lp = Path(str(logo_path))
            if lp.is_file() and lp.suffix.lower() != ".svg":
                img = ImageReader(str(lp))
                iw, ih = img.getSize()
                if iw > 0 and ih > 0:
                    scale = min(88 / float(iw), 42 / float(ih))
                    logo_w, logo_h = iw * scale, ih * scale
                    c.drawImage(img, M, y - logo_h, width=logo_w, height=logo_h, mask="auto")
        except Exception:
            logo_w = logo_h = 0.0
    tx = M + ((logo_w + 10) if logo_h else 0)
    co_name = (_txt(co.get("companyName") or co.get("name") or "WEOS")).upper()
    c.setFillColorRGB(*green)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(tx, y - 14, co_name[:70])
    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 8)
    ty = y - 28
    for bit in (
        _txt(co.get("address")),
        " · ".join(x for x in (_txt(co.get("phone")), _txt(co.get("email")), _txt(co.get("website"))) if x),
        f"GSTIN: {_txt(co.get('gstNo'))}" if _txt(co.get("gstNo")) else "",
    ):
        if bit:
            c.drawString(tx, ty, bit[:100])
            ty -= 11
    y = min(y - max(logo_h, 46) - 8, ty - 6)

    c.setFillColorRGB(*green)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(M, y, "Customer Quotation")
    y -= 16

    qid = _txt(payload.get("quotationId") or payload.get("quoteNumber") or payload.get("projectId") or "—")
    status = _txt(payload.get("status") or "")
    card_h = 62
    card(card_h)
    inner = y - 14
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*muted)
    c.drawString(M + 10, inner, "Quote")
    c.setFillColorRGB(*ink)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(M + 10, inner - 14, qid[:50])
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*muted)
    c.drawString(M + 10, inner - 28, f"Customer: {cust_name or '—'}")
    extra = " · ".join(
        x
        for x in (
            _txt(profile.get("phone")),
            f"GSTIN {_txt(profile.get('gstNo'))}" if _txt(profile.get("gstNo")) else "",
            _txt(profile.get("address"))[:48],
        )
        if x
    )
    if extra:
        c.drawString(M + 10, inner - 40, extra[:95])
    if status:
        c.setFillColorRGB(*green)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(W - M - 12, inner - 8, status.replace("_", " ").title())
    y -= card_h + 12

    # Products
    c.setFillColorRGB(*ink)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(M, y, "Products")
    y -= 14
    cols = [
        (M, "S.No"),
        (M + 36, "Location"),
        (M + 118, "Type"),
        (M + 230, "Size"),
        (M + 318, "Qty"),
        (M + 348, "Glass / colour"),
        (W - M, "Amount"),
    ]
    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 7)
    for x, lab in cols[:-1]:
        c.drawString(x, y, lab.upper())
    c.drawRightString(cols[-1][0], y, cols[-1][1].upper())
    y -= 4
    c.setStrokeColorRGB(0.82, 0.80, 0.74)
    c.line(M, y, W - M, y)
    y -= 12
    c.setFillColorRGB(*ink)
    if not products:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*muted)
        c.drawString(M, y, "No products on this quote")
        y -= 16
    else:
        for p in products:
            ensure(36)
            c.setFont("Helvetica-Bold", 8)
            c.setFillColorRGB(*ink)
            c.drawString(M, y, str(p.get("serial") or "—")[:8])
            c.setFont("Helvetica", 8)
            loc = _txt(p.get("location") or p.get("locationName"))
            c.drawString(M + 36, y, (loc if loc and loc != "—" else "—")[:18])
            c.drawString(M + 118, y, _txt(p.get("type") or "—")[:22])
            c.drawString(M + 230, y, _txt(p.get("size") or "—")[:16])
            c.drawString(M + 318, y, str(p.get("qty") or "1"))
            glass = _txt(p.get("glass"))
            colour = _txt(p.get("colour"))
            gc = " · ".join(x for x in (glass if glass != "—" else "", colour if colour != "—" else "") if x) or "—"
            c.setFillColorRGB(*muted)
            c.setFont("Helvetica", 7)
            c.drawString(M + 348, y, gc[:28])
            amt = p.get("amount")
            c.setFillColorRGB(*ink)
            c.setFont("Helvetica-Bold", 8)
            c.drawRightString(W - M, y, _inr(amt) if amt is not None else "—")
            y -= 14

    y -= 6
    ensure(90)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColorRGB(*ink)
    c.drawString(M, y, "Totals")
    y -= 14
    c.setFont("Helvetica", 8)
    for row in type_totals:
        c.setFillColorRGB(*ink)
        c.drawString(M, y, f"{row.get('type')} × {row.get('qty')}")
        c.drawRightString(W - M, y, _inr(row.get("amount")))
        y -= 12
    y -= 4
    c.setStrokeColorRGB(*green)
    c.setLineWidth(1)
    c.line(M, y + 6, W - M, y + 6)
    c.setFont("Helvetica", 9)
    c.drawString(M, y - 6, "Taxable")
    c.drawRightString(W - M, y - 6, _inr(money["totalTaxable"]))
    c.drawString(M, y - 20, f"GST {money['gstPercent']:g}%")
    c.drawRightString(W - M, y - 20, _inr(money["totalGst"]))
    c.setFont("Helvetica-Bold", 11)
    c.setFillColorRGB(*green)
    c.drawString(M, y - 38, "Grand total (with GST)")
    c.drawRightString(W - M, y - 38, _inr(money["totalGrand"]))
    y -= 56

    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 7)
    c.drawString(M, max(M - 8, 24), "Powered by WEOS")
    c.drawRightString(W - M, max(M - 8, 24), datetime.now(timezone.utc).strftime("%d %b %Y"))
    c.showPage()
    c.save()
    return buf.getvalue()
