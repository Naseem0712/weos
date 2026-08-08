"""Glass sizing from profile insertion depth (Part 4).

The visible clear opening is not the glass size: glass sits *inside* the profile
groove, so it is larger than the daylight opening by the engagement depth on each
side, minus any edge clearance/gap. Users configure how much the glass goes into
the profile, on which side, and separately for the vertical vs horizontal edges.

This module never guesses magic numbers — every deduction/addition is an explicit
input carried on the profile JSON (``glassInsertion`` block) or passed in. It also
returns a human-readable derivation so it can feed the Explain / proof engine.
"""

from __future__ import annotations

from typing import Any, Mapping


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def insertion_from_profile(glass_rules: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract a normalized insertion spec from a profile's glass rules.

    Recognized ``glassInsertion`` keys (all optional, mm):
      - sameAllSides: bool
      - engagementMm: uniform engagement when sameAllSides
      - horizontalEngagementMm / verticalEngagementMm: per-axis engagement
      - left/right/top/bottom EngagementMm: per-side engagement
      - edgeClearanceMm: uniform clearance/gap subtracted per side
      - <side>ClearanceMm: per-side clearance
    Falls back to legacy overlap keys (handleSideOverlap, etc.) if present.
    """
    g = dict(glass_rules or {})
    ins = dict(g.get("glassInsertion") or {})

    same = bool(ins.get("sameAllSides"))
    uniform = _f(ins.get("engagementMm"))
    horiz = _f(ins.get("horizontalEngagementMm"), uniform if same else 0.0)
    vert = _f(ins.get("verticalEngagementMm"), uniform if same else 0.0)

    def side(name: str, axis_default: float) -> float:
        return _f(ins.get(f"{name}EngagementMm"), axis_default)

    left = side("left", horiz)
    right = side("right", horiz)
    top = side("top", vert)
    bottom = side("bottom", vert)

    clr_uniform = _f(ins.get("edgeClearanceMm"))
    clr = {
        "left": _f(ins.get("leftClearanceMm"), clr_uniform),
        "right": _f(ins.get("rightClearanceMm"), clr_uniform),
        "top": _f(ins.get("topClearanceMm"), clr_uniform),
        "bottom": _f(ins.get("bottomClearanceMm"), clr_uniform),
    }

    # Legacy fallback: reuse existing per-side overlaps as engagement if nothing set.
    if not ins:
        left = _f(g.get("interlockSideOverlap"))
        right = _f(g.get("handleSideOverlap"))
        top = _f(g.get("topOverlap"))
        bottom = _f(g.get("bottomOverlap"))

    return {
        "engagement": {"left": left, "right": right, "top": top, "bottom": bottom},
        "clearance": clr,
        "interlockOverlapMm": _f(ins.get("interlockOverlapMm"), _f(g.get("interlockSideOverlap"))),
        "raw": ins,
    }


def compute_glass_size(
    clear_width_mm: float,
    clear_height_mm: float,
    *,
    insertion: Mapping[str, Any] | None = None,
    interlock_left: bool = False,
    interlock_right: bool = False,
    label: str = "glass",
) -> dict[str, Any]:
    """Return accurate glass width/height from the clear opening + insertion.

    glass_width  = clear_width  + left_net + right_net (+interlock overlaps)
    glass_height = clear_height + top_net + bottom_net
    where side_net = engagement - clearance for that side.
    """
    spec = dict(insertion or {})
    eng = dict(spec.get("engagement") or {})
    clr = dict(spec.get("clearance") or {})
    interlock = _f(spec.get("interlockOverlapMm"))

    def net(sidename: str) -> float:
        return _f(eng.get(sidename)) - _f(clr.get(sidename))

    left_net = net("left")
    right_net = net("right")
    top_net = net("top")
    bottom_net = net("bottom")

    steps: list[dict[str, Any]] = []
    gw = float(clear_width_mm)
    steps.append({"step": "clear opening width", "value": round(gw, 2)})
    gw += left_net
    steps.append({"step": f"+ left engagement/clearance ({left_net:+.1f})", "value": round(gw, 2)})
    gw += right_net
    steps.append({"step": f"+ right engagement/clearance ({right_net:+.1f})", "value": round(gw, 2)})

    interlock_add = 0.0
    if interlock_left:
        interlock_add += interlock
    if interlock_right:
        interlock_add += interlock
    if interlock_add:
        gw += interlock_add
        steps.append({"step": f"+ interlock overlap ({interlock_add:+.1f})", "value": round(gw, 2)})

    gh = float(clear_height_mm)
    steps.append({"step": "clear opening height", "value": round(gh, 2)})
    gh += top_net
    steps.append({"step": f"+ top engagement/clearance ({top_net:+.1f})", "value": round(gh, 2)})
    gh += bottom_net
    steps.append({"step": f"+ bottom engagement/clearance ({bottom_net:+.1f})", "value": round(gh, 2)})

    area_m2 = (gw / 1000.0) * (gh / 1000.0)
    return {
        "label": label,
        "clearWidthMm": round(float(clear_width_mm), 2),
        "clearHeightMm": round(float(clear_height_mm), 2),
        "glassWidthMm": round(gw, 2),
        "glassHeightMm": round(gh, 2),
        "areaM2": round(area_m2, 4),
        "areaSqft": round(area_m2 * 10.7639, 4),
        "deductions": {
            "leftNetMm": round(left_net, 2),
            "rightNetMm": round(right_net, 2),
            "topNetMm": round(top_net, 2),
            "bottomNetMm": round(bottom_net, 2),
            "interlockOverlapMm": round(interlock_add, 2),
        },
        "derivation": steps,
        "explanation": (
            f"Glass {label}: {round(gw, 1)} × {round(gh, 1)} mm "
            f"= clear {round(float(clear_width_mm), 1)} × {round(float(clear_height_mm), 1)} mm "
            f"adjusted by profile insertion (L{left_net:+.1f} R{right_net:+.1f} "
            f"T{top_net:+.1f} B{bottom_net:+.1f}, interlock {interlock_add:+.1f})."
        ),
    }


def preview_from_profile(
    glass_rules: Mapping[str, Any] | None,
    *,
    clear_width_mm: float,
    clear_height_mm: float,
    interlock_left: bool = False,
    interlock_right: bool = False,
    label: str = "glass",
) -> dict[str, Any]:
    """Convenience: derive insertion from a profile block, then size the glass."""
    ins = insertion_from_profile(glass_rules)
    result = compute_glass_size(
        clear_width_mm,
        clear_height_mm,
        insertion=ins,
        interlock_left=interlock_left,
        interlock_right=interlock_right,
        label=label,
    )
    result["insertion"] = ins
    return result
