"""Customer-safe package quotation for WoodenMax / public calculators.

Runs the same design_cost engine, then returns only public specs + package price
(actual cost × 2 for 100% markup). Never exposes purchase rates, labour, profit,
or cost breakup. Persists an opaque quoteId so discount reopen can load selection later.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import data_dir

# Customer package = actual fabrication cost + 100% markup (= 2× cost). GST later.
PACKAGE_MARKUP_PERCENT = 100.0
DEFAULT_PRODUCT_ID = "29mm_premium"

_GLASS_MAP = {
    "5": "5mm_clear_toughened",
    "5mm": "5mm_clear_toughened",
    "5mm_clear": "5mm_clear_toughened",
    "5mm_clear_toughened": "5mm_clear_toughened",
    "6": "6mm_toughened",
    "6mm": "6mm_toughened",
    "6mm_toughened": "6mm_toughened",
    "8": "8mm_toughened",
    "8mm": "8mm_toughened",
    "8mm_toughened": "8mm_toughened",
    "10": "10mm_toughened",
    "10mm": "10mm_toughened",
    "10mm_toughened": "10mm_toughened",
}

_COLOUR_MAP = {
    "matte black": "black",
    "matt black": "black",
    "matt_black": "black",
    "matte_black": "black",
    "black": "black",
    "white": "white",
    "wood finish": "wood_oak",
    "wood_finish": "wood_oak",
    "wooden": "wood_oak",
    "wood": "wood_oak",
    "wood_oak": "wood_oak",
}

_LOCK_LABELS = {
    "single_point": "Single Point",
    "single": "Single Point",
    "multipoint": "Multipoint",
    "multi": "Multipoint",
    "multi_point": "Multipoint",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _str(v: Any) -> str:
    return str(v or "").strip()


def store_dir() -> Path:
    d = data_dir() / "public_package_quotes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _quote_path(quote_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "", quote_id or "")
    if not safe or len(safe) < 8:
        raise ValueError("invalid quoteId")
    return store_dir() / f"{safe}.json"


def new_quote_id() -> str:
    return f"pq_{secrets.token_urlsafe(12)}"


def normalize_glass(raw: Any) -> tuple[str, str]:
    key = _str(raw).lower().replace(" ", "")
    # strip trailing "clear"/"tuff" noise for map lookup
    for suffix in ("cleartuff", "cleartoughened", "toughened", "tuff", "clear"):
        if key.endswith(suffix) and key not in _GLASS_MAP:
            pass
    glass_id = _GLASS_MAP.get(key) or _GLASS_MAP.get(re.sub(r"[^0-9mm]", "", key)[:4])
    if not glass_id:
        m = re.search(r"(5|6|8|10)\s*mm", _str(raw), re.I)
        if m:
            glass_id = _GLASS_MAP.get(f"{m.group(1)}mm")
    glass_id = glass_id or "10mm_toughened"
    label = re.sub(r"_", " ", glass_id).replace("toughened", "toughened").strip()
    mm = re.search(r"(\d+)\s*mm", glass_id)
    thickness_label = f"{mm.group(1)}mm" if mm else glass_id
    return glass_id, thickness_label


def normalize_colour(raw: Any) -> tuple[str, str]:
    key = _str(raw).lower().replace("-", " ").replace("_", " ").strip()
    key_us = key.replace(" ", "_")
    colour_id = _COLOUR_MAP.get(key) or _COLOUR_MAP.get(key_us) or "black"
    labels = {"black": "Matte Black", "white": "White", "wood_oak": "Wood Finish"}
    return colour_id, labels.get(colour_id, _str(raw) or colour_id)


def normalize_lock(raw: Any) -> tuple[str, str]:
    key = _str(raw).lower().replace("-", "_").replace(" ", "_")
    if key in ("multi", "mp", "multipoint", "multi_point", "metro"):
        lock_type = "multipoint"
    else:
        lock_type = "single_point"
    return lock_type, _LOCK_LABELS.get(lock_type, lock_type)


def normalize_mesh(body: Mapping[str, Any]) -> tuple[bool, int, float]:
    """Return (mesh_enabled, mesh_shutters, track_count)."""
    mesh_raw = body.get("mesh")
    mesh_shutters = body.get("meshShutters")
    track = body.get("trackCount")
    mesh_choice = _str(body.get("meshChoice") or body.get("meshOption") or "").lower()

    if mesh_choice in ("no", "none", "no_mesh", "nomesh", "0"):
        return False, 0, float(track or 2)
    if mesh_choice in ("mesh", "mesh1", "mesh_1", "1", "yes"):
        return True, int(mesh_shutters or 1), float(track or 3)

    if mesh_shutters is not None:
        n = int(_f(mesh_shutters, 0))
        if n > 0:
            return True, n, float(track or 3)
        return False, 0, float(track or 2)

    if mesh_raw is True or str(mesh_raw).lower() in ("1", "true", "yes"):
        return True, 1, float(track or 3)
    if mesh_raw is False or str(mesh_raw).lower() in ("0", "false", "no"):
        return False, 0, float(track or 2)

    # Default demo: Mesh 1 on 3-track
    return True, 1, float(track or 3)


def _pick_lock_from_product(product: Mapping[str, Any], lock_type: str) -> dict[str, Any]:
    """Resolve lock rate/brand from series hardware list (no rates returned publicly)."""
    setup = product.get("setup") if isinstance(product.get("setup"), Mapping) else {}
    sliding = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else {}
    pack = sliding.get("hardwarePack") if isinstance(sliding.get("hardwarePack"), Mapping) else {}
    base = dict(pack.get("lock") or {}) if isinstance(pack.get("lock"), Mapping) else {}
    hw_list = sliding.get("hardware") if isinstance(sliding.get("hardware"), list) else []
    derived = ((setup.get("derived") or {}).get("hardware") if isinstance(setup.get("derived"), Mapping) else None) or []
    items = [h for h in list(hw_list) + list(derived) if isinstance(h, Mapping)]

    pick = None
    if lock_type == "multipoint":
        for h in items:
            name = _str(h.get("name")).lower()
            if "multipoint" in name and "mesh" not in name and "premium" not in name:
                pick = h
                break
        if pick is None:
            for h in items:
                name = _str(h.get("name")).lower()
                if "multipoint" in name and "mesh" not in name:
                    pick = h
                    break
    else:
        for h in items:
            name = _str(h.get("name")).lower()
            if "single" in name and "lock" in name and "mesh" not in name:
                pick = h
                break
        if pick is None:
            for h in items:
                name = _str(h.get("name")).lower()
                if "single" in name and "point" in name:
                    pick = h
                    break

    out = {
        "type": lock_type,
        "rate": _f(base.get("rate"), 450.0),
        "unit": _str(base.get("unit") or "SET") or "SET",
        "brand": _str(base.get("brand") or "HIVIC") or "HIVIC",
        "origin": _str(base.get("origin") or "indian") or "indian",
        "name": "Single point lock" if lock_type == "single_point" else "Multipoint lock",
        "notes": _str(base.get("notes")),
    }
    if pick:
        out["rate"] = _f(pick.get("rate"), out["rate"])
        out["unit"] = _str(pick.get("unit") or out["unit"]) or out["unit"]
        out["brand"] = _str(pick.get("brand") or out["brand"]) or out["brand"]
        out["name"] = _str(pick.get("name") or out["name"])
    return out


def _apply_lock_override(product: Mapping[str, Any], lock_type: str) -> Mapping[str, Any]:
    import copy

    prod = copy.deepcopy(dict(product))
    setup = prod.get("setup") if isinstance(prod.get("setup"), Mapping) else {}
    sliding = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else {}
    pack = dict(sliding.get("hardwarePack") or {}) if isinstance(sliding.get("hardwarePack"), Mapping) else {}
    pack["lock"] = _pick_lock_from_product(prod, lock_type)
    sliding["hardwarePack"] = pack
    setup["sliding"] = sliding
    prod["setup"] = setup
    return prod


def _render_preview(line: Mapping[str, Any], product: Mapping[str, Any]) -> dict[str, Any]:
    from WEOS.factory.layout_options import resolve_mesh_track
    from WEOS.factory.mesh_addon import is_addon_mesh
    from WEOS.factory.pipeline import generate_job
    from WEOS.factory.product_loader import resolve_engine_product_id
    from WEOS.factory.svg_export import layout_summary_for_job, render_svg_string

    product_id = _str(line.get("product") or product.get("id") or DEFAULT_PRODUCT_ID)
    mesh = bool(line.get("mesh"))
    addon = is_addon_mesh(line)
    sash_mesh = mesh and not addon
    section_series = line.get("sectionSeries") or product.get("sectionSeries") or product_id
    series_doc = None
    try:
        from WEOS.factory.section_catalogue import get_series

        series_doc = get_series(str(section_series))
    except Exception:
        series_doc = None
    mesh_res = resolve_mesh_track(mesh=sash_mesh, track_count=line.get("trackCount"), series=series_doc)

    engine_ids = [product_id]
    linked = resolve_engine_product_id(product, product_id)
    if linked and linked not in engine_ids:
        engine_ids.append(linked)
    if "29mm_sliding" not in engine_ids:
        engine_ids.append("29mm_sliding")

    job = None
    last_exc: Exception | None = None
    for engine_id in engine_ids:
        try:
            job = generate_job(
                float(line["width"]),
                float(line["height"]),
                engine_id,
                glass=_str(line.get("glass") or "10mm_toughened"),
                colour=_str(line.get("colour") or "black"),
                handle="standard",
                mesh=sash_mesh,
                track_count=mesh_res["trackCount"],
                section_series=section_series,
                glass_count=int(line.get("glassShutters") or 2),
                mesh_count=0 if addon else int(line.get("meshShutters") or 0),
                system="sliding",
            )
            break
        except Exception as exc:
            last_exc = exc
            job = None
    if job is None:
        return {"svg": None, "error": str(last_exc or "preview failed"), "trackCount": mesh_res.get("trackCount")}

    colour_raw = _str(line.get("colour") or "black")
    svg = render_svg_string(
        job.drawing,
        colour=colour_raw.lower().replace(" ", "_"),
        annotations=True,
        include_plan=True,
    )
    layout = layout_summary_for_job(
        width=float(line["width"]),
        height=float(line["height"]),
        layout_meta=job.layout_meta,
    )
    return {
        "svg": svg,
        "layout": layout,
        "trackCount": mesh_res.get("trackCount"),
        "system": job.layout_meta.get("system") or "sliding",
        "glassShutters": job.layout_meta.get("glass_count") or line.get("glassShutters"),
        "meshShutters": job.layout_meta.get("mesh_count"),
    }


def _hardware_brand_public(product: Mapping[str, Any], lock: Mapping[str, Any]) -> str:
    specs = product.get("specifications") if isinstance(product.get("specifications"), Mapping) else {}
    return _str(lock.get("brand") or specs.get("hardwareBrand") or "HIVIC") or "HIVIC"


def _save_record(quote_id: str, record: Mapping[str, Any]) -> None:
    path = _quote_path(quote_id)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_package_quote(quote_id: str) -> dict[str, Any] | None:
    try:
        path = _quote_path(quote_id)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def build_public_package_quote(body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Compute customer package quote + SVG. Strips all internal cost fields."""
    from WEOS.factory.design_cost import compute_design_cost
    from WEOS.factory.product_loader import load_product

    body = body if isinstance(body, Mapping) else {}
    product_id = _str(body.get("product") or body.get("productId") or DEFAULT_PRODUCT_ID) or DEFAULT_PRODUCT_ID
    width = _f(body.get("width"), 1500)
    height = _f(body.get("height"), 1200)
    qty = max(int(_f(body.get("qty") or body.get("quantity"), 1)), 1)
    if width <= 0 or height <= 0:
        return {"ok": False, "error": "width and height must be > 0"}

    glass_id, glass_label = normalize_glass(body.get("glass") or body.get("glassThickness") or "10mm")
    colour_id, colour_label = normalize_colour(body.get("colour") or body.get("color") or body.get("frameColour") or "Matte Black")
    lock_type, lock_label = normalize_lock(body.get("locking") or body.get("lock") or body.get("lockType") or "multipoint")
    mesh_on, mesh_n, track_count = normalize_mesh(body)
    glass_shutters = int(_f(body.get("glassShutters"), 2) or 2)

    try:
        product = load_product(product_id, strict=False)
    except FileNotFoundError:
        return {"ok": False, "error": f"product not found: {product_id}"}

    product = _apply_lock_override(product, lock_type)
    lock_pack = ((product.get("setup") or {}).get("sliding") or {}).get("hardwarePack", {}).get("lock") or {}

    line = {
        "product": product_id,
        "width": width,
        "height": height,
        "qty": qty,
        "glass": glass_id,
        "colour": colour_id,
        "mesh": mesh_on,
        "meshShutters": mesh_n if mesh_on else 0,
        "glassShutters": glass_shutters,
        "trackCount": track_count,
        "sectionSeries": product.get("sectionSeries") or product_id,
        "productType": product.get("productType") or "sliding",
        "system": "sliding",
        "lockType": lock_type,
        "options": {
            "glass": glass_id,
            "colour": colour_id,
            "mesh": mesh_on,
            "meshShutters": mesh_n if mesh_on else 0,
            "trackCount": track_count,
            "lockType": lock_type,
        },
    }

    design = compute_design_cost(line, product=product)
    if not isinstance(design, Mapping) or not design.get("ok"):
        return {
            "ok": False,
            "error": _str((design or {}).get("reason") or "design_cost failed"),
            "product": product_id,
        }

    unit_cost = _f(design.get("unitTotal") or design.get("perWindowCost") or design.get("total"))
    # design.total is usually qty-aware; prefer per-window then × qty
    per_window_cost = _f(design.get("perWindowCost") or design.get("unitTotal") or (unit_cost / max(qty, 1)))
    cost_total = _f(design.get("total"))
    if cost_total <= 0:
        cost_total = per_window_cost * qty
    if per_window_cost <= 0 and qty > 0:
        per_window_cost = cost_total / qty

    markup_mult = 1.0 + (PACKAGE_MARKUP_PERCENT / 100.0)
    package_unit = round(per_window_cost * markup_mult, 2)
    package_total = round(cost_total * markup_mult, 2)

    area_sqft = round((width / 1000.0) * (height / 1000.0) * 10.7639, 4)
    preview = _render_preview(line, product)
    hw_brand = _hardware_brand_public(product, lock_pack if isinstance(lock_pack, Mapping) else {})

    quote_id = _str(body.get("quoteId")) or new_quote_id()
    # Reuse prior id only if it already exists or client asks to refresh
    if body.get("quoteId"):
        try:
            _quote_path(quote_id)
        except ValueError:
            quote_id = new_quote_id()

    selection = {
        "product": product_id,
        "productName": _str(product.get("displayName") or "29mm SERIES Premium"),
        "widthMm": width,
        "heightMm": height,
        "qty": qty,
        "trackCount": track_count,
        "mesh": mesh_on,
        "meshShutters": mesh_n if mesh_on else 0,
        "glassShutters": glass_shutters,
        "glass": glass_id,
        "glassLabel": glass_label,
        "locking": lock_type,
        "lockingLabel": lock_label,
        "colour": colour_id,
        "colourLabel": colour_label,
        "hardwareBrand": hw_brand,
        "areaSqft": area_sqft,
    }

    public = {
        "ok": True,
        "quoteId": quote_id,
        "product": product_id,
        "productName": selection["productName"],
        "widthMm": width,
        "heightMm": height,
        "qty": qty,
        "trackCount": track_count,
        "shutters": {
            "glass": glass_shutters,
            "mesh": mesh_n if mesh_on else 0,
        },
        "mesh": mesh_on,
        "meshLabel": f"Mesh {mesh_n}" if mesh_on and mesh_n else "No Mesh",
        "glass": glass_id,
        "glassLabel": glass_label,
        "locking": lock_type,
        "lockingLabel": lock_label,
        "finish": colour_id,
        "finishLabel": colour_label,
        "hardwareBrand": hw_brand,
        "areaSqft": area_sqft,
        "currency": "INR",
        "packagePrice": package_total,
        "packagePricePerUnit": package_unit,
        "packagePriceLabel": "Total Package Price",
        "markupPercent": PACKAGE_MARKUP_PERCENT,
        "gstNote": "GST extra as applicable (via quote settings)",
        "preview": {
            "svg": preview.get("svg"),
            "layout": preview.get("layout"),
            "system": preview.get("system"),
            "trackCount": preview.get("trackCount"),
        },
        "selection": selection,
        "updatedAt": _now(),
    }

    # Persist selection + package totals only (no cost breakup / rates)
    _save_record(
        quote_id,
        {
            "quoteId": quote_id,
            "createdAt": _now(),
            "updatedAt": _now(),
            "source": _str(body.get("source") or "woodenmax"),
            "selection": selection,
            "packagePrice": package_total,
            "packagePricePerUnit": package_unit,
            "currency": "INR",
            # Internal stub for future discount simulator (not returned on public GET)
            "_internal": {
                "actualCost": round(cost_total, 2),
                "actualCostPerUnit": round(per_window_cost, 2),
                "markupPercent": PACKAGE_MARKUP_PERCENT,
                "costEngine": design.get("costEngine"),
                "savedAt": time.time(),
            },
        },
    )
    return public


