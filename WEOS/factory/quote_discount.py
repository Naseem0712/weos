"""Site-final discount on a saved quote: percent, fix amount, or GST off."""

from __future__ import annotations

from typing import Any, Mapping

DISCOUNT_MODES = ("off", "percent", "amount", "gst_off")


def _money(n: Any) -> float:
    try:
        if n is None or n == "":
            return 0.0
        return round(float(n), 2)
    except (TypeError, ValueError):
        return 0.0


def normalize_discount(raw: Any) -> dict[str, Any]:
    src = raw if isinstance(raw, Mapping) else {}
    mode = str(src.get("mode") or src.get("kind") or "off").strip().lower()
    if mode in {"gst", "gstless", "gst_less", "no_gst"}:
        mode = "gst_off"
    if mode in {"fixed", "flat", "value"}:
        mode = "amount"
    if mode in {"pct", "%", "percentage"}:
        mode = "percent"
    if mode not in DISCOUNT_MODES:
        mode = "off"
    try:
        pct = float(src.get("percent") if src.get("percent") is not None else src.get("discountPercent") or 0)
    except (TypeError, ValueError):
        pct = 0.0
    if pct < 0:
        pct = 0.0
    if pct > 100:
        pct = 100.0
    amt = _money(src.get("amount") if src.get("amount") is not None else src.get("discountAmount"))
    if amt < 0:
        amt = 0.0
    note = str(src.get("note") or "").strip() or None
    return {
        "mode": mode,
        "percent": round(pct, 2) if mode == "percent" else 0.0,
        "amount": amt if mode == "amount" else 0.0,
        "note": note,
    }


def apply_discount(parts: Mapping[str, Any] | None, discount: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return money parts after discount. Input is taxable / GST / grand."""
    src = parts if isinstance(parts, Mapping) else {}
    tax = _money(src.get("totalTaxable"))
    gst = _money(src.get("totalGst") if src.get("totalGst") is not None else src.get("gstAmount"))
    grand = _money(src.get("totalGrand") if src.get("totalGrand") is not None else src.get("projectValue"))
    if grand <= 0 and tax > 0:
        grand = round(tax + gst, 2)
    disc = normalize_discount(discount)
    out = {
        "totalTaxable": tax,
        "totalGst": gst,
        "gstAmount": gst,
        "totalGrand": grand,
        "projectValue": grand,
        "discountMode": disc["mode"],
        "discountPercent": disc["percent"],
        "discountAmount": 0.0,
        "discountNote": disc.get("note"),
        "gstPercent": src.get("gstPercent"),
    }
    mode = disc["mode"]
    if mode == "off" or grand <= 0:
        return out
    if mode == "gst_off":
        cut = gst
        out["totalGst"] = 0.0
        out["gstAmount"] = 0.0
        out["totalGrand"] = tax
        out["projectValue"] = tax
        out["discountAmount"] = cut
        return out
    cut = 0.0
    if mode == "percent" and disc["percent"] > 0:
        cut = round(grand * disc["percent"] / 100.0, 2)
    elif mode == "amount" and disc["amount"] > 0:
        cut = min(disc["amount"], grand)
    if cut <= 0:
        return out
    new_grand = round(max(0.0, grand - cut), 2)
    if grand > 0 and tax > 0:
        ratio = new_grand / grand
        new_tax = round(tax * ratio, 2)
        new_gst = round(max(0.0, new_grand - new_tax), 2)
    else:
        new_tax = new_grand
        new_gst = 0.0
    out["totalTaxable"] = new_tax
    out["totalGst"] = new_gst
    out["gstAmount"] = new_gst
    out["totalGrand"] = new_grand
    out["projectValue"] = new_grand
    out["discountAmount"] = cut
    return out
