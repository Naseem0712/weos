"""WEOS FastAPI V2 — Manufacturing Operating System API.

Exact project routes for websites + ERP frontend.
Engines are never duplicated — always call factory pipeline.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from WEOS import TAGLINE, __version__
from WEOS.api.calculate import build_api_response, get_product_detail, products_catalog
from WEOS.factory.formula import (
    DEFAULT_QTY_FORMULA_BY_UNIT,
    FORMULA_VARIABLE_HELP,
    FORMULA_VARIABLES,
    MATERIAL_UNITS,
    preview_formula,
    validate_formula,
)
from WEOS.factory.import_engine import import_bytes
from WEOS.factory.pdf_engine import build_customer_pdf_bytes, build_factory_pdf_bytes
from WEOS.factory.product_admin import create_product, delete_product, get_admin_product, update_product
from WEOS.factory.project_engine import calculate_project
from WEOS.factory.project_store import (
    archive_project,
    dashboard_stats,
    delete_project,
    duplicate_project,
    empty_project,
    list_projects,
    load_project,
    project_history,
    redo_project,
    restore_project,
    save_project,
    undo_project,
)
from WEOS.factory.svg_export import render_svg_string
from WEOS.factory.pipeline import generate_job
from WEOS.factory.template_store import (
    BRANDS,
    create_template,
    delete_template,
    list_templates,
    load_template,
    save_template,
)
from WEOS.paths import PACKAGE_ROOT, WORKSPACE_ROOT, data_dir, website_dir

WEBSITE_DIR = website_dir()

_log = logging.getLogger("weos.api")
if _log.level == logging.NOTSET:
    _log.setLevel(logging.INFO)

app = FastAPI(
    title="WEOS API",
    description="WEOS — Design • Calculate • Manufacture • Quote",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _weos_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Log the full traceback for any unhandled error so production 500s on
    Railway are diagnosable (uvicorn shows this in the deploy logs)."""
    _log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "path": request.url.path},
    )


class CalculateRequest(BaseModel):
    product: str = "29mm_sliding"
    profile: str | None = None
    width: float
    height: float
    glass: str = "5mm_clear"
    colour: str = "white"
    handle: str = "standard"
    includeQuote: bool = True
    includePdf: bool = False
    includeSvg: bool = True
    includePng: bool = False
    includeJson: bool = True
    includeBom: bool = True
    includeDxf: bool = False
    persist: bool = False


class CartLine(BaseModel):
    lineId: str | None = None
    product: str = "29mm_sliding"
    width: float
    height: float
    qty: int = 1
    glass: str = "5mm_clear"
    colour: str = "white"
    handle: str = "standard"
    category: str | None = None
    sectionSeries: str | None = None
    saleUnit: str | None = "sqft"
    sellingRate: float | None = None
    description: str | None = None
    terms: str | None = None
    partitions: list[dict[str, Any]] | None = None
    mesh: bool | None = None
    trackCount: float | None = None
    glassShutters: int | None = None
    meshShutters: int | None = None
    fixShutters: Any = None
    opening: str | None = None
    system: str | None = None
    foldLeft: int | None = None
    foldRight: int | None = None
    sectionSizes: dict[str, Any] | None = None
    handleFinish: str | None = None
    handleLevel: float | None = None
    handleOverrides: dict[str, Any] | None = None
    grid: dict[str, Any] | None = None
    handleName: str | None = None
    meshName: str | None = None
    powderCoatName: str | None = None


class LivePriceRequest(BaseModel):
    product: str = "29mm_sliding"
    width: float = 1440
    height: float = 1800
    qty: int = 1
    glass: str = "5mm_clear"
    colour: str = "white"
    handle: str = "standard"
    sectionSeries: str | None = None
    saleUnit: str | None = "sqft"
    sellingRate: float | None = None
    customer: str | None = None
    description: str | None = None
    lookupSavedRate: bool = True
    partitions: list[dict[str, Any]] | None = None
    mesh: bool | None = None
    trackCount: float | None = None


class CustomerRateBody(BaseModel):
    customer: str
    product: str
    sellingRate: float
    saleUnit: str = "sqft"
    sectionSeries: str | None = None
    notes: str | None = None


class AgentObserveBody(BaseModel):
    customer: str | None = None
    projectId: str | None = None
    quotationId: str | None = None
    terms: str | None = None
    lines: list[dict[str, Any]] = Field(default_factory=list)
    architect: str | None = None
    dealer: str | None = None
    vendor: str | None = None
    discountPercent: float | None = None
    paymentTerm: str | None = None


class MaterialWeightBody(BaseModel):
    material: str = "aluminium_section"
    formulaKey: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class SuggestionApplyBody(BaseModel):
    suggestionId: str
    domain: str | None = None
    suggestion: dict[str, Any] | None = None
    appliedBy: str = "admin"


class CustomerMemoryApplyBody(BaseModel):
    customer: str
    confirm: bool = True


class ProjectCreate(BaseModel):
    name: str = "Untitled Project"
    customer: str = ""
    status: str = "draft"
    lines: list[CartLine] = Field(default_factory=list)
    # Bill-to (from Project Setup — mobile/name identify the customer) + quote text.
    customerMobile: str | None = None
    customerAddress: str | None = None
    customerGst: str | None = None
    description: str | None = None
    terms: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    customer: str | None = None
    status: str | None = None
    lines: list[CartLine] | None = None
    customerMobile: str | None = None
    customerAddress: str | None = None
    customerGst: str | None = None
    description: str | None = None
    terms: str | None = None


class ProjectCalculateOpts(BaseModel):
    optimize: bool = True


class PreviewRequest(BaseModel):
    product: str = "29mm_sliding"
    width: float = 1440
    height: float = 1800
    colour: str = "white"
    glass: str = "5mm_clear"
    handle: str = "standard"
    partitions: list[dict[str, Any]] | None = None
    mesh: bool | None = None
    trackCount: float | None = None
    glassShutters: int | None = None
    meshShutters: int | None = None
    fixShutters: Any = None
    opening: str | None = None
    system: str | None = None
    foldLeft: int | None = None
    foldRight: int | None = None
    sectionSizes: dict[str, Any] | None = None
    handleFinish: str | None = None
    handleLevel: float | None = None
    handleOverrides: dict[str, Any] | None = None
    handleName: str | None = None
    meshName: str | None = None
    powderCoatName: str | None = None
    sectionSeries: str | None = None
    grid: Any = None
    railing: dict[str, Any] | None = None
    productType: str | None = None
    category: str | None = None
    panelFill: dict[str, Any] | None = None
    features: list[dict[str, Any]] | None = None


class FormulaPreviewRequest(BaseModel):
    expr: str
    width: float = 1440
    height: float = 1800
    qty: float = 1
    extras: dict[str, float] = Field(default_factory=dict)


class ProductAdminBody(BaseModel):
    id: str | None = None
    displayName: str | None = None
    productType: str | None = None
    category: str | None = None
    units: str | None = None
    version: int | None = None
    status: str | None = None
    description: str | None = None
    tagline: str | None = None
    warranty: str | None = None
    heroImage: str | None = None
    gallery: list[str] | None = None
    sectionDrawings: list[str] | None = None
    specifications: dict[str, Any] | None = None
    materials: list[dict[str, Any]] | None = None
    formulas: dict[str, Any] | None = None
    pdfLayout: dict[str, Any] | None = None
    brand: str | None = None
    rules: dict[str, Any] | None = None
    catalogue: dict[str, Any] | None = None
    sectionSeries: str | None = None
    linkedProductId: str | None = None
    setup: dict[str, Any] | None = None
    syncHardware: bool = True
    bumpVersion: bool = True
    manualRatePerOpening: float | None = None


class CompanyBody(BaseModel):
    companyName: str | None = None
    address: str | None = None
    website: str | None = None
    gstNo: str | None = None
    phone: str | None = None
    email: str | None = None
    tagline: str | None = None
    state: str | None = None
    stateCode: str | None = None
    pan: str | None = None
    bankDetails: str | None = None
    cin: str | None = None
    terms: str | None = None


class CustomerProfileBody(BaseModel):
    name: str | None = None
    address: str | None = None
    gstNo: str | None = None
    phone: str | None = None
    email: str | None = None
    contactPerson: str | None = None
    state: str | None = None
    stateCode: str | None = None
    site: str | None = None
    notes: str | None = None


class TemplateBody(BaseModel):
    model_config = {"extra": "allow"}

    id: str | None = None
    brand: str | None = None
    kind: str | None = None
    name: str | None = None
    pageSize: str = "A4"
    layoutStyle: str | None = None
    branding: dict[str, Any] | None = None
    blocks: list[dict[str, Any]] | None = None


class TemplatePreviewRequest(BaseModel):
    templateId: str | None = None
    brand: str = "woodenmax"
    kind: str = "customer"
    projectId: str | None = None
    template: dict[str, Any] | None = None


class LearningApproveBody(BaseModel):
    approvedBy: str = "admin"
    publishVersion: bool = True


class LearningRejectBody(BaseModel):
    reason: str = ""
    rejectedBy: str = "admin"


class LearningEditBody(BaseModel):
    edits: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] | None = None


class ProductBuilderPublishBody(BaseModel):
    overwrite: bool = False


class MemorySaveBody(BaseModel):
    item: dict[str, Any] = Field(default_factory=dict)
    asApproved: bool = False
    approvedBy: str = "admin"
    publishToLibrary: bool = False


class MemoryApproveBody(BaseModel):
    approvedBy: str = "admin"
    publishVersion: bool = True
    publishToLibrary: bool = True
    reason: str = ""


class MemoryRejectBody(BaseModel):
    rejectedBy: str = "admin"
    reason: str = ""


class MemoryMergeBody(BaseModel):
    sourceId: str
    targetId: str
    mergedBy: str = "admin"


class MemoryVersionBody(BaseModel):
    reason: str = "Manual KB version publish"
    approvedBy: str = "admin"


class MemoryRollbackBody(BaseModel):
    toVersion: int
    rolledBackBy: str = "admin"
    reason: str = ""


class MemorySearchBody(BaseModel):
    query: str = ""
    memoryType: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = 25


class LearningObservationBody(BaseModel):
    observationType: str = "generic"
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggestion: str = ""
    targetMemoryType: str = ""
    targetPayload: dict[str, Any] = Field(default_factory=dict)
    domain: str = "engineering"


class BrainLoadBody(BaseModel):
    series: str
    productType: str | None = None
    customer: str | None = None
    useCache: bool = True


class BrainGenerateBody(BaseModel):
    series: str
    productType: str | None = None
    customer: str | None = None
    widthMm: float | None = 1200
    heightMm: float | None = 1500
    quantity: int = 1
    outputs: list[str] | None = None
    glassThicknessMm: float | None = None
    shutterCount: int = 2
    selections: list[dict[str, Any]] | None = None
    skipValidation: bool = False


class BrainExplainBody(BaseModel):
    series: str
    widthMm: float = 1200
    heightMm: float = 1500
    shutterCount: int = 2
    productType: str | None = None


class BrainCompatBody(BaseModel):
    series: str
    glassThicknessMm: float | None = None
    selections: dict[str, Any] = Field(default_factory=dict)


class BrainConflictBody(BaseModel):
    series: str
    selections: list[dict[str, Any]] = Field(default_factory=list)


class BrainRecommendBody(BaseModel):
    series: str | None = None
    productType: str | None = "Sliding"


class MemoryVersionCompareBody(BaseModel):
    fromVersion: int
    toVersion: int
    folder: str | None = None


class MemoryGraphNeighborsBody(BaseModel):
    memoryType: str
    id: str
    depth: int = 1
    direction: str = "both"


