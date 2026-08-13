"""ReportLab railing elevation — customer PDF without Cairo / huge SVG.

Same geometry rules as ``railing_svg``: continuous bottom rail (no pillars),
spigot/block pillars 100 mm from glass edges, staircase side view.
"""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory.railing_engine import (
    ANCHOR_INSET_MM,
    DEFAULT_GLASS_GAP_MM,
    GLASS_EDGE_INSET_MM,
    MM_PER_FT,
    PILLAR_EDGE_MM,
    _parse_section_mm,
    _pillar_positions_along,
    _spigot_dims,
    compute_railing,
    continuous_rail_anchor_count,
    continuous_rail_anchor_spacing_mm,
    ensure_railing_dims,
    normalize_bottom_kind,
    railing_mount_label,
    side_stud_column_xs,
    side_stud_row_offsets_mm,
)


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


def _section_face_mm(raw: Any, default: float = 40.0) -> float:
    """Elevation face height from sizes like ``100×45`` (use the larger dim)."""
    s = str(raw or "").replace("×", "x").replace("*", "x").replace("Ø", " ").replace("ø", " ")
    nums: list[float] = []
    cur = ""
    for ch in s:
        if ch.isdigit() or ch == ".":
            cur += ch
        elif cur:
            try:
                nums.append(float(cur))
            except ValueError:
                pass
            cur = ""
    if cur:
        try:
            nums.append(float(cur))
        except ValueError:
            pass
    if not nums:
        return default
    face = max(nums) if len(nums) >= 2 else nums[0]
    return face if face >= 8.0 else default


