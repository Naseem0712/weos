"""Smoke: Canvas Batch E — member canvas interaction wiring (static + API)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_member_canvas_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

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
    sys.path.insert(0, str(ROOT))

    mt = (CANVAS / "member_tools.js").read_text(encoding="utf-8")
    uc = (CANVAS / "universal_canvas.js").read_text(encoding="utf-8")
    cmd = (CANVAS / "commands.js").read_text(encoding="utf-8")
    ws = (CANVAS / "workspace.js").read_text(encoding="utf-8")
    css = (CANVAS / "workspace.css").read_text(encoding="utf-8")
    idx = INDEX.read_text(encoding="utf-8")

    _ok("confirmGhost" in mt and "updateGhost" in mt and "promptGrid" in mt, "ghost + grid APIs")
    _ok("cancelGhost" in mt and "Escape" in uc, "Esc cancel")
    _ok("positionMm" in mt and " mm" in mt, "mm labels")
    _ok("setStructureEnabled" in uc and "STRUCTURE_TOOLS" in cmd, "capability gating")
    _ok('toolBtn("member_v"' in ws and "disabled" not in ws.split("member_v")[1][:80], "V-Mem enabled in shell")
    _ok("/static/canvas/member_tools.js" in idx, "index loads member_tools")
    _ok("uc-layer--structure" in css and "uc-cell" in css and "uc-member" in css, "overlay CSS")
    _ok("deleteMember" in mt and "delete_member" in uc, "delete/merge wired")
    _ok("structure/undo" in mt or "structure/undo" in uc, "server undo path")
    _ok("Batch F" in (ROOT / "WEOS" / "factory" / "member_grid.py").read_text(encoding="utf-8"), "Batch F deferred noted")
    _ok("forbidProductAssignment" in (ROOT / "WEOS" / "factory" / "member_grid.py").read_text(encoding="utf-8"), "no cell assignment")

    from WEOS.factory import canvas_workspace as cw

    st = cw.create_command_state(structure_enabled=True)
    st = cw.set_active_tool(st, cw.TOOL_MEMBER_V)
    _ok(st["activeTool"] == cw.TOOL_MEMBER_V, "V-Mem tool when enabled")
    st2 = cw.create_command_state(structure_enabled=False)
    st2 = cw.set_active_tool(st2, cw.TOOL_MEMBER_H)
    _ok(st2["activeTool"] == cw.TOOL_SELECT, "H-Mem refused when capability off")

    print("PASS: _smoke_member_canvas_interaction")


if __name__ == "__main__":
    main()
