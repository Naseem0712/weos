"""Railing product — pricing calculator + 2D designer geometry / SVG.

Supports straight, L, U, multi-segment polyline, arch, and staircase layouts
with fabricator hardware rules:

* turns → modular bends
* short handrail joins → 180° connectors
* free ends (no wall) → end caps
* blocks / SS pillars: 100 mm clear from both edges, remainder equal-spaced;
  continuous rail where no pillar/block
* staircase: every 3 steps → side-mounted pillar/block; opposite the 3rd step →
  dual 38/50 mm SS studs with 1 anchor each
* staircase glass: trapezoid/parallelogram panels (100 mm edge inset, 12 mm gaps),
  dual cut-angle display, Level-2 sheet nesting wastage (Level-1 % fallback),
  full internal cost cascade vs customer commercial rate only
* normal (non-stair) railings: SAME cost cascade, but wastage = 0 / nesting OFF
  (purchased glass area = net glass area); materials pulled from railing gallery

Glass panels keep the classic 12 mm gap / wall-gap model on each run segment.
Per-RFT / per-RMT selling rate is preserved.
"""

from __future__ import annotations

import math
from typing import Any, Mapping
from xml.sax.saxutils import escape

MM_PER_FT = 304.8
MM_PER_IN = 25.4
MM_PER_M = 1000.0
# Explicit conversion used by fabricator costing (304.8²).
SQMM_PER_SQFT = 92903.04
SQMM_PER_SQM = MM_PER_M * MM_PER_M
RFT_PER_RMT = 3.28084

# Default stock length before a handrail needs a 180° join connector.
DEFAULT_HANDRAIL_MAX_MM = 6000.0
PILLAR_EDGE_MM = 100.0
GLASS_EDGE_INSET_MM = 100.0
DEFAULT_GLASS_GAP_MM = 12.0
DEFAULT_SHEET_W_MM = 3660.0
DEFAULT_SHEET_H_MM = 2440.0
FLOOR_RISE_TOL_MM = 1.0


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


def _length_mm(cfg: Mapping[str, Any]) -> float:
    if cfg.get("lengthMm") not in (None, ""):
        return _f(cfg.get("lengthMm"))
    if cfg.get("lengthFt") not in (None, ""):
        return _f(cfg.get("lengthFt")) * MM_PER_FT
    if cfg.get("lengthIn") not in (None, ""):
        return _f(cfg.get("lengthIn")) * MM_PER_IN
    if cfg.get("lengthM") not in (None, ""):
        return _f(cfg.get("lengthM")) * MM_PER_M
    return 0.0


def _height_mm(cfg: Mapping[str, Any]) -> float:
    if cfg.get("heightMm") not in (None, ""):
        return _f(cfg.get("heightMm"))
    if cfg.get("heightFt") not in (None, ""):
        return _f(cfg.get("heightFt")) * MM_PER_FT
    if cfg.get("heightIn") not in (None, ""):
        return _f(cfg.get("heightIn")) * MM_PER_IN
    return 0.0


def _shape(cfg: Mapping[str, Any]) -> str:
    s = str(cfg.get("shape") or "straight").strip().lower()
    aliases = {
        "l-shape": "L", "l_shape": "L", "ell": "L",
        "u-shape": "U", "u_shape": "U",
        "poly": "polyline", "multi": "polyline", "path": "polyline",
        "round": "arch", "arc": "arch", "curve": "arch",
        "stairs": "staircase", "stair": "staircase",
        "straight": "straight", "l": "L", "u": "U",
        "polyline": "polyline", "arch": "arch", "staircase": "staircase",
    }
    return aliases.get(s, s if s in ("straight", "L", "U", "polyline", "arch", "staircase") else "straight")