def get_public_package_quote(quote_id: str, *, include_preview: bool = False) -> dict[str, Any] | None:
    rec = load_package_quote(quote_id)
    if not rec:
        return None
    selection = rec.get("selection") if isinstance(rec.get("selection"), Mapping) else {}
    out = {
        "ok": True,
        "quoteId": rec.get("quoteId") or quote_id,
        "product": selection.get("product"),
        "productName": selection.get("productName"),
        "widthMm": selection.get("widthMm"),
        "heightMm": selection.get("heightMm"),
        "qty": selection.get("qty"),
        "trackCount": selection.get("trackCount"),
        "mesh": selection.get("mesh"),
        "meshLabel": f"Mesh {selection.get('meshShutters')}" if selection.get("mesh") else "No Mesh",
        "glass": selection.get("glass"),
        "glassLabel": selection.get("glassLabel"),
        "locking": selection.get("locking"),
        "lockingLabel": selection.get("lockingLabel"),
        "finish": selection.get("colour"),
        "finishLabel": selection.get("colourLabel"),
        "hardwareBrand": selection.get("hardwareBrand"),
        "areaSqft": selection.get("areaSqft"),
        "currency": rec.get("currency") or "INR",
        "packagePrice": rec.get("packagePrice"),
        "packagePricePerUnit": rec.get("packagePricePerUnit"),
        "packagePriceLabel": "Total Package Price",
        "gstNote": "GST extra as applicable (via quote settings)",
        "selection": selection,
        "updatedAt": rec.get("updatedAt"),
    }
    if include_preview and selection:
        rebuilt = build_public_package_quote({**selection, "quoteId": quote_id, "colour": selection.get("colour"), "locking": selection.get("locking"), "glass": selection.get("glass"), "width": selection.get("widthMm"), "height": selection.get("heightMm"), "mesh": selection.get("mesh"), "meshShutters": selection.get("meshShutters"), "trackCount": selection.get("trackCount"), "qty": selection.get("qty")})
        if rebuilt.get("ok"):
            out["preview"] = rebuilt.get("preview")
            out["packagePrice"] = rebuilt.get("packagePrice")
            out["packagePricePerUnit"] = rebuilt.get("packagePricePerUnit")
    return out
