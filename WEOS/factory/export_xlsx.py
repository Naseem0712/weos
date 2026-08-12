"""Excel exports mirroring Quote / Ledger / Advance slip PDF section order."""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


def _txt(v: Any) -> str:
    return str(v or "").strip()


def _num(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _wb():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    return wb, Font(bold=True), Alignment(wrap_text=True, vertical="top")


def _write_header(ws, rows: Sequence[Sequence[Any]], bold_font) -> int:
    r = 1
    for row in rows:
        for c, val in enumerate(row, start=1):
            cell = ws.cell(r, c, val)
            if r == 1 or (c == 1 and isinstance(val, str) and val.endswith(":")):
                cell.font = bold_font
        r += 1
    return r


def export_quote_xlsx(payload: Mapping[str, Any], company: Mapping[str, Any] | None = None) -> bytes:
    company = company or {}
    wb, bold, wrap = _wb()
    ws = wb.active
    ws.title = "Quote"

    qid = _txt(payload.get("quotationId") or payload.get("quoteNumber") or payload.get("projectId"))
    cust = _txt(payload.get("customer"))
    header = [
        ["Company", (_txt(company.get("companyName")) or "WEOS").upper()],
        ["Address", _txt(company.get("address"))],
        ["GSTIN", _txt(company.get("gstNo"))],
        ["Phone", _txt(company.get("phone"))],
        ["Email", _txt(company.get("email"))],
        [],
        ["Quote No", qid],
        ["Date", _txt(payload.get("quoteDate") or payload.get("createdOn"))],
        ["Customer", cust],
        ["Project", _txt(payload.get("name"))],
        [],
        ["#", "Description", "W mm", "H mm", "Qty", "Rate", "Amount", "Series", "Track", "Shutters"],
    ]
    r = _write_header(ws, header, bold)
    for i, line in enumerate(payload.get("lines") or [], start=1):
        selling = line.get("selling") or {}
        opts = line.get("options") or {}
        layout = line.get("layout") or {}
        ws.cell(r, 1, i)
        ws.cell(r, 2, _txt(line.get("description") or line.get("displayName") or line.get("product"))).alignment = wrap
        ws.cell(r, 3, _num(line.get("width")))
        ws.cell(r, 4, _num(line.get("height")))
        ws.cell(r, 5, int(line.get("qty") or 1))
        ws.cell(r, 6, _num(selling.get("sellingRate") or line.get("sellingRate")))
        ws.cell(r, 7, _num(selling.get("sellingAmount") or line.get("commercialTotal") or (line.get("price") or {}).get("total")))
        ws.cell(r, 8, _txt(line.get("sectionSeries") or (line.get("sectionSpecs") or {}).get("seriesTitle")))
        ws.cell(r, 9, _txt(layout.get("trackCount") or opts.get("trackCount")))
        ws.cell(r, 10, _txt(layout.get("glassCount") or opts.get("glassShutters") or opts.get("glassCount")))
        r += 1

    price = payload.get("price") or {}
    combined = payload.get("combined") or {}
    r += 1
    ws.cell(r, 1, "Totals").font = bold
    r += 1
    ws.cell(r, 1, "Grand total")
    ws.cell(r, 2, _num(price.get("total") or combined.get("grandTotal") or combined.get("commercialGrandTotal")))
    r += 2
    ws.cell(r, 1, "Terms").font = bold
    r += 1
    ws.cell(r, 1, _txt(payload.get("terms") or company.get("terms"))).alignment = wrap

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(42, max(12, len(str(col[0].value or "")) + 4))

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_ledger_xlsx(ledger: Mapping[str, Any], company: Mapping[str, Any] | None = None) -> bytes:
    company = company or {}
    wb, bold, wrap = _wb()
    ws = wb.active
    ws.title = "Ledger"
    profile = ledger.get("profile") or {}
    totals = ledger.get("totals") or {}

    r = _write_header(
        ws,
        [
            ["Company", (_txt(company.get("companyName")) or "WEOS").upper()],
            ["Address", _txt(company.get("address"))],
            ["GSTIN", _txt(company.get("gstNo"))],
            [],
            ["CUSTOMER ACCOUNT LEDGER"],
            ["Customer", _txt(ledger.get("customer") or profile.get("name"))],
            ["Address", _txt(profile.get("address"))],
            ["Phone", _txt(profile.get("phone"))],
            ["GSTIN", _txt(profile.get("gstNo"))],
            ["As of", _txt(ledger.get("asOf"))],
            [],
            ["Project Id", "Name", "Quote #", "Version", "Status", "Amount"],
        ],
        bold,
    )
    for p in ledger.get("projects") or []:
        ws.cell(r, 1, _txt(p.get("projectId")))
        ws.cell(r, 2, _txt(p.get("name")))
        ws.cell(r, 3, _txt(p.get("quotationId")))
        ws.cell(r, 4, p.get("version"))
        ws.cell(r, 5, _txt(p.get("status")))
        ws.cell(r, 6, _num(p.get("grandTotal")))
        r += 1

    r += 1
    ws.cell(r, 1, "Advance breakdown").font = bold
    r += 1
    for c, h in enumerate(["Date", "Amount", "Mode", "Quote", "Version", "Reference", "Note"], start=1):
        ws.cell(r, c, h).font = bold
    r += 1
    for a in ledger.get("advances") or []:
        linked = a.get("linkedQuote") or {}
        ws.cell(r, 1, _txt(a.get("paidAt"))[:10])
        ws.cell(r, 2, _num(a.get("amount")))
        ws.cell(r, 3, _txt(a.get("paymentMode")))
        ws.cell(r, 4, _txt(a.get("quoteId") or linked.get("quotationId") or a.get("projectId")))
        ws.cell(r, 5, a.get("quoteVersion") if a.get("quoteVersion") is not None else linked.get("version"))
        ws.cell(r, 6, _txt(a.get("reference")))
        ws.cell(r, 7, _txt(a.get("note")))
        r += 1

    r += 1
    ws.cell(r, 1, "Totals").font = bold
    r += 1
    ws.cell(r, 1, "Total value")
    ws.cell(r, 2, _num(totals.get("value", totals.get("billed"))))
    r += 1
    ws.cell(r, 1, "Total advances")
    ws.cell(r, 2, _num(totals.get("advances")))
    r += 1
    ws.cell(r, 1, "Balance")
    ws.cell(r, 2, _num(totals.get("balance")))

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_advance_xlsx(
    advance: Mapping[str, Any],
    *,
    company: Mapping[str, Any] | None = None,
    ledger: Mapping[str, Any] | None = None,
    customer: str | None = None,
) -> bytes:
    company = company or {}
    ledger = ledger or {}
    profile = ledger.get("profile") or {}
    totals = ledger.get("totals") or {}
    linked = advance.get("linkedQuote") if isinstance(advance.get("linkedQuote"), Mapping) else {}
    wb, bold, wrap = _wb()
    ws = wb.active
    ws.title = "Advance Slip"
    _write_header(
        ws,
        [
            ["Company", (_txt(company.get("companyName")) or "WEOS").upper()],
            ["Address", _txt(company.get("address"))],
            ["GSTIN", _txt(company.get("gstNo"))],
            [],
            ["ADVANCE RECEIPT / PAYMENT SLIP"],
            ["Slip No", _txt(advance.get("slipNo") or advance.get("id") or advance.get("advanceId"))],
            ["Date", _txt(advance.get("paidAt") or advance.get("date"))[:10]],
            ["Customer", _txt(customer or advance.get("customerName") or ledger.get("customer") or profile.get("name"))],
            ["Customer address", _txt(profile.get("address"))],
            ["Project", _txt(advance.get("projectName") or linked.get("name") or advance.get("projectId"))],
            ["Quote Ref", _txt(advance.get("quoteId") or linked.get("quotationId") or advance.get("quotationId"))],
            ["Advance amount", _num(advance.get("amount"))],
            ["Payment mode", _txt(advance.get("paymentMode"))],
            ["Reference", _txt(advance.get("reference"))],
            ["Note", _txt(advance.get("note"))],
            [],
            ["Total value", _num(totals.get("value", totals.get("billed")))],
            ["Total advances", _num(totals.get("advances"))],
            ["Balance outstanding", _num(totals.get("balance"))],
            ["As of", _txt(ledger.get("asOf")) or datetime.now(timezone.utc).isoformat()],
        ],
        bold,
    )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def safe_xlsx_name(*parts: str) -> str:
    bits = []
    for p in parts:
        s = re.sub(r"[^A-Za-z0-9._-]+", "_", _txt(p)).strip("._")
        if s:
            bits.append(s[:40])
    return ("_".join(bits) or "export") + ".xlsx"
