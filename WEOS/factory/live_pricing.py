"""Live commercial pricing — cost from engines + customer selling rate.

Sale units (non-technical labels):
  sqft     — rate × area(sqft) × qty   (default for windows; MAR-QT style)
  sqm      — rate × area(m²) × qty
  opening  — rate × qty               (per window/door)
  rft      — rate × perimeter(ft) × qty
"""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory.product_loader import load_product

SALE_UNITS: dict[str, dict[str, str]] = {
    "sqft": {"label": "Per Sq.Ft.", "short": "₹/sft"},
    "sqm": {"label": "Per Sq.M.", "short": "₹/m²"},
    "opening": {"label": "Per Opening", "short": "₹/nos"},
    "rft": {"label": "Per Running Ft", "short": "₹/rft"},
    "rmt": {"label": "Per Running M", "short": "₹/rmt"},
    "pc": {"label": "Per Piece", "short": "₹/pc"},
}


def area_metrics(width_mm: float, height_mm: float) -> dict[str, float]:
    w = max(float(width_mm or 0), 0.0)
    h = max(float(height_mm or 0), 0.0)
    area_sqm = (w * h) / 1_000_000.0
    area_sqft = area_sqm * 10.7639
    peri_mm = 2.0 * (w + h)
    peri_ft = peri_mm / 304.8
    peri_m = peri_mm / 1000.0
    return {
        "widthMm": w,
        "heightMm": h,
        "areaSqm": round(area_sqm, 4),
        "areaSqft": round(area_sqft, 3),
        "perimeterMm": round(peri_mm, 1),
        "perimeterFt": round(peri_ft, 3),
        "perimeterM": round(peri_m, 3),
    }


def default_sale_unit(product: Mapping[str, Any] | None = None) -> str:
    if not product:
        return "sqft"
    specs = product.get("specifications") or {}
    q = product.get("quotation") or {}
    raw = (
        q.get("saleUnit")
        or specs.get("saleUnit")
        or product.get("saleUnit")
        or "sqft"
    )
    key = str(raw).lower().strip()
    aliases = {
        "sft": "sqft",
        "sq.ft": "sqft",
        "sq.ft.": "sqft",
        "per_sft": "sqft",
        "per_sqft": "sqft",
        "m2": "sqm",
        "m²": "sqm",
        "nos": "opening",
        "pcs": "opening",
        "pc": "pc",
        "each": "opening",
        "running_ft": "rft",
        "rft": "rft",
        "rmt": "rmt",
        "running_m": "rmt",
    }
    return aliases.get(key, key if key in SALE_UNITS else "sqft")


def sell_amount(
    *,
    width_mm: float,
    height_mm: float,
    qty: int,
    selling_rate: float,
    sale_unit: str = "sqft",
) -> dict[str, Any]:
    metrics = area_metrics(width_mm, height_mm)
    q = max(int(qty or 1), 1)
    rate = float(selling_rate or 0)
    unit = (sale_unit or "sqft").lower()
    if unit not in SALE_UNITS:
        unit = "sqft"

    if unit == "sqft":
        billable = metrics["areaSqft"] * q
    elif unit == "sqm":
        billable = metrics["areaSqm"] * q
    elif unit == "rft":
        billable = metrics["perimeterFt"] * q
    elif unit == "rmt":
        billable = metrics["perimeterM"] * q
    elif unit == "pc":
        billable = float(q)
    else:  # opening
        billable = float(q)

    from WEOS.factory.fmt import money_n

    amount = money_n(billable * rate)
    return {
        "saleUnit": unit,
        "saleUnitLabel": SALE_UNITS[unit]["label"],
        "sellingRate": money_n(rate),
        "billableQty": round(billable, 4),
        "sellingAmount": amount,
        **metrics,
        "qty": q,
    }


