"""
Geometry Engine — sliding layout from named profile geometry rules.

Supports optional fix partitions (top/bottom/left/right) and mesh track count.
Coordinates are never hardcoded; every inset/width comes from profile JSON geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from WEOS.factory.dimensioning import (
    DimStyleParams,
    dim_offset_above,
    dim_offset_below,
    dim_offset_left,
    dim_offset_right,
    horizontal_dim,
    vertical_dim,
)
from WEOS.factory.geometry import (
    frame_miter_segments,
    rect_polyline,
    u_polyline_open_left,
    u_polyline_open_right,
    vertical_segment,
)
from WEOS.factory.layout_options import normalize_partitions, partition_sizes
from WEOS.factory.types import DrawingModel, Point, Rect, Segment

# Fold & Sliding size envelope (feet → mm)
MM_PER_FOOT = 304.8
BIFOLD_MAX_WIDTH_MM = 25.0 * MM_PER_FOOT   # 7620 mm
BIFOLD_MAX_HEIGHT_MM = 12.0 * MM_PER_FOOT  # 3657.6 mm


@dataclass(frozen=True, slots=True)
class FixPanel:
    side: str
    size_mm: float
    role: str
    outer: Rect
    glass: Rect


@dataclass(frozen=True, slots=True)
class ShutterPanel:
    """One sliding sash (glass or mesh) inside the sliding band.

    depth: 0 = frontmost (inner / room side); larger = further back (outer track).
    track_label: friendly track name ('front' / 'back' / 'mesh' / 'fix').
    open_dir: -1 slides left, +1 slides right, 0 = fixed / non-operable.
    handle_side: which vertical stile carries the handle ('left' / 'right' / None).
    """

    index: int
    role: str
    operable: bool
    outer: Rect
    glass: Rect
    depth: int
    track_label: str
    open_dir: int
    handle_side: str | None = None
    handle: Rect | None = None
    nom_x0: float = 0.0
    nom_x1: float = 0.0
    pack: str = ""
    hinge_side: str | None = None

    @property
    def nominal_width(self) -> float:
        return self.nom_x1 - self.nom_x0


def _build_shutters(
    area: Rect,
    *,
    frame_width: float,
    glass_clip: float,
    interlock_width: float,
    glass_count: int,
    mesh_count: int,
    opening: str,
    fixed_set: set[int],
    handle_length: float | None,
    system: str = "sliding",
    handle_level: float = 0.5,
    handle_overrides: Mapping[Any, Any] | None = None,
) -> tuple[list[ShutterPanel], list[Rect], list[Rect]]:
    """Divide the band into exactly-equal glass sashes (+ mesh sashes).

    Each sash gets an identical nominal share of the usable width
    (``band_width / glass_count``) so widths sum back to the usable width with no
    leftover mm.

    ``system`` selects behaviour:
      * ``sliding`` — back-track sashes lap the front-track neighbour by the
        interlock (front/back stagger); 2-sash windows carry handles on the
        OUTER vertical stiles (real slider look), others meet at the centre.
      * ``casement`` — coplanar openable sashes with handles on the centre-meeting
        stile and hinges on the OPPOSITE (outer) stile.

    Handle vertical position is a shared level (``handle_level`` as a 0..1 fraction
    of the sash height) so sliding handles line up. ``handle_overrides`` maps a
    panel index → ``{"side": left|right|none, "x": 0..1, "y": 0..1}`` to move a
    handle anywhere (casement) or remove/add it on any panel.

    Returns ``(panels, handles, hinges)``.
    """
    fw = float(frame_width)
    iw = float(interlock_width)
    G = max(int(glass_count), 1)
    x0, y0, x1, y1 = area.x0, area.y0, area.x1, area.y1
    band_w = x1 - x0
    band_h = y1 - y0
    casement = str(system).strip().lower() in ("casement", "openable", "opening")
    # Exact equal nominal boundaries (last boundary pinned to x1 → no rounding drift)
    bounds = [x0 + (band_w * k) / G for k in range(G + 1)]
    bounds[0] = x0
    bounds[-1] = x1

    hlen = float(handle_length) if handle_length and handle_length > 0 else max(min(band_h * 0.16, 300.0), 120.0)
    hlen = min(hlen, band_h * 0.9)
    hw = max(fw * 0.5, 12.0)
    # Interlock lap: the front sash laps a FULL stile over the back sash so the two
    # meeting stiles nest into a single tight interlock band (no mullion-like gap).
    overlap = min(max(fw, iw), (band_w / G) * 0.45)
    hlevel = min(max(float(handle_level), 0.04), 0.96)

    overrides: dict[int, Mapping[str, Any]] = {}
    for k, v in dict(handle_overrides or {}).items():
        try:
            overrides[int(k)] = v if isinstance(v, Mapping) else {}
        except (TypeError, ValueError):
            continue

    center_l = (G - 1) // 2
    center_r = G // 2
    mode = "center" if opening == "center" else "telescopic"

    def depth_for(i: int) -> int:
        if casement:
            return 1  # coplanar openable sashes
        if mode == "center":
            if G == 2:
                return 2 if i == 0 else 1
            return min(abs(i - center_l), abs(i - center_r)) + 1
        return G - i  # telescopic: leftmost deepest, rightmost frontmost

    depths = [(G + 1) if i in fixed_set else depth_for(i) for i in range(G)]

    def default_handle_side(i: int, operable: bool) -> str | None:
        # Fixed panels NEVER carry a handle (applies to every system).
        if not operable:
            return None
        if casement:
            # Handle on the centre-meeting stile (hinge ends up on the outer stile)
            return "right" if i <= center_l else "left"
        # --- Sliding handle placement rules (fix-aware) ---
        # 2 glass: handle on BOTH doors, on the OUTER stiles (left→left, right→right).
        if G <= 2:
            return "left" if i == 0 else "right"
        # 3 glass: handles ONLY on the outer sliding doors; the centre door gets none.
        if G == 3:
            if i == 0:
                return "left"
            if i == G - 1:
                return "right"
            return None
        # 4+ glass (centre-opening family): every operable door gets a handle.
        #   - outer doors → outer stile
        #   - inner doors → their centre-meeting stile
        # Fixed side doors are already excluded above (operable=False → None), so
        # when the sides ARE fixed only the selected sliding doors keep handles.
        if i == 0:
            return "left"
        if i == G - 1:
            return "right"
        return "right" if i <= center_l else "left"

    def make_handle(nom_a: float, nom_b: float, side: str | None, x_frac: float | None, y_frac: float) -> Rect | None:
        if side == "none":
            return None
        yc = y0 + band_h * y_frac
        if x_frac is not None:
            xc = nom_a + (nom_b - nom_a) * min(max(x_frac, 0.0), 1.0)
        elif side == "right":
            xc = nom_b - fw / 2.0
        elif side == "left":
            xc = nom_a + fw / 2.0
        else:
            return None
        return Rect(xc - hw / 2.0, yc - hlen / 2.0, xc + hw / 2.0, yc + hlen / 2.0)

    panels: list[ShutterPanel] = []
    handles: list[Rect] = []
    hinges: list[Rect] = []
    knuckle_w = max(fw * 0.7, 14.0)
    knuckle_h = max(band_h * 0.05, 18.0)

    for i in range(G):
        nom_x0 = bounds[i]
        nom_x1 = bounds[i + 1]
        # Front sash (smaller depth) laps OVER a differing-depth neighbour by the
        # interlock; the back sash keeps its nominal edge (hidden behind front).
        xa, xb = nom_x0, nom_x1
        if not casement:
            if i > 0 and depths[i] != depths[i - 1] and depths[i] < depths[i - 1]:
                xa = nom_x0 - overlap
            if i < G - 1 and depths[i] != depths[i + 1] and depths[i] < depths[i + 1]:
                xb = nom_x1 + overlap
        outer = Rect(xa, y0, xb, y1)
        glass = outer.inset(fw, fw, fw, fw)
        is_fixed = i in fixed_set
        operable = not is_fixed

        ov_cfg = overrides.get(i) or {}
        handle_side = ov_cfg.get("side") if "side" in ov_cfg else default_handle_side(i, operable)
        x_frac = ov_cfg.get("x")
        try:
            x_frac = float(x_frac) if x_frac is not None else None
        except (TypeError, ValueError):
            x_frac = None
        try:
            y_frac = float(ov_cfg["y"]) if "y" in ov_cfg else hlevel
        except (TypeError, ValueError):
            y_frac = hlevel
        # Sliding handles share the common vertical level (equal on every sash)
        if not casement:
            y_frac = hlevel

        handle_rect = make_handle(nom_x0, nom_x1, handle_side, x_frac, y_frac) if handle_side else None
        if handle_rect is not None:
            handles.append(handle_rect)

        # Open direction: sliding slides toward centre (away from outer handle);
        # casement swing sign follows the hinge side.
        if operable:
            if casement:
                open_dir = 1 if (i <= center_l) else -1
            elif G == 2:
                open_dir = 1 if i == 0 else -1
            elif mode == "center":
                open_dir = -1 if i <= center_l else 1
            else:
                open_dir = 1
        else:
            open_dir = 0

        # Casement hinge is on the OPPOSITE stile from the handle
        hinge_side: str | None = None
        if casement and handle_rect is not None:
            handle_cx = (handle_rect.x0 + handle_rect.x1) / 2.0
            on_right = handle_cx > (nom_x0 + nom_x1) / 2.0
            hinge_side = "left" if on_right else "right"
            hx = nom_x0 + knuckle_w * 0.0 + fw / 2.0 if hinge_side == "left" else nom_x1 - fw / 2.0
            for t in (0.18, 0.5, 0.82):
                ky = y0 + band_h * t
                hinges.append(Rect(hx - knuckle_w / 2.0, ky - knuckle_h / 2.0, hx + knuckle_w / 2.0, ky + knuckle_h / 2.0))

        depth = depths[i]
        if is_fixed:
            track_label = "fix"
        elif casement:
            track_label = "sash"
        else:
            track_label = "front" if depth == 1 else "back"

        panels.append(
            ShutterPanel(
                index=i,
                role="glass",
                operable=operable,
                outer=outer,
                glass=glass,
                depth=depth,
                track_label=track_label,
                open_dir=open_dir,
                handle_side=handle_side if handle_side != "none" else None,
                handle=handle_rect,
                nom_x0=nom_x0,
                nom_x1=nom_x1,
                hinge_side=hinge_side,
            )
        )

    if mesh_count and mesh_count > 0 and not casement:
        # Mesh rule: each mesh sash is EXACTLY one sliding-panel wide (band_w / G),
        # never the full opening. Meshes stack from the left jamb rightward.
        panel_w = band_w / G
        for j in range(int(mesh_count)):
            mx0 = x0 + panel_w * j
            mx1 = min(mx0 + panel_w, x1)
            mouter = Rect(mx0, y0, mx1, y1)
            mglass = mouter.inset(fw * 0.6, fw * 0.6, fw * 0.6, fw * 0.6)
            panels.append(
                ShutterPanel(
                    index=G + j,
                    role="mesh",
                    operable=True,
                    outer=mouter,
                    glass=mglass,
                    depth=0,
                    track_label="mesh",
                    open_dir=0,
                    handle_side=None,
                    handle=None,
                    nom_x0=mx0,
                    nom_x1=mx1,
                )
            )
    return panels, handles, hinges


def _build_bifold_leaves(
    area: Rect,
    *,
    frame_width: float,
    fold_left: int,
    fold_right: int,
    handle_length: float | None,
) -> tuple[list[ShutterPanel], list[Rect], list[Rect]]:
    """Fold & Sliding: equal-width leaves split into a left pack + right pack.

    All leaves share an identical width (usable width / total leaves). Leaves in
    the left pack fold to the left, the right pack folds to the right; the two
    innermost leaves meet at the centre and carry the handles. Returns
    (leaves, handles, hinges).
    """
    fw = float(frame_width)
    L = max(int(fold_left), 0)
    R = max(int(fold_right), 0)
    total = max(L + R, 1)
    if L == 0:
        L, R = total, 0
    x0, y0, x1, y1 = area.x0, area.y0, area.x1, area.y1
    band_w = x1 - x0
    band_h = y1 - y0
    bounds = [x0 + (band_w * k) / total for k in range(total + 1)]
    bounds[0] = x0
    bounds[-1] = x1
    cy = (y0 + y1) / 2.0

    hlen = float(handle_length) if handle_length and handle_length > 0 else max(min(band_h * 0.16, 300.0), 120.0)
    hlen = min(hlen, band_h * 0.9)
    hw = max(fw * 0.5, 12.0)

    meeting = L  # boundary index between the two packs
    leaves: list[ShutterPanel] = []
    handles: list[Rect] = []

    for i in range(total):
        nx0, nx1 = bounds[i], bounds[i + 1]
        outer = Rect(nx0, y0, nx1, y1)
        glass = outer.inset(fw, fw, fw, fw)
        pack = "L" if i < meeting else "R"
        # Distance from the central meeting line → stacking depth when folded
        depth = (meeting - i) if pack == "L" else (i - meeting + 1)
        depth = max(depth, 1)
        open_dir = -1 if pack == "L" else 1

        # Hinge sides: leaves hinge to their pack neighbours; the lead (meeting)
        # leaf of each pack carries the handle on its centre-facing stile.
        handle_side: str | None = None
        if pack == "L" and i == meeting - 1:
            handle_side = "right"
        elif pack == "R" and i == meeting:
            handle_side = "left"

        handle_rect: Rect | None = None
        if handle_side:
            xc = nx1 - fw / 2.0 if handle_side == "right" else nx0 + fw / 2.0
            handle_rect = Rect(xc - hw / 2.0, cy - hlen / 2.0, xc + hw / 2.0, cy + hlen / 2.0)
            handles.append(handle_rect)

        # hinge_side marks the stile shared with the outward pack neighbour
        hinge_side = None
        if pack == "L" and i > 0:
            hinge_side = "left"
        elif pack == "R" and i < total - 1:
            hinge_side = "right"

        leaves.append(
            ShutterPanel(
                index=i,
                role="glass",
                operable=True,
                outer=outer,
                glass=glass,
                depth=depth,
                track_label=f"fold_{pack.lower()}",
                open_dir=open_dir,
                handle_side=handle_side,
                handle=handle_rect,
                nom_x0=nx0,
                nom_x1=nx1,
                pack=pack,
                hinge_side=hinge_side,
            )
        )

    # Hinge knuckles: at every internal boundary WITHIN a pack (not the centre),
    # plus a pivot at each pack's outer jamb edge.
    hinges: list[Rect] = []
    knuckle_w = max(fw * 0.7, 14.0)
    knuckle_h = max(band_h * 0.045, 18.0)

    def add_hinges_at(xc: float) -> None:
        for t in (0.2, 0.5, 0.8):
            ky = y0 + band_h * t
            hinges.append(Rect(xc - knuckle_w / 2.0, ky - knuckle_h / 2.0, xc + knuckle_w / 2.0, ky + knuckle_h / 2.0))

    for i in range(1, total):
        if i == meeting:
            continue  # centre meeting = opening, not a hinge
        add_hinges_at(bounds[i])
    # Outer pivots (frame jambs)
    if L > 0:
        add_hinges_at(bounds[0])
    if R > 0:
        add_hinges_at(bounds[total])

    return leaves, handles, hinges


@dataclass(frozen=True, slots=True)
class SlidingLayout:
    W: float
    H: float
    track_width: float
    frame_width: float
    interlock_width: float
    overlap: float
    glass_clip: float
    track: Rect
    interlock_left: float
    interlock_right: float
    shutter_inset: float
    left_shutter: Rect
    right_shutter: Rect
    left_glass: Rect
    right_glass: Rect
    left_clip: Rect
    right_clip: Rect
    fix_panels: tuple[FixPanel, ...] = ()
    mullions: tuple[Rect, ...] = ()
    mesh: bool = False
    track_count: float = 2.0
    sliding_area: Rect | None = None
    shutters: tuple[ShutterPanel, ...] = ()
    glass_count: int = 2
    mesh_count: int = 0
    opening: str = "center"
    system: str = "sliding"
    fold_left: int = 0
    fold_right: int = 0
    hinges: tuple[Rect, ...] = ()
    section_sizes: Mapping[str, float] | None = None
    notes: tuple[str, ...] = ()
    grid_spec: Mapping[str, Any] | None = None

    @property
    def left_shutter_width(self) -> float:
        return self.left_shutter.width

    @property
    def right_shutter_width(self) -> float:
        return self.right_shutter.width

    @property
    def left_glass_width(self) -> float:
        return self.left_glass.width

    @property
    def right_glass_width(self) -> float:
        return self.right_glass.width

    @property
    def glass_height(self) -> float:
        return self.left_glass.height

    def meta(self) -> dict[str, Any]:
        sliding = self.sliding_area or Rect(
            self.left_shutter.x0,
            self.left_shutter.y0,
            self.right_shutter.x1,
            self.left_shutter.y1,
        )
        return {
            "left_shutter_width": self.left_shutter_width,
            "right_shutter_width": self.right_shutter_width,
            "left_glass_width": self.left_glass_width,
            "right_glass_width": self.right_glass_width,
            "glass_height": self.glass_height,
            "interlock_left": self.interlock_left,
            "interlock_right": self.interlock_right,
            "shutter_inset": self.shutter_inset,
            "clear_opening_left": self.interlock_left - self.track.x0,
            "clear_opening_right": self.track.x1 - self.interlock_right,
            "mesh": self.mesh,
            "track_count": float(self.track_count),
            "glass_count": int(self.glass_count),
            "mesh_count": int(self.mesh_count),
            "opening": str(self.opening),
            "system": str(self.system),
            "fold_left": int(self.fold_left),
            "fold_right": int(self.fold_right),
            "hinges": [
                {"x0": round(h.x0, 2), "y0": round(h.y0, 2), "x1": round(h.x1, 2), "y1": round(h.y1, 2)}
                for h in self.hinges
            ],
            "sectionSizes": dict(self.section_sizes) if self.section_sizes else None,
            "notes": list(self.notes),
            "grid": dict(self.grid_spec) if self.grid_spec else None,
            "sliding_width": sliding.width,
            "sliding_height": sliding.height,
            "sliding_x0": sliding.x0,
            "sliding_y0": sliding.y0,
            "sliding_x1": sliding.x1,
            "sliding_y1": sliding.y1,
            "shutters": [
                {
                    "index": sp.index,
                    "role": sp.role,
                    "operable": sp.operable,
                    "depth": sp.depth,
                    "track": sp.track_label,
                    "openDir": sp.open_dir,
                    "handleSide": sp.handle_side,
                    "pack": sp.pack,
                    "hingeSide": sp.hinge_side,
                    "x0": round(sp.outer.x0, 2),
                    "x1": round(sp.outer.x1, 2),
                    "y0": round(sp.outer.y0, 2),
                    "y1": round(sp.outer.y1, 2),
                    "nomX0": round(sp.nom_x0, 2),
                    "nomX1": round(sp.nom_x1, 2),
                    "widthMm": round(sp.nominal_width, 1),
                    "glassWidthMm": round(sp.glass.width, 1),
                    "glassHeightMm": round(sp.glass.height, 1),
                    "handle": (
                        {
                            "x0": round(sp.handle.x0, 2),
                            "y0": round(sp.handle.y0, 2),
                            "x1": round(sp.handle.x1, 2),
                            "y1": round(sp.handle.y1, 2),
                        }
                        if sp.handle
                        else None
                    ),
                }
                for sp in self.shutters
            ],
            "partitions": [
                {
                    "side": fp.side,
                    "sizeMm": fp.size_mm,
                    "role": fp.role,
                    "widthMm": round(fp.outer.width, 1),
                    "heightMm": round(fp.outer.height, 1),
                    "glassWidthMm": round(fp.glass.width, 1),
                    "glassHeightMm": round(fp.glass.height, 1),
                }
                for fp in self.fix_panels
            ],
        }


def dim_style_from_profile(dimensioning: Mapping[str, Any]) -> DimStyleParams:
    """Dimension presentation — all values from profile JSON dimensioning section."""
    d = dimensioning or {}
    required = ("arrowSize", "textHeight", "offsetOuter", "offsetInner", "offsetDetail", "stackGap")
    missing = [k for k in required if k not in d]
    if missing:
        raise KeyError(f"profile.dimensioning missing keys: {', '.join(missing)}")
    return DimStyleParams(
        arrow_size=float(d["arrowSize"]),
        text_height=float(d["textHeight"]),
        offset_outer=float(d["offsetOuter"]),
        offset_inner=float(d["offsetInner"]),
        offset_detail=float(d["offsetDetail"]),
        stack_gap=float(d["stackGap"]),
    )


def compute_two_track_layout(
    width: float,
    height: float,
    geometry: Mapping[str, Any],
    *,
    partitions: Sequence[Mapping[str, Any]] | None = None,
    mesh: bool = False,
    track_count: float | None = None,
    glass_count: int | None = None,
    mesh_count: int | None = None,
    opening: str | None = None,
    fixed_shutters: Sequence[int] | None = None,
    system: str | None = None,
    fold_left: int | None = None,
    fold_right: int | None = None,
    section_sizes: Mapping[str, Any] | None = None,
    handle_level: float | None = None,
    handle_overrides: Mapping[Any, Any] | None = None,
    grid: Mapping[str, Any] | None = None,
) -> SlidingLayout:
    """Core sliding formulas from profile geometry + optional fix partitions / mesh.

    Supports a flexible number of equal-width glass sashes (``glass_count``) plus
    mesh sashes (``mesh_count``), center-opening handle placement, per-sash FIX
    locking (``fixed_shutters``) and front/back track stacking. ``system`` may be
    ``sliding`` (default), ``casement`` (openable, hinges opposite the handle) or
    ``bifold`` (Fold & Sliding leaves with per-side section sizes).
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    sys_kind = str(system or "sliding").strip().lower()
    if sys_kind in ("bifold", "fold", "fold_sliding", "fold_and_sliding"):
        return _compute_bifold_layout(
            width,
            height,
            geometry,
            fold_left=fold_left,
            fold_right=fold_right,
            section_sizes=section_sizes,
        )
    if sys_kind == "grid":
        return _compute_grid_layout(width, height, geometry, grid=grid, handle_level=handle_level)

    tw = float(geometry["trackWidth"])
    fw = float(geometry["frameWidth"])
    iw = float(geometry["interlockWidth"])
    ov = float(geometry["overlap"])
    gc = float(geometry["glassClip"])

    if tw <= 0 or fw <= 0 or iw <= 0:
        raise ValueError("profile widths must be positive")
    if ov < 0 or ov >= tw:
        raise ValueError("overlap must be in [0, trackWidth)")
    if gc < 0:
        raise ValueError("glassClip must be >= 0")

    W, H = float(width), float(height)
    shutter_inset = tw - ov
    track = Rect(tw, tw, W - tw, H - tw)

    parts = normalize_partitions(partitions)
    sizes = partition_sizes(parts)
    top_fix = sizes["top"]
    bot_fix = sizes["bottom"]
    left_fix = sizes["left"]
    right_fix = sizes["right"]

    # Sliding band inside outer track, after carving fix panels + mullions
    mullion = fw
    slide_x0 = track.x0 + (left_fix + mullion if left_fix > 0 else 0.0)
    slide_x1 = track.x1 - (right_fix + mullion if right_fix > 0 else 0.0)
    slide_y0 = track.y0 + (bot_fix + mullion if bot_fix > 0 else 0.0)
    slide_y1 = track.y1 - (top_fix + mullion if top_fix > 0 else 0.0)
    if slide_x1 - slide_x0 < fw * 2 or slide_y1 - slide_y0 < fw * 2:
        raise ValueError("partition sizes leave too little room for sliding sashes")

    sliding_area = Rect(slide_x0, slide_y0, slide_x1, slide_y1)
    cx = (slide_x0 + slide_x1) / 2.0
    il = cx - iw / 2.0
    ir = cx + iw / 2.0

    # Flexible shutter model — equal-width glass sashes + mesh sashes
    g_count = int(glass_count) if glass_count else int(float(geometry.get("shutterCount") or 2))
    g_count = max(g_count, 1)
    m_count = int(mesh_count) if mesh_count is not None else (1 if mesh else 0)
    if mesh and m_count <= 0:
        m_count = 1
    mode = str(opening or "").strip().lower()
    if mode not in ("center", "telescopic"):
        mode = "center" if g_count % 2 == 0 else "telescopic"
    fixed_set = {int(i) for i in (fixed_shutters or []) if 0 <= int(i) < g_count}
    handle_length = float(geometry["handleLengthMm"]) if geometry.get("handleLengthMm") else None
    is_casement = sys_kind in ("casement", "openable", "opening")
    h_level = float(handle_level) if handle_level is not None else 0.5

    shutters, handles, hinges = _build_shutters(
        sliding_area,
        frame_width=fw,
        glass_clip=gc,
        interlock_width=iw,
        glass_count=g_count,
        mesh_count=m_count,
        opening=mode,
        fixed_set=fixed_set,
        handle_length=handle_length,
        system="casement" if is_casement else "sliding",
        handle_level=h_level,
        handle_overrides=handle_overrides,
    )

    glass_panels = [sp for sp in shutters if sp.role == "glass"]
    first = glass_panels[0]
    last = glass_panels[-1]
    left_shutter = first.outer
    right_shutter = last.outer
    left_glass = first.glass
    right_glass = last.glass
    left_clip = Rect(
        left_glass.x0 - gc,
        left_glass.y0 - gc,
        left_glass.x1,
        left_glass.y1 + gc,
    )
    right_clip = Rect(
        right_glass.x0,
        right_glass.y0 - gc,
        right_glass.x1 + gc,
        right_glass.y1 + gc,
    )

    fix_panels: list[FixPanel] = []
    mullions: list[Rect] = []

    if top_fix > 0:
        outer = Rect(track.x0, track.y1 - top_fix, track.x1, track.y1)
        glass = outer.inset_uniform(fw * 0.55)
        fix_panels.append(FixPanel("top", top_fix, "fix", outer, glass))
        mullions.append(Rect(track.x0, slide_y1, track.x1, track.y1 - top_fix))
    if bot_fix > 0:
        outer = Rect(track.x0, track.y0, track.x1, track.y0 + bot_fix)
        glass = outer.inset_uniform(fw * 0.55)
        fix_panels.append(FixPanel("bottom", bot_fix, "fix", outer, glass))
        mullions.append(Rect(track.x0, track.y0 + bot_fix, track.x1, slide_y0))
    if left_fix > 0:
        # Left fix spans sliding height (between top/bottom mullions)
        outer = Rect(track.x0, slide_y0, track.x0 + left_fix, slide_y1)
        glass = outer.inset_uniform(fw * 0.55)
        fix_panels.append(FixPanel("left", left_fix, "fix", outer, glass))
        mullions.append(Rect(track.x0 + left_fix, slide_y0, slide_x0, slide_y1))
    if right_fix > 0:
        outer = Rect(track.x1 - right_fix, slide_y0, track.x1, slide_y1)
        glass = outer.inset_uniform(fw * 0.55)
        fix_panels.append(FixPanel("right", right_fix, "fix", outer, glass))
        mullions.append(Rect(slide_x1, slide_y0, track.x1 - right_fix, slide_y1))

    # Casement/openable: a vertical mullion sits BETWEEN adjacent leaves. It is the
    # member that carries the hinges (jamb side) and the meeting-stile lock. Emit a
    # thin section on each interior leaf boundary so 2+ door windows read correctly
    # (both live canvas and PDF draw L.mullions as clean 2D profiles).
    if is_casement and len(glass_panels) >= 2:
        for gp in glass_panels[1:]:
            bx = float(gp.nom_x0)
            mullions.append(Rect(bx - fw / 2.0, sliding_area.y0, bx + fw / 2.0, sliding_area.y1))

    tc = float(track_count) if track_count is not None else float(geometry.get("trackCount") or 2)
    if mesh and tc < 2.5:
        tc = 3.0

    return SlidingLayout(
        W=W,
        H=H,
        track_width=tw,
        frame_width=fw,
        interlock_width=iw,
        overlap=ov,
        glass_clip=gc,
        track=track,
        interlock_left=il,
        interlock_right=ir,
        shutter_inset=shutter_inset,
        left_shutter=left_shutter,
        right_shutter=right_shutter,
        left_glass=left_glass,
        right_glass=right_glass,
        left_clip=left_clip,
        right_clip=right_clip,
        fix_panels=tuple(fix_panels),
        mullions=tuple(mullions),
        mesh=bool(mesh) or m_count > 0,
        track_count=tc,
        sliding_area=sliding_area,
        shutters=tuple(shutters),
        glass_count=g_count,
        mesh_count=m_count,
        opening=mode,
        system="casement" if is_casement else "sliding",
        hinges=tuple(hinges),
    )


