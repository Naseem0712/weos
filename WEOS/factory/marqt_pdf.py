"""MAR-QT-style customer quotation PDF — drawings with W/H callouts + detail specs."""

from __future__ import annotations

import io
import logging
from datetime import date
from typing import Any, Mapping, Sequence

_log = logging.getLogger("weos.marqt_pdf")


def _rgb(color: Sequence[float] | None, fallback=(0.12, 0.22, 0.38)):
    if not color or len(color) < 3:
        return fallback
    return float(color[0]), float(color[1]), float(color[2])


def _money(v: Any) -> str:
    from WEOS.factory.pdf_fonts import money_text

    return money_text(v)


def _set_font(c, size: float, *, bold: bool = False) -> None:
    from WEOS.factory.pdf_fonts import set_font

    set_font(c, size, bold=bold)


def _area_sqft(w: float, h: float) -> float:
    return round((w * h) / 1_000_000.0 * 10.7639, 2)


# Uniform page margin (all four sides) used across every page.
MARGIN = 40


def _fit_font_size(c, text: str, max_width: float, base: float, *, bold: bool = False, minimum: float = 8.0) -> float:
    """Largest font size ≤ base whose ``text`` fits within ``max_width`` (never < minimum)."""
    font = "Helvetica-Bold" if bold else "Helvetica"
    size = float(base)
    if not text:
        return size
    while size > minimum and c.stringWidth(text, font, size) > max_width:
        size -= 0.5
    return size


def _draw_fit(c, text: str, x: float, y: float, max_width: float, base: float, *, bold: bool = False, minimum: float = 8.0) -> None:
    """Draw ``text`` at (x,y), auto-shrinking the font so it never overflows ``max_width``."""
    size = _fit_font_size(c, text, max_width, base, bold=bold, minimum=minimum)
    _set_font(c, size, bold=bold)
    c.drawString(x, y, text)


def draw_window_elevation(c, x, y, box_w, box_h, width_mm: float, height_mm: float, *, track_count: int = 2):
    """Fallback schematic only — prefer draw_line_elevation (canvas geometry SVG)."""
    # Outer frame — outline drafting style
    c.setStrokeColorRGB(0.12, 0.12, 0.14)
    c.setLineWidth(0.9)
    c.rect(x, y, box_w, box_h, fill=0, stroke=1)
    c.setLineWidth(0.55)
    c.rect(x + 3, y + 3, box_w - 6, box_h - 6, fill=0, stroke=1)

    # Inner glass panes
    pad = 6
    panes = max(int(track_count or 2), 1)
    pane_w = (box_w - pad * (panes + 1)) / panes
    for i in range(panes):
        px = x + pad + i * (pane_w + pad)
        c.setFillColorRGB(0.78, 0.88, 0.95)
        c.setStrokeColorRGB(0.30, 0.48, 0.65)
        c.setLineWidth(0.55)
        c.rect(px, y + pad, pane_w, box_h - 2 * pad, fill=1, stroke=1)

    c.setStrokeColorRGB(0.55, 0.15, 0.12)
    c.setFillColorRGB(0.55, 0.15, 0.12)
    c.setLineWidth(0.55)
    dim_y = y - 12
    c.line(x, dim_y, x + box_w, dim_y)
    c.line(x, dim_y - 3, x, dim_y + 3)
    c.line(x + box_w, dim_y - 3, x + box_w, dim_y + 3)
    c.setFont("Helvetica", 6)
    c.drawCentredString(x + box_w / 2, dim_y - 10, f"W = {width_mm:g} mm")

    dim_x = x + box_w + 10
    c.line(dim_x, y, dim_x, y + box_h)
    c.line(dim_x - 3, y, dim_x + 3, y)
    c.line(dim_x - 3, y + box_h, dim_x + 3, y + box_h)
    c.saveState()
    c.translate(dim_x + 8, y + box_h / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, f"H = {height_mm:g} mm")
    c.restoreState()


def _line_is_railing(line: Mapping[str, Any]) -> bool:
    """Detect railing designer lines even when product id varies."""
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    if isinstance(opts, Mapping) and isinstance(opts.get("railing"), Mapping):
        return True
    if str(line.get("status") or "").lower() == "railing":
        return True
    if isinstance(line.get("railing"), Mapping):
        return True
    pid = str(line.get("product") or "").lower()
    return pid in ("railing", "railings_stub", "glass_railings") or "railing" in pid


