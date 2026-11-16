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
    "12": "12mm_toughened",
    "12mm": "12mm_toughened",
    "12mm_toughened": "12mm_toughened",
}

# 3-track page: DGU overall ≤22 mm; laminated overall ≤13.52 mm.
PUBLIC_DGU_MAX_MM = 22.0
PUBLIC_LAM_MAX_MM = 13.52

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


def _glass_label_from_spec(glass_id: str, spec: Mapping[str, Any] | None = None) -> str:
    if isinstance(spec, Mapping):
        for key in ("display_label", "name", "label", "specLine", "makeupLabel"):
            val = _str(spec.get(key))
            if val:
                return val
    return re.sub(r"_+", " ", glass_id).strip()


def _lookup_glass_spec(glass_id: str) -> dict[str, Any] | None:
    gid = _str(glass_id)
    if not gid:
        return None
    try:
        from WEOS.factory.glass_catalogue import get_glass

        return get_glass(gid)
    except Exception:
        pass
    try:
        from WEOS.factory.glass_catalogue import cart_glass_options

        for opt in cart_glass_options(merge_library=True):
            if str(opt.get("id") or "") == gid:
                return dict(opt)
    except Exception:
        pass
    return None


def normalize_glass(raw: Any) -> tuple[str, str]:
    """Resolve single / DGU / laminated catalogue ids (never force unknown packs → 10mm)."""
    raw_s = _str(raw)
    key = raw_s.lower().replace(" ", "").replace("-", "_")
    glass_id: str | None = None

    if key in _GLASS_MAP:
        glass_id = _GLASS_MAP[key]
    elif key.startswith(("dgu_", "lam_")) or re.match(
        r"^\d+mm_(clear_)?(black_|grey_|brown_)?toughened$", key
    ):
        glass_id = key
    else:
        compact = re.sub(r"[^0-9mm]", "", key)
        glass_id = _GLASS_MAP.get(compact) or _GLASS_MAP.get(compact[:4] if len(compact) >= 3 else "")
        if not glass_id:
            m = re.search(r"(5|6|8|10|12)\s*mm", raw_s, re.I)
            if m:
                glass_id = _GLASS_MAP.get(f"{m.group(1)}mm")

    glass_id = glass_id or "10mm_toughened"
    spec = _lookup_glass_spec(glass_id)
    if spec is None and glass_id not in _GLASS_MAP.values():
        # Unknown catalogue id → fall back to 10mm rather than silently mis-price as 10mm via map bug;
        # keep id if it looks like a single thickness we can still cost.
        m = re.search(r"(5|6|8|10|12)", glass_id)
        if glass_id.startswith(("dgu_", "lam_")):
            glass_id = "10mm_toughened"
            spec = _lookup_glass_spec(glass_id)
        elif m and f"{m.group(1)}mm" in _GLASS_MAP:
            glass_id = _GLASS_MAP[f"{m.group(1)}mm"]
            spec = _lookup_glass_spec(glass_id)

    label = _glass_label_from_spec(glass_id, spec)
    return glass_id, label


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
    """Legacy helper — prefer :func:`normalize_shutter_config` for 3-track rules."""
    cfg = normalize_shutter_config(body)
    return bool(cfg["mesh"]), int(cfg["meshShutters"]), float(cfg["trackCount"])


