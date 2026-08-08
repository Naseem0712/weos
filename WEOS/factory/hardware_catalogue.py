"""Standalone Hardware Engine + configurable Hardware Library + rules (Part 3).

Users register hardware once (hinges, wheels/rollers, floor spring, door closer,
handle, lock, keeper, connectors, brush, …) with brand, rate, unit, weight and
part number, then attach compatibility + quantity/weight rules to a product or
series in Product Library setup. Those rules drive hardware quantities in the BOM
automatically:

  * count rules — N of item per shutter / leaf / door / opening / track
  * weight-based selection — which hinge / wheel / floor spring / door closer to
    use based on the shutter/leaf weight range.

Library JSON lives under ``knowledge_base/libraries/hardware_catalogue/``.
Explicit user setup is directly editable; learned rules stay admin-approved via
the existing Learning/Memory gate.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from WEOS.paths import knowledge_base_dir

HARDWARE_CATEGORIES = [
    "hinge",
    "roller",
    "wheel",
    "floor_spring",
    "door_closer",
    "handle",
    "lock",
    "keeper",
    "connector",
    "brush",
    "gasket",
    "screw",
    "accessory",
]

# per-unit basis → context variable that supplies the count
PER_BASIS = {
    "opening": None,
    "shutter": "shutterCount",
    "leaf": "leafCount",
    "door": "doorCount",
    "track": "trackCount",
    "corner": "cornerCount",
    "pair": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "hw"


def catalogue_dir() -> Path:
    d = knowledge_base_dir() / "libraries" / "hardware_catalogue"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Library persistence ──────────────────────────────────────────────────────

def build_hardware_item(spec: Mapping[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name") or spec.get("id") or "Hardware")
    category = str(spec.get("category") or "accessory").strip().lower()
    hid = str(spec.get("id") or f"hw_{_slug(category)}_{_slug(name)}")
    return {
        "id": hid,
        "name": name,
        "category": category,
        "brand": str(spec.get("brand") or ""),
        "partNumber": str(spec.get("partNumber") or spec.get("partNo") or ""),
        "unit": str(spec.get("unit") or "PC"),
        "rate": float(spec["rate"]) if spec.get("rate") is not None else None,
        "weightKg": float(spec["weightKg"]) if spec.get("weightKg") is not None else None,
        "supplier": str(spec.get("supplier") or ""),
        "compatibleProducts": list(spec.get("compatibleProducts") or []),
        "compatibleSeries": list(spec.get("compatibleSeries") or []),
        "remarks": str(spec.get("remarks") or ""),
        "status": str(spec.get("status") or "active"),
        "updatedAt": _now(),
    }


def list_hardware() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(catalogue_dir().glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items


def get_hardware(hardware_id: str) -> dict[str, Any]:
    path = catalogue_dir() / f"{hardware_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Hardware '{hardware_id}' not found")
    return json.loads(path.read_text(encoding="utf-8"))


def save_hardware(spec: Mapping[str, Any]) -> dict[str, Any]:
    item = build_hardware_item(spec)
    (catalogue_dir() / f"{item['id']}.json").write_text(
        json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return item


def delete_hardware(hardware_id: str) -> dict[str, Any]:
    path = catalogue_dir() / f"{hardware_id}.json"
    if path.is_file():
        path.unlink()
        return {"ok": True, "deleted": hardware_id}
    raise FileNotFoundError(f"Hardware '{hardware_id}' not found")


def _library_index() -> dict[str, dict[str, Any]]:
    return {it["id"]: it for it in list_hardware() if it.get("id")}


# ── Rules engine (quantity + weight-based selection) ─────────────────────────

def _basis_count(per: str, ctx: Mapping[str, Any]) -> float:
    per = (per or "opening").strip().lower()
    var = PER_BASIS.get(per, None)
    if var is None:
        return 1.0
    try:
        return float(ctx.get(var) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _select_by_weight(rule: Mapping[str, Any], weight_kg: float) -> dict[str, Any] | None:
    """Pick a variant from weight ranges: first whose maxKg >= weight; else last."""
    ranges = list(rule.get("ranges") or [])
    if not ranges:
        return None
    ordered = sorted(ranges, key=lambda r: float(r.get("maxKg", 1e9)))
    for rng in ordered:
        try:
            if weight_kg <= float(rng.get("maxKg", 1e9)):
                return dict(rng)
        except (TypeError, ValueError):
            continue
    return dict(ordered[-1])


def apply_hardware_rules(
    rules: Sequence[Mapping[str, Any]] | None,
    ctx: Mapping[str, Any],
    *,
    leaf_weights_kg: Sequence[float] | None = None,
    library: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute hardware quantities from Product Library rules.

    Returns {"lines": [...], "trace": [...]} where each line has name/qty/unit/
    unitRate/weightKg/partNumber/remarks — ready to append to the BOM/quotation.
    """
    lib = dict(library or _library_index())
    leaf_weights = [float(w) for w in (leaf_weights_kg or []) if w is not None]
    typical_weight = max(leaf_weights) if leaf_weights else float(ctx.get("leafWeightKg") or ctx.get("shutterWeightKg") or 0.0)

    lines: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []

    for rule in rules or []:
        per = str(rule.get("per") or "opening")
        qty_each = float(rule.get("qty") or rule.get("quantity") or 1)
        select_by = str(rule.get("selectBy") or "").strip().lower()

        # Resolve which library item this rule points at.
        chosen_id = rule.get("hardwareId") or rule.get("item") or rule.get("hardware")
        chosen_name = rule.get("name")
        note = ""

        if select_by in ("leafweight", "shutterweight", "weight"):
            # Weight-based selection: per-leaf when we have individual weights.
            weights = leaf_weights or [typical_weight]
            picks: dict[str, dict[str, Any]] = {}
            for w in weights:
                variant = _select_by_weight(rule, w)
                if not variant:
                    continue
                vid = str(variant.get("item") or variant.get("hardwareId") or variant.get("name") or "variant")
                picks.setdefault(vid, {"variant": variant, "count": 0, "weights": []})
                picks[vid]["count"] += 1
                picks[vid]["weights"].append(round(w, 2))
            basis = _basis_count(per, ctx) or float(len(weights))
            for vid, info in picks.items():
                variant = info["variant"]
                lib_item = lib.get(str(variant.get("item") or variant.get("hardwareId") or ""), {})
                # qty = per-basis multiplier × how many leaves fell in this range
                count_leaves = info["count"] if leaf_weights else basis
                qty = qty_each * count_leaves
                lines.append(_line_from(variant, lib_item, qty, chosen_name or variant.get("name"),
                                        remarks=f"weight-selected ≤{variant.get('maxKg')}kg for {info['weights']}"))
                trace.append({
                    "rule": rule.get("hardware") or select_by,
                    "selectBy": select_by,
                    "picked": vid,
                    "leafWeights": info["weights"],
                    "qty": qty,
                })
            continue

        # Count-based rule.
        basis = _basis_count(per, ctx)
        qty = qty_each * (basis if PER_BASIS.get(per.lower()) is not None else 1.0)
        if qty <= 0 and per.lower() == "opening":
            qty = qty_each
        lib_item = lib.get(str(chosen_id), {}) if chosen_id else {}
        lines.append(_line_from(rule, lib_item, qty, chosen_name or (lib_item.get("name") if lib_item else chosen_id), remarks=note))
        trace.append({"rule": chosen_id or chosen_name, "per": per, "each": qty_each, "basis": basis, "qty": qty})

    return {"lines": lines, "trace": trace}


