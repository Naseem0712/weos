"""Thin FastAPI routes for Floor / Location / DesignDocument (Batch 5+)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["design-hierarchy"])


class FloorCreateBody(BaseModel):
    name: str
    code: str | None = None
    levelIndex: int = 0
    elevationMm: float | None = None
    status: str = "active"
    meta: dict[str, Any] | None = None


class FloorUpdateBody(BaseModel):
    name: str | None = None
    code: str | None = None
    levelIndex: int | None = None
    elevationMm: float | None = None
    status: str | None = None
    meta: dict[str, Any] | None = None


class LocationCreateBody(BaseModel):
    name: str
    code: str | None = None
    notes: str | None = None
    sortOrder: int = 0
    status: str = "active"


class LocationUpdateBody(BaseModel):
    name: str | None = None
    code: str | None = None
    notes: str | None = None
    sortOrder: int | None = None
    status: str | None = None


class DesignDocumentCreateBody(BaseModel):
    name: str = "Main Design"
    status: str = "draft"
    payload: dict[str, Any] | None = None


class DesignDocumentUpdateBody(BaseModel):
    name: str | None = None
    status: str | None = None
    payload: dict[str, Any] | None = None


class GeometryRevisionCreateBody(BaseModel):
    payload: dict[str, Any] | None = None
    label: str | None = None


def _map_err(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/api/projects/{project_id}/floors")
def api_list_floors(project_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_owned_project
    from WEOS.factory import design_hierarchy as dh

    g, _ = require_owned_project(request, project_id, gst)
    try:
        floors = dh.list_floors(project_id, company_gst=g)
    except Exception as exc:
        raise _map_err(exc) from exc
    return {"floors": floors, "projectId": project_id}


@router.post("/api/projects/{project_id}/floors")
def api_create_floor(
    project_id: str, body: FloorCreateBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_owned_project
    from WEOS.factory import design_hierarchy as dh

    g, _ = require_owned_project(request, project_id, gst)
    try:
        return dh.create_floor(
            project_id=project_id,
            company_gst=g,
            name=body.name,
            code=body.code,
            level_index=body.levelIndex,
            elevation_mm=body.elevationMm,
            status=body.status,
            meta=body.meta,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.patch("/api/floors/{floor_id}")
def api_update_floor(
    floor_id: str, body: FloorUpdateBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_hierarchy as dh

    g = require_company_gst(request, gst)
    try:
        return dh.update_floor(
            floor_id,
            company_gst=g,
            name=body.name,
            code=body.code,
            level_index=body.levelIndex,
            elevation_mm=body.elevationMm,
            status=body.status,
            meta=body.meta,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/floors/{floor_id}/locations")
def api_list_floor_locations(
    floor_id: str, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_hierarchy as dh

    g = require_company_gst(request, gst)
    try:
        locs = dh.list_locations(floor_id=floor_id, company_gst=g)
    except Exception as exc:
        raise _map_err(exc) from exc
    return {"locations": locs, "floorId": floor_id}


@router.post("/api/floors/{floor_id}/locations")
def api_create_location(
    floor_id: str, body: LocationCreateBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_hierarchy as dh

    g = require_company_gst(request, gst)
    try:
        return dh.create_location(
            floor_id=floor_id,
            company_gst=g,
            name=body.name,
            code=body.code,
            notes=body.notes,
            sort_order=body.sortOrder,
            status=body.status,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.patch("/api/locations/{location_id}")
def api_update_location(
    location_id: str, body: LocationUpdateBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_hierarchy as dh

    g = require_company_gst(request, gst)
    try:
        return dh.update_location(
            location_id,
            company_gst=g,
            name=body.name,
            code=body.code,
            notes=body.notes,
            sort_order=body.sortOrder,
            status=body.status,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/projects/{project_id}/design-documents")
def api_list_design_documents(
    project_id: str, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_owned_project
    from WEOS.factory import design_hierarchy as dh

    g, _ = require_owned_project(request, project_id, gst)
    try:
        docs = dh.list_design_documents(project_id, company_gst=g)
    except Exception as exc:
        raise _map_err(exc) from exc
    return {"designDocuments": docs, "projectId": project_id}


@router.post("/api/projects/{project_id}/design-documents")
def api_create_design_document(
    project_id: str,
    body: DesignDocumentCreateBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_owned_project
    from WEOS.factory import design_hierarchy as dh

    g, _ = require_owned_project(request, project_id, gst)
    try:
        return dh.create_design_document(
            project_id=project_id,
            company_gst=g,
            name=body.name,
            status=body.status,
            payload=body.payload,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/design-documents/{design_document_id}")
def api_get_design_document(
    design_document_id: str, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_hierarchy as dh

    g = require_company_gst(request, gst)
    doc = dh.get_design_document(design_document_id, company_gst=g)
    if doc is None:
        raise HTTPException(status_code=404, detail="design document not found")
    return doc


@router.patch("/api/design-documents/{design_document_id}")
def api_update_design_document(
    design_document_id: str,
    body: DesignDocumentUpdateBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_hierarchy as dh

    g = require_company_gst(request, gst)
    try:
        return dh.update_design_document_draft(
            design_document_id,
            company_gst=g,
            name=body.name,
            status=body.status,
            payload=body.payload,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/design-documents/{design_document_id}/revisions")
def api_create_geometry_revision(
    design_document_id: str,
    body: GeometryRevisionCreateBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_hierarchy as dh

    g = require_company_gst(request, gst)
    try:
        return dh.create_geometry_revision(
            design_document_id,
            company_gst=g,
            payload=body.payload,
            label=body.label,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/projects/{project_id}/design/migrate-legacy")
def api_migrate_legacy_locations(
    project_id: str, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_owned_project
    from WEOS.factory import design_hierarchy as dh

    g, _ = require_owned_project(request, project_id, gst)
    try:
        return dh.migrate_legacy_locations(company_gst=g, project_id=project_id)
    except Exception as exc:
        raise _map_err(exc) from exc
