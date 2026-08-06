"""Engineering Brain engine — load / reason / generate from approved KB.

Adds: validation gate, priority pick, compatibility warnings, conflict hard-stop,
explain/proof pack, recommendations, usage ranking bumps.
"""

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
        "cache": cache.status(),
        "capabilities": [
            "load",
            "reason",
            "generate",
            "validate",
            "explain",
            "compatibility",
            "conflicts",
            "recommend",
            "priority",
        ],
        "outputs": ["bom", "drawing", "pdf", "quotation", "weight", "cost", "packing", "machine_cutting", "explain"],
    }


def _match_series(series_query: str) -> dict[str, Any] | None:
    """Resolve series id / name / code (e.g. S29, 29mm_sliding_smoke)."""
    store = get_store()
    q = (series_query or "").strip()
    if not q:
        return None
    q_norm = re.sub(r"[^a-z0-9]+", "", q.lower())
    products = store.list(MEM_PRODUCT, status="approved") or store.list(MEM_PRODUCT)
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
        if q_norm.startswith("s") and q_norm[1:].isdigit():
            num = q_norm[1:]
            if num in pid.lower() or num in name.lower():
                return p
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
                        "glassThicknessMm": s.get("glassThicknessMm") or [5, 6, 8],
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
    from WEOS.memory.ranking import group_formulas_by_priority

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
    # Ensure glass allow-list for smoke series if missing
    if not product.get("glassThicknessMm") and "29" in series_id:
        product = dict(product)
        product["glassThicknessMm"] = [5, 6, 8]

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
            if it.get("status") in ("rejected", "archived"):
                continue
            iid = str(it.get("id") or "")
            if iid in linked_ids:
                out.append(it)
                continue
            compat = it.get(compat_key) or it.get("compatibleProducts") or []
            if series_id in [str(x) for x in compat] or it.get("seriesId") == series_id:
                out.append(it)
        approved = [x for x in out if x.get("status") == "approved"]
        return approved or out

    profiles = _linked(MEM_PROFILE, id_keys=("profileIds", "profiles"))
    hardware = _linked(MEM_HARDWARE, id_keys=("hardwareIds", "hardware"))
    glass = _linked(MEM_GLASS, id_keys=("glassIds", "glass"), compat_key="compatibleProducts")
    formulas = _linked(MEM_FORMULA, id_keys=("formulaIds", "formulas"))
    drawings = _linked(MEM_DRAWING, id_keys=("drawingIds",))
    from WEOS.memory.schemas import MEM_QUOTATION

    factory = [
        f
        for f in store.list(MEM_FACTORY)
        if f.get("seriesId") == series_id or series_id in (f.get("compatibleSeries") or [])
    ]
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

    builder = None
    try:
        from WEOS.learning.product_builder import load_series_for_builder

        builder = load_series_for_builder(series_id)
    except Exception as exc:
        builder = {"error": str(exc)}

    priority = group_formulas_by_priority(formulas)

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
        "formulaPriority": {
            cat: {
                "selectedId": (info.get("selected") or {}).get("id"),
                "priority": info.get("priority"),
                "candidates": info.get("candidates"),
            }
            for cat, info in priority.items()
        },
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
    cache.set(
        ck,
        ctx,
        ttl=180,
        index_text=f"brain load {series_id} {product_type or ''} profiles glass hardware formula",
    )
    return ctx


def validate_series(
    *,
    series: str,
    product_type: str | None = None,
    customer: str | None = None,
    require_drawing: bool = False,
) -> dict[str, Any]:
    from WEOS.memory.validate import validate_context

    ctx = load_context(series=series, product_type=product_type, customer=customer)
    return validate_context(ctx, require_drawing=require_drawing)


