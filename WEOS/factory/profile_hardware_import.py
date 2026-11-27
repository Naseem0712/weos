"""Import user Excel ``profile and hardwares weos.xlsx`` into WEOS catalogues.

Sheets:
  * Sliding / Caments → section catalogue + Product Library series with
    ``setup.sliding`` / ``setup.casement`` (rates editable defaults)
  * Hardwares → Hardware Library (+ sliding/casement hardwarePack seed)
  * Stile / Slim Doors → empty in source (skipped)

Brand defaults (HIVIC / CMECH / ETTE) come from :mod:`WEOS.factory.hardware_brands`.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from WEOS.factory.hardware_brands import (
    brand_for_origin,
    infer_origin_from_text,
    normalize_origin,
    resolve_hardware_brand,
    with_resolved_brand,
)
from WEOS.factory.hardware_catalogue import build_hardware_item, catalogue_dir, save_hardware
from WEOS.factory.product_setup import normalize_setup
from WEOS.factory.section_catalogue import (
    SERIES_PRODUCT_MAP,
    infer_usage,
    is_center_opening_only,
    parse_glass_options,
    parse_track_count,
    persist_catalogue,
    sync_catalogue_to_library,
)
from WEOS.paths import WORKSPACE_ROOT, products_dir

DEFAULT_EXCEL_CANDIDATES = [
    Path(r"D:\Downloads\profile and hardwares weos.xlsx"),
    WORKSPACE_ROOT / "profile and hardwares weos.xlsx",
    WORKSPACE_ROOT / "references" / "profile and hardwares weos.xlsx",
]

# Old DETA / placeholder sliding stubs superseded by this workbook
DUMMY_SLIDING_STUBS = (
    "25mm_eco_gulf",
    "27mm_high_end_domal",
    "29mm_premium_euro",
    "31mm_gulf_lux_slim",
    "32mm_dual_euro",
    "35mm_gulf_slim",
    "35mm_sliding",
    "new_product",
    "fixed_stub",
)

# Keep manufacturing engines / unrelated products (engines stay on disk for linkedProductId)
KEEP_PRODUCTS = {
    "29mm_sliding",
    "casement_stub",
    "bathroom_ventilator",
    "shower_partition",
    "railings_stub",
    "acp_stub",
    "folding_stub",
    "louvers_stub",
    "perforated_stub",
    "pergola_stub",
    "fluted_stub",
}

# Engines must remain loadable but must NOT appear beside Excel series in Product Library
CATALOG_HIDDEN_ENGINES = (
    "29mm_sliding",
    "casement_stub",
)

# Only these casement series stay selectable in Product Library / cart
EXCEL_CASEMENT_SERIES = frozenset({
    "40mm_casement_standard",
    "50mm_casement_prestige",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "item"


def _clean(val: Any) -> str | None:
    if val is None:
        return None
    s = re.sub(r"\s+", " ", str(val).strip())
    return s or None


def _num(val: Any) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower().replace(",", ".")
    # Fix typos like 0.7.2 → 0.72
    if re.fullmatch(r"\d+\.\d+\.\d+", s):
        parts = s.split(".")
        s = parts[0] + "." + "".join(parts[1:])
    m = re.search(r"(-?\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def _parse_dims(val: Any) -> tuple[float | None, float | None]:
    """Return (face/wMm, depth/hMm) from written ``FACE×DEPTH``.

    Convention (all profile sections): number before X = face (elevation
    visible thickness); number after X = depth (into the opening — BOM/3D
    only). Examples: ``40X50.99`` → face=40, depth=50.99; ``26.X125.1`` same.
    A single number is treated as face only.
    """
    if val is None or val == "":
        return None, None
    if isinstance(val, (int, float)):
        return float(val), None
    s = str(val).strip().upper().replace("×", "X").replace("*", "X")
    s = re.sub(r"\s+", "", s)
    # Allow trailing/leading dots: 26.X125.1
    m = re.match(r"(\d+(?:\.\d*)?)\s*X\s*(\d+(?:\.\d*)?)", s)
    if m:
        face = float(m.group(1).rstrip("."))
        depth = float(m.group(2).rstrip("."))
        return face, depth
    n = _num(val)
    return n, None


def _parse_rate(val: Any) -> tuple[float | None, str]:
    """Return (rate, unit).

    Excel: most profile rates are **per kg**; when the cell explicitly says
    ``rft`` / ``per rft`` / ``200 rft`` use **per RFT**. Coating is always
    stored separately as per-RFT (see ``coatingUnit``).
    """
    if val is None or val == "":
        return None, "kg"
    if isinstance(val, (int, float)):
        return float(val), "kg"
    s = str(val).strip().lower().replace("₹", "").replace("rs", " ")
    n = _num(val)
    if re.search(r"per\s*rft|/rft|\brft\b", s):
        return n, "rft"
    if re.search(r"per\s*rmt|per\s*m\b|/m\b|\brmt\b", s) and "rft" not in s:
        return n, "rmt"
    if re.search(r"\bpc\b|\bnos\b|per\s*pc", s):
        return n, "pc"
    if re.search(r"per\s*kg|/kg|\bkg\b", s):
        return n, "kg"
    return n, "kg"


def _parse_std_length(val: Any) -> str | None:
    t = _clean(val)
    if t is None:
        return None
    return t


def parse_use_bom_counts(
    all_side: Any = None,
    use_v: Any = None,
    use_h: Any = None,
    *,
    section_name: str | None = None,
) -> dict[str, Any]:
    """Map Excel ``use all side`` / ``use V`` / ``use H`` → cut pcs.

    - **V** / ``use V`` = vertical pcs (per shutter / outer as row context)
    - **H** / ``use H`` = horizontal pcs
    - **V2 H2** (in all-side) = one section builds the whole frame/shutter
      (all sides same) → 2 vertical + 2 horizontal

    Some sheet rows put top/bottom qty in the V column and vertical L/R qty in
    H (inverted). When the product name clearly says top/bottom or vertical,
    counts are swapped to the matching axis.
    """
    raw_all = _clean(all_side) or ""
    blob = " ".join(
        str(x) for x in (raw_all, use_v, use_h) if x is not None and str(x).strip() != ""
    ).lower().replace(",", " ")
    compact = re.sub(r"\s+", "", blob)

    all_sides_same = bool(
        re.search(r"v\s*2", blob) and re.search(r"h\s*2", blob)
    ) or ("v2" in compact and "h2" in compact) or ("allside" in compact) or ("all side" in blob)

    pcs_v: int | None = None
    pcs_h: int | None = None

    def _as_int(val: Any) -> int | None:
        if val is None or str(val).strip() == "":
            return None
        # Bare "V" / "H" without digit → 1
        s = str(val).strip().lower()
        if s in ("v", "h"):
            return 1
        n = _num(val)
        if n is None:
            m = re.search(r"(\d+)", s)
            return int(m.group(1)) if m else None
        return int(round(float(n)))

    pcs_v = _as_int(use_v)
    pcs_h = _as_int(use_h)

    # Digits embedded in all-side text: v2, h2, V1, …
    if pcs_v is None:
        mv = re.search(r"\bv\s*([0-9]+)\b", blob)
        if mv:
            pcs_v = int(mv.group(1))
        elif re.search(r"\bv\b", blob) and not all_sides_same:
            pcs_v = 1
    if pcs_h is None:
        mh = re.search(r"\bh\s*([0-9]+)\b", blob)
        if mh:
            pcs_h = int(mh.group(1))
        elif re.search(r"\bh\b", blob) and not all_sides_same:
            pcs_h = 1

    if all_sides_same:
        pcs_v = 2 if pcs_v is None else pcs_v
        pcs_h = 2 if pcs_h is None else pcs_h

    # Name-based axis correction for inverted Excel columns
    nl = (section_name or "").lower()
    is_horiz_name = any(k in nl for k in ("top", "bottom", "horizon"))
    is_vert_name = any(k in nl for k in ("vertical", "left", "right", "jamb")) and not is_horiz_name
    if is_horiz_name and pcs_v and not pcs_h:
        pcs_h, pcs_v = pcs_v, None
    elif is_vert_name and pcs_h and not pcs_v:
        pcs_v, pcs_h = pcs_h, None

    bits: list[str] = []
    if raw_all:
        bits.append(raw_all)
    if use_v is not None and str(use_v).strip() != "":
        bits.append(f"V{_clean(use_v) or use_v}")
    if use_h is not None and str(use_h).strip() != "":
        bits.append(f"H{_clean(use_h) or use_h}")
    return {
        "use": " ".join(str(b) for b in bits),
        "allSidesSame": all_sides_same,
        "pcsVertical": pcs_v,
        "pcsHorizontal": pcs_h,
        "bomHint": (
            "all_sides_same_v2h2" if all_sides_same
            else ("split_vh" if (pcs_v or pcs_h) else "unspecified")
        ),
    }


def _parse_use_sides(all_side: Any, use_v: Any, use_h: Any, *, section_name: str | None = None) -> str:
    return str(parse_use_bom_counts(all_side, use_v, use_h, section_name=section_name).get("use") or "")


def _is_series_header(name: str | None, product: str | None) -> bool:
    if not name:
        return False
    n = name.lower()
    # Section-group labels, not series
    if n.strip() in ("shutters", "shutter", "shutters ", "track rail options"):
        return False
    if re.search(r"\d+\s*mm|series|stander|standard|domal|prestige|gulf|premium", n):
        # If product name also present on same row, still a series start
        return True
    return False


def _is_group_label(name: str | None) -> bool:
    if not name:
        return False
    n = name.strip().lower()
    return n in ("shutters", "shutter", "track rail options", "lock, handle options",
                 "friction stay options", "hinges", "connecters", "connectors",
                 "lock options", "caments system") or n.startswith("hinges ke")


def _series_id_from_title(title: str, *, family: str) -> str:
    t = title.strip()
    tl = t.lower()
    if family == "sliding":
        if "25" in tl and "prestige" in tl:
            return "25mm_prestige"
        if "27" in tl and ("domal" in tl or "27mm" in tl):
            return "27mm_domal"
        if "29" in tl and "premium" in tl:
            return "29mm_premium"
        if "35" in tl and "gulf" in tl:
            return "35mm_gulf"
        if "35" in tl and "prestige" in tl:
            return "35mm_prestige"
        if "40" in tl and "prestige" in tl:
            return "40mm_prestige"
    if family == "casement":
        if "40" in tl and ("stander" in tl or "standard" in tl):
            return "40mm_casement_standard"
        if "50" in tl and "prestige" in tl:
            return "50mm_casement_prestige"
    return _slug(t)


def find_excel_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Excel not found: {explicit}")
    for c in DEFAULT_EXCEL_CANDIDATES:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "profile and hardwares weos.xlsx not found. Pass path or place in Downloads / workspace."
    )


def _usage_label(usage: str) -> str:
    return {
        "track": "Track / Outer frame",
        "track_horizontal": "Track — horizontal",
        "track_vertical": "Track — vertical",
        "track_add": "Add track",
        "sash": "Sash / Shutter",
        "interlock": "Interlock",
        "meeting": "Meeting section",
        "frame": "Frame",
        "other": "Section",
        "unknown": "Section",
    }.get(usage, usage)


def _section_record(
    series_id: str,
    *,
    name: str,
    face: float | None,
    depth: float | None,
    wall: float | None,
    weight: float | None,
    rate: float | None,
    rate_unit: str,
    std_length: str | None,
    coating: float | None,
    use: str,
    notes: str = "",
    pcs_vertical: int | None = None,
    pcs_horizontal: int | None = None,
    all_sides_same: bool | None = None,
    bom_hint: str | None = None,
) -> dict[str, Any]:
    usage = infer_usage(name)
    # Prefer shutter/interlock when name implies it
    nl = name.lower()
    if any(k in nl for k in ("handle", "shutter", "top, bottom", "top bottom", "mesh shutter", "mesh adepetr", "mesh adapter")):
        if "interlock" not in nl and "track" not in nl:
            usage = "sash" if "mesh adapter" not in nl and "adepetr" not in nl else "other"
    if "interlock" in nl or "renf" in nl or "renfor" in nl:
        usage = "interlock"
    if "meeting" in nl:
        usage = "meeting"
    if "outer frame" in nl or (nl.startswith("outer") and "track" not in nl):
        usage = "frame"
    if "mullion" in nl:
        usage = "other"
    if "clip" in nl:
        usage = "other"
    if "door" in nl and "track" not in nl:
        usage = "sash"
    if "reducer" in nl:
        usage = "other"
    # Coating on sheet is always ₹/RFT
    ru = str(rate_unit or "kg").lower()
    if ru not in ("kg", "rft", "rmt", "pc"):
        ru = "kg"
    return {
        "id": f"{series_id}__{_slug(name)}",
        "name": name,
        "usage": usage,
        "usageLabel": _usage_label(usage),
        # FACE×DEPTH: widthMm/wMm = face (elevation); sectionDepthMm/hMm = depth
        "widthMm": face,
        "sectionDepthMm": depth,
        "standardLength": std_length,
        "weightKgPerMtrRaw": f"{weight} kg/m" if weight is not None else None,
        "weightKgPerMtr": weight,
        "heightLimit": None,
        "heightLimitMm": None,
        "wallThicknessMm": wall,
        "designNote": notes or use or None,
        "trackCount": parse_track_count(name),
        "glassOptions": parse_glass_options(name),
        "centerOpeningOnly": is_center_opening_only(name),
        "rate": rate,
        "rateUnit": ru,
        "coatingCost": coating,
        "coatingUnit": "rft",
        "use": use,
        "pcsVertical": pcs_vertical,
        "pcsHorizontal": pcs_horizontal,
        "allSidesSame": bool(all_sides_same) if all_sides_same is not None else None,
        "bomHint": bom_hint,
    }


def _setup_section_from_row(sec: Mapping[str, Any]) -> dict[str, Any]:
    face = sec.get("widthMm")
    depth = sec.get("sectionDepthMm")
    rate = sec.get("rate")
    rate_unit = str(sec.get("rateUnit") or "kg").lower()
    if rate_unit not in ("kg", "rft", "rmt", "pc"):
        rate_unit = "kg"
    # Re-parse use text when pcs missing (legacy imports)
    use_raw = sec.get("use") or sec.get("usageLabel") or ""
    parsed = parse_use_bom_counts(use_raw, section_name=str(sec.get("name") or ""))
    pcs_v = sec.get("pcsVertical")
    pcs_h = sec.get("pcsHorizontal")
    if pcs_v is None:
        pcs_v = parsed.get("pcsVertical")
    if pcs_h is None:
        pcs_h = parsed.get("pcsHorizontal")
    all_same = sec.get("allSidesSame")
    if all_same is None:
        all_same = parsed.get("allSidesSame")
    return {
        "name": sec.get("name") or "",
        "use": use_raw or parsed.get("use") or "",
        "wMm": face,   # elevation face
        "hMm": depth,  # into opening (not drawn as face width)
        "wallMm": sec.get("wallThicknessMm"),
        "weightKgPerM": sec.get("weightKgPerMtr"),
        "weightUnit": "m",
        "stdLength": sec.get("standardLength"),
        "stdLengthUnit": "rft",
        "rate": float(rate) if rate is not None else 0.0,
        "rateUnit": rate_unit,
        "coatingCost": float(sec.get("coatingCost") or 0) or 0.0,
        "coatingUnit": "rft",  # Excel coating column is always per RFT
        "pcsVertical": int(pcs_v) if pcs_v is not None else None,
        "pcsHorizontal": int(pcs_h) if pcs_h is not None else None,
        "allSidesSame": bool(all_same) if all_same is not None else None,
        "bomHint": sec.get("bomHint") or parsed.get("bomHint"),
        "notes": sec.get("designNote") or "",
    }


def parse_sliding_sheet(ws) -> list[dict[str, Any]]:
    series_list: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_shutters = False

    for row in ws.iter_rows(values_only=True):
        cells = list(row[:11]) if row else []
        if not any(c is not None and str(c).strip() != "" for c in cells):
            continue
        col0 = _clean(cells[0]) if len(cells) > 0 else None
        col1 = _clean(cells[1]) if len(cells) > 1 else None
        # Skip header
        if col0 and "seiers" in col0.lower() and "name" in col0.lower():
            continue
        if col0 and _is_group_label(col0):
            in_shutters = "shutter" in col0.lower()
            continue
        if col0 and _is_series_header(col0, col1):
            sid = _series_id_from_title(col0, family="sliding")
            current = {
                "id": sid,
                "title": col0.strip(),
                "displayName": col0.strip(),
                "family": "sliding",
                "productId": sid,
                "engineProductId": SERIES_PRODUCT_MAP.get(sid) or "29mm_sliding",
                "sections": [],
                "designOptions": [],
            }
            series_list.append(current)
            in_shutters = False
            # Same row may also carry first product
            if not col1:
                continue
        if current is None:
            continue
        name = col1
        if not name:
            continue
        face, depth = _parse_dims(cells[2] if len(cells) > 2 else None)
        wall = _num(cells[3] if len(cells) > 3 else None)
        weight = _num(cells[4] if len(cells) > 4 else None)
        rate, rate_unit = _parse_rate(cells[5] if len(cells) > 5 else None)
        std_len = _parse_std_length(cells[6] if len(cells) > 6 else None)
        use_pat = parse_use_bom_counts(
            cells[7] if len(cells) > 7 else None,
            cells[8] if len(cells) > 8 else None,
            cells[9] if len(cells) > 9 else None,
            section_name=name,
        )
        coating = _num(cells[10] if len(cells) > 10 else None)
        # Prefer shutter naming when under Shutters group
        display_name = name
        if in_shutters and "track" not in name.lower() and "shutter" not in name.lower() and "interlock" not in name.lower():
            if "handle" in name.lower() or "top" in name.lower() or "bottom" in name.lower():
                pass
        sec = _section_record(
            current["id"],
            name=display_name,
            face=face,
            depth=depth,
            wall=wall,
            weight=weight,
            rate=rate,
            rate_unit=rate_unit,
            std_length=std_len,
            coating=coating,
            use=str(use_pat.get("use") or ""),
            pcs_vertical=use_pat.get("pcsVertical"),
            pcs_horizontal=use_pat.get("pcsHorizontal"),
            all_sides_same=use_pat.get("allSidesSame"),
            bom_hint=use_pat.get("bomHint"),
        )
        current["sections"].append(sec)
    return [s for s in series_list if s["sections"]]


def parse_casement_sheet(ws) -> list[dict[str, Any]]:
    series_list: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for row in ws.iter_rows(values_only=True):
        cells = list(row[:11]) if row else []
        if not any(c is not None and str(c).strip() != "" for c in cells):
            continue
        col0 = _clean(cells[0]) if len(cells) > 0 else None
        col1 = _clean(cells[1]) if len(cells) > 1 else None
        if col0 and "seiers" in col0.lower():
            continue
        if col0 and _is_series_header(col0, col1):
            sid = _series_id_from_title(col0, family="casement")
            current = {
                "id": sid,
                "title": col0.strip(),
                "displayName": col0.strip(),
                "family": "casement",
                "productId": sid,
                "engineProductId": "casement_stub",
                "sections": [],
                "designOptions": [],
            }
            series_list.append(current)
            if not col1:
                continue
        if current is None or not col1:
            continue
        face, depth = _parse_dims(cells[2] if len(cells) > 2 else None)
        wall = _num(cells[3] if len(cells) > 3 else None)
        weight = _num(cells[4] if len(cells) > 4 else None)
        rate, rate_unit = _parse_rate(cells[5] if len(cells) > 5 else None)
        std_len = _parse_std_length(cells[6] if len(cells) > 6 else None)
        use_raw = _clean(cells[7] if len(cells) > 7 else None) or ""
        use_pat = parse_use_bom_counts(use_raw, section_name=col1)
        coating = _num(cells[8] if len(cells) > 8 else None)
        texture = _clean(cells[9] if len(cells) > 9 else None)
        wooden = _clean(cells[10] if len(cells) > 10 else None)
        notes = " · ".join(x for x in (use_pat.get("use") or use_raw, texture, wooden) if x)
        sec = _section_record(
            current["id"],
            name=col1,
            face=face,
            depth=depth,
            wall=wall,
            weight=weight,
            rate=rate,
            rate_unit=rate_unit,
            std_length=std_len,
            coating=coating,
            use=str(use_pat.get("use") or use_raw),
            notes=notes,
            pcs_vertical=use_pat.get("pcsVertical"),
            pcs_horizontal=use_pat.get("pcsHorizontal"),
            all_sides_same=use_pat.get("allSidesSame"),
            bom_hint=use_pat.get("bomHint"),
        )
        current["sections"].append(sec)
        for opt in (texture, wooden):
            if opt and opt not in current["designOptions"]:
                current["designOptions"].append(opt)
    return [s for s in series_list if s["sections"]]


def _hw_category(name: str, system: str) -> str:
    n = name.lower()
    s = system.lower()
    if "wheel" in n or "roller" in n:
        return "wheel"
    if "hinge" in n:
        return "hinge"
    if "friction" in n or "stay" in n or re.search(r"\bss\s*\d+\s*inch", n):
        return "accessory"
    if "lock" in n or "mortice" in n:
        return "lock"
    if "handle" in n:
        return "handle"
    if "brush" in n:
        return "brush"
    if "epdm" in n or "gaicket" in n or "gasket" in n:
        return "gasket"
    if "connect" in n or "wing" in n or "angle" in n or "cap" in n or "guid" in n or "rail" in n:
        return "connector" if "rail" not in n else "accessory"
    if "floor spring" in n:
        return "floor_spring"
    if "closer" in n:
        return "door_closer"
    if "caments" in s or "casement" in s:
        return "accessory"
    return "accessory"


def _hw_unit(rate_raw: Any, name: str) -> str:
    s = str(rate_raw or "").lower()
    n = name.lower()
    if "rft" in s:
        return "RFT"
    if "rmt" in s or "/m" in s:
        return "RM"
    if "brush" in n or "epdm" in n or "gasket" in n:
        return "RM"
    if "rail" in n:
        return "RFT"
    return "PC"


def parse_hardware_sheet(ws) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    system = "Sliding System"
    for row in ws.iter_rows(values_only=True):
        cells = list(row[:6]) if row else []
        if not any(c is not None and str(c).strip() != "" for c in cells):
            continue
        col0 = _clean(cells[0]) if len(cells) > 0 else None
        col1 = _clean(cells[1]) if len(cells) > 1 else None
        if col0 and "system name" in col0.lower():
            continue
        if col0 and not col1:
            # System / section header
            if not _is_group_label(col0):
                system = col0
            else:
                system = col0
            continue
        if col0 and col1 and _is_series_header(col0, None) and "option" in col0.lower():
            system = col0
        elif col0 and ("option" in col0.lower() or "system" in col0.lower() or "caments" in col0.lower()
                       or "hinges" in col0.lower() or "lock" in col0.lower()
                       or "connect" in col0.lower() or "side swing" in col0.lower()
                       or "lekin" in col0.lower() or "nhi" in col0.lower() or "karna" in col0.lower()):
            system = col0 if len(col0) > 3 else system
        if not col1:
            continue
        # Long Hindi instruction rows without rate → skip as products
        rate_raw = cells[4] if len(cells) > 4 else None
        rate = _num(rate_raw)
        if rate is None and not _clean(cells[2]) and not _clean(cells[3]):
            continue
        qty_window = cells[2] if len(cells) > 2 else None
        qty_shutter = cells[3] if len(cells) > 3 else None
        capacity = _num(cells[5] if len(cells) > 5 else None)
        # capacity may be "30 kg"
        if capacity is None and cells[5] is not None:
            capacity = _num(cells[5])
        origin = infer_origin_from_text(col1, system)
        brand = brand_for_origin(origin)
        unit = _hw_unit(rate_raw, col1)
        cat = _hw_category(col1, system)
        # Friction stay inch sizes
        inch_m = re.search(r"(\d+)\s*inch", col1.lower())
        remarks_parts = [f"system: {system}"]
        if qty_window is not None and str(qty_window).strip():
            remarks_parts.append(f"per window: {qty_window}")
        if qty_shutter is not None and str(qty_shutter).strip():
            remarks_parts.append(f"per shutter/door: {qty_shutter}")
        if capacity is not None:
            remarks_parts.append(f"capacity {capacity:g} kg")
        if inch_m:
            remarks_parts.append(f'{inch_m.group(1)}"')

        # Qty hint
        qty_per = _num(qty_shutter)
        if qty_per is None:
            qty_per = _num(qty_window)
        basis = "shutter"
        if qty_window is not None and str(qty_window).strip() and (qty_shutter is None or str(qty_shutter).strip() == ""):
            basis = "window"

        item = {
            "name": col1.strip(),
            "category": cat,
            "origin": origin,
            "brand": brand,
            "unit": unit,
            "rate": rate,
            "weightKg": None,
            "weightCapacityKg": capacity,
            "compatibleProducts": [],
            "compatibleSeries": [],
            "remarks": " · ".join(remarks_parts),
            "status": "active",
            "systemGroup": system,
            "qtyPer": qty_per,
            "basis": basis,
            "inch": float(inch_m.group(1)) if inch_m else None,
            "editableRate": True,
        }
        items.append(with_resolved_brand(item))
    return items


def parse_workbook(path: str | Path | None = None) -> dict[str, Any]:
    from openpyxl import load_workbook

    xlsx = find_excel_path(path)
    wb = load_workbook(xlsx, data_only=True, read_only=True)
    sheets = {str(n).strip().lower(): n for n in wb.sheetnames}

    def sheet(key: str):
        for k, n in sheets.items():
            if key in k:
                return wb[n]
        return None

    sliding = parse_sliding_sheet(sheet("sliding")) if sheet("sliding") is not None else []
    casement = parse_casement_sheet(sheet("caments") or sheet("casement")) if (
        sheet("caments") or sheet("casement")
    ) is not None else []
    hardware = parse_hardware_sheet(sheet("hardware")) if sheet("hardware") is not None else []
    empty_sheets = []
    for label in ("stile", "slim"):
        ws = sheet(label)
        if ws is not None:
            rows = sum(1 for r in ws.iter_rows(values_only=True) if any(c is not None and str(c).strip() for c in r))
            if rows <= 1:
                empty_sheets.append(label)

    wb.close()
    all_series = sliding + casement
    return {
        "source": xlsx.name,
        "sourcePath": str(xlsx),
        "version": 2,
        "importedAt": _now(),
        "sheets": {
            "sliding": len(sliding),
            "casement": len(casement),
            "hardware": len(hardware),
            "empty": empty_sheets,
        },
        "seriesCount": len(all_series),
        "sectionCount": sum(len(s["sections"]) for s in all_series),
        "hardwareCount": len(hardware),
        "series": all_series,
        "hardware": hardware,
    }


def _section_name_l(sec: Mapping[str, Any] | None) -> str:
    return str((sec or {}).get("name") or "").strip().lower()


def _is_mesh_adapter_name(nl: str) -> bool:
    """Excel typos: mesh adepetr / adeptor / adapter."""
    return any(k in nl for k in ("adapt", "adept", "adepet", "adeptor", "adepetr"))


def _is_mesh_section(sec: Mapping[str, Any] | None) -> bool:
    if not isinstance(sec, Mapping):
        return False
    usage = str(sec.get("usage") or "").lower()
    nl = _section_name_l(sec)
    if _is_mesh_adapter_name(nl):
        return False
    if usage == "mesh":
        return True
    if "mesh" in nl:
        return True
    return False


def _is_track_section(sec: Mapping[str, Any] | None) -> bool:
    if not isinstance(sec, Mapping):
        return False
    usage = str(sec.get("usage") or "").lower()
    nl = _section_name_l(sec)
    if _is_mesh_section(sec):
        return False
    if usage.startswith("track"):
        return True
    return ("track" in nl or "trck" in nl) and "mesh" not in nl


def _is_glass_sash_section(sec: Mapping[str, Any] | None) -> bool:
    """Glass / door shutter profiles — never mesh, never outer track."""
    if not isinstance(sec, Mapping):
        return False
    if _is_mesh_section(sec) or _is_track_section(sec):
        return False
    usage = str(sec.get("usage") or "").lower()
    nl = _section_name_l(sec)
    if "interlock" in nl or "reducer" in nl or "meeting" in nl:
        return False
    if "adapt" in nl or "adept" in nl:
        return False
    if usage in ("sash", "door", "leaf"):
        return True
    if "handle" in nl or "hnadle" in nl:
        return True
    if "all side" in nl or nl in ("shutter", "sash", "door"):
        return True
    if any(k in nl for k in ("top", "bottom", "horizon")) and "track" not in nl:
        return True
    if "shutter" in nl or "sash" in nl:
        return True
    return False


def _track_tid(tc: float) -> str:
    return "2.5" if abs(float(tc) - 2.5) < 0.01 else str(int(float(tc)))


def _rail_count_for_tc(tc: float) -> int:
    if float(tc) < 3:
        return 2
    if float(tc) < 4:
        return 3
    return 4


def _classify_track_row(sec: Mapping[str, Any]) -> str:
    """vertical | horizontal | all — how this track row maps onto outer frame sides."""
    usage = str(sec.get("usage") or "").lower()
    nl = _section_name_l(sec)
    if "vertical" in usage or (
        any(k in nl for k in ("vertical", "left", "right", "jamb"))
        and not any(k in nl for k in ("top", "bottom", "horizon"))
    ):
        return "vertical"
    if "horizontal" in usage or any(k in nl for k in ("top", "bottom", "horizon")):
        return "horizontal"
    if "all" in nl:
        return "all"
    return "all"


def _build_sliding_setup(series: Mapping[str, Any], hw_items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sections = list(series.get("sections") or [])
    tracks = [s for s in sections if _is_track_section(s)]
    shutters = [s for s in sections if _is_glass_sash_section(s)]
    interlocks = [
        s for s in sections
        if str(s.get("usage") or "").lower() == "interlock"
        or "interlock" in _section_name_l(s)
    ]
    meetings = [
        s for s in sections
        if str(s.get("usage") or "").lower() == "meeting" or "meeting" in _section_name_l(s)
    ]
    mesh = [s for s in sections if _is_mesh_section(s) or (
        "mesh" in _section_name_l(s) and "adapt" not in _section_name_l(s) and "adept" not in _section_name_l(s)
    )]

    # Group track rows by track count so OUTER gets the selected track only;
    # when Excel lists separate vertical + top/bottom rows, keep both sides.
    by_tc: dict[float, list[Mapping[str, Any]]] = {}
    for t in tracks:
        tc = t.get("trackCount")
        if tc is None:
            tc = parse_track_count(t.get("name"))
        if tc is None:
            continue
        by_tc.setdefault(float(tc), []).append(t)

    track_options: list[dict[str, Any]] = []
    seen: set[str] = set()
    has_split_track = False
    for tc in sorted(by_tc.keys()):
        rows = by_tc[tc]
        tid = _track_tid(tc)
        if tid in seen:
            continue
        seen.add(tid)
        vert = next((r for r in rows if _classify_track_row(r) == "vertical"), None)
        horiz = next((r for r in rows if _classify_track_row(r) == "horizontal"), None)
        allside = next((r for r in rows if _classify_track_row(r) == "all"), None)
        if vert and horiz:
            has_split_track = True
            vsec = _setup_section_from_row(vert)
            hsec = _setup_section_from_row(horiz)
            track_options.append({
                "id": tid,
                "label": f"{tid} track",
                "railCount": _rail_count_for_tc(tc),
                "sides": {
                    "vertical": vsec,
                    "top": hsec,
                    "bottom": hsec,
                    "leftVertical": vsec,
                    "rightVertical": vsec,
                    "all": hsec,
                },
                "weightKgPerM": vsec.get("weightKgPerM"),
                "rate": vsec.get("rate"),
                "rateUnit": vsec.get("rateUnit"),
            })
        else:
            src = allside or vert or horiz or rows[0]
            sec = _setup_section_from_row(src)
            track_options.append({
                "id": tid,
                "label": f"{tid} track",
                "railCount": _rail_count_for_tc(tc),
                "sides": {"all": sec, "top": sec, "bottom": sec, "vertical": sec},
                "weightKgPerM": sec.get("weightKgPerM"),
                "rate": sec.get("rate"),
                "rateUnit": sec.get("rateUnit"),
            })
    for tid in ("2", "2.5", "3", "4"):
        if tid not in seen:
            track_options.append({
                "id": tid,
                "label": f"{tid} track",
                "railCount": 2 if float(tid) < 3 else int(float(tid)),
                "sides": {},
            })

    track_mode = "verticals_same_h_diff" if has_split_track else "all_sides_same"

    # Glass shutters only (mesh stays in mesh block). Handle typo "hnadle" included.
    handle = next(
        (s for s in shutters if "handle" in _section_name_l(s) or "hnadle" in _section_name_l(s)),
        None,
    )
    all_side_sh = next(
        (
            s for s in shutters
            if "all side" in _section_name_l(s) or _section_name_l(s) in ("shutter", "sash", "door")
        ),
        None,
    )
    top_bot = next(
        (
            s for s in shutters
            if any(k in _section_name_l(s) for k in ("top", "bottom", "horizon"))
            and "handle" not in _section_name_l(s)
            and "hnadle" not in _section_name_l(s)
        ),
        None,
    )
    # Combined "handle side, top, bottom" → one section for V+H
    if handle and top_bot is None and any(k in _section_name_l(handle) for k in ("top", "bottom")):
        top_bot = handle
    if handle is None:
        handle = all_side_sh or (shutters[0] if shutters else None)
    if all_side_sh is None and handle is not None:
        # V2 H2 handle/shutter row = all-sides glass sash for that series
        parsed = parse_use_bom_counts(handle.get("use"), section_name=str(handle.get("name") or ""))
        if parsed.get("allSidesSame") and top_bot is None:
            all_side_sh = handle

    slim = next(
        (s for s in interlocks if "slim" in _section_name_l(s)),
        None,
    )
    if slim is None:
        slim = next(
            (s for s in interlocks if "renf" not in _section_name_l(s) and "renfor" not in _section_name_l(s)),
            interlocks[0] if interlocks else None,
        )
    renf = next(
        (s for s in interlocks if "renf" in _section_name_l(s) or "renfor" in _section_name_l(s)),
        None,
    )
    if renf is None and len(interlocks) > 1:
        renf = next((s for s in interlocks if s is not slim), interlocks[-1])
    glass_reducer = next(
        (s for s in sections if "reducer" in _section_name_l(s)),
        None,
    )

    shutter_mode = "split"
    if all_side_sh and top_bot is None and (handle is None or handle is all_side_sh or handle == all_side_sh):
        shutter_mode = "all_sides_same"
    elif handle and top_bot is None:
        parsed_h = parse_use_bom_counts(handle.get("use"), section_name=str(handle.get("name") or ""))
        if parsed_h.get("allSidesSame"):
            shutter_mode = "all_sides_same"
            all_side_sh = all_side_sh or handle
    elif not handle and not all_side_sh and not top_bot:
        shutter_mode = "all_sides_same"

    # Hardware pack from catalogue items (sliding group)
    def pick_hw(*needles: str) -> Mapping[str, Any] | None:
        for it in hw_items:
            nm = (it.get("name") or "").lower()
            sys = (it.get("systemGroup") or "").lower()
            if "caments" in sys or "friction" in sys or "hinge" in sys:
                continue
            if all(n in nm for n in needles):
                return it
        return None

    wheel = pick_hw("wheel", "2x2") or pick_hw("wheel")
    outer_c = pick_hw("outer", "connect") or pick_hw("outer connect")
    shut_c = pick_hw("shutter", "connect")
    wings = pick_hw("wing") or pick_hw("angle")
    brush = pick_hw("brush")
    epdm = pick_hw("epdm")
    lock = pick_hw("single", "point") or pick_hw("lock")

    brand_default = "HIVIC"
    hw_pack = {
        "trackConnectors": {
            "qty": float((outer_c or {}).get("qtyPer") or 4),
            "rate": float((outer_c or {}).get("rate") or 40),
            "unit": "PC",
            "brand": resolve_hardware_brand(outer_c) if outer_c else brand_default,
            "notes": "editable default from Excel",
        },
        "shutterConnectors": {
            "qty": float((shut_c or {}).get("qtyPer") or 4),
            "rate": float((shut_c or {}).get("rate") or 30),
            "unit": "PC",
            "brand": resolve_hardware_brand(shut_c) if shut_c else brand_default,
        },
        "epdm": {
            "ratePerM": float((epdm or {}).get("rate") or 19),
            "formula": "height_m*4 + width_m*4",
            "brand": resolve_hardware_brand(epdm) if epdm else brand_default,
        },
        "brush": {
            "ratePerM": float((brush or {}).get("rate") or 9),
            "formula": "height_m*4 + width_m*4",
            "brand": resolve_hardware_brand(brush) if brush else brand_default,
        },
        "wings": {
            "rate": float((wings or {}).get("rate") or 5),
            "qtyAllSidesSame": 8,
            "qtySplit": 4,
            "brand": resolve_hardware_brand(wings) if wings else brand_default,
        },
        "lock": {
            "type": "single_point",
            "rate": float((lock or {}).get("rate") or 450),
            "unit": "SET",
            "brand": resolve_hardware_brand(lock) if lock else brand_default,
        },
        "wheels": {
            "qtyPerShutter": float((wheel or {}).get("qtyPer") or 2),
            "rate": float((wheel or {}).get("rate") or 70),
            "unit": "PC",
            "brand": resolve_hardware_brand(wheel) if wheel else brand_default,
            "weightCapacityKg": (wheel or {}).get("weightCapacityKg"),
            "name": (wheel or {}).get("name") or "Wheel 2x2 SS",
        },
    }

    # Freeform hardware list (all sliding-compatible, rates editable)
    hw_list = []
    for it in hw_items:
        sys = (it.get("systemGroup") or "").lower()
        if "caments" in sys or "friction" in sys:
            continue
        if any(k in sys for k in ("hinge", "lock option")) and "sliding" not in sys and "wheel" not in sys and "lock, handle" not in sys:
            if "sliding" not in sys and "track" not in sys and "lock, handle" not in sys and "wheel" not in sys:
                if "connect" not in sys and "wing" not in (it.get("name") or "").lower():
                    # skip pure casement blocks
                    if "hinge" in sys or (it.get("category") == "hinge"):
                        continue
        hw_list.append({
            "name": it.get("name"),
            "brand": it.get("brand"),
            "unit": it.get("unit") or "PC",
            "rate": it.get("rate") or 0,
            "qtyPer": it.get("qtyPer") or 0,
            "basis": it.get("basis") or "shutter",
            "notes": it.get("remarks") or "",
        })

    meeting = meetings[0] if meetings else None
    mesh_adapters = [
        m for m in sections
        if "mesh" in _section_name_l(m) and _is_mesh_adapter_name(_section_name_l(m))
    ]
    mesh_adapter = mesh_adapters[0] if mesh_adapters else None
    mesh_shutter = next(
        (m for m in mesh if "shutter" in _section_name_l(m)),
        next((m for m in mesh if not _is_mesh_adapter_name(_section_name_l(m))), None),
    )

    # Defined (non-empty) track options first for active default
    defined_opts = [o for o in track_options if (o.get("sides") or {}).get("all") or (o.get("sides") or {}).get("vertical")]
    active_tid = (defined_opts[0]["id"] if defined_opts else (track_options[0]["id"] if track_options else "2"))

    handle_sec = _setup_section_from_row(handle) if handle else {}
    all_side_sec = (
        _setup_section_from_row(all_side_sh)
        if all_side_sh and shutter_mode == "all_sides_same"
        else {}
    )
    top_sec = _setup_section_from_row(top_bot) if top_bot else {}
    # Split mode still needs a handle vertical — never leave glass sash empty.
    if shutter_mode == "split" and not handle_sec.get("name") and all_side_sh:
        handle_sec = _setup_section_from_row(all_side_sh)

    raw = {
        "type": "sliding",
        "imported": False,
        "notes": f"Loaded from {series.get('title')} — rates editable in Series Setup",
        "sliding": {
            "trackMode": track_mode,
            "bomPattern": "all_side_4" if track_mode == "all_sides_same" else "v2_t1_b1",
            "activeTrackOption": active_tid,
            "trackOptions": track_options,
            "shutters": {
                "mode": shutter_mode,
                "allSides": all_side_sec,
                "handleSide": handle_sec if shutter_mode == "split" else (handle_sec or all_side_sec),
                "top": top_sec if shutter_mode == "split" else {},
                "bottom": top_sec if shutter_mode == "split" else {},
                "interlockSlim": _setup_section_from_row(slim) if slim else {},
                "interlockRenf": _setup_section_from_row(renf) if renf else {},
                "glassReducer": _setup_section_from_row(glass_reducer) if glass_reducer else {},
            },
            "meeting": {
                "enabled": bool(meeting),
                "section": _setup_section_from_row(meeting) if meeting else {},
            },
            "mesh": {
                "compatible": bool(mesh_shutter or mesh_adapter),
                "sameAsShutter": mesh_shutter is None,
                "adapter": {
                    "sameAllSides": True,
                    "section": _setup_section_from_row(mesh_adapter) if mesh_adapter else {},
                },
                "meshSection": _setup_section_from_row(mesh_shutter) if mesh_shutter else {},
            },
            "hardware": hw_list[:24],
            "hardwarePack": hw_pack,
            "costing": {"costEngine": "live", "cutFromOwnStock": True, "projectWastageReuse": True},
        },
    }
    return normalize_setup(raw)


def _build_casement_setup(series: Mapping[str, Any], hw_items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sections = list(series.get("sections") or [])

    def find(*needles: str) -> Mapping[str, Any] | None:
        for s in sections:
            nl = (s.get("name") or "").lower()
            if all(n in nl for n in needles):
                return s
        return None

    outer = find("outer", "frame") or find("outer")
    outer_grill = find("grill")
    mull_slim = find("mullion", "slim") or find("mullion")
    mull_big = find("mullion", "big") or find("mullion")
    if mull_slim and mull_big and mull_slim is mull_big:
        mulls = [s for s in sections if "mullion" in (s.get("name") or "").lower()]
        if len(mulls) >= 2:
            mull_slim, mull_big = mulls[0], mulls[1]
    door_slim = find("door", "slim") or find("shutter", "sg") or find("shutter")
    door_big = find("door", "big") or find("shutter")
    clip_sg = find("clip", "sg") or find("clip")
    clip_dg = find("clip", "dg")

    # Hardware
    def pick(*needles: str, system_has: str | None = None) -> Mapping[str, Any] | None:
        for it in hw_items:
            nm = (it.get("name") or "").lower()
            sys = (it.get("systemGroup") or "").lower()
            if system_has and system_has not in sys and "caments" not in sys and "friction" not in sys and "hinge" not in sys and "lock option" not in sys:
                continue
            if all(n in nm for n in needles):
                return it
        return None

    stays = [it for it in hw_items if it.get("inch") or "inch" in (it.get("name") or "").lower()]
    stay_lengths = []
    for it in stays:
        inch = it.get("inch") or _num(it.get("name"))
        if inch:
            stay_lengths.append({"inch": float(inch), "rate": float(it.get("rate") or 0), "label": f'{float(inch):g}"'})
    hinge = pick("stander") or pick("standard") or pick("hinge")
    lock = next((it for it in hw_items if "single" in (it.get("name") or "").lower() and "lock" in (it.get("systemGroup") or "").lower()), None)
    lock = lock or pick("single")
    epdm = pick("epdm")
    outer_c = next((it for it in hw_items if "outer connect" in (it.get("name") or "").lower()), None)
    mull_c = next((it for it in hw_items if "mullion connect" in (it.get("name") or "").lower()), None)
    door_c = next((it for it in hw_items if "door connect" in (it.get("name") or "").lower()), None)
    wings = next((it for it in hw_items if "wing" in (it.get("name") or "").lower()), None)

    brand_imp = "CMECH"
    brand_ind = "HIVIC"

    raw = {
        "type": "casement",
        "imported": False,
        "notes": f"Loaded from {series.get('title')} — rates editable in Series Setup",
        "casement": {
            "kind": "normal",
            "outerFrame": {
                "mode": "all_sides_same",
                "variants": {
                    "plain": _setup_section_from_row(outer) if outer else {},
                    "grills": _setup_section_from_row(outer_grill) if outer_grill else (_setup_section_from_row(outer) if outer else {}),
                    "grills_mesh": _setup_section_from_row(outer_grill) if outer_grill else {},
                },
            },
            "mullions": {
                "slim": _setup_section_from_row(mull_slim) if mull_slim else {},
                "big": _setup_section_from_row(mull_big) if mull_big else {},
            },
            "doors": {
                "mode": "all_sides_same",
                "slim": _setup_section_from_row(door_slim) if door_slim else {},
                "big": _setup_section_from_row(door_big) if door_big else {},
            },
            "glass": {
                "sgClip": _setup_section_from_row(clip_sg) if clip_sg else {},
                "dgClip": _setup_section_from_row(clip_dg) if clip_dg else {},
            },
            "hardwarePack": {
                "hinges": {
                    "enabled": True,
                    "name": (hinge or {}).get("name") or "Standard hinge",
                    "brand": resolve_hardware_brand(hinge) if hinge else brand_ind,
                    "weightCapacityKg": (hinge or {}).get("weightCapacityKg"),
                    "qty": float((hinge or {}).get("qtyPer") or 2),
                    "rate": float((hinge or {}).get("rate") or 90),
                    "unit": "PC",
                },
                "stay": {
                    "kind": "side_swing",
                    "enabled": True,
                    "name": "Friction stay SS",
                    "brand": brand_imp,
                    "selectedInch": 10,
                    "lengths": stay_lengths or None,
                    "rate": next((float(x["rate"]) for x in stay_lengths if x.get("inch") == 10), 550),
                    "unit": "SET",
                    "setsPerDoor": 1,
                },
                "topHungStay": {
                    "kind": "top_hung",
                    "enabled": True,
                    "name": "Top-hung friction stay",
                    "brand": brand_imp,
                    "selectedInch": 10,
                    "lengths": stay_lengths or None,
                    "rate": next((float(x["rate"]) for x in stay_lengths if x.get("inch") == 10), 550),
                    "unit": "SET",
                    "setsPerDoor": 1,
                },
                "lock": {
                    "name": (lock or {}).get("name") or "Single point",
                    "brand": resolve_hardware_brand(lock) if lock else brand_ind,
                    "rate": float((lock or {}).get("rate") or 450),
                    "unit": "SET",
                    "qty": 1,
                },
                "connectors": {
                    "outer": {"qty": 4, "rate": float((outer_c or {}).get("rate") or 40), "brand": brand_ind},
                    "mullion": {"qty": 2, "rate": float((mull_c or {}).get("rate") or 40), "brand": brand_ind},
                    "door": {"qty": 4, "rate": float((door_c or {}).get("rate") or 40), "brand": brand_ind},
                },
                "wings": {"qty": 8, "rate": float((wings or {}).get("rate") or 5), "brand": brand_ind},
                "gasket": {
                    "epdm": {"ratePerM": float((epdm or {}).get("rate") or 19), "brand": brand_ind},
                },
            },
            "costing": {"costEngine": "live", "soldPerRft": False},
        },
    }
    return normalize_setup(raw)


def rebuild_setups_from_catalogue(
    *,
    series_ids: Sequence[str] | None = None,
    hardware: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild product.setup from section catalogue without wiping quotes / meta.

    Fixes track→outer-only and glass-shutter (not mesh) section mapping for every
    active Excel series so live design_cost uses the correct rates/weights.
    """
    from WEOS.factory.section_catalogue import load_catalogue

    cat = load_catalogue()
    hw = list(hardware or [])
    if not hw:
        try:
            from WEOS.factory.hardware_catalogue import list_hardware

            hw = list(list_hardware() or [])
        except Exception:
            hw = []

    wanted = {str(x) for x in series_ids} if series_ids else None
    updated: list[str] = []
    skipped: list[str] = []
    for series in cat.get("series") or []:
        if not isinstance(series, Mapping):
            continue
        sid = str(series.get("id") or "")
        if not sid:
            continue
        if wanted is not None and sid not in wanted:
            continue
        # Refresh usage tags from names so handle/hnadle/mesh classify correctly
        secs = []
        for sec in series.get("sections") or []:
            if not isinstance(sec, Mapping):
                continue
            row = dict(sec)
            row["usage"] = infer_usage(str(row.get("name") or ""))
            secs.append(row)
        series_fix = dict(series)
        series_fix["sections"] = secs
        fam = str(series_fix.get("family") or "sliding").lower()
        if fam == "casement":
            setup = _build_casement_setup(series_fix, hw)
        else:
            setup = _build_sliding_setup(series_fix, hw)
        pdir = products_dir() / sid
        meta_path = pdir / "product.json"
        if not meta_path.is_file():
            _write_product(series_fix, setup, family="casement" if fam == "casement" else "sliding")
            updated.append(sid)
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            skipped.append(sid)
            continue
        if not isinstance(meta, dict):
            skipped.append(sid)
            continue
        # Preserve labour/profit overrides on costing when present
        old_setup = meta.get("setup") if isinstance(meta.get("setup"), Mapping) else {}
        old_cost = {}
        if fam == "casement":
            old_cost = ((old_setup.get("casement") or {}).get("costing") or {}) if isinstance(old_setup, Mapping) else {}
            new_sl = setup.get("casement") if isinstance(setup.get("casement"), Mapping) else {}
            if isinstance(old_cost, Mapping) and new_sl:
                merged = dict(new_sl.get("costing") or {})
                for k in ("labourPerSft", "profitPercent", "installationPerSft", "wastagePercent"):
                    if old_cost.get(k) not in (None, ""):
                        merged[k] = old_cost.get(k)
                merged["costEngine"] = "live"
                new_sl = dict(new_sl)
                new_sl["costing"] = merged
                setup = dict(setup)
                setup["casement"] = new_sl
        else:
            old_cost = ((old_setup.get("sliding") or {}).get("costing") or {}) if isinstance(old_setup, Mapping) else {}
            new_sl = setup.get("sliding") if isinstance(setup.get("sliding"), Mapping) else {}
            if isinstance(old_cost, Mapping) and new_sl:
                merged = dict(new_sl.get("costing") or {})
                for k in ("labourPerSft", "profitPercent", "installationPerSft", "wastagePercent",
                          "cutFromOwnStock", "projectWastageReuse"):
                    if old_cost.get(k) not in (None, ""):
                        merged[k] = old_cost.get(k)
                merged["costEngine"] = "live"
                new_sl = dict(new_sl)
                new_sl["costing"] = merged
                setup = dict(setup)
                setup["sliding"] = new_sl
        meta["setup"] = setup
        meta["ratesEditable"] = True
        meta["status"] = meta.get("status") or "active"
        if str(meta.get("status") or "").lower() in ("stub", ""):
            meta["status"] = "active"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Ensure quotation marks live engine without wiping rates/history fields
        qpath = pdir / "rules" / "quotation.json"
        if qpath.is_file():
            try:
                qdoc = json.loads(qpath.read_text(encoding="utf-8-sig"))
            except Exception:
                qdoc = {}
            if isinstance(qdoc, dict):
                qdoc["costEngine"] = "live"
                qdoc["ratesEditable"] = True
                # Keep stub geometry flag; do not invent manualRate
                qdoc.setdefault("stub", True)
                qpath.write_text(json.dumps(qdoc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Mirror usage fixes into per-series section JSON
        sec_path = products_dir() / "sections" / f"{sid}.json"
        if sec_path.is_file():
            try:
                sdoc = json.loads(sec_path.read_text(encoding="utf-8-sig"))
                if isinstance(sdoc, dict):
                    sdoc["sections"] = secs
                    sec_path.write_text(json.dumps(sdoc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            except Exception:
                pass
        updated.append(sid)

    # Refresh aggregate catalogue usage tags
    try:
        cat2 = dict(cat)
        new_series = []
        for series in cat.get("series") or []:
            if not isinstance(series, Mapping):
                continue
            sid = str(series.get("id") or "")
            if wanted is not None and sid not in wanted:
                new_series.append(series)
                continue
            secs = []
            for sec in series.get("sections") or []:
                if not isinstance(sec, Mapping):
                    continue
                row = dict(sec)
                row["usage"] = infer_usage(str(row.get("name") or ""))
                secs.append(row)
            row = dict(series)
            row["sections"] = secs
            new_series.append(row)
        cat2["series"] = new_series
        persist_catalogue(cat2)
    except Exception:
        pass

    return {"ok": True, "updated": updated, "skipped": skipped, "count": len(updated)}


def _write_product(series: Mapping[str, Any], setup: Mapping[str, Any], *, family: str) -> Path:
    from WEOS.factory.section_catalogue import _library_catalogue_block, specs_summary_for_series

    sid = str(series["id"])
    pdir = products_dir() / sid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "rules").mkdir(exist_ok=True)
    catalogue_block = _library_catalogue_block(series)
    try:
        specs = specs_summary_for_series(sid)
    except Exception:
        specs = {}
    hw_brand = "HIVIC"
    # Prefer brand from setup hardware pack
    try:
        if family == "sliding":
            pack = ((setup.get("sliding") or {}).get("hardwarePack") or {})
            hw_brand = (pack.get("wheels") or {}).get("brand") or (pack.get("lock") or {}).get("brand") or hw_brand
        else:
            pack = ((setup.get("casement") or {}).get("hardwarePack") or {})
            hw_brand = (pack.get("hinges") or {}).get("brand") or hw_brand
    except Exception:
        pass

    meta = {
        "id": sid,
        "displayName": series.get("displayName") or series.get("title") or sid,
        "productType": "sliding" if family == "sliding" else "casements",
        "category": "Windows",
        "units": "mm",
        "version": 1,
        "status": "active",
        "description": f"Loaded from profile/hardwares Excel — {series.get('title') or sid}. Rates editable in Series Setup.",
        "tagline": series.get("title") or "",
        "warranty": "",
        "heroImage": "/static/products/placeholder.svg",
        "gallery": [],
        "sectionDrawings": [],
        "specifications": {
            "profileSeries": series.get("title"),
            "sectionSizeMm": catalogue_block.get("sizeMm"),
            "standardLength": catalogue_block.get("standardLength"),
            "wallThicknessMm": specs.get("wallThicknessMm"),
            "track": specs.get("track"),
            "sash": specs.get("sash"),
            "interlock": specs.get("interlock"),
            "hardwareBrand": hw_brand,
            "hardwareOrigin": "indian",
        },
        "materials": [],
        "formulas": {},
        "pdfLayout": {"customer": "marqt_customer", "factory": "woodenmax_factory"},
        "brand": "woodenmax",
        "sectionSeries": sid,
        "linkedProductId": "29mm_sliding" if family == "sliding" else "casement_stub",
        "catalogue": catalogue_block,
        "setup": setup,
        "sourceExcel": "profile and hardwares weos.xlsx",
        "ratesEditable": True,
    }
    meta_path = pdir / "product.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    qpath = pdir / "rules" / "quotation.json"
    # Keep quotation.stub so generate_job uses renderable stub geometry; live
    # Al/coat/glass/HW still come from design_cost overlay (ratesEditable + setup).
    qpath.write_text(
        json.dumps(
            {
                "currency": "INR",
                "labourPerOpening": 0,
                "markupPercent": 15,
                "gstPercent": 18,
                "stub": True,
                "manualRatePerOpening": 0,
                "rates": {},
                "ratesEditable": True,
                "costEngine": "live",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return meta_path


def _hide_dummy_stubs(keep_ids: set[str]) -> list[str]:
    hidden: list[str] = []
    for sid in DUMMY_SLIDING_STUBS:
        if sid in keep_ids or sid in KEEP_PRODUCTS:
            continue
        pdir = products_dir() / sid
        meta_path = pdir / "product.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        meta["status"] = "hidden"
        meta["hiddenReason"] = "Superseded by profile and hardwares weos.xlsx import"
        meta["hiddenAt"] = _now()
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Archive section JSON if present
        sec = products_dir() / "sections" / f"{sid}.json"
        if sec.is_file():
            archive = products_dir() / "sections" / "_archived"
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(sec), str(archive / f"{sid}.json"))
        hidden.append(sid)
    return hidden


def _seed_hardware_library(items: Sequence[Mapping[str, Any]], *, force: bool = False) -> list[str]:
    created: list[str] = []
    # Clear prior Excel-seeded items when force
    sentinel = catalogue_dir() / "_profile_hw_seeded.json"
    if force and sentinel.is_file():
        try:
            prev = json.loads(sentinel.read_text(encoding="utf-8"))
            for hid in prev.get("ids") or []:
                p = catalogue_dir() / f"{hid}.json"
                if p.is_file():
                    p.unlink()
        except Exception:
            pass

    for raw in items:
        spec = with_resolved_brand(dict(raw))
        # Stable id from name + capacity + rate
        cap = spec.get("weightCapacityKg")
        suffix = f"_{int(cap)}kg" if cap else ""
        rate = spec.get("rate")
        rate_sfx = f"_{int(rate)}" if rate is not None else ""
        hid = f"hw_{_slug(spec.get('category') or 'acc')}_{_slug(spec.get('name') or 'item')}{suffix}{rate_sfx}"
        spec["id"] = hid
        spec["status"] = "active"
        spec["editableRate"] = True
        item = build_hardware_item(spec)
        # Preserve origin / capacity beyond build_hardware_item
        item["origin"] = spec.get("origin") or normalize_origin("indian")
        item["brand"] = resolve_hardware_brand(item)
        item["weightCapacityKg"] = spec.get("weightCapacityKg")
        item["qtyPer"] = spec.get("qtyPer")
        item["basis"] = spec.get("basis")
        item["systemGroup"] = spec.get("systemGroup")
        item["inch"] = spec.get("inch")
        item["editableRate"] = True
        item["remarks"] = spec.get("remarks") or ""
        (catalogue_dir() / f"{item['id']}.json").write_text(
            json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        created.append(item["id"])

    # Update legacy seed items with brands if empty
    for path in catalogue_dir().glob("hw_*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if doc.get("brand"):
            continue
        updated = with_resolved_brand(doc)
        path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")

    sentinel.write_text(
        json.dumps({"ok": True, "ids": created, "count": len(created), "at": _now()}, indent=2),
        encoding="utf-8",
    )
    return created


def _enrich_29mm_sliding(series_29: Mapping[str, Any] | None, hw_items: Sequence[Mapping[str, Any]]) -> None:
    """Attach editable setup to the live manufacturing product without wiping engines."""
    if not series_29:
        return
    setup = _build_sliding_setup(series_29, hw_items)
    path = products_dir() / "29mm_sliding" / "product.json"
    if not path.is_file():
        return
    meta = json.loads(path.read_text(encoding="utf-8-sig"))
    meta["setup"] = setup
    specs = dict(meta.get("specifications") or {})
    specs["hardwareBrand"] = "HIVIC"
    specs["hardwareOrigin"] = "indian"
    meta["specifications"] = specs
    meta["ratesEditable"] = True
    meta["sourceExcel"] = "profile and hardwares weos.xlsx"
    # Keep engine hidden from Product Library (Excel 29mm_premium is the selectable series)
    meta["status"] = "hidden"
    meta["hiddenReason"] = "Manufacturing engine — use Excel series (e.g. 29mm_premium) in Product Library"
    meta["hiddenAt"] = _now()
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _enrich_casement_stub(series_40: Mapping[str, Any] | None, hw_items: Sequence[Mapping[str, Any]]) -> None:
    if not series_40:
        return
    setup = _build_casement_setup(series_40, hw_items)
    path = products_dir() / "casement_stub" / "product.json"
    if not path.is_file():
        return
    meta = json.loads(path.read_text(encoding="utf-8-sig"))
    meta["setup"] = setup
    # Do NOT mirror Excel displayName/status — that duplicated 40mm_casement_standard in the library
    meta["displayName"] = "Casement (manufacturing engine)"
    meta["description"] = "Casement manufacturing engine linked by Excel series — not shown in Product Library."
    meta["status"] = "hidden"
    meta["hiddenReason"] = (
        "Manufacturing engine — use Excel casement series "
        "(40mm_casement_standard / 50mm_casement_prestige) in Product Library"
    )
    meta["hiddenAt"] = _now()
    specs = dict(meta.get("specifications") or {})
    specs["hardwareBrand"] = "HIVIC"
    specs["hardwareOrigin"] = "indian"
    specs["profileSeries"] = series_40.get("title")
    meta["specifications"] = specs
    meta["sectionSeries"] = series_40.get("id")
    meta["ratesEditable"] = True
    meta["sourceExcel"] = "profile and hardwares weos.xlsx"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _hide_catalog_engines() -> list[str]:
    """Soft-hide manufacturing engines so Product Library only lists Excel series."""
    hidden: list[str] = []
    for sid in CATALOG_HIDDEN_ENGINES:
        pdir = products_dir() / sid
        meta_path = pdir / "product.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if str(meta.get("status") or "").lower() == "hidden":
            hidden.append(sid)
            continue
        meta["status"] = "hidden"
        if sid == "casement_stub":
            meta["displayName"] = "Casement (manufacturing engine)"
            meta["hiddenReason"] = (
                "Manufacturing engine — use Excel casement series "
                "(40mm_casement_standard / 50mm_casement_prestige) in Product Library"
            )
        else:
            meta["hiddenReason"] = (
                "Manufacturing engine — use Excel series (e.g. 29mm_premium) in Product Library"
            )
        meta["hiddenAt"] = _now()
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        hidden.append(sid)
    return hidden


def _hide_non_excel_casements() -> list[str]:
    """Soft-hide casement clones so only Excel series remain selectable.

    ``casement_stub`` stays on disk (hidden engine). ``bathroom_ventilator`` is a
    separate product type linked to ``50mm_casement_prestige``, not a casement
    series row.
    """
    hidden: list[str] = []
    root = products_dir()
    if not root.is_dir():
        return hidden
    seen_names: dict[str, str] = {}
    for pdir in sorted(root.iterdir()):
        meta_path = pdir / "product.json"
        if not pdir.is_dir() or not meta_path.is_file():
            continue
        sid = pdir.name
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        pt = str(meta.get("productType") or "").strip().lower()
        if pt not in ("casements", "casement"):
            continue
        if sid in EXCEL_CASEMENT_SERIES:
            dn = str(meta.get("displayName") or sid).strip().lower()
            seen_names[dn] = sid
            continue
        # Engines / clones — keep loadable but not selectable
        if str(meta.get("status") or "").lower() == "hidden":
            hidden.append(sid)
            continue
        meta["status"] = "hidden"
        if sid == "casement_stub":
            meta["displayName"] = "Casement (manufacturing engine)"
            meta["hiddenReason"] = (
                "Manufacturing engine — use Excel casement series "
                "(40mm_casement_standard / 50mm_casement_prestige) in Product Library"
            )
        else:
            meta["hiddenReason"] = (
                "Duplicate / non-Excel casement — use "
                "40mm_casement_standard or 50mm_casement_prestige"
            )
        meta["hiddenAt"] = _now()
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        hidden.append(sid)
    # Soft-hide Excel series that collide on displayName (keep first id)
    for pdir in sorted(root.iterdir()):
        meta_path = pdir / "product.json"
        if not pdir.is_dir() or not meta_path.is_file():
            continue
        sid = pdir.name
        if sid not in EXCEL_CASEMENT_SERIES:
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if str(meta.get("status") or "").lower() == "hidden":
            continue
        dn = str(meta.get("displayName") or sid).strip().lower()
        first = seen_names.get(dn)
        if first and first != sid:
            meta["status"] = "hidden"
            meta["hiddenReason"] = f"Duplicate display name of {first}"
            meta["hiddenAt"] = _now()
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            hidden.append(sid)
        else:
            seen_names[dn] = sid
    return hidden


def import_profile_hardware_excel(
    path: str | Path | None = None,
    *,
    hide_dummies: bool = True,
    force_hardware: bool = True,
) -> dict[str, Any]:
    """Full import: catalogue + products + hardware library + hide superseded stubs."""
    # Extend product map for new ids
    SERIES_PRODUCT_MAP.update({
        "25mm_prestige": "29mm_sliding",
        "27mm_domal": "29mm_sliding",
        "29mm_premium": "29mm_sliding",
        "35mm_prestige": "29mm_sliding",
        "35mm_gulf": "29mm_sliding",
        "40mm_prestige": "29mm_sliding",
        "40mm_casement_standard": "casement_stub",
        "50mm_casement_prestige": "casement_stub",
    })

    doc = parse_workbook(path)
    series = list(doc.get("series") or [])
    hardware = list(doc.get("hardware") or [])

    # Persist section catalogue (sliding + casement profiles)
    cat_doc = {
        "source": doc.get("source"),
        "sourcePath": doc.get("sourcePath"),
        "version": 2,
        "importedAt": doc.get("importedAt"),
        "seriesCount": len(series),
        "sectionCount": sum(len(s.get("sections") or []) for s in series),
        "series": series,
    }
    persist_catalogue(cat_doc)

    hw_ids = _seed_hardware_library(hardware, force=force_hardware)

    created_products: list[str] = []
    for s in series:
        fam = s.get("family") or "sliding"
        if fam == "casement":
            setup = _build_casement_setup(s, hardware)
        else:
            setup = _build_sliding_setup(s, hardware)
        _write_product(s, setup, family=fam)
        created_products.append(s["id"])

    # Sync catalogue blocks onto products (idempotent refresh)
    try:
        sync_catalogue_to_library()
    except Exception:
        pass

    # Re-apply setup after sync (sync may not know about setup)
    for s in series:
        fam = s.get("family") or "sliding"
        setup = _build_casement_setup(s, hardware) if fam == "casement" else _build_sliding_setup(s, hardware)
        _write_product(s, setup, family=fam)

    series_29 = next((s for s in series if s.get("id") == "29mm_premium"), None)
    series_40 = next((s for s in series if s.get("id") == "40mm_casement_standard"), None)
    _enrich_29mm_sliding(series_29, hardware)
    _enrich_casement_stub(series_40, hardware)

    hidden: list[str] = []
    if hide_dummies:
        hidden = _hide_dummy_stubs(set(created_products))
    hidden_engines = _hide_catalog_engines()
    hidden_casements = _hide_non_excel_casements()

    consolidation: dict[str, Any] = {}
    try:
        from WEOS.factory.series_consolidation import consolidate_series

        consolidation = consolidate_series(persist=False)
    except Exception as exc:
        consolidation = {"ok": False, "error": str(exc)}

    # Durable snapshot when DB available
    persisted = False
    persist_error = None
    try:
        from WEOS.db.product_store import snapshot_all, snapshot_dir

        snapshot_dir("sections")
        snapshot_all()
        persisted = True
    except Exception as exc:
        persist_error = str(exc)

    return {
        "ok": True,
        "source": doc.get("source"),
        "sourcePath": doc.get("sourcePath"),
        "sheets": doc.get("sheets"),
        "seriesCount": len(series),
        "sectionCount": cat_doc["sectionCount"],
        "hardwareCount": len(hardware),
        "hardwareIds": hw_ids,
        "products": created_products,
        "hiddenDummies": hidden,
        "hiddenEngines": hidden_engines,
        "hiddenCasements": hidden_casements,
        "consolidation": consolidation,
        "brandDefaults": {"indian": "HIVIC", "imported": "CMECH", "ette": "ETTE"},
        "ratesEditable": True,
        "editRatesIn": [
            "Admin · Product Library · Series Setup",
            "Admin · Hardware Library",
            "WEOS/products/sections/profiles_catalogue.json",
        ],
        "persisted": persisted,
        "persistError": persist_error,
        "series": [{"id": s["id"], "title": s["title"], "family": s.get("family"), "sections": len(s.get("sections") or [])} for s in series],
    }


if __name__ == "__main__":
    import pprint
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else None
    pprint.pp(import_profile_hardware_excel(p))
