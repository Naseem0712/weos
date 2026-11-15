"""Worldwide currency codes → display prefix (symbol or ISO fallback).

Never emit a tofu / missing-glyph box. When the active PDF font cannot draw a
symbol (e.g. ₹ on Helvetica / Vera / Segoe UI Symbol), print the ISO code
instead (``INR 1,234.00``). ASCII-safe symbols (``$``, ``€``, ``£`` …) are used
when they are known to render in the active face.
"""

from __future__ import annotations

from typing import Any, Mapping

# code → (preferred symbol, ASCII/ISO-safe fallback label, symbol codepoint(s) to check)
_CURRENCY: dict[str, tuple[str, str, tuple[int, ...]]] = {
    "INR": ("\u20b9", "INR", (0x20B9,)),
    "USD": ("$", "USD", (0x24,)),
    "EUR": ("\u20ac", "EUR", (0x20AC,)),
    "GBP": ("\u00a3", "GBP", (0xA3,)),
    "AED": ("AED", "AED", ()),  # Arabic glyph often missing — ISO by default
    "SAR": ("SAR", "SAR", ()),
    "QAR": ("QAR", "QAR", ()),
    "KWD": ("KWD", "KWD", ()),
    "OMR": ("OMR", "OMR", ()),
    "BHD": ("BHD", "BHD", ()),
    "AUD": ("A$", "AUD", (0x24,)),
    "CAD": ("C$", "CAD", (0x24,)),
    "SGD": ("S$", "SGD", (0x24,)),
    "NZD": ("NZ$", "NZD", (0x24,)),
    "JPY": ("\u00a5", "JPY", (0xA5,)),
    "CNY": ("\u00a5", "CNY", (0xA5,)),
    "HKD": ("HK$", "HKD", (0x24,)),
    "CHF": ("CHF", "CHF", ()),
    "SEK": ("SEK", "SEK", ()),
    "NOK": ("NOK", "NOK", ()),
    "DKK": ("DKK", "DKK", ()),
    "ZAR": ("R", "ZAR", (0x52,)),
    "THB": ("\u0e3f", "THB", (0x0E3F,)),
    "MYR": ("RM", "MYR", ()),
    "IDR": ("Rp", "IDR", ()),
    "PHP": ("\u20b1", "PHP", (0x20B1,)),
    "KRW": ("\u20a9", "KRW", (0x20A9,)),
    "VND": ("\u20ab", "VND", (0x20AB,)),
    "PKR": ("Rs", "PKR", ()),
    "BDT": ("Tk", "BDT", ()),
    "LKR": ("Rs", "LKR", ()),
    "NPR": ("Rs", "NPR", ()),
    "TRY": ("\u20ba", "TRY", (0x20BA,)),
    "RUB": ("\u20bd", "RUB", (0x20BD,)),
    "BRL": ("R$", "BRL", (0x24,)),
    "MXN": ("MX$", "MXN", (0x24,)),
}

_DEFAULT = "INR"


def normalize_currency_code(raw: Any) -> str:
    code = str(raw or "").strip().upper().replace(" ", "")
    if not code:
        return _DEFAULT
    aliases = {
        "RS": "INR",
        "RS.": "INR",
        "RUPEE": "INR",
        "RUPEES": "INR",
        "INDIANRUPEE": "INR",
        "\u20b9": "INR",
        "DOLLAR": "USD",
        "DOLLARS": "USD",
        "EURO": "EUR",
        "EUROS": "EUR",
        "POUND": "GBP",
        "DIRHAM": "AED",
        "DIRHAMS": "AED",
    }
    code = aliases.get(code, code)
    if len(code) > 3 and code.endswith("S") and code[:-1] in _CURRENCY:
        code = code[:-1]
    if code in _CURRENCY:
        return code
    if len(code) == 3 and code.isalpha():
        return code
    return _DEFAULT


def currency_meta(code: Any = None) -> tuple[str, str, str, tuple[int, ...]]:
    """Return (code, symbol, iso_fallback, codepoints)."""
    c = normalize_currency_code(code)
    if c in _CURRENCY:
        sym, iso, cps = _CURRENCY[c]
        return c, sym, iso, cps
    return c, c, c, ()


def resolve_currency(
    *sources: Any,
    default: str = _DEFAULT,
) -> str:
    """Pick currency from company / project / price blobs (first hit wins)."""
    for src in sources:
        if src is None or src == "":
            continue
        if isinstance(src, str):
            return normalize_currency_code(src)
        if isinstance(src, Mapping):
            for key in (
                "currency",
                "currencyCode",
                "currency_code",
                "moneyCurrency",
            ):
                raw = src.get(key)
                if raw not in (None, ""):
                    return normalize_currency_code(raw)
            for nested in ("company", "branding", "price", "workspace", "totals"):
                blob = src.get(nested)
                if isinstance(blob, Mapping):
                    hit = resolve_currency(blob, default="")
                    if hit:
                        return hit
    return normalize_currency_code(default)


def currency_prefix(
    code: Any = None,
    *,
    glyph_ok: bool | None = None,
    force_iso: bool = False,
) -> str:
    """Safe printable prefix — never a private-use / replacement / tofu glyph."""
    c, sym, iso, cps = currency_meta(code)
    if force_iso:
        return iso
    if glyph_ok is False:
        return iso
    if not cps:
        # Symbol is already ASCII/ISO text (AED, CHF, …)
        return sym if sym and "\ufffd" not in sym else iso
    if glyph_ok is True:
        return sym
    # glyph_ok unknown — allow common Latin marks; exotic/Indic → ISO unless proven.
    if all(cp < 0x100 or cp in (0x20AC, 0xA3, 0xA5, 0x24) for cp in cps):
        return sym
    # UI callers that want ₹ should pass glyph_ok=True; PDF always sets it.
    return sym if c == "INR" else iso


def format_money(
    value: Any,
    code: Any = None,
    *,
    glyph_ok: bool | None = None,
    force_iso: bool = False,
    decimals: int = 2,
) -> str:
    from WEOS.factory.fmt import money_n

    prefix = currency_prefix(code, glyph_ok=glyph_ok, force_iso=force_iso)
    try:
        n = money_n(value)
        places = 2 if decimals is None else max(int(decimals), 0)
        body = f"{n:,.{places}f}"
    except (TypeError, ValueError):
        body = "\u2014"
    return f"{prefix} {body}".strip()


def currency_choices() -> list[tuple[str, str]]:
    """(code, label) for UI selects — common world currencies first."""
    preferred = [
        "INR", "USD", "AED", "EUR", "GBP", "SAR", "QAR", "KWD", "OMR", "BHD",
        "AUD", "CAD", "SGD", "JPY", "CNY", "HKD", "CHF", "THB", "MYR", "IDR",
        "PHP", "KRW", "PKR", "BDT", "LKR", "ZAR", "BRL", "MXN", "TRY", "RUB",
    ]
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for code in preferred:
        if code in seen:
            continue
        seen.add(code)
        _c, sym, iso, _cps = currency_meta(code)
        label = f"{code} ({sym})" if sym != code and sym != iso else code
        out.append((code, label))
    for code in sorted(_CURRENCY):
        if code in seen:
            continue
        _c, sym, iso, _cps = currency_meta(code)
        label = f"{code} ({sym})" if sym != code and sym != iso else code
        out.append((code, label))
    return out
