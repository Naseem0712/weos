"""Render Customer / Factory PDFs from Template Designer JSON layouts."""

from __future__ import annotations

import io
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from WEOS.factory.template_store import load_template, resolve_template_id


def render_template_pdf(
    payload: Mapping[str, Any],
    *,
    kind: str = "customer",
    brand: str | None = None,
    template_id: str | None = None,
) -> bytes:
    tid = resolve_template_id(
        kind=kind,
        brand=brand or payload.get("brand"),
        template_id=template_id or payload.get("templateId"),
        product_pdf_layout=payload.get("pdfLayout"),
    )
    try:
        template = load_template(tid)
    except FileNotFoundError:
        template = load_template(f"woodenmax_{kind}")
    return _render_reportlab(template, payload)


def _rgb(color: Sequence[float] | None, fallback=(0, 0, 0)):
    if not color or len(color) < 3:
        return fallback
    return float(color[0]), float(color[1]), float(color[2])


def _qr_png(data: str) -> bytes | None:
    try:
        import qrcode

        img = qrcode.make(data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _render_reportlab(template: Mapping[str, Any], payload: Mapping[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    page = A4
    c = canvas.Canvas(buf, pagesize=page)
    W, H = page
    branding = template.get("branding") or {}
    primary = _rgb(branding.get("primaryColor"), (0.04, 0.35, 0.28))
    accent = _rgb(branding.get("accentColor"), (0.71, 0.33, 0.14))
    company = branding.get("companyName") or branding.get("logoText") or "WEOS"

    # PDF y is from bottom; template y is from top (designer canvas)
    def ty(y: float, h: float = 0) -> float:
        return H - float(y) - float(h)

    for block in template.get("blocks") or []:
        btype = str(block.get("type") or "")
        x = float(block.get("x", 40))
        y_top = float(block.get("y", 40))
        w = float(block.get("w", 200))
        h = float(block.get("h", 24))
        y = ty(y_top, 0)

        if btype == "logo":
            c.setFillColorRGB(*primary)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(x, y - 18, str(block.get("label") or company))
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.setFont("Helvetica", 8)
            c.drawString(x, y - 30, str(branding.get("tagline") or ""))
            c.setFillColorRGB(0, 0, 0)

        elif btype == "title":
            c.setFillColorRGB(*primary)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(x, y - 16, str(block.get("text") or "Document"))
            c.setFillColorRGB(0, 0, 0)

        elif btype == "customer_details":
            c.setFont("Helvetica", 9)
            c.drawString(x, y - 12, f"Project: {payload.get('projectId', '')}")
            c.drawString(x, y - 24, f"Quotation: {payload.get('quotationId', '')}")
            c.drawString(x, y - 36, f"Customer: {payload.get('customer') or '—'}")
            c.drawString(x, y - 48, f"Name: {payload.get('name') or '—'}")

        elif btype == "product_image":
            c.setStrokeColorRGB(*accent)
            c.setFillColorRGB(0.95, 0.95, 0.93)
            c.rect(x, y - h, w, h, fill=1, stroke=1)
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.setFont("Helvetica", 8)
            c.drawCentredString(x + w / 2, y - h / 2, "Product")
            c.setFillColorRGB(0, 0, 0)

        elif btype == "price_table":
            c.setFont("Helvetica-Bold", 10)
            c.setFillColorRGB(*primary)
            c.drawString(x, y - 12, "Line items")
            c.setFillColorRGB(0, 0, 0)
            yy = y - 28
            c.setFont("Helvetica", 8)
            for line in payload.get("lines") or []:
                if yy < 60:
                    c.showPage()
                    yy = H - 50
                desc = f"{line.get('displayName')}  {line.get('width')}×{line.get('height')} mm  ×{line.get('qty')}"
                amt = (line.get("price") or {}).get("total", 0)
                c.drawString(x, yy, desc[:72])
                c.drawRightString(x + w, yy, f"₹ {amt}")
                yy -= 12
                opts = line.get("options") or {}
                c.setFillColorRGB(0.45, 0.45, 0.45)
                c.drawString(x + 8, yy, f"Glass: {opts.get('glass')}  Colour: {opts.get('colour')}")
                c.setFillColorRGB(0, 0, 0)
                yy -= 14

        elif btype == "totals":
            cats = (payload.get("price") or {}).get("categoryTotals") or (payload.get("combined") or {}).get("categoryTotals") or {}
            yy = y - 12
            c.setFont("Helvetica", 9)
            for cat, total in cats.items():
                c.drawString(x, yy, str(cat))
                c.drawRightString(x + w, yy, f"₹ {total}")
                yy -= 12
            grand = (payload.get("price") or {}).get("total") or (payload.get("combined") or {}).get("grandTotal")
            c.setFont("Helvetica-Bold", 12)
            c.setFillColorRGB(*accent)
            c.drawString(x, yy - 6, "Grand Total")
            c.drawRightString(x + w, yy - 6, f"₹ {grand}")
            c.setFillColorRGB(0, 0, 0)

        elif btype == "terms":
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.3, 0.3, 0.3)
            text = str(block.get("text") or "")
            # simple wrap
            words = text.split()
            line = ""
            yy = y - 10
            for word in words:
                trial = (line + " " + word).strip()
                if c.stringWidth(trial, "Helvetica", 7) > w:
                    c.drawString(x, yy, line)
                    yy -= 10
                    line = word
                else:
                    line = trial
            if line:
                c.drawString(x, yy, line)
            c.setFillColorRGB(0, 0, 0)

        elif btype == "footer":
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.drawString(x, y - 10, str(block.get("text") or f"{company} · WEOS"))
            c.setFillColorRGB(0, 0, 0)

        elif btype == "qr":
            qid = payload.get("quotationId") or payload.get("projectId") or "WEOS"
            pid = payload.get("projectId", "")
            qr_data = f"weos://production/{quote(str(qid), safe='')}?project={quote(str(pid), safe='')}"
            png = _qr_png(qr_data)
            if png:
                img = ImageReader(io.BytesIO(png))
                c.drawImage(img, x, y - h, width=w, height=h, mask="auto")

        elif btype == "glass_table":
            c.setFont("Helvetica-Bold", 10)
            c.setFillColorRGB(*primary)
            c.drawString(x, y - 12, "Glass sizes")
            c.setFillColorRGB(0, 0, 0)
            yy = y - 26
            c.setFont("Helvetica", 8)
            for line in payload.get("lines") or []:
                for g in line.get("glass") or []:
                    c.drawString(x, yy, f"{g.get('qty')} pcs  {g.get('width')}×{g.get('height')}×{g.get('thicknessMm')} mm")
                    yy -= 11
                    if yy < 50:
                        c.showPage()
                        yy = H - 50

        elif btype == "hardware_table":
            c.setFont("Helvetica-Bold", 10)
            c.setFillColorRGB(*primary)
            c.drawString(x, y - 12, "Hardware")
            c.setFillColorRGB(0, 0, 0)
            yy = y - 26
            c.setFont("Helvetica", 8)
            for h_item in (payload.get("combined") or {}).get("hardwareRolled") or []:
                c.drawString(x, yy, f"{h_item.get('name')}: {h_item.get('qty')}")
                yy -= 11

        elif btype == "cutlist_table":
            c.setFont("Helvetica-Bold", 10)
            c.setFillColorRGB(*primary)
            c.drawString(x, y - 12, "Cut list")
            c.setFillColorRGB(0, 0, 0)
            yy = y - 26
            c.setFont("Helvetica", 8)
            for line in payload.get("lines") or []:
                for cut in line.get("cutList") or []:
                    c.drawString(x, yy, f"{cut.get('profile')}: {cut.get('length_mm')} mm × {cut.get('quantity')}")
                    yy -= 11
                    if yy < 50:
                        c.showPage()
                        yy = H - 50

        elif btype == "materials_table":
            c.setFont("Helvetica-Bold", 10)
            c.setFillColorRGB(*primary)
            c.drawString(x, y - 12, "Materials")
            c.setFillColorRGB(0, 0, 0)
            yy = y - 26
            c.setFont("Helvetica", 8)
            for line in payload.get("lines") or []:
                for m in line.get("materials") or []:
                    c.drawString(x, yy, f"{m.get('description')}: {m.get('quantity')} {m.get('unit')}")
                    yy -= 11

    c.showPage()
    c.save()
    return buf.getvalue()
