"""KB / memory version field-level compare (e.g. V3 vs V4 Track 29→30)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from WEOS.learning.v2_store import versions_dir
from WEOS.paths import knowledge_base_dir


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _version_lib_dir(version: int) -> Path:
    return versions_dir() / f"v{int(version)}"


def _iter_items(version: int) -> dict[str, dict[str, Any]]:
    """Map 'folder/id' → document for a KB version snapshot."""
    root = _version_lib_dir(version)
    out: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return out
    for folder in root.iterdir():
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        for f in folder.glob("*.json"):
            if f.name.startswith("_") or f.name == "meta.json":
                continue
            doc = _load_json(f)
            if doc is None:
                continue
            iid = str(doc.get("id") or f.stem)
            out[f"{folder.name}/{iid}"] = doc
    return out


def _diff_dicts(a: Any, b: Any, prefix: str = "") -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    skip = {"updated_at", "created_at", "approved_at", "history"}
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a) | set(b)
        for k in sorted(keys):
            if k in skip:
                continue
            path = f"{prefix}.{k}" if prefix else k
            if k not in a:
                diffs.append({"path": path, "change": "added", "before": None, "after": b[k]})
            elif k not in b:
                diffs.append({"path": path, "change": "removed", "before": a[k], "after": None})
            else:
                diffs.extend(_diff_dicts(a[k], b[k], path))
    elif isinstance(a, list) and isinstance(b, list):
        if a != b:
            diffs.append({"path": prefix or "$", "change": "changed", "before": a, "after": b})
    else:
        if a != b:
            diffs.append({"path": prefix or "$", "change": "changed", "before": a, "after": b})
    return diffs


def compare_versions(from_version: int, to_version: int, *, folder: str | None = None) -> dict[str, Any]:
    """
    Field-level diff between two KB version snapshots.
    Example: Track 29→30 appears as path crossSectionWidthMm changed.
    """
    a = _iter_items(from_version)
    b = _iter_items(to_version)
    if folder:
        a = {k: v for k, v in a.items() if k.startswith(folder.rstrip("/") + "/")}
        b = {k: v for k, v in b.items() if k.startswith(folder.rstrip("/") + "/")}

    keys = set(a) | set(b)
    items: list[dict[str, Any]] = []
    for key in sorted(keys):
        left = a.get(key)
        right = b.get(key)
        if left is None:
            items.append({"key": key, "change": "added", "diffs": [{"path": "$", "change": "added", "before": None, "after": right}]})
        elif right is None:
            items.append({"key": key, "change": "removed", "diffs": [{"path": "$", "change": "removed", "before": left, "after": None}]})
        else:
            field_diffs = _diff_dicts(left, right)
            if field_diffs:
                items.append({"key": key, "change": "modified", "diffs": field_diffs, "id": left.get("id") or right.get("id"), "name": left.get("name") or left.get("seriesName") or right.get("name")})

    summary = {
        "added": sum(1 for x in items if x["change"] == "added"),
        "removed": sum(1 for x in items if x["change"] == "removed"),
        "modified": sum(1 for x in items if x["change"] == "modified"),
        "unchanged": len(keys) - len(items),
    }

    # Highlight common engineering fields in a flat list for UI
    highlights = []
    for it in items:
        for d in it.get("diffs") or []:
            path = str(d.get("path") or "")
            if any(
                x in path.lower()
                for x in ("track", "width", "height", "thickness", "weight", "rate", "expression", "priority")
            ):
                highlights.append(
                    {
                        "item": it.get("key"),
                        "name": it.get("name"),
                        "path": path,
                        "before": d.get("before"),
                        "after": d.get("after"),
                        "label": f"{it.get('name') or it.get('key')}: {path} {d.get('before')}→{d.get('after')}",
                    }
                )

    return {
        "ok": True,
        "fromVersion": int(from_version),
        "toVersion": int(to_version),
        "fromExists": _version_lib_dir(from_version).is_dir(),
        "toExists": _version_lib_dir(to_version).is_dir(),
        "summary": summary,
        "items": items,
        "highlights": highlights[:50],
        "message": f"Compared KB v{from_version} → v{to_version}: {summary['modified']} modified, {summary['added']} added, {summary['removed']} removed",
        "production_modified": False,
    }


def compare_working_to_version(version: int) -> dict[str, Any]:
    """Diff current libraries/ working set vs a frozen version (optional helper)."""
    # Synthesize a pseudo compare by publishing nothing — walk libraries vs version
    from WEOS.learning.v2_store import current_kb_version, lib_subdir

    cur = current_kb_version()
    # Reuse version-to-version if current was just published; else build from libraries
    working: dict[str, dict[str, Any]] = {}
    for name in ("product_series", "profiles", "hardware", "glass", "formulas"):
        d = lib_subdir(name)
        if not d.is_dir():
            continue
        for f in d.glob("*.json"):
            if f.name.startswith("_"):
                continue
            doc = _load_json(f)
            if doc:
                working[f"{name}/{doc.get('id') or f.stem}"] = doc

    frozen = _iter_items(version)
    # Temporary: write working as fake "to" by using compare logic inline
    keys = set(working) | set(frozen)
    items = []
    for key in sorted(keys):
        left = frozen.get(key)
        right = working.get(key)
        if left is None and right is not None:
            items.append({"key": key, "change": "added", "diffs": []})
        elif right is None and left is not None:
            items.append({"key": key, "change": "removed", "diffs": []})
        elif left and right:
            diffs = _diff_dicts(left, right)
            if diffs:
                items.append({"key": key, "change": "modified", "diffs": diffs})
    return {
        "ok": True,
        "fromVersion": version,
        "toVersion": f"working(v{cur})",
        "items": items,
        "summary": {
            "modified": sum(1 for x in items if x["change"] == "modified"),
            "added": sum(1 for x in items if x["change"] == "added"),
            "removed": sum(1 for x in items if x["change"] == "removed"),
        },
        "kbDir": str(knowledge_base_dir()),
    }
