"""Canvas Batch F — CellProductAssignment domain + composite CELL-mode rendering.

DesignCell = geometry (Batch E). CellProductAssignment = behavior/infill (this module).
No Master Data / BOM. No second canvas.
"""

from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from typing import Any, Mapping

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.factory.canonical_customer import _norm_company_gst
from WEOS.db.models import CELL_ASSIGNMENT_PRODUCT_TYPES

_log = logging.getLogger("weos.cell_assignment")

BATCH_ID = "CANVAS-F"

# Map assignment product → DesignElement / adapter product type
PRODUCT_TYPE_TO_ELEMENT = {
    "FIXED": "FIXED_WINDOW",
    "SLIDING": "SLIDING_WINDOW",
    "CASEMENT": "CASEMENT_WINDOW",
    "VENTILATOR": "VENTILATOR",
    "DOOR": "DOOR",
    "OPEN": "OPEN",
}

ADAPTER_BY_PRODUCT = {
    "FIXED": "cell_fixed",
    "SLIDING": "cell_sliding",
    "CASEMENT": "cell_casement",
    "VENTILATOR": "cell_ventilator",
    "DOOR": "cell_door",
    "OPEN": "cell_open",
}

CELL_ASSIGNABLE_PRODUCTS = frozenset(CELL_ASSIGNMENT_PRODUCT_TYPES)

# Explicit: these must NOT be assigned to window cells
FORBIDDEN_CELL_PRODUCTS = frozenset(
    {
        "PERGOLA",
        "RAILING",
        "SHOWER_PARTITION",
        "SHOWER",
        "ACP",
        "LOUVER",
        "HPL",
        "FLUTED",
        "PERFORATED",
    }
)


def new_assignment_id() -> str:
    return "CPAS-" + uuid.uuid4().hex[:16].upper()


def _require_db() -> None:
    if not db_available():
        raise RuntimeError("Database unavailable for cell assignment")
    init_db()


def supports_cell_assignment(product_type: str | None) -> bool:
    """Adapter capability: which product types may be assigned to a leaf cell."""
    pt = str(product_type or "").strip().upper()
    if not pt:
        return False
    if pt in FORBIDDEN_CELL_PRODUCTS:
        return False
    # Normalize WINDOW family aliases
    aliases = {
        "FIXED_WINDOW": "FIXED",
        "SLIDING_WINDOW": "SLIDING",
        "CASEMENT_WINDOW": "CASEMENT",
        "BATHROOM_VENTILATOR": "VENTILATOR",
    }
    key = aliases.get(pt, pt)
    return key in CELL_ASSIGNABLE_PRODUCTS


def normalize_assignment_product(product_type: str | None) -> str:
    pt = str(product_type or "").strip().upper()
    aliases = {
        "FIXED_WINDOW": "FIXED",
        "SLIDING_WINDOW": "SLIDING",
        "CASEMENT_WINDOW": "CASEMENT",
        "BATHROOM_VENTILATOR": "VENTILATOR",
        "VENT": "VENTILATOR",
    }
    key = aliases.get(pt, pt)
    if key not in CELL_ASSIGNABLE_PRODUCTS:
        raise ValueError(
            f"productType '{product_type}' is not assignable to a DesignCell. "
            f"Allowed: {', '.join(CELL_ASSIGNMENT_PRODUCT_TYPES)}"
        )
    return key


def default_configuration(product_type: str) -> dict[str, Any]:
    pt = normalize_assignment_product(product_type)
    if pt == "FIXED":
        return {"glass": {"makeup": "single", "thicknessMm": 5}, "finish": None}
    if pt == "SLIDING":
        return {
            "seriesCode": None,
            "trackCount": 2,
            "shutterCount": 2,
            "opening": "left",
            "glass": {"makeup": "single", "thicknessMm": 5},
            "mesh": False,
            "finish": None,
        }
    if pt == "CASEMENT":
        return {
            "seriesCode": None,
            "sashCount": 1,
            "opening": "out",
            "handleSide": "right",
            "glass": {"makeup": "single", "thicknessMm": 5},
            "finish": None,
        }
    if pt == "VENTILATOR":
        return {
            "mode": "top_hung",
            "fan": False,
            "fanDiameterMm": None,
            "fanSide": None,
            "glass": {"makeup": "single", "thicknessMm": 5},
            "finish": None,
        }
    if pt == "DOOR":
        return {
            "doorType": "hinged",
            "opening": "in",
            "handleSide": "right",
            "glass": {"makeup": "single", "thicknessMm": 5},
            "finish": None,
        }
    # OPEN
    return {"open": True, "note": "structural opening — no infill"}


