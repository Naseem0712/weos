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


def rates_dir() -> Path:
    d = data_dir() / "customer_rates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def customer_path(customer: str) -> Path:
    return rates_dir() / f"{_slug(customer)}.json"


def load_customer_rates(customer: str) -> dict[str, Any]:
    if not (customer or "").strip():
        return {"customer": "", "rates": [], "updatedAt": None}
    path = customer_path(customer)
    if not path.is_file():
        return {"customer": customer.strip(), "rates": [], "updatedAt": None}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_customer_rate(
    customer: str,
    *,
    product: str,
    selling_rate: float,
    sale_unit: str = "sqft",
    section_series: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    cust = (customer or "").strip() or "Walk-in"
    doc = load_customer_rates(cust)
    doc["customer"] = cust
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
    path = customer_path(cust)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def lookup_rate(
    customer: str,
    product: str,
    *,
    sale_unit: str | None = None,
    section_series: str | None = None,
) -> dict[str, Any] | None:
    doc = load_customer_rates(customer)
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


def list_customers_with_rates() -> list[dict[str, Any]]:
    out = []
    for path in sorted(rates_dir().glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        out.append(
            {
                "customer": doc.get("customer") or path.stem,
                "rateCount": len(doc.get("rates") or []),
                "updatedAt": doc.get("updatedAt"),
            }
        )
    return out


def save_quote_line_rates(
    customer: str,
    lines: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Persist selling rates from saved quote lines for that customer."""
    saved = 0
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
        )
        saved += 1
    return {"customer": customer, "saved": saved, "doc": load_customer_rates(customer)}
