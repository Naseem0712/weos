"""PDF Template store — JSON layouts per brand (WoodenMax / AllKraft)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import PACKAGE_ROOT, data_dir

PACKAGE_TEMPLATES = PACKAGE_ROOT / "templates"
BRANDS = ("woodenmax", "allkraft", "marqt")
KINDS = ("customer", "factory")


def templates_dir() -> Path:
    """Writable templates root (data dir) with package fallback for seeds."""
    d = data_dir() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _seed_defaults() -> None:
    """Ensure default brand templates exist in writable dir (copy from package or create)."""
    for brand in BRANDS:
        for kind in KINDS:
            tid = f"{brand}_{kind}"
            dest = templates_dir() / f"{tid}.json"
            if dest.is_file():
                continue
            pkg = PACKAGE_TEMPLATES / f"{tid}.json"
            if pkg.is_file():
                dest.write_text(pkg.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                dest.write_text(json.dumps(default_template(brand, kind), indent=2) + "\n", encoding="utf-8")


def default_template(brand: str, kind: str) -> dict[str, Any]:
    brand = brand.lower()
    company = {"woodenmax": "WoodenMax", "allkraft": "AllKraft", "marqt": "WEOS Windows"}.get(brand, brand.title())
    colors = {
        "woodenmax": {"primary": [0.04, 0.35, 0.28], "accent": [0.71, 0.33, 0.14]},
        "allkraft": {"primary": [0.12, 0.22, 0.45], "accent": [0.85, 0.55, 0.12]},
        "marqt": {"primary": [0.12, 0.22, 0.38], "accent": [0.75, 0.15, 0.12]},
    }
    c = colors.get(brand, colors["woodenmax"])
    if brand == "marqt" and kind == "customer":
        pkg = PACKAGE_TEMPLATES / "marqt_customer.json"
        if pkg.is_file():
            import json as _json

            return _json.loads(pkg.read_text(encoding="utf-8-sig"))
    if kind == "factory":
        blocks = [
            {"id": "logo", "type": "logo", "x": 40, "y": 40, "w": 160, "h": 36, "label": company},
            {"id": "title", "type": "title", "x": 40, "y": 90, "w": 400, "h": 28, "text": "Factory Production Package"},
            {"id": "qr", "type": "qr", "x": 480, "y": 40, "w": 70, "h": 70},
            {"id": "meta", "type": "customer_details", "x": 40, "y": 130, "w": 400, "h": 60},
            {"id": "glass", "type": "glass_table", "x": 40, "y": 210, "w": 515, "h": 160},
            {"id": "hardware", "type": "hardware_table", "x": 40, "y": 390, "w": 515, "h": 140},
            {"id": "cutlist", "type": "cutlist_table", "x": 40, "y": 550, "w": 515, "h": 160},
            {"id": "footer", "type": "footer", "x": 40, "y": 780, "w": 515, "h": 24, "text": f"{company} Factory — machine-ready data"},
        ]
    else:
        blocks = [
            {"id": "logo", "type": "logo", "x": 40, "y": 40, "w": 180, "h": 40, "label": company},
            {"id": "title", "type": "title", "x": 40, "y": 95, "w": 400, "h": 28, "text": "Customer Quotation"},
            {"id": "customer", "type": "customer_details", "x": 40, "y": 140, "w": 320, "h": 70},
            {"id": "product_image", "type": "product_image", "x": 400, "y": 140, "w": 155, "h": 100},
            {"id": "prices", "type": "price_table", "x": 40, "y": 260, "w": 515, "h": 280},
            {"id": "totals", "type": "totals", "x": 300, "y": 560, "w": 255, "h": 80},
            {"id": "terms", "type": "terms", "x": 40, "y": 660, "w": 515, "h": 80,
             "text": "Terms: 50% advance, balance before dispatch. Rates excl. site installation unless noted. Warranty: 1 year manufacturing defects."},
            {"id": "footer", "type": "footer", "x": 40, "y": 780, "w": 515, "h": 24,
             "text": f"{company} · Powered by WEOS"},
        ]
    return {
        "id": f"{brand}_{kind}",
        "brand": brand,
        "kind": kind,
        "name": f"{company} {kind.title()} PDF",
        "pageSize": "A4",
        "branding": {
            "companyName": company,
            "tagline": "Design • Calculate • Manufacture • Quote",
            "primaryColor": c["primary"],
            "accentColor": c["accent"],
            "logoText": company,
        },
        "blocks": blocks,
    }


def list_templates(*, brand: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    _seed_defaults()
    out: list[dict[str, Any]] = []
    for path in sorted(templates_dir().glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if brand and str(doc.get("brand", "")).lower() != brand.lower():
            continue
        if kind and str(doc.get("kind", "")).lower() != kind.lower():
            continue
        out.append({
            "id": doc.get("id", path.stem),
            "name": doc.get("name", path.stem),
            "brand": doc.get("brand"),
            "kind": doc.get("kind"),
            "pageSize": doc.get("pageSize", "A4"),
            "blockCount": len(doc.get("blocks") or []),
        })
    return out


def load_template(template_id: str) -> dict[str, Any]:
    _seed_defaults()
    path = templates_dir() / f"{template_id.replace('.json', '')}.json"
    if not path.is_file():
        # try package
        pkg = PACKAGE_TEMPLATES / path.name
        if pkg.is_file():
            return json.loads(pkg.read_text(encoding="utf-8-sig"))
        raise FileNotFoundError(f"Template '{template_id}' not found")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_template(template_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    _seed_defaults()
    tid = template_id.replace(".json", "")
    doc = copy.deepcopy(dict(payload))
    doc["id"] = tid
    doc.setdefault("brand", tid.split("_")[0] if "_" in tid else "woodenmax")
    doc.setdefault("kind", "customer" if "customer" in tid else "factory")
    doc.setdefault("pageSize", "A4")
    doc.setdefault("blocks", [])
    path = templates_dir() / f"{tid}.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # also mirror into package templates for git-tracked defaults when writable
    try:
        PACKAGE_TEMPLATES.mkdir(parents=True, exist_ok=True)
        (PACKAGE_TEMPLATES / f"{tid}.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass
    return load_template(tid)


def create_template(payload: Mapping[str, Any]) -> dict[str, Any]:
    brand = str(payload.get("brand") or "woodenmax").lower()
    kind = str(payload.get("kind") or "customer").lower()
    tid = str(payload.get("id") or f"{brand}_{kind}")
    base = default_template(brand, kind)
    base.update({k: v for k, v in payload.items() if k != "id"})
    base["id"] = tid
    return save_template(tid, base)


def delete_template(template_id: str) -> dict[str, Any]:
    path = templates_dir() / f"{template_id.replace('.json', '')}.json"
    if path.is_file():
        path.unlink()
    return {"deleted": template_id}


def resolve_template_id(
    *,
    kind: str = "customer",
    brand: str | None = None,
    template_id: str | None = None,
    product_pdf_layout: Mapping[str, Any] | None = None,
) -> str:
    if template_id:
        return template_id.replace(".json", "")
    layout = product_pdf_layout or {}
    if kind in layout and layout[kind]:
        return str(layout[kind])
    b = (brand or ("marqt" if kind == "customer" else "woodenmax")).lower()
    return f"{b}_{kind}"
