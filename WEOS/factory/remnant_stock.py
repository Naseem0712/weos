"""Reusable aluminium remnant / leftover stock (cross-order hook).

Wastage rule: leftover ≤ ~3 ft is scrap charged to the product; leftover > ~3 ft
is reusable stock keyed by series + section + colour.

In-quote reuse lives in ``design_cost`` remnant pools. This module persists
remnants to ``WEOS/stock/inventory.json`` so the Stock viewer can show them
anytime. Cross-order consume is opt-in (load leftovers into a quote nest).
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from WEOS.factory.optimize_engine import DEFAULT_STOCK_PATH, load_stock
from WEOS.paths import stock_dir

# ~3 ft — scraps at or below this are wastage, not stock.
WASTAGE_THRESHOLD_FT = 3.0
WASTAGE_THRESHOLD_M = WASTAGE_THRESHOLD_FT * 0.3048  # ≈ 0.9144 m


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _str(v: Any) -> str:
    return str(v or "").strip()


def stock_path() -> Path:
    return Path(DEFAULT_STOCK_PATH)


def is_reusable_remnant_m(length_m: float, *, threshold_m: float = WASTAGE_THRESHOLD_M) -> bool:
    return _f(length_m) > max(_f(threshold_m), 0.0) + 1e-9


def remnant_key(
    *,
    series: Any = None,
    section: Any = None,
    colour: Any = None,
    profile_family: Any = None,
) -> str:
    bits = [
        _str(series) or _str(profile_family) or "series",
        _str(section) or "section",
        _str(colour).lower().replace(" ", "_") or "any",
    ]
    return "|".join(bits).lower()


def list_remnants(stock: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Normalised remnant rows for Stock viewer / nesting."""
    doc = stock if isinstance(stock, Mapping) else load_stock()
    out: list[dict[str, Any]] = []
    for raw in doc.get("leftoverStock") or []:
        if not isinstance(raw, Mapping):
            continue
        if _str(raw.get("material") or "aluminium").lower() not in ("aluminium", "aluminum", "al", ""):
            continue
        length_mm = _f(raw.get("lengthMm") or raw.get("length_mm"))
        length_m = _f(raw.get("lengthM"))
        if length_mm <= 0 and length_m > 0:
            length_mm = length_m * 1000.0
        if length_m <= 0 and length_mm > 0:
            length_m = length_mm / 1000.0
        if length_m <= 0:
            continue
        # Drop scraps that somehow landed in stock (≤3 ft)
        if not is_reusable_remnant_m(length_m):
            continue
        series = _str(raw.get("series") or raw.get("seriesId") or raw.get("profileFamily") or "default")
        section = _str(raw.get("section") or raw.get("sectionName") or raw.get("profile") or "—")
        colour = _str(raw.get("colour") or raw.get("color") or "any")
        out.append({
            "id": _str(raw.get("id")) or f"LO-{len(out)+1}",
            "series": series,
            "section": section,
            "colour": colour,
            "lengthMm": round(length_mm, 1),
            "lengthM": round(length_m, 4),
            "lengthFt": round(length_m / 0.3048, 2),
            "material": "aluminium",
            "profileFamily": _str(raw.get("profileFamily") or series),
            "key": remnant_key(series=series, section=section, colour=colour),
            "source": _str(raw.get("source") or "stock"),
            "updatedAt": _str(raw.get("updatedAt") or raw.get("createdAt")),
            "notes": _str(raw.get("notes")),
        })
    out.sort(key=lambda r: (r["series"].lower(), r["section"].lower(), -r["lengthM"]))
    return out


def stock_viewer_payload() -> dict[str, Any]:
    """API payload for the Stock viewer UI."""
    doc = load_stock()
    remnants = list_remnants(doc)
    bars = []
    for b in doc.get("aluminiumBars") or []:
        if not isinstance(b, Mapping):
            continue
        bars.append({
            "id": _str(b.get("id")),
            "lengthMm": _f(b.get("lengthMm")),
            "profileFamily": _str(b.get("profileFamily") or "default"),
            "label": _str(b.get("label")),
        })
    by_series: dict[str, list[dict[str, Any]]] = {}
    for r in remnants:
        by_series.setdefault(r["series"], []).append(r)
    return {
        "ok": True,
        "path": str(stock_path().as_posix()),
        "wastageThresholdFt": WASTAGE_THRESHOLD_FT,
        "wastageThresholdM": round(WASTAGE_THRESHOLD_M, 4),
        "notes": _str(doc.get("notes"))
        or "Reusable aluminium remnants (leftover > ~3 ft). Short scrap is charged as wastage on the product.",
        "aluminiumBars": bars,
        "remnants": remnants,
        "bySeries": by_series,
        "counts": {
            "remnantPieces": len(remnants),
            "totalRemnantM": round(sum(r["lengthM"] for r in remnants), 3),
            "series": len(by_series),
        },
        "stub": {
            "crossOrderConsume": True,
            "detail": (
                "Remnants persist in inventory.json. Quote nesting reuses in-quote "
                "pool first; load leftovers from stock when projectWastageReuse is on."
            ),
        },
    }


