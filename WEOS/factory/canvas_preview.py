"""Canvas preview helpers — transparent SVG for Universal Canvas (not PDF).

CANVAS_RENDER strips artificial paper/page backgrounds so drawings sit on the
grey/grid workspace. PDF/PRINT keep white paper via the original engine SVGs.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

GEOM_KEYS = frozenset(
    {"widthMm", "heightMm", "depthMm", "xMm", "yMm", "orientation", "sillHeightMm"}
)

# Full-bleed page backgrounds (width/height 100% + solid white).
_PAGE_BG_PCT = re.compile(
    r"<rect\b(?=[^>]*\bfill\s*=\s*[\"'](?:#fff(?:fff)?|white)[\"'])"
    r"(?=[^>]*\bwidth\s*=\s*[\"']100%[\"'])"
    r"(?=[^>]*\bheight\s*=\s*[\"']100%[\"'])"
    r"[^>]*\/?>",
    re.IGNORECASE,
)

# Railing / similar: first solid white rect covering entire viewBox (x=0 y=0).
_VIEWBOX_RE = re.compile(r"\bviewBox\s*=\s*[\"']\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*[\"']", re.I)
_SVG_WH_RE = re.compile(
    r"<svg\b[^>]*\bwidth\s*=\s*[\"']([-\d.]+)[\"'][^>]*\bheight\s*=\s*[\"']([-\d.]+)[\"']",
    re.I | re.DOTALL,
)


def _full_bleed_white_rect_re(w: str, h: str) -> re.Pattern[str]:
    # Allow formatting like 1234 / 1234.0 / 1234.1
    def flex(n: str) -> str:
        try:
            f = float(n)
        except ValueError:
            return re.escape(n)
        base = f"{f:g}"
        return rf"(?:{re.escape(base)}|{re.escape(f'{f:.1f}')}|{re.escape(f'{f:.0f}')})"

    ww, hh = flex(w), flex(h)
    return re.compile(
        rf"<rect\b(?=[^>]*\bfill\s*=\s*[\"'](?:#fff(?:fff)?|white)[\"'])"
        rf"(?=[^>]*\bx\s*=\s*[\"']0(?:\.0+)?[\"'])"
        rf"(?=[^>]*\by\s*=\s*[\"']0(?:\.0+)?[\"'])"
        rf"(?=[^>]*\bwidth\s*=\s*[\"']{ww}[\"'])"
        rf"(?=[^>]*\bheight\s*=\s*[\"']{hh}[\"'])"
        rf"(?![^>]*\bstroke\s*=)"  # page bg usually has no stroke
        rf"[^>]*\/?>",
        re.IGNORECASE,
    )


def normalize_for_canvas(svg: str | None) -> str:
    """Remove artificial white page backgrounds for CANVAS_RENDER only.

    Preserves legitimate glass/panel/profile fills (partial opacity, stroked
    shapes, non-full-bleed whites, chip/handle circles).
    """
    if not svg:
        return ""
    text = str(svg)
    if "<svg" not in text.lower():
        return text
    if 'data-weos-canvas-normalized="1"' in text or "data-weos-canvas-normalized='1'" in text:
        return text

    out = _PAGE_BG_PCT.sub("", text)

    vb = _VIEWBOX_RE.search(out)
    if vb:
        out = _full_bleed_white_rect_re(vb.group(3), vb.group(4)).sub("", out, count=1)
    else:
        wh = _SVG_WH_RE.search(out)
        if wh:
            out = _full_bleed_white_rect_re(wh.group(1), wh.group(2)).sub("", out, count=1)

    # Mark + ensure transparent root (CSS also enforces).
    out = re.sub(
        r"(<svg\b)",
        r'\1 data-weos-canvas-normalized="1" style="background:transparent"',
        out,
        count=1,
        flags=re.IGNORECASE,
    )
    return out


def enrich_field_meta(field: Mapping[str, Any] | None) -> dict[str, Any]:
    """Stamp editable / readOnly / supported / updateTarget on a schema field."""
    f = dict(field or {})
    key = str(f.get("key") or "")
    domain = str(f.get("domain") or ("geometry" if key in GEOM_KEYS else "config"))
    f["domain"] = domain
    ftype = str(f.get("type") or "string")
    if "updateTarget" not in f:
        if domain == "geometry":
            f["updateTarget"] = "GEOMETRY"
        elif domain == "identity":
            f["updateTarget"] = "IDENTITY"
        else:
            f["updateTarget"] = "CONFIG"
    read_only = bool(f.get("readOnly")) or ftype in ("readonly", "json") or f.get("editable") is False
    supported = f.get("supported")
    if supported is None:
        supported = True
    f["supported"] = bool(supported)
    f["readOnly"] = read_only
    f["editable"] = (not read_only) and bool(supported)
    if not f["supported"]:
        f.setdefault("disabledReason", "Not supported for this product")
    elif read_only:
        f.setdefault("disabledReason", "Read-only")
    return f


def enrich_schema(schema: Mapping[str, Any] | None) -> dict[str, Any]:
    out = dict(schema or {})
    groups = []
    for g in out.get("groups") or []:
        if not isinstance(g, Mapping):
            continue
        gg = dict(g)
        gg["fields"] = [enrich_field_meta(f) for f in (g.get("fields") or []) if isinstance(f, Mapping)]
        groups.append(gg)
    out["groups"] = groups
    return out


def is_page_background_rect(fragment: str) -> bool:
    """Heuristic used by smokes — true for full-bleed white page rects."""
    if not fragment:
        return False
    return bool(_PAGE_BG_PCT.search(fragment)) or (
        "fill" in fragment.lower()
        and ("#fff" in fragment.lower() or "white" in fragment.lower())
        and ('width="100%"' in fragment.lower() or "width='100%'" in fragment.lower())
    )
