"""
Learning Engine — extract & propose engineering rules (never auto-write production).

SAFETY:
  Learning learns RULES. It does NOT generate drawings.
  It NEVER modifies profiles/*.json until an explicit approve step.

Workflow:
  1. extract_from_source(DXF|JSON|PDF-stub)
  2. compare_to_library → create | update | noop
  3. propose(...) → knowledge_base/pending/<id>.json  (review rows with value/confidence/source)
  4. approve(...) → version snapshot + write production profile + provenance
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from WEOS.factory.profile_loader import (
    PROFILES_DIR,
    REQUIRED_SECTIONS,
    list_profiles,
    load_profile,
    validate_profile_sections,
)
from WEOS.learning.extract import extract_from_source
from WEOS.learning.knowledge_base import (
    archive_pending,
    ensure_kb_dirs,
    list_pending,
    load_pending_proposal,
    seed_initial_version_if_missing,
    snapshot_profile,
    write_pending_proposal,
)
from WEOS.learning.provenance import confirm_paths, set_rule_provenance

Action = Literal["create", "update", "noop"]

TEMPLATE_ID = "29mm_sliding"


def compare_to_library(proposed_id: str) -> dict[str, Any]:
    """Decide create vs update when a series id is considered."""
    known = {pid for pid, _ in list_profiles()}
    path = PROFILES_DIR / f"{proposed_id}.json"
    if proposed_id in known or path.is_file():
        existing = load_profile(proposed_id, strict=False)
        sections = [k for k in existing.keys() if not str(k).startswith("_")]
        return {
            "action": "update",
            "profile_id": proposed_id,
            "reason": "Profile id already exists — propose changed rules only.",
            "proposed_path": str(path),
            "existing_sections": sections,
            "library": list_profiles(),
        }
    return {
        "action": "create",
        "profile_id": proposed_id,
        "reason": "No matching profile in library — propose new series JSON from template.",
        "proposed_path": str(path),
        "existing_sections": [],
        "library": list_profiles(),
    }


def _set_by_path(doc: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur: Any = doc
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    leaf = parts[-1]
    # Coerce numeric strings
    if isinstance(value, str):
        try:
            value = float(value) if "." in value else int(value)
        except ValueError:
            pass
    cur[leaf] = value


def _get_by_path(doc: dict[str, Any], dotted: str) -> Any:
    cur: Any = doc
    for p in dotted.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _load_template() -> dict[str, Any]:
    return load_profile(TEMPLATE_ID, strict=False)


def _blank_profile_shell(profile_id: str, display_name: str | None = None) -> dict[str, Any]:
    tpl = _load_template()
    tpl.pop("_path", None)
    tpl["id"] = profile_id
    tpl["displayName"] = display_name or profile_id.replace("_", " ").title()
    tpl["version"] = 0
    tpl["_provenance"] = {}
    return tpl


def build_proposed_profile(
    plan: dict[str, Any],
    extraction: dict[str, Any],
    *,
    confirm_all: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Merge extracted rules into a draft profile; return (draft, review_rows)."""
    profile_id = plan["profile_id"]
    action = plan["action"]
    review: list[dict[str, Any]] = []

    if action == "create":
        draft = _blank_profile_shell(profile_id)
        base_note = "New series draft from 29mm_sliding template + extracted rules"
    else:
        draft = load_profile(profile_id, strict=False)
        draft.pop("_path", None)
        base_note = "Update draft — only changed rules applied"

    raw_sections = extraction.get("raw_sections") or {}
    for sec, val in raw_sections.items():
        if sec in REQUIRED_SECTIONS and val is not None:
            existing = draft.get(sec)
            review.append(
                {
                    "path": sec,
                    "detected_value": "(section replace)",
                    "existing_value": type(existing).__name__,
                    "confidence_percent": 70.0,
                    "confidence": 0.7,
                    "source": extraction.get("source_path", "catalogue"),
                    "action": "replace_section",
                }
            )
            if confirm_all:
                draft[sec] = copy.deepcopy(val)

    for row in extraction.get("rules") or []:
        path = row["path"]
        detected = row["detected_value"]
        existing = _get_by_path(draft, path)
        changed = existing != detected
        out_row = {
            "path": path,
            "detected_value": detected,
            "existing_value": existing,
            "confidence_percent": row.get("confidence_percent", round(float(row.get("confidence", 0)) * 100, 1)),
            "confidence": float(row.get("confidence", 0)),
            "source": row.get("source", extraction.get("source_path", "unknown")),
            "action": "set" if changed else "confirm",
        }
        review.append(out_row)
        # Draft always shows proposed values for review; production write only on approve
        if changed or action == "create":
            _set_by_path(draft, path, detected)
            set_rule_provenance(
                draft,
                path,
                source=str(out_row["source"]),
                confidence=float(out_row["confidence"]),
                notes="Proposed by Learning Engine — pending approval",
            )

    draft["id"] = profile_id
    draft["_draft_note"] = base_note
    return draft, review


