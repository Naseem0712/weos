"""WEOS FastAPI V2 — Manufacturing Operating System API.

Exact project routes for websites + ERP frontend.
Engines are never duplicated — always call factory pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from WEOS import TAGLINE, __version__, BUILD_REVISION
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
    model_config = {"extra": "allow"}

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
    openingSide: str | None = None
    openingExplicit: bool | None = None
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
    productType: str | None = None
    casementPanels: list[dict[str, Any]] | None = None
    sashOverlapMm: float | None = None
    mullionGapMm: float | None = None
    shower: dict[str, Any] | None = None
    options: dict[str, Any] | None = None


class LivePriceRequest(BaseModel):
    model_config = {"extra": "allow"}

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
    productType: str | None = None
    system: str | None = None
    handleOverrides: dict[str, Any] | None = None
    casementPanels: list[dict[str, Any]] | None = None
    sashOverlapMm: float | None = None
    mullionGapMm: float | None = None
    shower: dict[str, Any] | None = None
    options: dict[str, Any] | None = None


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
    model_config = {"extra": "allow"}

    name: str = "Untitled Project"
    customer: str = ""
    status: str = "draft"
    # dicts — CartLine validation was dropping railing/shower/vent (missing width etc).
    # list[Any] so leftover line-id strings do not 422; _coerce_cart_lines resolves them.
    lines: list[Any] = Field(default_factory=list)
    # Bill-to (from Project Setup — mobile/name identify the customer) + quote text.
    customerMobile: str | None = None
    customerAddress: str | None = None
    customerGst: str | None = None
    description: str | None = None
    terms: str | None = None
    quotationId: str | None = None
    companyGst: str | None = None
    packageQuotes: list[Any] | None = None
    masterJobId: str | None = None
    quoteKind: str | None = None
    quoteDiscount: dict[str, Any] | None = None


class ProjectUpdate(BaseModel):
    model_config = {"extra": "allow"}

    name: str | None = None
    customer: str | None = None
    status: str | None = None
    lines: list[Any] | None = None
    customerMobile: str | None = None
    customerAddress: str | None = None
    customerGst: str | None = None
    description: str | None = None
    terms: str | None = None
    quotationId: str | None = None
    companyGst: str | None = None
    packageQuotes: list[Any] | None = None
    masterJobId: str | None = None
    quoteKind: str | None = None
    quoteDiscount: dict[str, Any] | None = None


class PackageQuoteBody(BaseModel):
    model_config = {"extra": "allow"}

    id: str | None = None
    quotationId: str | None = None
    gstMode: str | None = "exclude"
    gstPercent: float | None = 18
    note: str | None = None
    items: list[Any] = Field(default_factory=list)
    attachments: list[Any] | None = None


class ProjectCalculateOpts(BaseModel):
    model_config = {"extra": "allow"}
    optimize: bool = True
    quotationId: str | None = None
    lines: list[Any] | None = None
    persist: bool = True


class PdfExportBody(BaseModel):
    """In-memory cart snapshot for Quote PDF — do not rely on a stale saved project."""

    model_config = {"extra": "allow"}

    lines: list[Any] | None = None
    customer: str | None = None
    name: str | None = None
    customerMobile: str | None = None
    customerAddress: str | None = None
    customerGst: str | None = None
    description: str | None = None
    terms: str | None = None
    quotationId: str | None = None
    companyGst: str | None = None
    brand: str | None = None
    templateId: str | None = None
    persist: bool = False


class PreviewRequest(BaseModel):
    model_config = {"extra": "allow"}

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
    openingSide: str | None = None
    openingExplicit: bool | None = None
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
    shower: dict[str, Any] | None = None
    ventilator: dict[str, Any] | None = None
    productType: str | None = None
    category: str | None = None
    panelFill: dict[str, Any] | None = None
    features: list[dict[str, Any]] | None = None
    casementPanels: list[dict[str, Any]] | None = None
    sashOverlapMm: float | None = None
    mullionGapMm: float | None = None


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
    deletePin: str | None = None
    loginPin: str | None = None
    clearDeletePin: bool = False
    clearLoginPin: bool = False


class FollowUpBody(BaseModel):
    channel: str
    note: str | None = None


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
    companyGst: str | None = None


class AdvanceBody(BaseModel):
    amount: float
    paymentMode: str | None = "cash"
    reference: str | None = None
    note: str | None = None
    projectId: str | None = None
    quoteId: str | None = None
    quoteVersion: int | None = None
    paidAt: str | None = None
    customerName: str | None = None
    entryType: str | None = None  # advance | refund


class ProjectStatusBody(BaseModel):
    status: str


class QuoteRejectBody(BaseModel):
    confirm: bool = False
    note: str | None = None


class QuoteDeleteBody(BaseModel):
    gstNo: str | None = None
    pin: str | None = None
    confirm: str | None = None
    hard: bool = True


class PackUpdateBody(BaseModel):
    text: str
    date: str | None = None
    gstNo: str | None = None


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


def _pdf_filename(quote_no: Any, customer: Any, project_id: str, kind: str, project_name: Any = None) -> str:
    """Downloaded PDF name = customer_project, with quote/project id as fallback."""
    parts: list[str] = []
    for raw in (customer, project_name):
        part = _sanitize_filename_part(raw)
        if part and part not in parts:
            parts.append(part)
    if not parts:
        parts = [p for p in (_sanitize_filename_part(quote_no), _sanitize_filename_part(project_id)) if p]
    base = "_".join(parts) or "WEOS-quotation"
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


def _coerce_cart_lines(
    raw: Any, existing: Any = None, *, keep_preview_svg: bool = False
) -> list[dict[str, Any]]:
    """Keep every cart row. Saves strip giant preview.svg; Quote PDF keeps it.

    Frontend must send full line dicts. If a slot is accidentally a line-id string,
    resolve it from existing project lines instead of dropping the row or 422-ing.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for prev_ln in existing or []:
        if not isinstance(prev_ln, Mapping):
            continue
        d0 = dict(prev_ln)
        for key in ("lineId", "id"):
            lid = str(d0.get(key) or "").strip()
            if lid:
                by_id[lid] = d0
    out: list[dict[str, Any]] = []
    for ln in raw or []:
        if isinstance(ln, str):
            hit = by_id.get(ln.strip())
            if not hit:
                _log.warning("Dropped cart line id with no matching object: %s", ln)
                continue
            d = dict(hit)
        elif isinstance(ln, Mapping):
            d = dict(ln)
        else:
            continue
        prev = d.get("preview")
        if isinstance(prev, Mapping):
            p = dict(prev)
            if not keep_preview_svg:
                p.pop("svg", None)
                p.pop("pdfSvg", None)
            d["preview"] = p
        if not d.get("product") and d.get("productId"):
            d["product"] = d.get("productId")
        out.append(d)
    return out


def _merge_calc_lines(doc_lines: list[Any], calc_lines: list[Any]) -> list[dict[str, Any]]:
    """Keep every cart row — overlay calculated prices/specs by lineId or index."""
    if not doc_lines:
        return [dict(ln) for ln in calc_lines if isinstance(ln, Mapping)]
    if not calc_lines:
        return [dict(ln) for ln in doc_lines if isinstance(ln, Mapping)]
    calc_by_id: dict[str, dict[str, Any]] = {}
    for ln in calc_lines:
        if not isinstance(ln, Mapping):
            continue
        lid = str(ln.get("lineId") or ln.get("id") or "").strip()
        if lid:
            calc_by_id[lid] = dict(ln)
    merged: list[dict[str, Any]] = []
    for i, raw in enumerate(doc_lines):
        if not isinstance(raw, Mapping):
            continue
        src = dict(raw)
        lid = str(src.get("lineId") or src.get("id") or "").strip()
        hit = calc_by_id.get(lid) if lid else None
        if hit is None and i < len(calc_lines) and isinstance(calc_lines[i], Mapping):
            cand = calc_lines[i]
            cand_id = str(cand.get("lineId") or cand.get("id") or "").strip()
            if not lid or not cand_id or cand_id == lid:
                hit = dict(cand)
        if hit:
            out = dict(hit)
            for key in ("designPhoto", "locationName", "positionName", "description"):
                if src.get(key) and not out.get(key):
                    out[key] = src[key]
            merged.append(out)
        else:
            merged.append(src)
    if len(merged) < len(calc_lines):
        seen = {str(ln.get("lineId") or ln.get("id") or "") for ln in merged}
        for ln in calc_lines:
            if not isinstance(ln, Mapping):
                continue
            lid = str(ln.get("lineId") or ln.get("id") or "").strip()
            if lid and lid in seen:
                continue
            merged.append(dict(ln))
            if lid:
                seen.add(lid)
    return merged


