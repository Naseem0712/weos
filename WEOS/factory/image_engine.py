"""Image engine — PNG preview from SVG (optional dependency: cairosvg or pillow+svglib)."""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path


def sanitize_svg_for_pdf(svg: str) -> str:
    """Make canvas SVG safe for Cairo / svglib / print.

    ``stroke-dasharray="none"`` crashes svglib (float('none')). Filters /
    foreignObject / huge dash patterns hang RIP. Structural print = solid.
    """
    s = str(svg or "")
    if not s:
        return s
    s = re.sub(r"\sstroke-dasharray\s*=\s*['\"][^'\"]*['\"]", "", s, flags=re.I)
    s = re.sub(r"<filter[\s\S]*?</filter>", "", s, flags=re.I)
    s = re.sub(r"<foreignObject[\s\S]*?</foreignObject>", "", s, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", "", s, flags=re.I)
    return s


def normalize_svg_viewbox(svg: str, *, max_px: float = 1000.0) -> str:
    """Keep the canvas viewBox, but set CSS width/height to a small pixel size.

    Railing/window SVGs use model-mm viewBoxes (2000–4000). Cairo/svglib treat
    those as pixels and hang. Shower SVG is already ~px — this is a no-op.
    """
    s = str(svg or "")
    if not s.strip():
        return s
    vb_w, vb_h = _svg_wh(s)
    long = max(vb_w, vb_h, 1.0)
    cap = max(float(max_px or 1000.0), 160.0)
    if long > cap:
        k = cap / long
        out_w, out_h = vb_w * k, vb_h * k
    else:
        out_w, out_h = vb_w, vb_h
    m = re.search(r"<svg\b[^>]*>", s, flags=re.I)
    if not m:
        return s
    tag = m.group(0)
    tag = re.sub(r"\swidth\s*=\s*['\"][^'\"]*['\"]", "", tag, flags=re.I)
    tag = re.sub(r"\sheight\s*=\s*['\"][^'\"]*['\"]", "", tag, flags=re.I)
    tag = re.sub(r"<svg\b", f'<svg width="{out_w:.1f}" height="{out_h:.1f}"', tag, count=1, flags=re.I)
    return s[: m.start()] + tag + s[m.end() :]


def _svg_wh(svg: str) -> tuple[float, float]:
    m = re.search(r'viewBox\s*=\s*["\']\s*[\d.+-]+\s+[\d.+-]+\s+([\d.+-]+)\s+([\d.+-]+)', svg, re.I)
    if m:
        try:
            return max(float(m.group(1)), 1.0), max(float(m.group(2)), 1.0)
        except (TypeError, ValueError):
            pass
    wm = re.search(r'\bwidth\s*=\s*["\']([\d.+-]+)', svg, re.I)
    hm = re.search(r'\bheight\s*=\s*["\']([\d.+-]+)', svg, re.I)
    try:
        w = float(wm.group(1)) if wm else 0.0
        h = float(hm.group(1)) if hm else 0.0
        if w > 1 and h > 1:
            return w, h
    except (TypeError, ValueError):
        pass
    return 800.0, 600.0


def _capped_scale(svg: str, scale: float, max_px: float) -> float:
    w, h = _svg_wh(svg)
    m = max(w, h, 1.0)
    req = float(scale or 1.0)
    if m * req <= max_px:
        return req
    return max(max_px / m, 0.05)


def _force_solid_rl_strokes(drawing, *, min_width: float = 0.55):
    """Clear dash arrays; bump hairlines. Never recurse into non-iterables."""
    seen: set[int] = set()

    def walk(obj) -> None:
        if obj is None:
            return
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)
        try:
            if hasattr(obj, "strokeDashArray"):
                obj.strokeDashArray = []
        except Exception:
            pass
        try:
            if hasattr(obj, "strokeWidth") and obj.strokeWidth not in (None, ""):
                sw = float(obj.strokeWidth)
                if 0 < sw < min_width:
                    obj.strokeWidth = min_width
        except (TypeError, ValueError):
            pass
        contents = getattr(obj, "contents", None)
        if not contents:
            return
        try:
            children = list(contents)
        except Exception:
            return
        for child in children:
            walk(child)

    try:
        walk(drawing)
    except Exception:
        pass
    return drawing


def cairo_png_available() -> bool:
    try:
        import cairosvg  # noqa: F401

        return True
    except Exception:
        return False


def svg_to_png_bytes(
    svg: str,
    *,
    scale: float = 1.0,
    allow_slow: bool = False,
    max_px: float = 1200.0,
) -> bytes | None:
    """SVG→PNG. Cairo is fast; svglib+renderPM is very slow and can fatten strokes.

    ``max_px`` caps the long edge so model-mm viewBoxes (2000–4000) do not
    explode into multi-megapixel rasters that hang Quote PDF.
    """
    svg = sanitize_svg_for_pdf(svg)
    svg = normalize_svg_viewbox(svg, max_px=max_px)
    if not svg.strip():
        return None
    # Width/height already pixel-capped — keep scale modest so RIP stays fast.
    use_scale = min(max(float(scale or 1.0), 0.5), 1.6)
    try:
        import cairosvg

        return cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=use_scale)
    except Exception:
        pass

    if not allow_slow:
        return None

    try:
        from reportlab.graphics import renderPM
        from svglib.svglib import svg2rlg

        drawing = svg2rlg(io.BytesIO(svg.encode("utf-8")))
        if drawing is None:
            return None
        drawing = _force_solid_rl_strokes(drawing)
        if use_scale and use_scale != 1.0:
            drawing.width *= use_scale
            drawing.height *= use_scale
            drawing.scale(use_scale, use_scale)
        return renderPM.drawToString(drawing, fmt="PNG")
    except Exception:
        pass

    return None


def svg_to_rl_drawing(svg: str):
    """Best-effort SVG → ReportLab vector Drawing (svglib). Returns None if unavailable."""
    svg = sanitize_svg_for_pdf(svg)
    svg = normalize_svg_viewbox(svg, max_px=900.0)
    if not svg.strip():
        return None
    try:
        from svglib.svglib import svg2rlg

        drawing = svg2rlg(io.BytesIO(svg.encode("utf-8")))
        if drawing is not None:
            _force_solid_rl_strokes(drawing)
        return drawing
    except Exception:
        return None


def svg_to_png_data_url(svg: str, *, scale: float = 1.0) -> str | None:
    raw = svg_to_png_bytes(svg, scale=scale)
    if raw is None:
        return None
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def export_png_from_svg(svg: str, path: str | Path, *, scale: float = 1.0) -> Path | None:
    raw = svg_to_png_bytes(svg, scale=scale)
    if raw is None:
        return None
    path = Path(path)
    path.write_bytes(raw)
    return path