def _cfg_and_quote(line: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    cfg = opts.get("railing") if isinstance(opts, Mapping) else None
    cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
    try:
        cfg = ensure_railing_dims(
            cfg,
            width=float(line.get("width") or 0) or None,
            height=float(line.get("height") or 0) or None,
        )
    except Exception:
        pass
    q = opts.get("railingQuote") if isinstance(opts, Mapping) else None
    if not isinstance(q, Mapping):
        q = line.get("railing") if isinstance(line.get("railing"), Mapping) else {}
    need = not isinstance(q, Mapping) or not q
    if not need:
        try:
            from WEOS.factory.railing_engine import railing_quote_matches_cfg

            if not railing_quote_matches_cfg(q, cfg):
                need = True
        except Exception:
            if _f(q.get("lengthMm")) <= 1.0 and _f(cfg.get("lengthMm") or line.get("width")) > 1.0:
                need = True
    if need and cfg:
        try:
            q = compute_railing(cfg)
        except Exception:
            q = q if isinstance(q, Mapping) else {}
    return cfg, dict(q) if isinstance(q, Mapping) else {}


def draw_railing_elevation(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    """Draw railing 2D into a PDF cell. Always draws geometry — never a text placeholder."""
    cfg, q = _cfg_and_quote(line)
    g = q.get("geometry") if isinstance(q.get("geometry"), Mapping) else {}
    shape = str(g.get("shape") or q.get("shape") or cfg.get("shape") or "straight").lower()
    try:
        c.setDash()
    except Exception:
        pass
    c.setFillColorRGB(1, 1, 1)
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.40)
    c.rect(x, y, box_w, box_h, fill=1, stroke=1)

    if shape == "staircase":
        return _draw_staircase(c, cfg, q, g, x, y, box_w, box_h)
    if shape in ("l", "u", "polyline", "poly"):
        return _draw_multi_span(c, cfg, q, g, x, y, box_w, box_h)
    if shape == "arch":
        return _draw_arch(c, cfg, q, g, x, y, box_w, box_h)
    return _draw_straight(c, cfg, q, g, x, y, box_w, box_h)


def _draw_straight(c, cfg, q, g, x, y, box_w, box_h) -> bool:
    L = _f(g.get("lengthMm") or q.get("lengthMm") or cfg.get("lengthMm"))
    Hgt = _f(g.get("heightMm") or q.get("heightMm") or q.get("glassHeightMm") or cfg.get("heightMm"))
    if L <= 1.0:
        L = max(_f(cfg.get("lengthMm")), 1000.0)
    if Hgt <= 1.0:
        Hgt = max(_f(cfg.get("heightMm")), 900.0)
    segs = list(g.get("segments") or [])
    widths = []
    if segs and segs[0].get("panelWidthsMm"):
        widths = [float(w) for w in segs[0]["panelWidthsMm"] if float(w) > 0]
    else:
        widths = [float(w) for w in (q.get("panelWidthsMm") or []) if float(w) > 0]
    gap = _f(g.get("gap") or q.get("gapMm"), DEFAULT_GLASS_GAP_MM)
    wall_gap = _f(g.get("wallGap") or q.get("wallGapMm"), DEFAULT_GLASS_GAP_MM)
    wall_left = bool(g.get("wallStart", True) if "wallStart" in g else cfg.get("wallStart", True))
    wall_right = bool(g.get("wallEnd", True) if "wallEnd" in g else cfg.get("wallEnd", True))
    if not widths:
        n = max(_i(q.get("panelCount") or cfg.get("panels"), 3), 1)
        usable = max(L - (wall_gap if wall_left else 0) - (wall_gap if wall_right else 0) - gap * max(n - 1, 0), 1.0)
        widths = [usable / n] * n

    bottom_kind = normalize_bottom_kind(q.get("bottomKind") or cfg.get("bottomKind"))
    continuous = bottom_kind == "continuous" or bool(q.get("continuousRail") or cfg.get("continuousRail"))
    mount = str(q.get("mountType") or cfg.get("mountType") or "top_mount")
    side_studs = mount == "side_mount" or bottom_kind == "studs"
    spigots_on = (not side_studs) and (not continuous)
    br_sz = str(q.get("bottomSize") or cfg.get("bottomSize") or "").strip()
    hr_sz = str(q.get("handrailSize") or cfg.get("handrailSize") or "").strip()
    rail_h = _section_face_mm(br_sz, 40.0) if continuous else _f(g.get("railH"), 40.0)
    if continuous:
        rail_h = max(min(rail_h, Hgt * 0.22), 28.0)
    hand_on = bool(g.get("handrail") if "handrail" in g else (q.get("handrail") or cfg.get("handrail")))
    hand_h = _section_face_mm(hr_sz, 24.0) if hand_on else 0.0
    if hand_on:
        hand_h = max(min(hand_h, Hgt * 0.14), 16.0)
    spigot = _spigot_dims(section_mm=_parse_section_mm(br_sz or q.get("pillarSize") or cfg.get("pillarSize"), 50.0))
    overlap = _f(q.get("beamOverlapMm") or cfg.get("beamOverlapMm")) if side_studs else 0.0

    extra_below = (overlap + 40.0) if overlap > 0 else 0.0
    m_left, m_right, m_bottom, m_top = 22.0, 18.0, 22.0, 14.0
    draw_w = max(box_w - m_left - m_right, 16.0)
    draw_h = max(box_h - m_bottom - m_top, 16.0)
    world_h = Hgt + extra_below
    scale = min(draw_w / max(L, 1.0), draw_h / max(world_h, 1.0))
    ox = x + m_left + (draw_w - L * scale) / 2.0
    oy = y + m_bottom + extra_below * scale + (draw_h - world_h * scale) / 2.0

    def px(mx: float) -> float:
        return ox + mx * scale

    def py(my: float) -> float:
        return oy + my * scale

    stroke = (0.07, 0.07, 0.08)
    glass_fill = (0.90, 0.94, 0.97)
    dim = (0.55, 0.12, 0.10)
    lw = max(0.55, min(0.80, 0.55 * (220.0 / max(box_w, 1.0))))

    # Walls
    if wall_left:
        c.setFillColorRGB(0.87, 0.90, 0.92)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw * 0.85)
        c.rect(px(-36), py(0), 28 * scale, Hgt * scale, fill=1, stroke=1)
    if wall_right:
        c.setFillColorRGB(0.87, 0.90, 0.92)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw * 0.85)
        c.rect(px(L + 8), py(0), 28 * scale, Hgt * scale, fill=1, stroke=1)

    if side_studs and overlap > 0:
        slab_h = min(max(overlap * 0.55, 90.0), 160.0)
        c.setFillColorRGB(0.92, 0.93, 0.94)
        c.setStrokeColorRGB(0.42, 0.45, 0.50)
        c.setLineWidth(lw * 0.7)
        c.rect(px(-20), py(-slab_h), (L + 40) * scale, slab_h * scale, fill=1, stroke=1)

    if continuous:
        c.setFillColorRGB(0.94, 0.95, 0.96)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        c.rect(px(0), py(0), L * scale, rail_h * scale, fill=1, stroke=1)
        # Simple anchor ticks: 100 mm inset, then every 2 ft (or cfg spacing)
        spacing = continuous_rail_anchor_spacing_mm(cfg) or (2.0 * MM_PER_FT)
        n_anc = continuous_rail_anchor_count(L, spacing)
        if n_anc > 0:
            usable = max(L - 2.0 * ANCHOR_INSET_MM, 0.0)
            xs = [L / 2.0] if n_anc == 1 else (
                [ANCHOR_INSET_MM + i * (usable / max(n_anc - 1, 1)) for i in range(n_anc)]
                if usable > 0 else [L * (i + 1) / (n_anc + 1) for i in range(n_anc)]
            )
            c.setFillColorRGB(*stroke)
            r = max(1.15, 3.2 * scale)
            for ax in xs:
                c.circle(px(ax), py(rail_h * 0.45), r, fill=1, stroke=0)

    glass_y0 = -overlap if (side_studs and overlap > 0) else (rail_h if continuous else (float(spigot["glass_y0"]) if spigots_on else rail_h))
    glass_y1 = Hgt - hand_h
    n_block = 0 if continuous else _i(cfg.get("blocksPerGlass") or (segs[0].get("blocksPerGlass") if segs else 0), 0)
    n_studs = 0 if continuous else _i(cfg.get("studsPerGlass") or q.get("studsPerGlass"), 0)
    if side_studs and n_studs <= 0:
        n_studs = max(_i(cfg.get("studsPerGlass") or cfg.get("blocksPerGlass"), 2), 0)
    n_sup = n_studs if side_studs else n_block
    panel_start = _i((segs[0] if segs else {}).get("panelStartIndex"), 1)

    cursor = wall_gap if wall_left else 0.0
    for i, w in enumerate(widths):
        gx0, gx1 = cursor, cursor + w
        gh = max(glass_y1 - glass_y0, 1.0)
        c.setFillColorRGB(*glass_fill)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        c.rect(px(gx0), py(glass_y0), (gx1 - gx0) * scale, gh * scale, fill=1, stroke=1)
        c.setFillColorRGB(0.09, 0.23, 0.39)
        c.setFont("Helvetica-Bold", max(5.5, min(8.0, 7.0 * scale * 12)))
        c.drawCentredString(px((gx0 + gx1) / 2.0), py((glass_y0 + glass_y1) / 2.0) - 2.5, f"G{panel_start + i}")
        if spigots_on and n_sup:
            for bx in _pillar_positions_along(w, n_sup, edge_mm=PILLAR_EDGE_MM):
                _draw_spigot_pdf(c, px, py, scale, gx0 + bx, 0.0, spigot, stroke, lw)
        elif side_studs and n_sup:
            xl, xr = side_stud_column_xs(gx0, gx1)
            row_ys = side_stud_row_offsets_mm(n_sup, overlap_mm=overlap, glass_height_from_bottom_mm=max(glass_y1 - glass_y0, 1.0))
            stud_sz = _f(q.get("studSizeMm") or cfg.get("studSizeMm"), 38.0)
            drawn = 0
            for y_off in row_ys:
                for cx in (xl, xr):
                    if drawn >= n_sup:
                        break
                    _draw_stud_pdf(c, px(cx), py(glass_y0 + y_off), stud_sz * scale, stroke, lw)
                    drawn += 1
                if drawn >= n_sup:
                    break
        cursor = gx1 + gap

    if hand_h > 0:
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        c.rect(px(0), py(Hgt - hand_h), L * scale, hand_h * scale, fill=0, stroke=1)

    # Overall dims (slim)
    c.setStrokeColorRGB(*dim)
    c.setFillColorRGB(*dim)
    c.setLineWidth(0.45)
    c.setFont("Helvetica", 5.5)
    c.line(px(0), py(-10 / max(scale, 1e-6)), px(L), py(-10 / max(scale, 1e-6)))
    c.drawCentredString(px(L / 2.0), py(-18 / max(scale, 1e-6)), f"{L:.0f}×{Hgt:.0f}")
    mount_lbl = q.get("mountLabel") or railing_mount_label(q.get("mountType") or mount)
    c.setFillColorRGB(0.15, 0.15, 0.16)
    c.setFont("Helvetica", 6.0)
    title = f"Railing · {q.get('panelCount') or len(widths)} panels"
    if continuous:
        title += " · continuous"
    elif spigots_on:
        title += " · pillars"
    c.drawString(x + 4, y + box_h - 10, title[:48])
    return True


