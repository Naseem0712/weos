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
    from WEOS.factory.pdf_fonts import money_text

    return money_text(v)


def _set_font(c, size: float, *, bold: bool = False) -> None:
    from WEOS.factory.pdf_fonts import set_font

    set_font(c, size, bold=bold)


def _area_sqft(w: float, h: float) -> float:
    return round((w * h) / 1_000_000.0 * 10.7639, 2)


def draw_window_elevation(c, x, y, box_w, box_h, width_mm: float, height_mm: float, *, track_count: int = 2):
    """Fallback schematic only — prefer draw_line_elevation (canvas geometry SVG)."""
    # Outer frame — outline drafting style
    c.setStrokeColorRGB(0.12, 0.12, 0.14)
    c.setLineWidth(0.9)
    c.rect(x, y, box_w, box_h, fill=0, stroke=1)
    c.setLineWidth(0.55)
    c.rect(x + 3, y + 3, box_w - 6, box_h - 6, fill=0, stroke=1)

    # Inner glass panes
    pad = 6
    panes = max(int(track_count or 2), 1)
    pane_w = (box_w - pad * (panes + 1)) / panes
    for i in range(panes):
        px = x + pad + i * (pane_w + pad)
        c.setFillColorRGB(0.78, 0.88, 0.95)
        c.setStrokeColorRGB(0.30, 0.48, 0.65)
        c.setLineWidth(0.55)
        c.rect(px, y + pad, pane_w, box_h - 2 * pad, fill=1, stroke=1)

    c.setStrokeColorRGB(0.55, 0.15, 0.12)
    c.setFillColorRGB(0.55, 0.15, 0.12)
    c.setLineWidth(0.55)
    dim_y = y - 12
    c.line(x, dim_y, x + box_w, dim_y)
    c.line(x, dim_y - 3, x, dim_y + 3)
    c.line(x + box_w, dim_y - 3, x + box_w, dim_y + 3)
    c.setFont("Helvetica", 6)
    c.drawCentredString(x + box_w / 2, dim_y - 10, f"W = {width_mm:g} mm")

    dim_x = x + box_w + 10
    c.line(dim_x, y, dim_x, y + box_h)
    c.line(dim_x - 3, y, dim_x + 3, y)
    c.line(dim_x - 3, y + box_h, dim_x + 3, y + box_h)
    c.saveState()
    c.translate(dim_x + 8, y + box_h / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, f"H = {height_mm:g} mm")
    c.restoreState()


