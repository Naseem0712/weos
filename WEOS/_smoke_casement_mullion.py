"""Smoke: casement door+door mullion — 20 mm wings, body = face − 40, always visible."""
from __future__ import annotations

import sys

from WEOS.factory.geometry_engine import (
    CASEMENT_WING_MM,
    compute_two_track_layout,
    resolve_casement_mullion_seating,
)
from WEOS.factory.pipeline import generate_job
from WEOS.factory.product_loader import load_product
from WEOS.factory.svg_export import render_svg_string


def main() -> int:
    fails: list[str] = []

    face, wing, body = resolve_casement_mullion_seating(None, None)
    if abs(wing - CASEMENT_WING_MM) > 0.1:
        fails.append(f"default wing {wing}, expected {CASEMENT_WING_MM}")
    if abs(body - 20.0) > 0.1:
        fails.append(f"default body {body}, expected 20")
    if abs(face - (body + 2 * wing)) > 0.1:
        fails.append(f"default face {face} != body+2*wing")

    # Catalogue face 67 (50mm slim) → body 27
    f67, w67, b67 = resolve_casement_mullion_seating(
        None, 20, section_sizes={"mullion": 67.0}
    )
    if abs(f67 - 67) > 0.1 or abs(b67 - 27) > 0.1 or abs(w67 - 20) > 0.1:
        fails.append(f"67 face seating got face={f67} wing={w67} body={b67}")

    # Legacy small gap 15 → expand to face 55 (body 20 floored? legacy 15 → body max(15,20)=20 → face 60)
    # Actually: v=15 <= 2*wing+5 → body_legacy = max(15, 20) = 20 → face = 60
    f_leg, w_leg, b_leg = resolve_casement_mullion_seating(15, 20)
    if abs(f_leg - 60) > 0.1 or abs(b_leg - 20) > 0.1:
        fails.append(f"legacy 15 seating got face={f_leg} body={b_leg}")

    job = generate_job(
        2050,
        1970,
        "casement_stub",
        system="casement",
        glass_count=2,
        handle_overrides={
            0: {"role": "fix", "side": "none"},
            1: {"role": "openable", "side": "right"},
        },
        sash_overlap_mm=20,
        mullion_gap_mm=60,
    )
    L = job.drawing
    meta = L.metadata or {}
    if meta.get("system") != "casement":
        fails.append(f"system {meta.get('system')}")
    if abs(float(meta.get("sashOverlapMm") or 0) - 20) > 0.1:
        fails.append(f"sashOverlapMm {meta.get('sashOverlapMm')}")
    if abs(float(meta.get("mullionGapMm") or 0) - 60) > 0.1:
        fails.append(f"mullionGapMm (face) {meta.get('mullionGapMm')}")
    if abs(float(meta.get("mullionBodyMm") or 0) - 20) > 0.1:
        fails.append(f"mullionBodyMm {meta.get('mullionBodyMm')}")

    segs = list(L.segments or [])
    names = [str(s.name or "") for s in segs]
    if not any(n.startswith("frame_miter_") for n in names):
        fails.append("outer frame missing 45° miters")
    if any("mullion" in n and "miter" in n for n in names):
        fails.append(f"mullion must be 90° T, not 45°: {[n for n in names if 'mullion' in n]}")
    if not any("mullion" in n and "body" in n for n in names):
        fails.append("missing mullion body seat edges (wings model)")

    prod = load_product("casement_stub")
    lay = compute_two_track_layout(
        2050, 1970, prod["geometry"], system="casement", glass_count=2,
        handle_overrides={0: {"role": "fix", "side": "none"}, 1: {"role": "openable", "side": "right"}},
        sash_overlap_mm=20, mullion_gap_mm=60,
    )
    if len(lay.mullions) < 1:
        fails.append("casement F1+A1 missing mullion geometry")
    elif abs(lay.mullions[0].width - 60) > 1.5:
        fails.append(f"mullion face width {lay.mullions[0].width}, expected ~60")

    # Door edges leave body visible: overlap 20 into face 60 → gap between doors = 20
    opens = [sp for sp in lay.shutters if sp.operable]
    if len(opens) >= 1 and lay.mullions:
        m = lay.mullions[0]
        sp = opens[0]
        # openable should stop at body edge (m.x0 + wing or m.x1 - wing)
        if sp.outer.x0 < m.x0:
            # left of mullion — right edge at body left
            if abs(sp.outer.x1 - (m.x0 + 20)) > 2.0:
                fails.append(f"door/mullion seating x1={sp.outer.x1} bodyL={m.x0+20}")
        else:
            if abs(sp.outer.x0 - (m.x1 - 20)) > 2.0:
                fails.append(f"door/mullion seating x0={sp.outer.x0} bodyR={m.x1-20}")

    polys = list(L.polylines or [])
    pnames = [str(p.name or "") for p in polys]
    if "track_inner" in pnames:
        fails.append("casement still emits track_inner (stray extra head line)")
    if not any(n.startswith("shutter_") and n.endswith("_outer") for n in pnames):
        fails.append(f"missing openable sash outer: {pnames}")

    svg = render_svg_string(L, annotations=True, include_plan=True)
    if "<svg" not in svg:
        fails.append("no svg")

    # Two operable doors — always a vertical mullion between them
    j3 = generate_job(
        1800, 1500, "casement_stub", system="casement", glass_count=2,
        sash_overlap_mm=20, mullion_gap_mm=67,
        section_sizes={"mullion": 67.0},
        handle_overrides={
            0: {"role": "openable", "side": "right"},
            1: {"role": "openable", "side": "left"},
        },
    )
    m3 = j3.drawing.metadata or {}
    lay3 = compute_two_track_layout(
        1800, 1500, prod["geometry"], system="casement", glass_count=2,
        sash_overlap_mm=20, mullion_gap_mm=67, section_sizes={"mullion": 67.0},
        handle_overrides={0: {"role": "openable", "side": "right"}, 1: {"role": "openable", "side": "left"}},
    )
    if len(lay3.mullions) < 1:
        fails.append("two openables (door+door) missing inter-door mullion geometry")
    elif abs(lay3.mullions[0].width - 67) > 1.5:
        fails.append(f"door+door mullion face {lay3.mullions[0].width}, expected 67")
    if abs(float(m3.get("mullionBodyMm") or 0) - 27) > 0.1:
        fails.append(f"door+door body {m3.get('mullionBodyMm')}, expected 27")
    doors = [sp for sp in lay3.shutters if sp.operable]
    if len(doors) >= 2 and lay3.mullions:
        m = lay3.mullions[0]
        gap = doors[1].outer.x0 - doors[0].outer.x1
        if abs(gap - 27) > 2.5:
            fails.append(f"visible gap between doors {gap:.1f}, expected ~27 body")

    n3 = [str(s.name or "") for s in (j3.drawing.segments or [])]
    if not any("mullion" in n and "body" in n for n in n3):
        fails.append("door+door missing mullion body lines in drawing")
    if not any(n.startswith("shutter_") and "miter" in n for n in n3):
        fails.append("two openables missing sash 45° miters")

    # 50mm Excel series via generate_job product id
    try:
        j50 = generate_job(
            1600, 1400, "50mm_casement_prestige", system="casement", glass_count=2,
            handle_overrides={
                0: {"role": "door", "side": "right"},
                1: {"role": "door", "side": "left"},
            },
        )
        m50 = j50.drawing.metadata or {}
        body50 = float(m50.get("mullionBodyMm") or 0)
        face50 = float(m50.get("mullionGapMm") or 0)
        if face50 < 40:
            fails.append(f"50mm series mullion face too small: {face50}")
        if body50 < 10:
            fails.append(f"50mm series mullion body missing: {body50}")
    except Exception as exc:
        fails.append(f"50mm_casement_prestige job failed: {exc}")

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print("OK casement mullion wings=20 · body=face-40 · door+door always mullion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
