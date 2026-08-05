"""SVG preview export — lightweight 2D preview from DrawingModel (no DXF copy)."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from WEOS.factory.types import DrawingModel


def render_svg_string(model: DrawingModel, *, margin: float = 120.0, colour: str | None = None) -> str:
    """Return SVG markup string for API preview (no file write)."""
    xs: list[float] = [0.0, model.width]
    ys: list[float] = [0.0, model.height]
    for pl in model.polylines:
        for p in pl.points:
            xs.append(p.x)
            ys.append(p.y)
    for seg in model.segments:
        xs.extend([seg.start.x, seg.end.x])
        ys.extend([seg.start.y, seg.end.y])

    min_x, max_x = min(xs) - margin, max(xs) + margin
    min_y, max_y = min(ys) - margin, max(ys) + margin
    w = max_x - min_x
    h = max_y - min_y

    def tx(x: float) -> float:
        return x - min_x

    def ty(y: float) -> float:
        return max_y - y

    # Colour tint for frame preview
    colour_map = {
        "white": "#e8e8e6",
        "black_texture": "#2a2a2a",
        "wood_oak": "#8b5a2b",
    }
    frame_fill = colour_map.get((colour or "white").lower().replace(" ", "_"), "#d0d0ce")
    glass_fill = "rgba(120, 180, 230, 0.35)"

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}" height="{h:.1f}" '
        f'viewBox="0 0 {w:.1f} {h:.1f}">',
        f"<title>{escape(model.product_type)} {model.width:g}x{model.height:g}</title>",
        '<rect width="100%" height="100%" fill="#f0efe9"/>',
    ]

    for pl in model.polylines:
        if len(pl.points) < 2:
            continue
        pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
        if pl.layer == "GLASS":
            parts.append(f'<polygon points="{pts}" fill="{glass_fill}" stroke="#2a6fdb" stroke-width="1.2"/>')
        elif pl.closed:
            parts.append(f'<polygon points="{pts}" fill="{frame_fill}" stroke="#222" stroke-width="1.4"/>')
        else:
            parts.append(
                f'<polyline points="{pts}" fill="none" stroke="#222" stroke-width="1.2"/>'
            )

    for seg in model.segments:
        stroke = "#222" if seg.layer == "PROFILES" else "#666"
        parts.append(
            f'<line x1="{tx(seg.start.x):.2f}" y1="{ty(seg.start.y):.2f}" '
            f'x2="{tx(seg.end.x):.2f}" y2="{ty(seg.end.y):.2f}" '
            f'stroke="{stroke}" stroke-width="1"/>'
        )

    label = escape(f"{model.product_type}  {model.width:g} × {model.height:g} mm")
    parts.append(
        f'<text x="12" y="{h - 16:.1f}" font-family="Segoe UI, Arial, sans-serif" '
        f'font-size="28" fill="#222">{label}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def export_svg(model: DrawingModel, path: str | Path, *, margin: float = 120.0, colour: str | None = None) -> Path:
    path = Path(path)
    path.write_text(render_svg_string(model, margin=margin, colour=colour), encoding="utf-8")
    return path

