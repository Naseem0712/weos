"""Commercial learning agent + Commercial Intelligence Platform.

Observes quotes; builds customer / architect / dealer / vendor / seasonal / margin
profiles and product upsell recommendations.

Customer Memory: preferred commercial settings with one-click apply (explicit user accept).
Engineering production data is NEVER auto-modified from this module.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter, defaultdict
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
    (d / "profiles").mkdir(parents=True, exist_ok=True)
    (d / "customer_memory").mkdir(parents=True, exist_ok=True)
    return d


def observations_path() -> Path:
    return commercial_dir() / "observations.jsonl"


def insights_cache_path() -> Path:
    return commercial_dir() / "insights_cache.json"


def intel_cache_path() -> Path:
    return commercial_dir() / "intelligence_cache.json"


def customer_memory_path(customer: str) -> Path:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (customer or "walkin").strip().lower()).strip("_") or "walkin"
    return commercial_dir() / "customer_memory" / f"{slug}.json"


def observe_quote(
    *,
    customer: str | None,
    project_id: str | None,
    quotation_id: str | None,
    lines: Sequence[Mapping[str, Any]],
    terms: str | None = None,
    source: str = "quote_save",
    architect: str | None = None,
    dealer: str | None = None,
    vendor: str | None = None,
    discount_percent: float | None = None,
    payment_term: str | None = None,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one observation per line (+ optional terms blob)."""
    commercial_dir()
    now = datetime.now(timezone.utc).isoformat()
    batch_id = uuid.uuid4().hex[:10]
    rows: list[dict[str, Any]] = []
    meta = dict(meta or {})

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
        disc = discount_percent
        if disc is None:
            disc = ln.get("discountPercent") or meta.get("discountPercent")
        row = {
            "id": f"obs_{uuid.uuid4().hex[:12]}",
            "batchId": batch_id,
            "ts": now,
            "source": source,
            "customer": (customer or "").strip() or None,
            "architect": (architect or meta.get("architect") or ln.get("architect") or "").strip() or None,
            "dealer": (dealer or meta.get("dealer") or ln.get("dealer") or "").strip() or None,
            "vendor": (vendor or meta.get("vendor") or ln.get("vendor") or "").strip() or None,
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
            "discountPercent": disc,
            "paymentTerm": payment_term or meta.get("paymentTerm") or ln.get("paymentTerm"),
            "options": ln.get("options"),
            "glass": (ln.get("options") or {}).get("glass") if isinstance(ln.get("options"), dict) else ln.get("glass"),
            "colour": (ln.get("options") or {}).get("colour") if isinstance(ln.get("options"), dict) else ln.get("colour"),
            "handle": (ln.get("options") or {}).get("handle") if isinstance(ln.get("options"), dict) else ln.get("handle"),
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
                "architect": (architect or "").strip() or None,
                "dealer": (dealer or "").strip() or None,
                "projectId": project_id,
                "quotationId": quotation_id,
                "kind": "terms_only",
                "terms": terms,
                "paymentTerm": payment_term,
                "discountPercent": discount_percent,
            }
        )

    path = observations_path()
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    for cache in (insights_cache_path(), intel_cache_path()):
        if cache.is_file():
            cache.unlink()

    # Refresh customer memory cache for this customer
    cust = (customer or "").strip()
    if cust:
        try:
            build_customer_memory(cust, persist=True)
        except Exception:
            pass

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


