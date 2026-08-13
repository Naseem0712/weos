"""Per-line design photo — durable blob + filesystem cache (not /tmp-only).

Used when a user uploads a photo of the design; customer PDF prints the photo
in the DESIGN column instead of the canvas SVG.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from WEOS.paths import data_dir

_log = logging.getLogger("weos.design_photo")

_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def photo_key(project_id: str, line_id: str) -> str:
    pid = (project_id or "project").strip() or "project"
    lid = (line_id or "line").strip() or "line"
    return f"design_photo:{pid}:{lid}"


def _cache_dir(project_id: str) -> Path:
    d = data_dir() / "design_photos" / str(project_id or "project").replace("/", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ext(content_type: str | None, filename: str | None) -> str:
    ct = (content_type or "").lower()
    if ct in _EXT:
        return _EXT[ct]
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"


def save_design_photo(
    project_id: str,
    line_id: str,
    raw: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    if not raw:
        raise ValueError("Empty upload")
    if not line_id:
        raise ValueError("line_id required")
    ct = (content_type or "").lower() or None
    ext = _ext(ct, filename)
    ct = ct or {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/png")
    folder = _cache_dir(project_id)
    for old in folder.glob(f"{line_id}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = folder / f"{line_id}{ext}"
    dest.write_bytes(raw)
    key = photo_key(project_id, line_id)
    try:
        from WEOS.db.durable_store import put_blob

        put_blob(
            key,
            kind="design_photo",
            raw=raw,
            content_type=ct,
            filename=dest.name,
            payload={"projectId": project_id, "lineId": line_id, "filename": filename},
        )
    except Exception:
        _log.exception("design photo DB put failed for %s", key)
    url = f"/api/projects/{project_id}/lines/{line_id}/design-photo"
    return {
        "ok": True,
        "key": key,
        "url": url,
        "path": str(dest),
        "contentType": ct,
        "filename": filename or dest.name,
        "projectId": project_id,
        "lineId": line_id,
    }


def design_photo_bytes_by_key(key: str) -> tuple[bytes | None, str | None]:
    if not key:
        return None, None
    try:
        from WEOS.db.durable_store import get_blob

        raw, ct, _fn = get_blob(key)
        if raw:
            return raw, ct or "image/jpeg"
    except Exception:
        _log.exception("design photo DB get failed for %s", key)
    # Filesystem fallback: design_photo:{project}:{line}
    parts = str(key).split(":")
    if len(parts) >= 3 and parts[0] == "design_photo":
        pid, lid = parts[1], parts[2]
        folder = data_dir() / "design_photos" / str(pid).replace("/", "_")
        if folder.is_dir():
            matches = list(folder.glob(f"{lid}.*"))
            if matches:
                try:
                    raw = matches[0].read_bytes()
                    mime = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".webp": "image/webp",
                        ".gif": "image/gif",
                    }.get(matches[0].suffix.lower(), "image/jpeg")
                    return raw, mime
                except OSError:
                    return None, None
    return None, None


def design_photo_bytes(project_id: str, line_id: str) -> tuple[bytes | None, str | None]:
    return design_photo_bytes_by_key(photo_key(project_id, line_id))


def delete_design_photo(project_id: str, line_id: str) -> bool:
    key = photo_key(project_id, line_id)
    ok = False
    try:
        from WEOS.db.durable_store import delete_key

        ok = bool(delete_key(key))
    except Exception:
        _log.exception("design photo DB delete failed for %s", key)
    folder = _cache_dir(project_id)
    for old in folder.glob(f"{line_id}.*"):
        try:
            old.unlink()
            ok = True
        except OSError:
            pass
    return ok
