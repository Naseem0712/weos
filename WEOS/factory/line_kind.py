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
    ("shower_partition", "Shower partition"),
    ("bathroom_ventilator", "Bathroom ventilator"),
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
    "shower_partition": "Bathrooms",
    "bathroom_ventilator": "Bathrooms",
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
    "shower": "shower_partition",
    "shower_partitions": "shower_partition",
    "bathroom_shower": "shower_partition",
    "bathroom_ventilator": "bathroom_ventilator",
    "ventilator": "bathroom_ventilator",
    "bathroom_vent": "bathroom_ventilator",
    "bath_ventilator": "bathroom_ventilator",
}

_WINDOW_QTY_TYPES = frozenset({"windows", "sliding", "casements", "telescopic", "synchron", "fold"})
_DOOR_QTY_TYPES = frozenset({"door", "style"})
_QTY_GROUP_ORDER = (
    "Windows",
    "Doors",
    "Showers",
    "Bathroom ventilators",
    "Railings",
    "Staircase railings",
    "Louvers",
    "ACP",
    "HPL",
    "Pergolas",
    "Other",
)


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
    if "ventilat" in t:
        return "bathroom_ventilator"
    if "shower" in t:
        return "shower_partition"
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


def line_world(line: Mapping[str, Any] | None = None, *, product: Mapping[str, Any] | None = None) -> str:
    """Single cart-line world for calc / PDF / UI.

    Prefer live designer blobs (``options.railing`` / shower / vent), then Product Library type.
    """
    if is_ventilator_cart_line(line):
        return "ventilator"
    if is_shower_cart_line(line):
        return "shower"
    if is_railing_cart_line(line):
        return railing_product_type_for_line(line)
    pt = cat = pid = None
    if isinstance(line, Mapping):
        opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        pt = line.get("productType") or (opts.get("productType") if isinstance(opts, Mapping) else None)
        cat = line.get("category")
        pid = line.get("product") or line.get("productId")
    if isinstance(product, Mapping):
        pt = pt or product.get("productType")
        cat = cat or product.get("category")
        pid = pid or product.get("id")
    return product_world(pt, category=cat, product_id=pid)


def product_world(product_type: Any = None, *, category: Any = None, product_id: Any = None) -> str:
    """High-level cart world: railing / staircase / shower / ventilator / window / other."""
    pt = normalize_product_type(product_type)
    if pt == "staircase_railing":
        return "staircase_railing"
    if pt == "railing":
        return "railing"
    if pt == "bathroom_ventilator":
        return "ventilator"
    if pt == "shower_partition":
        return "shower"
    cat = str(category or "").lower()
    pid = str(product_id or "").lower()
    if "ventilat" in cat or "ventilat" in pid:
        return "ventilator"
    if "stair" in cat and "rail" in cat:
        return "staircase_railing"
    if "rail" in cat:
        return "railing"
    if "shower" in cat or ("bathroom" in cat and "ventilat" not in pid):
        return "shower"
    if "stair" in pid and "rail" in pid:
        return "staircase_railing"
    if "rail" in pid:
        return "railing"
    if "shower" in pid:
        return "shower"
    if pt in PRODUCT_TYPES:
        return "window"
    return "other"


def is_shower_product_type(product_type: Any) -> bool:
    return normalize_product_type(product_type) == "shower_partition"


def is_ventilator_product_type(product_type: Any) -> bool:
    return normalize_product_type(product_type) == "bathroom_ventilator"


def is_casement_product_type(product_type: Any) -> bool:
    return normalize_product_type(product_type) == "casements"


def product_has_tracks(product_type: Any = None, *, system: Any = None, category: Any = None) -> bool:
    """True when the Track UI / trackCount belongs on this product.

    Sliding, telescopic, synchron, style slide-doors, and fold systems use tracks.
    Casement, railing, shower, pergola, ACP/HPL/louvers do not.
    """
    sys = str(system or "").strip().lower()
    if sys in ("casement", "openable", "opening", "shower", "ventilator", "railing", "grid"):
        return False
    if sys in ("sliding", "telescopic", "synchron", "style", "bifold", "fold", "fold_sliding", "fold_and_sliding"):
        return True
    pt = normalize_product_type(product_type)
    if pt in ("casements", "railing", "staircase_railing", "shower_partition", "bathroom_ventilator", "pergolas"):
        return False
    if pt in ("sliding", "telescopic", "synchron", "style", "fold", "windows", "door"):
        return True
    cat = str(category or "").lower()
    if any(x in cat for x in ("rail", "shower", "bathroom", "pergola", "facade", "acp", "hpl", "louver")):
        return False
    if "casement" in cat or "openable" in cat:
        return False
    if sys:
        return "slid" in sys or "fold" in sys or "tele" in sys or "sync" in sys
    return False


def is_ventilator_cart_line(line: Mapping[str, Any] | None) -> bool:
    """True when a cart line is a bathroom ventilator (not shower or window)."""
    if not isinstance(line, Mapping):
        return False
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    if isinstance(opts, Mapping):
        if isinstance(opts.get("ventilator"), Mapping):
            return True
        if is_ventilator_product_type(opts.get("productType")):
            return True
    if isinstance(line.get("ventilator"), Mapping):
        return True
    if is_ventilator_product_type(line.get("productType")):
        return True
    cat = str(line.get("category") or "").lower()
    if "ventilat" in cat:
        return True
    pid = str(line.get("product") or line.get("productId") or "").lower()
    if "ventilat" in pid:
        return True
    return False