class SizeCompareBody(BaseModel):
    small: dict[str, Any]
    large: dict[str, Any]
    seriesId: str | None = None
    productType: str | None = None
    profilesUsed: list[Any] = Field(default_factory=list)
    jointTypes: list[Any] = Field(default_factory=list)
    designWhy: str = ""
    saveObservation: bool = True


class TeachUploadBody(BaseModel):
    seriesId: str | None = None
    productType: str | None = None
    profilesUsed: list[Any] = Field(default_factory=list)
    jointTypes: list[Any] = Field(default_factory=list)
    designWhy: str = ""
    sizes: list[dict[str, Any]] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=dict)


class ConflictSaveBody(BaseModel):
    rule: dict[str, Any] = Field(default_factory=dict)
    asApproved: bool = False
    approvedBy: str = "admin"


class CompatibilitySaveBody(BaseModel):
    rule: dict[str, Any] = Field(default_factory=dict)
    asApproved: bool = False
    approvedBy: str = "admin"


class GlassSpecBody(BaseModel):
    model_config = {"extra": "allow"}

    id: str | None = None
    name: str | None = None
    makeup: str = "single"
    thicknessMm: float | None = None
    overallMm: float | None = None
    glass1Mm: float | None = None
    glass2Mm: float | None = None
    airGapMm: float | None = None
    pvbMm: float | None = None
    colour: str = "clear"
    brand: str = ""
    toughened: bool = False
    rate: float | None = None
    rateUnit: str = "sqft"
    densityKgPerM3: float = 2500.0
    status: str = "active"


class GlassComputeBody(BaseModel):
    spec: dict[str, Any] = Field(default_factory=dict)
    clearWidthMm: float = 650
    clearHeightMm: float = 1700
    glassRules: dict[str, Any] | None = None
    qty: float = 1.0
    interlockLeft: bool = False
    interlockRight: bool = False


class GlassSizeBody(BaseModel):
    clearWidthMm: float
    clearHeightMm: float
    glassRules: dict[str, Any] | None = None
    insertion: dict[str, Any] | None = None
    interlockLeft: bool = False
    interlockRight: bool = False
    label: str = "glass"


class RailingMaterialBody(BaseModel):
    model_config = {"extra": "allow"}

    id: str | None = None
    name: str
    category: str = "block"
    sizeMm: str = ""
    widthMm: float | None = None
    heightMm: float | None = None
    thicknessMm: float | None = None
    diameterMm: float | None = None
    color: str = "natural"
    grade: str = ""
    mountType: str = "none"
    unit: str = "pc"
    rate: float | None = None
    weightKgPerUnit: float | None = None
    brand: str = ""
    remarks: str = ""
    status: str = "active"


class HardwareItemBody(BaseModel):
    model_config = {"extra": "allow"}

    id: str | None = None
    name: str
    category: str = "accessory"
    brand: str = ""
    partNumber: str = ""
    unit: str = "PC"
    rate: float | None = None
    weightKg: float | None = None
    supplier: str = ""
    compatibleProducts: list[str] = Field(default_factory=list)
    compatibleSeries: list[str] = Field(default_factory=list)
    remarks: str = ""
    status: str = "active"


class HardwareRulesApplyBody(BaseModel):
    rules: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    leafWeightsKg: list[float] = Field(default_factory=list)


class DefaultsSuggestBody(BaseModel):
    product: str | None = None
    customer: str | None = None


def _sanitize_filename_part(value: Any) -> str:
    """ASCII-safe, filesystem-safe chunk for a Content-Disposition filename."""
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text


def _pdf_filename(quote_no: Any, customer: Any, project_id: str, kind: str) -> str:
    """Downloaded PDF name = quotenumber_customername (sanitized)."""
    parts = [p for p in (_sanitize_filename_part(quote_no), _sanitize_filename_part(customer)) if p]
    base = "_".join(parts) or _sanitize_filename_part(project_id) or "WEOS-quotation"
    if kind == "factory":
        base = f"{base}_factory"
    return f"{base}.pdf"


def _public_base_url(request: Request | None) -> str:
    """Absolute base URL for QR/share links. Prefers explicit env, then Railway
    public domain, then the incoming request base URL (proxy-aware)."""
    env = (os.environ.get("WEOS_PUBLIC_BASE_URL") or "").strip()
    if env:
        return env.rstrip("/")
    dom = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    if dom:
        if not dom.startswith("http://") and not dom.startswith("https://"):
            dom = "https://" + dom
        return dom.rstrip("/")
    if request is not None:
        try:
            return str(request.base_url).rstrip("/")
        except Exception:
            return ""
    return ""


def _pdf_response(
    project_id: str,
    kind: str,
    brand: str | None = None,
    template_id: str | None = None,
    *,
    request: Request | None = None,
    inline: bool = False,
) -> Response:
    # load_project raises FileNotFoundError → 404 (handled by the caller).
    doc = load_project(project_id)
    try:
        result = calculate_project(doc, optimize=True)
    except Exception:
        # Never 500 the export because a calculation edge-case failed — log the
        # real traceback and still produce a (header-only) PDF for the customer.
        _log.exception("calculate_project failed for %s during %s PDF export", project_id, kind)
        result = {"lines": [], "combined": {}, "price": {}}
    created_at = doc.get("createdAt")
    updated_at = doc.get("updatedAt")
    version = int(doc.get("version") or 1)
    # Bill-to identity: mobile OR name identifies the customer (name optional).
    cust_name = (doc.get("customer") or "").strip()
    cust_mobile = (doc.get("customerMobile") or "").strip()
    bill_to = cust_name or cust_mobile or "—"
    payload = {
        **result,
        "projectId": project_id,
        "customer": bill_to,
        "name": doc.get("name"),
        "brand": brand or doc.get("brand") or "woodenmax",
        "templateId": template_id,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "version": version,
        # Per-quote description + terms (terms override the company default).
        "description": doc.get("description"),
        "terms": doc.get("terms"),
        # Absolute base + stable ref so the PDF QR opens the quote from the DB.
        "publicBaseUrl": _public_base_url(request),
        "quoteRef": doc.get("quoteId") or doc.get("quoteNumber") or project_id,
    }
    # Bill-to profile: saved customer profile first, then overlay the Project-Setup
    # values (mobile/address/GST) so the bill-to prints even without a saved profile.
    profile: dict[str, Any] = {}
    try:
        from WEOS.factory.customer_store import load_customer_profile

        if cust_name:
            profile = dict(load_customer_profile(cust_name) or {})
    except Exception:
        profile = {}
    if cust_mobile and not profile.get("phone"):
        profile["phone"] = cust_mobile
    if doc.get("customerAddress") and not profile.get("address"):
        profile["address"] = doc.get("customerAddress")
    if doc.get("customerGst") and not profile.get("gstNo"):
        profile["gstNo"] = doc.get("customerGst")
    if profile:
        payload["customerProfile"] = profile
    # Print an "Updated on" date automatically when an old quote is edited
    try:
        from datetime import datetime as _dt

        def _fmt(iso: str | None) -> str | None:
            if not iso:
                return None
            try:
                return _dt.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d-%m-%Y")
            except Exception:
                return None

        created_fmt = _fmt(created_at)
        updated_fmt = _fmt(updated_at)
        payload["createdOn"] = created_fmt
        # Print "Updated on" only for a genuine later-date edit of an existing quote
        if updated_fmt and created_fmt and updated_fmt != created_fmt:
            payload["updatedOn"] = updated_fmt
    except Exception:
        pass
    quote_no = payload.get("quotationId") or result.get("quotationId") or project_id
    name = _pdf_filename(quote_no, doc.get("customer") or payload.get("customer"), project_id, kind)
    try:
        if kind == "factory":
            pdf = build_factory_pdf_bytes(payload)
        else:
            pdf = build_customer_pdf_bytes(payload)
    except Exception:
        # build_*_pdf_bytes already degrade internally; this is a final belt-and-
        # suspenders guard so a PDF is ALWAYS returned instead of a bare 500.
        _log.exception("PDF build failed for %s (%s); returning minimal PDF", project_id, kind)
        from WEOS.factory.pdf_engine import _minimal_text_pdf

        pdf = _minimal_text_pdf(f"WEOS {kind.title()} PDF", payload)
    disposition = "inline" if inline else "attachment"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{name}"'},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "WEOS",
        "version": __version__,
        "tagline": TAGLINE,
    }


@app.get("/api/version")
def api_version() -> dict[str, Any]:
    """App identity + git-free build info for deploy checks."""
    return {
        "name": "WEOS",
        "app": "WEOS",
        "version": __version__,
        "tagline": TAGLINE,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packageRoot": PACKAGE_ROOT.as_posix(),
        "workspaceRoot": WORKSPACE_ROOT.as_posix(),
        "dataDir": data_dir().as_posix(),
        "railway": bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID")),
        "port": os.environ.get("PORT") or os.environ.get("WEOS_PORT"),
    }


@app.get("/api/dashboard")
def api_dashboard() -> dict[str, Any]:
    return dashboard_stats()


@app.get("/api/products")
def api_products(category: str | None = None) -> dict[str, Any]:
    items = products_catalog()
    if category:
        items = [p for p in items if str(p.get("category", "")).lower() == category.lower()]
    return {"products": items}


@app.get("/api/products/{product_id}")
def api_product_detail(product_id: str) -> dict[str, Any]:
    try:
        return get_product_detail(product_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/railing/quote")
def api_railing_quote(body: dict[str, Any]) -> dict[str, Any]:
    """Railing calculator + 2D designer preview.

    Accepts a railing config (length/height/panels/blocks/anchors/rates/extras/
    manual rate) and returns the full pricing breakdown plus a clean 2D SVG
    elevation. Pure/stateless — the cart persists the config in the quote line.
    """
    try:
        from WEOS.factory.railing_engine import compute_railing, ensure_railing_dims, railing_svg

        raw = dict(body or {})
        cfg = ensure_railing_dims(
            raw,
            width=float(raw.get("width") or 0) or None,
            height=float(raw.get("height") or 0) or None,
        )
        quote = compute_railing(cfg)
        svg = railing_svg(cfg, quote=quote)
        return {"quote": quote, "svg": svg}
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"railing quote failed: {exc}") from exc