def _line_from(
    rule: Mapping[str, Any],
    lib_item: Mapping[str, Any],
    qty: float,
    name: Any,
    *,
    remarks: str = "",
) -> dict[str, Any]:
    rate = rule.get("unitRate")
    if rate is None:
        rate = rule.get("rate")
    if rate is None and lib_item:
        rate = lib_item.get("rate")
    weight = rule.get("weightKg")
    if weight is None and lib_item:
        weight = lib_item.get("weightKg")
    return {
        "category": "hardware",
        "name": str(name or lib_item.get("name") or rule.get("hardware") or "hardware"),
        "qty": round(float(qty), 4),
        "unit": str(rule.get("unit") or (lib_item.get("unit") if lib_item else None) or "PC"),
        "unitRate": float(rate) if rate is not None else None,
        "weightKg": float(weight) if weight is not None else None,
        "partNumber": str(rule.get("partNumber") or (lib_item.get("partNumber") if lib_item else "") or ""),
        "brand": str(rule.get("brand") or (lib_item.get("brand") if lib_item else "") or ""),
        "remarks": remarks,
    }


def to_line_items(lines: Sequence[Mapping[str, Any]]) -> list[Any]:
    """Convert rule engine lines into factory LineItem objects for the BOM."""
    from WEOS.factory.job_types import LineItem

    out: list[LineItem] = []
    for ln in lines or []:
        remarks = ln.get("remarks") or ""
        if ln.get("partNumber"):
            remarks = (f"P/N {ln['partNumber']} · " + remarks).strip(" ·")
        if ln.get("weightKg") is not None:
            remarks = (remarks + f" · {float(ln['weightKg']):.3f} kg").strip(" ·")
        out.append(
            LineItem(
                category="hardware",
                description=str(ln.get("name") or "hardware"),
                quantity=float(ln.get("qty") or 0),
                unit=str(ln.get("unit") or "PC"),
                length_mm=0.0,
                remarks=remarks,
                unit_rate=float(ln["unitRate"]) if ln.get("unitRate") is not None else None,
            )
        )
    return out


