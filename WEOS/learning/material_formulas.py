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
GLASS_DENSITY = 2500.0  # typical float / toughened glass (~2.5 kg/m² per mm)
PVB_DENSITY = 1070.0  # PVB interlayer for laminated glass (~1.07 kg/m² per mm)
# ACP = aluminium composite panel (2 Al skins + PE core). Typical 4 mm ≈ 5.6 kg/m²
# → effective ~1.4 kg/m² per mm of panel thickness.
ACP_KG_PER_SQM_PER_MM = 1.4

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
    "glass_dgu": {
        "id": "fx_glass_dgu_weight",
        "name": "DGU (double-glazed unit) weight",
        "category": "glass",
        "material": "glass_dgu",
        # Air gap adds ~0 kg. Weight = area × (Σ glass thickness × density) per pane.
        "expression": "widthMm * heightMm / 1e6 * ((glass1Mm + glass2Mm) * densityKgPerM3 / 1000) * qty",
        "variables": ["widthMm", "heightMm", "glass1Mm", "glass2Mm", "densityKgPerM3", "qty"],
        "defaults": {"densityKgPerM3": GLASS_DENSITY, "qty": 1},
        "description": "Insulated glass unit weight = pane area × sum of both glass leaves × glass density (air gap ≈ 0 kg).",
        "unit": "kg",
        "source": "baseline_engineering",
    },
    "glass_laminated": {
        "id": "fx_glass_laminated_weight",
        "name": "Laminated glass weight (glass + PVB)",
        "category": "glass",
        "material": "glass_laminated",
        "expression": (
            "widthMm * heightMm / 1e6 * "
            "((glass1Mm + glass2Mm) * densityKgPerM3 / 1000 + pvbMm * pvbDensityKgPerM3 / 1000) * qty"
        ),
        "variables": [
            "widthMm",
            "heightMm",
            "glass1Mm",
            "glass2Mm",
            "pvbMm",
            "densityKgPerM3",
            "pvbDensityKgPerM3",
            "qty",
        ],
        "defaults": {
            "densityKgPerM3": GLASS_DENSITY,
            "pvbDensityKgPerM3": PVB_DENSITY,
            "pvbMm": 0.76,
            "qty": 1,
        },
        "description": "Laminated glass = two glass leaves + PVB interlayer; 11.52 = 5+0.52+5 style makeups.",
        "unit": "kg",
        "source": "baseline_engineering",
    },
    "acp_sheet": {
        "id": "fx_acp_weight",
        "name": "ACP (aluminium composite panel) weight",
        "category": "weight",
        "material": "acp_sheet",
        "expression": "widthMm * heightMm / 1e6 * thicknessMm * kgPerSqmPerMm * (1 + wastePercent/100) * qty",
        "variables": ["widthMm", "heightMm", "thicknessMm", "kgPerSqmPerMm", "wastePercent", "qty"],
        "defaults": {"kgPerSqmPerMm": ACP_KG_PER_SQM_PER_MM, "wastePercent": 5.0, "qty": 1},
        "description": "ACP panel weight from area × thickness × panel weight factor (4 mm ≈ 5.6 kg/m²).",
        "unit": "kg",
        "source": "baseline_engineering",
    },
    "sheet_generic": {
        "id": "fx_sheet_generic_weight",
        "name": "Generic sheet weight (size × thickness × density)",
        "category": "weight",
        "material": "sheet_generic",
        "expression": "thicknessMm * widthMm * heightMm * densityKgPerM3 / 1e9 * (1 + wastePercent/100) * qty",
        "variables": ["thicknessMm", "widthMm", "heightMm", "densityKgPerM3", "wastePercent", "qty"],
        "defaults": {"densityKgPerM3": ALUMINIUM_DENSITY, "wastePercent": 5.0, "qty": 1},
        "description": "Any flat sheet: volume × material density (set densityKgPerM3 per material).",
        "unit": "kg",
        "source": "baseline_engineering",
    },
}

