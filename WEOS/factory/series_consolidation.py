"""Consolidate window profile series: one selectable product per Excel series.

Old DETA stubs / empty orphans stay on disk (quotes may reference them) but are
soft-hidden. Manufacturing engines stay hidden. Canonical Excel series keep the
richer rates / powder / weight / dimensions and remain editable via sections JSON
+ Admin Series Setup.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.factory.profile_hardware_import import (
    CATALOG_HIDDEN_ENGINES,
    DUMMY_SLIDING_STUBS,
    EXCEL_CASEMENT_SERIES,
    KEEP_PRODUCTS,
)
from WEOS.factory.section_catalogue import SERIES_PRODUCT_MAP, catalogue_path, load_catalogue, sections_dir
from WEOS.paths import products_dir

# Canonical Excel series that must stay selectable (one product each).
# Brand variants at the same mm (e.g. 35mm gulf vs prestige) are different
# products with different dims/rates — both are kept.
CANONICAL_EXCEL_SERIES: frozenset[str] = frozenset(
    {
        "25mm_prestige",
        "27mm_domal",
        "29mm_premium",
        "35mm_gulf",
        "35mm_prestige",
        "40mm_prestige",
        "40mm_casement_standard",
        "50mm_casement_prestige",
    }
)

# Old DETA / empty products that duplicate a mm-role already covered by Excel.
HIDE_ORPHAN_SERIES: tuple[str, ...] = DUMMY_SLIDING_STUBS + (
    "27mm_high_end_domal",
    "31mm_gulf_lux_slim",
    "32mm_dual_euro",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_meta(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _write_meta(path: Path, meta: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def soft_hide_product(
    product_id: str,
    *,
    reason: str,
    archive_sections: bool = True,
) -> dict[str, Any]:
    """Hide a product without deleting (quote history may still reference the id)."""
    pdir = products_dir() / product_id
    meta_path = pdir / "product.json"
    meta = _read_meta(meta_path)
    if meta is None:
        return {"id": product_id, "ok": False, "reason": "missing"}
    already = str(meta.get("status") or "").lower() in ("hidden", "archived", "deleted")
    meta["status"] = "hidden"
    meta["hiddenReason"] = reason
    meta["hiddenAt"] = _now()
    _write_meta(meta_path, meta)

    archived_section = False
    if archive_sections:
        sec = sections_dir() / f"{product_id}.json"
        if sec.is_file() and product_id not in CANONICAL_EXCEL_SERIES:
            archive = sections_dir() / "_archived"
            archive.mkdir(parents=True, exist_ok=True)
            dest = archive / f"{product_id}.json"
            if not dest.is_file():
                shutil.move(str(sec), str(dest))
                archived_section = True
            else:
                sec.unlink(missing_ok=True)
                archived_section = True
    return {
        "id": product_id,
        "ok": True,
        "alreadyHidden": already,
        "archivedSection": archived_section,
    }


def fix_catalogue_product_ids() -> dict[str, Any]:
    """Point catalogue series.productId at the series product (not the engine).

    Engines remain on ``linkedProductId`` / ``SERIES_PRODUCT_MAP``.
    """
    path = catalogue_path()
    if not path.is_file():
        return {"ok": False, "reason": "no_catalogue"}
    doc = load_catalogue()
    changed: list[str] = []
    for series in doc.get("series") or []:
        if not isinstance(series, dict):
            continue
        sid = str(series.get("id") or "")
        if not sid:
            continue
        engine = SERIES_PRODUCT_MAP.get(sid) or series.get("engineProductId")
        if series.get("productId") != sid:
            series["productId"] = sid
            changed.append(sid)
        if engine:
            series["engineProductId"] = engine
        # Per-series file
        sp = sections_dir() / f"{sid}.json"
        if sp.is_file():
            try:
                sdoc = json.loads(sp.read_text(encoding="utf-8-sig"))
            except Exception:
                sdoc = dict(series)
            if isinstance(sdoc, dict):
                sdoc["productId"] = sid
                if engine:
                    sdoc["engineProductId"] = engine
                sp.write_text(json.dumps(sdoc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Product meta: selectable series, linked engine
        meta_path = products_dir() / sid / "product.json"
        meta = _read_meta(meta_path)
        if meta is not None:
            if str(meta.get("status") or "").lower() in ("stub", ""):
                meta["status"] = "active"
            meta["sectionSeries"] = sid
            if engine:
                meta["linkedProductId"] = engine
            cat = dict(meta.get("catalogue") or {})
            cat["sectionSeries"] = sid
            cat["productId"] = sid
            if engine:
                cat["engineProductId"] = engine
            meta["catalogue"] = cat
            meta["ratesEditable"] = True
            _write_meta(meta_path, meta)
            # Keep quotation.stub for geometry; mark costEngine live for design_cost.
            qpath = products_dir() / sid / "rules" / "quotation.json"
            if qpath.is_file():
                try:
                    qdoc = json.loads(qpath.read_text(encoding="utf-8-sig"))
                except Exception:
                    qdoc = {}
                if isinstance(qdoc, dict):
                    qdoc["stub"] = True
                    qdoc["costEngine"] = "live"
                    qdoc["ratesEditable"] = True
                    qpath.write_text(
                        json.dumps(qdoc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                    )
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "updatedSeries": changed, "count": len(changed)}


def build_profiles_catalogue() -> dict[str, Any]:
    """Writable profiles index: name, dims, rates, powder, weight, formulas hooks.

    Humans edit via Admin Series Setup / section JSON / this index; import refreshes
    defaults without wiping quote history.
    """
    doc = load_catalogue()
    entries: list[dict[str, Any]] = []
    for series in doc.get("series") or []:
        if not isinstance(series, Mapping):
            continue
        sid = str(series.get("id") or "")
        if not sid:
            continue
        meta = _read_meta(products_dir() / sid / "product.json") or {}
        status = str(meta.get("status") or "active").lower()
        sections_out: list[dict[str, Any]] = []
        for sec in series.get("sections") or []:
            if not isinstance(sec, Mapping):
                continue
            sections_out.append(
                {
                    "id": sec.get("id"),
                    "name": sec.get("name"),
                    "usage": sec.get("usage"),
                    "usageLabel": sec.get("usageLabel"),
                    "widthMm": sec.get("widthMm"),
                    "sectionDepthMm": sec.get("sectionDepthMm"),
                    "wallThicknessMm": sec.get("wallThicknessMm"),
                    "weightKgPerMtr": sec.get("weightKgPerMtr"),
                    "standardLength": sec.get("standardLength"),
                    "rate": sec.get("rate"),
                    "rateUnit": sec.get("rateUnit") or "kg",
                    "coatingCost": sec.get("coatingCost"),
                    "coatingUnit": sec.get("coatingUnit") or "rft",
                    "trackCount": sec.get("trackCount"),
                    "glassOptions": list(sec.get("glassOptions") or []),
                    "formulaHint": sec.get("use") or sec.get("designNote"),
                }
            )
        setup = meta.get("setup") if isinstance(meta.get("setup"), Mapping) else {}
        entries.append(
            {
                "id": sid,
                "displayName": meta.get("displayName") or series.get("displayName") or series.get("title"),
                "family": series.get("family") or meta.get("productType") or "sliding",
                "status": status,
                "canonical": sid in CANONICAL_EXCEL_SERIES,
                "productId": sid,
                "engineProductId": series.get("engineProductId")
                or meta.get("linkedProductId")
                or SERIES_PRODUCT_MAP.get(sid),
                "sectionCount": len(sections_out),
                "sections": sections_out,
                "ratesEditable": True,
                "editIn": [
                    "Admin · Product Library · Series Setup",
                    "Admin · Product Library · Catalogue",
                    f"WEOS/products/sections/{sid}.json",
                ],
                "hasSetup": bool(setup),
                "labourPerSft": ((setup.get("sliding") or setup.get("casement") or {}).get("costing") or {}).get(
                    "labourPerSft"
                )
                if isinstance(setup, Mapping)
                else None,
            }
        )
    out = {
        "version": 1,
        "updatedAt": _now(),
        "description": (
            "Editable profiles catalogue index. Correct name / dimensions / rates / "
            "powder coating / weight in Series Setup or section JSON; re-import refreshes defaults."
        ),
        "canonicalSeries": sorted(CANONICAL_EXCEL_SERIES),
        "seriesCount": len(entries),
        "series": entries,
    }
    dest = sections_dir() / "profiles_catalogue.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Runtime mirror
    try:
        from WEOS.paths import data_dir

        mirror = data_dir() / "sections"
        mirror.mkdir(parents=True, exist_ok=True)
        (mirror / "profiles_catalogue.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except Exception:
        pass
    return out


def consolidate_series(*, persist: bool = True) -> dict[str, Any]:
    """Hide orphans/engines, fix catalogue product ids, rebuild profiles catalogue."""
    hidden: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sid in HIDE_ORPHAN_SERIES:
        if sid in seen or sid in CANONICAL_EXCEL_SERIES or sid in KEEP_PRODUCTS:
            continue
        seen.add(sid)
        hidden.append(
            soft_hide_product(
                sid,
                reason="Superseded by Excel profile series — soft-hidden to avoid duplicate Product Library rows",
            )
        )
    for sid in CATALOG_HIDDEN_ENGINES:
        if sid in seen:
            continue
        seen.add(sid)
        hidden.append(
            soft_hide_product(
                sid,
                reason="Manufacturing engine — use Excel series in Product Library",
                archive_sections=False,
            )
        )

    # Soft-hide any non-Excel casement still active (except bathroom ventilator)
    root = products_dir()
    for pdir in sorted(root.iterdir()):
        if not pdir.is_dir():
            continue
        sid = pdir.name
        if sid in seen or sid in EXCEL_CASEMENT_SERIES or sid in CANONICAL_EXCEL_SERIES:
            continue
        if sid in KEEP_PRODUCTS or sid == "bathroom_ventilator":
            continue
        meta = _read_meta(pdir / "product.json")
        if not meta:
            continue
        pt = str(meta.get("productType") or "").lower()
        st = str(meta.get("status") or "").lower()
        if st in ("hidden", "archived", "deleted", "stub"):
            continue
        # Empty Windows products with no sections and not canonical
        sec = sections_dir() / f"{sid}.json"
        if pt in ("sliding", "windows", "window", "section_series", "") and not sec.is_file():
            if sid.startswith(("25mm_", "27mm_", "29mm_", "31mm_", "32mm_", "35mm_")):
                hidden.append(
                    soft_hide_product(
                        sid,
                        reason="Empty / orphan mm series without section catalogue — use canonical Excel series",
                    )
                )
                seen.add(sid)

    cat_fix = fix_catalogue_product_ids()
    profiles = build_profiles_catalogue()

    persisted = False
    persist_error = None
    if persist:
        try:
            from WEOS.db.product_store import snapshot_all, snapshot_dir

            snapshot_dir("sections")
            snapshot_all()
            persisted = True
        except Exception as exc:
            persist_error = str(exc)

    active = []
    for sid in sorted(CANONICAL_EXCEL_SERIES):
        meta = _read_meta(products_dir() / sid / "product.json") or {}
        active.append(
            {
                "id": sid,
                "displayName": meta.get("displayName") or sid,
                "status": meta.get("status") or "missing",
                "sectionFile": (sections_dir() / f"{sid}.json").is_file(),
            }
        )

    return {
        "ok": True,
        "hidden": [h for h in hidden if h.get("ok")],
        "hiddenCount": sum(1 for h in hidden if h.get("ok")),
        "catalogue": cat_fix,
        "profilesCatalogue": {
            "path": str(sections_dir() / "profiles_catalogue.json"),
            "seriesCount": profiles.get("seriesCount"),
        },
        "canonical": active,
        "persisted": persisted,
        "persistError": persist_error,
    }


if __name__ == "__main__":
    import pprint

    pprint.pp(consolidate_series())
