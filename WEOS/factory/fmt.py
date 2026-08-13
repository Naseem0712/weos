"""Display rounding: money = 2 decimals; millimetre sizes = integers; RFT = 2 decimals."""

from __future__ import annotations

from typing import Any


def money_n(value: Any, default: float = 0.0) -> float:
    """Round a rupee amount to exactly 2 decimal places."""
    try:
        if value is None or value == "":
            return default
        return round(float(value) + 0.0, 2)
    except (TypeError, ValueError):
        return default


def money_str(value: Any, *, prefix: str = "") -> str:
    n = money_n(value)
    body = f"{n:,.2f}"
    return f"{prefix}{body}" if prefix else body


def mm_n(value: Any, default: int = 0) -> int:
    """Nearest integer millimetre (no fractional mm on sizes)."""
    try:
        if value is None or value == "":
            return default
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def mm_str(value: Any, *, suffix: str = " mm") -> str:
    return f"{mm_n(value)}{suffix}"


def rft_n(value: Any, default: float = 0.0) -> float:
    """Running-foot qty / length — 2 decimals."""
    try:
        if value is None or value == "":
            return default
        return round(float(value) + 0.0, 2)
    except (TypeError, ValueError):
        return default


def rft_str(value: Any, *, suffix: str = " RFT") -> str:
    return f"{rft_n(value):.2f}{suffix}"
