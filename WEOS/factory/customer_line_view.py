"""Customer-facing cart line helpers — scan page, quote PDF, ledger.

Never leak stub ids, ``coming soon``, or internal glass codes. Recompute selling
amounts from width/height/qty/sellingRate when stored totals are missing/zero
(common for eco-gulf lines that only keep a rate).
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from WEOS.factory.line_kind import (
    PRODUCT_TYPE_CHOICES,
    design_serial_label,
    is_railing_cart_line,
    is_shower_cart_line,
    is_ventilator_cart_line,
    line_location_name,
    normalize_product_type,
    quote_qty_breakdown,
    railing_product_type_for_line,
    totals_group_for_line,
)

_COMING_SOON = re.compile(r"(?i)\s*\(?\s*coming\s+soon\s*\)?")
_ID_LIKE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")

_TYPE_LABELS: dict[str, str] = {
    "sliding": "Sliding window",
    "casements": "Casement",
    "windows": "Window",
    "door": "Door",
    "staircase_railing": "Staircase railing",
    "railing": "Railing",
    "shower_partition": "Shower partition",
    "bathroom_ventilator": "Bathroom ventilator",
    "fold": "Fold & sliding",
    "telescopic": "Telescopic",
    "synchron": "Synchron",
    "style": "Style / slide door",
    "pergolas": "Pergola",
}
for _k, _lab in PRODUCT_TYPE_CHOICES:
    _TYPE_LABELS.setdefault(_k, _lab)


def _money(n: Any) -> float | None:
    if n is None or n == "":
        return None
    try:
        return float(n)
    except (TypeError, ValueError):
        return None


def _opts(line: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(line, Mapping):
        return {}
    opts = line.get("options")
    return dict(opts) if isinstance(opts, Mapping) else {}


def _clean_coming_soon(text: Any) -> str:
    s = _COMING_SOON.sub(" ", str(text or "")).strip()
    return re.sub(r"\s{2,}", " ", s).strip(" -·/")


def _looks_like_id(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    low = t.lower()
    if "_stub" in low or low.endswith("_stub"):
        return True
    if low in {"section_series", "casement_stub", "product", "item"}:
        return True
    if _ID_LIKE.match(low) and any(tok in low for tok in ("stub", "mm_", "_sliding", "_gulf", "_eco", "casement")):
        return True
    return False


def line_colour(line: Mapping[str, Any] | None) -> str:
    if not isinstance(line, Mapping):
        return ""
    opts = _opts(line)
    for src in (line, opts):
        for key in ("colour", "color", "finishColour", "profileColour"):
            val = str(src.get(key) or "").strip()
            if val:
                return val.replace("_", " ")
    return ""


def line_glass_label(line: Mapping[str, Any] | None) -> str:
    if not isinstance(line, Mapping):
        return ""
    try:
        from WEOS.factory.window_specs import human_glass_label

        lab = human_glass_label(line) or ""
    except Exception:
        lab = ""
    if lab and "shutter_" not in lab.lower() and "_glass" not in lab.lower().replace(" ", "_"):
        return lab.replace("_", " ")
    raw = line.get("glass")
    if isinstance(raw, str) and raw.strip():
        return raw.split("@")[0].replace("_", " ").strip()
    return lab.replace("_", " ") if lab else ""


def customer_type_label(line: Mapping[str, Any] | None) -> str:
    """Human product type for customer scan / quote — never stub ids or coming soon."""
    if not isinstance(line, Mapping):
        return "Item"
    opts = _opts(line)
    raw_display = str(line.get("displayName") or line.get("productLabel") or line.get("description") or "")
    had_coming_soon = bool(_COMING_SOON.search(raw_display))
    display = _clean_coming_soon(raw_display)
    pid = str(line.get("product") or line.get("productId") or "").strip()
    pt = normalize_product_type(
        line.get("productType") or opts.get("productType") or pid
    )
    if is_railing_cart_line(line):
        pt = railing_product_type_for_line(line)
    elif is_shower_cart_line(line):
        pt = "shower_partition"
    elif is_ventilator_cart_line(line):
        pt = "bathroom_ventilator"

    if (
        display
        and not had_coming_soon
        and not _looks_like_id(display)
        and "coming soon" not in display.lower()
    ):
        # Prefer a specific display name when it is already customer-friendly.
        if pt and display.lower() in {"window", "windows", "product", "fixed light"}:
            return _TYPE_LABELS.get(pt, display)
        return display

    if pt and pt in _TYPE_LABELS:
        return _TYPE_LABELS[pt]
    if pt:
        return pt.replace("_", " ").title()

    blob = (pid + " " + display).lower()
    if "casement" in blob or "openable" in blob:
        return "Casement"
    if "stair" in blob and "rail" in blob:
        return "Staircase railing"
    if "rail" in blob:
        return "Railing"
    if "shower" in blob:
        return "Shower partition"
    if "ventilat" in blob:
        return "Bathroom ventilator"
    if "slid" in blob:
        return "Sliding window"
    if "fold" in blob:
        return "Fold & sliding"
    if display:
        return display
    if pid:
        return pid.replace("_", " ").title()
    return "Item"


def _railing_amount(line: Mapping[str, Any]) -> float | None:
    opts = _opts(line)
    rq = opts.get("railingQuote") if isinstance(opts.get("railingQuote"), Mapping) else {}
    shower_q = opts.get("showerQuote") if isinstance(opts.get("showerQuote"), Mapping) else {}
    vent_q = opts.get("ventilatorQuote") if isinstance(opts.get("ventilatorQuote"), Mapping) else {}
    for src in (rq, shower_q, vent_q, line.get("price") if isinstance(line.get("price"), Mapping) else {}):
        if not isinstance(src, Mapping):
            continue
        for key in ("sellingAmount", "sellingTotal", "grandTotal", "total", "commercialTotal"):
            n = _money(src.get(key))
            if n is not None and n > 0:
                return round(n, 2)
    return None


def customer_line_amount(line: Mapping[str, Any] | None) -> float | None:
    """Selling / grand line total (₹). Recompute from rate×size×qty when stored is 0."""
    if not isinstance(line, Mapping):
        return None
    selling = line.get("selling") if isinstance(line.get("selling"), Mapping) else {}
    price = line.get("price") if isinstance(line.get("price"), Mapping) else {}
    candidates = [
        selling.get("sellingAmount"),
        line.get("commercialTotal"),
        line.get("sellingAmount"),
        line.get("lineTotal"),
        line.get("amount"),
        price.get("sellingAmount"),
        price.get("commercialTotal"),
        price.get("total"),
    ]
    for raw in candidates:
        n = _money(raw)
        if n is not None and n > 0:
            return round(n, 2)

    special = _railing_amount(line)
    if special is not None and special > 0:
        return special

    rate = line.get("sellingRate")
    if rate is None or str(rate).strip() == "":
        rate = selling.get("sellingRate") or line.get("customerRate")
    opts = _opts(line)
    rq = opts.get("railingQuote") if isinstance(opts.get("railingQuote"), Mapping) else {}
    if rate is None or str(rate).strip() == "":
        rate = rq.get("sellingPerUnit") or rq.get("sellingRate")
    rate_n = _money(rate)
    if rate_n is None:
        return None

    try:
        qty = int(round(float(line.get("qty") or line.get("quantity") or 1)))
    except (TypeError, ValueError):
        qty = 1
    qty = max(qty, 1)
    try:
        width = float(line.get("width") or 0)
        height = float(line.get("height") or 0)
    except (TypeError, ValueError):
        width = height = 0.0
    sale_unit = str(
        line.get("saleUnit") or selling.get("saleUnit") or rq.get("saleUnit") or "sqft"
    ).strip() or "sqft"
    try:
        from WEOS.factory.live_pricing import sell_amount

        sell = sell_amount(
            width_mm=width,
            height_mm=height,
            qty=qty,
            selling_rate=rate_n,
            sale_unit=sale_unit,
        )
        amt = _money(sell.get("sellingAmount"))
        if amt is not None and amt > 0:
            return round(amt, 2)
    except Exception:
        pass
    # Per-opening / per-piece fallback when size is missing.
    if sale_unit.lower() in ("opening", "pc", "nos", "each") or (not width and not height):
        return round(rate_n * qty, 2)
    return None


def line_size_label(line: Mapping[str, Any] | None) -> str:
    if not isinstance(line, Mapping):
        return "—"
    w, h = line.get("width"), line.get("height")
    try:
        if w and h:
            return f"{int(float(w))}×{int(float(h))} mm"
    except (TypeError, ValueError):
        pass
    size = str(line.get("size") or "").strip()
    return size or "—"


def public_product_row(index: int, line: Mapping[str, Any] | None) -> dict[str, Any]:
    """One customer-safe product row for scan JSON / HTML / PDF."""
    line = line if isinstance(line, Mapping) else {}
    loc = line_location_name(line)
    serial = str(line.get("serial") or line.get("serialLabel") or "").strip()
    if not serial or loc and serial.endswith(loc):
        serial = f"W{index + 1}"
    elif serial.lower().startswith("w") and "·" in serial:
        serial = serial.split("·", 1)[0].strip() or f"W{index + 1}"
    qty = line.get("qty") if line.get("qty") is not None else line.get("quantity")
    try:
        qty_n: Any = int(round(float(qty or 1)))
    except (TypeError, ValueError):
        qty_n = qty or 1
    amt = customer_line_amount(line)
    return {
        "serial": serial or design_serial_label(index, None),
        "location": loc or "—",
        "locationName": loc or "",
        "positionName": loc or "",
        "type": customer_type_label(line),
        "size": line_size_label(line),
        "qty": qty_n,
        "glass": line_glass_label(line) or "—",
        "colour": line_colour(line) or "—",
        "amount": amt,
    }


def merge_calc_line(stored: Mapping[str, Any] | None, calc: Mapping[str, Any] | None) -> dict[str, Any]:
    """Overlay calculation snapshot onto a stored cart line (location + selling)."""
    out = dict(stored or {})
    if not isinstance(calc, Mapping):
        return out
    if not line_location_name(out) and line_location_name(calc):
        loc = line_location_name(calc)
        out["locationName"] = loc
        out["positionName"] = loc
        opts = dict(out.get("options") or {}) if isinstance(out.get("options"), Mapping) else {}
        opts["locationName"] = loc
        opts["positionName"] = loc
        out["options"] = opts
    if customer_line_amount(out) is None and customer_line_amount(calc) is not None:
        for key in ("selling", "commercialTotal", "sellingAmount", "sellingRate", "saleUnit", "price"):
            if key in calc and key not in out:
                out[key] = calc[key]
            elif key == "selling" and isinstance(calc.get("selling"), Mapping):
                out["selling"] = dict(calc["selling"])
            elif key == "price" and isinstance(calc.get("price"), Mapping) and not isinstance(out.get("price"), Mapping):
                out["price"] = dict(calc["price"])
        if calc.get("sellingRate") is not None and out.get("sellingRate") is None:
            out["sellingRate"] = calc.get("sellingRate")
    for key in ("displayName", "productType", "colour", "glass", "width", "height", "qty"):
        if not out.get(key) and calc.get(key) not in (None, ""):
            out[key] = calc[key]
    return out


def totals_by_type(lines: list[Any] | None) -> list[dict[str, Any]]:
    """Qty + amount buckets for customer quote totals."""
    buckets: dict[str, dict[str, Any]] = {}
    for i, ln in enumerate(lines or []):
        if not isinstance(ln, Mapping):
            continue
        label = totals_group_for_line(ln) or customer_type_label(ln)
        try:
            qty = int(round(float(ln.get("qty") or ln.get("quantity") or 1)))
        except (TypeError, ValueError):
            qty = 1
        amt = customer_line_amount(ln) or 0.0
        row = buckets.setdefault(label, {"type": label, "qty": 0, "amount": 0.0})
        row["qty"] += max(qty, 0)
        row["amount"] = round(row["amount"] + float(amt), 2)
    order = [g[0] for g in quote_qty_breakdown(lines or [])]
    extra = [k for k in buckets if k not in order]
    out = []
    for lab in order + extra:
        row = buckets.get(lab)
        if row and (row["qty"] or row["amount"]):
            out.append(row)
    return out


def public_products_from_doc(doc: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Build scan product rows from a project/quote document."""
    doc = doc if isinstance(doc, Mapping) else {}
    lines = [ln for ln in (doc.get("lines") or []) if isinstance(ln, Mapping)]
    calc = doc.get("lastCalculation") if isinstance(doc.get("lastCalculation"), Mapping) else {}
    calc_lines = [ln for ln in (calc.get("lines") or []) if isinstance(ln, Mapping)]
    by_id: dict[str, Mapping[str, Any]] = {}
    for ln in calc_lines:
        lid = str(ln.get("lineId") or "").strip()
        if lid:
            by_id[lid] = ln
    out: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        calc_ln = by_id.get(str(ln.get("lineId") or ""))
        if calc_ln is None and i < len(calc_lines):
            calc_ln = calc_lines[i]
        merged = merge_calc_line(ln, calc_ln)
        out.append(public_product_row(i, merged))
    if not out and calc_lines:
        out = [public_product_row(i, ln) for i, ln in enumerate(calc_lines)]
    return out
