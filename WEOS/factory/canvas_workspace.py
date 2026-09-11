"""Canvas Batch D/E — Professional Universal Canvas Workspace foundations.

Pure helpers for command state, history, grid, snap, dimensions, and save status.
Batch E enables FrameMember / Cell tools when product supportsFrameGrid.
World geometry stays engineering mm.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, MutableMapping, Sequence

BATCH_ID = "CANVAS-E"

TOOL_SELECT = "select"
TOOL_PAN = "pan"
TOOL_MEASURE = "measure"
TOOL_MEMBER = "member"
TOOL_MEMBER_V = "member_v"
TOOL_MEMBER_H = "member_h"
TOOL_GRID = "grid_split"

ACTIVE_TOOLS = (
    TOOL_SELECT,
    TOOL_PAN,
    TOOL_MEASURE,
    TOOL_MEMBER,
    TOOL_MEMBER_V,
    TOOL_MEMBER_H,
    TOOL_GRID,
)
# Specialty products keep these visually present but disabled unless capability says otherwise.
STRUCTURE_TOOLS = (TOOL_MEMBER, TOOL_MEMBER_V, TOOL_MEMBER_H, TOOL_GRID)
RESERVED_TOOLS: tuple[str, ...] = ()  # Batch E: no longer reserved globally

ZOOM_MIN = 0.15
ZOOM_MAX = 6.0
HISTORY_MAX_DEFAULT = 50

SAVE_LOCAL = "local"
SAVE_UNSAVED = "unsaved"
SAVE_SAVING = "saving"
SAVE_SAVED = "saved"
SAVE_ERROR = "error"


def clamp_zoom(zoom: float, *, lo: float = ZOOM_MIN, hi: float = ZOOM_MAX) -> float:
    try:
        z = float(zoom)
    except (TypeError, ValueError):
        z = 1.0
    if not (z == z) or z <= 0:  # NaN or non-positive
        z = 1.0
    # Infinity / extreme — clamp without overflowing round()
    if z == float("inf") or z > hi * 10:
        return float(hi)
    if z == float("-inf"):
        return float(lo)
    return max(lo, min(hi, round(z * 100) / 100))


def create_command_state(
    *,
    active_tool: str = TOOL_SELECT,
    zoom: float = 1.0,
    save_status: str = SAVE_LOCAL,
    selected_ids: Sequence[str] | None = None,
    grid_visible: bool = True,
    snap_enabled: bool = True,
    structure_enabled: bool = False,
) -> dict[str, Any]:
    tool = str(active_tool or TOOL_SELECT).lower()
    if tool not in ACTIVE_TOOLS:
        tool = TOOL_SELECT
    if tool in STRUCTURE_TOOLS and not structure_enabled:
        tool = TOOL_SELECT
    ids = [str(x) for x in (selected_ids or []) if str(x)]
    return {
        "batch": BATCH_ID,
        "activeTool": tool,
        "canUndo": False,
        "canRedo": False,
        "selection": {
            "selectedIds": ids,
            "primaryId": ids[0] if ids else None,
            "kind": "none",
        },
        "zoom": clamp_zoom(zoom),
        "saveStatus": save_status
        if save_status in (SAVE_LOCAL, SAVE_UNSAVED, SAVE_SAVING, SAVE_SAVED, SAVE_ERROR)
        else SAVE_LOCAL,
        "gridVisible": bool(grid_visible),
        "snapEnabled": bool(snap_enabled),
        "cursor": {"xMm": None, "yMm": None},
        "deleteEnabled": False,
        "structureEnabled": bool(structure_enabled),
    }


def set_active_tool(
    state: MutableMapping[str, Any],
    tool: str,
    *,
    structure_enabled: bool | None = None,
) -> dict[str, Any]:
    t = str(tool or TOOL_SELECT).lower()
    enabled = (
        bool(structure_enabled)
        if structure_enabled is not None
        else bool(state.get("structureEnabled"))
    )
    if t in STRUCTURE_TOOLS and not enabled:
        return dict(state)
    if t not in ACTIVE_TOOLS:
        t = TOOL_SELECT
    out = dict(state)
    out["activeTool"] = t
    out["structureEnabled"] = enabled
    return out


def set_structure_enabled(state: MutableMapping[str, Any], enabled: bool) -> dict[str, Any]:
    out = dict(state)
    out["structureEnabled"] = bool(enabled)
    if not enabled and out.get("activeTool") in STRUCTURE_TOOLS:
        out["activeTool"] = TOOL_SELECT
    return out


def sync_selection(
    state: MutableMapping[str, Any],
    *,
    selected_ids: Sequence[str] | None = None,
    kind: str = "element",
) -> dict[str, Any]:
    ids = [str(x) for x in (selected_ids or []) if str(x)]
    out = dict(state)
    out["selection"] = {
        "selectedIds": ids,
        "primaryId": ids[0] if ids else None,
        "kind": kind if ids else "none",
    }
    return out


def save_status_from_durable(
    *,
    saving: bool = False,
    error: bool = False,
    persisted: bool | None = None,
    durable: bool | None = None,
    local_only: bool = False,
) -> str:
    if error:
        return SAVE_ERROR
    if saving:
        return SAVE_SAVING
    if local_only:
        return SAVE_LOCAL
    if persisted is True and durable is True:
        return SAVE_SAVED
    if persisted is False or durable is False:
        return SAVE_ERROR
    return SAVE_UNSAVED


def keyboard_shortcut_allowed(
    *, tag_name: str | None, is_content_editable: bool = False
) -> bool:
    if is_content_editable:
        return False
    tag = (tag_name or "").lower()
    return tag not in ("input", "textarea", "select")


class CommandHistory:
    def __init__(self, *, max_size: int = HISTORY_MAX_DEFAULT) -> None:
        self.max_size = max(1, int(max_size))
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []

    def push(
        self,
        *,
        type: str,
        payload: Mapping[str, Any] | None = None,
        before: Any = None,
        after: Any = None,
        id: str | None = None,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        cmd = {
            "id": id or f"cmd-{len(self._undo) + 1}",
            "type": str(type or "noop"),
            "payload": dict(payload or {}),
            "before": deepcopy(before),
            "after": deepcopy(after),
            "timestamp": timestamp,
        }
        self._undo.append(cmd)
        if len(self._undo) > self.max_size:
            self._undo = self._undo[-self.max_size :]
        self._redo.clear()
        return cmd

    def undo(self) -> dict[str, Any] | None:
        if not self._undo:
            return None
        cmd = self._undo.pop()
        self._redo.append(cmd)
        return cmd

    def redo(self) -> dict[str, Any] | None:
        if not self._redo:
            return None
        cmd = self._redo.pop()
        self._undo.append(cmd)
        return cmd

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def snapshot(self) -> dict[str, Any]:
        return {
            "canUndo": self.can_undo,
            "canRedo": self.can_redo,
            "undoDepth": len(self._undo),
            "redoDepth": len(self._redo),
            "maxSize": self.max_size,
        }


def grid_spacing_for_zoom(zoom: float, *, base_mm: float = 100.0) -> dict[str, float]:
    z = clamp_zoom(zoom)
    target_px = 50.0
    minor = base_mm
    while minor * z < target_px * 0.45 and minor < 5000:
        minor *= 2
    while minor * z > target_px * 2.2 and minor > 10:
        minor /= 2
    minor = max(10.0, round(minor))
    major = minor * 5
    return {"minorMm": float(minor), "majorMm": float(major), "zoom": z}


def snap_world_mm(
    x_mm: float,
    y_mm: float,
    *,
    enabled: bool = True,
    grid_mm: float = 100.0,
    elements: Sequence[Mapping[str, Any]] | None = None,
    tolerance_px: float = 8.0,
    zoom: float = 1.0,
    prefer: Sequence[str] | None = None,
) -> dict[str, Any]:
    x = float(x_mm)
    y = float(y_mm)
    if not enabled:
        return {"xMm": x, "yMm": y, "snapped": False, "source": None, "candidates": []}

    z = max(1e-9, float(zoom) or 1.0)
    tol_mm = float(tolerance_px) / z
    prefer_list = list(prefer or ("grid", "edge", "center", "point"))
    candidates: list[dict[str, Any]] = []

    g = max(1e-9, float(grid_mm) or 100.0)
    gx = round(x / g) * g
    gy = round(y / g) * g
    candidates.append(
        {"source": "grid", "xMm": gx, "yMm": gy, "distMm": ((gx - x) ** 2 + (gy - y) ** 2) ** 0.5}
    )

    for el in elements or []:
        ex = float(el.get("xMm") or 0)
        ey = float(el.get("yMm") or 0)
        ew = float(el.get("widthMm") or 0)
        eh = float(el.get("heightMm") or 0)
        edges = [
            ("edge", ex, y),
            ("edge", ex + ew, y),
            ("edge", x, ey),
            ("edge", x, ey + eh),
            ("edge", ex, ey),
            ("edge", ex + ew, ey),
            ("edge", ex, ey + eh),
            ("edge", ex + ew, ey + eh),
        ]
        for src, sx, sy in edges:
            d = ((sx - x) ** 2 + (sy - y) ** 2) ** 0.5
            candidates.append({"source": src, "xMm": sx, "yMm": sy, "distMm": d})
        cx, cy = ex + ew / 2.0, ey + eh / 2.0
        candidates.append(
            {"source": "center", "xMm": cx, "yMm": cy, "distMm": ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5}
        )

    best = None
    for src in prefer_list:
        pool = [c for c in candidates if c["source"] == src and c["distMm"] <= tol_mm]
        if not pool:
            continue
        pool.sort(key=lambda c: c["distMm"])
        best = pool[0]
        break
    if best is None:
        near = [c for c in candidates if c["distMm"] <= tol_mm]
        if near:
            near.sort(key=lambda c: c["distMm"])
            best = near[0]

    if best is None:
        return {"xMm": x, "yMm": y, "snapped": False, "source": None, "candidates": candidates[:8]}

    return {
        "xMm": float(best["xMm"]),
        "yMm": float(best["yMm"]),
        "snapped": True,
        "source": best["source"],
        "candidates": candidates[:8],
        "toleranceMm": tol_mm,
        "tolerancePx": float(tolerance_px),
    }


def dimension_overlay_from_element(el: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not el:
        return None
    w = el.get("widthMm")
    h = el.get("heightMm")
    if w is None or h is None:
        return None
    return {
        "kind": "overall",
        "elementId": el.get("elementId") or el.get("element_id"),
        "widthMm": float(w),
        "heightMm": float(h),
        "xMm": float(el.get("xMm") or 0),
        "yMm": float(el.get("yMm") or 0),
        "labelW": f"{int(round(float(w)))} mm",
        "labelH": f"{int(round(float(h)))} mm",
        "source": "engineering_mm",
    }


def resize_preserve_viewport(
    *,
    old_w: float,
    old_h: float,
    new_w: float,
    new_h: float,
    zoom: float,
    pan_x: float,
    pan_y: float,
    world_origin_x: float = 0.0,
    world_origin_y: float = 0.0,
) -> dict[str, float]:
    z = clamp_zoom(zoom)
    ow = max(1.0, float(old_w) or 1.0)
    oh = max(1.0, float(old_h) or 1.0)
    nw = max(1.0, float(new_w) or 1.0)
    nh = max(1.0, float(new_h) or 1.0)
    cx = (ow / 2.0 - float(pan_x)) / z + float(world_origin_x)
    cy = (oh / 2.0 - float(pan_y)) / z + float(world_origin_y)
    new_pan_x = nw / 2.0 - (cx - float(world_origin_x)) * z
    new_pan_y = nh / 2.0 - (cy - float(world_origin_y)) * z
    return {
        "zoom": z,
        "panX": new_pan_x,
        "panY": new_pan_y,
        "worldOriginX": float(world_origin_x),
        "worldOriginY": float(world_origin_y),
    }


def fit_with_padding(
    bounds: Mapping[str, float],
    viewport_w: float,
    viewport_h: float,
    *,
    padding: float = 48.0,
) -> float:
    """Compute centered Fit zoom (display-only). Matches JS viewport.computeFit."""
    return float(compute_fit(bounds, viewport_w, viewport_h, padding=padding)["zoom"])


def compute_fit(
    bounds: Mapping[str, float],
    viewport_w: float,
    viewport_h: float,
    *,
    padding: float = 48.0,
) -> dict[str, float]:
    """Deterministic Fit: center engineering bounds in viewport with padding.

    Never uses SVG viewBox units — callers pass widthMm/heightMm scene bounds.
    Safe for tall/wide/tiny/invalid (falls back to 1000×1000).
    """
    try:
        ww = float(bounds.get("width") or 0)
    except (TypeError, ValueError):
        ww = 0.0
    try:
        wh = float(bounds.get("height") or 0)
    except (TypeError, ValueError):
        wh = 0.0
    if not (ww > 0) or ww != ww:
        ww = 1000.0
    if not (wh > 0) or wh != wh:
        wh = 1000.0
    try:
        min_x = float(bounds.get("minX") if bounds.get("minX") is not None else 0)
    except (TypeError, ValueError):
        min_x = 0.0
    try:
        min_y = float(bounds.get("minY") if bounds.get("minY") is not None else 0)
    except (TypeError, ValueError):
        min_y = 0.0
    if min_x != min_x:
        min_x = 0.0
    if min_y != min_y:
        min_y = 0.0

    pad = float(padding) if padding == padding and padding is not None else 48.0
    if pad < 0 or pad != pad:
        pad = 48.0
    if wh > ww * 1.35:
        pad = min(pad, 40.0)
    elif ww > wh * 1.8:
        pad = min(pad, 48.0)

    vw = max(1.0, float(viewport_w) or 1.0)
    vh = max(1.0, float(viewport_h) or 1.0)
    avail_w = max(1.0, vw - 2 * pad)
    avail_h = max(1.0, vh - 2 * pad)
    raw = min(avail_w / ww, avail_h / wh)
    if not (raw > 0) or raw != raw:
        raw = 1.0
    zoom = clamp_zoom(raw)
    cx = min_x + ww / 2.0
    cy = min_y + wh / 2.0
    pan_x = vw / 2.0 - cx * zoom
    pan_y = vh / 2.0 - cy * zoom
    return {
        "zoom": float(zoom),
        "panX": float(pan_x),
        "panY": float(pan_y),
        "worldOriginX": 0.0,
        "worldOriginY": 0.0,
        "width": ww,
        "height": wh,
        "minX": min_x,
        "minY": min_y,
        "padding": pad,
        "viewportW": vw,
        "viewportH": vh,
    }