"""Single-click A4 PDF of the public scan page (quote + pack + photos)."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Mapping


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


def _fmt_dt(iso: Any) -> str:
    if not iso:
        return "—"
    text = str(iso)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except Exception:
        return text[:16].replace("T", " ")


def render_scan_all_pdf(record: Mapping[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    rec = record or {}
    co = rec.get("company") or {}
    cust = rec.get("customer") or {}
    val = rec.get("value") or {}
    pack = rec.get("pack") or {}
    products = list(rec.get("products") or [])
    advances = list(rec.get("advances") or [])
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

    def heading(text: str) -> None:
        nonlocal y
        ensure(28)
        c.setFillColorRGB(*green)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(M, y, text)
        y -= 16
        c.setFillColorRGB(*ink)

    # Header
    c.setFillColorRGB(*green)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(M, y, (_txt(co.get("name") or "WEOS")).upper()[:70])
    y -= 14
    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 8)
    bits = [
        f"GSTIN {_txt(co.get('gstNo'))}" if _txt(co.get("gstNo")) else "",
        _txt(co.get("phone")),
        _txt(co.get("email")),
    ]
    line1 = " · ".join(x for x in bits if x)
    if line1:
        c.drawString(M, y, line1[:110])
        y -= 11
    if _txt(co.get("address")):
        c.drawString(M, y, _txt(co.get("address"))[:110])
        y -= 12
    y -= 4
    c.setStrokeColorRGB(*green)
    c.setLineWidth(1.2)
    c.line(M, y, W - M, y)
    y -= 18

    status = _txt(rec.get("status") or "draft")
    badge = "Approved" if rec.get("approved") else status.replace("_", " ").title()
    c.setFillColorRGB(*ink)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(M, y, f"Quote {_txt(rec.get('quoteNumber') or '—')}")
    c.setFillColorRGB(*green)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(W - M, y, badge)
    y -= 14
    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 8)
    c.drawString(
        M,
        y,
        f"Customer: {_txt(cust.get('name') or '—')}"
        + (f" · {_txt(cust.get('phone'))}" if cust.get("phone") else ""),
    )
    y -= 18

    heading("Summary")
    kpis = [
        ("Taxable", _inr(val.get("totalTaxable"))),
        (f"GST {val.get('gstPercent') or 18}%", _inr(val.get("totalGst"))),
        ("Grand (w/ GST)", _inr(val.get("totalGrand"))),
        ("Advance", _inr(rec.get("totalAdvance"))),
        ("Balance (taxable)", _inr(rec.get("balance"))),
        ("Balance (w/ GST)", _inr(rec.get("balanceWithGst"))),
    ]
    col_w = (W - 2 * M) / 3.0
    row_h = 36
    for i, (lab, amt) in enumerate(kpis):
        if i and i % 3 == 0:
            y -= row_h + 8
        ensure(row_h + 12)
        cx = M + (i % 3) * col_w
        c.setFillColorRGB(0.95, 0.96, 0.94)
        c.roundRect(cx, y - row_h + 10, col_w - 8, row_h, 6, fill=1, stroke=0)
        c.setFillColorRGB(*muted)
        c.setFont("Helvetica", 7)
        c.drawString(cx + 8, y - 2, lab.upper())
        c.setFillColorRGB(*ink)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(cx + 8, y - 18, amt)
    y -= row_h + 16

    heading("Advances")
    if not advances:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*muted)
        c.drawString(M, y, "No advances recorded yet")
        y -= 14
    else:
        c.setFillColorRGB(*muted)
        c.setFont("Helvetica", 7)
        c.drawString(M, y, "#")
        c.drawString(M + 24, y, "AMOUNT")
        c.drawString(M + 110, y, "MODE")
        c.drawString(M + 180, y, "DATE")
        c.drawRightString(W - M, y, "RUNNING")
        y -= 12
        c.setFillColorRGB(*ink)
        c.setFont("Helvetica", 8)
        for a in advances:
            ensure(16)
            c.drawString(M, y, str(a.get("n") or ""))
            c.drawString(M + 24, y, _inr(a.get("amount")))
            c.drawString(M + 110, y, _txt(a.get("paymentMode") or "—")[:12])
            c.drawString(M + 180, y, _fmt_dt(a.get("date")))
            c.drawRightString(W - M, y, _inr(a.get("runningTotal")))
            y -= 12

    y -= 6
    heading("Products")
    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 7)
    c.drawString(M, y, "S.NO")
    c.drawString(M + 36, y, "LOCATION")
    c.drawString(M + 130, y, "TYPE")
    c.drawString(M + 250, y, "SIZE")
    c.drawString(M + 340, y, "QTY")
    c.drawRightString(W - M, y, "AMOUNT")
    y -= 12
    c.setFillColorRGB(*ink)
    if not products:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*muted)
        c.drawString(M, y, "No products on this quote")
        y -= 14
    else:
        c.setFont("Helvetica", 8)
        for p in products:
            ensure(18)
            c.setFillColorRGB(*ink)
            c.drawString(M, y, _txt(p.get("serial") or "—")[:8])
            loc = _txt(p.get("location") or p.get("locationName") or "—")
            c.drawString(M + 36, y, loc[:20])
            c.drawString(M + 130, y, _txt(p.get("type") or "—")[:22])
            c.drawString(M + 250, y, _txt(p.get("size") or "—")[:16])
            c.drawString(M + 340, y, str(p.get("qty") or "1"))
            amt = p.get("amount")
            c.drawRightString(W - M, y, _inr(amt) if amt is not None else "—")
            y -= 12

    if rec.get("approved") and pack.get("available"):
        updates = list(pack.get("updates") or [])
        docs = list(pack.get("documents") or [])
        photos = list(pack.get("photos") or [])
        y -= 4
        heading("Process updates")
        if not updates:
            c.setFont("Helvetica", 8)
            c.setFillColorRGB(*muted)
            c.drawString(M, y, "No process updates yet")
            y -= 14
        else:
            c.setFont("Helvetica", 8)
            for u in updates:
                ensure(28)
                c.setFillColorRGB(*green)
                c.setFont("Helvetica-Bold", 8)
                c.drawString(M, y, _fmt_dt(u.get("date") or u.get("createdAt")))
                c.setFillColorRGB(*ink)
                c.setFont("Helvetica", 8)
                text = _txt(u.get("text") or u.get("note"))
                y -= 12
                # wrap
                words = text.split()
                chunk = ""
                for w in words:
                    trial = (chunk + " " + w).strip()
                    if len(trial) > 95 and chunk:
                        c.drawString(M, y, chunk)
                        y -= 11
                        chunk = w
                    else:
                        chunk = trial
                if chunk:
                    c.drawString(M, y, chunk)
                    y -= 14

        heading("Bills / warranty / delivery challan")
        if not docs:
            c.setFont("Helvetica", 8)
            c.setFillColorRGB(*muted)
            c.drawString(M, y, "No documents uploaded")
            y -= 14
        else:
            labels = {"bill": "Bill", "warranty": "Warranty card", "challan": "Delivery challan"}
            c.setFont("Helvetica", 8)
            for d in docs:
                ensure(16)
                c.setFillColorRGB(*ink)
                kind = labels.get(str(d.get("kind") or ""), str(d.get("kind") or "File").title())
                note = _txt(d.get("note") or d.get("filename") or "")
                c.drawString(M, y, f"{kind} · {_fmt_dt(d.get('date') or d.get('createdAt'))} · {note[:70]}")
                y -= 12

        if photos:
            heading("Process photos")
            token = _txt(rec.get("shareToken"))
            pid = _txt(rec.get("projectId"))
            for ph in photos:
                ensure(220)
                c.setFillColorRGB(*muted)
                c.setFont("Helvetica", 8)
                cap = _txt(ph.get("note") or ph.get("filename") or "Photo")
                c.drawString(M, y, f"{_fmt_dt(ph.get('date') or ph.get('createdAt'))} · {cap[:80]}")
                y -= 12
                raw = None
                try:
                    from WEOS.factory.project_pack import get_file

                    if pid and ph.get("id"):
                        raw, _ct, _fn, _it = get_file(pid, str(ph["id"]))
                except Exception:
                    raw = None
                if raw:
                    try:
                        img = ImageReader(BytesIO(raw))
                        iw, ih = img.getSize()
                        if iw > 0 and ih > 0:
                            max_w, max_h = W - 2 * M, 180.0
                            scale = min(max_w / float(iw), max_h / float(ih), 1.0)
                            dw, dh = iw * scale, ih * scale
                            ensure(dh + 16)
                            c.drawImage(img, M, y - dh, width=dw, height=dh, mask="auto")
                            y -= dh + 14
                            continue
                    except Exception:
                        pass
                c.setFillColorRGB(*ink)
                c.setFont("Helvetica", 8)
                c.drawString(M, y, "(photo attached — open scan page to view)")
                y -= 14
    elif not rec.get("approved"):
        y -= 4
        heading("Process pack")
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*muted)
        c.drawString(M, y, "Available after approval")
        y -= 14

    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 7)
    c.drawString(M, 22, "Powered by WEOS · live quote pack")
    c.drawRightString(W - M, 22, _fmt_dt(rec.get("updatedAt") or datetime.now(timezone.utc).isoformat()))
    c.showPage()
    c.save()
    return buf.getvalue()