def merge_remnants_into_stock(
    remnants: Sequence[Mapping[str, Any]],
    *,
    path: str | Path | None = None,
    source_quote: str | None = None,
    source_version: int | str | None = None,
) -> dict[str, Any]:
    """Append reusable remnants (>3 ft) into leftoverStock.

    Rulebook v2: approval retry / re-open must not duplicate stock. When
    ``source_quote`` (+ optional version) is set and those pieces already exist,
    the post is skipped.
    """
    p = Path(path) if path else stock_path()
    doc = load_stock(p)
    leftover = list(doc.get("leftoverStock") or [])
    sq = _str(source_quote)
    sv = None if source_version is None or _str(source_version) == "" else _str(source_version)
    if sq:
        already = [
            x for x in leftover
            if isinstance(x, Mapping)
            and _str(x.get("sourceQuote")) == sq
            and (sv is None or _str(x.get("sourceVersion")) == sv)
        ]
        if already:
            payload = stock_viewer_payload()
            payload["added"] = 0
            payload["skipped"] = True
            payload["reason"] = "already_posted"
            payload["existing"] = len(already)
            return payload
    added = 0
    for raw in remnants or []:
        if not isinstance(raw, Mapping):
            continue
        length_m = _f(raw.get("lengthM"))
        if length_m <= 0:
            length_m = _f(raw.get("lengthMm")) / 1000.0
        if not is_reusable_remnant_m(length_m):
            continue
        series = _str(raw.get("series") or raw.get("profileFamily") or "default")
        section = _str(raw.get("section") or raw.get("sectionName") or "section")
        colour = _str(raw.get("colour") or "any")
        rid = _str(raw.get("id"))
        if not rid:
            rid = f"LO-{sq or series[:8]}-{sv or 'x'}-{int(length_m * 1000)}-{len(leftover)+1}"
        piece = {
            "id": rid,
            "lengthMm": round(length_m * 1000.0, 1),
            "lengthM": round(length_m, 4),
            "material": "aluminium",
            "series": series,
            "section": section,
            "colour": colour,
            "profileFamily": series,
            "source": _str(raw.get("source") or "quote"),
            "updatedAt": _now(),
            "notes": _str(raw.get("notes")),
        }
        if sq:
            piece["sourceQuote"] = sq
        if sv is not None:
            piece["sourceVersion"] = sv
        if raw.get("profileFamily"):
            piece["windowFamily"] = _str(raw.get("profileFamily"))
        leftover.append(piece)
        added += 1
    doc = deepcopy(doc) if isinstance(doc, dict) else {}
    doc["leftoverStock"] = leftover
    doc["updatedAt"] = _now()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    payload = stock_viewer_payload()
    payload["added"] = added
    payload["skipped"] = False
    return payload


def leftovers_for_nesting(
    *,
    series: Any = None,
    section: Any = None,
    colour: Any = None,
) -> list[dict[str, Any]]:
    """Leftover rows matching series/section/colour for FFD bar nesting."""
    want = remnant_key(series=series, section=section, colour=colour)
    series_s = _str(series).lower()
    section_s = _str(section).lower()
    colour_s = _str(colour).lower().replace(" ", "_") or "any"
    out: list[dict[str, Any]] = []
    for r in list_remnants():
        if series_s and r["series"].lower() not in (series_s, "default") and series_s not in r["series"].lower():
            # Allow profileFamily default match
            if r.get("profileFamily", "").lower() != series_s and r["series"].lower() != "default":
                continue
        if section_s and section_s not in ("section", "—", "-"):
            if r["section"].lower() != section_s and section_s not in r["section"].lower():
                continue
        if colour_s not in ("any", "", "white") and r["colour"].lower() not in (colour_s, "any"):
            if colour_s not in r["colour"].lower():
                continue
        out.append({
            "id": r["id"],
            "lengthMm": r["lengthMm"],
            "series": r["series"],
            "section": r["section"],
            "colour": r["colour"],
            "key": r["key"],
        })
    # Prefer exact key matches first
    out.sort(key=lambda x: (0 if remnant_key(series=x["series"], section=x["section"], colour=x["colour"]) == want else 1, -_f(x["lengthMm"])))
    return out
