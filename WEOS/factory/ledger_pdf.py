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
    # Indian-style grouping via locale-ish formatting
    neg = v < 0
    v = abs(v)
    s = f"{v:,.2f}"
    return ("-₹" if neg else "₹") + s


def _txt(v: Any) -> str:
    return str(v or "").strip()


def render_ledger_pdf(ledger: Mapping[str, Any], company: Mapping[str, Any] | None = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

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
    y = H - M

    def line(txt: str, *, size: int = 10, bold: bool = False, dy: float = 14) -> None:
        nonlocal y
        if y < 60:
            c.showPage()
            y = H - M
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(M, y, txt[:110])
        y -= dy

    co_name = (_txt(company.get("companyName")) or "WEOS").upper()
    line(co_name, size=16, bold=True, dy=18)
    for bit in (
        _txt(company.get("address")),
        " · ".join(x for x in (_txt(company.get("phone")), _txt(company.get("email")), _txt(company.get("website"))) if x),
        f"GSTIN: {_txt(company.get('gstNo'))}" if _txt(company.get("gstNo")) else "",
        _txt(company.get("bankDetails")),
    ):
        if bit:
            line(bit, size=8, dy=11)

    y -= 6
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.line(M, y + 8, W - M, y + 8)
    line("CUSTOMER ACCOUNT LEDGER", size=13, bold=True, dy=18)

    cust = _txt(ledger.get("customer") or profile.get("name"))
    line(f"Customer: {cust}", bold=True)
    for bit in (
        _txt(profile.get("address")),
        " · ".join(x for x in (_txt(profile.get("phone")), _txt(profile.get("email")), _txt(profile.get("contactPerson"))) if x),
        f"GSTIN: {_txt(profile.get('gstNo'))}" if _txt(profile.get("gstNo")) else "",
        f"Site: {_txt(profile.get('site'))}" if _txt(profile.get("site")) else "",
    ):
        if bit:
            line(bit, size=9, dy=12)

    y -= 4
    line("Projects / Quotes", bold=True, dy=16)
    if not projects:
        line("  (none)", size=9)
    else:
        for p in projects:
            amt = p.get("grandTotal")
            amt_s = _inr(amt) if amt is not None else "—"
            line(
                f"  {_txt(p.get('projectId'))}  {_txt(p.get('name')) or '—'}  "
                f"[{_txt(p.get('status'))}]  {amt_s}",
                size=9,
                dy=12,
            )

    y -= 4
    line("Advances received", bold=True, dy=16)
    if not advances:
        line("  (none)", size=9)
    else:
        for a in advances:
            paid = _txt(a.get("paidAt"))[:10] or "—"
            mode = (_txt(a.get("paymentMode")) or "cash").upper()
            ref = _txt(a.get("reference"))
            note = _txt(a.get("note"))
            link = _txt(a.get("projectId") or a.get("quoteId"))
            extra = " · ".join(x for x in (ref, note, link) if x)
            line(
                f"  {paid}  {_inr(a.get('amount'))}  via {mode}"
                + (f"  ({extra})" if extra else ""),
                size=9,
                dy=12,
            )

    y -= 8
    c.line(M, y + 10, W - M, y + 10)
    line(f"Total billed (quote grand totals):  {_inr(totals.get('billed'))}", bold=True)
    line(f"Total advances:  {_inr(totals.get('advances'))}", bold=True)
    line(f"Balance up to date:  {_inr(totals.get('balance'))}", size=12, bold=True, dy=16)
    line(f"As of: {as_of_disp}", size=9)
    note = _txt((totals or {}).get("note"))
    if note:
        line(note, size=8, dy=11)

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
