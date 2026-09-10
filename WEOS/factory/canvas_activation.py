"""Canvas D1 — Universal Canvas activation policy.

Normal V2 workflow: Universal Canvas ON by default.
Rollback: WEOS_UNIVERSAL_CANVAS=0/false/off OR URL ?universalCanvas=0
"""

from __future__ import annotations

import os
from typing import Any

FLAG_ENV = "WEOS_UNIVERSAL_CANVAS"

_FALSE = frozenset({"0", "false", "no", "off"})
_TRUE = frozenset({"1", "true", "yes", "on"})


def _parse_bool(raw: Any) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in _FALSE:
        return False
    if s in _TRUE:
        return True
    return None


def is_universal_canvas_enabled(
    *,
    env_value: str | bool | None = None,
    query_value: str | bool | None = None,
    override: str | bool | None = None,
) -> bool:
    """Resolve UC activation.

    Precedence (highest first):
      1. explicit ``override`` (tests / callers)
      2. URL query ``universalCanvas`` when provided
      3. env ``WEOS_UNIVERSAL_CANVAS`` when set
      4. default **ON** (Canvas D1)
    """
    if override is not None:
        parsed = _parse_bool(override)
        if parsed is not None:
            return parsed
        return bool(override)

    q = _parse_bool(query_value)
    if q is not None:
        return q

    if env_value is not None:
        e = _parse_bool(env_value)
        if e is not None:
            return e
    else:
        raw = os.environ.get(FLAG_ENV)
        e = _parse_bool(raw)
        if e is not None:
            return e

    return True


def activation_docs() -> dict[str, Any]:
    return {
        "default": "on",
        "env": FLAG_ENV,
        "queryOn": "?universalCanvas=1",
        "queryOff": "?universalCanvas=0",
        "legacyFallback": "Set WEOS_UNIVERSAL_CANVAS=0 or open ?universalCanvas=0",
        "batch": "CANVAS-D1",
    }
