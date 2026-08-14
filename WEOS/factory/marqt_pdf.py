"""MAR-QT-style customer quotation PDF — drawings with W/H callouts + detail specs.

DESIGN column: uploaded photo, else the live-canvas SVG (same as ``#livePreview``),
sanitized + pixel-normalized then rasterized. Never a dumbed-down schematic stub.
"""

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


def _flow_paragraphs(
    c,
    text: str,
    *,
    x: float,
    y: float,
    max_width: float,
    font_size: float,
    line_h: float,
    bottom: float,
    set_font,
    on_new_page,
    para_gap: float = 4.0,
    bold: bool = False,
) -> float:
    """Draw wrapping paragraphs; call on_new_page() when y hits bottom. Returns y."""
    for para in str(text or "").split("\n"):
        words = para.split()
        if not words:
            y -= para_gap
            if y < bottom:
                y = on_new_page()
            continue
        line = ""
        set_font(c, font_size, bold=bold)
        for word in words:
            trial = (line + " " + word).strip()
            try:
                too_wide = c.stringWidth(trial, c._fontname, font_size) > max_width
            except Exception:
                too_wide = len(trial) * (font_size * 0.5) > max_width
            if too_wide and line:
                if y < bottom:
                    y = on_new_page()
                    set_font(c, font_size, bold=bold)
                c.drawString(x, y, line)
                y -= line_h
                line = word
            else:
                line = trial
        if line:
            if y < bottom:
                y = on_new_page()
                set_font(c, font_size, bold=bold)
            c.drawString(x, y, line)
            y -= line_h
        y -= para_gap
    return y


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


def line_elevation_png_bytes(line: Mapping[str, Any], *, scale: float = 0.55, max_px: int | None = 220) -> bytes | None:
    """PNG of the customer design column (photo or canvas SVG) for Excel embed.

    Thumbnails by default — full-res embeds made Excel export very slow.
    Does not change PDF layout — same sources as ``draw_line_elevation``.
    """
    try:
        from WEOS.factory.elevation_cache import png_for_line

        return png_for_line(line, scale=scale, max_px=max_px)
    except Exception:
        _log.debug("excel elevation png skipped", exc_info=True)
        return None


# A4 DESIGN cell ~200×210 pt. Cap rasters so 40–100 page quotes do not RIP-hang.
# 720 keeps shower/railing canvas readable without Cairo exploding mm viewBoxes.
_PDF_ELEV_MAX_PX = 720


def _line_canvas_svg(line: Mapping[str, Any]) -> str:
    """Live canvas SVG: keep ``preview.svg`` or regenerate from the designer engine."""
    prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
    live = str((prev or {}).get("svg") or (prev or {}).get("pdfSvg") or "").strip()
    if live and "<svg" in live.lower():
        return live
    try:
        from WEOS.factory.svg_export import elevation_svg_for_line

        svg = elevation_svg_for_line(line, style="preview") or ""
        return str(svg) if svg and "<svg" in str(svg).lower() else ""
    except Exception:
        _log.debug("canvas svg rebuild skipped", exc_info=True)
        return ""


def _usable_png(png: bytes | None) -> bytes | None:
    if not png:
        return None
    try:
        from WEOS.factory.image_engine import png_has_ink

        if not png_has_ink(png):
            return None
    except Exception:
        pass
    return png


