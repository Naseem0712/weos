"""MAR-QT-style customer quotation PDF — drawings with W/H callouts + detail specs."""

from __future__ import annotations

import io
from datetime import date
from typing import Any, Mapping, Sequence


def _rgb(color: Sequence[float] | None, fallback=(0.12, 0.22, 0.38)):
    if not color or len(color) < 3:
        return fallback
    return float(color[0]), float(color[1]), float(color[2])


def _money(v: Any) -> str:
    try:
        return f"₹ {float(v):,.2f}"
    except (TypeError, ValueError):
        return "₹ —"


def _area_sqft(w: float, h: float) -> float:
    return round((w * h) / 1_000_000.0 * 10.7639, 2)


def draw_window_elevation(c, x, y, box_w, box_h, width_mm: float, height_mm: float, *, track_count: int = 2):
    """Schematic elevation with dimension callouts (MAR-QT style markings)."""
    from reportlab.lib.colors import Color

    # Outer frame
    c.setStrokeColorRGB(0.15, 0.15, 0.18)
    c.setFillColorRGB(0.93, 0.95, 0.97)
    c.setLineWidth(1.4)
    c.rect(x, y, box_w, box_h, fill=1, stroke=1)

    # Inner glass panes
    pad = 6
    panes = max(int(track_count or 2), 1)
    pane_w = (box_w - pad * (panes + 1)) / panes
    for i in range(panes):
        px = x + pad + i * (pane_w + pad)
        c.setFillColorRGB(0.78, 0.88, 0.95)
        c.setStrokeColorRGB(0.35, 0.45, 0.55)
        c.setLineWidth(0.8)
        c.rect(px, y + pad, pane_w, box_h - 2 * pad, fill=1, stroke=1)
        # sash handle hint on first pane
        if i == 0 and pane_w > 18:
            c.setFillColorRGB(0.25, 0.25, 0.28)
            c.circle(px + pane_w - 6, y + box_h / 2, 2, fill=1, stroke=0)

    # Width dimension below
    c.setStrokeColorRGB(0.55, 0.15, 0.12)
    c.setFillColorRGB(0.55, 0.15, 0.12)
    c.setLineWidth(0.7)
    dim_y = y - 12
    c.line(x, dim_y, x + box_w, dim_y)
    c.line(x, dim_y - 3, x, dim_y + 3)
    c.line(x + box_w, dim_y - 3, x + box_w, dim_y + 3)
    c.setFont("Helvetica", 6)
    c.drawCentredString(x + box_w / 2, dim_y - 10, f"W = {width_mm:g} mm")

    # Height dimension to the right
    dim_x = x + box_w + 10
    c.line(dim_x, y, dim_x, y + box_h)
    c.line(dim_x - 3, y, dim_x + 3, y)
    c.line(dim_x - 3, y + box_h, dim_x + 3, y + box_h)
    c.saveState()
    c.translate(dim_x + 8, y + box_h / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, f"H = {height_mm:g} mm")
    c.restoreState()


def _spec_lines(line: Mapping[str, Any]) -> list[str]:
    opts = line.get("options") or {}
    selling = line.get("selling") or {}
    w = float(line.get("width") or 0)
    h = float(line.get("height") or 0)
    weight = (line.get("weight") or {}).get("totalKg")
    section = line.get("sectionSpecs") or {}
    if not section and line.get("sectionSeries"):
        try:
            from WEOS.factory.section_catalogue import specs_summary_for_series

            section = specs_summary_for_series(str(line.get("sectionSeries")))
        except Exception:
            section = {}

    lines = [
        str(line.get("description") or line.get("displayName") or line.get("product") or "Window"),
        f"W = {w:g} mm; H = {h:g} mm",
        f"Area = {_area_sqft(w, h)} Sq.Ft.",
    ]
    if weight is not None:
        lines.append(f"Weight = {weight} kg")
    glass = opts.get("glass") or line.get("glass")
    if isinstance(glass, list) and glass:
        g0 = glass[0]
        lines.append(f"Glazing = {g0.get('thicknessMm', '')} mm")
    elif glass:
        lines.append(f"Glazing = {str(glass).replace('_', ' ')}")
    colour = opts.get("colour") or line.get("colour")
    if colour:
        lines.append(f"Profile Color = {str(colour).replace('_', ' ').title()}")
    if section.get("seriesTitle"):
        lines.append(f"Series = {section['seriesTitle']}")
    if section.get("track"):
        lines.append(f"Track / Outer = {section['track']}")
    if section.get("sash"):
        lines.append(f"Sash = {section['sash']}")
    if section.get("interlock"):
        lines.append(f"Interlock = {section['interlock']}")
    handle = opts.get("handle")
    if handle:
        lines.append(f"Handle = {str(handle).replace('_', ' ').title()}")
    if selling.get("sellingRate") is not None:
        lines.append(
            f"Sell rate = ₹{selling.get('sellingRate')} / {selling.get('saleUnit', 'sqft')}"
        )
    return lines


