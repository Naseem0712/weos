"""Declarative conflict rules — hard block / soft warning for incompatible selections."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from WEOS.memory.schemas import MEM_ENGINEERING, empty_conflict_rule
from WEOS.memory.store import get_store, memories_root, write_observation_as_learning


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rules_path() -> Path:
    d = memories_root() / "_rules"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "conflicts.json"
    if not p.is_file():
        seed = {
            "description": "Declarative conflict rules. Hard = stop generation. Soft = warning. Admin approve required for production use.",
            "rules": [
                {
                    "id": "conflict_premium_handle_old_roller",
                    "title": "Premium Handle + Old Roller incompatible",
                    "a": {"memoryType": "hardware", "id": "hw_handle_premium", "name": "Premium Handle"},
                    "b": {"memoryType": "hardware", "id": "hw_roller_old", "name": "Old Roller"},
                    "severity": "hard",
                    "reason": "Premium Handle requires matched roller set — Old Roller is mechanically incompatible.",
                    "seriesIds": [],
                    "status": "approved",
                    "priority": 100,
                    "approved_at": _now(),
                    "approved_by": "seed",
                }
            ],
            "updated_at": _now(),
        }
        p.write_text(json.dumps(seed, indent=2), encoding="utf-8")
    return p


def list_conflicts(*, status: str | None = "approved") -> list[dict[str, Any]]:
    data = json.loads(_rules_path().read_text(encoding="utf-8"))
    rules = list(data.get("rules") or [])
    # Merge engineering memories tagged as conflict drafts
    try:
        for eng in get_store().list(MEM_ENGINEERING):
            for cr in eng.get("conflictRules") or []:
                if isinstance(cr, dict) and cr.get("id"):
                    rules.append({**cr, "fromEngineering": eng.get("id")})
    except Exception:
        pass
    if status:
        rules = [r for r in rules if (r.get("status") or "approved") == status]
    return rules


def save_conflict(rule: dict[str, Any], *, as_approved: bool = False, approved_by: str = "admin") -> dict[str, Any]:
    """Save/update a conflict rule into _rules/conflicts.json (draft by default)."""
    path = _rules_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = list(data.get("rules") or [])
    shell = empty_conflict_rule()
    shell.update({k: v for k, v in rule.items() if v is not None})
    shell["id"] = shell.get("id") or f"conflict_{uuid.uuid4().hex[:8]}"
    shell["updated_at"] = _now()
    shell.setdefault("created_at", _now())
    if as_approved:
        shell["status"] = "approved"
        shell["approved_at"] = _now()
        shell["approved_by"] = approved_by
    else:
        shell.setdefault("status", "pending_approval")

    replaced = False
    for i, r in enumerate(rules):
        if r.get("id") == shell["id"]:
            rules[i] = shell
            replaced = True
            break
    if not replaced:
        rules.append(shell)
    data["rules"] = rules
    data["updated_at"] = _now()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return shell


def suggest_conflict(rule: dict[str, Any]) -> dict[str, Any]:
    """AI/agent path: store pending conflict + Learning Memory observation (never auto-approve)."""
    pending = save_conflict(rule, as_approved=False)
    obs = write_observation_as_learning(
        observation_type="conflict_rule",
        summary=pending.get("title") or pending.get("reason") or "New conflict rule suggested",
        evidence={"rule": pending},
        suggestion=f"Review conflict: {pending.get('reason')}",
        target_memory_type=MEM_ENGINEERING,
        target_payload={"conflictRules": [pending]},
        domain="engineering",
    )
    return {"ok": True, "rule": pending, "learning": obs, "production_modified": False}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _matches_ref(ref: dict[str, Any], selection: dict[str, Any]) -> bool:
    """Match conflict side against a selected item by id, name, or type."""
    if not ref or not selection:
        return False
    rid = _norm(ref.get("id"))
    rname = _norm(ref.get("name"))
    sid = _norm(selection.get("id"))
    sname = _norm(selection.get("name") or selection.get("profileName") or selection.get("seriesName"))
    if rid and rid == sid:
        return True
    if rname and (rname == sname or rname in sname or sname in rname):
        return True
    # Allow matching by category/type labels in name
    stype = _norm(selection.get("category") or selection.get("hardwareType") or selection.get("profileType"))
    if rname and stype and rname == stype:
        return True
    return False


def check_conflicts(
    *,
    selections: list[dict[str, Any]] | None = None,
    series_id: str | None = None,
    hardware: list[dict[str, Any]] | None = None,
    profiles: list[dict[str, Any]] | None = None,
    glass: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Evaluate approved conflict rules against current selections.
    Returns hard_blocks (must stop generation) and warnings.
    """
    pool: list[dict[str, Any]] = list(selections or [])
    for lst in (hardware, profiles, glass):
        if lst:
            pool.extend(lst)

    rules = list_conflicts(status="approved")
    hard: list[dict[str, Any]] = []
    soft: list[dict[str, Any]] = []

    for rule in rules:
        sids = rule.get("seriesIds") or []
        if sids and series_id and series_id not in [str(x) for x in sids]:
            continue
        a = rule.get("a") or {}
        b = rule.get("b") or {}
        hit_a = any(_matches_ref(a, s) for s in pool)
        hit_b = any(_matches_ref(b, s) for s in pool)
        if not (hit_a and hit_b):
            continue
        entry = {
            "id": rule.get("id"),
            "title": rule.get("title"),
            "severity": rule.get("severity") or "hard",
            "reason": rule.get("reason") or "Incompatible selection",
            "a": a,
            "b": b,
            "action": "stop" if (rule.get("severity") or "hard") == "hard" else "warn",
        }
        if entry["severity"] == "hard":
            hard.append(entry)
        else:
            soft.append(entry)

    blocked = len(hard) > 0
    return {
        "ok": not blocked,
        "blocked": blocked,
        "hardBlocks": hard,
        "warnings": soft,
        "message": (
            hard[0]["reason"]
            if hard
            else (soft[0]["reason"] if soft else "No conflicts")
        ),
        "checked": len(rules),
        "selectionCount": len(pool),
    }
