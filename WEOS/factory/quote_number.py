"""Company-prefixed quotation numbers: ``{PREFIX}-{YY}/{SERIAL}/{VERSION}``.

Examples
--------
- ALLUKRAFT → ``AK-26/00001/A1``
- WOODENMAX → ``WM-26/00001/A1``
- WOODENMAX ARCHITECTURAL ELEMENTS → ``WAE-26/00001/A1``
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

# Skip legal / filler tokens when building multi-word prefixes.
_SKIP_WORDS = {
    "pvt",
    "ltd",
    "llc",
    "inc",
    "co",
    "corp",
    "corporation",
    "private",
    "limited",
    "llp",
    "plc",
    "the",
    "and",
    "of",
    "company",
    "companies",
}

# Compound tails so ALLUKRAFT → AK, WOODENMAX → WM (brand monogram style).
_COMPOUND_TAILS = (
    "KRAFT",
    "CRAFT",
    "MAX",
    "TECH",
    "SOFT",
    "WARE",
    "WORKS",
    "GLASS",
    "ALUMINIUM",
    "ALUMINUM",
    "STEEL",
    "SYSTEMS",
    "SOLUTIONS",
)

_NEW_RE = re.compile(
    r"^([A-Z0-9]{1,8})-(\d{2})/(\d{1,8})/(A\d{1,3})$",
    re.IGNORECASE,
)
_LEGACY_QT_RE = re.compile(r"^QT-(\d{4})-(\d+)$", re.IGNORECASE)
_LEGACY_WQ_RE = re.compile(r"^WQ-(\d{4})-(\d+)$", re.IGNORECASE)


def _split_compound_token(token: str) -> list[str]:
    w = token.upper()
    for tail in _COMPOUND_TAILS:
        if w.endswith(tail) and len(w) > len(tail) + 1:
            head = w[: -len(tail)]
            if head:
                return [head, tail]
    return [w]


def company_quote_prefix(company_name: str | None) -> str:
    """Derive quote prefix from seller company display name.

    Multi-word → first letter of each significant word (WAE).
    Single token → first 2 letters, after splitting common compound tails
    (ALLUKRAFT→AK, WOODENMAX→WM).
    """
    raw = str(company_name or "").strip()
    # Strip trademark / punctuation noise before tokenising.
    raw = raw.replace("™", " ").replace("®", " ").replace("©", " ")
    words = re.findall(r"[A-Za-z0-9]+", raw)
    words = [w for w in words if w.lower() not in _SKIP_WORDS]
    if not words:
        return "QT"
    if len(words) == 1:
        parts = _split_compound_token(words[0])
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        w = parts[0].upper()
        return (w[:2] if len(w) >= 2 else (w + "X")[:2])
    return "".join(w[0].upper() for w in words)[:8]


def version_label(version: int | Any) -> str:
    try:
        n = max(1, int(version or 1))
    except (TypeError, ValueError):
        n = 1
    return f"A{n}"


def format_quote_number(
    *,
    company_name: str | None = None,
    prefix: str | None = None,
    year: int | None = None,
    serial: int,
    version: int = 1,
    serial_width: int = 5,
) -> str:
    """Build ``PREFIX-YY/SERIAL/A#``."""
    pref = (prefix or company_quote_prefix(company_name) or "QT").upper()
    y = int(year or datetime.now(timezone.utc).year)
    yy = f"{y % 100:02d}"
    width = max(3, min(int(serial_width or 5), 8))
    try:
        seq = max(1, int(serial))
    except (TypeError, ValueError):
        seq = 1
    return f"{pref}-{yy}/{seq:0{width}d}/{version_label(version)}"


def parse_quote_number(value: Any) -> dict[str, Any] | None:
    """Parse new or legacy quote numbers into parts."""
    text = re.sub(r"\s+", "", str(value or "").strip())
    if not text:
        return None
    m = _NEW_RE.match(text)
    if m:
        ver_raw = m.group(4).upper()
        try:
            ver_n = int(ver_raw[1:])
        except ValueError:
            ver_n = 1
        yy = int(m.group(2))
        year = 2000 + yy if yy < 100 else yy
        return {
            "style": "company",
            "prefix": m.group(1).upper(),
            "year": year,
            "yy": f"{yy:02d}",
            "serial": int(m.group(3)),
            "serialWidth": len(m.group(3)),
            "version": ver_n,
            "versionLabel": ver_raw,
            "base": f"{m.group(1).upper()}-{yy:02d}/{m.group(3)}",
            "raw": text.upper().replace(" ", ""),
        }
    m = _LEGACY_QT_RE.match(text) or _LEGACY_WQ_RE.match(text)
    if m:
        year = int(m.group(1))
        serial = int(m.group(2))
        return {
            "style": "legacy",
            "prefix": "QT" if text.upper().startswith("QT") else "WQ",
            "year": year,
            "yy": f"{year % 100:02d}",
            "serial": serial,
            "serialWidth": max(5, len(m.group(2))),
            "version": 1,
            "versionLabel": "A1",
            "base": text.upper(),
            "raw": text.upper(),
        }
    return None


def quote_number_base(value: Any) -> str:
    """Canonical match key ignoring version suffix (and whitespace)."""
    parsed = parse_quote_number(value)
    if parsed:
        return str(parsed["base"]).upper()
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def bump_quote_version(value: Any, *, to_version: int | None = None) -> str:
    """Return the same quote with VERSION bumped (A1→A2). Legacy QT stays as-is unless converted."""
    parsed = parse_quote_number(value)
    if not parsed:
        return str(value or "").strip()
    next_ver = int(to_version) if to_version is not None else int(parsed["version"]) + 1
    if parsed["style"] == "company":
        return format_quote_number(
            prefix=parsed["prefix"],
            year=parsed["year"],
            serial=parsed["serial"],
            version=next_ver,
            serial_width=parsed["serialWidth"],
        )
    # Legacy QT/WQ: keep the legacy body, append version only when bumping past v1
    # is requested via conversion to company format — otherwise leave unchanged.
    if next_ver <= 1:
        return str(parsed["raw"])
    return format_quote_number(
        prefix=parsed["prefix"],
        year=parsed["year"],
        serial=parsed["serial"],
        version=next_ver,
        serial_width=parsed["serialWidth"],
    )


def resolve_company_name(explicit: str | None = None, payload: Mapping[str, Any] | None = None) -> str:
    """Best-effort seller company name for prefix derivation."""
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    if isinstance(payload, Mapping):
        for key in ("companyName", "sellerCompany", "brandName"):
            val = payload.get(key)
            if val and str(val).strip():
                return str(val).strip()
        branding = payload.get("branding") if isinstance(payload.get("branding"), Mapping) else {}
        for key in ("companyName", "logoText"):
            val = (branding or {}).get(key)
            if val and str(val).strip():
                return str(val).strip()
    try:
        from WEOS.factory.company_store import load_company

        doc = load_company() or {}
        name = str(doc.get("companyName") or "").strip()
        if name:
            return name
    except Exception:
        pass
    return ""
