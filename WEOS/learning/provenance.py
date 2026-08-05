"""Provenance helpers — every engineering rule traces to a source + confidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def make_provenance(
    *,
    source: str,
    confidence: float,
    notes: str = "",
    confirmed_by: str | None = None,
) -> dict[str, Any]:
    conf = max(0.0, min(1.0, float(confidence)))
    entry: dict[str, Any] = {
        "source": source,
        "confidence": round(conf, 4),
    }
    if notes:
        entry["notes"] = notes
    if confirmed_by:
        entry["confirmedBy"] = confirmed_by
        entry["confirmedAt"] = datetime.now(timezone.utc).isoformat()
    return entry


def set_rule_provenance(
    profile: dict[str, Any],
    path: str,
    *,
    source: str,
    confidence: float,
    notes: str = "",
    confirmed_by: str | None = None,
) -> None:
    prov = dict(profile.get("_provenance") or {})
    prov[path] = make_provenance(
        source=source,
        confidence=confidence,
        notes=notes,
        confirmed_by=confirmed_by,
    )
    profile["_provenance"] = prov


def confirm_paths(
    profile: dict[str, Any],
    paths: list[str],
    *,
    confirmed_by: str = "user",
    source_override: str | None = None,
) -> None:
    """Mark listed dotted paths (or section keys) as user-confirmed."""
    prov = dict(profile.get("_provenance") or {})
    now = datetime.now(timezone.utc).isoformat()
    for p in paths:
        entry = dict(prov.get(p) or {})
        if source_override:
            entry["source"] = source_override
        elif "source" not in entry:
            entry["source"] = "user_confirmation"
        entry["confidence"] = 1.0
        entry["confirmedBy"] = confirmed_by
        entry["confirmedAt"] = now
        prov[p] = entry
    profile["_provenance"] = prov


def rule_review_row(
    path: str,
    detected_value: Any,
    confidence: float,
    source: str,
    *,
    existing_value: Any = None,
    action: str = "set",
) -> dict[str, Any]:
    """Standard review row shown to the user before approval."""
    return {
        "path": path,
        "detected_value": detected_value,
        "existing_value": existing_value,
        "confidence_percent": round(float(confidence) * 100.0, 1),
        "confidence": round(float(confidence), 4),
        "source": source,
        "action": action,
    }

