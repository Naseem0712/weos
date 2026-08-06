"""Memory relationship graph — neighbors / tree / lightweight JSON for UI."""

from __future__ import annotations

from typing import Any

from WEOS.memory.store import get_store


CHAIN = [
    ("commercial", "Customer"),
    ("quotation", "Quotation"),
    ("product", "Series / Product"),
    ("profile", "Outer Track / Profiles"),
    ("hardware", "Handle / Hardware"),
    ("glass", "Glass"),
    ("formula", "Formula / Brush"),
    ("factory", "Factory"),
    ("quotation", "Quotation"),
    ("commercial", "Customer"),
]


def graph_snapshot() -> dict[str, Any]:
    rel = get_store().relationships()
    edges = list(rel.get("edges") or [])
    nodes: dict[str, dict[str, Any]] = {}
    for e in edges:
        for side, typ, iid in (
            ("from", e.get("fromType"), e.get("fromId")),
            ("to", e.get("toType"), e.get("toId")),
        ):
            if not iid:
                continue
            key = f"{typ}:{iid}"
            nodes.setdefault(key, {"id": iid, "memoryType": typ, "key": key})
    return {
        "ok": True,
        "chain": rel.get("chain") or [c[1] for c in CHAIN],
        "nodes": list(nodes.values()),
        "edges": edges,
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
    }


def neighbors(
    memory_type: str,
    item_id: str,
    *,
    depth: int = 1,
    direction: str = "both",
) -> dict[str, Any]:
    """Query graph neighbors for a node (list/tree JSON)."""
    rel = get_store().relationships()
    edges = list(rel.get("edges") or [])
    depth = max(1, min(4, int(depth)))

    visited: set[tuple[str, str]] = {(memory_type, item_id)}
    frontier = [(memory_type, item_id, 0)]
    out_edges: list[dict[str, Any]] = []
    tree: dict[str, Any] = {
        "memoryType": memory_type,
        "id": item_id,
        "children": [],
    }
    node_map: dict[tuple[str, str], dict[str, Any]] = {(memory_type, item_id): tree}

    while frontier:
        typ, iid, d = frontier.pop(0)
        if d >= depth:
            continue
        for e in edges:
            nxt: tuple[str, str] | None = None
            if direction in ("both", "out") and e.get("fromType") == typ and e.get("fromId") == iid:
                nxt = (str(e.get("toType")), str(e.get("toId")))
            elif direction in ("both", "in") and e.get("toType") == typ and e.get("toId") == iid:
                nxt = (str(e.get("fromType")), str(e.get("fromId")))
            if not nxt or not nxt[1]:
                continue
            out_edges.append(e)
            if nxt in visited:
                continue
            visited.add(nxt)
            child = {"memoryType": nxt[0], "id": nxt[1], "rel": e.get("rel"), "children": []}
            node_map[(typ, iid)]["children"].append(child)
            node_map[nxt] = child
            frontier.append((nxt[0], nxt[1], d + 1))

    # Deduplicate edges
    seen = set()
    uniq = []
    for e in out_edges:
        key = (e.get("fromType"), e.get("fromId"), e.get("toType"), e.get("toId"), e.get("rel"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)

    return {
        "ok": True,
        "root": {"memoryType": memory_type, "id": item_id},
        "depth": depth,
        "neighbors": [
            {"memoryType": t, "id": i}
            for (t, i) in visited
            if not (t == memory_type and i == item_id)
        ],
        "tree": tree,
        "edges": uniq,
        "chainHint": "Series → Outer Track → Handle → Glass → Brush → Factory → Quotation → Customer",
    }


def ensure_series_edges(series_id: str, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist / refresh edges from a Brain context pack for graph visualization."""
    store = get_store()
    try:
        product = store.get("product", series_id)
    except FileNotFoundError:
        product = (ctx or {}).get("series") or {"id": series_id}
    # Touch save to rebuild edges from relationships/compatible ids
    if product.get("id"):
        # Non-destructive: re-save existing to refresh relationship index
        try:
            store.save(
                "product",
                product,
                as_approved=product.get("status") == "approved",
                approved_by=product.get("approved_by"),
                publish_to_library=False,
            )
        except Exception:
            pass
    # Also touch linked items from context
    if ctx:
        for mt, key in (
            ("profile", "profiles"),
            ("hardware", "hardware"),
            ("glass", "glass"),
            ("formula", "formulas"),
            ("drawing", "drawings"),
            ("factory", "factoryRules"),
        ):
            for it in ctx.get(key) or []:
                if not it.get("id"):
                    continue
                it = dict(it)
                it.setdefault("relationships", {})
                rels = dict(it.get("relationships") or {})
                rels.setdefault("seriesIds", [])
                if series_id not in rels["seriesIds"]:
                    rels["seriesIds"] = list(rels["seriesIds"]) + [series_id]
                it["relationships"] = rels
                it.setdefault("seriesId", series_id)
                try:
                    store.save(
                        mt,
                        it,
                        as_approved=it.get("status") == "approved",
                        approved_by=it.get("approved_by"),
                        publish_to_library=False,
                    )
                except Exception:
                    continue
    return neighbors("product", series_id, depth=2)
