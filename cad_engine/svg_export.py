"""SVG preview export — lightweight 2D preview from DrawingModel (no DXF copy)."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from cad_engine.types import DrawingModel


def export_svg(model: DrawingModel, path: str | Path, *, margin: float = 120.0) -> Path:
    path = Path(path)
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

    # SVG Y is down; flip drawing Y for human-readable preview
    def tx(x: float) -> float:
        return x - min_x

    def ty(y: float) -> float:
        return max_y - y

    layer_stroke = {
        "PROFILES": "#222",
        "GLASS": "#2a6fdb",
        "Defpoints": "#999",
        "DIMS": "#2d8a3e",
        "0": "#444",
    }

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}" height="{h:.1f}" '
        f'viewBox="0 0 {w:.1f} {h:.1f}">',
        f"<title>{escape(model.product_type)} {model.width:g}x{model.height:g}</title>",
        '<rect width="100%" height="100%" fill="#f7f7f5"/>',
    ]

    for pl in model.polylines:
        if len(pl.points) < 2:
            continue
        pts = " ".join(f"{tx(p.x):.2f},{ty(p.y):.2f}" for p in pl.points)
        stroke = layer_stroke.get(pl.layer, "#333")
        close = " Z" if pl.closed else ""
        fill = "rgba(42,111,219,0.08)" if pl.layer == "GLASS" else "none"
        parts.append(
            f'<polyline points="{pts}{close}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="1.2" fill-rule="evenodd"/>'
            if not pl.closed
            else f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>'
        )

    for seg in model.segments:
        stroke = layer_stroke.get(seg.layer, "#333")
        parts.append(
            f'<line x1="{tx(seg.start.x):.2f}" y1="{ty(seg.start.y):.2f}" '
            f'x2="{tx(seg.end.x):.2f}" y2="{ty(seg.end.y):.2f}" '
            f'stroke="{stroke}" stroke-width="1"/>'
        )

    # Dimension guides as thin lines (true dims live in DXF)
    for dim in model.dimensions:
        stroke = layer_stroke.get(dim.layer, "#2d8a3e")
        parts.append(
            f'<line x1="{tx(dim.p1.x):.2f}" y1="{ty(dim.p1.y):.2f}" '
            f'x2="{tx(dim.p2.x):.2f}" y2="{ty(dim.p2.y):.2f}" '
            f'stroke="{stroke}" stroke-width="0.8" stroke-dasharray="4 3"/>'
        )

    label = escape(f"{model.product_type}  {model.width:g} × {model.height:g} mm")
    parts.append(
        f'<text x="12" y="{h - 16:.1f}" font-family="Segoe UI, Arial, sans-serif" '
        f'font-size="28" fill="#222">{label}</text>'
    )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