def _pdf_response(
    project_id: str,
    kind: str,
    brand: str | None = None,
    template_id: str | None = None,
    *,
    request: Request | None = None,
    inline: bool = False,
    overlay: dict[str, Any] | None = None,
) -> Response:
    # load_project raises FileNotFoundError → 404 (handled by the caller).
    doc = load_project(project_id)
    if overlay:
        # PDF must print the live cart payload, not a stale autosave snapshot.
        if overlay.get("lines") is not None:
            overlay_lines = _coerce_cart_lines(
                overlay["lines"], existing=doc.get("lines"), keep_preview_svg=True
            )
            # Empty overlay must not wipe a saved cart. Non-empty overlay is the live cart (incl. deletes).
            if overlay_lines:
                doc["lines"] = overlay_lines
        for _fld in (
            "customer",
            "name",
            "customerMobile",
            "customerAddress",
            "customerGst",
            "description",
            "terms",
            "quotationId",
            "companyGst",
        ):
            if overlay.get(_fld) is not None:
                doc[_fld] = overlay[_fld]
        # Customer export persists the same live design in lastPdfExport below;
        # avoid a duplicate write before PDF generation so the button responds faster.
        if kind == "factory" and overlay.get("persist") and overlay.get("lines") is not None:
            try:
                save_project(doc, action="pdf-flush")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception:
                _log.exception("pdf-flush save failed for %s; continuing with in-memory lines", project_id)
    src_n = len(doc.get("lines") or [])
    try:
        # Customer PDF does not need factory cut/glass nesting — that was a multi-second wait.
        result = calculate_project(
            doc,
            optimize=(kind == "factory"),
            include_preview=False,
        )
        calc_lines = list(result.get("lines") or [])
        merged_lines = _merge_calc_lines(list(doc.get("lines") or []), calc_lines)
        if src_n and len(merged_lines) < src_n:
            _log.warning(
                "PDF merge returned %s lines, cart had %s — keeping raw cart rows",
                len(merged_lines),
                src_n,
            )
            merged_lines = [dict(ln) for ln in (doc.get("lines") or []) if isinstance(ln, Mapping)]
        elif src_n and len(merged_lines) != src_n:
            _log.warning(
                "PDF line count after merge: cart=%s calc=%s merged=%s",
                src_n,
                len(calc_lines),
                len(merged_lines),
            )
        result["lines"] = merged_lines
    except Exception:
        # Never 500 the export because a calculation edge-case failed — log the
        # real traceback and still print the live cart lines.
        _log.exception("calculate_project failed for %s during %s PDF export", project_id, kind)
        result = {"lines": list(doc.get("lines") or []), "combined": {}, "price": {}}
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
        "brand": brand or doc.get("brand") or ("marqt" if kind == "customer" else ""),
        "templateId": template_id,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "version": version,
        "status": doc.get("status"),
        "quotationId": doc.get("quotationId") or doc.get("quoteNumber") or doc.get("quoteId"),
        "quoteNumber": doc.get("quotationId") or doc.get("quoteNumber") or doc.get("quoteId"),
        "companyGst": doc.get("companyGst"),
        # Per-quote description + terms (terms override the company default).
        "description": doc.get("description"),
        "terms": doc.get("terms"),
        # Absolute base + stable ref so the PDF QR opens the quote from the DB.
        "publicBaseUrl": _public_base_url(request),
        "quoteRef": doc.get("quotationId") or doc.get("quoteNumber") or doc.get("quoteId") or project_id,
    }
    try:
        from WEOS.factory.company_store import company_branding, load_company, load_company_by_gst

        gst = str(doc.get("companyGst") or "").strip()
        co = (load_company_by_gst(gst) if gst else None) or load_company() or {}
        branding = company_branding(gst=gst or None)
        if co:
            payload["company"] = {
                "companyName": co.get("companyName") or co.get("name") or "",
                "name": co.get("companyName") or co.get("name") or "",
                "gstNo": co.get("gstNo") or gst,
                "phone": co.get("phone") or "",
                "email": co.get("email") or "",
                "address": co.get("address") or "",
                "website": co.get("website") or "",
                "logoPath": co.get("logoPath") or branding.get("logoPath"),
            }
        if branding:
            payload["branding"] = branding
            co_brand = str(branding.get("pdfBrand") or "").strip()
            if co_brand:
                payload["brand"] = co_brand
                tid = str(payload.get("templateId") or template_id or "")
                if tid and not tid.lower().startswith(co_brand.lower()):
                    payload["templateId"] = None
                    template_id = None
            elif branding.get("companyName") and not payload.get("brand"):
                payload["brand"] = "marqt"
    except Exception:
        _log.debug("PDF company branding overlay skipped", exc_info=True)
    try:
        from WEOS.factory.quote_share import ensure_project_share_token

        token = ensure_project_share_token(doc, persist=True)
        payload["shareToken"] = token
        payload["quoteShareToken"] = token
        # Keep quoteRef as the human quote number shown on the PDF; shareToken is
        # still on the payload for legacy scans that encoded the opaque token.
        if not payload.get("quoteRef"):
            payload["quoteRef"] = token
    except Exception:
        _log.debug("share token mint during PDF skipped", exc_info=True)
    if kind == "customer" and not payload.get("templateId"):
        # Company branding (AllKraft/WoodenMax/etc.) should change logos/colors,
        # not downgrade the customer quote to the old single-page table layout.
        payload["templateId"] = "marqt_customer"
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
    # Keep uploaded design photos on calculated lines (calculate rebuilds line dicts).
    try:
        orig_lines = list(doc.get("lines") or [])
        calc_lines = list(result.get("lines") or [])
        by_id = {
            str(ln.get("lineId")): ln
            for ln in orig_lines
            if isinstance(ln, dict) and ln.get("lineId")
        }
        for i, ln in enumerate(calc_lines):
            if not isinstance(ln, dict) or ln.get("designPhoto"):
                continue
            src = by_id.get(str(ln.get("lineId") or ""))
            if src is None and i < len(orig_lines) and isinstance(orig_lines[i], dict):
                src = orig_lines[i]
            photo = (src or {}).get("designPhoto") if isinstance((src or {}).get("designPhoto"), dict) else None
            if photo:
                ln["designPhoto"] = dict(photo)
            loc = ""
            if isinstance(src, dict):
                loc = str(src.get("locationName") or src.get("positionName") or "").strip()
                if not loc and isinstance(src.get("options"), dict):
                    loc = str(src["options"].get("locationName") or src["options"].get("positionName") or "").strip()
            if loc and not ln.get("locationName"):
                ln["locationName"] = loc
                ln["positionName"] = loc
                opts = dict(ln.get("options") or {}) if isinstance(ln.get("options"), dict) else {}
                opts["locationName"] = loc
                opts["positionName"] = loc
                ln["options"] = opts
    except Exception:
        _log.exception("design photo merge failed for %s", project_id)

    quote_no = payload.get("quotationId") or result.get("quotationId") or project_id
    name = _pdf_filename(
        quote_no,
        doc.get("customer") or payload.get("customer"),
        project_id,
        kind,
        project_name=doc.get("name") or payload.get("name"),
    )
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
    if overlay and overlay.get("persist"):
        try:
            from datetime import datetime as _dt, timezone as _tz

            doc["lastPdfExport"] = {
                "kind": kind,
                "exportedAt": _dt.now(_tz.utc).isoformat(),
                "projectId": project_id,
                "quotationId": payload.get("quotationId"),
                "customer": payload.get("customer"),
                "customerMobile": doc.get("customerMobile"),
                "customerGst": doc.get("customerGst"),
                "companyGst": payload.get("companyGst"),
                "templateId": payload.get("templateId") or ("marqt_customer" if kind == "customer" else None),
                "brand": payload.get("brand"),
                "lineCount": len(payload.get("lines") or []),
                "total": (payload.get("price") or {}).get("total") or (payload.get("combined") or {}).get("grandTotal"),
                "pdfBytes": len(pdf or b""),
            }
            save_project(doc, bump_version=False, action=f"{kind}_pdf_export")
        except Exception:
            _log.exception("PDF export snapshot save failed for %s (%s)", project_id, kind)
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
        "buildRevision": BUILD_REVISION,
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
def api_dashboard(request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory.company_dashboard import company_dashboard
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, gst)
    return company_dashboard(g)


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


@app.post("/api/ventilator/quote")
def api_ventilator_quote(body: dict[str, Any]) -> dict[str, Any]:
    """Bathroom ventilator calculator + 2D elevation SVG (canvas === PDF)."""
    try:
        from WEOS.factory.ventilator_engine import compute_ventilator, ensure_ventilator_dims, ventilator_svg

        raw = dict(body or {})
        cfg = ensure_ventilator_dims(
            raw,
            width=float(raw.get("width") or raw.get("widthMm") or 0) or None,
            height=float(raw.get("height") or raw.get("heightMm") or 0) or None,
        )
        quote = compute_ventilator(cfg)
        svg = ventilator_svg(cfg, quote=quote)
        return {"quote": quote, "svg": svg}
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"ventilator quote failed: {exc}") from exc


@app.post("/api/shower/quote")
def api_shower_quote(body: dict[str, Any]) -> dict[str, Any]:
    """Shower partition calculator + 2D elevation / floor-plan SVG."""
    try:
        from WEOS.factory.shower_engine import compute_shower, ensure_shower_dims, shower_svg

        raw = dict(body or {})
        cfg = ensure_shower_dims(
            raw,
            width=float(raw.get("width") or raw.get("widthMm") or 0) or None,
            height=float(raw.get("height") or raw.get("heightMm") or 0) or None,
        )
        quote = compute_shower(cfg)
        svg = shower_svg(cfg, quote=quote)
        return {"quote": quote, "svg": svg}
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"shower quote failed: {exc}") from exc


@app.get("/api/finishes")
def api_finishes(kind: str | None = None) -> dict[str, Any]:
    from WEOS.factory.finish_catalogue import cart_colour_options, list_finishes

    return {"finishes": list_finishes(kind=kind), "options": cart_colour_options(), "count": len(list_finishes(kind=kind))}


