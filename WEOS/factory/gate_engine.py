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
    # Prefer synthetic solid round — do not pick SHS 12×12 hollow by size alone.
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
    spacing = _f(cfg.get("grillSpacingMm"), 100.0)
    cuts: list[dict[str, Any]] = []
    mid = section
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
        # Straight bars — vertical by default
        orient = _s(cfg.get("grillOrientation"), "vertical").lower()
        if orient == "horizontal":
            n = max(int(math.floor((clear_h + spacing) / (spacing + 1))), 1)
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
            n = max(int(math.floor((clear_w + spacing) / (spacing + 1))), 1)
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

    if spacing_mode == "equal_spacing" and cfg.get("bladeCount"):
        pack = equal_spacing_layout(usable_mm=usable, face_mm=face, blade_count=_i(cfg.get("bladeCount")))
    else:
        pack = fixed_gap_blade_count(usable_mm=usable, face_mm=face, gap_mm=gap)

    # Also run panel_fills for drawable geometry (aligned to pack count when possible)
    fill = normalize_panel_fill({
        "fillType": "louvers",
        "orientation": orient,
        "gapMm": pack.get("actualGapMm", gap),
        "bladeWidthMm": face,
        "bladeDepthMm": _f(louver_sec.get("depthMm") or louver_sec.get("heightMm"), face),
        "bladeThicknessMm": _f(louver_sec.get("thicknessMm"), 1.2),
        "patternMode": "uniform",
    })
    layout = compute_louver_layout(x0=0, y0=0, x1=clear_w, y1=clear_h, fill=fill)
    # Prefer fixed-gap count from acceptance formula when uniform
    n = int(pack.get("bladeCount") or layout.get("bladeCount") or 0)
    cuts: list[dict[str, Any]] = []
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
        "gapMm": pack.get("actualGapMm"),
        "marginMm": pack.get("marginMm"),
        "spacingMode": pack.get("mode"),
        "bladeFaceMm": face,
        "bladeLengthMm": round(blade_len, 1),
        "clearWidthMm": round(clear_w, 1),
        "clearHeightMm": round(clear_h, 1),
        "supportRodCount": rod_count,
        "supportCutMm": round(rod_cut, 1),
        "layout": layout,
        "pack": pack,
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
            "bars": bars,
            "nest": nest,
            "oversize": oversize,
            "purchase": purch,
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

    frame = _resolve_frame_section(c)
    # Apply acceptance MS commercial overrides onto frame card copy
    frame = dict(frame)
    if c.get("msBarWeightKg") is not None:
        frame["kgPerStockLength"] = _f(c.get("msBarWeightKg"))
    if c.get("msStockFt") is not None:
        frame["stockLengthFt"] = _f(c.get("msStockFt"))
        frame["stockLengthMm"] = _f(c.get("msStockFt")) * MM_PER_FT
    if c.get("msRatePerKg") is not None:
        frame["purchaseRate"] = _f(c.get("msRatePerKg"))
        frame["purchaseRateUnit"] = "kg"
    # Full-bar commercial: 25 kg / 20 ft → kg/m for used weight
    if frame.get("kgPerStockLength") and frame.get("stockLengthMm"):
        frame["weightKgPerM"] = _f(frame["kgPerStockLength"]) / (_f(frame["stockLengthMm"]) / 1000.0)

    louver_sec = dict(_resolve_louver_section(c))
    if c.get("alRatePerBar") is not None:
        louver_sec["purchaseRate"] = _f(c.get("alRatePerBar"))
        louver_sec["purchaseRateUnit"] = "full_length"
    if c.get("alStockFt") is not None:
        louver_sec["stockLengthFt"] = _f(c.get("alStockFt"))
        louver_sec["stockLengthMm"] = _f(c.get("alStockFt")) * MM_PER_FT
    support_sec = dict(_resolve_support_section(c))
    if c.get("msRatePerKg") is not None:
        support_sec["purchaseRate"] = _f(c.get("msRatePerKg"))
        support_sec["purchaseRateUnit"] = "kg"

    face = _section_face(frame, 75.0)
    left_n = max(_i(c.get("foldLeft"), 2), 0)
    right_n = max(_i(c.get("foldRight"), 2), 0)
    if bay_type.startswith("folding") or bay_type == "folding_privacy":
        if left_n + right_n <= 0:
            left_n, right_n = 2, 2
    leaf_count = left_n + right_n
    if bay_type.startswith("swing"):
        leaf_count = max(_i(c.get("leafCount"), 1), 1)
        left_n, right_n = leaf_count, 0
    if bay_type.startswith("sliding"):
        leaf_count = max(_i(c.get("leafCount"), 2), 1)
        left_n, right_n = leaf_count // 2, leaf_count - leaf_count // 2
    if bay_type in ("fixed_grill", "fixed_louvers"):
        leaf_count = 0
        left_n = right_n = 0

    wall_posts = _i(c.get("wallPostCount"), 2 if leaf_count else 0)
    # Shared posts/dividers counted once
    usable_w = W - wall_posts * face - 2 * wall_clear
    if leaf_count > 0:
        # Meeting clearances between leaves
        meetings = max(leaf_count - 1, 0)
        usable_w -= meetings * meeting_clear
        leaf_outer_w = usable_w / leaf_count
    else:
        leaf_outer_w = usable_w
    leaf_outer_h = H - bottom_clear - top_clear

    cuts: list[dict[str, Any]] = []
    bays: list[dict[str, Any]] = []
    leaves_meta: list[dict[str, Any]] = []
    bay_id = "bay-1"

    # Wall posts (separate physical members)
    for i in range(wall_posts):
        cuts.append(_cut_row(
            design_id=f"wall-post-{i+1}",
            bay_id=bay_id,
            leaf_id=None,
            role="wall_post",
            section=frame,
            cut_mm=H,
            pcs=1,
            end_cut="square",
            joint="wall",
        ))

    fill_metas: list[dict[str, Any]] = []
    if leaf_count > 0:
        idx = 0
        for side, n in (("L", left_n), ("R", right_n)):
            for j in range(n):
                idx += 1
                leaf_id = f"leaf-{side}{j+1}"
                # Leaf frame
                frame_cuts = _leaf_frame_cuts(
                    leaf_id=leaf_id, bay_id=bay_id,
                    leaf_w=leaf_outer_w, leaf_h=leaf_outer_h, frame=frame,
                    mitre=_bool(c.get("mitreLeafFrames"), True),
                )
                cuts.extend([fc for fc in frame_cuts if fc.get("memberRole") != "_meta_face"])
                clear_w = max(leaf_outer_w - 2 * face, 0.0)
                clear_h = max(leaf_outer_h - 2 * face, 0.0)
                leaf_rec = {
                    "leafId": leaf_id,
                    "side": side,
                    "index": j + 1,
                    "outerWidthMm": round(leaf_outer_w, 1),
                    "outerHeightMm": round(leaf_outer_h, 1),
                    "clearWidthMm": round(clear_w, 1),
                    "clearHeightMm": round(clear_h, 1),
                }
                if bay_type in ("folding_privacy", "folding_door", "fixed_louvers", "privacy_screen") or _s(c.get("fillType"), "louvers") == "louvers":
                    fill_cuts, meta = _louver_fill_cuts(
                        leaf_id=leaf_id, bay_id=bay_id,
                        clear_w=clear_w, clear_h=clear_h, cfg=c,
                        louver_sec=louver_sec, support_sec=support_sec,
                    )
                    cuts.extend(fill_cuts)
                    leaf_rec["fill"] = meta
                    fill_metas.append(meta)
                elif bay_type == "fixed_grill" or _s(c.get("fillType")) == "grill":
                    cuts.extend(_grill_cuts(
                        clear_w=clear_w, clear_h=clear_h, cfg=c, bay_id=bay_id, section=support_sec,
                    ))
                leaves_meta.append(leaf_rec)
    else:
        # Single fixed bay — outer frame + fill
        # Outer frame members
        for role, length, pcs in (
            ("outer_jamb", H, 2),
            ("outer_head", W, 1),
            ("outer_sill", W, 1),
        ):
            # expand pcs into separate design ids
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
        clear_w = max(W - 2 * face - 2 * wall_clear, 0.0)
        clear_h = max(H - 2 * face - bottom_clear - top_clear, 0.0)
        if bay_type == "fixed_grill":
            cuts.extend(_grill_cuts(clear_w=clear_w, clear_h=clear_h, cfg=c, bay_id=bay_id, section=support_sec))
        else:
            fill_cuts, meta = _louver_fill_cuts(
                leaf_id="bay-fill", bay_id=bay_id,
                clear_w=clear_w, clear_h=clear_h, cfg=c,
                louver_sec=louver_sec, support_sec=support_sec,
            )
            cuts.extend(fill_cuts)
            fill_metas.append(meta)

    bays.append({
        "bayId": bay_id,
        "bayType": bay_type,
        "widthMm": round(W, 1),
        "heightMm": round(H, 1),
        "leafCount": leaf_count,
        "foldLeft": left_n,
        "foldRight": right_n,
        "leaves": leaves_meta,
    })

    sections_map = {
        frame.get("sectionId"): frame,
        louver_sec.get("sectionId"): louver_sec,
        support_sec.get("sectionId"): support_sec,
    }
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

    # Selling
    selling_basis = _s(c.get("sellingBasis") or c.get("saleUnit"), "sft").lower()
    # Customer selling = materials selling basis OR cost+markup; acceptance uses itemised
    material_cost = ms_purchase + al_purchase + coating_amount + hw_amount
    # Internal cost
    cost_total = money_n((material_cost + fab_amount / max(qty, 1)) * qty) if False else money_n(
        (ms_purchase + al_purchase + coating_amount + hw_amount) * 1  # nests already × qty
        + fab_amount
    )
    # Recompute: nests already include qty; fab includes qty; hw is per opening × qty
    hw_total = money_n(hw_amount * qty)
    coat_total = money_n(coating_amount * qty) if qty > 1 and False else money_n(coating_amount)
    # Coating/nest amounts: nests already × qty for used; purchase amounts in nest are for qty
    # Fix coat: compute from nest used which is qty-scaled
    coat_total = money_n(coat_qty * coat_rate)  # coat_qty from used_m already ×qty in nests... 
    # Actually used_m in nests is qty-scaled; coat_qty used ms_used_m from nests → already × qty
    coat_total = money_n(coat_qty * coat_rate)
    hw_total = money_n(hw_amount * qty)
    selling_parts = {
        "iron": money_n(ms_purchase),
        "aluminium": money_n(al_purchase),
        "coating": coat_total,
        "hardware": hw_total,
        "fabricationInstall": fab_amount,
    }
    selling_total = money_n(sum(selling_parts.values()))
    selling_per_sft = money_n(selling_total / (area_sft * qty)) if area_sft * qty > 0 else None

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
        "louverSectionId": louver_sec.get("sectionId"),
        "supportSectionId": support_sec.get("sectionId"),
        "frameFaceMm": face,
        "bays": bays,
        "leaves": leaves_meta,
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
        "cost": {
            "iron": money_n(ms_purchase),
            "aluminium": money_n(al_purchase),
            "coating": coat_total,
            "hardware": hw_total,
            "fabricationInstall": fab_amount,
            "total": money_n(ms_purchase + al_purchase + coat_total + hw_total + fab_amount),
        },
        "selling": selling_parts,
        "sellingTotal": selling_total,
        "sellingPerSft": selling_per_sft,
        "sellingBasis": selling_basis,
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


