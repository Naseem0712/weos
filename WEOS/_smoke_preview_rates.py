"""Smoke tests for consistent preview, partitions, mesh, INR rates."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WEOS.factory.pipeline import generate_job
from WEOS.factory.svg_export import render_svg_string, export_svg, layout_summary_for_job
from WEOS.factory.pdf_fonts import ensure_rupee_font, money_text, rupee_prefix
from WEOS.factory.marqt_pdf import render_marqt_pdf, _spec_lines
from WEOS.factory.project_engine import calculate_line

out = Path("_pdf_preview")
out.mkdir(exist_ok=True)

face, ok = ensure_rupee_font()
prefix = rupee_prefix()
print("font", face, "rupee_ok", ok, "prefix_ord", [ord(c) for c in prefix], money_text(890).encode("utf-8"))

cases = [
    ("small_750x970", 750, 970, None, False, None),
    ("large_2750x1970", 2750, 1970, None, False, None),
    ("fix_top_2000x1900", 2000, 1900, [{"side": "top", "sizeMm": 290, "role": "fix"}], False, None),
    ("mesh_2track", 1500, 1200, None, True, 2.0),
]
for name, w, h, parts, mesh, tc in cases:
    job = generate_job(
        w, h, "29mm_sliding",
        partitions=parts, mesh=mesh, track_count=tc,
        section_series="29mm_premium_euro",
    )
    svg = render_svg_string(job.drawing, annotations=True, include_plan=True, style="preview")
    export_svg(job.drawing, out / f"smoke_{name}.svg", annotations=True, include_plan=True)
    lay = layout_summary_for_job(width=w, height=h, layout_meta=job.layout_meta)
    meta = job.layout_meta or {}
    print(
        name,
        "track", meta.get("track_count"),
        "mesh", meta.get("mesh"),
        "panels", [p["id"] + ":" + p["role"] for p in lay["panels"]],
        "svg", len(svg),
    )
    assert "SLIDING" in svg or "FIX" in svg
    # stroke scale present for large windows — profile stroke should not be tiny constant
    if w >= 2000:
        assert 'stroke-width="' in svg

line = calculate_line({
    "product": "29mm_sliding",
    "width": 750,
    "height": 970,
    "qty": 1,
    "glass": "5mm_clear",
    "colour": "black_texture",
    "handle": "standard",
    "sellingRate": 890,
    "saleUnit": "sqft",
    "sectionSeries": "29mm_premium_euro",
})
specs = _spec_lines(line)
assert not any("Sell rate" in s for s in specs), specs
print("specs_ok_no_duplicate_rate", specs[-4:])

# mesh shift
mesh_line = calculate_line({
    "product": "29mm_sliding",
    "width": 1500,
    "height": 1200,
    "qty": 1,
    "mesh": True,
    "trackCount": 2,
    "sectionSeries": "29mm_premium_euro",
    "glass": "5mm_clear",
})
assert float(mesh_line.get("trackCount") or 0) >= 2.5, mesh_line.get("trackCount")
print("mesh_shifted_track", mesh_line.get("trackCount"))

# top fix
fix_line = calculate_line({
    "product": "29mm_sliding",
    "width": 2000,
    "height": 1900,
    "qty": 1,
    "partitions": [{"side": "top", "sizeMm": 290, "role": "fix"}],
    "glass": "5mm_clear",
})
panels = (fix_line.get("layout") or {}).get("panels") or []
assert any(p.get("role") == "fix" for p in panels), panels
print("fix_panels", [(p["id"], p["role"], p.get("heightMm")) for p in panels])

pdf = render_marqt_pdf(
    {"branding": {"companyName": "WEOS"}, "blocks": [], "layoutStyle": "marqt"},
    {"quotationId": "SMOKE", "customer": "Test", "lines": [line, fix_line, mesh_line], "name": "Smoke"},
)
Path("_smoke_marqt_rates.pdf").write_bytes(pdf)
print("pdf_bytes", len(pdf))
print("ALL_SMOKE_OK")
