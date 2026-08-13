"""Dual PDF generation — Customer Quotation + Factory Production Package."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

_log = logging.getLogger("weos.pdf_engine")


def export_pdf_bytes(builder_name: str, payload: Mapping[str, Any]) -> bytes:
    if builder_name == "factory":
        return build_factory_pdf_bytes(payload)
    return build_customer_pdf_bytes(payload)


def export_pdf(payload: Mapping[str, Any], path: str | Path, *, kind: str = "customer") -> Path:
    path = Path(path)
    path.write_bytes(export_pdf_bytes(kind, payload))
    return path


def build_quote_pdf_bytes(payload: Mapping[str, Any]) -> bytes:
    """Back-compat alias → customer quotation."""
    return build_customer_pdf_bytes(payload)


def build_customer_pdf_bytes(payload: Mapping[str, Any]) -> bytes:
    """Customer PDF — prefer Template Designer JSON, fallback to hardcoded layout."""
    try:
        from WEOS.factory.template_pdf import render_template_pdf

        return render_template_pdf(payload, kind="customer")
    except Exception:
        _log.exception("customer template PDF failed; falling back to reportlab layout")
        try:
            return _customer_reportlab(payload)
        except Exception:
            _log.exception("customer reportlab PDF failed; falling back to minimal text PDF")
            return _minimal_text_pdf("WEOS Customer Quotation", payload)


def build_factory_pdf_bytes(payload: Mapping[str, Any]) -> bytes:
    """Factory PDF — a dedicated PRODUCTION package, deliberately distinct from the
    customer quotation: panel schedule, glass sizes, hardware BOM, cut list, weights
    and optimization/nesting — and NO customer pricing/margins.

    The rich reportlab factory renderer is used as the primary path so the output is
    always a proper factory document (never the MAR-QT commercial customer layout).
    Template JSON is a fallback only.
    """
    try:
        return _factory_reportlab(payload)
    except Exception:
        _log.exception("factory reportlab PDF failed; trying template layout")
        try:
            from WEOS.factory.template_pdf import render_template_pdf

            return render_template_pdf(payload, kind="factory")
        except Exception:
            _log.exception("factory template PDF failed; falling back to minimal text PDF")
            return _minimal_text_pdf("WEOS Factory Package", payload)


def _qr_png(data: str, box_size: int = 4) -> bytes | None:
    try:
        import qrcode

        img = qrcode.make(data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _customer_reportlab(payload: Mapping[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from WEOS.factory.pdf_fonts import ensure_rupee_font, money_text, set_font

    ensure_rupee_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    y = H - 40

    set_font(c, 18, bold=True)
    c.drawString(40, y, "WEOS — Quotation")
    y -= 16
    set_font(c, 9)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.drawString(40, y, "Design • Calculate • Manufacture • Quote")
    c.setFillColorRGB(0, 0, 0)
    y -= 22

    set_font(c, 10)
    c.drawString(40, y, f"Project: {payload.get('projectId', '')}   Quotation: {payload.get('quotationId', '')}")
    y -= 14
    c.drawString(40, y, f"Customer: {payload.get('customer') or '—'}   Name: {payload.get('name') or '—'}")
    y -= 22

    set_font(c, 11, bold=True)
    c.drawString(40, y, "Line items")
    y -= 16
    set_font(c, 9)
    for line in payload.get("lines") or []:
        if y < 80:
            c.showPage()
            y = H - 50
            set_font(c, 9)
        desc = f"{line.get('displayName')}  {line.get('width')}×{line.get('height')} mm  ×{line.get('qty')}"
        amt = (line.get("price") or {}).get("total", 0)
        c.drawString(40, y, desc[:70])
        c.drawRightString(W - 40, y, money_text(amt))
        y -= 12
        opts = line.get("options") or {}
        c.setFillColorRGB(0.4, 0.4, 0.4)
        # Print full glass spec (makeup · colour · toughened · brand) when resolved.
        glass_spec = line.get("glassSpec") or {}
        first_glass = (line.get("glass") or [{}])[0] if line.get("glass") else {}
        spec_line = glass_spec.get("specLine") or first_glass.get("spec")
        glass_text = spec_line or opts.get("glass")
        c.drawString(50, y, f"Glass: {glass_text}  Colour: {opts.get('colour')}  Handle: {opts.get('handle')}")
        c.setFillColorRGB(0, 0, 0)
        y -= 14

    y -= 8
    cats = (payload.get("price") or {}).get("categoryTotals") or (payload.get("combined") or {}).get("categoryTotals") or {}
    set_font(c, 10, bold=True)
    for cat, total in cats.items():
        c.drawString(40, y, f"{cat}")
        c.drawRightString(W - 40, y, money_text(total))
        y -= 14

    grand = (payload.get("price") or {}).get("total") or (payload.get("combined") or {}).get("grandTotal")
    y -= 6
    set_font(c, 14, bold=True)
    c.drawString(40, y, "Grand Total")
    c.drawRightString(W - 40, y, money_text(grand))
    y -= 28

    set_font(c, 8)
    c.drawString(40, y, "Warranty: 1 year manufacturing defects (demo terms).")
    y -= 12
    c.drawString(40, y, "Terms: 50% advance, balance before dispatch. Rates excl. site installation unless noted.")
    y -= 12
    c.drawString(40, y, "Generated by WEOS — Window Engineering Operating System.")

    # QR → absolute public URL that fetches this quote from the database.
    from WEOS.factory.pdf_qr import draw_quote_qr

    draw_quote_qr(c, payload, x=W - 104, y=48, size=64, label="Scan to view quote")

    c.showPage()
    c.save()
    return buf.getvalue()


def _factory_reportlab(payload: Mapping[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    y = H - 40
    qid = payload.get("quotationId") or payload.get("projectId") or "WEOS"
    pid = payload.get("projectId", "")

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, "WEOS — Factory Production Package")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Production ID / Quotation: {qid}")
    y -= 14
    c.drawString(40, y, f"Project: {pid}")
    y -= 8

    # QR → absolute public URL that opens the quote from the database when scanned.
    from WEOS.factory.pdf_qr import draw_quote_qr

    draw_quote_qr(c, payload, x=W - 110, y=H - 118, size=70, label="Scan to view quote")

    # Customer/site reference (no pricing) so the shop floor knows the job.
    cust = payload.get("customer") or payload.get("name")
    if cust:
        c.setFont("Helvetica", 9)
        c.drawString(40, y, f"Job: {str(cust)}")
        y -= 6

    # Panel schedule — per-line dimensions, qty, section series and weight.
    y -= 14
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Panel schedule")
    y -= 14
    c.setFont("Helvetica", 8)
    for line in payload.get("lines") or []:
        if y < 60:
            c.showPage()
            y = H - 50
            c.setFont("Helvetica", 8)
        w_ = line.get("width")
        h_ = line.get("height")
        q_ = line.get("qty")
        wt = (line.get("weight") or {}).get("totalKg")
        series = line.get("sectionSeries")
        seg = f"  · series {series}" if series else ""
        wtext = f"  · {wt} kg" if wt else ""
        tc = (line.get("options") or {}).get("trackCount")
        tctext = f"  · {tc} track" if tc else ""
        rail_note = ""
        opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        from WEOS.factory.line_kind import is_railing_cart_line

        if is_railing_cart_line(line):
            rq = opts.get("railingQuote") if isinstance(opts, Mapping) else None
            if not isinstance(rq, Mapping):
                rq = line.get("railing") if isinstance(line.get("railing"), Mapping) else {}
            rail_note = (
                f"  · RAILING {rq.get('shape') or ''} · panels {rq.get('panelCount') or 0}"
                f" · pillars {rq.get('pillarCount') or 0} · {rq.get('mountType') or ''}"
            )
            tctext = ""  # never print window track on railing factory lines
        c.drawString(40, y, f"{line.get('displayName')}  {w_}×{h_} mm  ×{q_}{tctext}{seg}{wtext}{rail_note}")
        y -= 11

    # Railing BOM (factory detail)
    from WEOS.factory.line_kind import is_railing_cart_line as _is_rail

    rail_lines = [ln for ln in (payload.get("lines") or []) if _is_rail(ln)]
    if rail_lines:
        y -= 8
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Railing BOM / hardware")
        y -= 14
        c.setFont("Helvetica", 8)
        for line in rail_lines:
            opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
            rq = (opts or {}).get("railingQuote") if isinstance(opts, Mapping) else None
            if not isinstance(rq, Mapping):
                rq = line.get("railing") if isinstance(line.get("railing"), Mapping) else {}
            bom = (rq or {}).get("bomDetails") or (rq or {}).get("items") or line.get("bom") or []
            for it in bom:
                if y < 60:
                    c.showPage()
                    y = H - 50
                    c.setFont("Helvetica", 8)
                if isinstance(it, Mapping):
                    name = it.get("item") or it.get("label") or it.get("name") or it.get("key")
                    rate_bit = ""
                    if it.get("rate") not in (None, "") or it.get("amount") not in (None, ""):
                        rate_bit = f"  @ {it.get('rate')} = {it.get('amount')}"
                    c.drawString(
                        40, y,
                        f"{line.get('displayName')}: {name}  {it.get('qty')} {it.get('unit')}"
                        f"  size {it.get('sizeMm') or '—'}  color {it.get('color') or '—'}"
                        f"  grade {it.get('grade') or '—'}{rate_bit}"
                    )
                y -= 11

    # Other product BOM (shower / windows) with purchase rates — factory only
    other_bom_lines = [ln for ln in (payload.get("lines") or []) if not _is_rail(ln) and (ln.get("bom") or ln.get("hardware"))]
    if other_bom_lines:
        y -= 8
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Product BOM / purchase")
        y -= 14
        c.setFont("Helvetica", 8)
        for line in other_bom_lines:
            bom = line.get("bom") or []
            if not isinstance(bom, list) or not bom:
                bom = line.get("hardware") or []
            for it in bom:
                if y < 60:
                    c.showPage()
                    y = H - 50
                    c.setFont("Helvetica", 8)
                if not isinstance(it, Mapping):
                    continue
                name = it.get("item") or it.get("label") or it.get("name") or it.get("key")
                rate_bit = ""
                if it.get("rate") not in (None, "") or it.get("amount") not in (None, ""):
                    rate_bit = f"  @ {it.get('rate')} = {it.get('amount')}"
                c.drawString(
                    40, y,
                    f"{line.get('displayName')}: {name}  {it.get('qty')} {it.get('unit') or ''}"
                    f"{rate_bit}",
                )
                y -= 11

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Glass sizes")
    y -= 14
    c.setFont("Helvetica", 8)
    for line in payload.get("lines") or []:
        for g in line.get("glass") or []:
            if y < 60:
                c.showPage()
                y = H - 50
            spec_suffix = f"  [{g.get('spec')}]" if g.get("spec") else ""
            c.drawString(40, y, f"{g.get('qty')} pcs  {g.get('width')}×{g.get('height')}×{g.get('thicknessMm')} mm  ({line.get('displayName')}){spec_suffix}")
            y -= 11

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Hardware (rolled)")
    y -= 14
    c.setFont("Helvetica", 8)
    for h in (payload.get("combined") or {}).get("hardwareRolled") or []:
        if y < 60:
            c.showPage()
            y = H - 50
        c.drawString(40, y, f"{h.get('name')}: {h.get('qty')}")
        y -= 11

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Cut list")
    y -= 14
    c.setFont("Helvetica", 8)
    for line in payload.get("lines") or []:
        for cut in line.get("cutList") or []:
            if y < 60:
                c.showPage()
                y = H - 50
            c.drawString(
                40,
                y,
                f"{cut.get('profile')}: {cut.get('length_mm')} mm × {cut.get('quantity')}  ∠{cut.get('cut_angle')}",
            )
            y -= 11

    opt = payload.get("optimization") or {}
    if opt:
        y -= 10
        if y < 100:
            c.showPage()
            y = H - 50
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Optimization report")
        y -= 14
        c.setFont("Helvetica", 8)
        alu = opt.get("aluminium") or {}
        gl = opt.get("glass") or {}
        c.drawString(40, y, f"Aluminium: {alu.get('newBars')} new bars, waste {alu.get('wastePercent')}%, leftovers used {len(alu.get('leftoversUsed') or [])}")
        y -= 11
        c.drawString(40, y, f"Glass: {gl.get('sheetsNeeded')} sheets, waste {gl.get('wastePercent')}%")
        y -= 14
        c.setFont("Helvetica-Bold", 10)
        c.drawString(40, y, "Purchase list")
        y -= 12
        c.setFont("Helvetica", 8)
        for p in opt.get("purchaseList") or []:
            c.drawString(40, y, f"{p.get('qty')} × {p.get('item')}")
            y -= 11

    wsum = (payload.get("combined") or {}).get("weight") or {}
    if wsum:
        y -= 12
        if y < 80:
            c.showPage()
            y = H - 50
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Weight summary")
        y -= 14
        c.setFont("Helvetica", 8)
        c.drawString(
            40,
            y,
            f"Aluminium {wsum.get('aluminiumKg', 0)} kg  ·  Glass {wsum.get('glassKg', 0)} kg  ·  "
            f"Hardware {wsum.get('hardwareKg', 0)} kg  ·  Total {wsum.get('totalKg', 0)} kg",
        )
        y -= 11

    y -= 16
    c.setFont("Helvetica", 8)
    c.drawString(40, y, "No marketing content — machine-ready factory data only. Pricing on customer quotation.")
    c.showPage()
    c.save()
    return buf.getvalue()


def _minimal_text_pdf(title: str, payload: Mapping[str, Any]) -> bytes:
    price = payload.get("price") or {}
    text = f"{title}\\nProject: {payload.get('projectId')}\\nQuote: {payload.get('quotationId')}\\nTotal: {price.get('total', 0)}"
    content = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET"
    objects = [
        "1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        "2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        "3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n",
        f"4 0 obj<< /Length {len(content)} >>stream\n{content}\nendstream\nendobj\n",
        "5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj.encode("latin-1"))
    xref = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.extend(f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1"))
    return bytes(out)
