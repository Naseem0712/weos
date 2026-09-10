"""Canvas D2 — Quote workspace separation helpers.

Engineering Design stays on Universal Canvas. Quote Review is a separate
commercial surface built from authoritative saved project lines (SQL/FS SoT),
not from DOM or localStorage-only state.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Mapping, Sequence


def _str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def new_line_id() -> str:
    return uuid.uuid4().hex[:10]


def line_id_of(line: Mapping[str, Any] | None) -> str:
    if not isinstance(line, Mapping):
        return ""
    return _str(line.get("lineId") or line.get("id"))


def durable_preview_svg(line: Mapping[str, Any] | None) -> str:
    """Authoritative saved preview only — never invent from live form."""
    if not isinstance(line, Mapping):
        return ""
    prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
    svg = _str((prev or {}).get("svg") or (prev or {}).get("pdfSvg"))
    if svg and "<svg" in svg.lower():
        return svg
    snap = line.get("itemSnapshot") or line.get("item_snapshot")
    if isinstance(snap, Mapping):
        ps = snap.get("preview_snapshot") or snap.get("preview")
        if isinstance(ps, Mapping):
            svg2 = _str(ps.get("svg") or ps.get("pdfSvg"))
            if svg2 and "<svg" in svg2.lower():
                return svg2
        elif isinstance(ps, str) and "<svg" in ps.lower():
            return ps
    return ""


def card_warnings_for_line(line: Mapping[str, Any]) -> list[str]:
    """Soft missing-data warnings (reuse PDF preflight concepts; non-blocking)."""
    from WEOS.factory import pdf_preflight as pf

    warnings: list[str] = []
    if not line_id_of(line):
        warnings.append("Missing stable design ID")
    product = _str(line.get("product") or line.get("productId") or line.get("productType"))
    if not product:
        warnings.append("Missing product type")
    w = _num(line.get("width"))
    h = _num(line.get("height"))
    if w <= 0 or h <= 0:
        opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        has_nest = False
        for nest_key in ("railing", "shower", "ventilator", "pergola"):
            nest = opts.get(nest_key) if isinstance(opts, Mapping) else None
            if isinstance(nest, Mapping):
                has_nest = True
                break
        if not has_nest and not pf.is_manual_commercial_line(line):
            warnings.append("Missing width/height")
    qty = _num(line.get("qty") or line.get("quantity"), 0)
    if qty <= 0:
        warnings.append("Missing quantity")
    status, _detail = pf.drawing_source_status(line)
    if status == "MISSING":
        warnings.append("Drawing / preview incomplete")
    if pf.is_manual_commercial_line(line):
        for msg in pf._manual_field_issues(line):  # noqa: SLF001
            if ":" in msg:
                warnings.append(msg.split(":", 1)[-1].strip())
            else:
                warnings.append(msg)
    rate = line.get("sellingRate")
    if rate in (None, "") and not line.get("commercialTotal") and not line.get("sellingAmount"):
        selling = line.get("selling") if isinstance(line.get("selling"), Mapping) else {}
        if not (selling or {}).get("sellingRate") and not (selling or {}).get("sellingAmount"):
            warnings.append("Missing rate / amount")
    out: list[str] = []
    seen: set[str] = set()
    for wmsg in warnings:
        key = wmsg.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(wmsg)
    return out[:8]


def line_amount(line: Mapping[str, Any]) -> float:
    for key in ("commercialTotal", "sellingAmount"):
        v = line.get(key)
        if v not in (None, ""):
            return round(_num(v), 2)
    selling = line.get("selling") if isinstance(line.get("selling"), Mapping) else {}
    if selling:
        for key in ("sellingAmount", "commercialTotal", "amount"):
            if selling.get(key) not in (None, ""):
                return round(_num(selling.get(key)), 2)
    rate = _num(line.get("sellingRate") or (selling or {}).get("sellingRate"))
    qty = _num(line.get("qty") or line.get("quantity"), 1.0)
    w = _num(line.get("width"))
    h = _num(line.get("height"))
    unit = _str(line.get("saleUnit") or (selling or {}).get("saleUnit") or "sqft").lower()
    if rate > 0:
        if unit in ("sqft", "sq_ft", "sft") and w > 0 and h > 0:
            area = (w / 304.8) * (h / 304.8)
            return round(area * rate * qty, 2)
        return round(rate * qty, 2)
    return 0.0


def build_design_card(line: Mapping[str, Any], *, index: int = 0) -> dict[str, Any]:
    lid = line_id_of(line) or f"tmp-{index + 1}"
    product = _str(
        line.get("displayName")
        or line.get("productType")
        or line.get("product")
        or line.get("productId")
        or "Design"
    )
    series = _str(line.get("sectionSeries") or line.get("system") or line.get("product"))
    glass = _str(line.get("glass") or line.get("glassType"))
    colour = _str(line.get("colour") or line.get("color"))
    sale_unit = _str(line.get("saleUnit") or "sqft") or "sqft"
    rate = _num(line.get("sellingRate"))
    if rate <= 0:
        selling = line.get("selling") if isinstance(line.get("selling"), Mapping) else {}
        rate = _num((selling or {}).get("sellingRate"))
    amount = line_amount(line)
    svg = durable_preview_svg(line)
    warnings = card_warnings_for_line(line)
    status = "ready" if not warnings else "needs_data"
    if warnings and any("drawing" in w.lower() or "preview" in w.lower() for w in warnings):
        status = "incomplete_drawing"
    qg = ""
    opts = line.get("options")
    if isinstance(opts, Mapping):
        qg = _str(opts.get("quoteGroup"))
    if not qg:
        qg = _str(line.get("quoteGroup")) or "Main"
    return {
        "designId": lid,
        "lineId": lid,
        "index": index + 1,
        "productType": _str(line.get("productType") or line.get("category")),
        "product": _str(line.get("product") or line.get("productId")),
        "displayName": product,
        "widthMm": _num(line.get("width")),
        "heightMm": _num(line.get("height")),
        "qty": _num(line.get("qty") or line.get("quantity"), 1.0),
        "floor": _str(line.get("locationName") or line.get("floor") or line.get("floorName")),
        "location": _str(line.get("positionName") or line.get("location") or line.get("mark")),
        "mark": _str(line.get("mark") or line.get("displayCode") or line.get("code")),
        "series": series,
        "glass": glass,
        "colour": colour,
        "saleUnit": sale_unit,
        "sellingRate": rate,
        "amount": amount,
        "status": status,
        "warnings": warnings,
        "previewSvg": svg,
        "hasDurablePreview": bool(svg),
        "quoteGroup": qg,
        "itemKind": (
            "MANUAL"
            if _str(line.get("itemKind")).upper() in ("MANUAL", "COMMERCIAL_MANUAL")
            else "ENGINEERED"
        ),
    }


def build_quote_totals(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """Subtotal / Discount / Taxable / GST / Grand from existing money calc."""
    from WEOS.factory.project_store import live_quote_money

    money = live_quote_money(doc if isinstance(doc, Mapping) else {})
    taxable = float(money.get("totalTaxable") or 0)
    gst = float(money.get("totalGst") or 0)
    grand = float(money.get("totalGrand") or 0)
    discount = float(money.get("discountAmount") or 0)
    subtotal = round(taxable + discount, 2) if discount > 0 else taxable
    lines = [ln for ln in ((doc or {}).get("lines") or []) if isinstance(ln, Mapping)]
    return {
        "itemCount": len(lines),
        "subtotal": subtotal,
        "discount": discount,
        "discountMode": money.get("discountMode") or "off",
        "taxable": taxable,
        "gst": gst,
        "gstPercent": money.get("gstPercent"),
        "grand": grand,
        "currency": "INR",
    }


def build_active_quote_context(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(doc, Mapping) or not doc.get("projectId"):
        return {
            "hasActiveQuote": False,
            "projectId": None,
            "quotationId": None,
            "name": None,
            "customer": None,
            "status": None,
            "itemCount": 0,
            "amount": 0.0,
        }
    totals = build_quote_totals(doc)
    return {
        "hasActiveQuote": True,
        "projectId": _str(doc.get("projectId")),
        "quotationId": _str(doc.get("quotationId")),
        "name": _str(doc.get("name") or "WEOS Project"),
        "customer": _str(doc.get("customer")),
        "customerMobile": _str(doc.get("customerMobile")),
        "status": _str(doc.get("status") or "draft"),
        "itemCount": totals["itemCount"],
        "amount": totals["grand"],
        "totals": totals,
    }


def build_quote_workspace(doc: Mapping[str, Any]) -> dict[str, Any]:
    lines = [ln for ln in (doc.get("lines") or []) if isinstance(ln, Mapping)]
    cards = [build_design_card(ln, index=i) for i, ln in enumerate(lines)]
    return {
        "ok": True,
        "batch": "CANVAS-D2",
        "context": build_active_quote_context(doc),
        "cards": cards,
        "totals": build_quote_totals(doc),
        "projectId": _str(doc.get("projectId")),
        "quotationId": _str(doc.get("quotationId")),
        "name": _str(doc.get("name")),
        "customer": _str(doc.get("customer")),
        "status": _str(doc.get("status") or "draft"),
    }


def _clear_preview_for_regen(line: dict[str, Any]) -> None:
    """Force regeneration at new dims — do not raw-clone SVG."""
    if "preview" in line:
        prev = line.get("preview")
        if isinstance(prev, dict):
            line["preview"] = {"key": "", "svg": "", "stale": True, "needsRegen": True}
        else:
            line["preview"] = None
    snap = line.get("itemSnapshot") or line.get("item_snapshot")
    if isinstance(snap, dict):
        snap = dict(snap)
        for k in ("preview_snapshot", "preview", "svg"):
            if k in snap:
                snap[k] = None
        line["itemSnapshot"] = snap
        if "item_snapshot" in line:
            line["item_snapshot"] = snap


def duplicate_design_rows(
    doc: Mapping[str, Any],
    *,
    source_line_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create real new lineIds / quote items from a source design."""
    if not isinstance(doc, Mapping) or not doc.get("projectId"):
        raise ValueError("Project document required")
    src_id = _str(source_line_id)
    if not src_id:
        raise ValueError("source_line_id required")
    lines = [ln for ln in (doc.get("lines") or []) if isinstance(ln, Mapping)]
    source = None
    for ln in lines:
        if line_id_of(ln) == src_id:
            source = ln
            break
    if source is None:
        raise ValueError(f"Source design not found: {src_id}")
    if not rows:
        raise ValueError("At least one duplicate row required")

    created: list[dict[str, Any]] = []
    new_lines = [dict(ln) for ln in lines]
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        clone = copy.deepcopy(dict(source))
        new_id = new_line_id()
        while any(line_id_of(ln) == new_id for ln in new_lines):
            new_id = new_line_id()
        clone["lineId"] = new_id
        if "id" in clone:
            clone["id"] = new_id
        if row.get("width") is not None or row.get("widthMm") is not None:
            clone["width"] = _num(row.get("widthMm", row.get("width")), _num(clone.get("width")))
        if row.get("height") is not None or row.get("heightMm") is not None:
            clone["height"] = _num(row.get("heightMm", row.get("height")), _num(clone.get("height")))
        if row.get("qty") is not None or row.get("quantity") is not None:
            clone["qty"] = _num(row.get("qty", row.get("quantity")), 1.0)
        if row.get("floor") is not None or row.get("locationName") is not None:
            clone["locationName"] = _str(row.get("floor", row.get("locationName")))
        if row.get("location") is not None or row.get("positionName") is not None:
            clone["positionName"] = _str(row.get("location", row.get("positionName")))
        if row.get("mark") is not None:
            clone["mark"] = _str(row.get("mark"))
        if row.get("sellingRate") is not None or row.get("rate") is not None:
            clone["sellingRate"] = _num(row.get("sellingRate", row.get("rate")))
        if isinstance(clone.get("itemSnapshot"), dict):
            snap = dict(clone["itemSnapshot"])
            snap["quote_item_id"] = new_id
            clone["itemSnapshot"] = snap
        _clear_preview_for_regen(clone)
        opts = clone.get("options")
        if isinstance(opts, dict):
            opts = dict(opts)
            for nest_key in ("railing", "shower", "ventilator", "pergola"):
                nest = opts.get(nest_key)
                if not isinstance(nest, dict):
                    continue
                nest = dict(nest)
                if "widthMm" in nest or "width" in nest:
                    nest["widthMm"] = clone["width"]
                    nest["width"] = clone["width"]
                if "heightMm" in nest or "height" in nest:
                    nest["heightMm"] = clone["height"]
                    nest["height"] = clone["height"]
                if nest_key == "pergola":
                    if "lengthMm" in nest:
                        nest["lengthMm"] = clone["width"]
                    if "depthMm" in nest:
                        nest["depthMm"] = clone["height"]
                opts[nest_key] = nest
            clone["options"] = opts
        new_lines.append(clone)
        created.append(build_design_card(clone, index=len(new_lines) - 1))

    out_doc = dict(doc)
    out_doc["lines"] = new_lines
    return {
        "ok": True,
        "batch": "CANVAS-D2",
        "sourceLineId": src_id,
        "createdCount": len(created),
        "created": created,
        "createdLineIds": [c["lineId"] for c in created],
        "doc": out_doc,
        "workspace": build_quote_workspace(out_doc),
    }