@app.post("/api/finishes")
def api_finishes_save(body: dict[str, Any]) -> dict[str, Any]:
    from WEOS.factory.finish_catalogue import save_finish

    name = str(body.get("name") or body.get("label") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Colour name required")
    rec = save_finish(name, kind=str(body.get("kind") or "powder_coat"), finish_id=body.get("id"))
    return {"ok": True, "finish": rec}


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
    from WEOS.factory.line_kind import (
        is_pergola_product_type,
        is_railing_product_type,
        is_shower_product_type,
        is_ventilator_product_type,
        product_world,
    )

    prod = str(getattr(body, "product", "") or "").lower()
    rail_cfg = getattr(body, "railing", None)
    shower_cfg = getattr(body, "shower", None)
    vent_cfg = getattr(body, "ventilator", None)
    panel_fill = getattr(body, "panelFill", None)
    world = product_world(
        getattr(body, "productType", None),
        category=getattr(body, "category", None),
        product_id=prod,
    )
    if (
        world == "ventilator"
        or is_ventilator_product_type(getattr(body, "productType", None))
        or "ventilat" in prod
        or isinstance(vent_cfg, dict)
    ):
        from WEOS.factory.ventilator_engine import compute_ventilator, ensure_ventilator_dims, ventilator_svg

        cfg = ensure_ventilator_dims(
            dict(vent_cfg or {}),
            width=float(getattr(body, "width", 0) or 0) or None,
            height=float(getattr(body, "height", 0) or 0) or None,
        )
        if getattr(body, "colour", None) and not cfg.get("colour"):
            cfg["colour"] = body.colour
        q = compute_ventilator(cfg)
        return {
            "svg": ventilator_svg(cfg, quote=q),
            "system": "ventilator",
            "productType": "bathroom_ventilator",
            "ventilator": q,
            "specifications": {
                "type": f"Bathroom ventilator · {q.get('mode')}",
                "size": f"{q.get('widthMm')}×{q.get('heightMm')} mm",
                "glass": q.get("glassLabel"),
                "colour": q.get("colour"),
                "layout": (
                    f"fan cut Ø{q.get('fanDiameterMm')}" if q.get("mode") == "full_cutout"
                    else f"{q.get('louversSide')} {q.get('louversFill')} / remain {q.get('remainFill')}"
                ),
                "areaSqft": q.get("areaSqft"),
                "sellingPerUnit": q.get("sellingPerUnit"),
            },
            "layout": {"system": "ventilator", "panels": q.get("panels") or [], "trackCount": None},
            "sectionSpecs": {},
        }
    if (
        world == "shower"
        or is_shower_product_type(getattr(body, "productType", None))
        or "shower" in prod
        or isinstance(shower_cfg, dict)
    ):
        from WEOS.factory.shower_engine import compute_shower, ensure_shower_dims, shower_svg

        cfg = ensure_shower_dims(
            dict(shower_cfg or {}),
            width=float(getattr(body, "width", 0) or 0) or None,
            height=float(getattr(body, "height", 0) or 0) or None,
        )
        if getattr(body, "colour", None) and not cfg.get("colour"):
            cfg["colour"] = body.colour
        q = compute_shower(cfg)
        return {
            "svg": shower_svg(cfg, quote=q),
            "system": "shower",
            "productType": "shower_partition",
            "shower": q,
            "specifications": {
                "type": f"{q.get('shape')} · {q.get('operation')}",
                "size": f"{q.get('widthMm')}×{q.get('heightMm')} mm",
                "glass": q.get("glassLabel"),
                "colour": q.get("colour"),
                "areaSqft": q.get("areaSqft"),
                "sellingPerUnit": q.get("sellingPerUnit"),
            },
            "layout": {"system": "shower", "panels": q.get("panels") or [], "footprint": q.get("footprint"), "trackCount": None},
            "sectionSpecs": {},
        }
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
    if (
        world == "louver"
        or "louver" in prod
        or "louvre" in prod
    ):
        from WEOS.factory.special_schematics import louver_svg

        w = float(getattr(body, "width", 0) or 0)
        h = float(getattr(body, "height", 0) or 0)
        cfg = {
            "width": w,
            "height": h,
            "productType": getattr(body, "productType", None) or "louvers",
            "category": getattr(body, "category", None) or "Louvers",
            "panelFill": panel_fill if isinstance(panel_fill, dict) else {"fillType": "louvers"},
        }
        return {
            "svg": louver_svg(cfg),
            "system": "louver",
            "productType": "louvers",
            "specifications": {
                "type": "Louvers",
                "size": f"{w:g} x {h:g} mm" if w and h else "",
                "blade": "Aluminium louver blades",
            },
            "layout": {"system": "louver", "widthMm": w, "heightMm": h, "trackCount": None},
            "sectionSpecs": {},
        }
    if (
        world == "pergola"
        or is_pergola_product_type(getattr(body, "productType", None))
        or "pergola" in prod
        or "pergola" in str(getattr(body, "category", "") or "").lower()
    ):
        from WEOS.factory.special_schematics import pergola_svg

        w = float(getattr(body, "width", 0) or 0)
        h = float(getattr(body, "height", 0) or 0)
        cfg = {
            "width": w,
            "height": h,
            "productType": "pergolas",
            "category": "Pergolas",
        }
        return {
            "svg": pergola_svg(cfg),
            "system": "pergola",
            "productType": "pergolas",
            "specifications": {
                "type": "Pergola",
                "size": f"{w:g} x {h:g} mm" if w and h else "",
                "fixing": "Floor / wall / garden as specified",
                "materials": "Posts, rafters, louvers / glass / polycarbonate",
            },
            "layout": {"system": "pergola", "widthMm": w, "heightMm": h, "trackCount": None},
            "sectionSpecs": {},
        }
    if (
        world == "surface"
        or any(x in prod for x in ("acp", "hpl", "fluted", "perforated", "cladding", "facade"))
        or any(x in str(getattr(body, "category", "") or "").lower() for x in ("acp", "hpl", "facade", "cladding"))
    ):
        from WEOS.factory.special_schematics import surface_svg

        w = float(getattr(body, "width", 0) or 0)
        h = float(getattr(body, "height", 0) or 0)
        cfg = {
            "width": w,
            "height": h,
            "product": getattr(body, "product", None) or "surface",
            "productType": getattr(body, "productType", None) or "surface",
            "category": getattr(body, "category", None) or "Facades",
            "displayName": "ACP Cladding" if "acp" in prod else "Surface panel",
        }
        return {
            "svg": surface_svg(cfg),
            "system": "surface",
            "productType": getattr(body, "productType", None) or "surface",
            "specifications": {
                "type": cfg["displayName"],
                "size": f"{w:g} x {h:g} mm" if w and h else "",
                "material": "Facade panel as specified",
            },
            "layout": {"system": "surface", "widthMm": w, "heightMm": h, "trackCount": None},
            "sectionSpecs": {},
        }
    try:
        from WEOS.factory.layout_options import resolve_mesh_track
        from WEOS.factory.product_loader import load_product, resolve_engine_product_id
        from WEOS.factory.svg_export import layout_summary_for_job

        meta = load_product(body.product, strict=False)
        # Catalogue/imported (stub) products now carry a synthesised renderable
        # geometry (see product_loader._ensure_renderable), so we draw a real
        # elevation instead of a placeholder. We only fall back to the catalogue
        # image if the product genuinely cannot be rendered.
        is_stub = bool(meta.get("_stub") or meta.get("status") == "stub")
        # Catalogue products are their own section series — use that when the
        # optional Series dropdown is empty so track/mesh resolution still works.
        section_series = body.sectionSeries or meta.get("sectionSeries") or (
            body.product if is_stub else None
        )
        series_doc = None
        if section_series:
            try:
                from WEOS.factory.section_catalogue import get_series

                series_doc = get_series(str(section_series))
            except Exception:
                series_doc = None
        mesh_res = resolve_mesh_track(
            mesh=bool(body.mesh),
            track_count=body.trackCount,
            series=series_doc,
        )
        engine_ids = [body.product]
        linked = resolve_engine_product_id(meta, body.product)
        if linked and linked not in engine_ids:
            engine_ids.append(linked)
        if "29mm_sliding" not in engine_ids and is_stub:
            cat = str(getattr(body, "category", "") or meta.get("category") or "").lower()
            ptype = str(getattr(body, "productType", None) or meta.get("productType") or "").lower()
            skip_window_engine = (
                world in ("louver", "pergola", "surface", "railing", "staircase_railing", "shower", "ventilator")
                or "louver" in prod or "louvre" in prod or "facade" in prod or "facade" in cat
                or "rail" in prod or "shower" in prod or "ventilat" in prod or "pergola" in prod
                or "louver" in ptype or "louvre" in ptype or "pergola" in ptype
            )
            if not skip_window_engine:
                engine_ids.append("29mm_sliding")

        last_exc: Exception | None = None
        job = None
        for engine_id in engine_ids:
            try:
                job = generate_job(
                    body.width,
                    body.height,
                    engine_id,
                    glass=body.glass,
                    colour=body.colour,
                    handle=body.handle,
                    partitions=body.partitions,
                    mesh=bool(body.mesh),
                    track_count=mesh_res["trackCount"],
                    section_series=section_series,
                    glass_count=body.glassShutters,
                    mesh_count=body.meshShutters,
                    opening=body.opening,
                    opening_side=getattr(body, "openingSide", None),
                    opening_explicit=bool(getattr(body, "openingExplicit", False)),
                    fixed_shutters=body.fixShutters,
                    system=body.system or "sliding",
                    fold_left=body.foldLeft,
                    fold_right=body.foldRight,
                    section_sizes=body.sectionSizes,
                    handle_finish=body.handleFinish,
                    handle_level=body.handleLevel,
                    handle_overrides=body.handleOverrides,
                    grid=body.grid if str(body.system or "").lower() == "grid" else None,
                    sash_overlap_mm=getattr(body, "sashOverlapMm", None),
                    mullion_gap_mm=getattr(body, "mullionGapMm", None),
                    frame_material=getattr(body, "frameMaterial", None),
                )
                break
            except Exception as exc:  # try next engine id
                last_exc = exc
                job = None
        if job is None:
            raise last_exc or RuntimeError("preview generate_job failed")
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
        colour_raw = str(body.colour or "white")
        svg = render_svg_string(
            job.drawing,
            colour=colour_raw.lower().replace(" ", "_"),
            annotations=True,
            include_plan=True,
            grid=body.grid if str(body.system or "").lower() != "grid" else None,
        )
        layout = layout_summary_for_job(
            width=body.width, height=body.height, layout_meta=job.layout_meta
        )
        glass_shutters = job.layout_meta.get("glass_count")
        if glass_shutters is None:
            glass_shutters = body.glassShutters
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
            "system": job.layout_meta.get("system") or body.system or "sliding",
            "glassShutters": glass_shutters,
            "meshShutters": job.layout_meta.get("mesh_count"),
            "foldLeft": job.layout_meta.get("fold_left"),
            "foldRight": job.layout_meta.get("fold_right"),
            "notes": job.layout_meta.get("notes"),
            "heroImage": meta.get("heroImage"),
            "specifications": meta.get("specifications"),
            "sectionSeries": section_series,
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
                "system": body.system or "sliding",
                "glassShutters": body.glassShutters,
                "meshShutters": body.meshShutters,
                "trackCount": body.trackCount,
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
    request: Request,
    q: str | None = None,
    status: str | None = None,
    sort: str = "updatedAt",
    order: str = "desc",
    gst: str | None = None,
    fy: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    from WEOS.factory.company_index import query_projects
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, gst)
    packed = query_projects(
        g,
        q=q,
        status=status,
        fy=fy or "current",
        include_archived=status == "archived",
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return {
        "projects": packed.get("items") or [],
        "total": packed.get("total") or 0,
        "fy": packed.get("fy"),
        "availableFy": packed.get("availableFy") or [],
        "limit": packed.get("limit"),
        "offset": packed.get("offset") or 0,
        "hasMore": bool(packed.get("hasMore")),
    }


@app.post("/api/projects")
def api_create_project(body: ProjectCreate) -> dict[str, Any]:
    doc = empty_project(name=body.name, customer=body.customer)
    doc["status"] = body.status or "draft"
    doc["lines"] = _coerce_cart_lines(body.lines)
    for _fld in ("customerMobile", "customerAddress", "customerGst", "description", "terms", "quotationId", "companyGst"):
        _val = getattr(body, _fld, None)
        if _val is not None:
            doc[_fld] = _val
    from WEOS.factory.package_quote import apply_package_fields

    dumped = body.model_dump(exclude_none=True)
    apply_package_fields(doc, dumped)
    if dumped.get("quoteDiscount") is not None:
        doc["quoteDiscount"] = dumped["quoteDiscount"]
    try:
        return save_project(doc, action="create")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory.project_store import _belongs_to_company

    g = require_company_gst(request, gst)
    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not _belongs_to_company(doc, g, include_unscoped=False):
        raise HTTPException(status_code=404, detail="Project not found")
    return doc


@app.post("/api/projects/{project_id}/follow-up")
def api_project_follow_up(
    project_id: str,
    body: FollowUpBody,
    request: Request,
    gst: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_dashboard import record_follow_up
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, gst)
    try:
        return record_follow_up(project_id, channel=body.channel, company_gst=g)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/projects/{project_id}")
def api_update_project(project_id: str, body: ProjectUpdate) -> dict[str, Any]:
    try:
        doc = load_project(project_id)
    except FileNotFoundError:
        # Stale browser id (deleted / never persisted / merged away) — start a new job.
        doc = empty_project(name=body.name or "WEOS Project", customer=body.customer or "")
        doc["status"] = body.status or "draft"
    if body.name is not None:
        doc["name"] = body.name
    if body.customer is not None:
        doc["customer"] = body.customer
    if body.status is not None:
        doc["status"] = body.status
    if body.lines is not None:
        incoming = _coerce_cart_lines(body.lines, existing=doc.get("lines"))
        # Never persist an accidental empty wipe over a non-empty cart.
        if incoming or not (doc.get("lines") or []):
            doc["lines"] = incoming
        else:
            _log.warning("PUT %s ignored empty lines (saved cart has %s rows)", project_id, len(doc.get("lines") or []))
    for _fld in ("customerMobile", "customerAddress", "customerGst", "description", "terms", "quotationId", "companyGst"):
        _val = getattr(body, _fld, None)
        if _val is not None:
            doc[_fld] = _val
    dumped = body.model_dump(exclude_unset=True)
    from WEOS.factory.package_quote import apply_package_fields

    apply_package_fields(doc, dumped)
    if "quoteDiscount" in dumped:
        doc["quoteDiscount"] = dumped.get("quoteDiscount")
    try:
        return save_project(doc, action="update")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/ledger/master")
def api_master_ledger_search(
    q: str | None = Query(None),
    projectId: str | None = Query(None),
    gst: str | None = Query(None),
) -> dict[str, Any]:
    from WEOS.factory.master_ledger import build_master_ledger

    try:
        return build_master_ledger(q=q, project_id=projectId, company_gst=gst)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/master-ledger")
def api_project_master_ledger(project_id: str, gst: str | None = Query(None)) -> dict[str, Any]:
    from WEOS.factory.master_ledger import build_master_ledger

    try:
        return build_master_ledger(project_id=project_id, company_gst=gst)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/package-quotes")
def api_append_package_quote(
    project_id: str,
    body: PackageQuoteBody,
    gst: str | None = Query(None),
) -> dict[str, Any]:
    """Append an outside / finalized quote onto an existing job. Cart lines stay."""
    from WEOS.factory.master_ledger import build_master_ledger
    from WEOS.factory.package_quote import MAX_QUOTES, apply_package_fields, normalize_package_quote
    from WEOS.factory.project_store import load_project, save_project

    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    quotes = list(doc.get("packageQuotes") or [])
    incoming = body.model_dump(exclude_none=True)
    q = normalize_package_quote(incoming, index=len(quotes), project_id=project_id)
    if not q:
        raise HTTPException(status_code=400, detail="Enter at least one item amount")
    from WEOS.factory.package_quote import merge_package_quotes

    merged = merge_package_quotes(quotes, [q], project_id=project_id)
    if merged.get("skippedCount") and not merged.get("addedCount") and not merged.get("updatedCount"):
        raise HTTPException(status_code=409, detail="This outside quote is already on the project — not added again")
    quotes = merged.get("quotes") or quotes
    if len(quotes) > MAX_QUOTES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_QUOTES} outside quotes on one project")
    apply_package_fields(doc, {"packageQuotes": quotes, "masterJobId": doc.get("masterJobId") or project_id})
    saved = save_project(doc, action="package_quote_add")
    wrap: dict[str, Any] = {}
    try:
        wrap = build_master_ledger(project_id=project_id, company_gst=gst)
    except Exception:
        wrap = {}
    return {"ok": True, "quote": q, "projectId": saved.get("projectId"), "ledger": wrap.get("ledger")}


