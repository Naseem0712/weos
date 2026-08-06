"""Admin gate for Memory Architecture: approve / reject / merge / version / rollback.

AI never calls these for production side-effects without an admin actor.
"""

from __future__ import annotations

from typing import Any

from WEOS.memory import cache
from WEOS.memory.schemas import MEM_LEARNING, MEMORY_TYPES
from WEOS.memory.store import get_store


def approve_memory(
    memory_type: str,
    item_id: str,
    *,
    approved_by: str = "admin",
    publish_version: bool = True,
    publish_to_library: bool = True,
    reason: str = "",
) -> dict[str, Any]:
    """Approve a memory item → optional library mirror → optional new KB version."""
    store = get_store()
    item = store.get(memory_type, item_id)
    item["status"] = "approved"
    if memory_type == MEM_LEARNING:
        item["adminDecision"] = "approved"
    saved = store.save(
        memory_type,
        item,
        as_approved=True,
        approved_by=approved_by,
        publish_to_library=publish_to_library,
    )

    version_meta = None
    if publish_version:
        from WEOS.learning.v2_store import publish_kb_version

        version_meta = publish_kb_version(
            reason=reason or f"Approved {memory_type}/{item_id}",
            proposal_id=None,
            approved_by=approved_by,
        )
        saved["kb_version"] = version_meta.get("version")
        if memory_type == MEM_LEARNING:
            saved["resultingKbVersion"] = version_meta.get("version")
            store.save(memory_type, saved, as_approved=True, approved_by=approved_by, publish_to_library=False)

    cache.invalidate_kb()
    try:
        from WEOS.memory.search.index import rebuild_index

        rebuild_index()
    except Exception:
        pass

    return {
        "ok": True,
        "item": saved,
        "kbVersion": version_meta,
        "production_modified": False,
        "message": "Approved into Knowledge Base. Production products unchanged.",
    }


def reject_memory(
    memory_type: str,
    item_id: str,
    *,
    rejected_by: str = "admin",
    reason: str = "",
) -> dict[str, Any]:
    store = get_store()
    item = store.get(memory_type, item_id)
    item["status"] = "rejected"
    item["rejected_by"] = rejected_by
    item["reject_reason"] = reason
    if memory_type == MEM_LEARNING:
        item["adminDecision"] = "rejected"
    saved = store.save(memory_type, item, as_approved=False)
    return {"ok": True, "item": saved}


def merge_memory(
    memory_type: str,
    source_id: str,
    target_id: str,
    *,
    merged_by: str = "admin",
) -> dict[str, Any]:
    """Merge source into target (target wins on conflicts for scalars; lists union)."""
    store = get_store()
    src = store.get(memory_type, source_id)
    tgt = store.get(memory_type, target_id)
    merged = dict(tgt)
    for k, v in src.items():
        if k in ("id", "created_at", "memoryType"):
            continue
        if v in (None, "", [], {}):
            continue
        if isinstance(v, list) and isinstance(merged.get(k), list):
            merged[k] = list(dict.fromkeys([*merged[k], *v])) if v and not isinstance(v[0], dict) else merged[k] + [
                x for x in v if x not in merged[k]
            ]
        elif k not in merged or merged[k] in (None, "", [], {}):
            merged[k] = v
    merged["merged_from"] = source_id
    merged["merged_by"] = merged_by
    saved = store.save(memory_type, merged, as_approved=tgt.get("status") == "approved", approved_by=merged_by)
    # soft-archive source
    store.delete(memory_type, source_id, soft=True)
    cache.invalidate_kb()
    return {"ok": True, "item": saved, "archivedSource": source_id}


def publish_version(*, reason: str, approved_by: str = "admin") -> dict[str, Any]:
    from WEOS.learning.v2_store import publish_kb_version

    meta = publish_kb_version(reason=reason, approved_by=approved_by)
    cache.invalidate_kb()
    return meta


def rollback_kb(to_version: int, *, rolled_back_by: str = "admin", reason: str = "") -> dict[str, Any]:
    """Restore libraries from versions/vN and publish a new snapshot marking the rollback."""
    from WEOS.learning.v2_store import rollback_kb_version

    result = rollback_kb_version(
        to_version,
        rolled_back_by=rolled_back_by,
        reason=reason or f"Rollback to v{to_version}",
    )
    cache.invalidate_kb()
    try:
        from WEOS.memory.search.index import rebuild_index

        rebuild_index()
    except Exception:
        pass
    return result


def list_types() -> list[dict[str, str]]:
    from WEOS.memory.schemas import MEMORY_LABELS

    return [{"id": t, "label": MEMORY_LABELS.get(t, t)} for t in MEMORY_TYPES]