def _draw_spigot_pdf(c, px, py, scale, cx_mm, floor_y, dims, stroke, lw) -> None:
    plate_w = float(dims["plate_w"])
    plate_h = float(dims["plate_h"])
    post_w = float(dims["post_w"])
    post_h = float(dims["post_h"])
    slot_w = float(dims["slot_w"])
    slot_d = float(dims["slot_d"])
    c.setFillColorRGB(0.95, 0.95, 0.96)
    c.setStrokeColorRGB(*stroke)
    c.setLineWidth(lw)
    c.rect(px(cx_mm - plate_w / 2.0), py(floor_y), plate_w * scale, plate_h * scale, fill=1, stroke=1)
    inset_x = max(plate_w * 0.18, 8.0)
    inset_y = max(plate_h * 0.22, 6.0)
    r_hole = max(min(plate_w, plate_h) * 0.10, 3.4) * scale
    for sx in (-1.0, 1.0):
        for sy in (inset_y, plate_h - inset_y):
            c.setFillColorRGB(1, 1, 1)
            c.circle(px(cx_mm + sx * (plate_w / 2.0 - inset_x)), py(floor_y + sy), r_hole, fill=1, stroke=1)
    post_y0 = floor_y + plate_h
    leg_w = max((post_w - slot_w) / 2.0, 6.0)
    c.setFillColorRGB(0.93, 0.93, 0.94)
    c.rect(px(cx_mm - post_w / 2.0), py(post_y0), leg_w * scale, post_h * scale, fill=1, stroke=1)
    c.rect(px(cx_mm + post_w / 2.0 - leg_w), py(post_y0), leg_w * scale, post_h * scale, fill=1, stroke=1)
    web_h = max(post_h - slot_d, 8.0)
    c.rect(px(cx_mm - post_w / 2.0), py(post_y0), post_w * scale, web_h * scale, fill=1, stroke=1)


