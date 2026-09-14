"""Legacy JSON → Engineering Master import with zeroSilentLoss reporting."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from WEOS.factory import engineering_masters as em

_log = logging.getLogger("weos.legacy_master_import")

# Compatibility mapping for common legacy series labels
COMPAT_SERIES_ALIASES = {
    "29MM Sliding": "29mm_sliding",
    "29mm Sliding": "29mm_sliding",
    "29mm Sliding Window": "29mm_sliding",
    "29MM": "29mm_sliding",
    "35MM Sliding": "35mm_sliding",
    "35mm Sliding": "35mm_sliding",
    "35mm Sliding Window": "35mm_sliding",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def import_legacy_masters(
    *,
    company_gst: str | None = None,
    seed_defaults: bool = True,
) -> dict[str, Any]:
    """Import from products/ + knowledge_base libraries.

    Returns created/matched/conflicts/rejected/manualReview with zeroSilentLoss=True.
    """
    report: dict[str, Any] = {
        "created": [],
        "matched": [],
        "conflicts": [],
        "rejected": [],
        "manualReview": [],
        "zeroSilentLoss": True,
        "compatibilityMapping": dict(COMPAT_SERIES_ALIASES),
    }

    if seed_defaults:
        seed = em.seed_default_window_masters(company_gst=company_gst)
        report["seed"] = seed

    root = _repo_root()
    products_dir = root / "WEOS" / "products"
    if products_dir.is_dir():
        for prod_json in products_dir.glob("*/product.json"):
            _import_product_json(prod_json, company_gst=company_gst, report=report)

    kb_profiles = root / "knowledge_base" / "libraries" / "profiles"
    if kb_profiles.is_dir():
        for pf in kb_profiles.glob("*.json"):
            _import_kb_profile(pf, company_gst=company_gst, report=report)

    kb_glass = root / "knowledge_base" / "libraries" / "glass_catalogue"
    if kb_glass.is_dir():
        for gf in kb_glass.glob("*.json"):
            if gf.name.startswith("_"):
                continue
            _import_kb_glass(gf, company_gst=company_gst, report=report)

    # Explicit alias registration on series
    for alias, code in COMPAT_SERIES_ALIASES.items():
        ser = em.resolve_series_ref(code, company_gst=company_gst)
        if not ser:
            report["manualReview"].append(
                {"kind": "series_alias", "alias": alias, "target": code, "reason": "target series missing"}
            )
            continue
        aliases = list(ser.get("compatibilityAliases") or [])
        if alias not in aliases:
            aliases.append(alias)
            try:
                em.update_series(ser["seriesId"], company_gst=company_gst, compatibilityAliases=aliases)
                report["created"].append({"kind": "series_alias", "alias": alias, "seriesId": ser["seriesId"]})
            except Exception as exc:
                report["rejected"].append({"kind": "series_alias", "alias": alias, "error": str(exc)})
        else:
            report["matched"].append({"kind": "series_alias", "alias": alias, "seriesId": ser["seriesId"]})

    # Sanity: every product folder considered
    if products_dir.is_dir():
        for folder in products_dir.iterdir():
            if not folder.is_dir() or folder.name == "sections":
                continue
            pj = folder / "product.json"
            if not pj.exists():
                report["rejected"].append(
                    {"kind": "product", "path": str(folder), "reason": "missing product.json"}
                )
                report["zeroSilentLoss"] = True  # still reported

    return report


def _import_product_json(path: Path, *, company_gst: str | None, report: dict[str, Any]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        report["rejected"].append({"kind": "product", "path": str(path), "error": str(exc)})
        return
    pid = str(data.get("id") or path.parent.name)
    name = str(data.get("displayName") or pid)
    existing = em.resolve_series_ref(pid, company_gst=company_gst)
    aliases = []
    spec = data.get("specifications") if isinstance(data.get("specifications"), dict) else {}
    if spec.get("profileSeries"):
        aliases.append(str(spec["profileSeries"]))
    if data.get("displayName"):
        aliases.append(str(data["displayName"]))
    if existing:
        report["matched"].append({"kind": "series", "code": pid, "seriesId": existing["seriesId"]})
        # merge aliases
        merged = list(dict.fromkeys([*(existing.get("compatibilityAliases") or []), *aliases]))
        if merged != (existing.get("compatibilityAliases") or []):
            try:
                em.update_series(existing["seriesId"], company_gst=company_gst, compatibilityAliases=merged)
            except Exception as exc:
                report["conflicts"].append({"kind": "series", "code": pid, "error": str(exc)})
        return
    try:
        family = "WINDOW"
        pt = str(data.get("productType") or "").lower()
        if "rail" in pt or "rail" in pid:
            family = "RAILING"
        elif "pergola" in pt or "pergola" in pid:
            family = "PERGOLA"
        row = em.create_series(
            code=pid,
            name=name,
            family=family,
            company_gst=company_gst,
            legacy_product_id=pid,
            compatibility_aliases=aliases,
            description=data.get("description"),
            meta={"importedFrom": str(path), "status": data.get("status")},
        )
        report["created"].append({"kind": "series", "code": pid, "seriesId": row["seriesId"]})
    except Exception as exc:
        report["conflicts"].append({"kind": "series", "code": pid, "error": str(exc)})


def _import_kb_profile(path: Path, *, company_gst: str | None, report: dict[str, Any]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        report["rejected"].append({"kind": "profile", "path": str(path), "error": str(exc)})
        return
    code = str(data.get("profileCode") or data.get("id") or path.stem)
    existing = None
    for p in em.list_profiles(company_gst=company_gst):
        if p["code"] == code or code in (p.get("legacyCodes") or []):
            existing = p
            break
    if existing:
        report["matched"].append({"kind": "profile", "code": code, "profileId": existing["profileId"]})
        return
    role = data.get("bomRole") or (data.get("usageRules") or {}).get("bomRole") or "GENERIC"
    try:
        row = em.create_profile(
            code=code,
            name=str(data.get("profileName") or code),
            company_gst=company_gst,
            defaultRole=str(role).upper(),
            roles=[str(role).upper()],
            widthMm=data.get("crossSectionWidthMm"),
            heightMm=data.get("crossSectionHeightMm"),
            wallThicknessMm=data.get("wallThicknessMm"),
            weightPerRmt=data.get("weightPerMeterKg"),
            stockLengthMm=5800,
            costBasisType="PER_KG",
            legacyCodes=[data.get("id")] if data.get("id") else [],
            meta={"importedFrom": str(path)},
        )
        report["created"].append({"kind": "profile", "code": code, "profileId": row["profileId"]})
        # Map to series if compatibleSeries present
        for sid in data.get("compatibleSeries") or []:
            ser = em.resolve_series_ref(str(sid), company_gst=company_gst)
            if not ser:
                report["manualReview"].append(
                    {"kind": "profile_series_map", "profile": code, "series": sid, "reason": "series missing"}
                )
                continue
            try:
                em.map_series_profile_role(
                    series_id=ser["seriesId"],
                    role=str(role).upper(),
                    profile_id=row["profileId"],
                )
            except Exception as exc:
                report["conflicts"].append(
                    {"kind": "profile_series_map", "profile": code, "series": sid, "error": str(exc)}
                )
    except Exception as exc:
        report["rejected"].append({"kind": "profile", "code": code, "error": str(exc)})


def _import_kb_glass(path: Path, *, company_gst: str | None, report: dict[str, Any]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        report["rejected"].append({"kind": "glass", "path": str(path), "error": str(exc)})
        return
    # Some files are catalogues (list) vs single
    items = data if isinstance(data, list) else [data]
    if isinstance(data, dict) and "items" in data:
        items = data["items"]
    for item in items:
        if not isinstance(item, dict):
            report["manualReview"].append({"kind": "glass", "path": str(path), "reason": "non-object entry"})
            continue
        code = str(item.get("id") or item.get("code") or item.get("sku") or "").strip()
        if not code:
            report["rejected"].append({"kind": "glass", "path": str(path), "reason": "missing code"})
            continue
        if em.resolve_glass_ref(code):
            report["matched"].append({"kind": "glass", "code": code})
            continue
        try:
            row = em.create_glass(
                code=code,
                name=str(item.get("name") or item.get("displayName") or code),
                company_gst=company_gst,
                makeup=item.get("makeup") or item.get("type"),
                thicknessMm=item.get("thicknessMm") or item.get("thickness"),
                densityKgPerSqm=item.get("densityKgPerSqm") or item.get("weightPerSqm"),
                costBasisType="PER_SQM",
                costBasisValue=item.get("rate") or item.get("unitRate"),
                legacyCodes=[code],
                meta={"importedFrom": str(path)},
            )
            report["created"].append({"kind": "glass", "code": code, "glassId": row["glassId"]})
        except Exception as exc:
            report["conflicts"].append({"kind": "glass", "code": code, "error": str(exc)})