def _section_size(sizes: Mapping[str, Any] | None, keys: Sequence[str], default: float) -> float:
    if sizes:
        for k in keys:
            if k in sizes and sizes[k] not in (None, ""):
                try:
                    v = float(sizes[k])
                    if v > 0:
                        return v
                except (TypeError, ValueError):
                    continue
    return float(default)


def _compute_bifold_layout(
    width: float,
    height: float,
    geometry: Mapping[str, Any],
    *,
    fold_left: int | None,
    fold_right: int | None,
    section_sizes: Mapping[str, Any] | None = None,
) -> SlidingLayout:
    """Fold & Sliding layout — equal leaves, per-side section sizes, size clamp."""
    tw = float(geometry["trackWidth"])
    fw = float(geometry["frameWidth"])
    iw = float(geometry["interlockWidth"])
    ov = float(geometry["overlap"])
    gc = float(geometry["glassClip"])

    notes: list[str] = []
    W, H = float(width), float(height)
    # Soft envelope only — never shrink the drawing/PDF dims (canvas must match quote).
    if W > BIFOLD_MAX_WIDTH_MM:
        notes.append(
            f"Width {W:g} mm exceeds recommended max 25 ft ({BIFOLD_MAX_WIDTH_MM:.0f} mm) for Fold & Sliding"
        )
    if H > BIFOLD_MAX_HEIGHT_MM:
        notes.append(
            f"Height {H:g} mm exceeds recommended max 12 ft ({BIFOLD_MAX_HEIGHT_MM:.0f} mm) for Fold & Sliding"
        )

    L = max(int(fold_left) if fold_left is not None else 2, 0)
    R = max(int(fold_right) if fold_right is not None else 1, 0)
    if L + R <= 0:
        L, R = 2, 1

    # Per-side section sizes (each editable; default to profile track/frame widths)
    top = _section_size(section_sizes, ("topRail", "top", "topTrack"), tw)
    bottom = _section_size(section_sizes, ("bottomRail", "bottom", "bottomTrack"), tw)
    left_j = _section_size(section_sizes, ("leftJamb", "left", "verticalTrack", "vertical"), tw)
    right_j = _section_size(section_sizes, ("rightJamb", "right", "verticalTrack", "vertical"), tw)
    leaf_stile = _section_size(section_sizes, ("leafStile", "verticalMember", "leafFrame"), fw)

    resolved_sizes = {
        "topRail": round(top, 1),
        "bottomRail": round(bottom, 1),
        "leftJamb": round(left_j, 1),
        "rightJamb": round(right_j, 1),
        "leafStile": round(leaf_stile, 1),
    }

    track = Rect(left_j, bottom, W - right_j, H - top)
    if track.width < fw * 2 or track.height < fw * 2:
        raise ValueError("section sizes leave too little room for fold leaves")

    handle_length = float(geometry["handleLengthMm"]) if geometry.get("handleLengthMm") else None
    leaves, handles, hinges = _build_bifold_leaves(
        track,
        frame_width=leaf_stile,
        fold_left=L,
        fold_right=R,
        handle_length=handle_length,
    )

    first = leaves[0]
    last = leaves[-1]
    left_clip = Rect(first.glass.x0 - gc, first.glass.y0 - gc, first.glass.x1, first.glass.y1 + gc)
    right_clip = Rect(last.glass.x0, last.glass.y0 - gc, last.glass.x1 + gc, last.glass.y1 + gc)
    cx = track.cx

    return SlidingLayout(
        W=W,
        H=H,
        track_width=tw,
        frame_width=leaf_stile,
        interlock_width=iw,
        overlap=ov,
        glass_clip=gc,
        track=track,
        interlock_left=cx - iw / 2.0,
        interlock_right=cx + iw / 2.0,
        shutter_inset=min(left_j, right_j),
        left_shutter=first.outer,
        right_shutter=last.outer,
        left_glass=first.glass,
        right_glass=last.glass,
        left_clip=left_clip,
        right_clip=right_clip,
        fix_panels=(),
        mullions=(),
        mesh=False,
        # Fold systems are not multi-track sliders — 0 avoids false "2-track" specs.
        track_count=0.0,
        sliding_area=track,
        shutters=tuple(leaves),
        glass_count=L + R,
        mesh_count=0,
        opening="center",
        system="bifold",
        fold_left=L,
        fold_right=R,
        hinges=tuple(hinges),
        section_sizes=resolved_sizes,
        notes=tuple(notes),
    )


