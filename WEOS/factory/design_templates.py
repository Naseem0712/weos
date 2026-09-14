"""Canvas Batch G — reusable engineering design templates.

Templates store topology + cell assignments + config defaults.
They MUST NOT contain customer / project / quote identity and never
appear in PDF totals or customer documents.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Mapping

BATCH_ID = "CANVAS-G"


def new_template_id() -> str:
    return "TPL-" + uuid.uuid4().hex[:16].upper()


def _norm_gst(v: str | None) -> str:
    return str(v or "").strip().upper()


def _str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def _require_db() -> None:
    from WEOS.db.engine import db_available, init_db

    if not db_available():
        raise RuntimeError("Database unavailable for design templates")
    init_db()


def _strip_customer_identity(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Ensure template snapshots never carry quote/customer/project IDs."""
    if not isinstance(payload, Mapping):
        return {}
    ban = {
        "customer",
        "customerId",
        "customerMobile",
        "projectId",
        "quotationId",
        "quoteId",
        "companyName",
        "legacyLineId",
        "lineId",
        "sellingAmount",
        "commercialTotal",
        "quote_item_id",
        "quoteItemId",
    }
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in ban:
            continue
        if isinstance(v, dict):
            out[k] = _strip_customer_identity(v)
        elif isinstance(v, list):
            out[k] = [
                _strip_customer_identity(i) if isinstance(i, dict) else i for i in v
            ]
        else:
            out[k] = v
    return out