def gate_svg(cfg: Mapping[str, Any], quote: Mapping[str, Any] | None = None) -> str:
    """Elevation SVG for canvas + PDF."""
    q = quote or compute_gate(cfg)
    W = _f(q.get("widthMm") or cfg.get("widthMm"), 3962)
    H = _f(q.get("heightMm") or cfg.get("heightMm"), 2438)
    face = _f(q.get("frameFaceMm"), 75)
    left = _i(q.get("foldLeft"), 2)
    right = _i(q.get("foldRight"), 2)
    leaves = list(q.get("leaves") or [])
    vb_w, vb_h = 720.0, 480.0
    pad = 40.0
    title_h = 36.0
    max_w = vb_w - pad * 2
    max_h = vb_h - pad * 2 - title_h
    scale = min(max_w / max(W, 1.0), max_h / max(H, 1.0))
    dw, dh = W * scale, H * scale
    x0 = (vb_w - dw) / 2.0
    y0 = title_h + (max_h - dh) / 2.0 + pad / 2.0

    def sx(mm: float) -> float:
        return x0 + mm * scale

    def sy(mm: float) -> float:
        return y0 + mm * scale

    bay = _s(q.get("bayType"), "folding_privacy").replace("_", " ").title()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:g} {vb_h:g}" '
        f'data-model-system="gate" data-bay-type="{escape(_s(q.get("bayType")))}" role="img">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{pad:g}" y="24" font-family="Arial" font-size="16" font-weight="700" fill="#1f2937">'
        f'{escape(bay)}</text>',
        f'<text x="{vb_w - pad:g}" y="24" font-family="Arial" font-size="12" text-anchor="end" fill="#475569">'
        f'{mm_n(W)} × {mm_n(H)} mm · {left}+{right}</text>',
        f'<rect x="{x0:g}" y="{y0:g}" width="{dw:g}" height="{dh:g}" fill="#f8fafc" stroke="#111827" stroke-width="2"/>',
    ]
    # Wall posts
    wp = _i(q.get("wallPostCount"), 2)
    if wp >= 1:
        parts.append(
            f'<rect x="{x0:g}" y="{y0:g}" width="{face*scale:g}" height="{dh:g}" '
            f'fill="#94a3b8" stroke="#0f172a" stroke-width="1" data-role="wall_post"/>'
        )
    if wp >= 2:
        parts.append(
            f'<rect x="{x0 + dw - face*scale:g}" y="{y0:g}" width="{face*scale:g}" height="{dh:g}" '
            f'fill="#94a3b8" stroke="#0f172a" stroke-width="1" data-role="wall_post"/>'
        )

    # Leaves
    n = len(leaves) or (left + right)
    if n > 0:
        inner_x = face if wp else 0.0
        inner_w = W - (2 * face if wp >= 2 else 0.0)
        leaf_w = inner_w / n
        for i, leaf in enumerate(leaves or [{"leafId": f"L{i+1}"} for i in range(n)]):
            lx = inner_x + i * leaf_w
            parts.append(
                f'<rect x="{sx(lx):g}" y="{sy(0):g}" width="{leaf_w*scale:g}" height="{dh:g}" '
                f'fill="none" stroke="#334155" stroke-width="1.4" data-leaf="{escape(str(leaf.get("leafId") or i+1))}"/>'
            )
            # Vertical louvers preview
            clear_x = lx + face
            clear_w = max(leaf_w - 2 * face, 0)
            clear_y = face
            clear_h = max(H - 2 * face, 0)
            fill = leaf.get("fill") if isinstance(leaf.get("fill"), Mapping) else {}
            bc = int(fill.get("bladeCount") or q.get("bladeCountPerLeaf") or 0)
            gap = _f(fill.get("gapMm") or q.get("louverGapMm"), 25)
            bf = _f(fill.get("bladeFaceMm"), 25)
            margin = _f(fill.get("marginMm"))
            cursor = clear_x + margin
            for b in range(bc):
                parts.append(
                    f'<rect x="{sx(cursor):g}" y="{sy(clear_y):g}" width="{max(bf*scale, 0.8):g}" '
                    f'height="{clear_h*scale:g}" fill="#cbd5e1" stroke="#1e293b" stroke-width="0.6" '
                    f'data-role="louver_blade"/>'
                )
                cursor += bf + gap
            # Centre open mark
            if i == left - 1 and left and right:
                mx = sx(lx + leaf_w)
                parts.append(
                    f'<line x1="{mx:g}" y1="{y0:g}" x2="{mx:g}" y2="{y0+dh:g}" '
                    f'stroke="#b91c1c" stroke-width="1.5" stroke-dasharray="4 3" data-role="centre_meet"/>'
                )

    parts.append(
        f'<text x="{pad:g}" y="{vb_h - 14:g}" font-family="Arial" font-size="11" fill="#475569">'
        f'Blades/leaf={q.get("bladeCountPerLeaf")} · gap={q.get("louverGapMm")} mm · '
        f'MS bars={((q.get("bars") or {}).get("ms"))} · Al bars={((q.get("bars") or {}).get("aluminium"))} · '
        f'Fe {((q.get("weight") or {}).get("ironKg"))} kg · Al {((q.get("weight") or {}).get("aluminiumKg"))} kg'
        f'</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def format_gate_description(quote: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> str:
    return _s(quote.get("description"), "Gate / privacy screen")