def _norm_sizes(raw: Any, total: float, default_n: int) -> list[float]:
    """Turn a list of relative/absolute sizes into absolute mm summing to ``total``."""
    vals: list[float] = []
    if isinstance(raw, (list, tuple)):
        for v in raw:
            try:
                f = float(v)
            except (TypeError, ValueError):
                f = 0.0
            vals.append(max(f, 0.0))
    vals = [v for v in vals if v > 0]
    if not vals:
        vals = [1.0] * max(int(default_n), 1)
    s = sum(vals)
    if s <= 0:
        vals = [1.0] * len(vals)
        s = float(len(vals))
    return [total * v / s for v in vals]


def _compute_grid_layout(
    width: float,
    height: float,
    geometry: Mapping[str, Any],
    *,
    grid: Mapping[str, Any] | None,
    handle_level: float | None = None,
) -> SlidingLayout:
    """Partition/grid designer — a non-uniform grid of FIX / SLIDING / OPENABLE cells.

    ``grid`` = ``{"cols": [..], "rows": [..], "cells": [{"r","c","role","glass","mesh","hinge"}]}``.
    ``cols`` / ``rows`` may be relative ratios or mm (scaled to fill the frame).
    Every cell is framed, dimensioned and labelled; each renders its role in clean
    2D (fix lite, sliding sashes + arrows, openable sash + hinges opposite handle).
    """
    fw = float(geometry["frameWidth"])
    gc = float(geometry.get("glassClip") or 0)
    iw = float(geometry.get("interlockWidth") or fw)
    W, H = float(width), float(height)
    grid = grid or {}

    cols = _norm_sizes(grid.get("cols"), W - 2 * fw, 2)
    rows = _norm_sizes(grid.get("rows"), H - 2 * fw, 1)
    nc, nr = len(cols), len(rows)

    # Column x-edges (left→right) and row y-edges (top→bottom, model y from bottom)
    colX = [fw]
    for w in cols:
        colX.append(colX[-1] + w)
    rowTop = [H - fw]
    for h in rows:
        rowTop.append(rowTop[-1] - h)

    # Role lookup keyed by (r, c)
    role_by = {}
    extra_by = {}
    for cell in (grid.get("cells") or []):
        if not isinstance(cell, Mapping):
            continue
        try:
            r, c = int(cell.get("r")), int(cell.get("c"))
        except (TypeError, ValueError):
            continue
        role_by[(r, c)] = str(cell.get("role") or "fix").strip().lower()
        extra_by[(r, c)] = cell

    hlevel = min(max(float(handle_level) if handle_level is not None else 0.5, 0.08), 0.92)
    hw = max(fw * 0.5, 12.0)

    cells_render: list[dict[str, Any]] = []
    shutters: list[ShutterPanel] = []
    hinges: list[Rect] = []
    counters = {"fix": 0, "sliding": 0, "openable": 0}
    prefix = {"fix": "F", "sliding": "S", "openable": "O"}
    sidx = 0

    for r in range(nr):
        for c in range(nc):
            role = role_by.get((r, c), "fix")
            if role in ("open", "opening", "casement"):
                role = "openable"
            if role not in ("fix", "sliding", "openable"):
                role = "fix"
            x0, x1 = colX[c], colX[c + 1]
            y1, y0 = rowTop[r], rowTop[r + 1]
            cell_rect = Rect(x0, y0, x1, y1)
            glass_rect = cell_rect.inset(fw, fw, fw, fw)
            cw, ch = (x1 - x0), (y1 - y0)
            counters[role] += 1
            label = f"{prefix[role]}{counters[role]}"
            cy = (y0 + y1) / 2.0
            hlen = min(max(ch * 0.18, 90.0), 320.0)
            extra = extra_by.get((r, c), {})

            cell: dict[str, Any] = {
                "r": r, "c": c, "role": role, "label": label,
                "x0": round(x0, 1), "y0": round(y0, 1), "x1": round(x1, 1), "y1": round(y1, 1),
                "wmm": round(cw, 1), "hmm": round(ch, 1),
                "glass": [], "sashLines": [], "arrows": [], "hinges": [],
                "handle": None, "mesh": None, "diagonals": [],
            }

            if role == "fix":
                cell["glass"].append({"x0": round(glass_rect.x0, 1), "y0": round(glass_rect.y0, 1), "x1": round(glass_rect.x1, 1), "y1": round(glass_rect.y1, 1)})
                shutters.append(ShutterPanel(index=sidx, role="glass", operable=False, outer=cell_rect, glass=glass_rect, depth=1, track_label="fix", open_dir=0, nom_x0=x0, nom_x1=x1))
                sidx += 1
            elif role == "sliding":
                g = max(int(extra.get("glass") or 2), 1)
                bounds = [x0 + (x1 - x0) * k / g for k in range(g + 1)]
                for i in range(g):
                    sx0, sx1 = bounds[i], bounds[i + 1]
                    sash = Rect(sx0, y0, sx1, y1)
                    sg = sash.inset(fw, fw, fw, fw)
                    cell["glass"].append({"x0": round(sg.x0, 1), "y0": round(sg.y0, 1), "x1": round(sg.x1, 1), "y1": round(sg.y1, 1)})
                    shutters.append(ShutterPanel(index=sidx, role="glass", operable=True, outer=sash, glass=sg, depth=1 if i % 2 else 2, track_label="front" if i % 2 else "back", open_dir=1 if i < g / 2 else -1, nom_x0=sx0, nom_x1=sx1))
                    sidx += 1
                    if i > 0:
                        cell["sashLines"].append(round(sx0, 1))
                    # Arrow toward centre
                    amid = (sx0 + sx1) / 2.0
                    if i < g / 2:
                        cell["arrows"].append({"x0": round(amid - cw / (g * 2) * 0.5, 1), "y0": round(cy, 1), "x1": round(amid + cw / (g * 2) * 0.5, 1), "y1": round(cy, 1)})
                    else:
                        cell["arrows"].append({"x0": round(amid + cw / (g * 2) * 0.5, 1), "y0": round(cy, 1), "x1": round(amid - cw / (g * 2) * 0.5, 1), "y1": round(cy, 1)})
                # Handles on the outer stiles of the two end sashes
                yc = y0 + ch * hlevel
                cell["handles"] = [
                    {"x0": round(x0 + fw / 2.0 - hw / 2, 1), "y0": round(yc - hlen / 2, 1), "x1": round(x0 + fw / 2.0 + hw / 2, 1), "y1": round(yc + hlen / 2, 1), "side": "left"},
                    {"x0": round(x1 - fw / 2.0 - hw / 2, 1), "y0": round(yc - hlen / 2, 1), "x1": round(x1 - fw / 2.0 + hw / 2, 1), "y1": round(yc + hlen / 2, 1), "side": "right"},
                ]
                if int(extra.get("mesh") or 0) > 0:
                    mw = (x1 - x0) / g  # one sliding-panel width
                    cell["mesh"] = {"x0": round(x0, 1), "y0": round(y0, 1), "x1": round(x0 + mw, 1), "y1": round(y1, 1)}
            else:  # openable
                hinge = str(extra.get("hinge") or "left").strip().lower()
                if hinge not in ("left", "right"):
                    hinge = "left"
                handle_side = "right" if hinge == "left" else "left"
                sash = cell_rect
                cell["glass"].append({"x0": round(glass_rect.x0, 1), "y0": round(glass_rect.y0, 1), "x1": round(glass_rect.x1, 1), "y1": round(glass_rect.y1, 1)})
                shutters.append(ShutterPanel(index=sidx, role="glass", operable=True, outer=sash, glass=glass_rect, depth=1, track_label="sash", open_dir=1, handle_side=handle_side, hinge_side=hinge, nom_x0=x0, nom_x1=x1))
                sidx += 1
                yc = y0 + ch * hlevel
                hx = (x1 - fw / 2.0) if handle_side == "right" else (x0 + fw / 2.0)
                cell["handles"] = [{"x0": round(hx - hw / 2, 1), "y0": round(yc - hlen / 2, 1), "x1": round(hx + hw / 2, 1), "y1": round(yc + hlen / 2, 1), "side": handle_side}]
                # Hinge knuckles on the opposite (hinge) stile
                khx = (x0 + fw / 2.0) if hinge == "left" else (x1 - fw / 2.0)
                kw = max(fw * 0.7, 14.0)
                kh = max(ch * 0.05, 18.0)
                for t in (0.18, 0.5, 0.82):
                    ky = y0 + ch * t
                    hr = Rect(khx - kw / 2, ky - kh / 2, khx + kw / 2, ky + kh / 2)
                    hinges.append(hr)
                    cell["hinges"].append({"x0": round(hr.x0, 1), "y0": round(hr.y0, 1), "x1": round(hr.x1, 1), "y1": round(hr.y1, 1)})
                # Openable symbol: two diagonals meeting at the handle-side mid
                hxm = glass_rect.x1 if handle_side == "right" else glass_rect.x0
                oxm = glass_rect.x0 if handle_side == "right" else glass_rect.x1
                cell["diagonals"] = [
                    [round(oxm, 1), round(glass_rect.y0, 1), round(hxm, 1), round((glass_rect.y0 + glass_rect.y1) / 2, 1)],
                    [round(oxm, 1), round(glass_rect.y1, 1), round(hxm, 1), round((glass_rect.y0 + glass_rect.y1) / 2, 1)],
                ]

            cells_render.append(cell)

    grid_spec = {
        "cols": [round(w, 1) for w in cols],
        "rows": [round(h, 1) for h in rows],
        "colX": [round(x, 1) for x in colX],
        "rowTop": [round(y, 1) for y in rowTop],
        "cells": cells_render,
        "frameWidth": round(fw, 1),
    }

    track = Rect(fw, fw, W - fw, H - fw)
    first = shutters[0] if shutters else ShutterPanel(index=0, role="glass", operable=False, outer=track, glass=track, depth=1, track_label="fix", open_dir=0)
    return SlidingLayout(
        W=W, H=H, track_width=fw, frame_width=fw, interlock_width=iw, overlap=0.0, glass_clip=gc,
        track=track, interlock_left=track.cx, interlock_right=track.cx, shutter_inset=fw,
        left_shutter=first.outer, right_shutter=shutters[-1].outer if shutters else track,
        left_glass=first.glass, right_glass=shutters[-1].glass if shutters else track,
        left_clip=first.glass, right_clip=shutters[-1].glass if shutters else track,
        fix_panels=(), mullions=(), mesh=False, track_count=2.0, sliding_area=track,
        shutters=tuple(shutters), glass_count=sum(1 for s in shutters if s.role == "glass"),
        mesh_count=0, opening="center", system="grid", hinges=tuple(hinges), grid_spec=grid_spec,
    )


