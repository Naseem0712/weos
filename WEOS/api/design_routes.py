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


# ── Batch 6 — Assembly / Element / Connection / scene read model ─────────────


class AssemblyCreateBody(BaseModel):
    name: str = ""
    displayCode: str | None = None
    locationId: str | None = None
    bounds: dict[str, Any] | None = None
    sortOrder: int = 0
    status: str = "draft"


class ElementCreateBody(BaseModel):
    productType: str
    widthMm: float
    heightMm: float
    xMm: float = 0.0
    yMm: float = 0.0
    displayCode: str | None = None
    productId: str | None = None
    orientation: str | None = None
    sillHeightMm: float | None = None
    parentElementId: str | None = None
    quantity: int = 1
    geometryPayload: dict[str, Any] | None = None
    configPayload: dict[str, Any] | None = None
    status: str = "draft"


class ConnectionCreateBody(BaseModel):
    elementAId: str
    elementBId: str
    connectionType: str
    sideA: str | None = None
    sideB: str | None = None
    parameters: dict[str, Any] | None = None


class CartLineAdaptBody(BaseModel):
    model_config = {"extra": "allow"}

    line: dict[str, Any]
    xMm: float = 0.0
    yMm: float = 0.0


@router.get("/api/design-documents/{design_document_id}/scene")
def api_get_design_scene(
    design_document_id: str, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds

    g = require_company_gst(request, gst)
    try:
        return ds.build_scene_read_model(design_document_id, company_gst=g)
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/design-documents/{design_document_id}/assemblies")
def api_list_assemblies(
    design_document_id: str, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds

    g = require_company_gst(request, gst)
    try:
        return {
            "assemblies": ds.list_assemblies(design_document_id, company_gst=g),
            "designDocumentId": design_document_id,
        }
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/design-documents/{design_document_id}/assemblies")
def api_create_assembly(
    design_document_id: str,
    body: AssemblyCreateBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds

    g = require_company_gst(request, gst)
    try:
        return ds.create_assembly(
            design_document_id=design_document_id,
            company_gst=g,
            name=body.name,
            display_code=body.displayCode,
            location_id=body.locationId,
            bounds=body.bounds,
            sort_order=body.sortOrder,
            status=body.status,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/assemblies/{assembly_id}/elements")
def api_create_element(
    assembly_id: str,
    body: ElementCreateBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds

    g = require_company_gst(request, gst)
    try:
        return ds.create_element(
            assembly_id=assembly_id,
            company_gst=g,
            product_type=body.productType,
            width_mm=body.widthMm,
            height_mm=body.heightMm,
            x_mm=body.xMm,
            y_mm=body.yMm,
            display_code=body.displayCode,
            product_id=body.productId,
            orientation=body.orientation,
            sill_height_mm=body.sillHeightMm,
            parent_element_id=body.parentElementId,
            quantity=body.quantity,
            geometry_payload=body.geometryPayload,
            config_payload=body.configPayload,
            status=body.status,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/assemblies/{assembly_id}/connections")
def api_create_connection(
    assembly_id: str,
    body: ConnectionCreateBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds

    g = require_company_gst(request, gst)
    try:
        return ds.create_connection(
            assembly_id=assembly_id,
            company_gst=g,
            element_a_id=body.elementAId,
            element_b_id=body.elementBId,
            connection_type=body.connectionType,
            side_a=body.sideA,
            side_b=body.sideB,
            parameters=body.parameters,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/design-documents/{design_document_id}/adapt-cart-line")
def api_adapt_cart_line(
    design_document_id: str,
    body: CartLineAdaptBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds

    g = require_company_gst(request, gst)
    try:
        return ds.adapt_cart_line_to_assembly_element(
            design_document_id=design_document_id,
            company_gst=g,
            line=body.line,
            x_mm=body.xMm,
            y_mm=body.yMm,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/projects/{project_id}/design/migrate-scene")
def api_migrate_cart_lines_to_scene(
    project_id: str, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_owned_project
    from WEOS.factory import design_scene as ds

    g, _ = require_owned_project(request, project_id, gst)
    try:
        return ds.migrate_cart_lines_to_scene(company_gst=g, project_id=project_id)
    except Exception as exc:
        raise _map_err(exc) from exc


# ── Batch 7 — Universal Canvas Host ──────────────────────────────────────────


class ElementPoseBody(BaseModel):
    xMm: float | None = None
    yMm: float | None = None


@router.get("/api/flags")
def api_feature_flags() -> dict[str, Any]:
    """Public feature flags — Universal Canvas defaults OFF for rollback."""
    from WEOS.factory import universal_canvas as uc

    return {
        "WEOS_UNIVERSAL_CANVAS": uc.is_universal_canvas_enabled(),
        "universalCanvas": uc.is_universal_canvas_enabled(),
        "elementDragEnabled": uc.ELEMENT_DRAG_ENABLED,
    }


@router.get("/api/design-documents/{design_document_id}/canvas")
def api_get_canvas_view(
    design_document_id: str,
    request: Request,
    gst: str | None = None,
    floorId: str | None = None,
    locationId: str | None = None,
    selectedElementId: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds
    from WEOS.factory import universal_canvas as uc

    g = require_company_gst(request, gst)
    try:
        scene = ds.build_scene_read_model(design_document_id, company_gst=g)
        sel = [selectedElementId] if selectedElementId else None
        return uc.build_canvas_view_model(
            scene,
            floor_id=floorId,
            location_id=locationId,
            selected_element_ids=sel,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.patch("/api/elements/{element_id}/pose")
def api_patch_element_pose(
    element_id: str,
    body: ElementPoseBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    """Durable x/y pose only — does not mutate engineering width/height."""
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import universal_canvas as uc

    g = require_company_gst(request, gst)
    if body.xMm is None and body.yMm is None:
        raise HTTPException(status_code=400, detail="xMm or yMm required")
    try:
        return uc.update_element_pose(
            element_id, company_gst=g, x_mm=body.xMm, y_mm=body.yMm
        )
    except Exception as exc:
        raise _map_err(exc) from exc


# ── Batch 8 — Product Plugin Adapters ─────────────────────────────────────────


class ElementUpdateBody(BaseModel):
    widthMm: float | None = None
    heightMm: float | None = None
    xMm: float | None = None
    yMm: float | None = None
    orientation: str | None = None
    sillHeightMm: float | None = None
    geometryPayload: dict[str, Any] | None = None
    configPayload: dict[str, Any] | None = None
    mergeConfig: bool = True
    status: str | None = None


class AssemblyUpdateBody(BaseModel):
    name: str | None = None
    locationId: str | None = None
    bounds: dict[str, Any] | None = None
    status: str | None = None


@router.get("/api/adapters")
def api_list_adapters() -> dict[str, Any]:
    from WEOS.factory import product_adapters as pa

    reg = pa.DEFAULT_PRODUCT_REGISTRY
    return {
        "host": "UniversalCanvas",
        "adapters": reg.registered_product_types(),
        "contract": [
            "supports",
            "loadConfiguration",
            "renderPreview",
            "validate",
            "getPropertySchema",
            "updateConfiguration",
            "calculate",
        ],
    }


@router.get("/api/adapters/{product_type}/schema")
def api_adapter_schema(product_type: str) -> dict[str, Any]:
    from WEOS.factory import product_adapters as pa

    pt = str(product_type or "").strip().upper()
    if pt == "WINDOW":
        raise HTTPException(
            status_code=400,
            detail="product type must not collapse to WINDOW — use SLIDING_WINDOW / CASEMENT_WINDOW / …",
        )
    return pa.property_schema_for(pt)


@router.post("/api/adapters/{product_type}/preview")
def api_adapter_preview(product_type: str, body: dict[str, Any]) -> dict[str, Any]:
    """Stateless adapter preview — element geometry + config → engine SVG."""
    from WEOS.factory import product_adapters as pa

    pt = str(product_type or "").strip().upper()
    if pt == "WINDOW":
        raise HTTPException(
            status_code=400,
            detail="product type must not collapse to WINDOW",
        )
    el = dict(body or {})
    el["productType"] = pt
    cfg = el.pop("config", None) or el.get("configPayload")
    return pa.render_element_preview(el, cfg if isinstance(cfg, dict) else None)


@router.get("/api/elements/{element_id}")
def api_get_element(
    element_id: str,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds

    g = require_company_gst(request, gst)
    row = ds.get_element(element_id, company_gst=g)
    if not row:
        raise HTTPException(status_code=404, detail="element not found")
    return row


@router.patch("/api/elements/{element_id}")
def api_patch_element(
    element_id: str,
    body: ElementUpdateBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    """Durable geometry and/or ProductConfiguration update (SQL SoT)."""
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds
    from WEOS.factory import product_adapters as pa

    g = require_company_gst(request, gst)
    try:
        existing = ds.get_element(element_id, company_gst=g)
        if not existing:
            raise PermissionError("element not found for company")
        cfg_patch = body.configPayload
        if cfg_patch is not None:
            ad = pa.resolve_adapter(existing.get("productType") or "")
            cfg_patch = ad.update_configuration(existing, cfg_patch)
        updated = ds.update_element(
            element_id,
            company_gst=g,
            width_mm=body.widthMm,
            height_mm=body.heightMm,
            x_mm=body.xMm,
            y_mm=body.yMm,
            orientation=body.orientation,
            sill_height_mm=body.sillHeightMm,
            geometry_payload=body.geometryPayload,
            config_payload=cfg_patch,
            merge_config=bool(body.mergeConfig),
            status=body.status,
        )
        return {"ok": True, "persisted": True, "element": updated}
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/elements/{element_id}/preview")
def api_element_preview(
    element_id: str,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds
    from WEOS.factory import product_adapters as pa

    g = require_company_gst(request, gst)
    el = ds.get_element(element_id, company_gst=g)
    if not el:
        raise HTTPException(status_code=404, detail="element not found")
    return pa.render_element_preview(el)


@router.post("/api/elements/{element_id}/calculate")
def api_element_calculate(
    element_id: str,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds
    from WEOS.factory import product_adapters as pa

    g = require_company_gst(request, gst)
    el = ds.get_element(element_id, company_gst=g)
    if not el:
        raise HTTPException(status_code=404, detail="element not found")
    ad = pa.resolve_adapter(el.get("productType") or "")
    cfg = ad.load_configuration(el)
    out = ad.calculate(el, cfg)
    return {"ok": out is not None, "adapterId": ad.adapter_id, "productType": el.get("productType"), "result": out}


@router.get("/api/elements/{element_id}/property-schema")
def api_element_property_schema(
    element_id: str,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds
    from WEOS.factory import product_adapters as pa

    g = require_company_gst(request, gst)
    el = ds.get_element(element_id, company_gst=g)
    if not el:
        raise HTTPException(status_code=404, detail="element not found")
    schema = pa.property_schema_for(el.get("productType") or "")
    schema["elementId"] = el.get("elementId")
    schema["assemblyId"] = el.get("assemblyId")
    return schema


@router.patch("/api/assemblies/{assembly_id}")
def api_patch_assembly(
    assembly_id: str,
    body: AssemblyUpdateBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import design_scene as ds

    g = require_company_gst(request, gst)
    try:
        updated = ds.update_assembly(
            assembly_id,
            company_gst=g,
            name=body.name,
            location_id=body.locationId,
            bounds=body.bounds,
            status=body.status,
        )
        return {"ok": True, "persisted": True, "assembly": updated}
    except Exception as exc:
        raise _map_err(exc) from exc