def _draw_stud_pdf(c, cx, cy, size_px, stroke, lw) -> None:
    plate = max(min(size_px * 0.55, 10.0), 3.6)
    c.setFillColorRGB(0.93, 0.93, 0.93)
    c.setStrokeColorRGB(*stroke)
    c.setLineWidth(lw)
    c.circle(cx, cy, plate / 2.0, fill=1, stroke=1)
    c.circle(cx, cy, max(plate * 0.22, 0.9), fill=0, stroke=1)


def _draw_multi_span(c, cfg, q, g, x, y, box_w, box_h) -> bool:
    segs = list(g.get("segments") or q.get("segments") or [])
    if not segs:
        return _draw_straight(c, cfg, q, g, x, y, box_w, box_h)
    # Draw the longest span elevation (PDF column is narrow).
    best = max(segs, key=lambda s: _f(s.get("lengthMm")))
    fake_g = {
        **dict(g),
        "shape": "straight",
        "lengthMm": _f(best.get("lengthMm") or q.get("lengthMm")),
        "segments": [best],
        "wallStart": bool(best.get("wallStart")),
        "wallEnd": bool(best.get("wallEnd")),
    }
    fake_q = {**dict(q), "shape": "straight", "panelWidthsMm": best.get("panelWidthsMm") or q.get("panelWidthsMm")}
    ok = _draw_straight(c, cfg, fake_q, fake_g, x, y, box_w, box_h)
    c.setFillColorRGB(0.20, 0.20, 0.22)
    c.setFont("Helvetica", 5.5)
    lab = str(best.get("label") or q.get("shape") or "span")
    c.drawRightString(x + box_w - 4, y + box_h - 10, str(lab)[:18])
    return ok


def _draw_arch(c, cfg, q, g, x, y, box_w, box_h) -> bool:
    L = max(_f(g.get("lengthMm") or q.get("lengthMm")), 1000.0)
    Hgt = max(_f(g.get("heightMm") or q.get("heightMm") or q.get("glassHeightMm")), 900.0)
    m_left, m_right, m_bottom, m_top = 18.0, 14.0, 16.0, 12.0
    draw_w = max(box_w - m_left - m_right, 16.0)
    draw_h = max(box_h - m_bottom - m_top, 16.0)
    scale = min(draw_w / L, draw_h / Hgt)
    ox = x + m_left + (draw_w - L * scale) / 2.0
    oy = y + m_bottom + (draw_h - Hgt * scale) / 2.0
    stroke = (0.07, 0.07, 0.08)
    c.setStrokeColorRGB(*stroke)
    c.setLineWidth(0.70)
    path = c.beginPath()
    path.moveTo(ox, oy)
    path.curveTo(ox + L * scale * 0.15, oy + Hgt * scale * 0.15, ox + L * scale * 0.35, oy + Hgt * scale, ox + L * scale * 0.5, oy + Hgt * scale)
    path.curveTo(ox + L * scale * 0.65, oy + Hgt * scale, ox + L * scale * 0.85, oy + Hgt * scale * 0.15, ox + L * scale, oy)
    c.drawPath(path, fill=0, stroke=1)
    c.setFillColorRGB(0.90, 0.94, 0.97)
    c.setLineWidth(0.55)
    c.rect(ox + 8 * scale, oy, (L - 16) * scale, Hgt * 0.55 * scale, fill=1, stroke=1)
    return True


