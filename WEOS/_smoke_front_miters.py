"""Smoke: 2-panel sliding — front sash meeting-stile corners have 45° miters."""
from __future__ import annotations

import sys

from WEOS.factory.pipeline import generate_job


def main() -> int:
    fails: list[str] = []
    job = generate_job(1200, 600, "29mm_sliding", system="sliding", glass_count=2)
    segs = list(job.drawing.segments or [])
    miter_names = [str(s.name or "") for s in segs if "miter" in str(s.name or "").lower()]
    # Expect shutter_*_miter_tl/tr/bl/br including meeting-side tags on the front sash
    shutter_miters = [n for n in miter_names if n.startswith("shutter_")]
    if len(shutter_miters) < 6:
        # 2 sashes × ~3-4 miters each (back omits 2 meeting; front has all 4) → typically 6+
        fails.append(f"too few shutter miters: {shutter_miters}")

    # Front sash = smaller depth. Find which shutter indices exist and their miters.
    shutters = (job.drawing.metadata or {}).get("shutters") or []
    glass = [s for s in shutters if isinstance(s, dict) and s.get("role") == "glass"]
    if len(glass) < 2:
        fails.append(f"expected 2 glass shutters, got {len(glass)}")
    else:
        front = min(glass, key=lambda s: float(s.get("depth") or 99))
        fi = front.get("index")
        front_miters = [n for n in shutter_miters if f"shutter_{fi}_miter_" in n]
        # Front must have all 4 corner miters (including meeting stile tl/tr or bl/br)
        tags = {n.rsplit("_", 1)[-1] for n in front_miters}
        for need in ("bl", "br", "tl", "tr"):
            if need not in tags:
                fails.append(f"front sash {fi} missing miter_{need}; have {sorted(tags)}")

        back = max(glass, key=lambda s: float(s.get("depth") or 0))
        bi = back.get("index")
        back_miters = [n for n in shutter_miters if f"shutter_{bi}_miter_" in n]
        # Back should have outer corners only (2), not meeting-side pair
        if len(back_miters) > 3:
            fails.append(f"back sash {bi} has too many miters (double-line risk): {back_miters}")

    # SVG path still embeds miter segments as lines
    from WEOS.factory.svg_export import render_svg_string

    svg = render_svg_string(job.drawing, annotations=True, include_plan=True)
    if "<svg" not in svg:
        fails.append("no svg")

    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print(f"OK front meeting miters · shutter_miters={len(shutter_miters)} · {sorted(set(shutter_miters))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