@app.post("/api/projects/{project_id}/package-quotes/{quote_id}/file")
async def api_package_quote_file(
    project_id: str,
    quote_id: str,
    file: UploadFile = File(...),
    kind: str | None = Query(None),
    gst: str | None = Query(None),
) -> dict[str, Any]:
    from WEOS.factory.master_ledger import build_master_ledger
    from WEOS.factory.package_quote import MAX_ATTACHMENTS, apply_package_fields, store_package_file
    from WEOS.factory.project_store import load_project, save_project

    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if gst:
        wrap = build_master_ledger(project_id=project_id, company_gst=gst)
        if not wrap.get("ledger"):
            raise HTTPException(status_code=403, detail="Project is not in this company workspace")
    qid = str(quote_id or "").strip()
    if not qid:
        raise HTTPException(status_code=400, detail="Quote id required")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 8 MB)")
    fname = str(file.filename or "quote").strip() or "quote"
    att = store_package_file(
        project_id=project_id,
        quote_id=qid,
        raw=raw,
        filename=fname,
        content_type=file.content_type,
        kind_hint=kind,
    )
    quotes = list(doc.get("packageQuotes") or [])
    hit = False
    for pq in quotes:
        if str(pq.get("id")) != qid:
            continue
        files = list(pq.get("attachments") or [])
        files.append(att)
        pq["attachments"] = files[:MAX_ATTACHMENTS]
        if att.get("kind") == "quote_pdf" or not pq.get("attachmentName"):
            pq["attachmentName"] = att.get("filename")
            pq["attachmentKey"] = att.get("key")
        hit = True
    if hit:
        apply_package_fields(doc, {"packageQuotes": quotes})
        save_project(doc, bump_version=False, action="package_quote_file")
    return {"ok": True, "quoteId": qid, "attachment": att, "filename": fname, "url": att.get("url")}


@app.get("/api/projects/{project_id}/package-quotes/{quote_id}/files/{file_id}")
def api_get_package_quote_file_id(project_id: str, quote_id: str, file_id: str) -> Response:
    from WEOS.factory.package_quote import load_package_file
    from WEOS.factory.project_store import load_project

    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raw, ctype, fname = load_package_file(project_id, quote_id, file_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="No file attached")
    headers = {"Content-Disposition": f'inline; filename="{fname or "file"}"'}
    return Response(content=raw, media_type=ctype or "application/octet-stream", headers=headers)


@app.get("/api/projects/{project_id}/package-quotes/{quote_id}/file")
def api_get_package_quote_file(project_id: str, quote_id: str) -> Response:
    from WEOS.factory.package_quote import load_package_file
    from WEOS.factory.project_store import load_project

    try:
        load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raw, ctype, fname = load_package_file(project_id, quote_id, None)
    if raw is None:
        raise HTTPException(status_code=404, detail="No file attached")
    headers = {"Content-Disposition": f'inline; filename="{fname or "quote"}"'}
    return Response(content=raw, media_type=ctype or "application/octet-stream", headers=headers)


@app.delete("/api/projects/{project_id}")
def api_delete_project(
    project_id: str,
    hard: bool = Query(False),
    gst: str | None = None,
    pin: str | None = None,
    confirm: str | None = None,
) -> dict[str, Any]:
    from WEOS.factory.company_quotes import delete_company_quote, require_delete_confirm
    from WEOS.factory.company_store import get_active_gst, load_company, normalise_gstin

    g = normalise_gstin(gst) if gst else (get_active_gst() or "")
    if not g:
        g = normalise_gstin((load_company() or {}).get("gstNo") or "")
    if hard or g:
        try:
            require_delete_confirm(project_id, company_gst=g or None, pin=pin, confirm=confirm)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if g:
        try:
            return delete_company_quote(project_id, company_gst=g, hard=hard)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return delete_project(project_id, hard=hard)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/delete")
def api_delete_project_post(project_id: str, body: QuoteDeleteBody) -> dict[str, Any]:
    """PIN-confirmed hard delete (Saved Projects)."""
    return api_delete_project(
        project_id,
        hard=body.hard,
        gst=body.gstNo,
        pin=body.pin,
        confirm=body.confirm,
    )


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


@app.post("/api/projects/{project_id}/status")
def api_project_set_status(project_id: str, body: ProjectStatusBody) -> dict[str, Any]:
    """Mark a project/quote status (draft → approved → rejected/cancelled)."""
    from WEOS.factory.project_store import set_project_status

    try:
        return set_project_status(project_id, body.status)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/approve")
def api_project_approve(project_id: str) -> dict[str, Any]:
    from WEOS.factory.project_store import set_project_status

    try:
        return set_project_status(project_id, "approved", source="admin", by_name="Admin")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/reject")
def api_project_reject(project_id: str, body: QuoteRejectBody | None = None) -> dict[str, Any]:
    """Un-approve: status=rejected, excluded from turnover; history + advances kept."""
    body = body or QuoteRejectBody()
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirm reject to un-approve this quote.")
    from WEOS.factory.project_store import load_project, set_project_status

    try:
        doc = set_project_status(project_id, "rejected", source="admin", by_name="Admin", note=body.note)
        if body.note:
            try:
                live = load_project(project_id)
                live["rejectNote"] = str(body.note).strip()
                from WEOS.factory.project_store import save_project

                doc = save_project(live, bump_version=False, action="reject_note")
            except Exception:
                pass
        return doc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/pack")
def api_project_pack(project_id: str, gst: str | None = Query(None)) -> dict[str, Any]:
    from WEOS.factory.project_pack import list_pack

    try:
        return list_pack(project_id, company_gst=gst)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/pack/updates")
def api_project_pack_update(project_id: str, body: PackUpdateBody, gst: str | None = Query(None)) -> dict[str, Any]:
    from WEOS.factory.project_pack import add_update

    try:
        item = add_update(
            project_id,
            body.text,
            date=body.date,
            company_gst=gst or body.gstNo,
        )
        return {"ok": True, "item": item}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/pack/files")
async def api_project_pack_file(
    project_id: str,
    file: UploadFile = File(...),
    kind: str = Query("photo"),
    note: str | None = Query(None),
    date: str | None = Query(None),
    gst: str | None = Query(None),
) -> dict[str, Any]:
    from WEOS.factory.project_pack import add_file

    raw = await file.read()
    try:
        item = add_file(
            project_id,
            kind=kind,
            raw=raw,
            filename=file.filename,
            content_type=file.content_type,
            note=note,
            date=date,
            company_gst=gst,
        )
        return {"ok": True, "item": item}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}/pack/{item_id}")
def api_project_pack_delete(project_id: str, item_id: str, gst: str | None = Query(None)) -> dict[str, Any]:
    from WEOS.factory.project_pack import delete_item

    try:
        return delete_item(project_id, item_id, company_gst=gst)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/pack/files/{item_id}")
