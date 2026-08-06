"""Unified Manufacturing Memory store.

Library-backed types (product/profile/hardware/glass/formula/quotation) read/write
through Learning Engine V2 libraries. Dedicated types live under
knowledge_base/memories/<type>/.

Production products are NEVER written from this store.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from WEOS.memory.schemas import (
    LIBRARY_FOLDER,
    MEM_COMMERCIAL,
    MEM_ENGINEERING,
    MEM_FORMULA,
    MEM_LEARNING,
    MEM_PRODUCT,
    MEMORY_TYPES,
    empty_memory,
    enrich_from_library,
)
from WEOS.paths import knowledge_base_dir

_store_lock = threading.RLock()
_store_singleton: "MemoryStore | None" = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "item"


def memories_root() -> Path:
    d = knowledge_base_dir() / "memories"
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_dir(memory_type: str) -> Path:
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"Unknown memory type: {memory_type}")
    d = memories_root() / memory_type
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_memory_dirs() -> None:
    from WEOS.learning.v2_store import ensure_v2_dirs

    ensure_v2_dirs()
    for mt in MEMORY_TYPES:
        memory_dir(mt)
    # Relationship index + search index live under memories/
    (memories_root() / "_index").mkdir(parents=True, exist_ok=True)
    rel = memories_root() / "relationships.json"
    if not rel.is_file():
        rel.write_text(
            json.dumps(
                {
                    "description": "Customer → Quotation → Products → Profiles → Hardware → Glass → Formula → Drawing → Machine → Factory → Costing → Reports",
                    "edges": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )


class MemoryStore:
    """CRUD / list across all memory namespaces."""

    def __init__(self) -> None:
        ensure_memory_dirs()

    # ── paths ──────────────────────────────────────────────────────────────

    def _dedicated_path(self, memory_type: str, item_id: str) -> Path:
        return memory_dir(memory_type) / f"{item_id}.json"

    def _uses_library(self, memory_type: str) -> bool:
        return LIBRARY_FOLDER.get(memory_type) is not None

    # ── list / get ─────────────────────────────────────────────────────────

    def list(self, memory_type: str, *, status: str | None = None) -> list[dict[str, Any]]:
        ensure_memory_dirs()
        if memory_type not in MEMORY_TYPES:
            raise ValueError(f"Unknown memory type: {memory_type}")

        items: list[dict[str, Any]] = []
        folder = LIBRARY_FOLDER.get(memory_type)
        if folder:
            from WEOS.learning.v2_store import list_library

            for lib in list_library(folder):
                items.append(enrich_from_library(memory_type, lib))
        # Always merge dedicated overrides / extras (drawings, engineering packs, etc.)
        for path in sorted(memory_dir(memory_type).glob("*.json")):
            if path.name.startswith("_"):
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            doc.setdefault("id", path.stem)
            doc.setdefault("memoryType", memory_type)
            # Prefer dedicated if same id (richer schema / overrides)
            items = [x for x in items if x.get("id") != doc["id"]]
            items.append(doc)

        if status:
            items = [x for x in items if (x.get("status") or "") == status]
        return items

    def get(self, memory_type: str, item_id: str) -> dict[str, Any]:
        path = self._dedicated_path(memory_type, item_id)
        if path.is_file():
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc.setdefault("memoryType", memory_type)
            return doc

        folder = LIBRARY_FOLDER.get(memory_type)
        if folder:
            from WEOS.learning.v2_store import get_library_item

            try:
                return enrich_from_library(memory_type, get_library_item(folder, item_id))
            except FileNotFoundError:
                pass
        raise FileNotFoundError(f"Memory not found: {memory_type}/{item_id}")

    # ── write ──────────────────────────────────────────────────────────────

    def save(
        self,
        memory_type: str,
        item: dict[str, Any],
        *,
        as_approved: bool = False,
        approved_by: str | None = None,
        publish_to_library: bool = False,
    ) -> dict[str, Any]:
        """
        Persist a memory record.

        - Default: writes to knowledge_base/memories/<type>/ (draft/pending).
        - as_approved + publish_to_library: also mirrors into V2 libraries (admin path).
        - Formula Memory: appends history instead of silent overwrite.
        """
        if memory_type not in MEMORY_TYPES:
            raise ValueError(f"Unknown memory type: {memory_type}")
        ensure_memory_dirs()

        item = dict(item)
        item["memoryType"] = memory_type
        item_id = item.get("id") or f"{_slug(memory_type)}_{uuid.uuid4().hex[:8]}"
        item["id"] = item_id
        now = _now()
        item.setdefault("created_at", now)
        item["updated_at"] = now

        if as_approved:
            item["status"] = "approved"
            item["approved_at"] = now
            item["approved_by"] = approved_by or "admin"
        else:
            item.setdefault("status", "draft")

        # Formula versioning — never silent overwrite of expression
        if memory_type == MEM_FORMULA:
            item = self._merge_formula_history(item, approved_by=approved_by if as_approved else None)

        path = self._dedicated_path(memory_type, item_id)
        path.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")

        if publish_to_library and as_approved:
            self._mirror_to_library(memory_type, item)

        self._touch_relationship(memory_type, item)
        return item

    def _merge_formula_history(self, item: dict[str, Any], *, approved_by: str | None) -> dict[str, Any]:
        path = self._dedicated_path(MEM_FORMULA, item["id"])
        history = list(item.get("history") or [])
        prev_expr = None
        prev_ver = int(item.get("formulaVersion") or 1)
        if path.is_file():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                prev_expr = old.get("expression")
                prev_ver = int(old.get("formulaVersion") or 1)
                history = list(old.get("history") or history)
            except Exception:
                pass

        new_expr = item.get("expression")
        if prev_expr is not None and new_expr and new_expr != prev_expr:
            # bump version + archive previous
            history.append(
                {
                    "formulaVersion": prev_ver,
                    "expression": prev_expr,
                    "variables": item.get("variables") or [],
                    "archived_at": _now(),
                    "reason": "superseded",
                }
            )
            item["formulaVersion"] = prev_ver + 1
            item["revision"] = int(item.get("revision") or 1) + 1
        else:
            item.setdefault("formulaVersion", prev_ver)

        if approved_by:
            item["approvalDate"] = _now()
            history.append(
                {
                    "formulaVersion": item["formulaVersion"],
                    "expression": item.get("expression"),
                    "variables": item.get("variables") or [],
                    "approved_at": _now(),
                    "approved_by": approved_by,
                    "reason": "admin_approve",
                }
            )
        item["history"] = history
        return item

    def _mirror_to_library(self, memory_type: str, item: dict[str, Any]) -> None:
        folder = LIBRARY_FOLDER.get(memory_type)
        if not folder:
            return
        from WEOS.learning.v2_store import save_library_item

        # Strip memory-only fields that libraries don't need, keep compatible shape
        lib_item = {k: v for k, v in item.items() if k not in ("memoryType", "history") or memory_type == MEM_FORMULA}
        if memory_type == MEM_PRODUCT:
            # libraries use product_series shell
            lib_item.setdefault("seriesName", item.get("seriesName") or item.get("id"))
            if item.get("profileIds") and not lib_item.get("profiles"):
                lib_item["profiles"] = list(item["profileIds"])
            if item.get("hardwareIds") and not lib_item.get("hardware"):
                lib_item["hardware"] = list(item["hardwareIds"])
            if item.get("glassIds") and not lib_item.get("glass"):
                lib_item["glass"] = list(item["glassIds"])
            if item.get("formulaIds") and not lib_item.get("formulas"):
                lib_item["formulas"] = list(item["formulaIds"])
        save_library_item(folder, lib_item, link_existing=True)

    def delete(self, memory_type: str, item_id: str, *, soft: bool = True) -> dict[str, Any]:
        """Soft-delete by default (status=archived). Hard delete only dedicated file."""
        try:
            item = self.get(memory_type, item_id)
        except FileNotFoundError as exc:
            raise exc
        if soft:
            item["status"] = "archived"
            item["updated_at"] = _now()
            path = self._dedicated_path(memory_type, item_id)
            path.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"ok": True, "action": "archived", "item": item}
        path = self._dedicated_path(memory_type, item_id)
        if path.is_file():
            path.unlink()
            return {"ok": True, "action": "deleted", "id": item_id}
        raise FileNotFoundError(f"No dedicated memory file to delete: {memory_type}/{item_id}")

    # ── relationships ──────────────────────────────────────────────────────

    def _touch_relationship(self, memory_type: str, item: dict[str, Any]) -> None:
        rel_path = memories_root() / "relationships.json"
        try:
            data = json.loads(rel_path.read_text(encoding="utf-8")) if rel_path.is_file() else {"edges": []}
        except Exception:
            data = {"edges": []}
        edges = list(data.get("edges") or [])
        item_id = item.get("id")
        # Rebuild edges from this node
        edges = [e for e in edges if not (e.get("fromType") == memory_type and e.get("fromId") == item_id)]

        def add(to_type: str, to_id: str, rel: str) -> None:
            if not to_id:
                return
            edges.append(
                {
                    "fromType": memory_type,
                    "fromId": item_id,
                    "toType": to_type,
                    "toId": to_id,
                    "rel": rel,
                    "updated_at": _now(),
                }
            )

        rels = item.get("relationships") or {}
        for key, to_type in (
            ("seriesIds", MEM_PRODUCT),
            ("profileIds", "profile"),
            ("hardwareIds", "hardware"),
            ("glassIds", "glass"),
            ("formulaIds", MEM_FORMULA),
            ("drawingIds", "drawing"),
            ("customerIds", MEM_COMMERCIAL),
        ):
            for tid in rels.get(key) or item.get(key) or []:
                if isinstance(tid, dict):
                    tid = tid.get("id")
                add(to_type, str(tid), key)

        for sid in item.get("compatibleSeries") or []:
            add(MEM_PRODUCT, str(sid), "compatibleSeries")
        if item.get("seriesId"):
            add(MEM_PRODUCT, str(item["seriesId"]), "seriesId")

        data["edges"] = edges[-5000:]  # cap growth
        data["updated_at"] = _now()
        rel_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def relationships(self) -> dict[str, Any]:
        ensure_memory_dirs()
        path = memories_root() / "relationships.json"
        if not path.is_file():
            return {"edges": [], "chain": _RELATIONSHIP_CHAIN}
        data = json.loads(path.read_text(encoding="utf-8"))
        data["chain"] = _RELATIONSHIP_CHAIN
        return data

    def summary(self) -> dict[str, Any]:
        ensure_memory_dirs()
        counts = {}
        for mt in MEMORY_TYPES:
            try:
                counts[mt] = len(self.list(mt))
            except Exception:
                counts[mt] = 0
        from WEOS.learning.v2_store import current_kb_version

        return {
            "memoryTypes": list(MEMORY_TYPES),
            "counts": counts,
            "kbVersion": current_kb_version(),
            "autoWriteProduction": False,
            "philosophy": "Observe → Suggest → Admin Review → Approve → KB Version → Brain",
        }


_RELATIONSHIP_CHAIN = [
    "Customer",
    "Quotation",
    "Products",
    "Profiles",
    "Hardware",
    "Glass",
    "Formula",
    "Drawing",
    "Machine",
    "Factory",
    "Costing",
    "Reports",
]


def get_store() -> MemoryStore:
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = MemoryStore()
        return _store_singleton


def write_observation_as_learning(
    *,
    observation_type: str,
    summary: str,
    evidence: dict[str, Any],
    suggestion: str,
    target_memory_type: str = "",
    target_payload: dict[str, Any] | None = None,
    domain: str = "engineering",
) -> dict[str, Any]:
    """Record a Learning Memory observation (suggestion only — not approved)."""
    store = get_store()
    total = float((evidence or {}).get("total") or 0) or 0
    count = float((evidence or {}).get("count") or 0) or 0
    freq = (count / total) if total else None
    shell = empty_memory(MEM_LEARNING)
    shell.update(
        {
            "id": f"learn_{_slug(observation_type)}_{uuid.uuid4().hex[:8]}",
            "observationType": observation_type,
            "summary": summary,
            "evidence": evidence or {},
            "suggestion": suggestion,
            "frequency": round(freq, 4) if freq is not None else None,
            "targetMemoryType": target_memory_type,
            "targetPayload": target_payload or {},
            "domain": domain,
            "status": "pending_approval",
            "adminDecision": None,
        }
    )
    return store.save(MEM_LEARNING, shell, as_approved=False)