def get_cell_property_schema(product_type: str | None) -> dict[str, Any]:
    """Contextual schema for an assigned (or about-to-assign) cell — no W/H edit."""
    if not product_type:
        return {
            "version": 1,
            "adapterId": "design_cell",
            "productType": None,
            "renderMode": "CELL",
            "supportsCellAssignment": True,
            "groups": [
                {
                    "id": "cell_geometry",
                    "label": "Cell",
                    "fields": [
                        {"key": "displayCode", "label": "ID", "type": "text", "domain": "readonly"},
                        {"key": "widthMm", "label": "Width (mm)", "type": "number", "domain": "readonly"},
                        {"key": "heightMm", "label": "Height (mm)", "type": "number", "domain": "readonly"},
                    ],
                },
                {
                    "id": "assignment",
                    "label": "Product",
                    "fields": [
                        {
                            "key": "productType",
                            "label": "Assign Design",
                            "type": "select",
                            "domain": "assignment",
                            "options": [{"value": t, "label": t.title()} for t in CELL_ASSIGNMENT_PRODUCT_TYPES],
                        }
                    ],
                },
            ],
            "guidance": "Assign Fixed / Sliding / Casement / Ventilator / Door / Open to this leaf cell.",
            "batch": BATCH_ID,
        }
    pt = normalize_assignment_product(product_type)
    groups: list[dict[str, Any]] = [
        {
            "id": "cell_geometry",
            "label": "Cell",
            "fields": [
                {"key": "displayCode", "label": "ID", "type": "text", "domain": "readonly"},
                {"key": "widthMm", "label": "Width (mm)", "type": "number", "domain": "readonly"},
                {"key": "heightMm", "label": "Height (mm)", "type": "number", "domain": "readonly"},
                {"key": "productType", "label": "Product", "type": "text", "domain": "readonly"},
            ],
        }
    ]
    if pt == "FIXED":
        groups.append(
            {
                "id": "fixed_config",
                "label": "Fixed",
                "fields": [
                    {"key": "glass.thicknessMm", "label": "Glass thk mm", "type": "number", "domain": "config"},
                    {"key": "glass.makeup", "label": "Glass makeup", "type": "text", "domain": "config"},
                    {"key": "finish", "label": "Finish", "type": "text", "domain": "config"},
                ],
            }
        )
    elif pt == "SLIDING":
        groups.append(
            {
                "id": "sliding_config",
                "label": "Sliding",
                "fields": [
                    {"key": "seriesCode", "label": "Series", "type": "text", "domain": "config"},
                    {"key": "trackCount", "label": "Track count", "type": "number", "domain": "config"},
                    {"key": "shutterCount", "label": "Shutter count", "type": "number", "domain": "config"},
                    {"key": "opening", "label": "Opening", "type": "text", "domain": "config"},
                    {"key": "glass.thicknessMm", "label": "Glass thk mm", "type": "number", "domain": "config"},
                    {"key": "mesh", "label": "Mesh", "type": "boolean", "domain": "config"},
                    {"key": "finish", "label": "Finish", "type": "text", "domain": "config"},
                ],
            }
        )
    elif pt == "CASEMENT":
        groups.append(
            {
                "id": "casement_config",
                "label": "Casement",
                "fields": [
                    {"key": "seriesCode", "label": "Series", "type": "text", "domain": "config"},
                    {"key": "sashCount", "label": "Sash count", "type": "number", "domain": "config"},
                    {"key": "opening", "label": "Opening", "type": "text", "domain": "config"},
                    {"key": "handleSide", "label": "Handle side", "type": "text", "domain": "config"},
                    {"key": "glass.thicknessMm", "label": "Glass thk mm", "type": "number", "domain": "config"},
                    {"key": "finish", "label": "Finish", "type": "text", "domain": "config"},
                ],
            }
        )
    elif pt == "VENTILATOR":
        groups.append(
            {
                "id": "vent_config",
                "label": "Ventilator",
                "fields": [
                    {"key": "mode", "label": "Mode", "type": "text", "domain": "config"},
                    {"key": "fan", "label": "Exhaust fan", "type": "boolean", "domain": "config"},
                    {"key": "fanDiameterMm", "label": "Fan Ø mm", "type": "number", "domain": "config"},
                    {"key": "fanSide", "label": "Fan side", "type": "text", "domain": "config"},
                    {"key": "glass.thicknessMm", "label": "Glass thk mm", "type": "number", "domain": "config"},
                    {"key": "finish", "label": "Finish", "type": "text", "domain": "config"},
                ],
            }
        )
    elif pt == "DOOR":
        groups.append(
            {
                "id": "door_config",
                "label": "Door",
                "fields": [
                    {"key": "doorType", "label": "Door type", "type": "text", "domain": "config"},
                    {"key": "opening", "label": "Opening", "type": "text", "domain": "config"},
                    {"key": "handleSide", "label": "Handle side", "type": "text", "domain": "config"},
                    {"key": "glass.thicknessMm", "label": "Glass thk mm", "type": "number", "domain": "config"},
                    {"key": "finish", "label": "Finish", "type": "text", "domain": "config"},
                ],
            }
        )
    else:
        groups.append(
            {
                "id": "open_config",
                "label": "Open",
                "fields": [
                    {"key": "note", "label": "Note", "type": "text", "domain": "config"},
                ],
            }
        )
    return {
        "version": 1,
        "adapterId": ADAPTER_BY_PRODUCT[pt],
        "productType": pt,
        "elementProductType": PRODUCT_TYPE_TO_ELEMENT[pt],
        "renderMode": "CELL",
        "supportsCellAssignment": True,
        "groups": groups,
        "guidance": f"{pt} cell — geometry from DesignCell; config is assignment-scoped.",
        "batch": BATCH_ID,
    }


