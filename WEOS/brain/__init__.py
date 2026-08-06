"""Engineering Brain — reasoning / orchestration layer over approved KB Memory.

Memory stores data; Brain decides.

User selects product type + series → Brain loads approved Profiles, Glass,
Hardware, Formula, Drawing Rules, Weight/Cutting/Pricing/Factory/Commercial
rules → validates → checks conflicts/compatibility → generates BOM / Drawing /
PDF / Quotation / Weight / Cost / Packing / Machine Cutting with explain proofs.
"""

from WEOS.brain.engine import (
    brain_status,
    check_series_compatibility,
    check_series_conflicts,
    explain,
    generate,
    load_context,
    reason,
    recommend,
    validate_series,
)

__all__ = [
    "load_context",
    "reason",
    "generate",
    "brain_status",
    "validate_series",
    "explain",
    "recommend",
    "check_series_compatibility",
    "check_series_conflicts",
]
