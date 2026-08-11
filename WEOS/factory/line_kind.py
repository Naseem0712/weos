"""Cart-line / product kind — railing vs window worlds for calc, PDF, and UI.

Single source of truth so PDF elevation never falls through to window
``generate_job`` for a railing designer line, and Product Library types gate
the cart canvas/tools.
"""

from __future__ import annotations

from typing import Any, Mapping

# Canonical product types (Admin · Product Library → required on save).
PRODUCT_TYPE_CHOICES: tuple[tuple[str, str], ...] = (
    ("railing", "Railing"),
    ("staircase_railing", "Staircase railing"),
    ("windows", "Windows"),
    ("door", "Door"),
    ("casements", "Casements"),
    ("pergolas", "Pergolas"),
    ("synchron", "Synchron (sync telescopic / 2+2)"),
    ("telescopic", "Telescopic"),
    ("fold", "Fold & sliding"),
    ("sliding", "Sliding"),
    ("style", "Style / slide door"),
)

PRODUCT_TYPES = frozenset(k for k, _ in PRODUCT_TYPE_CHOICES)

CATEGORY_FOR_TYPE: dict[str, str] = {
    "railing": "Railings",
    "staircase_railing": "Railings",
    "windows": "Windows",
    "door": "Doors",
    "casements": "Windows",
    "pergolas": "Pergolas",
    "synchron": "Windows",
    "telescopic": "Windows",
    "fold": "Windows",
    "sliding": "Windows",
    "style": "Doors",
}

# Series-setup form types (aluminium window systems) — not used for railing worlds.
SETUP_FORM_TYPES = frozenset({"sliding", "casement", "telescopic", "style", "fold", "synchron"})

_RAILING_TYPE_ALIASES = {
    "rail": "railing",
    "railings": "railing",
    "glass_railing": "railing",
    "glass_railings": "railing",
    "normal_railing": "railing",
    "staircase": "staircase_railing",
    "stair_railing": "staircase_railing",
    "stairs": "staircase_railing",
    "window": "windows",
    "doors": "door",
    "casement": "casements",
    "pergola": "pergolas",
    "sync": "synchron",
    "synchro": "synchron",
    "bifold": "fold",
    "fold_sliding": "fold",
    "telescopic_sliding": "telescopic",
    "style_slide_door": "style",
}


def normalize_product_type(raw: Any) -> str | None:
    """Return a canonical product type id, or None if empty/unknown."""
    if raw is None or raw == "":
        return None
    t = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if not t:
        return None
    t = _RAILING_TYPE_ALIASES.get(t, t)
    if t in PRODUCT_TYPES:
        return t
    if "stair" in t and "rail" in t:
        return "staircase_railing"
    if "rail" in t:
        return "railing"
    if "pergola" in t:
        return "pergolas"
    if "casement" in t or "openable" in t:
        return "casements"
    if "fold" in t or "bifold" in t:
        return "fold"
    if "sync" in t:
        return "synchron"
    if "tele" in t:
        return "telescopic"
    if "style" in t:
        return "style"
    if "door" in t:
        return "door"
    if "slid" in t:
        return "sliding"
    if "window" in t:
        return "windows"
    return None


def category_for_product_type(product_type: str | None) -> str | None:
    pt = normalize_product_type(product_type)
    return CATEGORY_FOR_TYPE.get(pt) if pt else None


def is_railing_product_type(product_type: Any) -> bool:
    pt = normalize_product_type(product_type)
    return pt in ("railing", "staircase_railing")


def is_staircase_product_type(product_type: Any) -> bool:
    return normalize_product_type(product_type) == "staircase_railing"


def product_world(product_type: Any = None, *, category: Any = None, product_id: Any = None) -> str:
    """High-level cart world: ``railing`` | ``staircase_railing`` | ``window`` | ``other``."""
    pt = normalize_product_type(product_type)
    if pt == "staircase_railing":
        return "staircase_railing"
    if pt == "railing":
        return "railing"
    cat = str(category or "").lower()
    if "stair" in cat and "rail" in cat:
        return "staircase_railing"
    if "rail" in cat:
        return "railing"
    pid = str(product_id or "").lower()
    if "stair" in pid and "rail" in pid:
        return "staircase_railing"
    if "rail" in pid:
        return "railing"
    if pt in PRODUCT_TYPES:
        return "window"
    return "other"


def is_railing_cart_line(line: Mapping[str, Any] | None) -> bool:
    """True when a cart / calculated line is railing designer (never window geometry)."""
    if not isinstance(line, Mapping):
        return False
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    if isinstance(opts, Mapping):
        if isinstance(opts.get("railing"), Mapping):
            return True
        if isinstance(opts.get("railingQuote"), Mapping):
            return True
        if is_railing_product_type(opts.get("productType")):
            return True
    if str(line.get("status") or "").lower() == "railing":
        return True
    if isinstance(line.get("railing"), Mapping):
        return True
    if is_railing_product_type(line.get("productType")):
        return True
    cat = str(line.get("category") or "").lower()
    if "rail" in cat:
        return True
    pid = str(line.get("product") or line.get("productId") or "").lower()
    if pid in ("railing", "railings_stub", "glass_railings") or "railing" in pid or pid.endswith("_rail"):
        return True
    return False


def railing_product_type_for_line(line: Mapping[str, Any] | None) -> str:
    """``staircase_railing`` or ``railing`` for a railing cart line.

    Prefer the live designer ``options.railing.shape`` over a stale
    ``productType`` (e.g. leftover staircase_railing after switching to Normal).
    """
    if not isinstance(line, Mapping):
        return "railing"
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    cfg = opts.get("railing") if isinstance(opts, Mapping) else None
    shape = ""
    if isinstance(cfg, Mapping):
        shape = str(cfg.get("shape") or "").lower()
    q = opts.get("railingQuote") if isinstance(opts, Mapping) else None
    if not shape and isinstance(q, Mapping):
        shape = str(q.get("shape") or "").lower()
    if not shape and isinstance(line.get("railing"), Mapping):
        shape = str((line.get("railing") or {}).get("shape") or "").lower()
    if shape in ("stairs", "stair"):
        shape = "staircase"
    if shape == "staircase":
        return "staircase_railing"
    if shape in ("straight", "l", "u", "polyline", "arch"):
        return "railing"
    pt = normalize_product_type(line.get("productType"))
    if pt == "staircase_railing":
        return "staircase_railing"
    if "stair" in str(line.get("category") or "").lower():
        return "staircase_railing"
    return "railing"