def normalize_shutter_config(body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Shutter / track rules for the WoodenMax 3-track package calculator.

    Correct mapping:
      - **3 glass** → side opening, mesh off, **3-track**
      - **4 glass + mesh** → center opening, meshShutters=2, stay on **3-track**
        (track layout: line1=2 glass, line2=2 glass, line3=both mesh inside)
      - **4-track** only when **side opening + 4 glass** and **no mesh**
        (WM UI does not offer this; honour if caller asks explicitly)

    Never bump 4-glass+mesh to 4-track — that mismatches WeOS cart preview.
    """
    body = body if isinstance(body, Mapping) else {}
    try:
        glass = int(round(_f(body.get("glassShutters") or body.get("glassCount"), 3)))
    except (TypeError, ValueError):
        glass = 3
    if glass not in (3, 4):
        glass = 4 if glass >= 4 else 3

    mesh_choice = _str(body.get("meshChoice") or body.get("meshOption") or "").lower()
    mesh_raw = body.get("mesh")
    mesh_shutters_raw = body.get("meshShutters")
    opening_raw = _str(body.get("opening") or "").lower().replace("-", "_").replace(" ", "_")

    mesh_on = False
    if mesh_choice in ("no", "none", "no_mesh", "nomesh", "0"):
        mesh_on = False
    elif mesh_choice in ("mesh", "mesh1", "mesh_1", "mesh2", "mesh_2", "1", "2", "yes"):
        mesh_on = True
    elif mesh_shutters_raw is not None:
        mesh_on = int(_f(mesh_shutters_raw, 0)) > 0
    elif mesh_raw is True or str(mesh_raw).lower() in ("1", "true", "yes"):
        mesh_on = True
    elif mesh_raw is False or str(mesh_raw).lower() in ("0", "false", "no"):
        mesh_on = False

    if glass == 3:
        return {
            "glassShutters": 3,
            "mesh": False,
            "meshShutters": 0,
            "opening": "side",
            "openingLabel": "Side opening",
            "openingExplicit": True,
            "trackCount": 3.0,
            "system": "sliding",
            "meshType": None,
            "meshLabel": "No Mesh",
        }

    # 4-track ONLY: side opening + 4 glass + no mesh
    side_4track = (not mesh_on) and opening_raw in (
        "side",
        "telescopic",
        "telescope",
        "side_opening",
    )
    if side_4track:
        return {
            "glassShutters": 4,
            "mesh": False,
            "meshShutters": 0,
            "opening": "side",
            "openingLabel": "Side opening",
            "openingExplicit": True,
            "trackCount": 4.0,
            "system": "sliding",
            "meshType": None,
            "meshLabel": "No Mesh",
        }

    # Default 4 glass on this page: center on 3-track; mesh if on = exactly 2
    mesh_n = 2 if mesh_on else 0
    return {
        "glassShutters": 4,
        "mesh": bool(mesh_n),
        "meshShutters": mesh_n,
        "opening": "center",
        "openingLabel": "Center opening",
        "openingExplicit": True,
        "trackCount": 3.0,
        "system": "sliding",
        "meshType": "standard" if mesh_n else None,
        "meshLabel": f"Mesh {mesh_n}" if mesh_n else "No Mesh",
    }


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
            opening_raw = _str(line.get("opening") or "side")
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
                opening=opening_raw,
                opening_explicit=bool(line.get("openingExplicit", True)),
                system=_str(line.get("system") or "sliding") or "sliding",
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
    shutters = normalize_shutter_config(body)
    mesh_on = bool(shutters["mesh"])
    mesh_n = int(shutters["meshShutters"])
    track_count = float(shutters["trackCount"])
    glass_shutters = int(shutters["glassShutters"])
    opening = _str(shutters.get("opening") or "side")
    opening_label = _str(shutters.get("openingLabel") or opening)
    mesh_label = _str(shutters.get("meshLabel") or ("No Mesh" if not mesh_on else f"Mesh {mesh_n}"))

    try:
        product = load_product(product_id, strict=False)
    except FileNotFoundError:
        return {"ok": False, "error": f"product not found: {product_id}"}

    product = _apply_lock_override(product, lock_type)
    lock_pack = ((product.get("setup") or {}).get("sliding") or {}).get("hardwarePack", {}).get("lock") or {}

    mesh_type = _str(shutters.get("meshType") or body.get("meshType") or ("standard" if mesh_on else "")) or None
    line = {
        "product": product_id,
        "width": width,
        "height": height,
        "qty": qty,
        "glass": glass_id,
        "colour": colour_id,
        "mesh": mesh_on,
        "meshShutters": mesh_n if mesh_on else 0,
        "meshType": mesh_type if mesh_on else None,
        "glassShutters": glass_shutters,
        "trackCount": track_count,
        "opening": opening,
        "openingExplicit": True,
        "sectionSeries": product.get("sectionSeries") or product_id,
        "productType": product.get("productType") or "sliding",
        "system": _str(shutters.get("system") or "sliding") or "sliding",
        "lockType": lock_type,
        "options": {
            "glass": glass_id,
            "colour": colour_id,
            "mesh": mesh_on,
            "meshShutters": mesh_n if mesh_on else 0,
            "meshType": mesh_type if mesh_on else None,
            "glassShutters": glass_shutters,
            "trackCount": track_count,
            "opening": opening,
            "openingExplicit": True,
            "system": "sliding",
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
        "opening": opening,
        "openingLabel": opening_label,
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
        "glassShutters": glass_shutters,
        "meshShutters": mesh_n if mesh_on else 0,
        "opening": opening,
        "openingLabel": opening_label,
        "mesh": mesh_on,
        "meshLabel": mesh_label,
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
            "opening": opening,
            "glassShutters": glass_shutters,
            "meshShutters": mesh_n if mesh_on else 0,
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
    customer = rec.get("customer") if isinstance(rec.get("customer"), Mapping) else {}
    out = {
        "ok": True,
        "quoteId": rec.get("quoteId") or quote_id,
        "projectId": rec.get("projectId"),
        "shareToken": rec.get("shareToken"),
        "scanUrl": rec.get("scanUrl"),
        "pdfUrl": rec.get("pdfUrl"),
        "product": selection.get("product"),
        "productName": selection.get("productName"),
        "widthMm": selection.get("widthMm"),
        "heightMm": selection.get("heightMm"),
        "qty": selection.get("qty"),
        "trackCount": selection.get("trackCount"),
        "glassShutters": selection.get("glassShutters"),
        "meshShutters": selection.get("meshShutters"),
        "opening": selection.get("opening"),
        "openingLabel": selection.get("openingLabel"),
        "mesh": selection.get("mesh"),
        "meshLabel": (
            selection.get("meshLabel")
            or (f"Mesh {selection.get('meshShutters')}" if selection.get("mesh") else "No Mesh")
        ),
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
        "customer": {
            "name": customer.get("name"),
            "mobile": customer.get("mobile"),
            "address": customer.get("address"),
        } if customer else None,
        "selection": selection,
        "updatedAt": rec.get("updatedAt"),
    }
    if include_preview and selection:
        rebuilt = build_public_package_quote(
            {
                **selection,
                "quoteId": quote_id,
                "colour": selection.get("colour"),
                "locking": selection.get("locking"),
                "glass": selection.get("glass"),
                "width": selection.get("widthMm"),
                "height": selection.get("heightMm"),
                "mesh": selection.get("mesh"),
                "meshShutters": selection.get("meshShutters"),
                "glassShutters": selection.get("glassShutters"),
                "opening": selection.get("opening"),
                "trackCount": selection.get("trackCount"),
                "qty": selection.get("qty"),
            }
        )
        if rebuilt.get("ok"):
            out["preview"] = rebuilt.get("preview")
            out["packagePrice"] = rebuilt.get("packagePrice")
            out["packagePricePerUnit"] = rebuilt.get("packagePricePerUnit")
    return out


def save_public_package_quote(
    body: Mapping[str, Any] | None = None,
    *,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Persist a customer-facing WeOS project from a package quote (no cost fields returned)."""
    from WEOS.factory.project_store import empty_project, save_project
    from WEOS.factory.quote_share import ensure_project_share_token

    body = body if isinstance(body, Mapping) else {}
    quote = build_public_package_quote(body)
    if not quote.get("ok"):
        return quote

    customer_name = _str(body.get("customerName") or body.get("name") or body.get("customer") or "WoodenMax Customer")
    customer_mobile = _str(body.get("customerMobile") or body.get("mobile") or body.get("phone"))
    customer_address = _str(body.get("customerAddress") or body.get("address"))
    if not customer_mobile and not customer_name:
        return {"ok": False, "error": "customer name or mobile required"}

    area = _f(quote.get("areaSqft"), 1.0) or 1.0
    package_total = _f(quote.get("packagePrice"))
    package_unit = _f(quote.get("packagePricePerUnit"))
    selling_rate = round(package_unit / area, 2) if area else package_unit
    selection = quote.get("selection") if isinstance(quote.get("selection"), Mapping) else {}
    glass_id = _str(selection.get("glass") or quote.get("glass") or "10mm_toughened")
    colour_id = _str(selection.get("colour") or quote.get("finish") or "black")
    opening = _str(selection.get("opening") or quote.get("opening") or "side")
    glass_shutters = int(_f(selection.get("glassShutters") or quote.get("glassShutters"), 3))
    mesh_n = int(_f(selection.get("meshShutters") or quote.get("meshShutters"), 0))
    mesh_on = bool(selection.get("mesh") if selection.get("mesh") is not None else quote.get("mesh"))
    track_count = _f(selection.get("trackCount") or quote.get("trackCount"), 3)
    product_id = _str(selection.get("product") or quote.get("product") or DEFAULT_PRODUCT_ID)

    existing_pid = _str(body.get("projectId"))
    doc = None
    if existing_pid:
        try:
            from WEOS.factory.project_store import load_project

            doc = load_project(existing_pid)
        except Exception:
            doc = None
    if not isinstance(doc, dict):
        doc = empty_project(
            name=_str(body.get("projectName") or f"Package · {quote.get('productName') or '29mm'}"),
            customer=customer_name,
        )
    doc["customer"] = customer_name
    doc["customerMobile"] = customer_mobile
    doc["customerAddress"] = customer_address
    doc["status"] = "draft"
    doc["source"] = _str(body.get("source") or "woodenmax-public")
    doc["packageQuoteId"] = quote.get("quoteId")
    doc["description"] = _str(
        body.get("description")
        or (
            f"WoodenMax package quote · {quote.get('widthMm')}×{quote.get('heightMm')} mm · "
            f"{glass_shutters} glass · {quote.get('glassLabel')} · {quote.get('finishLabel')}"
        )
    )
    line = {
        "lineId": "pkg1",
        "product": product_id,
        "width": quote.get("widthMm"),
        "height": quote.get("heightMm"),
        "qty": quote.get("qty") or 1,
        "glass": glass_id,
        "colour": colour_id,
        "mesh": mesh_on,
        "meshShutters": mesh_n,
        "glassShutters": glass_shutters,
        "trackCount": track_count,
        "opening": opening,
        "openingExplicit": True,
        "system": "sliding",
        "productType": "sliding",
        "sectionSeries": product_id,
        "lockType": selection.get("locking") or quote.get("locking"),
        "sellingRate": selling_rate,
        "saleUnit": "sqft",
        "windowAmount": package_total,
        "options": {
            "glass": glass_id,
            "colour": colour_id,
            "mesh": mesh_on,
            "meshShutters": mesh_n,
            "glassShutters": glass_shutters,
            "trackCount": track_count,
            "opening": opening,
            "openingExplicit": True,
            "lockType": selection.get("locking") or quote.get("locking"),
        },
    }
    # Keep SVG on the line for re-export without leaking cost
    preview = quote.get("preview") if isinstance(quote.get("preview"), Mapping) else {}
    if preview.get("svg"):
        line["previewSvg"] = preview.get("svg")
    doc["lines"] = [line]
    saved = save_project(doc, action="public_package_quote_save")
    token = ensure_project_share_token(saved, persist=True)
    base = (_str(base_url) or "http://127.0.0.1:8000").rstrip("/")
    scan_url = f"{base}/q/{token}"
    scan_alt = f"{base}/scan/{token}"
    pdf_url = f"{base}/api/projects/{saved.get('projectId')}/pdf/customer"
    quote_id = _str(quote.get("quoteId"))

    # Merge customer + WeOS project refs into package quote store (costs stay in _internal only)
    prior = load_package_quote(quote_id) or {}
    record = {
        **prior,
        "quoteId": quote_id,
        "updatedAt": _now(),
        "createdAt": prior.get("createdAt") or _now(),
        "source": _str(body.get("source") or "woodenmax-public"),
        "selection": selection,
        "packagePrice": package_total,
        "packagePricePerUnit": package_unit,
        "currency": "INR",
        "customer": {
            "name": customer_name,
            "mobile": customer_mobile,
            "address": customer_address,
        },
        "projectId": saved.get("projectId"),
        "shareToken": token,
        "scanUrl": scan_url,
        "scanAltUrl": scan_alt,
        "pdfUrl": pdf_url,
        "_internal": {
            **(prior.get("_internal") if isinstance(prior.get("_internal"), Mapping) else {}),
            "projectId": saved.get("projectId"),
            "shareToken": token,
            "savedAt": time.time(),
        },
    }
    _save_record(quote_id, record)

    return {
        "ok": True,
        "quoteId": quote_id,
        "projectId": saved.get("projectId"),
        "shareToken": token,
        "scanUrl": scan_url,
        "scanAltUrl": scan_alt,
        "pdfUrl": pdf_url,
        "packagePrice": package_total,
        "packagePricePerUnit": package_unit,
        "packagePriceLabel": "Total Package Price",
        "currency": "INR",
        "gstNote": quote.get("gstNote"),
        "productName": quote.get("productName"),
        "widthMm": quote.get("widthMm"),
        "heightMm": quote.get("heightMm"),
        "qty": quote.get("qty"),
        "glassLabel": quote.get("glassLabel"),
        "meshLabel": quote.get("meshLabel"),
        "openingLabel": quote.get("openingLabel"),
        "finishLabel": quote.get("finishLabel"),
        "lockingLabel": quote.get("lockingLabel"),
        "glassShutters": glass_shutters,
        "meshShutters": mesh_n,
        "trackCount": track_count,
        "areaSqft": quote.get("areaSqft"),
        "customer": {
            "name": customer_name,
            "mobile": customer_mobile,
            "address": customer_address,
        },
        "preview": {"svg": preview.get("svg")} if preview.get("svg") else None,
        "updatedAt": _now(),
    }
