"""End-to-end verify: profile JSON rules drive geometry + BOM; param changes regenerate."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cad_engine.pipeline import export_job_package, generate_job
from cad_engine.profile_loader import DEFAULT_PROFILE_ID, load_profile, apply_geometry_overrides
from cad_engine.geometry_engine import compute_two_track_layout
from products.two_track_sliding import TwoTrackParams, compute_layout


def approx(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(a - b) <= tol


def test_profile_json_is_source_of_truth() -> None:
    profile = load_profile(DEFAULT_PROFILE_ID)
    assert profile["id"] == "29mm_sliding"
    g = profile["geometry"]
    for key in ("trackWidth", "frameWidth", "interlockWidth", "overlap", "glassClip"):
        assert key in g
    for key in ("handleSideOverlap", "interlockSideOverlap", "topOverlap", "bottomOverlap"):
        assert key in profile["glass"]
    assert profile["hardware"] and profile["cutList"] and profile["brush"] and profile["trackRail"]
    print("test_profile_json_is_source_of_truth: OK")
    print(f"  path={profile['_path']}")
    print(f"  geometry={g}")


def test_reference_structure() -> None:
    p = TwoTrackParams.from_master_json()
    L = compute_layout(1440, 1800, p)
    assert approx(L.interlock_right - L.interlock_left, p.interlock_width)
    assert approx(L.shutter_inset, p.track_width - p.overlap)
    assert approx(L.track.x0, p.track_width)
    assert approx(L.track.x0 - L.left_shutter.x0, p.overlap)
    assert approx(L.left_glass.x0 - L.left_shutter.x0, p.shutter_frame)
    assert approx(L.right_shutter_width - L.left_shutter_width, p.interlock_width)
    print("test_reference_structure: OK")


def test_profile_param_regen() -> None:
    """Change trackWidth/interlockWidth/frameWidth in overrides only -> new geometry + BOM."""
    W, H = 1440.0, 1800.0
    base = generate_job(W, H, DEFAULT_PROFILE_ID)
    mod = generate_job(
        W,
        H,
        DEFAULT_PROFILE_ID,
        overrides={"trackWidth": 32, "interlockWidth": 26, "frameWidth": 75},
    )
    assert approx(mod.geometry_params["track_width"], 32)
    assert approx(mod.geometry_params["interlock_width"], 26)
    assert approx(mod.geometry_params["shutter_frame"], 75)
    assert approx(mod.layout_meta["shutter_inset"], 32 - base.geometry_params["overlap"])
    assert mod.layout_meta["interlock_right"] - mod.layout_meta["interlock_left"] == 26
    assert mod.layout_meta["shutter_inset"] != base.layout_meta["shutter_inset"]

    # Glass sizes change with frame / opening
    assert mod.glass[0].width_mm != base.glass[0].width_mm or mod.glass[0].height_mm != base.glass[0].height_mm
    # BOM / cut list lengths change
    base_cut = sum(c.length_mm * c.quantity for c in base.cut_list)
    mod_cut = sum(c.length_mm * c.quantity for c in mod.cut_list)
    assert mod_cut != base_cut or mod.weight.total_kg != base.weight.total_kg

    out = ROOT / "output"
    paths_a = export_job_package(base, out, basename="29mm_defaults_1440x1800")
    paths_b = export_job_package(mod, out, basename="29mm_tw32_il26_fw75_1440x1800")
    assert paths_a["dxf"].stat().st_size > 500
    assert paths_b["svg"].is_file() and paths_b["json"].is_file()

    print("test_profile_param_regen: OK")
    print(f"  defaults inset={base.layout_meta['shutter_inset']} quote={base.quotation.total}")
    print(f"  modified inset={mod.layout_meta['shutter_inset']} quote={mod.quotation.total}")
    print(f"  glass0 defaults={base.glass[0].width_mm:.1f}x{base.glass[0].height_mm:.1f}")
    print(f"  glass0 modified={mod.glass[0].width_mm:.1f}x{mod.glass[0].height_mm:.1f}")


def test_json_file_edit_regen() -> None:
    """Editing a profile JSON file (no Python change) regenerates geometry."""
    src = load_profile(DEFAULT_PROFILE_ID)
    src = apply_geometry_overrides(src, {"trackWidth": 32, "interlockWidth": 26, "frameWidth": 75})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "29mm_sliding.json"
        # strip internal
        doc = {k: v for k, v in src.items() if not k.startswith("_")}
        doc["id"] = "29mm_sliding_tmp"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        # load via path
        from cad_engine.profile_loader import load_profile as lp
        # pipeline expects id under profiles/ — call layout directly
        g = json.loads(path.read_text(encoding="utf-8"))["geometry"]
        L = compute_two_track_layout(1440, 1800, g)
        assert approx(L.track_width, 32)
        assert approx(L.interlock_width, 26)
        assert approx(L.frame_width, 75)
        assert approx(L.shutter_inset, 24)
    print("test_json_file_edit_regen: OK")


def test_full_package_modules() -> None:
    job = generate_job(2000, 2200, DEFAULT_PROFILE_ID)
    assert job.glass and job.hardware and job.brush and job.track_rail
    assert job.cut_list and job.bom and job.weight and job.quotation
    assert job.track_rail[0].quantity == 2
    assert approx(job.track_rail[0].length_mm, 2000)
    assert len(job.drawing.dimensions) >= 8
    print("test_full_package_modules: OK")
    print(f"  BOM lines={len(job.bom)} weight={job.weight.total_kg:.3f}kg quote={job.quotation.total}")


if __name__ == "__main__":
    test_profile_json_is_source_of_truth()
    test_reference_structure()
    test_profile_param_regen()
    test_json_file_edit_regen()
    test_full_package_modules()
    print("\nAll checks passed.")
