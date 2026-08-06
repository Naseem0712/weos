"""Engineering Brain engine — load / reason / generate from approved KB."""

from __future__ import annotations

import re
from typing import Any

from WEOS.memory import cache
from WEOS.memory.schemas import (
    MEM_COMMERCIAL,
    MEM_DRAWING,
    MEM_FACTORY,
    MEM_FORMULA,
    MEM_GLASS,
    MEM_HARDWARE,
    MEM_PRODUCT,
    MEM_PROFILE,
    MEM_QUOTATION,
)
from WEOS.memory.store import get_store


def brain_status() -> dict[str, Any]:
    from WEOS.learning.v2_store import current_kb_version, list_kb_versions

    store = get_store()
    return {
        "role": "Engineering Brain — reasoning layer over approved Knowledge Base",
        "kbVersion": current_kb_version(),
        "versions": len(list_kb_versions()),
        "memories": store.summary().get("counts"),
        "autoWriteProduction": False,
        "cache": "in-process + file TTL",
        "capabilities": ["load", "reason", "generate"],
        "outputs": ["bom", "drawing", "pdf", "quotation", "weight", "cost", "packing", "machine_cutting"],
    }


def _match_series(series_query: str) -> dict[str, Any] | None:
    """Resolve series id / name / code (e.g. S29, 29mm_sliding_smoke)."""
    store = get_store()
    q = (series_query or "").strip()
    if not q:
        return None
    q_norm = re.sub(r"[^a-z0-9]+", "", q.lower())
    products = store.list(MEM_PRODUCT, status="approved") or store.list(MEM_PRODUCT)
    # Prefer approved
    approved = [p for p in products if (p.get("status") or "") == "approved"] or products

    for p in approved:
        pid = str(p.get("id") or "")
        name = str(p.get("seriesName") or "")
        code = str(p.get("seriesCode") or "")
        candidates = [
            re.sub(r"[^a-z0-9]+", "", pid.lower()),
            re.sub(r"[^a-z0-9]+", "", name.lower()),
            re.sub(r"[^a-z0-9]+", "", code.lower()),
        ]
        if q_norm in candidates or any(q_norm and q_norm in c for c in candidates):
            return p
        # S29 ↔ 29mm / series containing 29
        if q_norm.startswith("s") and q_norm[1:].isdigit():
            num = q_norm[1:]
            if num in pid.lower() or num in name.lower():
                return p
    # Fallback: library via product_builder list
    try:
        from WEOS.learning.product_builder import list_buildable_series

        for s in list_buildable_series():
            sid = str(s.get("id") or "")
            if q_norm in re.sub(r"[^a-z0-9]+", "", sid.lower()) or q_norm in re.sub(
                r"[^a-z0-9]+", "", str(s.get("seriesName") or "").lower()
            ):
                try:
                    return get_store().get(MEM_PRODUCT, sid)
                except FileNotFoundError:
                    return {
                        "id": sid,
                        "seriesName": s.get("seriesName"),
                        "brand": s.get("brand"),
                        "productCategory": s.get("productCategory"),
                        "status": "approved",
                        "memoryType": MEM_PRODUCT,
                    }
    except Exception:
        pass
    return None


