"""Bridge helpers — connect Learning V2 agents to Memory Architecture.

Keeps agents as observers; Memory admin remains the only write gate to KB versions.
"""

from __future__ import annotations

from typing import Any

from WEOS.memory.store import write_observation_as_learning


def observation_from_engineering(summary: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return write_observation_as_learning(
        observation_type="engineering_insight",
        summary=summary,
        evidence=evidence or {},
        suggestion=summary,
        domain="engineering",
    )


def observation_from_commercial(summary: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return write_observation_as_learning(
        observation_type="commercial_insight",
        summary=summary,
        evidence=evidence or {},
        suggestion=summary,
        domain="commercial",
    )
