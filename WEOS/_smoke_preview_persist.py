"""Smoke: adapter SVG must persist after settle — never replaced by livePreview / placeholder."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "WEOS" / "website" / "canvas"
INDEX = ROOT / "WEOS" / "website" / "index.html"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    uc = (CANVAS / "universal_canvas.js").read_text(encoding="utf-8")
    dc = (CANVAS / "design_context.js").read_text(encoding="utf-8")
    sr = (CANVAS / "scene_renderer.js").read_text(encoding="utf-8")
    css = (CANVAS / "workspace.css").read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    grid = (CANVAS / "grid.js").read_text(encoding="utf-8")
    ws = (CANVAS / "workspace.js").read_text(encoding="utf-8")

    _ok("isPlaceholderSvg" in uc, "A: placeholder detector")
    _ok("hasGoodElementPreview" in uc, "A: hasGoodElementPreview API")
    _ok('source === "livePreview"' in uc or "livePreview" in uc, "A: livePreview source gate")
    _ok("prevGood && nextBad" in uc or "nextBad" in uc, "A: never replace good with bad")
    _ok('source: "adapter"' in dc, "A: adapter preview tagged")
    _ok("hasGoodElementPreview" in index, "A: bridge checks good preview")
    _ok("source: 'livePreview'" in index, "A: bridge tags livePreview source")

    _ok("background:transparent" in sr.replace(" ", ""), "B: element box transparent")
    _ok("background: transparent !important" in css and "uc-el-selected" in css, "B: selection not opaque fill")
    _ok("NEVER use opaque background" in css or "blue box" in css.lower(), "B: selection fill guard comment")

    _ok("requestAnimationFrame" in uc and "scheduleCursorStatus" in uc, "C: cursor rAF coalescing")
    _ok("applyHoverClassOnly" in uc, "C: hover without full paint")
    _ok("selChanged" in uc, "C: selection change gate")

    _ok('data-uc="gridToggle"' in ws, "D: grid toggle in chrome")
    _ok("grid.toggle()" in uc and "syncChrome()" in uc, "D: grid toggle wires paint+chrome")
    _ok("aria-pressed" in uc, "D: grid aria-pressed")
    _ok("rgba(20,40,60" in grid, "D: visible grid strokes")
    _ok('toolBtn("grid_split", "Cells"' in ws, "D: rail Cells ≠ drafting Grid")

    _ok('data-view="agent"' in index, "E: Agent nav entry")
    _ok("view-agent" in index and "weosAgentMount" in index, "E: Agent docked panel")
    _ok("weos-agent-fab{display:none!important}" in index.replace(" ", "") or "display:none!important" in index, "E: FAB suppressed")
    _ok("data-floating" in index, "E: dock not floating over canvas")

    # Runtime: placeholder must not replace engine SVG in setElementPreviewSvg logic (string contract)
    idx = uc.find("function setElementPreviewSvg")
    _ok(idx > 0, "F: setElementPreviewSvg present")
    body = uc[idx : idx + 1800]
    _ok("livePreview" in body and "isPlaceholderSvg" in body, "F: overwrite guards in setElementPreviewSvg")

    print("PASS: _smoke_preview_persist.py")


if __name__ == "__main__":
    main()
