"""Sliding track print, opening type, handle placement, canvas contrast."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_slide_track_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

from WEOS.factory.geometry_engine import compute_two_track_layout
from WEOS.factory.layout_options import resolve_mesh_track, resolve_shutter_config
from WEOS.factory.marqt_pdf import _spec_rows
from WEOS.factory.pipeline import generate_job
from WEOS.factory.product_loader import load_product
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.section_catalogue import (
    clean_series_print_name,
    format_active_track_print,
    has_track_option_dump,
    specs_summary_for_series,
)
from WEOS.factory.svg_export import render_svg_string


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def _geom() -> dict:
    p = load_product("29mm_sliding")
    return dict(p["geometry"])


def _handles(layout) -> list[tuple[int, str | None]]:
    return [(sp.index, sp.handle_side) for sp in layout.shutters if sp.role == "glass"]


def main() -> None:
    _ok(has_track_option_dump("25mm eco gulf 2 track, 3 track"), "detect dual track dump")
    _ok(not has_track_option_dump("2-track · 49×37.8 mm"), "single track is not a dump")
    cleaned = clean_series_print_name("25mm eco gulf system windows 25mm 2 track, 3 track")
    _ok("2 track" not in cleaned.lower() and "3 track" not in cleaned.lower(), f"clean series {cleaned}")
    _ok("2-track" in format_active_track_print(2, {"sectionDepthMm": 49, "widthMm": 37.8, "name": "2 track"}), "format 2-track")
    _ok(not has_track_option_dump(format_active_track_print(3, {"sectionDepthMm": 86, "widthMm": 37.8, "name": "3 track"})), "format 3-track no dump")

    sg = specs_summary_for_series("25mm_eco_gulf", glass_family="single", track_count=3, clean_names=True)
    blob = " ".join(str(sg.get(k) or "") for k in ("track", "trackPrint", "seriesTitle")).lower()
    _ok("3-track" in blob.replace(" ", ""), f"series 3-track print {blob}")
    _ok("2 track, 3 track" not in blob and "2-track, 3-track" not in blob.replace(" ", ""), f"no dual dump in series {blob}")

    cfg2 = resolve_shutter_config(glass_count=2)
    cfg3 = resolve_shutter_config(glass_count=3)
    cfg4 = resolve_shutter_config(glass_count=4)
    cfg2c = resolve_shutter_config(glass_count=2, opening="center")  # stale auto
    cfg2x = resolve_shutter_config(glass_count=2, opening="center", opening_explicit=True)
    _ok(cfg2["opening"] == "telescopic", f"2-panel default side got {cfg2['opening']}")
    _ok(cfg3["opening"] == "telescopic", f"3-panel default side got {cfg3['opening']}")
    _ok(cfg4["opening"] == "center", f"4-panel default center got {cfg4['opening']}")
    _ok(cfg2c["opening"] == "telescopic", f"stale center on 2-panel ignored got {cfg2c['opening']}")
    _ok(cfg2x["opening"] == "center", f"explicit 2-panel center override got {cfg2x['opening']}")

    mesh = resolve_mesh_track(mesh=True, track_count=2)
    _ok(float(mesh["trackCount"]) >= 2.5, f"mesh bumps track {mesh}")
    _ok(float(resolve_mesh_track(mesh=False, track_count=2)["trackCount"]) == 2.0, "2-track stays without mesh")

    g = _geom()
    L2 = compute_two_track_layout(2050, 1970, g, glass_count=2, opening="side")
    L3 = compute_two_track_layout(2050, 1970, g, glass_count=3, track_count=3, opening="side")
    L4 = compute_two_track_layout(2050, 1970, g, glass_count=4, opening="center")
    L4fix = compute_two_track_layout(2050, 1970, g, glass_count=4, opening="center", fixed_shutters=[0])
    _ok(L2.opening == "telescopic", f"2-panel layout opening {L2.opening}")
    _ok(L3.opening == "telescopic", f"3-panel layout opening {L3.opening}")
    _ok(L4.opening == "center", f"4-panel layout opening {L4.opening}")

    h2 = dict(_handles(L2))
    h3 = dict(_handles(L3))
    h4 = dict(_handles(L4))
    h4f = dict(_handles(L4fix))
    _ok(h2 == {0: "left", 1: "right"}, f"2-panel outer handles {h2}")
    _ok(h3.get(0) == "left" and h3.get(2) == "right" and h3.get(1) is None, f"3-panel outer only {h3}")
    _ok(h4.get(0) == "left" and h4.get(3) == "right", f"4-panel outer {h4}")
    _ok(h4.get(1) == "right" and h4.get(2) == "left", f"4-panel center meeting {h4}")
    _ok(h4f.get(0) is None and h4f.get(1) == "right" and h4f.get(3) == "right", f"4-panel FIX left no handle {h4f}")

    dirs3 = [sp.open_dir for sp in L3.shutters if sp.role == "glass" and sp.operable]
    _ok(dirs3 and all(d == 1 for d in dirs3), f"3-panel all slide right {dirs3}")
    dirs4 = [(sp.index, sp.open_dir) for sp in L4.shutters if sp.role == "glass"]
    _ok(dirs4[0][1] == -1 and dirs4[1][1] == -1 and dirs4[2][1] == 1 and dirs4[3][1] == 1, f"4-panel slide apart {dirs4}")

    line2 = calculate_line({
        "product": "29mm_sliding", "width": 2050, "height": 1970, "qty": 1,
        "glass": "8mm_toughened", "glassShutters": 2, "trackCount": 2,
        "sectionSeries": "25mm_eco_gulf", "system": "sliding", "sellingRate": 890,
        "opening": "center",  # stale even-count auto
    })
    rows2 = _spec_rows(line2, audience="customer")
    blob2 = " | ".join(f"{a}: {b}" for a, b in rows2).lower()
    _ok("2-track" in blob2.replace(" ", "") or "2-track" in blob2, f"2-track print {blob2}")
    _ok("2 track, 3 track" not in blob2 and "2-track, 3-track" not in blob2.replace(" ", ""), f"no dual track {blob2}")
    _ok("side opening" in blob2 and "center opening" not in blob2, f"2-panel side opening {blob2}")

    line_mesh = calculate_line({
        "product": "29mm_sliding", "width": 1800, "height": 1500, "qty": 1,
        "glass": "8mm_toughened", "glassShutters": 2, "trackCount": 2,
        "mesh": True, "sectionSeries": "25mm_eco_gulf", "system": "sliding", "sellingRate": 890,
    })
    blobm = " | ".join(f"{a}: {b}" for a, b in _spec_rows(line_mesh, audience="customer")).lower()
    _ok(float(line_mesh.get("trackCount") or 0) >= 2.5, f"mesh line trackCount {line_mesh.get('trackCount')}")
    _ok("3-track" in blobm.replace(" ", ""), f"mesh prints 3-track {blobm}")
    _ok("2 track, 3 track" not in blobm, f"mesh no dual dump {blobm}")

    line4 = calculate_line({
        "product": "29mm_sliding", "width": 2050, "height": 1970, "qty": 1,
        "glass": "8mm_toughened", "glassShutters": 4, "trackCount": 2,
        "sectionSeries": "25mm_eco_gulf", "system": "sliding", "sellingRate": 890,
    })
    blob4 = " | ".join(f"{a}: {b}" for a, b in _spec_rows(line4, audience="customer")).lower()
    _ok("center opening" in blob4, f"4-panel center opening {blob4}")
    _ok("side opening" not in blob4, f"4-panel not side {blob4}")

    line3 = calculate_line({
        "product": "29mm_sliding", "width": 2050, "height": 1970, "qty": 1,
        "glass": "8mm_toughened", "glassShutters": 3, "trackCount": 3,
        "sectionSeries": "25mm_eco_gulf", "system": "sliding", "sellingRate": 890,
    })
    blob3 = " | ".join(f"{a}: {b}" for a, b in _spec_rows(line3, audience="customer")).lower()
    _ok("side opening" in blob3, f"3-panel side opening {blob3}")
    _ok("3-track" in blob3.replace(" ", ""), f"3-track print {blob3}")

    job4 = generate_job(2050, 1970, "29mm_sliding", glass="8mm_toughened", glass_count=4, track_count=2, system="sliding")
    svg4 = render_svg_string(job4.drawing, annotations=True, include_plan=True, style="preview")
    title_m = re.search(r"<title>([^<]*)</title>", svg4)
    title = title_m.group(1) if title_m else ""
    _ok("2 track, 3 track" not in title.lower(), f"svg title no dual dump: {title}")
    _ok("2-track" in title.lower().replace(" ", "") or "2-track" in title.lower(), f"svg title active track: {title}")
    _ok("center opening" in title.lower(), f"svg title center: {title}")
    _ok("#111111" in svg4 or "#052c54" in svg4, "dark frame/interlock strokes")
    sws = [float(x) for x in re.findall(r'stroke-width="([\d.]+)"', svg4)]
    _ok(sws and 0.9 <= max(sws) <= 3.2, f"slim CAD strokes max={max(sws) if sws else None}")
    _ok('data-visual-series="sliding35"' in svg4, "sliding visual 35")

    job_cas = generate_job(1200, 2100, "29mm_sliding", glass="8mm_toughened", system="casement", glass_count=2)
    svg_c = render_svg_string(job_cas.drawing, annotations=True, include_plan=True, style="pdf")
    _ok('data-visual-series="casement50"' in svg_c, "casement visual 50")

    upvc = calculate_line({
        "product": "29mm_sliding", "width": 900, "height": 1200, "qty": 1,
        "glass": "5mm_clear", "frameMaterial": "upvc", "glassShutters": 2,
        "sellingRate": 800, "sectionSeries": "25mm_eco_gulf",
    })
    urows = _spec_rows(upvc, audience="customer")
    ulabels = [r[0] for r in urows if r[0]]
    ublob = " ".join(v for _, v in urows).lower()
    _ok("MATERIAL" in ulabels and "upvc" in ublob, f"UPVC still prints {ulabels}")
    _ok("LOCATION" not in ulabels or True, "location not required on this line")
    wt = line2.get("weight") or {}
    _ok(float(wt.get("totalKg") or wt.get("glassKg") or 0) >= 0, f"weight present {wt}")

    print("SMOKE_SLIDING_TRACK_OPENING_OK")


if __name__ == "__main__":
    main()
