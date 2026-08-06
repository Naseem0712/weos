"""Old Quotation Learning — analyze previous quotes without overwriting templates.

Suggests format / T&C / warranty / payment patterns. Admin always decides.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from WEOS.learning.v2_store import list_library, new_id


_WARRANTY = re.compile(r"(?i)warranty[^\n.]{0,120}")
_PAYMENT = re.compile(r"(?i)(payment|advance|balance|against\s+delivery)[^\n.]{0,120}")
_INSTALL = re.compile(r"(?i)(installation|fixing|erection)[^\n.]{0,120}")
_VALIDITY = re.compile(r"(?i)(validity|valid\s+for|offer\s+valid)[^\n.]{0,80}")
_TERMS_HEADER = re.compile(r"(?i)(terms\s*(?:&|and)?\s*conditions|t\s*&\s*c|general\s+conditions)")


def _pdf_text(path: Path) -> str:
    try:
        from WEOS.learning.pdf_catalogue import _read_pdf_pages

        pages = _read_pdf_pages(path)
        return "\n".join(p.get("text") or "" for p in pages)
    except Exception:
        return ""


def _docx_text(path: Path) -> str:
    # Minimal: unzip XML if python-docx missing
    try:
        import zipfile
        from xml.etree import ElementTree as ET

        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        parts = [n.text for n in root.findall(".//w:t", ns) if n.text]
        return "\n".join(parts)
    except Exception:
        return path.read_text(encoding="utf-8", errors="ignore")


def _plain_text(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".pdf":
        return _pdf_text(path)
    if suf in (".docx",):
        return _docx_text(path)
    if suf in (".txt", ".md", ".html", ".htm"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suf == ".json":
        return path.read_text(encoding="utf-8", errors="ignore")
    return path.read_bytes()[:5000].decode("utf-8", errors="ignore")


def _first(rx: re.Pattern[str], text: str) -> str | None:
    m = rx.search(text or "")
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else None


def extract_quotation_patterns(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = _plain_text(path)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    warranty = _first(_WARRANTY, text)
    payment = _first(_PAYMENT, text)
    installation = _first(_INSTALL, text)
    validity = _first(_VALIDITY, text)

    # Product description-ish lines (contain mm / sliding / window)
    descriptions = []
    for ln in lines:
        if re.search(r"(?i)(\d+\s*mm|sliding|casement|window|door|aluminium)", ln) and 20 < len(ln) < 160:
            descriptions.append(ln)
    descriptions = descriptions[:12]

    # Notes / remarks
    notes = []
    for ln in lines:
        if re.search(r"(?i)^(note|remark|nb|please\s+note)", ln):
            notes.append(ln[:200])

    terms_block = ""
    for i, ln in enumerate(lines):
        if _TERMS_HEADER.search(ln):
            terms_block = "\n".join(lines[i : i + 25])
            break

    # Detect likely layout format tags
    format_tags = []
    low = text.lower()
    if "quotation" in low or "quote no" in low:
        format_tags.append("quotation_header")
    if "bill to" in low or "buyer" in low or "customer" in low:
        format_tags.append("customer_block")
    if "sqft" in low or "sq.ft" in low or "sqm" in low:
        format_tags.append("area_pricing")
    if "terms" in low:
        format_tags.append("terms_section")
    if "warranty" in low:
        format_tags.append("warranty_clause")
    if re.search(r"w\s*[x×]\s*h|\d+\s*[x×]\s*\d+", low):
        format_tags.append("size_wh_lines")

    pattern = {
        "id": new_id("qpat"),
        "sourceFile": path.name,
        "formatTags": format_tags,
        "warranty": warranty,
        "paymentTerm": payment,
        "installationTerm": installation,
        "validity": validity,
        "termsExcerpt": terms_block[:1500],
        "productDescriptions": descriptions,
        "frequentNotes": notes[:10],
        "charCount": len(text),
        "lineCount": len(lines),
        "suggestedTemplateKinds": ["customer"] if "quotation_header" in format_tags else [],
    }

    # Stats vs existing approved patterns
    existing = list_library("quotation_patterns")
    tag_counter: Counter[str] = Counter()
    warranty_counter: Counter[str] = Counter()
    payment_counter: Counter[str] = Counter()
    for e in existing:
        for t in e.get("formatTags") or []:
            tag_counter[t] += 1
        if e.get("warranty"):
            warranty_counter[e["warranty"][:80]] += 1
        if e.get("paymentTerm"):
            payment_counter[e["paymentTerm"][:80]] += 1
    # Include this one in projected stats
    for t in format_tags:
        tag_counter[t] += 1
    if warranty:
        warranty_counter[warranty[:80]] += 1
    if payment:
        payment_counter[payment[:80]] += 1

    suggestions = []
    for t, n in tag_counter.most_common(5):
        suggestions.append(f'Format tag "{t}" seen {n} time(s) across learned quotes')
    if warranty_counter:
        w, n = warranty_counter.most_common(1)[0]
        suggestions.append(f'Most common warranty style ({n}×): "{w}"')
    if payment_counter:
        p, n = payment_counter.most_common(1)[0]
        suggestions.append(f'Preferred payment term ({n}×): "{p}"')
    suggestions.append("Templates are never auto-overwritten — approve only stores a quotation pattern suggestion.")

    return {
        "extractor": "quotation_learn_v2",
        "source_path": str(path.resolve()),
        "source_type": path.suffix.lower().lstrip(".") or "file",
        "pattern": pattern,
        "stats": {
            "existingPatterns": len(existing),
            "formatTagCounts": dict(tag_counter),
            "topWarranty": warranty_counter.most_common(3),
            "topPayment": payment_counter.most_common(3),
        },
        "suggestions": suggestions,
        "notes": [
            "Non-destructive: approving saves a pattern in the Knowledge Base only.",
            "Use Template Designer to apply patterns manually.",
        ],
        "confidence": 0.55 if text.strip() else 0.15,
    }


def build_template_suggestion_from_quote(pattern: dict[str, Any]) -> dict[str, Any]:
    """Pending reusable template shell (customer/dealer/factory/architect)."""
    tags = set(pattern.get("formatTags") or [])
    kinds = []
    if "quotation_header" in tags or "customer_block" in tags:
        kinds.append("customer")
    kinds.append("dealer")
    kinds.append("factory")
    kinds.append("architect")
    return {
        "id": new_id("tplsug"),
        "name": f"Suggested from {pattern.get('sourceFile', 'quote')}",
        "kinds": kinds,
        "blocks": [
            *(["quote_header"] if "quotation_header" in tags else []),
            *(["customer_details"] if "customer_block" in tags else []),
            *(["line_items_marqt"] if "size_wh_lines" in tags else ["price_table"]),
            *(["terms"] if "terms_section" in tags else []),
            "footer",
        ],
        "suggestedTerms": pattern.get("termsExcerpt") or "",
        "suggestedWarranty": pattern.get("warranty") or "",
        "suggestedPayment": pattern.get("paymentTerm") or "",
        "sourcePatternId": pattern.get("id"),
        "status": "pending_suggestion",
        "note": "Suggestion only — open Template Designer to create/edit. Existing templates are never overwritten.",
    }
