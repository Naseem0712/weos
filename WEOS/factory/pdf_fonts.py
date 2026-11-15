"""ReportLab fonts + safe currency prefixes (no tofu boxes).

Cross-platform + defensive: this module MUST never raise. PDF export runs on
Windows (dev) *and* Linux (Railway). Windows fonts (Nirmala / Segoe UI) do not
exist on the Linux server, so we search, in order:

  1. ``WEOS_RUPEE_FONT`` env var (explicit override — absolute path to a .ttf)
  2. a repo-bundled font under ``WEOS/assets/fonts/`` (ships with the app)
  3. common Linux system fonts (DejaVu / Liberation / Noto)
  4. common Windows system fonts (Nirmala / Arial / Segoe)
  5. reportlab's own bundled Vera TTF (always present wherever reportlab is)

Prefer a face that actually contains the active currency glyph (₹ for INR).
If the chosen face lacks that glyph we still use it for text but print the ISO
code (``INR`` / ``USD`` / …) for currency instead of a tofu box.
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
_GLYPH_OK: set[int] = set()
_ACTIVE_CURRENCY = "INR"


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

    import os

    override = (os.environ.get("WEOS_RUPEE_FONT") or "").strip()
    if override:
        p = Path(override).expanduser()
        if p.is_file():
            out.append(p)

    bundled = _bundled_font_dir()
    if bundled and bundled.is_dir():
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
    # Prefer faces known to include ₹ / wide Unicode before symbol-only fonts.
    names = (
        "DejaVuSans.ttf",
        "dejavu-sans.ttf",
        "NotoSans-Regular.ttf",
        "NotoSansDevanagari-Regular.ttf",
        "LiberationSans-Regular.ttf",
        "Nirmala.ttf",
        "NirmalaUI.ttf",
        "nirmala.ttf",
        "arial.ttf",
        "ARIAL.TTF",
        "arialuni.ttf",
        "ARIALUNI.TTF",
        "segoeui.ttf",
        "SegoeUI.ttf",
        # Symbol fonts last — often lack ₹ even when present on Windows
        "seguisym.ttf",
        "SegoeUISymbol.ttf",
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
        for pat in (
            "**/DejaVuSans.ttf",
            "**/NotoSans-Regular.ttf",
            "**/NotoSansDevanagari-Regular.ttf",
            "**/LiberationSans-Regular.ttf",
            "**/Nirmala*.ttf",
            "**/arial.ttf",
        ):
            try:
                out.extend(root.glob(pat))
            except Exception:
                pass

    rl_dir = _reportlab_font_dir()
    if rl_dir and rl_dir.is_dir():
        for name in ("DejaVuSans.ttf", "Vera.ttf"):
            p = rl_dir / name
            try:
                if p.is_file():
                    out.append(p)
            except OSError:
                continue

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


def _font_codepoints(font_name: str) -> set[int]:
    try:
        from reportlab.pdfbase import pdfmetrics

        face = pdfmetrics.getFont(font_name).face
        char_map = getattr(face, "charToGlyph", None)
        if isinstance(char_map, dict):
            return {int(k) for k in char_map.keys() if isinstance(k, int)}
    except Exception:
        pass
    return set()


def _font_has_codepoints(font_name: str, codepoints: tuple[int, ...]) -> bool:
    if not codepoints:
        return True
    glyphs = _font_codepoints(font_name)
    if not glyphs:
        return False
    return all(cp in glyphs for cp in codepoints)


def _font_has_rupee(font_name: str) -> bool:
    return _font_has_codepoints(font_name, (0x20B9,))


def _try_register_bold(path: Path) -> str:
    global _FACE_BOLD
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        stem = path.name
        bold_names: list[str] = []
        low = stem.lower()
        if "dejavusans" in low:
            bold_names = ["DejaVuSans-Bold.ttf"]
        elif "notosans" in low:
            bold_names = ["NotoSans-Bold.ttf"]
        elif "liberationsans" in low:
            bold_names = ["LiberationSans-Bold.ttf"]
        elif "nirmala" in low:
            bold_names = ["Nirmala Bold.ttf", "NirmalaB.ttf"]
        elif "segoeui" in low and "sym" not in low:
            bold_names = ["segoeuib.ttf"]
        elif "arial" in low and "uni" not in low:
            bold_names = ["arialbd.ttf"]
        elif "vera" in low:
            bold_names = ["VeraBd.ttf"]
        for bn in bold_names:
            bp = path.with_name(bn)
            if bp.is_file():
                pdfmetrics.registerFont(TTFont("WEOSRupee-Bold", str(bp)))
                _FACE_BOLD = "WEOSRupee-Bold"
                return _FACE_BOLD
    except Exception as exc:
        _log.debug("bold font register skipped: %s", exc)
    _FACE_BOLD = _FACE
    return _FACE_BOLD


@lru_cache(maxsize=1)
def ensure_rupee_font() -> tuple[str, bool]:
    """Register a Unicode TTF if available. Returns (fontName, supports_rupee).

    Prefer a face that contains ₹. Never raises — always returns a usable font.
    """
    global _REGISTERED, _FACE, _FACE_BOLD, _HAS_RUPEE, _GLYPH_OK
    if _REGISTERED:
        return _FACE, _HAS_RUPEE
    _REGISTERED = True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception as exc:
        _log.warning("reportlab TTF support unavailable (%s); using Helvetica", exc)
        _FACE, _FACE_BOLD, _HAS_RUPEE = "Helvetica", "Helvetica-Bold", False
        _GLYPH_OK = set()
        return _FACE, _HAS_RUPEE

    fallback_face: str | None = None
    fallback_path: Path | None = None
    fallback_glyphs: set[int] = set()

    for path in _candidate_fonts():
        try:
            # Unique temp name per attempt so a failed ₹ face can be skipped
            tmp_name = "WEOSRupeeTry"
            if "WEOSRupeeTry" in pdfmetrics.getRegisteredFontNames():
                # overwrite by re-registering same name
                pass
            pdfmetrics.registerFont(TTFont(tmp_name, str(path)))
        except Exception as exc:
            _log.debug("font register failed for %s: %s", path, exc)
            continue
        glyphs = _font_codepoints(tmp_name)
        has_r = 0x20B9 in glyphs
        if has_r:
            # Promote to canonical name
            try:
                pdfmetrics.registerFont(TTFont("WEOSRupee", str(path)))
            except Exception:
                _FACE = tmp_name
            else:
                _FACE = "WEOSRupee"
            _HAS_RUPEE = True
            _GLYPH_OK = glyphs
            _try_register_bold(path)
            _log.info(
                "PDF font registered: %s (rupee_glyph=%s, bold=%s)",
                path.name,
                True,
                _FACE_BOLD,
            )
            return _FACE, _HAS_RUPEE
        if fallback_face is None:
            fallback_face = tmp_name
            fallback_path = path
            fallback_glyphs = glyphs

    if fallback_path is not None:
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            pdfmetrics.registerFont(TTFont("WEOSRupee", str(fallback_path)))
            _FACE = "WEOSRupee"
        except Exception:
            _FACE = fallback_face or "Helvetica"
        _HAS_RUPEE = False
        _GLYPH_OK = fallback_glyphs
        if fallback_path:
            _try_register_bold(fallback_path)
        _log.info(
            "PDF font registered: %s (rupee_glyph=%s, bold=%s) — currency uses ISO fallback",
            fallback_path.name if fallback_path else "?",
            False,
            _FACE_BOLD,
        )
        return _FACE, _HAS_RUPEE

    _log.warning("No unicode TTF found on this host; using Helvetica + ISO currency prefix")
    _FACE, _FACE_BOLD, _HAS_RUPEE = "Helvetica", "Helvetica-Bold", False
    _GLYPH_OK = set()
    return _FACE, _HAS_RUPEE


def set_active_currency(code: Any = None) -> str:
    """Remember currency for this PDF render (company / project setting)."""
    global _ACTIVE_CURRENCY
    from WEOS.factory.currency import normalize_currency_code

    _ACTIVE_CURRENCY = normalize_currency_code(code)
    return _ACTIVE_CURRENCY


def active_currency() -> str:
    return _ACTIVE_CURRENCY or "INR"


def _glyph_ok_for_currency(code: Any = None) -> bool:
    from WEOS.factory.currency import currency_meta

    ensure_rupee_font()
    _c, _sym, _iso, cps = currency_meta(code or active_currency())
    if not cps:
        return True
    if not _GLYPH_OK:
        # Helvetica / unknown — only ASCII-safe codepoints
        return all(cp < 0x100 for cp in cps)
    return all(cp in _GLYPH_OK for cp in cps)


def rupee_prefix() -> str:
    """Currency prefix that will not render as a tofu box in the active PDF font."""
    return currency_prefix_safe(active_currency())


def currency_prefix_safe(code: Any = None) -> str:
    try:
        from WEOS.factory.currency import currency_prefix

        ensure_rupee_font()
        c = code or active_currency()
        return currency_prefix(c, glyph_ok=_glyph_ok_for_currency(c))
    except Exception:
        return "INR"


def money_text(v: Any, *, decimals: int = 2, currency: Any = None) -> str:
    """Always exactly 2 decimal places; safe currency prefix (never tofu)."""
    try:
        from WEOS.factory.currency import format_money

        ensure_rupee_font()
        c = currency if currency not in (None, "") else active_currency()
        return format_money(
            v,
            c,
            glyph_ok=_glyph_ok_for_currency(c),
            decimals=decimals,
        )
    except Exception:
        try:
            from WEOS.factory.fmt import money_n

            return f"INR {money_n(v):,.2f}"
        except Exception:
            return "INR \u2014"


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
        name = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(name, size)
    return name


def rate_text(rate: Any, unit: str = "sqft", *, currency: Any = None) -> str:
    prefix = currency_prefix_safe(currency)
    try:
        from WEOS.factory.fmt import money_n

        return f"{prefix}{money_n(rate):,.2f} / {unit}"
    except (TypeError, ValueError):
        return f"{prefix}\u2014 / {unit}"