def _draw_special_reportlab(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    """Last-resort schematic only when no canvas SVG exists."""
    from WEOS.factory.line_kind import is_railing_cart_line, is_shower_cart_line, is_ventilator_cart_line

    try:
        if is_railing_cart_line(line):
            from WEOS.factory.railing_pdf import draw_railing_elevation

            return bool(draw_railing_elevation(c, line, x, y, box_w, box_h))
        if is_shower_cart_line(line):
            from WEOS.factory.shower_pdf import draw_shower_elevation

            return bool(draw_shower_elevation(c, line, x, y, box_w, box_h))
        if is_ventilator_cart_line(line):
            from WEOS.factory.ventilator_pdf import draw_ventilator_elevation

            return bool(draw_ventilator_elevation(c, line, x, y, box_w, box_h))
    except Exception:
        _log.exception("special ReportLab elevation failed")
    return False


def _embed_rl_drawing(c, drawing, x: float, y: float, box_w: float, box_h: float) -> bool:
    """Place a svglib Drawing into the DESIGN cell, letterboxed."""
    try:
        from reportlab.graphics import renderPDF
    except Exception:
        return False
    dw = float(getattr(drawing, "width", 0) or 0)
    dh = float(getattr(drawing, "height", 0) or 0)
    if dw <= 1 or dh <= 1:
        return False
    scale = min(box_w / dw, box_h / dh)
    c.saveState()
    try:
        c.translate(x + (box_w - dw * scale) / 2.0, y + (box_h - dh * scale) / 2.0)
        c.scale(scale, scale)
        renderPDF.draw(drawing, c, 0, 0)
    finally:
        c.restoreState()
    return True


def _draw_canvas_svg(c, svg: str, x: float, y: float, box_w: float, box_h: float) -> bool:
    """Print the live-canvas SVG: sanitized + pixel-normalized PNG, else svglib vectors."""
    raw = str(svg or "").strip()
    if not raw or "<svg" not in raw.lower():
        return False
    png = None
    try:
        from WEOS.factory.image_engine import svg_to_png_bytes

        png = _usable_png(
            svg_to_png_bytes(raw, scale=1.15, allow_slow=False, max_px=float(_PDF_ELEV_MAX_PX))
        )
        if not png:
            png = _usable_png(
                svg_to_png_bytes(raw, scale=1.0, allow_slow=True, max_px=min(float(_PDF_ELEV_MAX_PX), 720.0))
            )
    except Exception:
        _log.debug("canvas svg rasterize skipped", exc_info=True)
        png = None
    if png:
        try:
            if _embed_png(c, png, x, y, box_w, box_h):
                return True
        except Exception:
            _log.exception("canvas png embed failed")
    try:
        from WEOS.factory.image_engine import svg_to_rl_drawing

        drawing = svg_to_rl_drawing(raw)
        if drawing is not None and _embed_rl_drawing(c, drawing, x, y, box_w, box_h):
            return True
    except Exception:
        _log.debug("canvas svg vector embed skipped", exc_info=True)
    return False


def _embed_png(c, png: bytes, x: float, y: float, box_w: float, box_h: float) -> bool:
    from reportlab.lib.utils import ImageReader

    img = ImageReader(io.BytesIO(png))
    iw, ih = img.getSize()
    if iw <= 0 or ih <= 0:
        return False
    scale = min(box_w / float(iw), box_h / float(ih))
    dw, dh = iw * scale, ih * scale
    c.drawImage(img, x + (box_w - dw) / 2.0, y + (box_h - dh) / 2.0, width=dw, height=dh, mask="auto")
    return True


def draw_line_elevation(c, line: Mapping[str, Any], x: float, y: float, box_w: float, box_h: float) -> bool:
    """DESIGN column: uploaded photo, else #livePreview SVG, else schematic.

    Railing / shower / ventilator MUST print the canvas SVG (sanitized +
    pixel-normalized) when it exists. Never a dumbed-down ReportLab drawing
    in that case. Windows keep the existing ReportLab model drawer.
    """
    from WEOS.factory.line_kind import (
        is_louver_cart_line,
        is_railing_cart_line,
        is_shower_cart_line,
        is_ventilator_cart_line,
    )

    w = float(line.get("width") or 0)
    h = float(line.get("height") or 0)
    try:
        c.setDash()
    except Exception:
        pass

    photo_raw, _photo_ct = _line_design_photo_bytes(line)
    if photo_raw:
        try:
            from WEOS.factory.elevation_cache import _resize_png

            thumb = _resize_png(photo_raw, max_px=_PDF_ELEV_MAX_PX) or photo_raw
            if _embed_png(c, thumb, x, y, box_w, box_h):
                return True
        except Exception:
            try:
                if _embed_png(c, photo_raw, x, y, box_w, box_h):
                    return True
            except Exception:
                _log.exception("design photo embed failed; falling back to canvas SVG")

    special = (
        is_railing_cart_line(line)
        or is_shower_cart_line(line)
        or is_ventilator_cart_line(line)
        or is_louver_cart_line(line)
    )
    if special:
        svg = _line_canvas_svg(line)
        if svg:
            if _draw_canvas_svg(c, svg, x, y, box_w, box_h):
                return True
            _log.warning("canvas SVG present but PDF embed failed; not using schematic")
            return False
        if _draw_special_reportlab(c, line, x, y, box_w, box_h):
            return True
        return False

    try:
        from WEOS.factory.elevation_pdf import draw_line_model_elevation

        if draw_line_model_elevation(c, line, x, y, box_w, box_h):
            return True
    except Exception:
        _log.exception("reportlab model elevation failed")

    layout = line.get("layout") if isinstance(line.get("layout"), Mapping) else {}
    panels = list((layout or {}).get("panels") or [])
    track_count = max(len(panels), 2)
    draw_window_elevation(c, x, y, box_w, box_h, w, h, track_count=track_count)
    return False


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
    from WEOS.factory.line_kind import is_railing_cart_line
    from WEOS.factory.railing_pdf import railing_cfg_and_quote

    if is_railing_cart_line(line):
        rail_cfg, q = railing_cfg_and_quote(line)
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
            bar_ft = q.get("handrailBarLengthFt") or (rail_cfg or {}).get("handrailBarLengthFt")
            if bar_ft:
                try:
                    hr_bits.append(f"bar {float(bar_ft):g} ft")
                except (TypeError, ValueError):
                    hr_bits.append(f"bar {bar_ft} ft")
            add("HANDRAIL", " · ".join(str(x) for x in hr_bits if x))

        thk = q.get("glassThicknessMm") or (rail_cfg or {}).get("glassThicknessMm")
        from WEOS.factory.quote_item_snapshot import get_glass_snapshot, glass_display_label

        rail_glass = get_glass_snapshot(line)
        glass_val = glass_display_label(rail_glass) if rail_glass else ""
        if not glass_val:
            gtype = (rail_cfg or {}).get("glassType") or q.get("glassType") or ""
            gcol = (rail_cfg or {}).get("glassColour") or q.get("glassColour") or ""
            from WEOS.factory.quote_item_snapshot import build_glass_snapshot

            rebuilt = build_glass_snapshot(line, railing=True)
            glass_val = glass_display_label(rebuilt)
            if not glass_val:
                if thk in (None, ""):
                    thk = 12
                glass_bits = [f"{float(thk):g} mm"]
                if gtype and "lam" not in str(gtype).lower():
                    glass_bits.append(str(gtype))
                if gcol and str(gcol).lower() not in str(gtype).lower():
                    glass_bits.append(str(gcol))
                glass_val = " · ".join(str(b) for b in glass_bits if b) or "—"
        # Never prepend a rounded mm ("12 mm · 5+1.52+5") onto a laminated label.
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
        br = _bom("bottomRail") or {}
        hr = _bom("handrail") or {}
        gl = _bom("glass") or {}
        mb = _bom("modularBend") or {}
        b180 = _bom("connector180") or {}
        cap = _bom("endCap") or {}
        def _qty(row, fallback=0):
            if row.get("qty") not in (None, ""):
                return row.get("qty")
            return fallback
        hw_bits.append(f"Bottom {_qty(br, q.get('lengthRft') or 0)} {br.get('unit') or 'rft'}")
        hw_bits.append(f"Handrails {_qty(hr, q.get('lengthRft') or 0)} {hr.get('unit') or 'rft'}")
        hw_bits.append(f"Glass {q.get('panelCount') or 0}")
        hw_bits.append(f"Modular band {_qty(mb, q.get('bendCount') or q.get('connector90Count') or 0)}")
        hw_bits.append(f"180° band {_qty(b180, q.get('connector180Count') or 0)}")
        hw_bits.append(f"End cap {_qty(cap, q.get('endCapCount') or 0)}")
        if q.get("anchorCount"):
            hw_bits.append(f"anchors {q.get('anchorCount') or 0}")
        asp = q.get("anchorSpacingFt") or (rail_cfg or {}).get("anchorSpacingFt")
        if asp and (bottom_kind in ("continuous", "rail") or q.get("continuousRail")):
            try:
                hw_bits.append(f"every {float(asp):g} ft")
            except (TypeError, ValueError):
                hw_bits.append(f"every {asp} ft")
        epdm_h = _bom("epdmHandrail") or {}
        epdm_b = _bom("epdmBottom") or {}
        epdm_hr_q = epdm_h.get("qty") or q.get("epdmHandrailRft")
        epdm_br_q = epdm_b.get("qty") or q.get("epdmBottomRft")
        if epdm_hr_q:
            hw_bits.append(f"EPDM handrail {epdm_hr_q} rft")
        if epdm_br_q:
            hw_bits.append(f"EPDM bottom {epdm_br_q} rft")
        if q.get("wallConnectors"):
            hw_bits.append(f"wall connectors {q.get('wallConnectors')}")
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
                f" · floor {sg.get('floorHeightMm') or (rail_cfg or {}).get('floorHeightMm') or '—'} mm"
                f" · {sg.get('flightCount') or len(q.get('runs') or []) or 1} floor(s)",
            )
            for run in (q.get("runs") or sg.get("flights") or []):
                if not isinstance(run, Mapping):
                    continue
                method = str(run.get("sizeMethod") or "")
                turn = str(run.get("turn") or "none")
                bits = [
                    str(run.get("label") or f"Floor {(run.get('index') or 0) + 1}"),
                    method,
                    f"H {run.get('floorHeightMm') or '—'} mm",
                    f"run {run.get('horizontalMm') or '—'} mm",
                    f"slope {run.get('slopeLengthMm') or run.get('lengthMm') or '—'} mm",
                    f"{run.get('panels') or 0} glass",
                ]
                if turn not in ("none", "", "end"):
                    bits.append(f"{int(round(float(run.get('turnDeg') or 180)))}° {turn}")
                add("FLOOR", " · ".join(str(b) for b in bits if b))
            if sg.get("riseMismatch"):
                add("NOTE", str(sg.get("riseMismatchMessage") or "Rise mismatch vs floor height"))
        runs_n = q.get("runs") if isinstance(q.get("runs"), list) else []
        if shape != "staircase" and len(runs_n) > 1:
            for run in runs_n:
                if not isinstance(run, Mapping):
                    continue
                turn = str(run.get("turn") or "none")
                bits = [
                    str(run.get("label") or "Span"),
                    f"{run.get('lengthMm') or 0} mm",
                    f"{run.get('panels') or 0} glass",
                ]
                if turn not in ("none", "", "end"):
                    bits.append(f"{int(round(float(run.get('turnDeg') or 90)))}° {turn}")
                add("SPAN", " · ".join(str(b) for b in bits))
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

    from WEOS.factory.line_kind import is_shower_cart_line, is_ventilator_cart_line
    if is_ventilator_cart_line(line):
        opts_v = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        cfg_v = opts_v.get("ventilator") if isinstance(opts_v, Mapping) else None
        cfg_v = dict(cfg_v) if isinstance(cfg_v, Mapping) else {}
        qv = opts_v.get("ventilatorQuote") if isinstance(opts_v, Mapping) else None
        if not isinstance(qv, Mapping):
            qv = line.get("ventilator") if isinstance(line.get("ventilator"), Mapping) else {}
        if (not qv or not qv.get("widthMm")) and cfg_v:
            try:
                from WEOS.factory.ventilator_engine import compute_ventilator, ensure_ventilator_dims

                qv = compute_ventilator(ensure_ventilator_dims(cfg_v, width=w or None, height=h or None))
            except Exception:
                qv = qv if isinstance(qv, Mapping) else {}
        from WEOS.factory.ventilator_engine import format_ventilator_description

        add("", format_ventilator_description(qv, cfg_v))
        add("TYPE", "Bathroom ventilator"
            + (f" · {qv.get('mode')}" if qv.get("mode") else ""))
        add("SIZE", f"{_mm(qv.get('widthMm') or w)} × {_mm(qv.get('heightMm') or h)} mm")
        add("PROFILE", f"outer {qv.get('outerProfile') or '25×40'}"
            + (f" · sash {qv.get('sashProfile')}" if qv.get('remainFill') == 'top_hung' or qv.get('mode') == 'split' else "")
            + (f" · mullion {qv.get('mullionProfile')}" if qv.get("mode") == "split" else ""))
        add("GLASS", qv.get("glassLabel") or f"{qv.get('glassThicknessMm') or 5} mm {qv.get('glassColour') or 'frosted'}")
        add("COLOUR", str(qv.get("colour") or line.get("colour") or "").replace("_", " "))
        layout_bits = []
        if qv.get("mode") == "full_cutout":
            layout_bits.append(f"full glass · fan cut-out Ø{_mm(qv.get('fanDiameterMm') or 200)} mm")
        else:
            layout_bits.append(f"{qv.get('louversSide') or 'left'} {(qv.get('louversFill') or 'glass').replace('_', ' ')}")
            layout_bits.append(f"remain {(qv.get('remainFill') or 'top_hung').replace('_', ' ')}")
            if qv.get("exhaust"):
                layout_bits.append(f"exhaust Ø{_mm(qv.get('fanDiameterMm') or 200)} mm · {qv.get('exhaustSide') or 'center'}")
        add("LAYOUT", " · ".join(layout_bits))
        hw_v = []
        if qv.get("hardwareBrand"):
            hw_v.append(str(qv.get("hardwareBrand")))
        if qv.get("hardwareOrigin"):
            hw_v.append(str(qv.get("hardwareOrigin")))
        if qv.get("handle"):
            hw_v.append(f"handle {qv.get('handleName') or 'D-type'} (bottom)")
        if qv.get("hingeCount"):
            hw_v.append(f"{qv.get('hingeType') or 'casement'} ×{qv.get('hingeCount')} (top)")
        if hw_v:
            add("HARDWARE", " · ".join(hw_v))
        add("SIDE", str(qv.get("louversSide") or qv.get("exhaustSide") or "—"))
        add("AREA", f"{qv.get('areaSqft') or 0} Sq.Ft.")
        sale_uv = str(qv.get("saleUnit") or line.get("saleUnit") or "sqft").upper()
        add("RATE", f"{_money(qv.get('sellingPerUnit') or line.get('sellingRate') or 0)} / {sale_uv}")
        add("AMOUNT", f"{_money(qv.get('sellingTotal') or line.get('commercialTotal') or 0)}")
        add("QTY", str(line.get("qty") or qv.get("qty") or 1))
        if factory:
            for it in qv.get("items") or []:
                if not isinstance(it, Mapping):
                    continue
                add("BOM", f"{it.get('label') or it.get('key')} · {it.get('qty')} {it.get('unit')} @ {it.get('rate')} = {it.get('amount')}")
        return rows

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
            + (f" · {q.get('frameKind')}" if q.get("frameKind") else
               (f" · chokhat {q.get('chokhat')}" if q.get("chokhat") else " · frameless")))
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
            hw_s.append(f"{q.get('hingeType') or 'casement'} ×{q.get('hingesPerDoor')}/door")
        add("HARDWARE", " · ".join(hw_s))
        add("COLOUR", str(q.get("colour") or line.get("colour") or "").replace("_", " "))
        add("AREA", f"{q.get('areaSqft') or 0} Sq.Ft. · qty {line.get('qty') or q.get('qty') or 1}")
        sale_u = str(q.get("saleUnit") or line.get("saleUnit") or "sqft").upper()
        add("AMOUNT", f"{_money(q.get('sellingPerUnit') or line.get('sellingRate') or 0)} / {sale_u} → "
            f"{_money(q.get('sellingTotal') or line.get('commercialTotal') or 0)}")
        return rows

    from WEOS.factory.line_kind import is_louver_cart_line

    if is_louver_cart_line(line):
        from WEOS.factory.quote_item_snapshot import get_item_snapshot, get_glass_snapshot, glass_display_label

        snap = get_item_snapshot(line)
        title = str(
            (snap or {}).get("product_name_snapshot")
            or line.get("displayName")
            or line.get("description")
            or "Louvers"
        )
        add("", title)
        add("CATEGORY", str((snap or {}).get("category_snapshot") or line.get("category") or "Louvers"))
        add("SIZE", f"{_mm(w)} × {_mm(h)} mm")
        add("QTY", str(line.get("qty") or line.get("quantity") or 1))
        opts_l = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        fill_type = "louvers"
        try:
            from WEOS.factory.panel_fills import fill_spec_rows, panel_fill_from_line

            fill = panel_fill_from_line(line) or {}
            fill_type = str(fill.get("fillType") or "louvers")
            if fill_type in ("", "glass"):
                fill = {**fill, "fillType": "louvers"}
                fill_type = "louvers"
            for lab, val in fill_spec_rows(fill):
                add(lab, val)
        except Exception:
            pass
        opted_glass = bool(line.get("glass") or (opts_l or {}).get("glass")) and fill_type == "glass"
        if opted_glass:
            gs = get_glass_snapshot(line)
            if gs and glass_display_label(gs):
                add("GLASS", glass_display_label(gs))
        handle = line.get("handle") or (opts_l or {}).get("handle")
        if handle:
            add("HANDLE", str(handle).replace("_", " "))
        gs_n = line.get("glassShutters") or (opts_l or {}).get("glassShutters")
        if gs_n not in (None, "", 0, "0"):
            add("SHUTTER", f"{gs_n} Nos")
        return rows

    from WEOS.factory.window_specs import short_window_spec_rows

    return short_window_spec_rows(line, audience=audience)


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
    bottom_limit: float | None = None,
    new_page=None,
) -> float:
    """Draw aligned LABEL: / value columns; returns y after last line."""
    value_x = x + label_col
    value_w = max(36.0, max_width - label_col)
    sy = y
    for label, value in rows:
        lab = f"{label}:" if label else ""
        if lab:
            wrapped = _wrap_text(c, value, value_w, font_size) or [""]
            needed = len(wrapped) * line_h
            if bottom_limit is not None and new_page is not None and sy - needed < bottom_limit:
                sy = new_page()
            set_font(c, font_size, bold=True)
            c.drawString(x, sy, lab)
            set_font(c, font_size)
            c.drawString(value_x, sy, wrapped[0])
            sy -= line_h
            for cont in wrapped[1:]:
                if bottom_limit is not None and new_page is not None and sy < bottom_limit:
                    sy = new_page()
                set_font(c, font_size)
                c.drawString(value_x, sy, cont)
                sy -= line_h
        else:
            wrapped = _wrap_text(c, value, max_width, font_size, bold=True) or [""]
            needed = len(wrapped) * line_h + 3.5
            if bottom_limit is not None and new_page is not None and sy - needed < bottom_limit:
                sy = new_page()
            for wl in wrapped:
                if bottom_limit is not None and new_page is not None and sy < bottom_limit:
                    sy = new_page()
                set_font(c, font_size, bold=True)
                c.drawString(x, sy, wl)
                sy -= line_h
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
    for label, value in rows:
        if label:
            wrapped = _wrap_text(c, value, value_w, font_size) or [""]
            lines += len(wrapped)
        else:
            wrapped = _wrap_text(c, value, max_width, font_size, bold=True) or [""]
            lines += len(wrapped)
            extra += 3.5
    return max(lines * line_h + extra, 24.0)


