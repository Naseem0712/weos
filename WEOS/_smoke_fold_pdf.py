"""Smoke: 4+4 Fold & Sliding calculate → layout → specs → PDF re-derive."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WEOS.factory.layout_options import line_layout_options
from WEOS.factory.marqt_pdf import _spec_lines
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.svg_export import elevation_svg_for_line


def main() -> None:
    line = {
        "product": "29mm_sliding",
        "description": "Folding Door",
        "width": 9144,
        "height": 2130,
        "qty": 1,
        "system": "bifold",
        "foldLeft": 4,
        "foldRight": 4,
        "glass": "5mm_clear",
        "colour": "black_texture",
        "sectionSizes": {
            "topRail": 50,
            "bottomRail": 50,
            "leftJamb": 40,
            "rightJamb": 40,
            "leafStile": 35,
        },
    }
    r = calculate_line(line)
    lay = r.get("layout") or {}
    panels = lay.get("panels") or []
    opts = r.get("options") or {}
    print("system", lay.get("system"), "fold", lay.get("foldLeft"), lay.get("foldRight"))
    print("npanels", len(panels))
    print("panels", [(p.get("id"), p.get("widthMm"), p.get("label")) for p in panels])
    print("layoutWH", lay.get("widthMm"), lay.get("heightMm"))
    print(
        "opts",
        {
            k: opts.get(k)
            for k in ("system", "foldLeft", "foldRight", "sectionSizes", "trackCount")
        },
    )
    print("weight", r.get("weight"))
    print("glass0", (r.get("glass") or [None])[0])
    print("---SPECS---")
    specs = _spec_lines(r)
    for s in specs:
        print(s)

    assert lay.get("foldLeft") == 4 and lay.get("foldRight") == 4, lay
    assert len(panels) == 8, panels
    assert abs(float(lay.get("widthMm") or 0) - 9144) < 0.1, lay.get("widthMm")
    assert opts.get("foldLeft") == 4 and opts.get("foldRight") == 4, opts
    assert "trackCount" not in opts or opts.get("trackCount") in (None, 0), opts
    joined = "\n".join(specs)
    assert "2-track" not in joined.lower(), joined
    assert "4+4" in joined, joined
    assert "Section sizes" in joined, joined
    assert "Fold & Sliding" in joined, joined

    # PDF path re-derive from calculated line only
    svg = elevation_svg_for_line(r)
    assert svg and "svg" in svg.lower(), "missing svg"

    # fold only on layout (legacy) still resolves
    legacy = {
        "width": 9144,
        "height": 2130,
        "product": "29mm_sliding",
        "options": {"system": "bifold"},
        "layout": {"system": "bifold", "foldLeft": 4, "foldRight": 4, "kind": "fold_and_sliding"},
    }
    lo = line_layout_options(legacy)
    assert lo.get("foldLeft") == 4 and lo.get("foldRight") == 4 and lo.get("system") == "bifold", lo
    print("OK")


if __name__ == "__main__":
    main()
