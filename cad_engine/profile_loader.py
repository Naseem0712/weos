"""Load aluminium profile-series JSON (sole source of engineering rules)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
DEFAULT_PROFILE_ID = "29mm_sliding"

REQUIRED_SECTIONS = (
    "geometry",
    "glass",
    "hardware",
    "brush",
    "trackRail",
    "cutList",
    "weight",
    "quotation",
    "dimensioning",
    "bomExtras",
)

# Flat override key → (section, camelKey)
_OVERRIDE_MAP: dict[str, tuple[str, str]] = {
    "trackWidth": ("geometry", "trackWidth"),
    "track_width": ("geometry", "trackWidth"),
    "frameWidth": ("geometry", "frameWidth"),
    "frame_width": ("geometry", "frameWidth"),
    "shutter_frame": ("geometry", "frameWidth"),
    "shutterFrame": ("geometry", "frameWidth"),
    "interlockWidth": ("geometry", "interlockWidth"),
    "interlock_width": ("geometry", "interlockWidth"),
    "overlap": ("geometry", "overlap"),
    "glassClip": ("geometry", "glassClip"),
    "glass_clip": ("geometry", "glassClip"),
    "trackCount": ("geometry", "trackCount"),
    "track_count": ("geometry", "trackCount"),
    "shutterCount": ("geometry", "shutterCount"),
    "shutter_count": ("geometry", "shutterCount"),
    "meetingGap": ("geometry", "meetingGap"),
    "meeting_gap": ("geometry", "meetingGap"),
    "handleSideOverlap": ("glass", "handleSideOverlap"),
    "interlockSideOverlap": ("glass", "interlockSideOverlap"),
    "topOverlap": ("glass", "topOverlap"),
    "bottomOverlap": ("glass", "bottomOverlap"),
    "thicknessMm": ("glass", "thicknessMm"),
    "densityKgPerM3": ("glass", "densityKgPerM3"),
    "arrowSize": ("dimensioning", "arrowSize"),
    "arrow_size": ("dimensioning", "arrowSize"),
    "textHeight": ("dimensioning", "textHeight"),
    "text_height": ("dimensioning", "textHeight"),
    "offsetOuter": ("dimensioning", "offsetOuter"),
    "offset_outer": ("dimensioning", "offsetOuter"),
    "offsetInner": ("dimensioning", "offsetInner"),
    "offset_inner": ("dimensioning", "offsetInner"),
    "offsetDetail": ("dimensioning", "offsetDetail"),
    "offset_detail": ("dimensioning", "offsetDetail"),
    "stackGap": ("dimensioning", "stackGap"),
    "stack_gap": ("dimensioning", "stackGap"),
}


def profile_path(profile_id: str) -> Path:
    pid = profile_id.replace(".json", "")
    path = PROFILES_DIR / f"{pid}.json"
    if not path.is_file():
        known = sorted(p.stem for p in PROFILES_DIR.glob("*.json"))
        raise FileNotFoundError(f"Profile '{pid}' not found. Known: {', '.join(known) or '(none)'}")
    return path


def list_profiles() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not PROFILES_DIR.is_dir():
        return out
    for path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append((data.get("id", path.stem), data.get("displayName", path.stem)))
        except Exception:
            out.append((path.stem, path.stem))
    return out


def validate_profile_sections(data: Mapping[str, Any], *, path: str | Path = "") -> list[str]:
    """Return list of missing / invalid required engineering sections."""
    issues = [s for s in REQUIRED_SECTIONS if s not in data]
    if "quotation" in data:
        rates = (data.get("quotation") or {}).get("rates") or {}
        if "hardwareLumpSum" in rates:
            issues.append("quotation.rates must NOT contain hardwareLumpSum")
    return issues


def load_profile(profile_id: str | Path | None = None, *, strict: bool = True) -> dict[str, Any]:
    """Load a deep-copied profile document."""
    if isinstance(profile_id, Path):
        path = profile_id
    elif profile_id is None:
        path = profile_path(DEFAULT_PROFILE_ID)
    else:
        path = profile_path(str(profile_id))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Profile must be a JSON object: {path}")
    if strict:
        issues = validate_profile_sections(data, path=path)
        if issues:
            raise ValueError(f"Profile {path} missing/invalid sections: {', '.join(issues)}")
    data["_path"] = str(path)
    return copy.deepcopy(data)


def apply_geometry_overrides(profile: dict[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge flat/camel/dotted overrides into geometry / glass / dimensioning sections."""
    doc = copy.deepcopy(profile)
    if not overrides:
        return doc
    for raw_key, value in overrides.items():
        if value is None:
            continue
        key = str(raw_key).strip()
        section: str | None = None
        leaf: str | None = None
        if "." in key:
            section, leaf = key.split(".", 1)
            section = {"geom": "geometry", "dim": "dimensioning"}.get(section, section)
            mapped = _OVERRIDE_MAP.get(leaf)
            if mapped:
                section, leaf = mapped
        elif key in _OVERRIDE_MAP:
            section, leaf = _OVERRIDE_MAP[key]
        if not section or not leaf:
            continue
        block = dict(doc.get(section) or {})
        block[leaf] = float(value)
        doc[section] = block
    return doc


def geometry_as_engine_dict(profile: Mapping[str, Any]) -> dict[str, float]:
    """Flat snake_case geometry dict for drawing metadata / CLI dump."""
    g = profile.get("geometry") or {}
    required = ("trackWidth", "frameWidth", "interlockWidth", "overlap", "glassClip", "trackCount", "shutterCount")
    missing = [k for k in required if k not in g]
    if missing:
        raise KeyError(f"profile.geometry missing keys: {', '.join(missing)}")
    return {
        "track_width": float(g["trackWidth"]),
        "shutter_frame": float(g["frameWidth"]),
        "interlock_width": float(g["interlockWidth"]),
        "overlap": float(g["overlap"]),
        "glass_clip": float(g["glassClip"]),
        "track_count": float(g["trackCount"]),
        "shutter_count": float(g["shutterCount"]),
        "meeting_gap": float(g.get("meetingGap", 0)),
    }