def find_active_draft(
    projects: Sequence[Mapping[str, Any]] | None,
    *,
    prefer_project_id: str | None = None,
) -> dict[str, Any] | None:
    """Pick restore candidate: preferred id, else newest draft."""
    items = [p for p in (projects or []) if isinstance(p, Mapping) and p.get("projectId")]
    if not items:
        return None
    pref = _str(prefer_project_id)
    if pref:
        for p in items:
            if _str(p.get("projectId")) == pref:
                return dict(p)
    drafts = [
        p
        for p in items
        if _str(p.get("status") or "draft").lower() in ("draft", "active", "")
    ]
    pool = drafts or items

    def _key(p: Mapping[str, Any]) -> str:
        return _str(p.get("updatedAt") or p.get("createdAt") or "")

    pool_sorted = sorted(pool, key=_key, reverse=True)
    return dict(pool_sorted[0]) if pool_sorted else None


def app_entry_plan(
    *,
    logged_in: bool,
    active_draft: Mapping[str, Any] | None = None,
    session_project_id: str | None = None,
) -> dict[str, Any]:
    """Login → restore draft OR New Quote / Quote Setup. No silent commercial create."""
    if not logged_in:
        return {
            "action": "login",
            "view": "company",
            "createQuote": False,
            "message": "Company login required",
        }
    draft = active_draft if isinstance(active_draft, Mapping) else None
    if draft and draft.get("projectId"):
        return {
            "action": "restore_draft",
            "view": "quote_home",
            "projectId": _str(draft.get("projectId")),
            "quotationId": _str(draft.get("quotationId")),
            "name": _str(draft.get("name")),
            "customer": _str(draft.get("customer")),
            "createQuote": False,
            "message": "Active draft available — restore or start New Quote",
        }
    if session_project_id:
        return {
            "action": "restore_session",
            "view": "quote_home",
            "projectId": _str(session_project_id),
            "createQuote": False,
            "message": "Session project available",
        }
    return {
        "action": "new_quote_setup",
        "view": "setup",
        "createQuote": False,
        "message": "No active draft — open New Quote / Quote Setup before adding products",
    }
