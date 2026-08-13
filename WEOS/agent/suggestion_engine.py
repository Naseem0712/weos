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

    # ── Rule 6: missing material weights (Universal Weight Engine + KB recall) ─
    weight_items = _collect_weight_items(ctx)
    if weight_items:
        try:
            from WEOS.factory.weight_engine import analyze_missing_weights

            report = analyze_missing_weights(weight_items)
            n = int(report.get("missingCount") or 0)
            if n > 0:
                m = int(report.get("calculableCount") or 0)
                k = int(report.get("needsCatalogueCount") or 0)
                fx = None
                try:
                    from WEOS.learning.material_formulas import recall_formula_for_context

                    fx = recall_formula_for_context(
                        material=str(ctx.get("material") or ctx.get("sectionSeries") or ""),
                        glass_makeup=str((ctx.get("glassMakeup") or ctx.get("glassType") or "")),
                        product=str(product or ""),
                    )
                except Exception:
                    fx = None
                msg = report.get("summary") or (
                    f"⚠️ {n} items have no weight data. {m} can be calculated from available dimensions. "
                    f"{k} requires catalogue weight."
                )
                if fx and fx.get("id"):
                    msg += f" Recalled KB formula {fx.get('id')} ({fx.get('name')}) — Review → Approve before production."
                out.append(
                    {
                        "key": "missing_weights",
                        "type": "warning",
                        "message": msg,
                        "reason": "Weight Source must be Catalogue, Manual, or Calculated — never guessed. Learned weights stay pending until admin approve.",
                        "source": "universal weight engine + formula memory",
                        "confidence": 0.9,
                        "action": "calculate_weights" if report.get("offerCalculateNow") else "add_catalogue_weight",
                        "why": {
                            "formula": (fx or {}).get("expression")
                            or "priority: catalogue/manual → calculated (dims×density) → unknown",
                            "formulaId": (fx or {}).get("id"),
                            "formulaName": (fx or {}).get("name"),
                            "inputs": {
                                "missingCount": n,
                                "calculableCount": m,
                                "needsCatalogueCount": k,
                            },
                            "result": {
                                "offerCalculateNow": report.get("offerCalculateNow"),
                                "calculatePrompt": report.get("calculatePrompt"),
                            },
                            "weightSources": ["Catalogue", "Manual", "Calculated", "Missing"],
                            "safety": "Learned candidates require Review → Approve. Never auto-applied.",
                        },
                        "data": {
                            "missingCount": n,
                            "calculableCount": m,
                            "needsCatalogueCount": k,
                            "offerCalculateNow": report.get("offerCalculateNow"),
                            "calculatePrompt": report.get("calculatePrompt"),
                            "recalledFormulaId": (fx or {}).get("id"),
                        },
                    }
                )
        except Exception:
            pass

    # ── Rule 7: mesh requires 2.5 / 3-track ────────────────────────────────
    for ln in _iter_quote_lines(ctx):
        mesh = _line_has_mesh(ln)
        track = _num(ln.get("trackCount") if ln.get("trackCount") is not None else ctx.get("trackCount"))
        if mesh and track is not None and track < 2.5:
            out.append(
                {
                    "key": "mesh_requires_3_track",
                    "type": "warning",
                    "message": "Mesh shutter needs 2.5-track or 3-track (2-track has no mesh sash room)",
                    "reason": "Approved layout rule: mesh on 2-track auto-shifts to 3-track when available.",
                    "source": "approved layout rule",
                    "confidence": 0.92,
                    "action": "shift_mesh_track",
                    "why": {
                        "ruleVersion": "mesh_track@v1",
                        "formula": "mesh ⇒ trackCount ≥ 2.5 (prefer 3)",
                        "inputs": {"mesh": True, "trackCount": track},
                        "result": {"suggestedTrackCount": 3.0},
                    },
                    "data": {"suggestedTrackCount": 3.0, "currentTrackCount": track},
                }
            )
            break

    # ── Rule 8: missing selling rates on quote lines ────────────────────────
    missing_rate_n = 0
    for ln in _iter_quote_lines(ctx):
        if _line_missing_rate(ln):
            missing_rate_n += 1
    if missing_rate_n:
        out.append(
            {
                "key": "missing_rates",
                "type": "warning",
                "message": f"{missing_rate_n} line(s) missing selling rate — quote value / PDF totals will be incomplete",
                "reason": "Each commercial line needs a selling rate (₹/sqft, ₹/rft, or ₹/nos) before approval.",
                "source": "commercial quote check",
                "confidence": 0.88,
                "action": "add_selling_rate",
                "why": {
                    "formula": "lineAmount = sellingRate × qtyBasis",
                    "inputs": {"missingRateLines": missing_rate_n},
                    "result": {"complete": False},
                },
                "data": {"missingRateLines": missing_rate_n},
            }
        )

    return out


def _iter_quote_lines(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    lines = ctx.get("lines")
    if isinstance(lines, list) and lines:
        return [ln for ln in lines if isinstance(ln, dict)]
    if isinstance(ctx.get("product"), str) or ctx.get("width") is not None:
        return [ctx]
    return []


def _line_has_mesh(ln: dict[str, Any]) -> bool:
    if ln.get("mesh") in (True, 1, "1", "true", "yes"):
        return True
    opts = ln.get("options") if isinstance(ln.get("options"), dict) else {}
    if opts.get("mesh") in (True, 1, "1", "true", "yes"):
        return True
    layout = ln.get("layout") if isinstance(ln.get("layout"), dict) else {}
    return layout.get("mesh") in (True, 1, "1", "true", "yes")


def _line_missing_rate(ln: dict[str, Any]) -> bool:
    for key in ("sellingRate", "saleRate", "rate"):
        if ln.get(key) not in (None, "", 0, "0"):
            return False
    price = ln.get("price") if isinstance(ln.get("price"), dict) else {}
    if price.get("rate") not in (None, "", 0, "0"):
        return False
    opts = ln.get("options") if isinstance(ln.get("options"), dict) else {}
    cq = opts.get("commercial") or opts.get("railingQuote") or {}
    if isinstance(cq, dict) and cq.get("sellingRatePerUnit") not in (None, "", 0, "0"):
        return False
    return True


def _collect_weight_items(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull BOM / materials / glass rows from a live quote context."""
    items: list[dict[str, Any]] = []
    for key in ("bom", "materials", "bomDetails", "items"):
        block = ctx.get(key)
        if isinstance(block, list):
            for row in block:
                if isinstance(row, dict):
                    items.append(row)
    glass = ctx.get("glass")
    if isinstance(glass, list):
        for g in glass:
            if isinstance(g, dict):
                items.append(
                    {
                        "name": g.get("name") or "glass",
                        "material": "glass",
                        "category": "glass",
                        "widthMm": g.get("widthMm") or g.get("width_mm"),
                        "heightMm": g.get("heightMm") or g.get("height_mm"),
                        "thicknessMm": g.get("thicknessMm") or g.get("thickness_mm"),
                        "quantity": g.get("quantity") or g.get("qty") or 1,
                        "weightKg": g.get("weightKg") or g.get("weight_kg"),
                        "unit": "pcs",
                    }
                )
    calc = ctx.get("calculation") or ctx.get("result") or {}
    if isinstance(calc, dict):
        for key in ("bom", "materials"):
            block = calc.get(key)
            if isinstance(block, list):
                for row in block:
                    if isinstance(row, dict):
                        items.append(row)
    return items
