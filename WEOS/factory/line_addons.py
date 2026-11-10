"""Per-window / per-door commercial add-ons and soft-cancel helpers.

Line keys (top-level or ``options``):
  - ``addons`` / ``lineAddons`` / ``extraServices`` — list of
    ``{name, note|spec, qty, rate, amount}``
  - ``cancelled`` / ``canceled`` — soft cancel (remain in list, excluded from money)

Amount for each add-on is always ``qty × rate`` (recomputed; stored amount is a hint).
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence
from uuid import uuid4


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opts(line: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(line, Mapping):
        return {}
    opts = line.get("options")
    return opts if isinstance(opts, Mapping) else {}


def is_line_cancelled(line: Mapping[str, Any] | None) -> bool:
    """True when the cart line is soft-cancelled (excluded from money / qty / area)."""
    if not isinstance(line, Mapping):
        return False
    for src in (line, _opts(line)):
        if not isinstance(src, Mapping):
            continue
        for key in ("cancelled", "canceled", "isCancelled", "isCanceled"):
            raw = src.get(key)
            if raw is True:
                return True
            if isinstance(raw, (int, float)) and raw == 1:
                return True
            if isinstance(raw, str) and raw.strip().lower() in ("1", "true", "yes", "y", "cancelled", "canceled"):
                return True
    return False


def _raw_addon_lists(line: Mapping[str, Any] | None) -> list[Any]:
    if not isinstance(line, Mapping):
        return []
    opts = _opts(line)
    for src in (line, opts):
        if not isinstance(src, Mapping):
            continue
        for key in ("addons", "lineAddons", "extraServices", "extra_services", "line_addons"):
            raw = src.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                return list(raw)
    return []


def normalize_addon(raw: Any) -> dict[str, Any] | None:
    """Normalize one add-on dict; return None when name+rate are both empty."""
    if not isinstance(raw, Mapping):
        return None
    name = str(raw.get("name") or raw.get("label") or raw.get("title") or "").strip()
    note = str(
        raw.get("note")
        or raw.get("spec")
        or raw.get("specification")
        or raw.get("description")
        or ""
    ).strip()
    qty_n = _num(raw.get("qty") if raw.get("qty") is not None else raw.get("quantity"))
    qty = max(float(qty_n) if qty_n is not None else 1.0, 0.0)
    rate_n = _num(raw.get("rate") if raw.get("rate") is not None else raw.get("unitAmount") or raw.get("unitRate"))
    rate = float(rate_n) if rate_n is not None else 0.0
    if rate < 0:
        rate = 0.0
    amount = round(qty * rate, 2)
    if not name and amount <= 0 and not note:
        return None
    aid = str(raw.get("id") or raw.get("addonId") or "").strip() or uuid4().hex[:10]
    return {
        "id": aid,
        "name": name or "Add-on",
        "note": note or None,
        "spec": note or None,
        "qty": round(qty, 4) if qty != int(qty) else int(qty),
        "rate": round(rate, 2),
        "amount": amount,
    }


def line_addons(line: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Resolved add-on rows for a cart line (empty when cancelled or none)."""
    if is_line_cancelled(line):
        # Still return addons for display under a cancelled window, but callers
        # that sum money should skip via ``line_addons_total`` / commercial.
        pass
    out: list[dict[str, Any]] = []
    for raw in _raw_addon_lists(line):
        row = normalize_addon(raw)
        if row:
            out.append(row)
    return out


def line_addons_for_display(line: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Add-ons listed under the window even when the line is cancelled."""
    out: list[dict[str, Any]] = []
    for raw in _raw_addon_lists(line):
        row = normalize_addon(raw)
        if row:
            out.append(row)
    return out


def line_addons_total(line: Mapping[str, Any] | None, *, include_cancelled: bool = False) -> float:
    if not include_cancelled and is_line_cancelled(line):
        return 0.0
    return round(sum(float(a.get("amount") or 0) for a in line_addons_for_display(line)), 2)


def persist_line_addons(
    options: MutableMapping[str, Any],
    line: Mapping[str, Any] | None = None,
    addons: Sequence[Any] | None = None,
) -> MutableMapping[str, Any]:
    """Write normalized ``addons`` onto the options blob (and drop aliases)."""
    src = addons
    if src is None and isinstance(line, Mapping):
        src = _raw_addon_lists(line)
    rows = []
    for raw in src or []:
        row = normalize_addon(raw)
        if row:
            rows.append(row)
    if rows:
        options["addons"] = rows
    else:
        options.pop("addons", None)
    for k in ("lineAddons", "extraServices", "extra_services", "line_addons"):
        options.pop(k, None)
    return options


def persist_cancelled(options: MutableMapping[str, Any], line: Mapping[str, Any] | None) -> MutableMapping[str, Any]:
    cancelled = is_line_cancelled(line)
    options["cancelled"] = bool(cancelled)
    if not cancelled:
        options.pop("canceled", None)
    return options


def addon_label(addon: Mapping[str, Any] | None) -> str:
    if not isinstance(addon, Mapping):
        return ""
    name = str(addon.get("name") or "Add-on").strip()
    note = str(addon.get("note") or addon.get("spec") or "").strip()
    qty = addon.get("qty")
    rate = addon.get("rate")
    amount = addon.get("amount")
    bits = [name]
    if note:
        bits.append(note)
    try:
        q = float(qty or 0)
        r = float(rate or 0)
        if q and r:
            bits.append(f"{q:g} × ₹{r:,.2f}")
    except (TypeError, ValueError):
        pass
    try:
        a = float(amount or 0)
        if a:
            bits.append(f"₹{a:,.2f}")
    except (TypeError, ValueError):
        pass
    return " · ".join(bits)
