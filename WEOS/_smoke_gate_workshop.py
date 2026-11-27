"""Smoke: pattern louvers, casement hinges, line-only SVG, units, walls/track."""
from __future__ import annotations

import re

from WEOS.factory.gate_engine import MM_PER_FT, compute_gate, gate_svg
from WEOS.factory.structural_catalogue import build_structural_catalogue, list_structural_sections


def _pick_al(w: float, h: float) -> str | None:
    best = None
    for s in list_structural_sections(material="aluminium"):
        if abs(float(s.get("widthMm") or 0) - w) < 0.8 and abs(float(s.get("heightMm") or 0) - h) < 0.8:
            shp = str(s.get("shape") or "")
            if "hollow" in shp or "square" in shp or "rect" in shp:
                return s.get("sectionId")
            best = best or s.get("sectionId")
    return best


def _member_fills(svg: str) -> list[str]:
    """Fills on structural members (ignore white bg / text)."""
    bad = []
    for m in re.finditer(r'<(?:rect|path|circle)[^>]*>', svg):
        tag = m.group(0)
        if 'width="100%"' in tag:
            continue
        if 'data-dim=' in tag or 'data-brick' in tag:
            continue
        fm = re.search(r'fill="([^"]*)"', tag)
        if not fm:
            continue
        fill = fm.group(1).lower()
        if fill in ("none", "transparent", "#fff", "#ffffff", "white"):
            continue
        # allow very light hinge fill only if windows still use it — gates use none
        if 'data-role=' in tag or 'data-mitre=' in tag or 'data-gate-hinge=' in tag:
            bad.append(fill)
    return bad


def main() -> int:
    fails: list[str] = []
    build_structural_catalogue(persist=True)

    # --- Pattern multi-section louvers ---
    s25 = _pick_al(25, 25)
    s50 = _pick_al(50, 25) or _pick_al(50, 50) or s25
    s100 = _pick_al(100, 25) or _pick_al(100, 50) or s50
    if not (s25 and s50 and s100):
        fails.append(f"missing Al sections for pattern {s25}/{s50}/{s100}")
    else:
        qp = compute_gate(
            {
                "widthFt": 13,
                "heightFt": 8,
                "bayType": "folding_privacy",
                "foldLeft": 2,
                "foldRight": 2,
                "louverPattern": [
                    {"sectionId": s25, "gapAfterMm": 30},
                    {"sectionId": s50, "gapAfterMm": 50},
                    {"sectionId": s100, "gapAfterMm": 25},
                ],
                "msRatePerKg": 215,
                "alRatePerBar": 1459,
                "fabRatePerSft": 150,
            }
        )
        svg_p = gate_svg({}, qp)
        counts: dict[str, int] = {}
        for c in qp.get("cuts") or []:
            if c.get("memberRole") != "louver_blade":
                continue
            sid = c.get("sectionId")
            counts[sid] = counts.get(sid, 0) + 1
        if len(counts) < 2:
            fails.append(f"pattern should use multiple sectionIds, got {counts}")
        for sid in (s25, s50, s100):
            if sid not in counts:
                fails.append(f"pattern missing blades for {sid}")
        # Weight/cost must nest each section separately
        nests = qp.get("nests") or {}
        for sid in counts:
            if sid not in nests:
                fails.append(f"nest missing for pattern section {sid}")
            elif float((nests[sid] or {}).get("usedKg") or 0) <= 0 and float((nests[sid] or {}).get("usedM") or 0) <= 0:
                fails.append(f"no used mass/length for {sid}")
        if 'data-hinge-segments="3"' not in svg_p and "data-hinge-bar=" not in svg_p:
            fails.append("casement hinge mid-lines missing")
        if svg_p.count("data-hinge-bar=") < 2:
            fails.append(f"expected ≥2 hinge bar dividers, got {svg_p.count('data-hinge-bar=')}")
        member_fills = _member_fills(svg_p)
        if member_fills:
            fails.append(f"line-only SVG still has fills: {set(member_fills)}")
        if "data-dim=" not in svg_p:
            fails.append("window-style dims missing")

    # Fixed grill + walls
    qg = compute_gate(
        {
            "widthFt": 13,
            "heightFt": 8,
            "bayType": "fixed_grill",
            "foldLeft": 0,
            "foldRight": 0,
            "sideWallWidthMm": 230,
        }
    )
    svg_g = gate_svg({}, qg)
    if "side_wall_L" not in svg_g or "brick_bed" not in svg_g:
        fails.append("grill walls/brick missing")
    if _member_fills(svg_g):
        fails.append(f"grill svg fills {_member_fills(svg_g)[:3]}")

    # Sliding track + unit round-trip via widthMm
    Wmm = 13 * MM_PER_FT
    qs = compute_gate(
        {
            "widthMm": Wmm,
            "heightMm": 8 * MM_PER_FT,
            "bayType": "sliding_gate",
            "foldLeft": 1,
            "foldRight": 1,
            "slidingMainWidthMm": 2800,
            "swingLeafWidthMm": 900,
            "handleSide": "R",
            "sizeUnit": "mm",
        }
    )
    track = qs.get("track") or {}
    if abs(float(track.get("lengthMm") or 0) - (2 * Wmm + MM_PER_FT)) > 1:
        fails.append(f"track len {track.get('lengthMm')}")
    # Unit conversion helper
    from WEOS.factory.gate_engine import ensure_gate_dims
    c_ft = ensure_gate_dims({"widthFt": 10, "heightFt": 7, "bayType": "swing_gate"})
    c_mm = ensure_gate_dims({"widthMm": 10 * MM_PER_FT, "heightMm": 7 * MM_PER_FT, "bayType": "swing_gate"})
    if abs(c_ft["widthMm"] - c_mm["widthMm"]) > 0.5 or abs(c_ft["heightMm"] - c_mm["heightMm"]) > 0.5:
        fails.append("unit round-trip ft/mm mismatch")

    if fails:
        print("FAIL gate workshop:")
        for f in fails:
            print(" -", f)
        return 1
    print(
        "OK gate workshop · "
        f"pattern sections={len(counts) if s25 else 0} "
        f"hingeBars={svg_p.count('data-hinge-bar=') if s25 else 0} "
        f"track={track.get('lengthMm')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