def build_drawing(
    layout: SlidingLayout,
    *,
    product_name: str,
    parameters: dict[str, float],
    style: DimStyleParams,
) -> DrawingModel:
    """Geometry + Dimension engines → DrawingModel."""
    L = layout
    model = DrawingModel(
        product_type=product_name,
        width=L.W,
        height=L.H,
        parameters=parameters,
        metadata=L.meta(),
    )
    if L.system == "grid":
        # Grid is rendered from metadata['grid'] by dedicated 2D routines in the
        # SVG/PDF exporters; emit just the outer frame so bbox sizing is correct.
        model.add_polyline(rect_polyline(Rect(0.0, 0.0, L.W, L.H), closed=True, layer="PROFILES", name="outer_frame"))
        return model
    _build_profiles(model, L)
    _build_dimensions(model, L, style)
    return model


def _build_profiles(model: DrawingModel, L: SlidingLayout) -> None:
    outer = Rect(0.0, 0.0, L.W, L.H)
    model.add_polyline(rect_polyline(outer, closed=True, layer="PROFILES", name="outer_frame"))
    model.add_polyline(rect_polyline(L.track, closed=True, layer="Defpoints", name="track_inner"))

    # Fix panels + mullions (clear linework, no fills)
    for i, fp in enumerate(L.fix_panels):
        model.add_polyline(rect_polyline(fp.outer, closed=True, layer="PROFILES", name=f"fix_{fp.side}_outer"))
        model.add_polyline(rect_polyline(fp.glass, closed=True, layer="GLASS", name=f"fix_{fp.side}_glass"))
        # Corner ticks so fix reads as framed lite
        g, o = fp.glass, fp.outer
        for name, p0, p1 in (
            (f"fix_{fp.side}_miter_bl", Point(o.x0, o.y0), Point(g.x0, g.y0)),
            (f"fix_{fp.side}_miter_br", Point(o.x1, o.y0), Point(g.x1, g.y0)),
            (f"fix_{fp.side}_miter_tr", Point(o.x1, o.y1), Point(g.x1, g.y1)),
            (f"fix_{fp.side}_miter_tl", Point(o.x0, o.y1), Point(g.x0, g.y1)),
        ):
            model.add_segment(Segment(p0, p1, layer="PROFILES", name=name))

    for i, m in enumerate(L.mullions):
        model.add_polyline(rect_polyline(m, closed=True, layer="PROFILES", name=f"mullion_{i+1}"))

    model.extend_segments(frame_miter_segments(outer, L.track, layer="PROFILES", name_prefix="track_miter"))

    glass_panels = [sp for sp in L.shutters if sp.role == "glass"]
    if L.system == "bifold" and glass_panels:
        _build_bifold_profiles(model, L, glass_panels)
    elif glass_panels:
        _build_shutter_profiles(model, L, glass_panels)
    else:  # pragma: no cover — legacy fallback
        model.add_polyline(rect_polyline(L.left_shutter, closed=True, layer="PROFILES", name="left_shutter_outer"))
        model.add_polyline(rect_polyline(L.right_shutter, closed=True, layer="PROFILES", name="right_shutter_outer"))
        model.add_polyline(rect_polyline(L.left_glass, closed=True, layer="GLASS", name="left_glass"))
        model.add_polyline(rect_polyline(L.right_glass, closed=True, layer="GLASS", name="right_glass"))


