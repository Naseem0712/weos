"""ReportLab fonts that can draw the Indian Rupee (₹) — Helvetica cannot.

Cross-platform + defensive: this module MUST never raise. PDF export runs on
Windows (dev) *and* Linux (Railway). Windows fonts (Nirmala / Segoe UI) do not
exist on the Linux server, so we search, in order:

  1. ``WEOS_RUPEE_FONT`` env var (explicit override — absolute path to a .ttf)
  2. a repo-bundled font under ``WEOS/assets/fonts/`` (ships with the app)
  3. common Linux system fonts (DejaVu / Liberation / Noto)
  4. common Windows system fonts (Nirmala / Segoe / Arial Unicode)
  5. reportlab's own bundled Vera TTF (always present wherever reportlab is)

Whatever we register is used for *all* text. If the chosen face lacks the ₹
glyph we still use it for text but print ``Rs.`` for currency instead of a
tofu box. If nothing at all can be registered we fall back to Helvetica.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

_log = logging.getLogger("weos.pdf_fonts")

_RUPEE = "\u20b9"
_REGISTERED = False
_FACE = "Helvetica"  # fallback until register
_FACE_BOLD = "Helvetica-Bold"
_HAS_RUPEE = False


def _bundled_font_dir() -> Path | None:
    try:
        from WEOS.paths import PACKAGE_ROOT

        return PACKAGE_ROOT / "assets" / "fonts"
    except Exception:
        return None


def _reportlab_font_dir() -> Path | None:
    try:
        import reportlab

        return Path(reportlab.__file__).resolve().parent / "fonts"
    except Exception:
        return None


def _candidate_fonts() -> list[Path]:
    """Ordered, de-duplicated list of .ttf candidates that exist on this box."""
    out: list[Path] = []

    # 1) Explicit override
    import os

    override = (os.environ.get("WEOS_RUPEE_FONT") or "").strip()
    if override:
        p = Path(override).expanduser()
        if p.is_file():
            out.append(p)

    # 2) Repo-bundled fonts (cross-platform — ships with the app)
    bundled = _bundled_font_dir()
    if bundled and bundled.is_dir():
        # Prefer files that clearly support ₹ / unicode first.
        preferred = (
            "DejaVuSans.ttf",
            "NotoSans-Regular.ttf",
            "NotoSansDevanagari-Regular.ttf",
            "LiberationSans-Regular.ttf",
        )
        for name in preferred:
            p = bundled / name
            if p.is_file():
                out.append(p)
        try:
            for p in sorted(bundled.glob("*.ttf")):
                out.append(p)
        except Exception:
            pass

    # 3) System font roots (Linux first, then Windows, then mac)
    roots = [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/usr/share/fonts/truetype/noto"),
        Path.home() / ".fonts",
        Path.home() / ".local" / "share" / "fonts",
        Path(r"C:\Windows\Fonts"),
        Path.home() / "Library" / "Fonts",
        Path("/Library/Fonts"),
    ]
    names = (
        # ₹-capable, cross-platform first
        "DejaVuSans.ttf",
        "dejavu-sans.ttf",
        "NotoSans-Regular.ttf",
        "NotoSansDevanagari-Regular.ttf",
        "LiberationSans-Regular.ttf",
        # Windows
        "Nirmala.ttf",
        "NirmalaUI.ttf",
        "nirmala.ttf",
        "seguisym.ttf",
        "SegoeUISymbol.ttf",
        "segoeui.ttf",
        "arialuni.ttf",
        "ARIALUNI.TTF",
        "arial.ttf",
    )
    for root in roots:
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        for name in names:
            p = root / name
            try:
                if p.is_file():
                    out.append(p)
            except OSError:
                continue
        # Light recursive scan for the ₹-capable families
        for pat in (
            "**/DejaVuSans.ttf",
            "**/NotoSans-Regular.ttf",
            "**/NotoSansDevanagari-Regular.ttf",
            "**/LiberationSans-Regular.ttf",
            "**/Nirmala*.ttf",
        ):
            try:
                out.extend(root.glob(pat))
            except Exception:
                pass

    # 5) reportlab's own bundled TTF (Vera) — guaranteed to exist, but old (no ₹)
    rl_dir = _reportlab_font_dir()
    if rl_dir and rl_dir.is_dir():
        for name in ("Vera.ttf", "DejaVuSans.ttf"):
            p = rl_dir / name
            try:
                if p.is_file():
                    out.append(p)
            except OSError:
                continue

    # De-dupe, preserve order
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def _font_has_rupee(font_name: str) -> bool:
    """True when the registered TTF actually contains the ₹ glyph (U+20B9)."""
    try:
        from reportlab.pdfbase import pdfmetrics

        face = pdfmetrics.getFont(font_name).face
        char_map = getattr(face, "charToGlyph", None)
        if isinstance(char_map, dict):
            return 0x20B9 in char_map
    except Exception:
        pass
    # Unknown → assume no, so we safely print "Rs." instead of a tofu box.
    return False


@lru_cache(maxsize=1)
def ensure_rupee_font() -> tuple[str, bool]:
    """Register a Unicode TTF if available. Returns (fontName, supports_rupee).

    Never raises — always returns a usable ReportLab font name.
    """
    global _REGISTERED, _FACE, _FACE_BOLD, _HAS_RUPEE
    if _REGISTERED:
        return _FACE, _HAS_RUPEE
    _REGISTERED = True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception as exc:  # reportlab missing/broken — Helvetica still draws text
        _log.warning("reportlab TTF support unavailable (%s); using Helvetica", exc)
        _FACE, _FACE_BOLD, _HAS_RUPEE = "Helvetica", "Helvetica-Bold", False
        return _FACE, _HAS_RUPEE

    for path in _candidate_fonts():
        try:
            pdfmetrics.registerFont(TTFont("WEOSRupee", str(path)))
        except Exception as exc:
            _log.debug("font register failed for %s: %s", path, exc)
            continue
        _FACE = "WEOSRupee"
        _HAS_RUPEE = _font_has_rupee("WEOSRupee")
        # Try to register a matching bold variant for nicer headers.
        _FACE_BOLD = _FACE
        try:
            stem = path.name
            bold_names = []
            low = stem.lower()
            if "dejavusans" in low:
                bold_names = ["DejaVuSans-Bold.ttf"]
            elif "notosans" in low:
                bold_names = ["NotoSans-Bold.ttf"]
            elif "liberationsans" in low:
                bold_names = ["LiberationSans-Bold.ttf"]
            elif "nirmala" in low:
                bold_names = ["Nirmala Bold.ttf", "NirmalaB.ttf"]
            elif "segoeui" in low:
                bold_names = ["segoeuib.ttf"]
            elif "arial" in low:
                bold_names = ["arialbd.ttf"]
            elif "vera" in low:
                bold_names = ["VeraBd.ttf"]
            for bn in bold_names:
                bp = path.with_name(bn)
                if bp.is_file():
                    pdfmetrics.registerFont(TTFont("WEOSRupee-Bold", str(bp)))
                    _FACE_BOLD = "WEOSRupee-Bold"
                    break
        except Exception as exc:
            _log.debug("bold font register skipped: %s", exc)
        _log.info(
            "PDF font registered: %s (rupee_glyph=%s, bold=%s)", path.name, _HAS_RUPEE, _FACE_BOLD
        )
        return _FACE, _HAS_RUPEE

    _log.warning("No unicode TTF found on this host; using Helvetica + 'Rs.' currency prefix")
    _FACE, _FACE_BOLD, _HAS_RUPEE = "Helvetica", "Helvetica-Bold", False
    return _FACE, _HAS_RUPEE


def rupee_prefix() -> str:
    """Currency prefix that will not render as a tofu box in the active PDF font."""
    try:
        _, ok = ensure_rupee_font()
        return _RUPEE if ok else "Rs."
    except Exception:
        return "Rs."


def money_text(v: Any, *, decimals: int = 2) -> str:
    prefix = rupee_prefix()
    try:
        return f"{prefix} {float(v):,.{decimals}f}"
    except (TypeError, ValueError):
        return f"{prefix} \u2014"


def set_font(c, size: float, *, bold: bool = False) -> str:
    """Set canvas font to a rupee-capable face, with a safe Helvetica fallback."""
    try:
        face, _ = ensure_rupee_font()
    except Exception:
        face = "Helvetica"
    if bold:
        if face == "Helvetica":
            name = "Helvetica-Bold"
        elif _FACE_BOLD and _FACE_BOLD != face:
            name = _FACE_BOLD
        else:
            name = face
    else:
        name = face
    try:
        c.setFont(name, size)
    except Exception:
        # Any registration mismatch → guaranteed built-in font.
        name = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(name, size)
    return name


def rate_text(rate: Any, unit: str = "sqft") -> str:
    prefix = rupee_prefix()
    try:
        return f"{prefix}{float(rate):g} / {unit}"
    except (TypeError, ValueError):
        return f"{prefix}\u2014 / {unit}"