def hardware_bom_for_product(
    product: Mapping[str, Any],
    ctx: Mapping[str, Any],
    *,
    leaf_weights_kg: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Read a product's hardwareRules block and produce BOM hardware lines."""
    block = product.get("hardwareRules") or {}
    rules = block.get("rules") or []
    result = apply_hardware_rules(rules, ctx, leaf_weights_kg=leaf_weights_kg)
    result["compatibleHardware"] = block.get("compatibleHardware") or []
    return result


def seed_default_hardware(*, force: bool = False) -> dict[str, Any]:
    """Preload a common hardware set so the library is not empty on first use."""
    sentinel = catalogue_dir() / "_seeded.json"
    if sentinel.is_file() and not force:
        try:
            return json.loads(sentinel.read_text(encoding="utf-8"))
        except Exception:
            pass
    starters = [
        {"name": "SS Handle", "category": "handle", "unit": "PC", "rate": 180, "weightKg": 0.3},
        {"name": "Sliding Roller (twin)", "category": "roller", "unit": "PAIR", "rate": 220, "weightKg": 0.25},
        {"name": "Touch Lock", "category": "lock", "unit": "PC", "rate": 260, "weightKg": 0.15},
        {"name": "Hinge 4in", "category": "hinge", "unit": "PC", "rate": 90, "weightKg": 0.2},
        {"name": "Floor Spring 80kg", "category": "floor_spring", "unit": "PC", "rate": 2200, "weightKg": 3.5, "partNumber": "FS-80"},
        {"name": "Floor Spring 120kg", "category": "floor_spring", "unit": "PC", "rate": 3200, "weightKg": 4.2, "partNumber": "FS-120"},
        {"name": "Floor Spring 150kg", "category": "floor_spring", "unit": "PC", "rate": 4200, "weightKg": 5.0, "partNumber": "FS-150"},
    ]
    created = []
    for s in starters:
        try:
            created.append(save_hardware(s)["id"])
        except Exception:
            continue
    result = {"ok": True, "seeded": created, "count": len(created)}
    try:
        sentinel.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result
