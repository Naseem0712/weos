"""Smoke: Canvas D3 — Viewport / Fit / Zoom / Placement stability (cases A–O)."""

from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_viewport_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ["WEOS_UNIVERSAL_CANVAS"] = "0"

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "WEOS" / "website" / "canvas"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def _read(name: str) -> str:
    return (CANVAS / name).read_text(encoding="utf-8")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from WEOS.factory import canvas_workspace as cw
    from WEOS.factory import universal_canvas as uc

    print("=== _smoke_viewport_stability A-O ===")
    vp_js = _read("viewport.js")
    uc_js = _read("universal_canvas.js")
    sr_js = _read("scene_renderer.js")
    ws_js = _read("workspace.js")
    dc_js = _read("design_context.js")

    # A: single authoritative transform (no double scale / no viewBox Fit)
    _ok("computeFit" in vp_js and "normalizeBounds" in vp_js, "A: computeFit/normalizeBounds")
    _ok("cssTransform" in vp_js, "A: cssTransform helper")
    _ok(
        "Never use SVG viewBox" in vp_js or "never use SVG viewBox" in vp_js.lower(),
        "A: documented no viewBox-Fit",
    )
    _ok("parts[2]" not in uc_js, "A: removed viewBox width Fit override")

    # B: Fit centers + padding; invalid bounds safe
    plan = cw.compute_fit({"width": 1200, "height": 1000, "minX": 0, "minY": 0}, 1200, 800, padding=48)
    _ok(0.15 <= plan["zoom"] <= 6.0, f"B: zoom in range {plan['zoom']}")
    _ok(abs(plan["panX"] - (600 - 600 * plan["zoom"])) < 1e-6, "B: horizontal center")
    _ok(abs(plan["panY"] - (400 - 500 * plan["zoom"])) < 1e-6, "B: vertical center")
    bad = cw.compute_fit({"width": 0, "height": -5}, 800, 600, padding=48)
    _ok(bad["width"] >= 1 and bad["height"] >= 1, "B: invalid bounds fallback")
    tiny = cw.compute_fit({"width": 50, "height": 50}, 800, 600, padding=48)
    _ok(tiny["zoom"] <= cw.ZOOM_MAX, "B: tiny clamped")

    # C: tall / wide / multi
    tall = cw.compute_fit({"width": 900, "height": 2400}, 1280, 720, padding=56)
    wide = cw.compute_fit({"width": 3600, "height": 900}, 1280, 720, padding=56)
    _ok(0.15 <= tall["zoom"] <= 6, f"C: tall zoom {tall['zoom']}")
    _ok(0.15 <= wide["zoom"] <= 6, f"C: wide zoom {wide['zoom']}")
    multi = cw.compute_fit(
        {"width": 2500, "height": 1800, "minX": 100, "minY": 50}, 1920, 1080, padding=48
    )
    _ok(math.isfinite(multi["panX"]) and math.isfinite(multi["panY"]), "C: multi finite pan")

    # D: zoom clamp NaN / Infinity / extremes
    _ok(cw.clamp_zoom(float("nan")) == 1.0, "D: NaN → 1")
    _ok(cw.clamp_zoom(float("inf")) == cw.ZOOM_MAX, "D: Inf → max")
    _ok(cw.clamp_zoom(0.01) >= cw.ZOOM_MIN, "D: min floor")
    _ok(cw.clamp_zoom(99) == cw.ZOOM_MAX, "D: max cap")

    # E: world↔viewport inverse (authoritative transform, worldOrigin 0)
    vx, vy = uc.world_to_viewport(100, 200, pan_x=10, pan_y=20, zoom=2)
    _ok(vx == 210 and vy == 420, f"E: world→screen {vx},{vy}")
    wx, wy = uc.viewport_to_world(vx, vy, pan_x=10, pan_y=20, zoom=2)
    _ok(abs(wx - 100) < 1e-9 and abs(wy - 200) < 1e-9, "E: inverse")

    # F: Fit priority helpers present
    _ok("fitScene" in uc_js and "fitSelected" in uc_js, "F: fitScene/fitSelected")
    _ok("Fit Priority" in uc_js or "Fit priority" in uc_js, "F: priority documented")
    _ok("resetView" in uc_js and "fitScene()" in uc_js, "F: Reset View recovers via fitScene")

    # G: wheel zoom anchors cursor; buttons use viewport center
    _ok("ev.clientX - rect.left" in uc_js, "G: wheel zoom cursor anchor")
    _ok("rect.width / 2" in uc_js and "zoomBy(1.15" in uc_js, "G: button zoom center")

    # H: async preview Fit once (pendingPreviewFit); not every property paint
    _ok("pendingPreviewFit" in uc_js, "H: pendingPreviewFit gate")
    _ok("markPendingPreviewFit" in uc_js and "markPendingPreviewFit" in dc_js, "H: product switch marks pending")
    _ok("setElementPreviewSvg(elementId, svg" in dc_js, "H: preview paints via host")

    # I: D0 renderRevision guard on preview apply
    _ok("renderRevision" in uc_js and "expectedRevision" in uc_js, "I: stale revision guard")
    _ok("_previewGen" in dc_js, "I: preview gen counter retained")

    # J: SVG artwork vs element bounds distinguished
    _ok("data-weos-artwork" in sr_js, "J: artwork marker")
    _ok("preserveAspectRatio" in sr_js and "none" in sr_js, "J: SVG fills element box")
    _ok("element_mm" in uc_js, "J: element_mm bound source")

    # K: zoom label uses viewport.zoom
    _ok("Math.round(viewport.zoom * 100)" in uc_js, "K: zoom label = actual scale")

    # L: pan/resize — preserve center, no auto-fit on ResizeObserver
    _ok("preserveCenterOnResize" in vp_js and "preserveCenterOnResize" in uc_js, "L: resize preserve")
    _ok(
        "ResizeObserver preserves zoom" in uc_js or "do not call fit()" in uc_js,
        "L: no auto-fit on resize",
    )

    # M: per-design viewport state
    _ok("viewByDesignId" in uc_js, "M: per-design view map")
    _ok("restoreViewFor" in uc_js and "persistActiveView" in uc_js, "M: save/restore on switch")

    # N: initial placement near origin (world mm)
    _ok("xMm: 0" in ws_js and "yMm: 0" in ws_js, "N: Add Design places at origin mm")
    _ok("widthMm" in ws_js and "heightMm" in ws_js, "N: engineering sizes")

    # O: batch marker + diag flag + zoom limits
    _ok("CANVAS-D3" in uc_js or "CANVAS-D4" in uc_js, "O: host batch D3/D4")
    _ok("ucViewportDiag" in uc_js or "setDiag" in vp_js, "O: optional diag flag")
    _ok(cw.ZOOM_MIN == 0.15 and cw.ZOOM_MAX == 6.0, "O: zoom limits aligned")

    # Extra: railing-like tiny viewBox must NOT drive Fit (regression of ~600% zoom)
    el_mm = cw.compute_fit({"width": 3000, "height": 900, "minX": 0, "minY": 0}, 1280, 720, padding=48)
    fake_vb = cw.compute_fit({"width": 640, "height": 160, "minX": 0, "minY": 0}, 1280, 720, padding=48)
    _ok(el_mm["zoom"] < 2.0, f"O+: element-mm Fit not extreme {el_mm['zoom']}")
    _ok(fake_vb["zoom"] > el_mm["zoom"], "O+: viewBox-sized Fit would over-zoom (why we ignore it)")

    print("ALL PASS: viewport stability A-O")


if __name__ == "__main__":
    main()
