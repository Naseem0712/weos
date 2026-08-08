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


def resolve_shutter_config(
    *,
    glass_count: Any = None,
    mesh_count: Any = None,
    mesh: bool = False,
    track_count: float | None = None,
    fixed_shutters: Any = None,
    opening: str | None = None,
    default_glass: int = 2,
) -> dict[str, Any]:
    """Normalize a flexible sliding configuration.

    Rules:
      - ``glass_count`` >= 1 (defaults to product ``shutterCount`` / 2).
      - ``mesh_count`` >= 0. If ``mesh`` is truthy but no count given, defaults to 1.
      - ``opening`` is 'center' for an even glass count (default), else 'telescopic'.
        An explicit value wins when provided.
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

    mode = str(opening or "").strip().lower()
    if mode not in ("center", "telescopic"):
        mode = "center" if g % 2 == 0 else "telescopic"

    fixed = normalize_fixed_shutters(fixed_shutters, g)

    return {
        "glassCount": int(g),
        "meshCount": int(m),
        "opening": mode,
        "fixedShutters": fixed,
        "mesh": bool(mesh) or m > 0,
        "trackCount": float(track_count) if track_count is not None else None,
    }


def line_layout_options(line: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract partitions / mesh / trackCount / shutter config from a cart line."""
    line = line or {}
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}

    def pick(*keys: str) -> Any:
        for k in keys:
            if line.get(k) is not None:
                return line.get(k)
            if isinstance(opts, Mapping) and opts.get(k) is not None:
                return opts.get(k)
        return None

    partitions = (
        line.get("partitions")
        or (opts or {}).get("partitions")
        or []
    )
    mesh = bool(line.get("mesh") if line.get("mesh") is not None else (opts or {}).get("mesh"))
    track_raw = pick("trackCount")
    try:
        track_count = float(track_raw) if track_raw is not None and str(track_raw).strip() != "" else None
    except (TypeError, ValueError):
        track_count = None

    shutter_cfg = resolve_shutter_config(
        glass_count=pick("glassShutters", "glassCount", "glass_count"),
        mesh_count=pick("meshShutters", "meshCount", "mesh_count"),
        mesh=mesh,
        track_count=track_count,
        fixed_shutters=pick("fixShutters", "fixedShutters", "fixed_shutters"),
        opening=pick("opening"),
    )
    system_raw = pick("system", "windowSystem")
    system = str(system_raw or "sliding").strip().lower()
    is_bifold = system in ("bifold", "fold", "fold_sliding", "fold_and_sliding")
    is_casement = system in ("casement", "openable", "opening")
    is_grid = system == "grid"
    if is_bifold:
        resolved_system = "bifold"
    elif is_casement:
        resolved_system = "casement"
    elif is_grid:
        resolved_system = "grid"
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

    return {
        "partitions": normalize_partitions(partitions),
        "mesh": shutter_cfg["mesh"] and not is_bifold and not is_casement,
        "trackCount": track_count,
        "glassCount": shutter_cfg["glassCount"],
        "meshCount": 0 if (is_bifold or is_casement) else shutter_cfg["meshCount"],
        "opening": shutter_cfg["opening"],
        "fixedShutters": shutter_cfg["fixedShutters"],
        # Raw (1-based / string) fix value — pass THIS to generate_job so it
        # normalises exactly once (avoids double 1-based conversion).
        "fixShuttersRaw": pick("fixShutters", "fixedShutters", "fixed_shutters"),
        "system": resolved_system,
        "foldLeft": _coerce_int(pick("foldLeft", "fold_left")),
        "foldRight": _coerce_int(pick("foldRight", "fold_right")),
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
    }
