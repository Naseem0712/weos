"""Knowledge base — versioned profile history + pending learning proposals.

Production profiles live in profiles/. Every approved update:
1. Snapshots the previous production JSON under knowledge_base/profiles/<id>/vN/
2. Writes the new production JSON
3. Updates the series manifest

Learning proposals NEVER write production profiles until explicit --approve.
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from WEOS.paths import PACKAGE_ROOT, WORKSPACE_ROOT, knowledge_base_dir

ROOT = WORKSPACE_ROOT
KB_ROOT = knowledge_base_dir()
KB_PROFILES = KB_ROOT / "profiles"
KB_PENDING = KB_ROOT / "pending"
KB_HARDWARE = KB_ROOT / "hardware_library"
KB_GLASS = KB_ROOT / "glass_library"
PRODUCTS_DIR = PACKAGE_ROOT / "products"


def ensure_kb_dirs() -> None:
    for d in (KB_PROFILES, KB_PENDING, KB_HARDWARE, KB_GLASS):
        d.mkdir(parents=True, exist_ok=True)
    # V2 libraries / versions / uploads (lazy; full ensure via v2_store.ensure_v2_dirs)
    for sub in ("libraries", "versions", "uploads", "pipeline", "pending/v2"):
        (KB_ROOT / sub).mkdir(parents=True, exist_ok=True)
    readme = KB_ROOT / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# Manufacturing Knowledge Base\n\n"
            "- `profiles/<series>/vN/` — immutable version snapshots of approved engineering profile JSON\n"
            "- `pending/` — legacy learning proposals; `pending/v2/` — Learning Engine V2 queue\n"
            "- `libraries/` — approved Product Series / Profiles / Hardware / Glass / Formulas / Templates\n"
            "- `versions/vN/` — immutable KB snapshots after admin approve\n"
            "- `uploads/` — source PDFs/images for review\n"
            "- `hardware_library/` / `glass_library/` — legacy shared catalogues (stubs)\n"
            "\nFlow: Extract → Review → Approve → Knowledge Base Version → Production (manual).\n"
            "Learning Engine never auto-writes production products or profiles.\n",
            encoding="utf-8",
        )


def series_dir(profile_id: str) -> Path:
    return KB_PROFILES / profile_id


def manifest_path(profile_id: str) -> Path:
    return series_dir(profile_id) / "manifest.json"


def load_manifest(profile_id: str) -> dict[str, Any]:
    ensure_kb_dirs()
    path = manifest_path(profile_id)
    if not path.is_file():
        return {
            "profile_id": profile_id,
            "current_version": 0,
            "versions": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(profile_id: str, manifest: dict[str, Any]) -> Path:
    ensure_kb_dirs()
    d = series_dir(profile_id)
    d.mkdir(parents=True, exist_ok=True)
    path = manifest_path(profile_id)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def next_version(profile_id: str) -> int:
    m = load_manifest(profile_id)
    return int(m.get("current_version", 0)) + 1


def snapshot_profile(
    profile_id: str,
    profile_doc: dict[str, Any],
    *,
    reason: str,
    source: str,
    proposal_id: str | None = None,
) -> dict[str, Any]:
    """Write immutable vN snapshot + bump manifest. Does not touch profiles/."""
    ensure_kb_dirs()
    ver = next_version(profile_id)
    dest = series_dir(profile_id) / f"v{ver}"
    dest.mkdir(parents=True, exist_ok=True)

    clean = {k: v for k, v in profile_doc.items() if not str(k).startswith("_") or k == "_provenance"}
    # Keep provenance; drop runtime _path
    clean.pop("_path", None)
    clean["version"] = ver

    profile_out = dest / "profile.json"
    meta = {
        "profile_id": profile_id,
        "version": ver,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "source": source,
        "proposal_id": proposal_id,
    }
    profile_out.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    manifest = load_manifest(profile_id)
    manifest["current_version"] = ver
    versions = list(manifest.get("versions") or [])
    versions.append(
        {
            "version": ver,
            "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "created_at": meta["created_at"],
            "reason": reason,
            "source": source,
            "proposal_id": proposal_id,
        }
    )
    manifest["versions"] = versions
    save_manifest(profile_id, manifest)
    return meta


def write_pending_proposal(proposal: dict[str, Any]) -> Path:
    ensure_kb_dirs()
    pid = proposal["proposal_id"]
    path = KB_PENDING / f"{pid}.json"
    path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    return path


def load_pending_proposal(proposal_id: str) -> dict[str, Any]:
    path = KB_PENDING / f"{proposal_id}.json"
    if not path.is_file():
        # allow bare stem or with .json
        alt = KB_PENDING / proposal_id
        if alt.is_file():
            path = alt
        else:
            raise FileNotFoundError(f"Pending proposal not found: {proposal_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_pending() -> list[str]:
    ensure_kb_dirs()
    return sorted(p.stem for p in KB_PENDING.glob("*.json"))


def archive_pending(proposal_id: str, *, status: str, proposal: dict[str, Any] | None = None) -> Path | None:
    ensure_kb_dirs()
    path = KB_PENDING / f"{proposal_id}.json"
    if not path.is_file():
        return None
    archive = KB_PENDING / "archived"
    archive.mkdir(parents=True, exist_ok=True)
    dest = archive / f"{proposal_id}_{status}.json"
    if proposal is not None:
        dest.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
        path.unlink(missing_ok=True)
    else:
        shutil.move(str(path), str(dest))
    return dest


def seed_initial_version_if_missing(profile_id: str, production_path: Path) -> None:
    """If series has no KB history, snapshot current production as v1."""
    ensure_kb_dirs()
    m = load_manifest(profile_id)
    if int(m.get("current_version", 0)) > 0:
        return
    if not production_path.is_file():
        return
    doc = json.loads(production_path.read_text(encoding="utf-8"))
    snapshot_profile(
        profile_id,
        doc,
        reason="Initial knowledge-base seed from production profile",
        source=str(production_path.name),
        proposal_id=None,
    )

