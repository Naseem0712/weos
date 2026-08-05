"""WEOS FastAPI V2 — Manufacturing Operating System API.

Exact project routes for websites + ERP frontend.
Engines are never duplicated — always call factory pipeline.
"""

from __future__ import annotations

import os
import platform
import sys
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from WEOS import TAGLINE, __version__
from WEOS.api.calculate import build_api_response, get_product_detail, products_catalog
from WEOS.factory.formula import FORMULA_VARIABLES, MATERIAL_UNITS, preview_formula, validate_formula
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


class ProjectCreate(BaseModel):
    name: str = "Untitled Project"
    customer: str = ""
    status: str = "draft"
    lines: list[CartLine] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = None
    customer: str | None = None
    status: str | None = None
    lines: list[CartLine] | None = None


class ProjectCalculateOpts(BaseModel):
    optimize: bool = True


class PreviewRequest(BaseModel):
    product: str = "29mm_sliding"
    width: float = 1440
    height: float = 1800
    colour: str = "white"
    glass: str = "5mm_clear"
    handle: str = "standard"


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
    syncHardware: bool = True
    bumpVersion: bool = True
    manualRatePerOpening: float | None = None


class TemplateBody(BaseModel):
    id: str | None = None
    brand: str | None = None
    kind: str | None = None
    name: str | None = None
    pageSize: str = "A4"
    branding: dict[str, Any] | None = None
    blocks: list[dict[str, Any]] | None = None


class TemplatePreviewRequest(BaseModel):
    templateId: str | None = None
    brand: str = "woodenmax"
    kind: str = "customer"
    projectId: str | None = None
    template: dict[str, Any] | None = None


def _pdf_response(project_id: str, kind: str, brand: str | None = None, template_id: str | None = None) -> Response:
    doc = load_project(project_id)
    result = calculate_project(doc, optimize=True)
    payload = {
        **result,
        "projectId": project_id,
        "customer": doc.get("customer"),
        "name": doc.get("name"),
        "brand": brand or doc.get("brand") or "woodenmax",
        "templateId": template_id,
    }
    if kind == "factory":
        pdf = build_factory_pdf_bytes(payload)
        name = f"{project_id}_factory.pdf"
    else:
        pdf = build_customer_pdf_bytes(payload)
        name = f"{project_id}_quotation.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
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


@app.post("/api/preview")
def api_preview(body: PreviewRequest) -> dict[str, Any]:
    """Fast SVG preview for live cart — uses geometry engine only path via generate_job."""
    try:
        from WEOS.factory.product_loader import load_product

        meta = load_product(body.product, strict=False)
        if meta.get("_stub") or meta.get("status") == "stub":
            return {
                "product": body.product,
                "stub": True,
                "svg": None,
                "heroImage": meta.get("heroImage"),
                "message": "Stub product — catalogue image only",
            }
        job = generate_job(
            body.width,
            body.height,
            body.product,
            glass=body.glass,
            colour=body.colour,
            handle=body.handle,
        )
        svg = render_svg_string(job.drawing, colour=body.colour.lower().replace(" ", "_"))
        return {
            "product": body.product,
            "stub": False,
            "svg": svg,
            "width": body.width,
            "height": body.height,
            "heroImage": meta.get("heroImage"),
            "specifications": meta.get("specifications"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/calculate")
def api_calculate(body: CalculateRequest) -> dict[str, Any]:
    try:
        return build_api_response(
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
    brand: str | None = Query(None),
    templateId: str | None = Query(None),
) -> Response:
    try:
        return _pdf_response(project_id, "customer", brand=brand, template_id=templateId)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/factory-pdf")
def api_factory_pdf(
    project_id: str,
    brand: str | None = Query(None),
    templateId: str | None = Query(None),
) -> Response:
    try:
        return _pdf_response(project_id, "factory", brand=brand, template_id=templateId)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Back-compat aliases
@app.get("/api/projects/{project_id}/pdf/customer")
def api_pdf_customer_alias(project_id: str, brand: str | None = Query(None)) -> Response:
    return api_customer_pdf(project_id, brand=brand)


@app.get("/api/projects/{project_id}/pdf/factory")
def api_pdf_factory_alias(project_id: str, brand: str | None = Query(None)) -> Response:
    return api_factory_pdf(project_id, brand=brand)


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
    return {
        "materialUnits": list(MATERIAL_UNITS),
        "formulaVariables": list(FORMULA_VARIABLES),
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

    pdf = render_template_pdf(sample, kind=body.kind, brand=body.brand, template_id=sample.get("templateId"))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="template_preview.pdf"'},
    )


@app.get("/", response_class=HTMLResponse)
def website_index() -> HTMLResponse:
    index = WEBSITE_DIR / "index.html"
    if not index.is_file():
        return HTMLResponse("<h1>WEOS</h1><p>UI missing.</p>")
    return HTMLResponse(index.read_text(encoding="utf-8"))


if WEBSITE_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEBSITE_DIR)), name="static")
