"""Compatibility checks — e.g. series glass thickness allow-list."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from WEOS.memory.schemas import MEM_ENGINEERING, MEM_PRODUCT, empty_compatibility_rule
from WEOS.memory.store import get_store, memories_root


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rules_path() -> Path:
    d = memories_root() / "_rules"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "compatibility.json"
    if not p.is_file():
        seed = {
            "description": "Compatibility constraints. Warnings by default; never auto-rewrite production.",
            "rules": [
                {
                    "id": "compat_29mm_glass_thickness",
                    "title": "29mm Sliding glass thickness",
                    "seriesId": "29mm_sliding_smoke",
                    "field": "glassThicknessMm",
                    "allowed": [5, 6, 8],
                    "message": "Series only supports 5/6/8 mm glass",
                    "severity": "warning",
                    "status": "approved",
                    "priority": 80,
                    "approved_by": "seed",
                    "approved_at": _now(),
                }
            ],
            "updated_at": _now(),
        }
        p.write_text(json.dumps(seed, indent=2), encoding="utf-8")
    return p


def list_compatibility(*, status: str | None = "approved", series_id: str | None = None) -> list[dict[str, Any]]:
    data = json.loads(_rules_path().read_text(encoding="utf-8"))
    rules = list(data.get("rules") or [])
    try:
        for eng in get_store().list(MEM_ENGINEERING):
            for cr in eng.get("compatibilityRules") or []:
                if isinstance(cr, dict) and cr.get("id"):
                    rules.append({**cr, "fromEngineering": eng.get("id")})
    except Exception:
        pass
    if status:
        rules = [r for r in rules if (r.get("status") or "approved") == status]
    if series_id:
        rules = [r for r in rules if not r.get("seriesId") or r.get("seriesId") == series_id]
    return rules


def save_compatibility(rule: dict[str, Any], *, as_approved: bool = False, approved_by: str = "admin") -> dict[str, Any]:
    path = _rules_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = list(data.get("rules") or [])
    shell = empty_compatibility_rule()
    shell.update({k: v for k, v in rule.items() if v is not None})
    shell["id"] = shell.get("id") or f"compat_{uuid.uuid4().hex[:8]}"
    shell["updated_at"] = _now()
    shell.setdefault("created_at", _now())
    if as_approved:
        shell["status"] = "approved"
        shell["approved_at"] = _now()
        shell["approved_by"] = approved_by
    else:
        shell.setdefault("status", "pending_approval")
    replaced = False
    for i, r in enumerate(rules):
        if r.get("id") == shell["id"]:
            rules[i] = shell
            replaced = True
            break
    if not replaced:
        rules.append(shell)
    data["rules"] = rules
    data["updated_at"] = _now()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return shell


def _series_allowed_glass(series: dict[str, Any] | None) -> list[float]:
    if not series:
        return []
    vals = series.get("glassThicknessMm") or []
    out: list[float] = []
    for v in vals:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def check_compatibility(
    *,
    series_id: str | None = None,
    series: dict[str, Any] | None = None,
    glass_thickness_mm: float | None = None,
    selections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pre-check selections against approved compatibility rules + series allow-lists.
    Example: 29mm + 10mm glass → warning (supports 5/6/8 only).
    """
    store = get_store()
    product = series
    if product is None and series_id:
        try:
            product = store.get(MEM_PRODUCT, series_id)
        except FileNotFoundError:
            product = None

    sid = series_id or (product or {}).get("id")
    rules = list_compatibility(status="approved", series_id=str(sid) if sid else None)
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    thickness = glass_thickness_mm
    if thickness is None and selections:
        thickness = selections.get("glassThicknessMm")

    # Built-in: product.glassThicknessMm allow-list
    allowed_from_product = _series_allowed_glass(product)
    if thickness is not None and allowed_from_product:
        if float(thickness) not in {float(x) for x in allowed_from_product}:
            warnings.append(
                {
                    "id": "product_glass_allowlist",
                    "field": "glassThicknessMm",
                    "value": thickness,
                    "allowed": allowed_from_product,
                    "message": f"Series only supports { '/'.join(str(int(x) if float(x).is_integer() else x) for x in allowed_from_product) } mm glass",
                    "severity": "warning",
                }
            )

    for rule in rules:
        field = rule.get("field") or "glassThicknessMm"
        allowed = rule.get("allowed") or []
        val = thickness if field == "glassThicknessMm" else (selections or {}).get(field)
        if val is None or not allowed:
            continue
        try:
            ok = float(val) in {float(x) for x in allowed}
        except (TypeError, ValueError):
            ok = val in allowed
        if ok:
            continue
        entry = {
            "id": rule.get("id"),
            "title": rule.get("title"),
            "field": field,
            "value": val,
            "allowed": allowed,
            "message": rule.get("message")
            or f"{field}={val} not compatible (allowed: {allowed})",
            "severity": rule.get("severity") or "warning",
        }
        if entry["severity"] == "error":
            errors.append(entry)
        else:
            warnings.append(entry)

    # Deduplicate by message
    seen: set[str] = set()
    uniq_w = []
    for w in warnings:
        key = str(w.get("message"))
        if key in seen:
            continue
        seen.add(key)
        uniq_w.append(w)

    return {
        "ok": len(errors) == 0,
        "compatible": len(errors) == 0 and len(uniq_w) == 0,
        "warnings": uniq_w,
        "errors": errors,
        "seriesId": sid,
        "checked": len(rules) + (1 if allowed_from_product else 0),
        "message": (errors[0]["message"] if errors else (uniq_w[0]["message"] if uniq_w else "Compatible")),
    }
