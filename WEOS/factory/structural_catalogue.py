"""Iron/MS + aluminium structural section library for gates / grills / privacy screens.

Loads Apollo MS hollow CSVs + calculated flats/channels + Silvassa Al structural
catalogue into one editable library. Stable ``sectionId`` is shared across canvas,
material editor, calculator, factory list, and PDF.

Al extrusion weight always comes from catalogue ``weightKgPerM`` (never outer W×D
only). MS may use catalogue kg/m, full-bar weight / stock length, or theoretical
hollow/solid formula labeled as theoretical.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from WEOS.paths import WORKSPACE_ROOT, data_dir, products_dir

MM_PER_FT = 304.8
MM_PER_M = 1000.0
DENSITY_MS = 7850.0
DENSITY_AL = 2700.0

SERIES_ID = "structural"
SERIES_NAME = "Iron / Aluminium structural"


def structural_dir() -> Path:
    d = products_dir() / "sections"
    d.mkdir(parents=True, exist_ok=True)
    return d


def structural_catalogue_path() -> Path:
    return structural_dir() / "structural_catalogue.json"


def structural_overrides_path() -> Path:
    """Admin edits (rates, stock, finish, hardware links) — never overwrite source CSVs."""
    return data_dir() / "materials" / "structural_overrides.json"


def _materials_src_dir() -> Path:
    return WORKSPACE_ROOT / "data" / "materials"


def _silvassa_path() -> Path:
    return structural_dir() / "silvassa_structural_catalogue.json"


def _num(val: Any, default: float | None = None) -> float | None:
    if val is None or val == "":
        return default
    try:
        return float(str(val).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _slug(*parts: Any) -> str:
    raw = "_".join(str(p or "").strip() for p in parts if str(p or "").strip())
    s = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    return s or "section"


SHAPE_LABELS: dict[str, str] = {
    "hollow_sq": "Square hollow",
    "hollow_rect": "Rectangle hollow",
    "hollow_round": "Round hollow / pipe",
    "solid_sq": "Solid square",
    "solid_round": "Solid round",
    "flat": "Flat bar",
    "angle": "Angle",
    "c_channel": "C-channel",
    "i_beam": "I-section",
    "louver": "Louver",
    "oval_louver": "Oval louver",
    "sheet": "Sheet",
    "extrusion": "Custom extrusion",
    "custom": "Other",
}

# Aliases accepted by list/filter API → canonical shape id
SHAPE_ALIASES: dict[str, str] = {
    "square": "hollow_sq",
    "sq": "hollow_sq",
    "shs": "hollow_sq",
    "square_hollow": "hollow_sq",
    "rectangle": "hollow_rect",
    "rect": "hollow_rect",
    "rhs": "hollow_rect",
    "rectangle_hollow": "hollow_rect",
    "pipe": "hollow_round",
    "tube": "hollow_round",
    "round_hollow": "hollow_round",
    "chs": "hollow_round",
    "round": "solid_round",
    "round_bar": "solid_round",
    "solid": "solid_round",
    "square_bar": "solid_sq",
    "flat_bar": "flat",
    "fb": "flat",
    "channel": "c_channel",
    "c": "c_channel",
    "i": "i_beam",
    "ibeam": "i_beam",
    "beam": "i_beam",
    "oval": "oval_louver",
}


def material_family(material: str | None) -> str:
    m = (material or "").strip().lower()
    if m.startswith("al") or m in ("aluminium", "aluminum", "alu"):
        return "aluminium"
    if m in ("mild_steel", "ms", "iron", "steel", "carbon_steel", "gi", "galvanised", "galvanized"):
        return "iron"
    return m or "other"


def normalize_shape_id(raw: str | None) -> str:
    t = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not t:
        return "custom"
    if t in SHAPE_LABELS:
        return t
    return SHAPE_ALIASES.get(t, t)


def _shape_from_type(section_type: str, *, material: str) -> str:
    t = (section_type or "").strip().upper().replace("-", " ")
    t_compact = t.replace(" ", "_")
    if t in ("SHS", "SQ", "SQUARE") or t_compact.startswith("SHS"):
        return "hollow_sq"
    if t in ("RHS", "RECT", "RECTANGLE") or t_compact.startswith("RHS"):
        return "hollow_rect"
    if t in ("CHS", "ROUND", "PIPE", "TUBE") or "HOLLOW ROUND" in t:
        return "hollow_round"
    if t in ("FLAT", "FB", "FLAT_BAR") or t.startswith("FLAT") or "SHEET" in t:
        return "flat" if "SHEET" not in t else "sheet"
    if t in ("ANGLE", "L", "ISA") or "ANGLE" in t:
        return "angle"
    if t in ("CHANNEL", "C", "PFC", "ISMC") or "CHANNEL" in t or t.startswith("C "):
        return "c_channel"
    if t in ("I", "UB", "UC", "BEAM") or t.startswith("I "):
        return "i_beam"
    if t in ("SOLID_SQ", "SQUARE_BAR") or "SOLID SQ" in t or "SOLID_SQUARE" in t_compact:
        return "solid_sq"
    if t in ("SOLID_ROUND", "ROUND_BAR") or "SOLID ROUND" in t or t_compact.startswith("SOLID_ROUND"):
        return "solid_round"
    if "LOUVER" in t or "Z_" in t or t.startswith("Z"):
        return "louver"
    if "OVAL" in t:
        return "oval_louver"
    if material == "aluminium":
        return "extrusion"
    return "custom"


def _tag_section(card: dict[str, Any]) -> dict[str, Any]:
    """Ensure stable materialFamily + shape labels for UI filters (IDs unchanged)."""
    out = dict(card)
    mat = str(out.get("material") or "mild_steel")
    fam = material_family(mat)
    # Canonical material string for filters
    if fam == "aluminium":
        out["material"] = "aluminium"
    elif fam == "iron":
        out["material"] = "mild_steel"
    shape = normalize_shape_id(str(out.get("shape") or out.get("category") or ""))
    out["shape"] = shape
    out["materialFamily"] = fam
    out["shapeFamily"] = shape
    out["shapeLabel"] = SHAPE_LABELS.get(shape, shape.replace("_", " ").title())
    out["materialLabel"] = "Aluminium" if fam == "aluminium" else ("Iron / MS" if fam == "iron" else mat)
    # Display helpers for picker
    w = out.get("widthMm")
    h = out.get("heightMm")
    th = out.get("thicknessMm")
    dims = []
    if w:
        dims.append(f"{w:g}")
    if h and (not w or abs(float(h) - float(w)) > 0.05):
        dims.append(f"{h:g}")
    elif h and w and abs(float(h) - float(w)) <= 0.05:
        pass  # square already shown once as W — still show ×W for tubes
        if shape.startswith("hollow") or shape.startswith("solid"):
            dims = [f"{float(w):g}", f"{float(h):g}"]
    dim_s = "×".join(dims) if dims else ""
    if th:
        dim_s = f"{dim_s}×{float(th):g}" if dim_s else f"t{float(th):g}"
    code = str(out.get("code") or out.get("sectionId") or "")
    name = str(out.get("name") or code)
    out["pickerLabel"] = " · ".join(
        p for p in (code, dim_s and f"{dim_s} mm", out.get("materialLabel"), out.get("shapeLabel")) if p
    )
    if name and name not in out["pickerLabel"]:
        out["pickerLabel"] = f"{name} · {out['pickerLabel']}" if out["pickerLabel"] else name
    return out


def theoretical_kg_per_m(
    *,
    shape: str,
    width_mm: float | None,
    height_mm: float | None,
    thickness_mm: float | None,
    density: float,
) -> float | None:
    """Metal area × density / 1e6. Hollow rect = B×H − (B−2t)(H−2t)."""
    B = float(width_mm or 0)
    H = float(height_mm or B or 0)
    t = float(thickness_mm or 0)
    if B <= 0 and H <= 0:
        return None
    area: float | None = None
    shape_l = (shape or "").lower()
    if shape_l in ("hollow_sq", "hollow_rect"):
        if t <= 0 or B <= 2 * t or H <= 2 * t:
            return None
        area = B * H - (B - 2 * t) * (H - 2 * t)
    elif shape_l in ("solid_sq", "flat"):
        th = t if t > 0 else H
        if B <= 0 or th <= 0:
            return None
        area = B * th
    elif shape_l in ("solid_round",):
        d = B or H
        if d <= 0:
            return None
        area = math.pi / 4.0 * d * d
    elif shape_l in ("hollow_round",):
        od = B or H
        if od <= 0 or t <= 0 or od <= 2 * t:
            return None
        id_ = od - 2 * t
        area = math.pi / 4.0 * (od * od - id_ * id_)
    elif shape_l == "angle":
        # Approx equal-leg: 2*A*t − t²
        A = B or H
        if A <= 0 or t <= 0:
            return None
        area = 2 * A * t - t * t
    elif shape_l == "c_channel":
        # Approx web + 2 flanges (outer)
        if B <= 0 or H <= 0 or t <= 0:
            return None
        area = H * t + 2 * max(B - t, 0) * t
    else:
        return None
    return round(area * density / 1e6, 4)


def resolve_kg_per_m(section: Mapping[str, Any]) -> dict[str, Any]:
    """Prefer verified unit weight; full-bar → kg/m; else theoretical labeled."""
    missing: list[str] = []
    cat = _num(section.get("weightKgPerM") or section.get("weightKgPerMtr"))
    if cat and cat > 0:
        return {
            "weightKgPerM": cat,
            "weightSource": "catalogue",
            "weightLabel": "Catalogue kg/m",
            "missing": missing,
        }
    bar_kg = _num(section.get("kgPerStockLength") or section.get("barWeightKg"))
    stock_mm = _num(section.get("stockLengthMm"))
    stock_ft = _num(section.get("stockLengthFt"))
    if not stock_mm and stock_ft:
        stock_mm = stock_ft * MM_PER_FT
    if bar_kg and bar_kg > 0 and stock_mm and stock_mm > 0:
        kg_m = bar_kg / (stock_mm / MM_PER_M)
        return {
            "weightKgPerM": round(kg_m, 4),
            "weightSource": "full_bar",
            "weightLabel": f"Bar {bar_kg:g} kg / {stock_mm/MM_PER_FT:g} ft",
            "missing": missing,
        }
    material = str(section.get("material") or "mild_steel").lower()
    if material in ("aluminium", "aluminum", "alu"):
        # Never invent Al extrusion weight from outer envelope
        missing.append("weightKgPerM")
        return {
            "weightKgPerM": None,
            "weightSource": "missing",
            "weightLabel": "Missing catalogue kg/m (Al extrusion)",
            "missing": missing,
        }
    dens = _num(section.get("densityKgPerM3"), DENSITY_MS) or DENSITY_MS
    theo = theoretical_kg_per_m(
        shape=str(section.get("shape") or ""),
        width_mm=_num(section.get("widthMm") or section.get("faceWidthMm")),
        height_mm=_num(section.get("heightMm") or section.get("depthMm")),
        thickness_mm=_num(section.get("thicknessMm") or section.get("wallThicknessMm")),
        density=dens,
    )
    if theo and theo > 0:
        return {
            "weightKgPerM": theo,
            "weightSource": "theoretical",
            "weightLabel": "Theoretical (labeled)",
            "missing": missing,
        }
    missing.append("weightKgPerM")
    return {
        "weightKgPerM": None,
        "weightSource": "missing",
        "weightLabel": "Missing kg/m",
        "missing": missing,
    }


def _base_card(
    *,
    section_id: str,
    code: str,
    name: str,
    material: str,
    grade: str | None,
    shape: str,
    width_mm: float | None,
    height_mm: float | None,
    thickness_mm: float | None,
    weight_kg_m: float | None,
    supplier: str,
    source: Mapping[str, Any] | None = None,
    category: str | None = None,
    uncertain: bool = False,
    notes: str | None = None,
) -> dict[str, Any]:
    face_w = width_mm
    face_d = height_mm if height_mm is not None else width_mm
    shape_n = normalize_shape_id(shape)
    fam = material_family(material)
    mat_n = "aluminium" if fam == "aluminium" else ("mild_steel" if fam == "iron" else material)
    card = {
        "sectionId": section_id,
        "id": section_id,
        "code": code,
        "name": name,
        "supplier": supplier,
        "material": mat_n,
        "materialFamily": fam,
        "grade": grade,
        "shape": shape_n,
        "shapeFamily": shape_n,
        "shapeLabel": SHAPE_LABELS.get(shape_n, shape_n.replace("_", " ").title()),
        "materialLabel": "Aluminium" if fam == "aluminium" else ("Iron / MS" if fam == "iron" else material),
        "category": category or shape_n,
        "widthMm": width_mm,
        "heightMm": height_mm if height_mm is not None else width_mm,
        "thicknessMm": thickness_mm,
        "wallThicknessMm": thickness_mm,
        "faceWidthMm": face_w,
        "depthMm": face_d,
        "orientationDeg": 0,
        "weightKgPerM": weight_kg_m,
        "kgPerStockLength": None,
        "stockLengthsMm": [],
        "stockLengthMm": None,
        "stockLengthFt": None,
        "finish": None,
        "colour": None,
        "purchaseRate": None,
        "purchaseRateUnit": "kg",  # kg | rft | m | full_length | piece
        "sellingRate": None,
        "sellingRateUnit": None,
        "compatibleUses": [],
        "compatibleHardware": [],
        "compatibleGlass": [],
        "compatibleClips": [],
        "drawing": None,
        "photo": None,
        "source": dict(source or {}),
        "uncertain": bool(uncertain),
        "notes": notes,
        "missingFields": [],
    }
    wr = resolve_kg_per_m(card)
    card["resolvedWeightKgPerM"] = wr.get("weightKgPerM")
    card["weightSource"] = wr.get("weightSource")
    card["weightLabel"] = wr.get("weightLabel")
    _mark_missing(card)
    return card


def _mark_missing(card: MutableMapping[str, Any]) -> None:
    miss: list[str] = []
    for key, label in (
        ("widthMm", "dims"),
        ("weightKgPerM", "kg/m"),
        ("purchaseRate", "purchase rate"),
        ("purchaseRateUnit", "purchase rate unit"),
        ("stockLengthMm", "stock length"),
    ):
        # stock length only required for full_length billing
        if key == "stockLengthMm":
            unit = str(card.get("purchaseRateUnit") or "")
            if unit in ("full_length", "bar", "length") and not (
                card.get("stockLengthMm") or (card.get("stockLengthsMm") or [])
            ):
                miss.append(label)
            continue
        if key == "weightKgPerM":
            if not card.get("weightKgPerM") and not card.get("resolvedWeightKgPerM"):
                if str(card.get("material") or "").lower().startswith("al"):
                    miss.append(label)
                elif not card.get("kgPerStockLength"):
                    miss.append(label)
            continue
        if card.get(key) in (None, "", []):
            miss.append(label)
    card["missingFields"] = miss


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _load_apollo_ms() -> list[dict[str, Any]]:
    src = _materials_src_dir()
    out: list[dict[str, Any]] = []
    files = [
        ("apl_apollo_shs_master_batch1.csv", "SHS"),
        ("apl_apollo_rhs_master_batch2.csv", "RHS"),
        ("apl_apollo_profiles_verified_partial.csv", None),
        ("ms_solid_bars_and_channels_calculated.csv", None),
    ]
    seen: set[str] = set()
    for fname, force_type in files:
        rows = _read_csv(src / fname)
        for row in rows:
            st = force_type or str(row.get("Section Type") or "").strip().upper()
            label = str(row.get("Section (mm)") or "").strip()
            w = _num(row.get("Width (mm)") or row.get("Width / Diameter (mm)"))
            h = _num(row.get("Height (mm)") or row.get("Height / Depth (mm)"))
            t = _num(row.get("Thickness (mm)"))
            kg = _num(row.get("Weight (kg/m)"))
            if not label and w:
                label = f"{w:g}x{h:g}" if h else f"{w:g}"
            if not label:
                continue
            sid = _slug("ms", st or "sec", label, t)
            if sid in seen:
                # Prefer verified PDF rows
                if "verified" not in str(row.get("Verification") or "").lower():
                    continue
            seen.add(sid)
            status = str(row.get("Status") or row.get("Verification") or "")
            shape = _shape_from_type(st, material="mild_steel")
            if st == "FLAT":
                h = t
            card = _base_card(
                section_id=sid,
                code=f"MS-{st}-{label}-T{t:g}" if t else f"MS-{st}-{label}",
                name=f"MS {st} {label}" + (f" × {t:g}" if t else ""),
                material="mild_steel",
                grade="MS",
                shape=shape,
                width_mm=w,
                height_mm=h if h is not None else w,
                thickness_mm=t,
                weight_kg_m=kg,
                supplier="APL Apollo" if "apollo" in fname else "Calculated MS",
                source={
                    "csvFile": fname,
                    "status": status,
                    "pdfPage": _num(row.get("PDF Page")),
                    "method": row.get("Method / Assumption"),
                },
                category=st.lower() if st else shape,
                notes=str(row.get("Method / Assumption") or "") or None,
            )
            if "Calculated" in status:
                card["weightSource"] = "theoretical"
                card["weightLabel"] = "Theoretical (CSV calculated)"
            out.append(card)
    return out


def _load_silvassa_al() -> list[dict[str, Any]]:
    path = _silvassa_path()
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, Mapping) else []
    out: list[dict[str, Any]] = []
    for it in items or []:
        if not isinstance(it, Mapping):
            continue
        code = str(it.get("code") or "").strip()
        name = str(it.get("name") or code or "Al section").strip()
        dims = it.get("dimensionsMm") if isinstance(it.get("dimensionsMm"), Mapping) else {}
        a = _num(dims.get("A"))
        b = _num(dims.get("B"))
        t = _num(it.get("thicknessMm"))
        cat = str(it.get("category") or "")
        shape = _shape_from_type(cat, material="aluminium")
        if cat == "square_section":
            shape = "hollow_sq"
        elif cat == "rectangle_section":
            shape = "hollow_rect"
        elif cat == "angle":
            shape = "angle"
        elif cat == "z_louver":
            shape = "louver"
        elif cat == "oval_louver":
            shape = "oval_louver"
        sid = _slug("al_sil", code or name, t)
        src = it.get("source") if isinstance(it.get("source"), Mapping) else {}
        card = _base_card(
            section_id=sid,
            code=code or sid,
            name=f"Al {name}",
            material="aluminium",
            grade="6063-T5",
            shape=shape,
            width_mm=a,
            height_mm=b if b is not None else a,
            thickness_mm=t,
            weight_kg_m=_num(it.get("weightKgPerM")),
            supplier="Silvassa",
            source={
                "pdfFile": src.get("pdfFile"),
                "pdfPage": src.get("pdfPage"),
                "catalogPage": src.get("catalogPage"),
                "sectionTitle": src.get("sectionTitle"),
                "catalogue": "silvassa_structural",
            },
            category=cat or shape,
            uncertain=bool(it.get("uncertain")),
            notes=str(it.get("notes") or "") or None,
        )
        # Default Al structural stock 16 ft (editable)
        card["stockLengthFt"] = 16.0
        card["stockLengthMm"] = 16.0 * MM_PER_FT
        card["stockLengthsMm"] = [12.0 * MM_PER_FT, 16.0 * MM_PER_FT]
        card["purchaseRateUnit"] = "full_length"
        _mark_missing(card)
        out.append(card)
    return out


def _load_overrides() -> dict[str, dict[str, Any]]:
    path = structural_overrides_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(raw, Mapping) and isinstance(raw.get("byId"), Mapping):
        return {str(k): dict(v) for k, v in raw["byId"].items() if isinstance(v, Mapping)}
    if isinstance(raw, Mapping):
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, Mapping)}
    return {}


def save_overrides(by_id: Mapping[str, Mapping[str, Any]]) -> Path:
    path = structural_overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "byId": {str(k): dict(v) for k, v in by_id.items()}}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _apply_override(card: dict[str, Any], ov: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(card)
    editable = (
        "name", "code", "supplier", "material", "grade", "shape",
        "widthMm", "heightMm", "thicknessMm", "wallThicknessMm",
        "faceWidthMm", "depthMm", "orientationDeg",
        "weightKgPerM", "kgPerStockLength", "stockLengthMm", "stockLengthFt",
        "stockLengthsMm", "finish", "colour",
        "purchaseRate", "purchaseRateUnit", "sellingRate", "sellingRateUnit",
        "compatibleUses", "compatibleHardware", "compatibleGlass", "compatibleClips",
        "drawing", "photo", "notes",
    )
    for k in editable:
        if k in ov and ov[k] is not None:
            out[k] = ov[k]
    if out.get("stockLengthFt") and not out.get("stockLengthMm"):
        out["stockLengthMm"] = float(out["stockLengthFt"]) * MM_PER_FT
    if out.get("orientationDeg"):
        # Rotate 60×40 → spacing uses visible face
        deg = float(out["orientationDeg"] or 0) % 180
        if 45 <= deg < 135:
            out["faceWidthMm"], out["depthMm"] = out.get("depthMm"), out.get("faceWidthMm")
    wr = resolve_kg_per_m(out)
    out["resolvedWeightKgPerM"] = wr.get("weightKgPerM")
    out["weightSource"] = wr.get("weightSource")
    out["weightLabel"] = wr.get("weightLabel")
    _mark_missing(out)
    return out


def build_structural_catalogue(*, persist: bool = True) -> dict[str, Any]:
    sections = _load_apollo_ms() + _load_silvassa_al()
    overrides = _load_overrides()
    merged = [_apply_override(s, overrides.get(s["sectionId"], {})) for s in sections]
    # Ensure acceptance defaults exist as explicit overrideable cards if missing
    ensure_ids = {
        "ms_shs_75x75_t3": {
            "sectionId": "ms_shs_75x75_t3",
            "code": "MS-SHS-75x75-T3",
            "name": "MS SHS 75×75 × 3",
            "supplier": "APL Apollo",
            "material": "mild_steel",
            "grade": "MS",
            "shape": "hollow_sq",
            "widthMm": 75.0,
            "heightMm": 75.0,
            "thicknessMm": 3.0,
            "faceWidthMm": 75.0,
            "depthMm": 75.0,
            "weightKgPerM": 6.6,
            "stockLengthFt": 20.0,
            "stockLengthMm": 20.0 * MM_PER_FT,
            "kgPerStockLength": 25.0,
            "purchaseRate": 150.0,
            "purchaseRateUnit": "kg",
        },
        "al_sil_sq_25x25": {
            "sectionId": "al_sil_sq_25x25",
            "code": "SIL-25x25",
            "name": "Al Square tube 25×25",
            "supplier": "Silvassa",
            "material": "aluminium",
            "grade": "6063-T5",
            "shape": "hollow_sq",
            "widthMm": 25.0,
            "heightMm": 25.0,
            "thicknessMm": 1.2,
            "faceWidthMm": 25.0,
            "depthMm": 25.0,
            "weightKgPerM": 0.308,
            "stockLengthFt": 16.0,
            "stockLengthMm": 16.0 * MM_PER_FT,
            "purchaseRate": 850.0,
            "purchaseRateUnit": "full_length",
        },
        "ms_round_12": {
            "sectionId": "ms_round_12",
            "code": "MS-ROUND-12",
            "name": "MS round 12 mm support",
            "supplier": "Local",
            "material": "mild_steel",
            "grade": "MS",
            "shape": "solid_round",
            "widthMm": 12.0,
            "heightMm": 12.0,
            "thicknessMm": 12.0,
            "faceWidthMm": 12.0,
            "depthMm": 12.0,
            "weightKgPerM": round(math.pi / 4.0 * 12 * 12 * DENSITY_MS / 1e6, 4),
            "stockLengthFt": 20.0,
            "stockLengthMm": 20.0 * MM_PER_FT,
            "purchaseRate": 150.0,
            "purchaseRateUnit": "kg",
            "weightSource": "theoretical",
            "weightLabel": "Theoretical round bar",
        },
    }
    by_id = {s["sectionId"]: s for s in merged}
    for sid, seed in ensure_ids.items():
        if sid not in by_id:
            # Prefer real catalogue match for 75×75 / 25×25 when present
            if sid == "ms_shs_75x75_t3":
                hit = next(
                    (
                        s for s in merged
                        if s.get("material") == "mild_steel"
                        and s.get("shape") == "hollow_sq"
                        and abs(float(s.get("widthMm") or 0) - 75) < 0.1
                        and abs(float(s.get("thicknessMm") or 0) - 3) < 0.05
                    ),
                    None,
                )
                if hit:
                    by_id[hit["sectionId"]] = hit
                    continue
            if sid == "al_sil_sq_25x25":
                hit = next(
                    (
                        s for s in merged
                        if s.get("material") == "aluminium"
                        and abs(float(s.get("widthMm") or 0) - 25) < 0.1
                        and abs(float(s.get("heightMm") or 0) - 25) < 0.1
                    ),
                    None,
                )
                if hit:
                    by_id[hit["sectionId"]] = _apply_override(hit, overrides.get(hit["sectionId"], {}))
                    continue
            card = _base_card(
                section_id=sid,
                code=seed["code"],
                name=seed["name"],
                material=seed["material"],
                grade=seed.get("grade"),
                shape=seed["shape"],
                width_mm=seed.get("widthMm"),
                height_mm=seed.get("heightMm"),
                thickness_mm=seed.get("thicknessMm"),
                weight_kg_m=seed.get("weightKgPerM"),
                supplier=seed.get("supplier") or "",
            )
            by_id[sid] = _apply_override(card, {**seed, **overrides.get(sid, {})})
        else:
            by_id[sid] = _apply_override(by_id[sid], overrides.get(sid, {}))

    sections_out = [_tag_section(s) for s in by_id.values()]
    sections_out.sort(key=lambda s: (s.get("materialFamily") or "", s.get("shape") or "", s.get("name") or ""))
    facets = section_facets(sections_out)
    pack = {
        "version": 1,
        "seriesId": SERIES_ID,
        "name": SERIES_NAME,
        "sectionCount": len(sections_out),
        "sections": sections_out,
        "facets": facets,
        "sources": {
            "ms": "data/materials/*.csv",
            "aluminium": "WEOS/products/sections/silvassa_structural_catalogue.json",
        },
    }
    if persist:
        structural_catalogue_path().write_text(
            json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return pack


def section_facets(rows: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Counts for material + shape chips in the section picker."""
    secs = list(rows) if rows is not None else list_structural_sections()
    mat_counts: dict[str, int] = {"iron": 0, "aluminium": 0, "other": 0}
    shape_counts: dict[str, int] = {}
    for s in secs:
        fam = material_family(str(s.get("materialFamily") or s.get("material") or ""))
        if fam in mat_counts:
            mat_counts[fam] += 1
        else:
            mat_counts["other"] += 1
        shp = normalize_shape_id(str(s.get("shapeFamily") or s.get("shape") or ""))
        shape_counts[shp] = shape_counts.get(shp, 0) + 1
    materials = [
        {"id": "all", "label": "All", "count": len(secs)},
        {"id": "iron", "label": "Iron / MS", "count": mat_counts["iron"]},
        {"id": "aluminium", "label": "Aluminium", "count": mat_counts["aluminium"]},
    ]
    if mat_counts["other"]:
        materials.append({"id": "other", "label": "Other", "count": mat_counts["other"]})
    shapes = [
        {"id": sid, "label": SHAPE_LABELS.get(sid, sid.replace("_", " ").title()), "count": n}
        for sid, n in sorted(shape_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if n > 0
    ]
    return {"materials": materials, "shapes": shapes}


def list_structural_sections(
    *,
    material: str | None = None,
    shape: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    pack = load_structural_catalogue()
    rows = [_tag_section(s) if "materialFamily" not in s else s for s in (pack.get("sections") or [])]
    mat = (material or "").strip().lower()
    shp = normalize_shape_id(shape) if shape else ""
    query = (q or "").strip().lower()
    out = []
    for s in rows:
        if mat and mat not in ("all", "*"):
            fam = material_family(str(s.get("materialFamily") or s.get("material") or ""))
            if mat in ("ms", "iron", "steel", "mild_steel"):
                if fam != "iron":
                    continue
            elif mat in ("al", "aluminium", "aluminum"):
                if fam != "aluminium":
                    continue
            elif mat != fam and mat not in str(s.get("material") or "").lower():
                continue
        if shp and shp not in ("all", "*"):
            ss = normalize_shape_id(str(s.get("shapeFamily") or s.get("shape") or ""))
            if ss != shp:
                continue
        if query:
            blob = " ".join(
                str(s.get(k) or "")
                for k in ("sectionId", "code", "name", "supplier", "shape", "shapeLabel", "materialLabel", "pickerLabel")
            ).lower()
            if query not in blob:
                continue
        out.append(s)
    return out


def get_structural_section(section_id: str) -> dict[str, Any] | None:
    if not section_id:
        return None
    sid = str(section_id).strip()
    for s in list_structural_sections():
        if s.get("sectionId") == sid or s.get("id") == sid or s.get("code") == sid:
            return s
    # Fuzzy: ms 75x75, al 25x25
    low = sid.lower()
    for s in list_structural_sections():
        if low in str(s.get("sectionId") or "").lower() or low in str(s.get("name") or "").lower():
            return s
    return None


def find_section_by_size(
    *,
    material: str,
    width_mm: float,
    height_mm: float | None = None,
    thickness_mm: float | None = None,
    shape: str | None = None,
) -> dict[str, Any] | None:
    h = height_mm if height_mm is not None else width_mm
    mat = material.lower()
    want_shape = (shape or "").strip().lower()
    best = None
    best_score = 1e18
    for s in list_structural_sections(material=mat):
        sw = float(s.get("widthMm") or 0)
        sh = float(s.get("heightMm") or sw)
        st = float(s.get("thicknessMm") or 0)
        if abs(sw - width_mm) > 0.6 or abs(sh - h) > 0.6:
            continue
        score = abs(sw - width_mm) + abs(sh - h)
        if thickness_mm is not None:
            score += abs(st - thickness_mm) * 2
        shp = str(s.get("shape") or "").lower()
        cat = str(s.get("category") or "").lower()
        if want_shape:
            if want_shape not in shp and want_shape not in cat:
                score += 50
        else:
            # Prefer hollow square/rect tubes over angles when size matches.
            if "angle" in shp or cat == "angle":
                score += 20
            if "hollow" in shp or "square" in cat or "rectangle" in cat:
                score -= 5
        if score < best_score:
            best_score = score
            best = s
    return best


def update_structural_section(section_id: str, patch: Mapping[str, Any]) -> dict[str, Any]:
    """Persist admin edits into overrides; rebuild catalogue card."""
    sid = str(section_id).strip()
    overrides = _load_overrides()
    cur = dict(overrides.get(sid) or {})
    cur.update({k: v for k, v in patch.items() if k != "sectionId"})
    overrides[sid] = cur
    save_overrides(overrides)
    pack = build_structural_catalogue(persist=True)
    for s in pack.get("sections") or []:
        if s.get("sectionId") == sid:
            return s
    # New custom card
    card = _base_card(
        section_id=sid,
        code=str(patch.get("code") or sid),
        name=str(patch.get("name") or sid),
        material=str(patch.get("material") or "mild_steel"),
        grade=patch.get("grade"),
        shape=str(patch.get("shape") or "custom"),
        width_mm=_num(patch.get("widthMm")),
        height_mm=_num(patch.get("heightMm")),
        thickness_mm=_num(patch.get("thicknessMm")),
        weight_kg_m=_num(patch.get("weightKgPerM")),
        supplier=str(patch.get("supplier") or "Custom"),
    )
    card = _apply_override(card, cur)
    overrides[sid] = {**cur, **{k: card.get(k) for k in ("name", "code", "material", "shape")}}
    save_overrides(overrides)
    build_structural_catalogue(persist=True)
    return card


def load_structural_catalogue() -> dict[str, Any]:
    path = structural_catalogue_path()
    if path.is_file():
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(pack, Mapping) and pack.get("sections"):
                return pack
        except Exception:
            pass
    return build_structural_catalogue(persist=True)


def amount_for_purchase(
    *,
    used_m: float,
    used_kg: float,
    bars: int,
    section: Mapping[str, Any],
) -> dict[str, Any]:
    """Purchase amount from saved rate unit (₹/kg, ₹/rft, ₹/m, ₹/full length)."""
    rate = _num(section.get("purchaseRate"))
    unit = str(section.get("purchaseRateUnit") or "kg").lower().replace(" ", "_")
    missing: list[str] = []
    if rate is None:
        missing.append(f"{section.get('name') or section.get('sectionId')}: purchase rate")
        return {"amount": None, "basis": unit, "qty": None, "missing": missing, "incomplete": True}
    if unit in ("kg", "per_kg"):
        return {"amount": round(used_kg * rate, 2), "basis": "kg", "qty": round(used_kg, 3), "rate": rate, "missing": missing}
    if unit in ("rft", "per_rft", "ft"):
        rft = used_m / 0.3048
        return {"amount": round(rft * rate, 2), "basis": "rft", "qty": round(rft, 3), "rate": rate, "missing": missing}
    if unit in ("m", "rm", "rmt", "per_m", "metre", "meter"):
        return {"amount": round(used_m * rate, 2), "basis": "m", "qty": round(used_m, 3), "rate": rate, "missing": missing}
    if unit in ("full_length", "bar", "length", "full_bar", "stock"):
        return {"amount": round(bars * rate, 2), "basis": "full_length", "qty": bars, "rate": rate, "missing": missing}
    if unit in ("piece", "pcs", "pc", "set"):
        return {"amount": round(bars * rate, 2), "basis": unit, "qty": bars, "rate": rate, "missing": missing}
    missing.append(f"unknown rate unit {unit}")
    return {"amount": None, "basis": unit, "qty": None, "rate": rate, "missing": missing, "incomplete": True}
