"""Export a DrawingModel to DXF via ezdxf — never copies reference entities."""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

from WEOS.factory.dimensioning import DimStyleParams
from WEOS.factory.types import DrawingModel


def export_dxf(
    model: DrawingModel,
    path: str | Path,
    *,
    dim_style: DimStyleParams | None = None,
) -> Path:
    path = Path(path)
    style = dim_style or DimStyleParams()

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # millimeters
    doc.header["$DIMASZ"] = style.arrow_size
    doc.header["$DIMTXT"] = style.text_height
    doc.header["$DIMEXE"] = 0.18
    doc.header["$DIMEXO"] = 0.0625
    doc.header["$DIMTAD"] = 0
    doc.header["$DIMTIH"] = 1
    doc.header["$DIMTOH"] = 1

    # Ensure layers
    if "Defpoints" not in doc.layers:
        doc.layers.add("Defpoints", color=7)
    if "DIMS" not in doc.layers:
        doc.layers.add("DIMS", color=3)
    if "PROFILES" not in doc.layers:
        doc.layers.add("PROFILES", color=7)
    if "GLASS" not in doc.layers:
        doc.layers.add("GLASS", color=4)

    # Update Standard dimstyle
    try:
        std = doc.dimstyles.get("Standard")
        std.dxf.dimasz = style.arrow_size
        std.dxf.dimtxt = style.text_height
        std.dxf.dimdec = 0
        std.dxf.dimtdec = 0
    except Exception:
        pass

    msp = doc.modelspace()

    for pl in model.polylines:
        pts = [p.as_tuple() for p in pl.points]
        if len(pts) < 2:
            continue
        msp.add_lwpolyline(pts, close=pl.closed, dxfattribs={"layer": pl.layer})

    for seg in model.segments:
        # Skip zero-length
        if seg.start.x == seg.end.x and seg.start.y == seg.end.y:
            continue
        msp.add_line(
            seg.start.as_tuple(),
            seg.end.as_tuple(),
            dxfattribs={"layer": seg.layer},
        )

    for dim in model.dimensions:
        _add_aligned_dim(msp, dim, style)

    # Title block note (product + size) — lightweight metadata, not copied from DXF
    note = f"{model.product_type}  {model.width:g} x {model.height:g} mm"
    msp.add_text(
        note,
        height=style.text_height * 0.5,
        dxfattribs={"layer": "0"},
    ).set_placement((0.0, -style.offset_outer * 2.5), align=TextEntityAlignment.LEFT)

    doc.saveas(path)
    return path


def _add_aligned_dim(msp, dim, style: DimStyleParams) -> None:
    """
    Create a true DIMENSION entity using ezdxf dim builder.
    Angle 0 => measure horizontally (p1/p2 share Y typically).
    Angle 90 => measure vertically.
    """
    p1 = dim.p1.as_tuple()
    p2 = dim.p2.as_tuple()
    # Distance from geometry to dim line
    if abs(dim.angle_deg) % 180 < 45 or abs(dim.angle_deg) % 180 > 135:
        # horizontal measurement — dim line at text_pos.y
        distance = dim.text_pos.y - dim.p1.y
        builder = msp.add_aligned_dim(
            p1=p1,
            p2=p2,
            distance=distance,
            dimstyle="Standard",
            override={"dimasz": style.arrow_size, "dimtxt": style.text_height, "dimdec": 1},
            dxfattribs={"layer": dim.layer},
        )
    else:
        # vertical measurement — use distance in X
        distance = dim.text_pos.x - dim.p1.x
        builder = msp.add_aligned_dim(
            p1=p1,
            p2=p2,
            distance=distance,
            dimstyle="Standard",
            override={"dimasz": style.arrow_size, "dimtxt": style.text_height, "dimdec": 1},
            dxfattribs={"layer": dim.layer},
        )
    if dim.override_text:
        builder.set_text(dim.override_text)
    builder.render()

