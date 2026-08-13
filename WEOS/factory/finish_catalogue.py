"""Powder-coat / finish colour library — cart Colour dropdown + custom add.

Defaults cover window powder-coats and shower hardware colours. Fabricators can
add extra colour *names* (no code) via the cart “+ colour” control; entries live
under ``knowledge_base/libraries/finishes/``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from WEOS.paths import knowledge_base_dir

DEFAULT_FINISHES: tuple[dict[str, str], ...] = (
    {"id": "white", "name": "White", "kind": "powder_coat"},
    {"id": "black_texture", "name": "Black Texture", "kind": "powder_coat"},
    {"id": "wood_oak", "name": "Wood Oak", "kind": "powder_coat"},
    {"id": "bronze", "name": "Bronze", "kind": "powder_coat"},
    {"id": "matt_black", "name": "Matt black", "kind": "shower"},
    {"id": "brush_gold", "name": "Brush gold", "kind": "shower"},
    {"id": "gold", "name": "Gold", "kind": "shower"},
    {"id": "grey", "name": "Grey", "kind": "shower"},
    {"id": "rose_gold", "name": "Rose gold", "kind": "shower"},
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "finish"


def catalogue_dir() -> Path:
    d = knowledge_base_dir() / "libraries" / "finishes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def custom_path() -> Path:
    return catalogue_dir() / "custom.json"


def _read_custom() -> list[dict[str, Any]]:
    path = custom_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, Mapping):
        items = data.get("finishes") or data.get("items") or []
    else:
        items = data
    out: list[dict[str, Any]] = []
    if isinstance(items, (list, tuple)):
        for it in items:
            if isinstance(it, Mapping) and (it.get("id") or it.get("name")):
                out.append(dict(it))
    return out


def _write_custom(items: list[dict[str, Any]]) -> None:
    custom_path().write_text(
        json.dumps({"finishes": items, "updatedOn": _now()}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def list_finishes(*, kind: str | None = None) -> list[dict[str, Any]]:
    """Defaults first, then custom names (no truncation)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for src in list(DEFAULT_FINISHES) + _read_custom():
        fid = _slug(str(src.get("id") or src.get("name") or ""))
        if not fid or fid in seen:
            continue
        k = str(src.get("kind") or "powder_coat")
        if kind and k not in (kind, "all") and kind not in ("all", "any"):
            if kind == "shower" and k not in ("shower", "all"):
                # still include powder coats — fabricator may reuse them
                pass
        seen.add(fid)
        out.append({
            "id": fid,
            "name": str(src.get("name") or fid.replace("_", " ").title()),
            "kind": k,
            "custom": bool(src.get("custom")),
        })
    return out


def cart_colour_options() -> list[dict[str, str]]:
    return [{"id": f["id"], "label": f["name"]} for f in list_finishes()]


def save_finish(name: str, *, kind: str = "powder_coat", finish_id: str | None = None) -> dict[str, Any]:
    label = (name or "").strip()
    if not label:
        raise ValueError("Colour name is required")
    fid = _slug(finish_id or label)
    items = _read_custom()
    rec = {"id": fid, "name": label, "kind": str(kind or "powder_coat"), "custom": True, "updatedOn": _now()}
    replaced = False
    for i, it in enumerate(items):
        if _slug(str(it.get("id") or "")) == fid:
            items[i] = rec
            replaced = True
            break
    if not replaced:
        items.append(rec)
    _write_custom(items)
    return rec


def delete_finish(finish_id: str) -> dict[str, Any]:
    fid = _slug(finish_id)
    items = [it for it in _read_custom() if _slug(str(it.get("id") or "")) != fid]
    _write_custom(items)
    return {"ok": True, "deleted": fid}
