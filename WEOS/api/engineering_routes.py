"""Thin FastAPI routes for Engineering Masters + BOM Foundation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["engineering-masters"])


def _map_err(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _gst(request: Request, gst: str | None = None) -> str:
    from WEOS.factory.company_workspace import require_company_gst

    return require_company_gst(request, gst)


# ── Masters ──────────────────────────────────────────────────────────────────


class SeriesBody(BaseModel):
    code: str
    name: str
    family: str = "WINDOW"
    productTypes: list[str] | None = None
    systemDepthMm: float | None = None
    trackCount: int | None = None
    legacyProductId: str | None = None
    compatibilityAliases: list[str] | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None


class SeriesUpdateBody(BaseModel):
    code: str | None = None
    name: str | None = None
    family: str | None = None
    productTypes: list[str] | None = None
    systemDepthMm: float | None = None
    trackCount: int | None = None
    compatibilityAliases: list[str] | None = None
    description: str | None = None
    status: str | None = None
    meta: dict[str, Any] | None = None


class ProfileBody(BaseModel):
    code: str
    name: str
    defaultRole: str | None = None
    roles: list[str] | None = None
    widthMm: float | None = None
    heightMm: float | None = None
    wallThicknessMm: float | None = None
    weightPerRmt: float | None = None
    stockLengthMm: float | None = None
    alloyOrMaterial: str | None = None
    finishRefId: str | None = None
    costBasisType: str | None = None
    costBasisValue: float | None = None
    legacyCodes: list[str] | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None


class ProfileUpdateBody(ProfileBody):
    code: str | None = None  # type: ignore[assignment]
    name: str | None = None  # type: ignore[assignment]
    status: str | None = None


class RoleMapBody(BaseModel):
    role: str
    profileId: str
    isRequired: bool = True
    notes: str | None = None


class HardwareBody(BaseModel):
    code: str
    name: str
    category: str = "HARDWARE"
    unit: str = "PC"
    costBasisType: str | None = None
    costBasisValue: float | None = None
    compatibleFamilies: list[str] | None = None
    legacyCodes: list[str] | None = None
    description: str | None = None


class HardwareRuleBody(BaseModel):
    hardwareId: str
    name: str
    quantityFormula: str = "1"
    seriesId: str | None = None
    productType: str | None = None
    conditionFormula: str | None = None
    unit: str = "PC"
    priority: int = 100


class GlassBody(BaseModel):
    code: str
    name: str
    makeup: str | None = None
    thicknessMm: float | None = None
    densityKgPerSqm: float | None = None
    costBasisType: str | None = None
    costBasisValue: float | None = None
    legacyCodes: list[str] | None = None
    description: str | None = None


class AccessoryBody(BaseModel):
    kind: str
    code: str
    name: str
    unit: str = "PC"
    costBasisType: str | None = None
    costBasisValue: float | None = None
    legacyCodes: list[str] | None = None
    description: str | None = None


@router.get("/api/engineering/series")
def api_list_series(request: Request, gst: str | None = None, family: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return {"series": em.list_series(company_gst=g, family=family)}
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/engineering/series")
def api_create_series(body: SeriesBody, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return em.create_series(
            code=body.code,
            name=body.name,
            family=body.family,
            company_gst=g,
            product_types=body.productTypes,
            system_depth_mm=body.systemDepthMm,
            track_count=body.trackCount,
            legacy_product_id=body.legacyProductId,
            compatibility_aliases=body.compatibilityAliases,
            description=body.description,
            meta=body.meta,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/engineering/series/{series_id}")
def api_get_series(series_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    _gst(request, gst)
    row = em.get_series(series_id)
    if not row:
        raise HTTPException(status_code=404, detail="series not found")
    mappings = em.list_series_role_mappings(series_id)
    return {**row, "roleMappings": mappings}


@router.patch("/api/engineering/series/{series_id}")
def api_update_series(
    series_id: str, body: SeriesUpdateBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return em.update_series(series_id, company_gst=g, **body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/engineering/series/{series_id}/role-mappings")
def api_map_role(
    series_id: str, body: RoleMapBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    _gst(request, gst)
    try:
        return em.map_series_profile_role(
            series_id=series_id,
            role=body.role,
            profile_id=body.profileId,
            is_required=body.isRequired,
            notes=body.notes,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/engineering/profiles")
def api_list_profiles(request: Request, gst: str | None = None, role: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return {"profiles": em.list_profiles(company_gst=g, role=role)}
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/engineering/profiles")
def api_create_profile(body: ProfileBody, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return em.create_profile(company_gst=g, **body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/engineering/profiles/{profile_id}")
def api_get_profile(profile_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    _gst(request, gst)
    row = em.get_profile(profile_id)
    if not row:
        raise HTTPException(status_code=404, detail="profile not found")
    return row


@router.patch("/api/engineering/profiles/{profile_id}")
def api_update_profile(
    profile_id: str, body: ProfileUpdateBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return em.update_profile(profile_id, company_gst=g, **body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/engineering/hardware")
def api_list_hardware(request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    return {"hardware": em.list_hardware(company_gst=g), "rules": em.list_hardware_rules()}


@router.post("/api/engineering/hardware")
def api_create_hardware(body: HardwareBody, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return em.create_hardware(company_gst=g, **body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/engineering/hardware-rules")
def api_create_hw_rule(body: HardwareRuleBody, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return em.create_hardware_rule(
            hardware_id=body.hardwareId,
            name=body.name,
            quantity_formula=body.quantityFormula,
            series_id=body.seriesId,
            product_type=body.productType,
            condition_formula=body.conditionFormula,
            unit=body.unit,
            company_gst=g,
            priority=body.priority,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/engineering/glass")
def api_list_glass(request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    return {"glass": em.list_glass(company_gst=g)}


@router.post("/api/engineering/glass")
def api_create_glass(body: GlassBody, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return em.create_glass(company_gst=g, **body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/engineering/accessories")
def api_list_accessories(
    request: Request, gst: str | None = None, kind: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    return {"accessories": em.list_accessories(company_gst=g, kind=kind)}


@router.post("/api/engineering/accessories")
def api_create_accessory(body: AccessoryBody, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return em.create_accessory(company_gst=g, **body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/engineering/seed")
def api_seed_masters(request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    g = _gst(request, gst)
    try:
        return em.seed_default_window_masters(company_gst=g)
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/engineering/import-legacy")
def api_import_legacy(request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory.legacy_master_import import import_legacy_masters

    g = _gst(request, gst)
    try:
        return import_legacy_masters(company_gst=g)
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/engineering/resolve-profile")
def api_resolve_profile(
    request: Request,
    seriesId: str | None = None,
    role: str | None = None,
    profileReference: str | None = None,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory import engineering_masters as em

    _gst(request, gst)
    return em.resolve_profile_for_role(seriesId, role, profile_reference=profileReference)


# ── BOM ──────────────────────────────────────────────────────────────────────


@router.get("/api/elements/{element_id}/bom")
def api_get_element_bom(element_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, gst)
    bom = eb.get_current_bom(element_id=element_id, company_gst=g)
    if not bom:
        raise HTTPException(status_code=404, detail="No engineering BOM for element — generate first")
    return bom


@router.post("/api/elements/{element_id}/bom/generate")
def api_generate_element_bom(
    element_id: str, request: Request, gst: str | None = None, force: bool = False
) -> dict[str, Any]:
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, gst)
    try:
        return eb.generate_element_bom(element_id, company_gst=g, persist=True, force=force)
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/elements/{element_id}/bom/regenerate")
def api_regenerate_element_bom(
    element_id: str, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, gst)
    try:
        return eb.regenerate_bom(element_id, company_gst=g)
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/projects/{project_id}/bom/rollup")
def api_project_bom_rollup(project_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory.company_workspace import require_owned_project

    g, _ = require_owned_project(request, project_id, gst)
    try:
        return eb.rollup_hierarchy(project_id=project_id, company_gst=g)
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/bom/{bom_id}")
def api_get_bom(bom_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, gst)
    bom = eb.get_current_bom(bom_id=bom_id, company_gst=g)
    if not bom:
        raise HTTPException(status_code=404, detail="BOM not found")
    return bom


# ── Cost Rules + Costing + Selling ────────────────────────────────────────────


class CostRuleBody(BaseModel):
    domain: str
    name: str
    scope: str = "COMPANY"
    scopeRef: str | None = None
    params: dict[str, Any] | None = None
    priority: int = 100
    meta: dict[str, Any] | None = None


class CostRuleUpdateBody(BaseModel):
    name: str | None = None
    params: dict[str, Any] | None = None
    priority: int | None = None
    status: str | None = None
    scope: str | None = None
    scopeRef: str | None = None
    manualReview: bool | None = None
    meta: dict[str, Any] | None = None


class SellingBody(BaseModel):
    method: str | None = None
    sellingMethod: str | None = None
    markupPct: float | None = None
    targetMarginPct: float | None = None
    manualRate: float | None = None
    manualAmount: float | None = None
    unitRate: float | None = None
    commercialUnit: str | None = None
    saleUnit: str | None = None
    billingQtyOverride: float | None = None
    actualSelling: float | None = None
    legacySellingRate: float | None = None
    sellingRate: float | None = None
    lockStatus: str | None = None
    qty: float | None = None
    widthMm: float | None = None
    heightMm: float | None = None


class CostOverrideBody(BaseModel):
    overrideUnitCost: float | None = None
    overrideExtendedCost: float | None = None
    reason: str
    user: str | None = None


class LegacyCostImportBody(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/engineering/cost-rules")
def api_list_cost_rules(
    request: Request, gst: str | None = None, domain: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import cost_rules as cr

    g = _gst(request, gst)
    return {"rules": cr.list_cost_rules(company_gst=g, domain=domain)}


@router.post("/api/engineering/cost-rules")
def api_create_cost_rule(body: CostRuleBody, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import cost_rules as cr

    g = _gst(request, gst)
    try:
        return cr.create_cost_rule(
            domain=body.domain,
            name=body.name,
            company_gst=g,
            scope=body.scope,
            scope_ref=body.scopeRef,
            params=body.params,
            priority=body.priority,
            meta=body.meta,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.patch("/api/engineering/cost-rules/{rule_id}")
def api_update_cost_rule(
    rule_id: str, body: CostRuleUpdateBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import cost_rules as cr

    g = _gst(request, gst)
    try:
        return cr.update_cost_rule(rule_id, company_gst=g, **body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/engineering/cost-rules/seed")
def api_seed_cost_rules(request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import cost_rules as cr

    g = _gst(request, gst)
    return cr.seed_safe_sample_cost_rules(company_gst=g)


@router.post("/api/engineering/cost-rules/import-legacy")
def api_import_legacy_cost(
    body: LegacyCostImportBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import cost_rules as cr

    g = _gst(request, gst)
    return cr.import_legacy_cost_semantics(body.payload, company_gst=g)


@router.get("/api/elements/{element_id}/costing")
def api_get_element_costing(element_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_costing as ec

    g = _gst(request, gst)
    row = ec.get_current_costing(element_id=element_id, company_gst=g)
    if not row:
        raise HTTPException(status_code=404, detail="Costing not found")
    return row


@router.post("/api/elements/{element_id}/costing/generate")
def api_generate_element_costing(
    element_id: str,
    request: Request,
    gst: str | None = None,
    force: bool = False,
    body: SellingBody | None = None,
) -> dict[str, Any]:
    from WEOS.factory import engineering_costing as ec

    g = _gst(request, gst)
    selling = body.model_dump(exclude_none=True) if body else None
    try:
        return ec.generate_element_costing(
            element_id, company_gst=g, persist=True, force=force, selling=selling
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/elements/{element_id}/costing/regenerate")
def api_regenerate_element_costing(
    element_id: str,
    request: Request,
    gst: str | None = None,
    body: SellingBody | None = None,
) -> dict[str, Any]:
    from WEOS.factory import engineering_costing as ec

    g = _gst(request, gst)
    selling = body.model_dump(exclude_none=True) if body else None
    try:
        return ec.regenerate_costing(element_id, company_gst=g, selling=selling)
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/costing/{costing_id}")
def api_get_costing(costing_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory import engineering_costing as ec

    g = _gst(request, gst)
    row = ec.get_current_costing(costing_id=costing_id, company_gst=g)
    if not row:
        raise HTTPException(status_code=404, detail="Costing not found")
    return row


@router.get("/api/costing/{costing_id}/public")
def api_get_costing_public(costing_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    """Public/commercial view — strips cost/markup/profit (QR/customer safe)."""
    from WEOS.factory import engineering_costing as ec

    g = _gst(request, gst)
    row = ec.get_current_costing(costing_id=costing_id, company_gst=g)
    if not row:
        raise HTTPException(status_code=404, detail="Costing not found")
    return ec.public_commercial_view(row)


@router.post("/api/costing/{costing_id}/selling")
def api_update_selling(
    costing_id: str, body: SellingBody, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import engineering_costing as ec

    g = _gst(request, gst)
    try:
        return ec.update_selling(costing_id, company_gst=g, selling=body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/costing/{costing_id}/lines/{line_id}/override")
def api_cost_line_override(
    costing_id: str,
    line_id: str,
    body: CostOverrideBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory import engineering_costing as ec

    g = _gst(request, gst)
    try:
        return ec.apply_line_override(
            costing_id,
            line_id,
            company_gst=g,
            override_unit_cost=body.overrideUnitCost,
            override_extended_cost=body.overrideExtendedCost,
            reason=body.reason,
            user=body.user,
        )
    except Exception as exc:
        raise _map_err(exc) from exc


@router.get("/api/projects/{project_id}/costing/rollup")
def api_project_costing_rollup(
    project_id: str, request: Request, gst: str | None = None
) -> dict[str, Any]:
    from WEOS.factory import engineering_costing as ec
    from WEOS.factory.company_workspace import require_owned_project

    g, _ = require_owned_project(request, project_id, gst)
    try:
        return ec.rollup_project_costing(project_id=project_id, company_gst=g)
    except Exception as exc:
        raise _map_err(exc) from exc


@router.post("/api/engineering/costing/audit-strip")
def api_audit_strip_cost_fields(body: dict[str, Any]) -> dict[str, Any]:
    """Dev/audit helper — demonstrate public serialization strips internal cost fields."""
    from WEOS.factory import engineering_costing as ec

    return {"stripped": ec.strip_internal_cost_fields(body)}