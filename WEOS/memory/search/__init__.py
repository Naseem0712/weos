"""Search package — pragmatic inverted index + keyword/filter (no embeddings required)."""

from WEOS.memory.search.index import rebuild_index, search

__all__ = ["search", "rebuild_index"]