def _mode(counter: Counter[str]) -> str | None:
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def _avg(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


def _month_name(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%B")
    except Exception:
        return None


def _product_family(product: str | None) -> str:
    p = (product or "").lower()
    if "slid" in p:
        return "sliding"
    if "case" in p:
        return "casement"
    if "fix" in p:
        return "fixed"
    if "pergola" in p:
        return "pergola"
    if "wardrobe" in p:
        return "wardrobe"
    if "shower" in p:
        return "shower"
    if "mosquito" in p or "mesh" in p:
        return "mosquito_mesh"
    return p or "unknown"


# Cross-sell graph (pragmatic defaults; learned co-occurrence strengthens)
DEFAULT_UPSELL: dict[str, list[str]] = {
    "sliding": ["mosquito_mesh", "shower", "wardrobe", "pergola"],
    "casement": ["mosquito_mesh", "fixed", "pergola"],
    "fixed": ["sliding", "casement"],
    "shower": ["wardrobe", "sliding"],
    "wardrobe": ["sliding", "shower"],
    "pergola": ["sliding", "casement"],
}


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


# ── Customer Memory ───────────────────────────────────────────────────────────

ASK_PROMPT_HI = "Is customer ke liye pichli baar jaisi commercial settings apply karni hain?"
ASK_PROMPT_EN = "Apply this customer's preferred commercial settings from previous quotations?"


def build_customer_memory(customer: str, *, persist: bool = True, last_n: int = 20) -> dict[str, Any]:
    """Per-customer commercial profile from last N quotation observations."""
    cust = (customer or "").strip()
    if not cust:
        return {"ok": False, "hasMemory": False, "message": "No customer name"}

    all_rows = _read_observations(limit=5000)
    rows = [r for r in all_rows if str(r.get("customer") or "").strip().lower() == cust.lower()]
    if not rows:
        empty = {
            "ok": True,
            "hasMemory": False,
            "customer": cust,
            "message": "No past quotations for this customer yet.",
            "askPrompt": ASK_PROMPT_HI,
            "askPromptEn": ASK_PROMPT_EN,
        }
        return empty

    # Group by quotation/batch for "last quotations"
    by_quote: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("kind") == "terms_only":
            continue
        qid = str(r.get("quotationId") or r.get("batchId") or r.get("projectId") or r.get("id"))
        by_quote[qid].append(r)

    quote_summaries = []
    for qid, qrows in by_quote.items():
        amts = []
        for r in qrows:
            if r.get("sellingAmount") is not None:
                try:
                    amts.append(float(r["sellingAmount"]))
                except (TypeError, ValueError):
                    pass
        quote_summaries.append(
            {
                "quotationId": qid,
                "ts": max((r.get("ts") or "") for r in qrows),
                "projectId": qrows[0].get("projectId"),
                "lineCount": len(qrows),
                "products": list({str(r.get("product")) for r in qrows if r.get("product")}),
                "totalSelling": round(sum(amts), 2) if amts else None,
                "colour": _mode(Counter(str(r.get("colour")) for r in qrows if r.get("colour"))),
                "glass": _mode(Counter(str(r.get("glass")) for r in qrows if r.get("glass"))),
            }
        )
    quote_summaries.sort(key=lambda x: x.get("ts") or "", reverse=True)
    last_quotes = quote_summaries[:last_n]

    colour_c: Counter[str] = Counter()
    glass_c: Counter[str] = Counter()
    handle_c: Counter[str] = Counter()
    payment_c: Counter[str] = Counter()
    terms_c: Counter[str] = Counter()
    sale_unit_c: Counter[str] = Counter()
    discounts: list[float] = []
    margins: list[float] = []
    project_values: list[float] = []
    rate_by_product: dict[str, list[float]] = defaultdict(list)

    for r in rows:
        if r.get("kind") == "terms_only":
            if r.get("terms"):
                terms_c[str(r["terms"])[:200]] += 1
            if r.get("paymentTerm"):
                payment_c[str(r["paymentTerm"])[:80]] += 1
            continue
        if r.get("colour"):
            colour_c[str(r["colour"])] += 1
        if r.get("glass"):
            glass_c[str(r["glass"])] += 1
        if r.get("handle"):
            handle_c[str(r["handle"])] += 1
        if r.get("paymentTerm"):
            payment_c[str(r["paymentTerm"])[:80]] += 1
        if r.get("terms"):
            terms_c[str(r["terms"])[:200]] += 1
        if r.get("saleUnit"):
            sale_unit_c[str(r["saleUnit"])] += 1
        if r.get("discountPercent") is not None:
            try:
                discounts.append(float(r["discountPercent"]))
            except (TypeError, ValueError):
                pass
        if r.get("marginAmount") is not None and r.get("sellingAmount"):
            try:
                sell = float(r["sellingAmount"])
                if sell:
                    margins.append(float(r["marginAmount"]) / sell * 100.0)
            except (TypeError, ValueError):
                pass
        prod = r.get("product")
        if prod and r.get("sellingRate") is not None:
            try:
                rate_by_product[str(prod)].append(float(r["sellingRate"]))
            except (TypeError, ValueError):
                pass

    for q in last_quotes:
        if q.get("totalSelling"):
            project_values.append(float(q["totalSelling"]))

    preferred_colour = _mode(colour_c)
    preferred_glass = _mode(glass_c)
    preferred_handle = _mode(handle_c)
    preferred_payment = _mode(payment_c) or "30 Days"
    preferred_terms = _mode(terms_c)
    preferred_sale_unit = _mode(sale_unit_c) or "sqft"

    rate_hints = []
    for prod, rates in sorted(rate_by_product.items()):
        rates_sorted = sorted(rates)
        rate_hints.append(
            {
                "product": prod,
                "medianRate": round(rates_sorted[len(rates_sorted) // 2], 2),
                "avgRate": round(sum(rates) / len(rates), 2),
                "samples": len(rates),
                "saleUnit": preferred_sale_unit,
            }
        )

    apply_payload = {
        "colour": preferred_colour,
        "glass": preferred_glass,
        "handle": preferred_handle,
        "saleUnit": preferred_sale_unit,
        "paymentTerm": preferred_payment,
        "terms": preferred_terms,
        "discountPercent": _avg(discounts),
        "sellingRateHints": rate_hints,
    }

    memory = {
        "ok": True,
        "hasMemory": True,
        "customer": cust,
        "observationCount": len(rows),
        "quotationCount": len(quote_summaries),
        "preferredPayment": preferred_payment,
        "preferredColour": preferred_colour,
        "preferredGlass": preferred_glass,
        "preferredHandle": preferred_handle,
        "preferredTerms": preferred_terms,
        "preferredSaleUnit": preferred_sale_unit,
        "averageDiscountPercent": _avg(discounts),
        "averageProjectValue": _avg(project_values),
        "averageMarginPercent": round(sum(margins) / len(margins), 1) if margins else None,
        "lastQuotations": last_quotes,
        "sellingRateHints": rate_hints,
        "askPrompt": ASK_PROMPT_HI,
        "askPromptEn": ASK_PROMPT_EN,
        "applyPayload": apply_payload,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "message": (
            f"{cust}: prefers {preferred_colour or '—'} / {preferred_glass or '—'} / "
            f"{preferred_handle or '—'} · payment {preferred_payment}"
        ),
        "safety": "Apply only after user confirms. Does not change engineering production rules.",
    }

    if persist:
        customer_memory_path(cust).write_text(
            json.dumps(memory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return memory


def get_customer_memory(customer: str) -> dict[str, Any]:
    cust = (customer or "").strip()
    if not cust:
        return {"ok": False, "hasMemory": False, "message": "Customer required"}
    path = customer_memory_path(cust)
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
            if doc.get("hasMemory"):
                return doc
        except Exception:
            pass
    return build_customer_memory(cust, persist=True)


def apply_customer_memory_settings(customer: str) -> dict[str, Any]:
    """Return commercial settings for one-click apply (caller applies to quote UI / draft).

    Explicit user accept required in UI — this does not write engineering production data.
    Optionally persists an 'acceptedAt' stamp on the memory file.
    """
    mem = get_customer_memory(customer)
    if not mem.get("hasMemory"):
        return {"ok": False, "applied": False, "message": mem.get("message") or "No memory"}
    payload = mem.get("applyPayload") or {}
    mem["lastAppliedAt"] = datetime.now(timezone.utc).isoformat()
    customer_memory_path(customer).write_text(
        json.dumps(mem, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "ok": True,
        "applied": True,  # means settings returned for client apply — not silent prod overwrite
        "customer": mem.get("customer"),
        "settings": payload,
        "message": "Commercial settings ready — applied to quote draft only after your confirm.",
        "memory": {
            "preferredPayment": mem.get("preferredPayment"),
            "preferredColour": mem.get("preferredColour"),
            "preferredGlass": mem.get("preferredGlass"),
            "preferredHandle": mem.get("preferredHandle"),
            "averageDiscountPercent": mem.get("averageDiscountPercent"),
        },
    }


# ── Full commercial intelligence ──────────────────────────────────────────────

def build_commercial_intelligence(*, limit: int = 2000) -> dict[str, Any]:
    rows = _read_observations(limit=limit)
    line_rows = [r for r in rows if r.get("kind") != "terms_only"]

    # Customer prefs
    customers: dict[str, Counter[str]] = defaultdict(Counter)
    customer_products: dict[str, Counter[str]] = defaultdict(Counter)

    # Architect
    architect_finish: dict[str, Counter[str]] = defaultdict(Counter)

    # Dealer discounts
    dealer_disc: dict[str, list[float]] = defaultdict(list)

    # Margin by product family
    margin_by_family: dict[str, list[float]] = defaultdict(list)

    # Seasonal colour
    season_colour: dict[str, Counter[str]] = defaultdict(Counter)

    # Vendor (price / mentions)
    vendor_price: dict[str, list[float]] = defaultdict(list)
    vendor_count: Counter[str] = Counter()

    # Co-occurrence for upsell (products in same batch)
    batch_products: dict[str, set[str]] = defaultdict(set)

    for r in line_rows:
        cust = r.get("customer")
        if cust and r.get("colour"):
            customers[str(cust)][f"colour:{r['colour']}"] += 1
        if cust and r.get("glass"):
            customers[str(cust)][f"glass:{r['glass']}"] += 1
        if cust and r.get("handle"):
            customers[str(cust)][f"handle:{r['handle']}"] += 1
        if cust and r.get("product"):
            customer_products[str(cust)][str(r["product"])] += 1

        arch = r.get("architect")
        if arch and r.get("colour"):
            architect_finish[str(arch)][str(r["colour"])] += 1

        dealer = r.get("dealer")
        if dealer and r.get("discountPercent") is not None:
            try:
                dealer_disc[str(dealer)].append(float(r["discountPercent"]))
            except (TypeError, ValueError):
                pass

        fam = _product_family(str(r.get("product") or ""))
        if r.get("marginAmount") is not None and r.get("sellingAmount"):
            try:
                sell = float(r["sellingAmount"])
                if sell:
                    margin_by_family[fam].append(float(r["marginAmount"]) / sell * 100.0)
            except (TypeError, ValueError):
                pass

        month = _month_name(r.get("ts"))
        if month and r.get("colour"):
            season_colour[month][str(r["colour"])] += 1

        vendor = r.get("vendor")
        if vendor:
            vendor_count[str(vendor)] += 1
            if r.get("costAmount") is not None:
                try:
                    vendor_price[str(vendor)].append(float(r["costAmount"]))
                except (TypeError, ValueError):
                    pass

        bid = str(r.get("batchId") or "")
        if bid and r.get("product"):
            batch_products[bid].add(_product_family(str(r["product"])))

    # Upsell from co-occurrence
    pair_c: Counter[tuple[str, str]] = Counter()
    for prods in batch_products.values():
        plist = sorted(prods)
        for i, a in enumerate(plist):
            for b in plist[i + 1 :]:
                pair_c[(a, b)] += 1

    customer_profiles = []
    for cust, prefs in list(customers.items())[:40]:
        customer_profiles.append(
            {
                "customer": cust,
                "topPrefs": prefs.most_common(6),
                "topProducts": customer_products.get(cust, Counter()).most_common(4),
            }
        )

    architects = [
        {"architect": a, "preferredFinish": _mode(c), "counts": c.most_common(3)}
        for a, c in sorted(architect_finish.items())
    ]
    dealers = [
        {"dealer": d, "avgDiscountPercent": _avg(xs), "samples": len(xs)}
        for d, xs in sorted(dealer_disc.items())
    ]
    margins = [
        {"productFamily": fam, "avgMarginPercent": round(sum(xs) / len(xs), 1), "samples": len(xs)}
        for fam, xs in sorted(margin_by_family.items())
        if xs
    ]
    seasonal = [
        {"month": m, "topColour": _mode(c), "colours": c.most_common(3)}
        for m, c in sorted(season_colour.items(), key=lambda x: x[0])
    ]
    vendors = [
        {
            "vendor": v,
            "mentions": vendor_count[v],
            "avgCostAmount": _avg(vendor_price.get(v, [])),
            "hint": "best_price" if vendor_price.get(v) and _avg(vendor_price[v]) == min(
                (_avg(xs) or 1e18) for xs in vendor_price.values() if xs
            ) else "active",
        }
        for v in vendor_count
    ]
    vendors.sort(key=lambda x: (-(x["mentions"] or 0), x.get("avgCostAmount") or 0))

    upsell = []
    for (a, b), n in pair_c.most_common(15):
        upsell.append({"when": a, "recommend": b, "coOccurrences": n, "source": "learned"})
    # Seed defaults if thin data
    if len(upsell) < 4:
        for when, recs in DEFAULT_UPSELL.items():
            for rec in recs[:2]:
                upsell.append({"when": when, "recommend": rec, "coOccurrences": 0, "source": "default"})

    tips = []
    if margins:
        tips.append(
            " · ".join(f"{m['productFamily']} margin ~{m['avgMarginPercent']}%" for m in margins[:4])
        )
    if seasonal:
        cur_month = datetime.now(timezone.utc).strftime("%B")
        for s in seasonal:
            if s["month"] == cur_month and s.get("topColour"):
                tips.append(f"{cur_month}: {s['topColour']} finish trending")
                break
    if dealers:
        d0 = dealers[0]
        tips.append(f"Dealer {d0['dealer']} typical discount ~{d0['avgDiscountPercent']}%")
    if architects:
        a0 = architects[0]
        tips.append(f"Architect {a0['architect']} usually {a0['preferredFinish']}")
    if not tips:
        tips.append("Save more quotes with customer / rates — commercial intelligence will deepen.")

    result = {
        "ok": True,
        "status": "learning" if line_rows else "waiting",
        "observationCount": len(line_rows),
        "tips": tips,
        "customers": customer_profiles,
        "architects": architects,
        "dealers": dealers,
        "marginsByProduct": margins,
        "seasonal": seasonal,
        "vendors": vendors,
        "productRecommendations": upsell[:20],
        "message": tips[0] if tips else "Commercial intelligence warming up…",
        "safety": "Insights & suggestions only. Customer Memory apply requires explicit confirm. No production engineering auto-write.",
    }
    intel_cache_path().write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Also store a slim profile snapshot
    (commercial_dir() / "profiles" / "latest.json").write_text(
        json.dumps(
            {
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "marginsByProduct": margins,
                "seasonal": seasonal,
                "productRecommendations": upsell[:20],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def product_recommendations(product: str | None = None) -> dict[str, Any]:
    intel = build_commercial_intelligence()
    fam = _product_family(product) if product else None
    recs = intel.get("productRecommendations") or []
    if fam:
        recs = [r for r in recs if r.get("when") == fam] or [
            {"when": fam, "recommend": x, "coOccurrences": 0, "source": "default"}
            for x in DEFAULT_UPSELL.get(fam, ["mosquito_mesh", "pergola"])
        ]
    return {"ok": True, "product": product, "family": fam, "recommendations": recs}


def commercial_suggestions() -> dict[str, Any]:
    """Actionable commercial suggestions (UI one-click → memory refresh / note — not eng production)."""
    intel = build_commercial_intelligence()
    suggestions = []
    for m in intel.get("marginsByProduct") or []:
        suggestions.append(
            {
                "id": f"margin_{m['productFamily']}",
                "domain": "commercial",
                "action": "insight",
                "title": f"{m['productFamily'].title()} avg margin {m['avgMarginPercent']}%",
                "summary": f"Use ~{m['avgMarginPercent']}% as pricing guidance ({m['samples']} samples). Not auto-applied.",
                "oneClick": False,
            }
        )
    for s in (intel.get("seasonal") or [])[-3:]:
        if s.get("topColour"):
            suggestions.append(
                {
                    "id": f"season_{s['month']}",
                    "domain": "commercial",
                    "action": "insight",
                    "title": f"{s['month']}: push {s['topColour']}",
                    "summary": "Seasonal colour preference from quote history.",
                    "oneClick": False,
                }
            )
    for d in (intel.get("dealers") or [])[:5]:
        suggestions.append(
            {
                "id": f"dealer_{d['dealer']}",
                "domain": "commercial",
                "action": "suggest_discount",
                "title": f"Dealer {d['dealer']}: suggest {d['avgDiscountPercent']}% discount",
                "summary": "Auto-suggest only — user must confirm on quote.",
                "payload": {"dealer": d["dealer"], "discountPercent": d["avgDiscountPercent"]},
                "oneClick": True,
            }
        )
    for a in (intel.get("architects") or [])[:5]:
        suggestions.append(
            {
                "id": f"arch_{a['architect']}",
                "domain": "commercial",
                "action": "suggest_finish",
                "title": f"Architect {a['architect']}: recommend {a['preferredFinish']}",
                "summary": "Finish preference — apply to quote line after confirm.",
                "payload": {"architect": a["architect"], "colour": a["preferredFinish"]},
                "oneClick": True,
            }
        )
    for u in (intel.get("productRecommendations") or [])[:8]:
        suggestions.append(
            {
                "id": f"upsell_{u['when']}_{u['recommend']}",
                "domain": "commercial",
                "action": "upsell",
                "title": f"When ordering {u['when']} → recommend {u['recommend']}",
                "summary": f"Co-occurrence {u.get('coOccurrences', 0)} ({u.get('source')})",
                "payload": u,
                "oneClick": False,
            }
        )
    return {
        "status": "suggestions_only",
        "message": "Commercial suggestions — never silent production overwrite.",
        "suggestions": suggestions,
        "intelligence": {
            "tips": intel.get("tips"),
            "observationCount": intel.get("observationCount"),
        },
    }
