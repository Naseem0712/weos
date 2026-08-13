"""Customer ledger — card-style A4 PDF + public HTML (scan visual language)."""

from __future__ import annotations

import html
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
    return ("-Rs." if neg else "Rs.") + s


def _txt(v: Any) -> str:
    return str(v or "").strip()


TOTALS_NOTE_SHORT = "Taxable is ex-GST; with GST adds 18%. Balance = total − advances."


def render_ledger_pdf(ledger: Mapping[str, Any], company: Mapping[str, Any] | None = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from WEOS.factory.media_assets import resolve_doc_images

    company = company or {}
    profile = ledger.get("profile") or {}
    projects = list(ledger.get("projects") or [])
    advances = list(ledger.get("advances") or [])
    totals = ledger.get("totals") or {}
    as_of = _txt(ledger.get("asOf")) or datetime.now(timezone.utc).isoformat()
    try:
        as_of_disp = datetime.fromisoformat(as_of.replace("Z", "+00:00")).strftime("%d %b %Y")
    except Exception:
        as_of_disp = as_of[:10]

    green = (0.039, 0.353, 0.282)
    ink = (0.08, 0.08, 0.06)
    muted = (0.36, 0.35, 0.31)
    card_bg = (0.998, 0.992, 0.976)
    line_c = (0.82, 0.80, 0.74)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    M = 32
    y = H - M

    def ensure(need: float = 70) -> None:
        nonlocal y
        if y < need:
            c.showPage()
            y = H - M

    def round_card(height: float) -> None:
        nonlocal y
        ensure(height + 12)
        c.setFillColorRGB(*card_bg)
        c.setStrokeColorRGB(*line_c)
        c.setLineWidth(0.8)
        c.roundRect(M, y - height, W - 2 * M, height, 10, fill=1, stroke=1)
        c.setFillColorRGB(*ink)

    # ── Compact letterhead ────────────────────────────────────────────────
    logo_w = logo_h = 0.0
    logo_path = company.get("logoPath")
    if logo_path:
        try:
            from pathlib import Path

            lp = Path(str(logo_path))
            if lp.is_file() and lp.suffix.lower() != ".svg":
                img = ImageReader(str(lp))
                iw, ih = img.getSize()
                if iw > 0 and ih > 0:
                    scale = min(72 / float(iw), 36 / float(ih))
                    logo_w, logo_h = iw * scale, ih * scale
                    c.drawImage(img, M, y - logo_h, width=logo_w, height=logo_h, mask="auto")
        except Exception:
            logo_w = logo_h = 0.0
    text_x = M + ((logo_w + 10) if logo_h else 0)
    co_name = (_txt(company.get("companyName") or company.get("name") or "WEOS")).upper()
    c.setFillColorRGB(*green)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(text_x, y - 14, co_name[:70])
    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 7.5)
    ty = y - 26
    for bit in (
        _txt(company.get("address")),
        " · ".join(
            x
            for x in (_txt(company.get("phone")), _txt(company.get("email")), _txt(company.get("website")))
            if x
        ),
        f"GSTIN {_txt(company.get('gstNo'))}" if _txt(company.get("gstNo")) else "",
    ):
        if bit:
            c.drawString(text_x, ty, bit[:100])
            ty -= 10
    y = min(y - max(logo_h, 40) - 8, ty - 4)

    c.setFillColorRGB(*green)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(M, y, "Customer account ledger")
    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 8)
    c.drawRightString(W - M, y, f"As of {as_of_disp}")
    y -= 14

    # ── Customer card ─────────────────────────────────────────────────────
    cust = _txt(ledger.get("customer") or profile.get("name"))
    cust_bits = [
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
        f"GSTIN {_txt(profile.get('gstNo'))}" if _txt(profile.get("gstNo")) else "",
        f"Site {_txt(profile.get('site'))}" if _txt(profile.get("site")) else "",
    ]
    cust_bits = [b for b in cust_bits if b]
    ch = 36 + 12 * len(cust_bits)
    round_card(ch)
    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 7)
    c.drawString(M + 12, y - 12, "CUSTOMER")
    c.setFillColorRGB(*ink)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(M + 12, y - 26, cust[:70] or "—")
    cy = y - 40
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*muted)
    for bit in cust_bits:
        c.drawString(M + 12, cy, bit[:100])
        cy -= 12
    y -= ch + 10

    # ── Running quotes as a list ──────────────────────────────────────────
    c.setFillColorRGB(*ink)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(M, y, "Running quotes / projects")
    y -= 12
    if not projects:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*muted)
        c.drawString(M + 4, y, "None yet")
        y -= 14
    else:
        for p in projects:
            ensure(52)
            ph = 44
            round_card(ph)
            qid = _txt(p.get("quotationId")) or _txt(p.get("projectId")) or "—"
            name = _txt(p.get("name") or "Quote")
            st = _txt(p.get("status") or "").replace("_", " ").title() or "—"
            ver = p.get("version")
            c.setFillColorRGB(*ink)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(M + 10, y - 14, name[:48])
            c.setFont("Helvetica", 8)
            c.setFillColorRGB(*muted)
            c.drawString(M + 10, y - 28, f"{qid}  ·  v{ver or 1}  ·  {st}")
            amt = p.get("totalGrand") if p.get("totalGrand") is not None else p.get("grandTotal")
            c.setFillColorRGB(*green)
            c.setFont("Helvetica-Bold", 9)
            c.drawRightString(W - M - 10, y - 14, _inr(amt) if amt is not None else "—")
            if p.get("totalTaxable") is not None:
                c.setFillColorRGB(*muted)
                c.setFont("Helvetica", 7)
                c.drawRightString(W - M - 10, y - 28, f"ex-GST {_inr(p.get('totalTaxable'))}")
            y -= ph + 8

    # ── Advances table ────────────────────────────────────────────────────
    y -= 4
    c.setFillColorRGB(*ink)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(M, y, "Advances")
    y -= 12
    if not advances:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*muted)
        c.drawString(M + 4, y, "None yet")
        y -= 14
    else:
        c.setFillColorRGB(*muted)
        c.setFont("Helvetica", 7)
        c.drawString(M, y, "DATE")
        c.drawString(M + 70, y, "AMOUNT")
        c.drawString(M + 150, y, "MODE")
        c.drawString(M + 210, y, "QUOTE / REF")
        y -= 10
        c.setStrokeColorRGB(*line_c)
        c.line(M, y + 4, W - M, y + 4)
        c.setFillColorRGB(*ink)
        running = 0.0
        for a in advances:
            ensure(16)
            paid = _txt(a.get("paidAt"))[:10] or "—"
            mode = (_txt(a.get("paymentMode")) or "cash").upper()
            try:
                running += float(a.get("amount") or 0)
            except (TypeError, ValueError):
                pass
            linked = a.get("linkedQuote") or {}
            qid = _txt(a.get("quoteId") or linked.get("quotationId") or a.get("projectId"))
            ver = a.get("quoteVersion")
            if ver is None:
                ver = linked.get("version")
            ref = _txt(a.get("reference") or a.get("note"))
            extra = " · ".join(x for x in ((f"{qid} v{ver}" if qid else qid), ref) if x)
            c.setFont("Helvetica", 8)
            c.drawString(M, y, paid)
            c.drawString(M + 70, y, _inr(a.get("amount")))
            c.drawString(M + 150, y, mode[:10])
            c.setFillColorRGB(*muted)
            c.drawString(M + 210, y, extra[:48] or "—")
            c.setFillColorRGB(*ink)
            y -= 13

    # ── Totals grid ───────────────────────────────────────────────────────
    y -= 10
    ensure(118)
    total_taxable = totals.get("totalTaxable", totals.get("value", totals.get("billed")))
    total_gst = totals.get("totalGst")
    total_grand = totals.get("totalGrand")
    total_adv = totals.get("advances") if totals.get("advances") is not None else totals.get("totalAdvances")
    bal = totals.get("balance")
    bal_gst = totals.get("balanceWithGst")
    kpis = [
        ("Taxable", _inr(total_taxable)),
        ("GST", _inr(total_gst)),
        ("With GST", _inr(total_grand)),
        ("Advance", _inr(total_adv)),
        ("Balance (taxable)", _inr(bal)),
        ("Balance (w/ GST)", _inr(bal_gst)),
    ]
    grid_h = 92
    round_card(grid_h)
    col_w = (W - 2 * M - 16) / 3.0
    for i, (lab, val) in enumerate(kpis):
        cx = M + 10 + (i % 3) * col_w
        cy = y - 18 - (i // 3) * 40
        c.setFillColorRGB(*muted)
        c.setFont("Helvetica", 7)
        c.drawString(cx, cy, lab.upper())
        c.setFillColorRGB(*green if "Balance" in lab else ink)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(cx, cy - 14, val)
    y -= grid_h + 10

    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 7)
    c.drawString(M, y, TOTALS_NOTE_SHORT)
    y -= 16

    imgs = resolve_doc_images(customer=cust)
    auth = imgs.get("authImage")
    recv = imgs.get("recvImage")
    if auth or recv:
        ensure(90)
        from WEOS.factory.media_assets import draw_stamp_signature_block

        y = draw_stamp_signature_block(
            c,
            x=M,
            y=y,
            width=W - 2 * M,
            company_name=co_name,
            customer_name=cust,
            stamp_path=auth,
            signature_path=recv,
        )

    c.setFillColorRGB(*muted)
    c.setFont("Helvetica", 7)
    c.drawString(M, 20, "Powered by WEOS")
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