def _build_shutter_profiles(model: DrawingModel, L: SlidingLayout, glass_panels: list[ShutterPanel]) -> None:
    """Emit sash frames, glass lites, meeting interlocks and handles for N shutters.

    Back-track sashes are drawn first so front-track sashes lap over them at the
    interlock (front/back stagger). A single clean interlock line is drawn only
    where two same-track sashes meet (e.g. the centre of a center-opening pair).
    """
    n = len(glass_panels)
    # Determine meeting (interlock) sides from nominal adjacency + depth difference.
    # FRONT sash meeting-stile corners get 45° miters (visible interlock stile).
    # BACK sash meeting corners stay square (avoids double center line / cap stubs).
    by_pos = sorted(glass_panels, key=lambda p: p.nom_x0)
    pos_of = {id(p): k for k, p in enumerate(by_pos)}

    def meeting_sides(sp: ShutterPanel) -> tuple[bool, bool]:
        k = pos_of[id(sp)]
        left_m = k > 0 and by_pos[k - 1].depth != sp.depth
        right_m = k < len(by_pos) - 1 and by_pos[k + 1].depth != sp.depth
        return left_m, right_m

    def overlapped_sides(sp: ShutterPanel) -> tuple[bool, bool]:
        """True on a side where a FRONT (smaller-depth) neighbour laps over this
        sash. That neighbour's continuous outline already reads the interlock, so
        this (back) sash must NOT draw its own meeting-side stile — doing so creates
        the double center line + top/bottom cap stubs the user flagged."""
        k = pos_of[id(sp)]
        ol = k > 0 and by_pos[k - 1].depth < sp.depth
        orr = k < len(by_pos) - 1 and by_pos[k + 1].depth < sp.depth
        return ol, orr

    # Back (larger depth) first so front sashes overlap on top.
    for sp in sorted(glass_panels, key=lambda p: -p.depth):
        o, g = sp.outer, sp.glass
        fixed = not sp.operable
        prefix = "fix_shutter" if fixed else "shutter"
        left_m, right_m = meeting_sides(sp)
        ol, orr = overlapped_sides(sp)
        # Outer sash outline. The FRONT sash (not overlapped) is a continuous closed
        # rectangle. A BACK sash omits the overlapped meeting edge so the front sash's
        # lap reads the interlock cleanly (no stray center line / cap stubs).
        oname = f"{prefix}_{sp.index}_outer"
        if ol and orr:
            # Deep middle sash lapped on both sides → only its top & bottom rails show.
            model.add_segment(Segment(Point(o.x0, o.y1), Point(o.x1, o.y1), layer="PROFILES", name=f"{oname}_top"))
            model.add_segment(Segment(Point(o.x0, o.y0), Point(o.x1, o.y0), layer="PROFILES", name=f"{oname}_bot"))
        elif orr:
            model.add_polyline(u_polyline_open_right(o, layer="PROFILES", name=oname))
        elif ol:
            model.add_polyline(u_polyline_open_left(o, layer="PROFILES", name=oname))
        else:
            model.add_polyline(rect_polyline(o, closed=True, layer="PROFILES", name=oname))
        glass_name = f"fix_shutter_{sp.index}_glass" if fixed else f"shutter_{sp.index}_glass"
        model.add_polyline(rect_polyline(g, closed=True, layer="GLASS", name=glass_name))
        # Corner miters: outer corners always. Meeting-stile corners only on the
        # FRONT (overlapping) sash — the visible interlock stile that the user sees.
        # BACK sash meeting corners stay square so we don't get double-line / cap stubs.
        miters = (
            ("bl", Point(o.x0, o.y0), Point(g.x0, g.y0), left_m, ol),
            ("br", Point(o.x1, o.y0), Point(g.x1, g.y0), right_m, orr),
            ("tr", Point(o.x1, o.y1), Point(g.x1, g.y1), right_m, orr),
            ("tl", Point(o.x0, o.y1), Point(g.x0, g.y1), left_m, ol),
        )
        for tag, p0, p1, is_meeting, is_back_lap in miters:
            if is_meeting and is_back_lap:
                continue  # back sash at lap — keep square; front sash draws the miter
            model.add_segment(Segment(p0, p1, layer="PROFILES", name=f"{prefix}_{sp.index}_miter_{tag}"))

    # Draw a meeting line ONLY where two same-track sashes butt together (no stray
    # duplicate at staggered interlocks — the front sash edge reads the meeting).
    for b in range(1, n):
        left, right = glass_panels[b - 1], glass_panels[b]
        if left.depth == right.depth:
            x = right.nom_x0
            name = "interlock_center" if b == n // 2 else f"interlock_{b}"
            model.add_segment(vertical_segment(x, right.outer.y0, right.outer.y1, layer="PROFILES", name=name))

    # Handles — drawn last on the HARDWARE layer at the centre of the handle section
    for sp in glass_panels:
        if sp.handle is None:
            continue
        model.add_polyline(rect_polyline(sp.handle, closed=True, layer="HARDWARE", name=f"handle_{sp.index}"))


