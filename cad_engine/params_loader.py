"""
Load nested master-parameter JSON and flatten to named engine keys.

Nested camelCase (outerFrame.trackWidth) and flat aliases (track_width / trackWidth)
all resolve to the same snake_case keys used by product generators.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

# Nested JSON paths → flat engine profile keys
PROFILE_NESTED: dict[tuple[str, str], str] = {
    ("outerFrame", "trackWidth"): "track_width",
    ("shutter", "frameWidth"): "shutter_frame",
    ("shutter", "overlap"): "overlap",
    ("interlock", "width"): "interlock_width",
    ("glass", "clipInset"): "glass_clip",
}

# Nested JSON paths → dimension presentation keys
DIM_NESTED: dict[tuple[str, str], str] = {
    ("dimensioning", "arrowSize"): "arrow_size",
    ("dimensioning", "textHeight"): "text_height",
    ("dimensioning", "offsetOuter"): "offset_outer",
    ("dimensioning", "offsetInner"): "offset_inner",
    ("dimensioning", "offsetDetail"): "offset_detail",
    ("dimensioning", "stackGap"): "stack_gap",
}

# Flat aliases (CLI --set, GUI, overrides) → engine key
PROFILE_ALIASES: dict[str, str] = {
    "track_width": "track_width",
    "trackWidth": "track_width",
    "track-width": "track_width",
    "shutter_frame": "shutter_frame",
    "shutterFrame": "shutter_frame",
    "frameWidth": "shutter_frame",
    "frame_width": "shutter_frame",
    "shutter-frame": "shutter_frame",
    "overlap": "overlap",
    "interlock_width": "interlock_width",
    "interlockWidth": "interlock_width",
    "interlock": "interlock_width",
    "interlock-width": "interlock_width",
    "glass_clip": "glass_clip",
    "glassClip": "glass_clip",
    "clipInset": "glass_clip",
    "glassInset": "glass_clip",
    "glass-clip": "glass_clip",
}

DIM_ALIASES: dict[str, str] = {
    "arrow_size": "arrow_size",
    "arrowSize": "arrow_size",
    "text_height": "text_height",
    "textHeight": "text_height",
    "offset_outer": "offset_outer",
    "offsetOuter": "offset_outer",
    "offset_inner": "offset_inner",
    "offsetInner": "offset_inner",
    "offset_detail": "offset_detail",
    "offsetDetail": "offset_detail",
    "stack_gap": "stack_gap",
    "stackGap": "stack_gap",
}

PROFILE_KEYS = ("track_width", "shutter_frame", "interlock_width", "overlap", "glass_clip")
DIM_KEYS = (
    "arrow_size",
    "text_height",
    "offset_outer",
    "offset_inner",
    "offset_detail",
    "stack_gap",
)

# Default master file for two-track (relative to project root)
DEFAULT_TWO_TRACK_PARAMS = Path(__file__).resolve().parent.parent / "params" / "two_track.json"


def camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower().replace("-", "_")


def load_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Params file must be a JSON object: {path}")
    return data


def _extract_nested(raw: Mapping[str, Any], schema: Mapping[tuple[str, str], str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for (section, key), flat in schema.items():
        block = raw.get(section)
        if isinstance(block, dict) and key in block:
            out[flat] = float(block[key])
    return out


def _extract_flat_aliases(raw: Mapping[str, Any], aliases: Mapping[str, str]) -> dict[str, float]:
    """Accept top-level flat keys (trackWidth / track_width) in addition to nested."""
    out: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, (dict, list)) or key in ("product", "units", "description"):
            continue
        if key in aliases:
            out[aliases[key]] = float(value)
            continue
        snake = camel_to_snake(str(key))
        if snake in aliases:
            out[aliases[snake]] = float(value)
    return out


def parse_master_params(raw: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    """
    Parse a master params document into (profile_params, dim_params).
    Nested sections win over flat aliases when both are present.
    """
    profile = _extract_flat_aliases(raw, PROFILE_ALIASES)
    profile.update(_extract_nested(raw, PROFILE_NESTED))

    dim = _extract_flat_aliases(raw, DIM_ALIASES)
    dim.update(_extract_nested(raw, DIM_NESTED))
    return profile, dim


def load_master_params(path: str | Path | None = None) -> tuple[dict[str, float], dict[str, float]]:
    """Load master JSON; returns (profile_params, dim_params)."""
    path = Path(path) if path else DEFAULT_TWO_TRACK_PARAMS
    return parse_master_params(load_json(path))


def normalize_overrides(overrides: Mapping[str, Any] | None) -> dict[str, float]:
    """Normalize CLI/GUI override keys to engine snake_case profile keys."""
    if not overrides:
        return {}
    out: dict[str, float] = {}
    for key, value in overrides.items():
        if value is None:
            continue
        if key in PROFILE_ALIASES:
            out[PROFILE_ALIASES[key]] = float(value)
        elif key in DIM_ALIASES:
            # Dimension overrides allowed but kept separate by caller if needed
            out[DIM_ALIASES[key]] = float(value)
        else:
            snake = camel_to_snake(str(key))
            if snake in PROFILE_ALIASES:
                out[PROFILE_ALIASES[snake]] = float(value)
            elif snake in DIM_ALIASES:
                out[DIM_ALIASES[snake]] = float(value)
            else:
                raise KeyError(
                    f"Unknown parameter '{key}'. "
                    f"Known profile: {', '.join(PROFILE_KEYS)}; "
                    f"dim: {', '.join(DIM_KEYS)}"
                )
    return out


def merge_params(
    base: Mapping[str, float],
    *layers: Mapping[str, float] | None,
) -> dict[str, float]:
    merged = dict(base)
    for layer in layers:
        if not layer:
            continue
        for k, v in layer.items():
            merged[k] = float(v)
    return merged


def split_profile_and_dim(flat: Mapping[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    profile = {k: float(flat[k]) for k in PROFILE_KEYS if k in flat}
    dim = {k: float(flat[k]) for k in DIM_KEYS if k in flat}
    return profile, dim


def parse_set_args(items: list[str] | None) -> dict[str, float]:
    """Parse --set trackWidth=32 --set interlock.width=26 style args."""
    if not items:
        return {}
    raw: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set expects key=value, got: {item!r}")
        key, val = item.split("=", 1)
        key = key.strip()
        # Allow dotted nested form: interlock.width → interlockWidth via last segment,
        # or map known dotted paths.
        if "." in key:
            parts = key.split(".")
            if len(parts) == 2:
                mapped = PROFILE_NESTED.get((parts[0], parts[1])) or DIM_NESTED.get(
                    (parts[0], parts[1])
                )
                if mapped:
                    raw[mapped] = float(val)
                    continue
            key = parts[-1]
        raw[key] = float(val)
    return normalize_overrides(raw)


def master_params_to_nested(
    profile: Mapping[str, float],
    dim: Mapping[str, float] | None = None,
    *,
    product: str = "two_track_sliding",
) -> dict[str, Any]:
    """Serialize flat engine params back to nested master JSON shape."""
    doc: dict[str, Any] = {
        "product": product,
        "units": "mm",
        "outerFrame": {"trackWidth": float(profile["track_width"])},
        "shutter": {
            "frameWidth": float(profile["shutter_frame"]),
            "overlap": float(profile["overlap"]),
        },
        "interlock": {"width": float(profile["interlock_width"])},
        "glass": {"clipInset": float(profile["glass_clip"])},
    }
    if dim:
        doc["dimensioning"] = {
            "arrowSize": float(dim.get("arrow_size", 30)),
            "textHeight": float(dim.get("text_height", 50)),
            "offsetOuter": float(dim.get("offset_outer", 72)),
            "offsetInner": float(dim.get("offset_inner", 70)),
            "offsetDetail": float(dim.get("offset_detail", 55)),
            "stackGap": float(dim.get("stack_gap", 90)),
        }
    return doc
