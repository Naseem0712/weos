"""Canvas Batch E — FrameMember + DesignCell structural topology engine.

Members split openings into stable-ID cells. SQL is SoT. Not decorative SVG.
No cell product assignment (Batch F). No BOM/profile masters.
"""

from __future__ import annotations

import logging
import re
import uuid
from copy import deepcopy
from typing import Any, Mapping, Sequence

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.factory.canonical_customer import _norm_company_gst
from WEOS.factory.design_scene import (
    ELEMENT_PRODUCT_CASEMENT,
    ELEMENT_PRODUCT_DOOR,
    ELEMENT_PRODUCT_FIXED,
    ELEMENT_PRODUCT_FOLD,
    ELEMENT_PRODUCT_LOUVER,
    ELEMENT_PRODUCT_PERGOLA,
    ELEMENT_PRODUCT_RAILING,
    ELEMENT_PRODUCT_SHOWER,
    ELEMENT_PRODUCT_SLIDING,
    ELEMENT_PRODUCT_VENTILATOR,
)
from WEOS.db.models import MEMBER_ORIENTATIONS, MEMBER_TYPES, SIZE_CHANGE_RULES

_log = logging.getLogger("weos.member_grid")

BATCH_ID = "CANVAS-E"

# Explicit overall-size rule when an opening already has a grid — never silent guess.
# KEEP_OFFSETS: preserve absolute member positions (clamp if outside); document choice.
SIZE_CHANGE_RULE_DEFAULT = "KEEP_OFFSETS"
SIZE_CHANGE_RULE_DOC = (
    "When overall W/H changes with an existing frame grid, the caller MUST pass "
    "sizeChangeRule=KEEP_OFFSETS|SCALE|CANCEL. Silent guessing is refused. "
    "Documented default for explicit KEEP_OFFSETS calls: keep absolute member "
    "offsets in mm; members outside the new opening are rejected."
)

EDGE_TOLERANCE_MM = 0.5
MIN_CELL_MM = 1.0

STRUCTURAL_EDIT_PENDING_RENDER = "STRUCTURAL_EDIT_PENDING_RENDER"

# Capability matrix — enable frame grid / cell subdivision only for fenestration families.
FRAME_GRID_ENABLED: frozenset[str] = frozenset(
    {
        ELEMENT_PRODUCT_SLIDING,
        ELEMENT_PRODUCT_CASEMENT,
        ELEMENT_PRODUCT_FIXED,
        ELEMENT_PRODUCT_DOOR,
        ELEMENT_PRODUCT_FOLD,
        ELEMENT_PRODUCT_VENTILATOR,
        "WINDOW_VENT_COMBO",
    }
)
FRAME_GRID_DISABLED_UNLESS_DECLARED: frozenset[str] = frozenset(
    {
        ELEMENT_PRODUCT_PERGOLA,
        ELEMENT_PRODUCT_RAILING,
        ELEMENT_PRODUCT_SHOWER,
        "ACP",
        ELEMENT_PRODUCT_LOUVER,
        "HPL",
        "FLUTED",
        "PERFORATED",
        "SURFACE",
        "GRILL",
    }
)


def new_member_id() -> str:
    return "FMEM-" + uuid.uuid4().hex[:16].upper()


def new_cell_id() -> str:
    return "CELL-" + uuid.uuid4().hex[:16].upper()


def _require_db() -> None:
    if not db_available():
        raise RuntimeError("Database unavailable for member/grid engine")
    init_db()


def supports_frame_grid(product_type: str | None, *, declared: Mapping[str, Any] | None = None) -> bool:
    """supportsFrameGrid capability — Sliding/Casement/Fixed/Door/Fold/Vent; specialty off unless declared."""
    pt = str(product_type or "").strip().upper()
    if not pt:
        return False
    decl = declared if isinstance(declared, Mapping) else {}
    if pt in FRAME_GRID_DISABLED_UNLESS_DECLARED:
        return bool(decl.get("supportsFrameGrid") or decl.get("supports_frame_grid"))
    if pt in FRAME_GRID_ENABLED:
        return True
    # Explicit opt-in for unknown types
    return bool(decl.get("supportsFrameGrid") or decl.get("supports_frame_grid"))


def supports_cell_subdivision(
    product_type: str | None, *, declared: Mapping[str, Any] | None = None
) -> bool:
    """supportsCellSubdivision — same matrix as frame grid unless separately declared false."""
    pt = str(product_type or "").strip().upper()
    decl = declared if isinstance(declared, Mapping) else {}
    if "supportsCellSubdivision" in decl or "supports_cell_subdivision" in decl:
        return bool(decl.get("supportsCellSubdivision") or decl.get("supports_cell_subdivision"))
    return supports_frame_grid(pt, declared=decl)