# Default weight formula key by loose material/category name — used to auto-attach
# a weightFormula to Product Library materials that don't declare one.
DEFAULT_WEIGHT_FORMULA_BY_MATERIAL: dict[str, str] = {
    "aluminium": "aluminium_section",
    "aluminum": "aluminium_section",
    "alu": "aluminium_section",
    "profile": "aluminium_section",
    "section": "aluminium_section",
    "extrusion": "aluminium_section",
    "aluminium_sheet": "aluminium_sheet",
    "alu_sheet": "aluminium_sheet",
    "sheet": "sheet_generic",
    "acp": "acp_sheet",
    "acp_sheet": "acp_sheet",
    "composite": "acp_sheet",
    "glass": "glass",
    "glass_dgu": "glass_dgu",
    "dgu": "glass_dgu",
    "glass_laminated": "glass_laminated",
    "laminated": "glass_laminated",
    "iron": "iron_steel",
    "steel": "iron_steel",
    "ms": "iron_steel",
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


def _formula_memory_dir() -> Path:
    return knowledge_base_dir() / "memories" / "formula"


def recall_approved_formulas() -> list[dict[str, Any]]:
    """Recall approved formulas from KB memory. Never invent weights/defaults.

    Sources (first wins per id): Formula Memory store (status=approved) →
    ``knowledge_base/memories/formula/*.json`` → baseline expressions only.
    Learned candidates without approval are ignored.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _take(item: Mapping[str, Any], *, source: str) -> None:
        if not isinstance(item, Mapping):
            return
        st = str(item.get("status") or "approved").strip().lower()
        if st and st not in ("approved", "active", ""):
            return
        expr = str(item.get("expression") or "").strip()
        if not expr:
            return
        fid = str(item.get("id") or item.get("key") or "").strip()
        if not fid or fid.startswith("_") or fid in seen:
            return
        seen.add(fid)
        row = {
            "id": fid,
            "key": str(item.get("key") or item.get("outputName") or item.get("material") or fid),
            "name": item.get("name") or fid,
            "category": item.get("category") or "weight",
            "material": item.get("material") or item.get("outputName") or item.get("key"),
            "expression": expr,
            "variables": list(item.get("variables") or []),
            "defaults": dict(item.get("defaults") or {}) if isinstance(item.get("defaults"), dict) else {},
            "unit": item.get("unit") or "kg",
            "description": item.get("description") or "",
            "source": source,
            "status": "approved",
            "recalled": True,
        }
        out.append(row)

    try:
        from WEOS.memory.schemas import MEM_FORMULA
        from WEOS.memory.store import get_store

        store = get_store()
        for item in store.list(MEM_FORMULA) or []:
            st = str(item.get("status") or "").strip().lower()
            if st and st not in ("approved", "active", ""):
                continue
            _take(item, source="formula_memory")
    except Exception:
        pass

    mem_dir = _formula_memory_dir()
    if mem_dir.is_dir():
        for path in sorted(mem_dir.glob("*.json")):
            if path.name.startswith("_"):
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(doc, dict):
                doc.setdefault("id", path.stem)
                _take(doc, source="kb_formula_file")

    return out


def list_baseline_formulas(*, include_refinements: bool = True, include_memory: bool = True) -> list[dict[str, Any]]:
    overrides = load_refinements().get("overrides") or {} if include_refinements else {}
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    if include_memory:
        for mem in recall_approved_formulas():
            item = copy.deepcopy(mem)
            fid = str(item.get("id") or "")
            if fid:
                seen_ids.add(fid)
            out.append(item)
    for key, base in BASELINE_FORMULAS.items():
        item = copy.deepcopy(base)
        item["key"] = key
        fid = str(item.get("id") or "")
        if fid and fid in seen_ids:
            # Memory already recalled this id — keep KB copy, overlay baseline
            # expression only when memory is missing fields (do not invent weights).
            continue
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
        if fid:
            seen_ids.add(fid)
    return out


_FORMULA_ALIASES = {
    "aluminium": "aluminium_section",
    "aluminum": "aluminium_section",
    "alu": "aluminium_section",
    "section": "aluminium_section",
    "profile": "aluminium_section",
    "railing": "iron_steel",
    "ms_railing": "iron_steel",
    "sheet": "sheet_generic",
    "generic_sheet": "sheet_generic",
    "aluminium_sheet": "aluminium_sheet",
    "acp": "acp_sheet",
    "composite": "acp_sheet",
    "dgu": "glass_dgu",
    "dg": "glass_dgu",
    "double_glazed": "glass_dgu",
    "sg": "glass",
    "single_glazed": "glass",
    "laminated": "glass_laminated",
    "steel": "iron_steel",
    "iron": "iron_steel",
    "ms": "iron_steel",
}


def get_formula(material_or_key: str) -> dict[str, Any] | None:
    key = (material_or_key or "").strip().lower().replace(" ", "_")
    key = _FORMULA_ALIASES.get(key, key)
    recalled = list_baseline_formulas()
    for f in recalled:
        ids = {
            str(f.get("key") or "").lower(),
            str(f.get("material") or "").lower(),
            str(f.get("id") or "").lower(),
            str(f.get("outputName") or "").lower(),
        }
        if key in ids or f"fx_{key}" in ids or key.replace("fx_", "") in {i.replace("fx_", "") for i in ids}:
            return f
    base = BASELINE_FORMULAS.get(key)
    if base:
        item = copy.deepcopy(base)
        item["key"] = key
        return item
    return None


def recall_formula_for_context(
    *,
    material: str | None = None,
    glass_makeup: str | None = None,
    product: str | None = None,
) -> dict[str, Any] | None:
    """Map quote context → approved KB formula. Returns None rather than inventing."""
    makeup = (glass_makeup or "").strip().lower()
    prod = (product or "").strip().lower()
    mat = (material or "").strip().lower()
    if makeup in ("dgu", "dg", "double", "double_glazed", "insulated") or "dgu" in mat or "double" in mat:
        return get_formula("glass_dgu")
    if makeup in ("laminated", "lami", "pvb") or "laminat" in mat:
        return get_formula("glass_laminated")
    if makeup in ("sg", "single", "single_glazed") or mat in ("glass", "sg"):
        return get_formula("glass")
    if "rail" in prod or "steel" in mat or "ms" == mat or "iron" in mat:
        return get_formula("iron_steel")
    if "acp" in mat or "composite" in mat:
        return get_formula("acp_sheet")
    if "sheet" in mat:
        return get_formula("aluminium_sheet") if "alu" in mat or "aluminium" in mat else get_formula("sheet_generic")
    if mat:
        return get_formula(mat)
    if "glass" in prod:
        return get_formula("glass")
    if any(k in prod for k in ("slid", "case", "window", "door")):
        return get_formula("aluminium_section")
    return None


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


def compute_glass_makeup_weight(
    *,
    makeup: str,
    width_mm: float,
    height_mm: float,
    layers_mm: list[float] | tuple[float, ...] | None = None,
    pvb_mm: float = 0.76,
    thickness_mm: float | None = None,
    density: float = GLASS_DENSITY,
    qty: float = 1.0,
) -> dict[str, Any]:
    """Weight for a glass pane by makeup: single | dgu | laminated.

    Reuses the preloaded baseline formulas so results stay consistent with the
    Formula Memory the admin can edit/version.
    """
    kind = (makeup or "single").strip().lower()
    layers = [float(x) for x in (layers_mm or []) if x]
    if kind in ("dgu", "double", "double_glazed", "insulated"):
        g1 = layers[0] if len(layers) > 0 else (thickness_mm or 5.0)
        g2 = layers[1] if len(layers) > 1 else g1
        return compute_weight(
            "glass_dgu",
            params={"widthMm": width_mm, "heightMm": height_mm, "glass1Mm": g1, "glass2Mm": g2, "densityKgPerM3": density, "qty": qty},
            formula_key="glass_dgu",
        )
    if kind in ("laminated", "lami", "pvb"):
        g1 = layers[0] if len(layers) > 0 else (thickness_mm or 5.0)
        g2 = layers[1] if len(layers) > 1 else g1
        return compute_weight(
            "glass_laminated",
            params={
                "widthMm": width_mm,
                "heightMm": height_mm,
                "glass1Mm": g1,
                "glass2Mm": g2,
                "pvbMm": pvb_mm,
                "densityKgPerM3": density,
                "qty": qty,
            },
            formula_key="glass_laminated",
        )
    thk = thickness_mm if thickness_mm is not None else (layers[0] if layers else 5.0)
    return compute_weight(
        "glass",
        params={"widthMm": width_mm, "heightMm": height_mm, "thicknessMm": thk, "densityKgPerM3": density, "qty": qty},
        formula_key="glass",
    )


def seed_formula_memory(*, approved_by: str = "system_default", force: bool = False) -> dict[str, Any]:
    """Preload baseline weight formulas into Formula Memory as approved defaults.

    Idempotent: guarded by a sentinel so it runs once unless ``force`` is set.
    These are editable + versionable like any Formula Memory object; production
    products are never modified here.
    """
    from WEOS.memory.schemas import MEM_FORMULA, empty_formula_memory
    from WEOS.memory.store import get_store, memory_dir

    sentinel = memory_dir(MEM_FORMULA) / "_seeded_defaults.json"
    if sentinel.is_file() and not force:
        try:
            return json.loads(sentinel.read_text(encoding="utf-8"))
        except Exception:
            pass

    store = get_store()
    seeded: list[str] = []
    for fx in list_baseline_formulas():
        fid = str(fx.get("id") or f"fx_{fx.get('key')}")
        shell = empty_formula_memory()
        shell.update(
            {
                "id": fid,
                "name": fx.get("name"),
                "category": fx.get("category") or "weight",
                "expression": fx.get("expression"),
                "variables": list(fx.get("variables") or []),
                "outputName": fx.get("material") or fx.get("key"),
                "unit": fx.get("unit") or "kg",
                "description": fx.get("description"),
                "defaults": fx.get("defaults") or {},
                "source": "baseline_engineering_default",
                "sourceKind": "baseline",
                "confidence": 95,
                "priority": 60,
            }
        )
        try:
            store.save(MEM_FORMULA, shell, as_approved=True, approved_by=approved_by)
            seeded.append(fid)
        except Exception:
            continue

    result = {
        "ok": True,
        "seeded": seeded,
        "count": len(seeded),
        "message": "Baseline weight formulas preloaded into Formula Memory (approved defaults, editable + versionable).",
    }
    try:
        sentinel.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result
