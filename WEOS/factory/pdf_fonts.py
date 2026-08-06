"""ReportLab fonts that can draw Indian Rupee (₹) — Helvetica cannot."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

_RUPEE = "\u20b9"
_REGISTERED = False
_FACE = "Helvetica"  # fallback until register
_HAS_RUPEE = False


def _candidate_fonts() -> list[Path]:
    roots = [
        Path(r"C:\Windows\Fonts"),
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
        Path.home() / "Library" / "Fonts",
    ]
    names = (
        "Nirmala.ttf",
        "NirmalaUI.ttf",
        "nirmala.ttf",
        "seguisym.ttf",
        "SegoeUISymbol.ttf",
        "segoeui.ttf",
        "Segoe UI.ttf",
        "arialuni.ttf",
        "ARIALUNI.TTF",
        "DejaVuSans.ttf",
        "dejavu-sans.ttf",
        "NotoSans-Regular.ttf",
        "NotoSansDevanagari-Regular.ttf",
    )
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for name in names:
            p = root / name
            if p.is_file():
                out.append(p)
        # recursive light scan for DejaVu / Noto
        for pat in ("**/DejaVuSans.ttf", "**/NotoSans-Regular.ttf", "**/Nirmala*.ttf"):
            try:
                out.extend(root.glob(pat))
            except Exception:
                pass
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


@lru_cache(maxsize=1)
def ensure_rupee_font() -> tuple[str, bool]:
    """Register a Unicode TTF if available. Returns (fontName, supports_rupee)."""
    global _REGISTERED, _FACE, _HAS_RUPEE
    if _REGISTERED:
        return _FACE, _HAS_RUPEE
    _REGISTERED = True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        _FACE, _HAS_RUPEE = "Helvetica", False
        return _FACE, _HAS_RUPEE

    for path in _candidate_fonts():
        try:
            pdfmetrics.registerFont(TTFont("WEOSRupee", str(path)))
            # Probe glyph presence via stringWidth difference vs replacement
            _FACE = "WEOSRupee"
            _HAS_RUPEE = True
            return _FACE, _HAS_RUPEE
        except Exception:
            continue
    _FACE, _HAS_RUPEE = "Helvetica", False
    return _FACE, _HAS_RUPEE


def rupee_prefix() -> str:
    """Currency prefix that will not render as ■ in the active PDF font."""
    _, ok = ensure_rupee_font()
    return _RUPEE if ok else "Rs."


def money_text(v: Any, *, decimals: int = 2) -> str:
    prefix = rupee_prefix()
    try:
        return f"{prefix} {float(v):,.{decimals}f}"
    except (TypeError, ValueError):
        return f"{prefix} —"


def set_font(c, size: float, *, bold: bool = False) -> str:
    """Set canvas font to rupee-capable face (bold falls back to regular TTF)."""
    face, _ = ensure_rupee_font()
    name = face
    if bold and face == "Helvetica":
        name = "Helvetica-Bold"
    elif bold and face == "WEOSRupee":
        # Prefer a bold TTF if previously registered as WEOSRupee-Bold
        try:
            from reportlab.pdfbase import pdfmetrics

            if "WEOSRupee-Bold" in pdfmetrics.getRegisteredFontNames():
                name = "WEOSRupee-Bold"
        except Exception:
            name = face
    c.setFont(name, size)
    return name


def rate_text(rate: Any, unit: str = "sqft") -> str:
    prefix = rupee_prefix()
    try:
        return f"{prefix}{float(rate):g} / {unit}"
    except (TypeError, ValueError):
        return f"{prefix}— / {unit}"
