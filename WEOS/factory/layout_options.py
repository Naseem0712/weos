"""Layout options — partitions (fix panels), mesh, track-count resolution."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def normalize_partitions(raw: Any) -> list[dict[str, Any]]:
    """Return cleaned partition list: [{side, sizeMm, role}]."""
    if not raw:
        return []
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        side = str(item.get("side") or "").strip().lower()
        if side not in ("top", "bottom", "left", "right"):
            continue
        try:
            size = float(item.get("sizeMm") or item.get("size_mm") or item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0.0
        if size <= 0:
            continue
        role = str(item.get("role") or "fix").strip().lower() or "fix"
        out.append({"side": side, "sizeMm": round(size, 1), "role": role})
    return out


def partition_sizes(partitions: Sequence[Mapping[str, Any]] | None) -> dict[str, float]:
    sizes = {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0}
    for p in normalize_partitions(partitions):
        sizes[str(p["side"])] = float(sizes.get(str(p["side"]), 0.0)) + float(p["sizeMm"])
    return sizes


def parse_track_count(name: str | None) -> float | None:
    """Infer track count from catalogue section name (2 / 2.5 / 3 / 4)."""
    if not name:
        return None
    import re

    text = str(name).lower().replace("½", ".5")
    m = re.search(r"(\d+(?:\.\d)?)\s*[-\s]*track", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    if "2.5" in text or "2,5" in text:
        return 2.5
    return None


def tracks_available_for_series(series: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """List unique track options from a catalogue series document."""
    if not series:
        return []
    seen: set[float] = set()
    out: list[dict[str, Any]] = []
    for sec in series.get("sections") or []:
        usage = str(sec.get("usage") or "")
        if usage not in ("track", "track_horizontal", "track_vertical", "frame"):
            continue
        tc = parse_track_count(sec.get("name") or "")
        if tc is None or tc in seen:
            continue
        seen.add(tc)
        out.append(
            {
                "trackCount": tc,
                "sectionId": sec.get("id"),
                "name": sec.get("name"),
                "depthMm": sec.get("sectionDepthMm"),
                "widthMm": sec.get("widthMm"),
            }
        )
    out.sort(key=lambda x: float(x["trackCount"]))
    return out


def resolve_mesh_track(
    *,
    mesh: bool,
    track_count: float | None = None,
    series: Mapping[str, Any] | None = None,
    prefer: float = 3.0,
) -> dict[str, Any]:
    """
    Mesh is only valid on 2.5-track or 3-track (or higher).
    If mesh is requested on a 2-track selection, auto-shift to an available
    2.5 / 3 track in the same series family (prefer 3 when both exist).
    """
    mesh = bool(mesh)
    available = tracks_available_for_series(series)
    avail_counts = [float(t["trackCount"]) for t in available]

    current = float(track_count) if track_count is not None else (
        avail_counts[0] if avail_counts else 2.0
    )

    mesh_ok = {c for c in (2.5, 3.0, 4.0) if True}  # 2.5+
    shifted = False
    reason = None
    chosen = current
    chosen_sec = None

    def pick_from_available(want: Sequence[float]) -> float | None:
        for w in want:
            if w in avail_counts:
                return w
        # any mesh-capable in catalogue
        mesh_caps = sorted(c for c in avail_counts if c >= 2.5)
        return mesh_caps[0] if mesh_caps else None

    if mesh:
        if current < 2.5:
            # Prefer 3, then 2.5, then whatever mesh-capable exists
            order = [prefer, 3.0, 2.5, 4.0]
            # unique preserve order
            seen: list[float] = []
            for x in order:
                if x not in seen:
                    seen.append(x)
            picked = pick_from_available(seen)
            if picked is None:
                # No catalogue entry — still bump geometry to 3-track for mesh
                picked = 3.0
                reason = "mesh_requires_3_track_default"
            else:
                reason = f"mesh_auto_shift_{current:g}_to_{picked:g}"
            chosen = picked
            shifted = chosen != current
        else:
            chosen = current
            reason = "mesh_ok"
        for t in available:
            if float(t["trackCount"]) == float(chosen):
                chosen_sec = t
                break
    else:
        chosen = current
        for t in available:
            if float(t["trackCount"]) == float(chosen):
                chosen_sec = t
                break

    return {
        "mesh": mesh,
        "trackCount": float(chosen),
        "shifted": shifted,
        "reason": reason,
        "previousTrackCount": float(current),
        "availableTracks": available,
        "trackSection": chosen_sec,
        "meshAllowed": float(chosen) >= 2.5,
    }


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        s = str(value).strip()
        if s == "":
            return None
        return int(round(float(s)))
    except (TypeError, ValueError):
        return None


def normalize_fixed_shutters(raw: Any, glass_count: int) -> list[int]:
    """Return sorted, de-duplicated 0-based glass-shutter indices to lock as FIX.

    Accepts a list/tuple, a comma-separated string ("1,3"), or a single value.
    Inputs are treated as 1-based positions (left→right) and clamped to range.
    """
    if raw is None or raw == "":
        return []
    items: list[Any]
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [p for p in str(raw).replace(";", ",").split(",")]
    out: set[int] = set()
    for it in items:
        n = _coerce_int(it)
        if n is None:
            continue
        idx = n - 1  # UI is 1-based
        if 0 <= idx < int(glass_count):
            out.add(idx)
    return sorted(out)


def parse_sliding_opening(raw: Any) -> tuple[str | None, str | None]:
    """Return ``(mode, side)`` from a UI/API opening string.

    ``mode`` is ``center`` / ``telescopic`` / None (auto).
    ``side`` is ``left`` / ``right`` / None (default right for side opening).
    """
    s = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not s or s in ("auto", "default", "none"):
        return None, None
    side = None
    if "left" in s:
        side = "left"
    elif "right" in s:
        side = "right"
    if "center" in s or "centre" in s:
        return "center", side
    if s in ("side", "telescopic", "telescope", "side_opening") or "telescopic" in s or s.startswith("side"):
        return "telescopic", side or "right"
    return None, side


def default_sliding_opening(glass_count: int) -> str:
    """Center opening only for 4 sliding glass shutters; everything else is side."""
    return "center" if int(glass_count or 0) == 4 else "telescopic"


def resolve_sliding_opening(
    raw: Any,
    glass_count: int,
    *,
    explicit: bool = False,
) -> tuple[str, str]:
    """Resolve opening mode + side.

    Stale persisted ``center`` on non-4-panel carts (old even-count auto) is
    treated as auto unless ``explicit`` is set by the UI override.
    Side / telescopic is always honoured (it was never the even-count auto).
    """
    mode, side = parse_sliding_opening(raw)
    g = max(int(glass_count or 0), 1)
    if mode == "telescopic":
        chosen = "telescopic"
    elif mode == "center" and (explicit or g == 4):
        chosen = "center"
    else:
        chosen = default_sliding_opening(g)
    if chosen == "center":
        return chosen, side or "right"
    return chosen, side or "right"


def resolve_shutter_config(
    *,
    glass_count: Any = None,
    mesh_count: Any = None,
    mesh: bool = False,
    track_count: float | None = None,
    fixed_shutters: Any = None,
    opening: str | None = None,
    opening_explicit: bool = False,
    opening_side: str | None = None,
    default_glass: int = 2,
) -> dict[str, Any]:
    """Normalize a flexible sliding configuration.

    Rules:
      - ``glass_count`` >= 1 (defaults to product ``shutterCount`` / 2).
      - ``mesh_count`` >= 0. If ``mesh`` is truthy but no count given, defaults to 1.
      - ``opening`` default: center only when glass_count == 4, else side (telescopic).
        Explicit UI/API values win (``opening_explicit`` or a side/telescopic value).
      - Mesh validity vs. track type is handled by ``resolve_mesh_track`` upstream;
        here we only clamp counts and derive the opening mode.
    """
    g = _coerce_int(glass_count)
    if g is None or g < 1:
        g = max(int(default_glass or 2), 1)

    m = _coerce_int(mesh_count)
    if m is None:
        m = 1 if bool(mesh) else 0
    m = max(int(m), 0)
    if bool(mesh) and m == 0:
        m = 1

    mode, side = resolve_sliding_opening(
        opening,
        g,
        explicit=bool(opening_explicit),
    )
    side_in = str(opening_side or "").strip().lower()
    if side_in in ("left", "right"):
        side = side_in

    fixed = normalize_fixed_shutters(fixed_shutters, g)

    return {
        "glassCount": int(g),
        "meshCount": int(m),
        "opening": mode,
        "openingSide": side,
        "fixedShutters": fixed,
        "mesh": bool(mesh) or m > 0,
        "trackCount": float(track_count) if track_count is not None else None,
    }


def line_layout_options(line: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract partitions / mesh / trackCount / shutter config from a cart line."""
    line = line or {}
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    layout = line.get("layout") if isinstance(line.get("layout"), Mapping) else {}

    def pick(*keys: str) -> Any:
        for k in keys:
            if line.get(k) is not None:
                return line.get(k)
            if isinstance(opts, Mapping) and opts.get(k) is not None:
                return opts.get(k)
            # PDF re-derive must honour fold/system persisted only on layout summary
            if isinstance(layout, Mapping) and layout.get(k) is not None:
                return layout.get(k)
        return None

    partitions = (
        line.get("partitions")
        or (opts or {}).get("partitions")
        or []
    )
    mesh_count_hint = _coerce_int(pick("meshShutters", "meshCount", "mesh_count")) or 0
    mesh = bool(line.get("mesh") if line.get("mesh") is not None else (opts or {}).get("mesh")) or mesh_count_hint > 0
    track_raw = pick("trackCount")
    try:
        track_count = float(track_raw) if track_raw is not None and str(track_raw).strip() != "" else None
    except (TypeError, ValueError):
        track_count = None

    opening_explicit = bool(pick("openingExplicit", "opening_explicit")) or str(pick("openingSource") or "").lower() == "user"
    shutter_cfg = resolve_shutter_config(
        glass_count=pick("glassShutters", "glassCount", "glass_count"),
        mesh_count=pick("meshShutters", "meshCount", "mesh_count"),
        mesh=mesh,
        track_count=track_count,
        fixed_shutters=pick("fixShutters", "fixedShutters", "fixed_shutters"),
        opening=pick("opening"),
        opening_explicit=opening_explicit,
        opening_side=pick("openingSide", "opening_side", "slideSide"),
    )
    system_raw = pick("system", "windowSystem")
    # layout.kind uses fold_and_sliding
    if system_raw is None and str((layout or {}).get("kind") or "") == "fold_and_sliding":
        system_raw = "bifold"
    if system_raw is None:
        try:
            from WEOS.factory.line_kind import normalize_product_type

            pt = normalize_product_type(pick("productType") or line.get("productType"))
            if pt == "casements":
                system_raw = "casement"
            elif pt == "fold":
                system_raw = "bifold"
            elif pt == "shower_partition":
                system_raw = "shower"
            elif pt == "bathroom_ventilator":
                system_raw = "ventilator"
        except Exception:
            pass
    system = str(system_raw or "sliding").strip().lower()
    is_bifold = system in ("bifold", "fold", "fold_sliding", "fold_and_sliding")
    is_casement = system in ("casement", "openable", "opening")
    is_grid = system == "grid"
    is_shower = system in ("shower", "shower_partition")
    is_ventilator = system in ("ventilator", "bathroom_ventilator")
    if is_bifold:
        resolved_system = "bifold"
    elif is_casement:
        resolved_system = "casement"
    elif is_grid:
        resolved_system = "grid"
    elif is_ventilator:
        resolved_system = "ventilator"
    elif is_shower:
        resolved_system = "shower"
    else:
        resolved_system = "sliding"

    grid_spec = pick("grid", "partitionGrid")
    if not isinstance(grid_spec, Mapping):
        grid_spec = None

    section_sizes = pick("sectionSizes", "sections")
    if not isinstance(section_sizes, Mapping):
        section_sizes = None

    handle_level_raw = pick("handleLevel", "handle_level")
    try:
        handle_level = float(handle_level_raw) if handle_level_raw is not None and str(handle_level_raw).strip() != "" else None
    except (TypeError, ValueError):
        handle_level = None
    handle_overrides = pick("handleOverrides", "handle_overrides", "handles")
    if not isinstance(handle_overrides, Mapping):
        handle_overrides = None

    # Prefer explicit fold counts; also accept layout.fold_left snake_case via pick keys
    fold_left = _coerce_int(pick("foldLeft", "fold_left"))
    fold_right = _coerce_int(pick("foldRight", "fold_right"))

    return {
        "partitions": normalize_partitions(partitions),
        "mesh": shutter_cfg["mesh"] and not is_bifold and not is_casement and not is_shower,
        "trackCount": None if (is_bifold or is_casement or is_shower) else track_count,
        "glassCount": shutter_cfg["glassCount"],
        "meshCount": 0 if (is_bifold or is_casement or is_shower) else shutter_cfg["meshCount"],
        "opening": shutter_cfg["opening"],
        "openingSide": shutter_cfg.get("openingSide") or "right",
        "openingExplicit": bool(opening_explicit),
        "fixedShutters": shutter_cfg["fixedShutters"],
        # Raw (1-based / string) fix value — pass THIS to generate_job so it
        # normalises exactly once (avoids double 1-based conversion).
        "fixShuttersRaw": pick("fixShutters", "fixedShutters", "fixed_shutters"),
        "system": resolved_system,
        "foldLeft": fold_left,
        "foldRight": fold_right,
        "sectionSizes": section_sizes,
        "handleFinish": pick("handleFinish", "handle_finish"),
        "handleLevel": handle_level,
        "handleOverrides": handle_overrides,
        "handleName": pick("handleName", "handle_name"),
        "meshName": pick("meshName", "mesh_name"),
        "powderCoatName": pick("powderCoatName", "powder_coat_name", "powderCoat", "coatingName"),
        "gridSpec": grid_spec,
        "sectionSeries": line.get("sectionSeries") or (opts or {}).get("sectionSeries"),
        "grid": line.get("grid") or (opts or {}).get("grid") or (opts or {}).get("grille"),
        "panelFill": _panel_fill_from_pick(line, opts),
        "features": (opts or {}).get("features") if isinstance((opts or {}).get("features"), (list, dict)) else line.get("features"),
        "casementPanels": pick("casementPanels", "panelRoles"),
        "productType": pick("productType") or line.get("productType"),
        "sashOverlapMm": pick("sashOverlapMm", "sash_overlap_mm", "sashOverlap"),
        "mullionGapMm": pick("mullionGapMm", "mullion_gap_mm", "mullionGap"),
        "frameMaterial": pick("frameMaterial", "frame_material", "material"),
        "reinforcement": pick("reinforcement", "reinforcementPresent"),
        "reinforcementMaterial": pick("reinforcementMaterial", "reinforcement_material"),
        "hardwareBrand": pick("hardwareBrand", "hardware_brand"),
        "hardwareType": pick("hardwareType", "hardware_type"),
        "hardwareColour": pick("hardwareColour", "hardware_colour", "hardwareColor"),
        "glassBrand": pick("glassBrand", "glass_brand"),
        "glassColour": pick("glassColour", "glass_colour", "glassColor"),
        "glassMakeup": pick("glassMakeup", "glass_makeup"),
        "topShape": pick("topShape", "top_shape", "headShape"),
        "curveRiseMm": pick("curveRiseMm", "curve_rise_mm", "archRiseMm", "arch_rise_mm"),
    }


def _panel_fill_from_pick(line: Mapping[str, Any], opts: Mapping[str, Any] | None) -> dict[str, Any] | None:
    try:
        from WEOS.factory.panel_fills import normalize_panel_fill, panel_fill_from_line

        merged = dict(line or {})
        if isinstance(opts, Mapping):
            merged.setdefault("options", opts)
            if opts.get("panelFill") and "panelFill" not in merged:
                merged["panelFill"] = opts.get("panelFill")
        fill = panel_fill_from_line(merged)
        if (fill or {}).get("fillType") in (None, "", "glass"):
            return None
        return normalize_panel_fill(fill)
    except Exception:
        return None
