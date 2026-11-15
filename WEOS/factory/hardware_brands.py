"""Default hardware brand names by origin (editable catalogue defaults).

Indian  → HIVIC
Imported → CMECH
ETTE (imported line) → ETTE

Used whenever hardware appears on a quote (descriptions, materials list, PDF /
window_specs). Rates stay editable in Series Setup / Hardware Library; only the
*default brand label* is derived from origin when brand is blank.
"""

from __future__ import annotations

from typing import Any, Mapping

BRAND_BY_ORIGIN: dict[str, str] = {
    "indian": "HIVIC",
    "imported": "CMECH",
    "ette": "ETTE",
}

ORIGIN_ALIASES: dict[str, str] = {
    "indian": "indian",
    "india": "indian",
    "local": "indian",
    "hivic": "indian",
    "imported": "imported",
    "import": "imported",
    "cmech": "imported",
    "ette": "ette",
    "ette_imported": "ette",
    "ette-imported": "ette",
}


def normalize_origin(value: Any) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not raw:
        return ""
    if raw in ORIGIN_ALIASES:
        return ORIGIN_ALIASES[raw]
    if "ette" in raw:
        return "ette"
    if "import" in raw or "cmech" in raw:
        return "imported"
    if "indian" in raw or "india" in raw or "hivic" in raw or "local" in raw:
        return "indian"
    return ""


def brand_for_origin(origin: Any) -> str:
    key = normalize_origin(origin)
    return BRAND_BY_ORIGIN.get(key, "")


def infer_origin_from_text(*parts: Any) -> str:
    """Best-effort origin from name/remarks when Excel has no origin column."""
    blob = " ".join(str(p or "") for p in parts).strip().lower()
    if not blob:
        return "indian"
    if "ette" in blob:
        return "ette"
    # Premium / imported-leaning casement & lock hardware
    imported_markers = (
        "friction stay",
        "friction",
        "multipoint premium",
        "mortice",
        "heavy duty",
        "lock matchine",
        "lock machine",
        "lamination arm",
        "limitation arm",
        "floor spring",
        "door closer",
        "3 wings",
    )
    if any(m in blob for m in imported_markers):
        return "imported"
    return "indian"


def resolve_hardware_brand(
    item: Mapping[str, Any] | None = None,
    *,
    brand: Any = None,
    origin: Any = None,
    name: Any = None,
    default_origin: str = "indian",
) -> str:
    """Pick printable brand: explicit brand → origin map → inferred → HIVIC."""
    src = item if isinstance(item, Mapping) else {}
    explicit = str(brand if brand is not None else src.get("brand") or "").strip()
    if explicit:
        # Normalize known brand aliases to canonical casing
        low = explicit.lower()
        if low in ("hivic", "cmech", "ette"):
            return explicit.upper() if low != "ette" else "ETTE"
        if low == "ette":
            return "ETTE"
        return explicit

    org = normalize_origin(origin if origin is not None else src.get("origin") or src.get("hardwareOrigin"))
    if not org:
        org = infer_origin_from_text(
            name if name is not None else src.get("name"),
            src.get("remarks"),
            src.get("category"),
            src.get("partNumber"),
        ) or normalize_origin(default_origin) or "indian"
    return brand_for_origin(org) or "HIVIC"


def with_resolved_brand(item: Mapping[str, Any], *, default_origin: str = "indian") -> dict[str, Any]:
    out = dict(item)
    origin = normalize_origin(out.get("origin") or out.get("hardwareOrigin"))
    if not origin:
        origin = infer_origin_from_text(out.get("name"), out.get("remarks"), out.get("category"))
        out["origin"] = origin
    elif "origin" not in out:
        out["origin"] = origin
    out["brand"] = resolve_hardware_brand(out, default_origin=default_origin)
    return out