def validate_cell_config(product_type: str, configuration: Mapping[str, Any] | None) -> dict[str, Any]:
    pt = normalize_assignment_product(product_type)
    cfg = deepcopy(default_configuration(pt))
    if isinstance(configuration, Mapping):
        for k, v in configuration.items():
            if k == "glass" and isinstance(v, Mapping) and isinstance(cfg.get("glass"), dict):
                cfg["glass"] = {**cfg["glass"], **dict(v)}
            else:
                cfg[k] = v
    # Strip W/H if caller tried to inject geometry
    for bad in ("widthMm", "heightMm", "xMm", "yMm", "width", "height"):
        cfg.pop(bad, None)
    if pt == "SLIDING":
        sc = int(cfg.get("shutterCount") or 2)
        if sc < 1 or sc > 6:
            raise ValueError("shutterCount must be 1–6")
        cfg["shutterCount"] = sc
        tc = int(cfg.get("trackCount") or 2)
        if tc < 1 or tc > 4:
            raise ValueError("trackCount must be 1–4")
        cfg["trackCount"] = tc
    return cfg


def _get_owned_cell(cell_id: str, company_gst: str):
    from WEOS.db.models import DesignCell

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        row = s.get(DesignCell, str(cell_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            raise PermissionError("cell not found for company")
        return row.to_dict()


def get_active_assignment(cell_id: str, *, company_gst: str) -> dict[str, Any] | None:
    _require_db()
    from WEOS.db.models import CellProductAssignment

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        from sqlalchemy import select

        row = s.execute(
            select(CellProductAssignment).where(
                CellProductAssignment.cell_id == str(cell_id).strip(),
                CellProductAssignment.company_gst == gst,
                CellProductAssignment.status == "active",
            )
        ).scalar_one_or_none()
        return row.to_dict() if row else None


def list_assignments_for_element(element_id: str, *, company_gst: str) -> list[dict[str, Any]]:
    _require_db()
    from WEOS.db.models import CellProductAssignment
    from sqlalchemy import select

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        rows = s.execute(
            select(CellProductAssignment)
            .where(
                CellProductAssignment.element_id == str(element_id).strip(),
                CellProductAssignment.company_gst == gst,
                CellProductAssignment.status == "active",
            )
            .order_by(CellProductAssignment.created_at)
        ).scalars().all()
        return [r.to_dict() for r in rows]


def cell_ids_with_assignments(element_id: str, *, company_gst: str) -> set[str]:
    return {a["cellId"] for a in list_assignments_for_element(element_id, company_gst=company_gst)}


def assert_no_assignment_conflict(
    *,
    element_id: str,
    company_gst: str,
    cell_ids: list[str] | None = None,
    action: str = "structural edit",
) -> None:
    """Block split/delete/grid when leaf cells have active assignments."""
    assigned = cell_ids_with_assignments(element_id, company_gst=company_gst)
    if not assigned:
        return
    if cell_ids is not None:
        hit = [c for c in cell_ids if c in assigned]
        if not hit:
            return
        raise ValueError(
            f"Clear cell product assignment(s) before {action}: " + ", ".join(hit)
        )
    raise ValueError(
        f"Clear cell product assignments before {action}: " + ", ".join(sorted(assigned))
    )


def assign_product(
    *,
    cell_id: str,
    company_gst: str,
    product_type: str,
    configuration: Mapping[str, Any] | None = None,
    series_code: str | None = None,
    product_model: str | None = None,
) -> dict[str, Any]:
    """Assign or reassign product behavior to a leaf cell — one active assignment."""
    _require_db()
    pt = normalize_assignment_product(product_type)
    cfg = validate_cell_config(pt, configuration)
    if series_code:
        cfg["seriesCode"] = str(series_code).strip() or None

    from WEOS.db.models import CellProductAssignment, DesignCell, GeometryRevision
    from WEOS.factory import member_grid as mg
    from sqlalchemy import select

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        cell = s.get(DesignCell, str(cell_id).strip())
        if cell is None or _norm_company_gst(cell.company_gst) != gst:
            raise PermissionError("cell not found for company")
        if cell.status != "active":
            raise ValueError("cell is not active")
        if not cell.is_leaf:
            raise ValueError("only leaf cells can receive a product assignment")

        # Supersede any existing active assignment (reassignment)
        existing = s.execute(
            select(CellProductAssignment).where(
                CellProductAssignment.cell_id == cell.cell_id,
                CellProductAssignment.status == "active",
            )
        ).scalars().all()
        for ex in existing:
            ex.status = "superseded"

        aid = new_assignment_id()
        row = CellProductAssignment(
            assignment_id=aid,
            cell_id=cell.cell_id,
            element_id=cell.element_id,
            assembly_id=cell.assembly_id,
            design_document_id=cell.design_document_id,
            project_id=cell.project_id,
            company_gst=gst,
            product_type=pt,
            product_model=product_model,
            adapter_id=ADAPTER_BY_PRODUCT[pt],
            series_id=None,
            series_code=cfg.get("seriesCode"),
            configuration=cfg,
            status="active",
            meta={"batch": BATCH_ID},
        )
        s.add(row)
        # Denormalized summary on cell (not geometry)
        cell.product_assignment = {
            "assignmentId": aid,
            "productType": pt,
            "adapterId": ADAPTER_BY_PRODUCT[pt],
        }
        s.flush()

        # Geometry revision for audit (inline — same session)
        from WEOS.factory.design_hierarchy import new_revision_id, _payload_hash
        from WEOS.db.models import GeometryRevision, DesignDocument
        from sqlalchemy import func

        payload = {
            "batch": BATCH_ID,
            "kind": "cell_assignment",
            "cellId": cell.cell_id,
            "assignmentId": aid,
            "productType": pt,
            "configuration": cfg,
        }
        next_num = (
            s.execute(
                select(func.coalesce(func.max(GeometryRevision.revision_number), 0)).where(
                    GeometryRevision.design_document_id == cell.design_document_id
                )
            ).scalar_one()
            + 1
        )
        rev = GeometryRevision(
            revision_id=new_revision_id(),
            design_document_id=cell.design_document_id,
            project_id=cell.project_id,
            company_gst=gst,
            revision_number=int(next_num),
            label=f"assign {pt} → {cell.display_code}",
            content_hash=_payload_hash(payload),
            payload=payload,
            immutable=True,
        )
        s.add(rev)
        doc = s.get(DesignDocument, cell.design_document_id)
        if doc is not None:
            doc.current_revision_id = rev.revision_id
        row.revision_id = rev.revision_id
        s.flush()

        # Mark element composite ready
        from WEOS.db.models import DesignElement

        el = s.get(DesignElement, cell.element_id)
        if el is not None:
            geo = dict(el.geometry_payload) if isinstance(el.geometry_payload, dict) else {}
            geo["structuralCompositeReady"] = True
            geo["structuralPendingRender"] = False
            geo["hasCellAssignments"] = True
            el.geometry_payload = geo
            s.flush()

        out = row.to_dict()
        out["cell"] = cell.to_dict()
        out["saveStatus"] = "saved"
        out["revisionId"] = rev.revision_id
        return out


def clear_assignment(*, cell_id: str, company_gst: str) -> dict[str, Any]:
    """Remove active assignment; DesignCell geometry/topology unchanged."""
    _require_db()
    from WEOS.db.models import CellProductAssignment, DesignCell
    from sqlalchemy import select

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        cell = s.get(DesignCell, str(cell_id).strip())
        if cell is None or _norm_company_gst(cell.company_gst) != gst:
            raise PermissionError("cell not found for company")
        existing = s.execute(
            select(CellProductAssignment).where(
                CellProductAssignment.cell_id == cell.cell_id,
                CellProductAssignment.status == "active",
            )
        ).scalars().all()
        cleared = []
        for ex in existing:
            ex.status = "cleared"
            cleared.append(ex.assignment_id)
        cell.product_assignment = None
        s.flush()
        # Update hasCellAssignments flag
        from WEOS.db.models import DesignElement

        still = s.execute(
            select(CellProductAssignment).where(
                CellProductAssignment.element_id == cell.element_id,
                CellProductAssignment.status == "active",
            )
        ).scalars().first()
        el = s.get(DesignElement, cell.element_id)
        if el is not None:
            geo = dict(el.geometry_payload) if isinstance(el.geometry_payload, dict) else {}
            geo["hasCellAssignments"] = still is not None
            el.geometry_payload = geo
            s.flush()
        return {
            "ok": True,
            "cellId": cell.cell_id,
            "clearedAssignmentIds": cleared,
            "cell": cell.to_dict(),
            "saveStatus": "saved",
            "batch": BATCH_ID,
        }


def update_assignment_config(
    *,
    cell_id: str,
    company_gst: str,
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Update config on active assignment — geometry unchanged; no viewport Fit required."""
    _require_db()
    active = get_active_assignment(cell_id, company_gst=company_gst)
    if not active:
        raise ValueError("no active assignment on cell")
    pt = active["productType"]
    merged = {**(active.get("configuration") or {}), **dict(configuration or {})}
    return assign_product(
        cell_id=cell_id,
        company_gst=company_gst,
        product_type=pt,
        configuration=merged,
        series_code=merged.get("seriesCode") or active.get("seriesCode"),
        product_model=active.get("productModel"),
    )


# ── CELL-mode infill rendering (no outer frame) ─────────────────────────────


def render_cell(
    *,
    product_type: str,
    width_mm: float,
    height_mm: float,
    configuration: Mapping[str, Any] | None = None,
    display_code: str | None = None,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
) -> str:
    """CELL renderMode — infill/sash only; never a full standalone outer frame."""
    pt = normalize_assignment_product(product_type)
    cfg = validate_cell_config(pt, configuration)
    w = max(1.0, float(width_mm))
    h = max(1.0, float(height_mm))
    x = float(x_mm)
    y = float(y_mm)
    label = (display_code or pt)[:12]
    # Glass-ish fill
    glass = "rgba(147, 197, 253, 0.35)"
    stroke = "#334155"
    parts = [
        f'<g data-weos-cell-infill="1" data-product="{pt}" data-render-mode="CELL" '
        f'data-batch="{BATCH_ID}">',
    ]
    if pt == "OPEN":
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" '
            f'stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="6 4"/>'
        )
        parts.append(
            f'<text x="{x + w/2}" y="{y + h/2}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="{max(10, min(w, h) * 0.08)}" '
            f'fill="#64748b">OPEN</text>'
        )
    elif pt == "FIXED":
        parts.append(
            f'<rect x="{x + 2}" y="{y + 2}" width="{max(1, w - 4)}" height="{max(1, h - 4)}" '
            f'fill="{glass}" stroke="{stroke}" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{x + w/2}" y="{y + h/2}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="{max(10, min(w, h) * 0.07)}" '
            f'fill="#1e293b">FIXED</text>'
        )
    elif pt == "SLIDING":
        sc = int(cfg.get("shutterCount") or 2)
        parts.append(
            f'<rect x="{x + 2}" y="{y + 2}" width="{max(1, w - 4)}" height="{max(1, h - 4)}" '
            f'fill="{glass}" stroke="{stroke}" stroke-width="1"/>'
        )
        for i in range(1, sc):
            sx = x + (w * i / sc)
            parts.append(
                f'<line x1="{sx}" y1="{y + 2}" x2="{sx}" y2="{y + h - 2}" '
                f'stroke="#0f172a" stroke-width="3"/>'
            )
        parts.append(
            f'<text x="{x + w/2}" y="{y + h * 0.55}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="{max(9, min(w, h) * 0.06)}" '
            f'fill="#1e293b">SLIDING {sc}S</text>'
        )
    elif pt == "CASEMENT":
        parts.append(
            f'<rect x="{x + 2}" y="{y + 2}" width="{max(1, w - 4)}" height="{max(1, h - 4)}" '
            f'fill="{glass}" stroke="{stroke}" stroke-width="1.5"/>'
        )
        # hinge hint
        side = str(cfg.get("handleSide") or "right").lower()
        hx = x + w - 8 if side == "right" else x + 8
        parts.append(
            f'<circle cx="{hx}" cy="{y + h/2}" r="4" fill="#0f172a"/>'
        )
        parts.append(
            f'<text x="{x + w/2}" y="{y + h/2}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="{max(9, min(w, h) * 0.06)}" '
            f'fill="#1e293b">CASEMENT</text>'
        )
    elif pt == "VENTILATOR":
        parts.append(
            f'<rect x="{x + 2}" y="{y + 2}" width="{max(1, w - 4)}" height="{max(1, h - 4)}" '
            f'fill="rgba(186, 230, 253, 0.4)" stroke="{stroke}" stroke-width="1.5"/>'
        )
        # louvre lines
        n = max(3, int(h / 40))
        for i in range(1, n):
            ly = y + (h * i / n)
            parts.append(
                f'<line x1="{x + 6}" y1="{ly}" x2="{x + w - 6}" y2="{ly}" '
                f'stroke="#0369a1" stroke-width="1.5"/>'
            )
        parts.append(
            f'<text x="{x + w/2}" y="{y + h/2}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="{max(9, min(w, h) * 0.055)}" '
            f'fill="#0c4a6e">VENT</text>'
        )
    else:  # DOOR
        parts.append(
            f'<rect x="{x + 2}" y="{y + 2}" width="{max(1, w - 4)}" height="{max(1, h - 4)}" '
            f'fill="rgba(253, 230, 138, 0.35)" stroke="{stroke}" stroke-width="2"/>'
        )
        parts.append(
            f'<circle cx="{x + w * 0.82}" cy="{y + h/2}" r="5" fill="#0f172a"/>'
        )
        parts.append(
            f'<text x="{x + w/2}" y="{y + h/2}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="{max(9, min(w, h) * 0.06)}" '
            f'fill="#1e293b">DOOR</text>'
        )
    _ = label
    parts.append("</g>")
    return "".join(parts)


def render_composite_svg(
    topology: Mapping[str, Any],
    assignments: list[Mapping[str, Any]] | None,
    *,
    width_mm: float,
    height_mm: float,
) -> str:
    """ONE connected assembly: outer frame + members + CELL infills. No double frames."""
    w = max(1.0, float(width_mm))
    h = max(1.0, float(height_mm))
    by_cell = {a["cellId"]: a for a in (assignments or []) if a.get("cellId")}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" data-weos-composite="1" data-weos-structural="1" '
        f'data-batch="{BATCH_ID}" style="background:transparent">'
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="none" stroke="#1f2937" stroke-width="8"/>'
    ]
    for cell in topology.get("cells") or []:
        if not cell.get("isLeaf"):
            continue
        cid = cell.get("cellId")
        asn = by_cell.get(cid)
        if asn:
            parts.append(
                render_cell(
                    product_type=str(asn.get("productType")),
                    width_mm=float(cell["widthMm"]),
                    height_mm=float(cell["heightMm"]),
                    configuration=asn.get("configuration"),
                    display_code=cell.get("displayCode"),
                    x_mm=float(cell["xMm"]),
                    y_mm=float(cell["yMm"]),
                )
            )
            # subtle cell code
            parts.append(
                f'<text x="{float(cell["xMm"]) + 6}" y="{float(cell["yMm"]) + 14}" '
                f'font-size="11" fill="#64748b">{cell.get("displayCode") or ""}</text>'
            )
        else:
            parts.append(
                f'<rect x="{float(cell["xMm"])}" y="{float(cell["yMm"])}" '
                f'width="{float(cell["widthMm"])}" height="{float(cell["heightMm"])}" '
                f'fill="rgba(148,163,184,0.08)" stroke="#94a3b8" stroke-width="1" '
                f'stroke-dasharray="4 3" data-cell-id="{cid}" data-unassigned="1"/>'
            )
            cx = float(cell["xMm"]) + float(cell["widthMm"]) / 2
            cy = float(cell["yMm"]) + float(cell["heightMm"]) / 2
            parts.append(
                f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="middle" '
                f'font-size="12" fill="#94a3b8">{cell.get("displayCode") or ""}</text>'
            )
    for mem in topology.get("members") or []:
        parts.append(
            f'<line x1="{float(mem["x1Mm"])}" y1="{float(mem["y1Mm"])}" '
            f'x2="{float(mem["x2Mm"])}" y2="{float(mem["y2Mm"])}" '
            f'stroke="#0f172a" stroke-width="4" data-member-id="{mem.get("memberId","")}" '
            f'data-orientation="{mem.get("orientation","")}"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def composition_summary(assignments: list[Mapping[str, Any]], cells: list[Mapping[str, Any]]) -> str:
    """Human summary for quote card e.g. 'Top Fixed + Bottom 2-Shutter Sliding'."""
    by_id = {c["cellId"]: c for c in cells if c.get("isLeaf")}
    bits = []
    for a in assignments:
        cell = by_id.get(a.get("cellId") or "")
        code = (cell or {}).get("displayCode") or "?"
        pt = a.get("productType") or "?"
        cfg = a.get("configuration") or {}
        if pt == "SLIDING":
            bits.append(f"{code} {int(cfg.get('shutterCount') or 2)}-Shutter Sliding")
        else:
            bits.append(f"{code} {str(pt).title()}")
    if not bits:
        return "Unassigned cells"
    return " + ".join(bits)


def pdf_preflight_composite(
    element_id: str, *, company_gst: str
) -> dict[str, Any]:
    """Fail-closed if any leaf is UNASSIGNED. OPEN counts as valid."""
    from WEOS.factory import member_grid as mg

    topo = mg.get_element_topology(element_id, company_gst=company_gst)
    if not topo.get("gridActivated"):
        return {"ok": True, "mode": "product_svg", "missing": [], "composite": False}
    leaves = [c for c in (topo.get("cells") or []) if c.get("isLeaf")]
    assignments = list_assignments_for_element(element_id, company_gst=company_gst)
    by_cell = {a["cellId"]: a for a in assignments}
    missing = []
    for c in leaves:
        a = by_cell.get(c["cellId"])
        if not a:
            missing.append(c.get("displayCode") or c["cellId"])
        # OPEN is valid
    if missing:
        return {
            "ok": False,
            "mode": "fail_closed",
            "missing": missing,
            "error": "Missing cell assignment: " + ", ".join(missing),
            "composite": True,
            "batch": BATCH_ID,
        }
    svg = render_composite_svg(
        topo,
        assignments,
        width_mm=float(topo["element"]["widthMm"]),
        height_mm=float(topo["element"]["heightMm"]),
    )
    return {
        "ok": True,
        "mode": "composite",
        "missing": [],
        "svg": svg,
        "compositionSummary": composition_summary(assignments, topo.get("cells") or []),
        "composite": True,
        "batch": BATCH_ID,
    }


def deep_copy_assignments(
    *,
    source_element_id: str,
    target_element_id: str,
    cell_id_map: Mapping[str, str],
    company_gst: str,
) -> list[dict[str, Any]]:
    """Clone assignments onto duplicated cells (new assignment IDs)."""
    _require_db()
    src = list_assignments_for_element(source_element_id, company_gst=company_gst)
    out = []
    for a in src:
        new_cell = cell_id_map.get(a["cellId"])
        if not new_cell:
            continue
        created = assign_product(
            cell_id=new_cell,
            company_gst=company_gst,
            product_type=a["productType"],
            configuration=a.get("configuration"),
            series_code=a.get("seriesCode"),
            product_model=a.get("productModel"),
        )
        out.append(created)
    return out


def adapter_capabilities(product_type: str | None = None) -> dict[str, Any]:
    return {
        "batch": BATCH_ID,
        "supportsCellAssignment": supports_cell_assignment(product_type) if product_type else True,
        "assignableProductTypes": list(CELL_ASSIGNMENT_PRODUCT_TYPES),
        "forbiddenProductTypes": sorted(FORBIDDEN_CELL_PRODUCTS),
        "renderModes": ["STANDALONE", "CELL"],
        "hasRenderCell": True,
        "hasValidateCellConfig": True,
        "hasGetCellPropertySchema": True,
    }
