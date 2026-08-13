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


def _mm(v: Any) -> str:
    from WEOS.factory.fmt import mm_str

    return mm_str(v, suffix="")


def _set_font(c, size: float, *, bold: bool = False) -> str:
    from WEOS.factory.pdf_fonts import set_font

    return set_font(c, size, bold=bold)


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


def _wrap_text(c, text: str, max_width: float, font_size: float = 7.0, *, bold: bool = False) -> list[str]:
    """Word-wrap ``text`` so each line fits within ``max_width`` (no mid-word hard truncate)."""
    face = "Helvetica-Bold" if bold else "Helvetica"
    try:
        face = _set_font(c, font_size, bold=bold) or face
    except Exception:
        pass
    raw = str(text or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for para in raw.split("\n"):
        words = para.split()
        if not words:
            continue
        line = words[0]
        for word in words[1:]:
            trial = f"{line} {word}"
            if c.stringWidth(trial, face, font_size) <= max_width:
                line = trial
            else:
                out.append(line)
                if c.stringWidth(word, face, font_size) > max_width:
                    chunk = ""
                    for ch in word:
                        t2 = chunk + ch
                        if chunk and c.stringWidth(t2, face, font_size) > max_width:
                            out.append(chunk)
                            chunk = ch
                        else:
                            chunk = t2
                    line = chunk
                else:
                    line = word
        if line:
            out.append(line)
    return out


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
    c.drawCentredString(x + box_w / 2, dim_y - 10, f"W = {_mm(width_mm)} mm")

    dim_x = x + box_w + 10
    c.line(dim_x, y, dim_x, y + box_h)
    c.line(dim_x - 3, y, dim_x + 3, y)
    c.line(dim_x - 3, y + box_h, dim_x + 3, y + box_h)
    c.saveState()
    c.translate(dim_x + 8, y + box_h / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, f"H = {_mm(height_mm)} mm")
    c.restoreState()


def _line_is_railing(line: Mapping[str, Any]) -> bool:
    """Detect railing designer lines even when product id varies."""
    from WEOS.factory.line_kind import is_railing_cart_line

    return is_railing_cart_line(line)


def _railing_cfg_and_quote(line: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    cfg = opts.get("railing") if isinstance(opts, Mapping) else None
    cfg = dict(cfg) if isinstance(cfg, Mapping) else {}
    try:
        from WEOS.factory.railing_engine import ensure_railing_dims

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
    # Recompute when quote is missing, length collapsed, or shape/panels diverge
    # from options.railing (stale staircase quote on a straight design, etc.).
    need_recompute = False
    if not isinstance(q, Mapping) or not q:
        need_recompute = bool(cfg)
    else:
        try:
            from WEOS.factory.railing_engine import railing_quote_matches_cfg

            if not railing_quote_matches_cfg(q, cfg):
                need_recompute = True
        except Exception:
            if float(q.get("lengthMm") or 0) <= 1.0 and float(cfg.get("lengthMm") or line.get("width") or 0) > 1.0:
                need_recompute = True
    if need_recompute and cfg:
        try:
            from WEOS.factory.railing_engine import compute_railing

            q = compute_railing(cfg)
        except Exception:
            q = q if isinstance(q, Mapping) else {}
    return cfg, dict(q) if isinstance(q, Mapping) else {}


def _line_design_photo_bytes(line: Mapping[str, Any]) -> tuple[bytes | None, str | None]:
    """Uploaded design photo (durable blob), if the line has one."""
    photo = line.get("designPhoto") if isinstance(line.get("designPhoto"), Mapping) else None
    if not photo:
        opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        photo = opts.get("designPhoto") if isinstance(opts.get("designPhoto"), Mapping) else None
    if not isinstance(photo, Mapping):
        return None, None
    key = str(photo.get("key") or "").strip()
    if not key:
        return None, None
    try:
        from WEOS.factory.design_photo import design_photo_bytes_by_key

        return design_photo_bytes_by_key(key)
    except Exception:
        _log.exception("design photo load failed")
        return None, None


def draw_line_elevation(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    """Draw the live-canvas SVG (or user-uploaded design photo) into the design column.

    Photo wins when uploaded; otherwise the same SVG as the live preview.
    Returns True when the real elevation was drawn.
    """
    from reportlab.lib.utils import ImageReader

    from WEOS.factory.image_engine import svg_to_png_bytes, svg_to_rl_drawing
    from WEOS.factory.svg_export import elevation_svg_for_line

    w = float(line.get("width") or 0)
    h = float(line.get("height") or 0)

    # User-uploaded design photo prints instead of canvas when present.
    photo_raw, _photo_ct = _line_design_photo_bytes(line)
    if photo_raw:
        try:
            img = ImageReader(io.BytesIO(photo_raw))
            iw, ih = img.getSize()
            if iw > 0 and ih > 0:
                scale = min(box_w / float(iw), box_h / float(ih))
                dw, dh = iw * scale, ih * scale
                c.drawImage(img, x + (box_w - dw) / 2.0, y + (box_h - dh) / 2.0, width=dw, height=dh, mask="auto")
                return True
        except Exception:
            _log.exception("design photo embed failed; falling back to canvas SVG")

    # One elevation path: live canvas SVG (shower / railing / window) via
    # elevation_svg_for_line. PNG first for fidelity, then vector.
    svg = elevation_svg_for_line(line, style="pdf")
    if not svg:
        prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
        svg = (prev or {}).get("svg")

    if svg:
        # 1) Raster of the canvas SVG (same look as live preview).
        png = svg_to_png_bytes(str(svg), scale=2.5)
        if png:
            img = ImageReader(io.BytesIO(png))
            iw, ih = img.getSize()
            if iw > 0 and ih > 0:
                scale = min(box_w / float(iw), box_h / float(ih))
                dw, dh = iw * scale, ih * scale
                c.drawImage(img, x + (box_w - dw) / 2.0, y + (box_h - dh) / 2.0, width=dw, height=dh, mask="auto")
                return True

        # 2) Vector fallback (crisp when svglib supports the markup).
        try:
            drawing = svg_to_rl_drawing(str(svg))
            if drawing is not None and getattr(drawing, "width", 0) and getattr(drawing, "height", 0):
                from reportlab.graphics import renderPDF

                dwid, dhei = float(drawing.width), float(drawing.height)
                scale = min(box_w / dwid, box_h / dhei)
                dw, dh = dwid * scale, dhei * scale
                drawing.scale(scale, scale)
                drawing.width, drawing.height = dw, dh
                renderPDF.draw(drawing, c, x + (box_w - dw) / 2.0, y + (box_h - dh) / 2.0)
                return True
        except Exception:
            _log.exception("svg vector embed failed; trying model fallback")

    # Railing must never fall through to a window stub.
    if _line_is_railing(line):
        rail_cfg, rail_q = _railing_cfg_and_quote(line)
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


def _laminated_config_label(thickness_mm: Any, glass_type: str = "") -> str | None:
    """Customer-facing laminated makeup e.g. ``5+1.52+6mm``."""
    try:
        thk = float(thickness_mm or 0)
    except (TypeError, ValueError):
        thk = 0.0
    gt = str(glass_type or "").lower()
    if thk <= 0 and "lam" not in gt:
        return None
    try:
        from WEOS.factory.glass_catalogue import LAMINATED_MAKEUPS_MM, default_layers_for

        layers = default_layers_for("laminated", thk) if thk else {}
        if not layers and thk:
            # nearest catalogue overall
            nearest = min(LAMINATED_MAKEUPS_MM.keys(), key=lambda k: abs(k - thk), default=None)
            if nearest is not None and abs(nearest - thk) < 0.6:
                layers = dict(LAMINATED_MAKEUPS_MM[nearest])
        if not layers and "lam" in gt:
            layers = default_layers_for("laminated", 13.52) or {}
        g1, pvb, g2 = layers.get("glass1Mm"), layers.get("pvbMm"), layers.get("glass2Mm")
        if g1 and pvb and g2:
            return f"{g1:g}+{pvb:g}+{g2:g}mm"
    except Exception:
        pass
    return None


def _spec_rows(line: Mapping[str, Any], *, audience: str = "customer") -> list[tuple[str, str]]:
    """Structured SPECIFICATIONS rows: (LABEL, value) for tabular PDF layout.

    Labels are uppercase without trailing colon. Empty label = full-width title line.
    ``audience``: customer (no BOM / purchase rates) or factory (full BOM + rates).
    Applies to windows, doors, railings, louvers, and other product lines.
    """
    factory = str(audience or "customer").lower() == "factory"
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

    rows: list[tuple[str, str]] = []

    def add(label: str, value: Any) -> None:
        v = str(value or "").strip()
        if not v:
            return
        rows.append((str(label or "").strip().upper(), v))

    # ── Railing lines: product → bottom → handrail → glass → hardware → qty → amount
    if _line_is_railing(line):
        rail_cfg, q = _railing_cfg_and_quote(line)
        shape = q.get("shape") or (rail_cfg or {}).get("shape") or "straight"
        color_mode = (rail_cfg or {}).get("colorMode") or "global"
        sys_color = (rail_cfg or {}).get("systemColor") or q.get("systemColor") or ""
        from WEOS.factory.railing_engine import format_railing_description

        title = format_railing_description(q, rail_cfg)
        try:
            from WEOS.factory.railing_engine import infer_railing_mount, railing_mount_label

            mount = q.get("mountType") or infer_railing_mount(
                bottom_kind=str(q.get("bottomKind") or (rail_cfg or {}).get("bottomKind") or ""),
                shape=str(shape),
                stair_bottom_type=str(q.get("stairBottomType") or (rail_cfg or {}).get("stairBottomType") or ""),
                stair_mount_type=str(q.get("stairMountType") or (rail_cfg or {}).get("stairMountType") or ""),
                mount_explicit=bool((rail_cfg or {}).get("mountExplicit") or (rail_cfg or {}).get("mountTypeLocked")),
                explicit_mount=str((rail_cfg or {}).get("mountType") or q.get("mountType") or ""),
            )
            mount_lbl = q.get("mountLabel") or railing_mount_label(mount)
        except Exception:
            mount = q.get("mountType") or (rail_cfg or {}).get("mountType") or "top_mount"
            mount_lbl = str(q.get("mountLabel") or str(mount).replace("_", " ").upper())
        add("", title)
        add("TYPE", f"{shape} · {mount_lbl}")
        add("MOUNT", mount_lbl)
        add("SIZE", f"{_mm(q.get('lengthMm') or w)} × {_mm(q.get('heightMm') or h)} mm")
        gh = q.get("glassHeightMm") or q.get("heightMm") or h
        add("GLASS HEIGHT", f"{_mm(gh)} mm")

        bom = list(q.get("bomDetails") or q.get("items") or [])
        def _bom(key: str) -> Mapping[str, Any] | None:
            for it in bom:
                if isinstance(it, Mapping) and str(it.get("key") or "") == key:
                    return it
            return None

        bottom_kind = str(q.get("bottomKind") or (rail_cfg or {}).get("bottomKind") or "").lower()
        if shape == "staircase":
            sbt = q.get("stairBottomType") or (rail_cfg or {}).get("stairBottomType") or "block"
            bottom_kind = "ss_pillar" if str(sbt).lower() in ("topiller", "ss", "ss_pillar") else "block"
        kind_label = {
            "continuous": "Continuous rail",
            "block": "Aluminium block",
            "ss_pillar": "SS pillars",
            "studs": "SS studs",
        }.get(bottom_kind, bottom_kind.replace("_", " ").title() or "Bottom")
        b_item = _bom("bottomRail") or _bom("blocks") or _bom("studs")
        b_bits = [kind_label]
        if sys_color:
            b_bits.append(f"color {sys_color}")
        elif b_item and b_item.get("color"):
            b_bits.append(f"color {b_item.get('color')}")
        br_size = (
            (b_item or {}).get("sizeMm")
            or q.get("bottomSize")
            or (rail_cfg or {}).get("bottomSize")
        )
        if br_size:
            b_bits.append(f"size {br_size}")
        if b_item:
            b_bits.append(f"qty {b_item.get('qty')} {b_item.get('unit') or ''}".strip())
            if b_item.get("lengthMm"):
                b_bits.append(f"{_mm(b_item.get('lengthMm'))} mm")
            elif bottom_kind == "continuous" and (q.get("runLengthMm") or q.get("lengthMm")):
                b_bits.append(f"{_mm(q.get('runLengthMm') or q.get('lengthMm'))} mm")
        elif q.get("lengthRft"):
            b_bits.append(f"len {q.get('lengthRft')} rft")
        b_bits.append(mount_lbl)
        add("BOTTOM", " · ".join(str(x) for x in b_bits if x))

        pillar_sz = (
            (rail_cfg or {}).get("bottomSize")
            or (rail_cfg or {}).get("pillarSize")
            or q.get("bottomSize")
            or q.get("studSizeMm")
            or (b_item or {}).get("sizeMm")
        )
        if pillar_sz and bottom_kind not in ("continuous", "rail", ""):
            add("PILLAR", f"{pillar_sz}" + (f" · {kind_label}" if kind_label else ""))

        supports = q.get("glassSupports") or []
        if supports:
            add(
                "SUPPORTS",
                " · ".join(
                    f"{s.get('glass')}: {s.get('count')} {s.get('kind')}"
                    + (f" ({s.get('where')})" if s.get("where") else "")
                    for s in supports
                    if isinstance(s, Mapping)
                ),
            )
        elif q.get("panelCount") and (q.get("studsPerGlass") or (rail_cfg or {}).get("blocksPerGlass")):
            n_g = int(q.get("panelCount") or 0)
            per = int(q.get("studsPerGlass") or (rail_cfg or {}).get("blocksPerGlass") or 0)
            if n_g and per:
                kind_s = "studs" if bottom_kind == "studs" or (q.get("stairStuds") or 0) else "supports"
                add("SUPPORTS", " · ".join(f"G{i + 1}: {per} {kind_s}" for i in range(n_g)))

        if q.get("handrail") or (rail_cfg or {}).get("handrail") or _bom("handrail"):
            hr = _bom("handrail") or {}
            hr_size = str((rail_cfg or {}).get("handrailSize") or q.get("handrailSize") or hr.get("sizeMm") or "Handrail")
            hr_len_rft = hr.get("qty") or q.get("lengthRft") or q.get("widthUnit") or 0
            hr_unit = hr.get("unit") or q.get("saleUnit") or "rft"
            try:
                hr_mm = round(float(hr_len_rft) * 304.8, 0) if str(hr_unit).lower() in ("rft", "ft") else None
            except (TypeError, ValueError):
                hr_mm = None
            hr_bits = [hr_size]
            if hr.get("color") or sys_color:
                hr_bits.append(f"color {hr.get('color') or sys_color}")
            hr_bits.append(f"{hr_len_rft} {hr_unit}")
            hr_len_mm = hr.get("lengthMm") or q.get("runLengthMm") or hr_mm or q.get("lengthMm")
            if hr_len_mm:
                hr_bits.append(f"{_mm(hr_len_mm)} mm")
            add("HANDRAIL", " · ".join(str(x) for x in hr_bits if x))

        thk = q.get("glassThicknessMm") or (rail_cfg or {}).get("glassThicknessMm") or 12
        gtype = (rail_cfg or {}).get("glassType") or q.get("glassType") or ""
        gcol = (rail_cfg or {}).get("glassColour") or q.get("glassColour") or ""
        gbrand = q.get("glassBrand") or (rail_cfg or {}).get("glassBrand") or ""
        lam = _laminated_config_label(thk, gtype)
        glass_bits = [f"{thk:g} mm"]
        if lam:
            glass_bits.append(lam)
        if gtype:
            glass_bits.append(str(gtype))
        if gcol and str(gcol).lower() not in str(gtype).lower():
            glass_bits.append(str(gcol))
        if gbrand:
            glass_bits.append(str(gbrand))
        glass_val = " · ".join(str(b) for b in glass_bits if b) or "—"
        if q.get("panelCount"):
            glass_val += f" · {q.get('panelCount')} glass"
        net_sft = q.get("netGlassAreaSqFt") or q.get("glassAreaSqft") or 0
        glass_val += f" · net {net_sft} sft"
        if factory:
            glass_val += (
                f" · purchased {q.get('purchasedGlassAreaSqFt') or 0} sft"
                f" · wastage {q.get('wastagePercent') or 0}%"
            )
        add("GLASS", glass_val)

        hw_brand = q.get("hardwareBrand") or (rail_cfg or {}).get("hardwareBrand") or ""
        hw_bits = []
        if hw_brand:
            hw_bits.append(str(hw_brand))
        hw_bits.append(f"anchors {q.get('anchorCount') or 0}")
        if q.get("endCapCount") or (rail_cfg or {}).get("endCaps"):
            hw_bits.append(f"end caps {q.get('endCapCount') or 0}")
        if q.get("wallConnectors"):
            hw_bits.append(f"wall connectors {q.get('wallConnectors')}")
        n90 = q.get("connector90Count") or q.get("bendCount") or 0
        n180 = q.get("connector180Count") or 0
        if n90 or n180:
            grade = ""
            c90 = _bom("modularBend") or _bom("connector180") or {}
            if c90.get("grade"):
                grade = f" · {c90.get('grade')}"
            hw_bits.append(f"90° {n90} / 180° {n180}{grade}")
        add("HARDWARE", " · ".join(hw_bits) or "—")
        ov = q.get("beamOverlapMm") or (rail_cfg or {}).get("beamOverlapMm")
        if ov:
            add("OVERLAP", f"{ov:g} mm over beam / slab")

        sale_u = str(q.get("saleUnit") or line.get("saleUnit") or "rft").upper()
        add(
            "QTY",
            f"Area {q.get('netGlassAreaSqFt') or q.get('glassAreaSqft') or 0} sft"
            f" · {sale_u} {q.get('widthUnit') or q.get('lengthRft') or q.get('lengthRmt') or 0}"
            f" · qty {line.get('qty') or 1}",
        )
        rate = q.get("sellingPerUnit") or line.get("sellingRate") or 0
        amt = q.get("sellingTotal") or line.get("commercialTotal") or (line.get("selling") or {}).get("sellingAmount")
        add("AMOUNT", f"{rate} / {sale_u} → {amt}")
        add("COLOUR", f"{sys_color or 'per-part'} ({color_mode})")

        sg = q.get("stairGeometry") if isinstance(q.get("stairGeometry"), Mapping) else {}
        if shape == "staircase" or sg:
            add(
                "STAIRS",
                f"{sg.get('steps') or (rail_cfg or {}).get('stairSteps') or '—'} steps"
                f" · riser {sg.get('riserMm') or (rail_cfg or {}).get('stairRiseMm') or '—'} mm"
                f" · tread {sg.get('treadMm') or (rail_cfg or {}).get('stairRunMm') or '—'} mm"
                f" · floor {sg.get('floorHeightMm') or (rail_cfg or {}).get('floorHeightMm') or '—'} mm",
            )
            if sg.get("riseMismatch"):
                add("NOTE", str(sg.get("riseMismatchMessage") or "Rise mismatch vs floor height"))
        if factory:
            for it in bom[:12]:
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
                add("BOM", " · ".join(bits))
        return rows

    try:
        from WEOS.factory.line_kind import is_shower_cart_line
    except Exception:
        is_shower_cart_line = lambda _l: False  # noqa: E731
    if is_shower_cart_line(line):
        opts_s = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        cfg_s = opts_s.get("shower") if isinstance(opts_s, Mapping) else None
        cfg_s = dict(cfg_s) if isinstance(cfg_s, Mapping) else {}
        q = opts_s.get("showerQuote") if isinstance(opts_s, Mapping) else None
        if not isinstance(q, Mapping):
            q = line.get("shower") if isinstance(line.get("shower"), Mapping) else {}
        if (not q or not q.get("panels")) and cfg_s:
            try:
                from WEOS.factory.shower_engine import compute_shower, ensure_shower_dims

                q = compute_shower(ensure_shower_dims(cfg_s, width=w or None, height=h or None))
            except Exception:
                q = q if isinstance(q, Mapping) else {}
        from WEOS.factory.shower_engine import format_shower_description

        add("", format_shower_description(q, cfg_s))
        add("TYPE", f"{q.get('shape') or 'straight'} · {q.get('operation') or 'sliding'}"
            + (f" · 1+1 slide {(q.get('slidingSide') or 'right')}" if q.get("operation") == "sliding" else ""))
        add("SIZE", f"{_mm(q.get('widthMm') or w)} × {_mm(q.get('heightMm') or h)} mm")
        fp = q.get("footprint") if isinstance(q.get("footprint"), Mapping) else {}
        if fp:
            if fp.get("kind") == "L":
                add("PLAN", f"L · front {fp.get('frontMm')} · return {fp.get('returnMm')} mm")
            elif fp.get("kind") == "U":
                add("PLAN", f"U · front {fp.get('frontMm')} · L {fp.get('leftMm')} · R {fp.get('rightMm')} mm")
            else:
                add("PLAN", f"Straight · {fp.get('frontMm')} mm")
        panels_s = q.get("panels") or []
        if panels_s:
            add("PANELS", "; ".join(
                f"{p.get('label') or p.get('role')} {_mm(p.get('widthMm'))}×{_mm(p.get('heightMm'))}"
                for p in panels_s if isinstance(p, Mapping)
            ))
        add("PROFILE", f"{q.get('verticalProfile') or '16×45'} vert"
            + (f" · {q.get('horizontalProfile')} horiz" if q.get("horizontalProfile") else "")
            + (f" · chokhat {q.get('chokhat')}" if q.get("chokhat") else " · frameless"))
        add("GLASS", q.get("glassLabel") or f"{q.get('glassThicknessMm') or ''} mm {q.get('glassColour') or ''}")
        hw_s = []
        if q.get("hardwareBrand"):
            hw_s.append(str(q.get("hardwareBrand")))
        if q.get("hardwareOrigin"):
            hw_s.append(str(q.get("hardwareOrigin")))
        if q.get("handle"):
            hw_s.append(f"handle {q.get('handleName') or 'D-type'}")
        hw_s.append(f"lock {'yes' if q.get('lock') else 'no'}")
        if q.get("hingesPerDoor"):
            hw_s.append(f"{q.get('hingeType') or 'butterfly'} ×{q.get('hingesPerDoor')}/door")
        add("HARDWARE", " · ".join(hw_s))
        add("COLOUR", str(q.get("colour") or line.get("colour") or "").replace("_", " "))
        add("AREA", f"{q.get('areaSqft') or 0} Sq.Ft. · qty {line.get('qty') or q.get('qty') or 1}")
        sale_u = str(q.get("saleUnit") or line.get("saleUnit") or "sqft").upper()
        add("AMOUNT", f"{_money(q.get('sellingPerUnit') or line.get('sellingRate') or 0)} / {sale_u} → "
            f"{_money(q.get('sellingTotal') or line.get('commercialTotal') or 0)}")
        return rows

    title = str(line.get("description") or line.get("displayName") or line.get("product") or "Window")
    add("", title)
    add("SIZE", f"{_mm(w)} × {_mm(h)} mm")
    add("AREA", f"{_area_sqft(w, h)} Sq.Ft.")

    glass_n = (
        (layout or {}).get("glassCount")
        or opts.get("glassShutters")
        or opts.get("glassCount")
        or line.get("glassShutters")
    )
    mesh_n = (layout or {}).get("meshCount") or opts.get("meshShutters") or opts.get("meshCount") or 0
    opening = (layout or {}).get("opening") or opts.get("opening") or ""
    try:
        glass_n_i = int(float(glass_n)) if glass_n is not None else 0
    except (TypeError, ValueError):
        glass_n_i = 0
    if glass_n_i <= 0:
        panels_tmp = list((layout or {}).get("panels") or [])
        glass_n_i = sum(1 for p in panels_tmp if str(p.get("role") or "").lower() in ("sliding", "glass", "openable", ""))
        if glass_n_i <= 0 and panels_tmp:
            glass_n_i = len(panels_tmp)
    if glass_n_i > 0:
        shut = f"{glass_n_i} Nos"
        if opening:
            shut += f" · opening {opening}"
        try:
            if int(float(mesh_n or 0)) > 0:
                shut += f" · mesh {int(float(mesh_n))} Nos"
        except (TypeError, ValueError):
            pass
        add("SHUTTER", shut)

    joint_bits: list[str] = []
    if section.get("interlock"):
        joint_bits.append(str(section["interlock"]))
    if section.get("meeting"):
        joint_bits.append(f"Meeting {section['meeting']}")
    jt = opts.get("jointTypes") or line.get("jointTypes") or []
    if isinstance(jt, (list, tuple)):
        for j in jt:
            if j and str(j).strip():
                joint_bits.append(str(j).replace("_", " ").title())
    elif jt:
        joint_bits.append(str(jt).replace("_", " ").title())
    if joint_bits:
        add("JOINT", " · ".join(joint_bits))
    elif section.get("sash"):
        add("JOINT", f"Sash {section['sash']}")

    # Panel mm / A1 A2 / shutter sides stay on the design drawing only.
    if weight is not None and float(weight or 0) > 0:
        add("WEIGHT", f"{weight} kg")

    specs_in = line.get("specifications") if isinstance(line.get("specifications"), Mapping) else {}
    alloy = (
        specs_in.get("alloy")
        or specs_in.get("aluminiumAlloy")
        or opts.get("alloy")
        or opts.get("aluminiumAlloy")
        or line.get("alloy")
        or section.get("alloy")
    )
    alu_brand = (
        specs_in.get("aluminiumBrand")
        or specs_in.get("profileBrand")
        or specs_in.get("powderCoatingBrand")
        or opts.get("aluminiumBrand")
        or section.get("brand")
    )

    glass = line.get("glass")
    if not (isinstance(glass, list) and glass):
        glass = opts.get("glass") or glass
    gspec = line.get("glassSpec") if isinstance(line.get("glassSpec"), Mapping) else {}
    if isinstance(glass, list) and glass:
        g0 = glass[0] if isinstance(glass[0], Mapping) else {}
        thick = g0.get("thicknessMm") or g0.get("thickness_mm") or gspec.get("thicknessMm") or gspec.get("overallMm")
        gname = g0.get("name") or gspec.get("name") or ""
        gcolour = g0.get("colour") or g0.get("color") or opts.get("glassColour") or gspec.get("colour") or ""
        gbrand = g0.get("brand") or opts.get("glassBrand") or gspec.get("brand") or ""
        makeup = str(g0.get("makeup") or gspec.get("makeup") or g0.get("kind") or "").lower()
        makeup_lbl = g0.get("makeupLabel") or gspec.get("makeupLabel") or ""
        lam = _laminated_config_label(thick, makeup or gname)
        if not lam and "+" in str(makeup_lbl):
            lam = str(makeup_lbl).replace("PVB", "").replace("A+", "+").strip()
            if lam and not lam.lower().endswith("mm"):
                lam = f"{lam}mm" if "+" in lam else lam
        bits = []
        if thick not in (None, ""):
            bits.append(f"{thick:g} mm" if isinstance(thick, (int, float)) else f"{thick} mm")
        if lam:
            bits.append(str(lam))
        if gname and str(gname).lower() not in " ".join(str(b).lower() for b in bits):
            bits.append(str(gname))
        if gcolour:
            bits.append(f"colour {gcolour}")
        if gbrand:
            bits.append(str(gbrand))
        if bits:
            add("GLASS", " · ".join(bits))
    elif isinstance(glass, str) and glass.strip():
        raw_g = str(glass).replace("_", " ")
        if "@" in raw_g:
            raw_g = raw_g.split("@")[0].strip()
        add("GLASS", raw_g)

    hw = line.get("hardware") or opts.get("hardware") or []
    if isinstance(hw, list) and hw:
        hw_bits = []
        for h in hw[:8]:
            if isinstance(h, Mapping):
                nm = h.get("name") or h.get("item") or h.get("label")
                if nm:
                    bit = str(nm)
                    if h.get("colour") or h.get("color"):
                        bit += f" · colour {h.get('colour') or h.get('color')}"
                    hw_bits.append(bit)
            elif h:
                hw_bits.append(str(h))
        if hw_bits:
            add("HARDWARE", " · ".join(hw_bits))

    try:
        from WEOS.factory.panel_fills import fill_spec_rows, panel_fill_from_line

        for lab, val in fill_spec_rows(panel_fill_from_line(line)):
            add(lab, val)
    except Exception:
        try:
            from WEOS.factory.panel_fills import fill_spec_lines, panel_fill_from_line

            for s in fill_spec_lines(panel_fill_from_line(line)):
                if ":" in s:
                    lab, _, rest = s.partition(":")
                    add(lab.strip(), rest.strip())
                elif "=" in s:
                    lab, _, rest = s.partition("=")
                    add(lab.strip(), rest.strip())
                else:
                    add("FILL", s)
        except Exception:
            pass

    colour = opts.get("colour") or line.get("colour")
    pc_name = opts.get("powderCoatName") or line.get("powderCoatName")
    if pc_name and str(pc_name).strip():
        add("COLOUR", str(pc_name))
    elif colour:
        add("COLOUR", str(colour).replace("_", " ").title())
    if section.get("seriesTitle"):
        add("SERIES", section["seriesTitle"])

    system = str((layout or {}).get("system") or opts.get("system") or line.get("productType") or "").lower()
    is_bifold = system in ("bifold", "fold", "fold_sliding", "fold_and_sliding") or (
        str((layout or {}).get("kind") or "") == "fold_and_sliding"
    )
    is_casement = system in ("casement", "openable", "opening", "casements")
    fl = (layout or {}).get("foldLeft")
    fr = (layout or {}).get("foldRight")
    if fl is None:
        fl = opts.get("foldLeft")
    if fr is None:
        fr = opts.get("foldRight")

    tc = layout.get("trackCount") if layout else None
    if not is_bifold and not is_casement:
        if tc and section.get("track"):
            add("TRACK", f"{section['track']} (using {float(tc):g}-track)")
        elif section.get("track"):
            add("TRACK", str(section["track"]))
        elif tc:
            add("TRACK", f"{float(tc):g}-track")
    if section.get("sash"):
        add("SASH", str(section["sash"]))
    if section.get("interlock"):
        add("INTERLOCK", str(section["interlock"]))
    handle = opts.get("handle")
    handle_name = opts.get("handleName") or line.get("handleName")
    handle_finish = opts.get("handleFinish") or line.get("handleFinish") or opts.get("handleColour")
    handle_brand = opts.get("handleBrand") or line.get("handleBrand") or specs_in.get("hardwareBrand")
    if handle_name or handle or handle_brand:
        hbits = [str(handle_name or (str(handle).replace("_", " ").title() if handle else "")).strip()]
        if handle_brand:
            hbits.append(str(handle_brand))
        if handle_finish:
            hbits.append(f"colour {handle_finish}")
        add("HANDLE", " · ".join(x for x in hbits if x))
    mesh_name = opts.get("meshName") or line.get("meshName")
    mesh_brand = opts.get("meshBrand") or line.get("meshBrand")
    mesh_colour = opts.get("meshColour") or opts.get("meshColor") or line.get("meshColour")
    mesh_on = bool((layout or {}).get("mesh") or (opts or {}).get("mesh") or (int(float(mesh_n or 0)) if mesh_n not in (None, "") else 0))
    mesh_bits = ["yes" if mesh_on else "no"]
    if mesh_name and mesh_on:
        mesh_bits.append(str(mesh_name))
    if mesh_brand:
        mesh_bits.append(str(mesh_brand))
    if mesh_colour:
        mesh_bits.append(f"colour {mesh_colour}")
    add("MESH", " · ".join(mesh_bits))
    if alloy:
        add("ALLOY", str(alloy))
    alu_bits = []
    if alu_brand:
        alu_bits.append(str(alu_brand))
    if pc_name:
        alu_bits.append(str(pc_name))
    elif colour:
        alu_bits.append(str(colour).replace("_", " ").title())
    if section.get("seriesTitle"):
        alu_bits.insert(0, str(section["seriesTitle"]))
    if alu_bits:
        add("ALUMINIUM", " · ".join(alu_bits))
    if system == "grid":
        add("TYPE", "Partition grid (per-cell fix/sliding/openable)")
    elif system == "casement":
        add("TYPE", "Casement / Openable")
    elif is_bifold:
        cfg = f"{int(fl or 0)}+{int(fr or 0)}"
        add("TYPE", f"Fold & Sliding ({cfg})")
        add("FOLD", f"{cfg} (left + right leaves)")

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
            add("SECTIONS", " · ".join(bits))

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
                    "trackCount": sec.get("trackCount"),
                }
            )
    try:
        tc_f = float(tc) if tc is not None else float(opts.get("trackCount") or 0) or None
    except (TypeError, ValueError):
        tc_f = None
    filtered: list[Mapping[str, Any]] = []
    for sec in detail_rows:
        if not isinstance(sec, Mapping):
            continue
        use = str(sec.get("use") or sec.get("usage") or "").lower()
        if use in ("sash", "interlock", "meeting", "shutter"):
            filtered.append(sec)
            continue
        if "track" in use or use in ("frame", "outer"):
            stc = sec.get("trackCount")
            if tc_f is None or stc is None:
                filtered.append(sec)
            else:
                try:
                    if abs(float(stc) - tc_f) < 0.05:
                        filtered.append(sec)
                except (TypeError, ValueError):
                    filtered.append(sec)
        elif not use:
            filtered.append(sec)
    if not filtered:
        filtered = [s for s in detail_rows if isinstance(s, Mapping)]
    for sec in filtered[:10]:
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
            bits.append(
                f"std {sec['stdLengthMm']:g} mm"
                if isinstance(sec["stdLengthMm"], (int, float))
                else f"std {sec['stdLengthMm']}"
            )
        add("SECTION", " · ".join(bits))

    notes = (layout or {}).get("notes") or []
    for note in notes[:3]:
        if note:
            add("NOTE", note)
    return rows


def _spec_lines(line: Mapping[str, Any], *, audience: str = "customer") -> list[str]:
    """Flat string form of specs (smoke tests / legacy). Prefer ``_spec_rows`` for PDF."""
    out: list[str] = []
    for label, value in _spec_rows(line, audience=audience):
        if label:
            out.append(f"{label}: {value}")
        else:
            out.append(value)
    return out


def _draw_spec_rows(
    c,
    rows: list[tuple[str, str]],
    *,
    x: float,
    y: float,
    max_width: float,
    set_font,
    font_size: float = 7.0,
    label_col: float = 72.0,
    line_h: float = 10.0,
) -> float:
    """Draw aligned LABEL: / value columns; returns y after last line."""
    value_x = x + label_col
    value_w = max(36.0, max_width - label_col)
    sy = y
    for label, value in rows[:22]:
        lab = f"{label}:" if label else ""
        if lab:
            set_font(c, font_size, bold=True)
            c.drawString(x, sy, lab)
            set_font(c, font_size)
            wrapped = _wrap_text(c, value, value_w, font_size) or [""]
            c.drawString(value_x, sy, wrapped[0])
            sy -= line_h
            for cont in wrapped[1:]:
                set_font(c, font_size)
                c.drawString(value_x, sy, cont)
                sy -= line_h
        else:
            set_font(c, font_size, bold=True)
            wrapped = _wrap_text(c, value, max_width, font_size, bold=True) or [""]
            for i, wl in enumerate(wrapped):
                set_font(c, font_size, bold=True)
                c.drawString(x, sy, wl)
                sy -= line_h
                if i >= 2:
                    break
            sy -= 3.5  # small heading-to-heading gap (not a wall of text)
    return sy


def _measure_spec_rows(
    c,
    rows: list[tuple[str, str]],
    *,
    max_width: float,
    font_size: float = 7.0,
    label_col: float = 72.0,
    line_h: float = 10.0,
) -> float:
    """Estimate vertical space for tabular specs."""
    value_w = max(36.0, max_width - label_col)
    lines = 0
    extra = 0.0
    for label, value in rows[:22]:
        if label:
            wrapped = _wrap_text(c, value, value_w, font_size) or [""]
            lines += len(wrapped)
        else:
            wrapped = _wrap_text(c, value, max_width, font_size, bold=True) or [""]
            lines += min(len(wrapped), 3)
            extra += 3.5
    return max(lines * line_h + extra, 24.0)


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

    def _draw_logo(cx: float, top_y: float, max_w: float, max_h: float) -> tuple[float, float]:
        """Draw company logo if configured. Returns (drawn_width, drawn_height)."""
        if not logo_path:
            return 0.0, 0.0
        try:
            from reportlab.lib.utils import ImageReader

            lp = str(logo_path)
            if lp.lower().endswith(".svg"):
                from WEOS.factory.image_engine import svg_to_png_bytes

                png = svg_to_png_bytes(open(lp, "r", encoding="utf-8").read(), scale=1.0)
                if not png:
                    return 0.0, 0.0
                img = ImageReader(io.BytesIO(png))
            else:
                img = ImageReader(lp)
            iw, ih = img.getSize()
            if iw <= 0 or ih <= 0:
                return 0.0, 0.0
            scale = min(max_w / float(iw), max_h / float(ih))
            dw, dh = iw * scale, ih * scale
            c.drawImage(img, cx, top_y - dh, width=dw, height=dh, mask="auto")
            return dw, dh
        except Exception:
            return 0.0, 0.0

    # —— Cover letter page ——
    M = MARGIN
    # Logo — compact gap to company text (actual drawn width + 10pt, not a fixed 205pt).
    logo_w, logo_h = _draw_logo(M, H - M, 120, 64)
    text_x = M + ((logo_w + 10) if logo_h else 0)
    name_avail = (W - M) - text_x  # keep company name inside the right margin
    c.setFillColorRGB(*primary)
    _draw_fit(c, company, text_x, H - 48, name_avail, 16, bold=True, minimum=10)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    set_font(c, 8)
    c.drawString(text_x, H - 62, (branding.get("tagline") or "Windows and Doors Quotation")[:90])
    header_extra = H - 74
    if address:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        for al in _wrap_text(c, address, name_avail, 8):
            c.drawString(text_x, header_extra, al)
            header_extra -= 10
    contact_bits = " · ".join(x for x in (phone, email, website) if x)
    if contact_bits:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        for cl in _wrap_text(c, contact_bits, name_avail, 8):
            c.drawString(text_x, header_extra, cl)
            header_extra -= 10
    if gst:
        set_font(c, 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(text_x, header_extra, f"GSTIN: {gst}")
        header_extra -= 11
    # Divider under the company header so the cover never reads as "blank".
    header_bottom = min(H - 96, header_extra - 6, (H - M - logo_h - 8) if logo_h else H - 96)
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
    # Company address lives in the letterhead only — do not repeat at cover bottom.
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
    # Keep descriptions clear of the QTY column (right-edge of wrapped text).
    spec_max_w = max(80.0, col_qty - col_spec - 14)

    def header(page_no: int):
        c.setFillColorRGB(*primary)
        _draw_fit(c, company, M, H - M, (col_qty - 40) - M, 12, bold=True, minimum=8)
        set_font(c, 8)
        c.setFillColorRGB(0.25, 0.25, 0.25)
        c.drawRightString(W - M, H - (M - 4), f"Quote No. {qid}")
        c.drawRightString(W - M, H - (M + 8), f"Quote Date {qdate}")
        # Cover page already has a single "Updated on" date — do not reprint it
        # here (the header rule sat on the divider and looked like a strike-through).
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

    # Elevation cell — tall enough for canvas SVG (plan + elevation) without stubbing.
    draw_w, draw_h = 200, 210
    bottom_limit = M + 30  # keep clear of footer + bottom margin

    for idx, line in enumerate(lines):
        # Specs first so we know how tall the text block is (wrap may exceed draw_h).
        try:
            spec_rows = _spec_rows(line)
        except Exception:
            _log.exception("marqt spec build failed for line %d; using name only", idx)
            spec_rows = [("", str(line.get("displayName") or line.get("product") or "Window"))]
        text_h = _measure_spec_rows(c, spec_rows, max_width=spec_max_w, font_size=7.0, label_col=72.0)
        need = max(draw_h, text_h) + 24
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

        # Specs — tabular LABEL: / value; never overflow into QTY/RATE/AMOUNT
        c.setFillColorRGB(0, 0, 0)
        sy = _draw_spec_rows(
            c,
            spec_rows,
            x=col_spec,
            y=y,
            max_width=spec_max_w,
            set_font=set_font,
            font_size=7.0,
            label_col=72.0,
        )

        # Qty / Rate / Amount — currency symbol via Unicode font
        set_font(c, 8)
        c.drawRightString(col_qty, y, str(qty))
        rate_str = f"{float(rate):,.2f}" if rate is not None else "—"
        c.drawRightString(col_rate, y, rate_str)
        set_font(c, 8, bold=True)
        c.drawRightString(col_amt, y, f"{float(amount):,.2f}")

        # row separator
        row_bottom = min(sy - 2, y - draw_h - 10)
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
