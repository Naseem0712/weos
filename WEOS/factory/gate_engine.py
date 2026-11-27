"""Gates / grills / louvers / privacy screens — layout, cut list, nest, cost, SVG.

Extends shower/railing product patterns. One design member → one BOM id/count.
Wall posts, outer frame, dividers, and moving-leaf frames are separate members.
Uses structural_catalogue sectionIds + panel_fills louver layout.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, MutableMapping, Sequence
from xml.sax.saxutils import escape

from WEOS.factory.fmt import mm_n, money_n
from WEOS.factory.optimize_engine import CutPiece, first_fit_decreasing_bars
from WEOS.factory.panel_fills import compute_louver_layout, normalize_panel_fill
from WEOS.factory.structural_catalogue import (
    MM_PER_FT,
    amount_for_purchase,
    find_section_by_size,
    get_structural_section,
    resolve_kg_per_m,
)

SQMM_PER_SQFT = 92903.04
DEFAULT_KERF_MM = 3.0
DEFAULT_TRIM_MM = 5.0
DEFAULT_SUPPORT_INSERTION_MM = 20.0  # each end into stile
DEFAULT_SUPPORT_SPACING_MM = 600.0


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


def _s(value: Any, default: str = "") -> str:
    t = "" if value is None else str(value).strip()
    return t or default


def _bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


BAY_TYPES = (
    "fixed_grill",
    "fixed_louvers",
    "swing_door",
    "swing_gate",
    "sliding_door",
    "sliding_gate",
    "folding_door",
    "folding_privacy",
    "privacy_screen",
)


def normalize_bay_type(raw: Any) -> str:
    t = _s(raw, "folding_privacy").lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fold": "folding_door",
        "folding": "folding_door",
        "bifold": "folding_door",
        "privacy": "folding_privacy",
        "privacy_screen": "folding_privacy",
        "screen": "folding_privacy",
        "grill": "fixed_grill",
        "grills": "fixed_grill",
        "louver": "fixed_louvers",
        "louvers": "fixed_louvers",
        "swing": "swing_gate",
        "gate": "swing_gate",
        "sliding": "sliding_gate",
    }
    t = aliases.get(t, t)
    return t if t in BAY_TYPES else "folding_privacy"


def ensure_gate_dims(
    cfg: Mapping[str, Any] | None,
    *,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, Any]:
    c = dict(cfg or {})
    w = _f(c.get("widthMm") or c.get("width") or width)
    h = _f(c.get("heightMm") or c.get("height") or height)
    # Accept feet inputs
    if w <= 0 and c.get("widthFt"):
        w = _f(c.get("widthFt")) * MM_PER_FT
    if h <= 0 and c.get("heightFt"):
        h = _f(c.get("heightFt")) * MM_PER_FT
    if w <= 0:
        w = 13.0 * MM_PER_FT
    if h <= 0:
        h = 8.0 * MM_PER_FT
    c["widthMm"] = w
    c["heightMm"] = h
    c["bayType"] = normalize_bay_type(c.get("bayType") or c.get("type") or c.get("kind"))
    c.setdefault("foldLeft", _i(c.get("foldLeft"), 2))
    c.setdefault("foldRight", _i(c.get("foldRight"), 2))
    c.setdefault("qty", max(_i(c.get("qty"), 1), 1))
    return c


def _section_face(section: Mapping[str, Any] | None, fallback: float = 75.0) -> float:
    if not isinstance(section, Mapping):
        return fallback
    orient = _f(section.get("orientationDeg"))
    w = _f(section.get("faceWidthMm") or section.get("widthMm"), fallback)
    d = _f(section.get("depthMm") or section.get("heightMm"), w)
    if 45 <= (orient % 180) < 135:
        return d if d > 0 else fallback
    return w if w > 0 else fallback


def _resolve_frame_section(cfg: Mapping[str, Any]) -> dict[str, Any]:
    sid = _s(cfg.get("frameSectionId") or cfg.get("msSectionId"))
    if sid:
        sec = get_structural_section(sid)
        if sec:
            return sec
    hit = find_section_by_size(
        material="mild_steel", width_mm=75, height_mm=75, thickness_mm=3, shape="hollow_sq"
    )
    if hit:
        return hit
    # Synthetic acceptance defaults
    return {
        "sectionId": "ms_shs_75x75_t3",
        "name": "MS SHS 75×75",
        "material": "mild_steel",
        "shape": "hollow_sq",
        "widthMm": 75,
        "heightMm": 75,
        "thicknessMm": 3,
        "faceWidthMm": 75,
        "depthMm": 75,
        "weightKgPerM": None,
        "kgPerStockLength": _f(cfg.get("msBarWeightKg"), 25.0),
        "stockLengthFt": _f(cfg.get("msStockFt"), 20.0),
        "stockLengthMm": _f(cfg.get("msStockFt"), 20.0) * MM_PER_FT,
        "purchaseRate": _f(cfg.get("msRatePerKg"), 150.0),
        "purchaseRateUnit": "kg",
    }


def _resolve_louver_section(cfg: Mapping[str, Any]) -> dict[str, Any]:
    sid = _s(cfg.get("louverSectionId") or cfg.get("alSectionId"))
    if sid:
        sec = get_structural_section(sid)
        if sec:
            return sec
    hit = find_section_by_size(
        material="aluminium", width_mm=25, height_mm=25, shape="hollow_sq"
    )
    if hit:
        return hit
    return {
        "sectionId": "al_sil_sq_25x25",
        "name": "Al Square tube 25×25",
        "material": "aluminium",
        "shape": "hollow_sq",
        "widthMm": 25,
        "heightMm": 25,
        "thicknessMm": 1.2,
        "faceWidthMm": 25,
        "depthMm": 25,
        "weightKgPerM": 0.308,
        "stockLengthFt": 16.0,
        "stockLengthMm": 16.0 * MM_PER_FT,
        "purchaseRate": _f(cfg.get("alRatePerBar"), 850.0),
        "purchaseRateUnit": "full_length",
    }


def _resolve_support_section(cfg: Mapping[str, Any]) -> dict[str, Any]:
    sid = _s(cfg.get("supportSectionId"))
    if sid:
        sec = get_structural_section(sid)
        if sec:
            return sec
    dia = _f(cfg.get("supportDiaMm"), 12.0)
    hit = find_section_by_size(material="mild_steel", width_mm=dia, height_mm=dia, shape="solid_round")
    if hit and str(hit.get("shape") or "") == "solid_round":
        return hit
    area = math.pi / 4.0 * dia * dia
    return {
        "sectionId": f"ms_round_{int(dia) if float(dia).is_integer() else dia}",
        "name": f"MS round {dia:g} mm support",
        "material": "mild_steel",
        "shape": "solid_round",
        "widthMm": dia,
        "heightMm": dia,
        "thicknessMm": dia,
        "faceWidthMm": dia,
        "depthMm": dia,
        "weightKgPerM": round(area * 7850.0 / 1e6, 4),
        "weightSource": "theoretical",
        "weightLabel": "Theoretical round bar",
        "stockLengthFt": 20.0,
        "stockLengthMm": 20.0 * MM_PER_FT,
        "purchaseRate": _f(cfg.get("msRatePerKg"), 150.0),
        "purchaseRateUnit": "kg",
    }


def _apply_ms_rates(sec: Mapping[str, Any], cfg: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(sec or {})
    if cfg.get("msBarWeightKg") is not None and not out.get("kgPerStockLength"):
        out["kgPerStockLength"] = _f(cfg.get("msBarWeightKg"))
    if cfg.get("msStockFt") is not None and not out.get("stockLengthMm"):
        out["stockLengthFt"] = _f(cfg.get("msStockFt"))
        out["stockLengthMm"] = _f(cfg.get("msStockFt")) * MM_PER_FT
    if cfg.get("msRatePerKg") is not None:
        out["purchaseRate"] = _f(cfg.get("msRatePerKg"))
        out["purchaseRateUnit"] = out.get("purchaseRateUnit") or "kg"
    if out.get("kgPerStockLength") and out.get("stockLengthMm") and not out.get("weightKgPerM"):
        out["weightKgPerM"] = _f(out["kgPerStockLength"]) / (_f(out["stockLengthMm"]) / 1000.0)
    return out


def _resolve_wall_post_section(cfg: Mapping[str, Any], frame: Mapping[str, Any]) -> dict[str, Any]:
    sid = _s(cfg.get("wallPostSectionId"))
    if sid:
        sec = get_structural_section(sid)
        if sec:
            return _apply_ms_rates(sec, cfg)
    return _apply_ms_rates(frame, cfg)


def _resolve_leaf_frame_section(cfg: Mapping[str, Any], frame: Mapping[str, Any]) -> dict[str, Any]:
    sid = _s(cfg.get("leafFrameSectionId") or cfg.get("leafSectionId"))
    if sid:
        sec = get_structural_section(sid)
        if sec:
            return _apply_ms_rates(sec, cfg)
    return _apply_ms_rates(frame, cfg)


def _resolve_grill_section(cfg: Mapping[str, Any], fallback: Mapping[str, Any]) -> dict[str, Any]:
    sid = _s(cfg.get("grillSectionId") or cfg.get("grillBarSectionId"))
    if sid:
        sec = get_structural_section(sid)
        if sec:
            return _apply_ms_rates(sec, cfg)
    # Prefer flat / round bar for grill
    hit = find_section_by_size(material="mild_steel", width_mm=12, height_mm=12, shape="solid_round")
    if hit:
        return _apply_ms_rates(hit, cfg)
    return _apply_ms_rates(fallback, cfg)


def _resolve_track_channel_section(cfg: Mapping[str, Any]) -> dict[str, Any]:
    sid = _s(cfg.get("trackChannelSectionId") or cfg.get("trackCChannelSectionId"))
    if sid:
        sec = get_structural_section(sid)
        if sec:
            return _apply_ms_rates(sec, cfg)
    # Prefer catalogue C-channel ~38×75
    hit = find_section_by_size(material="mild_steel", width_mm=38, height_mm=75, thickness_mm=5, shape="c_channel")
    if hit:
        return _apply_ms_rates(hit, cfg)
    for s in (get_structural_section("ms_c_channel_38x75_5") or {},):
        if s:
            return _apply_ms_rates(s, cfg)
    # Synthetic C-channel for sliding floor track
    return _apply_ms_rates({
        "sectionId": "ms_c_channel_38x75_5",
        "name": "MS C-channel 38×75×5",
        "material": "mild_steel",
        "shape": "c_channel",
        "widthMm": 38.0,
        "heightMm": 75.0,
        "thicknessMm": 5.0,
        "faceWidthMm": 38.0,
        "depthMm": 75.0,
        "weightKgPerM": 5.5342,
        "weightSource": "theoretical",
        "stockLengthFt": 20.0,
        "stockLengthMm": 20.0 * MM_PER_FT,
        "purchaseRateUnit": "kg",
    }, cfg)


def _resolve_track_bar_section(cfg: Mapping[str, Any]) -> dict[str, Any]:
    sid = _s(cfg.get("trackBarSectionId") or cfg.get("trackRoundSectionId"))
    if sid:
        sec = get_structural_section(sid)
        if sec:
            return _apply_ms_rates(sec, cfg)
    dia = _f(cfg.get("trackBarDiaMm") or cfg.get("trackRoundDiaMm"), 20.0)
    dia = min(max(dia, 16.0), 25.0)
    hit = find_section_by_size(material="mild_steel", width_mm=dia, height_mm=dia, shape="solid_round")
    if hit and str(hit.get("shape") or "") == "solid_round":
        return _apply_ms_rates(hit, cfg)
    area = math.pi / 4.0 * dia * dia
    return _apply_ms_rates({
        "sectionId": f"ms_solid_round_{int(dia)}",
        "name": f"MS solid round Ø{dia:g}",
        "material": "mild_steel",
        "shape": "solid_round",
        "widthMm": dia,
        "heightMm": dia,
        "thicknessMm": dia,
        "faceWidthMm": dia,
        "depthMm": dia,
        "weightKgPerM": round(area * 7850.0 / 1e6, 4),
        "weightSource": "theoretical",
        "stockLengthFt": 20.0,
        "stockLengthMm": 20.0 * MM_PER_FT,
        "purchaseRateUnit": "kg",
    }, cfg)


WHEEL_INSET_MM = 300.0
TRACK_BURY_RATIO = 0.5  # half buried in ground
WALL_ABOVE_GATE_MM = 100.0  # side walls / pillars always gate H + 100
DEFAULT_SIDE_WALL_MM = 230.0
DEFAULT_MID_PILLAR_MM = 230.0
DEFAULT_BRICK_L_MM = 230.0
DEFAULT_BRICK_H_MM = 76.0
HANDLE_FACE_MM = 25.0
HANDLE_STUB_MM = 90.0


def _resolve_handle_section(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """25×25 mm pipe for elevation handle (catalogue SHS preferred)."""
    sid = _s(cfg.get("handleSectionId"))
    if sid:
        sec = get_structural_section(sid)
        if sec:
            return _apply_ms_rates(sec, cfg)
    hit = find_section_by_size(
        material="mild_steel", width_mm=25, height_mm=25, shape="hollow_sq"
    )
    if hit:
        return _apply_ms_rates(hit, cfg)
    return _apply_ms_rates({
        "sectionId": "ms_shs_25x25_t2",
        "name": "MS SHS 25×25 handle",
        "material": "mild_steel",
        "shape": "hollow_sq",
        "widthMm": 25.0,
        "heightMm": 25.0,
        "thicknessMm": 2.0,
        "faceWidthMm": 25.0,
        "depthMm": 25.0,
        "weightKgPerM": 1.42,
        "weightSource": "theoretical",
        "stockLengthFt": 20.0,
        "stockLengthMm": 20.0 * MM_PER_FT,
        "purchaseRateUnit": "kg",
    }, cfg)


def _parse_mm_list(raw: Any) -> list[float]:
    if isinstance(raw, (list, tuple)):
        return [_f(x) for x in raw if _f(x) > 0]
    if isinstance(raw, str) and raw.strip():
        out: list[float] = []
        for part in raw.replace(";", ",").split(","):
            v = _f(part.strip())
            if v > 0:
                out.append(v)
        return out
    return []


def _ft_or_mm(cfg: Mapping[str, Any], mm_key: str, ft_key: str, default: float = 0.0) -> float:
    if cfg.get(mm_key) not in (None, ""):
        return _f(cfg.get(mm_key), default)
    if cfg.get(ft_key) not in (None, ""):
        return _f(cfg.get(ft_key)) * MM_PER_FT
    return default


def _masonry_dims(cfg: Mapping[str, Any], gate_h: float, *, ground_y_mm: float | None = None) -> dict[str, Any]:
    """Preview-only masonry. Wall top is 100 mm above gate; bottom = ground."""
    side_w = max(_ft_or_mm(cfg, "sideWallWidthMm", "sideWallWidthFt", DEFAULT_SIDE_WALL_MM), 50.0)
    side_d = max(_ft_or_mm(cfg, "sideWallDepthMm", "sideWallDepthFt", side_w), 50.0)
    mid_on = _bool(cfg.get("midPillarEnabled") or cfg.get("midWallEnabled") or cfg.get("hasMidPillar"))
    mid_w = max(_ft_or_mm(cfg, "midPillarWidthMm", "midPillarWidthFt", DEFAULT_MID_PILLAR_MM), 50.0) if mid_on else 0.0
    mid_d = max(_ft_or_mm(cfg, "midPillarDepthMm", "midPillarDepthFt", mid_w or side_d), 50.0) if mid_on else 0.0
    ground = _f(ground_y_mm, gate_h)
    wall_top = -WALL_ABOVE_GATE_MM
    wall_h = ground - wall_top  # gate H (to ground) + 100 mm above
    return {
        "sideWallWidthMm": round(side_w, 1),
        "sideWallDepthMm": round(side_d, 1),
        "midPillarEnabled": mid_on,
        "midPillarWidthMm": round(mid_w, 1),
        "midPillarDepthMm": round(mid_d, 1),
        "wallTopMm": round(wall_top, 1),
        "wallBottomMm": round(ground, 1),
        "wallHeightMm": round(wall_h, 1),
        "aboveGateMm": WALL_ABOVE_GATE_MM,
        "previewOnly": True,
    }


def _resolve_handle_side(cfg: Mapping[str, Any], *, bay_type: str, left_n: int, right_n: int) -> str:
    raw = _s(cfg.get("handleSide") or cfg.get("handleHand"), "").upper()[:1]
    if raw in ("L", "R"):
        return raw
    # Defaults: hinge on left → handle right; double fold → meeting (treat as R for track pocket L)
    if bay_type.startswith("sliding"):
        return "R"
    if left_n and not right_n:
        return "R"
    if right_n and not left_n:
        return "L"
    return "R"


def _plan_leaf_widths(
    cfg: Mapping[str, Any],
    *,
    bay_type: str,
    usable_w: float,
    left_n: int,
    right_n: int,
    mid_w: float,
) -> list[dict[str, Any]]:
    """User-controlled leaf widths when provided; else equal split within L/R groups."""
    leaf_count = left_n + right_n
    if leaf_count <= 0:
        return []
    custom = _parse_mm_list(cfg.get("leafWidthsMm") or cfg.get("leafWidths"))
    roles_in = cfg.get("leafRoles") if isinstance(cfg.get("leafRoles"), (list, tuple)) else []
    handle_side = _resolve_handle_side(cfg, bay_type=bay_type, left_n=left_n, right_n=right_n)
    # Mid pillar is preview-only — never shrink clear gate leaf span.
    _ = mid_w
    span = max(usable_w, 1.0)

    def _scale(ws: list[float]) -> list[float]:
        total = sum(ws) or 1.0
        return [w * span / total for w in ws]

    def _group_spans() -> tuple[float, float]:
        if leaf_count <= 0:
            return 0.0, 0.0
        # Explicit left/right clear sizes (priority) — scale into usable leaf span
        lb = _ft_or_mm(cfg, "leftGateWidthMm", "leftGateWidthFt", 0.0)
        rb = _ft_or_mm(cfg, "rightGateWidthMm", "rightGateWidthFt", 0.0)
        if (lb > 0 or rb > 0) and (left_n or right_n):
            if left_n and lb <= 0:
                lb = span * left_n / leaf_count
            if right_n and rb <= 0:
                rb = span * right_n / leaf_count
            if not left_n:
                lb = 0.0
            if not right_n:
                rb = 0.0
            total = max(lb + rb, 1.0)
            return span * lb / total, span * rb / total
        ls = span * left_n / leaf_count
        return ls, span - ls

    # --- Sliding: honour main/swing widths or explicit list ---
    if bay_type.startswith("sliding"):
        swing_w = _ft_or_mm(cfg, "swingLeafWidthMm", "swingLeafWidthFt", 0.0)
        main_w = _ft_or_mm(cfg, "slidingMainWidthMm", "slidingMainWidthFt", 0.0)
        widths: list[float]
        roles: list[str]

        if len(custom) >= 1:
            widths = list(custom)
            while len(widths) < leaf_count:
                widths.append(widths[-1])
            widths = _scale(widths[:leaf_count])
            roles = []
            for i in range(leaf_count):
                r = _s(roles_in[i] if i < len(roles_in) else "", "")
                if not r:
                    r = "swing" if swing_w > 0 and (
                        (handle_side == "R" and i == leaf_count - 1) or (handle_side == "L" and i == 0)
                    ) else "sliding"
                roles.append(r)
        elif swing_w > 0:
            slide_w = main_w if main_w > 0 else max(span - swing_w, 100.0)
            if handle_side == "R":
                widths = _scale([slide_w] * max(leaf_count - 1, 1) + [swing_w])
                roles = ["sliding"] * max(leaf_count - 1, 1) + ["swing"]
            else:
                widths = _scale([swing_w] + [slide_w] * max(leaf_count - 1, 1))
                roles = ["swing"] + ["sliding"] * max(leaf_count - 1, 1)
            widths = widths[:leaf_count]
            roles = roles[:leaf_count]
        elif main_w > 0 and leaf_count >= 2:
            rest = max(span - main_w, 100.0)
            if handle_side == "R":
                widths = _scale([main_w] + [rest / max(leaf_count - 1, 1)] * (leaf_count - 1))
            else:
                widths = _scale([rest / max(leaf_count - 1, 1)] * (leaf_count - 1) + [main_w])
            roles = ["sliding"] * leaf_count
        else:
            ls, rs = _group_spans()
            widths = [ls / max(left_n, 1)] * left_n + [rs / max(right_n, 1)] * right_n
            roles = ["sliding"] * leaf_count

        plans: list[dict[str, Any]] = []
        for i, w in enumerate(widths):
            side = "L" if i < left_n else ("R" if right_n else "L")
            if left_n + right_n != leaf_count:
                side = "L" if i < (leaf_count + 1) // 2 else "R"
            role = roles[i] if i < len(roles) else "sliding"
            if role == "swing":
                hinge_side = "L" if handle_side == "R" else "R"
            else:
                hinge_side = "L" if handle_side == "R" else "R"
            show_h = (role == "swing") or (
                role == "sliding" and (
                    (handle_side == "R" and i == leaf_count - 1) or
                    (handle_side == "L" and i == 0) or
                    leaf_count == 1
                )
            )
            # If swing present, only swing shows the door handle
            if "swing" in roles and role == "sliding":
                show_h = False
            plans.append({
                "outerWidthMm": w,
                "role": role,
                "side": side,
                "hingeSide": hinge_side,
                "handleSide": handle_side if show_h else ("R" if hinge_side == "L" else "L"),
                "operable": True,
                "showHandle": show_h,
            })
        return plans

    # --- Fold / swing ---
    if len(custom) >= leaf_count:
        widths = _scale(custom[:leaf_count])
    elif len(custom) == 1 and leaf_count == 1:
        widths = [min(custom[0], span)]
    else:
        ls, rs = _group_spans()
        widths = [ls / max(left_n, 1)] * left_n + [rs / max(right_n, 1)] * right_n

    plans = []
    for i, w in enumerate(widths):
        side = "L" if i < left_n else "R"
        if bay_type.startswith("folding") or "privacy" in bay_type:
            role = "fold"
            hinge_side = "L" if side == "L" else "R"
            show_h = (side == "L" and i == left_n - 1) or (side == "R" and i == left_n) or leaf_count == 1
            hnd = "R" if side == "L" else "L"
        else:
            role = _s(roles_in[i] if i < len(roles_in) else "", "swing")
            hinge_side = "L" if side == "L" else "R"
            show_h = True
            hnd = "R" if hinge_side == "L" else "L"
        plans.append({
            "outerWidthMm": w,
            "role": role,
            "side": side,
            "hingeSide": hinge_side,
            "handleSide": hnd,
            "operable": True,
            "showHandle": show_h,
        })
    return plans


def fixed_gap_blade_count(*, usable_mm: float, face_mm: float, gap_mm: float) -> dict[str, Any]:
    """Fixed clear-gap packing: count = floor((usable+gap)/(face+gap)); remainder → edge margins."""
    face = max(face_mm, 1.0)
    gap = max(gap_mm, 0.0)
    usable = max(usable_mm, 0.0)
    pitch = face + gap
    if pitch <= 0:
        return {"bladeCount": 0, "marginMm": 0.0, "actualGapMm": gap, "mode": "fixed_gap"}
    n = int(math.floor((usable + gap) / pitch))
    if n < 1 and usable >= face:
        n = 1
    used = n * face + max(n - 1, 0) * gap
    rem = max(usable - used, 0.0)
    margin = rem / 2.0
    return {
        "bladeCount": n,
        "marginMm": round(margin, 2),
        "actualGapMm": gap,
        "mode": "fixed_gap",
        "usedSpanMm": round(used, 2),
        "remainderMm": round(rem, 2),
    }


def equal_spacing_layout(*, usable_mm: float, face_mm: float, blade_count: int) -> dict[str, Any]:
    """Equal spacing: derive actual clear gap between faces."""
    n = max(int(blade_count), 1)
    face = max(face_mm, 1.0)
    usable = max(usable_mm, 0.0)
    if n == 1:
        margin = max((usable - face) / 2.0, 0.0)
        return {"bladeCount": 1, "marginMm": round(margin, 2), "actualGapMm": 0.0, "mode": "equal_spacing"}
    free = usable - n * face
    if free < 0:
        return fixed_gap_blade_count(usable_mm=usable, face_mm=face, gap_mm=0)
    gap = free / (n - 1)
    return {
        "bladeCount": n,
        "marginMm": 0.0,
        "actualGapMm": round(gap, 2),
        "mode": "equal_spacing",
        "usedSpanMm": round(usable, 2),
    }


def _capsule_developed_length_mm(*, straight_mm: float, centreline_dia_mm: float) -> float:
    """Capsule ring: 2×straight + π×centreline diameter — one bent rod = one cut."""
    return 2.0 * max(straight_mm, 0.0) + math.pi * max(centreline_dia_mm, 0.0)


def _grill_cuts(
    *,
    clear_w: float,
    clear_h: float,
    cfg: Mapping[str, Any],
    bay_id: str,
    section: Mapping[str, Any],
) -> list[dict[str, Any]]:
    style = _s(cfg.get("grillStyle") or cfg.get("grillType"), "straight").lower()
    # Prefer explicit grill gap; fall back to shared louver gap field from UI.
    spacing = _f(cfg.get("grillSpacingMm") or cfg.get("louverGapMm"), 66.0)
    cuts: list[dict[str, Any]] = []
    mid = section
    face = max(_section_face(section, 12), 1.0)
    spacing_mode = _s(cfg.get("louverSpacingMode") or cfg.get("spacingMode") or cfg.get("grillSpacingMode"), "fixed_gap").lower()
    if style in ("diagonal", "cross"):
        # Diagonal from endpoints of clear rect
        diag = math.hypot(clear_w, clear_h)
        cuts.append(_cut_row(
            design_id=f"{bay_id}-diag-a",
            bay_id=bay_id,
            leaf_id=None,
            role="grill_diagonal",
            section=mid,
            cut_mm=diag,
            pcs=1,
            end_cut="butt",
            joint="between",
        ))
        cuts.append(_cut_row(
            design_id=f"{bay_id}-diag-b",
            bay_id=bay_id,
            leaf_id=None,
            role="grill_diagonal",
            section=mid,
            cut_mm=diag,
            pcs=1,
            end_cut="butt",
            joint="between",
        ))
    elif style in ("capsule", "capsule_ring", "ring"):
        straight = _f(cfg.get("capsuleStraightMm"), min(clear_w, clear_h) * 0.35)
        dia = _f(cfg.get("capsuleDiaMm"), spacing)
        developed = _capsule_developed_length_mm(straight_mm=straight, centreline_dia_mm=dia)
        cuts.append(_cut_row(
            design_id=f"{bay_id}-capsule",
            bay_id=bay_id,
            leaf_id=None,
            role="grill_capsule_ring",
            section=mid,
            cut_mm=developed,
            pcs=1,
            end_cut="bent",
            joint="one_piece",
            note=f"developed=2×{straight:g}+π×{dia:g}",
        ))
    else:
        # Straight bars — vertical by default; clear-gap / equal-spacing like louvers
        orient = _s(cfg.get("grillOrientation"), "vertical").lower()
        span = clear_h if orient == "horizontal" else clear_w
        if spacing_mode == "equal_spacing" and cfg.get("bladeCount"):
            pack = equal_spacing_layout(usable_mm=span, face_mm=face, blade_count=_i(cfg.get("bladeCount")))
        else:
            pack = fixed_gap_blade_count(usable_mm=span, face_mm=face, gap_mm=spacing)
        n = max(int(pack.get("bladeCount") or 0), 1)
        if orient == "horizontal":
            for i in range(n):
                cuts.append(_cut_row(
                    design_id=f"{bay_id}-bar-h{i+1}",
                    bay_id=bay_id,
                    leaf_id=None,
                    role="grill_bar",
                    section=mid,
                    cut_mm=clear_w,
                    pcs=1,
                    end_cut="butt",
                    joint="between",
                ))
        else:
            for i in range(n):
                cuts.append(_cut_row(
                    design_id=f"{bay_id}-bar-v{i+1}",
                    bay_id=bay_id,
                    leaf_id=None,
                    role="grill_bar",
                    section=mid,
                    cut_mm=clear_h,
                    pcs=1,
                    end_cut="butt",
                    joint="between",
                ))
    return cuts


def _cut_row(
    *,
    design_id: str,
    bay_id: str | None,
    leaf_id: str | None,
    role: str,
    section: Mapping[str, Any],
    cut_mm: float,
    pcs: int,
    end_cut: str = "butt",
    joint: str = "butt_through",
    note: str | None = None,
) -> dict[str, Any]:
    wr = resolve_kg_per_m(section)
    kg_m = wr.get("weightKgPerM")
    used_m = (cut_mm * pcs) / 1000.0
    used_kg = (used_m * float(kg_m)) if kg_m else None
    return {
        "designId": design_id,
        "bayId": bay_id,
        "leafId": leaf_id,
        "memberRole": role,
        "sectionId": section.get("sectionId") or section.get("id"),
        "sectionName": section.get("name"),
        "material": section.get("material"),
        "finish": section.get("finish") or section.get("colour"),
        "cutLengthMm": round(cut_mm, 1),
        "pieces": int(pcs),
        "endCut": end_cut,
        "joint": joint,
        "weightKgPerM": kg_m,
        "weightSource": wr.get("weightSource"),
        "usedM": round(used_m, 4),
        "usedKg": round(used_kg, 3) if used_kg is not None else None,
        "note": note,
        "incomplete": bool(wr.get("missing")),
        "missing": list(wr.get("missing") or []),
    }


def _leaf_frame_cuts(
    *,
    leaf_id: str,
    bay_id: str,
    leaf_w: float,
    leaf_h: float,
    frame: Mapping[str, Any],
    mitre: bool = True,
) -> list[dict[str, Any]]:
    """Moving-leaf frame: 2 verticals + 2 horizontals (separate members)."""
    face = _section_face(frame)
    # Mitre convention: cut length = outer member length (shop mitre from outer)
    vert = leaf_h
    horiz = leaf_w
    end = "mitre" if mitre else "butt"
    joint = "mitre" if mitre else "butt_through"
    return [
        _cut_row(design_id=f"{leaf_id}-stile-L", bay_id=bay_id, leaf_id=leaf_id, role="moving_leaf_stile",
                 section=frame, cut_mm=vert, pcs=1, end_cut=end, joint=joint),
        _cut_row(design_id=f"{leaf_id}-stile-R", bay_id=bay_id, leaf_id=leaf_id, role="moving_leaf_stile",
                 section=frame, cut_mm=vert, pcs=1, end_cut=end, joint=joint),
        _cut_row(design_id=f"{leaf_id}-rail-T", bay_id=bay_id, leaf_id=leaf_id, role="moving_leaf_rail",
                 section=frame, cut_mm=horiz, pcs=1, end_cut=end, joint=joint),
        _cut_row(design_id=f"{leaf_id}-rail-B", bay_id=bay_id, leaf_id=leaf_id, role="moving_leaf_rail",
                 section=frame, cut_mm=horiz, pcs=1, end_cut=end, joint=joint),
        # face recorded for clear calc
        _cut_row(design_id=f"{leaf_id}-face-meta", bay_id=bay_id, leaf_id=leaf_id, role="_meta_face",
                 section=frame, cut_mm=face, pcs=0, end_cut="none", joint="none", note="face width meta"),
    ]


def _parse_louver_pattern(cfg: Mapping[str, Any], default_sec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build repeating pattern slots: each has section + clear gapAfter (face-to-face)."""
    raw = cfg.get("louverPattern") or cfg.get("bladePattern") or cfg.get("pattern")
    if not isinstance(raw, (list, tuple)) or not raw:
        return []
    slots: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        sid = _s(row.get("sectionId") or row.get("section_id"))
        sec = get_structural_section(sid) if sid else None
        if not sec:
            sec = dict(default_sec)
            sid = _s(sec.get("sectionId"))
        else:
            sec = dict(sec)
            if cfg.get("alRatePerBar") is not None and str(sec.get("material") or "").lower().startswith("al"):
                sec["purchaseRate"] = _f(cfg.get("alRatePerBar"))
                sec["purchaseRateUnit"] = "full_length"
            if cfg.get("msRatePerKg") is not None and not str(sec.get("material") or "").lower().startswith("al"):
                sec = _apply_ms_rates(sec, cfg)
        face = _section_face(sec, _f(row.get("sizeMm") or row.get("faceMm"), 25))
        depth = _f(sec.get("depthMm") or sec.get("heightMm") or row.get("depthMm"), face)
        gap_after = _f(row.get("gapAfterMm") or row.get("gapMm") or row.get("gap"), _f(cfg.get("louverGapMm"), 25))
        slots.append({
            "sectionId": sid,
            "section": sec,
            "shape": "round" if str(sec.get("shape") or "").endswith("round") else "rect",
            "sizeMm": face,
            "depthMm": depth,
            "thicknessMm": _f(sec.get("thicknessMm"), 1.2),
            "gapAfterMm": gap_after,
            "depthOffsetMm": _f(row.get("depthOffsetMm")),
        })
    return slots