def product_capabilities(
    product_type: str | None, *, declared: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    pt = str(product_type or "").strip().upper() or None
    fg = supports_frame_grid(pt, declared=declared)
    cs = supports_cell_subdivision(pt, declared=declared)
    return {
        "productType": pt,
        "supportsFrameGrid": fg,
        "supportsCellSubdivision": cs,
        "batch": BATCH_ID,
        "sizeChangeRuleDoc": SIZE_CHANGE_RULE_DOC,
        "sizeChangeRules": list(SIZE_CHANGE_RULES),
        "defaultSizeChangeRule": SIZE_CHANGE_RULE_DEFAULT,
    }


def _get_owned_element(element_id: str, company_gst: str) -> dict[str, Any]:
    from WEOS.db.models import DesignElement

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        el = s.get(DesignElement, str(element_id).strip())
        if el is None or _norm_company_gst(el.company_gst) != gst:
            raise PermissionError("element not found for company")
        return el.to_dict()


def _assert_capable(el: Mapping[str, Any]) -> None:
    cfg = el.get("configPayload") if isinstance(el.get("configPayload"), Mapping) else {}
    decl = {}
    if isinstance(cfg, Mapping):
        caps = cfg.get("capabilities") if isinstance(cfg.get("capabilities"), Mapping) else cfg
        if isinstance(caps, Mapping):
            decl = dict(caps)
    if not supports_frame_grid(el.get("productType"), declared=decl):
        raise ValueError(
            f"productType {el.get('productType')} does not support FrameMember / cell grid "
            "(supportsFrameGrid=false)"
        )


def _active_cells(s, element_id: str) -> list:
    from sqlalchemy import select

    from WEOS.db.models import DesignCell

    return list(
        s.execute(
            select(DesignCell)
            .where(
                DesignCell.element_id == element_id,
                DesignCell.status == "active",
            )
            .order_by(DesignCell.sort_order, DesignCell.display_code)
        ).scalars().all()
    )


def _active_members(s, element_id: str) -> list:
    from sqlalchemy import select

    from WEOS.db.models import FrameMember

    return list(
        s.execute(
            select(FrameMember)
            .where(
                FrameMember.element_id == element_id,
                FrameMember.status == "active",
            )
            .order_by(FrameMember.sort_order, FrameMember.display_code)
        ).scalars().all()
    )


def _next_member_code(existing: Sequence[str]) -> str:
    nums: list[int] = []
    for code in existing:
        m = re.match(r"^M-(\d+)$", str(code or ""), re.I)
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    return f"M-{n:02d}"


def _child_codes(parent_code: str, count: int) -> list[str]:
    """Stable nested IDs: C-01 → C-01A, C-01B; deeper → C-01A1, C-01A2 …"""
    base = str(parent_code or "C-01").strip() or "C-01"
    if count <= 0:
        return []
    # Letter suffix for first nesting level under C-NN
    if re.match(r"^C-\d+$", base, re.I) and count <= 26:
        return [f"{base}{chr(ord('A') + i)}" for i in range(count)]
    # Numeric suffix for deeper / large grids
    return [f"{base}.{i + 1}" for i in range(count)]


def _validate_position_in_cell(
    *,
    orientation: str,
    position_mm: float,
    cell_x: float,
    cell_y: float,
    cell_w: float,
    cell_h: float,
    edge_tol: float = EDGE_TOLERANCE_MM,
) -> float:
    if orientation == "V":
        lo, hi = cell_x, cell_x + cell_w
        pos = float(position_mm)
        if pos < lo - edge_tol or pos > hi + edge_tol:
            raise ValueError(f"vertical member position {pos} outside cell span [{lo},{hi}]")
        # Snap to interior — reject edge (zero-size) unless within tol of edge then refuse
        if abs(pos - lo) <= edge_tol or abs(pos - hi) <= edge_tol:
            raise ValueError("member coincides with cell edge (zero-size cell)")
        if pos <= lo or pos >= hi:
            raise ValueError("member position must be strictly inside cell")
        return pos
    lo, hi = cell_y, cell_y + cell_h
    pos = float(position_mm)
    if pos < lo - edge_tol or pos > hi + edge_tol:
        raise ValueError(f"horizontal member position {pos} outside cell span [{lo},{hi}]")
    if abs(pos - lo) <= edge_tol or abs(pos - hi) <= edge_tol:
        raise ValueError("member coincides with cell edge (zero-size cell)")
    if pos <= lo or pos >= hi:
        raise ValueError("member position must be strictly inside cell")
    return pos


def _topology_snapshot(s, element_id: str) -> dict[str, Any]:
    members = [m.to_dict() for m in _active_members(s, element_id)]
    cells = [c.to_dict() for c in _active_cells(s, element_id)]
    return {
        "batch": BATCH_ID,
        "elementId": element_id,
        "members": members,
        "cells": cells,
        "memberCount": len(members),
        "cellCount": len(cells),
        "leafCellCount": sum(1 for c in cells if c.get("isLeaf")),
        "gridActivated": any(c.get("isRoot") for c in cells),
    }


def get_element_topology(element_id: str, *, company_gst: str) -> dict[str, Any]:
    _require_db()
    el = _get_owned_element(element_id, company_gst)
    with session_scope() as s:
        snap = _topology_snapshot(s, el["elementId"])
    caps = product_capabilities(el.get("productType"))
    return {
        **snap,
        "element": {
            "elementId": el["elementId"],
            "assemblyId": el["assemblyId"],
            "designDocumentId": el["designDocumentId"],
            "productType": el["productType"],
            "widthMm": el["widthMm"],
            "heightMm": el["heightMm"],
            "xMm": el["xMm"],
            "yMm": el["yMm"],
        },
        "capabilities": caps,
        "worldOrigin": {"xMm": el["xMm"], "yMm": el["yMm"]},
    }


def list_members(element_id: str, *, company_gst: str) -> list[dict[str, Any]]:
    topo = get_element_topology(element_id, company_gst=company_gst)
    return list(topo.get("members") or [])


def list_cells(element_id: str, *, company_gst: str) -> list[dict[str, Any]]:
    topo = get_element_topology(element_id, company_gst=company_gst)
    return list(topo.get("cells") or [])


def _ensure_root_cell(s, el: Mapping[str, Any]) -> Any:
    """Bootstrap root cell on first structural activation only (non-destructive)."""
    from WEOS.db.models import DesignCell

    cells = _active_cells(s, el["elementId"])
    roots = [c for c in cells if c.is_root]
    if roots:
        return roots[0]
    if cells:
        # Corrupt: active cells without root
        raise ValueError("corrupt cell topology: active cells without root")
    w = float(el["widthMm"] or 0)
    h = float(el["heightMm"] or 0)
    if w < MIN_CELL_MM or h < MIN_CELL_MM:
        raise ValueError("element size too small for root cell")
    cell = DesignCell(
        cell_id=new_cell_id(),
        element_id=el["elementId"],
        assembly_id=el["assemblyId"],
        design_document_id=el["designDocumentId"],
        project_id=el["projectId"],
        company_gst=el["companyGst"],
        display_code="C-01",
        parent_cell_id=None,
        x_mm=0.0,
        y_mm=0.0,
        width_mm=w,
        height_mm=h,
        is_root=True,
        is_leaf=True,
        split_by_member_id=None,
        sort_order=0,
        status="active",
        product_assignment=None,
        meta={"bootstrapped": True, "batch": BATCH_ID},
    )
    s.add(cell)
    s.flush()
    return cell


def _find_leaf_at(s, element_id: str, x_mm: float, y_mm: float):
    cells = [c for c in _active_cells(s, element_id) if c.is_leaf]
    for c in cells:
        if c.x_mm <= x_mm <= c.x_mm + c.width_mm and c.y_mm <= y_mm <= c.y_mm + c.height_mm:
            return c
    return None


def _find_leaf_by_id(s, element_id: str, cell_id: str | None):
    if not cell_id:
        return None
    for c in _active_cells(s, element_id):
        if c.cell_id == cell_id and c.is_leaf and c.status == "active":
            return c
    return None


def _push_geometry_revision(
    s,
    el: Mapping[str, Any],
    *,
    label: str,
    topology: Mapping[str, Any],
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Create immutable GeometryRevision; enforce stale revision safety."""
    from sqlalchemy import func, select

    from WEOS.db.models import DesignDocument, DesignElement, GeometryRevision
    from WEOS.factory.design_hierarchy import new_revision_id, _payload_hash

    doc = s.get(DesignDocument, el["designDocumentId"])
    if doc is None:
        raise PermissionError("design document not found")
    if expected_revision_id is not None:
        cur = str(doc.current_revision_id or "")
        if cur and cur != str(expected_revision_id):
            raise ValueError(
                f"stale geometry revision: expected {expected_revision_id}, current {cur}"
            )

    elem_row = s.get(DesignElement, el["elementId"])
    geo = dict(elem_row.geometry_payload) if isinstance(elem_row.geometry_payload, dict) else {}
    hist = dict(geo.get("_structureHistory") or {})
    undo = list(hist.get("undo") or [])
    # Before mutation snapshot already applied; push previous current onto undo after new rev

    payload = {
        "batch": BATCH_ID,
        "kind": "structure_topology",
        "elementId": el["elementId"],
        "label": label,
        "topology": dict(topology),
        "elementSize": {"widthMm": el["widthMm"], "heightMm": el["heightMm"]},
    }
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
        company_gst=doc.company_gst,
        revision_number=int(next_num),
        label=label,
        content_hash=_payload_hash(payload),
        payload=payload,
        immutable=True,
    )
    s.add(rev)
    prev_id = doc.current_revision_id
    doc.current_revision_id = rev.revision_id
    if prev_id:
        undo.append(prev_id)
        undo = undo[-50:]
    hist["undo"] = undo
    hist["redo"] = []
    hist["currentRevisionId"] = rev.revision_id
    geo["_structureHistory"] = hist
    geo["gridActivated"] = bool(topology.get("gridActivated"))
    geo["structuralCompositeReady"] = True  # topology SVG available
    geo["structuralPendingRender"] = False
    elem_row.geometry_payload = geo
    s.flush()
    return rev.to_dict()


def _restore_topology_from_payload(s, el: Mapping[str, Any], topology: Mapping[str, Any]) -> None:
    """Replace active members/cells with snapshot (used by undo/redo)."""
    from WEOS.db.models import DesignCell, FrameMember

    eid = el["elementId"]
    for m in _active_members(s, eid):
        m.status = "superseded"
        m.display_code = f"{m.display_code}~{m.member_id[-6:]}"
    for c in _active_cells(s, eid):
        c.status = "superseded"
        c.display_code = f"{c.display_code}~{c.cell_id[-6:]}"
    s.flush()

    for cd in topology.get("cells") or []:
        cell = DesignCell(
            cell_id=str(cd["cellId"]),
            element_id=eid,
            assembly_id=el["assemblyId"],
            design_document_id=el["designDocumentId"],
            project_id=el["projectId"],
            company_gst=el["companyGst"],
            display_code=str(cd.get("displayCode") or "C-01"),
            parent_cell_id=cd.get("parentCellId"),
            x_mm=float(cd.get("xMm") or 0),
            y_mm=float(cd.get("yMm") or 0),
            width_mm=float(cd.get("widthMm") or 0),
            height_mm=float(cd.get("heightMm") or 0),
            is_root=bool(cd.get("isRoot")),
            is_leaf=bool(cd.get("isLeaf")),
            split_by_member_id=cd.get("splitByMemberId"),
            sort_order=int(cd.get("sortOrder") or 0),
            status="active",
            product_assignment=None,
            meta=cd.get("meta"),
        )
        s.merge(cell)
    for md in topology.get("members") or []:
        mem = FrameMember(
            member_id=str(md["memberId"]),
            element_id=eid,
            assembly_id=el["assemblyId"],
            design_document_id=el["designDocumentId"],
            project_id=el["projectId"],
            company_gst=el["companyGst"],
            display_code=str(md.get("displayCode") or "M-01"),
            orientation=str(md.get("orientation") or "V"),
            member_type=str(md.get("memberType") or "MULLION"),
            position_mm=float(md.get("positionMm") or 0),
            x1_mm=float(md.get("x1Mm") or 0),
            y1_mm=float(md.get("y1Mm") or 0),
            x2_mm=float(md.get("x2Mm") or 0),
            y2_mm=float(md.get("y2Mm") or 0),
            span_cell_id=md.get("spanCellId"),
            parent_member_id=md.get("parentMemberId"),
            profile_role=md.get("profileRole"),
            thickness_mm=float(md.get("thicknessMm") or 0),
            sort_order=int(md.get("sortOrder") or 0),
            status="active",
            meta=md.get("meta"),
        )
        s.merge(mem)
    s.flush()


def _ensure_structure_baseline(s, el: Mapping[str, Any]) -> None:
    """Ensure undo can return to pre-structure (no members/cells) after first activation."""
    from WEOS.db.models import DesignElement

    elem_row = s.get(DesignElement, el["elementId"])
    geo = dict(elem_row.geometry_payload) if isinstance(elem_row.geometry_payload, dict) else {}
    hist = dict(geo.get("_structureHistory") or {})
    if hist.get("baselineRevisionId"):
        return
    empty = {
        "batch": BATCH_ID,
        "elementId": el["elementId"],
        "members": [],
        "cells": [],
        "memberCount": 0,
        "cellCount": 0,
        "leafCellCount": 0,
        "gridActivated": False,
    }
    rev = _push_geometry_revision(
        s,
        el,
        label="structure_baseline_empty",
        topology=empty,
        expected_revision_id=None,
    )
    # Re-read after push
    elem_row = s.get(DesignElement, el["elementId"])
    geo = dict(elem_row.geometry_payload) if isinstance(elem_row.geometry_payload, dict) else {}
    hist = dict(geo.get("_structureHistory") or {})
    hist["baselineRevisionId"] = rev["revisionId"]
    # Clear undo so baseline is the floor (first real op will push baseline onto undo)
    hist["undo"] = []
    hist["redo"] = []
    hist["currentRevisionId"] = rev["revisionId"]
    geo["_structureHistory"] = hist
    elem_row.geometry_payload = geo
    s.flush()


def place_member(
    *,
    element_id: str,
    company_gst: str,
    orientation: str,
    position_mm: float,
    cell_id: str | None = None,
    member_type: str | None = None,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Place V or H member splitting one leaf cell — atomic txn + GeometryRevision."""
    _require_db()
    ori = str(orientation or "").strip().upper()
    if ori not in ("V", "H", "VERTICAL", "HORIZONTAL"):
        raise ValueError("orientation must be V or H")
    if ori in ("VERTICAL", "V"):
        ori = "V"
    else:
        ori = "H"
    mt = str(member_type or ("MULLION" if ori == "V" else "TRANSOM")).strip().upper()
    if mt not in MEMBER_TYPES:
        raise ValueError(f"memberType must be one of {MEMBER_TYPES}")
    try:
        pos = float(position_mm)
    except (TypeError, ValueError) as exc:
        raise ValueError("positionMm must be a number") from exc
    if pos != pos or pos < 0:
        raise ValueError("positionMm must be finite and non-negative")

    el = _get_owned_element(element_id, company_gst)
    _assert_capable(el)

    from WEOS.db.models import DesignCell, FrameMember

    with session_scope() as s:
        _ensure_structure_baseline(s, el)
        root = _ensure_root_cell(s, el)
        target = _find_leaf_by_id(s, el["elementId"], cell_id)
        if cell_id and target is None:
            raise ValueError("cellId must reference an active leaf cell")
        if target is None:
            # Resolve leaf by position
            if ori == "V":
                target = _find_leaf_at(s, el["elementId"], pos, float(root.y_mm) + float(root.height_mm) / 2)
            else:
                target = _find_leaf_at(s, el["elementId"], float(root.x_mm) + float(root.width_mm) / 2, pos)
        if target is None:
            # Fall back to root if still leaf
            cells = _active_cells(s, el["elementId"])
            leaves = [c for c in cells if c.is_leaf]
            if len(leaves) == 1:
                target = leaves[0]
            else:
                raise ValueError("no leaf cell found for member placement")

        pos = _validate_position_in_cell(
            orientation=ori,
            position_mm=pos,
            cell_x=float(target.x_mm),
            cell_y=float(target.y_mm),
            cell_w=float(target.width_mm),
            cell_h=float(target.height_mm),
        )

        # Duplicate check: same orientation + position within tol in same cell span
        for m in _active_members(s, el["elementId"]):
            if m.orientation != ori:
                continue
            if m.span_cell_id and m.span_cell_id != target.cell_id:
                # Only compare siblings spanning same parent cell — also check overlap
                pass
            if abs(float(m.position_mm) - pos) <= EDGE_TOLERANCE_MM:
                # Same line if spans overlap
                if ori == "V":
                    if not (m.y2_mm <= target.y_mm or m.y1_mm >= target.y_mm + target.height_mm):
                        raise ValueError("duplicate vertical member at this position")
                else:
                    if not (m.x2_mm <= target.x_mm or m.x1_mm >= target.x_mm + target.width_mm):
                        raise ValueError("duplicate horizontal member at this position")

        codes = [m.display_code for m in _active_members(s, el["elementId"])]
        mcode = _next_member_code(codes)
        mid = new_member_id()

        if ori == "V":
            x1 = x2 = pos
            y1 = float(target.y_mm)
            y2 = float(target.y_mm + target.height_mm)
            left_w = pos - float(target.x_mm)
            right_w = float(target.x_mm + target.width_mm) - pos
            if left_w < MIN_CELL_MM or right_w < MIN_CELL_MM:
                raise ValueError("split would create zero/negative cell size")
            child_dims = [
                (float(target.x_mm), float(target.y_mm), left_w, float(target.height_mm)),
                (pos, float(target.y_mm), right_w, float(target.height_mm)),
            ]
        else:
            y1 = y2 = pos
            x1 = float(target.x_mm)
            x2 = float(target.x_mm + target.width_mm)
            top_h = pos - float(target.y_mm)
            bot_h = float(target.y_mm + target.height_mm) - pos
            if top_h < MIN_CELL_MM or bot_h < MIN_CELL_MM:
                raise ValueError("split would create zero/negative cell size")
            child_dims = [
                (float(target.x_mm), float(target.y_mm), float(target.width_mm), top_h),
                (float(target.x_mm), pos, float(target.width_mm), bot_h),
            ]

        member = FrameMember(
            member_id=mid,
            element_id=el["elementId"],
            assembly_id=el["assemblyId"],
            design_document_id=el["designDocumentId"],
            project_id=el["projectId"],
            company_gst=el["companyGst"],
            display_code=mcode,
            orientation=ori,
            member_type=mt,
            position_mm=pos,
            x1_mm=x1,
            y1_mm=y1,
            x2_mm=x2,
            y2_mm=y2,
            span_cell_id=target.cell_id,
            parent_member_id=None,
            profile_role=None,
            thickness_mm=0.0,
            sort_order=len(codes),
            status="active",
            meta={"batch": BATCH_ID},
        )
        s.add(member)

        target.is_leaf = False
        target.split_by_member_id = mid
        child_codes = _child_codes(target.display_code, 2)
        children = []
        for i, (cx, cy, cw, ch) in enumerate(child_dims):
            child = DesignCell(
                cell_id=new_cell_id(),
                element_id=el["elementId"],
                assembly_id=el["assemblyId"],
                design_document_id=el["designDocumentId"],
                project_id=el["projectId"],
                company_gst=el["companyGst"],
                display_code=child_codes[i],
                parent_cell_id=target.cell_id,
                x_mm=cx,
                y_mm=cy,
                width_mm=cw,
                height_mm=ch,
                is_root=False,
                is_leaf=True,
                split_by_member_id=None,
                sort_order=int(target.sort_order) * 10 + i + 1,
                status="active",
                product_assignment=None,
                meta={"batch": BATCH_ID, "splitFrom": target.cell_id},
            )
            s.add(child)
            children.append(child)
        s.flush()

        topo = _topology_snapshot(s, el["elementId"])
        rev = _push_geometry_revision(
            s,
            el,
            label=f"place_{ori}_member@{pos}",
            topology=topo,
            expected_revision_id=expected_revision_id,
        )
        return {
            "ok": True,
            "member": member.to_dict(),
            "parentCell": target.to_dict(),
            "childCells": [c.to_dict() for c in children],
            "topology": topo,
            "revision": rev,
            "saveStatus": "saved",
        }


def apply_equal_grid(
    *,
    element_id: str,
    company_gst: str,
    rows: int,
    columns: int,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Atomic equal Rows×Columns subdivision of the current root/opening.

    Custom unequal sizes deferred. Replaces leaf topology under root with equal grid.
    If grid already exists, rebuilds from root (full equal reset) atomically.
    """
    _require_db()
    try:
        r = int(rows)
        c = int(columns)
    except (TypeError, ValueError) as exc:
        raise ValueError("rows and columns must be integers") from exc
    if r < 1 or c < 1:
        raise ValueError("rows and columns must be >= 1")
    if r == 1 and c == 1:
        raise ValueError("grid 1×1 is a no-op; use root cell only")
    if r > 20 or c > 20:
        raise ValueError("grid limited to 20×20")

    el = _get_owned_element(element_id, company_gst)
    _assert_capable(el)
    w = float(el["widthMm"] or 0)
    h = float(el["heightMm"] or 0)
    cell_w = w / c
    cell_h = h / r
    if cell_w < MIN_CELL_MM or cell_h < MIN_CELL_MM:
        raise ValueError("equal grid would create zero/negative cells")

    from WEOS.db.models import DesignCell, FrameMember

    with session_scope() as s:
        _ensure_structure_baseline(s, el)
        # Clear prior active topology (atomic rebuild)
        for m in _active_members(s, el["elementId"]):
            m.status = "superseded"
            m.display_code = f"{m.display_code}~{m.member_id[-6:]}"
        for cell in _active_cells(s, el["elementId"]):
            cell.status = "superseded"
            cell.display_code = f"{cell.display_code}~{cell.cell_id[-6:]}"
        s.flush()

        root = DesignCell(
            cell_id=new_cell_id(),
            element_id=el["elementId"],
            assembly_id=el["assemblyId"],
            design_document_id=el["designDocumentId"],
            project_id=el["projectId"],
            company_gst=el["companyGst"],
            display_code="C-01",
            parent_cell_id=None,
            x_mm=0.0,
            y_mm=0.0,
            width_mm=w,
            height_mm=h,
            is_root=True,
            is_leaf=False,
            split_by_member_id=None,
            sort_order=0,
            status="active",
            product_assignment=None,
            meta={"batch": BATCH_ID, "grid": {"rows": r, "columns": c, "equal": True}},
        )
        s.add(root)
        s.flush()

        # Vertical members (columns-1) spanning full height
        members: list[FrameMember] = []
        for i in range(1, c):
            pos = cell_w * i
            mid = new_member_id()
            m = FrameMember(
                member_id=mid,
                element_id=el["elementId"],
                assembly_id=el["assemblyId"],
                design_document_id=el["designDocumentId"],
                project_id=el["projectId"],
                company_gst=el["companyGst"],
                display_code=f"M-V{i:02d}",
                orientation="V",
                member_type="MULLION",
                position_mm=pos,
                x1_mm=pos,
                y1_mm=0.0,
                x2_mm=pos,
                y2_mm=h,
                span_cell_id=root.cell_id,
                parent_member_id=None,
                thickness_mm=0.0,
                sort_order=i,
                status="active",
                meta={"batch": BATCH_ID, "grid": True},
            )
            s.add(m)
            members.append(m)
        # Horizontal members (rows-1)
        for j in range(1, r):
            pos = cell_h * j
            mid = new_member_id()
            m = FrameMember(
                member_id=mid,
                element_id=el["elementId"],
                assembly_id=el["assemblyId"],
                design_document_id=el["designDocumentId"],
                project_id=el["projectId"],
                company_gst=el["companyGst"],
                display_code=f"M-H{j:02d}",
                orientation="H",
                member_type="TRANSOM",
                position_mm=pos,
                x1_mm=0.0,
                y1_mm=pos,
                x2_mm=w,
                y2_mm=pos,
                span_cell_id=root.cell_id,
                parent_member_id=None,
                thickness_mm=0.0,
                sort_order=100 + j,
                status="active",
                meta={"batch": BATCH_ID, "grid": True},
            )
            s.add(m)
            members.append(m)

        leaves = []
        idx = 0
        for row in range(r):
            for col in range(c):
                idx += 1
                code = f"C-{idx:02d}" if r * c > 1 else "C-01A"
                # Prefer letter grid labels for small grids under root
                if r * c <= 26:
                    code = f"C-01{chr(ord('A') + idx - 1)}"
                child = DesignCell(
                    cell_id=new_cell_id(),
                    element_id=el["elementId"],
                    assembly_id=el["assemblyId"],
                    design_document_id=el["designDocumentId"],
                    project_id=el["projectId"],
                    company_gst=el["companyGst"],
                    display_code=code,
                    parent_cell_id=root.cell_id,
                    x_mm=cell_w * col,
                    y_mm=cell_h * row,
                    width_mm=cell_w,
                    height_mm=cell_h,
                    is_root=False,
                    is_leaf=True,
                    split_by_member_id=None,
                    sort_order=idx,
                    status="active",
                    product_assignment=None,
                    meta={"batch": BATCH_ID, "row": row, "col": col},
                )
                s.add(child)
                leaves.append(child)
        # Mark root split by first member if any
        if members:
            root.split_by_member_id = members[0].member_id
        s.flush()

        topo = _topology_snapshot(s, el["elementId"])
        rev = _push_geometry_revision(
            s,
            el,
            label=f"equal_grid_{r}x{c}",
            topology=topo,
            expected_revision_id=expected_revision_id,
        )
        return {
            "ok": True,
            "rows": r,
            "columns": c,
            "equal": True,
            "members": [m.to_dict() for m in members],
            "cells": [root.to_dict()] + [c.to_dict() for c in leaves],
            "topology": topo,
            "revision": rev,
            "saveStatus": "saved",
        }


def delete_member(
    *,
    member_id: str,
    company_gst: str,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Delete member and merge its two child cells back into the parent span cell."""
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import DesignCell, DesignElement, FrameMember

    with session_scope() as s:
        mem = s.get(FrameMember, str(member_id).strip())
        if mem is None or _norm_company_gst(mem.company_gst) != gst:
            raise PermissionError("member not found for company")
        if mem.status != "active":
            raise ValueError("member is not active")
        el_row = s.get(DesignElement, mem.element_id)
        if el_row is None:
            raise PermissionError("element not found")
        el = el_row.to_dict()
        _assert_capable(el)

        parent = None
        if mem.span_cell_id:
            parent = s.get(DesignCell, mem.span_cell_id)
        if parent is None or parent.status != "active":
            raise ValueError("corrupt topology: span cell missing")

        children = [
            c
            for c in _active_cells(s, el["elementId"])
            if c.parent_cell_id == parent.cell_id and c.split_by_member_id is None
        ]
        # Children of this split: parent.split_by_member_id == mem, kids parent_cell_id == parent
        kids = [
            c
            for c in _active_cells(s, el["elementId"])
            if c.parent_cell_id == parent.cell_id and c.status == "active"
        ]
        # Refuse if any child was further subdivided (has own children)
        for kid in kids:
            if not kid.is_leaf:
                raise ValueError("cannot delete member: nested splits exist — delete children first")
            grand = [
                c
                for c in _active_cells(s, el["elementId"])
                if c.parent_cell_id == kid.cell_id and c.status == "active"
            ]
            if grand:
                raise ValueError("cannot delete member: nested cell lineage present")

        # Also refuse if other members span only these kids
        for m in _active_members(s, el["elementId"]):
            if m.member_id == mem.member_id:
                continue
            if m.span_cell_id in {k.cell_id for k in kids}:
                raise ValueError("cannot delete member: dependent members on child cells")

        for kid in kids:
            kid.status = "merged"
        mem.status = "deleted"
        parent.is_leaf = True
        parent.split_by_member_id = None
        s.flush()

        topo = _topology_snapshot(s, el["elementId"])
        rev = _push_geometry_revision(
            s,
            el,
            label=f"delete_member_{mem.display_code}",
            topology=topo,
            expected_revision_id=expected_revision_id,
        )
        return {
            "ok": True,
            "deletedMemberId": mem.member_id,
            "mergedCell": parent.to_dict(),
            "topology": topo,
            "revision": rev,
            "saveStatus": "saved",
        }


def update_member_position(
    *,
    member_id: str,
    company_gst: str,
    position_mm: float,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Numeric position edit in world/local mm — updates endpoints and child cell bounds."""
    _require_db()
    gst = _norm_company_gst(company_gst)
    try:
        pos = float(position_mm)
    except (TypeError, ValueError) as exc:
        raise ValueError("positionMm must be a number") from exc
    if pos != pos or pos < 0:
        raise ValueError("positionMm must be finite and non-negative")

    from WEOS.db.models import DesignCell, DesignElement, FrameMember

    with session_scope() as s:
        mem = s.get(FrameMember, str(member_id).strip())
        if mem is None or _norm_company_gst(mem.company_gst) != gst:
            raise PermissionError("member not found for company")
        if mem.status != "active":
            raise ValueError("member is not active")
        el_row = s.get(DesignElement, mem.element_id)
        el = el_row.to_dict()
        _assert_capable(el)
        parent = s.get(DesignCell, mem.span_cell_id) if mem.span_cell_id else None
        if parent is None or parent.status != "active":
            raise ValueError("span cell missing")
        pos = _validate_position_in_cell(
            orientation=mem.orientation,
            position_mm=pos,
            cell_x=float(parent.x_mm),
            cell_y=float(parent.y_mm),
            cell_w=float(parent.width_mm),
            cell_h=float(parent.height_mm),
        )
        kids = sorted(
            [
                c
                for c in _active_cells(s, el["elementId"])
                if c.parent_cell_id == parent.cell_id and c.status == "active"
            ],
            key=lambda c: (c.x_mm, c.y_mm),
        )
        if len(kids) != 2:
            raise ValueError("member must have exactly two child cells for position edit")
        if any(not k.is_leaf for k in kids):
            raise ValueError("cannot move member with nested splits")

        if mem.orientation == "V":
            mem.position_mm = pos
            mem.x1_mm = mem.x2_mm = pos
            left, right = kids[0], kids[1]
            if left.x_mm > right.x_mm:
                left, right = right, left
            left.width_mm = pos - float(parent.x_mm)
            right.x_mm = pos
            right.width_mm = float(parent.x_mm + parent.width_mm) - pos
            if left.width_mm < MIN_CELL_MM or right.width_mm < MIN_CELL_MM:
                raise ValueError("position would create zero-size cell")
        else:
            mem.position_mm = pos
            mem.y1_mm = mem.y2_mm = pos
            top, bot = kids[0], kids[1]
            if top.y_mm > bot.y_mm:
                top, bot = bot, top
            top.height_mm = pos - float(parent.y_mm)
            bot.y_mm = pos
            bot.height_mm = float(parent.y_mm + parent.height_mm) - pos
            if top.height_mm < MIN_CELL_MM or bot.height_mm < MIN_CELL_MM:
                raise ValueError("position would create zero-size cell")
        s.flush()
        topo = _topology_snapshot(s, el["elementId"])
        rev = _push_geometry_revision(
            s,
            el,
            label=f"move_member_{mem.display_code}@{pos}",
            topology=topo,
            expected_revision_id=expected_revision_id,
        )
        return {
            "ok": True,
            "member": mem.to_dict(),
            "topology": topo,
            "revision": rev,
            "saveStatus": "saved",
        }


def undo_structure(*, element_id: str, company_gst: str) -> dict[str, Any]:
    """Server-side undo of last structural GeometryRevision for this element."""
    _require_db()
    el = _get_owned_element(element_id, company_gst)
    from WEOS.db.models import DesignDocument, DesignElement, GeometryRevision

    with session_scope() as s:
        elem_row = s.get(DesignElement, el["elementId"])
        geo = dict(elem_row.geometry_payload) if isinstance(elem_row.geometry_payload, dict) else {}
        hist = dict(geo.get("_structureHistory") or {})
        undo = list(hist.get("undo") or [])
        redo = list(hist.get("redo") or [])
        if not undo:
            raise ValueError("nothing to undo")
        prev_id = undo.pop()
        cur_id = hist.get("currentRevisionId") or (
            s.get(DesignDocument, el["designDocumentId"]).current_revision_id
            if s.get(DesignDocument, el["designDocumentId"])
            else None
        )
        prev = s.get(GeometryRevision, str(prev_id))
        if prev is None:
            raise ValueError("undo revision missing")
        payload = prev.payload if isinstance(prev.payload, dict) else {}
        topo = payload.get("topology") if isinstance(payload.get("topology"), dict) else {
            "members": [],
            "cells": [],
            "gridActivated": False,
        }
        # If previous revision is not structure for this element, clear topology
        if payload.get("elementId") and payload.get("elementId") != el["elementId"]:
            raise ValueError("undo revision belongs to another element")
        if payload.get("kind") == "structure_topology" or topo.get("cells") is not None:
            _restore_topology_from_payload(s, el, topo)
        if cur_id:
            redo.append(cur_id)
        hist["undo"] = undo
        hist["redo"] = redo[-50:]
        hist["currentRevisionId"] = prev.revision_id
        geo["_structureHistory"] = hist
        geo["gridActivated"] = bool(topo.get("gridActivated"))
        elem_row.geometry_payload = geo
        doc = s.get(DesignDocument, el["designDocumentId"])
        if doc is not None:
            doc.current_revision_id = prev.revision_id
        s.flush()
        return {
            "ok": True,
            "action": "undo",
            "revisionId": prev.revision_id,
            "topology": _topology_snapshot(s, el["elementId"]),
            "canUndo": bool(undo),
            "canRedo": bool(redo),
            "saveStatus": "saved",
        }


def redo_structure(*, element_id: str, company_gst: str) -> dict[str, Any]:
    _require_db()
    el = _get_owned_element(element_id, company_gst)
    from WEOS.db.models import DesignDocument, DesignElement, GeometryRevision

    with session_scope() as s:
        elem_row = s.get(DesignElement, el["elementId"])
        geo = dict(elem_row.geometry_payload) if isinstance(elem_row.geometry_payload, dict) else {}
        hist = dict(geo.get("_structureHistory") or {})
        undo = list(hist.get("undo") or [])
        redo = list(hist.get("redo") or [])
        if not redo:
            raise ValueError("nothing to redo")
        next_id = redo.pop()
        cur_id = hist.get("currentRevisionId")
        nxt = s.get(GeometryRevision, str(next_id))
        if nxt is None:
            raise ValueError("redo revision missing")
        payload = nxt.payload if isinstance(nxt.payload, dict) else {}
        topo = payload.get("topology") if isinstance(payload.get("topology"), dict) else {
            "members": [],
            "cells": [],
            "gridActivated": False,
        }
        _restore_topology_from_payload(s, el, topo)
        if cur_id:
            undo.append(cur_id)
        hist["undo"] = undo[-50:]
        hist["redo"] = redo
        hist["currentRevisionId"] = nxt.revision_id
        geo["_structureHistory"] = hist
        geo["gridActivated"] = bool(topo.get("gridActivated"))
        elem_row.geometry_payload = geo
        doc = s.get(DesignDocument, el["designDocumentId"])
        if doc is not None:
            doc.current_revision_id = nxt.revision_id
        s.flush()
        return {
            "ok": True,
            "action": "redo",
            "revisionId": nxt.revision_id,
            "topology": _topology_snapshot(s, el["elementId"]),
            "canUndo": bool(undo),
            "canRedo": bool(redo),
            "saveStatus": "saved",
        }


def apply_size_change(
    *,
    element_id: str,
    company_gst: str,
    width_mm: float,
    height_mm: float,
    size_change_rule: str,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    """Resize opening with existing grid — explicit KEEP_OFFSETS | SCALE | CANCEL only."""
    _require_db()
    rule = str(size_change_rule or "").strip().upper()
    if rule not in SIZE_CHANGE_RULES:
        raise ValueError(
            f"sizeChangeRule required: one of {SIZE_CHANGE_RULES}. {SIZE_CHANGE_RULE_DOC}"
        )
    if rule == "CANCEL":
        return {"ok": False, "cancelled": True, "rule": "CANCEL", "saveStatus": "unsaved"}

    try:
        new_w = float(width_mm)
        new_h = float(height_mm)
    except (TypeError, ValueError) as exc:
        raise ValueError("widthMm/heightMm must be numbers") from exc
    if new_w < MIN_CELL_MM or new_h < MIN_CELL_MM:
        raise ValueError("new size too small")

    el = _get_owned_element(element_id, company_gst)
    old_w = float(el["widthMm"] or 0)
    old_h = float(el["heightMm"] or 0)
    from WEOS.db.models import DesignCell, DesignElement, FrameMember

    with session_scope() as s:
        topo_before = _topology_snapshot(s, el["elementId"])
        if not topo_before.get("gridActivated"):
            # No grid — just update element size
            row = s.get(DesignElement, el["elementId"])
            row.width_mm = new_w
            row.height_mm = new_h
            s.flush()
            return {
                "ok": True,
                "rule": rule,
                "gridActivated": False,
                "element": row.to_dict(),
                "saveStatus": "saved",
            }

        sx = (new_w / old_w) if old_w > 0 else 1.0
        sy = (new_h / old_h) if old_h > 0 else 1.0

        if rule == "KEEP_OFFSETS":
            # Keep absolute positions; reject if any member/cell falls outside
            for m in _active_members(s, el["elementId"]):
                if m.orientation == "V":
                    if m.position_mm <= 0 or m.position_mm >= new_w:
                        raise ValueError(
                            f"KEEP_OFFSETS: member {m.display_code} at {m.position_mm} outside new width {new_w}"
                        )
                    m.y2_mm = new_h if abs(m.y2_mm - old_h) <= EDGE_TOLERANCE_MM else min(m.y2_mm, new_h)
                else:
                    if m.position_mm <= 0 or m.position_mm >= new_h:
                        raise ValueError(
                            f"KEEP_OFFSETS: member {m.display_code} at {m.position_mm} outside new height {new_h}"
                        )
                    m.x2_mm = new_w if abs(m.x2_mm - old_w) <= EDGE_TOLERANCE_MM else min(m.x2_mm, new_w)
            for c in _active_cells(s, el["elementId"]):
                if c.is_root:
                    c.width_mm = new_w
                    c.height_mm = new_h
                else:
                    if c.x_mm + c.width_mm > new_w + EDGE_TOLERANCE_MM or c.y_mm + c.height_mm > new_h + EDGE_TOLERANCE_MM:
                        raise ValueError(
                            f"KEEP_OFFSETS: cell {c.display_code} does not fit new opening — use SCALE or CANCEL"
                        )
        elif rule == "SCALE":
            for m in _active_members(s, el["elementId"]):
                if m.orientation == "V":
                    m.position_mm = float(m.position_mm) * sx
                    m.x1_mm = m.x2_mm = m.position_mm
                    m.y1_mm = float(m.y1_mm) * sy
                    m.y2_mm = float(m.y2_mm) * sy
                else:
                    m.position_mm = float(m.position_mm) * sy
                    m.y1_mm = m.y2_mm = m.position_mm
                    m.x1_mm = float(m.x1_mm) * sx
                    m.x2_mm = float(m.x2_mm) * sx
            for c in _active_cells(s, el["elementId"]):
                c.x_mm = float(c.x_mm) * sx
                c.y_mm = float(c.y_mm) * sy
                c.width_mm = float(c.width_mm) * sx
                c.height_mm = float(c.height_mm) * sy

        row = s.get(DesignElement, el["elementId"])
        row.width_mm = new_w
        row.height_mm = new_h
        el = row.to_dict()
        s.flush()
        topo = _topology_snapshot(s, el["elementId"])
        rev = _push_geometry_revision(
            s,
            el,
            label=f"size_change_{rule}_{new_w}x{new_h}",
            topology=topo,
            expected_revision_id=expected_revision_id,
        )
        return {
            "ok": True,
            "rule": rule,
            "ruleDoc": SIZE_CHANGE_RULE_DOC,
            "topology": topo,
            "revision": rev,
            "element": el,
            "saveStatus": "saved",
        }


def render_structural_svg(
    topology: Mapping[str, Any],
    *,
    width_mm: float,
    height_mm: float,
    world_x: float = 0.0,
    world_y: float = 0.0,
) -> str:
    """Honest structural topology drawing for canvas/PDF — not legacy product SVG."""
    w = max(1.0, float(width_mm))
    h = max(1.0, float(height_mm))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" data-weos-structural="1" data-batch="{BATCH_ID}">',
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="none" stroke="#1f2937" stroke-width="8"/>',
    ]
    for cell in topology.get("cells") or []:
        if not cell.get("isLeaf"):
            continue
        parts.append(
            f'<rect x="{float(cell["xMm"])}" y="{float(cell["yMm"])}" '
            f'width="{float(cell["widthMm"])}" height="{float(cell["heightMm"])}" '
            f'fill="rgba(148,163,184,0.08)" stroke="#94a3b8" stroke-width="1" '
            f'data-cell-id="{cell.get("cellId","")}" data-cell-code="{cell.get("displayCode","")}"/>'
        )
        cx = float(cell["xMm"]) + float(cell["widthMm"]) / 2
        cy = float(cell["yMm"]) + float(cell["heightMm"]) / 2
        parts.append(
            f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="middle" '
            f'font-size="14" fill="#64748b">{cell.get("displayCode") or ""}</text>'
        )
    for mem in topology.get("members") or []:
        parts.append(
            f'<line x1="{float(mem["x1Mm"])}" y1="{float(mem["y1Mm"])}" '
            f'x2="{float(mem["x2Mm"])}" y2="{float(mem["y2Mm"])}" '
            f'stroke="#0f172a" stroke-width="4" data-member-id="{mem.get("memberId","")}" '
            f'data-orientation="{mem.get("orientation","")}"/>'
        )
    parts.append("</svg>")
    _ = (world_x, world_y)  # reserved for world-space compositing
    return "".join(parts)


def pdf_drawing_for_element(element_id: str, *, company_gst: str) -> dict[str, Any]:
    """PDF safety: if grid activated, use structural SVG or fail-closed — never silent old drawing."""
    topo = get_element_topology(element_id, company_gst=company_gst)
    el = topo["element"]
    if not topo.get("gridActivated"):
        return {
            "mode": "product_svg",
            "pending": False,
            "code": None,
            "svg": None,
            "topology": topo,
        }
    geo_ready = True
    # If topology corrupt (no leaves), fail closed
    leaves = [c for c in (topo.get("cells") or []) if c.get("isLeaf")]
    if not leaves:
        return {
            "mode": "fail_closed",
            "pending": True,
            "code": STRUCTURAL_EDIT_PENDING_RENDER,
            "svg": None,
            "error": "structural topology activated but leaf cells missing",
            "topology": topo,
        }
    svg = render_structural_svg(
        topo,
        width_mm=float(el["widthMm"]),
        height_mm=float(el["heightMm"]),
        world_x=float(el["xMm"]),
        world_y=float(el["yMm"]),
    )
    if not svg or "data-weos-structural" not in svg:
        return {
            "mode": "fail_closed",
            "pending": True,
            "code": STRUCTURAL_EDIT_PENDING_RENDER,
            "svg": None,
            "error": "structural composite render not ready",
            "topology": topo,
        }
    return {
        "mode": "structural",
        "pending": False,
        "code": None,
        "svg": svg,
        "topology": topo,
        "compositeReady": geo_ready,
    }


def member_panel_schema(member: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "adapterId": "frame_member",
        "productType": None,
        "groups": [
            {
                "id": "member_geometry",
                "label": "Member",
                "fields": [
                    {"key": "displayCode", "label": "ID", "type": "text", "domain": "readonly"},
                    {"key": "orientation", "label": "Orientation", "type": "text", "domain": "readonly"},
                    {"key": "memberType", "label": "Type", "type": "select", "domain": "geometry",
                     "options": [{"value": t, "label": t} for t in MEMBER_TYPES]},
                    {"key": "positionMm", "label": "Position (mm)", "type": "number", "domain": "geometry"},
                    {"key": "x1Mm", "label": "X1", "type": "number", "domain": "readonly"},
                    {"key": "y1Mm", "label": "Y1", "type": "number", "domain": "readonly"},
                    {"key": "x2Mm", "label": "X2", "type": "number", "domain": "readonly"},
                    {"key": "y2Mm", "label": "Y2", "type": "number", "domain": "readonly"},
                ],
            }
        ],
        "guidance": "Structural member — profile/BOM deferred. No cell product assignment (Batch F).",
    }


def cell_panel_schema(cell: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "adapterId": "design_cell",
        "productType": None,
        "groups": [
            {
                "id": "cell_geometry",
                "label": "Cell",
                "fields": [
                    {"key": "displayCode", "label": "ID", "type": "text", "domain": "readonly"},
                    {"key": "widthMm", "label": "Width (mm)", "type": "number", "domain": "readonly"},
                    {"key": "heightMm", "label": "Height (mm)", "type": "number", "domain": "readonly"},
                    {"key": "xMm", "label": "X (mm)", "type": "number", "domain": "readonly"},
                    {"key": "yMm", "label": "Y (mm)", "type": "number", "domain": "readonly"},
                    {"key": "isLeaf", "label": "Leaf", "type": "text", "domain": "readonly"},
                ],
            }
        ],
        "guidance": "Cell geometry only. Product assignment (Sliding/Fixed/…) is Batch F — not available.",
        "batchFDeferred": True,
        "forbidProductAssignment": True,
    }


def panel_for_member(member: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "member",
        "title": f"Member {member.get('displayCode') or member.get('memberId')}",
        "guidance": "Edit position / type. Profile masters deferred.",
        "schema": member_panel_schema(member),
        "values": {
            "memberId": member.get("memberId"),
            "displayCode": member.get("displayCode"),
            "orientation": member.get("orientation"),
            "memberType": member.get("memberType"),
            "positionMm": member.get("positionMm"),
            "x1Mm": member.get("x1Mm"),
            "y1Mm": member.get("y1Mm"),
            "x2Mm": member.get("x2Mm"),
            "y2Mm": member.get("y2Mm"),
            "elementId": member.get("elementId"),
        },
        "selection": {
            "kind": "member",
            "memberId": member.get("memberId"),
            "elementId": member.get("elementId"),
            "cellId": None,
        },
    }


def panel_for_cell(cell: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "cell",
        "title": f"Cell {cell.get('displayCode') or cell.get('cellId')}",
        "guidance": "Cell selected. Product assignment deferred to Batch F.",
        "schema": cell_panel_schema(cell),
        "values": {
            "cellId": cell.get("cellId"),
            "displayCode": cell.get("displayCode"),
            "widthMm": cell.get("widthMm"),
            "heightMm": cell.get("heightMm"),
            "xMm": cell.get("xMm"),
            "yMm": cell.get("yMm"),
            "isLeaf": cell.get("isLeaf"),
            "elementId": cell.get("elementId"),
            # Explicitly omit Sliding/Fixed assignment controls
        },
        "selection": {
            "kind": "cell",
            "cellId": cell.get("cellId"),
            "elementId": cell.get("elementId"),
            "memberId": None,
        },
        "forbidProductAssignment": True,
    }


def get_member(member_id: str, *, company_gst: str) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import FrameMember

    with session_scope() as s:
        row = s.get(FrameMember, str(member_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            return None
        return row.to_dict()


def get_cell(cell_id: str, *, company_gst: str) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import DesignCell

    with session_scope() as s:
        row = s.get(DesignCell, str(cell_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            return None
        d = row.to_dict()
        d["productAssignment"] = None
        return d
