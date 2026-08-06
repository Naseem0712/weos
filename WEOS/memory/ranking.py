"""Memory ranking metadata — Confidence / Source / Approved / Used / Last Used."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from WEOS.memory.schemas import ranking_fields
from WEOS.memory.store import get_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enrich_item(item: dict[str, Any]) -> dict[str, Any]:
    """Attach a `ranking` card to a memory item (non-destructive copy)."""
    out = dict(item)
    out["ranking"] = ranking_fields(item)
    return out


def enrich_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [enrich_item(x) for x in items]


def list_ranked(memory_type: str, *, status: str | None = None) -> list[dict[str, Any]]:
    items = enrich_list(get_store().list(memory_type, status=status))
    # Sort: approved first, then priority desc, confidence desc, used desc
    items.sort(
        key=lambda x: (
            0 if (x.get("ranking") or {}).get("approved") else 1,
            -int((x.get("ranking") or {}).get("priority") or 0),
            -float((x.get("ranking") or {}).get("confidence") or 0),
            -int((x.get("ranking") or {}).get("usedInProjects") or 0),
        )
    )
    return items


def record_usage(memory_type: str, item_id: str, *, projects: int = 1) -> dict[str, Any] | None:
    """Bump usedInProjects + lastUsed when Brain successfully generates from a memory."""
    store = get_store()
    try:
        item = store.get(memory_type, item_id)
    except FileNotFoundError:
        return None
    item["usedInProjects"] = int(item.get("usedInProjects") or 0) + max(1, int(projects))
    item["lastUsed"] = _now()
    # Persist without changing approval status / library mirror
    return store.save(
        memory_type,
        item,
        as_approved=(item.get("status") == "approved"),
        approved_by=item.get("approved_by"),
        publish_to_library=False,
    )


def pick_by_priority(
    items: list[dict[str, Any]],
    *,
    category: str | None = None,
    approved_only: bool = True,
) -> dict[str, Any] | None:
    """Pick highest-priority approved item (optionally filtered by formula category)."""
    pool = list(items or [])
    if category:
        pool = [x for x in pool if (x.get("category") or "").lower() == category.lower()]
    if approved_only:
        approved = [x for x in pool if (x.get("status") or "") == "approved"]
        pool = approved or []
    if not pool:
        return None
    pool.sort(key=lambda x: (-int(x.get("priority") if x.get("priority") is not None else 50), str(x.get("id"))))
    return pool[0]


def group_formulas_by_priority(formulas: list[dict[str, Any]]) -> dict[str, Any]:
    """For each category, select the winning formula and list runners-up."""
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for f in formulas or []:
        cat = str(f.get("category") or f.get("outputName") or "general")
        by_cat.setdefault(cat, []).append(f)
    winners: dict[str, Any] = {}
    for cat, group in by_cat.items():
        win = pick_by_priority(group, approved_only=True) or pick_by_priority(group, approved_only=False)
        ranked = sorted(
            group,
            key=lambda x: (-int(x.get("priority") if x.get("priority") is not None else 50), str(x.get("id"))),
        )
        winners[cat] = {
            "selected": win,
            "priority": int((win or {}).get("priority") or 50) if win else None,
            "candidates": [
                {
                    "id": x.get("id"),
                    "name": x.get("name"),
                    "priority": int(x.get("priority") if x.get("priority") is not None else 50),
                    "status": x.get("status"),
                    "formulaVersion": x.get("formulaVersion") or 1,
                }
                for x in ranked
            ],
        }
    return winners