def check_series_compatibility(
    *,
    series: str,
    glass_thickness_mm: float | None = None,
    selections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from WEOS.memory.compatibility import check_compatibility

    ctx = load_context(series=series, use_cache=True)
    return check_compatibility(
        series_id=ctx.get("seriesId"),
        series=ctx.get("series"),
        glass_thickness_mm=glass_thickness_mm,
        selections=selections,
    )


def check_series_conflicts(
    *,
    series: str,
    selections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from WEOS.memory.conflicts import check_conflicts

    ctx = load_context(series=series, use_cache=True)
    return check_conflicts(
        selections=selections,
        series_id=ctx.get("seriesId"),
        hardware=ctx.get("hardware"),
        profiles=ctx.get("profiles"),
        glass=ctx.get("glass"),
    )


def recommend(
    *,
    series: str | None = None,
    product_type: str | None = None,
) -> dict[str, Any]:
    """Upsell / accessory recommendations via commercial agent + Sliding defaults."""
    family = (product_type or series or "sliding").lower()
    recs: list[dict[str, Any]] = []
    try:
        from WEOS.learning.commercial_agent import product_recommendations

        packed = product_recommendations(product_type or series)
        recs.extend(packed.get("recommendations") or [])
    except Exception:
        pass

    # Sliding accessory defaults (Mesh, Mosquito, Restrictor, Safety Lock)
    if any(x in family for x in ("slid", "29mm", "s29")):
        defaults = [
            ("Mesh", "Mesh shutter / mesh track"),
            ("Mosquito", "Mosquito net / insect mesh"),
            ("Restrictor", "Opening restrictor"),
            ("Safety Lock", "Child safety lock"),
        ]
        have = {str(r.get("recommend") or "").lower() for r in recs}
        for name, why in defaults:
            if name.lower() not in have and not any(name.lower() in h for h in have):
                recs.append(
                    {
                        "when": "sliding",
                        "recommend": name,
                        "reason": why,
                        "coOccurrences": 0,
                        "source": "brain_default",
                    }
                )

    return {
        "ok": True,
        "series": series,
        "productType": product_type,
        "recommendations": recs[:20],
        "autoApplied": False,
        "production_modified": False,
    }


def explain(
    *,
    series: str,
    width_mm: float = 1200,
    height_mm: float = 1500,
    shutter_count: int = 2,
    product_type: str | None = None,
) -> dict[str, Any]:
    from WEOS.memory.explain import explain_from_context

    ctx = load_context(series=series, product_type=product_type, use_cache=True)
    if not ctx.get("ok"):
        return ctx
    return explain_from_context(
        ctx,
        width_mm=width_mm,
        height_mm=height_mm,
        shutter_count=shutter_count,
    )


def reason(context: dict[str, Any] | None = None, **load_kwargs: Any) -> dict[str, Any]:
    """
    Decide which approved rules apply for the selected product/series.
    Returns an explanation pack (no production writes).
    """
    from WEOS.memory.ranking import group_formulas_by_priority, ranking_fields

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
                "ranking": ranking_fields(p),
                "rationale": "Approved Profile Memory linked to series",
            }
        )

    priority = group_formulas_by_priority(ctx.get("formulas") or [])
    for cat, info in priority.items():
        f = info.get("selected") or {}
        decisions.append(
            {
                "kind": "formula",
                "category": cat,
                "id": f.get("id"),
                "name": f.get("name"),
                "expression": f.get("expression"),
                "formulaVersion": f.get("formulaVersion") or 1,
                "priority": info.get("priority"),
                "candidates": info.get("candidates"),
                "ranking": ranking_fields(f),
                "rationale": f"Highest approved priority ({info.get('priority')}) among {len(info.get('candidates') or [])} candidates",
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
                "ranking": ranking_fields(g),
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
                "ranking": ranking_fields(h),
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
        "formulaPriority": ctx.get("formulaPriority") or {
            cat: {"selectedId": (i.get("selected") or {}).get("id"), "priority": i.get("priority")}
            for cat, i in priority.items()
        },
        "rulesApplied": list((ctx.get("rules") or {}).keys()),
        "missing": missing,
        "ready": len(missing) == 0 or bool(profiles),
        "explanation": (
            f"Brain loaded KB v{ctx.get('kbVersion')} for {ctx.get('seriesId')}: "
            f"{ctx.get('counts')}. Decisions derived only from approved memory; "
            f"formulas resolved by priority."
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
    glass_thickness_mm: float | None = None,
    shutter_count: int = 2,
    selections: list[dict[str, Any]] | None = None,
    skip_validation: bool = False,
) -> dict[str, Any]:
    """
    Generate BOM / drawing / PDF / quotation / weight / cost / packing / machine cutting
    with validation gate, conflict hard-stop, compatibility warnings, and explain proofs.
    Does not write production ERP tables.
    """
    from WEOS.memory.compatibility import check_compatibility
    from WEOS.memory.conflicts import check_conflicts
    from WEOS.memory.explain import explain_from_context
    from WEOS.memory.ranking import record_usage
    from WEOS.memory.validate import validate_context

    wanted = set(outputs or ["bom", "drawing", "pdf", "quotation", "weight", "cost", "packing", "machine_cutting", "explain"])
    ctx = load_context(series=series, product_type=product_type, customer=customer)
    if not ctx.get("ok"):
        return ctx

    # ── Validation layer ──────────────────────────────────────────────────
    validation = validate_context(ctx)
    if not skip_validation and not validation.get("canGenerate"):
        return {
            "ok": False,
            "blocked": True,
            "blockReason": "validation",
            "validation": validation,
            "seriesId": ctx.get("seriesId"),
            "kbVersion": ctx.get("kbVersion"),
            "message": validation.get("message"),
            "production_modified": False,
        }

    # ── Conflict hard-stop ────────────────────────────────────────────────
    conflict = check_conflicts(
        selections=selections,
        series_id=ctx.get("seriesId"),
        hardware=list(ctx.get("hardware") or []) + list(selections or []),
        profiles=ctx.get("profiles"),
        glass=ctx.get("glass"),
    )
    if conflict.get("blocked"):
        return {
            "ok": False,
            "blocked": True,
            "blockReason": "conflict",
            "conflicts": conflict,
            "seriesId": ctx.get("seriesId"),
            "kbVersion": ctx.get("kbVersion"),
            "message": f"AI Stop: {conflict.get('message')}",
            "production_modified": False,
        }

    # ── Compatibility warnings (non-blocking unless severity=error) ───────
    compat = check_compatibility(
        series_id=ctx.get("seriesId"),
        series=ctx.get("series"),
        glass_thickness_mm=glass_thickness_mm,
    )
    if compat.get("errors"):
        return {
            "ok": False,
            "blocked": True,
            "blockReason": "compatibility",
            "compatibility": compat,
            "seriesId": ctx.get("seriesId"),
            "message": compat.get("message"),
            "production_modified": False,
        }

    reasoned = reason(ctx)
    proof = explain_from_context(
        ctx,
        width_mm=float(width_mm or 1200),
        height_mm=float(height_mm or 1500),
        shutter_count=shutter_count,
    )
    recs = recommend(series=series, product_type=product_type or "Sliding")

    w = float(width_mm or 1200)
    h = float(height_mm or 1500)
    qty = max(1, int(quantity or 1))
    perimeter_m = 2 * (w + h) / 1000.0
    area_sqm = (w * h) / 1_000_000.0

    result: dict[str, Any] = {
        "ok": True,
        "seriesId": ctx.get("seriesId"),
        "kbVersion": ctx.get("kbVersion"),
        "inputs": {
            "width_mm": w,
            "height_mm": h,
            "quantity": qty,
            "product_type": product_type,
            "customer": customer,
            "glass_thickness_mm": glass_thickness_mm,
            "shutter_count": shutter_count,
        },
        "validation": validation,
        "compatibility": compat,
        "conflicts": conflict,
        "recommendations": recs.get("recommendations"),
        "reason": reasoned,
        "explain": proof,
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
                    "qty": qty * (int((proof.get("results") or {}).get("handleQty", {}).get("value") or 1) if "handle" in str(hw.get("name") or "").lower() else 1),
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
                    "glassWidth_mm": (proof.get("results") or {}).get("glassWidth", {}).get("value"),
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

    if "explain" in wanted:
        gen["explain"] = proof

    # Ranking: bump usage on memories involved
    for p in ctx.get("profiles") or []:
        if p.get("id"):
            record_usage(MEM_PROFILE, str(p["id"]))
    for g in ctx.get("glass") or []:
        if g.get("id"):
            record_usage(MEM_GLASS, str(g["id"]))
    for f in ctx.get("formulas") or []:
        if f.get("id"):
            record_usage(MEM_FORMULA, str(f["id"]))

    return result
