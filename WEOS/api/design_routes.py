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
    """Public feature flags — Universal Canvas defaults ON (D1); env/query can disable."""
    from WEOS.factory import universal_canvas as uc
    from WEOS.factory import canvas_activation as ca

    enabled = uc.is_universal_canvas_enabled()
    return {
        "WEOS_UNIVERSAL_CANVAS": enabled,
        "universalCanvas": enabled,
        "elementDragEnabled": uc.ELEMENT_DRAG_ENABLED,
        "universalCanvasDefault": "on",
        "universalCanvasFallback": ca.activation_docs()["legacyFallback"],
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


class DesignContextBody(BaseModel):
    productType: str | None = None
    elementId: str | None = None
    assemblyId: str | None = None
    configPayload: dict[str, Any] | None = None
    source: str | None = "switch"
    previous: dict[str, Any] | None = None


@router.get("/api/design-context")
def api_get_design_context(
    productType: str | None = None,
    elementId: str | None = None,
    assemblyId: str | None = None,
) -> dict[str, Any]:
    """ActiveDesignContext snapshot — product_type → adapter → schema → toolset."""
    from WEOS.factory import design_context as dc

    return dc.resolve_active_design_context(
        product_type=productType,
        element_id=elementId,
        assembly_id=assemblyId,
        source="api",
    )


@router.post("/api/design-context/switch")
def api_switch_design_context(body: DesignContextBody) -> dict[str, Any]:
    """Atomic product switch — bumps renderRevision; clears prior toolset/schema."""
    from WEOS.factory import design_context as dc

    return dc.switch_product_context(
        body.previous,
        product_type=body.productType,
        element_id=body.elementId,
        assembly_id=body.assemblyId,
        config_payload=body.configPayload,
        source=body.source or "switch",
    )


@router.post("/api/adapters/{product_type}/preview")
def api_adapter_preview(product_type: str, body: dict[str, Any]) -> dict[str, Any]:
    """Stateless adapter preview — element geometry + config → engine SVG.

    When renderPurpose/purpose is CANVAS_RENDER, strip artificial white page
    backgrounds. PDF/PRINT callers omit that flag and keep paper white.
    """
    from WEOS.factory import product_adapters as pa
    from WEOS.factory.canvas_preview import normalize_for_canvas

    pt = str(product_type or "").strip().upper()
    if pt == "WINDOW":
        raise HTTPException(
            status_code=400,
            detail="product type must not collapse to WINDOW",
        )
    el = dict(body or {})
    purpose = str(el.pop("renderPurpose", None) or el.pop("purpose", None) or "").strip().upper()
    el["productType"] = pt
    cfg = el.pop("config", None) or el.get("configPayload")
    out = pa.render_element_preview(el, cfg if isinstance(cfg, dict) else None)
    if purpose in ("CANVAS_RENDER", "CANVAS") and isinstance(out, dict) and out.get("svg"):
        out = dict(out)
        out["svg"] = normalize_for_canvas(out.get("svg"))
        out["canvasNormalized"] = True
    return out


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


# ── Batch 9 — Contextual Property Panel ───────────────────────────────────────


class PropertyUpdateBody(BaseModel):
    """Mixed patch — server splits geometry vs configPayload."""

    widthMm: float | None = None
    heightMm: float | None = None
    xMm: float | None = None
    yMm: float | None = None
    orientation: str | None = None
    sillHeightMm: float | None = None
    config: dict[str, Any] | None = None
    # Flat keys also accepted (panel form posts)
    extras: dict[str, Any] | None = None


@router.get("/api/property-panel")
def api_property_panel(
    request: Request,
    kind: str = "none",
    id: str | None = None,
    gst: str | None = None,
) -> dict[str, Any]:
    """ONE contextual panel payload keyed by stable IDs — not DOM/row index."""
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import contextual_properties as cp
    from WEOS.factory import design_scene as ds

    k = str(kind or "none").strip().lower()
    if k not in cp.SELECTION_KINDS:
        raise HTTPException(status_code=400, detail="kind must be none|element|assembly|connection")
    if k == "none" or not id:
        return cp.empty_panel_guidance()

    g = require_company_gst(request, gst)
    try:
        if k == "element":
            el = ds.get_element(id, company_gst=g)
            if not el:
                raise PermissionError("element not found for company")
            return cp.panel_for_element(el)
        if k == "assembly":
            asm = ds.get_assembly(id, company_gst=g)
            if not asm:
                raise PermissionError("assembly not found for company")
            kids = ds.list_elements(id, company_gst=g)
            # connections listed via scene helper if available
            conn_n = 0
            try:
                from WEOS.db.engine import session_scope
                from WEOS.db.models import Connection
                from sqlalchemy import select, func

                with session_scope() as s:
                    conn_n = int(
                        s.execute(
                            select(func.count()).select_from(Connection).where(Connection.assembly_id == id)
                        ).scalar()
                        or 0
                    )
            except Exception:
                conn_n = 0
            return cp.panel_for_assembly(asm, child_count=len(kids), connection_count=conn_n)
        # connection
        from WEOS.db.engine import session_scope
        from WEOS.db.models import Connection
        from WEOS.factory.canonical_customer import _norm_company_gst

        with session_scope() as s:
            row = s.get(Connection, str(id).strip())
            if row is None or _norm_company_gst(row.company_gst) != _norm_company_gst(g):
                raise PermissionError("connection not found for company")
            return cp.panel_for_connection(row.to_dict())
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/property-panel/element/{element_id}")
def api_property_panel_update_element(
    element_id: str,
    body: dict[str, Any],
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    """Property Panel → config/element → SQL save → preview. Fail closed on save error."""
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import contextual_properties as cp

    g = require_company_gst(request, gst)
    raw = dict(body or {})
    # Flatten nested config into patch
    patch = {k: v for k, v in raw.items() if k not in ("config", "configPayload")}
    nested = raw.get("config") if isinstance(raw.get("config"), dict) else None
    if nested is None and isinstance(raw.get("configPayload"), dict):
        nested = raw.get("configPayload")
    if nested:
        patch.update(nested)
    try:
        return cp.apply_element_property_update(element_id, company_gst=g, patch=patch)
    except Exception as exc:
        raise _map_err(exc) from exc


# ── Canvas D2 — App entry + Quote workspace (cards / duplicate) ──────────────


class DesignDuplicateBody(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class AppEntryBody(BaseModel):
    sessionProjectId: str | None = None
    preferProjectId: str | None = None


@router.get("/api/projects/{project_id}/quote-workspace")
def api_quote_workspace(project_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    """Authoritative Quote Review payload: design cards + totals + active context."""
    from WEOS.factory.company_workspace import require_owned_project
    from WEOS.factory import quote_workspace as qw
    from WEOS.factory.project_store import load_project

    require_owned_project(request, project_id, gst)
    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return qw.build_quote_workspace(doc)


@router.post("/api/projects/{project_id}/designs/{line_id}/duplicate")
def api_duplicate_design(
    project_id: str,
    line_id: str,
    body: DesignDuplicateBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    """Multi-size duplicate → real new lineIds; original unchanged; durable save."""
    from WEOS.factory.company_workspace import require_owned_project
    from WEOS.factory import quote_workspace as qw
    from WEOS.factory.project_store import DurableSaveError, load_project, save_project

    require_owned_project(request, project_id, gst)
    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        result = qw.duplicate_design_rows(doc, source_line_id=line_id, rows=body.rows or [])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        saved = save_project(result["doc"], action="duplicate_design")
    except DurableSaveError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    workspace = qw.build_quote_workspace(saved)
    return {
        "ok": True,
        "batch": "CANVAS-D2",
        "projectId": project_id,
        "sourceLineId": line_id,
        "createdCount": result["createdCount"],
        "createdLineIds": result["createdLineIds"],
        "created": result["created"],
        "persisted": True,
        "durable": True,
        "workspace": workspace,
        "project": saved,
    }


@router.get("/api/quote-workspace/app-entry")
def api_quote_app_entry(request: Request, gst: str | None = None, prefer: str | None = None) -> dict[str, Any]:
    """Post-login entry plan: restore draft or New Quote Setup — never silent create."""
    from fastapi import HTTPException as FastAPIHTTPException
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory import quote_workspace as qw
    from WEOS.factory.project_store import list_projects

    try:
        g = require_company_gst(request, gst)
    except FastAPIHTTPException:
        plan = qw.app_entry_plan(logged_in=False)
        return {"ok": True, "batch": "CANVAS-D2", "loggedIn": False, **plan}

    projects = list_projects(company_gst=g, status="draft", limit=30, sort="updatedAt", order="desc")
    draft = qw.find_active_draft(projects, prefer_project_id=prefer)
    plan = qw.app_entry_plan(logged_in=True, active_draft=draft)
    return {
        "ok": True,
        "batch": "CANVAS-D2",
        "loggedIn": True,
        "draft": draft,
        **plan,
    }
