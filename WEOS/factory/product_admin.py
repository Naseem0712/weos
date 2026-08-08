"""Product Library admin — CRUD for catalogue + materials + formula rules (JSON only)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Mapping

from WEOS.factory.formula import MATERIAL_UNITS, validate_formula
from WEOS.factory.product_loader import RULE_FILES, load_product, product_dir
from WEOS.paths import products_dir

PRODUCTS_DIR = products_dir()

_META_KEYS = {
    "id", "displayName", "productType", "category", "units", "version", "status",
    "description", "tagline", "warranty", "heroImage", "gallery", "sectionDrawings",
    "specifications", "materials", "formulas", "pdfLayout", "brand", "engineeringRules",
    "glassRules", "hardwareRules", "weightRules", "pricingRules",
    "catalogue", "sectionSeries", "linkedProductId",
}


def _slug(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip().lower()).strip("_")
    return s or "product"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def get_admin_product(product_id: str) -> dict[str, Any]:
    """Full editable product document for admin UI."""
    doc = load_product(product_id, strict=False)
    pdir = Path(doc.get("_product_dir") or product_dir(product_id))
    meta_path = pdir / "product.json"
    meta = _read_json(meta_path) if meta_path.is_file() else {"id": product_id}

    materials = meta.get("materials") or doc.get("materials") or []
    # Seed materials from hardware rules when empty
    if not materials and isinstance(doc.get("hardware"), list):
        materials = [
            {
                "id": _slug(str(h.get("part", f"hw_{i}"))),
                "name": h.get("part"),
                "category": h.get("category") or "hardware",
                "unit": str(h.get("unit", "PC")).upper().replace("PCS", "PC").replace("M", "RM") if h.get("unit") != "pcs" else "PC",
                "quantityFormula": h.get("quantityFormula", "1"),
                "lengthFormula": h.get("lengthFormula", "0"),
                "unitRate": h.get("unitRate", 0),
                "remarks": h.get("remarks", ""),
                "optionKey": h.get("optionKey"),
                "variants": h.get("variants"),
            }
            for i, h in enumerate(doc.get("hardware") or [])
        ]

    return {
        "id": meta.get("id", product_id),
        "displayName": meta.get("displayName", product_id),
        "productType": meta.get("productType"),
        "category": meta.get("category", "Windows"),
        "units": meta.get("units", "mm"),
        "version": meta.get("version", 1),
        "status": meta.get("status", "active"),
        "description": meta.get("description", ""),
        "tagline": meta.get("tagline", ""),
        "warranty": meta.get("warranty", ""),
        "heroImage": meta.get("heroImage"),
        "gallery": meta.get("gallery") or [],
        "sectionDrawings": meta.get("sectionDrawings") or [],
        "specifications": meta.get("specifications") or {},
        "materials": materials,
        "formulas": meta.get("formulas") or {},
        "pdfLayout": meta.get("pdfLayout") or {},
        "brand": meta.get("brand", "woodenmax"),
        "catalogue": meta.get("catalogue") or {},
        "sectionSeries": meta.get("sectionSeries"),
        "linkedProductId": meta.get("linkedProductId"),
        "materialUnits": list(MATERIAL_UNITS),
        "rules": {
            "geometry": doc.get("geometry"),
            "glass": doc.get("glass"),
            "hardware": doc.get("hardware"),
            "brush": doc.get("brush"),
            "trackRail": doc.get("trackRail"),
            "cutList": doc.get("cutList"),
            "weight": doc.get("weight"),
            "quotation": doc.get("quotation"),
            "dimensioning": doc.get("dimensioning"),
            "bomExtras": doc.get("bomExtras"),
            "pricing": doc.get("pricing"),
        },
        "manufacturingReady": not (doc.get("_stub") or meta.get("status") == "stub"),
        "_path": str(pdir),
    }


def create_product(payload: Mapping[str, Any]) -> dict[str, Any]:
    pid = _slug(str(payload.get("id") or payload.get("displayName") or "new_product"))
    target = PRODUCTS_DIR / pid
    if target.exists():
        raise FileExistsError(f"Product '{pid}' already exists")
    target.mkdir(parents=True)
    (target / "rules").mkdir(exist_ok=True)

    meta = {
        "id": pid,
        "displayName": payload.get("displayName") or pid,
        "productType": payload.get("productType") or "custom",
        "category": payload.get("category") or "Windows",
        "units": payload.get("units") or "mm",
        "version": int(payload.get("version") or 1),
        "status": payload.get("status") or "stub",
        "description": payload.get("description") or "",
        "tagline": payload.get("tagline") or "",
        "warranty": payload.get("warranty") or "",
        "heroImage": payload.get("heroImage") or "/static/products/placeholder.svg",
        "gallery": list(payload.get("gallery") or []),
        "sectionDrawings": list(payload.get("sectionDrawings") or []),
        "specifications": dict(payload.get("specifications") or {}),
        "materials": list(payload.get("materials") or []),
        "formulas": dict(payload.get("formulas") or {}),
        "pdfLayout": dict(payload.get("pdfLayout") or {"customer": "woodenmax_customer", "factory": "woodenmax_factory"}),
        "brand": payload.get("brand") or "woodenmax",
        "catalogue": dict(payload.get("catalogue") or {}),
    }
    _write_json(target / "product.json", meta)

    # Minimal stub quotation so catalogue quotes work
    if payload.get("status", "stub") == "stub" or not (target / "rules" / "quotation.json").is_file():
        _write_json(
            target / "rules" / "quotation.json",
            {
                "currency": "INR",
                "labourPerOpening": 0,
                "markupPercent": 15,
                "gstPercent": 18,
                "stub": True,
                "manualRatePerOpening": float(payload.get("manualRatePerOpening") or 0),
                "rates": {},
            },
        )
    return get_admin_product(pid)


def update_product(product_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    pdir = product_dir(product_id)
    meta_path = pdir / "product.json"
    meta = _read_json(meta_path) if meta_path.is_file() else {"id": product_id}

    for key in (
        "displayName", "productType", "category", "units", "version", "status",
        "description", "tagline", "warranty", "heroImage", "gallery", "sectionDrawings",
        "specifications", "materials", "formulas", "pdfLayout", "brand",
        "catalogue", "sectionSeries", "linkedProductId",
    ):
        if key in payload:
            meta[key] = copy.deepcopy(payload[key])

    # Validate material formulas
    issues: list[str] = []
    for i, mat in enumerate(meta.get("materials") or []):
        for field in ("quantityFormula", "lengthFormula", "weightFormula"):
            if mat.get(field) in (None, ""):
                continue
            check = validate_formula(mat[field])
            if not check["ok"]:
                issues.append(f"materials[{i}].{field}: {check['error']}")
    if issues:
        raise ValueError("; ".join(issues))

    meta["version"] = int(meta.get("version") or 1) + (1 if payload.get("bumpVersion", True) else 0)
    _write_json(meta_path, meta)

    # Optional rules patch
    rules = payload.get("rules")
    if isinstance(rules, Mapping):
        rules_dir = pdir / "rules"
        rules_dir.mkdir(exist_ok=True)
        reverse = {v: k for k, v in RULE_FILES.items()}
        for section, data in rules.items():
            if data is None:
                continue
            stem = reverse.get(section, section)
            # map camel section names to file stems
            file_stem = {
                "geometry": "geometry", "glass": "glass", "hardware": "hardware",
                "brush": "brush", "trackRail": "track_rail", "cutList": "cutlist",
                "weight": "weight", "quotation": "quotation", "dimensioning": "dimensioning",
                "bomExtras": "bom_extras", "pricing": "pricing",
            }.get(section, stem)
            _write_json(rules_dir / f"{file_stem}.json", data)

    # Sync hardware.json from materials when requested or when materials present and syncHardware
    if payload.get("syncHardware", True) and meta.get("materials"):
        from WEOS.factory.materials_engine import materials_to_hardware_rules

        hw = materials_to_hardware_rules(meta["materials"])
        if hw:
            _write_json(pdir / "rules" / "hardware.json", hw)

    return get_admin_product(product_id)


def delete_product(product_id: str, *, hard: bool = False) -> dict[str, Any]:
    pdir = product_dir(product_id)
    if product_id == "29mm_sliding" and not hard:
        raise ValueError("Cannot delete core product 29mm_sliding without hard=true")
    meta_path = pdir / "product.json"
    if hard:
        import shutil

        shutil.rmtree(pdir)
        return {"deleted": product_id, "hard": True}
    meta = _read_json(meta_path) if meta_path.is_file() else {"id": product_id}
    meta["status"] = "archived"
    _write_json(meta_path, meta)
    return {"deleted": product_id, "hard": False, "status": "archived"}
