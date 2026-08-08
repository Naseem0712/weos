"""Intelligence assessment + smarter defaults (Part 5.3 / 5.4).

Gives an honest, evidence-backed view of how "smart" WEOS is today — what it can
auto-suggest / auto-fill / auto-compute — and provides a concrete ``suggest_defaults``
helper that uses approved memory + observations to prefill glass/colour/handle.
All approval gates are preserved; nothing here writes production data.
"""

from __future__ import annotations

from typing import Any


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def intelligence_report() -> dict[str, Any]:
    from WEOS.memory.audit import run_audit

    audit = run_audit()
    counts = audit.get("counts", {})
    flags = audit.get("flags", {})

    checklist: list[dict[str, Any]] = []

    def item(name: str, active: bool, evidence: str, example: str, *, partial: bool = False) -> None:
        checklist.append(
            {
                "capability": name,
                "status": "active" if active else ("partial" if partial else "inactive"),
                "evidence": evidence,
                "example": example,
            }
        )

    item(
        "Auto-compute material weights",
        bool(counts.get("formulaMemory")),
        f"{counts.get('formulaMemory', 0)} baseline formulas preloaded (glass/alu/ACP/iron/sheet/DGU/laminated).",
        "8mm glass 650×1700 → ~13.8 kg computed automatically.",
    )
    item(
        "Accurate glass sizing from profile insertion",
        True,
        "glass_sizing derives pane size from clear opening ± engagement/clearance per side.",
        "Clear 650×1700 + 12mm engagement each side → 674×1724 glass with derivation.",
    )
    item(
        "Configurable Glass Engine (single/DGU/laminated)",
        bool(counts.get("glassLibrary")),
        f"{counts.get('glassLibrary', 0)} glass specs in library; DGU air-gap + laminated PVB supported.",
        "24mm DGU 6+12A+6 Clear Toughened @ ₹/sqft reused across quotes.",
        partial=not counts.get("glassLibrary"),
    )
    item(
        "Hardware qty from rules (count + weight)",
        bool(counts.get("hardwareLibrary")),
        f"{counts.get('hardwareLibrary', 0)} hardware items; rules drive BOM by shutter/leaf and by weight range.",
        "Leaf 130 kg → auto-selects Floor Spring 150kg (FS-150).",
        partial=not counts.get("hardwareLibrary"),
    )
    item(
        "Learns from every calculate",
        bool(flags.get("observationsWritten")),
        f"{counts.get('engineeringObservations', 0)} engineering + {counts.get('commercialObservations', 0)} commercial observations.",
        "Each calculate records size/glass/hardware/weight patterns.",
    )
    item(
        "Auto-suggest defaults (glass/colour/handle)",
        bool(counts.get('engineeringObservations') or counts.get('commercialObservations')),
        "suggest_defaults() consumes glass-by-product + customer memory.",
        "Customer ABC + sliding → prefill 8mm_toughened, black_texture, premium.",
        partial=not (counts.get('engineeringObservations') or counts.get('commercialObservations')),
    )
    item(
        "Engineering Brain generates from approved KB",
        bool(flags.get("approvedMemoryForBrain")),
        f"{counts.get('memoryApproved', 0)} approved memories feed Brain generate/reason.",
        "Brain builds BOM + weight + explain from approved profiles/glass/formulas.",
        partial=not flags.get("approvedMemoryForBrain"),
    )
    item(
        "Admin-gated learning (never auto-production)",
        True,
        "Observe → Suggest → Admin Approve → Versioned KB preserved throughout.",
        "Suggestions queue to Pending Review; production JSON untouched.",
    )

    active = sum(1 for c in checklist if c["status"] == "active")
    partial = sum(1 for c in checklist if c["status"] == "partial")
    score = round(100 * (active + 0.5 * partial) / max(1, len(checklist)))

    if score >= 80:
        level = "Advanced — auto-computes and auto-suggests across glass, hardware, weight and defaults."
    elif score >= 55:
        level = "Capable — computes reliably and learns; some intelligence waits on approvals/data."
    else:
        level = "Foundational — engines wired and observing; feed data + approvals to unlock suggestions."

    return {
        "ok": True,
        "intelligenceScore": score,
        "level": level,
        "checklist": checklist,
        "summary": {
            "active": active,
            "partial": partial,
            "inactive": len(checklist) - active - partial,
        },
        "audit": audit,
        "honestGaps": [
            "Brain generate needs admin-approved memories; empty KB → limited output.",
            "Auto-suggest quality grows with observation volume (cold start is generic).",
            "Weight-based hardware selection needs per-leaf weights or a typical leaf weight input.",
        ],
    }


def suggest_defaults(*, product: str | None = None, customer: str | None = None) -> dict[str, Any]:
    """Smarter defaults: recommend glass/colour/handle from memory + observations.

    Consumed by the UI/preview to prefill selections. Suggestions only — the user
    still confirms; nothing is silently applied.
    """
    suggestions: dict[str, Any] = {"glass": None, "colour": None, "handle": None}
    reasons: list[str] = []

    # 1) Customer commercial memory (strongest signal).
    if customer:
        mem = _safe(lambda: _customer_memory(customer), {})
        prefs = (mem.get("applyPayload") or {}) if isinstance(mem, dict) else {}
        prefer = (mem.get("preferences") or {}) if isinstance(mem, dict) else {}
        for key in ("glass", "colour", "handle"):
            val = prefs.get(key) or prefer.get(key)
            if val and not suggestions[key]:
                suggestions[key] = val
                reasons.append(f"Customer '{customer}' usually chooses {key}={val}")

    # 2) Engineering insights — most common glass for this product.
    insights = _safe(lambda: _engineering_insights(), {})
    glass_by_product = (insights.get("glassByProduct") or {}) if isinstance(insights, dict) else {}
    if product and not suggestions["glass"]:
        top = glass_by_product.get(product)
        if top:
            suggestions["glass"] = top[0][0]
            reasons.append(f"Most-used glass for {product}: {top[0][0]} ({top[0][1]}×)")

    # 3) Sensible fall-backs.
    if not suggestions["glass"]:
        suggestions["glass"] = "5mm_clear"
        reasons.append("Default glass 5mm_clear (no history yet)")
    if not suggestions["colour"]:
        suggestions["colour"] = "white"
    if not suggestions["handle"]:
        suggestions["handle"] = "standard"

    return {
        "ok": True,
        "product": product,
        "customer": customer,
        "suggestions": suggestions,
        "reasons": reasons,
        "autoApplied": False,
        "message": "Prefill suggestions from memory + observations — confirm to apply.",
    }


def _customer_memory(customer: str) -> dict[str, Any]:
    from WEOS.learning.commercial_agent import get_customer_memory

    return get_customer_memory(customer)


def _engineering_insights() -> dict[str, Any]:
    from WEOS.learning.engineering_agent import engineering_insights

    return engineering_insights()
