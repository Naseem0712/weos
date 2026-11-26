"""Customer-specific selling rates — persisted JSON (not hardcoded in Python)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import data_dir


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "default").strip().lower()).strip("_")
    return s or "default"


def _norm_gst(company_gst: str | None) -> str:
    try:
        from WEOS.factory.company_store import normalise_gstin

        return normalise_gstin(company_gst) or ""
    except Exception:
        return re.sub(r"[^A-Za-z0-9]", "", str(company_gst or "")).upper()


def rates_dir(company_gst: str | None = None) -> Path:
    d = data_dir() / "customer_rates"
    gst = _norm_gst(company_gst)
    if gst:
        d = d / gst
    d.mkdir(parents=True, exist_ok=True)
    return d


def customer_path(customer: str, company_gst: str | None = None) -> Path:
    return rates_dir(company_gst) / f"{_slug(customer)}.json"


def load_customer_rates(customer: str, *, company_gst: str | None = None) -> dict[str, Any]:
    if not (customer or "").strip():
        return {"customer": "", "rates": [], "updatedAt": None, "companyGst": _norm_gst(company_gst)}
    gst = _norm_gst(company_gst)
    path = customer_path(customer, gst or None)
    # Fall back to legacy unscoped file only when reading for a logged-in GST
    # that has no scoped rates yet (do not write back into the shared file).
    if not path.is_file() and gst:
        legacy = rates_dir(None) / f"{_slug(customer)}.json"
        if legacy.is_file():
            try:
                doc = json.loads(legacy.read_text(encoding="utf-8-sig"))
                if not _norm_gst(doc.get("companyGst")) or _norm_gst(doc.get("companyGst")) == gst:
                    doc = dict(doc)
                    doc["companyGst"] = gst
                    return doc
            except Exception:
                pass
    if not path.is_file():
        return {"customer": customer.strip(), "rates": [], "updatedAt": None, "companyGst": gst}
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    if gst:
        doc["companyGst"] = gst
    return doc


def save_customer_rate(
    customer: str,
    *,
    product: str,
    selling_rate: float,
    sale_unit: str = "sqft",
    section_series: str | None = None,
    notes: str | None = None,
    company_gst: str | None = None,
) -> dict[str, Any]:
    cust = (customer or "").strip() or "Walk-in"
    gst = _norm_gst(company_gst)
    doc = load_customer_rates(cust, company_gst=gst or None)
    doc["customer"] = cust
    if gst:
        doc["companyGst"] = gst
    rates = list(doc.get("rates") or [])
    now = datetime.now(timezone.utc).isoformat()
    key_match = None
    for i, row in enumerate(rates):
        if (
            str(row.get("product")) == str(product)
            and str(row.get("saleUnit") or "sqft") == str(sale_unit or "sqft")
            and str(row.get("sectionSeries") or "") == str(section_series or "")
        ):
            key_match = i
            break
    entry = {
        "product": product,
        "saleUnit": sale_unit or "sqft",
        "sellingRate": float(selling_rate),
        "sectionSeries": section_series,
        "notes": notes,
        "updatedAt": now,
    }
    if key_match is None:
        rates.append(entry)
    else:
        rates[key_match] = {**rates[key_match], **entry}
    doc["rates"] = rates
    doc["updatedAt"] = now
    path = customer_path(cust, gst or None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def lookup_rate(
    customer: str,
    product: str,
    *,
    sale_unit: str | None = None,
    section_series: str | None = None,
    company_gst: str | None = None,
) -> dict[str, Any] | None:
    doc = load_customer_rates(customer, company_gst=company_gst)
    candidates = [
        r
        for r in (doc.get("rates") or [])
        if str(r.get("product")) == str(product)
    ]
    if sale_unit:
        narrowed = [r for r in candidates if str(r.get("saleUnit") or "sqft") == str(sale_unit)]
        if narrowed:
            candidates = narrowed
    if section_series:
        narrowed = [
            r for r in candidates if str(r.get("sectionSeries") or "") == str(section_series)
        ]
        if narrowed:
            candidates = narrowed
    if not candidates:
        return None
    # most recently updated
    candidates.sort(key=lambda r: str(r.get("updatedAt") or ""), reverse=True)
    return candidates[0]


def list_customers_with_rates(*, company_gst: str | None = None) -> list[dict[str, Any]]:
    out = []
    gst = _norm_gst(company_gst)
    root = rates_dir(gst or None)
    for path in sorted(root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        row_gst = _norm_gst(doc.get("companyGst"))
        if gst and row_gst and row_gst != gst:
            continue
        out.append(
            {
                "customer": doc.get("customer") or path.stem,
                "rateCount": len(doc.get("rates") or []),
                "updatedAt": doc.get("updatedAt"),
                "companyGst": row_gst or gst,
            }
        )
    return out


def save_quote_line_rates(
    customer: str,
    lines: list[Mapping[str, Any]],
    *,
    company_gst: str | None = None,
) -> dict[str, Any]:
    """Persist selling rates from saved quote lines for that customer."""
    saved = 0
    gst = _norm_gst(company_gst)
    for ln in lines:
        rate = ln.get("sellingRate")
        if rate is None or str(rate).strip() == "":
            continue
        save_customer_rate(
            customer,
            product=str(ln.get("product") or ln.get("productId") or ""),
            selling_rate=float(rate),
            sale_unit=str(ln.get("saleUnit") or "sqft"),
            section_series=ln.get("sectionSeries"),
            notes=ln.get("description"),
            company_gst=gst or None,
        )
        saved += 1
    return {"customer": customer, "saved": saved, "doc": load_customer_rates(customer, company_gst=gst or None)}