def live_price(line: Mapping[str, Any]) -> dict[str, Any]:
    """Reactive quote preview: factory cost + optional customer selling amount."""
    from WEOS.factory.project_engine import calculate_line
    from WEOS.factory.product_loader import load_product

    product_id = str(line.get("product") or line.get("productId") or "29mm_sliding")
    product = load_product(product_id, strict=False)
    width = float(line.get("width") or 0)
    height = float(line.get("height") or 0)
    qty = int(line.get("qty") or line.get("quantity") or 1)

    payload = dict(line) if isinstance(line, Mapping) else {}
    payload.setdefault("product", product_id)
    payload.setdefault("width", width)
    payload.setdefault("height", height)
    payload.setdefault("qty", qty)
    payload.setdefault("glass", line.get("glass") or "5mm_clear")
    payload.setdefault("colour", line.get("colour") or "white")
    payload.setdefault("handle", line.get("handle") or "standard")
    calc = calculate_line(payload, include_preview=False)

    from WEOS.factory.line_kind import is_railing_cart_line, is_shower_cart_line, is_ventilator_cart_line

    special = (
        is_railing_cart_line(payload) or is_railing_cart_line(calc)
        or is_shower_cart_line(payload) or is_shower_cart_line(calc)
        or is_ventilator_cart_line(payload) or is_ventilator_cart_line(calc)
    )

    cost_total = float((calc.get("price") or {}).get("total") or 0)
    cost_unit = float((calc.get("price") or {}).get("unitTotal") or (cost_total / max(qty, 1)))
    sale_unit = str(line.get("saleUnit") or calc.get("saleUnit") or default_sale_unit(product))
    selling_rate = line.get("sellingRate")
    if selling_rate is None or selling_rate == "":
        selling_rate = line.get("customerRate") or calc.get("sellingRate")
    has_sell = selling_rate is not None and str(selling_rate).strip() != ""
    sell = None
    if special and isinstance(calc.get("selling"), Mapping) and (calc.get("selling") or {}).get("sellingAmount"):
        sell = dict(calc["selling"])
        sale_unit = str(sell.get("saleUnit") or sale_unit)
    elif has_sell:
        if special and (is_railing_cart_line(payload) or is_railing_cart_line(calc)):
            # Running-ft along length, not window perimeter.
            unit = (sale_unit or "rft").lower()
            length = float(calc.get("width") or width or 0)
            if unit == "rmt":
                billable = (length / 1000.0) * max(qty, 1)
            elif unit in ("opening", "pc", "nos"):
                billable = float(max(qty, 1))
            else:
                billable = (length / 304.8) * max(qty, 1)
            from WEOS.factory.fmt import money_n

            sell = {
                "saleUnit": unit if unit in SALE_UNITS else "rft",
                "saleUnitLabel": SALE_UNITS.get(unit, SALE_UNITS["rft"])["label"],
                "sellingRate": money_n(float(selling_rate)),
                "billableQty": round(billable, 4),
                "sellingAmount": money_n(billable * float(selling_rate)),
                "qty": max(qty, 1),
            }
        else:
            sell = sell_amount(
                width_mm=width,
                height_mm=height,
                qty=qty,
                selling_rate=float(selling_rate),
                sale_unit=sale_unit,
            )

    metrics = area_metrics(width, height)
    margin = None
    if sell:
        margin = {
            "sellingAmount": sell["sellingAmount"],
            "costAmount": round(cost_total, 2),
            "marginAmount": round(sell["sellingAmount"] - cost_total, 2),
            "marginPercent": round(
                ((sell["sellingAmount"] - cost_total) / sell["sellingAmount"] * 100.0)
                if sell["sellingAmount"]
                else 0.0,
                1,
            ),
        }

    section_series = line.get("sectionSeries")
    section_specs = {}
    if section_series:
        try:
            from WEOS.factory.section_catalogue import specs_summary_for_series

            section_specs = specs_summary_for_series(str(section_series))
        except Exception:
            section_specs = {}

    return {
        "product": product_id,
        "displayName": calc.get("displayName") or product.get("displayName"),
        "width": width,
        "height": height,
        "qty": qty,
        "metrics": metrics,
        "saleUnits": SALE_UNITS,
        "saleUnit": sale_unit,
        "saleUnitLabel": SALE_UNITS.get(sale_unit, SALE_UNITS["sqft"])["label"],
        "cost": {
            "currency": (calc.get("price") or {}).get("currency", "INR"),
            "unitTotal": round(cost_unit, 2),
            "total": round(cost_total, 2),
            "status": calc.get("status"),
        },
        "selling": sell,
        "margin": margin,
        "sectionSeries": section_series,
        "sectionSpecs": section_specs,
        "description": line.get("description")
        or calc.get("displayName")
        or product.get("displayName"),
        "options": calc.get("options") or {},
        "weight": calc.get("weight"),
        "preview": calc.get("preview"),
        "lineCalc": {
            "price": calc.get("price"),
            "glass": calc.get("glass"),
            "cutList": calc.get("cutList"),
        },
    }


def apply_selling_to_line_result(result: dict[str, Any], line: Mapping[str, Any]) -> dict[str, Any]:
    """Attach commercial selling fields onto a calculate_line result."""
    from WEOS.factory.line_kind import is_railing_cart_line, is_shower_cart_line

    # Railing / shower lines already carry commercial totals from the designer — do not
    # attach window sectionSpecs / series metadata or reprice via sqft sell_amount.
    if (
        is_railing_cart_line(result) or is_railing_cart_line(line)
        or is_shower_cart_line(result) or is_shower_cart_line(line)
    ):
        out = dict(result)
        out.setdefault("sectionSeries", None)
        out.setdefault("sectionSpecs", {})
        out.setdefault("sectionDetails", [])
        out.setdefault("specifications", {})
        out.setdefault("layout", {})
        return out

    product = load_product(str(result.get("product") or line.get("product") or ""), strict=False)
    sale_unit = str(line.get("saleUnit") or default_sale_unit(product))
    selling_rate = line.get("sellingRate")
    out = dict(result)
    out["saleUnit"] = sale_unit
    out["description"] = line.get("description") or result.get("displayName")
    out["sectionSeries"] = line.get("sectionSeries")
    out["terms"] = line.get("terms")
    if line.get("sectionSeries"):
        try:
            from WEOS.factory.section_catalogue import specs_summary_for_series

            out["sectionSpecs"] = specs_summary_for_series(str(line.get("sectionSeries")))
        except Exception:
            out["sectionSpecs"] = {}
    if selling_rate is not None and str(selling_rate).strip() != "":
        sell = sell_amount(
            width_mm=float(result.get("width") or 0),
            height_mm=float(result.get("height") or 0),
            qty=int(result.get("qty") or 1),
            selling_rate=float(selling_rate),
            sale_unit=sale_unit,
        )
        out["sellingRate"] = sell["sellingRate"]
        out["selling"] = sell
        cost = float((result.get("price") or {}).get("total") or 0)
        out["commercialTotal"] = sell["sellingAmount"]
        out["margin"] = {
            "sellingAmount": sell["sellingAmount"],
            "costAmount": round(cost, 2),
            "marginAmount": round(sell["sellingAmount"] - cost, 2),
            "marginPercent": round(
                ((sell["sellingAmount"] - cost) / sell["sellingAmount"] * 100.0)
                if sell["sellingAmount"]
                else 0.0,
                1,
            ),
        }
    else:
        out["sellingRate"] = None
        out["selling"] = None
        out["commercialTotal"] = (result.get("price") or {}).get("total")
    return out
