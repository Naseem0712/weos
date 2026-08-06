"""Manufacturing Knowledge Base V2 — pending queue, libraries, versioned publish.

Flow: Extract → Pending Review → Admin Approve → Knowledge Base Version
Production products/profiles are NEVER written from this module.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from WEOS.learning.knowledge_base import ensure_kb_dirs, KB_PENDING
from WEOS.learning.models import (
    ALL_KINDS,
    KIND_GLASS,
    KIND_HARDWARE,
    KIND_PRODUCT_SERIES,
    KIND_PROFILE,
    STATUS_PENDING,
    TREE_GROUPS,
)
from WEOS.paths import knowledge_base_dir

# ── Paths ────────────────────────────────────────────────────────────────────

def kb_root() -> Path:
    return knowledge_base_dir()


def uploads_dir() -> Path:
    d = kb_root() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def libraries_dir() -> Path:
    d = kb_root() / "libraries"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lib_subdir(name: str) -> Path:
    d = libraries_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def versions_dir() -> Path:
    d = kb_root() / "versions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pipeline_dir() -> Path:
    d = kb_root() / "pipeline"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pending_v2_dir() -> Path:
    """V2 pending proposals live under knowledge_base/pending/v2/."""
    d = KB_PENDING / "v2"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_v2_dirs() -> None:
    ensure_kb_dirs()
    for name in (
        "product_series",
        "profiles",
        "hardware",
        "glass",
        "accessories",
        "packaging",
        "formulas",
        "templates",
        "quotation_patterns",
    ):
        lib_subdir(name)
    uploads_dir()
    versions_dir()
    pending_v2_dir()
    pipeline_dir()
    hooks = pipeline_dir() / "hooks.json"
    if not hooks.is_file():
        from WEOS.learning.models import PIPELINE_SOURCES

        hooks.write_text(
            json.dumps(
                {
                    "description": "Continuous learn pipeline hooks — always gated by admin review",
                    "autoWriteProduction": False,
                    "sources": list(PIPELINE_SOURCES),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "item"


def new_id(prefix: str = "item") -> str:
    return f"{_slug(prefix)}_{uuid.uuid4().hex[:8]}"


# ── Pending queue ────────────────────────────────────────────────────────────

def write_pending(proposal: dict[str, Any]) -> Path:
    ensure_v2_dirs()
    pid = proposal["proposal_id"]
    path = pending_v2_dir() / f"{pid}.json"
    path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_pending(proposal_id: str) -> dict[str, Any]:
    ensure_v2_dirs()
    path = pending_v2_dir() / f"{proposal_id}.json"
    if not path.is_file():
        # Fall back to legacy pending root
        legacy = KB_PENDING / f"{proposal_id}.json"
        if legacy.is_file():
            return json.loads(legacy.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"Pending proposal not found: {proposal_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_pending_v2(*, kind: str | None = None, status: str | None = STATUS_PENDING) -> list[dict[str, Any]]:
    ensure_v2_dirs()
    items: list[dict[str, Any]] = []
    for path in sorted(pending_v2_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if kind and doc.get("kind") != kind:
            continue
        if status and doc.get("status") != status:
            continue
        items.append(_pending_summary(doc))
    return items


def _pending_summary(doc: dict[str, Any]) -> dict[str, Any]:
    payload = doc.get("payload") or {}
    return {
        "proposal_id": doc.get("proposal_id"),
        "kind": doc.get("kind"),
        "status": doc.get("status"),
        "title": doc.get("title") or payload.get("seriesName") or payload.get("profileName") or payload.get("name") or doc.get("proposal_id"),
        "summary": doc.get("summary") or "",
        "confidence": doc.get("confidence"),
        "created_at": doc.get("created_at"),
        "source_type": (doc.get("source") or {}).get("type"),
        "source_name": (doc.get("source") or {}).get("filename"),
        "item_counts": doc.get("item_counts") or {},
        "match_hints": doc.get("match_hints") or [],
    }


def archive_pending_v2(proposal_id: str, *, status: str, proposal: dict[str, Any]) -> Path:
    ensure_v2_dirs()
    path = pending_v2_dir() / f"{proposal_id}.json"
    archive = pending_v2_dir() / "archived"
    archive.mkdir(parents=True, exist_ok=True)
    dest = archive / f"{proposal_id}_{status}.json"
    dest.write_text(json.dumps(proposal, indent=2, ensure_ascii=False), encoding="utf-8")
    path.unlink(missing_ok=True)
    return dest


def create_pending(
    *,
    kind: str,
    title: str,
    payload: dict[str, Any],
    source: dict[str, Any] | None = None,
    summary: str = "",
    confidence: float = 0.6,
    item_counts: dict[str, int] | None = None,
    notes: list[str] | None = None,
    match_hints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if kind not in ALL_KINDS:
        raise ValueError(f"Unknown proposal kind: {kind}")
    ensure_v2_dirs()
    stem = _slug(title)[:40]
    proposal_id = f"v2_{stem}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
    proposal = {
        "proposal_id": proposal_id,
        "kind": kind,
        "status": STATUS_PENDING,
        "created_at": _now(),
        "title": title,
        "summary": summary,
        "confidence": round(float(confidence), 3),
        "source": source or {},
        "payload": payload,
        "edits": {},
        "item_counts": item_counts or {},
        "match_hints": match_hints or [],
        "notes": notes or [],
        "safety": {
            "auto_write_production": False,
            "message": "Production data is never modified automatically. Approve publishes to the Knowledge Base only.",
        },
    }
    write_pending(proposal)
    return proposal


# ── Dedupe / link ────────────────────────────────────────────────────────────

def _norm_key(*parts: Any) -> str:
    raw = " ".join(str(p or "").strip().lower() for p in parts)
    return re.sub(r"[^a-z0-9]+", "", raw)


def find_library_match(kind: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """Return best existing library item to link, or None."""
    folder = {
        KIND_PRODUCT_SERIES: "product_series",
        KIND_PROFILE: "profiles",
        KIND_HARDWARE: "hardware",
        KIND_GLASS: "glass",
        "accessory": "accessories",
        "packaging": "packaging",
        "formula": "formulas",
        "template": "templates",
        "quotation_pattern": "quotation_patterns",
    }.get(kind)
    if not folder:
        return None

    candidates = list_library(folder)
    if not candidates:
        return None

    if kind == KIND_PROFILE:
        code = _norm_key(item.get("profileCode"))
        name = _norm_key(item.get("profileName"))
        w = item.get("crossSectionWidthMm")
        h = item.get("crossSectionHeightMm")
        for c in candidates:
            if code and _norm_key(c.get("profileCode")) == code:
                return {"action": "link", "existing_id": c["id"], "reason": "Matching profile code", "existing": c}
            if name and _norm_key(c.get("profileName")) == name:
                same_dims = (
                    w is not None
                    and h is not None
                    and c.get("crossSectionWidthMm") == w
                    and c.get("crossSectionHeightMm") == h
                )
                if same_dims or not (w and h):
                    return {"action": "link", "existing_id": c["id"], "reason": "Matching profile name", "existing": c}
        return None

    if kind == KIND_HARDWARE:
        pn = _norm_key(item.get("partNumber"))
        name = _norm_key(item.get("name"), item.get("brand"))
        for c in candidates:
            if pn and _norm_key(c.get("partNumber")) == pn:
                return {"action": "link", "existing_id": c["id"], "reason": "Matching part number", "existing": c}
            if name and _norm_key(c.get("name"), c.get("brand")) == name:
                return {"action": "link", "existing_id": c["id"], "reason": "Matching hardware name+brand", "existing": c}
        return None

    if kind == KIND_GLASS:
        key = _norm_key(item.get("name") or item.get("glassType"), item.get("thicknessMm"), item.get("colour"))
        for c in candidates:
            ck = _norm_key(c.get("name") or c.get("glassType"), c.get("thicknessMm"), c.get("colour"))
            if key and key == ck:
                return {"action": "link", "existing_id": c["id"], "reason": "Matching glass type/thickness/colour", "existing": c}
        return None

    if kind == KIND_PRODUCT_SERIES:
        sid = _norm_key(item.get("id") or item.get("seriesName"))
        for c in candidates:
            if sid and _norm_key(c.get("id") or c.get("seriesName")) == sid:
                return {"action": "link", "existing_id": c["id"], "reason": "Matching series id/name", "existing": c}
        return None

    # Generic name match
    name = _norm_key(item.get("name") or item.get("seriesName") or item.get("id"))
    for c in candidates:
        if name and _norm_key(c.get("name") or c.get("seriesName") or c.get("id")) == name:
            return {"action": "link", "existing_id": c["id"], "reason": "Matching name", "existing": c}
    return None


# ── Library CRUD ─────────────────────────────────────────────────────────────

def list_library(folder: str) -> list[dict[str, Any]]:
    ensure_v2_dirs()
    out: list[dict[str, Any]] = []
    for path in sorted(lib_subdir(folder).glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc.setdefault("id", path.stem)
            out.append(doc)
        except Exception:
            continue
    return out


def get_library_item(folder: str, item_id: str) -> dict[str, Any]:
    path = lib_subdir(folder) / f"{item_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"{folder}/{item_id} not found")
    return json.loads(path.read_text(encoding="utf-8"))


def save_library_item(folder: str, item: dict[str, Any], *, link_existing: bool = True) -> dict[str, Any]:
    """Save item; if match found and link_existing, merge into existing instead of duplicating."""
    ensure_v2_dirs()
    kind_map = {
        "product_series": KIND_PRODUCT_SERIES,
        "profiles": KIND_PROFILE,
        "hardware": KIND_HARDWARE,
        "glass": KIND_GLASS,
        "accessories": "accessory",
        "packaging": "packaging",
        "formulas": "formula",
        "templates": "template",
        "quotation_patterns": "quotation_pattern",
    }
    kind = kind_map.get(folder, folder)
    match = find_library_match(kind, item) if link_existing else None
    if match and match.get("existing_id"):
        existing = get_library_item(folder, match["existing_id"])
        merged = {**existing}
        for k, v in item.items():
            if k in ("id",):
                continue
            if v in (None, "", [], {}):
                continue
            if isinstance(v, list) and isinstance(merged.get(k), list):
                # union lists of scalars / dicts by id
                if v and isinstance(v[0], dict):
                    by_id = {x.get("id"): x for x in merged[k] if isinstance(x, dict) and x.get("id")}
                    for x in v:
                        xid = x.get("id")
                        if xid and xid in by_id:
                            by_id[xid] = {**by_id[xid], **{kk: vv for kk, vv in x.items() if vv not in (None, "", [])}}
                        else:
                            merged[k].append(x)
                else:
                    merged[k] = list(dict.fromkeys([*merged[k], *v]))
            else:
                merged[k] = v
        merged["updated_at"] = _now()
        merged["linked_from_learning"] = True
        path = lib_subdir(folder) / f"{merged['id']}.json"
        path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"action": "linked", "item": merged, "match": match}

    item_id = item.get("id") or new_id(folder.rstrip("s"))
    item = {**item, "id": item_id}
    item.setdefault("created_at", _now())
    item["updated_at"] = _now()
    item["status"] = "approved"
    path = lib_subdir(folder) / f"{item_id}.json"
    path.write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"action": "created", "item": item, "match": None}


# ── Versioned KB publish ─────────────────────────────────────────────────────

def current_kb_version() -> int:
    ensure_v2_dirs()
    manifest = versions_dir() / "manifest.json"
    if not manifest.is_file():
        return 0
    return int(json.loads(manifest.read_text(encoding="utf-8")).get("current_version", 0))


def publish_kb_version(
    *,
    reason: str,
    proposal_id: str | None = None,
    approved_by: str = "admin",
    snapshot_libraries: bool = True,
) -> dict[str, Any]:
    """Create immutable KB version snapshot of approved libraries."""
    ensure_v2_dirs()
    ver = current_kb_version() + 1
    dest = versions_dir() / f"v{ver}"
    dest.mkdir(parents=True, exist_ok=True)

    copied: dict[str, int] = {}
    if snapshot_libraries:
        for name in (
            "product_series",
            "profiles",
            "hardware",
            "glass",
            "accessories",
            "packaging",
            "formulas",
            "templates",
            "quotation_patterns",
        ):
            src = lib_subdir(name)
            target = dest / name
            target.mkdir(parents=True, exist_ok=True)
            n = 0
            for f in src.glob("*.json"):
                if f.name.startswith("_"):
                    continue
                shutil.copy2(f, target / f.name)
                n += 1
            copied[name] = n

    meta = {
        "version": ver,
        "created_at": _now(),
        "reason": reason,
        "proposal_id": proposal_id,
        "approved_by": approved_by,
        "libraries": copied,
        "auto_write_production": False,
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    manifest_path = versions_dir() / "manifest.json"
    manifest = {"current_version": 0, "versions": []}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["current_version"] = ver
    versions = list(manifest.get("versions") or [])
    versions.append(
        {
            "version": ver,
            "created_at": meta["created_at"],
            "reason": reason,
            "proposal_id": proposal_id,
            "approved_by": approved_by,
            "path": f"versions/v{ver}",
        }
    )
    manifest["versions"] = versions
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return meta


def list_kb_versions() -> list[dict[str, Any]]:
    ensure_v2_dirs()
    manifest_path = versions_dir() / "manifest.json"
    if not manifest_path.is_file():
        return []
    return list(json.loads(manifest_path.read_text(encoding="utf-8")).get("versions") or [])


def rollback_kb_version(
    to_version: int,
    *,
    rolled_back_by: str = "admin",
    reason: str = "",
) -> dict[str, Any]:
    """Restore working libraries from an immutable snapshot versions/vN.

    Does NOT delete historical versions. Creates a NEW version snapshot after
    restore so the rollback itself is auditable. Production products untouched.
    """
    ensure_v2_dirs()
    to_version = int(to_version)
    src = versions_dir() / f"v{to_version}"
    if not src.is_dir():
        raise FileNotFoundError(f"KB version v{to_version} not found")

    lib_names = (
        "product_series",
        "profiles",
        "hardware",
        "glass",
        "accessories",
        "packaging",
        "formulas",
        "templates",
        "quotation_patterns",
    )

    # Wipe current library JSON (not the whole folder — keep structure)
    restored: dict[str, int] = {}
    for name in lib_names:
        target = lib_subdir(name)
        for f in target.glob("*.json"):
            if f.name.startswith("_"):
                continue
            f.unlink(missing_ok=True)
        snap = src / name
        n = 0
        if snap.is_dir():
            for f in snap.glob("*.json"):
                if f.name.startswith("_"):
                    continue
                shutil.copy2(f, target / f.name)
                n += 1
        restored[name] = n

    # Publish a new version documenting the rollback (append-only history)
    meta = publish_kb_version(
        reason=reason or f"Rollback restore from v{to_version}",
        proposal_id=None,
        approved_by=rolled_back_by,
        snapshot_libraries=True,
    )
    meta["rolled_back_to"] = to_version
    meta["production_modified"] = False

    # Annotate manifest entry
    manifest_path = versions_dir() / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    versions = list(manifest.get("versions") or [])
    if versions:
        versions[-1]["rollback_from"] = to_version
        versions[-1]["action"] = "rollback"
        manifest["versions"] = versions
        # Keep a pointer for UI convenience
        manifest["last_rollback"] = {
            "to_version": to_version,
            "new_version": meta.get("version"),
            "at": meta.get("created_at"),
            "by": rolled_back_by,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Update new version meta.json too
    ver_dir = versions_dir() / f"v{meta['version']}"
    meta_path = ver_dir / "meta.json"
    if meta_path.is_file():
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        m["rolled_back_to"] = to_version
        m["action"] = "rollback"
        m["libraries_restored"] = restored
        meta_path.write_text(json.dumps(m, indent=2), encoding="utf-8")
        meta["libraries_restored"] = restored

    return meta


# ── Product Library tree ─────────────────────────────────────────────────────

def build_series_tree(series_id: str | None = None) -> list[dict[str, Any]]:
    """Product Library tree: series → profile groups → items (+ hardware/accessories)."""
    ensure_v2_dirs()
    series_list = list_library("product_series")
    profiles = list_library("profiles")
    hardware = list_library("hardware")
    accessories = list_library("accessories")

    if series_id:
        series_list = [s for s in series_list if s.get("id") == series_id]
        if not series_list:
            # synthesize from profiles that claim this series
            series_list = [
                {
                    "id": series_id,
                    "seriesName": series_id.replace("_", " ").title(),
                    "brand": "",
                    "productCategory": "",
                }
            ]

    trees: list[dict[str, Any]] = []
    for series in series_list:
        sid = series.get("id") or ""
        sname = series.get("seriesName") or sid
        series_profiles = [
            p
            for p in profiles
            if sid in (p.get("compatibleSeries") or [])
            or sid == p.get("seriesId")
            or any(_slug(sname) in _slug(str(x)) for x in (p.get("compatibleSeries") or []))
        ]
        # Also include profiles referenced on series payload
        for pid in series.get("profiles") or []:
            if isinstance(pid, str):
                if not any(p.get("id") == pid for p in series_profiles):
                    try:
                        series_profiles.append(get_library_item("profiles", pid))
                    except FileNotFoundError:
                        pass
            elif isinstance(pid, dict) and pid.get("id"):
                if not any(p.get("id") == pid["id"] for p in series_profiles):
                    series_profiles.append(pid)

        children: list[dict[str, Any]] = []
        used_ids: set[str] = set()
        for gid, glabel, types in TREE_GROUPS:
            if gid == "hardware":
                hw = [
                    h
                    for h in hardware
                    if sid in (h.get("compatibleSeries") or []) or not (h.get("compatibleSeries") or [])
                ]
                # Prefer series-linked; if none, skip empty
                hw_linked = [h for h in hardware if sid in (h.get("compatibleSeries") or [])]
                hw = hw_linked
                children.append(
                    {
                        "id": f"{sid}__{gid}",
                        "label": glabel,
                        "group": gid,
                        "children": [
                            {
                                "id": h.get("id"),
                                "label": h.get("name") or h.get("id"),
                                "kind": "hardware",
                                "meta": {
                                    "partNumber": h.get("partNumber"),
                                    "unit": h.get("unit"),
                                },
                            }
                            for h in hw
                        ],
                    }
                )
                continue
            if gid == "accessories":
                acc = [a for a in accessories if sid in (a.get("compatibleSeries") or [])]
                # profiles typed as accessory-like
                acc_profiles = [
                    p
                    for p in series_profiles
                    if (p.get("profileType") or "Other") in types and p.get("id") not in used_ids
                ]
                for p in acc_profiles:
                    used_ids.add(p["id"])
                children.append(
                    {
                        "id": f"{sid}__{gid}",
                        "label": glabel,
                        "group": gid,
                        "children": [
                            *[
                                {
                                    "id": p.get("id"),
                                    "label": p.get("profileName") or p.get("id"),
                                    "kind": "profile",
                                    "meta": {
                                        "code": p.get("profileCode"),
                                        "w": p.get("crossSectionWidthMm"),
                                        "h": p.get("crossSectionHeightMm"),
                                        "kg_m": p.get("weightPerMeterKg"),
                                    },
                                }
                                for p in acc_profiles
                            ],
                            *[
                                {
                                    "id": a.get("id"),
                                    "label": a.get("name") or a.get("id"),
                                    "kind": "accessory",
                                    "meta": {},
                                }
                                for a in acc
                            ],
                        ],
                    }
                )
                continue

            group_items = [
                p
                for p in series_profiles
                if (p.get("profileType") or "Other") in types and p.get("id") not in used_ids
            ]
            for p in group_items:
                used_ids.add(p["id"])
            children.append(
                {
                    "id": f"{sid}__{gid}",
                    "label": glabel,
                    "group": gid,
                    "children": [
                        {
                            "id": p.get("id"),
                            "label": p.get("profileName") or p.get("id"),
                            "kind": "profile",
                            "meta": {
                                "code": p.get("profileCode"),
                                "w": p.get("crossSectionWidthMm"),
                                "h": p.get("crossSectionHeightMm"),
                                "kg_m": p.get("weightPerMeterKg"),
                                "page": p.get("pdfPageNumber"),
                            },
                        }
                        for p in group_items
                    ],
                }
            )

        # Orphan profiles
        orphans = [p for p in series_profiles if p.get("id") not in used_ids]
        if orphans:
            children.append(
                {
                    "id": f"{sid}__other",
                    "label": "Other Profiles",
                    "group": "other",
                    "children": [
                        {
                            "id": p.get("id"),
                            "label": p.get("profileName") or p.get("id"),
                            "kind": "profile",
                            "meta": {
                                "code": p.get("profileCode"),
                                "type": p.get("profileType"),
                            },
                        }
                        for p in orphans
                    ],
                }
            )

        trees.append(
            {
                "id": sid,
                "label": sname,
                "kind": "product_series",
                "brand": series.get("brand"),
                "category": series.get("productCategory"),
                "children": children,
                "profileCount": len(series_profiles),
            }
        )
    return trees


def save_upload(filename: str, data: bytes) -> dict[str, Any]:
    ensure_v2_dirs()
    safe = re.sub(r"[^\w.\- ]+", "_", filename or "upload.bin").strip() or "upload.bin"
    digest = hashlib.sha1(data).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest_name = f"{stamp}_{digest}_{safe}"
    path = uploads_dir() / dest_name
    path.write_bytes(data)
    return {
        "path": str(path),
        "filename": safe,
        "stored_as": dest_name,
        "size": len(data),
        "sha1": digest,
    }