@app.post("/api/preview")
def api_preview(body: PreviewRequest) -> dict[str, Any]:
    """Fast SVG preview for live cart — uses geometry engine only path via generate_job."""
    # Railing is not a window — never route it through generate_job.
    from WEOS.factory.line_kind import is_railing_product_type, product_world

    prod = str(getattr(body, "product", "") or "").lower()
    rail_cfg = getattr(body, "railing", None)
    world = product_world(
        getattr(body, "productType", None),
        category=getattr(body, "category", None),
        product_id=prod,
    )
    if (
        world in ("railing", "staircase_railing")
        or is_railing_product_type(getattr(body, "productType", None))
        or prod in ("railing", "railings_stub", "glass_railings")
        or "railing" in prod
        or isinstance(rail_cfg, dict)
    ):
        from WEOS.factory.railing_engine import compute_railing, ensure_railing_dims, railing_svg

        cfg = ensure_railing_dims(
            dict(rail_cfg or {}),
            width=float(getattr(body, "width", 0) or 0) or None,
            height=float(getattr(body, "height", 0) or 0) or None,
        )
        if not cfg.get("shape") and world == "staircase_railing":
            cfg["shape"] = "staircase"
        q = compute_railing(cfg)
        # Railing world: never return Product Library window series metadata.
        shape = q.get("shape") or cfg.get("shape") or "straight"
        rail_specs = {
            "type": shape,
            "mount": q.get("mountType") or cfg.get("mountType") or "side_mount",
            "lengthMm": q.get("lengthMm"),
            "heightMm": q.get("heightMm") or q.get("glassHeightMm"),
            "panels": q.get("panelCount"),
            "saleUnit": q.get("saleUnit"),
            "sellingPerUnit": q.get("sellingPerUnit"),
        }
        if shape == "staircase" or isinstance(q.get("stairGeometry"), dict):
            sg = q.get("stairGeometry") or {}
            rail_specs["stairs"] = (
                f"{sg.get('steps') or cfg.get('stairSteps') or '—'} steps"
            )
        return {
            "svg": railing_svg(cfg, quote=q),
            "system": "railing",
            "productType": "staircase_railing" if shape == "staircase" else "railing",
            "railing": q,
            "specifications": rail_specs,
            "layout": {},
            "sectionSpecs": {},
        }
    try:
        from WEOS.factory.layout_options import resolve_mesh_track
        from WEOS.factory.product_loader import load_product
        from WEOS.factory.svg_export import layout_summary_for_job

        meta = load_product(body.product, strict=False)
        # Catalogue/imported (stub) products now carry a synthesised renderable
        # geometry (see product_loader._ensure_renderable), so we draw a real
        # elevation instead of a placeholder. We only fall back to the catalogue
        # image if the product genuinely cannot be rendered.
        is_stub = bool(meta.get("_stub") or meta.get("status") == "stub")
        series_doc = None
        if body.sectionSeries:
            try:
                from WEOS.factory.section_catalogue import get_series

                series_doc = get_series(str(body.sectionSeries))
            except Exception:
                series_doc = None
        mesh_res = resolve_mesh_track(
            mesh=bool(body.mesh),
            track_count=body.trackCount,
            series=series_doc,
        )
        job = generate_job(
            body.width,
            body.height,
            body.product,
            glass=body.glass,
            colour=body.colour,
            handle=body.handle,
            partitions=body.partitions,
            mesh=bool(body.mesh),
            track_count=mesh_res["trackCount"],
            section_series=body.sectionSeries,
            glass_count=body.glassShutters,
            mesh_count=body.meshShutters,
            opening=body.opening,
            fixed_shutters=body.fixShutters,
            system=body.system,
            fold_left=body.foldLeft,
            fold_right=body.foldRight,
            section_sizes=body.sectionSizes,
            handle_finish=body.handleFinish,
            handle_level=body.handleLevel,
            handle_overrides=body.handleOverrides,
            grid=body.grid if str(body.system or "").lower() == "grid" else None,
        )
        pf = getattr(body, "panelFill", None)
        if not pf and getattr(body, "features", None):
            try:
                from WEOS.factory.panel_fills import panel_fill_from_line

                pf = panel_fill_from_line({"features": body.features, "panelFill": None})
                if (pf or {}).get("fillType") == "glass":
                    pf = None
            except Exception:
                pf = None
        if pf:
            from WEOS.factory.panel_fills import attach_fill_to_drawing

            attach_fill_to_drawing(job.drawing, pf)
        svg = render_svg_string(
            job.drawing,
            colour=body.colour.lower().replace(" ", "_"),
            annotations=True,
            include_plan=True,
            grid=body.grid if str(body.system or "").lower() != "grid" else None,
        )
        layout = layout_summary_for_job(
            width=body.width, height=body.height, layout_meta=job.layout_meta
        )
        return {
            "product": body.product,
            "stub": False,
            "svg": svg,
            "width": body.width,
            "height": body.height,
            "layout": layout,
            "meshTrack": mesh_res,
            "trackCount": mesh_res["trackCount"],
            "mesh": bool(job.layout_meta.get("mesh")),
            "system": job.layout_meta.get("system"),
            "glassShutters": job.layout_meta.get("glass_count"),
            "meshShutters": job.layout_meta.get("mesh_count"),
            "foldLeft": job.layout_meta.get("fold_left"),
            "foldRight": job.layout_meta.get("fold_right"),
            "notes": job.layout_meta.get("notes"),
            "heroImage": meta.get("heroImage"),
            "specifications": meta.get("specifications"),
        }
    except Exception as exc:
        # A catalogue/stub product that still cannot be drawn falls back to its
        # image rather than erroring, so the cart preview stays usable.
        _meta = locals().get("meta")
        if locals().get("is_stub") and isinstance(_meta, dict):
            return {
                "product": body.product,
                "stub": True,
                "svg": None,
                "heroImage": _meta.get("heroImage"),
                "message": f"Catalogue product — preview unavailable ({exc})",
            }
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/calculate")
def api_calculate(body: CalculateRequest) -> dict[str, Any]:
    try:
        response = build_api_response(
            product=body.profile or body.product,
            width=body.width,
            height=body.height,
            glass=body.glass,
            colour=body.colour,
            handle=body.handle,
            include_quote=body.includeQuote,
            include_pdf=body.includePdf,
            include_svg=body.includeSvg,
            include_png=body.includePng,
            include_json=body.includeJson,
            include_bom=body.includeBom,
            include_dxf=body.includeDxf,
            persist=body.persist,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Part 5 fix: a normal single calculate now *creates memory* (observations +
    # a Learning Memory record) so the Brain / insights have something to consume.
    try:
        _observe_calculation(response)
    except Exception:
        pass
    return response


def _observe_calculation(response: dict[str, Any]) -> None:
    """Turn a calculate response into engineering + learning-memory observations."""
    from WEOS.learning.engineering_agent import observe_engineering
    from WEOS.memory.store import write_observation_as_learning

    product = (response.get("product") or {})
    weight = response.get("weight") or {}
    line = {
        "product": product.get("id"),
        "displayName": product.get("displayName"),
        "width": response.get("width"),
        "height": response.get("height"),
        "qty": 1,
        "options": response.get("options") or {},
        "weight": weight,
        "glass": response.get("glass") or [],
        "hardware": response.get("hardware") or [],
        "cutList": response.get("cutList") or [],
        "bom": response.get("bom") or [],
    }
    observe_engineering(lines=[line], source="calculate_single")
    opts = response.get("options") or {}
    write_observation_as_learning(
        observation_type="calculation",
        summary=(
            f"Calculated {product.get('id')} {response.get('width')}×{response.get('height')} "
            f"glass={opts.get('glass')} colour={opts.get('colour')} → {weight.get('totalKg')} kg"
        ),
        evidence={
            "product": product.get("id"),
            "size": f"{response.get('width')}x{response.get('height')}",
            "glass": opts.get("glass"),
            "colour": opts.get("colour"),
            "totalKg": weight.get("totalKg"),
        },
        suggestion="Observed calculation — feeds glass/colour default suggestions.",
        domain="engineering",
    )


@app.get("/api/projects")
def api_list_projects(
    q: str | None = None,
    status: str | None = None,
    sort: str = "updatedAt",
    order: str = "desc",
) -> dict[str, Any]:
    return {"projects": list_projects(q=q, status=status, sort=sort, order=order, include_archived=status == "archived")}


@app.post("/api/projects")
def api_create_project(body: ProjectCreate) -> dict[str, Any]:
    doc = empty_project(name=body.name, customer=body.customer)
    doc["status"] = body.status or "draft"
    doc["lines"] = [ln.model_dump() for ln in body.lines]
    for _fld in ("customerMobile", "customerAddress", "customerGst", "description", "terms"):
        _val = getattr(body, _fld, None)
        if _val is not None:
            doc[_fld] = _val
    return save_project(doc, action="create")


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str) -> dict[str, Any]:
    try:
        return load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/projects/{project_id}")
def api_update_project(project_id: str, body: ProjectUpdate) -> dict[str, Any]:
    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if body.name is not None:
        doc["name"] = body.name
    if body.customer is not None:
        doc["customer"] = body.customer
    if body.status is not None:
        doc["status"] = body.status
    if body.lines is not None:
        doc["lines"] = [ln.model_dump() for ln in body.lines]
    for _fld in ("customerMobile", "customerAddress", "customerGst", "description", "terms"):
        _val = getattr(body, _fld, None)
        if _val is not None:
            doc[_fld] = _val
    return save_project(doc, action="update")


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str, hard: bool = Query(False)) -> dict[str, Any]:
    try:
        return delete_project(project_id, hard=hard)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/duplicate")
def api_duplicate(project_id: str) -> dict[str, Any]:
    try:
        return duplicate_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/archive")
def api_archive(project_id: str) -> dict[str, Any]:
    try:
        return archive_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/restore")
def api_restore(project_id: str) -> dict[str, Any]:
    try:
        return restore_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/undo")
def api_undo(project_id: str) -> dict[str, Any]:
    try:
        return undo_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/redo")
def api_redo(project_id: str) -> dict[str, Any]:
    try:
        return redo_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/history")
def api_history(project_id: str) -> dict[str, Any]:
    return {"projectId": project_id, "history": project_history(project_id)}


@app.post("/api/projects/{project_id}/calculate")
def api_project_calculate(project_id: str, body: ProjectCalculateOpts | None = None) -> dict[str, Any]:
    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    optimize = True if body is None else body.optimize
    result = calculate_project(doc, optimize=optimize)
    doc["quotationId"] = result["quotationId"]
    doc["status"] = "active"
    doc["lastCalculation"] = {
        "quotationId": result["quotationId"],
        "price": result["price"],
        "combined": result["combined"],
        "optimization": result.get("optimization"),
        "lines": result.get("lines"),
    }
    for i, ln in enumerate(doc.get("lines") or []):
        if i < len(result["lines"]):
            ln["lineId"] = result["lines"][i].get("lineId", ln.get("lineId"))
    save_project(doc, action="calculate")
    try:
        from WEOS.learning.commercial_agent import observe_quote
        from WEOS.learning.engineering_agent import observe_engineering
        from WEOS.factory.customer_rates import save_quote_line_rates

        lines = result.get("lines") or []
        observe_quote(
            customer=doc.get("customer"),
            project_id=project_id,
            quotation_id=result.get("quotationId"),
            lines=lines,
            terms=doc.get("terms"),
            source="calculate",
            architect=doc.get("architect"),
            dealer=doc.get("dealer"),
            vendor=doc.get("vendor"),
            discount_percent=doc.get("discountPercent"),
            payment_term=doc.get("paymentTerm"),
            meta=doc.get("commercialMeta") or {},
        )
        observe_engineering(
            lines=lines,
            project_id=project_id,
            quotation_id=result.get("quotationId"),
            customer=doc.get("customer"),
            source="calculate",
            optimization=result.get("optimization"),
        )
        if doc.get("customer"):
            save_quote_line_rates(str(doc["customer"]), doc.get("lines") or [])
    except Exception:
        pass
    result["project"] = {
        "projectId": doc["projectId"],
        "version": doc["version"],
        "name": doc.get("name"),
        "status": doc.get("status"),
    }
    result["links"] = {
        "quotation": f"/api/projects/{project_id}/quotation",
        "customerPdf": f"/api/projects/{project_id}/customer-pdf",
        "factoryPdf": f"/api/projects/{project_id}/factory-pdf",
    }
    return result


@app.get("/api/projects/{project_id}/quotation")
def api_quotation(project_id: str) -> dict[str, Any]:
    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = calculate_project(doc, optimize=True)
    return {
        "projectId": project_id,
        "quotationId": result["quotationId"],
        "customer": doc.get("customer"),
        "name": doc.get("name"),
        "price": result["price"],
        "combined": result["combined"],
        "lines": [
            {
                "lineId": ln.get("lineId"),
                "displayName": ln.get("displayName"),
                "width": ln.get("width"),
                "height": ln.get("height"),
                "qty": ln.get("qty"),
                "options": ln.get("options"),
                "price": ln.get("price"),
                "category": ln.get("category"),
            }
            for ln in result["lines"]
        ],
        "optimization": result.get("optimization"),
        "links": {
            "customerPdf": f"/api/projects/{project_id}/customer-pdf",
            "factoryPdf": f"/api/projects/{project_id}/factory-pdf",
        },
    }