def _build_bifold_profiles(model: DrawingModel, L: SlidingLayout, leaves: list[ShutterPanel]) -> None:
    """Emit Fold & Sliding leaves: framed leaf panels, division lines, hinges, handles."""
    for sp in leaves:
        o, g = sp.outer, sp.glass
        model.add_polyline(rect_polyline(o, closed=True, layer="PROFILES", name=f"leaf_{sp.index}_outer"))
        model.add_polyline(rect_polyline(g, closed=True, layer="GLASS", name=f"leaf_{sp.index}_glass"))
        for tag, p0, p1 in (
            ("bl", Point(o.x0, o.y0), Point(g.x0, g.y0)),
            ("br", Point(o.x1, o.y0), Point(g.x1, g.y0)),
            ("tr", Point(o.x1, o.y1), Point(g.x1, g.y1)),
            ("tl", Point(o.x0, o.y1), Point(g.x0, g.y1)),
        ):
            model.add_segment(Segment(p0, p1, layer="PROFILES", name=f"leaf_{sp.index}_miter_{tag}"))

    # Centre meeting line between the two packs
    meeting = L.fold_left
    if 0 < meeting < len(leaves):
        x = leaves[meeting].nom_x0
        model.add_segment(vertical_segment(x, L.track.y0, L.track.y1, layer="PROFILES", name="interlock_center"))

    # Hinge knuckles
    for i, h in enumerate(L.hinges):
        model.add_polyline(rect_polyline(h, closed=True, layer="HARDWARE", name=f"hinge_{i}"))

    # Handles on the meeting leaves
    for sp in leaves:
        if sp.handle is None:
            continue
        model.add_polyline(rect_polyline(sp.handle, closed=True, layer="HARDWARE", name=f"handle_{sp.index}"))


