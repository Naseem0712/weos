"""WEOS Manufacturing Memory Architecture.

Separate memory namespaces for engineering / commercial / product knowledge.
AI may only Observe → Suggest. Admin alone Approves → KB Version → Brain use.
Production data is never written automatically from this package.
"""

from WEOS.memory.schemas import MEMORY_TYPES, empty_memory
from WEOS.memory.store import MemoryStore, get_store

__all__ = [
    "MEMORY_TYPES",
    "empty_memory",
    "MemoryStore",
    "get_store",
]
