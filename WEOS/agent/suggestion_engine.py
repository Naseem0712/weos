"""Live Suggestion Engine (Part 4 + Part 5).

Turns a live Quote Context into concrete suggestions/warnings/recommendations,
each carrying: type, message, reason, source, confidence, action, why, status.

Every rule is traceable — the ``why`` block records the formula / approved rule
version behind the recommendation so the UI "Why?" button can explain it.

Rules here are deterministic engineering/commercial heuristics. Approved
series-specific constraints are pulled (best-effort) from the Engineering Brain
so the same approved Knowledge Base drives the live panel.
"""

from __future__ import annotations

import re
from typing import Any

# Approved rule versions — bump when the underlying approved rule changes.
RULE_HANDLES_PER_SHUTTER = "handles_per_shutter@v1"
RULE_GLASS_THICKNESS = "glass_thickness_approved@v1"
RULE_GLASS_SIZING = "glass_sizing_formula@v1"
RULE_TRACK_SHUTTER = "track_vs_shutter@v1"

# Fallback approved glass thicknesses (mm) when the Brain has no series rule.
DEFAULT_APPROVED_GLASS_MM = [5, 6, 8]


def _num(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _mm(val: Any) -> str:
    n = _num(val)
    if n is None:
        return "?mm"
    return f"{int(n) if float(n).is_integer() else n}mm"


def _glass_thickness_mm(glass: Any) -> float | None:
    """Extract a numeric thickness from many glass shapes (string / dict / list)."""
    if glass is None:
        return None
    if isinstance(glass, (int, float)):
        return float(glass)
    if isinstance(glass, str):
        m = re.search(r"(\d+(?:\.\d+)?)\s*mm", glass.lower())
        if m:
            return float(m.group(1))
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*$", glass)
        return float(m.group(1)) if m else None
    if isinstance(glass, dict):
        for k in ("thicknessMm", "overallMm", "thickness"):
            if glass.get(k) is not None:
                return _num(glass[k])
        return _glass_thickness_mm(glass.get("name"))
    if isinstance(glass, list) and glass:
        for g in glass:
            t = _glass_thickness_mm(g)
            if t is not None:
                return t
    return None


def brain_glass_warning(series: str | None, glass_mm: float) -> dict[str, Any] | None:
    """Ask the Engineering Brain if this glass thickness violates an approved rule.

    Returns the first approved-compatibility warning (with its ``allowed`` list
    and message) or None. This reuses the approved Knowledge Base directly.
    """
    if not series:
        return None
    try:
        from WEOS.brain import check_series_compatibility

        res = check_series_compatibility(series=series, glass_thickness_mm=glass_mm)
        for w in res.get("warnings") or []:
            if isinstance(w, dict) and str(w.get("field") or "").startswith("glass"):
                return w
    except Exception:
        pass
    return None


def _shutter_count(ctx: dict[str, Any]) -> int | None:
    for key in ("shutterCount", "shutter_count", "glassShutters", "shutters"):
        v = ctx.get(key)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


def _handle_qty(ctx: dict[str, Any]) -> float | None:
    hardware = ctx.get("hardware")
    if isinstance(hardware, list):
        for h in hardware:
            if isinstance(h, dict) and "handle" in str(h.get("name") or h.get("category") or "").lower():
                return _num(h.get("qty"))
    return None


def explain_glass_size(ctx: dict[str, Any]) -> dict[str, Any]:
    """The traceable 'Why?' for glass sizing (Part 5).

    Glass width = inner opening + 2×handle/frame engagement + interlock overlap.
    Uses the real glass-sizing engine when profile insertion is provided.
    """
    width = _num(ctx.get("width")) or 0.0
    engagement = _num((ctx.get("glassRules") or {}).get("engagementMm")) or 12.0
    interlock = _num(ctx.get("interlockOverlapMm")) or 20.0
    try:
        from WEOS.factory.glass_sizing import compute_glass_size, insertion_from_profile

        insertion = insertion_from_profile(ctx.get("glassRules") or {"glassInsertion": {"sameAllSides": True, "engagementMm": engagement}})
        res = compute_glass_size(width or 650, _num(ctx.get("height")) or 1700, insertion=insertion)
        return {
            "ruleVersion": RULE_GLASS_SIZING,
            "source": "approved glass-sizing formula",
            "formula": "glassWidth = innerOpening + engagement(both sides) + interlockOverlap",
            "inputs": {"innerOpeningMm": width, "engagementMm": engagement, "interlockOverlapMm": interlock},
            "result": {"glassWidthMm": res.get("glassWidthMm"), "glassHeightMm": res.get("glassHeightMm")},
            "derivation": res.get("derivation"),
        }
    except Exception:
        glass_w = width + 2 * engagement + interlock
        return {
            "ruleVersion": RULE_GLASS_SIZING,
            "source": "approved glass-sizing formula",
            "formula": "glassWidth = innerOpening + 2×engagement + interlockOverlap",
            "inputs": {"innerOpeningMm": width, "engagementMm": engagement, "interlockOverlapMm": interlock},
            "result": {"glassWidthMm": round(glass_w, 1)},
        }


def generate(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Produce live suggestions for a quote context."""
    out: list[dict[str, Any]] = []
    product = ctx.get("product")
    series = ctx.get("series") or ctx.get("sectionSeries")
    shutters = _shutter_count(ctx)
    glass_mm = _glass_thickness_mm(ctx.get("glass"))

    # ── Rule 1: handles per shutter ──────────────────────────────────────────
    if shutters and shutters > 0:
        required = shutters
        current = _handle_qty(ctx)
        if current is None or int(current) != required:
            out.append(
                {
                    "key": "handles_per_shutter",
                    "type": "warning" if current is not None else "recommendation",
                    "message": f"{shutters} shutters → {required} handles required",
                    "reason": "Approved rule: 1 handle per shutter.",
                    "source": "approved rule",
                    "confidence": 0.95,
                    "action": "apply_handles",
                    "why": {
                        "ruleVersion": RULE_HANDLES_PER_SHUTTER,
                        "formula": "handles = shutterCount",
                        "inputs": {"shutterCount": shutters, "currentHandles": current},
                        "result": {"requiredHandles": required},
                    },
                    "data": {"requiredHandles": required, "field": "hardware.handle.qty"},
                }
            )

    # ── Rule 2: glass thickness approved for series ──────────────────────────
    if glass_mm is not None:
        # Prefer the approved Brain compatibility rule; fall back to a baseline set.
        bw = brain_glass_warning(series, glass_mm)
        if bw is not None:
            approved = [float(x) for x in (bw.get("allowed") or []) if _num(x) is not None] or list(DEFAULT_APPROVED_GLASS_MM)
            source = f"approved compatibility rule (series {series})"
            message = bw.get("message") or f"{_mm(glass_mm)} glass not approved for this series"
            emit = True
        else:
            approved = list(DEFAULT_APPROVED_GLASS_MM)
            source = "approved glass baseline rule"
            emit = glass_mm not in approved
            supported = "/".join(_mm(x) for x in approved)
            message = f"{_mm(glass_mm)} glass not approved for this series (supports {supported})"
        if emit:
            out.append(
                {
                    "key": "glass_thickness_approved",
                    "type": "warning",
                    "message": message,
                    "reason": f"Selected glass thickness is outside the approved set for {series or product}.",
                    "source": source,
                    "confidence": 0.85,
                    "action": "change_glass",
                    "why": {
                        "ruleVersion": RULE_GLASS_THICKNESS,
                        "formula": "selectedThickness ∈ approvedThicknesses",
                        "inputs": {"selectedMm": glass_mm, "approvedMm": approved},
                        "result": {"approved": False},
                    },
                    "data": {"approvedMm": approved, "selectedMm": glass_mm},
                }
            )

    # ── Rule 3: track vs shutter sanity ──────────────────────────────────────
    track = _num(ctx.get("trackCount"))
    if track and shutters:
        max_shutters = int(track) * 2
        if shutters > max_shutters:
            out.append(
                {
                    "key": "track_vs_shutter",
                    "type": "warning",
                    "message": f"{shutters} shutters on {int(track)} track(s) — max {max_shutters} for this track count",
                    "reason": "Approved rule: each track carries up to 2 shutters.",
                    "source": "approved rule",
                    "confidence": 0.8,
                    "action": "review_tracks",
                    "why": {
                        "ruleVersion": RULE_TRACK_SHUTTER,
                        "formula": "maxShutters = trackCount × 2",
                        "inputs": {"trackCount": track, "shutterCount": shutters},
                        "result": {"maxShutters": max_shutters},
                    },
                    "data": {"trackCount": track, "shutterCount": shutters},
                }
            )

    # ── Rule 4: material optimization hint ───────────────────────────────────
    w = _num(ctx.get("width"))
    h = _num(ctx.get("height"))
    if w and h:
        area_m2 = (w * h) / 1_000_000.0
        if area_m2 >= 4.5:
            out.append(
                {
                    "key": "heavy_section_hint",
                    "type": "recommendation",
                    "message": f"Large opening ({area_m2:.1f} m²) — consider a heavy-duty section/track for deflection safety",
                    "reason": "Large sliding leaves deflect; heavier interlock/track recommended above ~4.5 m².",
                    "source": "engineering heuristic",
                    "confidence": 0.55,
                    "action": "review_section",
                    "why": {
                        "formula": "area = width × height",
                        "inputs": {"widthMm": w, "heightMm": h},
                        "result": {"areaM2": round(area_m2, 2), "thresholdM2": 4.5},
                    },
                    "data": {"areaM2": round(area_m2, 2)},
                }
            )

    # ── Rule 5: glass-sizing explanation (always available) ──────────────────
    if w:
        gexpl = explain_glass_size(ctx)
        out.append(
            {
                "key": "glass_sizing",
                "type": "info",
                "message": "Glass size derived from inner opening + engagement + interlock overlap",
                "reason": "Cutting size must include profile engagement so glass seats correctly.",
                "source": gexpl.get("source"),
                "confidence": 0.9,
                "action": "explain",
                "why": gexpl,
                "data": gexpl.get("result") or {},
            }
        )

    return out