def _preset_segments(shape: str, cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build segment list (lengthMm + turnDeg after segment) from shape + cfg."""
    raw = cfg.get("segments")
    # Explicit segment lists are for polyline (and named presets); L/U use leg fields.
    if shape == "polyline" and isinstance(raw, (list, tuple)) and raw:
        segs: list[dict[str, Any]] = []
        for i, s in enumerate(raw):
            if isinstance(s, Mapping):
                L = _f(s.get("lengthMm") or s.get("length") or s.get("len"))
                if L <= 0 and s.get("lengthFt") not in (None, ""):
                    L = _f(s.get("lengthFt")) * MM_PER_FT
                turn = _f(s.get("turnDeg"), 90.0 if i < len(raw) - 1 else 0.0)
            else:
                L = _f(s)
                turn = 90.0 if i < len(raw) - 1 else 0.0
            if L > 0:
                segs.append({"lengthMm": L, "turnDeg": turn if i < len(list(raw)) - 1 else 0.0})
        if segs:
            segs[-1]["turnDeg"] = 0.0
            return segs

    # Named presets from the attached sketches
    preset = str(cfg.get("preset") or "").strip().lower()
    if preset in ("wall_jog", "jog", "sketch1"):
        return [
            {"lengthMm": 6694, "turnDeg": 90},
            {"lengthMm": 6585, "turnDeg": 90},
            {"lengthMm": 1900, "turnDeg": 90},
            {"lengthMm": 4567, "turnDeg": 90},
            {"lengthMm": 6835, "turnDeg": 0},
        ]
    if preset in ("stepped", "step_u", "sketch2"):
        return [
            {"lengthMm": 6865, "turnDeg": 90},
            {"lengthMm": 11500, "turnDeg": 90},
            {"lengthMm": 5100, "turnDeg": 90},
            {"lengthMm": 4700, "turnDeg": 90},
            {"lengthMm": 5100, "turnDeg": 90},
            {"lengthMm": 11700, "turnDeg": 0},
        ]

    L = _length_mm(cfg)
    if shape == "L":
        a = _f(cfg.get("legAMm"), L * 0.55 if L else 3000.0)
        b = _f(cfg.get("legBMm"), L * 0.45 if L else 2000.0)
        if a <= 0:
            a = 3000.0
        if b <= 0:
            b = 2000.0
        return [{"lengthMm": a, "turnDeg": 90}, {"lengthMm": b, "turnDeg": 0}]
    if shape == "U":
        a = _f(cfg.get("legAMm"), 3000.0)  # left
        b = _f(cfg.get("legBMm"), L or 5000.0)  # bottom / open span
        c = _f(cfg.get("legCMm"), a)  # right
        return [
            {"lengthMm": a, "turnDeg": 90},
            {"lengthMm": b, "turnDeg": 90},
            {"lengthMm": c, "turnDeg": 0},
        ]
    if shape == "arch":
        span = _f(cfg.get("archSpanMm"), L or 4000.0)
        return [{"lengthMm": span, "turnDeg": 0, "kind": "arch"}]
    if shape == "staircase":
        sg = compute_stair_geometry(cfg)
        return [{
            "lengthMm": _f(sg["totalSlopeLengthMm"]),
            "turnDeg": 0,
            "kind": "staircase",
            "steps": sg["steps"],
            "riseMm": sg["riserMm"],
            "runMm": sg["treadMm"],
            "horizontalRunMm": sg["totalHorizontalRunMm"],
        }]
    # straight
    return [{"lengthMm": L or 0.0, "turnDeg": 0}]


def _polyline_points(segments: list[Mapping[str, Any]], *, start_heading_deg: float = 90.0) -> list[tuple[float, float]]:
    """Walk segments from origin; heading 0 = +X, 90 = +Y (plan view)."""
    x = y = 0.0
    heading = math.radians(start_heading_deg)
    pts = [(x, y)]
    for seg in segments:
        L = _f(seg.get("lengthMm"))
        x += L * math.cos(heading)
        y += L * math.sin(heading)
        pts.append((x, y))
        turn = _f(seg.get("turnDeg"))
        # Positive turnDeg = left (CCW) in plan — matches typical “turn left at corner”.
        heading += math.radians(turn)
    return pts


def _pillar_positions_along(length_mm: float, count: int, *, edge_mm: float = PILLAR_EDGE_MM) -> list[float]:
    """Pillar centres: 100 mm from both edges, remaining span divided equally."""
    if count <= 0 or length_mm <= 0:
        return []
    edge = min(edge_mm, length_mm / 2.0)
    usable = max(length_mm - 2.0 * edge, 0.0)
    if count == 1:
        return [length_mm / 2.0]
    if usable <= 0:
        return [length_mm * (i + 1) / (count + 1) for i in range(count)]
    # First at edge, last at length-edge, intermediates equal.
    if count == 2:
        return [edge, length_mm - edge]
    step = usable / (count - 1)
    return [edge + i * step for i in range(count)]


def _panel_widths_for_run(
    length_mm: float, *, panels: int, gap: float, wall_gap: float,
    wall_left: bool, wall_right: bool, explicit: list[float] | None,
) -> list[float]:
    if explicit:
        return [max(w, 0.0) for w in explicit if w > 0]
    n = max(panels, 1)
    gaps_total = (wall_gap if wall_left else 0.0) + (wall_gap if wall_right else 0.0) + gap * max(n - 1, 0)
    glass_total = max(length_mm - gaps_total, 0.0)
    each = glass_total / n if n else 0.0
    return [each] * n


def _handrail_connectors(length_mm: float, max_mm: float) -> int:
    if length_mm <= 0 or max_mm <= 0:
        return 0
    pieces = max(int(math.ceil(length_mm / max_mm)), 1)
    return max(pieces - 1, 0)


def _measurement_basis(cfg: Mapping[str, Any], *, default: str = "sloping_rft") -> str:
    raw = str(cfg.get("measurementBasis") or cfg.get("saleBasis") or "").strip().lower()
    if not raw:
        # saleUnit alone → horizontal for flat runs when default is horizontal
        su = str(cfg.get("saleUnit") or "").strip().lower()
        if su == "rmt":
            return "horizontal_rmt" if "horizontal" in default else "sloping_rmt"
        if su == "rft":
            return "horizontal_rft" if "horizontal" in default else "sloping_rft"
        return default
    aliases = {
        "rft": default if "rft" in default else "sloping_rft",
        "rmt": default if "rmt" in default else "sloping_rmt",
        "horizontal rft": "horizontal_rft", "horizontal_rft": "horizontal_rft", "hrft": "horizontal_rft",
        "sloping rft": "sloping_rft", "sloping_rft": "sloping_rft", "srft": "sloping_rft",
        "horizontal rmt": "horizontal_rmt", "horizontal_rmt": "horizontal_rmt", "hrmt": "horizontal_rmt",
        "sloping rmt": "sloping_rmt", "sloping_rmt": "sloping_rmt", "srmt": "sloping_rmt",
    }
    return aliases.get(raw, raw if raw in (
        "horizontal_rft", "sloping_rft", "horizontal_rmt", "sloping_rmt",
    ) else default)


def _zero_wastage_nest(panels: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Normal railing path: purchased = net, nesting skipped, wastage 0%."""
    net_sqmm = sum(_f(p.get("netGlassAreaSqMm")) for p in panels)
    net_sqft = net_sqmm / SQMM_PER_SQFT if net_sqmm else 0.0
    return {
        "method": "no_wastage",
        "nestingAvailable": False,
        "nestingSkipped": True,
        "netGlassAreaSqMm": round(net_sqmm, 2),
        "netGlassAreaSqFt": round(net_sqft, 4),
        "netGlassAreaSqM": round(net_sqmm / SQMM_PER_SQM, 6) if net_sqmm else 0.0,
        "purchasedGlassAreaSqMm": round(net_sqmm, 2),
        "purchasedGlassAreaSqFt": round(net_sqft, 4),
        "purchasedGlassAreaSqM": round(net_sqmm / SQMM_PER_SQM, 6) if net_sqmm else 0.0,
        "wastageAreaSqMm": 0.0,
        "wastageAreaSqFt": 0.0,
        "wastagePercent": 0.0,
        "sheetsNeeded": 0,
        "sheetWidthMm": None,
        "sheetHeightMm": None,
        "nesting": {
            "algorithm": "skipped",
            "note": "Normal (non-stair) railing — wastage disabled; purchased = net glass area.",
        },
    }


def _span_overrides(cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Optional per-span config for L/U/polyline: panels, blocks, length, height."""
    raw = cfg.get("spans") or cfg.get("spanConfigs") or cfg.get("segmentPanels")
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[dict[str, Any]] = []
    for s in raw:
        if isinstance(s, Mapping):
            out.append(dict(s))
        elif isinstance(s, (int, float)):
            out.append({"panels": int(s)})
        else:
            out.append({})
    return out


def compute_stair_geometry(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Stair run geometry + floor-height mismatch flag.

    Inputs: riser, tread, optional steps, optional floor height.
    If steps omitted but riser + floor height given → derive steps from floor/riser.
    """
    riser = _f(cfg.get("stairRiseMm") or cfg.get("riserMm") or cfg.get("riser"), 150.0)
    tread = _f(cfg.get("stairRunMm") or cfg.get("treadMm") or cfg.get("tread"), 250.0)
    if riser <= 0:
        riser = 150.0
    if tread <= 0:
        tread = 250.0

    floor_h = _f(
        cfg.get("floorHeightMm") or cfg.get("stairTotalRiseMm") or cfg.get("floorHeight"),
        0.0,
    )
    if floor_h <= 0 and cfg.get("floorHeightM") not in (None, ""):
        floor_h = _f(cfg.get("floorHeightM")) * MM_PER_M
    if floor_h <= 0 and cfg.get("floorHeightFt") not in (None, ""):
        floor_h = _f(cfg.get("floorHeightFt")) * MM_PER_FT

    steps_in = cfg.get("stairSteps")
    if steps_in in (None, "") and cfg.get("steps") not in (None, ""):
        steps_in = cfg.get("steps")
    steps = _i(steps_in, 0)
    steps_derived = False
    if steps <= 0:
        if floor_h > 0 and riser > 0:
            steps = max(int(round(floor_h / riser)), 1)
            steps_derived = True
        else:
            steps = 12

    stair_angle_rad = math.atan(riser / tread)
    stair_angle_deg = stair_angle_rad * 180.0 / math.pi
    step_slope = math.hypot(riser, tread)
    total_rise = steps * riser
    total_run = steps * tread
    total_slope = steps * step_slope
    rise_mismatch = False
    rise_delta = 0.0
    if floor_h > 0:
        rise_delta = total_rise - floor_h
        rise_mismatch = abs(rise_delta) > FLOOR_RISE_TOL_MM

    return {
        "steps": steps,
        "stepsDerived": steps_derived,
        "riserMm": round(riser, 3),
        "treadMm": round(tread, 3),
        "floorHeightMm": round(floor_h, 3) if floor_h > 0 else None,
        "stairAngleDeg": round(stair_angle_deg, 4),
        "stairAngleRad": stair_angle_rad,
        "complementaryAngleDeg": round(90.0 - stair_angle_deg, 4),
        "stepSlopeLengthMm": round(step_slope, 3),
        "totalRiseMm": round(total_rise, 3),
        "totalHorizontalRunMm": round(total_run, 3),
        "totalSlopeLengthMm": round(total_slope, 3),
        "calculatedRiseMm": round(total_rise, 3),
        "riseMismatch": rise_mismatch,
        "riseDeltaMm": round(rise_delta, 3),
        "riseMismatchMessage": (
            f"Calculated rise {total_rise:.1f} mm ≠ floor height {floor_h:.1f} mm "
            f"(Δ {rise_delta:+.1f} mm)"
            if rise_mismatch else None
        ),
    }


def compute_stair_glass_panels(
    cfg: Mapping[str, Any],
    geo: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Per-panel trapezoid / parallelogram glass along the stair horizontal run.

    Glass inset 100 mm from both edges; 12 mm gaps between panels.
    When top/bottom follow the slope at constant vertical glass height, net area =
    horizontalPanelWidth × glassVerticalHeight (NOT × sloping length).
    """
    geo = geo or compute_stair_geometry(cfg)
    total_run = _f(geo.get("totalHorizontalRunMm"))
    angle = _f(geo.get("stairAngleDeg"))
    comp = _f(geo.get("complementaryAngleDeg"), 90.0 - angle)
    glass_h = _f(cfg.get("glassHeightMm") or cfg.get("heightMm"), 0.0)
    if glass_h <= 0:
        glass_h = _height_mm(cfg) or 900.0
    n = max(_i(cfg.get("panels") or cfg.get("glassPanels"), 1), 1)
    gap = _f(cfg.get("gapMm"), DEFAULT_GLASS_GAP_MM)
    edge = _f(cfg.get("glassEdgeInsetMm"), GLASS_EDGE_INSET_MM)
    edge = min(edge, total_run / 2.0) if total_run > 0 else edge
    usable = max(total_run - 2.0 * edge, 0.0)
    gaps_total = gap * max(n - 1, 0)
    glass_total = max(usable - gaps_total, 0.0)
    each_h = glass_total / n if n else 0.0

    # Optional landing rectangle after the slope (horizontal).
    landing = _f(cfg.get("stairLandingMm") or cfg.get("landingMm"), 0.0)
    landing_panels = max(_i(cfg.get("landingPanels"), 1 if landing > 0 else 0), 0)

    panels: list[dict[str, Any]] = []
    cursor = edge
    for i in range(n):
        start = cursor
        end = start + each_h
        # Constant vertical height + slope-parallel cuts → parallelogram.
        left_h = glass_h
        right_h = glass_h
        net_sqmm = ((left_h + right_h) / 2.0) * each_h
        panels.append({
            "index": i + 1,
            "kind": "slope",
            "panelStartHorizontalPosition": round(start, 2),
            "panelEndHorizontalPosition": round(end, 2),
            "panelWidthHorizontal": round(each_h, 2),
            "panelSlopeLengthMm": round(each_h / max(math.cos(math.radians(angle)), 1e-9), 2),
            "leftGlassHeight": round(left_h, 2),
            "rightGlassHeight": round(right_h, 2),
            "bottomCutAngle": round(angle, 4),
            "topCutAngle": round(angle, 4),
            "bottomCutAngleVsHorizontal": round(angle, 4),
            "topCutAngleVsHorizontal": round(angle, 4),
            "bottomCutAngleVsVertical": round(comp, 4),
            "topCutAngleVsVertical": round(comp, 4),
            "netGlassAreaSqMm": round(net_sqmm, 2),
            "netGlassAreaSqFt": round(net_sqmm / SQMM_PER_SQFT, 4),
            "netGlassAreaSqM": round(net_sqmm / SQMM_PER_SQM, 6),
            "bboxWidthMm": round(each_h, 2),
            "bboxHeightMm": round(max(left_h, right_h), 2),
        })
        cursor = end + gap

    if landing > 0 and landing_panels > 0:
        land_gap = gap * max(landing_panels - 1, 0)
        land_each = max(landing - land_gap, 0.0) / landing_panels
        lx = total_run + edge  # start after slope run (visual offset)
        for j in range(landing_panels):
            start = lx + j * (land_each + gap)
            end = start + land_each
            net_sqmm = glass_h * land_each
            panels.append({
                "index": n + j + 1,
                "kind": "landing",
                "panelStartHorizontalPosition": round(start, 2),
                "panelEndHorizontalPosition": round(end, 2),
                "panelWidthHorizontal": round(land_each, 2),
                "panelSlopeLengthMm": round(land_each, 2),
                "leftGlassHeight": round(glass_h, 2),
                "rightGlassHeight": round(glass_h, 2),
                "bottomCutAngle": 0.0,
                "topCutAngle": 0.0,
                "bottomCutAngleVsHorizontal": 0.0,
                "topCutAngleVsHorizontal": 0.0,
                "bottomCutAngleVsVertical": 90.0,
                "topCutAngleVsVertical": 90.0,
                "netGlassAreaSqMm": round(net_sqmm, 2),
                "netGlassAreaSqFt": round(net_sqmm / SQMM_PER_SQFT, 4),
                "netGlassAreaSqM": round(net_sqmm / SQMM_PER_SQM, 6),
                "bboxWidthMm": round(land_each, 2),
                "bboxHeightMm": round(glass_h, 2),
            })
    return panels


def nest_railing_glass(
    panels: list[Mapping[str, Any]],
    *,
    sheet_w: float,
    sheet_h: float,
    estimated_wastage_pct: float | None = None,
    gap_mm: float = 5.0,
) -> dict[str, Any]:
    """Level-2 sheet nesting; Level-1 % fallback when nesting unavailable.

    wastagePercent = ((purchased − net) / net) × 100  (relative to net glass).
    """
    net_sqmm = sum(_f(p.get("netGlassAreaSqMm")) for p in panels)
    net_sqft = net_sqmm / SQMM_PER_SQFT if net_sqmm else 0.0

    pieces = []
    for p in panels:
        w = _f(p.get("bboxWidthMm") or p.get("panelWidthHorizontal"))
        h = _f(p.get("bboxHeightMm") or max(_f(p.get("leftGlassHeight")), _f(p.get("rightGlassHeight"))))
        if w > 0 and h > 0:
            pieces.append({
                "widthMm": w,
                "heightMm": h,
                "label": f"G{p.get('index', '?')}",
                "qty": 1,
            })

    nesting: dict[str, Any] | None = None
    nesting_ok = False
    sheets_needed = 0
    purchased_sqmm = 0.0
    method = "estimated_pct"

    if pieces and sheet_w > 0 and sheet_h > 0:
        try:
            from WEOS.factory.optimize_engine import GlassPiece, nest_glass_shelf

            gp = [
                GlassPiece(width_mm=_f(x["widthMm"]), height_mm=_f(x["heightMm"]),
                           label=str(x.get("label") or ""), qty=1)
                for x in pieces
            ]
            # Try both sheet orientations; keep lower purchased area.
            candidates: list[dict[str, Any]] = []
            for sw, sh in ((sheet_w, sheet_h), (sheet_h, sheet_w)):
                try:
                    candidates.append(nest_glass_shelf(gp, sheet_w=sw, sheet_h=sh, gap_mm=gap_mm, allow_rotate=True))
                except Exception:
                    continue
            if candidates:
                best = min(
                    candidates,
                    key=lambda c: (_f(c.get("totalSheetAreaMm2"), 1e18), _f(c.get("wastePercent"), 1e9)),
                )
                nesting = best
                nesting_ok = True
                method = "sheet_nesting"
                sheets_needed = _i(best.get("sheetsNeeded"), 0)
                purchased_sqmm = _f(best.get("totalSheetAreaMm2"))
        except Exception as exc:
            nesting = {"error": str(exc), "algorithm": "unavailable"}

    if not nesting_ok:
        pct = _f(estimated_wastage_pct, 10.0) if estimated_wastage_pct is not None else 10.0
        purchased_sqmm = net_sqmm * (1.0 + pct / 100.0) if net_sqmm else 0.0
        method = "estimated_pct"
        nesting = {
            "algorithm": "estimated_pct",
            "estimatedWastagePercent": pct,
            "note": "Sheet nesting unavailable or panels do not fit — using configurable % wastage only.",
        }

    purchased_sqft = purchased_sqmm / SQMM_PER_SQFT if purchased_sqmm else 0.0
    unused_sqmm = max(purchased_sqmm - net_sqmm, 0.0)
    wastage_pct = ((purchased_sqmm - net_sqmm) / net_sqmm * 100.0) if net_sqmm > 0 else 0.0

    return {
        "method": method,
        "nestingAvailable": nesting_ok,
        "netGlassAreaSqMm": round(net_sqmm, 2),
        "netGlassAreaSqFt": round(net_sqft, 4),
        "netGlassAreaSqM": round(net_sqmm / SQMM_PER_SQM, 6) if net_sqmm else 0.0,
        "purchasedGlassAreaSqMm": round(purchased_sqmm, 2),
        "purchasedGlassAreaSqFt": round(purchased_sqft, 4),
        "purchasedGlassAreaSqM": round(purchased_sqmm / SQMM_PER_SQM, 6) if purchased_sqmm else 0.0,
        "wastageAreaSqMm": round(unused_sqmm, 2),
        "wastageAreaSqFt": round(unused_sqmm / SQMM_PER_SQFT, 4) if unused_sqmm else 0.0,
        "wastagePercent": round(wastage_pct, 3),
        "sheetsNeeded": sheets_needed,
        "sheetWidthMm": sheet_w,
        "sheetHeightMm": sheet_h,
        "nesting": nesting,
    }


def compute_railing_cost_cascade(
    *,
    net_glass_sqft: float,
    purchased_glass_sqft: float,
    glass_rate: float,
    hardware_cost: float,
    profile_cost: float,
    installation: float,
    transport: float,
    other_cost: float,
    overhead_pct: float,
    markup_pct: float,
    commercial_rft: float,
    commercial_rmt: float,
) -> dict[str, Any]:
    """Full internal cost cascade — wastage is explicit, not hidden in the rate."""
    glass_material = purchased_glass_sqft * glass_rate
    direct = glass_material + hardware_cost + profile_cost + installation + transport + other_cost
    overhead = direct * (overhead_pct / 100.0)
    before_profit = direct + overhead
    selling = before_profit * (1.0 + markup_pct / 100.0)
    profit = selling - before_profit

    def _per(length: float, amount: float) -> float:
        return round(amount / length, 4) if length > 0 else 0.0

    return {
        "netGlassAreaSqFt": round(net_glass_sqft, 4),
        "purchasedGlassAreaSqFt": round(purchased_glass_sqft, 4),
        "wastageAreaSqFt": round(max(purchased_glass_sqft - net_glass_sqft, 0.0), 4),
        "glassMaterialCost": round(glass_material, 2),
        "hardwareCost": round(hardware_cost, 2),
        "profileCost": round(profile_cost, 2),
        "installationCost": round(installation, 2),
        "transportCost": round(transport, 2),
        "otherCost": round(other_cost, 2),
        "directCost": round(direct, 2),
        "overheadPercent": overhead_pct,
        "overheadCost": round(overhead, 2),
        "totalBeforeProfit": round(before_profit, 2),
        "markupPercent": markup_pct,
        "profitAmount": round(profit, 2),
        "sellingPrice": round(selling, 2),
        "costPerRFTBeforeProfit": _per(commercial_rft, before_profit),
        "costPerRMTBeforeProfit": _per(commercial_rmt, before_profit),
        "sellingRatePerRFT": _per(commercial_rft, selling),
        "sellingRatePerRMT": _per(commercial_rmt, selling),
        "commercialRailingLengthRFT": round(commercial_rft, 4),
        "commercialRailingLengthRMT": round(commercial_rmt, 4),
    }


def compute_railing(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Compute quantities, BOM, per-RFT/RMT rate, and geometry for any shape."""
    cfg = dict(cfg or {})
    shape = _shape(cfg)
    height_mm = _height_mm(cfg)
    glass_height_mm = _f(cfg.get("glassHeightMm"), height_mm)
    if glass_height_mm <= 0:
        glass_height_mm = height_mm

    stair_geo: dict[str, Any] | None = None
    stair_panels: list[dict[str, Any]] = []
    if shape == "staircase":
        stair_geo = compute_stair_geometry(cfg)
        if glass_height_mm <= 0:
            glass_height_mm = 900.0
        if height_mm <= 0:
            height_mm = glass_height_mm
        cfg = {
            **cfg,
            "stairSteps": stair_geo["steps"],
            "stairRiseMm": stair_geo["riserMm"],
            "stairRunMm": stair_geo["treadMm"],
            "glassHeightMm": glass_height_mm,
            "heightMm": height_mm if height_mm > 0 else glass_height_mm,
        }
        stair_panels = compute_stair_glass_panels(cfg, stair_geo)

    segments = _preset_segments(shape, cfg)
    total_length_mm = sum(_f(s.get("lengthMm")) for s in segments)
    if shape == "arch":
        span = _f(segments[0].get("lengthMm")) if segments else _length_mm(cfg)
        rise = _f(cfg.get("archRiseMm"), span * 0.35 if span else 1000.0)
        if rise > 0 and span > 0:
            r = (rise / 2.0) + (span ** 2) / (8.0 * rise)
            theta = 2.0 * math.asin(min(1.0, (span / 2.0) / max(r, 1e-6)))
            total_length_mm = r * theta
            segments = [{"lengthMm": total_length_mm, "turnDeg": 0, "kind": "arch",
                         "spanMm": span, "riseMm": rise, "radiusMm": r}]

    gap = _f(cfg.get("gapMm"), DEFAULT_GLASS_GAP_MM)
    wall_gap = _f(cfg.get("wallGapMm"), DEFAULT_GLASS_GAP_MM)
    wall_start = bool(cfg.get("wallStart", cfg.get("wallLeft", True)))
    wall_end = bool(cfg.get("wallEnd", cfg.get("wallRight", True)))
    # Flat runs default to horizontal RFT; stairs keep sloping RFT.
    basis_default = "sloping_rft" if shape == "staircase" else "horizontal_rft"
    basis = _measurement_basis(cfg, default=basis_default)
    sale_unit = "rmt" if basis.endswith("rmt") else "rft"
    if str(cfg.get("saleUnit") or "").lower() in ("rft", "rmt") and not cfg.get("measurementBasis"):
        sale_unit = str(cfg.get("saleUnit")).lower()

    # Gallery selections → rates (UI may still override rates explicitly)
    material_selections = cfg.get("materialSelections") or cfg.get("materials") or {}
    gallery_meta: dict[str, dict[str, Any]] = {}
    gallery_rates: dict[str, float] = {}
    try:
        from WEOS.factory.railing_materials import rates_from_selections, resolve_selections

        gallery_rates = rates_from_selections(material_selections if isinstance(material_selections, Mapping) else {})
        gallery_meta = resolve_selections(material_selections if isinstance(material_selections, Mapping) else {})
    except Exception:
        gallery_rates = {}
        gallery_meta = {}

    rates = dict(gallery_rates)
    for k, v in dict(cfg.get("rates") or {}).items():
        # Explicit UI rates win when non-zero; zeros do not wipe gallery SKUs
        if v in (None, ""):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv != 0.0 or k not in rates:
            rates[k] = fv
    r_glass = _f(rates.get("glassPerSqft") or cfg.get("glassRatePerSqft"), 200.0)
    r_block = _f(rates.get("blockPerPc"), 100.0)
    r_anchor = _f(rates.get("anchorPerPc"), 50.0)
    r_brail = _f(rates.get("bottomRailPerUnit") or cfg.get("profileCostPerUnit"))
    w_brail = _f(rates.get("bottomRailWeightPerUnit"))
    r_hrail = _f(rates.get("handrailPerUnit"))
    w_hrail = _f(rates.get("handrailWeightPerUnit"))
    r_wall = _f(rates.get("wallConnectorPerPc"))
    r_bend = _f(rates.get("modularBendPerPc"), _f(rates.get("bendPerPc"), 0.0))
    r_conn180 = _f(rates.get("connector180PerPc"), 0.0)
    r_endcap = _f(rates.get("endCapPerPc"), 0.0)
    r_stud = _f(rates.get("studPerPc"), 0.0)

    # Install components — UI multi-select of what is being installed.
    # Stairs never use a bottom rail option; continuous bottom-rail-only hides pillars.
    install = cfg.get("installComponents") if isinstance(cfg.get("installComponents"), Mapping) else {}
    if not install:
        install = {
            "bottomRail": shape != "staircase",
            "block": True,
            "ssPillar": False,
            "handrail": bool(cfg.get("handrail", shape != "straight")),
            "glass": True,
        }
    want_bottom = bool(install.get("bottomRail", shape != "staircase")) and shape != "staircase"
    want_block = bool(install.get("block", False))
    want_ss = bool(install.get("ssPillar", False) or install.get("ss_pillar", False))
    want_pillars = want_block or want_ss
    want_handrail = bool(install.get("handrail", cfg.get("handrail", shape != "straight")))
    want_glass = bool(install.get("glass", True))
    if want_ss and not want_block:
        cfg["pillarType"] = "ss"
    elif want_block and not str(cfg.get("pillarType") or "").lower().startswith("ss"):
        cfg["pillarType"] = cfg.get("pillarType") or "block"

    panels_cfg = max(_i(cfg.get("panels") or cfg.get("glassPanels"), 1), 1)
    blocks_per_glass = max(_i(cfg.get("blocksPerGlass"), 0), 0)
    if not want_pillars:
        blocks_per_glass = 0
    pillar_edge = _f(cfg.get("pillarEdgeMm"), PILLAR_EDGE_MM)
    handrail_on = want_handrail
    handrail_max = _f(cfg.get("handrailMaxMm"), DEFAULT_HANDRAIL_MAX_MM)
    continuous_rail = bool(cfg.get("continuousRail", blocks_per_glass == 0 or (want_bottom and not want_pillars)))
    span_cfgs = _span_overrides(cfg)

    # Color system: global color applied to whole railing, or per-component overrides.
    color_mode = str(cfg.get("colorMode") or "global").lower()
    system_color = str(cfg.get("systemColor") or cfg.get("colour") or cfg.get("color") or "").strip()
    component_colors = cfg.get("componentColors") if isinstance(cfg.get("componentColors"), Mapping) else {}
    glass_type = str(cfg.get("glassType") or cfg.get("glassColour") or cfg.get("glassColor") or "clear")
    glass_brand = str(cfg.get("glassBrand") or "")
    glass_thickness = _f(cfg.get("glassThicknessMm"), 12.0)

    # ── per-segment glass / pillars ─────────────────────────────────────────
    explicit = cfg.get("panelSizesMm")
    explicit_list = [max(_f(x), 0.0) for x in explicit] if isinstance(explicit, (list, tuple)) else None

    run_details: list[dict[str, Any]] = []
    all_panel_widths: list[float] = []
    pillar_count = 0
    pillar_positions_plan: list[dict[str, Any]] = []
    global_panel_index = 0

    if shape == "staircase" and stair_panels:
        all_panel_widths = [_f(p.get("panelWidthHorizontal")) for p in stair_panels]
        L = total_length_mm
        run_details.append({
            "index": 0,
            "lengthMm": round(L, 1),
            "turnDeg": 0.0,
            "kind": "staircase",
            "panelWidthsMm": [round(w, 1) for w in all_panel_widths],
            "pillarPositionsMm": [],
            "wallStart": wall_start,
            "wallEnd": wall_end,
            "continuousRail": False,
            "glassPanels": stair_panels,
            "panelStartIndex": 1,
        })
    else:
        n_seg = len(segments)
        for si, seg in enumerate(segments):
            L = _f(seg.get("lengthMm"))
            # Per-span length override
            if si < len(span_cfgs) and _f(span_cfgs[si].get("lengthMm")) > 0:
                L = _f(span_cfgs[si].get("lengthMm"))
                seg = {**seg, "lengthMm": L}
            w_left = wall_start if si == 0 else False
            w_right = wall_end if si == n_seg - 1 else False
            span_ov = span_cfgs[si] if si < len(span_cfgs) else {}
            if n_seg == 1 and not span_ov:
                seg_panels = panels_cfg
                seg_explicit = explicit_list
                seg_blocks = blocks_per_glass
            else:
                # Prefer explicit per-span panels; else proportional share of total
                if span_ov.get("panels") not in (None, ""):
                    seg_panels = max(_i(span_ov.get("panels"), 1), 1)
                elif n_seg == 1:
                    seg_panels = panels_cfg
                else:
                    share = L / total_length_mm if total_length_mm else 0
                    seg_panels = max(1, int(round(panels_cfg * share))) if panels_cfg else 1
                seg_explicit = None
                if isinstance(span_ov.get("panelSizesMm"), (list, tuple)):
                    seg_explicit = [max(_f(x), 0.0) for x in span_ov["panelSizesMm"]]
                seg_blocks = (
                    max(_i(span_ov.get("blocksPerGlass"), blocks_per_glass), 0)
                    if span_ov.get("blocksPerGlass") not in (None, "")
                    else blocks_per_glass
                )
            widths = _panel_widths_for_run(
                L, panels=seg_panels, gap=gap, wall_gap=wall_gap,
                wall_left=w_left, wall_right=w_right, explicit=seg_explicit,
            )
            all_panel_widths.extend(widths)
            if seg_blocks > 0:
                n_pillars = seg_blocks * len(widths)
            elif continuous_rail and seg_blocks == 0:
                n_pillars = 0
            else:
                n_pillars = max(_i(span_ov.get("pillarsPerSegment") or cfg.get("pillarsPerSegment"), 0), 0)
            positions = _pillar_positions_along(L, n_pillars, edge_mm=pillar_edge)
            pillar_count += len(positions)
            for px in positions:
                pillar_positions_plan.append({"segment": si, "sMm": round(px, 1)})
            panel_start = global_panel_index + 1
            global_panel_index += len(widths)
            span_label = str(span_ov.get("label") or f"Span {chr(65 + si)}" if n_seg > 1 else "Span A")
            run_details.append({
                "index": si,
                "label": span_label,
                "lengthMm": round(L, 1),
                "turnDeg": _f(seg.get("turnDeg")),
                "kind": seg.get("kind") or "straight",
                "panelWidthsMm": [round(w, 1) for w in widths],
                "pillarPositionsMm": [round(p, 1) for p in positions],
                "blocksPerGlass": seg_blocks,
                "wallStart": w_left,
                "wallEnd": w_right,
                "continuousRail": n_pillars == 0,
                "panelStartIndex": panel_start,
                "panelEndIndex": global_panel_index,
            })
            # Keep segment list in sync for plan polyline / connectors
            if si < len(segments):
                segments[si] = {**segments[si], "lengthMm": L}
        # Recompute total length if spans overrode segment lengths
        total_length_mm = sum(_f(r.get("lengthMm")) for r in run_details) or total_length_mm

    panel_count = len(all_panel_widths)
    panel_widths_in = [round(w / MM_PER_IN, 2) for w in all_panel_widths]

    if shape == "staircase" and stair_panels:
        glass_area_sqmm = sum(_f(p.get("netGlassAreaSqMm")) for p in stair_panels)
        glass_h_for_area = glass_height_mm
    else:
        glass_h_for_area = glass_height_mm if glass_height_mm > 0 else height_mm
        glass_area_sqmm = sum(w * glass_h_for_area for w in all_panel_widths)
    glass_area_sqft = glass_area_sqmm / SQMM_PER_SQFT
    glass_area_sqm = glass_area_sqmm / SQMM_PER_SQM

    # ── corner / join hardware ──────────────────────────────────────────────
    bend_count = sum(1 for s in segments[:-1] if abs(_f(s.get("turnDeg"))) > 1e-6)
    if shape == "arch":
        bend_count = 0

    connector_180 = 0
    if handrail_on:
        for s in segments:
            connector_180 += _handrail_connectors(_f(s.get("lengthMm")), handrail_max)

    end_caps = 0
    if handrail_on:
        if not wall_start:
            end_caps += 1
        if not wall_end:
            end_caps += 1

    wall_connectors = (1 if wall_start else 0) + (1 if wall_end else 0)

    # ── staircase studs (side-mounted, every 3 steps, dual SS) ───────────────
    stair_pillars = 0
    stair_studs = 0
    stair_stud_anchors = 0
    stud_stations: list[dict[str, Any]] = []
    stud_size = _i(cfg.get("studSizeMm"), 38)
    if stud_size not in (38, 50):
        stud_size = 38
    if shape == "staircase" and stair_geo:
        steps = int(stair_geo["steps"])
        stair_pillars = steps // 3
        dual_stations = steps // 3
        stair_studs = dual_stations * 2
        stair_stud_anchors = stair_studs
        pillar_count = stair_pillars
        bend_count = 0
        connector_180 = _handrail_connectors(total_length_mm, handrail_max) if handrail_on else 0
        tread = _f(stair_geo["treadMm"])
        riser = _f(stair_geo["riserMm"])
        for n in range(3, steps + 1, 3):
            stud_stations.append({
                "step": n,
                "horizontalMm": round(tread * n, 2),
                "riseMm": round(riser * n, 2),
                "studs": 2,
                "anchors": 2,
                "edgeInsetMm": GLASS_EDGE_INSET_MM,
            })
        if not want_pillars:
            stair_pillars = 0
            pillar_count = 0
            # keep studs (structural dual studs) unless glass+pillars both off
            if not want_glass:
                stair_studs = 0
                stair_stud_anchors = 0
                stud_stations = []

    anchors_per_pillar = min(max(_i(cfg.get("anchorsPerPillar"), 1), 1), 2) if pillar_count else 0
    pillar_anchors = pillar_count * anchors_per_pillar

    # Commercial lengths (measurement basis)
    horiz_mm = _f(stair_geo.get("totalHorizontalRunMm")) if stair_geo else total_length_mm
    slope_mm = _f(stair_geo.get("totalSlopeLengthMm")) if stair_geo else total_length_mm
    # Allow explicit stair railing length override
    override_len = _f(cfg.get("stairRailingLengthMm") or cfg.get("railingLengthMm"), 0.0)
    if override_len > 0:
        if "horizontal" in basis:
            horiz_mm = override_len
        else:
            slope_mm = override_len

    horiz_rft = horiz_mm / MM_PER_FT if horiz_mm else 0.0
    slope_rft = slope_mm / MM_PER_FT if slope_mm else 0.0
    horiz_rmt = horiz_mm / MM_PER_M if horiz_mm else 0.0
    slope_rmt = slope_mm / MM_PER_M if slope_mm else 0.0

    if basis == "horizontal_rft":
        commercial_rft, commercial_rmt = horiz_rft, horiz_rft / RFT_PER_RMT
        length_rft, length_rmt = horiz_rft, horiz_rmt
        total_length_mm = horiz_mm
    elif basis == "horizontal_rmt":
        commercial_rmt, commercial_rft = horiz_rmt, horiz_rmt * RFT_PER_RMT
        length_rft, length_rmt = horiz_rft, horiz_rmt
        total_length_mm = horiz_mm
    elif basis == "sloping_rmt":
        commercial_rmt, commercial_rft = slope_rmt, slope_rmt * RFT_PER_RMT
        length_rft, length_rmt = slope_rft, slope_rmt
        total_length_mm = slope_mm
    else:  # sloping_rft
        commercial_rft, commercial_rmt = slope_rft, slope_rft / RFT_PER_RMT
        length_rft, length_rmt = slope_rft, slope_rmt
        total_length_mm = slope_mm

    width_unit = commercial_rmt if sale_unit == "rmt" else commercial_rft

    anchors_per_rft = _f(cfg.get("anchorsPerRft"), 0.0)
    include_base = bool(cfg.get("includeBaseAnchors", False))
    base_anchors = math.ceil(length_rft * anchors_per_rft) if (include_base and anchors_per_rft) else 0
    anchor_count = pillar_anchors + base_anchors + stair_stud_anchors
    if anchor_count == 0 and not pillar_count and shape != "staircase":
        anchor_count = math.ceil(length_rft * (anchors_per_rft or 1.0))

    rail_unit_len = width_unit
    items: list[dict[str, Any]] = []

    def _mat_for(*roles: str) -> dict[str, Any]:
        for role in roles:
            if role in gallery_meta:
                return gallery_meta[role]
            # also match by category
            for m in gallery_meta.values():
                if str(m.get("category") or "") == role:
                    return m
        return {}

    def add(
        key: str, label: str, qty: float, unit: str, rate: float,
        weight: float | None = None, *, material: Mapping[str, Any] | None = None,
        color_role: str | None = None,
    ) -> None:
        amount = round(qty * rate, 2)
        row: dict[str, Any] = {
            "key": key, "label": label, "qty": round(qty, 3), "unit": unit,
            "rate": round(rate, 3), "amount": amount,
        }
        if weight is not None:
            row["weightKg"] = round(weight, 3)
        mat = material or {}
        if mat:
            try:
                from WEOS.factory.railing_materials import bom_meta_from_material
                row.update(bom_meta_from_material(mat))
            except Exception:
                row["materialId"] = mat.get("id")
                row["color"] = mat.get("color")
                row["grade"] = mat.get("grade")
                row["sizeMm"] = mat.get("sizeMm")
                row["mountType"] = mat.get("mountType")
            # Prefer gallery display name in label when present
            if mat.get("name") and key != "glass":
                row["label"] = f"{label} · {mat.get('name')}"
        # Color system override
        role = color_role or key
        if color_mode == "per_part" and component_colors.get(role):
            row["color"] = component_colors.get(role)
        elif system_color and (color_mode == "global" or not row.get("color")):
            row["color"] = system_color
        if key == "glass":
            row["glassType"] = glass_type
            row["glassBrand"] = glass_brand or None
            row["sizeMm"] = row.get("sizeMm") or f"{glass_thickness:g} mm"
        items.append(row)

    # ── nesting wastage (stairs) / zero wastage (normal) ─────────────────────
    sheet_w = _f(cfg.get("sheetWidthMm") or cfg.get("standardGlassSheetWidthMm"), DEFAULT_SHEET_W_MM)
    sheet_h = _f(cfg.get("sheetHeightMm") or cfg.get("standardGlassSheetHeightMm"), DEFAULT_SHEET_H_MM)
    est_waste = cfg.get("estimatedWastagePercent")
    if est_waste in (None, ""):
        est_waste = cfg.get("wastagePercent")
    nest_panels: list[dict[str, Any]]
    if shape == "staircase" and stair_panels:
        nest_panels = stair_panels
    else:
        nest_panels = [{
            "index": i + 1,
            "netGlassAreaSqMm": w * glass_h_for_area,
            "panelWidthHorizontal": w,
            "bboxWidthMm": w,
            "bboxHeightMm": glass_h_for_area,
            "leftGlassHeight": glass_h_for_area,
            "rightGlassHeight": glass_h_for_area,
        } for i, w in enumerate(all_panel_widths) if w > 0 and glass_h_for_area > 0]

    # Normal railings: wastage OFF (purchased = net). Stairs keep nesting path.
    apply_wastage = shape == "staircase" and not bool(cfg.get("forceNoWastage", False))
    if apply_wastage:
        glass_nest = nest_railing_glass(
            nest_panels,
            sheet_w=sheet_w,
            sheet_h=sheet_h,
            estimated_wastage_pct=_f(est_waste, 10.0) if est_waste is not None else None,
        )
    else:
        glass_nest = _zero_wastage_nest(nest_panels)
    purchased_sqft = _f(glass_nest.get("purchasedGlassAreaSqFt"))
    net_sqft = _f(glass_nest.get("netGlassAreaSqFt"), glass_area_sqft)

    mount_hint = str(
        cfg.get("mountType")
        or (_mat_for("block", "ss_pillar", "bottom_rail", "u_channel") or {}).get("mountType")
        or "side_mount"
    )

    # BOM glass line uses purchased area when nesting/estimate available
    include_stair_glass = want_glass and (shape != "staircase" or bool(cfg.get("stairGlass", True)))
    if net_sqft > 0 and include_stair_glass:
        glass_label = (
            f"Glass {glass_thickness:g} mm {glass_type}" + (" · no wastage" if not apply_wastage else " · purchased / cutting")
        )
        add("glass", glass_label, round(purchased_sqft or net_sqft, 3), "sqft", r_glass, color_role="glass")

    pillar_type = str(cfg.get("pillarType") or ("ss" if want_ss else "block")).lower()
    block_mat = _mat_for("ss_pillar" if pillar_type in ("ss", "ss_pillar", "pillar") else "block", "block", "ss_pillar")
    if pillar_count and want_pillars:
        label = f"Blocks / pillars ({pillar_type}) · {mount_hint}"
        if shape == "staircase":
            label = f"Side-mount pillars (every 3 steps · {pillar_type})"
        add("blocks", label, pillar_count, "pc", r_block, material=block_mat, color_role="block")
    if stair_studs:
        add("studs", f"SS studs {stud_size} mm (dual @ every 3rd step)", stair_studs, "pc",
            r_stud or r_block, material=_mat_for("stud"), color_role="stud")
    if anchor_count and (want_pillars or shape == "staircase"):
        add("anchors", "Anchor bolts", anchor_count, "pc", r_anchor, material=_mat_for("anchor"), color_role="anchor")
    if want_bottom and r_brail and total_length_mm:
        brail_mat = _mat_for("bottom_rail", "u_channel")
        add("bottomRail", f"Bottom / continuous rail · {mount_hint}", round(rail_unit_len, 3), sale_unit, r_brail,
            weight=rail_unit_len * w_brail if w_brail else None, material=brail_mat, color_role="bottom_rail")
    if handrail_on and r_hrail and total_length_mm:
        add("handrail", "Handrail", round(rail_unit_len, 3), sale_unit, r_hrail,
            weight=rail_unit_len * w_hrail if w_hrail else None, material=_mat_for("handrail"), color_role="handrail")
    if bend_count and (r_bend or True):
        add("modularBend", "Modular bend (corners)", bend_count, "pc", r_bend, material=_mat_for("bend"), color_role="bend")
    if connector_180 and (r_conn180 or True):
        add("connector180", "180° handrail connector", connector_180, "pc", r_conn180,
            material=_mat_for("connector_180"), color_role="connector_180")
    if end_caps and (r_endcap or True):
        add("endCap", "Handrail end cap", end_caps, "pc", r_endcap, material=_mat_for("end_cap"), color_role="end_cap")
    if wall_connectors and (r_wall or True):
        add("wallConnector", "Wall connector", wall_connectors, "pc", r_wall,
            material=_mat_for("wall_connector"), color_role="wall_connector")

    extras_in = cfg.get("extras") if isinstance(cfg.get("extras"), (list, tuple)) else []
    extras: list[dict[str, Any]] = []
    extras_total = 0.0
    for ex in extras_in:
        if not isinstance(ex, Mapping):
            continue
        amt = _f(ex.get("amount"))
        nm = str(ex.get("name") or "Extra")
        extras.append({"name": nm, "amount": round(amt, 2)})
        extras_total += amt

    items_total = sum(float(it["amount"]) for it in items)
    # Hardware / profile split for cascade (exclude glass line)
    hardware_cost = sum(
        float(it["amount"]) for it in items
        if it.get("key") in ("blocks", "studs", "anchors", "modularBend", "connector180", "endCap", "wallConnector")
    )
    profile_cost = sum(
        float(it["amount"]) for it in items if it.get("key") in ("bottomRail", "handrail")
    )
    # Allow lump-sum overrides from UI
    hw_override = cfg.get("hardwareCost")
    if hw_override not in (None, ""):
        hardware_cost = _f(hw_override)
    prof_override = cfg.get("profileCost")
    if prof_override not in (None, ""):
        profile_cost = _f(prof_override)
    installation = _f(cfg.get("installation") or cfg.get("installationCost") or rates.get("installation"), 0.0)
    transport = _f(cfg.get("transport") or cfg.get("transportCost") or rates.get("transport"), 0.0)
    other_cost = extras_total + _f(cfg.get("otherCost"), 0.0)
    overhead_pct = _f(cfg.get("overheadPercent") or rates.get("overheadPercent"), 0.0)
    markup_pct = _f(cfg.get("markupPercent") or cfg.get("profitPercent") or rates.get("markupPercent"), 0.0)

    cost = compute_railing_cost_cascade(
        net_glass_sqft=net_sqft,
        purchased_glass_sqft=purchased_sqft or net_sqft,
        glass_rate=r_glass,
        hardware_cost=hardware_cost,
        profile_cost=profile_cost,
        installation=installation,
        transport=transport,
        other_cost=other_cost,
        overhead_pct=overhead_pct,
        markup_pct=markup_pct,
        commercial_rft=commercial_rft,
        commercial_rmt=commercial_rmt,
    )

    # Prefer cascade selling: always for stairs; for normal when cascade inputs present
    # OR always for non-stair (same formula as stairs, wastage already zeroed).
    use_cascade = bool(
        shape != "staircase"
        or overhead_pct or markup_pct or installation or transport
        or cfg.get("hardwareCost") not in (None, "")
        or shape == "staircase"
    )
    # Force cascade for all railing shapes (shared commercial path).
    use_cascade = True
    total = round(cost["sellingPrice"] if use_cascade else (items_total + extras_total), 2)
    per_unit_rate = (
        cost["sellingRatePerRFT"] if sale_unit == "rft" else cost["sellingRatePerRMT"]
    ) if use_cascade else (round((items_total + extras_total) / width_unit, 2) if width_unit else 0.0)
    manual = cfg.get("manualRatePerUnit")
    manual_rate = _f(manual) if manual not in (None, "") else None
    selling_per_unit = manual_rate if manual_rate is not None else per_unit_rate
    selling_total = round(selling_per_unit * width_unit, 2) if width_unit else round(total, 2)

    # Customer-facing commercial (only final rate) vs internal breakdown
    commercial = {
        "saleUnit": sale_unit,
        "measurementBasis": basis,
        "sellingRatePerUnit": round(selling_per_unit, 4),
        "sellingTotal": selling_total,
        "sellingRatePerRFT": cost["sellingRatePerRFT"] if manual_rate is None else (
            round(selling_total / commercial_rft, 4) if commercial_rft else 0.0
        ),
        "sellingRatePerRMT": cost["sellingRatePerRMT"] if manual_rate is None else (
            round(selling_total / commercial_rmt, 4) if commercial_rmt else 0.0
        ),
    }
    internal = {
        "netGlassAreaSqFt": cost["netGlassAreaSqFt"],
        "wastageAreaSqFt": cost["wastageAreaSqFt"],
        "purchasedGlassAreaSqFt": cost["purchasedGlassAreaSqFt"],
        "wastagePercent": glass_nest.get("wastagePercent"),
        "nestingMethod": glass_nest.get("method"),
        "nestingSkipped": bool(glass_nest.get("nestingSkipped")),
        "glassMaterialCost": cost["glassMaterialCost"],
        "directCost": cost["directCost"],
        "overheadCost": cost["overheadCost"],
        "overheadPercent": overhead_pct,
        "profitMarkup": cost["profitAmount"],
        "markupPercent": markup_pct,
        "totalBeforeProfit": cost["totalBeforeProfit"],
        "sellingPrice": cost["sellingPrice"],
        "costPerRFTBeforeProfit": cost["costPerRFTBeforeProfit"],
        "costPerRMTBeforeProfit": cost["costPerRMTBeforeProfit"],
        "sellingRatePerRFT": cost["sellingRatePerRFT"],
        "sellingRatePerRMT": cost["sellingRatePerRMT"],
        "cutAngles": {
            "stairAngleDeg": (stair_geo or {}).get("stairAngleDeg"),
            "complementaryAngleDeg": (stair_geo or {}).get("complementaryAngleDeg"),
            "note": "Bottom/top vs horizontal = stairAngle; vs vertical edge = 90 − stairAngle",
        },
    }

    geometry = _railing_geometry(
        shape=shape, height_mm=height_mm if height_mm > 0 else glass_height_mm,
        segments=segments, run_details=run_details,
        gap=gap, wall_gap=wall_gap, wall_start=wall_start, wall_end=wall_end,
        handrail=handrail_on, bend_count=bend_count, end_caps=end_caps,
        connector_180=connector_180, cfg=cfg,
        stair_geo=stair_geo, stair_panels=stair_panels, stud_stations=stud_stations,
        glass_height_mm=glass_height_mm,
    )

    # Flat BOM detail rows for PDF / quote (rate + amount + specs)
    bom_details = []
    for it in items:
        bom_details.append({
            "item": it.get("label"),
            "key": it.get("key"),
            "qty": it.get("qty"),
            "unit": it.get("unit"),
            "rate": it.get("rate"),
            "amount": it.get("amount"),
            "color": it.get("color"),
            "grade": it.get("grade"),
            "sizeMm": it.get("sizeMm"),
            "mountType": it.get("mountType") or (mount_hint if it.get("key") in ("blocks", "bottomRail") else None),
            "materialId": it.get("materialId"),
            "bends": bend_count if it.get("key") == "modularBend" else None,
            "anchors": anchor_count if it.get("key") == "anchors" else None,
            "endCaps": end_caps if it.get("key") == "endCap" else None,
            "wallConnectors": wall_connectors if it.get("key") == "wallConnector" else None,
        })

    return {
        "shape": shape,
        "lengthMm": round(total_length_mm, 2), "heightMm": round(height_mm if height_mm > 0 else glass_height_mm, 2),
        "glassHeightMm": round(glass_height_mm, 2),
        "glassThicknessMm": glass_thickness,
        "glassType": glass_type,
        "glassColour": glass_type,
        "glassBrand": glass_brand or None,
        "installComponents": {
            "bottomRail": want_bottom,
            "block": want_block,
            "ssPillar": want_ss,
            "handrail": handrail_on,
            "glass": want_glass,
        },
        "colorMode": color_mode,
        "systemColor": system_color or None,
        "componentColors": dict(component_colors) if component_colors else {},
        "lengthRft": round(length_rft, 3), "lengthRmt": round(length_rmt, 3),
        "saleUnit": sale_unit, "measurementBasis": basis, "widthUnit": round(width_unit, 3),
        "commercialRailingLengthRFT": round(commercial_rft, 4),
        "commercialRailingLengthRMT": round(commercial_rmt, 4),
        "panelCount": panel_count, "gapMm": gap, "wallGapMm": wall_gap,
        "panelWidthsMm": [round(w, 1) for w in all_panel_widths],
        "panelWidthsIn": panel_widths_in,
        "glassPanels": stair_panels if stair_panels else [
            {
                "index": i + 1,
                "panelWidthHorizontal": round(w, 2),
                "leftGlassHeight": round(glass_h_for_area, 2),
                "rightGlassHeight": round(glass_h_for_area, 2),
                "netGlassAreaSqFt": round(w * glass_h_for_area / SQMM_PER_SQFT, 4),
                "netGlassAreaSqMm": round(w * glass_h_for_area, 2),
            }
            for i, w in enumerate(all_panel_widths)
        ],
        "glassAreaSqft": round(net_sqft, 4),
        "glassAreaSqm": round(net_sqft * SQMM_PER_SQFT / SQMM_PER_SQM, 6),
        "netGlassAreaSqFt": round(net_sqft, 4),
        "purchasedGlassAreaSqFt": round(purchased_sqft, 4),
        "wastageAreaSqFt": round(_f(glass_nest.get("wastageAreaSqFt")), 4),
        "wastagePercent": glass_nest.get("wastagePercent"),
        "glassNesting": glass_nest,
        "wastageEnabled": apply_wastage,
        "pillarCount": pillar_count, "anchorsPerPillar": anchors_per_pillar,
        "anchorCount": anchor_count, "baseAnchorCount": base_anchors,
        "handrail": handrail_on, "wallConnectors": wall_connectors,
        "bendCount": bend_count, "connector180Count": connector_180, "endCapCount": end_caps,
        "stairPillars": stair_pillars, "stairStuds": stair_studs,
        "stairStudAnchors": stair_stud_anchors, "studSizeMm": stud_size,
        "studStations": stud_stations,
        "stairGeometry": stair_geo,
        "segments": run_details,
        "continuousRailSegments": sum(1 for r in run_details if r.get("continuousRail")),
        "mountType": mount_hint,
        "materialSelections": {
            k: {"id": v.get("id"), "name": v.get("name"), "category": v.get("category")}
            for k, v in gallery_meta.items()
        },
        "items": items, "bomDetails": bom_details,
        "extras": extras, "extrasTotal": round(extras_total, 2),
        "costCascade": cost,
        "internal": internal,
        "commercial": commercial,
        "total": total, "perUnitRate": round(float(per_unit_rate), 4),
        "manualRatePerUnit": manual_rate,
        "sellingPerUnit": round(float(selling_per_unit), 4), "sellingTotal": selling_total,
        "sellingRatePerRFT": commercial["sellingRatePerRFT"],
        "sellingRatePerRMT": commercial["sellingRatePerRMT"],
        "geometry": geometry,
    }


# ── 2D designer geometry + SVG ───────────────────────────────────────────────

def _railing_geometry(
    *, shape: str, height_mm: float, segments: list[dict[str, Any]],
    run_details: list[dict[str, Any]], gap: float, wall_gap: float,
    wall_start: bool, wall_end: bool, handrail: bool,
    bend_count: int, end_caps: int, connector_180: int, cfg: Mapping[str, Any],
    stair_geo: Mapping[str, Any] | None = None,
    stair_panels: list[dict[str, Any]] | None = None,
    stud_stations: list[dict[str, Any]] | None = None,
    glass_height_mm: float = 0.0,
) -> dict[str, Any]:
    pts = _polyline_points(segments, start_heading_deg=_f(cfg.get("startHeadingDeg"), 90.0))
    rail_h = max(min(height_mm * 0.06, 60.0), 25.0) if height_mm else 40.0
    sg = dict(stair_geo or {})
    return {
        "shape": shape,
        "heightMm": round(height_mm, 1),
        "glassHeightMm": round(glass_height_mm or height_mm, 1),
        "railH": round(rail_h, 1),
        "handrail": handrail,
        "wallStart": wall_start, "wallEnd": wall_end,
        "gap": gap, "wallGap": wall_gap,
        "bendCount": bend_count, "endCapCount": end_caps, "connector180Count": connector_180,
        "points": [{"x": round(x, 1), "y": round(y, 1)} for x, y in pts],
        "segments": run_details,
        "stairSteps": _i(sg.get("steps"), _i(cfg.get("stairSteps"), _i(segments[0].get("steps") if segments else 0, 0))),
        "stairRiseMm": _f(sg.get("riserMm"), _f(cfg.get("stairRiseMm"), _f(segments[0].get("riseMm") if segments else 0, 150))),
        "stairRunMm": _f(sg.get("treadMm"), _f(cfg.get("stairRunMm"), _f(segments[0].get("runMm") if segments else 0, 250))),
        "stairAngleDeg": _f(sg.get("stairAngleDeg")),
        "complementaryAngleDeg": _f(sg.get("complementaryAngleDeg")),
        "riseMismatch": bool(sg.get("riseMismatch")),
        "riseMismatchMessage": sg.get("riseMismatchMessage"),
        "glassPanels": list(stair_panels or []),
        "studStations": list(stud_stations or []),
        "studSizeMm": _i(cfg.get("studSizeMm"), 38),
        "archSpanMm": _f(segments[0].get("spanMm") if segments else 0, 0),
        "archRiseMm": _f(segments[0].get("riseMm") if segments else 0, 0),
        "archRadiusMm": _f(segments[0].get("radiusMm") if segments else 0, 0),
        "lengthMm": round(sum(_f(s.get("lengthMm")) for s in segments), 1),
        "panels": list(stair_panels or []),
        "blocks": [],
    }


def railing_svg(cfg: Mapping[str, Any], *, quote: Mapping[str, Any] | None = None) -> str:
    """2D railing drawing — plan+elevations for multi-segment; elevation for straight; stair side view."""
    q = quote if isinstance(quote, Mapping) else compute_railing(cfg)
    g = q.get("geometry") or {}
    shape = str(g.get("shape") or q.get("shape") or "straight")

    if shape == "straight" and len(g.get("segments") or []) <= 1:
        return _svg_elevation_straight(cfg, q, g)
    if shape == "staircase":
        return _svg_staircase(q, g)
    if shape == "arch":
        return _svg_arch_plan(q, g)
    # L / U / polyline → shop drawing: plan + per-span elevations
    return _svg_shop_drawing_multi(cfg, q, g)


def _svg_elevation_straight(cfg: Mapping[str, Any], q: Mapping[str, Any], g: Mapping[str, Any]) -> str:
    """Classic front elevation for a single straight run (with glass panels)."""
    segs = g.get("segments") or []
    L = _f(g.get("lengthMm")) or _f(q.get("lengthMm")) or 1.0
    Hgt = _f(g.get("heightMm")) or _f(q.get("heightMm")) or 1.0
    rail_h = _f(g.get("railH"), 40.0)
    hand_h = rail_h if g.get("handrail") else 0.0
    post_w = max(min(L * 0.01, 40.0), 18.0)
    gap = _f(g.get("gap"), 12.0)
    wall_gap = _f(g.get("wallGap"), 12.0)
    wall_left = bool(g.get("wallStart", True))
    wall_right = bool(g.get("wallEnd", True))

    widths = []
    if segs and segs[0].get("panelWidthsMm"):
        widths = [float(w) for w in segs[0]["panelWidthsMm"]]
    else:
        widths = [float(w) for w in (q.get("panelWidthsMm") or [])]

    pad = max(L, Hgt) * 0.16 + 120.0
    vb_w = L + pad * 2
    vb_h = Hgt + pad * 2
    ox, oy = pad, pad

    def X(mx: float) -> float:
        return ox + mx

    def Y(my: float) -> float:
        return oy + (Hgt - my)

    sw = max(L, Hgt) / 500.0
    stroke, glass, glass_stroke, dim = "#14181c", "#e6eef6", "#2f6db0", "#8c1f18"
    fs = max(vb_w, vb_h) * 0.018
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.1f} {vb_h:.1f}" font-family="Segoe UI, Arial, sans-serif">',
        f'<rect x="0" y="0" width="{vb_w:.1f}" height="{vb_h:.1f}" fill="#ffffff"/>',
        f'<rect x="{X(0):.1f}" y="{Y(rail_h):.1f}" width="{L:.1f}" height="{rail_h:.1f}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>',
    ]
    if hand_h > 0:
        p.append(f'<rect x="{X(0):.1f}" y="{Y(Hgt):.1f}" width="{L:.1f}" height="{hand_h:.1f}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>')
    for px in (0.0, L - post_w):
        p.append(f'<rect x="{X(px):.1f}" y="{Y(Hgt):.1f}" width="{post_w:.1f}" height="{Hgt:.1f}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>')

    x = wall_gap if wall_left else 0.0
    glass_y0, glass_y1 = rail_h, Hgt - hand_h
    panel_start = _i((segs[0] if segs else {}).get("panelStartIndex"), 1)
    for i, w in enumerate(widths):
        gx0, gx1 = x, x + w
        p.append(f'<rect x="{X(gx0):.1f}" y="{Y(glass_y1):.1f}" width="{(gx1-gx0):.1f}" height="{(glass_y1-glass_y0):.1f}" '
                 f'fill="{glass}" stroke="{glass_stroke}" stroke-width="{sw*0.8:.2f}"/>')
        pno = panel_start + i
        p.append(f'<text x="{X((gx0+gx1)/2):.1f}" y="{Y((glass_y0+glass_y1)/2):.1f}" text-anchor="middle" font-size="{fs:.1f}" fill="#173a63">Panel #{pno}</text>')
        _dim_h(p, X(gx0), X(gx1), Y(0) + fs * 1.6, f'{(gx1-gx0):.0f}', dim, sw, fs)
        # Gap label between panels
        if i < len(widths) - 1:
            p.append(f'<text x="{X(gx1 + gap/2):.1f}" y="{Y(glass_y1) - fs*0.3:.1f}" text-anchor="middle" '
                     f'font-size="{fs*0.65:.1f}" fill="#666">gap {gap:.0f}</text>')
        # pillars along panel with 100 mm edge rule inside panel
        n_block = _i((cfg or {}).get("blocksPerGlass"), _i((segs[0] if segs else {}).get("blocksPerGlass"), 0))
        for bx in _pillar_positions_along(w, n_block):
            cx = gx0 + bx
            bw = post_w
            p.append(f'<rect x="{X(cx-bw/2):.1f}" y="{Y(rail_h*1.4):.1f}" width="{bw:.1f}" height="{rail_h*1.4:.1f}" '
                     f'fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>')
        x = gx1 + gap

    # End caps / wall ticks
    if wall_left:
        p.append(f'<rect x="{X(-40):.1f}" y="{Y(Hgt):.1f}" width="30" height="{Hgt:.1f}" fill="#dfe6ea" stroke="{stroke}" stroke-width="{sw*0.6:.2f}"/>')
        p.append(f'<text x="{X(-25):.1f}" y="{Y(Hgt/2):.1f}" text-anchor="middle" font-size="{fs*0.7:.1f}" fill="#444" transform="rotate(-90 {X(-25):.1f} {Y(Hgt/2):.1f})">Wall</text>')
    elif q.get("endCapCount"):
        p.append(f'<circle cx="{X(0):.1f}" cy="{Y(Hgt-hand_h/2 if hand_h else Hgt):.1f}" r="{post_w*0.45:.1f}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}"/>')
    if wall_right:
        p.append(f'<rect x="{X(L+10):.1f}" y="{Y(Hgt):.1f}" width="30" height="{Hgt:.1f}" fill="#dfe6ea" stroke="{stroke}" stroke-width="{sw*0.6:.2f}"/>')
        p.append(f'<text x="{X(L+25):.1f}" y="{Y(Hgt/2):.1f}" text-anchor="middle" font-size="{fs*0.7:.1f}" fill="#444" transform="rotate(-90 {X(L+25):.1f} {Y(Hgt/2):.1f})">Wall</text>')

    _dim_h(p, X(0), X(L), Y(0) + fs * 3.4, f'{L:.0f} mm  ·  {q.get("lengthRft")} RFT', dim, sw, fs)
    _dim_v(p, Y(0), Y(Hgt), X(0) - fs * 1.6, f'{Hgt:.0f}', dim, sw, fs)
    mount = q.get("mountType") or "side_mount"
    summ = (f'Railing · straight · {q.get("panelCount")} panels · {q.get("glassAreaSqft")} sft · '
            f'{mount} · waste {q.get("wastagePercent", 0)}%')
    p.append(f'<text x="{X(0):.1f}" y="{oy - fs*0.6:.1f}" font-size="{fs*1.05:.1f}" fill="#111">{escape(summ)}</text>')
    p.append('</svg>')
    return "".join(p)


def _svg_elevation_span(
    *, L: float, Hgt: float, widths: list[float], gap: float, wall_gap: float,
    wall_left: bool, wall_right: bool, handrail: bool, blocks_per_glass: int,
    panel_start: int, title: str, ox: float, oy: float, scale: float = 1.0,
) -> tuple[list[str], float, float]:
    """Draw one span elevation into SVG fragments; returns (parts, width, height) in SVG units."""
    rail_h = max(min(Hgt * 0.06, 60.0), 25.0)
    hand_h = rail_h if handrail else 0.0
    post_w = max(min(L * 0.01, 40.0), 18.0)
    stroke, glass, glass_stroke, dim = "#14181c", "#e6eef6", "#2f6db0", "#8c1f18"
    sw = max(L, Hgt) / 500.0
    fs = max(L, Hgt) * 0.022 * scale
    pad_x, pad_y = 80.0, 70.0

    def X(mx: float) -> float:
        return ox + pad_x + mx

    def Y(my: float) -> float:
        return oy + pad_y + (Hgt - my)

    parts: list[str] = [
        f'<text x="{ox + pad_x:.1f}" y="{oy + fs*1.1:.1f}" font-size="{fs*1.05:.1f}" fill="#111" font-weight="600">{escape(title)}</text>',
        f'<rect x="{X(0):.1f}" y="{Y(rail_h):.1f}" width="{L:.1f}" height="{rail_h:.1f}" fill="#f0f2f4" stroke="{stroke}" stroke-width="{sw:.2f}"/>',
    ]
    if hand_h > 0:
        parts.append(f'<line x1="{X(0):.1f}" y1="{Y(Hgt):.1f}" x2="{X(L):.1f}" y2="{Y(Hgt):.1f}" '
                     f'stroke="#6b3fa0" stroke-width="{sw*2:.2f}"/>')

    x = wall_gap if wall_left else 0.0
    glass_y0, glass_y1 = rail_h, Hgt - hand_h
    for i, w in enumerate(widths):
        if w <= 0:
            continue
        gx0, gx1 = x, x + w
        parts.append(
            f'<rect x="{X(gx0):.1f}" y="{Y(glass_y1):.1f}" width="{(gx1-gx0):.1f}" height="{(glass_y1-glass_y0):.1f}" '
            f'fill="{glass}" stroke="{glass_stroke}" stroke-width="{sw*0.8:.2f}"/>'
        )
        pno = panel_start + i
        parts.append(
            f'<text x="{X((gx0+gx1)/2):.1f}" y="{Y((glass_y0+glass_y1)/2):.1f}" text-anchor="middle" '
            f'font-size="{fs*0.9:.1f}" fill="#173a63">Panel #{pno}</text>'
        )
        _dim_h(parts, X(gx0), X(gx1), Y(0) + fs * 1.4, f'{w:.0f}', dim, sw, fs * 0.85)
        if i < len(widths) - 1:
            parts.append(
                f'<text x="{X(gx1 + gap/2):.1f}" y="{Y(glass_y1)-fs*0.25:.1f}" text-anchor="middle" '
                f'font-size="{fs*0.6:.1f}" fill="#666">{gap:.0f}</text>'
            )
        for bx in _pillar_positions_along(w, blocks_per_glass):
            cx = gx0 + bx
            parts.append(
                f'<rect x="{X(cx-post_w/2):.1f}" y="{Y(rail_h*1.5):.1f}" width="{post_w:.1f}" height="{rail_h*1.5:.1f}" '
                f'fill="#fff" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
            )
        x = gx1 + gap

    if wall_left:
        parts.append(f'<rect x="{X(-36):.1f}" y="{Y(Hgt):.1f}" width="28" height="{Hgt:.1f}" fill="#dfe6ea" stroke="{stroke}" stroke-width="{sw*0.5:.2f}"/>')
    if wall_right:
        parts.append(f'<rect x="{X(L+8):.1f}" y="{Y(Hgt):.1f}" width="28" height="{Hgt:.1f}" fill="#dfe6ea" stroke="{stroke}" stroke-width="{sw*0.5:.2f}"/>')
    _dim_h(parts, X(0), X(L), Y(0) + fs * 3.0, f'{L:.0f} mm', dim, sw, fs * 0.9)
    _dim_v(parts, Y(0), Y(Hgt), X(0) - fs * 1.4, f'{Hgt:.0f}', dim, sw, fs * 0.85)
    drawn_w = L + pad_x * 2 + 40
    drawn_h = Hgt + pad_y * 2 + fs * 2
    return parts, drawn_w, drawn_h


def _svg_shop_drawing_multi(cfg: Mapping[str, Any], q: Mapping[str, Any], g: Mapping[str, Any]) -> str:
    """Shop drawing: plan (top) + per-span elevations (Panel #, gaps, blocks) for L/U/poly."""
    segs = list(g.get("segments") or q.get("segments") or [])
    Hgt = _f(g.get("heightMm") or q.get("heightMm") or q.get("glassHeightMm"), 900.0)
    gap = _f(g.get("gap"), DEFAULT_GLASS_GAP_MM)
    wall_gap = _f(g.get("wallGap"), DEFAULT_GLASS_GAP_MM)
    handrail = bool(g.get("handrail") or q.get("handrail"))
    blocks_default = _i(cfg.get("blocksPerGlass"), 0)

    pts_raw = g.get("points") or []
    pts = [(_f(p.get("x")), _f(p.get("y"))) for p in pts_raw]
    if len(pts) < 2:
        pts = [(0.0, 0.0), (_f(q.get("lengthMm"), 1000.0), 0.0)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    span_x = max(max(xs) - min(xs), 1.0)
    span_y = max(max(ys) - min(ys), 1.0)
    plan_pad = max(span_x, span_y) * 0.18 + 160.0
    plan_w = span_x + plan_pad * 2
    plan_h = span_y + plan_pad * 2

    elev_parts_all: list[str] = []
    elev_y = 36.0 + plan_h + 24.0
    elev_max_w = plan_w
    for si, seg in enumerate(segs):
        L = _f(seg.get("lengthMm"))
        widths = [float(w) for w in (seg.get("panelWidthsMm") or [])]
        if not widths:
            continue
        label = str(seg.get("label") or f"Span {chr(65 + si)}")
        pstart = _i(seg.get("panelStartIndex"), 1)
        bpg = _i(seg.get("blocksPerGlass"), blocks_default)
        title = f"{label} elevation · {len(widths)} panels · {L:.0f} mm"
        parts, dw, dh = _svg_elevation_span(
            L=L, Hgt=Hgt, widths=widths, gap=gap, wall_gap=wall_gap,
            wall_left=bool(seg.get("wallStart")), wall_right=bool(seg.get("wallEnd")),
            handrail=handrail, blocks_per_glass=bpg, panel_start=pstart,
            title=title, ox=20.0, oy=elev_y,
        )
        elev_parts_all.extend(parts)
        elev_y += dh + 30.0
        elev_max_w = max(elev_max_w, dw + 40.0)

    vb_w = max(plan_w, elev_max_w) + 20.0
    vb_h = elev_y + 40.0
    plan_body = _svg_plan_polyline(q, g)
    inner = plan_body
    if inner.startswith("<svg"):
        start = inner.find(">")
        end = inner.rfind("</svg>")
        if start >= 0 and end > start:
            inner = inner[start + 1:end]

    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.1f} {vb_h:.1f}" font-family="Segoe UI, Arial, sans-serif">',
        f'<rect x="0" y="0" width="{vb_w:.1f}" height="{vb_h:.1f}" fill="#ffffff"/>',
        f'<text x="20" y="28" font-size="22" fill="#111" font-weight="600">'
        f'Railing shop drawing · {escape(str(q.get("shape")))} · '
        f'{q.get("panelCount")} panels · waste {q.get("wastagePercent", 0)}% · '
        f'{escape(str(q.get("mountType") or ""))}</text>',
        f'<svg x="0" y="36" width="{plan_w:.1f}" height="{plan_h:.1f}" viewBox="0 0 {plan_w:.1f} {plan_h:.1f}">',
        inner,
        '</svg>',
    ]
    p.extend(elev_parts_all)
    p.append('</svg>')
    return "".join(p)