def propose(
    source_path: str | Path,
    *,
    profile_id: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    """
    Extract rules and write a pending proposal JSON.
    Does NOT modify profiles/*.json.
    """
    ensure_kb_dirs()
    source_path = Path(source_path)

    baseline_geom = None
    hint = profile_id
    if hint:
        try:
            existing = load_profile(hint, strict=False)
            baseline_geom = {k: float(v) for k, v in (existing.get("geometry") or {}).items() if isinstance(v, (int, float))}
        except FileNotFoundError:
            pass
    elif (PROFILES_DIR / f"{TEMPLATE_ID}.json").is_file():
        existing = load_profile(TEMPLATE_ID, strict=False)
        baseline_geom = {k: float(v) for k, v in (existing.get("geometry") or {}).items() if isinstance(v, (int, float))}

    extraction = extract_from_source(source_path, profile_id_hint=hint, baseline_geometry=baseline_geom)
    series_id = hint or extraction.get("series_guess") or "unknown_series"
    series_id = re.sub(r"[^a-zA-Z0-9_]+", "_", str(series_id)).strip("_").lower() or "unknown_series"

    plan = compare_to_library(series_id)
    draft, review = build_proposed_profile(plan, extraction)

    if display_name:
        draft["displayName"] = display_name

    proposal_id = f"{series_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
    proposal = {
        "proposal_id": proposal_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending_approval",
        "action": plan["action"],
        "profile_id": series_id,
        "source_path": str(source_path.resolve()),
        "source_type": extraction.get("source_type"),
        "extractor": extraction.get("extractor"),
        "reason": plan["reason"],
        "safety": {
            "auto_write_production": False,
            "message": "Production profiles are NOT modified until --approve",
        },
        "review": review,
        "notes": extraction.get("notes") or [],
        "proposed_profile": {k: v for k, v in draft.items() if k != "_path"},
        "extraction_meta": {
            "measurements_mm": extraction.get("measurements_mm"),
            "overall_dims_mm": extraction.get("overall_dims_mm"),
        },
    }
    path = write_pending_proposal(proposal)
    proposal["pending_path"] = str(path)
    return proposal


def approve(
    proposal_id: str,
    *,
    confirmed_by: str = "user",
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """
    Apply an approved proposal to production profiles/ after KB version snapshot.

    If `paths` is provided, only those dotted rule paths are applied (partial approve).
    Otherwise all review rows with action set/replace_section/confirm are applied.
    """
    ensure_kb_dirs()
    proposal = load_pending_proposal(proposal_id)
    if proposal.get("status") not in ("pending_approval", "pending"):
        raise ValueError(f"Proposal {proposal_id} status is {proposal.get('status')!r}, not pending")

    profile_id = proposal["profile_id"]
    action = proposal["action"]
    proposed = copy.deepcopy(proposal["proposed_profile"])
    proposed.pop("_draft_note", None)
    proposed.pop("_path", None)

    prod_path = PROFILES_DIR / f"{profile_id}.json"

    # Seed history from current production before first overwrite
    if prod_path.is_file():
        seed_initial_version_if_missing(profile_id, prod_path)
        current = load_profile(profile_id, strict=False)
        current.pop("_path", None)
    else:
        current = _blank_profile_shell(profile_id, proposed.get("displayName"))

    review = proposal.get("review") or []
    apply_paths = set(paths) if paths else None
    applied: list[str] = []

    for row in review:
        path = row["path"]
        if apply_paths is not None and path not in apply_paths:
            continue
        act = row.get("action", "set")
        if act == "replace_section":
            # Full section from proposed_profile
            if path in proposed:
                current[path] = copy.deepcopy(proposed[path])
                applied.append(path)
            continue
        if act in ("set", "confirm"):
            val = _get_by_path(proposed, path)
            if val is None and "detected_value" in row:
                val = row["detected_value"]
            if val is not None and path != "(section replace)":
                _set_by_path(current, path, val)
                set_rule_provenance(
                    current,
                    path,
                    source=str(row.get("source", proposal.get("source_path", "approved"))),
                    confidence=float(row.get("confidence", 1.0)),
                    notes="Approved learning proposal",
                    confirmed_by=confirmed_by,
                )
                applied.append(path)

    # If create and no selective paths, take full proposed shell for missing sections
    if action == "create" and apply_paths is None:
        for sec in REQUIRED_SECTIONS:
            if sec not in current and sec in proposed:
                current[sec] = copy.deepcopy(proposed[sec])
                applied.append(sec)

    confirm_paths(current, applied, confirmed_by=confirmed_by, source_override="user_confirmation")

    current["id"] = profile_id
    if "displayName" in proposed:
        current["displayName"] = proposed["displayName"]

    issues = validate_profile_sections(current)
    if issues:
        raise ValueError(f"Approved profile incomplete: {', '.join(issues)}")

    # Snapshot NEW version first (immutable history), then write production
    meta = snapshot_profile(
        profile_id,
        current,
        reason=f"Approved proposal {proposal_id}",
        source=str(proposal.get("source_path", "user_confirmation")),
        proposal_id=proposal_id,
    )
    current["version"] = meta["version"]

    # Strip runtime-only keys before write
    out_doc = {k: v for k, v in current.items() if k != "_path"}
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    prod_path.write_text(json.dumps(out_doc, indent=2) + "\n", encoding="utf-8")

    proposal["status"] = "approved"
    proposal["approved_at"] = datetime.now(timezone.utc).isoformat()
    proposal["approved_by"] = confirmed_by
    proposal["applied_paths"] = applied
    proposal["version"] = meta["version"]
    archive_pending(proposal_id, status="approved", proposal=proposal)

    return {
        "status": "approved",
        "proposal_id": proposal_id,
        "profile_id": profile_id,
        "version": meta["version"],
        "production_path": str(prod_path),
        "knowledge_base_version": meta,
        "applied_paths": applied,
    }


def reject(proposal_id: str, *, reason: str = "") -> dict[str, Any]:
    proposal = load_pending_proposal(proposal_id)
    proposal["status"] = "rejected"
    proposal["rejected_at"] = datetime.now(timezone.utc).isoformat()
    proposal["reject_reason"] = reason
    archive_pending(proposal_id, status="rejected", proposal=proposal)
    return {"status": "rejected", "proposal_id": proposal_id, "reason": reason}


def pending_proposals() -> list[str]:
    """List pending proposal ids awaiting --approve."""
    return list_pending()


def write_ingest_report(plan: dict[str, Any], out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return out_path


# Back-compat aliases for earlier scaffold API
class IngestPlan:
    """Deprecated thin wrapper — prefer compare_to_library() dict."""

    def __init__(self, data: dict[str, Any]):
        self._data = data
        self.action = data["action"]
        self.profile_id = data["profile_id"]
        self.reason = data["reason"]
        self.proposed_path = Path(data["proposed_path"])
        self.existing_sections = data.get("existing_sections") or []
        self.notes = data.get("notes") or []

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)


def stub_extract_from_reference(source_path: str | Path) -> dict[str, Any]:
    """Deprecated — use extract_from_source."""
    return extract_from_source(source_path)

