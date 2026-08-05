"""Image engine — PNG preview from SVG (optional dependency: cairosvg or pillow+svglib)."""

from __future__ import annotations

import base64
import io
from pathlib import Path


def svg_to_png_bytes(svg: str, *, scale: float = 1.0) -> bytes | None:
    """Best-effort SVG→PNG. Returns None if no renderer available."""
    # Try cairosvg
    try:
        import cairosvg

        return cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=scale)
    except Exception:
        pass

    # Try svglib + reportlab + pillow
    try:
        from reportlab.graphics import renderPM
        from svglib.svglib import svg2rlg

        drawing = svg2rlg(io.BytesIO(svg.encode("utf-8")))
        if drawing is None:
            return None
        if scale and scale != 1.0:
            drawing.width *= scale
            drawing.height *= scale
            drawing.scale(scale, scale)
        return renderPM.drawToString(drawing, fmt="PNG")
    except Exception:
        pass

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
