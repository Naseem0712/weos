"""Best-effort PDF / image catalogue extraction for Learning Engine V2.

Uses pypdf (text) and optionally pdfplumber (tables) + Pillow (page renders).
Full vision OCR is not assumed — heuristics + placeholders for admin correction.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from WEOS.learning.models import (
    DEFAULT_USAGE_RULES,
    GLASS_KEYWORDS,
    HARDWARE_KEYWORDS,
    PROFILE_TYPES,
    empty_glass,
    empty_hardware,
    empty_product_series,
    empty_profile,
)
from WEOS.learning.v2_store import find_library_match, new_id, _slug

# Patterns
_DIM_PAIR = re.compile(
    r"(?P<w>\d+(?:\.\d+)?)\s*[x×X]\s*(?P<h>\d+(?:\.\d+)?)\s*(?:mm)?",
    re.I,
)
_WEIGHT = re.compile(
    r"(?P<w>\d+(?:\.\d+)?)\s*(?:kg\s*/\s*m|kg/mtr|kg/mtr\.|kgm|kg\s*per\s*m)",
    re.I,
)
_WALL = re.compile(
    r"(?:wall\s*(?:thk|thickness|th\.?)|thk\.?)\s*[:=]?\s*(?P<t>\d+(?:\.\d+)?)\s*mm?",
    re.I,
)
_PART = re.compile(
    r"(?:part\s*(?:no|number|#)|code|item\s*no\.?)\s*[:=]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
    re.I,
)
_SERIES = re.compile(
    r"(\d{2,3}\s*mm)\s*(sliding|casement|slim|series|system|track)?",
    re.I,
)
_THICKNESS_GLASS = re.compile(r"(\d+(?:\.\d+)?)\s*mm\s*(clear|toughened|tempered|laminated|reflective|low[\s\-]?e)?", re.I)
_FORMULA_HINT = re.compile(
    r"(?i)(glass\s*(width|height|area)|brush\s*length|track\s*length|weight\s*=|waste\s*%|packing)",
)


def _read_pdf_pages(path: Path) -> list[dict[str, Any]]:
    """Return list of {page, text, tables?}."""
    pages: list[dict[str, Any]] = []

    # Prefer pdfplumber when available (tables)
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                tables = []
                try:
                    for t in page.extract_tables() or []:
                        tables.append(t)
                except Exception:
                    pass
                pages.append({"page": i, "text": text, "tables": tables})
        if pages:
            return pages
    except Exception:
        pass

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            pages.append({"page": i, "text": text, "tables": []})
        return pages
    except Exception as exc:
        return [{"page": 1, "text": "", "tables": [], "error": str(exc)}]


def _guess_profile_type(text: str) -> str:
    t = (text or "").lower()
    mapping = [
        ("Outer Track", ("outer track", "outer frame", "bottom track", "top track", "frame track", "domal track")),
        ("Shutter Frame", ("shutter frame", "shutter", "sash frame")),
        ("Interlock", ("interlock", "inter lock", "meeting stile", "renforcement")),
        ("Meeting Rail", ("meeting rail", "meeting section")),
        ("Glass Beading", ("glass bead", "glass beading", "glazing bead")),
        ("Beading", ("beading", "bead ")),
        ("Mullion", ("mullion",)),
        ("Transom", ("transom",)),
        ("Handle Section", ("handle section", "handle profile")),
        ("Adapter", ("adapter", "adaptor")),
        ("Corner Profile", ("corner profile", "corner section")),
        ("Extension Profile", ("extension", "extender")),
        ("Drain Cover", ("drain cover", "drainage")),
        ("Sash", ("sash",)),
    ]
    for label, keys in mapping:
        if any(k in t for k in keys):
            return label
    return "Other"


def _extract_dims(text: str) -> tuple[float | None, float | None]:
    m = _DIM_PAIR.search(text or "")
    if not m:
        # also try "W: 29 H: 65" style
        mw = re.search(r"(?:width|w)\s*[:=]?\s*(\d+(?:\.\d+)?)", text or "", re.I)
        mh = re.search(r"(?:height|h|depth)\s*[:=]?\s*(\d+(?:\.\d+)?)", text or "", re.I)
        if mw and mh:
            return float(mw.group(1)), float(mh.group(1))
        return None, None
    return float(m.group("w")), float(m.group("h"))


def _extract_weight(text: str) -> float | None:
    m = _WEIGHT.search(text or "")
    return float(m.group("w")) if m else None


def _extract_wall(text: str) -> float | None:
    m = _WALL.search(text or "")
    return float(m.group("t")) if m else None


def _extract_part_code(text: str) -> str:
    m = _PART.search(text or "")
    if m:
        return m.group(1).upper()
    # Bare codes like AL-29-OT-001
    m2 = re.search(r"\b([A-Z]{1,3}[-_]?\d{2,}[-_][A-Z0-9\-]{2,})\b", text or "")
    return m2.group(1).upper() if m2 else ""


def _series_from_filename(name: str) -> dict[str, str]:
    stem = Path(name).stem
    m = _SERIES.search(stem.replace("_", " "))
    series_name = stem.replace("_", " ").replace("-", " ").strip()
    if m:
        mm = re.sub(r"\s+", "", m.group(1))
        kind = (m.group(2) or "Series").title()
        series_name = f"{mm} {kind}".strip()
        sid = _slug(f"{mm}_{kind}")
    else:
        sid = _slug(stem)
    return {"id": sid, "seriesName": series_name}


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def infer_usage_rules(profile_type: str) -> dict[str, Any]:
    return dict(DEFAULT_USAGE_RULES.get(profile_type) or {
        "positions": [],
        "bomRole": "other",
        "orientation": [],
        "notes": "",
    })


def extract_profiles_from_pages(
    pages: list[dict[str, Any]],
    *,
    series_id: str,
    series_name: str,
) -> list[dict[str, Any]]:
    """Heuristic profile detection from page text blocks."""
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in pages:
        text = page.get("text") or ""
        page_no = page.get("page")
        # Split into candidate blocks by blank-ish grouping of lines
        blocks: list[str] = []
        buf: list[str] = []
        for ln in _lines(text):
            if re.match(r"^\d+$", ln):
                continue
            buf.append(ln)
            # Flush when line looks like a section header or dim line ends a block
            if _DIM_PAIR.search(ln) or _WEIGHT.search(ln) or any(
                k in ln.lower() for k in ("track", "shutter", "interlock", "bead", "mullion", "frame", "sash")
            ):
                if len(buf) >= 1:
                    blocks.append("\n".join(buf[-6:]))
                buf = []
        if buf:
            blocks.append("\n".join(buf[-8:]))

        # Also scan whole page once for profile-type keywords
        for ptype in PROFILE_TYPES:
            if ptype == "Other":
                continue
            if ptype.lower() in text.lower():
                # find a window around the keyword
                idx = text.lower().find(ptype.lower())
                snippet = text[max(0, idx - 40) : idx + 160]
                blocks.append(snippet)

        for block in blocks:
            ptype = _guess_profile_type(block)
            if ptype == "Other" and not _DIM_PAIR.search(block) and not _WEIGHT.search(block):
                continue
            w, h = _extract_dims(block)
            weight = _extract_weight(block)
            wall = _extract_wall(block)
            code = _extract_part_code(block)
            # Name: first meaningful line
            name_line = ""
            for ln in _lines(block):
                if len(ln) > 2 and not _DIM_PAIR.fullmatch(ln):
                    name_line = ln[:80]
                    break
            if not name_line:
                name_line = f"{ptype} ({series_name})"

            key = _slug(f"{ptype}_{code}_{w}_{h}_{page_no}")
            if key in seen:
                continue
            # Skip very weak detections
            if ptype == "Other" and w is None and weight is None:
                continue
            seen.add(key)

            usage = infer_usage_rules(ptype)
            prof = empty_profile()
            prof.update(
                {
                    "id": new_id("prof"),
                    "profileName": name_line,
                    "profileCode": code,
                    "profileType": ptype,
                    "crossSectionWidthMm": w,
                    "crossSectionHeightMm": h,
                    "wallThicknessMm": wall,
                    "weightPerMeterKg": weight,
                    "materialGrade": "",
                    "usePosition": list(usage.get("positions") or []),
                    "usageRules": usage,
                    "compatibleSeries": [series_id],
                    "seriesId": series_id,
                    "profileImage": None,
                    "dxfCrossSection": None,
                    "pdfPageNumber": page_no,
                    "engineeringNotes": "Auto-detected from catalogue PDF — please verify dimensions.",
                    "bomRole": usage.get("bomRole"),
                    "confidence": 0.55
                    if (w and weight)
                    else 0.4
                    if (w or weight or code)
                    else 0.3,
                    "sourceSnippet": block[:240],
                }
            )
            profiles.append(prof)

    # Deduplicate within extraction by type+dims
    uniq: list[dict[str, Any]] = []
    keys2: set[str] = set()
    for p in profiles:
        k = f"{p['profileType']}|{p.get('crossSectionWidthMm')}|{p.get('crossSectionHeightMm')}|{p.get('profileCode')}"
        if k in keys2:
            continue
        keys2.add(k)
        uniq.append(p)
    return uniq


def extract_hardware_from_text(text: str, *, series_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    lower = text.lower()
    for hw_type, keys in HARDWARE_KEYWORDS:
        if any(k in lower for k in keys):
            # Find a line containing the keyword
            line = ""
            for ln in _lines(text):
                if any(k in ln.lower() for k in keys):
                    line = ln
                    break
            hw = empty_hardware()
            code = _extract_part_code(line) or _extract_part_code(text)
            hw.update(
                {
                    "id": new_id("hw"),
                    "name": line[:80] if line else hw_type,
                    "hardwareType": hw_type,
                    "partNumber": code,
                    "compatibleSeries": [series_id],
                    "unit": "PC",
                    "description": f"Detected {hw_type} mention in catalogue",
                    "confidence": 0.45,
                }
            )
            items.append(hw)
    # Dedupe by type
    by_type: dict[str, dict[str, Any]] = {}
    for h in items:
        by_type.setdefault(h["hardwareType"], h)
    return list(by_type.values())


def extract_glass_from_text(text: str, *, series_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not any(k in text.lower() for k in GLASS_KEYWORDS):
        # Still look for thickness patterns near "glass"
        pass
    for m in _THICKNESS_GLASS.finditer(text or ""):
        # Only keep if near glass context or coating word present
        start = max(0, m.start() - 40)
        ctx = text[start : m.end() + 40].lower()
        if "glass" not in ctx and not m.group(2):
            continue
        gtype = (m.group(2) or "clear").title()
        th = float(m.group(1))
        if th < 2 or th > 25:
            continue
        g = empty_glass()
        g.update(
            {
                "id": new_id("glass"),
                "name": f"{th:g}mm {gtype} Glass",
                "glassType": gtype,
                "thicknessMm": th,
                "compatibleProducts": [series_id],
                "applications": ["windows"],
                "confidence": 0.5,
            }
        )
        items.append(g)
    # unique by thickness+type
    uniq: dict[str, dict[str, Any]] = {}
    for g in items:
        uniq[f"{g['thicknessMm']}_{g['glassType']}"] = g
    return list(uniq.values())


def extract_formulas_from_text(text: str, *, series_id: str) -> list[dict[str, Any]]:
    from WEOS.learning.models import empty_formula

    found: list[dict[str, Any]] = []
    for ln in _lines(text):
        if not _FORMULA_HINT.search(ln):
            continue
        # Look for simple "A = B + C" patterns
        if "=" not in ln and not re.search(r"(width|height|length|qty|area)", ln, re.I):
            continue
        cat = "other"
        low = ln.lower()
        if "glass" in low:
            cat = "glass"
        elif "brush" in low:
            cat = "brush"
        elif "track" in low:
            cat = "track"
        elif "weight" in low:
            cat = "weight"
        elif "waste" in low:
            cat = "waste"
        elif "pack" in low:
            cat = "packing"
        elif "hardware" in low or "handle" in low or "lock" in low:
            cat = "hardware"
        f = empty_formula()
        f.update(
            {
                "id": new_id("fx"),
                "name": ln[:60],
                "category": cat,
                "expression": ln.strip()[:200],
                "description": "Detected formula-like line — rewrite as safe Formula Builder expression before approve.",
                "compatibleSeries": [series_id],
                "source": "pdf_heuristic",
                "confidence": 0.35,
            }
        )
        found.append(f)
    return found[:20]


def extract_dimension_tables(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tables_out: list[dict[str, Any]] = []
    for page in pages:
        for ti, table in enumerate(page.get("tables") or []):
            if not table or len(table) < 2:
                continue
            headers = [str(c or "").strip() for c in table[0]]
            rows = []
            for row in table[1:12]:
                rows.append([str(c or "").strip() for c in row])
            tables_out.append(
                {
                    "page": page.get("page"),
                    "tableIndex": ti,
                    "headers": headers,
                    "rows": rows,
                }
            )
    return tables_out


def extract_catalogue_pdf(path: str | Path) -> dict[str, Any]:
    """
    Main catalogue extractor.

    Returns structured series + profiles + hardware + glass + formulas
    with confidence notes for admin review.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    series_meta = _series_from_filename(path.name)
    pages = _read_pdf_pages(path)
    full_text = "\n".join(p.get("text") or "" for p in pages)

    # Refine series name from first pages
    for p in pages[:3]:
        m = _SERIES.search(p.get("text") or "")
        if m:
            mm = re.sub(r"\s+", "", m.group(1))
            kind = (m.group(2) or "Series").title()
            series_meta["seriesName"] = f"{mm} {kind}".strip()
            series_meta["id"] = _slug(f"{mm}_{kind}")
            break

    # Brand / alloy / finish heuristics
    brand = ""
    alloy = ""
    temper = ""
    powder = ""
    finish = ""
    category = "Windows"
    for ln in _lines(full_text)[:80]:
        low = ln.lower()
        if "brand" in low or "manufacturer" in low:
            brand = re.sub(r"(?i)brand\s*[:=]?\s*", "", ln).strip()[:60]
        if re.search(r"6063|6061|6082", ln):
            alloy = re.search(r"60\d{2}(?:\s*[A-Z]-?[A-Z0-9]*)?", ln)
            alloy = alloy.group(0) if alloy else ""
        if re.search(r"\bT5\b|\bT6\b", ln):
            temper = re.search(r"T[56]", ln).group(0)  # type: ignore[union-attr]
        if "powder" in low:
            powder = ln[:80]
        if "anodiz" in low or "surface finish" in low or "finish" in low:
            finish = ln[:80]
        if "casement" in low:
            category = "Casement Windows"
        elif "sliding" in low:
            category = "Sliding Windows"
        elif "slim" in low:
            category = "Slim Series"

    series = empty_product_series()
    series.update(
        {
            "id": series_meta["id"],
            "seriesName": series_meta["seriesName"],
            "brand": brand,
            "productCategory": category,
            "productDescription": _lines(full_text)[0][:240] if _lines(full_text) else "",
            "aluminiumAlloy": alloy,
            "temper": temper,
            "powderCoatingType": powder,
            "surfaceFinish": finish,
            "dimensionTables": extract_dimension_tables(pages),
        }
    )

    profiles = extract_profiles_from_pages(pages, series_id=series["id"], series_name=series["seriesName"])
    hardware = extract_hardware_from_text(full_text, series_id=series["id"])
    glass = extract_glass_from_text(full_text, series_id=series["id"])
    formulas = extract_formulas_from_text(full_text, series_id=series["id"])

    # Wall thickness from series-level mentions
    wall = _extract_wall(full_text)
    if wall:
        series["wallThicknessMm"] = wall
    series["glassThicknessMm"] = sorted({g["thicknessMm"] for g in glass if g.get("thicknessMm")})
    series["hardwareCompatibility"] = [h["hardwareType"] for h in hardware]
    series["profiles"] = [{"id": p["id"], "profileType": p["profileType"], "profileName": p["profileName"]} for p in profiles]
    series["hardware"] = [{"id": h["id"], "name": h["name"]} for h in hardware]
    series["glass"] = [{"id": g["id"], "name": g["name"]} for g in glass]
    series["formulas"] = [{"id": f["id"], "name": f["name"]} for f in formulas]

    # Match hints against existing libraries
    match_hints = []
    sm = find_library_match("product_series", series)
    if sm:
        match_hints.append({"kind": "product_series", **{k: v for k, v in sm.items() if k != "existing"}})
    for p in profiles:
        m = find_library_match("profile", p)
        if m:
            match_hints.append({"kind": "profile", "name": p.get("profileName"), **{k: v for k, v in m.items() if k != "existing"}})
            p["linkTo"] = m.get("existing_id")

    notes = [
        "Best-effort PDF extraction — review every field before approve.",
        "Cross-section images are not auto-cropped unless pdf2image/PIL page render succeeds (see profile_recognition).",
        "Production products are NOT modified on approve — only Knowledge Base libraries + version.",
    ]
    if not full_text.strip():
        notes.append("Little or no text extracted (likely scanned PDF). Fill fields manually in Review.")

    conf = 0.35
    if profiles:
        conf = 0.55
    if profiles and (hardware or glass):
        conf = 0.65
    if full_text.strip() and profiles:
        conf = min(0.8, conf + 0.1)

    return {
        "extractor": "pdf_catalogue_v2",
        "source_path": str(path.resolve()),
        "source_type": "pdf",
        "page_count": len(pages),
        "series": series,
        "profiles": profiles,
        "hardware": hardware,
        "glass": glass,
        "formulas": formulas,
        "match_hints": match_hints,
        "notes": notes,
        "confidence": conf,
        "pages_preview": [{"page": p["page"], "chars": len(p.get("text") or "")} for p in pages[:20]],
    }


def extract_image_stub(path: str | Path) -> dict[str, Any]:
    """Image upload placeholder — stores path for admin to annotate."""
    path = Path(path)
    series_meta = _series_from_filename(path.name)
    series = empty_product_series()
    series.update(
        {
            "id": series_meta["id"],
            "seriesName": series_meta["seriesName"],
            "productImages": [str(path)],
            "productDescription": "Image upload — annotate series and profiles in Review.",
        }
    )
    return {
        "extractor": "image_stub_v2",
        "source_path": str(path.resolve()),
        "source_type": "image",
        "series": series,
        "profiles": [],
        "hardware": [],
        "glass": [],
        "formulas": [],
        "match_hints": [],
        "notes": [
            "Image OCR not fully implemented. Use Review to name the series and add profiles manually.",
        ],
        "confidence": 0.2,
    }