def load_context(
    *,
    series: str,
    product_type: str | None = None,
    customer: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Load approved Profiles, Glass, Hardware, Formula, Drawing, Weight/Cutting/
    Pricing/Factory/Commercial rules for a series into one Brain context pack.
    """
    from WEOS.learning.v2_store import current_kb_version

    kb_ver = current_kb_version()
    ck = cache.cache_key("brain", "load", series, product_type or "", customer or "", kb_ver)
    if use_cache:
        hit = cache.get(ck)
        if hit is not None:
            hit = dict(hit)
            hit["cacheHit"] = True
            return hit

    store = get_store()
    product = _match_series(series)
    if not product:
        return {
            "ok": False,
            "error": f"No approved product/series memory matching '{series}'",
            "series": series,
            "kbVersion": kb_ver,
        }

    series_id = str(product.get("id"))

    def _linked(memory_type: str, *, id_keys: tuple[str, ...] = (), compat_key: str = "compatibleSeries") -> list[dict[str, Any]]:
        items = store.list(memory_type)
        out: list[dict[str, Any]] = []
        linked_ids: set[str] = set()
        for key in id_keys:
            for ref in product.get(key) or []:
                rid = ref if isinstance(ref, str) else (ref.get("id") if isinstance(ref, dict) else None)
                if rid:
                    linked_ids.add(str(rid))
        for it in items:
            if (it.get("status") or "") not in ("approved", "draft", None, ""):
                if it.get("status") == "rejected" or it.get("status") == "archived":
                    continue
            iid = str(it.get("id") or "")
            if iid in linked_ids:
                out.append(it)
                continue
            compat = it.get(compat_key) or it.get("compatibleProducts") or []
            if series_id in [str(x) for x in compat] or it.get("seriesId") == series_id:
                out.append(it)
        # Prefer approved
        approved = [x for x in out if x.get("status") == "approved"]
        return approved or out

    profiles = _linked(MEM_PROFILE, id_keys=("profileIds", "profiles"))
    hardware = _linked(MEM_HARDWARE, id_keys=("hardwareIds", "hardware"))
    glass = _linked(MEM_GLASS, id_keys=("glassIds", "glass"), compat_key="compatibleProducts")
    formulas = _linked(MEM_FORMULA, id_keys=("formulaIds", "formulas"))
    drawings = _linked(MEM_DRAWING, id_keys=("drawingIds",))
    factory = [f for f in store.list(MEM_FACTORY) if f.get("seriesId") == series_id or series_id in (f.get("compatibleSeries") or [])]
    quotations = store.list(MEM_QUOTATION)

    commercial = None
    if customer:
        for c in store.list(MEM_COMMERCIAL):
            if (c.get("customerName") or "").lower() == customer.lower() or c.get("id") == customer:
                commercial = c
                break
        if commercial is None:
            try:
                from WEOS.learning.commercial_agent import get_customer_memory

                commercial = get_customer_memory(customer)
            except Exception:
                commercial = None

    # Also reuse product_builder assembly for geometry/BOM hints
    builder = None
    try:
        from WEOS.learning.product_builder import load_series_for_builder

        builder = load_series_for_builder(series_id)
    except Exception as exc:
        builder = {"error": str(exc)}

    ctx = {
        "ok": True,
        "cacheHit": False,
        "kbVersion": kb_ver,
        "productType": product_type,
        "seriesQuery": series,
        "seriesId": series_id,
        "series": product,
        "profiles": profiles,
        "hardware": hardware,
        "glass": glass,
        "formulas": formulas,
        "drawings": drawings,
        "factoryRules": factory,
        "quotationMemories": quotations[:10],
        "commercial": commercial,
        "rules": {
            "drawing": product.get("pdfLayout") or (builder or {}).get("pdfLayout") or {},
            "weight": product.get("weightRules") or (builder or {}).get("weightRules") or {},
            "cutting": product.get("cuttingRules") or (builder or {}).get("cuttingRules") or {},
            "pricing": product.get("pricingRules") or (builder or {}).get("pricingRules") or {},
            "factory": (factory[0] if factory else {}),
            "commercial": (commercial or {}),
            "quotation": product.get("quotationRules") or (builder or {}).get("quotationRules") or {},
        },
        "builder": builder,
        "counts": {
            "profiles": len(profiles),
            "hardware": len(hardware),
            "glass": len(glass),
            "formulas": len(formulas),
            "drawings": len(drawings),
            "factory": len(factory),
        },
        "source": "approved_knowledge_base",
        "production_modified": False,
    }
    cache.set(ck, ctx, ttl=180)
    return ctx


def reason(context: dict[str, Any] | None = None, **load_kwargs: Any) -> dict[str, Any]:
    """
    Decide which approved rules apply for the selected product/series.
    Returns an explanation pack (no production writes).
    """
    ctx = context or load_context(**load_kwargs)
    if not ctx.get("ok"):
        return ctx

    decisions: list[dict[str, Any]] = []
    profiles = ctx.get("profiles") or []
    for p in profiles:
        decisions.append(
            {
                "kind": "profile_usage",
                "id": p.get("id"),
                "name": p.get("profileName") or p.get("name"),
                "bomRole": p.get("bomRole") or (p.get("usageRules") or {}).get("bomRole"),
                "positions": p.get("usePosition") or (p.get("usageRules") or {}).get("positions") or [],
                "weightPerMeterKg": p.get("weightPerMeterKg"),
                "rationale": "Approved Profile Memory linked to series",
            }
        )

    for f in ctx.get("formulas") or []:
        decisions.append(
            {
                "kind": "formula",
                "id": f.get("id"),
                "name": f.get("name"),
                "expression": f.get("expression"),
                "formulaVersion": f.get("formulaVersion") or 1,
                "category": f.get("category"),
                "rationale": "Approved Formula Memory (versioned)",
            }
        )

    for g in ctx.get("glass") or []:
        decisions.append(
            {
                "kind": "glass",
                "id": g.get("id"),
                "name": g.get("name"),
                "thicknessMm": g.get("thicknessMm"),
                "overlapRules": g.get("overlapRules") or {},
                "rationale": "Approved Glass Memory",
            }
        )

    for h in ctx.get("hardware") or []:
        decisions.append(
            {
                "kind": "hardware",
                "id": h.get("id"),
                "name": h.get("name"),
                "unit": h.get("unit"),
                "installPosition": h.get("installPosition"),
                "rationale": "Approved Hardware Memory",
            }
        )

    missing: list[str] = []
    if not profiles:
        missing.append("profiles")
    if not (ctx.get("formulas") or []):
        missing.append("formulas")
    if not (ctx.get("glass") or []):
        missing.append("glass")

    return {
        "ok": True,
        "seriesId": ctx.get("seriesId"),
        "kbVersion": ctx.get("kbVersion"),
        "decisions": decisions,
        "rulesApplied": list((ctx.get("rules") or {}).keys()),
        "missing": missing,
        "ready": len(missing) == 0 or bool(profiles),
        "explanation": (
            f"Brain loaded KB v{ctx.get('kbVersion')} for {ctx.get('seriesId')}: "
            f"{ctx.get('counts')}. Decisions derived only from approved memory."
        ),
        "production_modified": False,
    }


def generate(
    *,
    series: str,
    product_type: str | None = None,
    customer: str | None = None,
    width_mm: float | None = None,
    height_mm: float | None = None,
    quantity: int = 1,
    outputs: list[str] | None = None,
) -> dict[str, Any]:
    """
    Generate BOM / drawing plan / PDF layout / quotation skeleton / weight /
    cost / packing / machine cutting from approved Brain context.

    This is the orchestration API that calculate / product_builder can call
    or gradually replace. Does not write production ERP tables.
    """
    wanted = set(outputs or ["bom", "drawing", "pdf", "quotation", "weight", "cost", "packing", "machine_cutting"])
    ctx = load_context(series=series, product_type=product_type, customer=customer)
    if not ctx.get("ok"):
        return ctx
    reasoned = reason(ctx)

    w = float(width_mm or 1200)
    h = float(height_mm or 1500)
    qty = max(1, int(quantity or 1))
    perimeter_m = 2 * (w + h) / 1000.0
    area_sqm = (w * h) / 1_000_000.0

    result: dict[str, Any] = {
        "ok": True,
        "seriesId": ctx.get("seriesId"),
        "kbVersion": ctx.get("kbVersion"),
        "inputs": {"width_mm": w, "height_mm": h, "quantity": qty, "product_type": product_type, "customer": customer},
        "reason": reasoned,
        "generated": {},
        "production_modified": False,
        "message": "Generated from approved Knowledge Base via Engineering Brain",
    }
    gen = result["generated"]

    if "bom" in wanted:
        bom_lines = []
        for p in ctx.get("profiles") or []:
            kg_m = float(p.get("weightPerMeterKg") or 0)
            positions = p.get("usePosition") or (p.get("usageRules") or {}).get("positions") or ["Top", "Bottom", "Left", "Right"]
            # Simple perimeter share heuristic
            length_m = perimeter_m if len(positions) >= 4 else (max(w, h) / 1000.0) * max(1, len(positions) // 2)
            bom_lines.append(
                {
                    "type": "profile",
                    "id": p.get("id"),
                    "name": p.get("profileName") or p.get("name"),
                    "code": p.get("profileCode"),
                    "bomRole": p.get("bomRole"),
                    "positions": positions,
                    "length_m": round(length_m * qty, 3),
                    "weight_kg": round(length_m * kg_m * qty, 3),
                    "unit": "MTR",
                }
            )
        for hw in ctx.get("hardware") or []:
            bom_lines.append(
                {
                    "type": "hardware",
                    "id": hw.get("id"),
                    "name": hw.get("name"),
                    "unit": hw.get("unit") or "PC",
                    "qty": qty,
                    "rate": hw.get("sellingRate") or hw.get("rate") or hw.get("purchaseRate"),
                }
            )
        for g in ctx.get("glass") or []:
            bom_lines.append(
                {
                    "type": "glass",
                    "id": g.get("id"),
                    "name": g.get("name"),
                    "thicknessMm": g.get("thicknessMm"),
                    "area_sqm": round(area_sqm * qty, 4),
                    "unit": "SQM",
                }
            )
        gen["bom"] = {"lines": bom_lines, "lineCount": len(bom_lines)}

    if "weight" in wanted:
        total_kg = 0.0
        for line in (gen.get("bom") or {}).get("lines") or []:
            total_kg += float(line.get("weight_kg") or 0)
        for g in ctx.get("glass") or []:
            kg_sqm = float(g.get("weightKgPerSqm") or 0)
            if not kg_sqm and g.get("thicknessMm"):
                # ~2.5 kg/m² per mm density heuristic when not in memory
                kg_sqm = float(g["thicknessMm"]) * 2.5
            total_kg += kg_sqm * area_sqm * qty
        gen["weight"] = {"total_kg": round(total_kg, 3), "rules": (ctx.get("rules") or {}).get("weight")}

    if "cost" in wanted:
        material_cost = 0.0
        for line in (gen.get("bom") or {}).get("lines") or []:
            rate = line.get("rate")
            if rate is not None:
                material_cost += float(rate) * float(line.get("qty") or line.get("length_m") or line.get("area_sqm") or 0)
        gen["cost"] = {
            "material_estimate": round(material_cost, 2),
            "currency": "INR",
            "pricingRules": (ctx.get("rules") or {}).get("pricing"),
            "note": "Estimate from approved rates only — not a live ERP price book",
        }

    if "drawing" in wanted:
        gen["drawing"] = {
            "width_mm": w,
            "height_mm": h,
            "profiles": [
                {"id": p.get("id"), "type": p.get("profileType"), "code": p.get("profileCode")}
                for p in (ctx.get("profiles") or [])
            ],
            "drawings": ctx.get("drawings") or [],
            "dimensionStyle": ((ctx.get("drawings") or [{}])[0].get("dimensionStyle") if ctx.get("drawings") else {}),
            "note": "Drawing plan from Drawing Memory + profile cross-sections",
        }

    if "pdf" in wanted:
        gen["pdf"] = {
            "layout": (ctx.get("rules") or {}).get("drawing") or {"customer": "marqt_customer", "factory": "woodenmax_factory"},
            "seriesName": (ctx.get("series") or {}).get("seriesName"),
        }

    if "quotation" in wanted:
        qmem = (ctx.get("quotationMemories") or [None])[0] or {}
        commercial = ctx.get("commercial") or {}
        gen["quotation"] = {
            "customer": customer,
            "terms": qmem.get("terms") or commercial.get("paymentTerms") or "",
            "warranty": qmem.get("warranty") or commercial.get("warranty") or "",
            "payment": qmem.get("payment") or commercial.get("paymentTerms") or "",
            "gst": qmem.get("gst") or commercial.get("gstRules") or {},
            "brandColours": qmem.get("brandColours") or {},
            "descriptions": qmem.get("descriptions") or commercial.get("descriptions") or {},
            "rules": (ctx.get("rules") or {}).get("quotation"),
        }

    if "packing" in wanted:
        factory = (ctx.get("rules") or {}).get("factory") or {}
        gen["packing"] = {
            "packingRules": factory.get("packingRules") or {},
            "bundleRules": factory.get("bundleRules") or {},
            "labelRules": factory.get("labelRules") or {},
            "qrRules": factory.get("qrRules") or {},
            "deliveryNotes": factory.get("deliveryNotes") or (ctx.get("series") or {}).get("deliveryNotes") or "",
        }

    if "machine_cutting" in wanted:
        factory = (ctx.get("rules") or {}).get("factory") or {}
        cuts = []
        for p in ctx.get("profiles") or []:
            positions = p.get("usePosition") or []
            if "Top" in positions or "Bottom" in positions or not positions:
                cuts.append({"profileId": p.get("id"), "label": "horizontal", "length_mm": w, "qty": 2 * qty})
            if "Left" in positions or "Right" in positions or not positions:
                cuts.append({"profileId": p.get("id"), "label": "vertical", "length_mm": h, "qty": 2 * qty})
        gen["machine_cutting"] = {
            "machine": factory.get("machine") or {},
            "cuts": cuts,
            "optimizationRules": factory.get("optimizationRules") or (ctx.get("rules") or {}).get("cutting") or {},
            "wasteRules": factory.get("wasteRules") or {},
        }

    return result