def is_shower_cart_line(line: Mapping[str, Any] | None) -> bool:
    """True when a cart line is a shower partition (own geometry, not window)."""
    if not isinstance(line, Mapping):
        return False
    if is_ventilator_cart_line(line):
        return False
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    if isinstance(opts, Mapping):
        if isinstance(opts.get("shower"), Mapping):
            return True
        if is_shower_product_type(opts.get("productType")):
            return True
    if isinstance(line.get("shower"), Mapping):
        return True
    if is_shower_product_type(line.get("productType")):
        return True
    cat = str(line.get("category") or "").lower()
    if "shower" in cat:
        return True
    pid = str(line.get("product") or line.get("productId") or "").lower()
    if "shower" in pid:
        return True
    return False


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


def _line_blob(line: Mapping[str, Any]) -> str:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    bits = [
        str(line.get("productType") or ""),
        str(line.get("product") or ""),
        str(line.get("productId") or ""),
        str(line.get("category") or ""),
        str(line.get("displayName") or ""),
        str(line.get("status") or ""),
        str(opts.get("productType") or "") if isinstance(opts, Mapping) else "",
    ]
    return " ".join(bits).lower()


def totals_group_for_line(line: Mapping[str, Any] | None) -> str:
    """Quote TOTALS bucket. Showers/doors/railings/ventilators are never Windows."""
    if not isinstance(line, Mapping):
        return "Other"
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    pt = normalize_product_type(
        line.get("productType")
        or (opts.get("productType") if isinstance(opts, Mapping) else None)
    )
    blob = _line_blob(line)
    if is_ventilator_cart_line(line) or pt == "bathroom_ventilator" or "ventilat" in blob:
        return "Bathroom ventilators"
    if is_shower_cart_line(line) or pt == "shower_partition" or "shower" in blob:
        return "Showers"
    if is_railing_cart_line(line) or is_railing_product_type(pt) or "rail" in blob:
        rpt = railing_product_type_for_line(line)
        if rpt == "staircase_railing" or "stair" in blob:
            return "Staircase railings"
        return "Railings"
    if "louver" in blob:
        return "Louvers"
    if "acp" in blob.split() or "_acp" in blob or blob.startswith("acp") or " acp" in blob:
        return "ACP"
    if "hpl" in blob.split() or "_hpl" in blob or blob.startswith("hpl") or " hpl" in blob:
        return "HPL"
    if pt == "pergolas" or "pergola" in blob:
        return "Pergolas"
    if pt in _DOOR_QTY_TYPES or str(line.get("category") or "").lower() == "doors":
        return "Doors"
    if "door" in blob and "window" not in blob and "shower" not in blob:
        return "Doors"
    if pt in _WINDOW_QTY_TYPES or str(line.get("category") or "").lower() == "windows":
        return "Windows"
    if "window" in blob or "casement" in blob or "slid" in blob or "tele" in blob or "fold" in blob:
        return "Windows"
    if pt:
        labels = dict(PRODUCT_TYPE_CHOICES)
        return labels.get(pt) or pt.replace("_", " ").title()
    name = str(line.get("displayName") or line.get("product") or "").strip()
    return name or "Other"


def quote_qty_breakdown(lines: Any) -> list[tuple[str, int]]:
    """Ordered (label, qty) for quote TOTALS. Qty = sum of line quantities."""
    counts: dict[str, int] = {}
    for line in lines or []:
        if not isinstance(line, Mapping):
            continue
        try:
            qty = int(round(float(line.get("qty") or line.get("quantity") or 1)))
        except (TypeError, ValueError):
            qty = 1
        if qty <= 0:
            continue
        lab = totals_group_for_line(line)
        counts[lab] = counts.get(lab, 0) + qty
    order = {name: i for i, name in enumerate(_QTY_GROUP_ORDER)}
    items = [(k, v) for k, v in counts.items() if v]
    items.sort(key=lambda kv: (order.get(kv[0], 80), kv[0].lower()))
    return items


def line_location_name(line: Mapping[str, Any] | None) -> str:
    """Optional location / position name (Master Bedroom, Kitchen, …)."""
    if not isinstance(line, Mapping):
        return ""
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    for src in (line, opts):
        if not isinstance(src, Mapping):
            continue
        for key in ("locationName", "positionName", "location", "position"):
            val = str(src.get(key) or "").strip()
            if val:
                return val
    return ""


def design_serial_label(index: int, line: Mapping[str, Any] | None = None, *, prefix: str = "W") -> str:
    """PDF DESIGN serial, e.g. ``W8`` or ``W8 · Master Bedroom``."""
    try:
        n = int(index) + 1
    except (TypeError, ValueError):
        n = 1
    code = f"{prefix}{max(n, 1)}"
    loc = line_location_name(line)
    return f"{code} · {loc}" if loc else code


def format_qty_totals_lines(groups: list[tuple[str, int]] | None, *, fallback_qty: int = 0) -> list[str]:
    """Wrapped TOTALS qty rows, e.g. ``Windows: 4 Nos    Doors: 2 Nos``."""
    if not groups:
        return [f"Items: {int(fallback_qty)} Nos"]
    chunks = [f"{lab}: {n} Nos" for lab, n in groups]
    lines: list[str] = []
    cur = ""
    for ch in chunks:
        if not cur:
            cur = ch
        elif len(cur) + 4 + len(ch) > 92:
            lines.append(cur)
            cur = ch
        else:
            cur = f"{cur}    {ch}"
    if cur:
        lines.append(cur)
    return lines
