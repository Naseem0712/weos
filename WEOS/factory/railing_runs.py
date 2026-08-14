"""Multi-run railing design: floor-by-floor stairs + span-by-span balcony.

Two size methods (stairs):
  * slope — tape length on the slope + floor height → horizontal run
  * steps — tread × riser × qty → floor height + slope + horizontal

Normal railing: each row is a span; turn left/right at a 90° or 180° band
before the next row. Glass divide suggestions default to max 2440 mm/panel
but the user may pick a larger split.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

DEFAULT_MAX_GLASS_MM = 2440.0
DEFAULT_GLASS_GAP_MM = 12.0
GLASS_EDGE_INSET_MM = 100.0
MM_PER_FT = 304.8
MM_PER_M = 1000.0


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def auto_panel_count(
    length_mm: float,
    *,
    max_mm: float = DEFAULT_MAX_GLASS_MM,
    gap: float = DEFAULT_GLASS_GAP_MM,
    edge: float = GLASS_EDGE_INSET_MM,
) -> int:
    """Fewest panels so each stays ≤ max_mm (user may still choose fewer/larger)."""
    usable = max(_f(length_mm) - 2.0 * _f(edge), 0.0)
    cap = max(_f(max_mm, DEFAULT_MAX_GLASS_MM), 1.0)
    g = max(_f(gap, DEFAULT_GLASS_GAP_MM), 0.0)
    if usable <= 0:
        return 1
    return max(1, int(math.ceil((usable + g) / (cap + g))))


def suggest_glass_divides(
    length_mm: float,
    *,
    gap: float = DEFAULT_GLASS_GAP_MM,
    edge: float = GLASS_EDGE_INSET_MM,
    max_mm: float = DEFAULT_MAX_GLASS_MM,
    extra: int = 4,
) -> list[dict[str, Any]]:
    """Clickable splits: 1 glass = X mm, 2 glass = Y mm, … (oversize flagged)."""
    L = max(_f(length_mm), 0.0)
    g = max(_f(gap, DEFAULT_GLASS_GAP_MM), 0.0)
    e = max(_f(edge, 0.0), 0.0)
    usable = max(L - 2.0 * e, 0.0)
    cap = max(_f(max_mm, DEFAULT_MAX_GLASS_MM), 1.0)
    n_fit = auto_panel_count(L, max_mm=cap, gap=g, edge=e)
    n_max = max(n_fit + extra, 4)
    out: list[dict[str, Any]] = []
    for n in range(1, n_max + 1):
        each = (usable - g * max(n - 1, 0)) / n if n else 0.0
        if each <= 1:
            continue
        out.append({
            "panels": n,
            "eachMm": int(round(each)),
            "overMax": each > cap + 0.5,
            "recommended": n == n_fit,
            "label": f"{n} glass · {int(round(each))} mm each"
            + (" · over 2440" if each > cap + 0.5 else ""),
        })
    return out


def _signed_turn(turn: Any, turn_deg: Any, *, last: bool, stairs: bool = False) -> float:
    if last:
        return 0.0
    side = str(turn or "").strip().lower()
    default_deg = 180.0 if stairs else 90.0
    deg = abs(_f(turn_deg, default_deg))
    if deg < 1:
        deg = default_deg
    if side in ("none", "end", "stop", ""):
        return 0.0
    if side in ("right", "r", "cw"):
        return -deg
    return deg  # left / default


def resolve_railing_run(raw: Mapping[str, Any] | None, *, stairs: bool = False) -> dict[str, Any]:
    """Fill length / floor height from slope-tape or step geometry."""
    src = dict(raw) if isinstance(raw, Mapping) else {}
    method = str(src.get("sizeMethod") or src.get("method") or "").strip().lower()
    if method in ("step", "treads", "riser"):
        method = "steps"
    if method in ("tape", "slope_tape", "sloping"):
        method = "slope"
    if method in ("length", "size", "mm"):
        method = "direct"

    riser = _f(src.get("riserMm") or src.get("stairRiseMm") or src.get("stepHeightMm"), 180.0)
    tread = _f(src.get("treadMm") or src.get("stairRunMm") or src.get("stepDepthMm"), 305.0)
    steps = _i(src.get("steps") or src.get("stairSteps") or src.get("stepQty"), 0)
    floor_h = _f(src.get("floorHeightMm") or src.get("floorH") or src.get("riseMm"), 0.0)
    slope = _f(src.get("slopeLengthMm") or src.get("slopeMm") or src.get("tapeMm"), 0.0)
    horiz = _f(src.get("horizontalMm") or src.get("lengthMm") or src.get("runMm"), 0.0)
    if not stairs:
        # Balcony span: length is the measured run.
        if horiz <= 0:
            horiz = _f(src.get("lengthFt"), 0.0) * MM_PER_FT
        if method not in ("direct", "slope", "steps"):
            method = "direct"
    else:
        has_steps = steps > 0 and riser > 0 and tread > 0
        has_slope = slope > 1 and floor_h > 1
        has_direct = floor_h > 1 and horiz > 1
        if method not in ("steps", "slope", "direct"):
            if has_steps and not has_slope:
                method = "steps"
            elif has_slope:
                method = "slope"
            elif has_direct:
                method = "direct"
            elif has_steps:
                method = "steps"
            else:
                method = "slope" if (slope > 1 or floor_h > 1) else "steps"

        if method == "steps":
            if steps <= 0 and floor_h > 0 and riser > 0:
                steps = max(int(round(floor_h / riser)), 1)
            if steps <= 0:
                steps = 12
            if riser <= 0:
                riser = 180.0
            if tread <= 0:
                tread = 305.0
            calc_floor = steps * riser
            if floor_h <= 1:
                floor_h = calc_floor
            horiz = steps * tread
            slope = steps * math.hypot(riser, tread)
        elif method == "slope":
            if slope <= 1 and horiz > 1 and floor_h > 1:
                slope = math.hypot(horiz, floor_h)
            if floor_h <= 1 and slope > 1 and horiz > 1 and slope > horiz:
                floor_h = math.sqrt(max(slope * slope - horiz * horiz, 0.0))
            if horiz <= 1 and slope > 1 and floor_h > 1:
                if slope > floor_h:
                    horiz = math.sqrt(max(slope * slope - floor_h * floor_h, 0.0))
                else:
                    horiz = slope
                    slope = math.hypot(horiz, floor_h)
            if riser <= 0:
                riser = 180.0
            if steps <= 0 and floor_h > 0 and riser > 0:
                steps = max(int(round(floor_h / riser)), 1)
            if steps <= 0:
                steps = 12
            if tread <= 0 and steps:
                tread = horiz / steps if horiz > 0 else 305.0
        else:  # direct: floor height + horizontal (or slope) length
            if horiz <= 1 and slope > 1:
                if floor_h > 1 and slope > floor_h:
                    horiz = math.sqrt(max(slope * slope - floor_h * floor_h, 0.0))
                else:
                    horiz = slope
            if slope <= 1 and horiz > 1 and floor_h > 1:
                slope = math.hypot(horiz, floor_h)
            if riser <= 0:
                riser = 180.0
            if steps <= 0 and floor_h > 0 and riser > 0:
                steps = max(int(round(floor_h / riser)), 1)
            if steps <= 0:
                steps = 12
            if tread <= 0 and steps:
                tread = horiz / steps if horiz > 0 else 305.0

    if stairs and slope <= 1 and horiz > 1 and floor_h > 1:
        slope = math.hypot(horiz, floor_h)
    if stairs and horiz <= 1 and slope > 1 and floor_h > 1 and slope > floor_h:
        horiz = math.sqrt(max(slope * slope - floor_h * floor_h, 0.0))

    angle = 0.0
    if stairs and horiz > 0.5:
        angle = math.degrees(math.atan(floor_h / horiz)) if floor_h > 0 else 0.0
    elif stairs and slope > 0.5 and floor_h > 0:
        angle = math.degrees(math.asin(min(1.0, floor_h / slope)))

    glass_h = _f(src.get("glassHeightMm") or src.get("heightMm"), 900.0 if stairs else 1000.0)
    if glass_h <= 0:
        glass_h = 900.0 if stairs else 1000.0
    gap = _f(src.get("gapMm"), DEFAULT_GLASS_GAP_MM)
    edge = GLASS_EDGE_INSET_MM if stairs else gap
    span_for_glass = horiz if stairs else (horiz or _f(src.get("lengthMm")))
    max_g = _f(src.get("maxGlassMm"), DEFAULT_MAX_GLASS_MM) or DEFAULT_MAX_GLASS_MM
    suggestions = suggest_glass_divides(span_for_glass, gap=gap, edge=edge, max_mm=max_g)
    panels = _i(src.get("panels") or src.get("glassPanels"), 0)
    if panels <= 0:
        rec = next((s for s in suggestions if s.get("recommended")), None)
        panels = int(rec["panels"]) if rec else auto_panel_count(span_for_glass, max_mm=max_g, gap=gap, edge=edge)

    turn = str(src.get("turn") or src.get("turnAfter") or src.get("bendSide") or "none").strip().lower()
    if turn in ("l", "lt"):
        turn = "left"
    if turn in ("r", "rt"):
        turn = "right"
    if turn not in ("left", "right", "none"):
        turn = "none"
    default_deg = 180.0 if stairs else 90.0
    turn_deg = abs(_f(src.get("turnDeg") or src.get("bendDeg"), default_deg if turn != "none" else 0.0))
    if turn != "none" and turn_deg < 1:
        turn_deg = default_deg

    length_out = slope if stairs else span_for_glass
    return {
        "kind": "stair" if stairs else "span",
        "sizeMethod": method or ("steps" if stairs else "direct"),
        "lengthMm": round(length_out, 2),
        "horizontalMm": round(horiz if stairs else span_for_glass, 2),
        "slopeLengthMm": round(slope if stairs else span_for_glass, 2),
        "floorHeightMm": round(floor_h, 2) if stairs else None,
        "steps": steps if stairs else None,
        "riserMm": round(riser, 3) if stairs else None,
        "treadMm": round(tread, 3) if stairs else None,
        "stairAngleDeg": round(angle, 4) if stairs else None,
        "glassHeightMm": round(glass_h, 2),
        "panels": panels,
        "gapMm": gap,
        "landingMm": round(_f(src.get("landingMm")), 2),
        "turn": turn,
        "turnDeg": turn_deg,
        "maxGlassMm": max_g,
        "divideSuggestions": suggestions,
        "label": str(src.get("label") or ""),
    }


def normalize_railing_runs(cfg: Mapping[str, Any] | None, *, stairs: bool = False) -> list[dict[str, Any]]:
    src = dict(cfg) if isinstance(cfg, Mapping) else {}
    # Do not treat L/U `spans` (panel overrides) as design runs.
    raw = src.get("runs") or src.get("flights")
    out: list[dict[str, Any]] = []
    if isinstance(raw, (list, tuple)) and raw:
        for i, row in enumerate(raw):
            if not isinstance(row, Mapping):
                continue
            resolved = resolve_railing_run(row, stairs=stairs)
            resolved["index"] = i
            resolved["label"] = resolved["label"] or (
                f"Floor {i + 1}" if stairs else f"Span {chr(65 + i)}"
            )
            out.append(resolved)
    if out:
        for i, row in enumerate(out):
            row["signedTurnDeg"] = _signed_turn(
                row.get("turn"), row.get("turnDeg"), last=(i == len(out) - 1), stairs=stairs,
            )
        return out
    # Legacy single-run seed so old carts still calculate.
    seed = {
        "sizeMethod": "steps" if stairs else "direct",
        "floorHeightMm": src.get("floorHeightMm"),
        "slopeLengthMm": src.get("slopeLengthMm") or src.get("lengthMm"),
        "lengthMm": src.get("lengthMm") or src.get("legAMm"),
        "riserMm": src.get("stairRiseMm"),
        "treadMm": src.get("stairRunMm"),
        "steps": src.get("stairSteps"),
        "glassHeightMm": src.get("glassHeightMm") or src.get("heightMm"),
        "panels": src.get("panels"),
        "gapMm": src.get("gapMm"),
        "turn": "none",
        "landingMm": src.get("stairLandingMm"),
    }
    one = resolve_railing_run(seed, stairs=stairs)
    one["index"] = 0
    one["label"] = "Floor 1" if stairs else "Span A"
    one["signedTurnDeg"] = 0.0
    if stairs and one.get("horizontalMm", 0) <= 1 and one.get("slopeLengthMm", 0) <= 1:
        return []
    if (not stairs) and one.get("lengthMm", 0) <= 1:
        return []
    return [one]


def segments_from_runs(runs: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    segs: list[dict[str, Any]] = []
    n = len(runs)
    for i, r in enumerate(runs):
        last = i == n - 1
        segs.append({
            "lengthMm": _f(r.get("lengthMm") or r.get("horizontalMm")),
            "turnDeg": _signed_turn(
                r.get("turn"), r.get("turnDeg"), last=last, stairs=str(r.get("kind")) == "stair",
            ),
            "kind": r.get("kind") or "span",
            "label": r.get("label") or f"Span {i + 1}",
            "panels": _i(r.get("panels"), 0),
            "glassHeightMm": _f(r.get("glassHeightMm")),
        })
    return segs


def build_stair_flights(
    cfg: Mapping[str, Any],
    runs: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Combine floor rows into stair geometry + offset glass panels + segments."""
    from WEOS.factory.railing_engine import compute_stair_geometry, compute_stair_glass_panels

    all_panels: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    geos: list[dict[str, Any]] = []
    total_slope = 0.0
    total_rise = 0.0
    total_run = 0.0
    panel_index = 1
    mismatch_any = False
    mismatch_msg = []

    for i, run in enumerate(runs):
        flight_cfg = {
            **dict(cfg),
            "stairSteps": run.get("steps"),
            "stairRiseMm": run.get("riserMm"),
            "stairRunMm": run.get("treadMm"),
            "floorHeightMm": run.get("floorHeightMm"),
            "glassHeightMm": run.get("glassHeightMm") or cfg.get("glassHeightMm"),
            "panels": run.get("panels") or cfg.get("panels"),
            "gapMm": run.get("gapMm") or cfg.get("gapMm"),
            "stairLandingMm": run.get("landingMm"),
        }
        geo = compute_stair_geometry(flight_cfg)
        geos.append(geo)
        if geo.get("riseMismatch"):
            mismatch_any = True
            if geo.get("riseMismatchMessage"):
                mismatch_msg.append(f"{run.get('label') or i + 1}: {geo['riseMismatchMessage']}")
        panels = compute_stair_glass_panels(flight_cfg, geo)
        x0 = total_run
        for p in panels:
            p = dict(p)
            p["flight"] = i + 1
            p["flightLabel"] = run.get("label") or f"Floor {i + 1}"
            p["index"] = panel_index
            if str(p.get("kind") or "slope") != "landing":
                p["panelStartHorizontalPosition"] = round(_f(p.get("panelStartHorizontalPosition")) + x0, 2)
                p["panelEndHorizontalPosition"] = round(_f(p.get("panelEndHorizontalPosition")) + x0, 2)
            p["localStartMm"] = _f(p.get("panelStartHorizontalPosition")) - x0
            all_panels.append(p)
            panel_index += 1
        last = i == len(runs) - 1
        signed = _signed_turn(run.get("turn"), run.get("turnDeg"), last=last, stairs=True)
        segments.append({
            "lengthMm": _f(geo.get("totalSlopeLengthMm")),
            "turnDeg": signed,
            "kind": "staircase",
            "label": run.get("label") or f"Floor {i + 1}",
            "steps": geo.get("steps"),
            "riseMm": geo.get("riserMm"),
            "runMm": geo.get("treadMm"),
            "horizontalRunMm": geo.get("totalHorizontalRunMm"),
            "floorHeightMm": geo.get("floorHeightMm") or geo.get("totalRiseMm"),
            "panels": run.get("panels"),
            "glassHeightMm": run.get("glassHeightMm"),
        })
        total_slope += _f(geo.get("totalSlopeLengthMm"))
        total_rise += _f(geo.get("totalRiseMm"))
        total_run += _f(geo.get("totalHorizontalRunMm")) + _f(run.get("landingMm"))

    combined = {
        "steps": sum(_i(g.get("steps")) for g in geos),
        "stepsDerived": any(g.get("stepsDerived") for g in geos),
        "riserMm": geos[0].get("riserMm") if geos else 180,
        "treadMm": geos[0].get("treadMm") if geos else 305,
        "floorHeightMm": round(total_rise, 3),
        "stairAngleDeg": geos[0].get("stairAngleDeg") if geos else 0,
        "stairAngleRad": geos[0].get("stairAngleRad") if geos else 0,
        "complementaryAngleDeg": geos[0].get("complementaryAngleDeg") if geos else 90,
        "stepSlopeLengthMm": geos[0].get("stepSlopeLengthMm") if geos else 0,
        "totalRiseMm": round(total_rise, 3),
        "totalHorizontalRunMm": round(total_run, 3),
        "totalSlopeLengthMm": round(total_slope, 3),
        "calculatedRiseMm": round(total_rise, 3),
        "riseMismatch": mismatch_any,
        "riseMismatchMessage": " · ".join(mismatch_msg) if mismatch_msg else None,
        "flights": list(runs),
        "flightCount": len(runs),
    }
    return combined, all_panels, segments
