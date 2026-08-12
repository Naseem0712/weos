"""Customer ledger PDF / printable letter."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Mapping


def _inr(n: Any) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    neg = v < 0
    v = abs(v)
    s = f"{v:,.2f}"
    # Rs. is WinAnsi-safe; ₹ is missing from Helvetica/WinAnsiEncoding.
    return ("-Rs." if neg else "Rs.") + s


def _txt(v: Any) -> str:
    return str(v or "").strip()


def render_ledger_pdf(ledger: Mapping[str, Any], company: Mapping[str, Any] | None = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from WEOS.factory.media_assets import draw_stamp_signature_block, resolve_doc_images

    company = company or {}
    profile = ledger.get("profile") or {}
    projects = list(ledger.get("projects") or [])
    advances = list(ledger.get("advances") or [])
    totals = ledger.get("totals") or {}
    as_of = _txt(ledger.get("asOf")) or datetime.now(timezone.utc).isoformat()
    try:
        as_of_disp = datetime.fromisoformat(as_of.replace("Z", "+00:00")).strftime("%d %b %Y %H:%M UTC")
    except Exception:
        as_of_disp = as_of

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    M = 40
    primary = (0.12, 0.22, 0.38)
    y = H - M

    def ensure_space(need: float = 60) -> None:
        nonlocal y
        if y < need:
            c.showPage()
            y = H - M

    def line(txt: str, *, size: int = 10, bold: bool = False, dy: float = 14) -> None:
        nonlocal y
        ensure_space(60)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(M, y, txt[:110])
        y -= dy

    # ── Company letterhead (tight logo gap) ───────────────────────────────
    logo_w = logo_h = 0.0
    logo_path = company.get("logoPath")
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
        _txt(company.get("address")),
        " · ".join(
            x
            for x in (
                _txt(company.get("phone")),
                _txt(company.get("email")),
                _txt(company.get("website")),
            )
            if x
        ),
        f"GSTIN: {_txt(company.get('gstNo'))}" if _txt(company.get("gstNo")) else "",
    ):
        if bit:
            c.drawString(text_x, ty, bit[:95])
            ty -= 11
    y = min(y - max(logo_h, 48) - 10, ty - 4)
    c.setStrokeColorRGB(*primary)
    c.setLineWidth(1)
    c.line(M, y + 6, W - M, y + 6)
    c.setFillColorRGB(0, 0, 0)
    line("CUSTOMER ACCOUNT LEDGER", size=13, bold=True, dy=18)

    cust = _txt(ledger.get("customer") or profile.get("name"))
    line(f"Customer: {cust}", bold=True)
    for bit in (
        _txt(profile.get("address")),
        " · ".join(
            x
            for x in (
                _txt(profile.get("phone")),
                _txt(profile.get("email")),
                _txt(profile.get("contactPerson")),
            )
            if x
        ),
        f"GSTIN: {_txt(profile.get('gstNo'))}" if _txt(profile.get("gstNo")) else "",
        f"Site: {_txt(profile.get('site'))}" if _txt(profile.get("site")) else "",
    ):
        if bit:
            line(bit, size=9, dy=12)

    y -= 4
    line("Running quotes / projects", bold=True, dy=16)
    if not projects:
        line("  (none)", size=9)
    else:
        for p in projects:
            amt = p.get("grandTotal")
            amt_s = _inr(amt) if amt is not None else "—"
            qid = _txt(p.get("quotationId")) or "—"
            ver = p.get("version")
            ver_s = f"v{ver}" if ver is not None else ""
            line(
                f"  {_txt(p.get('projectId'))}  {_txt(p.get('name')) or '—'}  "
                f"Quote {qid} {ver_s}  [{_txt(p.get('status'))}]  {amt_s}",
                size=9,
                dy=12,
            )
            for hv in (p.get("versions") or [])[:8]:
                hv_amt = hv.get("grandTotal")
                line(
                    f"      history v{hv.get('version')}  "
                    f"{_inr(hv_amt) if hv_amt is not None else '—'}",
                    size=8,
                    dy=10,
                )

    y -= 4
    line("Advance breakdown", bold=True, dy=16)
    if not advances:
        line("  (none)", size=9)
    else:
        for a in advances:
            paid = _txt(a.get("paidAt"))[:10] or "—"
            mode = (_txt(a.get("paymentMode")) or "cash").upper()
            ref = _txt(a.get("reference"))
            note = _txt(a.get("note"))
            linked = a.get("linkedQuote") or {}
            qid = _txt(a.get("quoteId") or linked.get("quotationId") or a.get("projectId"))
            ver = a.get("quoteVersion")
            if ver is None:
                ver = linked.get("version")
            ver_s = f"v{ver}" if ver is not None else ""
            link_s = " · ".join(x for x in (f"Quote {qid}" if qid else "", ver_s, ref, note) if x)
            line(
                f"  {paid}  {_inr(a.get('amount'))}  via {mode}"
                + (f"  ({link_s})" if link_s else ""),
                size=9,
                dy=12,
            )

    y -= 8
    ensure_space(160)
    c.line(M, y + 10, W - M, y + 10)
    total_taxable = totals.get("totalTaxable", totals.get("value", totals.get("billed")))
    total_gst = totals.get("totalGst")
    total_grand = totals.get("totalGrand")
    line(f"Total taxable (without GST):  {_inr(total_taxable)}", bold=True)
    if total_gst is not None:
        line(f"Total GST:  {_inr(total_gst)}", bold=True)
    if total_grand is not None:
        line(f"Total with GST:  {_inr(total_grand)}", bold=True)
    line(f"Total advance:  {_inr(totals.get('advances') or totals.get('totalAdvances'))}", bold=True)
    line(f"Total balance (taxable − advances):  {_inr(totals.get('balance'))}", size=12, bold=True, dy=14)
    if totals.get("balanceWithGst") is not None:
        line(f"Balance with GST:  {_inr(totals.get('balanceWithGst'))}", bold=True, dy=14)
    line(f"As of: {as_of_disp} (up to date)", size=9)
    note = _txt((totals or {}).get("note"))
    if note:
        # Wrap long note across lines
        words = note.split()
        chunk = ""
        for w in words:
            trial = (chunk + " " + w).strip()
            if len(trial) > 100 and chunk:
                line(chunk, size=8, dy=11)
                chunk = w
            else:
                chunk = trial
        if chunk:
            line(chunk, size=8, dy=11)

    ensure_space(120)
    imgs = resolve_doc_images(customer=cust)
    draw_stamp_signature_block(
        c,
        x=M,
        y=min(y - 8, 130),
        width=W - 2 * M,
        company_name=co_name,
        customer_name=cust,
        stamp_path=imgs.get("authImage"),
        signature_path=imgs.get("recvImage"),
    )

    c.showPage()
    c.save()
    return buf.getvalue()


def ledger_filename(customer: str, as_of: str | None = None) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (customer or "customer").strip()).strip("_") or "customer"
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    if as_of:
        try:
            day = datetime.fromisoformat(as_of.replace("Z", "+00:00")).strftime("%Y%m%d")
        except Exception:
            pass
    return f"{slug}_ledger_{day}.pdf"