def render_marqt_pdf(template: Mapping[str, Any], payload: Mapping[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    page = A4
    c = canvas.Canvas(buf, pagesize=page)
    W, H = page
    branding = template.get("branding") or {}
    primary = _rgb(branding.get("primaryColor"), (0.12, 0.22, 0.38))
    accent = _rgb(branding.get("accentColor"), (0.75, 0.15, 0.12))
    company = branding.get("companyName") or branding.get("logoText") or "WEOS"
    phone = branding.get("phone") or ""
    email = branding.get("email") or ""
    address = branding.get("address") or ""
    qid = payload.get("quotationId") or payload.get("projectId") or "WEOS-QT"
    qdate = payload.get("quoteDate") or date.today().strftime("%d-%m-%Y")
    customer = payload.get("customer") or "—"
    project_name = payload.get("name") or ""
    lines = list(payload.get("lines") or [])

    # —— Cover letter page ——
    c.setFillColorRGB(*primary)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, H - 50, company)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.setFont("Helvetica", 9)
    c.drawString(40, H - 66, branding.get("tagline") or "Windows and Doors Quotation")
    y = H - 100
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"To: {customer}")
    y -= 16
    if project_name:
        c.drawString(40, y, f"Project: {project_name}")
        y -= 16
    c.drawString(40, y, f"Quote No: {qid}    Date: {qdate}")
    y -= 28
    cover = ""
    for b in template.get("blocks") or []:
        if b.get("type") == "cover_letter":
            cover = str(b.get("text") or "")
            break
    if not cover:
        cover = (
            "We thank you for your enquiry and are pleased to offer our windows and doors "
            "as per the enclosed design, specifications and value."
        )
    c.setFont("Helvetica", 10)
    for para in cover.split("\n"):
        # wrap
        words = para.split()
        line = ""
        for word in words:
            trial = (line + " " + word).strip()
            if c.stringWidth(trial, "Helvetica", 10) > 515:
                c.drawString(40, y, line)
                y -= 14
                line = word
            else:
                line = trial
        if line:
            c.drawString(40, y, line)
            y -= 14
        y -= 6
    y -= 20
    c.setFont("Helvetica", 9)
    c.drawString(40, y, "Enclosures:")
    y -= 14
    c.drawString(50, y, "a) Design / Specifications / Value")
    y -= 12
    c.drawString(50, y, "b) Terms & Conditions")
    y -= 30
    if phone or email or address:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        if address:
            c.drawString(40, y, address)
            y -= 12
        contact = " · ".join(x for x in (phone, email) if x)
        if contact:
            c.drawString(40, y, contact)
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(W / 2, 28, f"powered by WEOS — page 1")
    c.showPage()

    # —— Line items pages ——
    def header(page_no: int):
        c.setFillColorRGB(*primary)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(36, H - 36, company)
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.25, 0.25, 0.25)
        c.drawRightString(W - 36, H - 32, f"Quote No. {qid}")
        c.drawRightString(W - 36, H - 44, f"Quote Date {qdate}")
        c.setStrokeColorRGB(*primary)
        c.setLineWidth(1)
        c.line(36, H - 52, W - 36, H - 52)
        # column headers
        yy = H - 68
        c.setFillColorRGB(*primary)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(40, yy, "DESIGN")
        c.drawString(160, yy, "SPECIFICATIONS")
        c.drawRightString(430, yy, "QTY")
        c.drawRightString(490, yy, "RATE")
        c.drawRightString(W - 40, yy, "AMOUNT")
        c.setStrokeColorRGB(0.75, 0.75, 0.75)
        c.line(36, yy - 6, W - 36, yy - 6)
        return yy - 18

    y = header(2)
    page_no = 2
    total_area = 0.0
    total_qty = 0
    grand = 0.0

    for idx, line in enumerate(lines):
        need = 118
        if y < 80 + need:
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawCentredString(W / 2, 28, f"powered by WEOS — page {page_no}")
            c.showPage()
            page_no += 1
            y = header(page_no)

        w = float(line.get("width") or 0)
        h = float(line.get("height") or 0)
        qty = int(line.get("qty") or 1)
        area = _area_sqft(w, h) * qty
        total_area += _area_sqft(w, h) * qty
        total_qty += qty

        selling = line.get("selling") or {}
        rate = selling.get("sellingRate")
        amount = selling.get("sellingAmount")
        if amount is None:
            amount = line.get("commercialTotal")
        if amount is None:
            amount = (line.get("price") or {}).get("total") or 0
        if rate is None and selling.get("billableQty"):
            try:
                rate = float(amount) / float(selling["billableQty"])
            except (TypeError, ValueError, ZeroDivisionError):
                rate = None
        if rate is None:
            # derive from cost / area for display
            try:
                rate = float(amount) / max(_area_sqft(w, h) * qty, 0.001)
            except (TypeError, ValueError):
                rate = 0
        grand += float(amount or 0)

        code = f"W{idx + 1}"
        # Design column — elevation
        draw_w, draw_h = 90, 70
        draw_window_elevation(c, 42, y - draw_h, draw_w, draw_h, w, h, track_count=2)
        c.setFillColorRGB(*accent)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(42, y + 4, code)

        # Specs
        specs = _spec_lines(line)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica", 7)
        sy = y
        for s in specs[:12]:
            c.drawString(160, sy, s[:70])
            sy -= 9

        # Qty / Rate / Amount
        c.setFont("Helvetica", 8)
        c.drawRightString(430, y, str(qty))
        c.drawRightString(490, y, f"{float(rate):,.2f}" if rate is not None else "—")
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(W - 40, y, f"{float(amount):,.2f}")

        # row separator
        row_bottom = min(sy, y - draw_h - 18)
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.5)
        c.line(36, row_bottom, W - 36, row_bottom)
        y = row_bottom - 14

    # Totals block
    if y < 140:
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawCentredString(W / 2, 28, f"powered by WEOS — page {page_no}")
        c.showPage()
        page_no += 1
        y = header(page_no)

    gst_pct = 18.0
    price = payload.get("price") or {}
    # Prefer commercial grand; fall back
    basic = float(grand or price.get("total") or (payload.get("combined") or {}).get("grandTotal") or 0)
    # If amounts already include GST from cost engine, show as project total with GST split estimate
    # For selling amounts we treat as basic + GST unless payload says otherwise
    if payload.get("sellingIncludesGst"):
        project = basic
        gst_amt = round(project * gst_pct / (100 + gst_pct), 2)
        basic_ex = round(project - gst_amt, 2)
    else:
        # Assume selling amounts are ex-GST (dealer style) → add GST
        basic_ex = round(basic, 2)
        gst_amt = round(basic_ex * gst_pct / 100.0, 2)
        project = round(basic_ex + gst_amt, 2)

    y -= 8
    c.setFillColorRGB(*primary)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, y, "TOTALS")
    y -= 14
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 8)
    c.drawString(40, y, f"Total Area: {round(total_area, 3)} Sq.Ft.    Windows: {total_qty} Nos")
    y -= 12
    c.drawString(40, y, f"Basic / Project Value: {_money(basic_ex)}")
    y -= 12
    c.drawString(40, y, f"GST @ {gst_pct:g}%: {_money(gst_amt)}")
    y -= 16
    c.setFont("Helvetica-Bold", 12)
    c.setFillColorRGB(*accent)
    c.drawString(40, y, "Grand Total")
    c.drawRightString(W - 40, y, _money(project))
    c.setFillColorRGB(0, 0, 0)

    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(W / 2, 28, f"powered by WEOS — page {page_no}")
    c.showPage()
    page_no += 1

    # —— Terms page ——
    c.setFillColorRGB(*primary)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, H - 50, "Terms & Conditions")
    terms_text = ""
    for b in template.get("blocks") or []:
        if b.get("type") == "terms":
            terms_text = str(b.get("text") or "")
            break
    if not terms_text:
        terms_text = payload.get("terms") or (
            "1. Specs & sizes may differ 7–9 mm after site measurement.\n"
            "2. Pricing Ex-Works unless noted. GST extra as applicable.\n"
            "3. Payment as agreed. Order confirmation required.\n"
            "4. Delivery typically 3+ weeks from confirmation.\n"
            "5. Quotation valid 15 days.\n"
            "6. Warranty: profile manufacturing defects as per policy."
        )
    y = H - 80
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 9)
    for para in terms_text.split("\n"):
        words = para.split()
        line = ""
        for word in words:
            trial = (line + " " + word).strip()
            if c.stringWidth(trial, "Helvetica", 9) > 515:
                c.drawString(40, y, line)
                y -= 13
                line = word
            else:
                line = trial
        if line:
            c.drawString(40, y, line)
            y -= 13
        y -= 4
        if y < 80:
            c.showPage()
            page_no += 1
            y = H - 50

    y -= 30
    c.setFont("Helvetica", 9)
    c.drawString(40, y, "For " + company)
    y -= 50
    c.drawString(40, y, "Authorized Signatory")
    c.drawRightString(W - 40, y, "Customer Acceptance")

    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(W / 2, 28, f"powered by WEOS — page {page_no}")
    c.showPage()
    c.save()
    return buf.getvalue()
