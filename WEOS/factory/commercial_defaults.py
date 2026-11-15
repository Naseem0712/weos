"""Company / project commercial defaults — labour, install, coating finishes.

Editable later in Series Setup / company profile; these are the seed defaults
after profile/hardware Excel load.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import PACKAGE_ROOT

# ── Hard-coded fallbacks (also written to commercial_defaults.json) ──────────
DEFAULT_LABOUR_PER_SFT = 120.0
DEFAULT_INSTALLATION_PER_SFT = 40.0

# Powder-coat brands (exterior grade) — user can change later.
DEFAULT_COATING_BRANDS: tuple[str, ...] = ("AkzoNobel", "Jotun")
DEFAULT_COATING_BRAND = "AkzoNobel"

# Finish family → multiplier applied to *coating* rate only (not aluminium).
# Plain = rates already loaded on sections; texture +20%; wooden +50%.
COATING_FAMILY_MULTIPLIER: dict[str, float] = {
    "plain": 1.0,
    "texture": 1.20,
    "wooden": 1.50,
}

# Colour id → finish family
COATING_COLOUR_FAMILY: dict[str, str] = {
    "white": "plain",
    "black": "plain",
    "brown": "plain",
    "bronze": "plain",
    "grey": "plain",
    "matt_black": "plain",
    "black_texture": "texture",
    "texture": "texture",
    "wood_oak": "wooden",
    "wooden": "wooden",
    "wood_finish": "wooden",
    "wood": "wooden",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def defaults_path() -> Path:
    d = PACKAGE_ROOT / "company"
    d.mkdir(parents=True, exist_ok=True)
    return d / "commercial_defaults.json"


def default_doc() -> dict[str, Any]:
    return {
        "labourPerSft": DEFAULT_LABOUR_PER_SFT,
        "installationPerSft": DEFAULT_INSTALLATION_PER_SFT,
        "coatingBrands": list(DEFAULT_COATING_BRANDS),
        "defaultCoatingBrand": DEFAULT_COATING_BRAND,
        "coatingFamilyMultiplier": dict(COATING_FAMILY_MULTIPLIER),
        "coatingColourFamily": dict(COATING_COLOUR_FAMILY),
        "notes": (
            "Labour ₹120/sft + installation ₹40/sft for windows. "
            "Coating: plain = section coatingCost; texture +20%; wooden +50%. "
            "Brands: AkzoNobel / Jotun (exterior). Editable in Series Setup."
        ),
        "updatedAt": _now(),
    }


def load_commercial_defaults() -> dict[str, Any]:
    path = defaults_path()
    base = default_doc()
    if not path.is_file():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return base
    if not isinstance(raw, Mapping):
        return base
    out = deepcopy(base)
    for k, v in raw.items():
        if v is not None:
            out[k] = v
    return out


def save_commercial_defaults(doc: Mapping[str, Any] | None = None) -> dict[str, Any]:
    data = dict(default_doc())
    if isinstance(doc, Mapping):
        data.update({k: v for k, v in doc.items() if v is not None})
    data["updatedAt"] = _now()
    path = defaults_path()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def labour_per_sft(override: Any = None) -> float:
    if override is not None and str(override).strip() != "":
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    doc = load_commercial_defaults()
    try:
        return float(doc.get("labourPerSft") or DEFAULT_LABOUR_PER_SFT)
    except (TypeError, ValueError):
        return DEFAULT_LABOUR_PER_SFT


def installation_per_sft(override: Any = None) -> float:
    if override is not None and str(override).strip() != "":
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    doc = load_commercial_defaults()
    try:
        return float(doc.get("installationPerSft") or DEFAULT_INSTALLATION_PER_SFT)
    except (TypeError, ValueError):
        return DEFAULT_INSTALLATION_PER_SFT


def coating_brands() -> list[str]:
    doc = load_commercial_defaults()
    brands = doc.get("coatingBrands") or list(DEFAULT_COATING_BRANDS)
    out: list[str] = []
    for b in brands:
        s = str(b or "").strip()
        if s and s not in out:
            out.append(s)
    return out or list(DEFAULT_COATING_BRANDS)


def default_coating_brand() -> str:
    doc = load_commercial_defaults()
    b = str(doc.get("defaultCoatingBrand") or "").strip()
    return b or DEFAULT_COATING_BRAND


def finish_family_for_colour(colour: Any) -> str:
    cid = str(colour or "white").strip().lower().replace(" ", "_").replace("-", "_")
    doc = load_commercial_defaults()
    mapping = dict(COATING_COLOUR_FAMILY)
    custom = doc.get("coatingColourFamily")
    if isinstance(custom, Mapping):
        mapping.update({str(k).lower(): str(v).lower() for k, v in custom.items()})
    if cid in mapping:
        return mapping[cid]
    if "texture" in cid or "textured" in cid:
        return "texture"
    if "wood" in cid or "wooden" in cid:
        return "wooden"
    return "plain"


def coating_multiplier_for_colour(colour: Any) -> float:
    family = finish_family_for_colour(colour)
    doc = load_commercial_defaults()
    mults = dict(COATING_FAMILY_MULTIPLIER)
    custom = doc.get("coatingFamilyMultiplier")
    if isinstance(custom, Mapping):
        for k, v in custom.items():
            try:
                mults[str(k).lower()] = float(v)
            except (TypeError, ValueError):
                continue
    try:
        return float(mults.get(family, 1.0))
    except (TypeError, ValueError):
        return 1.0


def ensure_commercial_defaults_file() -> dict[str, Any]:
    path = defaults_path()
    if path.is_file():
        return load_commercial_defaults()
    return save_commercial_defaults()