def _svg_plan_polyline(q: Mapping[str, Any], g: Mapping[str, Any]) -> str:
    """Plan (top) view for L / U / polyline with segment dims, bends, walls, end caps."""
    pts_raw = g.get("points") or []
    pts = [(_f(p.get("x")), _f(p.get("y"))) for p in pts_raw]
    if len(pts) < 2:
        pts = [(0.0, 0.0), (_f(q.get("lengthMm"), 1000.0), 0.0)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    pad = max(span_x, span_y) * 0.18 + 160.0
    vb_w = span_x + pad * 2
    vb_h = span_y + pad * 2
    ox = pad - min_x
    oy = pad + max_y  # flip Y for SVG

    def X(mx: float) -> float:
        return ox + mx

    def Y(my: float) -> float:
        return oy - my

    sw = max(span_x, span_y) / 450.0
    stroke, dim, bend_c, rail_c = "#14181c", "#8c1f18", "#0a5a48", "#2f6db0"
    fs = max(vb_w, vb_h) * 0.016
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.1f} {vb_h:.1f}" font-family="Segoe UI, Arial, sans-serif">',
        f'<rect x="0" y="0" width="{vb_w:.1f}" height="{vb_h:.1f}" fill="#ffffff"/>',
    ]
    # Path polyline
    d = " ".join(f'{"M" if i == 0 else "L"}{X(x):.1f},{Y(y):.1f}' for i, (x, y) in enumerate(pts))
    p.append(f'<path d="{d}" fill="none" stroke="{rail_c}" stroke-width="{sw*2.2:.2f}" stroke-linecap="round" stroke-linejoin="round"/>')
    p.append(f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{sw*0.9:.2f}" stroke-linecap="round" stroke-linejoin="round"/>')

    segs = g.get("segments") or []
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        L = math.hypot(x1 - x0, y1 - y0)
        label = f'{L:.0f}'
        p.append(f'<text x="{X(mx):.1f}" y="{Y(my) - fs*0.4:.1f}" text-anchor="middle" font-size="{fs:.1f}" fill="{dim}">{escape(label)}</text>')
        # Pillar ticks along segment
        positions = (segs[i].get("pillarPositionsMm") if i < len(segs) else None) or []
        dx, dy = x1 - x0, y1 - y0
        for s in positions:
            t = s / L if L else 0
            px, py = x0 + dx * t, y0 + dy * t
            p.append(f'<rect x="{X(px)-sw*3:.1f}" y="{Y(py)-sw*3:.1f}" width="{sw*6:.1f}" height="{sw*6:.1f}" '
                     f'fill="#fff" stroke="{stroke}" stroke-width="{sw*0.7:.2f}"/>')
        # Bend marker at corner (end of segment except last)
        if i < len(pts) - 2:
            p.append(f'<circle cx="{X(x1):.1f}" cy="{Y(y1):.1f}" r="{sw*4:.1f}" fill="#e7f3ee" stroke="{bend_c}" stroke-width="{sw*0.8:.2f}"/>')
            p.append(f'<text x="{X(x1)+fs*0.6:.1f}" y="{Y(y1)-fs*0.3:.1f}" font-size="{fs*0.75:.1f}" fill="{bend_c}">bend</text>')

    # Wall / end-cap markers
    def _end_marker(pt: tuple[float, float], is_wall: bool, label: str) -> None:
        x, y = pt
        if is_wall:
            p.append(f'<rect x="{X(x)-fs*1.2:.1f}" y="{Y(y)-fs*0.45:.1f}" width="{fs*2.4:.1f}" height="{fs*0.9:.1f}" '
                     f'rx="{fs*0.2:.1f}" fill="#dfe6ea" stroke="{stroke}" stroke-width="{sw*0.6:.2f}"/>')
            p.append(f'<text x="{X(x):.1f}" y="{Y(y)+fs*0.25:.1f}" text-anchor="middle" font-size="{fs*0.7:.1f}" fill="#333">Wall</text>')
        else:
            p.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="{sw*3.5:.1f}" fill="#fff" stroke="{stroke}" stroke-width="{sw:.2f}"/>')
            p.append(f'<text x="{X(x):.1f}" y="{Y(y)-fs*0.7:.1f}" text-anchor="middle" font-size="{fs*0.65:.1f}" fill="#555">end cap</text>')

    _end_marker(pts[0], bool(g.get("wallStart", True)), "start")
    _end_marker(pts[-1], bool(g.get("wallEnd", True)), "end")

    shape = g.get("shape") or q.get("shape")
    summ = (f'Railing · {shape} · {len(segs)} runs · {q.get("lengthMm")} mm · '
            f'bends {q.get("bendCount", 0)} · 180°×{q.get("connector180Count", 0)} · caps {q.get("endCapCount", 0)}')
    p.append(f'<text x="{pad*0.3:.1f}" y="{fs*1.4:.1f}" font-size="{fs*1.05:.1f}" fill="#111">{escape(summ)}</text>')
    p.append(f'<text x="{pad*0.3:.1f}" y="{fs*2.6:.1f}" font-size="{fs*0.85:.1f}" fill="#555">'
             f'{q.get("lengthRft")} RFT · pillars {q.get("pillarCount")} · anchors {q.get("anchorCount")}</text>')
    p.append('</svg>')
    return "".join(p)


def _svg_arch_plan(q: Mapping[str, Any], g: Mapping[str, Any]) -> str:
    span = _f(g.get("archSpanMm"), _f(q.get("lengthMm"), 4000))
    rise = _f(g.get("archRiseMm"), span * 0.35)
    r = _f(g.get("archRadiusMm"))
    if r <= 0:
        r = (rise / 2.0) + (span ** 2) / (8.0 * max(rise, 1.0))
    pad = max(span, rise) * 0.2 + 140.0
    vb_w = span + pad * 2
    vb_h = rise + pad * 2
    ox, oy = pad, pad + rise
    sw = max(span, rise) / 400.0
    stroke, dim, rail_c = "#14181c", "#8c1f18", "#2f6db0"
    fs = max(vb_w, vb_h) * 0.018
    # SVG arc from (-span/2) to (+span/2) with given rise (approx via quadratic)
    x0, y0 = 0.0, 0.0
    x1, y1 = span, 0.0
    cx, cy = span / 2.0, rise

    def X(mx: float) -> float:
        return ox + mx

    def Y(my: float) -> float:
        return oy - my

    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.1f} {vb_h:.1f}" font-family="Segoe UI, Arial, sans-serif">',
        f'<rect x="0" y="0" width="{vb_w:.1f}" height="{vb_h:.1f}" fill="#ffffff"/>',
        f'<path d="M {X(x0):.1f},{Y(y0):.1f} Q {X(cx):.1f},{Y(cy):.1f} {X(x1):.1f},{Y(y1):.1f}" '
        f'fill="none" stroke="{rail_c}" stroke-width="{sw*2.2:.2f}"/>',
        f'<path d="M {X(x0):.1f},{Y(y0):.1f} Q {X(cx):.1f},{Y(cy):.1f} {X(x1):.1f},{Y(y1):.1f}" '
        f'fill="none" stroke="{stroke}" stroke-width="{sw*0.9:.2f}"/>',
    ]
    _dim_h(p, X(0), X(span), Y(0) + fs * 2.2, f'span {span:.0f}', dim, sw, fs)
    _dim_v(p, Y(0), Y(rise), X(span / 2) + fs * 1.2, f'rise {rise:.0f}', dim, sw, fs)
    if g.get("wallStart"):
        p.append(f'<rect x="{X(-fs):.1f}" y="{Y(0)-fs*0.4:.1f}" width="{fs*1.6:.1f}" height="{fs*0.8:.1f}" rx="4" fill="#dfe6ea" stroke="{stroke}"/>')
        p.append(f'<text x="{X(0):.1f}" y="{Y(0)+fs*0.2:.1f}" text-anchor="middle" font-size="{fs*0.65:.1f}">Wall</text>')
    else:
        p.append(f'<circle cx="{X(0):.1f}" cy="{Y(0):.1f}" r="{sw*3:.1f}" fill="#fff" stroke="{stroke}"/>')
    if g.get("wallEnd"):
        p.append(f'<rect x="{X(span)-fs*0.8:.1f}" y="{Y(0)-fs*0.4:.1f}" width="{fs*1.6:.1f}" height="{fs*0.8:.1f}" rx="4" fill="#dfe6ea" stroke="{stroke}"/>')
    summ = f'Railing · arch · arc {q.get("lengthMm")} mm · caps {q.get("endCapCount", 0)}'
    p.append(f'<text x="{ox:.1f}" y="{fs*1.3:.1f}" font-size="{fs:.1f}" fill="#111">{escape(summ)}</text>')
    p.append('</svg>')
    return "".join(p)


