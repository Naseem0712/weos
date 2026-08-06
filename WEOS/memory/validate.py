"""Pre-generate validation — require approved Glass/Profiles/Formula/Hardware/Drawing."""

from __future__ import annotations

from typing import Any

from WEOS.memory.schemas import (
    MEM_DRAWING,
    MEM_FORMULA,
    MEM_GLASS,
    MEM_HARDWARE,
    MEM_PROFILE,
)


REQUIRED_DEFAULT = ("profiles", "glass", "formulas", "hardware")


def validate_context(
    ctx: dict[str, Any],
    *,
    require: tuple[str, ...] | list[str] | None = None,
    require_drawing: bool = False,
) -> dict[str, Any]:
    """
    Before Brain generate: ensure approved memories exist.
    If missing → do NOT generate; return clear missing list.
    """
    if not ctx or not ctx.get("ok"):
        return {
            "ok": False,
            "valid": False,
            "canGenerate": False,
            "missing": ["series"],
            "present": {},
            "message": ctx.get("error") if ctx else "No Brain context",
            "seriesId": (ctx or {}).get("seriesId"),
            "kbVersion": (ctx or {}).get("kbVersion"),
        }

    need = list(require or REQUIRED_DEFAULT)
    if require_drawing and "drawings" not in need:
        need.append("drawings")

    def _approved(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        items = items or []
        appr = [x for x in items if (x.get("status") or "") == "approved"]
        return appr or []

    buckets = {
        "profiles": _approved(ctx.get("profiles")),
        "glass": _approved(ctx.get("glass")),
        "formulas": _approved(ctx.get("formulas")),
        "hardware": _approved(ctx.get("hardware")),
        "drawings": _approved(ctx.get("drawings")),
    }

    # Also accept product-linked ids even if list empty but builder has data
    builder = ctx.get("builder") or {}
    if not buckets["profiles"] and builder.get("profiles"):
        buckets["profiles"] = [{"id": "builder_profiles", "status": "approved", "source": "builder"}]

    missing: list[dict[str, Any]] = []
    present: dict[str, Any] = {}
    for key in need:
        items = buckets.get(key) or []
        present[key] = {"count": len(items), "ids": [x.get("id") for x in items[:12]]}
        if not items:
            missing.append(
                {
                    "key": key,
                    "memoryType": {
                        "profiles": MEM_PROFILE,
                        "glass": MEM_GLASS,
                        "formulas": MEM_FORMULA,
                        "hardware": MEM_HARDWARE,
                        "drawings": MEM_DRAWING,
                    }.get(key, key),
                    "message": f"Missing approved {key} for series {ctx.get('seriesId')}",
                }
            )

    can = len(missing) == 0
    return {
        "ok": can,
        "valid": can,
        "canGenerate": can,
        "missing": missing,
        "present": present,
        "seriesId": ctx.get("seriesId"),
        "kbVersion": ctx.get("kbVersion"),
        "message": (
            "Ready to generate"
            if can
            else "Cannot generate — missing: " + ", ".join(m["key"] for m in missing)
        ),
        "production_modified": False,
    }
