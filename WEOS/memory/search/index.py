"""Inverted-index + keyword/filter search across Manufacturing Memories.

Supports pragmatic queries such as:
  - sliding systems with 30mm track
  - products using Premium Handle
  - quotations with Black Texture
  - formulas related to Glass Width
  - products compatible with Series S29

Honest gap: no vector embeddings / semantic ANN in this skeleton.
Optional embeddings can be layered later behind the same search() API.
"""

from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from WEOS.memory.schemas import MEMORY_TYPES
from WEOS.memory.store import get_store, memories_root

_lock = threading.RLock()
_INDEX: dict[str, Any] | None = None

# Stopwords kept tiny so engineering tokens (mm, kg) survive
_STOP = {"a", "an", "the", "with", "and", "or", "of", "to", "for", "in", "on", "using", "related"}


def _index_path() -> Path:
    d = memories_root() / "_index"
    d.mkdir(parents=True, exist_ok=True)
    return d / "inverted.json"


def _tokenize(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", (text or "").lower())
    tokens: list[str] = []
    for t in raw:
        if t in _STOP or len(t) < 2:
            continue
        tokens.append(t)
        # Also index number+unit splits: 30mm → 30, mm
        m = re.match(r"^(\d+(?:\.\d+)?)(mm|kg|m|rft|pc)?$", t)
        if m:
            tokens.append(m.group(1))
            if m.group(2):
                tokens.append(m.group(2))
    return tokens


def _doc_text(memory_type: str, item: dict[str, Any]) -> str:
    parts: list[str] = [memory_type, str(item.get("id") or "")]
    for key in (
        "title",
        "name",
        "seriesName",
        "profileName",
        "profileCode",
        "profileType",
        "brand",
        "productCategory",
        "productDescription",
        "hardwareType",
        "category",
        "glassType",
        "colour",
        "expression",
        "description",
        "summary",
        "suggestion",
        "customerName",
        "customerFormat",
        "warranty",
        "payment",
        "notes",
        "stockCode",
        "partNumber",
        "supplier",
        "seriesCode",
        "drawingType",
    ):
        v = item.get(key)
        if v:
            parts.append(str(v))
    for key in ("compatibleSeries", "compatibleProducts", "usePosition", "tags", "preferredColours", "preferredProducts"):
        for v in item.get(key) or []:
            parts.append(str(v))
    # Dimensional tokens for track / profile search
    for key in ("crossSectionWidthMm", "crossSectionHeightMm", "wallThicknessMm", "thicknessMm"):
        if item.get(key) is not None:
            parts.append(f"{item[key]}mm")
            parts.append(str(item[key]))
    return " ".join(parts)


def rebuild_index() -> dict[str, Any]:
    """Full rebuild of inverted index from all memory namespaces."""
    store = get_store()
    inverted: dict[str, list[dict[str, str]]] = defaultdict(list)
    docs: list[dict[str, Any]] = []

    for mt in MEMORY_TYPES:
        try:
            items = store.list(mt)
        except Exception:
            continue
        for item in items:
            if (item.get("status") or "") == "archived":
                continue
            doc_id = f"{mt}:{item.get('id')}"
            text = _doc_text(mt, item)
            tokens = set(_tokenize(text))
            meta = {
                "id": item.get("id"),
                "memoryType": mt,
                "title": (
                    item.get("title")
                    or item.get("seriesName")
                    or item.get("profileName")
                    or item.get("name")
                    or item.get("id")
                ),
                "status": item.get("status"),
                "snippet": text[:220],
            }
            docs.append(meta)
            for tok in tokens:
                inverted[tok].append({"doc": doc_id, "type": mt, "id": str(item.get("id"))})

    payload = {
        "docs": docs,
        "inverted": dict(inverted),
        "docCount": len(docs),
        "tokenCount": len(inverted),
        "embeddings": False,
        "note": "Keyword/inverted index only — embeddings optional future layer",
    }
    path = _index_path()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    global _INDEX
    with _lock:
        _INDEX = payload
    return {"ok": True, "docCount": len(docs), "tokenCount": len(inverted)}


def _load_index() -> dict[str, Any]:
    global _INDEX
    with _lock:
        if _INDEX is not None:
            return _INDEX
        path = _index_path()
        if path.is_file():
            try:
                _INDEX = json.loads(path.read_text(encoding="utf-8"))
                return _INDEX
            except Exception:
                pass
    rebuild_index()
    with _lock:
        return _INDEX or {"docs": [], "inverted": {}}


def search(
    query: str,
    *,
    memory_type: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Keyword + filter search. Returns ranked hits."""
    q = (query or "").strip()
    idx = _load_index()
    inverted: dict[str, list[dict[str, str]]] = idx.get("inverted") or {}
    docs_by_key = {f"{d['memoryType']}:{d['id']}": d for d in (idx.get("docs") or [])}

    tokens = _tokenize(q) if q else []
    scores: dict[str, float] = defaultdict(float)

    if tokens:
        for tok in tokens:
            for hit in inverted.get(tok) or []:
                key = hit["doc"]
                scores[key] += 1.0
            # prefix match for short engineering queries
            if len(tok) >= 3:
                for inv_tok, hits in inverted.items():
                    if inv_tok.startswith(tok) and inv_tok != tok:
                        for hit in hits:
                            scores[hit["doc"]] += 0.4
    else:
        # empty query → list by type/filter
        for d in idx.get("docs") or []:
            scores[f"{d['memoryType']}:{d['id']}"] = 0.1

    # Phrase boosts for common manufacturing queries
    ql = q.lower()
    boosts = [
        ("sliding", 0.5),
        ("track", 0.3),
        ("handle", 0.4),
        ("glass", 0.3),
        ("formula", 0.3),
        ("black", 0.3),
        ("texture", 0.3),
        ("s29", 0.8),
        ("29mm", 0.6),
        ("series", 0.2),
    ]
    for word, boost in boosts:
        if word in ql:
            for key, doc in docs_by_key.items():
                if word in (doc.get("snippet") or "").lower() or word in (doc.get("title") or "").lower():
                    scores[key] += boost

    filters = filters or {}
    results: list[dict[str, Any]] = []
    for key, score in sorted(scores.items(), key=lambda x: -x[1]):
        doc = docs_by_key.get(key)
        if not doc:
            continue
        if memory_type and doc.get("memoryType") != memory_type:
            continue
        if filters.get("status") and doc.get("status") != filters["status"]:
            continue
        # series compatibility filter
        series = filters.get("seriesId") or filters.get("compatibleSeries")
        if series:
            snippet = (doc.get("snippet") or "").lower()
            if str(series).lower() not in snippet and str(series).lower() not in (doc.get("title") or "").lower():
                # soft filter — still allow if query explicitly asked
                if "compatible" in ql or "series" in ql:
                    continue
        results.append({**doc, "score": round(score, 3)})
        if len(results) >= limit:
            break

    return {
        "query": query,
        "memoryType": memory_type,
        "filters": filters,
        "count": len(results),
        "results": results,
        "index": {"docCount": idx.get("docCount"), "embeddings": False},
    }