def _svg_staircase(q: Mapping[str, Any], g: Mapping[str, Any]) -> str:
    """Side-view stair railing: trapezoid glass panels + dual studs every 3 steps."""
    steps = max(_i(g.get("stairSteps"), 12), 1)
    rise = _f(g.get("stairRiseMm"), 150.0)
    run = _f(g.get("stairRunMm"), 250.0)
    total_w = run * steps
    total_h = rise * steps
    glass_h = _f(g.get("glassHeightMm") or q.get("glassHeightMm") or q.get("heightMm"), 900.0)
    guard = min(max(glass_h, 600.0), 1400.0) if glass_h > 50 else 900.0
    angle = _f(g.get("stairAngleDeg"))
    if angle <= 0 and run > 0:
        angle = math.degrees(math.atan(rise / run))
    comp = _f(g.get("complementaryAngleDeg"), 90.0 - angle)
    panels = list(g.get("glassPanels") or g.get("panels") or q.get("glassPanels") or [])
    pad = max(total_w, total_h + guard) * 0.12 + 140.0
    vb_w = total_w + pad * 2
    vb_h = total_h + guard + pad * 2.2
    ox, oy = pad, pad + total_h + guard

    def X(mx: float) -> float:
        return ox + mx

    def Y(my: float) -> float:
        return oy - my

    def nosing_y_at(x_h: float) -> float:
        """Stair nosing elevation at horizontal position (sawtooth top envelope ≈ slope)."""
        if run <= 0:
            return 0.0
        # Continuous slope line through nosings for glass baseline.
        return (rise / run) * x_h

    sw = max(total_w, total_h) / 500.0
    stroke, dim, rail_c, stud_c = "#14181c", "#8c1f18", "#2f6db0", "#0a5a48"
    glass, glass_stroke = "#dceaf6", "#2f6db0"
    fs = max(vb_w, vb_h) * 0.014
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.1f} {vb_h:.1f}" font-family="Segoe UI, Arial, sans-serif">',
        f'<rect x="0" y="0" width="{vb_w:.1f}" height="{vb_h:.1f}" fill="#ffffff"/>',
    ]
    # Stair polyline
    sx = sy = 0.0
    d_steps = [f'M{X(0):.1f},{Y(0):.1f}']
    for _step in range(steps):
        sx += run
        d_steps.append(f'L{X(sx):.1f},{Y(sy):.1f}')
        sy += rise
        d_steps.append(f'L{X(sx):.1f},{Y(sy):.1f}')
    p.append(f'<path d="{" ".join(d_steps)}" fill="none" stroke="{stroke}" stroke-width="{sw*1.2:.2f}"/>')

    # Trapezoidal / parallelogram glass panels (vertical edges, slope-parallel top/bottom)
    if not panels:
        # Fallback equal split with 100 mm edge inset + 12 mm gaps
        n = max(_i(q.get("panelCount"), 3), 1)
        edge = GLASS_EDGE_INSET_MM
        gap = _f(g.get("gap"), DEFAULT_GLASS_GAP_MM)
        usable = max(total_w - 2 * edge, 0.0)
        each = max(usable - gap * max(n - 1, 0), 0.0) / n
        cursor = edge
        for i in range(n):
            panels.append({
                "index": i + 1,
                "panelStartHorizontalPosition": cursor,
                "panelEndHorizontalPosition": cursor + each,
                "leftGlassHeight": guard,
                "rightGlassHeight": guard,
            })
            cursor += each + gap

    for panel in panels:
        if str(panel.get("kind") or "slope") == "landing":
            continue  # landing drawn as rectangle at top if present
        x0 = _f(panel.get("panelStartHorizontalPosition"))
        x1 = _f(panel.get("panelEndHorizontalPosition"))
        if x1 <= x0:
            continue
        hl = _f(panel.get("leftGlassHeight"), guard)
        hr = _f(panel.get("rightGlassHeight"), guard)
        y0 = nosing_y_at(x0)
        y1 = nosing_y_at(x1)
        # Bottom-left, bottom-right, top-right, top-left (plumb sides)
        pts = [
            (X(x0), Y(y0)),
            (X(x1), Y(y1)),
            (X(x1), Y(y1 + hr)),
            (X(x0), Y(y0 + hl)),
        ]
        poly = " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)
        p.append(f'<polygon points="{poly}" fill="{glass}" fill-opacity="0.85" stroke="{glass_stroke}" stroke-width="{sw*0.85:.2f}"/>')
        mx = (x0 + x1) / 2
        my = nosing_y_at(mx) + (hl + hr) / 4
        label = f'G{panel.get("index", "")} { (x1-x0):.0f}×{max(hl,hr):.0f}'
        p.append(f'<text x="{X(mx):.1f}" y="{Y(my):.1f}" text-anchor="middle" font-size="{fs*0.85:.1f}" fill="#173a63">{escape(label)}</text>')

    # Landing rectangular panels (horizontal after run)
    for panel in panels:
        if str(panel.get("kind")) != "landing":
            continue
        x0 = _f(panel.get("panelStartHorizontalPosition"))
        x1 = _f(panel.get("panelEndHorizontalPosition"))
        # Map landing start onto top of stair (after total_w)
        lx0 = total_w + (x0 - total_w) if x0 >= total_w else total_w
        w = max(x1 - x0, 0.0)
        hl = _f(panel.get("leftGlassHeight"), guard)
        p.append(
            f'<rect x="{X(lx0):.1f}" y="{Y(total_h + hl):.1f}" width="{w:.1f}" height="{hl:.1f}" '
            f'fill="{glass}" fill-opacity="0.85" stroke="{glass_stroke}" stroke-width="{sw*0.85:.2f}"/>'
        )

    # Top rail along slope
    p.append(
        f'<line x1="{X(0):.1f}" y1="{Y(guard):.1f}" x2="{X(total_w):.1f}" y2="{Y(total_h + guard):.1f}" '
        f'stroke="{rail_c}" stroke-width="{sw*2:.2f}" stroke-linecap="round"/>'
    )

    stud_size = _i(g.get("studSizeMm"), 38)
    stations = g.get("studStations") or []
    if not stations:
        for n in range(3, steps + 1, 3):
            stations.append({"step": n, "horizontalMm": run * n, "riseMm": rise * n})
    for st in stations:
        px = _f(st.get("horizontalMm"), run * _i(st.get("step"), 0))
        py = _f(st.get("riseMm"), nosing_y_at(px))
        p.append(f'<line x1="{X(px):.1f}" y1="{Y(py):.1f}" x2="{X(px):.1f}" y2="{Y(py+guard):.1f}" '
                 f'stroke="{stroke}" stroke-width="{sw*1.5:.2f}"/>')
        # Dual studs (upper + lower) — side-mounted pairs opposite the step
        for frac in (0.35, 0.65):
            cy = py + guard * frac
            p.append(f'<circle cx="{X(px):.1f}" cy="{Y(cy):.1f}" r="{max(stud_size*0.18, sw*2.8):.1f}" '
                     f'fill="#e7f3ee" stroke="{stud_c}" stroke-width="{sw*0.75:.2f}"/>')
        p.append(f'<text x="{X(px)+fs*0.45:.1f}" y="{Y(py+guard*0.5):.1f}" font-size="{fs*0.7:.1f}" fill="{stud_c}">'
                 f'{stud_size}×2</text>')

    _dim_h(p, X(0), X(total_w), Y(0) + fs * 2.0, f'tread {run:.0f} × {steps} = {total_w:.0f} run', dim, sw, fs)
    _dim_v(p, Y(0), Y(total_h), X(0) - fs * 1.4, f'rise {total_h:.0f}', dim, sw, fs)
    mismatch = ""
    if g.get("riseMismatch") or (q.get("stairGeometry") or {}).get("riseMismatch"):
        msg = g.get("riseMismatchMessage") or (q.get("stairGeometry") or {}).get("riseMismatchMessage") or "rise ≠ floor height"
        mismatch = f' · ⚠ {msg}'
    summ = (f'Staircase railing · {steps} steps · {len(panels)} panels · '
            f'angle {angle:.2f}° / complement {comp:.2f}° · '
            f'pillars {q.get("stairPillars", 0)} · studs {q.get("stairStuds", 0)}')
    p.append(f'<text x="{ox:.1f}" y="{fs*1.25:.1f}" font-size="{fs:.1f}" fill="#111">{escape(summ)}</text>')
    p.append(f'<text x="{ox:.1f}" y="{fs*2.35:.1f}" font-size="{fs*0.85:.1f}" fill="#555">'
             f'net {q.get("netGlassAreaSqFt") or q.get("glassAreaSqft")} sft · '
             f'purchased {q.get("purchasedGlassAreaSqFt")} sft · '
             f'wastage {q.get("wastagePercent")}%{escape(mismatch)}</text>')
    p.append('</svg>')
    return "".join(p)


