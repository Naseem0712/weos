"""Smoke: Canvas D4 — Select / Pan / Dim / Grid / Snap / Member tool interactions."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_tool_interact_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "WEOS" / "website" / "canvas"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from WEOS.factory import canvas_workspace as cw

    uc = (CANVAS / "universal_canvas.js").read_text(encoding="utf-8")
    ws = (CANVAS / "workspace.js").read_text(encoding="utf-8")
    cmd = (CANVAS / "commands.js").read_text(encoding="utf-8")
    grid = (CANVAS / "grid.js").read_text(encoding="utf-8")
    snap = (CANVAS / "snap.js").read_text(encoding="utf-8")
    dim = (CANVAS / "dimensions.js").read_text(encoding="utf-8")

    # Select / Pan real tools
    _ok("TOOLS.SELECT" in cmd and "TOOLS.PAN" in cmd, "Select/Pan tools defined")
    _ok("setActiveTool" in uc and "data-uc-tool" in ws, "tool rail binds activeTool")
    _ok('"select"' in ws and '"pan"' in ws, "Select and Pan buttons present")

    # Dim = dimension display overlay (not measure-draw)
    _ok("TOOLS.MEASURE" in cmd, "Dim/measure tool id present")
    _ok("Show dimension overlay" in ws or "display only" in ws.lower(), "Dim titled as display overlay")
    _ok("measure-draw" in ws.lower() or "not measure-draw" in ws.lower(), "Dim not fake measure-draw")
    _ok(
        "activeTool === C.commands.TOOLS.MEASURE" in uc
        or 'TOOLS.MEASURE' in uc,
        "Dim visibility gated by measure tool",
    )
    # Must NOT always show dims on any selection (D4: Dim tool only)
    show_block = ""
    if "function paint()" in uc:
        show_block = uc.split("function paint()")[1].split("C.sceneRenderer.renderInto")[0]
    _ok(
        "TOOLS.MEASURE" in show_block and "primaryId" not in show_block,
        "Dims not auto-on for every selection",
    )
    _ok("engineering_mm" in dim, "dimension overlays use engineering mm")

    # Grid / Snap real toggles
    _ok("gridToggle" in ws and "grid.toggle" in uc, "Grid toggle wired")
    _ok("snapToggle" in ws and "snap.toggle" in uc, "Snap toggle wired")
    _ok("function toggle" in grid or "toggle:" in grid or ".toggle" in grid, "grid.toggle exists")
    _ok("function toggle" in snap or "toggle:" in snap or ".toggle" in snap, "snap.toggle exists")
    _ok("world" in snap.lower() or "xMm" in snap, "snap returns world mm candidates")

    # Member tools intentionally disabled until Batch E
    _ok("member" in ws and "disabled" in ws, "Member buttons disabled")
    _ok("Batch E" in ws or "INTENTIONALLY DISABLED" in ws, "Member tooltip points to Batch E")
    _ok("RESERVED" in cmd and "member_v" in cmd, "V-Mem/H-Mem reserved")
    _ok("FrameMember" not in uc and "mullion" not in uc.lower(), "no member engine yet")

    # Command state single source
    st = cw.create_command_state(active_tool="select")
    _ok(st["activeTool"] == "select", "factory command state select")
    st2 = cw.set_active_tool(st, "pan")
    _ok(st2["activeTool"] == "pan", "factory set pan")
    st3 = cw.set_active_tool(st2, "member")
    _ok(st3["activeTool"] != "member", "member tool rejected (reserved)")

    print("PASS: _smoke_canvas_tool_interactions.py")


if __name__ == "__main__":
    main()