def render_ledger_html(ledger: Mapping[str, Any], company: Mapping[str, Any] | None = None, *, base_url: str = "") -> str:
    """Public / print HTML ledger — same card language as the live scan page."""
    company = company or {}
    profile = ledger.get("profile") or {}
    projects = list(ledger.get("projects") or [])
    advances = list(ledger.get("advances") or [])
    totals = ledger.get("totals") or {}
    cust = _txt(ledger.get("customer") or profile.get("name"))
    co_name = html.escape(_txt(company.get("companyName") or company.get("name") or "WEOS"))

    def esc(x: Any) -> str:
        return html.escape("" if x is None else str(x))

    def inr_html(n: Any) -> str:
        try:
            return f"₹{float(n or 0):,.2f}"
        except (TypeError, ValueError):
            return "₹—"

    proj_html = ""
    if not projects:
        proj_html = '<p class="muted">No running quotes yet</p>'
    else:
        for p in projects:
            amt = p.get("totalGrand") if p.get("totalGrand") is not None else p.get("grandTotal")
            qid = esc(p.get("quotationId") or p.get("projectId") or "—")
            st = esc(str(p.get("status") or "").replace("_", " ").title() or "—")
            proj_html += (
                '<div class="item">'
                f"<strong>{esc(p.get('name') or 'Quote')}</strong>"
                f'<div class="muted">{qid} · v{esc(p.get("version") or 1)} · {st}</div>'
                f'<div class="amt">{inr_html(amt)}</div>'
                "</div>"
            )

    adv_rows = ""
    if not advances:
        adv_rows = '<tr><td colspan="4" class="muted">No advances yet</td></tr>'
    else:
        for a in advances:
            linked = a.get("linkedQuote") or {}
            qid = a.get("quoteId") or linked.get("quotationId") or a.get("projectId") or ""
            ver = a.get("quoteVersion") if a.get("quoteVersion") is not None else linked.get("version")
            ref = " · ".join(
                x
                for x in (
                    (f"{qid} v{ver}" if qid else str(qid or "")),
                    _txt(a.get("reference") or a.get("note")),
                )
                if x
            )
            adv_rows += (
                f"<tr><td>{esc(str(a.get('paidAt') or '')[:10] or '—')}</td>"
                f"<td>{inr_html(a.get('amount'))}</td>"
                f"<td>{esc((a.get('paymentMode') or 'cash').upper())}</td>"
                f"<td>{esc(ref or '—')}</td></tr>"
            )

    gst_pct = totals.get("gstPercent") or 18
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="robots" content="noindex"/>
<title>Ledger · {esc(cust)} · {co_name}</title>
<style>
:root{{--ink:#141410;--muted:#5c584f;--bg:#e8e3d8;--card:#fffdf9;--line:rgba(20,20,16,.12);--green:#0a5a48}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);
  background:radial-gradient(ellipse 80% 50% at 0% -10%,#c9e5db,transparent 55%),
             radial-gradient(ellipse 60% 40% at 100% 0%,#efd6c2,transparent 50%),var(--bg)}}
.wrap{{max-width:820px;margin:0 auto;padding:1.1rem 1rem 2.5rem}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem;margin-bottom:.85rem;
  box-shadow:0 10px 40px rgba(20,20,16,.06)}}
h1{{font-size:1.2rem;margin:.1rem 0 .25rem}}
h2{{font-size:.95rem;margin:0 0 .55rem}}
.muted{{color:var(--muted);font-size:.82rem}}
.kpis{{display:flex;flex-wrap:wrap;gap:.6rem}}
.kpi{{flex:1;min-width:140px;background:#f7f4ee;border-radius:10px;padding:.55rem .7rem}}
.kpi .l{{font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
.kpi .v{{font-size:1.05rem;font-weight:650;margin-top:.15rem}}
.item{{position:relative;padding:.55rem .2rem .55rem 0;border-bottom:1px solid var(--line)}}
.item:last-child{{border-bottom:0}}
.item .amt{{position:absolute;right:0;top:.55rem;font-weight:650;color:var(--green)}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th,td{{text-align:left;padding:.4rem .35rem;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}
.btn{{display:inline-block;background:var(--green);color:#f4faf7;text-decoration:none;border-radius:10px;
  padding:.45rem .75rem;font-weight:600;font-size:.85rem;margin:.15rem .25rem 0 0}}
.btn.ghost{{background:transparent;color:var(--green);border:1px solid var(--green)}}
@page{{size:A4 portrait;margin:12mm}}
@media print{{
  html,body{{background:#fff!important}}
  .wrap{{max-width:none;margin:0;padding:0}}
  .card{{box-shadow:none;break-inside:avoid;border-radius:8px}}
  .btn{{display:none!important}}
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="muted">Customer account ledger · WEOS</div>
    <h1>{co_name}</h1>
    <div class="muted">GSTIN {esc(company.get('gstNo') or '—')}
      {(' · ' + esc(company.get('phone'))) if company.get('phone') else ''}
      {(' · ' + esc(company.get('email'))) if company.get('email') else ''}
    </div>
    {f"<div class='muted' style='margin-top:.25rem'>{esc(company.get('address'))}</div>" if company.get('address') else ""}
  </div>
  <div class="card">
    <div class="muted">Customer</div>
    <strong style="font-size:1.1rem">{esc(cust or '—')}</strong>
    <div class="muted" style="margin-top:.25rem">{esc(profile.get('phone') or '')}
      {(' · GSTIN ' + esc(profile.get('gstNo'))) if profile.get('gstNo') else ''}
    </div>
    {f"<div class='muted'>{esc(profile.get('address'))}</div>" if profile.get('address') else ""}
  </div>
  <div class="card">
    <h2>Running quotes / projects</h2>
    {proj_html}
  </div>
  <div class="card">
    <h2>Advances</h2>
    <table>
      <thead><tr><th>Date</th><th>Amount</th><th>Mode</th><th>Quote / ref</th></tr></thead>
      <tbody>{adv_rows}</tbody>
    </table>
  </div>
  <div class="card">
    <h2>Totals</h2>
    <div class="kpis">
      <div class="kpi"><div class="l">Taxable</div><div class="v">{inr_html(totals.get('totalTaxable', totals.get('billed')))}</div></div>
      <div class="kpi"><div class="l">GST {esc(gst_pct)}%</div><div class="v">{inr_html(totals.get('totalGst'))}</div></div>
      <div class="kpi"><div class="l">With GST</div><div class="v">{inr_html(totals.get('totalGrand'))}</div></div>
      <div class="kpi"><div class="l">Advance</div><div class="v">{inr_html(totals.get('totalAdvances', totals.get('advances')))}</div></div>
      <div class="kpi"><div class="l">Balance (taxable)</div><div class="v">{inr_html(totals.get('balance'))}</div></div>
      <div class="kpi"><div class="l">Balance (w/ GST)</div><div class="v">{inr_html(totals.get('balanceWithGst'))}</div></div>
    </div>
    <p class="muted" style="margin:.7rem 0 0">{esc(TOTALS_NOTE_SHORT)}</p>
  </div>
</div>
</body>
</html>"""
