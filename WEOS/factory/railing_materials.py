"""Railing materials gallery — bottom rail, handrail, blocks, pillars, connectors.

Postgres-friendly JSON store under ``knowledge_base/libraries/railing_materials/``.
Each SKU carries dimensions (mm), colour, grade, mount/side type, unit (RFT/RMT/pc)
and rate so the normal-railing calculator can pull live prices into the cost cascade.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import knowledge_base_dir

RAILING_MATERIAL_CATEGORIES = [
    "bottom_rail",
    "handrail",
    "block",
    "ss_pillar",
    "u_channel",
    "end_cap",
    "wall_connector",
    "bend",
    "connector_180",
    "anchor",
    "stud",
]

MOUNT_TYPES = ["side_mount", "top_mount", "base_channel", "none"]
UNITS = ["RFT", "RMT", "pc", "sqft"]

# Maps gallery category → compute_railing rates key
CATEGORY_RATE_KEYS = {
    "bottom_rail": "bottomRailPerUnit",
    "handrail": "handrailPerUnit",
    "block": "blockPerPc",
    "ss_pillar": "blockPerPc",
    "u_channel": "bottomRailPerUnit",
    "end_cap": "endCapPerPc",
    "wall_connector": "wallConnectorPerPc",
    "bend": "modularBendPerPc",
    "connector_180": "connector180PerPc",
    "anchor": "anchorPerPc",
    "stud": "studPerPc",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "rm"


def catalogue_dir() -> Path:
    d = knowledge_base_dir() / "libraries" / "railing_materials"
    d.mkdir(parents=True, exist_ok=True)
    return d


def category_options() -> dict[str, Any]:
    return {
        "categories": RAILING_MATERIAL_CATEGORIES,
        "mountTypes": MOUNT_TYPES,
        "units": UNITS,
        "grades": ["316", "304", "6063-T5", "6063-T6", "MS", "other"],
        "colours": ["natural", "black", "white", "bronze", "4753", "RAL custom", "unfinished"],
        "rateKeys": CATEGORY_RATE_KEYS,
    }


def build_material(spec: Mapping[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name") or spec.get("id") or "Railing material")
    category = str(spec.get("category") or "block").strip().lower().replace("-", "_").replace(" ", "_")
    if category not in RAILING_MATERIAL_CATEGORIES:
        category = "block"
    mid = str(spec.get("id") or f"rm_{_slug(category)}_{_slug(name)}")
    unit = str(spec.get("unit") or ("pc" if category not in ("bottom_rail", "handrail", "u_channel") else "RFT")).upper()
    if unit == "PC":
        unit = "pc"
    return {
        "id": mid,
        "name": name,
        "category": category,
        "sizeMm": str(spec.get("sizeMm") or spec.get("size") or ""),
        "widthMm": float(spec["widthMm"]) if spec.get("widthMm") not in (None, "") else None,
        "heightMm": float(spec["heightMm"]) if spec.get("heightMm") not in (None, "") else None,
        "thicknessMm": float(spec["thicknessMm"]) if spec.get("thicknessMm") not in (None, "") else None,
        "diameterMm": float(spec["diameterMm"]) if spec.get("diameterMm") not in (None, "") else None,
        "color": str(spec.get("color") or spec.get("colour") or "natural"),
        "grade": str(spec.get("grade") or ""),
        "mountType": str(spec.get("mountType") or spec.get("side") or "none"),
        "unit": unit if unit in ("RFT", "RMT", "pc", "sqft") else "pc",
        "rate": float(spec["rate"]) if spec.get("rate") not in (None, "") else None,
        "weightKgPerUnit": float(spec["weightKgPerUnit"]) if spec.get("weightKgPerUnit") not in (None, "") else None,
        "brand": str(spec.get("brand") or ""),
        "remarks": str(spec.get("remarks") or ""),
        "status": str(spec.get("status") or "active"),
        "updatedAt": _now(),
    }


def list_materials(*, category: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(catalogue_dir().glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if active_only and str(data.get("status") or "active") != "active":
            continue
        if category and str(data.get("category") or "") != category:
            continue
        items.append(data)
    return items


def get_material(material_id: str) -> dict[str, Any] | None:
    path = catalogue_dir() / f"{material_id}.json"
    if not path.exists():
        # also try slug match
        for item in list_materials(active_only=False):
            if item.get("id") == material_id:
                return item
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_material(spec: Mapping[str, Any]) -> dict[str, Any]:
    item = build_material(spec)
    path = catalogue_dir() / f"{item['id']}.json"
    path.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return item


def delete_material(material_id: str) -> dict[str, Any]:
    path = catalogue_dir() / f"{material_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"railing material not found: {material_id}")
    path.unlink()
    return {"ok": True, "id": material_id}


DEFAULT_SEED: list[dict[str, Any]] = [
    {
        "id": "rm_bottom_rail_50x10_316_black",
        "name": "Bottom continuous rail 50×10",
        "category": "bottom_rail",
        "sizeMm": "50×10",
        "widthMm": 50,
        "heightMm": 10,
        "color": "black",
        "grade": "316",
        "mountType": "side_mount",
        "unit": "RFT",
        "rate": 180,
    },
    {
        "id": "rm_handrail_38_round_316_4753",
        "name": "Ø38 round slot handrail",
        "category": "handrail",
        "sizeMm": "Ø38×1.2",
        "diameterMm": 38,
        "thicknessMm": 1.2,
        "color": "4753",
        "grade": "316",
        "mountType": "top_mount",
        "unit": "RFT",
        "rate": 320,
    },
    {
        "id": "rm_block_side_50_316",
        "name": "Side-mount glass block 50 mm",
        "category": "block",
        "sizeMm": "50×50×30",
        "widthMm": 50,
        "heightMm": 50,
        "thicknessMm": 30,
        "color": "natural",
        "grade": "316",
        "mountType": "side_mount",
        "unit": "pc",
        "rate": 100,
    },
    {
        "id": "rm_ss_pillar_50_316",
        "name": "SS pillar 50 mm",
        "category": "ss_pillar",
        "sizeMm": "50×50",
        "widthMm": 50,
        "heightMm": 50,
        "color": "natural",
        "grade": "316",
        "mountType": "side_mount",
        "unit": "pc",
        "rate": 450,
    },
    {
        "id": "rm_u_channel_102x62_alu",
        "name": "Aluminium U-channel 102×62",
        "category": "u_channel",
        "sizeMm": "102×62",
        "widthMm": 102,
        "heightMm": 62,
        "color": "unfinished",
        "grade": "6063-T5",
        "mountType": "base_channel",
        "unit": "RFT",
        "rate": 220,
    },
    {
        "id": "rm_end_cap_38_316",
        "name": "Handrail end cap Ø38",
        "category": "end_cap",
        "sizeMm": "Ø38",
        "diameterMm": 38,
        "color": "4753",
        "grade": "316",
        "mountType": "none",
        "unit": "pc",
        "rate": 85,
    },
    {
        "id": "rm_wall_conn_38_316",
        "name": "Wall connector Ø38",
        "category": "wall_connector",
        "sizeMm": "Ø38",
        "diameterMm": 38,
        "color": "4753",
        "grade": "316",
        "mountType": "none",
        "unit": "pc",
        "rate": 120,
    },
    {
        "id": "rm_bend_90_38_316",
        "name": "Modular 90° bend Ø38",
        "category": "bend",
        "sizeMm": "Ø38 90°",
        "diameterMm": 38,
        "color": "4753",
        "grade": "316",
        "mountType": "none",
        "unit": "pc",
        "rate": 250,
    },
    {
        "id": "rm_conn180_38_316",
        "name": "180° handrail connector Ø38",
        "category": "connector_180",
        "sizeMm": "Ø38",
        "diameterMm": 38,
        "color": "4753",
        "grade": "316",
        "mountType": "none",
        "unit": "pc",
        "rate": 95,
    },
    {
        "id": "rm_anchor_m10",
        "name": "Anchor bolt M10",
        "category": "anchor",
        "sizeMm": "M10",
        "color": "natural",
        "grade": "SS",
        "mountType": "none",
        "unit": "pc",
        "rate": 50,
    },
]


def seed_default_materials(*, force: bool = False) -> dict[str, Any]:
    created = 0
    skipped = 0
    for spec in DEFAULT_SEED:
        path = catalogue_dir() / f"{spec['id']}.json"
        if path.exists() and not force:
            skipped += 1
            continue
        save_material(spec)
        created += 1
    return {"ok": True, "created": created, "skipped": skipped, "total": len(DEFAULT_SEED)}


def resolve_selections(selections: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Resolve materialIds from a selections map → full SKU dicts keyed by role."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(selections, Mapping):
        return out
    for role, raw in selections.items():
        mid = raw
        if isinstance(raw, Mapping):
            mid = raw.get("id") or raw.get("materialId")
        if not mid:
            continue
        item = get_material(str(mid))
        if item:
            out[str(role)] = item
    return out


def rates_from_selections(selections: Mapping[str, Any] | None) -> dict[str, float]:
    """Build compute_railing ``rates`` dict from gallery selections."""
    resolved = resolve_selections(selections)
    rates: dict[str, float] = {}
    weights: dict[str, float] = {}
    for role, item in resolved.items():
        cat = str(item.get("category") or role)
        key = CATEGORY_RATE_KEYS.get(cat)
        if not key:
            continue
        rate = item.get("rate")
        if rate is not None:
            rates[key] = float(rate)
        w = item.get("weightKgPerUnit")
        if w is not None:
            if key == "bottomRailPerUnit":
                weights["bottomRailWeightPerUnit"] = float(w)
            elif key == "handrailPerUnit":
                weights["handrailWeightPerUnit"] = float(w)
    rates.update(weights)
    return rates


def bom_meta_from_material(item: Mapping[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    return {
        "materialId": item.get("id"),
        "materialName": item.get("name"),
        "color": item.get("color"),
        "grade": item.get("grade"),
        "sizeMm": item.get("sizeMm"),
        "widthMm": item.get("widthMm"),
        "heightMm": item.get("heightMm"),
        "thicknessMm": item.get("thicknessMm"),
        "diameterMm": item.get("diameterMm"),
        "mountType": item.get("mountType"),
        "unit": item.get("unit"),
    }
