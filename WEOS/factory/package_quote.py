"""Deal / package quotes — commercial lines without a WEOS drawing.

A project may hold 1–20 package quotes. Each quote has item amounts plus a
GST mode (include / exclude / off). Project value is the sum of quote
``projectValue`` figures (agreed payable), never mixed with another job.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

MAX_QUOTES = 20
MAX_ITEMS = 40

CATEGORIES: tuple[tuple[str, str], ...] = (
    ("window", "Windows"),
    ("casement", "Casement windows"),
    ("ventilator", "Vents"),
    ("louver", "Louvers"),
    ("railing", "Railings"),
    ("iron_fabrication", "Iron fabrication"),
    ("gate", "Gates"),
    ("grill", "Grills"),
    ("pergola", "Pergola"),
    ("other", "Other"),
)

_CAT_IDS = {c[0] for c in CATEGORIES}
_CAT_LABEL = dict(CATEGORIES)

UNITS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "window": ("pcs",),
    "casement": ("pcs",),
    "ventilator": ("pcs",),
    "louver": ("pcs",),
    "railing": ("rft", "sft", "pcs"),
    "iron_fabrication": ("kg", "sft"),
    "gate": ("pcs", "sft"),
    "grill": ("pcs", "sft"),
    "pergola": ("sft", "pcs"),
    "other": ("pcs", "sft", "kg", "rft"),
}

GST_MODES = ("exclude", "include", "off")
DEFAULT_GST_PERCENT = 18.0


def _money(n: Any) -> float:
    try:
        if n is None or n == "":
            return 0.0
        return round(float(n), 2)
    except (TypeError, ValueError):
        return 0.0


def _qty(n: Any) -> float | None:
    try:
        if n is None or n == "":
            return None
        v = float(n)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _slug_id(value: Any, prefix: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "", str(value or "")).strip()
    if raw:
        return raw[:24]
    import secrets

    return prefix + secrets.token_hex(4)


def category_id(raw: Any) -> str:
    key = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "windows": "window",
        "casements": "casement",
        "casement_windows": "casement",
        "vent": "ventilator",
        "vents": "ventilator",
        "bathroom_ventilator": "ventilator",
        "louvers": "louver",
        "louvres": "louver",
        "louvre": "louver",
        "railings": "railing",
        "iron": "iron_fabrication",
        "fabrication": "iron_fabrication",
        "ms": "iron_fabrication",
        "gates": "gate",
        "grills": "grill",
        "grilles": "grill",
        "pergolas": "pergola",
    }
    key = aliases.get(key, key)
    return key if key in _CAT_IDS else "other"


def compute_gst_split(
    items_total: float,
    *,
    gst_mode: str = "exclude",
    gst_percent: float = DEFAULT_GST_PERCENT,
) -> dict[str, Any]:
    """Split entered item amounts into taxable / GST / project value."""
    subtotal = round(max(0.0, _money(items_total)), 2)
    mode = str(gst_mode or "exclude").strip().lower()
    if mode not in GST_MODES:
        mode = "exclude"
    try:
        pct = float(gst_percent if gst_percent is not None else DEFAULT_GST_PERCENT)
    except (TypeError, ValueError):
        pct = DEFAULT_GST_PERCENT
    if pct < 0:
        pct = 0.0
    if mode == "off" or pct == 0:
        return {
            "gstMode": "off" if mode == "off" else mode,
            "gstPercent": 0.0 if mode == "off" else round(pct, 2),
            "itemsSubtotal": subtotal,
            "totalTaxable": subtotal,
            "gstAmount": 0.0,
            "totalGrand": subtotal,
            "projectValue": subtotal,
        }
    if mode == "include":
        grand = subtotal
        gst_amt = round(grand * pct / (100.0 + pct), 2) if pct else 0.0
        taxable = round(grand - gst_amt, 2)
        return {
            "gstMode": "include",
            "gstPercent": round(pct, 2),
            "itemsSubtotal": subtotal,
            "totalTaxable": taxable,
            "gstAmount": gst_amt,
            "totalGrand": grand,
            "projectValue": grand,
        }
    taxable = subtotal
    gst_amt = round(taxable * pct / 100.0, 2)
    grand = round(taxable + gst_amt, 2)
    return {
        "gstMode": "exclude",
        "gstPercent": round(pct, 2),
        "itemsSubtotal": subtotal,
        "totalTaxable": taxable,
        "gstAmount": gst_amt,
        "totalGrand": grand,
        "projectValue": grand,
    }


def normalize_package_item(raw: Mapping[str, Any] | None, *, index: int = 0) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    amount = _money(raw.get("amount") or raw.get("value") or raw.get("total"))
    cat = category_id(raw.get("category") or raw.get("kind") or raw.get("type"))
    allowed_units = UNITS_BY_CATEGORY.get(cat) or ("pcs",)
    unit = str(raw.get("unit") or allowed_units[0]).strip().lower()
    if unit not in allowed_units:
        unit = allowed_units[0]
    item_id = str(raw.get("id") or "").strip() or _slug_id(None, "pi")
    qty = _qty(raw.get("qty") or raw.get("quantity") or raw.get("count"))
    size = str(raw.get("size") or raw.get("sizeText") or "").strip() or None
    note = str(raw.get("note") or raw.get("label") or "").strip() or None
    if amount <= 0 and not qty and not size and not note:
        return None
    return {
        "id": item_id[:24],
        "category": cat,
        "categoryLabel": _CAT_LABEL.get(cat, "Other"),
        "qty": qty,
        "size": size,
        "unit": unit,
        "amount": amount,
        "note": note,
        "sort": index,
    }


def normalize_package_quote(raw: Mapping[str, Any] | None, *, index: int = 0) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    items_in = raw.get("items") or raw.get("lines") or []
    items: list[dict[str, Any]] = []
    if isinstance(items_in, list):
        for i, row in enumerate(items_in[:MAX_ITEMS]):
            it = normalize_package_item(row if isinstance(row, Mapping) else None, index=i)
            if it:
                items.append(it)
    if not items:
        return None
    qid = str(raw.get("id") or "").strip() or _slug_id(None, "pq")
    split = compute_gst_split(
        sum(_money(it.get("amount")) for it in items),
        gst_mode=str(raw.get("gstMode") or raw.get("gst") or "exclude"),
        gst_percent=raw.get("gstPercent") if raw.get("gstPercent") is not None else DEFAULT_GST_PERCENT,
    )
    quote_no = str(raw.get("quotationId") or raw.get("quoteNumber") or raw.get("quoteNo") or "").strip() or None
    return {
        "id": qid[:24],
        "index": index,
        "quotationId": quote_no,
        "note": str(raw.get("note") or "").strip() or None,
        "items": items,
        "attachmentName": str(raw.get("attachmentName") or "").strip() or None,
        "attachmentKey": str(raw.get("attachmentKey") or "").strip() or None,
        **split,
    }


def normalize_package_quotes(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, row in enumerate(raw[:MAX_QUOTES]):
        q = normalize_package_quote(row if isinstance(row, Mapping) else None, index=i)
        if not q:
            continue
        if q["id"] in seen:
            q["id"] = _slug_id(None, "pq")
        seen.add(q["id"])
        out.append(q)
    for i, q in enumerate(out):
        q["index"] = i
    return out


def package_money_for_doc(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    quotes = normalize_package_quotes((doc or {}).get("packageQuotes") if isinstance(doc, Mapping) else None)
    taxable = round(sum(_money(q.get("totalTaxable")) for q in quotes), 2)
    gst_amt = round(sum(_money(q.get("gstAmount")) for q in quotes), 2)
    value = round(sum(_money(q.get("projectValue")) for q in quotes), 2)
    percents = [float(q.get("gstPercent") or 0) for q in quotes if str(q.get("gstMode")) != "off"]
    return {
        "quotes": quotes,
        "quoteCount": len(quotes),
        "totalTaxable": taxable,
        "gstAmount": gst_amt,
        "totalGst": gst_amt,
        "totalGrand": value,
        "projectValue": value,
        "gstPercent": percents[0] if len(set(round(p, 2) for p in percents)) == 1 else None,
        "gstModes": sorted({str(q.get("gstMode")) for q in quotes}),
    }


def apply_package_fields(doc: dict[str, Any], payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy package / master-job fields from a PUT/POST body onto the project doc."""
    if not isinstance(doc, dict):
        return doc
    src = payload if isinstance(payload, Mapping) else {}
    if "packageQuotes" in src and src.get("packageQuotes") is not None:
        doc["packageQuotes"] = normalize_package_quotes(src.get("packageQuotes"))
    elif isinstance(doc.get("packageQuotes"), list):
        doc["packageQuotes"] = normalize_package_quotes(doc.get("packageQuotes"))
    quotes = doc.get("packageQuotes") or []
    if quotes:
        has_lines = bool(doc.get("lines"))
        doc["quoteKind"] = "mixed" if has_lines else "package"
    if src.get("quoteKind"):
        kind = str(src.get("quoteKind") or "").strip().lower()
        if kind in {"package", "cart", "mixed", "weos"}:
            doc["quoteKind"] = kind
    mid = str(src.get("masterJobId") or doc.get("masterJobId") or doc.get("projectId") or "").strip()
    if mid:
        doc["masterJobId"] = mid
    return doc