def save_element_as_template(
    *,
    element_id: str,
    company_gst: str,
    name: str,
    category: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Persist reusable engineering model from an existing composite/simple element."""
    from WEOS.db.engine import session_scope
    from WEOS.db.models import DesignTemplate
    from WEOS.factory import cell_assignment as ca
    from WEOS.factory import composite_duplicate as cd
    from WEOS.factory import design_scene as ds
    from WEOS.factory import member_grid as mg

    _require_db()
    gst = _norm_gst(company_gst)
    nm = _str(name)
    if not nm:
        raise ValueError("Template name required")

    el = ds.get_element(element_id, company_gst=gst)
    if el is None:
        raise PermissionError("element not found for company")

    topo = mg.get_element_topology(el["elementId"], company_gst=gst)
    assignments = ca.list_assignments_for_element(el["elementId"], company_gst=gst)
    preview = cd.regenerate_composite_preview(el["elementId"], company_gst=gst)

    # Strip identity from topology rows
    clean_cells = []
    for c in topo.get("cells") or []:
        cc = _strip_customer_identity(c)
        for k in ("projectId", "companyGst", "assemblyId", "designDocumentId", "elementId"):
            cc.pop(k, None)
        clean_cells.append(cc)
    clean_members = []
    for m in topo.get("members") or []:
        mm = _strip_customer_identity(m)
        for k in ("projectId", "companyGst", "assemblyId", "designDocumentId", "elementId"):
            mm.pop(k, None)
        clean_members.append(mm)
    clean_assigns = []
    for a in assignments:
        aa = _strip_customer_identity(a)
        for k in (
            "projectId",
            "companyGst",
            "assemblyId",
            "designDocumentId",
            "elementId",
            "assignmentId",
            "revisionId",
        ):
            aa.pop(k, None)
        clean_assigns.append(aa)

    topology_snapshot = {
        "batch": BATCH_ID,
        "members": clean_members,
        "cells": clean_cells,
        "memberCount": len(clean_members),
        "cellCount": len(clean_cells),
        "leafCellCount": sum(1 for c in clean_cells if c.get("isLeaf")),
        "gridActivated": bool(topo.get("gridActivated")),
        "elementSize": {
            "widthMm": float(el["widthMm"] or 0),
            "heightMm": float(el["heightMm"] or 0),
        },
        "productType": el.get("productType"),
        "configPayload": _strip_customer_identity(el.get("configPayload") or {}),
    }
    tid = new_template_id()
    with session_scope() as s:
        row = DesignTemplate(
            template_id=tid,
            company_gst=gst,
            name=nm,
            category=_str(category) or None,
            description=_str(description) or None,
            product_type=_str(el.get("productType")) or None,
            source_element_id=el["elementId"],
            topology_snapshot=topology_snapshot,
            assignments_snapshot=clean_assigns,
            default_size={
                "widthMm": float(el["widthMm"] or 0),
                "heightMm": float(el["heightMm"] or 0),
            },
            preview_svg=preview.get("svg") or None,
            composition_summary=preview.get("compositionSummary")
            or ca.composition_summary(assignments, topo.get("cells") or []),
            tags=list(tags or []),
            status="active",
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def list_templates(*, company_gst: str, status: str = "active") -> list[dict[str, Any]]:
    from sqlalchemy import select

    from WEOS.db.engine import session_scope
    from WEOS.db.models import DesignTemplate

    _require_db()
    gst = _norm_gst(company_gst)
    with session_scope() as s:
        q = select(DesignTemplate).where(DesignTemplate.company_gst == gst)
        if status:
            q = q.where(DesignTemplate.status == status)
        q = q.order_by(DesignTemplate.name, DesignTemplate.created_at)
        return [r.to_dict() for r in s.execute(q).scalars().all()]


def get_template(template_id: str, *, company_gst: str) -> dict[str, Any] | None:
    from WEOS.db.engine import session_scope
    from WEOS.db.models import DesignTemplate

    _require_db()
    gst = _norm_gst(company_gst)
    with session_scope() as s:
        row = s.get(DesignTemplate, str(template_id).strip())
        if row is None or _norm_gst(row.company_gst) != gst:
            return None
        return row.to_dict()


def instantiate_template(
    *,
    template_id: str,
    company_gst: str,
    design_document_id: str,
    legacy_line_id: str,
    width_mm: float,
    height_mm: float,
    size_change_rule: str | None = None,
    location_id: str | None = None,
    display_code: str | None = None,
    assembly_name: str | None = None,
) -> dict[str, Any]:
    """Create NEW design IDs from template — template itself unchanged."""
    from WEOS.factory import cell_assignment as ca
    from WEOS.factory import composite_duplicate as cd
    from WEOS.factory import design_scene as ds
    from WEOS.factory import member_grid as mg

    _require_db()
    gst = _norm_gst(company_gst)
    tpl = get_template(template_id, company_gst=gst)
    if tpl is None:
        raise PermissionError("template not found for company")
    if tpl.get("status") != "active":
        raise ValueError("template is not active")

    snap = tpl.get("topologySnapshot") or {}
    src_size = (snap.get("elementSize") or tpl.get("defaultSize") or {})
    src_w = float(src_size.get("widthMm") or width_mm)
    src_h = float(src_size.get("heightMm") or height_mm)
    new_w = float(width_mm)
    new_h = float(height_mm)
    if new_w <= 0 or new_h <= 0:
        raise ValueError("widthMm/heightMm must be positive")

    grid = bool(snap.get("gridActivated") and (snap.get("members") or snap.get("cells")))
    differ = abs(src_w - new_w) > 0.5 or abs(src_h - new_h) > 0.5
    rule = _str(size_change_rule).upper() or None
    if grid and differ:
        if not rule:
            raise ValueError(
                "sizeChangeRule required when template has members and dimensions differ: "
                "KEEP_OFFSETS or SCALE"
            )
        if rule not in ("KEEP_OFFSETS", "SCALE"):
            raise ValueError("sizeChangeRule must be KEEP_OFFSETS or SCALE")

    product_type = _str(tpl.get("productType") or snap.get("productType") or "SLIDING_WINDOW")
    new_asm = ds.create_assembly(
        design_document_id=design_document_id,
        company_gst=gst,
        name=assembly_name or tpl.get("name") or "From Template",
        location_id=location_id,
        legacy_line_id=legacy_line_id,
        status="draft",
    )
    new_el = ds.create_element(
        assembly_id=new_asm["assemblyId"],
        company_gst=gst,
        product_type=product_type,
        width_mm=src_w,
        height_mm=src_h,
        display_code=display_code,
        geometry_payload={},
        config_payload=copy.deepcopy(snap.get("configPayload") or {}),
        legacy_line_id=legacy_line_id,
        status="draft",
    )

    cell_map: dict[str, str] = {}
    member_map: dict[str, str] = {}
    if grid:
        # Restore template IDs into remappable payload shape
        fake_topo = {
            "cells": snap.get("cells") or [],
            "members": snap.get("members") or [],
            "gridActivated": True,
        }
        remapped, cell_map, member_map = cd._remap_topology_payload(  # noqa: SLF001
            fake_topo, new_element=new_el
        )
        cd._insert_remapped_topology(new_element=new_el, remapped=remapped)  # noqa: SLF001

        # Assignments: map by cell displayCode when cellId was stripped/remapped
        assigns_src = list(tpl.get("assignmentsSnapshot") or [])
        # Prefer cellId map from template cells (old cell ids still in snapshot)
        for a in assigns_src:
            old_cell = _str(a.get("cellId"))
            new_cell = cell_map.get(old_cell)
            if not new_cell and a.get("displayCode"):
                # fallback: match display code on remapped cells
                for oc, nc in cell_map.items():
                    # find old cell display
                    pass
            if not new_cell:
                # Match by displayCode across remapped cells
                code = _str(a.get("displayCode"))
                if code:
                    for c in remapped.get("cells") or []:
                        if _str(c.get("displayCode")) == code and c.get("isLeaf"):
                            new_cell = c["cellId"]
                            break
            if not new_cell:
                continue
            ca.assign_product(
                cell_id=new_cell,
                company_gst=gst,
                product_type=_str(a.get("productType") or "OPEN"),
                configuration=a.get("configuration"),
                series_code=a.get("seriesCode"),
                product_model=a.get("productModel"),
            )

    if grid and differ and rule:
        try:
            mg.apply_size_change(
                element_id=new_el["elementId"],
                company_gst=gst,
                width_mm=new_w,
                height_mm=new_h,
                size_change_rule=rule,
            )
        except ValueError:
            cd.retire_element_tree(new_el["elementId"], company_gst=gst, reason="template_size_rejected")
            raise
    elif not grid and differ:
        ds.update_element(
            new_el["elementId"],
            company_gst=gst,
            width_mm=new_w,
            height_mm=new_h,
        )

    new_el = ds.get_element(new_el["elementId"], company_gst=gst) or new_el
    preview = cd.regenerate_composite_preview(new_el["elementId"], company_gst=gst)
    new_topo = mg.get_element_topology(new_el["elementId"], company_gst=gst)
    assignments = ca.list_assignments_for_element(new_el["elementId"], company_gst=gst)

    # Template unchanged
    tpl_after = get_template(template_id, company_gst=gst)

    return {
        "ok": True,
        "batch": BATCH_ID,
        "templateId": template_id,
        "assembly": new_asm,
        "element": new_el,
        "topology": new_topo,
        "assignments": assignments,
        "cellIdMap": cell_map,
        "memberIdMap": member_map,
        "sizeChangeRule": rule,
        "preview": preview,
        "compositionSummary": preview.get("compositionSummary")
        or ca.composition_summary(assignments, new_topo.get("cells") or []),
        "templateUnchanged": {
            "templateId": template_id,
            "name": (tpl_after or tpl).get("name"),
            "sourceElementId": (tpl_after or tpl).get("sourceElementId"),
        },
        "isQuoteItem": True,  # instantiated design becomes a quote line separately
        "fromTemplate": True,
    }
