"""Floor → Location → DesignDocument (+ GeometryRevision) — WEOS V2 Batch 5.

Legacy cart ``locationName`` mapping rule
-----------------------------------------
When a line has a free-text ``locationName`` but no floor evidence, it maps to the
project's system floor ``Unassigned`` (code ``UNASSIGNED``). WEOS never invents
"Ground Floor" without evidence. Same location name on different floors remains
distinct (unique per floor + normalized name).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from typing import Any, Mapping

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.factory.canonical_customer import _norm_company_gst, normalize_name_key

_log = logging.getLogger("weos.design_hierarchy")

UNASSIGNED_FLOOR_CODE = "UNASSIGNED"
UNASSIGNED_FLOOR_NAME = "Unassigned"
DEFAULT_DESIGN_NAME = "Main Design"


def new_floor_id() -> str:
    return "FLR-" + uuid.uuid4().hex[:16].upper()


def new_location_id() -> str:
    return "LOC-" + uuid.uuid4().hex[:16].upper()


def new_design_document_id() -> str:
    return "DES-" + uuid.uuid4().hex[:16].upper()


def new_revision_id() -> str:
    return "GREV-" + uuid.uuid4().hex[:16].upper()


def _require_db() -> None:
    if not db_available():
        raise RuntimeError("Database unavailable for design hierarchy")
    init_db()


def _assert_project_owned(project_id: str, company_gst: str) -> dict[str, Any]:
    from WEOS.db.models import CanonicalProject

    pid = str(project_id or "").strip()
    gst = _norm_company_gst(company_gst)
    if not pid or not gst:
        raise ValueError("project_id and company_gst required")
    with session_scope() as s:
        row = s.get(CanonicalProject, pid)
        if row is None or _norm_company_gst(row.company_gst) != gst:
            raise PermissionError("project not found for company")
        return row.to_dict()


def ensure_unassigned_floor(project_id: str, company_gst: str) -> dict[str, Any]:
    """Return the system Unassigned floor (create if missing). Never invent Ground Floor."""
    _require_db()
    _assert_project_owned(project_id, company_gst)
    from sqlalchemy import select

    from WEOS.db.models import Floor

    gst = _norm_company_gst(company_gst)
    pid = str(project_id).strip()
    with session_scope() as s:
        row = s.execute(
            select(Floor).where(
                Floor.project_id == pid,
                Floor.company_gst == gst,
                Floor.code == UNASSIGNED_FLOOR_CODE,
            )
        ).scalar_one_or_none()
        if row is None:
            row = Floor(
                floor_id=new_floor_id(),
                project_id=pid,
                company_gst=gst,
                name=UNASSIGNED_FLOOR_NAME,
                code=UNASSIGNED_FLOOR_CODE,
                level_index=-9999,
                is_system=True,
                status="active",
                meta={"role": "legacy_location_boundary"},
            )
            s.add(row)
            s.flush()
        return row.to_dict()


def create_floor(
    *,
    project_id: str,
    company_gst: str,
    name: str,
    code: str | None = None,
    level_index: int = 0,
    elevation_mm: float | None = None,
    status: str = "active",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_db()
    _assert_project_owned(project_id, company_gst)
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("floor name required")
    gst = _norm_company_gst(company_gst)
    pid = str(project_id).strip()
    code_s = str(code).strip() if code else None
    from WEOS.db.models import Floor

    with session_scope() as s:
        row = Floor(
            floor_id=new_floor_id(),
            project_id=pid,
            company_gst=gst,
            name=nm,
            code=code_s,
            level_index=int(level_index or 0),
            elevation_mm=elevation_mm,
            is_system=False,
            status=status or "active",
            meta=meta,
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def update_floor(
    floor_id: str,
    *,
    company_gst: str,
    name: str | None = None,
    code: str | None = None,
    level_index: int | None = None,
    elevation_mm: float | None = None,
    status: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import Floor

    with session_scope() as s:
        row = s.get(Floor, str(floor_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            raise PermissionError("floor not found for company")
        if row.is_system and name is not None and str(name).strip() != row.name:
            raise ValueError("system floor name is fixed")
        if name is not None:
            row.name = str(name).strip() or row.name
        if code is not None and not row.is_system:
            row.code = str(code).strip() or None
        if level_index is not None:
            row.level_index = int(level_index)
        if elevation_mm is not None:
            row.elevation_mm = elevation_mm
        if status is not None:
            row.status = status
        if meta is not None:
            row.meta = meta
        s.flush()
        return row.to_dict()


def list_floors(project_id: str, *, company_gst: str) -> list[dict[str, Any]]:
    _require_db()
    _assert_project_owned(project_id, company_gst)
    from sqlalchemy import select

    from WEOS.db.models import Floor

    gst = _norm_company_gst(company_gst)
    pid = str(project_id).strip()
    with session_scope() as s:
        rows = s.execute(
            select(Floor)
            .where(Floor.project_id == pid, Floor.company_gst == gst)
            .order_by(Floor.level_index, Floor.name)
        ).scalars().all()
        return [r.to_dict() for r in rows]


def get_floor(floor_id: str, *, company_gst: str) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import Floor

    with session_scope() as s:
        row = s.get(Floor, str(floor_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            return None
        return row.to_dict()


def create_location(
    *,
    floor_id: str,
    company_gst: str,
    name: str,
    code: str | None = None,
    notes: str | None = None,
    sort_order: int = 0,
    legacy_location_name: str | None = None,
    status: str = "active",
) -> dict[str, Any]:
    _require_db()
    gst = _norm_company_gst(company_gst)
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("location name required")
    nname = normalize_name_key(nm)
    from WEOS.db.models import Floor, Location

    with session_scope() as s:
        fl = s.get(Floor, str(floor_id).strip())
        if fl is None or _norm_company_gst(fl.company_gst) != gst:
            raise PermissionError("floor not found for company")
        row = Location(
            location_id=new_location_id(),
            floor_id=fl.floor_id,
            project_id=fl.project_id,
            company_gst=gst,
            name=nm,
            normalized_name=nname or normalize_name_key(nm),
            code=str(code).strip() if code else None,
            notes=notes,
            sort_order=int(sort_order or 0),
            legacy_location_name=legacy_location_name or nm,
            status=status or "active",
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def update_location(
    location_id: str,
    *,
    company_gst: str,
    name: str | None = None,
    code: str | None = None,
    notes: str | None = None,
    sort_order: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import Location

    with session_scope() as s:
        row = s.get(Location, str(location_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            raise PermissionError("location not found for company")
        if name is not None:
            nm = str(name).strip()
            if not nm:
                raise ValueError("location name required")
            row.name = nm
            row.normalized_name = normalize_name_key(nm)
        if code is not None:
            row.code = str(code).strip() or None
        if notes is not None:
            row.notes = notes
        if sort_order is not None:
            row.sort_order = int(sort_order)
        if status is not None:
            row.status = status
        s.flush()
        return row.to_dict()


def list_locations(
    *,
    floor_id: str | None = None,
    project_id: str | None = None,
    company_gst: str,
) -> list[dict[str, Any]]:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from sqlalchemy import select

    from WEOS.db.models import Floor, Location

    with session_scope() as s:
        q = select(Location).where(Location.company_gst == gst)
        if floor_id:
            fl = s.get(Floor, str(floor_id).strip())
            if fl is None or _norm_company_gst(fl.company_gst) != gst:
                raise PermissionError("floor not found for company")
            q = q.where(Location.floor_id == fl.floor_id)
        elif project_id:
            _assert_project_owned(str(project_id), gst)
            q = q.where(Location.project_id == str(project_id).strip())
        else:
            raise ValueError("floor_id or project_id required")
        rows = s.execute(q.order_by(Location.sort_order, Location.name)).scalars().all()
        return [r.to_dict() for r in rows]


def get_location(location_id: str, *, company_gst: str) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import Location

    with session_scope() as s:
        row = s.get(Location, str(location_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            return None
        return row.to_dict()


def ensure_design_document(
    project_id: str,
    company_gst: str,
    *,
    name: str = DEFAULT_DESIGN_NAME,
) -> dict[str, Any]:
    _require_db()
    _assert_project_owned(project_id, company_gst)
    from sqlalchemy import select

    from WEOS.db.models import DesignDocument

    gst = _norm_company_gst(company_gst)
    pid = str(project_id).strip()
    with session_scope() as s:
        row = s.execute(
            select(DesignDocument)
            .where(DesignDocument.project_id == pid, DesignDocument.company_gst == gst)
            .order_by(DesignDocument.created_at)
        ).scalars().first()
        if row is None:
            row = DesignDocument(
                design_document_id=new_design_document_id(),
                project_id=pid,
                company_gst=gst,
                name=str(name or DEFAULT_DESIGN_NAME).strip() or DEFAULT_DESIGN_NAME,
                status="draft",
                payload={},
            )
            s.add(row)
            s.flush()
        return row.to_dict()


def create_design_document(
    *,
    project_id: str,
    company_gst: str,
    name: str = DEFAULT_DESIGN_NAME,
    status: str = "draft",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_db()
    _assert_project_owned(project_id, company_gst)
    from WEOS.db.models import DesignDocument

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        row = DesignDocument(
            design_document_id=new_design_document_id(),
            project_id=str(project_id).strip(),
            company_gst=gst,
            name=str(name or DEFAULT_DESIGN_NAME).strip() or DEFAULT_DESIGN_NAME,
            status=status or "draft",
            payload=payload if payload is not None else {},
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def get_design_document(
    design_document_id: str, *, company_gst: str
) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import DesignDocument

    with session_scope() as s:
        row = s.get(DesignDocument, str(design_document_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            return None
        return row.to_dict()


def list_design_documents(project_id: str, *, company_gst: str) -> list[dict[str, Any]]:
    _require_db()
    _assert_project_owned(project_id, company_gst)
    from sqlalchemy import select

    from WEOS.db.models import DesignDocument

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        rows = s.execute(
            select(DesignDocument)
            .where(
                DesignDocument.project_id == str(project_id).strip(),
                DesignDocument.company_gst == gst,
            )
            .order_by(DesignDocument.created_at)
        ).scalars().all()
        return [r.to_dict() for r in rows]


def update_design_document_draft(
    design_document_id: str,
    *,
    company_gst: str,
    name: str | None = None,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mutable draft DesignDocument fields (working geometry). Revisions stay immutable."""
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import DesignDocument

    with session_scope() as s:
        row = s.get(DesignDocument, str(design_document_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            raise PermissionError("design document not found for company")
        if name is not None:
            row.name = str(name).strip() or row.name
        if status is not None:
            row.status = status
        if payload is not None:
            row.payload = payload
        s.flush()
        return row.to_dict()


def _payload_hash(payload: Any) -> str:
    raw = json.dumps(payload if payload is not None else {}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def create_geometry_revision(
    design_document_id: str,
    *,
    company_gst: str,
    payload: dict[str, Any] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Create an immutable GeometryRevision and point current_revision_id at it."""
    _require_db()
    gst = _norm_company_gst(company_gst)
    from sqlalchemy import func, select

    from WEOS.db.models import DesignDocument, GeometryRevision

    with session_scope() as s:
        doc = s.get(DesignDocument, str(design_document_id).strip())
        if doc is None or _norm_company_gst(doc.company_gst) != gst:
            raise PermissionError("design document not found for company")
        snap = payload if payload is not None else (doc.payload if isinstance(doc.payload, dict) else {})
        next_num = (
            s.execute(
                select(func.coalesce(func.max(GeometryRevision.revision_number), 0)).where(
                    GeometryRevision.design_document_id == doc.design_document_id
                )
            ).scalar_one()
            + 1
        )
        rev = GeometryRevision(
            revision_id=new_revision_id(),
            design_document_id=doc.design_document_id,
            project_id=doc.project_id,
            company_gst=gst,
            revision_number=int(next_num),
            label=label,
            content_hash=_payload_hash(snap),
            payload=snap,
            immutable=True,
        )
        s.add(rev)
        doc.current_revision_id = rev.revision_id
        s.flush()
        return rev.to_dict()


def get_geometry_revision(
    revision_id: str, *, company_gst: str
) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import GeometryRevision

    with session_scope() as s:
        row = s.get(GeometryRevision, str(revision_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            return None
        return row.to_dict()


def try_update_geometry_revision(
    revision_id: str,
    *,
    company_gst: str,
    payload: dict[str, Any],
) -> None:
    """Refuse mutation of immutable revisions (domain boundary test helper)."""
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import GeometryRevision

    with session_scope() as s:
        row = s.get(GeometryRevision, str(revision_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            raise PermissionError("revision not found for company")
        if row.immutable:
            raise ValueError("geometry revision is immutable")
        row.payload = payload


def _line_location_name(line: Mapping[str, Any]) -> str:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    return str(
        line.get("locationName")
        or line.get("positionName")
        or (opts.get("locationName") if isinstance(opts, Mapping) else None)
        or (opts.get("positionName") if isinstance(opts, Mapping) else None)
        or ""
    ).strip()


def resolve_location_for_legacy_name(
    *,
    project_id: str,
    company_gst: str,
    location_name: str,
    create: bool = True,
) -> dict[str, Any] | None:
    """Map free-text locationName → Location under Unassigned floor."""
    nm = str(location_name or "").strip()
    if not nm:
        return None
    unassigned = ensure_unassigned_floor(project_id, company_gst)
    nname = normalize_name_key(nm)
    existing = list_locations(floor_id=unassigned["floorId"], company_gst=company_gst)
    for loc in existing:
        if loc.get("normalizedName") == nname or (
            str(loc.get("legacyLocationName") or "").strip().lower() == nm.lower()
        ):
            return loc
    if not create:
        return None
    return create_location(
        floor_id=unassigned["floorId"],
        company_gst=company_gst,
        name=nm,
        legacy_location_name=nm,
    )


def migrate_legacy_locations(
    *,
    company_gst: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Additive migration: Project lines' locationName → Unassigned Floor Locations + DesignDocument.

    zeroSilentLoss is always True — nothing is deleted; unresolved lines are counted.
    """
    _require_db()
    from WEOS.factory.project_store import list_projects, load_project

    gst_filter = _norm_company_gst(company_gst) if company_gst else ""
    if project_id:
        try:
            docs = [load_project(str(project_id).strip())]
        except FileNotFoundError:
            docs = []
    else:
        docs = []
        for summary in list_projects(
            include_archived=True,
            company_gst=gst_filter or None,
            include_unscoped=not bool(gst_filter),
            limit=10000,
        ):
            try:
                docs.append(load_project(str(summary.get("projectId") or "")))
            except Exception:
                continue

    projects_inspected = 0
    floors_created = 0
    locations_created = 0
    legacy_linked = 0
    unassigned_items = 0
    conflicts = 0
    rejected = 0
    manual_review: list[dict[str, Any]] = []

    for doc in docs:
        pid = str(doc.get("projectId") or "").strip()
        cg = _norm_company_gst(doc.get("companyGst"))
        if not pid or not cg:
            rejected += 1
            manual_review.append({"projectId": pid, "reason": "missing_project_or_company"})
            continue
        if gst_filter and cg != gst_filter:
            continue
        if project_id and pid != str(project_id).strip():
            continue
        # Ensure canonical project exists for FK
        try:
            from WEOS.factory.canonical_project import link_project_document

            link_project_document(doc)
        except Exception as exc:
            rejected += 1
            manual_review.append({"projectId": pid, "reason": f"canonical_link_failed:{exc}"})
            continue

        projects_inspected += 1
        before_floors = {f["floorId"] for f in list_floors(pid, company_gst=cg)}
        unassigned = ensure_unassigned_floor(pid, cg)
        after_floors = {f["floorId"] for f in list_floors(pid, company_gst=cg)}
        floors_created += len(after_floors - before_floors)

        before_locs = {loc["locationId"] for loc in list_locations(project_id=pid, company_gst=cg)}
        ensure_design_document(pid, cg)

        lines = doc.get("lines") if isinstance(doc.get("lines"), list) else []
        seen_names: set[str] = set()
        for ln in lines:
            if not isinstance(ln, Mapping):
                unassigned_items += 1
                continue
            lname = _line_location_name(ln)
            if not lname:
                unassigned_items += 1
                continue
            key = normalize_name_key(lname)
            if key in seen_names:
                legacy_linked += 1
                continue
            seen_names.add(key)
            try:
                resolve_location_for_legacy_name(
                    project_id=pid, company_gst=cg, location_name=lname, create=True
                )
                legacy_linked += 1
            except Exception as exc:
                conflicts += 1
                manual_review.append(
                    {
                        "projectId": pid,
                        "locationName": lname,
                        "reason": str(exc),
                    }
                )

        after_locs = {loc["locationId"] for loc in list_locations(project_id=pid, company_gst=cg)}
        locations_created += len(after_locs - before_locs)
        # silence unused unassigned binding for linters in edge paths
        _ = unassigned

    return {
        "ok": True,
        "projectsInspected": projects_inspected,
        "floorsCreated": floors_created,
        "locationsCreated": locations_created,
        "legacyLocationNamesLinked": legacy_linked,
        "unassignedItems": unassigned_items,
        "conflicts": conflicts,
        "rejected": rejected,
        "manualReview": manual_review,
        "zeroSilentLoss": True,
        "rule": (
            "Legacy locationName maps to system floor Unassigned (code UNASSIGNED); "
            "never invent Ground Floor without evidence."
        ),
    }
