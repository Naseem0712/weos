"""Quote commercial totals — sliding / casement / other + add-services + GST.

Rules (user commercial panel):
  - Product selling amount → Sliding / Casement / Other by system
  - All line-attached add-ons → Add services bucket (also printed under each window)
  - Soft-cancelled lines are excluded from qty / area / money (but may still print marked)
  - GST 18% on taxable after site discount (same ``apply_discount`` / ledger path)
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from WEOS.factory.line_addons import (
    is_line_cancelled,
    line_addons_for_display,
    line_addons_total,
)
from WEOS.factory.line_kind import normalize_product_type
from WEOS.factory.quote_discount import apply_discount, normalize_discount

SQFT_PER_MM2 = 10.7639 / 1_000_000.0

_SLIDING_TYPES = frozenset({"sliding", "telescopic", "synchron", "fold", "style"})
_CASEMENT_TYPES = frozenset({"casements"})


def _money(n: Any) -> float:
    try:
        if n is None or n == "":
            return 0.0
        return round(float(n), 2)
    except (TypeError, ValueError):
        return 0.0


def _qty(line: Mapping[str, Any]) -> int:
    try:
        q = int(round(float(line.get("qty") or line.get("quantity") or 1)))
    except (TypeError, ValueError):
        q = 1
    return max(q, 0)


def _area_sqft(line: Mapping[str, Any]) -> float:
    """Billable area for one line (qty already applied)."""
    try:
        w = float(line.get("width") or 0)
        h = float(line.get("height") or 0)
    except (TypeError, ValueError):
        w = h = 0.0
    if w > 0 and h > 0:
        return round(w * h * SQFT_PER_MM2 * max(_qty(line), 1), 4)
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    for key in ("showerQuote", "ventilatorQuote", "railingQuote"):
        blob = opts.get(key) if isinstance(opts, Mapping) else None
        if not isinstance(blob, Mapping):
            continue
        for ak in ("areaSqft", "areaSft", "lengthRft"):
            n = _money(blob.get(ak))
            if n > 0:
                return n
    return 0.0


def commercial_system_bucket(line: Mapping[str, Any] | None) -> str:
    """``sliding`` | ``casement`` | ``other`` for commercial totals."""
    if not isinstance(line, Mapping):
        return "other"
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    sys = str(
        line.get("system")
        or (opts.get("system") if isinstance(opts, Mapping) else "")
        or ""
    ).strip().lower()
    pt = normalize_product_type(
        line.get("productType")
        or (opts.get("productType") if isinstance(opts, Mapping) else None)
        or line.get("product")
        or line.get("productId")
    )
    if sys in ("casement", "openable", "opening") or pt in _CASEMENT_TYPES:
        return "casement"
    if sys in ("sliding", "telescopic", "synchron", "bifold", "fold", "fold_sliding", "style") or pt in _SLIDING_TYPES:
        return "sliding"
    blob = " ".join(
        str(x or "").lower()
        for x in (
            line.get("displayName"),
            line.get("product"),
            line.get("productId"),
            line.get("category"),
            pt,
            sys,
        )
    )
    if "casement" in blob or "openable" in blob:
        return "casement"
    if "slid" in blob or "tele" in blob or "fold" in blob:
        return "sliding"
    return "other"


def _product_amount(line: Mapping[str, Any]) -> float:
    """Window/door product selling amount excluding line add-ons."""
    from WEOS.factory.customer_line_view import customer_line_product_amount

    total = customer_line_product_amount(line)
    if total is None:
        return 0.0
    return round(max(float(total), 0.0), 2)


def _empty_bucket(label: str) -> dict[str, Any]:
    return {
        "key": label.lower().replace(" ", "_"),
        "label": label,
        "qty": 0,
        "areaSqft": 0.0,
        "amount": 0.0,
        "avgRate": None,
    }


def _finalize_bucket(b: dict[str, Any]) -> dict[str, Any]:
    area = float(b.get("areaSqft") or 0)
    amt = float(b.get("amount") or 0)
    b["areaSqft"] = round(area, 4)
    b["amount"] = round(amt, 2)
    if area > 0:
        b["avgRate"] = round(amt / area, 2)
    else:
        b["avgRate"] = None
    return b


def quote_commercial_breakdown(
    lines: Sequence[Any] | None,
    *,
    discount: Mapping[str, Any] | None = None,
    gst_percent: float = 18.0,
) -> dict[str, Any]:
    """Structured commercial totals from currently visible non-cancelled lines."""
    sliding = _empty_bucket("Sliding windows")
    casement = _empty_bucket("Casements")
    other = _empty_bucket("Other")
    add_services = 0.0
    active_lines = 0

    for ln in lines or []:
        if not isinstance(ln, Mapping):
            continue
        if is_line_cancelled(ln):
            continue
        active_lines += 1
        bucket_key = commercial_system_bucket(ln)
        bucket = {"sliding": sliding, "casement": casement, "other": other}[bucket_key]
        q = _qty(ln)
        bucket["qty"] += q
        bucket["areaSqft"] += _area_sqft(ln)
        bucket["amount"] += _product_amount(ln)
        add_services += line_addons_total(ln)

    for b in (sliding, casement, other):
        _finalize_bucket(b)

    products_total = round(
        float(sliding["amount"]) + float(casement["amount"]) + float(other["amount"]),
        2,
    )
    add_services = round(add_services, 2)
    before_gst = round(products_total + add_services, 2)
    total_area = round(
        float(sliding["areaSqft"]) + float(casement["areaSqft"]) + float(other["areaSqft"]),
        4,
    )

    from WEOS.factory.ledger_store import quote_money_parts

    raw_parts = quote_money_parts(before_gst, gst_percent=gst_percent)
    money = apply_discount(raw_parts, discount)
    disc = normalize_discount(discount)
    disc_amt = _money(money.get("discountAmount"))
    # % of total quote (pre-GST commercial) — for amount mode, derive the %
    if disc["mode"] == "percent":
        disc_pct = float(disc.get("percent") or 0)
    elif before_gst > 0 and disc_amt > 0:
        # amount discount was applied on grand in apply_discount; show % of before_gst
        # using the taxable reduction when available
        tax_cut = round(before_gst - _money(money.get("totalTaxable")), 2)
        disc_pct = round((tax_cut / before_gst) * 100.0, 2) if tax_cut > 0 else round((disc_amt / before_gst) * 100.0, 2)
    else:
        disc_pct = 0.0

    after_discount = _money(money.get("totalTaxable"))
    gst_amt = _money(money.get("totalGst") if money.get("totalGst") is not None else money.get("gstAmount"))
    grand = _money(money.get("totalGrand") if money.get("totalGrand") is not None else money.get("projectValue"))

    buckets = [sliding, casement]
    if other["qty"] or other["amount"]:
        buckets.append(other)

    return {
        "sliding": sliding,
        "casement": casement,
        "other": other,
        "buckets": buckets,
        "totalAreaSqft": total_area,
        "addServices": add_services,
        "productsTotal": products_total,
        "beforeGst": before_gst,
        "discountMode": disc["mode"],
        "discountPercent": disc_pct,
        "discountAmount": disc_amt,
        "discountNote": disc.get("note"),
        "afterDiscount": after_discount,
        "gstPercent": float(money.get("gstPercent") if money.get("gstPercent") is not None else gst_percent),
        "gstAmount": gst_amt,
        "grandTotal": grand,
        "activeLineCount": active_lines,
        "money": money,
    }


def format_commercial_totals_rows(breakdown: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """Label / value rows for PDF TOTALS block."""
    b = breakdown if isinstance(breakdown, Mapping) else {}
    rows: list[tuple[str, str]] = []

    def _bucket_line(lab: str, bucket: Mapping[str, Any]) -> None:
        qty = int(bucket.get("qty") or 0)
        area = float(bucket.get("areaSqft") or 0)
        amt = float(bucket.get("amount") or 0)
        avg = bucket.get("avgRate")
        if qty <= 0 and amt <= 0 and area <= 0:
            return
        avg_s = f" · avg ₹{float(avg):,.2f}/sft" if avg is not None else ""
        rows.append(
            (
                lab,
                f"{qty} Nos · {area:g} sft · ₹{amt:,.2f}{avg_s}",
            )
        )

    _bucket_line("Sliding windows", b.get("sliding") or {})
    _bucket_line("Casements", b.get("casement") or {})
    _bucket_line("Other", b.get("other") or {})
    rows.append(("Total area", f"{float(b.get('totalAreaSqft') or 0):g} Sq.Ft."))
    rows.append(("Add services", f"₹{float(b.get('addServices') or 0):,.2f}"))
    rows.append(("Total before GST", f"₹{float(b.get('beforeGst') or 0):,.2f}"))
    disc_amt = float(b.get("discountAmount") or 0)
    disc_pct = float(b.get("discountPercent") or 0)
    if disc_amt > 0 or str(b.get("discountMode") or "off") != "off":
        pct_bit = f" ({disc_pct:g}% of quote)" if disc_pct else ""
        rows.append(("Discount", f"₹{disc_amt:,.2f}{pct_bit}"))
        rows.append(("Total after discount", f"₹{float(b.get('afterDiscount') or 0):,.2f}"))
    gst_pct = float(b.get("gstPercent") or 18)
    rows.append((f"GST {gst_pct:g}%", f"₹{float(b.get('gstAmount') or 0):,.2f}"))
    rows.append(("Grand total", f"₹{float(b.get('grandTotal') or 0):,.2f}"))
    return rows