def _build_dimensions(model: DrawingModel, L: SlidingLayout, style: DimStyleParams) -> None:
    W, H = L.W, L.H
    glass_panels = [sp for sp in L.shutters if sp.role == "glass"]
    top_y = glass_panels[0].outer.y1 if glass_panels else L.left_shutter.y1
    mid_y = (L.left_shutter.y0 + L.left_shutter.y1) / 2.0

    model.add_dimension(horizontal_dim(0.0, W, 0.0, text_y=dim_offset_below(0.0, style, 0), name="overall_width", layer="DIMS"))
    model.add_dimension(vertical_dim(0.0, H, 0.0, text_x=dim_offset_left(0.0, style, 0), name="overall_height", layer="DIMS"))
    # Per-shutter equal-division widths along the top (nominal equal shares)
    for sp in glass_panels:
        model.add_dimension(
            horizontal_dim(
                sp.nom_x0, sp.nom_x1, top_y,
                text_y=dim_offset_above(H, style, 0),
                name=f"shutter_{sp.index}_width", layer="DIMS",
            )
        )
    model.add_dimension(
        vertical_dim(L.left_glass.y0, L.left_glass.y1, L.right_shutter.x1, text_x=dim_offset_right(W, style, 0), name="glass_height", layer="DIMS")
    )
    # Fix partition height/width callouts
    for fp in L.fix_panels:
        if fp.side in ("top", "bottom"):
            model.add_dimension(
                vertical_dim(
                    fp.outer.y0, fp.outer.y1, W,
                    text_x=dim_offset_right(W, style, 1),
                    name=f"fix_{fp.side}_height",
                    layer="DIMS",
                )
            )
        else:
            model.add_dimension(
                horizontal_dim(
                    fp.outer.x0, fp.outer.x1, fp.outer.y0,
                    text_y=dim_offset_below(fp.outer.y0, style, 0),
                    name=f"fix_{fp.side}_width",
                    layer="DIMS",
                )
            )
    model.add_dimension(
        horizontal_dim(
            L.left_glass.x0, L.left_glass.x1, L.left_glass.y0,
            text_y=dim_offset_below(L.left_glass.y0, style, 0), name="left_glass_width", layer="DIMS",
        )
    )
    detail_y = dim_offset_below(0.0, style, 1)
    model.add_dimension(horizontal_dim(0.0, L.track_width, 0.0, text_y=detail_y, name="track_width", layer="DIMS"))
    model.add_dimension(
        horizontal_dim(L.left_shutter.x0, L.track.x0, 0.0, text_y=dim_offset_below(0.0, style, 2), name="overlap", layer="DIMS")
    )
    model.add_dimension(
        horizontal_dim(L.interlock_left, L.interlock_right, mid_y, text_y=mid_y - style.offset_detail, name="interlock_width", layer="DIMS")
    )
    model.add_dimension(
        horizontal_dim(
            L.left_shutter.x0, L.left_glass.x0, L.left_glass.y0,
            text_y=L.left_glass.y0 - style.offset_detail, name="shutter_frame_width", layer="DIMS",
        )
    )
    model.add_dimension(horizontal_dim(L.track.x1, W, 0.0, text_y=detail_y, name="outer_frame_width", layer="DIMS"))