def _louver_fill_cuts(
    *,
    leaf_id: str,
    bay_id: str,
    clear_w: float,
    clear_h: float,
    cfg: Mapping[str, Any],
    louver_sec: Mapping[str, Any],
    support_sec: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    face = _section_face(louver_sec, 25.0)
    gap = _f(cfg.get("louverGapMm") or cfg.get("gapMm"), 25.0)
    orient = _s(cfg.get("louverOrientation") or cfg.get("orientation"), "vertical").lower()
    if orient not in ("vertical", "horizontal"):
        orient = "vertical"
    spacing_mode = _s(cfg.get("louverSpacingMode") or cfg.get("spacingMode"), "fixed_gap").lower()
    usable = clear_w if orient == "vertical" else clear_h
    blade_len = clear_h if orient == "vertical" else clear_w

    pattern_slots = _parse_louver_pattern(cfg, louver_sec)
    section_by_id: dict[str, Mapping[str, Any]] = {}
    cuts: list[dict[str, Any]] = []
    pack: dict[str, Any] | None = None

    if pattern_slots:
        # Multi-section repeating pattern — BOM from each canvas blade's own section
        fill = normalize_panel_fill({
            "fillType": "louvers",
            "orientation": orient,
            "patternMode": "repeat",
            "pattern": [
                {
                    "sectionId": s["sectionId"],
                    "sizeMm": s["sizeMm"],
                    "depthMm": s["depthMm"],
                    "thicknessMm": s["thicknessMm"],
                    "gapAfterMm": s["gapAfterMm"],
                    "shape": s.get("shape") or "rect",
                    "depthOffsetMm": s.get("depthOffsetMm") or 0,
                }
                for s in pattern_slots
            ],
            "gapMm": pattern_slots[0]["gapAfterMm"],
            "bladeWidthMm": pattern_slots[0]["sizeMm"],
            "bladeDepthMm": pattern_slots[0]["depthMm"],
            "bladeThicknessMm": pattern_slots[0]["thicknessMm"],
        })
        for s in pattern_slots:
            section_by_id[_s(s["sectionId"])] = s["section"]
        layout = compute_louver_layout(x0=0, y0=0, x1=clear_w, y1=clear_h, fill=fill)
        n = int(layout.get("bladeCount") or 0)
        counts: dict[str, int] = {}
        for i, blade in enumerate(layout.get("blades") or []):
            sid = _s(blade.get("sectionId") or pattern_slots[i % len(pattern_slots)]["sectionId"])
            sec = section_by_id.get(sid) or get_structural_section(sid) or louver_sec
            section_by_id[sid] = sec
            counts[sid] = counts.get(sid, 0) + 1
            cuts.append(_cut_row(
                design_id=f"{leaf_id}-louver-{i+1}",
                bay_id=bay_id,
                leaf_id=leaf_id,
                role="louver_blade",
                section=sec,
                cut_mm=_f(blade.get("lengthMm"), blade_len),
                pcs=1,
                end_cut="butt",
                joint="between",
                note=f"pattern blade · face {_section_face(sec, 25):g} · gap after clear",
            ))
        pack = {
            "mode": "repeat_pattern",
            "bladeCount": n,
            "marginMm": layout.get("marginMm"),
            "actualGapMm": layout.get("gapMm"),
            "countsBySectionId": counts,
        }
        face = _f((layout.get("blades") or [{}])[0].get("sizeMm"), face) if n else face
    else:
        if spacing_mode == "equal_spacing" and cfg.get("bladeCount"):
            pack = equal_spacing_layout(usable_mm=usable, face_mm=face, blade_count=_i(cfg.get("bladeCount")))
        else:
            pack = fixed_gap_blade_count(usable_mm=usable, face_mm=face, gap_mm=gap)

        fill = normalize_panel_fill({
            "fillType": "louvers",
            "orientation": orient,
            "gapMm": pack.get("actualGapMm", gap),
            "bladeWidthMm": face,
            "bladeDepthMm": _f(louver_sec.get("depthMm") or louver_sec.get("heightMm"), face),
            "bladeThicknessMm": _f(louver_sec.get("thicknessMm"), 1.2),
            "patternMode": "uniform",
            "sectionId": louver_sec.get("sectionId"),
        })
        layout = compute_louver_layout(x0=0, y0=0, x1=clear_w, y1=clear_h, fill=fill)
        n = int(pack.get("bladeCount") or layout.get("bladeCount") or 0)
        for i in range(n):
            cuts.append(_cut_row(
                design_id=f"{leaf_id}-louver-{i+1}",
                bay_id=bay_id,
                leaf_id=leaf_id,
                role="louver_blade",
                section=louver_sec,
                cut_mm=blade_len,
                pcs=1,
                end_cut="butt",
                joint="between",
                note=f"clear gap {pack.get('actualGapMm')} mm · margin {pack.get('marginMm')} mm",
            ))
        section_by_id[_s(louver_sec.get("sectionId"))] = louver_sec

    # Support rods: horizontal through vertical blades (or vice versa)
    insertion = _f(cfg.get("supportInsertionMm"), DEFAULT_SUPPORT_INSERTION_MM)
    rod_spacing = _f(cfg.get("supportSpacingMm"), DEFAULT_SUPPORT_SPACING_MM)
    rod_count = _i(cfg.get("supportRodCount"), 0)
    span_for_rods = clear_h if orient == "vertical" else clear_w
    if rod_count <= 0:
        rod_count = max(int(math.floor(span_for_rods / max(rod_spacing, 1.0))), 1)
        if span_for_rods >= 800:
            rod_count = max(rod_count, 2)
    rod_cut = (clear_w if orient == "vertical" else clear_h) + 2.0 * insertion
    for i in range(rod_count):
        cuts.append(_cut_row(
            design_id=f"{leaf_id}-support-{i+1}",
            bay_id=bay_id,
            leaf_id=leaf_id,
            role="support_rod",
            section=support_sec,
            cut_mm=rod_cut,
            pcs=1,
            end_cut="butt",
            joint="inserted",
            note=f"leaf clear + {insertion:g} mm insertion each end",
        ))

    meta = {
        "orientation": orient,
        "bladeCount": n,
        "gapMm": (pack or {}).get("actualGapMm", gap),
        "marginMm": (pack or {}).get("marginMm"),
        "spacingMode": (pack or {}).get("mode") or spacing_mode,
        "bladeFaceMm": face,
        "bladeLengthMm": round(blade_len, 1),
        "clearWidthMm": round(clear_w, 1),
        "clearHeightMm": round(clear_h, 1),
        "supportRodCount": rod_count,
        "supportCutMm": round(rod_cut, 1),
        "layout": layout,
        "pack": pack,
        "patternMode": "repeat" if pattern_slots else "uniform",
        "pattern": [
            {"sectionId": s["sectionId"], "sizeMm": s["sizeMm"], "gapAfterMm": s["gapAfterMm"]}
            for s in pattern_slots
        ] if pattern_slots else None,
        "countsBySectionId": (pack or {}).get("countsBySectionId"),
        "fillType": "louvers",
    }
    return cuts, meta


def _nest_by_section(
    cuts: Sequence[Mapping[str, Any]],
    *,
    sections: Mapping[str, Mapping[str, Any]],
    kerf_mm: float,
    trim_mm: float,
    qty: int,
) -> dict[str, Any]:
    """Quote-wide nest per sectionId; reuse compatible offcuts in same quote."""
    groups: dict[str, list[CutPiece]] = {}
    for c in cuts:
        if _i(c.get("pieces")) <= 0:
            continue
        sid = _s(c.get("sectionId"))
        if not sid:
            continue
        groups.setdefault(sid, [])
        groups[sid].append(
            CutPiece(
                length_mm=float(c.get("cutLengthMm") or 0) + trim_mm,
                label=_s(c.get("designId") or c.get("memberRole")),
                qty=int(c.get("pieces") or 1) * max(qty, 1),
            )
        )

    nests: dict[str, Any] = {}
    for sid, pieces in groups.items():
        sec = sections.get(sid) or get_structural_section(sid) or {}
        stock = _f(sec.get("stockLengthMm"))
        if stock <= 0 and sec.get("stockLengthFt"):
            stock = _f(sec.get("stockLengthFt")) * MM_PER_FT
        if stock <= 0:
            stock = 16.0 * MM_PER_FT if str(sec.get("material") or "").startswith("al") else 20.0 * MM_PER_FT
        # Filter pieces that fit; oversize flagged incomplete
        fit: list[CutPiece] = []
        oversize: list[dict[str, Any]] = []
        for p in pieces:
            if p.length_mm > stock:
                oversize.append({"label": p.label, "lengthMm": p.length_mm, "stockMm": stock})
            else:
                fit.append(p)
        try:
            nest = first_fit_decreasing_bars(fit, bar_length_mm=stock, kerf_mm=kerf_mm, leftovers=[])
        except ValueError as exc:
            nest = {"error": str(exc), "newBarCount": 0, "bars": []}
        used_m = sum((p.length_mm - trim_mm) * p.qty for p in fit) / 1000.0
        # Recompute without double-adding trim into used metal
        used_m = 0.0
        used_kg = 0.0
        wr = resolve_kg_per_m(sec)
        kg_m = wr.get("weightKgPerM")
        for c in cuts:
            if _s(c.get("sectionId")) != sid or _i(c.get("pieces")) <= 0:
                continue
            um = _f(c.get("usedM")) * qty
            used_m += um
            if c.get("usedKg") is not None:
                used_kg += _f(c.get("usedKg")) * qty
            elif kg_m:
                used_kg += um * float(kg_m)
        # optimize_engine returns newBars as an int count
        bars = _i(nest.get("newBars") or nest.get("newBarCount") or nest.get("barsUsed"), 0)
        if not bars and isinstance(nest.get("barsDetail"), list):
            bars = len([b for b in nest["barsDetail"] if b.get("source") == "new"])
        if not bars and isinstance(nest.get("bars"), list):
            bars = len([b for b in nest["bars"] if b.get("source") == "new"]) or len(nest["bars"])
        purchase_kg = None
        if sec.get("kgPerStockLength") and bars:
            purchase_kg = bars * _f(sec.get("kgPerStockLength"))
        elif kg_m and bars and stock:
            purchase_kg = bars * (stock / 1000.0) * float(kg_m)
        purch = amount_for_purchase(used_m=used_m, used_kg=used_kg or (purchase_kg or 0), bars=bars, section=sec)
        # Distinct used vs purchase money — wastage is breakup of full-bar amount (never added twice).
        unit = str(sec.get("purchaseRateUnit") or "kg").lower().replace(" ", "_")
        rate = sec.get("purchaseRate")
        stock_m = stock / 1000.0 if stock else 0.0
        purchase_m = bars * stock_m if bars and stock_m else 0.0
        wastage_m = max(purchase_m - used_m, 0.0) if purchase_m else 0.0
        used_amt = None
        purchase_amt = purch.get("amount")
        if rate is not None:
            try:
                r = float(rate)
                if unit in ("kg", "per_kg") and kg_m:
                    used_amt = round(used_kg * r, 2)
                    if purchase_kg is not None:
                        purchase_amt = round(float(purchase_kg) * r, 2)
                elif unit in ("rft", "per_rft", "ft"):
                    used_amt = round((used_m / 0.3048) * r, 2)
                    purchase_amt = round((purchase_m / 0.3048) * r, 2) if purchase_m else used_amt
                elif unit in ("m", "rm", "rmt", "per_m", "metre", "meter"):
                    used_amt = round(used_m * r, 2)
                    purchase_amt = round(purchase_m * r, 2) if purchase_m else used_amt
                elif unit in ("full_length", "bar", "length", "full_bar", "stock"):
                    # Cost = full bars × rate; used money is proportional breakup only
                    purchase_amt = round(bars * r, 2)
                    used_amt = round(purchase_amt * (used_m / purchase_m), 2) if purchase_m > 0 else purchase_amt
            except (TypeError, ValueError):
                pass
        # Internal cost line: used×rate for kg/rft/m; full-bar for ₹/bar (wastage inside purchase)
        if unit in ("full_length", "bar", "length", "full_bar", "stock", "piece", "pcs", "pc", "set"):
            cost_amount = purchase_amt
        else:
            cost_amount = used_amt if used_amt is not None else purchase_amt
        if cost_amount is not None:
            purch = dict(purch)
            purch["amount"] = cost_amount
            purch["usedAmount"] = used_amt
            purch["purchaseAmount"] = purchase_amt
            purch["wastageAmountBreakup"] = (
                round(float(purchase_amt) - float(used_amt), 2)
                if purchase_amt is not None and used_amt is not None
                else None
            )
        nests[sid] = {
            "sectionId": sid,
            "sectionName": sec.get("name"),
            "material": sec.get("material"),
            "stockLengthMm": stock,
            "stockLengthFt": round(stock / MM_PER_FT, 3),
            "kerfMm": kerf_mm,
            "trimMm": trim_mm,
            "usedM": round(used_m, 4),
            "usedKg": round(used_kg, 3),
            "purchaseKg": round(purchase_kg, 3) if purchase_kg is not None else None,
            "purchaseM": round(purchase_m, 4) if purchase_m else None,
            "wastageM": round(wastage_m, 4) if wastage_m else 0.0,
            "bars": bars,
            "nest": nest,
            "oversize": oversize,
            "purchase": purch,
            "usedAmount": used_amt,
            "purchaseAmount": purchase_amt,
            "costAmount": cost_amount,
            "weightSource": wr.get("weightSource"),
            "weightLabel": wr.get("weightLabel"),
            "kgPerM": kg_m,
            "purchaseRate": sec.get("purchaseRate"),
            "purchaseRateUnit": sec.get("purchaseRateUnit"),
            "incomplete": bool(purch.get("incomplete") or oversize or wr.get("missing")),
            "missing": list(purch.get("missing") or []) + list(wr.get("missing") or []),
        }
    return nests


def _hardware_lines(cfg: Mapping[str, Any], *, leaves: Sequence[Mapping[str, Any]], leaf_weight_kg: float) -> list[dict[str, Any]]:
    """Hardware BOM — folding joints ≠ locks; capacity from moving-leaf weight."""
    bay = normalize_bay_type(cfg.get("bayType"))
    left = _i(cfg.get("foldLeft"), 0)
    right = _i(cfg.get("foldRight"), 0)
    n_leaves = len(leaves) or (left + right) or 1
    lines: list[dict[str, Any]] = []
    pkg = cfg.get("hardwarePackage") if isinstance(cfg.get("hardwarePackage"), Mapping) else {}
    package_amount = _f(pkg.get("amount") or cfg.get("hardwarePackageAmount"), 10000.0)
    package_included = list(pkg.get("included") or cfg.get("hardwareIncluded") or [
        "hinges", "tower_bolts", "lock", "guide_wheels"
    ])
    # Explicit editable items
    hw_cfg = cfg.get("hardware") if isinstance(cfg.get("hardware"), list) else None

    def _in_package(hid: str, name: str) -> bool:
        blob = f"{hid} {name}".lower()
        for token in package_included:
            t = str(token or "").lower().replace("-", "_").replace(" ", "_")
            if not t:
                continue
            if t in blob or t.rstrip("s") in blob:
                return True
            # hinges matches hinges_wall / hinges_interleaf
            if t == "hinges" and "hinge" in blob:
                return True
            if t in ("guide_wheels", "guidewheels") and "guide" in blob and "wheel" in blob:
                return True
            if t in ("tower_bolts", "towerbolts") and "tower" in blob:
                return True
        return False

    def add(hid: str, name: str, qty: float, *, basis: str, unit_rate: float | None, included: bool) -> None:
        use_pkg = _bool(cfg.get("hardwareUsePackage"), True) and package_amount > 0
        if included and use_pkg and _in_package(hid, name):
            lines.append({
                "catalogueId": hid,
                "name": name,
                "qty": qty,
                "qtyBasis": basis,
                "unitRate": 0.0,
                "amount": 0.0,
                "includedInPackage": True,
                "brand": _s(cfg.get("hardwareBrand"), "SS304"),
                "capacityNote": f"leaf weight {leaf_weight_kg:.2f} kg" if "hinge" in hid or "wheel" in hid else None,
            })
            return
        rate = unit_rate if unit_rate is not None else 0.0
        lines.append({
            "catalogueId": hid,
            "name": name,
            "qty": qty,
            "qtyBasis": basis,
            "unitRate": rate,
            "amount": money_n(qty * rate),
            "includedInPackage": False,
            "brand": _s(cfg.get("hardwareBrand"), "SS304"),
            "capacityNote": f"leaf weight {leaf_weight_kg:.2f} kg" if "hinge" in hid or "wheel" in hid else None,
        })

    if hw_cfg:
        for h in hw_cfg:
            if not isinstance(h, Mapping):
                continue
            hid = _s(h.get("id") or h.get("catalogueId") or h.get("name"))
            included = _bool(h.get("includedInPackage"), hid in package_included)
            add(
                hid,
                _s(h.get("name"), hid),
                _f(h.get("qty"), 1),
                basis=_s(h.get("qtyBasis") or h.get("basis"), "manual"),
                unit_rate=_f(h.get("unitRate") or h.get("rate"), 0) or None,
                included=included,
            )
    else:
        if bay.startswith("folding") or bay == "folding_privacy":
            # Wall hinges: one joint per side that has leaves
            wall_joints = (1 if left else 0) + (1 if right else 0)
            interleaf = max(left - 1, 0) + max(right - 1, 0)
            hinges_per_joint = _i(cfg.get("hingesPerJoint"), 3)
            add("hinges_wall", "SS304 heavy wall hinges", wall_joints * hinges_per_joint,
                basis="wall_post_joint", unit_rate=_f(cfg.get("hingeRate"), 350), included=True)
            add("hinges_interleaf", "SS304 heavy interleaf hinges", interleaf * hinges_per_joint,
                basis="folding_joint", unit_rate=_f(cfg.get("hingeRate"), 350), included=True)
            add("tower_bolts", "2-ft tower bolts", _f(cfg.get("towerBoltQty"), 4),
                basis="manual", unit_rate=_f(cfg.get("towerBoltRate"), 180), included=True)
            add("lock", "Lock set", _f(cfg.get("lockQty"), 1),
                basis="opening", unit_rate=_f(cfg.get("lockRate"), 800), included=True)
            if _bool(cfg.get("guideWheels", True), True):
                add("guide_wheels", "Guide wheels", _f(cfg.get("guideWheelQty"), 2),
                    basis="opening", unit_rate=_f(cfg.get("guideWheelRate"), 250), included=True)
        elif bay.startswith("swing"):
            add("hinges_swing", "SS304 heavy hinges", _f(cfg.get("hingeQty"), max(n_leaves * 3, 3)),
                basis="per_leaf", unit_rate=_f(cfg.get("hingeRate"), 350), included=True)
            add("lock", "Lock set", _f(cfg.get("lockQty"), 1),
                basis="opening", unit_rate=_f(cfg.get("lockRate"), 800), included=True)
        elif bay.startswith("sliding"):
            add("wheels", "Sliding wheels", _f(cfg.get("wheelQty"), max(n_leaves * 2, 2)),
                basis="per_leaf", unit_rate=_f(cfg.get("wheelRate"), 400), included=True)
            add("rail", "Sliding rail", 1, basis="opening", unit_rate=_f(cfg.get("railRate"), 1200), included=True)
            add("guide", "Guide", 1, basis="opening", unit_rate=_f(cfg.get("guideRate"), 300), included=True)
            add("stoppers", "Stoppers", 2, basis="opening", unit_rate=_f(cfg.get("stopperRate"), 80), included=True)
            add("lock", "Lock set", _f(cfg.get("lockQty"), 1),
                basis="opening", unit_rate=_f(cfg.get("lockRate"), 800), included=True)

    if _bool(cfg.get("hardwareUsePackage"), True) and package_amount > 0:
        lines.insert(0, {
            "catalogueId": "hw_package",
            "name": _s(pkg.get("name"), "Hardware package"),
            "qty": 1,
            "qtyBasis": "opening",
            "unitRate": package_amount,
            "amount": money_n(package_amount),
            "includedInPackage": False,
            "isPackage": True,
            "includes": package_included,
            "brand": _s(cfg.get("hardwareBrand"), "SS304"),
        })
    return lines


def compute_gate(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Full factory + commercial quote for one gate/grill/privacy design."""
    c = ensure_gate_dims(cfg)
    W = _f(c["widthMm"])
    H = _f(c["heightMm"])
    qty = max(_i(c.get("qty"), 1), 1)
    bay_type = normalize_bay_type(c.get("bayType"))
    incomplete: list[str] = []
    deductions = c.get("deductions") if isinstance(c.get("deductions"), Mapping) else {}
    # Never silently zero missing deductions as factory-ready
    for key in ("wallClearanceMm", "meetingClearanceMm", "bottomClearanceMm", "topClearanceMm"):
        if key not in deductions and c.get(key) is None:
            # defaults applied but flagged
            pass
    wall_clear = _f(deductions.get("wallClearanceMm") or c.get("wallClearanceMm"), 5.0)
    meeting_clear = _f(deductions.get("meetingClearanceMm") or c.get("meetingClearanceMm"), 5.0)
    bottom_clear = _f(deductions.get("bottomClearanceMm") or c.get("bottomClearanceMm"), 10.0)
    top_clear = _f(deductions.get("topClearanceMm") or c.get("topClearanceMm"), 5.0)
    if c.get("deductionsMissing"):
        incomplete.append("clearance deductions incomplete")

    # Weight/cost must follow exactly the sectionIds the user selected in the UI.
    # Resolve each role from its cfg id first; only fall back when the id is absent.
    frame = _apply_ms_rates(_resolve_frame_section(c), c)
    wall_post_sec = _resolve_wall_post_section(c, frame)
    leaf_frame_sec = _resolve_leaf_frame_section(c, frame)
    louver_sec = dict(_resolve_louver_section(c))
    if c.get("alRatePerBar") is not None:
        louver_sec["purchaseRate"] = _f(c.get("alRatePerBar"))
        louver_sec["purchaseRateUnit"] = "full_length"
    if c.get("alStockFt") is not None:
        louver_sec["stockLengthFt"] = _f(c.get("alStockFt"))
        louver_sec["stockLengthMm"] = _f(c.get("alStockFt")) * MM_PER_FT
    support_sec = _apply_ms_rates(_resolve_support_section(c), c)
    grill_sec = _resolve_grill_section(c, support_sec)
    track_ch_sec = _resolve_track_channel_section(c)
    track_bar_sec = _resolve_track_bar_section(c)
    handle_sec = _resolve_handle_section(c)
    # Flag when a requested sectionId could not be loaded (silent default would skew kg/₹).
    for label, wanted, got in (
        ("frame", _s(c.get("frameSectionId") or c.get("msSectionId")), _s(frame.get("sectionId"))),
        ("wallPost", _s(c.get("wallPostSectionId")), _s(wall_post_sec.get("sectionId"))),
        ("leaf", _s(c.get("leafFrameSectionId") or c.get("leafSectionId")), _s(leaf_frame_sec.get("sectionId"))),
        ("louver", _s(c.get("louverSectionId") or c.get("alSectionId")), _s(louver_sec.get("sectionId"))),
        ("support", _s(c.get("supportSectionId")), _s(support_sec.get("sectionId"))),
        ("grill", _s(c.get("grillSectionId") or c.get("grillBarSectionId")), _s(grill_sec.get("sectionId"))),
        ("trackChannel", _s(c.get("trackChannelSectionId") or c.get("trackCChannelSectionId")), _s(track_ch_sec.get("sectionId"))),
        ("trackBar", _s(c.get("trackBarSectionId") or c.get("trackRoundSectionId")), _s(track_bar_sec.get("sectionId"))),
    ):
        if wanted and got and wanted != got:
            msg = f"{label} section {wanted} not in catalogue (using {got})"
            if msg not in incomplete:
                incomplete.append(msg)
        elif wanted and not got:
            msg = f"{label} section {wanted} missing"
            if msg not in incomplete:
                incomplete.append(msg)
    # Walls: top = gate top − 100 mm, bottom = ground (H). Gate leaf keeps bottom gap.
    masonry = _masonry_dims(c, H, ground_y_mm=H)

    face = _section_face(frame, 75.0)
    leaf_face = _section_face(leaf_frame_sec, face)
    post_face = _section_face(wall_post_sec, face)
    handle_face = _section_face(handle_sec, HANDLE_FACE_MM)
    left_n = max(_i(c.get("foldLeft"), 0), 0)
    right_n = max(_i(c.get("foldRight"), 0), 0)
    if bay_type.startswith("folding") or bay_type == "folding_privacy":
        if left_n + right_n <= 0:
            left_n, right_n = 2, 2
    leaf_count = left_n + right_n
    if bay_type.startswith("swing"):
        if leaf_count <= 0:
            leaf_count = max(_i(c.get("leafCount"), 1), 1)
            left_n, right_n = leaf_count, 0
    if bay_type.startswith("sliding"):
        # Honour Fold L/R from UI (e.g. 1+1); fall back to leafCount
        if leaf_count <= 0:
            swing_w0 = _ft_or_mm(c, "swingLeafWidthMm", "swingLeafWidthFt", 0.0)
            leaf_count = max(_i(c.get("leafCount"), 2 if swing_w0 > 0 else 1), 1)
            if swing_w0 > 0 and leaf_count < 2:
                leaf_count = 2
            left_n, right_n = leaf_count // 2, leaf_count - leaf_count // 2
            if left_n == 0 and right_n:
                left_n, right_n = right_n, 0
    if bay_type in ("fixed_grill", "fixed_louvers"):
        leaf_count = 0
        left_n = right_n = 0

    # Left/right clear gate sizes take priority; quote W = sum of gate bays (walls/pillar preview-only).
    left_bay_w = _ft_or_mm(c, "leftGateWidthMm", "leftGateWidthFt", 0.0)
    right_bay_w = _ft_or_mm(c, "rightGateWidthMm", "rightGateWidthFt", 0.0)
    if (left_bay_w > 0 or right_bay_w > 0) and leaf_count > 0:
        if left_n and left_bay_w <= 0:
            left_bay_w = W * left_n / leaf_count
        if right_n and right_bay_w <= 0:
            right_bay_w = W * right_n / leaf_count
        if not left_n:
            left_bay_w = 0.0
        if not right_n:
            right_bay_w = 0.0
        W = left_bay_w + right_bay_w
        c = dict(c)
        c["widthMm"] = W

    handle_side = _resolve_handle_side(c, bay_type=bay_type, left_n=left_n, right_n=right_n)
    mid_w = _f(masonry.get("midPillarWidthMm"))
    wall_posts = _i(c.get("wallPostCount"), 2 if leaf_count else 0)
    # Mid pillar is preview-only — does not steal clear leaf span from quote W.
    usable_w = W - wall_posts * post_face - 2 * wall_clear
    if leaf_count > 0:
        meetings = max(leaf_count - 1, 0)
        if mid_w > 0 and left_n and right_n:
            meetings = max(left_n - 1, 0) + max(right_n - 1, 0)
        usable_w -= meetings * meeting_clear
    leaf_outer_h = H - bottom_clear - top_clear
    leaf_y0 = top_clear  # flush under top clearance; bottom gap = bottom_clear at ground
    leaf_plans = _plan_leaf_widths(
        c, bay_type=bay_type, usable_w=usable_w, left_n=left_n, right_n=right_n, mid_w=0.0,
    )
    leaf_count = len(leaf_plans) if leaf_plans else leaf_count

    cuts: list[dict[str, Any]] = []
    bays: list[dict[str, Any]] = []
    leaves_meta: list[dict[str, Any]] = []
    handles_meta: list[dict[str, Any]] = []
    grill_meta: dict[str, Any] | None = None
    bay_id = "bay-1"
    fill_type = _s(c.get("fillType"), "louvers" if "louver" in bay_type or "privacy" in bay_type or "folding" in bay_type or "sliding" in bay_type or "swing" in bay_type else "grill")
    if bay_type == "fixed_grill":
        fill_type = "grill"
    elif bay_type == "fixed_louvers":
        fill_type = "louvers"

    # Wall posts (separate physical members / section)
    for i in range(wall_posts):
        cuts.append(_cut_row(
            design_id=f"wall-post-{i+1}",
            bay_id=bay_id,
            leaf_id=None,
            role="wall_post",
            section=wall_post_sec,
            cut_mm=H,
            pcs=1,
            end_cut="square",
            joint="wall",
        ))

    fill_metas: list[dict[str, Any]] = []
    # Assign x positions across opening (posts → leaves, optional mid pillar between L/R)
    cursor_x = post_face if wall_posts else 0.0
    mid_x0 = None
    if leaf_count > 0 and leaf_plans:
        left_plans = [p for p in leaf_plans if p.get("side") == "L"]
        right_plans = [p for p in leaf_plans if p.get("side") == "R"]
        if not left_plans and not right_plans:
            left_plans = list(leaf_plans)
        ordered = left_plans + ([{"_mid": True}] if mid_w > 0 and left_plans and right_plans else []) + right_plans
        seq_i = 0
        for plan in ordered:
            if plan.get("_mid"):
                mid_x0 = cursor_x
                cursor_x += mid_w
                continue
            leaf_outer_w = _f(plan.get("outerWidthMm"))
            side = _s(plan.get("side"), "L")
            j = sum(1 for p in leaves_meta if p.get("side") == side)
            leaf_id = f"leaf-{side}{j+1}"
            frame_cuts = _leaf_frame_cuts(
                leaf_id=leaf_id, bay_id=bay_id,
                leaf_w=leaf_outer_w, leaf_h=leaf_outer_h, frame=leaf_frame_sec,
                mitre=_bool(c.get("mitreLeafFrames"), True),
            )
            cuts.extend([fc for fc in frame_cuts if fc.get("memberRole") != "_meta_face"])
            clear_w = max(leaf_outer_w - 2 * leaf_face, 0.0)
            clear_h = max(leaf_outer_h - 2 * leaf_face, 0.0)
            role = _s(plan.get("role"), "sliding" if bay_type.startswith("sliding") else "fold")
            leaf_rec = {
                "leafId": leaf_id,
                "side": side,
                "index": j + 1,
                "role": role,
                "outerWidthMm": round(leaf_outer_w, 1),
                "outerHeightMm": round(leaf_outer_h, 1),
                "clearWidthMm": round(clear_w, 1),
                "clearHeightMm": round(clear_h, 1),
                "frameFaceMm": leaf_face,
                "x0Mm": round(cursor_x, 1),
                "y0Mm": round(leaf_y0, 1),
                "hingeSide": plan.get("hingeSide"),
                "handleSide": plan.get("handleSide"),
                "showHandle": bool(plan.get("showHandle")),
                "operable": bool(plan.get("operable", True)),
            }
            if fill_type == "grill":
                gcuts = _grill_cuts(
                    clear_w=clear_w, clear_h=clear_h, cfg=c, bay_id=bay_id, section=grill_sec,
                )
                for gc in gcuts:
                    gc["leafId"] = leaf_id
                cuts.extend(gcuts)
                leaf_rec["fill"] = {
                    "fillType": "grill",
                    "grillStyle": _s(c.get("grillStyle"), "straight"),
                    "grillOrientation": _s(c.get("grillOrientation"), "vertical"),
                    "grillSpacingMm": _f(c.get("grillSpacingMm") or c.get("louverGapMm"), 66),
                    "bladeCount": len(gcuts),
                    "clearWidthMm": clear_w,
                    "clearHeightMm": clear_h,
                    "spacingMode": _s(c.get("louverSpacingMode") or c.get("spacingMode"), "fixed_gap"),
                }
                fill_metas.append(leaf_rec["fill"])
            else:
                fill_cuts, meta = _louver_fill_cuts(
                    leaf_id=leaf_id, bay_id=bay_id,
                    clear_w=clear_w, clear_h=clear_h, cfg=c,
                    louver_sec=louver_sec, support_sec=support_sec,
                )
                cuts.extend(fill_cuts)
                leaf_rec["fill"] = meta
                fill_metas.append(meta)
            # Wheels under sliding leaves only
            if bay_type.startswith("sliding") and role == "sliding":
                leaf_rec["wheels"] = [
                    {"insetFromLeftMm": WHEEL_INSET_MM, "role": "wheel_left"},
                    {"insetFromRightMm": WHEEL_INSET_MM, "role": "wheel_right"},
                ]
            # Handle on handle stile centreline — 25×25 pipe, half leaf height
            if leaf_rec.get("showHandle") and leaf_rec.get("operable"):
                hnd_side = _s(leaf_rec.get("handleSide"), handle_side)
                handle_h = max(leaf_outer_h * 0.5, 400.0)
                handle_h = min(handle_h, leaf_outer_h - 40.0) if leaf_outer_h > 80 else leaf_outer_h
                y_h = leaf_y0 + max((leaf_outer_h - handle_h) / 2.0, 0.0)
                # Centre of handle stile (not floating over louvers)
                if hnd_side == "L":
                    hx = cursor_x + leaf_face / 2.0
                else:
                    hx = cursor_x + leaf_outer_w - leaf_face / 2.0
                developed = handle_h + 2 * HANDLE_STUB_MM
                cuts.append(_cut_row(
                    design_id=f"handle-{leaf_id}",
                    bay_id=bay_id,
                    leaf_id=leaf_id,
                    role="handle",
                    section=handle_sec,
                    cut_mm=developed,
                    pcs=1,
                    end_cut="square",
                    joint="stile_mount",
                    note=f"25×25 pull on {hnd_side} stile · H={handle_h:g} + stubs",
                ))
                hrec = {
                    "leafId": leaf_id,
                    "side": hnd_side,
                    "xMm": round(hx, 1),
                    "yMm": round(y_h, 1),
                    "heightMm": round(handle_h, 1),
                    "faceMm": handle_face,
                    "stubMm": HANDLE_STUB_MM,
                    "stileX0Mm": round(cursor_x if hnd_side == "L" else cursor_x + leaf_outer_w - leaf_face, 1),
                    "sectionId": handle_sec.get("sectionId"),
                }
                leaf_rec["handle"] = hrec
                handles_meta.append(hrec)
            leaves_meta.append(leaf_rec)
            cursor_x += leaf_outer_w
            seq_i += 1
        if mid_x0 is None and mid_w > 0 and left_n and right_n:
            # Fallback mid at centre if plan lacked both sides
            mid_x0 = post_face + (W - 2 * post_face - mid_w) / 2.0 if wall_posts else (W - mid_w) / 2.0
    else:
        # Fixed bay — outer frame + fill (mitred hollow section)
        for role, length, pcs in (
            ("outer_jamb", H, 2),
            ("outer_head", W, 1),
            ("outer_sill", W, 1),
        ):
            for p in range(pcs):
                cuts.append(_cut_row(
                    design_id=f"{role}-{p+1}",
                    bay_id=bay_id,
                    leaf_id=None,
                    role=role,
                    section=frame,
                    cut_mm=length,
                    pcs=1,
                    end_cut="mitre" if _bool(c.get("mitreOuter"), True) else "butt",
                    joint="mitre" if _bool(c.get("mitreOuter"), True) else "butt_through",
                ))
        clear_w = max(W - 2 * face, 0.0)
        clear_h = max(H - 2 * face, 0.0)
        if bay_type == "fixed_grill" or fill_type == "grill":
            gcuts = _grill_cuts(clear_w=clear_w, clear_h=clear_h, cfg=c, bay_id=bay_id, section=grill_sec)
            cuts.extend(gcuts)
            grill_meta = {
                "fillType": "grill",
                "grillStyle": _s(c.get("grillStyle"), "straight"),
                "grillOrientation": _s(c.get("grillOrientation"), "vertical"),
                "grillSpacingMm": _f(c.get("grillSpacingMm") or c.get("louverGapMm"), 66),
                "bladeCount": len(gcuts),
                "clearWidthMm": round(clear_w, 1),
                "clearHeightMm": round(clear_h, 1),
                "marginMm": 0,
                "faceMm": _section_face(grill_sec, 12),
                "spacingMode": _s(c.get("louverSpacingMode") or c.get("spacingMode"), "fixed_gap"),
            }
            # Derive equal visual spacing for SVG from bar count
            style = grill_meta["grillStyle"]
            if style in ("straight", "") and grill_meta["bladeCount"] > 0:
                orient = grill_meta["grillOrientation"]
                span = clear_w if orient == "vertical" else clear_h
                n = int(grill_meta["bladeCount"])
                pitch = span / max(n, 1)
                grill_meta["pitchMm"] = round(pitch, 2)
                grill_meta["bladeFaceMm"] = min(_section_face(grill_sec, 12), pitch * 0.35)
            fill_metas.append(grill_meta)
        else:
            fill_cuts, meta = _louver_fill_cuts(
                leaf_id="bay-fill", bay_id=bay_id,
                clear_w=clear_w, clear_h=clear_h, cfg=c,
                louver_sec=louver_sec, support_sec=support_sec,
            )
            cuts.extend(fill_cuts)
            fill_metas.append(meta)

    # Sliding floor track: always 2×gate width + 1 ft; pocket / anti-handle side gets the overrun
    track_meta = None
    if bay_type.startswith("sliding"):
        track_len = 2.0 * W + MM_PER_FT
        if handle_side == "R":
            # Align with opening on handle (right); extra extends left into pocket/wall
            track_x0 = W - track_len
        else:
            track_x0 = 0.0
        cuts.append(_cut_row(
            design_id="track-c-channel",
            bay_id=bay_id,
            leaf_id=None,
            role="track_c_channel",
            section=track_ch_sec,
            cut_mm=track_len,
            pcs=1,
            end_cut="square",
            joint="floor",
            note="floor track C-channel · half buried · 2×W+1ft",
        ))
        cuts.append(_cut_row(
            design_id="track-round-bar",
            bay_id=bay_id,
            leaf_id=None,
            role="track_round_bar",
            section=track_bar_sec,
            cut_mm=track_len,
            pcs=1,
            end_cut="square",
            joint="on_channel",
            note=f"Ø{_section_face(track_bar_sec, 20):g} round on C-channel",
        ))
        track_meta = {
            "lengthMm": round(track_len, 1),
            "x0Mm": round(track_x0, 1),
            "x1Mm": round(track_x0 + track_len, 1),
            "handleSide": handle_side,
            "pocketSide": "L" if handle_side == "R" else "R",
            "channelSectionId": track_ch_sec.get("sectionId"),
            "channelFaceMm": _section_face(track_ch_sec, 38),
            "channelDepthMm": _f(track_ch_sec.get("depthMm") or track_ch_sec.get("heightMm"), 75),
            "barSectionId": track_bar_sec.get("sectionId"),
            "barDiaMm": _section_face(track_bar_sec, 20),
            "buryRatio": TRACK_BURY_RATIO,
            "wheelInsetMm": WHEEL_INSET_MM,
            "formula": "2×W+1ft",
        }

    # Hinge layout for fold/swing (+ sliding swing leaf) elevation
    hinge_meta = None
    hinges_per_joint = _i(c.get("hingesPerJoint"), 3)
    joints: list[dict[str, Any]] = []
    if bay_type.startswith("folding") or bay_type.startswith("swing") or bay_type == "folding_privacy":
        if wall_posts and left_n:
            joints.append({"kind": "wall_leaf", "side": "L", "atLeaf": 0, "count": hinges_per_joint})
        for i in range(max(left_n - 1, 0)):
            joints.append({"kind": "leaf_leaf", "side": "L", "atLeaf": i + 1, "count": hinges_per_joint})
        for i in range(max(right_n - 1, 0)):
            joints.append({"kind": "leaf_leaf", "side": "R", "atLeaf": left_n + i, "count": hinges_per_joint})
        if wall_posts and right_n:
            joints.append({"kind": "wall_leaf", "side": "R", "atLeaf": left_n + right_n - 1, "count": hinges_per_joint})
        if bay_type.startswith("swing") and leaves_meta:
            joints = [{"kind": "wall_leaf", "side": "L", "atLeaf": 0, "count": hinges_per_joint}]
            if leaf_count > 1:
                joints.append({"kind": "wall_leaf", "side": "R", "atLeaf": leaf_count - 1, "count": hinges_per_joint})
    elif bay_type.startswith("sliding"):
        for i, leaf in enumerate(leaves_meta):
            if _s(leaf.get("role")) != "swing":
                continue
            hs = _s(leaf.get("hingeSide"), "L")
            joints.append({
                "kind": "wall_leaf",
                "side": hs,
                "atLeaf": i,
                "count": hinges_per_joint,
                "xMm": leaf.get("x0Mm") if hs == "L" else (_f(leaf.get("x0Mm")) + _f(leaf.get("outerWidthMm"))),
            })
    if joints:
        hinge_meta = {"hingesPerJoint": hinges_per_joint, "joints": joints}

    # Visual extent includes preview mid pillar between L/R; quote W excludes walls/pillar.
    visual_w = W
    if mid_w > 0 and left_n and right_n and mid_x0 is not None:
        visual_w = W + mid_w
    elif leaves_meta:
        last = leaves_meta[-1]
        visual_w = max(W, _f(last.get("x0Mm")) + _f(last.get("outerWidthMm")) + (post_face if wall_posts else 0.0))

    bay_dims: list[dict[str, Any]] = []
    left_leaves = [L for L in leaves_meta if _s(L.get("side")) == "L"]
    right_leaves = [L for L in leaves_meta if _s(L.get("side")) == "R"]
    if left_leaves:
        x0b = _f(left_leaves[0].get("x0Mm"))
        x1b = _f(left_leaves[-1].get("x0Mm")) + _f(left_leaves[-1].get("outerWidthMm"))
        bay_dims.append({
            "side": "L", "x0Mm": round(x0b, 1), "x1Mm": round(x1b, 1),
            "widthMm": round(x1b - x0b, 1), "label": "Left gate",
        })
    if right_leaves:
        x0b = _f(right_leaves[0].get("x0Mm"))
        x1b = _f(right_leaves[-1].get("x0Mm")) + _f(right_leaves[-1].get("outerWidthMm"))
        bay_dims.append({
            "side": "R", "x0Mm": round(x0b, 1), "x1Mm": round(x1b, 1),
            "widthMm": round(x1b - x0b, 1), "label": "Right gate",
        })
    if not bay_dims and leaves_meta:
        x0b = _f(leaves_meta[0].get("x0Mm"))
        x1b = _f(leaves_meta[-1].get("x0Mm")) + _f(leaves_meta[-1].get("outerWidthMm"))
        bay_dims.append({
            "side": "C", "x0Mm": round(x0b, 1), "x1Mm": round(x1b, 1),
            "widthMm": round(x1b - x0b, 1), "label": "Gate",
        })

    masonry_out = {
        **masonry,
        "midPillarX0Mm": round(mid_x0, 1) if mid_x0 is not None else None,
        "brickPattern": "running_bond",
        "visualWidthMm": round(visual_w, 1),
        "leftWall": {
            "x0Mm": round(-_f(masonry["sideWallWidthMm"]), 1),
            "widthMm": masonry["sideWallWidthMm"],
            "topMm": masonry.get("wallTopMm"),
            "bottomMm": masonry.get("wallBottomMm"),
            "heightMm": masonry["wallHeightMm"],
            "depthMm": masonry["sideWallDepthMm"],
        },
        "rightWall": {
            "x0Mm": round(visual_w, 1),
            "widthMm": masonry["sideWallWidthMm"],
            "topMm": masonry.get("wallTopMm"),
            "bottomMm": masonry.get("wallBottomMm"),
            "heightMm": masonry["wallHeightMm"],
            "depthMm": masonry["sideWallDepthMm"],
        },
    }

    bays.append({
        "bayId": bay_id,
        "bayType": bay_type,
        "widthMm": round(W, 1),
        "heightMm": round(H, 1),
        "leafCount": leaf_count,
        "foldLeft": left_n,
        "foldRight": right_n,
        "leaves": leaves_meta,
        "grill": grill_meta,
        "fillType": fill_type,
        "handleSide": handle_side,
        "masonry": masonry_out,
    })

    sections_map: dict[str, Any] = {
        frame.get("sectionId"): frame,
        wall_post_sec.get("sectionId"): wall_post_sec,
        leaf_frame_sec.get("sectionId"): leaf_frame_sec,
        louver_sec.get("sectionId"): louver_sec,
        support_sec.get("sectionId"): support_sec,
        grill_sec.get("sectionId"): grill_sec,
        track_ch_sec.get("sectionId"): track_ch_sec,
        track_bar_sec.get("sectionId"): track_bar_sec,
        handle_sec.get("sectionId"): handle_sec,
    }
    # Include every cut's section (multi-section louver pattern) so nest/cost use real kg/m
    for cut in cuts:
        sid = _s(cut.get("sectionId"))
        if sid and sid not in sections_map:
            hit = get_structural_section(sid)
            if hit:
                if str(hit.get("material") or "").lower().startswith("al") and c.get("alRatePerBar") is not None:
                    hit = dict(hit)
                    hit["purchaseRate"] = _f(c.get("alRatePerBar"))
                    hit["purchaseRateUnit"] = "full_length"
                elif c.get("msRatePerKg") is not None:
                    hit = _apply_ms_rates(hit, c)
                sections_map[sid] = hit
    kerf = _f(c.get("kerfMm"), DEFAULT_KERF_MM)
    trim = _f(c.get("trimMm"), DEFAULT_TRIM_MM)
    nests = _nest_by_section(cuts, sections=sections_map, kerf_mm=kerf, trim_mm=trim, qty=qty)

    # Weight subtotals
    iron_kg = 0.0
    al_kg = 0.0
    for nest in nests.values():
        uk = _f(nest.get("usedKg"))
        mat = str(nest.get("material") or "").lower()
        if mat.startswith("al"):
            al_kg += uk
        else:
            iron_kg += uk

    # Leaf weight for hinge capacity (moving leaf frame + fill only)
    leaf_weight = 0.0
    if leaves_meta:
        per_leaf_cuts = [c for c in cuts if c.get("leafId") == leaves_meta[0].get("leafId")]
        leaf_weight = sum(_f(x.get("usedKg")) for x in per_leaf_cuts)

    hardware = _hardware_lines(c, leaves=leaves_meta, leaf_weight_kg=leaf_weight)
    hw_amount = sum(_f(h.get("amount")) for h in hardware if not h.get("includedInPackage"))

    # Coating — ₹/rft | sft | kg
    coat_rate = _f(c.get("coatingRate") or c.get("powderRate"), 25.0)
    coat_unit = _s(c.get("coatingRateUnit") or c.get("powderRateUnit"), "rft").lower()
    # Coat MS framing used length as rft by default (wood-finish)
    ms_used_m = sum(_f(n.get("usedM")) for n in nests.values() if not str(n.get("material") or "").startswith("al"))
    coat_qty = 0.0
    if coat_unit in ("rft", "ft"):
        coat_qty = ms_used_m / 0.3048
    elif coat_unit in ("sft", "sqft"):
        coat_qty = (W * H) / SQMM_PER_SQFT
    elif coat_unit == "kg":
        coat_qty = iron_kg
    else:
        coat_qty = ms_used_m
        coat_unit = "m"
    coating_amount = money_n(coat_qty * coat_rate)

    # Making + install
    area_sft = (W * H) / SQMM_PER_SQFT
    fab_rate = _f(c.get("fabRatePerSft") or c.get("makingInstallRate"), 150.0)
    fab_amount = money_n(area_sft * fab_rate * qty)

    # Material purchase subtotals
    ms_purchase = 0.0
    al_purchase = 0.0
    for nest in nests.values():
        amt = nest.get("purchase", {}).get("amount")
        if amt is None:
            for m in nest.get("missing") or []:
                if m not in incomplete:
                    incomplete.append(m)
            continue
        if str(nest.get("material") or "").startswith("al"):
            al_purchase += _f(amt)
        else:
            ms_purchase += _f(amt)

    # Internal cost from real BOM nests only (purchase amount already excludes double wastage).
    # Customer selling is NOT cost — set later via cart sale unit / profit % / lump rate.
    if coat_rate <= 0:
        incomplete.append("coating rate missing")
    if fab_rate < 0:
        incomplete.append("fab rate missing")
    coat_total = money_n(coat_qty * coat_rate)
    hw_total = money_n(hw_amount * qty)
    cost_parts = {
        "iron": money_n(ms_purchase),
        "aluminium": money_n(al_purchase),
        "coating": coat_total,
        "hardware": hw_total,
        "fabricationInstall": fab_amount,
    }
    cost_total = money_n(sum(cost_parts.values()))
    cost_per_sft = money_n(cost_total / (area_sft * qty)) if area_sft * qty > 0 else None
    # Suggested sell targets (do not write into price as if sold)
    selling_basis = _s(c.get("sellingBasis") or c.get("saleUnit"), "sft").lower()
    selling_parts = dict(cost_parts)  # legacy alias — UI must treat as cost breakdown
    selling_total = cost_total
    selling_per_sft = cost_per_sft

    # Blade summary
    blade_count_total = sum(int(m.get("bladeCount") or 0) for m in fill_metas)
    al_bars = 0
    ms_bars = 0
    for nest in nests.values():
        if str(nest.get("material") or "").startswith("al"):
            al_bars += int(nest.get("bars") or 0)
        else:
            ms_bars += int(nest.get("bars") or 0)

    for nest in nests.values():
        for m in nest.get("missing") or []:
            if m not in incomplete:
                incomplete.append(m)
    for cut in cuts:
        for m in cut.get("missing") or []:
            label = f"{cut.get('sectionName') or cut.get('sectionId')}: {m}"
            if label not in incomplete:
                incomplete.append(label)

    description = (
        f"{bay_type.replace('_', ' ').title()} · {mm_n(W)}×{mm_n(H)} mm · "
        f"{left_n}+{right_n} leaves" if leaf_count else f"{bay_type.replace('_', ' ').title()} · {mm_n(W)}×{mm_n(H)} mm"
    )

    return {
        "ok": not incomplete,
        "incomplete": incomplete,
        "bayType": bay_type,
        "widthMm": round(W, 1),
        "heightMm": round(H, 1),
        "widthFt": round(W / MM_PER_FT, 3),
        "heightFt": round(H / MM_PER_FT, 3),
        "areaSft": round(area_sft, 3),
        "qty": qty,
        "foldLeft": left_n,
        "foldRight": right_n,
        "leafCount": leaf_count,
        "wallPostCount": wall_posts,
        "frameSectionId": frame.get("sectionId"),
        "wallPostSectionId": wall_post_sec.get("sectionId"),
        "leafFrameSectionId": leaf_frame_sec.get("sectionId"),
        "louverSectionId": louver_sec.get("sectionId"),
        "supportSectionId": support_sec.get("sectionId"),
        "grillSectionId": grill_sec.get("sectionId"),
        "trackChannelSectionId": track_ch_sec.get("sectionId"),
        "trackBarSectionId": track_bar_sec.get("sectionId"),
        "handleSectionId": handle_sec.get("sectionId"),
        "handleSide": handle_side,
        "frameFaceMm": face,
        "leafFaceMm": leaf_face,
        "wallPostFaceMm": post_face,
        "fillType": fill_type,
        "louverSpacingMode": _s(c.get("louverSpacingMode") or c.get("spacingMode"), "fixed_gap"),
        "grillStyle": _s(c.get("grillStyle"), "straight"),
        "bays": bays,
        "leaves": leaves_meta,
        "handles": handles_meta,
        "masonry": masonry_out,
        "grill": grill_meta,
        "track": track_meta,
        "hinges": hinge_meta,
        "cuts": [c for c in cuts if _i(c.get("pieces")) > 0 or c.get("memberRole") == "wall_post"],
        "cutList": cuts,
        "nests": nests,
        "bladeCountTotal": blade_count_total,
        "bladeCountPerLeaf": (fill_metas[0].get("bladeCount") if fill_metas else 0),
        "louverGapMm": fill_metas[0].get("gapMm") if fill_metas else _f(c.get("louverGapMm"), 25),
        "fillMetas": fill_metas,
        "hardware": hardware,
        "weight": {
            "ironKg": round(iron_kg, 3),
            "aluminiumKg": round(al_kg, 3),
            "totalKg": round(iron_kg + al_kg, 3),
            "leafKg": round(leaf_weight, 3),
        },
        "bars": {"ms": ms_bars, "aluminium": al_bars},
        "coating": {
            "rate": coat_rate,
            "unit": coat_unit,
            "qty": round(coat_qty, 3),
            "amount": coat_total,
            "finish": _s(c.get("coatingFinish") or c.get("finish"), "wood_finish"),
        },
        "rates": {
            "msPurchaseRate": frame.get("purchaseRate"),
            "msPurchaseUnit": frame.get("purchaseRateUnit"),
            "msStockFt": frame.get("stockLengthFt"),
            "msBarKg": frame.get("kgPerStockLength"),
            "alPurchaseRate": louver_sec.get("purchaseRate"),
            "alPurchaseUnit": louver_sec.get("purchaseRateUnit"),
            "alStockFt": louver_sec.get("stockLengthFt"),
            "coatingRate": coat_rate,
            "coatingUnit": coat_unit,
            "fabRatePerSft": fab_rate,
            "hardwarePackage": money_n(_f(c.get("hardwarePackageAmount"), 10000)),
        },
        "bayDims": bay_dims,
        "visualWidthMm": round(visual_w, 1),
        "leftGateWidthMm": round(sum(_f(L.get("outerWidthMm")) for L in left_leaves), 1) if left_leaves else 0.0,
        "rightGateWidthMm": round(sum(_f(L.get("outerWidthMm")) for L in right_leaves), 1) if right_leaves else 0.0,
        "cost": {
            "iron": cost_parts["iron"],
            "aluminium": cost_parts["aluminium"],
            "coating": cost_parts["coating"],
            "hardware": cost_parts["hardware"],
            "fabricationInstall": cost_parts["fabricationInstall"],
            "total": cost_total,
            "perSft": cost_per_sft,
            "breakdown": cost_parts,
            "incomplete": list(incomplete),
            "factoryReady": not incomplete,
        },
        # Legacy keys kept for older UI — equal to cost until cart applies user sell rate.
        "selling": selling_parts,
        "sellingTotal": selling_total,
        "sellingPerSft": selling_per_sft,
        "sellingBasis": selling_basis,
        "costPerSft": cost_per_sft,
        "description": description,
        "kerfMm": kerf,
        "trimMm": trim,
        "clearances": {
            "wallClearanceMm": wall_clear,
            "meetingClearanceMm": meeting_clear,
            "bottomClearanceMm": bottom_clear,
            "topClearanceMm": top_clear,
        },
    }


def _svg_mitred_hollow_frame(
    parts: list[str],
    *,
    sx,
    sy,
    x_mm: float,
    y_mm: float,
    w_mm: float,
    h_mm: float,
    face_mm: float,
    role: str = "frame",
    fill: str = "none",
    stroke: str = "#111111",
    sw: float = 1.15,
) -> None:
    """Line-only hollow section frame with 45° mitre corners (window CAD style)."""
    f = max(face_mm, 1.0)
    # Outer + inner rectangles — stroke only
    parts.append(
        f'<rect x="{sx(x_mm):.2f}" y="{sy(y_mm):.2f}" width="{abs(sx(x_mm+w_mm)-sx(x_mm)):.2f}" '
        f'height="{abs(sy(y_mm+h_mm)-sy(y_mm)):.2f}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}" '
        f'data-role="{escape(role)}" data-mitre="1"/>'
    )
    ix, iy = x_mm + f, y_mm + f
    iw, ih = max(w_mm - 2 * f, 0.0), max(h_mm - 2 * f, 0.0)
    if iw > 1 and ih > 1:
        parts.append(
            f'<rect x="{sx(ix):.2f}" y="{sy(iy):.2f}" width="{abs(sx(ix+iw)-sx(ix)):.2f}" '
            f'height="{abs(sy(iy+ih)-sy(iy)):.2f}" fill="none" stroke="{stroke}" stroke-width="{max(sw*0.85, 0.7):.2f}" '
            f'data-role="{escape(role)}_inner"/>'
        )
    # Profile edge paths (no fill) — head / sill / jambs
    for d, role_s in (
        (f"M {sx(x_mm):.2f} {sy(y_mm):.2f} L {sx(x_mm+w_mm):.2f} {sy(y_mm):.2f} "
         f"L {sx(x_mm+w_mm-f):.2f} {sy(y_mm+f):.2f} L {sx(x_mm+f):.2f} {sy(y_mm+f):.2f} Z", f"{role}_head"),
        (f"M {sx(x_mm):.2f} {sy(y_mm+h_mm):.2f} L {sx(x_mm+w_mm):.2f} {sy(y_mm+h_mm):.2f} "
         f"L {sx(x_mm+w_mm-f):.2f} {sy(y_mm+h_mm-f):.2f} L {sx(x_mm+f):.2f} {sy(y_mm+h_mm-f):.2f} Z", f"{role}_sill"),
        (f"M {sx(x_mm):.2f} {sy(y_mm):.2f} L {sx(x_mm+f):.2f} {sy(y_mm+f):.2f} "
         f"L {sx(x_mm+f):.2f} {sy(y_mm+h_mm-f):.2f} L {sx(x_mm):.2f} {sy(y_mm+h_mm):.2f} Z", f"{role}_jamb_L"),
        (f"M {sx(x_mm+w_mm):.2f} {sy(y_mm):.2f} L {sx(x_mm+w_mm):.2f} {sy(y_mm+h_mm):.2f} "
         f"L {sx(x_mm+w_mm-f):.2f} {sy(y_mm+h_mm-f):.2f} L {sx(x_mm+w_mm-f):.2f} {sy(y_mm+f):.2f} Z", f"{role}_jamb_R"),
    ):
        parts.append(
            f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{max(sw*0.7, 0.65):.2f}" '
            f'data-role="{escape(role_s)}" data-mitre="1"/>'
        )
    # Explicit 45° mitre corner marks
    for ox, oy, ix_, iy_ in (
        (x_mm, y_mm, x_mm + f, y_mm + f),
        (x_mm + w_mm, y_mm, x_mm + w_mm - f, y_mm + f),
        (x_mm + w_mm, y_mm + h_mm, x_mm + w_mm - f, y_mm + h_mm - f),
        (x_mm, y_mm + h_mm, x_mm + f, y_mm + h_mm - f),
    ):
        parts.append(
            f'<line x1="{sx(ox):.2f}" y1="{sy(oy):.2f}" x2="{sx(ix_):.2f}" y2="{sy(iy_):.2f}" '
            f'stroke="{stroke}" stroke-width="{max(sw*0.9, 0.8):.2f}" data-mitre-line="1"/>'
        )


def _svg_gate_hinges(
    parts: list[str],
    *,
    sx,
    sy,
    scale: float,
    x_mm: float,
    h_mm: float,
    y0_mm: float = 0.0,
    count: int = 3,
    stile_mm: float = 75.0,
    thicker: bool = True,
) -> None:
    """Casement-style hinges: same placement + stadium glyph, slightly taller, line-only."""
    try:
        from WEOS.factory.geometry import (
            casement_hinge_svg,
            hinge_capsule_size_mm,
            hinge_centers_mm,
        )
    except Exception:
        return
    centers = hinge_centers_mm(h_mm, count=max(count, 2))
    # Casement sizing in model-mm, then to SVG px; bump height ~18% for gates
    tw, th = hinge_capsule_size_mm(h_mm, max(stile_mm, 20.0), orientation="vertical")
    th = th * (1.18 if thicker else 1.0)
    hw = max(tw * scale, 6.0)
    hh = max(th * scale, 14.0)
    for cy_from_top in centers:
        cy = sy(y0_mm + cy_from_top)
        cx = sx(x_mm)
        parts.append(
            casement_hinge_svg(
                cx, cy, w=hw, h=hh, stroke="#111111", stroke_width=0.7,
                fill="none", segments=3,
                extra_attrs='data-gate-hinge="1" data-hinge="1"',
            )
        )


def _svg_brick_hatch(
    parts: list[str],
    *,
    sx,
    sy,
    x_mm: float,
    y_mm: float,
    w_mm: float,
    h_mm: float,
    role: str = "masonry",
    brick_l: float = DEFAULT_BRICK_L_MM,
    brick_h: float = DEFAULT_BRICK_H_MM,
) -> None:
    """Line-only running-bond brick hatch (elevation) — no fills/textures."""
    if w_mm <= 1 or h_mm <= 1:
        return
    x1, y1 = x_mm + w_mm, y_mm + h_mm
    parts.append(
        f'<rect x="{sx(x_mm):.2f}" y="{sy(y_mm):.2f}" width="{abs(sx(x1)-sx(x_mm)):.2f}" '
        f'height="{abs(sy(y1)-sy(y_mm)):.2f}" fill="none" stroke="#111827" stroke-width="1.2" '
        f'data-role="{escape(role)}" data-brick="1"/>'
    )
    # Bed joints (horizontal courses)
    course = max(brick_h, 40.0)
    y = y_mm + course
    while y < y1 - 0.5:
        parts.append(
            f'<line x1="{sx(x_mm):.2f}" y1="{sy(y):.2f}" x2="{sx(x1):.2f}" y2="{sy(y):.2f}" '
            f'stroke="#111827" stroke-width="0.7" data-role="brick_bed"/>'
        )
        y += course
    # Head joints — running bond (offset every other course)
    bl = max(brick_l, 60.0)
    row = 0
    y0 = y_mm
    while y0 < y1 - 0.5:
        yb = min(y0 + course, y1)
        offset = (bl * 0.5) if (row % 2) else 0.0
        x = x_mm + offset
        while x < x1 - 0.5:
            if x > x_mm + 0.5:
                parts.append(
                    f'<line x1="{sx(x):.2f}" y1="{sy(y0):.2f}" x2="{sx(x):.2f}" y2="{sy(yb):.2f}" '
                    f'stroke="#111827" stroke-width="0.65" data-role="brick_head"/>'
                )
            x += bl
        row += 1
        y0 += course


def _svg_handle_2d(
    parts: list[str],
    *,
    sx,
    sy,
    x_mm: float,
    y_mm: float,
    height_mm: float,
    face_mm: float = HANDLE_FACE_MM,
    stub_mm: float = HANDLE_STUB_MM,
    side: str = "R",
) -> None:
    """Full 2D pipe pull handle on stile centreline — line-only."""
    f = max(face_mm, 10.0)
    stub = max(stub_mm, 40.0)
    stroke = "#111111"
    vx0 = x_mm - f / 2.0
    parts.append(
        f'<rect x="{sx(vx0):.2f}" y="{sy(y_mm):.2f}" width="{max(abs(sx(vx0+f)-sx(vx0)), 1):.2f}" '
        f'height="{abs(sy(y_mm+height_mm)-sy(y_mm)):.2f}" fill="none" stroke="{stroke}" '
        f'stroke-width="1.0" data-role="handle" data-face-mm="{f:g}"/>'
    )
    inward = -1.0 if side == "R" else 1.0
    for yy in (y_mm, y_mm + height_mm - f):
        sx0 = x_mm
        sx1 = x_mm + inward * stub
        x_lo, x_hi = (sx0, sx1) if sx0 < sx1 else (sx1, sx0)
        parts.append(
            f'<rect x="{sx(x_lo):.2f}" y="{sy(yy):.2f}" width="{max(abs(sx(x_hi)-sx(x_lo)), 1):.2f}" '
            f'height="{max(abs(sy(yy+f)-sy(yy)), 1):.2f}" fill="none" stroke="{stroke}" '
            f'stroke-width="0.95" data-role="handle_stub"/>'
        )


def _svg_dim_h(parts: list[str], *, sx, sy, x0: float, x1: float, y: float, text: str, font: float = 11.0) -> None:
    """Window-style horizontal dimension (maroon thin ticks)."""
    stroke = "#8b1e1a"
    parts.append(
        f'<line x1="{sx(x0):.2f}" y1="{sy(y):.2f}" x2="{sx(x1):.2f}" y2="{sy(y):.2f}" '
        f'stroke="{stroke}" stroke-width="0.7" data-dim="1"/>'
    )
    for xx in (x0, x1):
        parts.append(
            f'<line x1="{sx(xx):.2f}" y1="{sy(y) - 3.5:.2f}" x2="{sx(xx):.2f}" y2="{sy(y) + 3.5:.2f}" '
            f'stroke="{stroke}" stroke-width="0.7" data-dim="1"/>'
        )
    mid = (x0 + x1) / 2.0
    parts.append(
        f'<text x="{sx(mid):.2f}" y="{sy(y) - 6:.2f}" text-anchor="middle" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{font:.0f}" fill="{stroke}" data-dim="1">'
        f'{escape(text)}</text>'
    )


def _svg_dim_v(parts: list[str], *, sx, sy, y0: float, y1: float, x: float, text: str, font: float = 11.0) -> None:
    """Window-style vertical dimension."""
    stroke = "#8b1e1a"
    parts.append(
        f'<line x1="{sx(x):.2f}" y1="{sy(y0):.2f}" x2="{sx(x):.2f}" y2="{sy(y1):.2f}" '
        f'stroke="{stroke}" stroke-width="0.7" data-dim="1"/>'
    )
    for yy in (y0, y1):
        parts.append(
            f'<line x1="{sx(x)-3.5:.2f}" y1="{sy(yy):.2f}" x2="{sx(x)+3.5:.2f}" y2="{sy(yy):.2f}" '
            f'stroke="{stroke}" stroke-width="0.7" data-dim="1"/>'
        )
    mid = (y0 + y1) / 2.0
    parts.append(
        f'<text x="{sx(x)-8:.2f}" y="{sy(mid):.2f}" text-anchor="middle" '
        f'transform="rotate(-90 {sx(x)-8:.2f} {sy(mid):.2f})" '
        f'font-family="Segoe UI, Arial, sans-serif" font-size="{font:.0f}" fill="{stroke}" data-dim="1">'
        f'{escape(text)}</text>'
    )


def _svg_grill_fill(
    parts: list[str],
    *,
    sx,
    sy,
    x0: float,
    y0: float,
    clear_w: float,
    clear_h: float,
    meta: Mapping[str, Any] | None,
) -> None:
    m = meta if isinstance(meta, Mapping) else {}
    style = _s(m.get("grillStyle"), "straight").lower()
    orient = _s(m.get("grillOrientation"), "vertical").lower()
    n = max(int(m.get("bladeCount") or 0), 0)
    face = max(_f(m.get("bladeFaceMm") or m.get("faceMm"), 10), 2.0)
    if style in ("diagonal", "cross"):
        parts.append(
            f'<line x1="{sx(x0):.2f}" y1="{sy(y0):.2f}" x2="{sx(x0+clear_w):.2f}" y2="{sy(y0+clear_h):.2f}" '
            f'stroke="#334155" stroke-width="1.4" data-role="grill_diagonal"/>'
        )
        parts.append(
            f'<line x1="{sx(x0+clear_w):.2f}" y1="{sy(y0):.2f}" x2="{sx(x0):.2f}" y2="{sy(y0+clear_h):.2f}" '
            f'stroke="#334155" stroke-width="1.4" data-role="grill_diagonal"/>'
        )
        return
    if n <= 0:
        # Fallback visual: pitch from spacing
        spacing = max(_f(m.get("grillSpacingMm"), 100), 40)
        if orient == "horizontal":
            n = max(int(math.floor(clear_h / spacing)), 1)
        else:
            n = max(int(math.floor(clear_w / spacing)), 1)
    if orient == "horizontal":
        pitch = clear_h / max(n, 1)
        for i in range(n):
            cy = y0 + pitch * (i + 0.5) - face / 2.0
            parts.append(
                f'<rect x="{sx(x0):.2f}" y="{sy(cy):.2f}" width="{abs(sx(x0+clear_w)-sx(x0)):.2f}" '
                f'height="{max(abs(sy(cy+face)-sy(cy)), 0.8):.2f}" fill="none" stroke="#111111" '
                f'stroke-width="0.7" data-role="grill_bar"/>'
            )
    else:
        pitch = clear_w / max(n, 1)
        for i in range(n):
            cx = x0 + pitch * (i + 0.5) - face / 2.0
            parts.append(
                f'<rect x="{sx(cx):.2f}" y="{sy(y0):.2f}" width="{max(abs(sx(cx+face)-sx(cx)), 0.8):.2f}" '
                f'height="{abs(sy(y0+clear_h)-sy(y0)):.2f}" fill="none" stroke="#111111" '
                f'stroke-width="0.7" data-role="grill_bar"/>'
            )


def _svg_louver_from_layout(
    parts: list[str],
    *,
    sx,
    sy,
    x0: float,
    y0: float,
    layout: Mapping[str, Any] | None,
    fallback_face: float = 25.0,
    fallback_gap: float = 25.0,
    fallback_count: int = 0,
    clear_w: float = 0.0,
    clear_h: float = 0.0,
) -> None:
    """Draw louvers from panel_fills layout (multi-section aware) — line-only."""
    stroke = "#111111"
    blades = list((layout or {}).get("blades") or [])
    if blades:
        for b in blades:
            bx0 = x0 + _f(b.get("x0"))
            by0 = y0 + _f(b.get("y0"))
            bx1 = x0 + _f(b.get("x1"))
            by1 = y0 + _f(b.get("y1"))
            parts.append(
                f'<rect x="{sx(min(bx0, bx1)):.2f}" y="{sy(min(by0, by1)):.2f}" '
                f'width="{max(abs(sx(bx1)-sx(bx0)), 0.7):.2f}" '
                f'height="{max(abs(sy(by1)-sy(by0)), 0.7):.2f}" fill="none" stroke="{stroke}" '
                f'stroke-width="0.7" data-role="louver_blade" data-section="{escape(_s(b.get("sectionId")))}"/>'
            )
        return
    # Uniform fallback
    bc = max(int(fallback_count), 0)
    bf = max(fallback_face, 2.0)
    gap = max(fallback_gap, 0.0)
    margin = _f((layout or {}).get("marginMm"))
    cursor = x0 + margin
    for _ in range(bc):
        parts.append(
            f'<rect x="{sx(cursor):.2f}" y="{sy(y0):.2f}" width="{max(abs(sx(cursor+bf)-sx(cursor)), 0.7):.2f}" '
            f'height="{abs(sy(y0+clear_h)-sy(y0)):.2f}" fill="none" stroke="{stroke}" '
            f'stroke-width="0.7" data-role="louver_blade"/>'
        )
        cursor += bf + gap


def gate_svg(cfg: Mapping[str, Any], quote: Mapping[str, Any] | None = None) -> str:
    """Elevation SVG: masonry walls, mitred frames, hinges, handles, wheels, track."""
    q = quote or compute_gate(cfg)
    W = _f(q.get("widthMm") or cfg.get("widthMm"), 3962)
    H = _f(q.get("heightMm") or cfg.get("heightMm"), 2438)
    face = _f(q.get("frameFaceMm"), 75)
    leaf_face = _f(q.get("leafFaceMm"), face)
    post_face = _f(q.get("wallPostFaceMm"), face)
    left = _i(q.get("foldLeft"), 0)
    right = _i(q.get("foldRight"), 0)
    leaves = list(q.get("leaves") or [])
    bay_type = _s(q.get("bayType"), "folding_privacy")
    track = q.get("track") if isinstance(q.get("track"), Mapping) else None
    hinge_meta = q.get("hinges") if isinstance(q.get("hinges"), Mapping) else None
    masonry = q.get("masonry") if isinstance(q.get("masonry"), Mapping) else _masonry_dims(cfg, H)
    handles = list(q.get("handles") or [])

    side_w = _f(masonry.get("sideWallWidthMm"), DEFAULT_SIDE_WALL_MM)
    wall_top = _f(masonry.get("wallTopMm"), -WALL_ABOVE_GATE_MM)
    wall_bot = _f(masonry.get("wallBottomMm"), H)
    wall_h = _f(masonry.get("wallHeightMm"), wall_bot - wall_top)
    mid_on = bool(masonry.get("midPillarEnabled"))
    mid_w = _f(masonry.get("midPillarWidthMm")) if mid_on else 0.0
    mid_x0 = masonry.get("midPillarX0Mm")
    visual_w = _f(q.get("visualWidthMm") or masonry.get("visualWidthMm"), W)
    if mid_on and mid_w > 0:
        visual_w = max(visual_w, W + mid_w)
    track_x0 = _f(track.get("x0Mm"), 0.0) if track else 0.0
    track_len = _f(track.get("lengthMm"), W) if track else W
    track_x1 = track_x0 + track_len

    # Content extents in mm (walls outside; mid may expand visual; track may overrun)
    content_x0 = min(-side_w, track_x0 if track else 0.0)
    content_x1 = max(visual_w + side_w, track_x1 if track else visual_w)
    content_w = max(content_x1 - content_x0, visual_w + 2 * side_w)
    content_y0 = min(wall_top, -28.0)  # room for dims above gate
    content_y1 = max(wall_bot, H)

    track_extra = 0.0
    if track:
        track_extra = max(_f(track.get("channelDepthMm"), 75) * 0.55, 40.0)

    vb_w, vb_h = 820.0, 540.0
    pad = 28.0
    title_h = 34.0
    max_w = vb_w - pad * 2
    max_h = vb_h - pad * 2 - title_h - (28 if track_extra else 8)
    content_h = content_y1 - content_y0
    scale = min(max_w / max(content_w, 1.0), max_h / max(content_h + track_extra, 1.0))
    x0 = pad + (max_w - content_w * scale) / 2.0 - content_x0 * scale
    y0 = title_h + pad * 0.35 - content_y0 * scale

    def sx(mm: float) -> float:
        return x0 + mm * scale

    def sy(mm: float) -> float:
        return y0 + mm * scale

    bay = bay_type.replace("_", " ").title()
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:g} {vb_h:g}" '
        f'data-model-system="gate" data-bay-type="{escape(bay_type)}" '
        f'data-frame-face-mm="{face:g}" data-scale-mm-per-px="{1/scale if scale else 0:g}" '
        f'data-handle-side="{escape(_s(q.get("handleSide"), ""))}" role="img">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{pad:g}" y="22" font-family="Arial" font-size="15" font-weight="700" fill="#1f2937">'
        f'{escape(bay)}</text>',
        f'<text x="{vb_w - pad:g}" y="22" font-family="Arial" font-size="11" text-anchor="end" fill="#475569">'
        f'{mm_n(W)} × {mm_n(H)} mm · {left}+{right}</text>',
    ]

    # Side walls — top +100 mm above gate, bottom at ground (gate bottom gap stays open)
    _svg_brick_hatch(
        parts, sx=sx, sy=sy, x_mm=-side_w, y_mm=wall_top, w_mm=side_w, h_mm=wall_h, role="side_wall_L",
    )
    _svg_brick_hatch(
        parts, sx=sx, sy=sy, x_mm=visual_w, y_mm=wall_top, w_mm=side_w, h_mm=wall_h, role="side_wall_R",
    )
    if mid_on and mid_w > 0:
        mx = _f(mid_x0, (W - mid_w) / 2.0)
        _svg_brick_hatch(
            parts, sx=sx, sy=sy, x_mm=mx, y_mm=wall_top, w_mm=mid_w, h_mm=wall_h, role="mid_pillar",
        )

    wp = _i(q.get("wallPostCount"), 0)
    if wp >= 1:
        _svg_mitred_hollow_frame(
            parts, sx=sx, sy=sy, x_mm=0, y_mm=0, w_mm=post_face, h_mm=H, face_mm=min(post_face * 0.35, 18),
            role="wall_post",
        )
    if wp >= 2:
        _svg_mitred_hollow_frame(
            parts, sx=sx, sy=sy, x_mm=visual_w - post_face, y_mm=0, w_mm=post_face, h_mm=H,
            face_mm=min(post_face * 0.35, 18),
            role="wall_post",
        )

    n = len(leaves) or (left + right)
    if n > 0:
        inner_x = post_face if wp else 0.0
        for i, leaf in enumerate(leaves or [{"leafId": f"L{i+1}"} for i in range(n)]):
            lx = _f(leaf.get("x0Mm"), inner_x)
            leaf_w = _f(leaf.get("outerWidthMm"))
            if leaf_w <= 0:
                # Legacy equal fallback
                inner_w = W - (2 * post_face if wp >= 2 else (post_face if wp else 0.0)) - mid_w
                leaf_w = inner_w / max(n, 1)
                lx = inner_x + i * leaf_w
                if mid_on and mid_x0 is not None and lx >= _f(mid_x0):
                    lx += mid_w
            lf = _f(leaf.get("frameFaceMm"), leaf_face)
            leaf_h = _f(leaf.get("outerHeightMm"), H)
            ly = _f(leaf.get("y0Mm"), 0.0)
            _svg_mitred_hollow_frame(
                parts, sx=sx, sy=sy, x_mm=lx, y_mm=ly, w_mm=leaf_w, h_mm=leaf_h, face_mm=lf,
                role="moving_leaf_frame",
            )
            clear_x = lx + lf
            clear_y = ly + lf
            clear_w = max(leaf_w - 2 * lf, 0)
            clear_h = max(leaf_h - 2 * lf, 0)
            fill = leaf.get("fill") if isinstance(leaf.get("fill"), Mapping) else {}
            if _s(fill.get("fillType")) == "grill" or bay_type == "fixed_grill":
                _svg_grill_fill(
                    parts, sx=sx, sy=sy, x0=clear_x, y0=clear_y,
                    clear_w=clear_w, clear_h=clear_h, meta=fill,
                )
            else:
                lay = fill.get("layout") if isinstance(fill.get("layout"), Mapping) else None
                _svg_louver_from_layout(
                    parts, sx=sx, sy=sy, x0=clear_x, y0=clear_y,
                    layout=lay or fill,
                    fallback_face=_f(fill.get("bladeFaceMm") or fill.get("bladeWidthMm"), 25),
                    fallback_gap=_f(fill.get("gapMm") or q.get("louverGapMm"), 25),
                    fallback_count=int(fill.get("bladeCount") or q.get("bladeCountPerLeaf") or 0),
                    clear_w=clear_w, clear_h=clear_h,
                )

            if bay_type.startswith("sliding") and _s(leaf.get("role"), "sliding") == "sliding":
                for wx_mm in (lx + WHEEL_INSET_MM, lx + leaf_w - WHEEL_INSET_MM):
                    wr = max(14.0 * scale, 5.0)
                    parts.append(
                        f'<circle cx="{sx(wx_mm):.2f}" cy="{sy(H - 8):.2f}" r="{wr:.2f}" '
                        f'fill="none" stroke="#111111" stroke-width="1" data-role="wheel" '
                        f'data-inset-mm="{WHEEL_INSET_MM:g}"/>'
                    )
                    parts.append(
                        f'<circle cx="{sx(wx_mm):.2f}" cy="{sy(H - 8):.2f}" r="{wr*0.35:.2f}" '
                        f'fill="none" stroke="#111111" stroke-width="0.7" data-role="wheel_hub"/>'
                    )

            hnd = leaf.get("handle") if isinstance(leaf.get("handle"), Mapping) else None
            if hnd:
                _svg_handle_2d(
                    parts, sx=sx, sy=sy,
                    x_mm=_f(hnd.get("xMm")),
                    y_mm=_f(hnd.get("yMm")),
                    height_mm=_f(hnd.get("heightMm"), H * 0.5),
                    face_mm=_f(hnd.get("faceMm"), HANDLE_FACE_MM),
                    stub_mm=_f(hnd.get("stubMm"), HANDLE_STUB_MM),
                    side=_s(hnd.get("side"), "R"),
                )

        # Handles listed only on quote (if leaf.handle missing)
        for hnd in handles:
            if not isinstance(hnd, Mapping):
                continue
            if any(isinstance(L.get("handle"), Mapping) and L.get("handle") is hnd for L in leaves):
                continue
            # skip duplicates already drawn via leaf.handle
            lid = hnd.get("leafId")
            if any(isinstance(L.get("handle"), Mapping) and L.get("leafId") == lid for L in leaves):
                continue
            _svg_handle_2d(
                parts, sx=sx, sy=sy,
                x_mm=_f(hnd.get("xMm")), y_mm=_f(hnd.get("yMm")),
                height_mm=_f(hnd.get("heightMm"), H * 0.5),
                face_mm=_f(hnd.get("faceMm"), HANDLE_FACE_MM),
                stub_mm=_f(hnd.get("stubMm"), HANDLE_STUB_MM),
                side=_s(hnd.get("side"), "R"),
            )

        # Hinges
        if hinge_meta:
            for joint in hinge_meta.get("joints") or []:
                if not isinstance(joint, Mapping):
                    continue
                at = _i(joint.get("atLeaf"), 0)
                kind = _s(joint.get("kind"))
                side = _s(joint.get("side"), "L")
                if joint.get("xMm") is not None:
                    hx = _f(joint.get("xMm"))
                elif kind == "wall_leaf":
                    hx = post_face if side == "L" else (W - post_face)
                elif 0 <= at < len(leaves):
                    leaf = leaves[at]
                    lx = _f(leaf.get("x0Mm"))
                    lw = _f(leaf.get("outerWidthMm"))
                    hx = lx if side == "L" else lx + lw
                else:
                    hx = post_face
                _svg_gate_hinges(
                    parts, sx=sx, sy=sy, scale=scale, x_mm=hx, h_mm=H,
                    count=_i(joint.get("count"), 3), thicker=True,
                    stile_mm=max(leaf_face, post_face, 40.0),
                )
    else:
        _svg_mitred_hollow_frame(
            parts, sx=sx, sy=sy, x_mm=0, y_mm=0, w_mm=W, h_mm=H, face_mm=face,
            role="outer_frame",
        )
        clear_x, clear_y = face, face
        clear_w, clear_h = max(W - 2 * face, 0), max(H - 2 * face, 0)
        grill = q.get("grill") if isinstance(q.get("grill"), Mapping) else None
        fill0 = (q.get("fillMetas") or [None])[0]
        if bay_type == "fixed_grill" or _s(q.get("fillType")) == "grill":
            _svg_grill_fill(
                parts, sx=sx, sy=sy, x0=clear_x, y0=clear_y,
                clear_w=clear_w, clear_h=clear_h, meta=grill or fill0 or {},
            )
        elif isinstance(fill0, Mapping):
            lay = fill0.get("layout") if isinstance(fill0.get("layout"), Mapping) else fill0
            _svg_louver_from_layout(
                parts, sx=sx, sy=sy, x0=clear_x, y0=clear_y, layout=lay,
                fallback_face=_f(fill0.get("bladeFaceMm"), 25),
                fallback_gap=_f(fill0.get("gapMm"), 25),
                fallback_count=int(fill0.get("bladeCount") or 0),
                clear_w=clear_w, clear_h=clear_h,
            )

    # Sliding floor track — line-only; length 2W+1ft on pocket side
    if track and bay_type.startswith("sliding"):
        ch_d = _f(track.get("channelDepthMm"), 75)
        ch_f = _f(track.get("channelFaceMm"), 38)
        bar_d = _f(track.get("barDiaMm"), 20)
        bury = _f(track.get("buryRatio"), TRACK_BURY_RATIO)
        buried = ch_d * bury
        above = ch_d - buried
        tw = track_len * scale
        gy = sy(H)
        stroke = "#111111"
        parts.append(
            f'<line x1="{sx(content_x0)-4:.2f}" y1="{gy:.2f}" x2="{sx(content_x1)+4:.2f}" y2="{gy:.2f}" '
            f'stroke="#78716c" stroke-width="0.9" stroke-dasharray="6 4" data-role="ground_line"/>'
        )
        parts.append(
            f'<rect x="{sx(track_x0):.2f}" y="{gy:.2f}" width="{tw:.2f}" height="{buried*scale:.2f}" '
            f'fill="none" stroke="{stroke}" stroke-width="0.85" data-role="track_c_channel_buried" '
            f'data-track-len-mm="{track_len:g}" data-track-x0-mm="{track_x0:g}"/>'
        )
        parts.append(
            f'<rect x="{sx(track_x0):.2f}" y="{gy - above*scale:.2f}" width="{tw:.2f}" height="{above*scale:.2f}" '
            f'fill="none" stroke="{stroke}" stroke-width="1" data-role="track_c_channel"/>'
        )
        parts.append(
            f'<rect x="{sx(track_x0):.2f}" y="{gy - above*scale - bar_d*scale:.2f}" width="{tw:.2f}" '
            f'height="{max(bar_d*scale, 2):.2f}" rx="{max(bar_d*scale/2, 1):.2f}" '
            f'fill="none" stroke="{stroke}" stroke-width="0.85" data-role="track_round_bar" '
            f'data-dia-mm="{bar_d:g}"/>'
        )
        parts.append(
            f'<text x="{sx(track_x0 + track_len/2):.2f}" y="{gy + buried*scale + 12:.2f}" text-anchor="middle" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="10" fill="#475569">'
            f'Track {mm_n(track_len)} · 2×W+1ft · pocket {_s(track.get("pocketSide"))} · '
            f'C-ch {ch_f:g}×{ch_d:g} + Ø{bar_d:g}</text>'
        )

    # Per-gate clear dims (exclude walls / mid pillar)
    bay_dims = list(q.get("bayDims") or [])
    if bay_dims:
        for bi, bd in enumerate(bay_dims):
            if not isinstance(bd, Mapping):
                continue
            _svg_dim_h(
                parts, sx=sx, sy=sy,
                x0=_f(bd.get("x0Mm")), x1=_f(bd.get("x1Mm")),
                y=-28 - bi * 18,
                text=str(mm_n(_f(bd.get("widthMm")))),
                font=11,
            )
    else:
        _svg_dim_h(parts, sx=sx, sy=sy, x0=0, x1=W, y=-28, text=str(mm_n(W)), font=11)
    _svg_dim_v(parts, sx=sx, sy=sy, y0=0, y1=H, x=-28 - side_w * 0.15, text=str(mm_n(H)), font=11)

    footer_y = vb_h - 12
    parts.append(
        f'<text x="{pad:g}" y="{footer_y:g}" font-family="Segoe UI, Arial, sans-serif" font-size="10" fill="#475569">'
        f'Blades/leaf={q.get("bladeCountPerLeaf")} · gap={q.get("louverGapMm")} mm · '
        f'MS bars={((q.get("bars") or {}).get("ms"))} · Al bars={((q.get("bars") or {}).get("aluminium"))} · '
        f'Fe {((q.get("weight") or {}).get("ironKg"))} kg · Al {((q.get("weight") or {}).get("aluminiumKg"))} kg'
        f'</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _section_dim_label(sec: Mapping[str, Any] | None, *, fallback_id: str = "") -> str:
    if not isinstance(sec, Mapping):
        return fallback_id or ""
    name = _s(sec.get("name") or sec.get("pickerLabel") or sec.get("sectionId") or fallback_id)
    w = _f(sec.get("widthMm") or sec.get("faceWidthMm"))
    h = _f(sec.get("heightMm") or sec.get("depthMm"))
    t = _f(sec.get("thicknessMm") or sec.get("wallThicknessMm"))
    bits = [name] if name else []
    if w > 0 and h > 0:
        dims = f"{w:g}×{h:g}" + (f"×{t:g}" if t > 0 else "")
        if dims not in name:
            bits.append(dims + " mm")
    elif t > 0:
        bits.append(f"t{t:g}")
    return " ".join(bits).strip()


def _role_location_label(role: str) -> str:
    r = (role or "").lower()
    mapping = {
        "wall_post": "Wall posts",
        "outer_jamb": "Outer frame jambs",
        "outer_head": "Outer frame head",
        "outer_sill": "Outer frame sill",
        "moving_leaf_stile": "Leaf frames (stiles)",
        "moving_leaf_rail": "Leaf frames (rails)",
        "louver_blade": "Inner louvers / blades",
        "support_rod": "Support rods",
        "grill_bar": "Grill bars",
        "handle": "Handles 25×25",
        "track_channel": "Track C-channel",
        "track_bar": "Track round bar",
    }
    return mapping.get(r, role.replace("_", " ").title() if role else "Member")


def gate_customer_spec_rows(
    quote: Mapping[str, Any],
    *,
    line: Mapping[str, Any] | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """Customer-facing gate/grill/privacy specs — flowing paragraphs, not skinny KV spam."""
    q = quote if isinstance(quote, Mapping) else {}
    ln = line if isinstance(line, Mapping) else {}
    c = cfg if isinstance(cfg, Mapping) else {}
    rows: list[tuple[str, str]] = []

    title = _s(
        ln.get("displayName")
        or q.get("description")
        or "Gate / Privacy screen"
    )
    bay = _s(q.get("bayType"), "folding_privacy").replace("_", " ").title()
    W = _f(q.get("widthMm") or ln.get("width"))
    H = _f(q.get("heightMm") or ln.get("height"))
    rows.append(("", f"{title} · {bay}"))

    size_bits = []
    if W > 0 and H > 0:
        size_bits.append(f"{mm_n(W)} × {mm_n(H)} mm")
        size_bits.append(f"{round(W / MM_PER_FT, 3)} × {round(H / MM_PER_FT, 3)} ft")
    if q.get("leafCount"):
        size_bits.append(f"leaves {q.get('foldLeft') or 0}+{q.get('foldRight') or 0}")
    if q.get("areaSft"):
        size_bits.append(f"{q.get('areaSft')} Sq.Ft.")
    if size_bits:
        rows.append(("SIZE", " · ".join(size_bits)))

    # Where used + section dims / thickness
    used_rows: list[str] = []
    dim_list: list[str] = []
    thick_list: list[str] = []
    seen_sid: set[str] = set()
    for sid_key, role_lbl in (
        ("frameSectionId", "Outer / wall frame"),
        ("wallPostSectionId", "Wall posts"),
        ("leafFrameSectionId", "Leaf frames"),
        ("louverSectionId", "Louver / blade"),
        ("grillSectionId", "Grill bar"),
        ("supportSectionId", "Support rods"),
        ("handleSectionId", "Handles"),
        ("trackChannelSectionId", "Track C-channel"),
        ("trackBarSectionId", "Track round"),
    ):
        sid = _s(q.get(sid_key))
        if not sid or sid in seen_sid:
            continue
        seen_sid.add(sid)
        sec = get_structural_section(sid) or {}
        label = _section_dim_label(sec, fallback_id=sid)
        used_rows.append(f"{role_lbl}: {label}" if label else role_lbl)
        if label:
            dim_list.append(label)
        t = _f(sec.get("thicknessMm") or sec.get("wallThicknessMm"))
        if t > 0:
            thick_list.append(f"{sec.get('name') or sid} t{t:g}")

    # Pattern blades (multi-section)
    gap_bits: list[str] = []
    pattern = None
    for meta in q.get("fillMetas") or []:
        if isinstance(meta, Mapping) and meta.get("pattern"):
            pattern = meta.get("pattern")
            break
    if isinstance(pattern, list) and pattern:
        for i, slot in enumerate(pattern):
            if not isinstance(slot, Mapping):
                continue
            sid = _s(slot.get("sectionId"))
            sec = get_structural_section(sid) if sid else {}
            lab = _section_dim_label(sec, fallback_id=sid) or sid
            gap = slot.get("gapAfterMm")
            bit = lab
            if gap is not None:
                bit += f" · gap {gap} mm"
                gap_bits.append(f"{gap} mm")
            used_rows.append(f"Pattern blade {i + 1}: {bit}")
            if sid and sid not in seen_sid:
                seen_sid.add(sid)
                if lab:
                    dim_list.append(lab)
    elif q.get("louverGapMm") is not None:
        gap_bits.append(f"{q.get('louverGapMm')} mm clear")

    if used_rows:
        rows.append(("SECTIONS", " · ".join(used_rows)))
    if dim_list:
        rows.append(("DIMS", " · ".join(dict.fromkeys(dim_list))))  # unique preserve order
    if thick_list:
        rows.append(("THICKNESS", " · ".join(dict.fromkeys(thick_list))))
    if gap_bits:
        rows.append(("GAPS", " · ".join(dict.fromkeys(gap_bits))))

    # Weights Fe / Al
    wt = q.get("weight") if isinstance(q.get("weight"), Mapping) else {}
    nests = q.get("nests") if isinstance(q.get("nests"), Mapping) else {}
    fe_bits: list[str] = []
    al_bits: list[str] = []
    for nest in nests.values():
        if not isinstance(nest, Mapping):
            continue
        mat = str(nest.get("material") or "").lower()
        kg = nest.get("usedKg")
        name = nest.get("sectionName") or nest.get("sectionId")
        if kg is None:
            continue
        line_w = f"{name} {kg} kg" if name else f"{kg} kg"
        if mat.startswith("al"):
            al_bits.append(line_w)
        else:
            fe_bits.append(line_w)
    wt_parts: list[str] = []
    if fe_bits or wt.get("ironKg") is not None:
        total_fe = wt.get("ironKg")
        wt_parts.append(
            "Iron "
            + (f"total {total_fe} kg" if total_fe is not None else "")
            + ((" · " + " · ".join(fe_bits[:6])) if fe_bits else "")
        )
    if al_bits or wt.get("aluminiumKg") is not None:
        total_al = wt.get("aluminiumKg")
        wt_parts.append(
            "Al "
            + (f"total {total_al} kg" if total_al is not None else "")
            + ((" · " + " · ".join(al_bits[:6])) if al_bits else "")
        )
    if wt.get("totalKg") is not None:
        wt_parts.append(f"Total {wt.get('totalKg')} kg")
    if wt_parts:
        rows.append(("WEIGHT", " · ".join(p.strip(" ·") for p in wt_parts if p.strip(" ·"))))

    # Finish / coating / brand
    coat = q.get("coating") if isinstance(q.get("coating"), Mapping) else {}
    finish = _s(coat.get("finish") or ln.get("colour") or c.get("finish") or c.get("coatingFinish"))
    brand = _s(c.get("hardwareBrand") or ln.get("hardwareBrand") or "SS304")
    alloy = _s((c.get("alloy") if isinstance(c, Mapping) else "") or "")
    finish_bits = []
    if finish:
        finish_bits.append(finish.replace("_", " "))
    if coat.get("rate") is not None:
        finish_bits.append(f"coat ₹{coat.get('rate')}/{coat.get('unit') or 'rft'}")
    if brand:
        finish_bits.append(f"HW brand {brand}")
    if alloy:
        finish_bits.append(alloy)
    if finish_bits:
        rows.append(("FINISH", " · ".join(finish_bits)))

    # Hardware
    hw_bits: list[str] = []
    for hitem in q.get("hardware") or []:
        if not isinstance(hitem, Mapping):
            continue
        if hitem.get("isPackage"):
            hw_bits.append(f"package ₹{hitem.get('amount')}")
            incl = hitem.get("includes") or []
            if incl:
                hw_bits.append("includes " + ", ".join(str(x) for x in incl[:6]))
            continue
        name = _s(hitem.get("name") or hitem.get("catalogueId"))
        qty = hitem.get("qty")
        if hitem.get("includedInPackage"):
            hw_bits.append(f"{name}×{qty} (incl)")
        else:
            amt = hitem.get("amount")
            hw_bits.append(f"{name}×{qty}" + (f" ₹{amt}" if amt else ""))
    if hw_bits:
        rows.append(("HARDWARE", " · ".join(hw_bits)))

    # Charge basis (rate/amount columns still authoritative)
    sale_unit = _s(ln.get("saleUnit") or c.get("saleUnit") or "sqft").lower()
    rate = ln.get("sellingRate")
    if rate in (None, ""):
        rate = (ln.get("selling") or {}).get("sellingRate") if isinstance(ln.get("selling"), Mapping) else None
    if rate in (None, ""):
        rate = q.get("costPerSft") or (q.get("cost") or {}).get("perSft")
    amt = None
    if isinstance(ln.get("selling"), Mapping):
        amt = ln["selling"].get("sellingAmount")
    if amt in (None, ""):
        amt = ln.get("commercialTotal")
    unit_lbl = {"sqft": "SFT", "sft": "SFT", "sqm": "SQM", "opening": "opening", "rft": "RFT"}.get(sale_unit, sale_unit.upper())
    charge = f"₹{rate} / {unit_lbl}" if rate not in (None, "") else f"— / {unit_lbl}"
    if amt not in (None, ""):
        charge += f" → ₹{amt}"
    rows.append(("CHARGE", charge))

    # Incomplete flags (never invent numbers)
    incomplete = list(q.get("incomplete") or (q.get("cost") or {}).get("incomplete") or [])
    if incomplete:
        rows.append(("NOTE", "Incomplete: " + "; ".join(str(x) for x in incomplete[:4])))

    return [(a, b) for a, b in rows if b]


def format_gate_description(quote: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> str:
    """Plain-text customer description from real BOM / nest / cost fields."""
    rows = gate_customer_spec_rows(quote, cfg=cfg)
    parts: list[str] = []
    for lab, val in rows:
        if lab:
            parts.append(f"{lab}: {val}")
        else:
            parts.append(val)
    return " · ".join(parts) if parts else _s(quote.get("description"), "Gate / privacy screen")
