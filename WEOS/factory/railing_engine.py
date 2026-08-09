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
SQMM_PER_SQFT = MM_PER_FT * MM_PER_FT
SQMM_PER_SQM = MM_PER_M * MM_PER_M

# Default stock length before a handrail needs a 180° join connector.
DEFAULT_HANDRAIL_MAX_MM = 6000.0
PILLAR_EDGE_MM = 100.0


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
        steps = max(_i(cfg.get("stairSteps"), 0), 0)
        rise = _f(cfg.get("stairRiseMm"), 150.0)
        run = _f(cfg.get("stairRunMm"), 250.0)
        if steps <= 0:
            total_rise = _f(cfg.get("stairTotalRiseMm"), _height_mm(cfg) or 2700.0)
            if rise <= 0:
                rise = 150.0
            steps = max(int(round(total_rise / rise)), 1)
        hyp = math.hypot(run, rise) * steps
        return [{"lengthMm": hyp, "turnDeg": 0, "kind": "staircase", "steps": steps,
                 "riseMm": rise, "runMm": run}]
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


def compute_railing(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Compute quantities, BOM, per-RFT/RMT rate, and geometry for any shape."""
    cfg = dict(cfg or {})
    shape = _shape(cfg)
    height_mm = _height_mm(cfg)
    if shape == "staircase" and height_mm <= 0:
        height_mm = _f(cfg.get("stairRiseMm"), 150.0) * max(_i(cfg.get("stairSteps"), 12), 1)

    segments = _preset_segments(shape, cfg)
    total_length_mm = sum(_f(s.get("lengthMm")) for s in segments)
    if shape == "arch":
        # Arc length ≈ π·r for semicircle, or chord-based approx with rise.
        span = _f(segments[0].get("lengthMm")) if segments else _length_mm(cfg)
        rise = _f(cfg.get("archRiseMm"), span * 0.35 if span else 1000.0)
        if rise > 0 and span > 0:
            # Circular arc through chord span and rise.
            r = (rise / 2.0) + (span ** 2) / (8.0 * rise)
            theta = 2.0 * math.asin(min(1.0, (span / 2.0) / max(r, 1e-6)))
            total_length_mm = r * theta
            segments = [{"lengthMm": total_length_mm, "turnDeg": 0, "kind": "arch",
                         "spanMm": span, "riseMm": rise, "radiusMm": r}]

    gap = _f(cfg.get("gapMm"), 12.0)
    wall_gap = _f(cfg.get("wallGapMm"), 12.0)
    wall_start = bool(cfg.get("wallStart", cfg.get("wallLeft", True)))
    wall_end = bool(cfg.get("wallEnd", cfg.get("wallRight", True)))
    sale_unit = str(cfg.get("saleUnit") or "rft").lower()
    if sale_unit not in ("rft", "rmt"):
        sale_unit = "rft"

    rates = dict(cfg.get("rates") or {})
    r_glass = _f(rates.get("glassPerSqft"), 200.0)
    r_block = _f(rates.get("blockPerPc"), 100.0)
    r_anchor = _f(rates.get("anchorPerPc"), 50.0)
    r_brail = _f(rates.get("bottomRailPerUnit"))
    w_brail = _f(rates.get("bottomRailWeightPerUnit"))
    r_hrail = _f(rates.get("handrailPerUnit"))
    w_hrail = _f(rates.get("handrailWeightPerUnit"))
    r_wall = _f(rates.get("wallConnectorPerPc"))
    r_bend = _f(rates.get("modularBendPerPc"), _f(rates.get("bendPerPc"), 0.0))
    r_conn180 = _f(rates.get("connector180PerPc"), 0.0)
    r_endcap = _f(rates.get("endCapPerPc"), 0.0)
    r_stud = _f(rates.get("studPerPc"), 0.0)

    panels_cfg = max(_i(cfg.get("panels"), 1), 1)
    blocks_per_glass = max(_i(cfg.get("blocksPerGlass"), 0), 0)
    pillar_edge = _f(cfg.get("pillarEdgeMm"), PILLAR_EDGE_MM)
    handrail_on = bool(cfg.get("handrail", shape != "straight"))
    handrail_max = _f(cfg.get("handrailMaxMm"), DEFAULT_HANDRAIL_MAX_MM)
    continuous_rail = bool(cfg.get("continuousRail", blocks_per_glass == 0))

    # ── per-segment glass / pillars ─────────────────────────────────────────
    explicit = cfg.get("panelSizesMm")
    explicit_list = [max(_f(x), 0.0) for x in explicit] if isinstance(explicit, (list, tuple)) else None

    run_details: list[dict[str, Any]] = []
    all_panel_widths: list[float] = []
    pillar_count = 0
    pillar_positions_plan: list[dict[str, Any]] = []

    n_seg = len(segments)
    for si, seg in enumerate(segments):
        L = _f(seg.get("lengthMm"))
        # Walls only at path ends for multi-segment (middle corners use bends).
        w_left = wall_start if si == 0 else False
        w_right = wall_end if si == n_seg - 1 else False
        # Distribute panels across segments proportionally for multi-run.
        if n_seg == 1:
            seg_panels = panels_cfg
            seg_explicit = explicit_list
        else:
            share = L / total_length_mm if total_length_mm else 0
            seg_panels = max(1, int(round(panels_cfg * share))) if panels_cfg else 1
            seg_explicit = None
        widths = _panel_widths_for_run(
            L, panels=seg_panels, gap=gap, wall_gap=wall_gap,
            wall_left=w_left, wall_right=w_right, explicit=seg_explicit,
        )
        all_panel_widths.extend(widths)
        # Pillars: blocks_per_glass × panels, or equal-space with 100 mm edges.
        if blocks_per_glass > 0:
            n_pillars = blocks_per_glass * len(widths)
        elif continuous_rail:
            n_pillars = 0
        else:
            n_pillars = max(_i(cfg.get("pillarsPerSegment"), 0), 0)
        positions = _pillar_positions_along(L, n_pillars, edge_mm=pillar_edge)
        pillar_count += len(positions)
        for px in positions:
            pillar_positions_plan.append({"segment": si, "sMm": round(px, 1)})
        run_details.append({
            "index": si,
            "lengthMm": round(L, 1),
            "turnDeg": _f(seg.get("turnDeg")),
            "kind": seg.get("kind") or "straight",
            "panelWidthsMm": [round(w, 1) for w in widths],
            "pillarPositionsMm": [round(p, 1) for p in positions],
            "wallStart": w_left,
            "wallEnd": w_right,
            "continuousRail": n_pillars == 0,
        })

    panel_count = len(all_panel_widths)
    panel_widths_in = [round(w / MM_PER_IN, 2) for w in all_panel_widths]
    glass_area_sqmm = sum(w * height_mm for w in all_panel_widths)
    glass_area_sqft = glass_area_sqmm / SQMM_PER_SQFT
    glass_area_sqm = glass_area_sqmm / SQMM_PER_SQM

    # ── corner / join hardware ──────────────────────────────────────────────
    bend_count = sum(1 for s in segments[:-1] if abs(_f(s.get("turnDeg"))) > 1e-6)
    # Arch uses no modular bends (continuous curve).
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

    # ── staircase studs ─────────────────────────────────────────────────────
    stair_pillars = 0
    stair_studs = 0
    stair_stud_anchors = 0
    stud_size = _i(cfg.get("studSizeMm"), 38)
    if stud_size not in (38, 50):
        stud_size = 38
    if shape == "staircase":
        steps = max(_i(cfg.get("stairSteps"), _i(segments[0].get("steps") if segments else 0, 12)), 1)
        # Every 3 steps → one side-mounted pillar/block
        stair_pillars = steps // 3
        # Opposite the 3rd step (and every 3rd): dual SS studs, 1 anchor each
        dual_stations = steps // 3
        stair_studs = dual_stations * 2
        stair_stud_anchors = stair_studs  # 1 anchor per stud
        pillar_count = stair_pillars
        # Glass along hypotenuse — keep panel math from above
        bend_count = 0
        connector_180 = _handrail_connectors(total_length_mm, handrail_max) if handrail_on else 0

    anchors_per_pillar = min(max(_i(cfg.get("anchorsPerPillar"), 1), 1), 2) if pillar_count else 0
    pillar_anchors = pillar_count * anchors_per_pillar
    length_rft = total_length_mm / MM_PER_FT if total_length_mm else 0.0
    length_rmt = total_length_mm / MM_PER_M if total_length_mm else 0.0
    width_unit = length_rft if sale_unit == "rft" else length_rmt

    anchors_per_rft = _f(cfg.get("anchorsPerRft"), 0.0)
    include_base = bool(cfg.get("includeBaseAnchors", False))
    base_anchors = math.ceil(length_rft * anchors_per_rft) if (include_base and anchors_per_rft) else 0
    anchor_count = pillar_anchors + base_anchors + stair_stud_anchors
    if anchor_count == 0 and not pillar_count and shape != "staircase":
        anchor_count = math.ceil(length_rft * (anchors_per_rft or 1.0))

    rail_unit_len = width_unit
    items: list[dict[str, Any]] = []

    def add(key: str, label: str, qty: float, unit: str, rate: float, weight: float | None = None) -> None:
        amount = round(qty * rate, 2)
        row = {"key": key, "label": label, "qty": round(qty, 3), "unit": unit, "rate": round(rate, 3), "amount": amount}
        if weight is not None:
            row["weightKg"] = round(weight, 3)
        items.append(row)

    if glass_area_sqft > 0 and shape != "staircase":
        add("glass", "Glass", round(glass_area_sqft, 3), "sqft", r_glass)
    elif glass_area_sqft > 0 and shape == "staircase" and bool(cfg.get("stairGlass", False)):
        add("glass", "Glass", round(glass_area_sqft, 3), "sqft", r_glass)

    if pillar_count:
        label = f"Blocks / pillars ({cfg.get('pillarType') or 'block'})"
        if shape == "staircase":
            label = f"Side-mount pillars (every 3 steps · {cfg.get('pillarType') or 'block'})"
        add("blocks", label, pillar_count, "pc", r_block)
    if stair_studs:
        add("studs", f"SS studs {stud_size} mm (dual @ 3rd steps)", stair_studs, "pc", r_stud or r_block)
    if anchor_count:
        add("anchors", "Anchor bolts", anchor_count, "pc", r_anchor)
    if r_brail and total_length_mm:
        add("bottomRail", "Bottom / continuous rail", round(rail_unit_len, 3), sale_unit, r_brail,
            weight=rail_unit_len * w_brail if w_brail else None)
    if handrail_on and r_hrail and total_length_mm:
        add("handrail", "Handrail", round(rail_unit_len, 3), sale_unit, r_hrail,
            weight=rail_unit_len * w_hrail if w_hrail else None)
    if bend_count and (r_bend or True):
        add("modularBend", "Modular bend (corners)", bend_count, "pc", r_bend)
    if connector_180 and (r_conn180 or True):
        add("connector180", "180° handrail connector", connector_180, "pc", r_conn180)
    if end_caps and (r_endcap or True):
        add("endCap", "Handrail end cap", end_caps, "pc", r_endcap)
    if wall_connectors and r_wall:
        add("wallConnector", "Wall connector", wall_connectors, "pc", r_wall)

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
    total = round(items_total + extras_total, 2)
    per_unit_rate = round(total / width_unit, 2) if width_unit else 0.0
    manual = cfg.get("manualRatePerUnit")
    manual_rate = _f(manual) if manual not in (None, "") else None
    selling_per_unit = manual_rate if manual_rate is not None else per_unit_rate
    selling_total = round(selling_per_unit * width_unit, 2) if width_unit else round(total, 2)

    geometry = _railing_geometry(
        shape=shape, height_mm=height_mm, segments=segments, run_details=run_details,
        gap=gap, wall_gap=wall_gap, wall_start=wall_start, wall_end=wall_end,
        handrail=handrail_on, bend_count=bend_count, end_caps=end_caps,
        connector_180=connector_180, cfg=cfg,
    )

    return {
        "shape": shape,
        "lengthMm": round(total_length_mm, 2), "heightMm": round(height_mm, 2),
        "lengthRft": round(length_rft, 3), "lengthRmt": round(length_rmt, 3),
        "saleUnit": sale_unit, "widthUnit": round(width_unit, 3),
        "panelCount": panel_count, "gapMm": gap, "wallGapMm": wall_gap,
        "panelWidthsMm": [round(w, 1) for w in all_panel_widths],
        "panelWidthsIn": panel_widths_in,
        "glassAreaSqft": round(glass_area_sqft, 3), "glassAreaSqm": round(glass_area_sqm, 4),
        "pillarCount": pillar_count, "anchorsPerPillar": anchors_per_pillar,
        "anchorCount": anchor_count, "baseAnchorCount": base_anchors,
        "handrail": handrail_on, "wallConnectors": wall_connectors,
        "bendCount": bend_count, "connector180Count": connector_180, "endCapCount": end_caps,
        "stairPillars": stair_pillars, "stairStuds": stair_studs,
        "stairStudAnchors": stair_stud_anchors, "studSizeMm": stud_size,
        "segments": run_details,
        "continuousRailSegments": sum(1 for r in run_details if r.get("continuousRail")),
        "items": items, "extras": extras, "extrasTotal": round(extras_total, 2),
        "total": total, "perUnitRate": per_unit_rate,
        "manualRatePerUnit": manual_rate,
        "sellingPerUnit": round(selling_per_unit, 2), "sellingTotal": selling_total,
        "geometry": geometry,
    }


# ── 2D designer geometry + SVG ───────────────────────────────────────────────

def _railing_geometry(
    *, shape: str, height_mm: float, segments: list[dict[str, Any]],
    run_details: list[dict[str, Any]], gap: float, wall_gap: float,
    wall_start: bool, wall_end: bool, handrail: bool,
    bend_count: int, end_caps: int, connector_180: int, cfg: Mapping[str, Any],
) -> dict[str, Any]:
    pts = _polyline_points(segments, start_heading_deg=_f(cfg.get("startHeadingDeg"), 90.0))
    rail_h = max(min(height_mm * 0.06, 60.0), 25.0) if height_mm else 40.0
    return {
        "shape": shape,
        "heightMm": round(height_mm, 1),
        "railH": round(rail_h, 1),
        "handrail": handrail,
        "wallStart": wall_start, "wallEnd": wall_end,
        "gap": gap, "wallGap": wall_gap,
        "bendCount": bend_count, "endCapCount": end_caps, "connector180Count": connector_180,
        "points": [{"x": round(x, 1), "y": round(y, 1)} for x, y in pts],
        "segments": run_details,
        "stairSteps": _i(cfg.get("stairSteps"), _i(segments[0].get("steps") if segments else 0, 0)),
        "stairRiseMm": _f(cfg.get("stairRiseMm"), _f(segments[0].get("riseMm") if segments else 0, 150)),
        "stairRunMm": _f(cfg.get("stairRunMm"), _f(segments[0].get("runMm") if segments else 0, 250)),
        "studSizeMm": _i(cfg.get("studSizeMm"), 38),
        "archSpanMm": _f(segments[0].get("spanMm") if segments else 0, 0),
        "archRiseMm": _f(segments[0].get("riseMm") if segments else 0, 0),
        "archRadiusMm": _f(segments[0].get("radiusMm") if segments else 0, 0),
        # Straight elevation helpers (compat)
        "lengthMm": round(sum(_f(s.get("lengthMm")) for s in segments), 1),
        "panels": [],
        "blocks": [],
    }


def railing_svg(cfg: Mapping[str, Any], *, quote: Mapping[str, Any] | None = None) -> str:
    """2D railing drawing — plan for multi-segment / arch / stair; elevation for straight."""
    q = quote if isinstance(quote, Mapping) else compute_railing(cfg)
    g = q.get("geometry") or {}
    shape = str(g.get("shape") or q.get("shape") or "straight")

    if shape == "straight" and len(g.get("segments") or []) <= 1:
        return _svg_elevation_straight(cfg, q, g)
    if shape == "staircase":
        return _svg_staircase(q, g)
    if shape == "arch":
        return _svg_arch_plan(q, g)
    return _svg_plan_polyline(q, g)


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
    for i, w in enumerate(widths):
        gx0, gx1 = x, x + w
        p.append(f'<rect x="{X(gx0):.1f}" y="{Y(glass_y1):.1f}" width="{(gx1-gx0):.1f}" height="{(glass_y1-glass_y0):.1f}" '
                 f'fill="{glass}" stroke="{glass_stroke}" stroke-width="{sw*0.8:.2f}"/>')
        p.append(f'<text x="{X((gx0+gx1)/2):.1f}" y="{Y((glass_y0+glass_y1)/2):.1f}" text-anchor="middle" font-size="{fs:.1f}" fill="#173a63">G{i+1}</text>')
        _dim_h(p, X(gx0), X(gx1), Y(0) + fs * 1.6, f'{(gx1-gx0):.0f}', dim, sw, fs)
        # pillars along panel with 100 mm edge rule inside panel
        n_block = _i((cfg or {}).get("blocksPerGlass"), 0)
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
    summ = f'Railing · straight · {q.get("panelCount")} panels · {q.get("glassAreaSqft")} sft'
    p.append(f'<text x="{X(0):.1f}" y="{oy - fs*0.6:.1f}" font-size="{fs*1.05:.1f}" fill="#111">{escape(summ)}</text>')
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
    steps = max(_i(g.get("stairSteps"), 12), 1)
    rise = _f(g.get("stairRiseMm"), 150.0)
    run = _f(g.get("stairRunMm"), 250.0)
    total_w = run * steps
    total_h = rise * steps
    rail_h = _f(q.get("heightMm"), 900.0)  # guard height above nosing — use as offset
    # Draw stair profile + railing parallel above nosings
    guard = min(max(rail_h, 600.0), 1200.0) if rail_h > 200 else 900.0
    pad = max(total_w, total_h + guard) * 0.12 + 120.0
    vb_w = total_w + pad * 2
    vb_h = total_h + guard + pad * 2
    ox, oy = pad, pad + total_h + guard

    def X(mx: float) -> float:
        return ox + mx

    def Y(my: float) -> float:
        return oy - my

    sw = max(total_w, total_h) / 500.0
    stroke, dim, rail_c, stud_c = "#14181c", "#8c1f18", "#2f6db0", "#0a5a48"
    fs = max(vb_w, vb_h) * 0.015
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.1f} {vb_h:.1f}" font-family="Segoe UI, Arial, sans-serif">',
        f'<rect x="0" y="0" width="{vb_w:.1f}" height="{vb_h:.1f}" fill="#ffffff"/>',
    ]
    # Stair polyline
    sx = sy = 0.0
    d_steps = [f'M{X(0):.1f},{Y(0):.1f}']
    for i in range(steps):
        sx += run
        d_steps.append(f'L{X(sx):.1f},{Y(sy):.1f}')
        sy += rise
        d_steps.append(f'L{X(sx):.1f},{Y(sy):.1f}')
    p.append(f'<path d="{" ".join(d_steps)}" fill="none" stroke="{stroke}" stroke-width="{sw*1.2:.2f}"/>')

    # Handrail parallel (offset by guard along normal ≈ vertical for drawing clarity)
    hx = hy = 0.0
    d_rail = [f'M{X(0):.1f},{Y(guard):.1f}']
    for i in range(steps):
        hx += run
        d_rail.append(f'L{X(hx):.1f},{Y(hy + guard):.1f}')
        hy += rise
        d_rail.append(f'L{X(hx):.1f},{Y(hy + guard):.1f}')
    p.append(f'<path d="{" ".join(d_rail)}" fill="none" stroke="{rail_c}" stroke-width="{sw*2:.2f}" stroke-linecap="round"/>')

    stud_size = _i(g.get("studSizeMm"), 38)
    # Every 3rd step: side pillar + dual studs opposite
    for n in range(3, steps + 1, 3):
        # Position at nosing after n-th rise
        px = run * n
        py = rise * n
        # Side-mount pillar (filled tick on lower side of rail)
        p.append(f'<line x1="{X(px):.1f}" y1="{Y(py):.1f}" x2="{X(px):.1f}" y2="{Y(py+guard):.1f}" '
                 f'stroke="{stroke}" stroke-width="{sw*1.6:.2f}"/>')
        p.append(f'<rect x="{X(px)-sw*4:.1f}" y="{Y(py+guard*0.15)-sw*4:.1f}" width="{sw*8:.1f}" height="{sw*8:.1f}" '
                 f'fill="#fff" stroke="{stroke}" stroke-width="{sw*0.7:.2f}"/>')
        # Dual studs opposite
        off = run * 0.35
        for k, sign in enumerate((-1, 1)):
            sx2 = px + sign * off * 0.15
            p.append(f'<circle cx="{X(sx2):.1f}" cy="{Y(py + guard * 0.55):.1f}" r="{max(stud_size*0.15, sw*2.5):.1f}" '
                     f'fill="#e7f3ee" stroke="{stud_c}" stroke-width="{sw*0.7:.2f}"/>')
        p.append(f'<text x="{X(px)+fs*0.4:.1f}" y="{Y(py+guard*0.55):.1f}" font-size="{fs*0.7:.1f}" fill="{stud_c}">'
                 f'{stud_size}×2</text>')

    _dim_h(p, X(0), X(total_w), Y(0) + fs * 2.0, f'run {run:.0f} × {steps} = {total_w:.0f}', dim, sw, fs)
    _dim_v(p, Y(0), Y(total_h), X(0) - fs * 1.4, f'rise {total_h:.0f}', dim, sw, fs)
    summ = (f'Staircase railing · {steps} steps · pillars {q.get("stairPillars", 0)} · '
            f'studs {q.get("stairStuds", 0)} · anchors {q.get("anchorCount", 0)}')
    p.append(f'<text x="{ox:.1f}" y="{fs*1.3:.1f}" font-size="{fs:.1f}" fill="#111">{escape(summ)}</text>')
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