def draw_line_elevation(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    """Draw the same geometry-engine elevation used by the live canvas into the design column.

    Prefers crisp ReportLab vector drawing; falls back to SVG→PNG, then schematic stub.
    Returns True when the real elevation was drawn.
    """
    from reportlab.lib.utils import ImageReader

    from WEOS.factory.elevation_pdf import draw_line_model_elevation
    from WEOS.factory.image_engine import svg_to_png_bytes
    from WEOS.factory.svg_export import elevation_svg_for_line

    w = float(line.get("width") or 0)
    h = float(line.get("height") or 0)

    if draw_line_model_elevation(c, line, x, y, box_w, box_h):
        return True

    svg = elevation_svg_for_line(line, style="pdf")
    if not svg:
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")
    if svg:
        png = svg_to_png_bytes(str(svg), scale=1.0)
        if png:
            img = ImageReader(io.BytesIO(png))
            iw, ih = img.getSize()
            if iw > 0 and ih > 0:
                scale = min(box_w / float(iw), box_h / float(ih))
                dw, dh = iw * scale, ih * scale
                c.drawImage(img, x, y + (box_h - dh), width=dw, height=dh, mask="auto")
                return True

    layout = line.get("layout") if isinstance(line.get("layout"), Mapping) else {}
    panels = list((layout or {}).get("panels") or [])
    track_count = max(len(panels), 2)
    draw_window_elevation(c, x, y, box_w, box_h, w, h, track_count=track_count)
    return False


def _spec_lines(line: Mapping[str, Any]) -> list[str]:
    opts = line.get("options") or {}
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
    layout = line.get("layout") if isinstance(line.get("layout"), Mapping) else {}
    panels = list((layout or {}).get("panels") or [])
    if panels:
        panel_bits = []
        for p in panels:
            pid = p.get("id") or "?"
            role = str(p.get("label") or p.get("role") or "").title()
            pw = p.get("widthMm")
            ph = p.get("heightMm")
            if pw is not None and ph is not None:
                panel_bits.append(f"{pid} {role} {pw:g}×{ph:g}")
        if panel_bits:
            lines.append("Panels: " + "; ".join(panel_bits))
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
    # Prefer resolved track from layout (mesh may have shifted 2→3)
    tc = layout.get("trackCount") if layout else None
    if tc and section.get("track"):
        lines.append(f"Track / Outer = {section['track']} (using {float(tc):g}-track)")
    elif section.get("track"):
        lines.append(f"Track / Outer = {section['track']}")
    elif tc:
        lines.append(f"Track = {float(tc):g}-track")
    if section.get("sash"):
        lines.append(f"Sash = {section['sash']}")
    if section.get("interlock"):
        lines.append(f"Interlock = {section['interlock']}")
    handle = opts.get("handle")
    if handle:
        lines.append(f"Handle = {str(handle).replace('_', ' ').title()}")
    # Sell rate prints in the RATE column only — never duplicate here
    if layout.get("mesh") or (opts or {}).get("mesh"):
        lines.append(f"Mesh = Yes (track {float(tc or 3):g})")
    return lines


def render_marqt_pdf(template: Mapping[str, Any], payload: Mapping[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from WEOS.factory.pdf_fonts import ensure_rupee_font, money_text, rupee_prefix, set_font

    ensure_rupee_font()  # register before any drawString with ₹

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
    website = branding.get("website") or ""
    gst = branding.get("gstNo") or ""
    logo_path = branding.get("logoPath")
    qid = payload.get("quotationId") or payload.get("projectId") or "WEOS-QT"
    qdate = payload.get("quoteDate") or payload.get("createdOn") or date.today().strftime("%d-%m-%Y")
    updated_on = payload.get("updatedOn")
    customer = payload.get("customer") or "—"
    cust_profile = payload.get("customerProfile") or {}
    project_name = payload.get("name") or ""
    lines = list(payload.get("lines") or [])
    _rs = rupee_prefix()

    def _draw_logo(cx: float, top_y: float, max_w: float, max_h: float) -> float:
        """Draw company logo if configured. Returns drawn height (0 if none)."""
        if not logo_path:
            return 0.0
        try:
            from reportlab.lib.utils import ImageReader

            lp = str(logo_path)
            if lp.lower().endswith(".svg"):
                from WEOS.factory.image_engine import svg_to_png_bytes

                png = svg_to_png_bytes(open(lp, "r", encoding="utf-8").read(), scale=1.0)
                if not png:
                    return 0.0
                img = ImageReader(io.BytesIO(png))
            else:
                img = ImageReader(lp)
            iw, ih = img.getSize()
            if iw <= 0 or ih <= 0:
                return 0.0
            scale = min(max_w / float(iw), max_h / float(ih))
            dw, dh = iw * scale, ih * scale
            c.drawImage(img, cx, top_y - dh, width=dw, height=dh, mask="auto")
            return dh
        except Exception:
            return 0.0

    # —— Cover letter page ——
    logo_h = _draw_logo(40, H - 34, 150, 46)
    text_x = 40 + (170 if logo_h else 0)
    c.setFillColorRGB(*primary)
    set_font(c, 16, bold=True)
    c.drawString(text_x, H - 50, company)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    set_font(c, 9)
    c.drawString(text_x, H - 66, branding.get("tagline") or "Windows and Doors Quotation")
    header_extra = H - 80
    if address:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(text_x, header_extra, address[:110])
        header_extra -= 11
    contact_bits = " · ".join(x for x in (phone, email, website) if x)
    if contact_bits:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(text_x, header_extra, contact_bits[:110])
        header_extra -= 11
    if gst:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(text_x, header_extra, f"GSTIN: {gst}")
        header_extra -= 11
    y = min(H - 118, header_extra - 8)
    c.setFillColorRGB(0, 0, 0)
    set_font(c, 10, bold=True)
    c.drawString(40, y, "To:")
    set_font(c, 10)
    c.drawString(60, y, str(customer).upper() if customer else "—")
    y -= 14
    set_font(c, 8)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    if cust_profile.get("address"):
        c.drawString(60, y, str(cust_profile["address"])[:110])
        y -= 11
    cust_contact = " · ".join(
        x for x in (cust_profile.get("contactPerson"), cust_profile.get("phone"), cust_profile.get("email")) if x
    )
    if cust_contact:
        c.drawString(60, y, cust_contact[:110])
        y -= 11
    if cust_profile.get("gstNo"):
        c.drawString(60, y, f"GSTIN: {cust_profile['gstNo']}")
        y -= 11
    c.setFillColorRGB(0, 0, 0)
    y -= 4
    set_font(c, 10)
    if project_name:
        c.drawString(40, y, f"Project: {project_name}")
        y -= 16
    c.drawString(40, y, f"Quote No: {qid}    Date: {qdate}")
    y -= 16
    if updated_on:
        c.setFillColorRGB(*accent)
        set_font(c, 9, bold=True)
        c.drawString(40, y, f"Updated on: {updated_on}")
        c.setFillColorRGB(0, 0, 0)
        set_font(c, 10)
        y -= 16
    y -= 12
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
    set_font(c, 10)
    for para in cover.split("\n"):
        # wrap
        words = para.split()
        line = ""
        for word in words:
            trial = (line + " " + word).strip()
            if c.stringWidth(trial, c._fontname, 10) > 515:
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
    set_font(c, 9)
    c.drawString(40, y, "Enclosures:")
    y -= 14
    c.drawString(50, y, "a) Design / Specifications / Value")
    y -= 12
    c.drawString(50, y, "b) Terms & Conditions")
    y -= 30
    if phone or email or address:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        if address:
            c.drawString(40, y, address)
            y -= 12
        contact = " · ".join(x for x in (phone, email) if x)
        if contact:
            c.drawString(40, y, contact)
    set_font(c, 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(W / 2, 28, f"powered by WEOS — page 1")
    c.showPage()

    # —— Line items pages ——
    def header(page_no: int):
        c.setFillColorRGB(*primary)
        set_font(c, 12, bold=True)
        c.drawString(36, H - 36, company)
        set_font(c, 8)
        c.setFillColorRGB(0.25, 0.25, 0.25)
        c.drawRightString(W - 36, H - 32, f"Quote No. {qid}")
        c.drawRightString(W - 36, H - 44, f"Quote Date {qdate}")
        if updated_on:
            c.setFillColorRGB(*accent)
            c.drawRightString(W - 36, H - 55, f"Updated {updated_on}")
            c.setFillColorRGB(0.25, 0.25, 0.25)
        c.setStrokeColorRGB(*primary)
        c.setLineWidth(1)
        c.line(36, H - 52, W - 36, H - 52)
        # column headers
        yy = H - 68
        c.setFillColorRGB(*primary)
        set_font(c, 8, bold=True)
        c.drawString(40, yy, "DESIGN")
        c.drawString(185, yy, "SPECIFICATIONS")
        c.drawRightString(430, yy, "QTY")
        c.drawRightString(490, yy, f"RATE ({_rs})")
        c.drawRightString(W - 40, yy, f"AMOUNT ({_rs})")
        c.setStrokeColorRGB(0.75, 0.75, 0.75)
        c.line(36, yy - 6, W - 36, yy - 6)
        return yy - 18

    y = header(2)
    page_no = 2
    total_area = 0.0
    total_qty = 0
    grand = 0.0

    for idx, line in enumerate(lines):
        # Design column needs room for annotated elevation + plan
        draw_w, draw_h = 138, 175
        need = max(draw_h + 28, 150)
        if y < 80 + need:
            set_font(c, 7)
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
        # Design column — same geometry SVG as live canvas (not schematic stub)
        c.setFillColorRGB(*accent)
        set_font(c, 9, bold=True)
        c.drawString(42, y + 4, code)
        draw_line_elevation(c, line, 38, y - draw_h, draw_w, draw_h)

        # Specs (no sell-rate line — rate is in RATE column only)
        specs = _spec_lines(line)
        c.setFillColorRGB(0, 0, 0)
        set_font(c, 7)
        sy = y
        for s in specs[:14]:
            c.drawString(180, sy, s[:66])
            sy -= 9

        # Qty / Rate / Amount — currency symbol via Unicode font
        set_font(c, 8)
        c.drawRightString(430, y, str(qty))
        rate_str = f"{float(rate):,.2f}" if rate is not None else "—"
        c.drawRightString(490, y, rate_str)
        set_font(c, 8, bold=True)
        c.drawRightString(W - 40, y, f"{float(amount):,.2f}")

        # row separator
        row_bottom = min(sy, y - draw_h - 10)
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.5)
        c.line(36, row_bottom, W - 36, row_bottom)
        y = row_bottom - 14

    # Totals block
    if y < 140:
        set_font(c, 7)
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
    set_font(c, 9, bold=True)
    c.drawString(40, y, "TOTALS")
    y -= 14
    c.setFillColorRGB(0, 0, 0)
    set_font(c, 8)
    c.drawString(40, y, f"Total Area: {round(total_area, 3)} Sq.Ft.    Windows: {total_qty} Nos")
    y -= 12
    c.drawString(40, y, f"Basic / Project Value: {money_text(basic_ex)}")
    y -= 12
    c.drawString(40, y, f"GST @ {gst_pct:g}%: {money_text(gst_amt)}")
    y -= 16
    set_font(c, 12, bold=True)
    c.setFillColorRGB(*accent)
    c.drawString(40, y, "Grand Total")
    c.drawRightString(W - 40, y, money_text(project))
    c.setFillColorRGB(0, 0, 0)

    set_font(c, 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(W / 2, 28, f"powered by WEOS — page {page_no}")
    c.showPage()
    page_no += 1

    # —— Terms page ——
    c.setFillColorRGB(*primary)
    set_font(c, 14, bold=True)
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
    set_font(c, 9)
    for para in terms_text.split("\n"):
        words = para.split()
        line = ""
        for word in words:
            trial = (line + " " + word).strip()
            if c.stringWidth(trial, c._fontname, 9) > 515:
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
    set_font(c, 9)
    c.drawString(40, y, "For " + company)
    y -= 50
    c.drawString(40, y, "Authorized Signatory")
    c.drawRightString(W - 40, y, "Customer Acceptance")

    set_font(c, 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(W / 2, 28, f"powered by WEOS — page {page_no}")
    c.showPage()
    c.save()
    return buf.getvalue()