def _draw_staircase(c, cfg, q, g, x, y, box_w, box_h) -> bool:
    steps = max(_i(g.get("stairSteps") or cfg.get("stairSteps"), 12), 1)
    rise = _f(g.get("stairRiseMm") or cfg.get("stairRiseMm"), 150.0)
    run = _f(g.get("stairRunMm") or cfg.get("stairRunMm"), 250.0)
    total_w = max(run * steps, 1.0)
    total_h = max(rise * steps, 1.0)
    glass_h = _f(g.get("glassHeightMm") or q.get("glassHeightMm") or q.get("heightMm") or cfg.get("heightMm"), 900.0)
    guard = min(max(glass_h, 600.0), 1400.0) if glass_h > 50 else 900.0
    stair_sm = str(q.get("stairMountType") or cfg.get("stairMountType") or "").lower()
    side_studs = "side" in stair_sm or str(q.get("mountType") or "").lower() == "side_mount"
    overlap = _f(q.get("beamOverlapMm") or cfg.get("beamOverlapMm")) if side_studs else 0.0
    extra_below = overlap if overlap > 0 else 0.0
    world_w = total_w
    world_h = total_h + guard + extra_below
    m_left, m_right, m_bottom, m_top = 14.0, 12.0, 14.0, 12.0
    draw_w = max(box_w - m_left - m_right, 16.0)
    draw_h = max(box_h - m_bottom - m_top, 16.0)
    scale = min(draw_w / world_w, draw_h / world_h)
    ox = x + m_left + (draw_w - world_w * scale) / 2.0
    oy = y + m_bottom + extra_below * scale + (draw_h - world_h * scale) / 2.0

    def px(mx: float) -> float:
        return ox + mx * scale

    def py(my: float) -> float:
        return oy + my * scale

    stroke = (0.07, 0.07, 0.08)
    glass_fill = (0.86, 0.92, 0.96)
    lw = 0.62
    c.setStrokeColorRGB(*stroke)
    c.setLineWidth(lw * 1.15)
    path = c.beginPath()
    path.moveTo(px(0), py(0))
    sx = sy = 0.0
    for _ in range(steps):
        sx += run
        path.lineTo(px(sx), py(sy))
        sy += rise
        path.lineTo(px(sx), py(sy))
    c.drawPath(path, fill=0, stroke=1)

    def nosing_y(xh: float) -> float:
        return (rise / run) * xh if run > 0 else 0.0

    panels = list(g.get("glassPanels") or g.get("panels") or q.get("glassPanels") or [])
    if not panels:
        n = max(_i(q.get("panelCount") or cfg.get("panels"), 3), 1)
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
            continue
        x0 = _f(panel.get("panelStartHorizontalPosition"))
        x1 = _f(panel.get("panelEndHorizontalPosition"))
        if x1 <= x0:
            continue
        hl = _f(panel.get("leftGlassHeight"), guard)
        hr = _f(panel.get("rightGlassHeight"), guard)
        y0 = nosing_y(x0)
        y1 = nosing_y(x1)
        y0b = y0 - overlap if overlap > 0 else y0
        y1b = y1 - overlap if overlap > 0 else y1
        pth = c.beginPath()
        pth.moveTo(px(x0), py(y0b))
        pth.lineTo(px(x1), py(y1b))
        pth.lineTo(px(x1), py(y1 + hr))
        pth.lineTo(px(x0), py(y0 + hl))
        pth.close()
        c.setFillColorRGB(*glass_fill)
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
        c.drawPath(pth, fill=1, stroke=1)

    # Slim handrail along slope top
    c.setStrokeColorRGB(*stroke)
    c.setLineWidth(lw)
    c.line(px(0), py(guard), px(total_w), py(total_h + guard))
    c.setFillColorRGB(0.15, 0.15, 0.16)
    c.setFont("Helvetica", 6.0)
    c.drawString(x + 4, y + box_h - 10, f"Staircase · {steps} steps")
    return True