def _railing_cfg_and_quote(line: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    cfg = opts.get("railing") if isinstance(opts, Mapping) else None
    cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
    q = opts.get("railingQuote") if isinstance(opts, Mapping) else None
    if not isinstance(q, Mapping):
        q = line.get("railing") if isinstance(line.get("railing"), Mapping) else {}
    if not q and cfg:
        try:
            from WEOS.factory.railing_engine import compute_railing

            q = compute_railing(cfg)
        except Exception:
            q = {}
    return cfg, dict(q) if isinstance(q, Mapping) else {}


def draw_line_elevation(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    """Draw the same geometry-engine elevation used by the live canvas into the design column.

    Prefers crisp ReportLab vector drawing; falls back to SVG→PNG, then schematic stub.
    Returns True when the real elevation was drawn.
    """
    from reportlab.lib.utils import ImageReader

    from WEOS.factory.image_engine import svg_to_png_bytes, svg_to_rl_drawing
    from WEOS.factory.svg_export import elevation_svg_for_line

    w = float(line.get("width") or 0)
    h = float(line.get("height") or 0)

    # Railing lines carry their own 2D designer geometry — never fall through to
    # window elevation (that produced blank/wrong "window" drawings on quotes).
    if _line_is_railing(line):
        rail_cfg, rail_q = _railing_cfg_and_quote(line)
        svg = None
        try:
            from WEOS.factory.railing_engine import railing_svg

            svg = railing_svg(rail_cfg or {}, quote=rail_q or None)
        except Exception:
            _log.exception("railing_svg failed; trying stored preview")
            prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
            svg = (prev or {}).get("svg")

        if svg:
            try:
                drawing = svg_to_rl_drawing(str(svg))
                if drawing is not None and getattr(drawing, "width", 0) and getattr(drawing, "height", 0):
                    from reportlab.graphics import renderPDF

                    dwid, dhei = float(drawing.width), float(drawing.height)
                    scale = min(box_w / dwid, box_h / dhei)
                    dw, dh = dwid * scale, dhei * scale
                    drawing.scale(scale, scale)
                    drawing.width, drawing.height = dw, dh
                    renderPDF.draw(drawing, c, x + (box_w - dw) / 2.0, y + (box_h - dh))
                    return True
            except Exception:
                _log.exception("railing vector embed failed; trying PNG")

            png = svg_to_png_bytes(str(svg), scale=2.0)
            if png:
                img = ImageReader(io.BytesIO(png))
                iw, ih = img.getSize()
                if iw > 0 and ih > 0:
                    scale = min(box_w / float(iw), box_h / float(ih))
                    dw, dh = iw * scale, ih * scale
                    c.drawImage(img, x + (box_w - dw) / 2.0, y + (box_h - dh), width=dw, height=dh, mask="auto")
                    return True

        # Last resort: labelled box so the design column is never a window stub.
        c.setStrokeColorRGB(0.35, 0.35, 0.35)
        c.setFillColorRGB(0.96, 0.96, 0.97)
        c.rect(x + 4, y + 4, box_w - 8, box_h - 8, stroke=1, fill=1)
        c.setFillColorRGB(0.2, 0.2, 0.2)
        _set_font(c, 8, bold=True)
        c.drawCentredString(x + box_w / 2, y + box_h / 2 + 6, "Railing design")
        _set_font(c, 7)
        shape = (rail_q or {}).get("shape") or (rail_cfg or {}).get("shape") or "—"
        c.drawCentredString(x + box_w / 2, y + box_h / 2 - 8, f"{shape} · {w:g}×{h:g} mm")
        return True

    # The live canvas is rendered by svg_export.render_svg_string. To guarantee the
    # PDF matches the canvas 1:1 (same geometry, labels, hinges, mullions, arrows,
    # grid cell labels, fold L/R leaves), embed that SAME SVG as a VECTOR drawing.
    svg = elevation_svg_for_line(line, style="pdf")
    if not svg:
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")

    if svg:
        # 1) Vector (crisp, identical to canvas) — preferred.
        try:
            drawing = svg_to_rl_drawing(str(svg))
            if drawing is not None and getattr(drawing, "width", 0) and getattr(drawing, "height", 0):
                from reportlab.graphics import renderPDF

                dwid, dhei = float(drawing.width), float(drawing.height)
                scale = min(box_w / dwid, box_h / dhei)
                dw, dh = dwid * scale, dhei * scale
                drawing.scale(scale, scale)
                drawing.width, drawing.height = dw, dh
                renderPDF.draw(drawing, c, x + (box_w - dw) / 2.0, y + (box_h - dh))
                return True
        except Exception:
            _log.exception("svg vector embed failed; trying raster/model fallback")

        # 2) Raster fallback (still the canvas SVG, just rasterised).
        png = svg_to_png_bytes(str(svg), scale=2.0)
        if png:
            img = ImageReader(io.BytesIO(png))
            iw, ih = img.getSize()
            if iw > 0 and ih > 0:
                scale = min(box_w / float(iw), box_h / float(ih))
                dw, dh = iw * scale, ih * scale
                c.drawImage(img, x + (box_w - dw) / 2.0, y + (box_h - dh), width=dw, height=dh, mask="auto")
                return True

    # 3) ReportLab model re-draw (only if the SVG path is unavailable).
    try:
        from WEOS.factory.elevation_pdf import draw_line_model_elevation

        if draw_line_model_elevation(c, line, x, y, box_w, box_h):
            return True
    except Exception:
        _log.exception("reportlab model elevation fallback failed")

    layout = line.get("layout") if isinstance(line.get("layout"), Mapping) else {}
    panels = list((layout or {}).get("panels") or [])
    track_count = max(len(panels), 2)
    draw_window_elevation(c, x, y, box_w, box_h, w, h, track_count=track_count)
    return False


def _spec_lines(line: Mapping[str, Any]) -> list[str]:
    opts = line.get("options") or {}
    layout = line.get("layout") if isinstance(line.get("layout"), Mapping) else {}
    w = float((layout or {}).get("widthMm") or line.get("width") or 0)
    h = float((layout or {}).get("heightMm") or line.get("height") or 0)
    weight = (line.get("weight") or {}).get("totalKg")
    section = line.get("sectionSpecs") or {}
    if not section and line.get("sectionSeries"):
        try:
            from WEOS.factory.section_catalogue import specs_summary_for_series

            section = specs_summary_for_series(str(line.get("sectionSeries")))
        except Exception:
            section = {}

    # ── Railing lines: full BOM / materials detail block ─────────────────────
    if _line_is_railing(line):
        rail_cfg, q = _railing_cfg_and_quote(line)
        shape = q.get("shape") or (rail_cfg or {}).get("shape") or "straight"
        color_mode = (rail_cfg or {}).get("colorMode") or "global"
        sys_color = (rail_cfg or {}).get("systemColor") or ""
        glass_bits = [
            f"{q.get('glassThicknessMm') or (rail_cfg or {}).get('glassThicknessMm') or 12} mm",
            (rail_cfg or {}).get("glassType") or q.get("glassType") or "",
            (rail_cfg or {}).get("glassColour") or q.get("glassColour") or "",
        ]
        glass_bits = [str(b) for b in glass_bits if b]
        lines = [
            str(line.get("description") or line.get("displayName") or "Railing"),
            f"Type = {shape} · Mount = {q.get('mountType') or (rail_cfg or {}).get('mountType') or 'side_mount'}",
            f"Length = {q.get('lengthMm') or w:g} mm · Height = {q.get('heightMm') or h:g} mm",
            f"Panels = {q.get('panelCount') or 0} · Gap = {q.get('gapMm') or 12} mm",
            f"Glass = {' · '.join(glass_bits) or '—'}"
            f" · net {q.get('netGlassAreaSqFt') or q.get('glassAreaSqft') or 0} sft"
            f" · purchased {q.get('purchasedGlassAreaSqFt') or 0} sft"
            f" · wastage {q.get('wastagePercent') or 0}%",
            f"RFT = {q.get('lengthRft') or q.get('widthUnit') or 0}"
            f" · Pillars/blocks = {q.get('pillarCount') or 0}"
            f" · Anchors = {q.get('anchorCount') or 0}",
            f"Bends = {q.get('bendCount') or 0} · End caps = {q.get('endCapCount') or 0}"
            f" · Wall connectors = {q.get('wallConnectors') or 0}"
            f" · 180° = {q.get('connector180Count') or 0}",
            f"Color = {sys_color or 'per-part'} ({color_mode})"
            f" · Sale = {q.get('sellingPerUnit') or line.get('sellingRate') or 0}"
            f" / {str(q.get('saleUnit') or line.get('saleUnit') or 'rft').upper()}",
        ]
        sg = q.get("stairGeometry") if isinstance(q.get("stairGeometry"), Mapping) else {}
        if shape == "staircase" or sg:
            lines.append(
                f"Stairs = {sg.get('steps') or (rail_cfg or {}).get('stairSteps') or '—'} steps"
                f" · riser {sg.get('riserMm') or (rail_cfg or {}).get('stairRiseMm') or '—'} mm"
                f" · tread {sg.get('treadMm') or (rail_cfg or {}).get('stairRunMm') or '—'} mm"
                f" · floor {sg.get('floorHeightMm') or (rail_cfg or {}).get('floorHeightMm') or '—'} mm"
            )
            if sg.get("riseMismatch"):
                lines.append(str(sg.get("riseMismatchMessage") or "Rise mismatch vs floor height"))
        bom = q.get("bomDetails") or q.get("items") or []
        for it in bom[:14]:
            if not isinstance(it, Mapping):
                continue
            bits = [
                str(it.get("item") or it.get("label") or it.get("key") or "Item"),
                f"{it.get('qty')} {it.get('unit')}",
            ]
            if it.get("sizeMm"):
                bits.append(f"size {it['sizeMm']}")
            if it.get("color"):
                bits.append(f"color {it['color']}")
            if it.get("grade"):
                bits.append(f"grade {it['grade']}")
            if it.get("mountType"):
                bits.append(str(it["mountType"]))
            bits.append(f"@ {it.get('rate')} = {it.get('amount')}")
            lines.append("BOM: " + " · ".join(bits))
        return lines

    lines = [
        str(line.get("description") or line.get("displayName") or line.get("product") or "Window"),
        f"W = {w:g} mm; H = {h:g} mm",
        f"Area = {_area_sqft(w, h)} Sq.Ft.",
    ]
    panels = list((layout or {}).get("panels") or [])
    if panels:
        panel_bits = []
        for p in panels:
            pid = p.get("id") or "?"
            role = str(p.get("label") or p.get("role") or "").title()
            pw = p.get("widthMm")
            ph = p.get("heightMm")
            if pw is not None and ph is not None:
                panel_bits.append(f"{pid} {role} {pw:g}×{ph:g}")
        if panel_bits:
            lines.append("Panels: " + "; ".join(panel_bits))
    if weight is not None and float(weight or 0) > 0:
        lines.append(f"Weight = {weight} kg")
    # Prefer sized glass from calculate_line; fall back to option glass id string
    glass = line.get("glass")
    if not (isinstance(glass, list) and glass):
        glass = opts.get("glass") or glass
    if isinstance(glass, list) and glass:
        g0 = glass[0] if isinstance(glass[0], Mapping) else {}
        thick = g0.get("thicknessMm") or g0.get("thickness_mm")
        gname = g0.get("name") or ""
        if thick not in (None, ""):
            glz = f"Glazing = {thick:g} mm" if isinstance(thick, (int, float)) else f"Glazing = {thick} mm"
            if gname and "glass" not in str(gname).lower():
                glz += f" ({gname})"
            lines.append(glz)
        elif gname:
            lines.append(f"Glazing = {gname}")
    elif isinstance(glass, str) and glass.strip():
        lines.append(f"Glazing = {str(glass).replace('_', ' ')}")
    colour = opts.get("colour") or line.get("colour")
    pc_name = opts.get("powderCoatName") or line.get("powderCoatName")
    if pc_name and str(pc_name).strip():
        lines.append(f"Colour / Powder-coat = {pc_name}")
    elif colour:
        lines.append(f"Colour / Powder-coat = {str(colour).replace('_', ' ').title()}")
    if section.get("seriesTitle"):
        lines.append(f"Series = {section['seriesTitle']}")

    system = str((layout or {}).get("system") or opts.get("system") or "").lower()
    is_bifold = system in ("bifold", "fold", "fold_sliding", "fold_and_sliding") or (
        str((layout or {}).get("kind") or "") == "fold_and_sliding"
    )
    fl = (layout or {}).get("foldLeft")
    fr = (layout or {}).get("foldRight")
    if fl is None:
        fl = opts.get("foldLeft")
    if fr is None:
        fr = opts.get("foldRight")

    # Prefer resolved track from layout (mesh may have shifted 2→3) — never for fold
    tc = layout.get("trackCount") if layout else None
    if not is_bifold:
        if tc and section.get("track"):
            lines.append(f"Track / Outer = {section['track']} (using {float(tc):g}-track)")
        elif section.get("track"):
            lines.append(f"Track / Outer = {section['track']}")
        elif tc:
            lines.append(f"Track = {float(tc):g}-track")
    if section.get("sash"):
        lines.append(f"Sash = {section['sash']}")
    if section.get("interlock"):
        lines.append(f"Interlock = {section['interlock']}")
    handle = opts.get("handle")
    handle_name = opts.get("handleName") or line.get("handleName")
    if handle_name:
        lines.append(f"Handle = {handle_name}")
    elif handle:
        lines.append(f"Handle = {str(handle).replace('_', ' ').title()}")
    # Sell rate prints in the RATE column only — never duplicate here
    mesh_name = opts.get("meshName") or line.get("meshName")
    if not is_bifold and (layout.get("mesh") or (opts or {}).get("mesh")):
        lines.append(f"Mesh = {mesh_name or 'Yes'} (track {float(tc or 3):g}, 1 panel wide)")
    elif mesh_name:
        lines.append(f"Mesh = {mesh_name}")
    if system == "grid":
        lines.append("Type = Partition grid (per-cell fix/sliding/openable)")
    elif system == "casement":
        lines.append("Type = Casement / Openable")
    elif is_bifold:
        cfg = f"{int(fl or 0)}+{int(fr or 0)}"
        lines.append(f"Type = Fold & Sliding ({cfg})")
        lines.append(f"Fold configuration = {cfg} (left + right leaves)")

    # Section sizes used by geometry (Series Setup / line overrides)
    sizes = (layout or {}).get("sectionSizes") or opts.get("sectionSizes") or {}
    if isinstance(sizes, Mapping) and sizes:
        bits = []
        labels = (
            ("topRail", "Top"),
            ("bottomRail", "Bottom"),
            ("leftJamb", "Left jamb"),
            ("rightJamb", "Right jamb"),
            ("leafStile", "Leaf stile"),
        )
        for key, lab in labels:
            if sizes.get(key) is not None and str(sizes.get(key)).strip() != "":
                bits.append(f"{lab} {sizes[key]:g} mm" if isinstance(sizes[key], (int, float)) else f"{lab} {sizes[key]}")
        if bits:
            lines.append("Section sizes = " + " · ".join(bits))

    # Rich section details from Series Setup / catalogue (name, dims, weight, std length)
    detail_rows = list(line.get("sectionDetails") or [])
    if not detail_rows and isinstance(section.get("sections"), list):
        for sec in section.get("sections") or []:
            if not isinstance(sec, Mapping):
                continue
            detail_rows.append(
                {
                    "name": sec.get("name"),
                    "use": sec.get("usage") or sec.get("use"),
                    "wMm": sec.get("widthMm") or sec.get("wMm"),
                    "hMm": sec.get("sectionDepthMm") or sec.get("hMm"),
                    "wallMm": sec.get("wallThicknessMm") or sec.get("wallMm"),
                    "weightKgPerM": sec.get("weightKgPerM"),
                    "stdLengthMm": sec.get("stdLengthMm") or sec.get("standardLengthMm"),
                }
            )
    for sec in detail_rows[:12]:
        if not isinstance(sec, Mapping):
            continue
        name = sec.get("name") or sec.get("use") or "Section"
        bits = [str(name)]
        if sec.get("use") and sec.get("name"):
            bits.append(f"({sec.get('use')})")
        w_mm, h_mm = sec.get("wMm"), sec.get("hMm")
        if w_mm is not None or h_mm is not None:
            bits.append(f"{w_mm or '—'}×{h_mm or '—'} mm")
        if sec.get("wallMm") is not None:
            bits.append(f"wall {sec['wallMm']} mm")
        if sec.get("weightKgPerM") is not None:
            bits.append(f"{sec['weightKgPerM']} kg/m")
        if sec.get("stdLengthMm") is not None:
            bits.append(f"std {sec['stdLengthMm']:g} mm" if isinstance(sec["stdLengthMm"], (int, float)) else f"std {sec['stdLengthMm']}")
        lines.append("Section: " + " · ".join(bits))

    notes = (layout or {}).get("notes") or []
    for note in notes[:3]:
        if note:
            lines.append(f"Note = {note}")
    return lines


def render_marqt_pdf(template: Mapping[str, Any], payload: Mapping[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from WEOS.factory.pdf_fonts import ensure_rupee_font, money_text, rupee_prefix, set_font

    ensure_rupee_font()  # register before any drawString with ₹

    buf = io.BytesIO()
    page = A4
    c = canvas.Canvas(buf, pagesize=page)
    W, H = page
    branding = template.get("branding") or {}
    primary = _rgb(branding.get("primaryColor"), (0.12, 0.22, 0.38))
    accent = _rgb(branding.get("accentColor"), (0.75, 0.15, 0.12))
    company = branding.get("companyName") or branding.get("logoText") or "WEOS"
    phone = branding.get("phone") or ""
    email = branding.get("email") or ""
    address = branding.get("address") or ""
    website = branding.get("website") or ""
    gst = branding.get("gstNo") or ""
    logo_path = branding.get("logoPath")
    qid = payload.get("quotationId") or payload.get("projectId") or "WEOS-QT"
    qdate = payload.get("quoteDate") or payload.get("createdOn") or date.today().strftime("%d-%m-%Y")
    updated_on = payload.get("updatedOn")
    customer = payload.get("customer") or "—"
    cust_profile = payload.get("customerProfile") or {}
    project_name = payload.get("name") or ""
    lines = list(payload.get("lines") or [])
    _rs = rupee_prefix()

    def _draw_logo(cx: float, top_y: float, max_w: float, max_h: float) -> float:
        """Draw company logo if configured. Returns drawn height (0 if none)."""
        if not logo_path:
            return 0.0
        try:
            from reportlab.lib.utils import ImageReader

            lp = str(logo_path)
            if lp.lower().endswith(".svg"):
                from WEOS.factory.image_engine import svg_to_png_bytes

                png = svg_to_png_bytes(open(lp, "r", encoding="utf-8").read(), scale=1.0)
                if not png:
                    return 0.0
                img = ImageReader(io.BytesIO(png))
            else:
                img = ImageReader(lp)
            iw, ih = img.getSize()
            if iw <= 0 or ih <= 0:
                return 0.0
            scale = min(max_w / float(iw), max_h / float(ih))
            dw, dh = iw * scale, ih * scale
            c.drawImage(img, cx, top_y - dh, width=dw, height=dh, mask="auto")
            return dh
        except Exception:
            return 0.0

    # —— Cover letter page ——
    M = MARGIN
    # Logo — larger header size, aspect preserved, capped to a sensible box.
    logo_h = _draw_logo(M, H - M, 210, 74)
    text_x = M + (205 if logo_h else 0)
    name_avail = (W - M) - text_x  # keep company name inside the right margin
    c.setFillColorRGB(*primary)
    _draw_fit(c, company, text_x, H - 52, name_avail, 18, bold=True, minimum=10)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    set_font(c, 9)
    c.drawString(text_x, H - 68, (branding.get("tagline") or "Windows and Doors Quotation")[:90])
    header_extra = H - 82
    if address:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(text_x, header_extra, address[:110])
        header_extra -= 11
    contact_bits = " · ".join(x for x in (phone, email, website) if x)
    if contact_bits:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(text_x, header_extra, contact_bits[:110])
        header_extra -= 11
    if gst:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(text_x, header_extra, f"GSTIN: {gst}")
        header_extra -= 11
    # Divider under the company header so the cover never reads as "blank".
    header_bottom = min(H - 108, header_extra - 6, (H - M - logo_h - 8) if logo_h else H - 108)
    c.setStrokeColorRGB(*primary)
    c.setLineWidth(1)
    c.line(M, header_bottom, W - M, header_bottom)
    y = header_bottom - 20
    c.setFillColorRGB(0, 0, 0)
    set_font(c, 10, bold=True)
    c.drawString(M, y, "To:")
    set_font(c, 10)
    c.drawString(M + 22, y, str(customer).upper() if customer and customer != "—" else "—")
    y -= 14
    set_font(c, 8)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    if cust_profile.get("address"):
        c.drawString(M + 22, y, str(cust_profile["address"])[:110])
        y -= 11
    cust_contact = " · ".join(
        str(x) for x in (cust_profile.get("contactPerson"), cust_profile.get("phone"), cust_profile.get("email")) if x
    )
    if cust_contact:
        c.drawString(M + 22, y, cust_contact[:110])
        y -= 11
    if cust_profile.get("gstNo"):
        c.drawString(M + 22, y, f"GSTIN: {cust_profile['gstNo']}")
        y -= 11
    c.setFillColorRGB(0, 0, 0)
    y -= 4
    set_font(c, 10)
    if project_name:
        c.drawString(M, y, f"Project: {project_name}")
        y -= 16
    c.drawString(M, y, f"Quote No: {qid}    Date: {qdate}")
    y -= 16
    if updated_on:
        c.setFillColorRGB(*accent)
        set_font(c, 9, bold=True)
        c.drawString(M, y, f"Updated on: {updated_on}")
        c.setFillColorRGB(0, 0, 0)
        set_font(c, 10)
        y -= 16
    y -= 12
    cover = ""
    for b in template.get("blocks") or []:
        if b.get("type") == "cover_letter":
            cover = str(b.get("text") or "")
            break
    if not cover:
        cover = (
            "We thank you for your enquiry and are pleased to offer our windows and doors "
            "as per the enclosed design, specifications and value."
        )
    text_w = W - 2 * M
    set_font(c, 10)
    for para in cover.split("\n"):
        # wrap
        words = para.split()
        line = ""
        for word in words:
            trial = (line + " " + word).strip()
            if c.stringWidth(trial, c._fontname, 10) > text_w:
                c.drawString(M, y, line)
                y -= 14
                line = word
            else:
                line = trial
        if line:
            c.drawString(M, y, line)
            y -= 14
        y -= 6

    # —— Per-quote Description (optional) ——
    description = str(payload.get("description") or "").strip()
    if description:
        y -= 6
        c.setFillColorRGB(*primary)
        set_font(c, 10, bold=True)
        c.drawString(M, y, "Description")
        y -= 15
        c.setFillColorRGB(0, 0, 0)
        set_font(c, 9)
        for para in description.split("\n"):
            words = para.split()
            line = ""
            for word in words:
                trial = (line + " " + word).strip()
                if c.stringWidth(trial, c._fontname, 9) > text_w:
                    c.drawString(M, y, line)
                    y -= 13
                    line = word
                else:
                    line = trial
            if line:
                c.drawString(M, y, line)
                y -= 13
            y -= 4

    y -= 16
    set_font(c, 9)
    c.drawString(M, y, "Enclosures:")
    y -= 14
    c.drawString(M + 10, y, "a) Design / Specifications / Value")
    y -= 12
    c.drawString(M + 10, y, "b) Terms & Conditions")
    y -= 30
    if phone or email or address:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        if address:
            c.drawString(M, y, address[:120])
            y -= 12
        contact = " · ".join(x for x in (phone, email) if x)
        if contact:
            c.drawString(M, y, contact[:120])
    set_font(c, 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(M, M / 2 + 8, "powered by WEOS — page 1")
    c.showPage()

    # —— Line items pages ——
    # Uniform margins on every side; SPEC/QTY/RATE/AMOUNT columns anchored to them.
    col_spec = M + 218
    col_qty = W - 165
    col_rate = W - 105
    col_amt = W - M

    def header(page_no: int):
        c.setFillColorRGB(*primary)
        _draw_fit(c, company, M, H - M, (col_qty - 40) - M, 12, bold=True, minimum=8)
        set_font(c, 8)
        c.setFillColorRGB(0.25, 0.25, 0.25)
        c.drawRightString(W - M, H - (M - 4), f"Quote No. {qid}")
        c.drawRightString(W - M, H - (M + 8), f"Quote Date {qdate}")
        if updated_on:
            c.setFillColorRGB(*accent)
            c.drawRightString(W - M, H - (M + 19), f"Updated {updated_on}")
            c.setFillColorRGB(0.25, 0.25, 0.25)
        c.setStrokeColorRGB(*primary)
        c.setLineWidth(1)
        c.line(M, H - (M + 16), W - M, H - (M + 16))
        # column headers
        yy = H - (M + 32)
        c.setFillColorRGB(*primary)
        set_font(c, 8, bold=True)
        c.drawString(M, yy, "DESIGN")
        c.drawString(col_spec, yy, "SPECIFICATIONS")
        c.drawRightString(col_qty, yy, "QTY")
        c.drawRightString(col_rate, yy, f"RATE ({_rs})")
        c.drawRightString(col_amt, yy, f"AMOUNT ({_rs})")
        c.setStrokeColorRGB(0.75, 0.75, 0.75)
        c.line(M, yy - 6, W - M, yy - 6)
        return yy - 18

    y = header(2)
    page_no = 2
    total_area = 0.0
    total_qty = 0
    grand = 0.0

    # Elevation cell sized so THREE window rows fit per page with clean margins.
    draw_w, draw_h = 200, 185
    bottom_limit = M + 30  # keep clear of footer + bottom margin

    for idx, line in enumerate(lines):
        need = draw_h + 24
        if y < bottom_limit + need:
            set_font(c, 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(M, M / 2 + 8, f"powered by WEOS — page {page_no}")
            c.showPage()
            page_no += 1
            y = header(page_no)

        w = float(line.get("width") or 0)
        h = float(line.get("height") or 0)
        qty = int(line.get("qty") or 1)
        area = _area_sqft(w, h) * qty
        total_area += _area_sqft(w, h) * qty
        total_qty += qty

        selling = line.get("selling") or {}
        rate = selling.get("sellingRate")
        amount = selling.get("sellingAmount")
        if amount is None:
            amount = line.get("commercialTotal")
        if amount is None:
            amount = (line.get("price") or {}).get("total") or 0
        if rate is None and selling.get("billableQty"):
            try:
                rate = float(amount) / float(selling["billableQty"])
            except (TypeError, ValueError, ZeroDivisionError):
                rate = None
        if rate is None and _line_is_railing(line):
            # Prefer railing commercial RFT/RMT rate — never fake sqft from length×height.
            rate = line.get("sellingRate") or (line.get("price") or {}).get("unitRate")
            if rate is None:
                _, rq = _railing_cfg_and_quote(line)
                rate = (rq or {}).get("sellingPerUnit")
        if rate is None:
            # derive from cost / area for display
            try:
                rate = float(amount) / max(_area_sqft(w, h) * qty, 0.001)
            except (TypeError, ValueError):
                rate = 0
        grand += float(amount or 0)

        code = f"W{idx + 1}"
        # Design column — same geometry SVG as live canvas (not schematic stub)
        c.setFillColorRGB(*accent)
        set_font(c, 9, bold=True)
        c.drawString(M + 2, y + 4, code)
        try:
            draw_line_elevation(c, line, M, y - draw_h, draw_w, draw_h)
        except Exception:
            _log.exception("marqt elevation draw failed for line %d; leaving cell blank", idx)

        # Specs (no sell-rate line — rate is in RATE column only)
        try:
            specs = _spec_lines(line)
        except Exception:
            _log.exception("marqt spec build failed for line %d; using name only", idx)
            specs = [str(line.get("displayName") or line.get("product") or "Window")]
        c.setFillColorRGB(0, 0, 0)
        set_font(c, 7)
        sy = y
        for s in specs[:18]:
            c.drawString(col_spec, sy, s[:50])
            sy -= 9

        # Qty / Rate / Amount — currency symbol via Unicode font
        set_font(c, 8)
        c.drawRightString(col_qty, y, str(qty))
        rate_str = f"{float(rate):,.2f}" if rate is not None else "—"
        c.drawRightString(col_rate, y, rate_str)
        set_font(c, 8, bold=True)
        c.drawRightString(col_amt, y, f"{float(amount):,.2f}")

        # row separator
        row_bottom = min(sy, y - draw_h - 10)
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.5)
        c.line(M, row_bottom, W - M, row_bottom)
        y = row_bottom - 14

    # Totals block
    if y < 140:
        set_font(c, 7)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(M, M / 2 + 8, f"powered by WEOS — page {page_no}")
        c.showPage()
        page_no += 1
        y = header(page_no)

    gst_pct = 18.0
    price = payload.get("price") or {}
    # Prefer commercial grand; fall back
    basic = float(grand or price.get("total") or (payload.get("combined") or {}).get("grandTotal") or 0)
    # If amounts already include GST from cost engine, show as project total with GST split estimate
    # For selling amounts we treat as basic + GST unless payload says otherwise
    if payload.get("sellingIncludesGst"):
        project = basic
        gst_amt = round(project * gst_pct / (100 + gst_pct), 2)
        basic_ex = round(project - gst_amt, 2)
    else:
        # Assume selling amounts are ex-GST (dealer style) → add GST
        basic_ex = round(basic, 2)
        gst_amt = round(basic_ex * gst_pct / 100.0, 2)
        project = round(basic_ex + gst_amt, 2)

    y -= 8
    c.setFillColorRGB(*primary)
    set_font(c, 9, bold=True)
    c.drawString(M, y, "TOTALS")
    y -= 14
    c.setFillColorRGB(0, 0, 0)
    set_font(c, 8)
    c.drawString(M, y, f"Total Area: {round(total_area, 3)} Sq.Ft.    Windows: {total_qty} Nos")
    y -= 12
    c.drawString(M, y, f"Basic / Project Value: {money_text(basic_ex)}")
    y -= 12
    c.drawString(M, y, f"GST @ {gst_pct:g}%: {money_text(gst_amt)}")
    y -= 16
    set_font(c, 12, bold=True)
    c.setFillColorRGB(*accent)
    c.drawString(M, y, "Grand Total")
    c.drawRightString(W - M, y, money_text(project))
    c.setFillColorRGB(0, 0, 0)

    set_font(c, 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(M, M / 2 + 8, f"powered by WEOS — page {page_no}")
    c.showPage()
    page_no += 1

    # —— Terms page ——
    text_w = W - 2 * M
    c.setFillColorRGB(*primary)
    set_font(c, 14, bold=True)
    c.drawString(M, H - (M + 14), "Terms & Conditions")
    # Precedence: per-quote override → template block → Company Setup default → built-in.
    terms_text = str(payload.get("terms") or "").strip()
    if not terms_text:
        for b in template.get("blocks") or []:
            if b.get("type") == "terms":
                terms_text = str(b.get("text") or "").strip()
                break
    if not terms_text:
        terms_text = str(branding.get("terms") or "").strip()
    if not terms_text:
        terms_text = (
            "1. Specs & sizes may differ 7–9 mm after site measurement.\n"
            "2. Pricing Ex-Works unless noted. GST extra as applicable.\n"
            "3. Payment as agreed. Order confirmation required.\n"
            "4. Delivery typically 3+ weeks from confirmation.\n"
            "5. Quotation valid 15 days.\n"
            "6. Warranty: profile manufacturing defects as per policy."
        )
    y = H - (M + 40)
    c.setFillColorRGB(0, 0, 0)
    set_font(c, 9)
    for para in terms_text.split("\n"):
        words = para.split()
        line = ""
        for word in words:
            trial = (line + " " + word).strip()
            if c.stringWidth(trial, c._fontname, 9) > text_w:
                c.drawString(M, y, line)
                y -= 13
                line = word
            else:
                line = trial
        if line:
            c.drawString(M, y, line)
            y -= 13
        y -= 4
        if y < M + 40:
            c.showPage()
            page_no += 1
            y = H - (M + 10)

    # —— Bank details (from Company Setup) ——
    bank = str(branding.get("bankDetails") or "").strip()
    if bank:
        if y < M + 80:
            c.showPage()
            page_no += 1
            y = H - (M + 10)
        y -= 18
        c.setFillColorRGB(*primary)
        set_font(c, 11, bold=True)
        c.drawString(M, y, "Bank Details")
        y -= 15
        c.setFillColorRGB(0, 0, 0)
        set_font(c, 9)
        for para in bank.split("\n"):
            words = para.split()
            line = ""
            for word in words:
                trial = (line + " " + word).strip()
                if c.stringWidth(trial, c._fontname, 9) > text_w:
                    c.drawString(M, y, line)
                    y -= 13
                    line = word
                else:
                    line = trial
            if line:
                c.drawString(M, y, line)
                y -= 13

    y -= 30
    set_font(c, 9)
    c.drawString(M, y, "For " + company)
    y -= 50
    c.drawString(M, y, "Authorized Signatory")
    c.drawRightString(W - M, y, "Customer Acceptance")

    # QR → absolute public URL that fetches this quote from the database when scanned.
    try:
        from WEOS.factory.pdf_qr import draw_quote_qr

        draw_quote_qr(c, payload, x=M, y=M + 8, size=64, label="Scan to view quote")
    except Exception:
        pass

    set_font(c, 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(M, M / 2 + 8, f"powered by WEOS — page {page_no}")
    c.showPage()
    c.save()
    return buf.getvalue()
