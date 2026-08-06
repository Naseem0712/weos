"""Learning package — catalogue / DXF / PDF ingest with approval gate (V1 + V2)."""

from WEOS.learning.ingest import approve, compare_to_library, pending_proposals, propose, reject

__all__ = [
    "propose",
    "approve",
    "reject",
    "compare_to_library",
    "pending_proposals",
]
