"""Analyze Two Track.dxf reference drawing structure."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.math import Vec3

DXF = Path(__file__).parent / "Two Track.dxf"


def main() -> None:
    doc = ezdxf.readfile(DXF)
    msp = doc.modelspace()

    print("=== HEADER DIM STYLE ===")
    for key in (
        "$DIMASZ",
        "$DIMTXT",
        "$DIMEXE",
        "$DIMEXO",
        "$DIMDLI",
        "$DIMSCALE",
        "$DIMTAD",
        "$DIMTIH",
        "$DIMTOH",
        "$EXTMIN",
        "$EXTMAX",
    ):
        try:
            print(f"  {key}: {doc.header.get(key)}")
        except Exception as e:
            print(f"  {key}: ERR {e}")

    print("\n=== LAYERS ===")
    for layer in doc.layers:
        print(f"  {layer.dxf.name!r} color={layer.dxf.color}")

    print("\n=== DIMSTYLES ===")
    for style in doc.dimstyles:
        data = {k: getattr(style.dxf, k, None) for k in style.dxfattribs().keys()}
        print(f"  {style.dxf.name}: {data}")

    counts: dict[str, int] = defaultdict(int)
    for e in msp:
        counts[e.dxftype()] += 1
    print("\n=== ENTITY COUNTS ===")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")

    print("\n=== DIMENSIONS ===")
    dims = []
    for e in msp.query("DIMENSION"):
        d = e.dxf
        info = {
            "layer": d.layer,
            "dimstyle": getattr(d, "dimstyle", None),
            "defpoint": tuple(d.defpoint) if hasattr(d, "defpoint") else None,
            "defpoint2": tuple(getattr(d, "defpoint2", (None,))) if hasattr(d, "defpoint2") else None,
            "defpoint3": tuple(getattr(d, "defpoint3", (None,))) if hasattr(d, "defpoint3") else None,
            "text_midpoint": tuple(d.text_midpoint) if hasattr(d, "text_midpoint") else None,
            "insert": tuple(d.insert) if hasattr(d, "insert") else None,
            "actual_measurement": getattr(d, "actual_measurement", None),
            "text": getattr(d, "text", None),
            "angle": getattr(d, "angle", None),
            "dimtype": getattr(d, "dimtype", None),
        }
        # measurement via geometry
        try:
            meas = e.get_measurement()
            info["measurement"] = float(meas)
        except Exception:
            info["measurement"] = None
        dims.append(info)
        print(
            f"  meas={info['measurement']} text={info['text']!r} "
            f"angle={info['angle']} layer={info['layer']} "
            f"p2={info['defpoint2']} p3={info['defpoint3']} mid={info['text_midpoint']}"
        )

    print("\n=== LINES (unique sorted by length / coords) ===")
    lines = []
    for e in msp.query("LINE"):
        s = Vec3(e.dxf.start)
        end = Vec3(e.dxf.end)
        length = s.distance(end)
        lines.append(
            {
                "layer": e.dxf.layer,
                "start": (round(s.x, 4), round(s.y, 4)),
                "end": (round(end.x, 4), round(end.y, 4)),
                "len": round(length, 4),
                "color": e.dxf.color,
            }
        )
    # sort by x then y of start
    lines.sort(key=lambda L: (L["start"][0], L["start"][1], L["end"][0], L["end"][1]))
    for L in lines:
        print(f"  {L['layer']:12s} {L['start']} -> {L['end']} len={L['len']}")

    print("\n=== LWPOLYLINES ===")
    for e in msp.query("LWPOLYLINE"):
        pts = [(round(p[0], 4), round(p[1], 4)) for p in e.get_points("xy")]
        closed = e.closed
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        print(
            f"  layer={e.dxf.layer} closed={closed} n={len(pts)} "
            f"bbox=({min(xs)},{min(ys)})-({max(xs)},{max(ys)}) pts={pts}"
        )

    print("\n=== TEXTS / MTEXTS ===")
    for e in msp.query("TEXT"):
        print(f"  TEXT layer={e.dxf.layer} insert={tuple(e.dxf.insert)} h={e.dxf.height} '{e.dxf.text}'")
    for e in msp.query("MTEXT"):
        print(f"  MTEXT layer={e.dxf.layer} insert={tuple(e.dxf.insert)} h={e.dxf.char_height} '{e.text}'")

    # Unique X and Y coordinates from all line geometry (construction grid)
    xs: set[float] = set()
    ys: set[float] = set()
    for e in msp.query("LINE"):
        xs.add(round(e.dxf.start.x, 3))
        xs.add(round(e.dxf.end.x, 3))
        ys.add(round(e.dxf.start.y, 3))
        ys.add(round(e.dxf.end.y, 3))
    for e in msp.query("LWPOLYLINE"):
        for p in e.get_points("xy"):
            xs.add(round(p[0], 3))
            ys.add(round(p[1], 3))

    print("\n=== UNIQUE X COORDS (sorted) ===")
    sx = sorted(xs)
    print(sx)
    print("\n  deltas between consecutive X:")
    for a, b in zip(sx, sx[1:]):
        print(f"    {a} -> {b}: {round(b - a, 3)}")

    print("\n=== UNIQUE Y COORDS (sorted) ===")
    sy = sorted(ys)
    print(sy)
    print("\n  deltas between consecutive Y:")
    for a, b in zip(sy, sy[1:]):
        print(f"    {a} -> {b}: {round(b - a, 3)}")

    # Overall extents of geometry (excluding dims maybe)
    try:
        cache = bbox.Cache()
        ext = bbox.extents(msp, cache=cache)
        print(f"\n=== EXTENTS === {ext.extmin} -> {ext.extmax}")
        print(f"  size W={ext.size.x} H={ext.size.y}")
    except Exception as e:
        print("extents err", e)

    out = Path(__file__).parent / "dxf_analysis.json"
    out.write_text(
        json.dumps({"dims": dims, "xs": sx, "ys": sy, "line_count": len(lines)}, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
