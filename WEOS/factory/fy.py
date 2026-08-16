"""Indian financial year (1 Apr – 31 Mar). Closed years stay fetchable, not hot-loaded."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fy_label(year_start: int) -> str:
    return f"{year_start}-{str(year_start + 1)[2:]}"


def fy_of(value: Any | None = None) -> str:
    dt = _as_dt(value) or datetime.now(timezone.utc)
    start = dt.year if dt.month >= 4 else dt.year - 1
    return fy_label(start)


def current_fy() -> str:
    return fy_of()


def fy_start_year(label: str | None) -> int | None:
    raw = str(label or "").strip()
    if raw.lower() in {"all", "*", "any"}:
        return None
    if raw.lower() in {"current", "this", ""}:
        return int(current_fy().split("-", 1)[0])
    head = raw.split("-", 1)[0]
    try:
        y = int(head)
    except ValueError:
        return int(current_fy().split("-", 1)[0])
    if y < 1990 or y > 2100:
        return int(current_fy().split("-", 1)[0])
    return y


def fy_bounds(label: str | None = None) -> tuple[datetime, datetime] | None:
    start_y = fy_start_year(label)
    if start_y is None:
        return None
    start = datetime(start_y, 4, 1, tzinfo=timezone.utc)
    end = datetime(start_y + 1, 4, 1, tzinfo=timezone.utc)
    return start, end


def in_fy(value: Any, label: str | None) -> bool:
    bounds = fy_bounds(label)
    if bounds is None:
        return True
    dt = _as_dt(value)
    if not dt:
        return False
    start, end = bounds
    return start <= dt < end
