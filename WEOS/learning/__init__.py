"""Learning package — catalogue / DXF rule ingest with approval gate."""

from WEOS.learning.ingest import approve, compare_to_library, pending_proposals, propose, reject

__all__ = [
    "propose",
    "approve",
    "reject",
    "compare_to_library",
    "pending_proposals",
]

