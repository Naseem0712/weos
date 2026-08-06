"""Material weight / waste engineering formulas.

Baseline knowledge the agent already knows, plus live compute helpers.
Refinements never write production — they queue as pending formula proposals.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import knowledge_base_dir
from WEOS.learning.knowledge_base import ensure_kb_dirs

# Industry-standard densities (kg/m³) — admin can refine via pending review
ALUMINIUM_DENSITY = 2700.0
STEEL_DENSITY = 7850.0
GLASS_DENSITY = 2500.0  # typical float / toughened glass

BASELINE_FORMULAS: dict[str, dict[str, Any]] = {
    "aluminium_sheet": {
        "id": "fx_alu_sheet_weight",
        "name": "Aluminium sheet weight",
        "category": "weight",
        "material": "aluminium_sheet",
        "expression": "thicknessMm * widthMm * heightMm * densityKgPerM3 / 1e9 * (1 + wastePercent/100) * qty",
        "variables": [
            "thicknessMm",
            "widthMm",
            "heightMm",
            "densityKgPerM3",
            "wastePercent",
            "qty",
        ],
        "defaults": {
            "densityKgPerM3": ALUMINIUM_DENSITY,
            "wastePercent": 5.0,
            "qty": 1,
        },
        "description": "Sheet weight (kg) from thickness × area × Al density, with waste allowance.",
        "unit": "kg",
        "source": "baseline_engineering",
    },
    "aluminium_section": {
        "id": "fx_alu_section_weight",
        "name": "Aluminium section / profile weight",
        "category": "weight",
        "material": "aluminium_section",
        "expression": "(lengthMm / 1000) * weightPerMeterKg * (1 + wastePercent/100) * qty",
        "variables": ["lengthMm", "weightPerMeterKg", "wastePercent", "qty"],
        "defaults": {"wastePercent": 8.0, "qty": 1},
        "description": "Extrusion weight from cut length × kg/m, with cutting waste.",
        "unit": "kg",
        "source": "baseline_engineering",
    },
    "iron_steel": {
        "id": "fx_steel_weight",
        "name": "Iron / steel plate weight",
        "category": "weight",
        "material": "iron_steel",
        "expression": "thicknessMm * widthMm * heightMm * densityKgPerM3 / 1e9 * (1 + wastePercent/100) * qty",
        "variables": [
            "thicknessMm",
            "widthMm",
            "heightMm",
            "densityKgPerM3",
            "wastePercent",
            "qty",
        ],
        "defaults": {
            "densityKgPerM3": STEEL_DENSITY,
            "wastePercent": 5.0,
            "qty": 1,
        },
        "description": "Steel/iron plate weight from dimensions × density, with waste.",
        "unit": "kg",
        "source": "baseline_engineering",
    },
    "glass": {
        "id": "fx_glass_weight",
        "name": "Glass panel weight",
        "category": "glass",
        "material": "glass",
        "expression": "thicknessMm * widthMm * heightMm * densityKgPerM3 / 1e9 * qty",
        "variables": ["thicknessMm", "widthMm", "heightMm", "densityKgPerM3", "qty"],
        "defaults": {"densityKgPerM3": GLASS_DENSITY, "qty": 1},
        "description": "Glass weight = volume × density (no cutting waste on pane; edge trim optional).",
        "unit": "kg",
        "source": "baseline_engineering",
    },
    "glass_with_waste": {
        "id": "fx_glass_weight_waste",
        "name": "Glass weight with edge waste",
        "category": "glass",
        "material": "glass",
        "expression": "thicknessMm * widthMm * heightMm * densityKgPerM3 / 1e9 * (1 + wastePercent/100) * qty",
        "variables": [
            "thicknessMm",
            "widthMm",
            "heightMm",
            "densityKgPerM3",
            "wastePercent",
            "qty",
        ],
        "defaults": {
            "densityKgPerM3": GLASS_DENSITY,
            "wastePercent": 3.0,
            "qty": 1,
        },
        "description": "Glass weight including optional edge / breakage waste %.",
        "unit": "kg",
        "source": "baseline_engineering",
    },
}


def formulas_dir() -> Path:
    ensure_kb_dirs()
    d = knowledge_base_dir() / "engineering" / "formulas"
    d.mkdir(parents=True, exist_ok=True)
    return d


def refinements_path() -> Path:
    return formulas_dir() / "learned_refinements.json"


def load_refinements() -> dict[str, Any]:
    path = refinements_path()
    if not path.is_file():
        return {"refinements": [], "overrides": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"refinements": [], "overrides": {}}


def save_refinements(doc: dict[str, Any]) -> None:
    refinements_path().write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def list_baseline_formulas(*, include_refinements: bool = True) -> list[dict[str, Any]]:
    overrides = load_refinements().get("overrides") or {} if include_refinements else {}
    out: list[dict[str, Any]] = []
    for key, base in BASELINE_FORMULAS.items():
        item = copy.deepcopy(base)
        item["key"] = key
        ov = overrides.get(key)
        if isinstance(ov, dict):
            # Only approved-style overrides stored after pending apply → still not production products
            if ov.get("defaults"):
                item["defaults"] = {**(item.get("defaults") or {}), **ov["defaults"]}
            if ov.get("expression"):
                item["expression"] = ov["expression"]
                item["refined"] = True
            item["refinementNote"] = ov.get("note")
        out.append(item)
    return out


def get_formula(material_or_key: str) -> dict[str, Any] | None:
    key = (material_or_key or "").strip().lower().replace(" ", "_")
    aliases = {
        "aluminium": "aluminium_section",
        "aluminum": "aluminium_section",
        "alu": "aluminium_section",
        "section": "aluminium_section",
        "profile": "aluminium_section",
        "sheet": "aluminium_sheet",
        "steel": "iron_steel",
        "iron": "iron_steel",
        "ms": "iron_steel",
    }
    key = aliases.get(key, key)
    for f in list_baseline_formulas():
        if f["key"] == key or f.get("material") == key or f.get("id") == key:
            return f
    return BASELINE_FORMULAS.get(key)


def _eval_expression(expression: str, vars_: Mapping[str, float]) -> float:
    """Safe arithmetic eval for formula expressions (no names/attrs)."""
    allowed = {k: float(v) for k, v in vars_.items()}
    # Only allow numbers and operators via restricted eval
    code = compile(expression, "<formula>", "eval")
    for name in code.co_names:
        if name not in allowed:
            raise ValueError(f"Unknown variable in formula: {name}")
    return float(eval(code, {"__builtins__": {}}, allowed))  # noqa: S307 — intentional sandbox


def compute_weight(
    material: str,
    *,
    params: Mapping[str, Any] | None = None,
    formula_key: str | None = None,
) -> dict[str, Any]:
    """Live weight compute for UI / admin assist."""
    fx = get_formula(formula_key or material)
    if not fx:
        raise ValueError(f"Unknown material formula: {material}")
    merged: dict[str, float] = {}
    for k, v in (fx.get("defaults") or {}).items():
        try:
            merged[k] = float(v)
        except (TypeError, ValueError):
            pass
    for k, v in (params or {}).items():
        if v is None or v == "":
            continue
        try:
            merged[k] = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid numeric param: {k}={v}") from None

    missing = [v for v in (fx.get("variables") or []) if v not in merged]
    if missing:
        return {
            "ok": False,
            "formula": fx,
            "missing": missing,
            "inputs": merged,
            "message": f"Missing inputs: {', '.join(missing)}",
        }

    value = _eval_expression(fx["expression"], merged)
    return {
        "ok": True,
        "formula": {
            "id": fx.get("id"),
            "key": fx.get("key"),
            "name": fx.get("name"),
            "expression": fx.get("expression"),
            "unit": fx.get("unit", "kg"),
            "refined": bool(fx.get("refined")),
        },
        "inputs": merged,
        "weightKg": round(value, 4),
        "message": f"{fx.get('name')}: {round(value, 3)} {fx.get('unit', 'kg')}",
    }


def propose_refinement_payload(
    formula_key: str,
    *,
    defaults: Mapping[str, Any] | None = None,
    expression: str | None = None,
    note: str | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a pending-review payload for a formula refinement (not applied yet)."""
    base = get_formula(formula_key)
    if not base:
        raise ValueError(f"Unknown formula key: {formula_key}")
    formulas = [
        {
            **{k: v for k, v in base.items() if k not in ("refined", "refinementNote")},
            "defaults": {**(base.get("defaults") or {}), **(defaults or {})},
            "expression": expression or base.get("expression"),
            "description": note or base.get("description"),
            "source": "engineering_live_learn",
            "evidence": dict(evidence or {}),
        }
    ]
    return {
        "formulas": formulas,
        "refinementOf": formula_key,
        "note": note,
        "safety": "Pending admin review — does not modify production engines until approved into KB formulas library.",
    }


def record_local_override(
    formula_key: str,
    *,
    defaults: Mapping[str, Any] | None = None,
    expression: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Store a learned override in engineering/formulas only (still not production product JSON).

    Prefer create_pending via apply_suggestion for the gated path; this is used after
    KB approve if admin opts to sync local live-compute defaults.
    """
    doc = load_refinements()
    overrides = dict(doc.get("overrides") or {})
    cur = dict(overrides.get(formula_key) or {})
    if defaults:
        cur["defaults"] = {**(cur.get("defaults") or {}), **dict(defaults)}
    if expression:
        cur["expression"] = expression
    if note:
        cur["note"] = note
    overrides[formula_key] = cur
    history = list(doc.get("refinements") or [])
    history.append({"formulaKey": formula_key, "change": cur, "note": note})
    doc["overrides"] = overrides
    doc["refinements"] = history[-200:]
    save_refinements(doc)
    return {"ok": True, "formulaKey": formula_key, "override": cur}
