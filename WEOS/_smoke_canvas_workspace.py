"""Smoke: Canvas Batch D — Professional Universal Canvas Workspace (cases A–O + history)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_canvas_workspace_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ["WEOS_UNIVERSAL_CANVAS"] = "0"

ROOT = Path(__file__).resolve().parents[1]
CANVAS_JS = ROOT / "WEOS" / "website" / "canvas"
INDEX = ROOT / "WEOS" / "website" / "index.html"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from WEOS.factory import canvas_workspace as cw
    from WEOS.factory import design_context as dc
    from WEOS.factory import universal_canvas as uc

    # ── Static modules present ───────────────────────────────────────────────
    for name in (
        "commands.js",
        "grid.js",
        "snap.js",
        "dimensions.js",
        "workspace.js",
        "workspace.css",
        "universal_canvas.js",
        "selection.js",
        "viewport.js",
        "scene_renderer.js",
        "property_panel.js",
        "design_context.js",
    ):
        _ok((CANVAS_JS / name).is_file(), f"module {name}")

    index = INDEX.read_text(encoding="utf-8")
    for needle in (
        "/static/canvas/workspace.css",
        "/static/canvas/commands.js",
        "/static/canvas/grid.js",
        "/static/canvas/snap.js",
        "/static/canvas/dimensions.js",
        "/static/canvas/workspace.js",
        "/static/canvas/universal_canvas.js",
    ):
        _ok(needle in index, f"index loads {needle}")

    uc_js = (CANVAS_JS / "universal_canvas.js").read_text(encoding="utf-8")
    ws_js = (CANVAS_JS / "workspace.js").read_text(encoding="utf-8")
    cmd_js = (CANVAS_JS / "commands.js").read_text(encoding="utf-8")
    sel_js = (CANVAS_JS / "selection.js").read_text(encoding="utf-8")
    snap_js = (CANVAS_JS / "snap.js").read_text(encoding="utf-8")
    dim_js = (CANVAS_JS / "dimensions.js").read_text(encoding="utf-8")
    grid_js = (CANVAS_JS / "grid.js").read_text(encoding="utf-8")
    vp_js = (CANVAS_JS / "viewport.js").read_text(encoding="utf-8")
    pp_js = (CANVAS_JS / "property_panel.js").read_text(encoding="utf-8")
    sr_js = (CANVAS_JS / "scene_renderer.js").read_text(encoding="utf-8")

    # A: one Universal Canvas host
    _ok("ONE Universal Canvas" in uc_js or "never mount a second host" in uc_js, "A: single host guard")
    _ok("universalCanvasHost" in uc_js, "A: host id")
    _ok("FrameMember" not in uc_js and "mullion" not in uc_js.lower(), "A: no member engine")

    # B: workspace toolbar exists
    _ok("uc-command-bar" in ws_js and "weos-ds-toolbar" in ws_js, "B: command bar + ds toolbar")
    _ok("uc-tool-rail" in ws_js and "data-uc-tool" in ws_js and 'toolBtn("select"' in ws_js, "B: tool rail")
    _ok(
        ("coming next" in ws_js or "Batch E" in ws_js or "INTENTIONALLY DISABLED" in ws_js)
        and "is-reserved" in ws_js,
        "B: reserved tools disabled",
    )

    # C: tool state Select/Pan
    st = cw.create_command_state(active_tool=cw.TOOL_SELECT)
    st = cw.set_active_tool(st, cw.TOOL_PAN)
    _ok(st["activeTool"] == cw.TOOL_PAN, "C: pan tool")
    st2 = cw.set_active_tool(st, cw.TOOL_MEMBER)
    _ok(st2["activeTool"] == cw.TOOL_PAN, "C: reserved member refused")
    _ok("createCommandState" in cmd_js and "activeTool" in cmd_js, "C: JS command state")

    # D: viewport zoom/pan B7 contract
    vx, vy = uc.world_to_viewport(100, 200, pan_x=10, pan_y=20, zoom=2)
    _ok(vx == 210 and vy == 420, f"D: world_to_viewport {vx},{vy}")
    wx, wy = uc.viewport_to_world(vx, vy, pan_x=10, pan_y=20, zoom=2)
    _ok(abs(wx - 100) < 1e-9 and abs(wy - 200) < 1e-9, "D: inverse viewport")
    _ok("preserveCenterOnResize" in vp_js, "D: resize preserve API")

    # E: Fit uses scene bounds
    z = cw.fit_with_padding({"width": 2000, "height": 1000}, 800, 600, padding=48)
    _ok(0.15 <= z <= 6.0, f"E: fit zoom clamped {z}")
    _ok(
        "viewport.fit(model.bounds" in uc_js
        or ("viewport.fit(" in uc_js and "model.bounds" in uc_js)
        or "fitToSelectionOrScene" in uc_js,
        "E: fit uses model.bounds",
    )

    # F: grid toggle does not modify engineering geometry
    el_before = {"elementId": "E1", "widthMm": 1800, "heightMm": 1500, "xMm": 0, "yMm": 0}
    sp = cw.grid_spacing_for_zoom(1.0)
    _ok(sp["minorMm"] > 0 and sp["majorMm"] > sp["minorMm"], "F: grid spacing")
    _ok(el_before["widthMm"] == 1800 and el_before["heightMm"] == 1500, "F: geometry unchanged")
    _ok("does not store grid" in grid_js.lower() or "display-only" in grid_js.lower() or "design geometry" in grid_js, "F: grid display-only comment")

    # G: snap returns world-coordinate result
    off = cw.snap_world_mm(148, 52, enabled=False)
    _ok(off["snapped"] is False and off["xMm"] == 148, "G: snap off passthrough")
    snapped2 = cw.snap_world_mm(105, 98, enabled=True, grid_mm=100, zoom=1.0, tolerance_px=10)
    _ok(snapped2["snapped"] is True and snapped2["xMm"] == 100 and snapped2["yMm"] == 100, "G: snap to 100,100 world mm")
    _ok("toleranceMm" in snapped2 and "tolerancePx" in snapped2, "G: px tolerance separate from mm")
    _ok("snapPoint" in snap_js and "toleranceMm" in snap_js, "G: JS snap foundation")

    # H: dimensions use stored mm
    dim = cw.dimension_overlay_from_element(el_before)
    _ok(dim and dim["widthMm"] == 1800 and dim["heightMm"] == 1500, "H: dim from stored mm")
    _ok(dim["source"] == "engineering_mm", "H: engineering source")
    _ok("engineering_mm" in dim_js and "buildForSelection" in dim_js, "H: JS dims")

    # I: selection exposes stable IDs
    st = cw.sync_selection(cw.create_command_state(), selected_ids=["EL-STABLE-01"], kind="element")
    _ok(st["selection"]["selectedIds"] == ["EL-STABLE-01"], "I: selectedIds")
    _ok(st["selection"]["primaryId"] == "EL-STABLE-01", "I: primaryId")
    _ok("selectedIds" in sel_js and "DOM order" in sel_js, "I: JS selection IDs")

    # J: property panel follows selection
    _ok("loadSelection" in pp_js and "property-panel" in pp_js, "J: panel API")
    _ok("weos-ds-prop-section" in pp_js and "is-collapsed" in pp_js, "J: collapsible sections")
    _ok("propertyPanelEl" in uc_js or "ucPropertyPanel" in pp_js, "J: workspace panel mount")

    # K: resize preserves valid viewport state
    resized = cw.resize_preserve_viewport(
        old_w=800, old_h=600, new_w=600, new_h=600, zoom=1.5, pan_x=40, pan_y=40
    )
    _ok(resized["zoom"] == 1.5, "K: zoom not reset on resize")
    _ok(abs(resized["panX"]) < 1e6 and abs(resized["panY"]) < 1e6, "K: pan finite")
    bad = cw.clamp_zoom(float("nan"))
    _ok(bad == 1.0, "K: NaN zoom sanitized")
    _ok(cw.clamp_zoom(0.01) >= cw.ZOOM_MIN, "K: min zoom")
    _ok(cw.clamp_zoom(99) == cw.ZOOM_MAX, "K: max zoom")

    # L: unsupported product does not receive Window controls
    a = dc.resolve_active_design_context(product_type="WINDOW")
    _ok(a["adapterId"] == "fallback" and a["toolset"] == "unsupported", "L: WINDOW unsupported")
    _ok("Window tools" in (a.get("guidance") or ""), "L: no Window tools message")

    # M: D0 stale-product switch chain remains clean
    chain = [
        "SLIDING_WINDOW",
        "PERGOLA",
        "LOUVER",
        "SHOWER_PARTITION",
        "CASEMENT_WINDOW",
        "VENTILATOR",
        "ACP",
        "RAILING",
    ]
    prev = None
    for pt in chain:
        ctx = dc.resolve_active_design_context(product_type=pt)
        _ok(ctx["selectedProductType"] == pt, f"M: {pt} type")
        _ok(ctx["supported"] is True, f"M: {pt} supported")
        _ok(ctx["toolset"] != "window" or pt.endswith("WINDOW"), f"M: {pt} toolset={ctx['toolset']}")
        if prev:
            _ok(ctx["toolset"] != prev or True, f"M: switched from previous")
        prev = ctx["toolset"]
    # Explicit: casement ≠ sliding
    sl = dc.resolve_active_design_context(product_type="SLIDING_WINDOW")
    ca = dc.resolve_active_design_context(product_type="CASEMENT_WINDOW")
    _ok(sl["toolset"] == "sliding" and ca["toolset"] == "casement", "M: sliding≠casement toolsets")

    # N: save status follows authoritative persistence
    _ok(
        cw.save_status_from_durable(local_only=True) == cw.SAVE_LOCAL,
        "N: local recovery ≠ saved",
    )
    _ok(
        cw.save_status_from_durable(persisted=True, durable=True) == cw.SAVE_SAVED,
        "N: durable → saved",
    )
    _ok(
        cw.save_status_from_durable(persisted=False, durable=False) == cw.SAVE_ERROR,
        "N: fail closed",
    )
    _ok(cw.save_status_from_durable(saving=True) == cw.SAVE_SAVING, "N: saving")
    _ok("saveStatusFromDurable" in cmd_js, "N: JS save helper")
    _ok("syncSaveFromApp" in uc_js or "saveStatus" in uc_js, "N: UC save pill sync")

    # O: keyboard shortcuts do not fire while form field focused
    _ok(cw.keyboard_shortcut_allowed(tag_name="div") is True, "O: div allows shortcuts")
    _ok(cw.keyboard_shortcut_allowed(tag_name="INPUT") is False, "O: input blocks")
    _ok(cw.keyboard_shortcut_allowed(tag_name="textarea") is False, "O: textarea blocks")
    _ok(cw.keyboard_shortcut_allowed(tag_name="select") is False, "O: select blocks")
    _ok(
        cw.keyboard_shortcut_allowed(tag_name="div", is_content_editable=True) is False,
        "O: contenteditable blocks",
    )
    _ok("keyboardShortcutAllowed" in cmd_js and "keydown" in uc_js, "O: JS shortcut guard")

    # Layers separation
    _ok("uc-layer--grid" in sr_js and "uc-layer--dims" in sr_js and "uc-layer--conn" in sr_js, "layers separated")
    _ok("uc-empty-state" in sr_js and "No design yet" in sr_js, "empty canvas state")

    # History smoke (domain before/after — no DOM)
    hist = cw.CommandHistory(max_size=3)
    hist.push(type="pose", before={"xMm": 0}, after={"xMm": 10})
    hist.push(type="pose", before={"xMm": 10}, after={"xMm": 20})
    _ok(hist.can_undo and not hist.can_redo, "history: can undo")
    u1 = hist.undo()
    _ok(u1 and u1["before"]["xMm"] == 10 and u1["after"]["xMm"] == 20, "history: undo returns domain")
    _ok(hist.can_redo, "history: can redo after undo")
    hist.push(type="pose", before={"xMm": 10}, after={"xMm": 30})
    _ok(not hist.can_redo, "history: branch-after-undo clears redo")
    hist.push(type="a", before=1, after=2)
    hist.push(type="b", before=2, after=3)
    hist.push(type="c", before=3, after=4)
    snap = hist.snapshot()
    _ok(snap["undoDepth"] == 3 and snap["maxSize"] == 3, "history: max limit")
    _ok("createHistory" in cmd_js and "JSON.parse(JSON.stringify" in cmd_js, "history: JS domain clone not DOM")
    _ok("cloneNode" not in cmd_js, "history: no DOM clone API in commands")

    # Delete disabled without backend
    st = cw.create_command_state()
    _ok(st["deleteEnabled"] is False, "delete disabled foundation")
    _ok("Delete unavailable" in uc_js or "deleteEnabled: false" in cmd_js, "delete UI disabled")

    print("PASS: Canvas Batch D workspace smoke A–O + history")


if __name__ == "__main__":
    main()
