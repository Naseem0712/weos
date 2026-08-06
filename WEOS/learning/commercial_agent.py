"""Commercial learning agent — observes quotes for future automation.

Persists observations under knowledge_base/commercial/ (JSONL + insights cache).
Does NOT auto-write engineering profile rules — commercial patterns only.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from WEOS.paths import knowledge_base_dir
from WEOS.learning.knowledge_base import ensure_kb_dirs


def commercial_dir() -> Path:
    ensure_kb_dirs()
    d = knowledge_base_dir() / "commercial"
    d.mkdir(parents=True, exist_ok=True)
    (d / "observations").mkdir(parents=True, exist_ok=True)
    return d


def observations_path() -> Path:
    return commercial_dir() / "observations.jsonl"


def insights_cache_path() -> Path:
    return commercial_dir() / "insights_cache.json"


def observe_quote(
    *,
    customer: str | None,
    project_id: str | None,
    quotation_id: str | None,
    lines: Sequence[Mapping[str, Any]],
    terms: str | None = None,
    source: str = "quote_save",
) -> dict[str, Any]:
    """Record one observation per line (+ optional terms blob)."""
    commercial_dir()
    now = datetime.now(timezone.utc).isoformat()
    batch_id = uuid.uuid4().hex[:10]
    rows: list[dict[str, Any]] = []

    for ln in lines or []:
        price = ln.get("price") or {}
        selling = ln.get("selling") or {}
        cost = float(price.get("total") or 0)
        sell_amt = selling.get("sellingAmount")
        if sell_amt is None:
            sell_amt = ln.get("commercialTotal")
        rate = ln.get("sellingRate")
        if rate is None and selling:
            rate = selling.get("sellingRate")
        row = {
            "id": f"obs_{uuid.uuid4().hex[:12]}",
            "batchId": batch_id,
            "ts": now,
            "source": source,
            "customer": (customer or "").strip() or None,
            "projectId": project_id,
            "quotationId": quotation_id,
            "product": ln.get("product") or ln.get("productId"),
            "displayName": ln.get("displayName"),
            "description": ln.get("description") or ln.get("displayName"),
            "sectionSeries": ln.get("sectionSeries"),
            "width": ln.get("width"),
            "height": ln.get("height"),
            "qty": ln.get("qty"),
            "saleUnit": ln.get("saleUnit") or (selling.get("saleUnit") if selling else "sqft"),
            "sellingRate": rate,
            "sellingAmount": sell_amt,
            "costAmount": cost,
            "marginAmount": (float(sell_amt) - cost) if sell_amt is not None else None,
            "options": ln.get("options"),
            "glass": (ln.get("options") or {}).get("glass") if isinstance(ln.get("options"), dict) else ln.get("glass"),
            "colour": (ln.get("options") or {}).get("colour") if isinstance(ln.get("options"), dict) else ln.get("colour"),
            "terms": terms or ln.get("terms"),
        }
        rows.append(row)

    if terms and not any(r.get("terms") for r in rows):
        rows.append(
            {
                "id": f"obs_{uuid.uuid4().hex[:12]}",
                "batchId": batch_id,
                "ts": now,
                "source": source,
                "customer": (customer or "").strip() or None,
                "projectId": project_id,
                "quotationId": quotation_id,
                "kind": "terms_only",
                "terms": terms,
            }
        )

    path = observations_path()
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Invalidate cache
    cache = insights_cache_path()
    if cache.is_file():
        cache.unlink()

    return {"ok": True, "batchId": batch_id, "observed": len(rows)}


def _read_observations(limit: int = 500) -> list[dict[str, Any]]:
    path = observations_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


def agent_insights(
    *,
    customer: str | None = None,
    product: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Simple non-technical insights for the dashboard agent panel."""
    rows = _read_observations(limit=800)
    if customer:
        c = customer.strip().lower()
        rows = [r for r in rows if str(r.get("customer") or "").lower() == c]
    if product:
        rows = [r for r in rows if str(r.get("product") or "") == product]
    rows = rows[-limit:]

    rate_by_product: dict[str, list[float]] = defaultdict(list)
    margins: list[float] = []
    terms_count: dict[str, int] = defaultdict(int)
    desc_count: dict[str, int] = defaultdict(int)
    size_patterns: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []

    for r in reversed(rows):
        if r.get("kind") == "terms_only":
            t = (r.get("terms") or "").strip()
            if t:
                terms_count[t[:180]] += 1
            continue
        prod = str(r.get("product") or "unknown")
        if r.get("sellingRate") is not None:
            try:
                rate_by_product[prod].append(float(r["sellingRate"]))
            except (TypeError, ValueError):
                pass
        if r.get("marginAmount") is not None and r.get("sellingAmount"):
            try:
                sell = float(r["sellingAmount"])
                if sell:
                    margins.append(float(r["marginAmount"]) / sell * 100.0)
            except (TypeError, ValueError):
                pass
        desc = (r.get("description") or "").strip()
        if desc:
            desc_count[desc[:120]] += 1
        t = (r.get("terms") or "").strip()
        if t:
            terms_count[t[:180]] += 1
        if len(size_patterns) < 12 and r.get("width") and r.get("height"):
            size_patterns.append(
                {
                    "product": prod,
                    "size": f"{r.get('width')}×{r.get('height')}",
                    "qty": r.get("qty"),
                    "sellingRate": r.get("sellingRate"),
                    "saleUnit": r.get("saleUnit"),
                    "customer": r.get("customer"),
                }
            )
        if len(recent) < 8:
            recent.append(
                {
                    "ts": r.get("ts"),
                    "customer": r.get("customer"),
                    "product": prod,
                    "displayName": r.get("displayName"),
                    "sellingRate": r.get("sellingRate"),
                    "saleUnit": r.get("saleUnit"),
                    "costAmount": r.get("costAmount"),
                    "sellingAmount": r.get("sellingAmount"),
                    "marginAmount": r.get("marginAmount"),
                }
            )

    suggested_rates = []
    for prod, rates in sorted(rate_by_product.items()):
        if not rates:
            continue
        rates_sorted = sorted(rates)
        mid = rates_sorted[len(rates_sorted) // 2]
        suggested_rates.append(
            {
                "product": prod,
                "samples": len(rates),
                "avgRate": round(sum(rates) / len(rates), 2),
                "medianRate": round(mid, 2),
                "minRate": round(min(rates), 2),
                "maxRate": round(max(rates), 2),
            }
        )

    top_terms = sorted(terms_count.items(), key=lambda x: -x[1])[:5]
    top_desc = sorted(desc_count.items(), key=lambda x: -x[1])[:5]
    avg_margin = round(sum(margins) / len(margins), 1) if margins else None

    tips = []
    if suggested_rates:
        best = suggested_rates[0]
        tips.append(
            f"Typical sell rate for {best['product']}: ₹{best['medianRate']} "
            f"(median of {best['samples']} quotes)."
        )
    if avg_margin is not None:
        tips.append(f"Average margin on observed quotes: {avg_margin}%.")
    if top_terms:
        tips.append("Common terms are remembered for faster quote fill.")
    if not tips:
        tips.append("Save quotes with selling rates — I’ll learn patterns for this customer.")

    result = {
        "ok": True,
        "customer": customer,
        "product": product,
        "observationCount": len(rows),
        "message": tips[0] if tips else "Watching your quotes…",
        "tips": tips,
        "suggestedRates": suggested_rates,
        "avgMarginPercent": avg_margin,
        "commonTerms": [{"text": t, "count": c} for t, c in top_terms],
        "commonDescriptions": [{"text": d, "count": c} for d, c in top_desc],
        "recentSizes": size_patterns,
        "recent": recent,
        "status": "learning" if rows else "waiting",
    }
    insights_cache_path().write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def agent_status() -> dict[str, Any]:
    rows = _read_observations(limit=50)
    return {
        "name": "Quote Learning Agent",
        "status": "learning" if rows else "waiting",
        "observationCount": len(_read_observations(limit=5000)),
        "lastObservation": rows[-1] if rows else None,
        "blurb": "I watch products, sizes, selling rates, cost, terms & descriptions you use — so WEOS can suggest quotes later.",
    }
