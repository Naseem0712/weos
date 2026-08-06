"""AI Suggestions — engineering + commercial insights with one-click gated apply.

Suggestions only — never auto-applied to production.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from WEOS.learning.v2_store import ensure_v2_dirs, list_library


def _commercial_rows(limit: int = 400) -> list[dict[str, Any]]:
    try:
        from WEOS.learning.commercial_agent import _read_observations

        return _read_observations(limit=limit)
    except Exception:
        return []


def build_suggestions(*, series_id: str | None = None) -> dict[str, Any]:
    ensure_v2_dirs()
    hardware = list_library("hardware")
    glass = list_library("glass")
    profiles = list_library("profiles")
    patterns = list_library("quotation_patterns")
    formulas = list_library("formulas")
    rows = _commercial_rows()

    if series_id:
        hardware = [h for h in hardware if series_id in (h.get("compatibleSeries") or []) or not (h.get("compatibleSeries") or [])]
        glass = [g for g in glass if series_id in (g.get("compatibleProducts") or [])]
        profiles = [p for p in profiles if series_id in (p.get("compatibleSeries") or []) or p.get("seriesId") == series_id]

    handle_c: Counter[str] = Counter()
    glass_c: Counter[str] = Counter()
    colour_c: Counter[str] = Counter()
    margins: list[float] = []
    for r in rows:
        if r.get("glass"):
            glass_c[str(r["glass"])] += 1
        if r.get("colour"):
            colour_c[str(r["colour"])] += 1
        opts = r.get("options") or {}
        if isinstance(opts, dict) and opts.get("handle"):
            handle_c[str(opts["handle"])] += 1
        elif r.get("handle"):
            handle_c[str(r["handle"])] += 1
        if r.get("marginAmount") is not None and r.get("sellingAmount"):
            try:
                sell = float(r["sellingAmount"])
                if sell:
                    margins.append(float(r["marginAmount"]) / sell * 100.0)
            except Exception:
                pass

    hw_types = Counter(h.get("hardwareType") or h.get("name") or "?" for h in hardware)
    powder = Counter()
    for s in list_library("product_series"):
        if s.get("powderCoatingType"):
            powder[str(s["powderCoatingType"])[:60]] += 1

    format_tags = Counter()
    warranty_c: Counter[str] = Counter()
    payment_c: Counter[str] = Counter()
    for p in patterns:
        for t in p.get("formatTags") or []:
            format_tags[t] += 1
        if p.get("warranty"):
            warranty_c[str(p["warranty"])[:80]] += 1
        if p.get("paymentTerm"):
            payment_c[str(p["paymentTerm"])[:80]] += 1

    tips: list[str] = []

    def top(counter: Counter[str], label: str) -> None:
        if not counter:
            return
        k, n = counter.most_common(1)[0]
        tips.append(f"Most used {label}: {k} ({n}×)")

    top(handle_c, "handle")
    top(glass_c, "glass")
    top(colour_c, "colour")
    top(hw_types, "hardware type (library)")
    top(powder, "powder coating (series)")
    top(format_tags, "quote layout tag")
    top(warranty_c, "warranty phrasing")
    top(payment_c, "payment term")

    if margins:
        avg = sum(margins) / len(margins)
        tips.append(f"Average margin on observed quotes: {avg:.1f}%")
    else:
        tips.append("Avg margin: not enough quote observations yet — save quotes from Window Cart.")

    # Engineering + commercial enrichment
    eng_suggestions: list[dict[str, Any]] = []
    com_suggestions: list[dict[str, Any]] = []
    eng_tips: list[str] = []
    try:
        from WEOS.learning.engineering_agent import build_engineering_suggestions, engineering_insights

        eng = build_engineering_suggestions()
        eng_suggestions = list(eng.get("suggestions") or [])
        eng_tips = list((eng.get("insightsSummary") or {}).get("tips") or [])
        tips.extend(eng_tips[:3])
        if eng.get("insightsSummary", {}).get("avgWastePercent") is not None:
            tips.append(f"Observed Al cut waste ~{eng['insightsSummary']['avgWastePercent']}%")
        else:
            tips.append("Average waste %: calculate with optimize to learn cut waste.")
    except Exception as exc:
        tips.append(f"Engineering suggestions unavailable: {exc}")

    try:
        from WEOS.learning.commercial_agent import commercial_suggestions

        com = commercial_suggestions()
        com_suggestions = list(com.get("suggestions") or [])
        tips.extend(list((com.get("intelligence") or {}).get("tips") or [])[:2])
    except Exception as exc:
        tips.append(f"Commercial suggestions unavailable: {exc}")

    actionable = [s for s in eng_suggestions if s.get("oneClick")][:15]
    actionable += [s for s in com_suggestions if s.get("oneClick")][:10]

    return {
        "status": "suggestions_only",
        "seriesId": series_id,
        "tips": tips,
        "counts": {
            "hardwareLibrary": len(hardware),
            "glassLibrary": len(glass),
            "profilesLibrary": len(profiles),
            "quotationPatterns": len(patterns),
            "formulas": len(formulas),
            "commercialObservations": len(rows),
            "engineeringSuggestions": len(eng_suggestions),
            "commercialSuggestions": len(com_suggestions),
        },
        "mostUsed": {
            "handle": handle_c.most_common(3),
            "glass": glass_c.most_common(3),
            "colour": colour_c.most_common(3),
            "hardwareType": hw_types.most_common(5),
            "formatTags": format_tags.most_common(5),
            "warranty": warranty_c.most_common(3),
            "payment": payment_c.most_common(3),
        },
        "actionable": actionable,
        "engineering": eng_suggestions[:20],
        "commercial": com_suggestions[:20],
        "message": "Suggestions only — admin one-click queues Pending Review (engineering) or returns quote prefs (commercial). Nothing auto-applies to production.",
    }


def apply_suggestion(
    *,
    suggestion_id: str,
    domain: str | None = None,
    suggestion: dict[str, Any] | None = None,
    applied_by: str = "admin",
) -> dict[str, Any]:
    """Gated one-click apply.

    engineering → pending V2 proposal
    commercial (dealer/architect) → returns settings for UI; no production write
    """
    sug = dict(suggestion or {})
    if not sug:
        bundled = build_suggestions()
        for bucket in ("actionable", "engineering", "commercial"):
            for s in bundled.get(bucket) or []:
                if s.get("id") == suggestion_id:
                    sug = s
                    break
            if sug:
                break
    if not sug:
        raise ValueError(f"Unknown suggestion: {suggestion_id}")

    dom = (domain or sug.get("domain") or "engineering").lower()
    if dom == "engineering" or sug.get("action", "").startswith("queue_"):
        from WEOS.learning.engineering_agent import apply_engineering_suggestion

        return apply_engineering_suggestion(sug, applied_by=applied_by)

    # Commercial: return payload for client / optional memory note
    return {
        "ok": True,
        "queued": False,
        "applied": False,
        "domain": "commercial",
        "settings": sug.get("payload") or {},
        "suggestion": {"id": sug.get("id"), "title": sug.get("title"), "action": sug.get("action")},
        "message": "Commercial preference returned — apply on quote only after user confirms. Production engineering unchanged.",
    }
