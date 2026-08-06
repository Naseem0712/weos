"""Engineering Brain — reasoning / orchestration layer over approved KB Memory.

Memory stores data; Brain decides.

User selects product type + series → Brain loads approved Profiles, Glass,
Hardware, Formula, Drawing Rules, Weight/Cutting/Pricing/Factory/Commercial
rules → generates BOM, Drawing plan, PDF layout, Quotation skeleton, Weight,
Cost, Packing, Machine Cutting — all from approved knowledge, not hardcoded ERP.
"""

from WEOS.brain.engine import generate, load_context, reason, brain_status

__all__ = ["load_context", "reason", "generate", "brain_status"]
