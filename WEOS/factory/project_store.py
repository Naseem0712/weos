"""Project persistence — save / reload / version / archive WEOS projects."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from WEOS.paths import PACKAGE_ROOT, projects_dir

WEOS_ROOT = PACKAGE_ROOT
PROJECTS_DIR = projects_dir()
ARCHIVE_DIR = PROJECTS_DIR / "archived"
COUNTER_FILE = PROJECTS_DIR / "_counter.json"
HISTORY_DIR = PROJECTS_DIR / "history"


def ensure_projects_dir() -> Path:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECTS_DIR / "versions").mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return PROJECTS_DIR


def _next_seq(year: int) -> int:
    ensure_projects_dir()
    data: dict[str, Any] = {"year": year, "seq": 0}
    if COUNTER_FILE.is_file():
        data = json.loads(COUNTER_FILE.read_text(encoding="utf-8"))
    if int(data.get("year", 0)) != year:
        data = {"year": year, "seq": 0, "quote_seq": int(data.get("quote_seq", 0))}
    data["seq"] = int(data.get("seq", 0)) + 1
    COUNTER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return int(data["seq"])


def new_project_id() -> str:
    year = datetime.now(timezone.utc).year
    return f"PRJ-{year}-{_next_seq(year):05d}"


def new_quotation_id() -> str:
    year = datetime.now(timezone.utc).year
    ensure_projects_dir()
    data: dict[str, Any] = {"year": year, "seq": 0, "quote_seq": 0}
    if COUNTER_FILE.is_file():
        data = json.loads(COUNTER_FILE.read_text(encoding="utf-8"))
    if int(data.get("year", 0)) != year:
        data = {"year": year, "seq": int(data.get("seq", 0)), "quote_seq": 0}
    data["quote_seq"] = int(data.get("quote_seq", 0)) + 1
    COUNTER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return f"QT-{year}-{data['quote_seq']:06d}"


def project_path(project_id: str) -> Path:
    return ensure_projects_dir() / f"{project_id}.json"


def _append_history(project_id: str, action: str, version: int) -> None:
    path = HISTORY_DIR / f"{project_id}.jsonl"
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "version": version,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def save_project(doc: dict[str, Any], *, bump_version: bool = True, action: str = "save") -> dict[str, Any]:
    ensure_projects_dir()
    pid = doc.get("projectId") or new_project_id()
    doc["projectId"] = pid
    doc.setdefault("status", "active")  # active | draft | archived
    now = datetime.now(timezone.utc).isoformat()
    if "createdAt" not in doc:
        doc["createdAt"] = now
    doc["updatedAt"] = now
    ver = int(doc.get("version", 0))
    if bump_version:
        ver += 1
    doc["version"] = ver

    # undo stack (last 20 snapshots of lines+meta for client undo)
    undo = list(doc.get("_undoStack") or [])
    if bump_version and project_path(pid).is_file():
        prev = json.loads(project_path(pid).read_text(encoding="utf-8"))
        undo.append(
            {
                "version": prev.get("version"),
                "lines": prev.get("lines"),
                "name": prev.get("name"),
                "customer": prev.get("customer"),
            }
        )
        undo = undo[-20:]
    doc["_undoStack"] = undo
    if bump_version:
        doc["_redoStack"] = []

    path = project_path(pid)
    if path.is_file() and bump_version:
        snap = PROJECTS_DIR / "versions" / f"{pid}_v{ver - 1}.json"
        shutil.copy2(path, snap)

    # strip runtime
    out = {k: v for k, v in doc.items() if k != "_path"}
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    _append_history(pid, action, ver)
    doc["_path"] = path.as_posix()
    return doc


def load_project(project_id: str) -> dict[str, Any]:
    path = project_path(project_id)
    if not path.is_file():
        archived = ARCHIVE_DIR / f"{project_id}.json"
        if archived.is_file():
            path = archived
        else:
            raise FileNotFoundError(f"Project not found: {project_id}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["_path"] = path.as_posix()
    return doc


def list_projects(
    *,
    q: str | None = None,
    status: str | None = None,
    sort: str = "updatedAt",
    order: str = "desc",
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    ensure_projects_dir()
    files = list(PROJECTS_DIR.glob("PRJ-*.json"))
    if include_archived or status == "archived":
        files += list(ARCHIVE_DIR.glob("PRJ-*.json"))
    out: list[dict[str, Any]] = []
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            st = d.get("status", "active")
            if status and st != status:
                continue
            if not include_archived and status != "archived" and st == "archived" and p.parent == ARCHIVE_DIR:
                continue
            row = {
                "projectId": d.get("projectId", p.stem),
                "name": d.get("name"),
                "customer": d.get("customer"),
                "customerMobile": d.get("customerMobile"),
                "status": st,
                "updatedAt": d.get("updatedAt"),
                "createdAt": d.get("createdAt"),
                "version": d.get("version"),
                "lineCount": len(d.get("lines") or []),
                "quotationId": d.get("quotationId"),
                "grandTotal": (d.get("lastCalculation") or {}).get("price", {}).get("total"),
            }
            if q:
                blob = f"{row['projectId']} {row['name']} {row['customer']} {row.get('quotationId')}".lower()
                if q.lower() not in blob:
                    continue
            out.append(row)
        except Exception:
            out.append({"projectId": p.stem, "status": "unknown"})
    reverse = order.lower() != "asc"
    out.sort(key=lambda r: r.get(sort) or "", reverse=reverse)
    return out


def duplicate_project(project_id: str, *, name: str | None = None) -> dict[str, Any]:
    src = load_project(project_id)
    src.pop("_path", None)
    src["projectId"] = new_project_id()
    src["name"] = name or f"Copy of {src.get('name') or project_id}"
    src["createdAt"] = datetime.now(timezone.utc).isoformat()
    src["version"] = 0
    src["status"] = "draft"
    src.pop("quotationId", None)
    src.pop("lastCalculation", None)
    src["_undoStack"] = []
    src["_redoStack"] = []
    return save_project(src, bump_version=True, action="duplicate")


def archive_project(project_id: str) -> dict[str, Any]:
    doc = load_project(project_id)
    doc["status"] = "archived"
    path = project_path(project_id)
    # save then move
    save_project(doc, bump_version=True, action="archive")
    if path.is_file():
        dest = ARCHIVE_DIR / path.name
        shutil.move(str(path), str(dest))
    doc["_path"] = (ARCHIVE_DIR / f"{project_id}.json").as_posix()
    return doc


def restore_project(project_id: str) -> dict[str, Any]:
    archived = ARCHIVE_DIR / f"{project_id}.json"
    if not archived.is_file():
        raise FileNotFoundError(f"Archived project not found: {project_id}")
    dest = project_path(project_id)
    shutil.move(str(archived), str(dest))
    doc = json.loads(dest.read_text(encoding="utf-8"))
    doc["status"] = "active"
    return save_project(doc, bump_version=True, action="restore")


def delete_project(project_id: str, *, hard: bool = False) -> dict[str, Any]:
    """Soft-delete = archive. hard=True removes active file after version keep."""
    if hard:
        path = project_path(project_id)
        if path.is_file():
            # keep last snapshot
            snap = PROJECTS_DIR / "versions" / f"{project_id}_deleted.json"
            shutil.copy2(path, snap)
            path.unlink()
            _append_history(project_id, "delete", -1)
            return {"deleted": True, "projectId": project_id}
        raise FileNotFoundError(project_id)
    return archive_project(project_id)


def project_history(project_id: str) -> list[dict[str, Any]]:
    ensure_projects_dir()
    path = HISTORY_DIR / f"{project_id}.jsonl"
    versions = sorted((PROJECTS_DIR / "versions").glob(f"{project_id}_v*.json"))
    hist = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                hist.append(json.loads(line))
    for v in versions:
        hist.append({"versionFile": v.name, "path": str(v.as_posix())})
    return hist


def undo_project(project_id: str) -> dict[str, Any]:
    doc = load_project(project_id)
    undo = list(doc.get("_undoStack") or [])
    if not undo:
        raise ValueError("Nothing to undo")
    current = {"version": doc.get("version"), "lines": doc.get("lines"), "name": doc.get("name"), "customer": doc.get("customer")}
    prev = undo.pop()
    redo = list(doc.get("_redoStack") or [])
    redo.append(current)
    doc["lines"] = prev.get("lines") or []
    if prev.get("name") is not None:
        doc["name"] = prev["name"]
    if prev.get("customer") is not None:
        doc["customer"] = prev["customer"]
    doc["_undoStack"] = undo
    doc["_redoStack"] = redo[-20:]
    # save without consuming undo again wrongly — manually write
    return save_project(doc, bump_version=True, action="undo")


def redo_project(project_id: str) -> dict[str, Any]:
    doc = load_project(project_id)
    redo = list(doc.get("_redoStack") or [])
    if not redo:
        raise ValueError("Nothing to redo")
    nxt = redo.pop()
    undo = list(doc.get("_undoStack") or [])
    undo.append({"version": doc.get("version"), "lines": doc.get("lines"), "name": doc.get("name"), "customer": doc.get("customer")})
    doc["lines"] = nxt.get("lines") or []
    if nxt.get("name") is not None:
        doc["name"] = nxt["name"]
    if nxt.get("customer") is not None:
        doc["customer"] = nxt["customer"]
    doc["_undoStack"] = undo[-20:]
    doc["_redoStack"] = redo
    return save_project(doc, bump_version=True, action="redo")


def empty_project(*, name: str = "Untitled Project", customer: str = "") -> dict[str, Any]:
    return {
        "projectId": new_project_id(),
        "name": name,
        "customer": customer,
        "status": "draft",
        "lines": [],
        "version": 0,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "_undoStack": [],
        "_redoStack": [],
    }


def dashboard_stats() -> dict[str, Any]:
    projects = list_projects(include_archived=False)
    archived = list_projects(status="archived", include_archived=True)
    active = [p for p in projects if p.get("status") == "active"]
    drafts = [p for p in projects if p.get("status") == "draft"]
    with_quote = [p for p in projects if p.get("quotationId")]
    today = datetime.now(timezone.utc).date().isoformat()
    todays = [p for p in projects if str(p.get("updatedAt", "")).startswith(today)]
    material = 0.0
    for p in projects[:50]:
        try:
            doc = load_project(p["projectId"])
            material += float((((doc.get("lastCalculation") or {}).get("combined") or {}).get("weight") or {}).get("aluminiumKg") or 0)
        except Exception:
            pass
    return {
        "activeProjects": len(active),
        "draftQuotations": len(drafts) + len([p for p in with_quote if p.get("status") == "draft"]),
        "todaysOrders": len(todays),
        "materialRequiredKg": round(material, 2),
        "productionStatus": {"queued": len(with_quote), "archived": len(archived)},
        "recentProjects": projects[:8],
    }
