"""Profile Cross-Section Recognition — best-effort crops + metadata from PDF pages.

When rendering tools are available, saves page preview images under knowledge_base/uploads/crops/.
Admins correct type / W×H / weight in the Review UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from WEOS.learning.models import DEFAULT_USAGE_RULES, empty_profile
from WEOS.learning.pdf_catalogue import (
    _extract_dims,
    _extract_part_code,
    _extract_wall,
    _extract_weight,
    _guess_profile_type,
    _read_pdf_pages,
    _series_from_filename,
)
from WEOS.learning.v2_store import new_id, uploads_dir


def _crops_dir() -> Path:
    d = uploads_dir() / "crops"
    d.mkdir(parents=True, exist_ok=True)
    return d


def try_render_page_previews(pdf_path: Path, *, max_pages: int = 8) -> list[dict[str, Any]]:
    """Attempt to render first N pages to PNG for visual review."""
    out: list[dict[str, Any]] = []
    # Try pypdfium2 or pdf2image; fall back to empty
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(pdf_path))
        for i in range(min(len(doc), max_pages)):
            page = doc[i]
            bitmap = page.render(scale=1.5)
            pil = bitmap.to_pil()
            dest = _crops_dir() / f"{pdf_path.stem}_p{i+1}.png"
            pil.save(dest)
            out.append({"page": i + 1, "image": str(dest), "width": pil.width, "height": pil.height})
        return out
    except Exception:
        pass

    try:
        from pdf2image import convert_from_path

        images = convert_from_path(str(pdf_path), first_page=1, last_page=max_pages, dpi=110)
        for i, img in enumerate(images, start=1):
            dest = _crops_dir() / f"{pdf_path.stem}_p{i}.png"
            img.save(dest)
            out.append({"page": i, "image": str(dest), "width": img.width, "height": img.height})
        return out
    except Exception:
        pass

    return out


def recognize_cross_sections(pdf_path: str | Path, *, series_id: str | None = None) -> dict[str, Any]:
    """
    Detect candidate profile cross-sections from a catalogue PDF.

    Returns profiles list with optional page preview image paths.
    """
    path = Path(pdf_path)
    meta = _series_from_filename(path.name)
    sid = series_id or meta["id"]
    pages = _read_pdf_pages(path)
    previews = try_render_page_previews(path)
    preview_by_page = {p["page"]: p for p in previews}

    profiles: list[dict[str, Any]] = []
    for page in pages:
        text = page.get("text") or ""
        page_no = int(page.get("page") or 0)
        # Candidate lines that look like profile entries
        for ln in text.splitlines():
            ln = ln.strip()
            if len(ln) < 4:
                continue
            ptype = _guess_profile_type(ln)
            w, h = _extract_dims(ln)
            weight = _extract_weight(ln)
            wall = _extract_wall(ln)
            code = _extract_part_code(ln)
            interesting = ptype != "Other" or w is not None or weight is not None or code
            if not interesting:
                continue
            usage = dict(DEFAULT_USAGE_RULES.get(ptype) or {})
            prev = preview_by_page.get(page_no)
            prof = empty_profile()
            prof.update(
                {
                    "id": new_id("xsec"),
                    "profileName": ln[:80],
                    "profileCode": code,
                    "profileType": ptype if ptype != "Other" or not code else "Other",
                    "crossSectionWidthMm": w,
                    "crossSectionHeightMm": h,
                    "wallThicknessMm": wall,
                    "weightPerMeterKg": weight,
                    "usePosition": list(usage.get("positions") or []),
                    "usageRules": usage,
                    "compatibleSeries": [sid],
                    "seriesId": sid,
                    "pdfPageNumber": page_no,
                    "profileImage": prev.get("image") if prev else None,
                    "engineeringNotes": "Cross-section candidate — confirm crop and dimensions in Review.",
                    "bomRole": usage.get("bomRole"),
                    "confidence": 0.5 if (w and h) else 0.35,
                }
            )
            profiles.append(prof)

    # If nothing found but we have page previews, create one placeholder per preview page
    if not profiles and previews:
        for prev in previews:
            prof = empty_profile()
            prof.update(
                {
                    "id": new_id("xsec"),
                    "profileName": f"Page {prev['page']} cross-section (unnamed)",
                    "profileType": "Other",
                    "compatibleSeries": [sid],
                    "seriesId": sid,
                    "pdfPageNumber": prev["page"],
                    "profileImage": prev["image"],
                    "engineeringNotes": "Scanned/drawing page — name the profile and enter W×H manually.",
                    "confidence": 0.2,
                    "usageRules": {},
                }
            )
            profiles.append(prof)

    return {
        "extractor": "profile_cross_section_v2",
        "series_id": sid,
        "series_name": meta["seriesName"],
        "profiles": profiles,
        "page_previews": previews,
        "notes": [
            "Auto-detection uses text heuristics; drawings without text need manual naming.",
            "Page preview images attached when a PDF renderer is installed (optional).",
        ],
        "confidence": 0.5 if profiles else 0.2,
    }