def api_project_pack_get_file(project_id: str, item_id: str) -> Response:
    from WEOS.factory.project_pack import get_file

    raw, ct, fname, item = get_file(project_id, item_id)
    if not raw:
        raise HTTPException(status_code=404, detail="File not found")
    name = fname or (item or {}).get("filename") or "file"
    return Response(
        content=raw,
        media_type=ct or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


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
    persist = True if body is None else bool(getattr(body, "persist", True))
    if body is not None and body.quotationId:
        doc["quotationId"] = body.quotationId
    if body is not None and body.lines is not None:
        doc["lines"] = _coerce_cart_lines(body.lines, existing=doc.get("lines"), keep_preview_svg=True)
    # Live canvas uses /api/preview + designer quotes — do not regenerate SVG here.
    result = calculate_project(doc, optimize=optimize, include_preview=False)
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
    saved = doc
    if persist:
        try:
            saved = save_project(doc, action="calculate")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    # If quote-number versioning folded into another project, surface the live id.
    live_id = saved.get("projectId") or project_id
    if persist:
        try:
            from WEOS.learning.commercial_agent import observe_quote
            from WEOS.learning.engineering_agent import observe_engineering
            from WEOS.factory.customer_rates import save_quote_line_rates

            lines = result.get("lines") or []
            observe_quote(
                customer=doc.get("customer"),
                project_id=live_id,
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
                project_id=live_id,
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
        "projectId": saved.get("projectId"),
        "version": saved.get("version"),
        "name": saved.get("name"),
        "status": saved.get("status"),
        "quoteNumberVersioned": bool(saved.get("quoteNumberVersioned")),
    }
    result["projectId"] = saved.get("projectId")
    result["version"] = saved.get("version")
    result["quoteNumberVersioned"] = bool(saved.get("quoteNumberVersioned"))
    result["links"] = {
        "quotation": f"/api/projects/{live_id}/quotation",
        "customerPdf": f"/api/projects/{live_id}/customer-pdf",
        "factoryPdf": f"/api/projects/{live_id}/factory-pdf",
    }
    return result


@app.get("/api/projects/{project_id}/quotation")
def api_quotation(project_id: str) -> dict[str, Any]:
    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = calculate_project(doc, optimize=True, include_preview=False)
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
        # Inline so Print / scan / browser open the same A4 quote PDF (not a download).
        return _pdf_response(project_id, "customer", brand=brand, template_id=templateId, request=request, inline=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/customer-pdf")
def api_customer_pdf_post(
    project_id: str,
    request: Request,
    body: PdfExportBody | None = None,
    brand: str | None = Query(None),
    templateId: str | None = Query(None),
) -> Response:
    try:
        overlay = (body.model_dump() if body is not None else {}) or {}
        return _pdf_response(
            project_id,
            "customer",
            brand=brand or overlay.get("brand"),
            template_id=templateId or overlay.get("templateId"),
            request=request,
            overlay=overlay,
        )
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


@app.post("/api/projects/{project_id}/factory-pdf")
def api_factory_pdf_post(
    project_id: str,
    request: Request,
    body: PdfExportBody | None = None,
    brand: str | None = Query(None),
    templateId: str | None = Query(None),
) -> Response:
    try:
        overlay = (body.model_dump() if body is not None else {}) or {}
        return _pdf_response(
            project_id,
            "factory",
            brand=brand or overlay.get("brand"),
            template_id=templateId or overlay.get("templateId"),
            request=request,
            overlay=overlay,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/lines/{line_id}/design-photo")
async def api_upload_design_photo(
    project_id: str,
    line_id: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    from WEOS.factory.design_photo import save_design_photo
    from WEOS.factory.project_store import load_project, save_project

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")
    try:
        info = save_design_photo(
            project_id,
            line_id,
            raw,
            filename=file.filename,
            content_type=file.content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        doc = load_project(project_id)
        for ln in doc.get("lines") or []:
            if isinstance(ln, dict) and str(ln.get("lineId") or "") == str(line_id):
                ln["designPhoto"] = {
                    "key": info.get("key"),
                    "url": info.get("url"),
                    "contentType": info.get("contentType"),
                    "filename": info.get("filename"),
                }
                break
        else:
            # Line not saved yet — still return the blob ref for the cart to attach.
            pass
        save_project(doc, action="design-photo")
    except FileNotFoundError:
        pass
    except Exception:
        _log.exception("design photo project attach failed")
    return info


@app.get("/api/projects/{project_id}/lines/{line_id}/design-photo")
def api_get_design_photo(project_id: str, line_id: str) -> Response:
    from WEOS.factory.design_photo import design_photo_bytes

    raw, mime = design_photo_bytes(project_id, line_id)
    if not raw:
        raise HTTPException(status_code=404, detail="No design photo uploaded")
    return Response(content=raw, media_type=mime or "image/jpeg")


@app.delete("/api/projects/{project_id}/lines/{line_id}/design-photo")
def api_delete_design_photo(project_id: str, line_id: str) -> dict[str, Any]:
    from WEOS.factory.design_photo import delete_design_photo
    from WEOS.factory.project_store import load_project, save_project

    ok = delete_design_photo(project_id, line_id)
    try:
        doc = load_project(project_id)
        for ln in doc.get("lines") or []:
            if isinstance(ln, dict) and str(ln.get("lineId") or "") == str(line_id):
                ln.pop("designPhoto", None)
                if isinstance(ln.get("options"), dict):
                    ln["options"].pop("designPhoto", None)
        save_project(doc, action="design-photo-clear")
    except Exception:
        _log.exception("design photo clear on project failed")
    return {"ok": ok}


def _public_ledger_html(record: dict[str, Any], request: Request) -> HTMLResponse:
    from WEOS.factory.ledger_pdf import render_ledger_html
    from WEOS.factory.ledger_store import build_ledger

    cust = ((record.get("customer") or {}).get("name") or "").strip()
    if not cust:
        raise HTTPException(status_code=404, detail="No customer on this quote")
    gst = ((record.get("company") or {}).get("gstNo") or "").strip() or None
    try:
        ledger = build_ledger(cust, company_gst=gst)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        ledger = build_ledger(cust)
    co = dict(record.get("company") or {})
    if co.get("name") and not co.get("companyName"):
        co["companyName"] = co["name"]
    html = render_ledger_html(ledger, co, base_url=_public_base_url(request))
    return HTMLResponse(html)


# Back-compat aliases
@app.get("/api/projects/{project_id}/pdf/customer")
def api_pdf_customer_alias(project_id: str, request: Request, brand: str | None = Query(None)) -> Response:
    return api_customer_pdf(project_id, request, brand=brand)


@app.get("/api/projects/{project_id}/pdf/factory")
def api_pdf_factory_alias(project_id: str, request: Request, brand: str | None = Query(None)) -> Response:
    return api_factory_pdf(project_id, request, brand=brand)


def _public_scan_response(ref: str, request: Request, *, fmt: str | None = None) -> Response:
    """Live public quote page (HTML) or optional PDF download."""
    from WEOS.factory.quote_share import build_public_quote_record, render_scan_html

    base = _public_base_url(request)
    kind = (fmt or "").strip().lower()
    want_pdf = kind in ("pdf", "download", "file")
    want_all = kind in ("all", "pack", "allpdf")
    want_ledger = kind in ("ledger", "account")
    record = build_public_quote_record(ref)
    if record and want_ledger:
        # Advance-slip QR must stay scoped to this project/quote token. Do not
        # expose the full customer ledger with other projects on a public scan.
        html = render_scan_html(record, base_url=base)
        return HTMLResponse(html)
    if record and want_all:
        from WEOS.factory.scan_all_pdf import render_scan_all_pdf

        pdf = render_scan_all_pdf(record)
        qn = str(record.get("quoteNumber") or ref or "quote").replace("/", "-")
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{qn}_all.pdf"'},
        )
    if record and not want_pdf:
        html = render_scan_html(record, base_url=base)
        return HTMLResponse(html)
    if record and want_pdf:
        pid = str(record.get("projectId") or "").strip()
        if pid:
            try:
                return _pdf_response(pid, "customer", request=request, inline=True)
            except FileNotFoundError:
                pass
    # Legacy: quote_store / project id PDF fallback when live HTML cannot build.
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
            "quoteRef": q.get("shareToken") or q.get("quoteNumber") or q.get("quoteId") or ref,
            "shareToken": q.get("shareToken"),
            "customer": cust_name,
            "name": "",
            "brand": q.get("brand") or "marqt",
            "templateId": q.get("templateId") or "marqt_customer",
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
    try:
        return _pdf_response(ref, "customer", request=request, inline=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Quote not found: {ref}") from exc


@app.get("/q/{ref}/ledger")
@app.get("/scan/{ref}/ledger")
def public_quote_ledger(ref: str, request: Request) -> Response:
    """Public customer ledger HTML (card layout, same language as scan)."""
    return _public_scan_response(ref, request, fmt="ledger")


@app.get("/q/{ref}/access/{access_token}")
@app.get("/scan/{ref}/access/{access_token}")
def public_quote_access(ref: str, access_token: str, request: Request, last6: str | None = Query(None)) -> Response:
    """Protected read-only monitor link for architects/site/accounts."""
    from WEOS.factory.quote_share import (
        build_public_quote_record,
        public_monitor_access_meta,
        render_access_verify_html,
        render_scan_html,
        verify_monitor_access,
    )

    if not last6:
        rec = build_public_quote_record(ref)
        grant = public_monitor_access_meta(ref, access_token)
        return HTMLResponse(render_access_verify_html(rec, ref=ref, access_token=access_token, grant=grant))
    try:
        rec = verify_monitor_access(ref, access_token, last6=last6)
    except FileNotFoundError as exc:
        rec = build_public_quote_record(ref)
        grant = public_monitor_access_meta(ref, access_token)
        return HTMLResponse(render_access_verify_html(rec, ref=ref, access_token=access_token, grant=grant, message=str(exc)), status_code=404)
    except PermissionError as exc:
        rec = build_public_quote_record(ref)
        grant = public_monitor_access_meta(ref, access_token)
        return HTMLResponse(render_access_verify_html(rec, ref=ref, access_token=access_token, grant=grant, message=str(exc)), status_code=403)
    except ValueError as exc:
        rec = build_public_quote_record(ref)
        grant = public_monitor_access_meta(ref, access_token)
        return HTMLResponse(render_access_verify_html(rec, ref=ref, access_token=access_token, grant=grant, message=str(exc)), status_code=400)
    return HTMLResponse(render_scan_html(rec, base_url=_public_base_url(request)))


@app.get("/q/{ref}/all.pdf")
@app.get("/scan/{ref}/all.pdf")
@app.get("/api/public/quote/{ref}/all.pdf")
def public_quote_all_pdf(ref: str, request: Request) -> Response:
    """Single-click A4 PDF of the live scan page (quote + pack)."""
    return _public_scan_response(ref, request, fmt="all")


@app.get("/q/{ref}")
def public_quote(ref: str, request: Request, format: str | None = Query(None)) -> Response:
    """Public QR target: live project record (HTML). ``?format=pdf`` downloads PDF."""
    return _public_scan_response(ref, request, fmt=format)


@app.get("/scan/{ref}")
def public_scan(ref: str, request: Request, format: str | None = Query(None)) -> Response:
    """Alias for ``/q/{token}`` — stable public scan URL."""
    return _public_scan_response(ref, request, fmt=format)


@app.get("/api/public/quote/{ref}")
def api_public_quote(ref: str) -> dict[str, Any]:
    """JSON live quote for the public scan page (no login)."""
    from WEOS.factory.quote_share import build_public_quote_record

    rec = build_public_quote_record(ref)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Quote not found: {ref}")
    return rec


class PublicScanDecideBody(BaseModel):
    confirm: bool = False
    name: str | None = None
    mobile: str | None = None
    verifyLast6: str | None = None
    note: str | None = None


class PublicMonitorAccessBody(BaseModel):
    role: str
    name: str
    mobile: str
    grantedByName: str | None = None
    customerLast6: str | None = None
    showDesign: bool = True
    showRate: bool = False
    showAmount: bool = False
    showAdvances: bool = True
    allowPdf: bool = False


@app.post("/api/public/quote/{ref}/approve")
def api_public_quote_approve(ref: str, body: PublicScanDecideBody | None = None) -> dict[str, Any]:
    """QR scanner approve — only within 15 days of generate date."""
    from WEOS.factory.quote_share import apply_scanner_status, build_public_quote_record

    body = body or PublicScanDecideBody()
    try:
        apply_scanner_status(
            ref,
            "approved",
            name=body.name,
            mobile=body.mobile,
            verify_last6=body.verifyLast6,
            note=body.note,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rec = build_public_quote_record(ref)
    if not rec:
        raise HTTPException(status_code=404, detail="Quote not found")
    return rec


@app.post("/api/public/quote/{ref}/reject")
def api_public_quote_reject(ref: str, body: PublicScanDecideBody | None = None) -> dict[str, Any]:
    """QR scanner reject — only within 7 days of generate date."""
    from WEOS.factory.quote_share import apply_scanner_status, build_public_quote_record

    body = body or PublicScanDecideBody()
    try:
        apply_scanner_status(
            ref,
            "rejected",
            confirm_reject=bool(body.confirm),
            name=body.name,
            mobile=body.mobile,
            verify_last6=body.verifyLast6,
            note=body.note,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rec = build_public_quote_record(ref)
    if not rec:
        raise HTTPException(status_code=404, detail="Quote not found")
    return rec


@app.post("/api/public/quote/{ref}/access")
def api_public_quote_access(ref: str, body: PublicMonitorAccessBody, request: Request) -> dict[str, Any]:
    """Customer-scanner grants a protected read-only monitor link."""
    from WEOS.factory.quote_share import add_monitor_access

    try:
        out = add_monitor_access(
            ref,
            role=body.role,
            name=body.name,
            mobile=body.mobile,
            granted_by_name=body.grantedByName,
            customer_last6=body.customerLast6,
            permissions={
                "design": body.showDesign,
                "rate": body.showRate,
                "amount": body.showAmount,
                "advances": body.showAdvances,
                "pdf": body.allowPdf,
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    base = _public_base_url(request).rstrip("/")
    if out.get("accessPath"):
        out["accessUrl"] = base + str(out["accessPath"])
    return out


@app.get("/api/public/quote/{ref}/pack/files/{item_id}")
def api_public_pack_file(ref: str, item_id: str) -> Response:
    """Public download of an approved project-pack file (bill / warranty / photo)."""
    from WEOS.factory.project_pack import get_file
    from WEOS.factory.quote_share import build_public_quote_record

    rec = build_public_quote_record(ref)
    if not rec:
        raise HTTPException(status_code=404, detail="Quote not found")
    pid = str(rec.get("projectId") or "").strip()
    if not pid:
        raise HTTPException(status_code=404, detail="No project on this quote")
    raw, ct, fname, item = get_file(pid, item_id)
    if not raw:
        raise HTTPException(status_code=404, detail="File not found")
    name = fname or (item or {}).get("filename") or "file"
    return Response(
        content=raw,
        media_type=ct or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


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


@app.post("/api/projects/import-pack")
async def api_projects_import_pack(
    files: list[UploadFile] = File(...),
    customer: str = Form(""),
    customerMobile: str = Form(""),
    customerAddress: str = Form(""),
    customerGst: str = Form(""),
    projectName: str = Form(""),
    quotationId: str = Form(""),
    projectId: str = Form(""),
    commit: str = Form("false"),
    importAdvances: str = Form("true"),
    gst: str = Form(""),
) -> dict[str, Any]:
    """Preview or save a multi-stage Excel/PDF job as one project + account."""
    from WEOS.factory.project_import import commit_imported_project, merge_previews, parse_upload, plan_import_merge

    packs: list[dict[str, Any]] = []
    errors: list[str] = []
    if not files:
        raise HTTPException(status_code=400, detail="Upload an Excel or PDF of the project")
    for up in files[:6]:
        raw = await up.read()
        fname = str(up.filename or "project").strip() or "project"
        if not raw:
            errors.append(f"{fname}: empty file")
            continue
        if len(raw) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"{fname} is too large (max 25 MB)")
        try:
            packs.append(parse_upload(fname, raw))
        except Exception as exc:
            errors.append(f"{fname}: {exc}")
    if not packs:
        raise HTTPException(status_code=400, detail="; ".join(errors) or "Could not read the file")
    preview = merge_previews(*packs)
    preview["parseWarnings"] = errors
    pid = (projectId or "").strip()
    if pid:
        from WEOS.factory.project_store import load_project

        try:
            existing_doc = load_project(pid)
            preview["merge"] = plan_import_merge(
                existing_doc.get("packageQuotes") or [],
                preview.get("quotes") or [],
                project_id=pid,
            )
            preview["merge"].pop("quotes", None)
        except FileNotFoundError:
            preview["merge"] = None
    do_commit = str(commit or "").strip().lower() in {"1", "true", "yes", "on"}
    if not do_commit:
        preview["ok"] = True
        preview["committed"] = False
        return preview
    try:
        saved = commit_imported_project(
            preview,
            customer=customer,
            customer_mobile=customerMobile or None,
            customer_address=customerAddress or None,
            customer_gst=customerGst or None,
            project_name=projectName or None,
            quotation_id=quotationId or None,
            project_id=(projectId or "").strip() or None,
            company_gst=(gst or "").strip() or None,
            import_advances=str(importAdvances or "true").strip().lower() not in {"0", "false", "no", "off"},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved["preview"] = {
        "quoteCount": preview.get("quoteCount"),
        "advanceCount": preview.get("advanceCount"),
        "projectValue": saved.get("projectValue") or preview.get("projectValue"),
        "advanceTotal": preview.get("advanceTotal"),
        "balance": preview.get("balance"),
        "stages": preview.get("stages"),
        "parseWarnings": errors,
        "merge": {
            "added": saved.get("added") or [],
            "skipped": saved.get("skipped") or [],
            "updated": saved.get("updated") or [],
            "addedCount": saved.get("addedCount") or 0,
            "skippedCount": saved.get("skippedCount") or 0,
            "updatedCount": saved.get("updatedCount") or 0,
            "quoteCountAfter": saved.get("quoteCount"),
        },
        "advanceSkipped": saved.get("advanceSkipped") or 0,
    }
    saved["committed"] = True
    return saved


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


# ── Company Setup / GST workspace ────────────────────────────────────────────

@app.get("/api/company")
def api_get_company(request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory.company_store import load_company_by_gst, public_company_profile
    from WEOS.factory.company_workspace import require_company_gst

    try:
        g = require_company_gst(request, gst)
    except HTTPException:
        return {"ok": False, "loggedIn": False, "companyName": "", "gstNo": ""}
    return public_company_profile(load_company_by_gst(g) or {})


@app.put("/api/company")
@app.post("/api/company")
def api_save_company(body: CompanyBody) -> dict[str, Any]:
    from WEOS.factory.company_store import save_company

    return save_company(body.model_dump(exclude_none=True))


class CompanyWorkspaceOpenBody(BaseModel):
    """JSON body for POST /api/company/workspace/open (login or session restore)."""

    model_config = {"extra": "allow"}

    login: str | None = None
    gstNo: str | None = None
    pin: str | None = None
    sessionToken: str | None = None
    create: bool = True
    companyName: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    tagline: str | None = None
    state: str | None = None
    stateCode: str | None = None
    pan: str | None = None
    bankDetails: str | None = None
    cin: str | None = None
    terms: str | None = None


@app.post("/api/company/workspace/open")
def api_company_workspace_open(body: CompanyWorkspaceOpenBody) -> dict[str, Any]:
    """Seller login: GST / company name / mobile + 4-digit PIN (or session)."""
    from WEOS.factory.company_workspace import open_workspace

    dumped = body.model_dump(exclude_none=True)
    gst = dumped.pop("gstNo", None)
    create = bool(dumped.pop("create", True))
    pin = dumped.pop("pin", None)
    session_token = dumped.pop("sessionToken", None)
    login = dumped.pop("login", None)
    try:
        return open_workspace(
            str(gst or "") or None,
            profile=dumped or None,
            create=create,
            pin=pin,
            session_token=session_token,
            login=login,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


class CompanyWorkspaceLogoutBody(BaseModel):
    gstNo: str | None = None
    sessionToken: str | None = None


@app.post("/api/company/workspace/logout")
def api_company_workspace_logout(body: CompanyWorkspaceLogoutBody | None = None) -> dict[str, Any]:
    from WEOS.factory.company_workspace import logout_workspace

    payload = (body.model_dump(exclude_none=True) if body else {}) or {}
    return logout_workspace(gst_no=payload.get("gstNo"), session_token=payload.get("sessionToken"))


class CompanyPinResetRequestBody(BaseModel):
    login: str | None = None
    gstNo: str | None = None
    email: str | None = None


@app.post("/api/company/workspace/pin-reset/request")
def api_company_pin_reset_request(body: CompanyPinResetRequestBody, request: Request) -> dict[str, Any]:
    from WEOS.factory.company_workspace import request_pin_reset

    q = (body.login or body.gstNo or body.email or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Enter GSTIN, company name, mobile, or registered email.")
    return request_pin_reset(q, base_url=_public_base_url(request))


class CompanyPinResetConfirmBody(BaseModel):
    token: str
    pin: str


@app.post("/api/company/workspace/pin-reset/confirm")
def api_company_pin_reset_confirm(body: CompanyPinResetConfirmBody) -> dict[str, Any]:
    from WEOS.factory.company_workspace import confirm_pin_reset

    try:
        return confirm_pin_reset(body.token, body.pin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/pin-reset")
def pin_reset_page(token: str = "") -> HTMLResponse:
    return HTMLResponse(
        f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WEOS PIN reset</title>
<style>
body{{font-family:system-ui,sans-serif;background:#e8e3d8;color:#141410;margin:0;padding:1.5rem}}
.card{{max-width:420px;margin:2rem auto;background:#fffdf9;border:1px solid rgba(20,20,16,.12);border-radius:14px;padding:1.2rem}}
label{{display:block;font-size:.78rem;margin:.55rem 0 .2rem}}
input{{width:100%;padding:.5rem .6rem;border-radius:10px;border:1px solid rgba(20,20,16,.18);font:inherit;box-sizing:border-box}}
button{{margin-top:.85rem;background:#0a5a48;color:#fff;border:0;border-radius:10px;padding:.55rem .9rem;font-weight:600;cursor:pointer}}
.muted{{color:#5c584f;font-size:.82rem}}
.err{{color:#8c1f18;font-size:.82rem;min-height:1.1em}}
</style></head><body>
<div class="card">
  <h1 style="font-size:1.2rem;margin:.1rem 0 .35rem">Set a new 4-digit PIN</h1>
  <p class="muted">This link was sent to the company’s registered email. After saving, log in with GST / name / mobile + this PIN.</p>
  <label>New PIN</label><input id="pin" type="password" inputmode="numeric" maxlength="4" autocomplete="new-password"/>
  <label>Confirm PIN</label><input id="pin2" type="password" inputmode="numeric" maxlength="4" autocomplete="new-password"/>
  <button type="button" id="go">Save PIN</button>
  <p class="err" id="err"></p>
</div>
<script>
document.getElementById('go').onclick = async function(){{
  var err = document.getElementById('err'); err.textContent = '';
  var a = (document.getElementById('pin').value||'').trim();
  var b = (document.getElementById('pin2').value||'').trim();
  if (!/^\\d{{4}}$/.test(a)) {{ err.textContent = 'PIN must be exactly 4 digits'; return; }}
  if (a !== b) {{ err.textContent = 'PINs do not match'; return; }}
  try {{
    var res = await fetch('/api/company/workspace/pin-reset/confirm', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{ token: {json.dumps(token or "")}, pin: a }})
    }});
    var j = await res.json();
    if (!res.ok) {{ err.textContent = j.detail || j.message || 'Could not save'; return; }}
    err.style.color = '#0a5a48';
    err.textContent = 'PIN saved. You can log in on WEOS now.';
    setTimeout(function(){{ location.href = '/'; }}, 1200);
  }} catch (e) {{ err.textContent = e.message || 'Network error'; }}
}};
</script>
</body></html>"""
    )


class CompanyQuotesBulkBody(BaseModel):
    gstNo: str | None = None
    filter: str = "unused"
    pin: str | None = None
    confirm: str | None = None


@app.get("/api/company/quotes")
def api_company_quotes(
    request: Request,
    gst: str | None = None,
    filter: str | None = Query("all"),
) -> dict[str, Any]:
    """List quotes/projects for the logged-in company GST (unused / duplicates / drafts)."""
    from WEOS.factory.company_quotes import list_company_quotes
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, gst)
    try:
        return list_company_quotes(g, filter_key=filter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/company/quotes/{project_id}")
def api_company_delete_quote(
    project_id: str,
    request: Request,
    gst: str | None = None,
    hard: bool = Query(True),
    pin: str | None = None,
    confirm: str | None = None,
) -> dict[str, Any]:
    """Delete a quote/project from Postgres, scoped to the logged-in company GST. PIN required."""
    from WEOS.factory.company_quotes import delete_company_quote, require_delete_confirm
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, gst)
    try:
        require_delete_confirm(project_id, company_gst=g, pin=pin, confirm=confirm)
        return delete_company_quote(project_id, company_gst=g, hard=hard)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/company/quotes/{project_id}/delete")
def api_company_delete_quote_post(project_id: str, body: QuoteDeleteBody, request: Request) -> dict[str, Any]:
    return api_company_delete_quote(
        project_id,
        request,
        gst=body.gstNo,
        hard=body.hard,
        pin=body.pin,
        confirm=body.confirm,
    )


@app.post("/api/company/quotes/bulk-delete")
def api_company_bulk_delete_quotes(body: CompanyQuotesBulkBody, request: Request) -> dict[str, Any]:
    """Bulk-delete unused / old-draft / duplicate extras for this GST only. PIN required."""
    from WEOS.factory.company_quotes import bulk_delete_unused, require_bulk_delete_confirm
    from WEOS.factory.company_workspace import require_company_gst

    g = require_company_gst(request, body.gstNo)
    fk = (body.filter or "unused").strip().lower()
    if fk in ("all", "*", ""):
        raise HTTPException(status_code=400, detail="Bulk delete requires filter=unused, old_draft, or duplicate.")
    try:
        require_bulk_delete_confirm(company_gst=g, pin=body.pin, confirm=body.confirm)
        return bulk_delete_unused(g, filter_key=fk)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/share-token")
def api_ensure_share_token(project_id: str) -> dict[str, Any]:
    """Mint or return the durable public scan token for a project."""
    from WEOS.factory.quote_share import ensure_project_share_token

    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    token = ensure_project_share_token(doc, persist=True)
    return {
        "ok": True,
        "projectId": project_id,
        "shareToken": token,
        "scanPath": f"/q/{token}",
        "scanAltPath": f"/scan/{token}",
    }


@app.get("/api/company/workspace")
def api_company_workspace(
    request: Request,
    gst: str | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """Return the open (or specified) company workspace hub payload."""
    from WEOS.factory.company_store import load_company_by_gst, public_company_profile
    from WEOS.factory.company_workspace import TOTALS_RULE, build_workspace_summary, require_company_gst

    g = require_company_gst(request, gst)
    company = load_company_by_gst(g) or {}
    summary = build_workspace_summary(g)
    return {
        "ok": True,
        "gstNo": g,
        "company": public_company_profile(company),
        "totalsRule": TOTALS_RULE,
        **summary,
    }


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


def _media_response(owner: str, kind: str, customer: str | None = None) -> Response:
    from WEOS.factory.media_assets import media_bytes

    raw, mime = media_bytes(owner, kind, customer)  # type: ignore[arg-type]
    if not raw:
        raise HTTPException(status_code=404, detail=f"No {kind} uploaded")
    return Response(content=raw, media_type=mime or "application/octet-stream")


@app.post("/api/company/stamp")
async def api_upload_company_stamp(file: UploadFile = File(...)) -> dict[str, Any]:
    from WEOS.factory.media_assets import save_media

    raw = await file.read()
    try:
        return save_media(raw, owner="company", kind="stamp", filename=file.filename, content_type=file.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/company/stamp")
def api_get_company_stamp() -> Response:
    return _media_response("company", "stamp")


@app.post("/api/company/signature")
async def api_upload_company_signature(file: UploadFile = File(...)) -> dict[str, Any]:
    from WEOS.factory.media_assets import save_media

    raw = await file.read()
    try:
        return save_media(raw, owner="company", kind="signature", filename=file.filename, content_type=file.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/company/signature")
def api_get_company_signature() -> Response:
    return _media_response("company", "signature")


# ── Customer profiles + accounts ─────────────────────────────────────────────

@app.get("/api/customers")
def api_list_customers(
    request: Request,
    q: str | None = None,
    gst: str | None = None,
    fy: str | None = None,
    limit: int = 80,
    offset: int = 0,
) -> dict[str, Any]:
    """Company hub customers with projects / advances / balance (not dashes)."""
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory.customer_store import find_customers

    g = require_company_gst(request, gst)
    if (q or "").strip():
        merged = find_customers(q or "", company_gst=g or None)
        from WEOS.factory.company_index import hub_customer_rows

        enriched = hub_customer_rows(g, q=q, fy=fy or "all", limit=80, offset=0)
        by_name = {str(c.get("name") or "").strip().lower(): c for c in (enriched.get("items") or [])}
        out = []
        for c in merged[:80]:
            name = str(c.get("name") or "").strip()
            hit = by_name.get(name.lower()) or {}
            out.append({**c, **{k: hit[k] for k in (
                "projectCount", "quoteVersionCount", "totalTaxable", "totalGst", "totalGrand",
                "totalAdvances", "balance", "balanceWithGst", "ledgerUrl", "ledgerPdfUrl",
            ) if k in hit}})
        return {"customers": out, "count": len(out), "query": q, "hasMore": len(merged) > 80}
    from WEOS.factory.company_index import hub_customer_rows

    packed = hub_customer_rows(g, q=None, fy=fy or "current", limit=limit or 80, offset=offset or 0)
    return {
        "customers": packed.get("items") or [],
        "count": packed.get("total") or 0,
        "fy": packed.get("fy"),
        "hasMore": bool(packed.get("hasMore")),
        "lazy": True,
    }


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
def api_customer_quotes(customer: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory.customer_store import customer_quotes

    g = require_company_gst(request, gst)
    return customer_quotes(customer, company_gst=g)


@app.get("/api/customers/{customer}/ledger")
def api_customer_ledger(customer: str, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory.ledger_store import build_ledger

    g = require_company_gst(request, gst)
    try:
        return build_ledger(customer, company_gst=g)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/customers/{customer}/advances")
def api_add_customer_advance(customer: str, body: AdvanceBody, request: Request, gst: str | None = None) -> dict[str, Any]:
    from WEOS.factory.company_workspace import require_company_gst
    from WEOS.factory.ledger_store import add_advance

    g = require_company_gst(request, gst)
    payload = body.model_dump(exclude_none=True)
    payload["companyGst"] = g
    payload.setdefault("customerName", customer)
    pid = str(payload.get("projectId") or "").strip()
    qid = str(payload.get("quoteId") or "").strip()
    if pid and qid:
        try:
            from WEOS.factory.project_store import _belongs_to_company, load_project

            linked = load_project(pid)
            if not _belongs_to_company(linked, g, include_unscoped=False):
                raise HTTPException(status_code=403, detail="Selected project belongs to another company workspace")
            want_q = re.sub(r"\s+", "", qid).upper()
            live_q = re.sub(r"\s+", "", str(linked.get("quotationId") or linked.get("quoteNumber") or "").strip()).upper()
            live_pid = re.sub(r"\s+", "", str(linked.get("projectId") or "").strip()).upper()
            if want_q not in {live_q, live_pid}:
                raise HTTPException(status_code=400, detail="Selected quote is not on this project")
            cust_slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(customer or "").strip().lower()).strip("_")
            linked_slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(linked.get("customer") or "").strip().lower()).strip("_")
            cust_digits = re.sub(r"\D", "", str(customer or ""))
            linked_digits = re.sub(r"\D", "", str(linked.get("customerMobile") or ""))
            if linked_slug and cust_slug and linked_slug != cust_slug:
                phone_match = (
                    bool(cust_digits and linked_digits)
                    and (cust_digits in linked_digits or linked_digits in cust_digits)
                )
                if not phone_match:
                    raise HTTPException(status_code=400, detail="Selected project belongs to a different customer")
            payload["quoteId"] = linked.get("quotationId") or qid
            payload["quoteVersion"] = linked.get("version") or payload.get("quoteVersion")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        created = add_advance(customer, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    pid = str(created.get("projectId") or payload.get("projectId") or "").strip()
    entry_type = str(created.get("entryType") or payload.get("entryType") or "advance").strip().lower()
    if pid and entry_type not in ("refund", "reversal", "return"):
        try:
            from WEOS.factory.ledger_store import CONFIRMED_STATUSES
            from WEOS.factory.project_store import load_project, set_project_status

            doc = load_project(pid)
            st = str(doc.get("status") or "").strip().lower()
            if st in {"rejected", "cancelled", "canceled"}:
                created["projectStatus"] = st
            elif st not in CONFIRMED_STATUSES:
                set_project_status(pid, "approved")
                created["projectStatus"] = "approved"
            else:
                created["projectStatus"] = st or "approved"
        except Exception:
            _log.debug("advance approve-status stamp skipped for %s", pid, exc_info=True)
    return created


@app.delete("/api/customers/{customer}/advances/{advance_id}")
def api_delete_customer_advance(customer: str, advance_id: int) -> dict[str, Any]:
    from WEOS.factory.ledger_store import delete_advance

    try:
        return delete_advance(customer, advance_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/master-advances")
def api_master_advance(project_id: str, body: AdvanceBody, gst: str | None = Query(None)) -> dict[str, Any]:
    """Record an advance against one quote on this Master Ledger job only."""
    from WEOS.factory.ledger_store import add_advance
    from WEOS.factory.master_ledger import build_master_ledger

    qid = str(body.quoteId or "").strip()
    from WEOS.factory.ledger_store import is_any_quote_id

    try:
        wrap = build_master_ledger(project_id=project_id, company_gst=gst)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    led = wrap.get("ledger") or {}
    quotes = led.get("quotes") or []
    any_quote = is_any_quote_id(qid)
    if not qid:
        raise HTTPException(status_code=400, detail="Select which quote this advance is against, or Any")
    row = None if any_quote else next((q for q in quotes if str(q.get("id")) == qid), None)
    if not any_quote and row is None:
        raise HTTPException(status_code=400, detail="Quote is not on this project")
    customer = (led.get("customer") or body.customerName or "").strip()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer name required")
    payload = body.model_dump(exclude_none=True)
    payload["projectId"] = str((row or {}).get("projectId") or project_id)
    payload["quoteId"] = "any" if any_quote else qid
    payload["customerName"] = customer
    payload["allowUnscoped"] = True
    try:
        created = add_advance(customer, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    created["ledger"] = build_master_ledger(project_id=project_id, company_gst=gst).get("ledger")
    return created


@app.get("/api/customers/{customer}/ledger.html")
def api_customer_ledger_html(customer: str, request: Request, gst: str | None = Query(None)) -> HTMLResponse:
    from WEOS.factory.company_store import company_branding, load_company, load_company_by_gst
    from WEOS.factory.ledger_pdf import render_ledger_html
    from WEOS.factory.ledger_store import build_ledger

    try:
        ledger = build_ledger(customer, company_gst=gst)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    co = dict((load_company_by_gst(gst) if gst else None) or load_company() or {})
    branding = company_branding(gst=gst)
    co.update({k: v for k, v in branding.items() if v})
    if branding.get("companyName") and not co.get("companyName"):
        co["companyName"] = branding["companyName"]
    return HTMLResponse(render_ledger_html(ledger, co, base_url=_public_base_url(request)))


@app.get("/api/customers/{customer}/ledger.pdf")
def api_customer_ledger_pdf(customer: str, gst: str | None = Query(None)) -> Response:
    from WEOS.factory.company_store import company_branding, load_company, load_company_by_gst, logo_file
    from WEOS.factory.ledger_pdf import ledger_filename, render_ledger_pdf
    from WEOS.factory.ledger_store import build_ledger

    try:
        ledger = build_ledger(customer, company_gst=gst)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    co = dict((load_company_by_gst(gst) if gst else None) or load_company() or {})
    branding = company_branding(gst=gst)
    co.update({k: v for k, v in branding.items() if v})
    lf = logo_file()
    if lf:
        co["logoPath"] = str(lf)
    pdf = render_ledger_pdf(ledger, co)
    fname = ledger_filename(customer, ledger.get("asOf"))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@app.get("/api/customers/{customer}/ledger.xlsx")
def api_customer_ledger_xlsx(customer: str, gst: str | None = Query(None)) -> Response:
    from WEOS.factory.company_store import company_branding, load_company, load_company_by_gst, logo_file
    from WEOS.factory.export_xlsx import export_ledger_xlsx, safe_xlsx_name
    from WEOS.factory.ledger_store import build_ledger

    try:
        ledger = build_ledger(customer, company_gst=gst)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    co = dict((load_company_by_gst(gst) if gst else None) or load_company() or {})
    co.update({k: v for k, v in company_branding(gst=gst).items() if v})
    lf = logo_file()
    if lf:
        co["logoPath"] = str(lf)
    raw = export_ledger_xlsx(ledger, co)
    fname = safe_xlsx_name(customer, "ledger")
    return Response(
        content=raw,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/api/customers/{customer}/stamp")
async def api_upload_customer_stamp(customer: str, file: UploadFile = File(...)) -> dict[str, Any]:
    from WEOS.factory.media_assets import save_media

    raw = await file.read()
    try:
        return save_media(
            raw, owner="customer", kind="stamp", customer=customer, filename=file.filename, content_type=file.content_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/customers/{customer}/stamp")
def api_get_customer_stamp(customer: str) -> Response:
    return _media_response("customer", "stamp", customer)


@app.post("/api/customers/{customer}/signature")
async def api_upload_customer_signature(customer: str, file: UploadFile = File(...)) -> dict[str, Any]:
    from WEOS.factory.media_assets import save_media

    raw = await file.read()
    try:
        return save_media(
            raw,
            owner="customer",
            kind="signature",
            customer=customer,
            filename=file.filename,
            content_type=file.content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/customers/{customer}/signature")
def api_get_customer_signature(customer: str) -> Response:
    return _media_response("customer", "signature", customer)


def _find_advance(customer: str, advance_id: int) -> dict[str, Any]:
    from WEOS.factory.ledger_store import list_advances

    for row in list_advances(customer):
        if int(row.get("id") or 0) == int(advance_id):
            return row
    raise FileNotFoundError(f"Advance {advance_id} not found")


def _advance_share_payload(adv: dict[str, Any], ledger: Mapping[str, Any], request: Request) -> dict[str, Any]:
    """Attach public scan token so the slip QR opens the customer account page."""
    from WEOS.factory.project_store import load_project
    from WEOS.factory.quote_share import ensure_project_share_token

    out = dict(adv or {})
    linked = out.get("linkedQuote") if isinstance(out.get("linkedQuote"), Mapping) else {}
    pid = str(out.get("projectId") or linked.get("projectId") or "").strip()
    if not pid:
        for p in ledger.get("projects") or []:
            if isinstance(p, Mapping) and str(p.get("projectId") or "").strip():
                pid = str(p.get("projectId")).strip()
                out.setdefault("projectName", p.get("name"))
                out.setdefault("linkedQuote", p)
                break
    if pid:
        try:
            doc = load_project(pid)
            tok = ensure_project_share_token(doc, persist=True)
            out["projectId"] = pid
            out["shareToken"] = tok
            out["quoteShareToken"] = tok
            out["quotationId"] = doc.get("quotationId") or out.get("quotationId")
            if not out.get("projectName"):
                out["projectName"] = doc.get("name")
        except Exception:
            _log.debug("advance slip share token skipped for %s", pid, exc_info=True)
    out["publicBaseUrl"] = _public_base_url(request)
    out["qrSuffix"] = "ledger"
    return out


@app.get("/api/customers/{customer}/advances/{advance_id}/slip.pdf")
def api_advance_slip_pdf(customer: str, advance_id: int, request: Request) -> Response:
    from WEOS.factory.advance_slip_pdf import advance_slip_filename, render_advance_slip_pdf
    from WEOS.factory.company_store import company_branding, load_company, logo_file
    from WEOS.factory.ledger_store import build_ledger, scope_ledger

    try:
        adv = _find_advance(customer, advance_id)
        ledger = build_ledger(customer)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    co = dict(load_company() or {})
    co.update({k: v for k, v in company_branding().items() if v})
    lf = logo_file()
    if lf:
        co["logoPath"] = str(lf)
    # Prefer linked quote display when present on advance
    for p in ledger.get("projects") or []:
        if str(p.get("projectId") or "") and str(p.get("projectId")) == str(adv.get("projectId") or ""):
            adv = {**adv, "projectName": p.get("name"), "linkedQuote": p}
            break
    adv = _advance_share_payload(adv, ledger, request)
    ledger = scope_ledger(
        ledger,
        project_id=str(adv.get("projectId") or "") or None,
        quote_id=str(adv.get("quoteId") or adv.get("quotationId") or "") or None,
    )
    pdf = render_advance_slip_pdf(adv, company=co, ledger=ledger, customer=customer)
    fname = advance_slip_filename(customer, adv)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@app.get("/api/customers/{customer}/advances/{advance_id}/slip.xlsx")
def api_advance_slip_xlsx(customer: str, advance_id: int) -> Response:
    from WEOS.factory.company_store import company_branding, load_company, logo_file
    from WEOS.factory.export_xlsx import export_advance_xlsx, safe_xlsx_name
    from WEOS.factory.ledger_store import build_ledger, scope_ledger

    try:
        adv = _find_advance(customer, advance_id)
        ledger = build_ledger(customer)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    co = dict(load_company() or {})
    co.update({k: v for k, v in company_branding().items() if v})
    lf = logo_file()
    if lf:
        co["logoPath"] = str(lf)
    for p in ledger.get("projects") or []:
        if str(p.get("projectId") or "") and str(p.get("projectId")) == str(adv.get("projectId") or ""):
            adv = {**adv, "projectName": p.get("name"), "linkedQuote": p}
            break
    ledger = scope_ledger(
        ledger,
        project_id=str(adv.get("projectId") or "") or None,
        quote_id=str(adv.get("quoteId") or adv.get("quotationId") or "") or None,
    )
    raw = export_advance_xlsx(adv, company=co, ledger=ledger, customer=customer)
    fname = safe_xlsx_name(customer, "advance", str(advance_id))
    return Response(
        content=raw,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _customer_xlsx_response(
    project_id: str,
    *,
    brand: str | None = None,
    overlay: dict[str, Any] | None = None,
    embed_drawings: str = "thumb",
) -> Response:
    from WEOS.factory.export_xlsx import export_quote_xlsx, prepare_customer_export_payload, safe_xlsx_name
    from WEOS.factory.project_store import load_project

    try:
        doc = load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if overlay:
        if overlay.get("lines") is not None:
            overlay_lines = _coerce_cart_lines(
                overlay["lines"], existing=doc.get("lines"), keep_preview_svg=True
            )
            if overlay_lines:
                doc["lines"] = overlay_lines
        for _fld in (
            "customer",
            "name",
            "customerMobile",
            "customerAddress",
            "customerGst",
            "description",
            "terms",
            "quotationId",
            "companyGst",
        ):
            if overlay.get(_fld) is not None:
                doc[_fld] = overlay[_fld]
        if overlay.get("persist") and overlay.get("lines") is not None:
            try:
                from WEOS.factory.project_store import save_project

                save_project(doc, action="xlsx-flush")
            except Exception:
                _log.exception("xlsx-flush save failed for %s", project_id)
    payload, co = prepare_customer_export_payload(doc)
    try:
        from WEOS.factory.company_store import company_branding

        gst = str(doc.get("companyGst") or "").strip()
        co_brand = str((company_branding(gst=gst or None) or {}).get("pdfBrand") or "").strip()
        if co_brand:
            payload["brand"] = co_brand
        elif brand and not payload.get("brand"):
            payload["brand"] = brand
    except Exception:
        if brand and not payload.get("brand"):
            payload["brand"] = brand
    ledger = None
    cust = str(doc.get("customer") or payload.get("customer") or "").strip()
    if cust and cust != "—":
        try:
            from WEOS.factory.ledger_store import build_ledger

            ledger = build_ledger(cust, company_gst=str(doc.get("companyGst") or "") or None)
        except Exception:
            ledger = None
    raw = export_quote_xlsx(payload, co, ledger=ledger, embed_drawings=embed_drawings)
    fname = safe_xlsx_name(payload.get("quotationId") or project_id, doc.get("customer") or "quote")
    return Response(
        content=raw,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/api/projects/{project_id}/customer.xlsx")
def api_customer_quote_xlsx(
    project_id: str,
    brand: str | None = Query(None),
    drawings: str | None = Query(None),
) -> Response:
    """Excel export mirroring the customer quote PDF (A4 + formulas, no factory BOM)."""
    return _customer_xlsx_response(project_id, brand=brand, embed_drawings=drawings or "thumb")


@app.post("/api/projects/{project_id}/customer.xlsx")
def api_customer_quote_xlsx_post(
    project_id: str,
    body: PdfExportBody | None = None,
    brand: str | None = Query(None),
    drawings: str | None = Query(None),
) -> Response:
    """Live-cart Excel — same overlay as Quote PDF, thumbnail drawings (not full-res PNG)."""
    overlay = (body.model_dump() if body is not None else {}) or {}
    embed = drawings or overlay.get("embedDrawings") or overlay.get("drawings") or "thumb"
    return _customer_xlsx_response(
        project_id,
        brand=brand or overlay.get("brand"),
        overlay=overlay,
        embed_drawings=str(embed or "thumb"),
    )


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


@app.get("/api/quote/copy-suggestions")
def api_quote_copy_suggestions(
    request: Request,
    product: str | None = None,
    gst: str | None = None,
) -> dict[str, Any]:
    """Standard terms + product description chips. Suggestions only — never auto-applied."""
    from WEOS.factory.quote_copy import quote_copy_suggestions

    g = gst
    try:
        from WEOS.factory.company_workspace import require_company_gst

        g = require_company_gst(request, gst)
    except Exception:
        g = gst
    return quote_copy_suggestions(product_id=product, gst=g)


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
def api_delete_quote(quote_id: str, gst: str | None = None) -> dict[str, Any]:
    from WEOS.db.quote_store import delete_quote
    from WEOS.factory.company_store import get_active_gst, normalise_gstin

    g = normalise_gstin(gst) if gst else (get_active_gst() or "")
    try:
        return delete_quote(quote_id, company_gst=g or None)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
    # Company / customers / projects — same ephemeral-volume problem as products.
    try:
        from WEOS.factory.company_store import bootstrap_company

        _log.info("Company store: %s", bootstrap_company())
    except Exception:
        _log.exception("Company rehydrate failed on startup")
    try:
        from WEOS.factory.customer_store import bootstrap_customers

        _log.info("Customer store: %s", bootstrap_customers())
    except Exception:
        _log.exception("Customer rehydrate failed on startup")
    try:
        from WEOS.factory.project_store import bootstrap_projects

        _log.info("Project store: %s", bootstrap_projects())
    except Exception:
        _log.exception("Project rehydrate failed on startup")


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