def _dim_h(p: list[str], x0: float, x1: float, y: float, text: str, dim: str, sw: float, fs: float) -> None:
    p.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" stroke="{dim}" stroke-width="{sw*0.7:.2f}"/>')
    for xx in (x0, x1):
        p.append(f'<line x1="{xx:.1f}" y1="{y-fs*0.4:.1f}" x2="{xx:.1f}" y2="{y+fs*0.4:.1f}" stroke="{dim}" stroke-width="{sw*0.7:.2f}"/>')
    p.append(f'<text x="{(x0+x1)/2:.1f}" y="{y-fs*0.5:.1f}" text-anchor="middle" font-size="{fs:.1f}" fill="{dim}">{escape(text)}</text>')


def _dim_v(p: list[str], y0: float, y1: float, x: float, text: str, dim: str, sw: float, fs: float) -> None:
    ylo, yhi = min(y0, y1), max(y0, y1)
    p.append(f'<line x1="{x:.1f}" y1="{ylo:.1f}" x2="{x:.1f}" y2="{yhi:.1f}" stroke="{dim}" stroke-width="{sw*0.7:.2f}"/>')
    for yy in (ylo, yhi):
        p.append(f'<line x1="{x-fs*0.4:.1f}" y1="{yy:.1f}" x2="{x+fs*0.4:.1f}" y2="{yy:.1f}" stroke="{dim}" stroke-width="{sw*0.7:.2f}"/>')
    cy = (ylo + yhi) / 2
    p.append(f'<text x="{x:.1f}" y="{cy:.1f}" text-anchor="middle" font-size="{fs:.1f}" fill="{dim}" '
             f'transform="rotate(-90 {x:.1f} {cy:.1f})">{escape(text)}</text>')