def render_marqt_pdf(template: Mapping[str, Any], payload: Mapping[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from WEOS.factory.line_kind import is_railing_cart_line
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
    cover_page = 1
    cover_bottom = M + 40

    def _cover_footer():
        set_font(c, 7)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(M, M / 2 + 8, f"powered by WEOS — page {cover_page}")
        c.setFillColorRGB(0, 0, 0)

    def _cover_new_page():
        nonlocal cover_page, y
        _cover_footer()
        c.showPage()
        cover_page += 1
        y = H - M - 20
        c.setFillColorRGB(0, 0, 0)
        return y

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
    y = _flow_paragraphs(
        c, cover, x=M, y=y, max_width=text_w, font_size=10, line_h=14,
        bottom=cover_bottom, set_font=set_font, on_new_page=_cover_new_page, para_gap=6.0,
    )

    # —— Per-quote Description (optional) ——
    description = str(payload.get("description") or "").strip()
    if description:
        y -= 6
        if y < cover_bottom + 20:
            y = _cover_new_page()
        c.setFillColorRGB(*primary)
        set_font(c, 10, bold=True)
        c.drawString(M, y, "Description")
        y -= 15
        c.setFillColorRGB(0, 0, 0)
        set_font(c, 9)
        y = _flow_paragraphs(
            c, description, x=M, y=y, max_width=text_w, font_size=9, line_h=13,
            bottom=cover_bottom, set_font=set_font, on_new_page=_cover_new_page, para_gap=4.0,
        )

    y -= 16
    if y < cover_bottom + 40:
        y = _cover_new_page()
    set_font(c, 9)
    c.drawString(M, y, "Enclosures:")
    y -= 14
    c.drawString(M + 10, y, "a) Design / Specifications / Value")
    y -= 12
    c.drawString(M + 10, y, "b) Terms & Conditions")
    # Company address lives in the letterhead only — do not repeat at cover bottom.
    _cover_footer()
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

    y = header(cover_page + 1)
    page_no = cover_page + 1
    total_area = 0.0
    total_qty = 0
    grand = 0.0

    # Elevation cell — tall enough for canvas SVG (plan + elevation) without stubbing.
    draw_w, draw_h = 200, 210
    bottom_limit = M + 30  # keep clear of footer + bottom margin

    # Per-line elevations only (no prefetch of all rasters). Windows = ReportLab
    # vectors; railing/shower/vent = canvas SVG (photo else sanitized PNG).

    for idx, line in enumerate(lines):
        # Specs first so we know how tall the text block is (wrap may exceed draw_h).
        try:
            spec_rows = _spec_rows(line)
        except Exception:
            _log.exception("marqt spec build failed for line %d; using name only", idx)
            spec_rows = [("", str(line.get("displayName") or line.get("product") or "Window"))]
        text_h = _measure_spec_rows(c, spec_rows, max_width=spec_max_w, font_size=7.0, label_col=72.0)
        need = max(draw_h, text_h) + 24
        page_usable = (H - M - 50) - bottom_limit
        min_block = min(draw_h, 80) + 40
        if y < bottom_limit + min_block:
            set_font(c, 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(M, M / 2 + 8, f"powered by WEOS — page {page_no}")
            c.showPage()
            page_no += 1
            y = header(page_no)
        elif need <= page_usable and y < bottom_limit + need:
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
        try:
            from WEOS.factory.customer_line_view import customer_line_amount

            amount = customer_line_amount(line)
        except Exception:
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
        if rate is None and is_railing_cart_line(line):
            # Prefer railing commercial RFT/RMT rate — never fake sqft from length×height.
            rate = line.get("sellingRate") or (line.get("price") or {}).get("unitRate")
            if rate is None:
                from WEOS.factory.railing_pdf import railing_cfg_and_quote

                _, rq = railing_cfg_and_quote(line)
                rate = (rq or {}).get("sellingPerUnit")
        if rate is None:
            # derive from cost / area for display
            try:
                rate = float(amount) / max(_area_sqft(w, h) * qty, 0.001)
            except (TypeError, ValueError):
                rate = 0
        grand += float(amount or 0)

        from WEOS.factory.line_kind import design_serial_label, line_location_name

        code = f"W{idx + 1}"
        loc = line_location_name(line)
        design_label = design_serial_label(idx, line)
        # Design column — reddish serial; location prints with it (under / beside W8).
        c.setFillColorRGB(*accent)
        max_code_w = draw_w - 6
        if loc:
            try:
                face = set_font(c, 9, bold=True) or "Helvetica-Bold"
                combined_w = c.stringWidth(design_label, face, 9)
            except Exception:
                combined_w = len(design_label) * 5.2
            if combined_w <= max_code_w:
                set_font(c, 9, bold=True)
                c.drawString(M + 2, y + 4, design_label)
            else:
                set_font(c, 9, bold=True)
                c.drawString(M + 2, y + 4, code)
                _draw_fit(c, loc, M + 2, y - 8, max_code_w, 7.5, bold=True, minimum=6.0)
        else:
            set_font(c, 9, bold=True)
            c.drawString(M + 2, y + 4, code)
        try:
            draw_line_elevation(c, line, M, y - draw_h, draw_w, draw_h)
        except Exception:
            _log.exception("marqt elevation draw failed for line %d; leaving cell blank", idx)

        # Specs — tabular LABEL: / value; never overflow into QTY/RATE/AMOUNT
        c.setFillColorRGB(0, 0, 0)
        specs_paged = [False]

        def _spec_new_page():
            nonlocal page_no
            specs_paged[0] = True
            set_font(c, 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(M, M / 2 + 8, f"powered by WEOS — page {page_no}")
            c.showPage()
            page_no += 1
            ny = header(page_no)
            c.setFillColorRGB(*accent)
            set_font(c, 8, bold=True)
            c.drawString(M + 2, ny + 4, f"{code} (continued)")
            c.setFillColorRGB(0, 0, 0)
            return ny - 12

        sy = _draw_spec_rows(
            c,
            spec_rows,
            x=col_spec,
            y=y,
            max_width=spec_max_w,
            set_font=set_font,
            font_size=7.0,
            label_col=72.0,
            bottom_limit=bottom_limit,
            new_page=_spec_new_page,
        )

        # Qty / Rate / Amount — currency symbol via Unicode font
        set_font(c, 8)
        c.drawRightString(col_qty, y, str(qty))
        rate_str = f"{float(rate):,.2f}" if rate is not None else "—"
        c.drawRightString(col_rate, y, rate_str)
        set_font(c, 8, bold=True)
        c.drawRightString(col_amt, y, f"{float(amount):,.2f}")

        # row separator
        if specs_paged[0]:
            row_bottom = sy - 2
        else:
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
    try:
        from WEOS.factory.line_kind import format_qty_totals_lines, quote_qty_breakdown

        qty_lines = format_qty_totals_lines(quote_qty_breakdown(lines), fallback_qty=total_qty)
    except Exception:
        qty_lines = [f"Items: {total_qty} Nos"]
    c.drawString(M, y, f"Total Area: {round(total_area, 3)} Sq.Ft.")
    y -= 12
    for ql in qty_lines:
        c.drawString(M, y, ql)
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
    terms_bottom = M + 48

    def _terms_footer():
        set_font(c, 7)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(M, M / 2 + 8, f"powered by WEOS — page {page_no}")
        c.setFillColorRGB(0, 0, 0)

    def _terms_new_page():
        nonlocal page_no, y
        _terms_footer()
        c.showPage()
        page_no += 1
        y = H - (M + 14)
        c.setFillColorRGB(*primary)
        set_font(c, 11, bold=True)
        c.drawString(M, y, "Terms & Conditions (continued)")
        y -= 18
        c.setFillColorRGB(0, 0, 0)
        set_font(c, 9)
        return y

    c.setFillColorRGB(0, 0, 0)
    set_font(c, 9)
    y = _flow_paragraphs(
        c, terms_text, x=M, y=y, max_width=text_w, font_size=9, line_h=13,
        bottom=terms_bottom, set_font=set_font, on_new_page=_terms_new_page, para_gap=4.0,
    )

    # —— Bank details (from Company Setup) ——
    bank = str(branding.get("bankDetails") or "").strip()
    if bank:
        if y < terms_bottom + 50:
            y = _terms_new_page()
        y -= 18
        c.setFillColorRGB(*primary)
        set_font(c, 11, bold=True)
        c.drawString(M, y, "Bank Details")
        y -= 15
        c.setFillColorRGB(0, 0, 0)
        set_font(c, 9)
        y = _flow_paragraphs(
            c, bank, x=M, y=y, max_width=text_w, font_size=9, line_h=13,
            bottom=terms_bottom, set_font=set_font, on_new_page=_terms_new_page, para_gap=4.0,
        )

    if y < M + 130:
        y = _terms_new_page()
    y -= 30
    set_font(c, 9)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(M, y, "For " + company)
    y -= 50
    if y < M + 80:
        y = _terms_new_page()
    c.drawString(M, y, "Authorized Signatory")
    c.drawRightString(W - M, y, "Customer Acceptance")

    # QR → absolute public URL that fetches this quote from the database when scanned.
    qr_y = M + 8
    if y - 70 < qr_y + 64:
        y = _terms_new_page()
        qr_y = M + 8
    try:
        from WEOS.factory.pdf_qr import draw_quote_qr

        draw_quote_qr(c, payload, x=M, y=qr_y, size=64, label="Scan to view quote")
    except Exception:
        pass

    set_font(c, 7)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(M, M / 2 + 8, f"powered by WEOS — page {page_no}")
    c.showPage()
    c.save()
    return buf.getvalue()
