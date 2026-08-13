"""Smoke: casement F1+A1 — mullion 90°, sash 45°, overlap hides stray head line."""
from __future__ import annotations

import sys

from WEOS.factory.geometry_engine import compute_two_track_layout
from WEOS.factory.pipeline import generate_job
from WEOS.factory.product_loader import load_product
from WEOS.factory.svg_export import render_svg_string


def main() -> int:
    fails: list[str] = []
    job = generate_job(
        2050,
        1970,
        "29mm_sliding",
        system="casement",
        glass_count=2,
        handle_overrides={
            0: {"role": "fix", "side": "none"},
            1: {"role": "openable", "side": "right"},
        },
        sash_overlap_mm=15,
        mullion_gap_mm=15,
    )
    L = job.drawing
    meta = L.metadata or {}
    if meta.get("system") != "casement":
        fails.append(f"system {meta.get('system')}")
    if abs(float(meta.get("sashOverlapMm") or 0) - 15) > 0.1:
        fails.append(f"sashOverlapMm {meta.get('sashOverlapMm')}")
    if abs(float(meta.get("mullionGapMm") or 0) - 15) > 0.1:
        fails.append(f"mullionGapMm {meta.get('mullionGapMm')}")

    segs = list(L.segments or [])
    names = [str(s.name or "") for s in segs]
    if not any(n.startswith("frame_miter_") for n in names):
        fails.append("outer frame missing 45° miters")
    if any("mullion" in n and "miter" in n for n in names):
        fails.append(f"mullion must be 90° T, not 45°: {[n for n in names if 'mullion' in n]}")

    prod = load_product("29mm_sliding")
    lay = compute_two_track_layout(
        2050, 1970, prod["geometry"], system="casement", glass_count=2,
        handle_overrides={0: {"role": "fix", "side": "none"}, 1: {"role": "openable", "side": "right"}},
        sash_overlap_mm=15, mullion_gap_mm=15,
    )
    if len(lay.mullions) < 1:
        fails.append("casement F1+A1 missing mullion geometry")
    elif abs(lay.mullions[0].width - 15) > 1.5:
        fails.append(f"mullion width {lay.mullions[0].width}, expected ~15")

    polys = list(L.polylines or [])
    pnames = [str(p.name or "") for p in polys]
    if "track_inner" in pnames:
        fails.append("casement still emits track_inner (stray extra head line)")
    if not any(n.startswith("shutter_") and n.endswith("_outer") for n in pnames):
        fails.append(f"missing openable sash outer: {pnames}")
    if not any("miter" in n and n.startswith("shutter_") for n in names):
        fails.append("openable sash missing 45° miters")

    shutters = [s for s in (meta.get("shutters") or []) if isinstance(s, dict)]
    opens = [s for s in shutters if s.get("operable")]
    if not opens:
        fails.append("no openable shutter in meta")
    else:
        sp = opens[0]
        track_y1 = float(meta.get("sliding_y1") or 0)
        if track_y1 and float(sp.get("y1") or 0) <= track_y1 + 1.0:
            fails.append(f"openable does not overlap head: sash.y1={sp.get('y1')} inner.y1={track_y1}")

    svg = render_svg_string(L, annotations=True, include_plan=True)
    if "<svg" not in svg:
        fails.append("no svg")
    if "track_inner" in svg:
        fails.append("svg still mentions track_inner")

    hinges = [h for h in (meta.get("hinges") or []) if isinstance(h, dict)]
    if len(hinges) < 2:
        fails.append(f"casement F1+A1 missing hinges ({len(hinges)})")
    else:
        hw = abs(float(hinges[0]["x1"]) - float(hinges[0]["x0"]))
        hh = abs(float(hinges[0]["y1"]) - float(hinges[0]["y0"]))
        aspect = hh / max(hw, 0.1)
        if hw > 18.0 or hh < 50.0 or aspect < 4.8:
            fails.append(f"hinge not slim capsule w={hw:.1f} h={hh:.1f} aspect={aspect:.2f}")
        if "data-hinge=\"1\"" not in svg or "data-hinge-split=\"h\"" not in svg:
            fails.append("svg missing stadium hinge + horizontal barrel split")

    j2 = generate_job(
        2050, 1970, "29mm_sliding", system="casement", glass_count=2,
        sash_overlap_mm=5, mullion_gap_mm=40,
        handle_overrides={0: {"role": "fix"}, 1: {"role": "openable", "side": "right"}},
    )
    m2 = j2.drawing.metadata or {}
    if abs(float(m2.get("sashOverlapMm") or 0) - 10) > 0.1:
        fails.append(f"overlap clamp expected 10, got {m2.get('sashOverlapMm')}")
    if abs(float(m2.get("mullionGapMm") or 0) - 20) > 0.1:
        fails.append(f"mullion gap clamp expected 20, got {m2.get('mullionGapMm')}")

    j3 = generate_job(
        1800, 1500, "29mm_sliding", system="casement", glass_count=2,
        sash_overlap_mm=15, mullion_gap_mm=15,
        handle_overrides={
            0: {"role": "openable", "side": "right"},
            1: {"role": "openable", "side": "left"},
        },
    )
    n3 = [str(s.name or "") for s in (j3.drawing.segments or [])]
    lay3 = compute_two_track_layout(
        1800, 1500, prod["geometry"], system="casement", glass_count=2,
        sash_overlap_mm=15, mullion_gap_mm=15,
        handle_overrides={0: {"role": "openable", "side": "right"}, 1: {"role": "openable", "side": "left"}},
    )
    if len(lay3.mullions) < 1:
        fails.append("two openables missing inter-door mullion geometry")
    if not any(n.startswith("shutter_") and "miter" in n for n in n3):
        fails.append("two openables missing sash 45° miters")

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print("OK casement mullion 90° · sash 45° · overlap 15 · no stray track_inner")
    return 0


if __name__ == "__main__":
    sys.exit(main())
