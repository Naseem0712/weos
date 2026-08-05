"""
Two Track Sliding — thin product adapter over the manufacturing pipeline.

Engineering values live in profiles/29mm_sliding.json only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cad_engine.geometry_engine import SlidingLayout, compute_two_track_layout  # noqa: F401
from cad_engine.pipeline import generate_job
from cad_engine.profile_loader import DEFAULT_PROFILE_ID, geometry_as_engine_dict, load_profile
from cad_engine.types import DrawingModel
from products import ProductGenerator, register


def compute_layout(width: float, height: float, params: Any = None) -> SlidingLayout:
    """Compatibility wrapper used by verify scripts."""
    profile = load_profile(DEFAULT_PROFILE_ID)
    geom = dict(profile["geometry"])
    if params is not None:
        d = params.as_dict() if hasattr(params, "as_dict") else dict(params)
        mapping = {
            "track_width": "trackWidth",
            "trackWidth": "trackWidth",
            "shutter_frame": "frameWidth",
            "frameWidth": "frameWidth",
            "shutterFrame": "frameWidth",
            "interlock_width": "interlockWidth",
            "interlockWidth": "interlockWidth",
            "overlap": "overlap",
            "glass_clip": "glassClip",
            "glassClip": "glassClip",
        }
        for k, v in d.items():
            ck = mapping.get(k)
            if ck:
                geom[ck] = float(v)
    return compute_two_track_layout(width, height, geom)


class TwoTrackParams:
    """Shim over profile geometry for older verify helpers — values from JSON only."""

    def __init__(self, **kwargs: float) -> None:
        g = load_profile(DEFAULT_PROFILE_ID)["geometry"]
        self.track_width = float(kwargs.get("track_width", g["trackWidth"]))
        self.shutter_frame = float(kwargs.get("shutter_frame", g["frameWidth"]))
        self.interlock_width = float(kwargs.get("interlock_width", g["interlockWidth"]))
        self.overlap = float(kwargs.get("overlap", g["overlap"]))
        self.glass_clip = float(kwargs.get("glass_clip", g["glassClip"]))

    def as_dict(self) -> dict[str, float]:
        return {
            "track_width": self.track_width,
            "shutter_frame": self.shutter_frame,
            "interlock_width": self.interlock_width,
            "overlap": self.overlap,
            "glass_clip": self.glass_clip,
        }

    @classmethod
    def from_master_json(cls, path: Path | str | None = None) -> TwoTrackParams:
        if path is not None and Path(path).is_file() and Path(path).parent.name == "profiles":
            g = load_profile(path)["geometry"]
        else:
            g = load_profile(DEFAULT_PROFILE_ID)["geometry"]
        return cls(
            track_width=float(g["trackWidth"]),
            shutter_frame=float(g["frameWidth"]),
            interlock_width=float(g["interlockWidth"]),
            overlap=float(g["overlap"]),
            glass_clip=float(g["glassClip"]),
        )

    @classmethod
    def from_dict(cls, data: dict[str, float] | None, *, master_path: Path | None = None) -> TwoTrackParams:
        base = cls.from_master_json(master_path)
        if not data:
            return base
        d = base.as_dict()
        aliases = {
            "track_width": "track_width",
            "trackWidth": "track_width",
            "shutter_frame": "shutter_frame",
            "frameWidth": "shutter_frame",
            "shutterFrame": "shutter_frame",
            "interlock_width": "interlock_width",
            "interlockWidth": "interlock_width",
            "overlap": "overlap",
            "glass_clip": "glass_clip",
            "glassClip": "glass_clip",
        }
        for k, v in data.items():
            key = aliases.get(k)
            if key:
                d[key] = float(v)
        return cls(**d)


@register
class TwoTrackSlidingDoor(ProductGenerator):
    product_id = "two_track_sliding"
    display_name = "Two Track Sliding Door"
    profile_id = DEFAULT_PROFILE_ID

    def default_params(self) -> dict[str, float]:
        return geometry_as_engine_dict(load_profile(self.profile_id))

    def generate(self, width: float, height: float, params: dict[str, float] | None = None) -> DrawingModel:
        return generate_job(width, height, self.profile_id, overrides=params).drawing

    def generate_job(self, width: float, height: float, params: dict[str, float] | None = None):
        return generate_job(width, height, self.profile_id, overrides=params)