@app.get("/api/projects/{project_id}/customer-pdf")
def api_customer_pdf(
    project_id: str,
    request: Request,
    brand: str | None = Query(None),
    templateId: str | None = Query(None),
) -> Response:
    try:
        return _pdf_response(project_id, "customer", brand=brand, template_id=templateId, request=request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/factory-pdf")
def api_factory_pdf(
    project_id: str,
    request: Request,
    brand: str | None = Query(None),
    templateId: str | None = Query(None),
) -> Response:
    try:
        return _pdf_response(project_id, "factory", brand=brand, template_id=templateId, request=request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Back-compat aliases
@app.get("/api/projects/{project_id}/pdf/customer")
def api_pdf_customer_alias(project_id: str, request: Request, brand: str | None = Query(None)) -> Response:
    return api_customer_pdf(project_id, request, brand=brand)


@app.get("/api/projects/{project_id}/pdf/factory")
def api_pdf_factory_alias(project_id: str, request: Request, brand: str | None = Query(None)) -> Response:
    return api_factory_pdf(project_id, request, brand=brand)


@app.get("/q/{ref}")
def public_quote(ref: str, request: Request) -> Response:
    """Public share link encoded in the PDF QR code.

    Resolves the quote from PostgreSQL (by quote number / id) and returns the
    customer PDF inline so scanning on a phone opens it — surviving redeploys.
    Falls back to a file-based project when the ref is a project id.
    """
    base = _public_base_url(request)
    try:
        from WEOS.db.quote_store import get_quote_by_ref

        q = get_quote_by_ref(ref)
    except Exception:
        q = None
    if q:
        cust = q.get("customer")
        cust_name = cust.get("name") if isinstance(cust, dict) else cust
        payload: dict[str, Any] = {
            "lines": q.get("lines") or [],
            "price": {"currency": "INR", "total": q.get("grandTotal"), "categoryTotals": {}},
            "combined": {"grandTotal": q.get("grandTotal")},
            "projectId": q.get("projectId"),
            "quotationId": q.get("quoteNumber") or q.get("quoteId"),
            "quoteRef": q.get("quoteNumber") or q.get("quoteId") or ref,
            "customer": cust_name,
            "name": "",
            "brand": q.get("brand") or "woodenmax",
            "publicBaseUrl": base,
        }
        try:
            if cust_name:
                from WEOS.factory.customer_store import load_customer_profile

                payload["customerProfile"] = load_customer_profile(str(cust_name))
        except Exception:
            pass
        try:
            pdf = build_customer_pdf_bytes(payload)
            return Response(
                content=pdf,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="quote_{ref}.pdf"'},
            )
        except Exception:
            _log.exception("public quote PDF build failed for %s", ref)
    # Fall back to a file-based project id (works while the project file exists).
    try:
        return _pdf_response(ref, "customer", request=request, inline=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Quote not found: {ref}") from exc


@app.post("/api/projects/import")
async def api_projects_import(
    file: UploadFile = File(...),
    projectId: str | None = Query(None),
    name: str = Query("Imported Project"),
    customer: str = Query(""),
) -> dict[str, Any]:
    """Import CSV/Excel into an existing project or create a new one."""
    data = await file.read()
    try:
        lines = import_bytes(file.filename or "import.csv", data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if projectId:
        try:
            doc = load_project(projectId)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        doc["lines"] = (doc.get("lines") or []) + lines
        saved = save_project(doc, action="import")
    else:
        doc = empty_project(name=name, customer=customer)
        doc["lines"] = lines
        saved = save_project(doc, action="import")
    return {
        "projectId": saved["projectId"],
        "imported": len(lines),
        "totalLines": len(saved["lines"]),
        "lines": lines,
    }


@app.post("/api/projects/{project_id}/import")
async def api_project_import(project_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    return await api_projects_import(file=file, projectId=project_id)


# ── Product Library admin + Formula Builder ──────────────────────────────────

@app.get("/api/admin/meta")
def api_admin_meta() -> dict[str, Any]:
    from WEOS.factory.line_kind import PRODUCT_TYPE_CHOICES

    return {
        "materialUnits": list(MATERIAL_UNITS),
        "formulaVariables": list(FORMULA_VARIABLES),
        "formulaVariableHelp": [dict(h) for h in FORMULA_VARIABLE_HELP],
        "defaultQtyFormulaByUnit": dict(DEFAULT_QTY_FORMULA_BY_UNIT),
        "productTypes": [{"id": k, "label": lab} for k, lab in PRODUCT_TYPE_CHOICES],
        "brands": list(BRANDS),
        "templateKinds": ["customer", "factory"],
        "blockTypes": [
            "logo", "title", "customer_details", "product_image", "price_table",
            "totals", "terms", "footer", "qr", "glass_table", "hardware_table",
            "cutlist_table", "materials_table",
        ],
    }


@app.get("/api/admin/products/{product_id}")
def api_admin_get_product(product_id: str) -> dict[str, Any]:
    try:
        return get_admin_product(product_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/products")
def api_admin_create_product(body: ProductAdminBody) -> dict[str, Any]:
    try:
        return create_product(body.model_dump(exclude_none=True))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/admin/products/{product_id}")
def api_admin_update_product(product_id: str, body: ProductAdminBody) -> dict[str, Any]:
    try:
        return update_product(product_id, body.model_dump(exclude_none=True))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/admin/products/{product_id}")
def api_admin_delete_product(product_id: str, hard: bool = Query(False)) -> dict[str, Any]:
    try:
        return delete_product(product_id, hard=hard)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/formulas/validate")
def api_formula_validate(body: FormulaPreviewRequest) -> dict[str, Any]:
    return validate_formula(body.expr, variables=body.extras or None)


@app.post("/api/formulas/preview")
def api_formula_preview(body: FormulaPreviewRequest) -> dict[str, Any]:
    return preview_formula(body.expr, width=body.width, height=body.height, qty=body.qty, extras=body.extras)


# ── PDF Template Designer ────────────────────────────────────────────────────

@app.get("/api/templates")
def api_list_templates(brand: str | None = None, kind: str | None = None) -> dict[str, Any]:
    return {"templates": list_templates(brand=brand, kind=kind), "brands": list(BRANDS)}


# ── Live pricing + sections + learning agent ─────────────────────────────────

@app.post("/api/quote/live")
def api_quote_live(body: LivePriceRequest) -> dict[str, Any]:
    """Reactive cost + selling amount for product × size × qty."""
    from WEOS.factory.live_pricing import live_price
    from WEOS.factory.customer_rates import lookup_rate

    payload = body.model_dump()
    if body.lookupSavedRate and body.customer and (body.sellingRate is None):
        saved = lookup_rate(
            body.customer,
            body.product,
            sale_unit=body.saleUnit,
            section_series=body.sectionSeries,
        )
        if saved:
            payload["sellingRate"] = saved.get("sellingRate")
            payload["saleUnit"] = saved.get("saleUnit") or body.saleUnit
            payload["_rateSource"] = "customer_saved"
    result = live_price(payload)
    if payload.get("_rateSource"):
        result["rateSource"] = payload["_rateSource"]
    return result


@app.get("/api/sale-units")
def api_sale_units() -> dict[str, Any]:
    from WEOS.factory.live_pricing import SALE_UNITS

    return {"units": SALE_UNITS}


@app.get("/api/customers/rates")
def api_list_customer_rates() -> dict[str, Any]:
    from WEOS.factory.customer_rates import list_customers_with_rates

    return {"customers": list_customers_with_rates()}


@app.get("/api/customers/{customer}/rates")
def api_get_customer_rates(customer: str) -> dict[str, Any]:
    from WEOS.factory.customer_rates import load_customer_rates

    return load_customer_rates(customer)


@app.post("/api/customers/rates")
def api_save_customer_rate(body: CustomerRateBody) -> dict[str, Any]:
    from WEOS.factory.customer_rates import save_customer_rate

    return save_customer_rate(
        body.customer,
        product=body.product,
        selling_rate=body.sellingRate,
        sale_unit=body.saleUnit,
        section_series=body.sectionSeries,
        notes=body.notes,
    )


# ── Company Setup ────────────────────────────────────────────────────────────

@app.get("/api/company")
def api_get_company() -> dict[str, Any]:
    from WEOS.factory.company_store import load_company

    return load_company()


@app.put("/api/company")
@app.post("/api/company")
def api_save_company(body: CompanyBody) -> dict[str, Any]:
    from WEOS.factory.company_store import save_company

    return save_company(body.model_dump(exclude_none=True))


@app.post("/api/company/logo")
async def api_upload_company_logo(file: UploadFile = File(...)) -> dict[str, Any]:
    from WEOS.factory.company_store import save_logo

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty logo upload")
    return save_logo(raw, filename=file.filename, content_type=file.content_type)


@app.get("/api/company/logo")
def api_get_company_logo() -> Response:
    from WEOS.factory.company_store import logo_file

    lf = logo_file()
    if not lf:
        raise HTTPException(status_code=404, detail="No company logo uploaded")
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".gif": "image/gif",
    }.get(lf.suffix.lower(), "application/octet-stream")
    return Response(content=lf.read_bytes(), media_type=mime)


# ── Customer profiles + accounts ─────────────────────────────────────────────

@app.get("/api/customers")
def api_list_customers() -> dict[str, Any]:
    """All customers (profiles ∪ rate books) for the customer account picker."""
    from WEOS.factory.customer_store import list_customer_profiles
    from WEOS.factory.customer_rates import list_customers_with_rates

    profiles = list_customer_profiles()
    seen = {str(p.get("name", "")).strip().lower() for p in profiles}
    merged = list(profiles)
    for r in list_customers_with_rates():
        nm = str(r.get("customer") or "").strip()
        if nm and nm.lower() not in seen:
            merged.append({"name": nm, "slug": nm.lower().replace(" ", "_"), "rateCount": r.get("rateCount")})
            seen.add(nm.lower())
    return {"customers": merged, "count": len(merged)}


@app.get("/api/customers/{customer}/profile")
def api_get_customer_profile(customer: str) -> dict[str, Any]:
    from WEOS.factory.customer_store import load_customer_profile

    return load_customer_profile(customer)


@app.put("/api/customers/{customer}/profile")
@app.post("/api/customers/{customer}/profile")
def api_save_customer_profile(customer: str, body: CustomerProfileBody) -> dict[str, Any]:
    from WEOS.factory.customer_store import save_customer_profile

    try:
        return save_customer_profile(customer, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/customers/{customer}/quotes")
def api_customer_quotes(customer: str) -> dict[str, Any]:
    from WEOS.factory.customer_store import customer_quotes

    return customer_quotes(customer)


@app.get("/api/sections")
def api_list_sections() -> dict[str, Any]:
    from WEOS.factory.section_catalogue import ensure_catalogue_imported, list_series

    ensure_catalogue_imported()
    return {"series": list_series()}


@app.get("/api/sections/{series_id}")
def api_get_section_series(series_id: str) -> dict[str, Any]:
    from WEOS.factory.section_catalogue import get_series

    try:
        return get_series(series_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/sections/import")
async def api_import_sections(file: UploadFile | None = File(None)) -> dict[str, Any]:
    """Import DETA windows Excel into series-wise section library JSON."""
    from WEOS.factory.section_catalogue import import_excel
    import tempfile
    from pathlib import Path

    if file is None:
        return import_excel()
    raw = await file.read()
    suffix = Path(file.filename or "sections.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        return import_excel(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/api/agent")
def api_agent_status() -> dict[str, Any]:
    from WEOS.learning.commercial_agent import agent_status

    return agent_status()


@app.get("/api/agent/insights")
def api_agent_insights(customer: str | None = None, product: str | None = None) -> dict[str, Any]:
    from WEOS.learning.commercial_agent import agent_insights

    return agent_insights(customer=customer, product=product)


@app.post("/api/agent/observe")
def api_agent_observe(body: AgentObserveBody) -> dict[str, Any]:
    from WEOS.learning.commercial_agent import observe_quote
    from WEOS.learning.engineering_agent import observe_engineering

    commercial = observe_quote(
        customer=body.customer,
        project_id=body.projectId,
        quotation_id=body.quotationId,
        lines=body.lines,
        terms=body.terms,
        source="manual",
        architect=body.architect,
        dealer=body.dealer,
        vendor=body.vendor,
        discount_percent=body.discountPercent,
        payment_term=body.paymentTerm,
    )
    engineering = observe_engineering(
        lines=body.lines,
        project_id=body.projectId,
        quotation_id=body.quotationId,
        customer=body.customer,
        source="manual",
    )
    return {"ok": True, "commercial": commercial, "engineering": engineering}


# ── Customer Memory + Commercial Intelligence ────────────────────────────────

@app.get("/api/customers/{customer}/memory")
def api_customer_memory(customer: str) -> dict[str, Any]:
    from WEOS.learning.commercial_agent import get_customer_memory

    return get_customer_memory(customer)


@app.post("/api/customers/memory/apply")
def api_customer_memory_apply(body: CustomerMemoryApplyBody) -> dict[str, Any]:
    """One-click commercial prefs — requires confirm=true (explicit user accept)."""
    from WEOS.learning.commercial_agent import apply_customer_memory_settings

    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required — commercial settings are never silent-applied")
    return apply_customer_memory_settings(body.customer)


@app.get("/api/commercial/intelligence")
def api_commercial_intelligence() -> dict[str, Any]:
    from WEOS.learning.commercial_agent import build_commercial_intelligence

    return build_commercial_intelligence()


@app.get("/api/commercial/recommendations")
def api_commercial_recommendations(product: str | None = None) -> dict[str, Any]:
    from WEOS.learning.commercial_agent import product_recommendations

    return product_recommendations(product)


# ── Engineering Live Learning ────────────────────────────────────────────────

@app.get("/api/engineering/status")
def api_engineering_status() -> dict[str, Any]:
    from WEOS.learning.engineering_agent import agent_status

    return agent_status()


@app.get("/api/engineering/stream")
def api_engineering_stream(limit: int = 40) -> dict[str, Any]:
    from WEOS.learning.engineering_agent import live_stream

    return live_stream(limit=limit)


@app.get("/api/engineering/insights")
def api_engineering_insights() -> dict[str, Any]:
    from WEOS.learning.engineering_agent import engineering_insights

    return engineering_insights()


@app.get("/api/engineering/formulas")
def api_engineering_formulas() -> dict[str, Any]:
    from WEOS.learning.material_formulas import list_baseline_formulas

    return {"formulas": list_baseline_formulas(), "count": len(list_baseline_formulas())}


@app.post("/api/engineering/weight")
def api_engineering_weight(body: MaterialWeightBody) -> dict[str, Any]:
    """Live formula weight (learning UI) + Universal Weight Engine when params fit."""
    from WEOS.learning.material_formulas import compute_weight

    # Prefer universal engine when caller sends structured dims (weightSource required)
    params = body.params or {}
    if any(
        k in params
        for k in (
            "widthMm",
            "heightMm",
            "thicknessMm",
            "lengthMm",
            "weightPerMeterKg",
            "weightPerMeter",
            "crossSectionAreaMm2",
            "useUniversalEngine",
        )
    ) and params.get("useFormulaEngine") is not True:
        try:
            from WEOS.factory.weight_engine import calculate_material_weight

            dims = {k: v for k, v in params.items() if k not in ("qty", "quantity", "wastePercent", "useUniversalEngine")}
            if "weightPerMeterKg" in dims and "weightPerMeter" not in dims:
                dims["weightPerMeter"] = dims["weightPerMeterKg"]
            qty = float(params.get("qty") or params.get("quantity") or 1)
            dens = params.get("densityKgPerM3")
            waste = params.get("wasteFactor")
            if waste is None and params.get("wastePercent") is not None:
                try:
                    waste = 1.0 + float(params["wastePercent"]) / 100.0
                except (TypeError, ValueError):
                    waste = None
            uni = calculate_material_weight(
                body.material,
                dimensions=dims,
                quantity=qty,
                density=float(dens) if dens is not None else None,
                weight_per_meter=float(params["weightPerMeterKg"])
                if params.get("weightPerMeterKg") is not None
                else None,
                waste_factor=waste,
            )
            # Keep legacy shape for existing UI
            return {
                **uni,
                "ok": bool(uni.get("ok")),
                "weightKg": uni.get("totalWeight"),
                "message": uni.get("formula")
                or (
                    f"{uni.get('sourceLabel')}: {uni.get('totalWeight')} kg"
                    if uni.get("ok")
                    else (uni.get("missingHints") or ["missing data"])[0]
                ),
                "engine": "universal_weight_engine",
            }
        except Exception:
            pass

    try:
        return compute_weight(body.material, params=body.params, formula_key=body.formulaKey)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class UniversalWeightBody(BaseModel):
    material: str
    dimensions: dict[str, Any] = Field(default_factory=dict)
    quantity: float = 1.0
    density: float | None = None
    unit: str | None = None
    catalogueWeight: float | None = None
    weightPerUnit: float | None = None
    weightPerMeter: float | None = None
    weightSource: str | None = None
    wasteFactor: float | None = None
    learnedWeight: float | None = None
    learnedApproved: bool = False


@app.post("/api/weight/calculate")
def api_weight_calculate(body: UniversalWeightBody) -> dict[str, Any]:
    from WEOS.factory.weight_engine import calculate_material_weight

    return calculate_material_weight(
        body.material,
        dimensions=body.dimensions,
        quantity=body.quantity,
        density=body.density,
        unit=body.unit,
        catalogue_weight=body.catalogueWeight,
        weight_per_unit=body.weightPerUnit,
        weight_per_meter=body.weightPerMeter,
        weight_source=body.weightSource,
        waste_factor=body.wasteFactor,
        learned_weight=body.learnedWeight,
        learned_approved=body.learnedApproved,
    )


@app.post("/api/weight/analyze")
def api_weight_analyze(body: dict[str, Any]) -> dict[str, Any]:
    from WEOS.factory.weight_engine import analyze_missing_weights, sum_product_weights

    items = body.get("items") or body.get("bom") or []
    return {
        "missing": analyze_missing_weights(items),
        "product": sum_product_weights(items, critical_unknown_blocks_total=bool(body.get("blockOnCritical", True))),
    }


@app.post("/api/weight/learn-candidate")
def api_weight_learn_candidate(body: dict[str, Any]) -> dict[str, Any]:
    from WEOS.factory.weight_engine import propose_learned_weight_candidate

    return propose_learned_weight_candidate(
        material=str(body.get("material") or "unknown"),
        weight_kg=float(body.get("weightKg") or body.get("weight") or 0),
        evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
        source_doc=body.get("sourceDoc"),
        unit=str(body.get("unit") or "kg"),
    )


@app.get("/api/engineering/suggestions")
def api_engineering_suggestions() -> dict[str, Any]:
    from WEOS.learning.engineering_agent import build_engineering_suggestions

    return build_engineering_suggestions()


# ── Learning Engine V2 (Manufacturing Knowledge AI) ──────────────────────────

@app.get("/api/learning/status")
def api_learning_status() -> dict[str, Any]:
    from WEOS.learning.engine_v2 import pipeline_status

    return pipeline_status()


@app.post("/api/learning/upload")
async def api_learning_upload(
    file: UploadFile = File(...),
    mode: str = Query("auto"),
    seriesId: str | None = Query(None),
) -> dict[str, Any]:
    """Upload catalogue PDF / quote / image / JSON → pending review (never production)."""
    from WEOS.learning.engine_v2 import ingest_upload_bytes

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")
    try:
        return ingest_upload_bytes(
            file.filename or "upload.bin",
            raw,
            mode=mode,
            series_id_hint=seriesId,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/learning/pending")
def api_learning_pending(kind: str | None = None) -> dict[str, Any]:
    from WEOS.learning.engine_v2 import list_proposals

    items = list_proposals(kind=kind)
    return {"pending": items, "count": len(items)}


@app.get("/api/learning/pending/{proposal_id}")
def api_learning_get_pending(proposal_id: str) -> dict[str, Any]:
    from WEOS.learning.engine_v2 import get_proposal

    try:
        return get_proposal(proposal_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/learning/pending/{proposal_id}")
def api_learning_edit_pending(proposal_id: str, body: LearningEditBody) -> dict[str, Any]:
    from WEOS.learning.engine_v2 import update_proposal_edits

    edits = dict(body.edits or {})
    if body.payload is not None:
        edits["payload"] = body.payload
    try:
        return update_proposal_edits(proposal_id, edits)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/learning/pending/{proposal_id}/approve")
def api_learning_approve(proposal_id: str, body: LearningApproveBody | None = None) -> dict[str, Any]:
    from WEOS.learning.engine_v2 import approve_proposal

    body = body or LearningApproveBody()
    try:
        return approve_proposal(
            proposal_id,
            approved_by=body.approvedBy,
            publish_version=body.publishVersion,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/learning/pending/{proposal_id}/reject")
def api_learning_reject(proposal_id: str, body: LearningRejectBody | None = None) -> dict[str, Any]:
    from WEOS.learning.engine_v2 import reject_proposal

    body = body or LearningRejectBody()
    try:
        return reject_proposal(proposal_id, reason=body.reason, rejected_by=body.rejectedBy)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/learning/libraries/{folder}")
def api_learning_library(folder: str) -> dict[str, Any]:
    from WEOS.learning.v2_store import list_library

    allowed = {
        "product_series", "profiles", "hardware", "glass",
        "accessories", "packaging", "formulas", "templates", "quotation_patterns",
    }
    if folder not in allowed:
        raise HTTPException(status_code=404, detail=f"Unknown library: {folder}")
    items = list_library(folder)
    return {"folder": folder, "items": items, "count": len(items)}


@app.get("/api/learning/tree")
def api_learning_tree(seriesId: str | None = None) -> dict[str, Any]:
    from WEOS.learning.v2_store import build_series_tree

    return {"tree": build_series_tree(seriesId)}


@app.get("/api/learning/versions")
def api_learning_versions() -> dict[str, Any]:
    from WEOS.learning.v2_store import current_kb_version, list_kb_versions

    return {"current": current_kb_version(), "versions": list_kb_versions()}


@app.post("/api/learning/versions/rollback")
def api_learning_versions_rollback(body: MemoryRollbackBody) -> dict[str, Any]:
    """Admin rollback of Knowledge Base libraries (alias of /api/memory/versions/rollback)."""
    from WEOS.memory.admin import rollback_kb

    try:
        return rollback_kb(body.toVersion, rolled_back_by=body.rolledBackBy, reason=body.reason)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/learning/suggestions")
def api_learning_suggestions(seriesId: str | None = None) -> dict[str, Any]:
    from WEOS.learning.suggestions import build_suggestions

    return build_suggestions(series_id=seriesId)


@app.post("/api/learning/suggestions/apply")
def api_learning_suggestions_apply(body: SuggestionApplyBody) -> dict[str, Any]:
    """One-click gated apply: engineering → pending review; commercial → settings payload only."""
    from WEOS.learning.suggestions import apply_suggestion

    try:
        return apply_suggestion(
            suggestion_id=body.suggestionId,
            domain=body.domain,
            suggestion=body.suggestion,
            applied_by=body.appliedBy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/learning/builder/series")
def api_builder_series_list() -> dict[str, Any]:
    from WEOS.learning.product_builder import list_buildable_series

    return {"series": list_buildable_series()}


@app.get("/api/learning/builder/{series_id}")
def api_builder_load(series_id: str) -> dict[str, Any]:
    from WEOS.learning.product_builder import load_series_for_builder

    try:
        return load_series_for_builder(series_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/learning/builder/{series_id}/publish")
def api_builder_publish(series_id: str, body: ProductBuilderPublishBody | None = None) -> dict[str, Any]:
    """Explicit admin publish of a draft product.json — never automatic."""
    from WEOS.learning.product_builder import publish_product_draft

    body = body or ProductBuilderPublishBody()
    result = publish_product_draft(series_id, overwrite=body.overwrite)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error") or "Publish failed")
    return result


# ── Manufacturing Memory Architecture + Engineering Brain ───────────────────

@app.get("/api/memory/status")
def api_memory_status() -> dict[str, Any]:
    from WEOS.memory.admin import list_types
    from WEOS.memory.store import get_store

    return {**get_store().summary(), "types": list_types()}


@app.get("/api/memory/types")
def api_memory_types() -> dict[str, Any]:
    from WEOS.memory.admin import list_types

    return {"types": list_types()}


@app.get("/api/memory/meta/relationships")
def api_memory_relationships() -> dict[str, Any]:
    from WEOS.memory.store import get_store

    return get_store().relationships()


@app.post("/api/memory/observe")
def api_memory_observe(body: LearningObservationBody) -> dict[str, Any]:
    """Write a Learning Memory observation (suggestion only)."""
    from WEOS.memory.store import write_observation_as_learning

    item = write_observation_as_learning(
        observation_type=body.observationType,
        summary=body.summary,
        evidence=body.evidence,
        suggestion=body.suggestion,
        target_memory_type=body.targetMemoryType,
        target_payload=body.targetPayload,
        domain=body.domain,
    )
    return {"ok": True, "item": item, "production_modified": False}


@app.post("/api/memory/search")
def api_memory_search_post(body: MemorySearchBody) -> dict[str, Any]:
    from WEOS.memory.search import search

    return search(body.query, memory_type=body.memoryType, filters=body.filters, limit=body.limit)


@app.get("/api/memory/search")
def api_memory_search_get(
    q: str = "",
    memoryType: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    from WEOS.memory.search import search

    return search(q, memory_type=memoryType, filters={}, limit=limit)


@app.post("/api/memory/search/rebuild")
def api_memory_search_rebuild() -> dict[str, Any]:
    from WEOS.memory.search import rebuild_index

    return rebuild_index()


@app.get("/api/memory/versions")
def api_memory_versions() -> dict[str, Any]:
    from WEOS.learning.v2_store import current_kb_version, list_kb_versions

    return {"current": current_kb_version(), "versions": list_kb_versions()}


@app.post("/api/memory/versions/publish")
def api_memory_versions_publish(body: MemoryVersionBody | None = None) -> dict[str, Any]:
    from WEOS.memory.admin import publish_version

    body = body or MemoryVersionBody()
    return publish_version(reason=body.reason, approved_by=body.approvedBy)


@app.post("/api/memory/versions/rollback")
def api_memory_versions_rollback(body: MemoryRollbackBody) -> dict[str, Any]:
    """Admin-only: restore libraries from versions/vN, then snapshot as new version."""
    from WEOS.memory.admin import rollback_kb

    try:
        return rollback_kb(body.toVersion, rolled_back_by=body.rolledBackBy, reason=body.reason)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/memory/versions/compare")
def api_memory_versions_compare_get(fromVersion: int, toVersion: int, folder: str | None = None) -> dict[str, Any]:
    from WEOS.memory.version_diff import compare_versions

    return compare_versions(fromVersion, toVersion, folder=folder)


@app.post("/api/memory/versions/compare")
def api_memory_versions_compare(body: MemoryVersionCompareBody) -> dict[str, Any]:
    from WEOS.memory.version_diff import compare_versions

    return compare_versions(body.fromVersion, body.toVersion, folder=body.folder)


@app.get("/api/memory/graph")
def api_memory_graph() -> dict[str, Any]:
    from WEOS.memory.graph import graph_snapshot

    return graph_snapshot()


@app.get("/api/memory/graph/neighbors")
def api_memory_graph_neighbors(
    memoryType: str,
    id: str,
    depth: int = 1,
    direction: str = "both",
) -> dict[str, Any]:
    from WEOS.memory.graph import neighbors

    return neighbors(memoryType, id, depth=depth, direction=direction)


@app.post("/api/memory/graph/neighbors")
def api_memory_graph_neighbors_post(body: MemoryGraphNeighborsBody) -> dict[str, Any]:
    from WEOS.memory.graph import neighbors

    return neighbors(body.memoryType, body.id, depth=body.depth, direction=body.direction)


@app.get("/api/memory/cache/status")
def api_memory_cache_status() -> dict[str, Any]:
    from WEOS.memory import cache

    return cache.status()


@app.post("/api/memory/cache/invalidate")
def api_memory_cache_invalidate() -> dict[str, Any]:
    from WEOS.memory import cache

    n = cache.invalidate_kb()
    return {"ok": True, "cleared": n}


@app.get("/api/memory/conflicts")
def api_memory_conflicts(status: str | None = "approved") -> dict[str, Any]:
    from WEOS.memory.conflicts import list_conflicts

    rules = list_conflicts(status=status)
    return {"rules": rules, "count": len(rules)}


@app.post("/api/memory/conflicts")
def api_memory_conflicts_save(body: ConflictSaveBody) -> dict[str, Any]:
    from WEOS.memory.conflicts import save_conflict, suggest_conflict

    if body.asApproved:
        rule = save_conflict(body.rule, as_approved=True, approved_by=body.approvedBy)
        return {"ok": True, "rule": rule, "production_modified": False}
    return suggest_conflict(body.rule)


@app.get("/api/memory/compatibility")
def api_memory_compatibility(status: str | None = "approved", seriesId: str | None = None) -> dict[str, Any]:
    from WEOS.memory.compatibility import list_compatibility

    rules = list_compatibility(status=status, series_id=seriesId)
    return {"rules": rules, "count": len(rules)}


@app.post("/api/memory/compatibility")
def api_memory_compatibility_save(body: CompatibilitySaveBody) -> dict[str, Any]:
    from WEOS.memory.compatibility import save_compatibility

    rule = save_compatibility(body.rule, as_approved=body.asApproved, approved_by=body.approvedBy)
    return {"ok": True, "rule": rule, "production_modified": False}


@app.post("/api/memory/size-compare")
def api_memory_size_compare(body: SizeCompareBody) -> dict[str, Any]:
    from WEOS.memory.size_learn import compare_sizes

    return compare_sizes(
        small=body.small,
        large=body.large,
        series_id=body.seriesId,
        product_type=body.productType,
        profiles_used=body.profilesUsed,
        joint_types=body.jointTypes,
        design_why=body.designWhy,
        save_observation=body.saveObservation,
    )


@app.post("/api/memory/teach-upload")
def api_memory_teach_upload(body: TeachUploadBody) -> dict[str, Any]:
    from WEOS.memory.size_learn import learn_from_upload

    return learn_from_upload(
        series_id=body.seriesId,
        product_type=body.productType,
        profiles_used=body.profilesUsed,
        joint_types=body.jointTypes,
        design_why=body.designWhy,
        sizes=body.sizes,
        source=body.source,
    )


@app.get("/api/memory/{memory_type}")
def api_memory_list(memory_type: str, status: str | None = None, ranked: bool = True) -> dict[str, Any]:
    from WEOS.memory.ranking import enrich_list, list_ranked
    from WEOS.memory.schemas import MEMORY_TYPES
    from WEOS.memory.store import get_store

    if memory_type not in MEMORY_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown memory type: {memory_type}")
    if ranked:
        items = list_ranked(memory_type, status=status)
    else:
        items = enrich_list(get_store().list(memory_type, status=status))
    return {"memoryType": memory_type, "items": items, "count": len(items)}


@app.get("/api/memory/{memory_type}/{item_id}")
def api_memory_get(memory_type: str, item_id: str) -> dict[str, Any]:
    from WEOS.memory.ranking import enrich_item
    from WEOS.memory.schemas import MEMORY_TYPES
    from WEOS.memory.store import get_store

    if memory_type not in MEMORY_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown memory type: {memory_type}")
    try:
        return enrich_item(get_store().get(memory_type, item_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/memory/{memory_type}")
def api_memory_save(memory_type: str, body: MemorySaveBody) -> dict[str, Any]:
    """Create/update a memory record. Default draft — production never touched."""
    from WEOS.memory.schemas import MEMORY_TYPES
    from WEOS.memory.store import get_store

    if memory_type not in MEMORY_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown memory type: {memory_type}")
    item = dict(body.item or {})
    item["memoryType"] = memory_type
    saved = get_store().save(
        memory_type,
        item,
        as_approved=body.asApproved,
        approved_by=body.approvedBy,
        publish_to_library=body.publishToLibrary and body.asApproved,
    )
    return {"ok": True, "item": saved, "production_modified": False}


@app.post("/api/memory/{memory_type}/{item_id}/approve")
def api_memory_approve(memory_type: str, item_id: str, body: MemoryApproveBody | None = None) -> dict[str, Any]:
    from WEOS.memory.admin import approve_memory

    body = body or MemoryApproveBody()
    try:
        return approve_memory(
            memory_type,
            item_id,
            approved_by=body.approvedBy,
            publish_version=body.publishVersion,
            publish_to_library=body.publishToLibrary,
            reason=body.reason,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/memory/{memory_type}/{item_id}/reject")
def api_memory_reject(memory_type: str, item_id: str, body: MemoryRejectBody | None = None) -> dict[str, Any]:
    from WEOS.memory.admin import reject_memory

    body = body or MemoryRejectBody()
    try:
        return reject_memory(memory_type, item_id, rejected_by=body.rejectedBy, reason=body.reason)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/memory/{memory_type}/merge")
def api_memory_merge(memory_type: str, body: MemoryMergeBody) -> dict[str, Any]:
    from WEOS.memory.admin import merge_memory

    try:
        return merge_memory(
            memory_type,
            body.sourceId,
            body.targetId,
            merged_by=body.mergedBy,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/brain/status")
def api_brain_status() -> dict[str, Any]:
    from WEOS.brain import brain_status

    return brain_status()


@app.post("/api/brain/load")
def api_brain_load(body: BrainLoadBody) -> dict[str, Any]:
    from WEOS.brain import load_context

    return load_context(
        series=body.series,
        product_type=body.productType,
        customer=body.customer,
        use_cache=body.useCache,
    )


@app.get("/api/brain/load/{series_id}")
def api_brain_load_get(series_id: str, productType: str | None = None, customer: str | None = None) -> dict[str, Any]:
    from WEOS.brain import load_context

    return load_context(series=series_id, product_type=productType, customer=customer)


@app.post("/api/brain/reason")
def api_brain_reason(body: BrainLoadBody) -> dict[str, Any]:
    from WEOS.brain import reason

    return reason(
        series=body.series,
        product_type=body.productType,
        customer=body.customer,
        use_cache=body.useCache,
    )


@app.post("/api/brain/generate")
def api_brain_generate(body: BrainGenerateBody) -> dict[str, Any]:
    from WEOS.brain import generate

    return generate(
        series=body.series,
        product_type=body.productType,
        customer=body.customer,
        width_mm=body.widthMm,
        height_mm=body.heightMm,
        quantity=body.quantity,
        outputs=body.outputs,
        glass_thickness_mm=body.glassThicknessMm,
        shutter_count=body.shutterCount,
        selections=body.selections,
        skip_validation=body.skipValidation,
    )


@app.post("/api/brain/validate")
def api_brain_validate(body: BrainLoadBody) -> dict[str, Any]:
    from WEOS.brain import validate_series

    return validate_series(series=body.series, product_type=body.productType, customer=body.customer)


@app.post("/api/brain/explain")
def api_brain_explain(body: BrainExplainBody) -> dict[str, Any]:
    from WEOS.brain import explain

    return explain(
        series=body.series,
        width_mm=body.widthMm,
        height_mm=body.heightMm,
        shutter_count=body.shutterCount,
        product_type=body.productType,
    )


@app.post("/api/brain/compatibility")
def api_brain_compatibility(body: BrainCompatBody) -> dict[str, Any]:
    from WEOS.brain import check_series_compatibility

    return check_series_compatibility(
        series=body.series,
        glass_thickness_mm=body.glassThicknessMm,
        selections=body.selections or None,
    )


@app.post("/api/brain/conflicts")
def api_brain_conflicts(body: BrainConflictBody) -> dict[str, Any]:
    from WEOS.brain import check_series_conflicts

    return check_series_conflicts(series=body.series, selections=body.selections)


@app.post("/api/brain/recommend")
def api_brain_recommend(body: BrainRecommendBody | None = None) -> dict[str, Any]:
    from WEOS.brain import recommend

    body = body or BrainRecommendBody()
    return recommend(series=body.series, product_type=body.productType)


# ── PDF Template Designer (handlers) ─────────────────────────────────────────

@app.get("/api/templates/{template_id}")
def api_get_template(template_id: str) -> dict[str, Any]:
    try:
        return load_template(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/templates")
def api_create_template(body: TemplateBody) -> dict[str, Any]:
    return create_template(body.model_dump(exclude_none=True))


@app.put("/api/templates/{template_id}")
def api_save_template(template_id: str, body: TemplateBody) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    data["id"] = template_id
    return save_template(template_id, data)


@app.delete("/api/templates/{template_id}")
def api_delete_template(template_id: str) -> dict[str, Any]:
    return delete_template(template_id)


@app.post("/api/templates/preview-pdf")
def api_template_preview_pdf(body: TemplatePreviewRequest) -> Response:
    """Render a preview PDF from a template id or inline template JSON."""
    from WEOS.factory.template_pdf import render_template_pdf
    from WEOS.factory.template_store import save_template as _save

    sample = {
        "projectId": body.projectId or "PRJ-PREVIEW",
        "quotationId": "Q-PREVIEW",
        "customer": "Sample Customer",
        "name": "Template Preview",
        "brand": body.brand,
        "lines": [
            {
                "displayName": "29mm Sliding Window",
                "width": 1440,
                "height": 1800,
                "qty": 2,
                "options": {"glass": "8mm_toughened", "colour": "white", "handle": "premium"},
                "price": {"total": 28500},
                "glass": [{"qty": 2, "width": 650, "height": 1700, "thicknessMm": 8}],
                "cutList": [{"profile": "outer_frame", "length_mm": 1440, "quantity": 2}],
            }
        ],
        "price": {"total": 57000, "categoryTotals": {"Windows": 57000}},
        "combined": {
            "grandTotal": 57000,
            "hardwareRolled": [{"name": "Handle", "qty": 4}, {"name": "Wheel", "qty": 8}],
            "categoryTotals": {"Windows": 57000},
        },
    }
    if body.projectId:
        try:
            doc = load_project(body.projectId)
            sample = {**calculate_project(doc, optimize=True), "customer": doc.get("customer"), "name": doc.get("name"), "brand": body.brand}
        except FileNotFoundError:
            pass

    tid = body.templateId
    if body.template:
        tid = body.template.get("id") or tid or f"{body.brand}_{body.kind}_preview"
        _save(tid, body.template)
        sample["templateId"] = tid
    elif tid:
        sample["templateId"] = tid
    else:
        sample["templateId"] = f"{body.brand}_{body.kind}"

    try:
        pdf = render_template_pdf(sample, kind=body.kind, brand=body.brand, template_id=sample.get("templateId"))
    except Exception:
        _log.exception("template preview render failed (brand=%s kind=%s)", body.brand, body.kind)
        from WEOS.factory.pdf_engine import _minimal_text_pdf

        pdf = _minimal_text_pdf("WEOS Template Preview", sample)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="template_preview.pdf"'},
    )


# ── Glass Engine + Glass Library (Part 2) ────────────────────────────────────

@app.get("/api/glass/options")
def api_glass_options() -> dict[str, Any]:
    from WEOS.factory.glass_catalogue import makeup_options

    return makeup_options()


@app.get("/api/glass/library")
def api_glass_library() -> dict[str, Any]:
    from WEOS.factory.glass_catalogue import list_glass

    items = list_glass()
    return {"glass": items, "count": len(items)}


@app.post("/api/glass/library")
def api_glass_library_save(body: GlassSpecBody) -> dict[str, Any]:
    from WEOS.factory.glass_catalogue import save_glass

    return {"ok": True, "glass": save_glass(body.model_dump(exclude_none=True))}


@app.delete("/api/glass/library/{glass_id}")
def api_glass_library_delete(glass_id: str) -> dict[str, Any]:
    from WEOS.factory.glass_catalogue import delete_glass

    try:
        return delete_glass(glass_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/glass/seed")
def api_glass_seed(force: bool = False) -> dict[str, Any]:
    from WEOS.factory.glass_catalogue import seed_default_glass

    return seed_default_glass(force=force, sync_products=True)


@app.get("/api/glass/cart-options")
def api_glass_cart_options() -> dict[str, Any]:
    """Full glass list for the cart dropdown (defaults + Glass Library extras)."""
    from WEOS.factory.glass_catalogue import cart_glass_options

    opts = cart_glass_options(merge_library=True)
    return {"options": opts, "count": len(opts)}


@app.post("/api/glass/sync-products")
def api_glass_sync_products() -> dict[str, Any]:
    """Push shared glass options into window product ``rules/glass.json`` files."""
    from WEOS.factory.glass_catalogue import sync_glass_options_to_products

    return sync_glass_options_to_products(merge_library=True)


@app.post("/api/glass/compute")
def api_glass_compute(body: GlassComputeBody) -> dict[str, Any]:
    from WEOS.factory.glass_catalogue import build_glass_spec, size_and_price

    spec = body.spec or {}
    if not spec.get("makeupLabel"):
        spec = build_glass_spec(
            makeup=str(spec.get("makeup") or "single"),
            thickness_mm=spec.get("thicknessMm"),
            overall_mm=spec.get("overallMm"),
            glass1_mm=spec.get("glass1Mm"),
            glass2_mm=spec.get("glass2Mm"),
            air_gap_mm=spec.get("airGapMm"),
            pvb_mm=spec.get("pvbMm"),
            colour=str(spec.get("colour") or "clear"),
            brand=str(spec.get("brand") or ""),
            toughened=bool(spec.get("toughened")),
            rate=spec.get("rate"),
            rate_unit=str(spec.get("rateUnit") or "sqft"),
            density=float(spec.get("densityKgPerM3") or 2500.0),
            name=spec.get("name"),
        )
    return size_and_price(
        spec,
        clear_width_mm=body.clearWidthMm,
        clear_height_mm=body.clearHeightMm,
        glass_rules=body.glassRules,
        qty=body.qty,
        interlock_left=body.interlockLeft,
        interlock_right=body.interlockRight,
    )


# ── Profile glass-insertion depth → accurate glass size (Part 4) ─────────────

@app.post("/api/glass/size")
def api_glass_size(body: GlassSizeBody) -> dict[str, Any]:
    from WEOS.factory.glass_sizing import compute_glass_size, insertion_from_profile

    if body.insertion is not None:
        if "engagement" in body.insertion or "clearance" in body.insertion:
            insertion = {
                "engagement": body.insertion.get("engagement") or {},
                "clearance": body.insertion.get("clearance") or {},
                "interlockOverlapMm": body.insertion.get("interlockOverlapMm", 0),
            }
        else:
            # Treat a flat dict as a glassInsertion block.
            insertion = insertion_from_profile({"glassInsertion": body.insertion})
    else:
        insertion = insertion_from_profile(body.glassRules)
    return compute_glass_size(
        body.clearWidthMm,
        body.clearHeightMm,
        insertion=insertion,
        interlock_left=body.interlockLeft,
        interlock_right=body.interlockRight,
        label=body.label,
    )


# ── Hardware Engine + Hardware Library + rules (Part 3) ──────────────────────

@app.get("/api/hardware/categories")
def api_hardware_categories() -> dict[str, Any]:
    from WEOS.factory.hardware_catalogue import HARDWARE_CATEGORIES, PER_BASIS

    return {"categories": HARDWARE_CATEGORIES, "perBasis": list(PER_BASIS.keys())}


@app.get("/api/hardware/library")
def api_hardware_library() -> dict[str, Any]:
    from WEOS.factory.hardware_catalogue import list_hardware

    items = list_hardware()
    return {"hardware": items, "count": len(items)}


@app.post("/api/hardware/library")
def api_hardware_library_save(body: HardwareItemBody) -> dict[str, Any]:
    from WEOS.factory.hardware_catalogue import save_hardware

    return {"ok": True, "hardware": save_hardware(body.model_dump(exclude_none=True))}


@app.delete("/api/hardware/library/{hardware_id}")
def api_hardware_library_delete(hardware_id: str) -> dict[str, Any]:
    from WEOS.factory.hardware_catalogue import delete_hardware

    try:
        return delete_hardware(hardware_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/hardware/seed")
def api_hardware_seed(force: bool = False) -> dict[str, Any]:
    from WEOS.factory.hardware_catalogue import seed_default_hardware

    return seed_default_hardware(force=force)


@app.post("/api/hardware/rules/apply")
def api_hardware_rules_apply(body: HardwareRulesApplyBody) -> dict[str, Any]:
    from WEOS.factory.hardware_catalogue import apply_hardware_rules

    return apply_hardware_rules(body.rules, body.context, leaf_weights_kg=body.leafWeightsKg)


# ── Railing materials gallery ────────────────────────────────────────────────

@app.get("/api/railing/materials/options")
def api_railing_materials_options() -> dict[str, Any]:
    from WEOS.factory.railing_materials import category_options

    return category_options()


@app.get("/api/railing/materials")
def api_railing_materials_list(category: str | None = None) -> dict[str, Any]:
    from WEOS.factory.railing_materials import list_materials, seed_default_materials

    items = list_materials(category=category)
    if not items:
        seed_default_materials()
        items = list_materials(category=category)
    return {"materials": items, "count": len(items)}


@app.post("/api/railing/materials")
def api_railing_materials_save(body: RailingMaterialBody) -> dict[str, Any]:
    from WEOS.factory.railing_materials import save_material

    return {"ok": True, "material": save_material(body.model_dump(exclude_none=True))}


@app.delete("/api/railing/materials/{material_id}")
def api_railing_materials_delete(material_id: str) -> dict[str, Any]:
    from WEOS.factory.railing_materials import delete_material

    try:
        return delete_material(material_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/railing/materials/seed")
def api_railing_materials_seed(force: bool = False) -> dict[str, Any]:
    from WEOS.factory.railing_materials import seed_default_materials

    return seed_default_materials(force=force)


# ── Memory audit + Intelligence (Part 5) ─────────────────────────────────────

@app.get("/api/memory-audit")
def api_memory_audit() -> dict[str, Any]:
    """Memory audit (renamed off /api/memory/* to avoid the dynamic
    /api/memory/{memory_type} matcher capturing 'audit')."""
    from WEOS.memory.audit import run_audit

    return run_audit()


@app.get("/api/intelligence")
def api_intelligence() -> dict[str, Any]:
    from WEOS.memory.intelligence import intelligence_report

    return intelligence_report()


@app.post("/api/intelligence/defaults")
def api_intelligence_defaults(body: DefaultsSuggestBody) -> dict[str, Any]:
    from WEOS.memory.intelligence import suggest_defaults

    return suggest_defaults(product=body.product, customer=body.customer)


@app.get("/api/intelligence/defaults")
def api_intelligence_defaults_get(product: str | None = None, customer: str | None = None) -> dict[str, Any]:
    from WEOS.memory.intelligence import suggest_defaults

    return suggest_defaults(product=product, customer=customer)


@app.post("/api/engineering/seed-formulas")
def api_engineering_seed_formulas(force: bool = False) -> dict[str, Any]:
    from WEOS.learning.material_formulas import seed_formula_memory

    return seed_formula_memory(force=force)


# ── Persistent Quotes (PostgreSQL) + Mobile Login + Live Agent (Parts 1-12) ──


class MobileLoginBody(BaseModel):
    # OTP-less login by any one of: mobile, quote number, or name. Name is optional.
    mobile: str | None = None
    name: str | None = None
    quoteNumber: str | None = None


class QuoteBody(BaseModel):
    model_config = {"extra": "allow"}

    quoteId: str | None = None
    quoteNumber: str | None = None
    customerId: int | None = None
    mobile: str | None = None
    customerMobile: str | None = None
    customerName: str | None = None
    projectId: int | None = None
    product: str | None = None
    series: str | None = None
    width: float | None = None
    height: float | None = None
    quantity: int | None = None
    trackCount: float | None = None
    shutterCount: int | None = None
    colour: str | None = None
    glass: Any = None
    hardware: Any = None
    materials: Any = None
    bom: Any = None
    rates: dict[str, Any] | None = None
    lines: list[dict[str, Any]] | None = None
    sellingPrice: float | None = None
    gstPercent: float | None = None
    gstAmount: float | None = None
    grandTotal: float | None = None
    status: str | None = None
    calculation: dict[str, Any] | None = None
    createdBy: str | None = None


class AgentAnalyzeBody(BaseModel):
    model_config = {"extra": "allow"}

    quoteId: str | None = None
    trigger: str = "manual"
    persist: bool = True
    learn: bool = True
    context: dict[str, Any] = Field(default_factory=dict)


class SuggestionStatusBody(BaseModel):
    status: str = "accepted"
    appliedBy: str = "customer"


def _db_error() -> HTTPException:
    """Consistent 503 when server persistence is offline (never fall back to browser)."""
    return HTTPException(
        status_code=503,
        detail="Server persistence unavailable. Set DATABASE_URL (PostgreSQL) on Railway. Quotes are never stored in the browser.",
    )


@app.post("/api/auth/login")
def api_auth_login(body: MobileLoginBody) -> dict[str, Any]:
    """OTP-less login by mobile, quote number, OR name (name optional).

    Returns the matched customer + their quotes (cross-device; DB is source of truth).
    """
    from WEOS.db.quote_store import login_flexible

    try:
        return login_flexible(mobile=body.mobile, name=body.name, quote_number=body.quoteNumber)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc


@app.get("/api/quotes")
def api_list_quotes(
    mobile: str | None = None,
    customerId: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    from WEOS.db.quote_store import list_quotes

    try:
        items = list_quotes(mobile=mobile, customer_id=customerId, status=status)
        return {"quotes": items, "count": len(items)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc


@app.post("/api/quotes")
def api_create_quote(body: QuoteBody) -> dict[str, Any]:
    from WEOS.db.quote_store import create_quote

    try:
        quote = create_quote(body.model_dump(exclude_none=True), created_by=body.createdBy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc
    # Run the Agent on create so suggestions are ready immediately (Part 3 + 12).
    try:
        from WEOS.agent import analyze

        quote["agent"] = analyze(_quote_to_context(quote), trigger="bom_calc", quote_id=quote["quoteId"])
    except Exception:
        _log.exception("agent analyze failed on quote create")
    return quote


@app.get("/api/quotes/{quote_id}")
def api_get_quote(quote_id: str) -> dict[str, Any]:
    from WEOS.db.quote_store import get_quote

    try:
        return get_quote(quote_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc


@app.put("/api/quotes/{quote_id}")
def api_update_quote(quote_id: str, body: QuoteBody) -> dict[str, Any]:
    from WEOS.db.quote_store import update_quote

    try:
        quote = update_quote(quote_id, body.model_dump(exclude_none=True), created_by=body.createdBy)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc
    try:
        from WEOS.agent import analyze

        quote["agent"] = analyze(_quote_to_context(quote), trigger="price_calc", quote_id=quote_id)
    except Exception:
        _log.exception("agent analyze failed on quote update")
    return quote


@app.delete("/api/quotes/{quote_id}")
def api_delete_quote(quote_id: str) -> dict[str, Any]:
    from WEOS.db.quote_store import delete_quote

    try:
        return delete_quote(quote_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc


@app.post("/api/quotes/{quote_id}/duplicate")
def api_duplicate_quote(quote_id: str) -> dict[str, Any]:
    from WEOS.db.quote_store import duplicate_quote

    try:
        return duplicate_quote(quote_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc


@app.get("/api/quotes/{quote_id}/versions")
def api_quote_versions(quote_id: str) -> dict[str, Any]:
    from WEOS.db.quote_store import list_versions

    try:
        versions = list_versions(quote_id)
        return {"quoteId": quote_id, "versions": versions, "count": len(versions)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc


@app.get("/api/quotes/{quote_id}/events")
def api_quote_events(quote_id: str) -> dict[str, Any]:
    from WEOS.db.quote_store import list_events

    try:
        events = list_events(quote_id)
        return {"quoteId": quote_id, "events": events, "count": len(events)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc


@app.post("/api/quotes/{quote_id}/finalize")
def api_finalize_quote(quote_id: str) -> dict[str, Any]:
    from WEOS.db.quote_store import finalize_quote

    try:
        quote = finalize_quote(quote_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc
    try:
        from WEOS.agent import analyze

        analyze(_quote_to_context(quote), trigger="finalize", quote_id=quote_id)
    except Exception:
        _log.exception("agent analyze failed on finalize")
    return quote


@app.post("/api/quotes/{quote_id}/suggestions/{suggestion_id}/status")
def api_suggestion_status(quote_id: str, suggestion_id: int, body: SuggestionStatusBody) -> dict[str, Any]:
    from WEOS.db.quote_store import set_suggestion_status

    try:
        return set_suggestion_status(quote_id, suggestion_id, body.status, created_by=body.appliedBy)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _db_error() from exc


def _quote_to_context(quote: dict[str, Any]) -> dict[str, Any]:
    """Build the live Agent context from a stored quote dict."""
    return {
        "product": quote.get("product"),
        "series": quote.get("series"),
        "width": quote.get("width"),
        "height": quote.get("height"),
        "quantity": quote.get("quantity"),
        "trackCount": quote.get("trackCount"),
        "shutterCount": quote.get("shutterCount"),
        "colour": quote.get("colour"),
        "glass": quote.get("glass"),
        "hardware": quote.get("hardware"),
        "rates": quote.get("rates"),
        "grandTotal": quote.get("grandTotal"),
    }


@app.post("/api/agent/analyze")
def api_agent_analyze(body: AgentAnalyzeBody) -> dict[str, Any]:
    """Live Agent Orchestrator — runs on any important quote change (Part 3/4)."""
    from WEOS.agent import analyze

    ctx = dict(body.context or {})
    # Allow flat context keys too (extra="allow").
    extra = body.model_dump(exclude={"quoteId", "trigger", "persist", "learn", "context"}, exclude_none=True)
    ctx.update({k: v for k, v in extra.items() if k not in ctx})
    return analyze(ctx, trigger=body.trigger, quote_id=body.quoteId, persist=body.persist, learn=body.learn)


@app.get("/api/admin/health")
@app.get("/api/health")
def api_admin_health() -> dict[str, Any]:
    """Startup / health diagnostic (Part 10)."""
    checks: dict[str, Any] = {}
    # Database
    try:
        from WEOS.db import health as db_health

        checks["database"] = db_health()
    except Exception as exc:
        checks["database"] = {"status": "ERROR", "error": str(exc)}
    # Quote Store
    try:
        from WEOS.db.quote_store import store_health

        checks["quoteStore"] = store_health()
    except Exception as exc:
        checks["quoteStore"] = {"status": "ERROR", "error": str(exc)}
    # Memory Store
    try:
        from WEOS.memory.store import get_store

        checks["memoryStore"] = {"status": "READY", **get_store().summary().get("counts", {})}
    except Exception as exc:
        checks["memoryStore"] = {"status": "ERROR", "error": str(exc)}
    # Knowledge Base
    try:
        from WEOS.learning.v2_store import current_kb_version

        checks["knowledgeBase"] = {"status": "READY", "kbVersion": current_kb_version()}
    except Exception as exc:
        checks["knowledgeBase"] = {"status": "ERROR", "error": str(exc)}
    # Agent + Suggestion Engine
    try:
        from WEOS.agent import status as agent_status_fn

        st = agent_status_fn()
        checks["agent"] = {"status": st.get("agent", "ERROR")}
        checks["suggestionEngine"] = {"status": st.get("suggestionEngine", "ERROR"), "triggers": st.get("triggers")}
    except Exception as exc:
        checks["agent"] = {"status": "ERROR", "error": str(exc)}
        checks["suggestionEngine"] = {"status": "ERROR", "error": str(exc)}

    def _ok(node: Any) -> bool:
        return isinstance(node, dict) and node.get("status") in ("READY", "CONNECTED")

    overall = "ok" if all(_ok(v) for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks, "version": __version__}


@app.on_event("startup")
def _weos_init_database() -> None:
    """Create quote tables on boot (PostgreSQL in prod, sqlite dev fallback)."""
    try:
        from WEOS.db import init_db

        res = init_db()
        if res.get("ok"):
            _log.info("WEOS DB ready (%s)", res.get("backend"))
        else:
            _log.warning("WEOS DB not ready: %s", res.get("error"))
    except Exception:
        _log.exception("WEOS DB init failed on startup")
    # Rehydrate the Product Library from the durable DB store (or seed it from the
    # shipped files on first run). Keeps imported/edited products across redeploys.
    try:
        from WEOS.db.product_store import bootstrap as _product_bootstrap

        _log.info("Product Library store: %s", _product_bootstrap())
    except Exception:
        _log.exception("Product Library rehydrate failed on startup")


@app.on_event("startup")
def _weos_seed_defaults() -> None:
    """Preload baseline formulas + starter glass/hardware libraries (idempotent)."""
    try:
        from WEOS.learning.material_formulas import seed_formula_memory

        seed_formula_memory()
    except Exception:
        pass
    try:
        from WEOS.factory.glass_catalogue import seed_default_glass

        seed_default_glass()
    except Exception:
        pass
    try:
        from WEOS.factory.hardware_catalogue import seed_default_hardware

        seed_default_hardware()
    except Exception:
        pass


@app.get("/", response_class=HTMLResponse)
def website_index() -> HTMLResponse:
    index = WEBSITE_DIR / "index.html"
    if not index.is_file():
        return HTMLResponse("<h1>WEOS</h1><p>UI missing.</p>")
    return HTMLResponse(index.read_text(encoding="utf-8"))


if WEBSITE_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEBSITE_DIR)), name="static")
