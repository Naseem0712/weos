"""Canvas Batch G — Composite design deep-copy with ID remapping.

Deep-copies Assembly/Element topology (FrameMembers, DesignCells),
CellProductAssignments, and relevant Connections. Never mutates the source.
Different-size duplicates require explicit KEEP_OFFSETS | SCALE (never silent).
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Mapping, Sequence

BATCH_ID = "CANVAS-G"
SIZE_RULES = ("KEEP_OFFSETS", "SCALE")


def _norm_gst(v: str | None) -> str:
    return str(v or "").strip().upper()


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def find_element_for_line(
    *,
    project_id: str,
    company_gst: str,
    line_id: str,
) -> dict[str, Any] | None:
    """Resolve SQL DesignElement linked via legacy_line_id."""
    from sqlalchemy import select

    from WEOS.db.engine import db_available, init_db, session_scope
    from WEOS.db.models import DesignElement

    if not db_available():
        return None
    init_db()
    lid = _str(line_id)
    if not lid:
        return None
    gst = _norm_gst(company_gst)
    pid = _str(project_id)
    with session_scope() as s:
        row = s.execute(
            select(DesignElement).where(
                DesignElement.project_id == pid,
                DesignElement.company_gst == gst,
                DesignElement.legacy_line_id == lid,
                DesignElement.status != "retired",
            )
        ).scalars().first()
        return row.to_dict() if row else None


def _dims_differ(src_w: float, src_h: float, new_w: float, new_h: float, tol: float = 0.5) -> bool:
    return abs(src_w - new_w) > tol or abs(src_h - new_h) > tol


def _remap_topology_payload(
    topology: Mapping[str, Any],
    *,
    new_element: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    """Mint new cell/member IDs and rewrite parent/split/span references."""
    from WEOS.factory.member_grid import new_cell_id, new_member_id

    cell_map: dict[str, str] = {}
    member_map: dict[str, str] = {}
    cells_in = list(topology.get("cells") or [])
    members_in = list(topology.get("members") or [])

    for c in cells_in:
        old = _str(c.get("cellId"))
        if old and old not in cell_map:
            cell_map[old] = new_cell_id()
    for m in members_in:
        old = _str(m.get("memberId"))
        if old and old not in member_map:
            member_map[old] = new_member_id()

    new_cells: list[dict[str, Any]] = []
    for c in cells_in:
        old = _str(c.get("cellId"))
        parent = _str(c.get("parentCellId")) or None
        split = _str(c.get("splitByMemberId")) or None
        nd = copy.deepcopy(dict(c))
        nd["cellId"] = cell_map[old]
        nd["elementId"] = new_element["elementId"]
        nd["assemblyId"] = new_element["assemblyId"]
        nd["designDocumentId"] = new_element["designDocumentId"]
        nd["projectId"] = new_element["projectId"]
        nd["companyGst"] = new_element["companyGst"]
        nd["parentCellId"] = cell_map.get(parent) if parent else None
        nd["splitByMemberId"] = member_map.get(split) if split else None
        nd["status"] = "active"
        new_cells.append(nd)

    new_members: list[dict[str, Any]] = []
    for m in members_in:
        old = _str(m.get("memberId"))
        span = _str(m.get("spanCellId")) or None
        parent_m = _str(m.get("parentMemberId")) or None
        nd = copy.deepcopy(dict(m))
        nd["memberId"] = member_map[old]
        nd["elementId"] = new_element["elementId"]
        nd["assemblyId"] = new_element["assemblyId"]
        nd["designDocumentId"] = new_element["designDocumentId"]
        nd["projectId"] = new_element["projectId"]
        nd["companyGst"] = new_element["companyGst"]
        nd["spanCellId"] = cell_map.get(span) if span else None
        nd["parentMemberId"] = member_map.get(parent_m) if parent_m else None
        nd["status"] = "active"
        new_members.append(nd)

    out = {
        "batch": BATCH_ID,
        "elementId": new_element["elementId"],
        "members": new_members,
        "cells": new_cells,
        "memberCount": len(new_members),
        "cellCount": len(new_cells),
        "leafCellCount": sum(1 for c in new_cells if c.get("isLeaf")),
        "gridActivated": any(c.get("isRoot") for c in new_cells),
    }
    return out, cell_map, member_map


def _insert_remapped_topology(
    *,
    new_element: Mapping[str, Any],
    remapped: Mapping[str, Any],
) -> None:
    """Persist remapped cells/members onto a fresh element (no prior active topology)."""
    from WEOS.db.engine import session_scope
    from WEOS.db.models import DesignCell, FrameMember
    from WEOS.factory import member_grid as mg

    eid = new_element["elementId"]
    with session_scope() as s:
        # Parent-before-child: roots first, then by sort
        cells = sorted(
            list(remapped.get("cells") or []),
            key=lambda c: (0 if c.get("isRoot") else 1, int(c.get("sortOrder") or 0), str(c.get("displayCode") or "")),
        )
        for cd in cells:
            s.add(
                DesignCell(
                    cell_id=str(cd["cellId"]),
                    element_id=eid,
                    assembly_id=new_element["assemblyId"],
                    design_document_id=new_element["designDocumentId"],
                    project_id=new_element["projectId"],
                    company_gst=new_element["companyGst"],
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
                    meta={**(cd.get("meta") or {}), "batch": BATCH_ID, "duplicatedFrom": True},
                )
            )
        for md in remapped.get("members") or []:
            s.add(
                FrameMember(
                    member_id=str(md["memberId"]),
                    element_id=eid,
                    assembly_id=new_element["assemblyId"],
                    design_document_id=new_element["designDocumentId"],
                    project_id=new_element["projectId"],
                    company_gst=new_element["companyGst"],
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
                    meta={**(md.get("meta") or {}), "batch": BATCH_ID, "duplicatedFrom": True},
                )
            )
        s.flush()
        # Push geometry revision on the new element
        el = dict(new_element)
        topo = mg._topology_snapshot(s, eid)  # noqa: SLF001
        mg._push_geometry_revision(  # noqa: SLF001
            s,
            el,
            label="composite_duplicate_clone",
            topology=topo,
            expected_revision_id=None,
        )


def _copy_intra_assembly_connections(
    *,
    source_assembly_id: str,
    target_assembly_id: str,
    element_id_map: Mapping[str, str],
    company_gst: str,
) -> list[dict[str, Any]]:
    """Deep-copy connections whose both ends are in the remapped set."""
    from WEOS.factory import design_scene as ds

    src = ds.list_connections(source_assembly_id, company_gst=company_gst)
    out: list[dict[str, Any]] = []
    for con in src:
        a = element_id_map.get(_str(con.get("elementAId")))
        b = element_id_map.get(_str(con.get("elementBId")))
        if not a or not b:
            # Connection points outside remapped set — fail closed for that link
            raise ValueError(
                f"Cannot safely copy connection {con.get('connectionId')}: "
                "endpoint not remapped (would point at original element)"
            )
        created = ds.create_connection(
            assembly_id=target_assembly_id,
            company_gst=company_gst,
            element_a_id=a,
            element_b_id=b,
            connection_type=_str(con.get("connectionType") or "adjacent_independent"),
            side_a=con.get("sideA"),
            side_b=con.get("sideB"),
            parameters=copy.deepcopy(con.get("parameters")) if isinstance(con.get("parameters"), dict) else con.get("parameters"),
        )
        out.append(created)
    return out


def regenerate_composite_preview(element_id: str, *, company_gst: str) -> dict[str, Any]:
    """Authoritative preview from new model — never raw SVG clone as SoT."""
    from WEOS.factory import cell_assignment as ca
    from WEOS.factory import member_grid as mg

    topo = mg.get_element_topology(element_id, company_gst=company_gst)
    if not topo.get("gridActivated"):
        return {
            "ok": True,
            "mode": "product_svg",
            "svg": "",
            "compositionSummary": "",
            "needsRegen": True,
        }
    pre = ca.pdf_preflight_composite(element_id, company_gst=company_gst)
    if not pre.get("ok"):
        # Structural SVG still useful for cards; PDF remains fail-closed
        svg = mg.render_structural_svg(
            topo,
            width_mm=float(topo["element"]["widthMm"]),
            height_mm=float(topo["element"]["heightMm"]),
        )
        return {
            "ok": False,
            "mode": "structural_pending",
            "svg": svg,
            "compositionSummary": "",
            "error": pre.get("error"),
            "missing": pre.get("missing") or [],
            "needsRegen": False,
        }
    return {
        "ok": True,
        "mode": "composite",
        "svg": pre.get("svg") or "",
        "compositionSummary": pre.get("compositionSummary") or "",
        "needsRegen": False,
    }


def duplicate_composite_element(
    *,
    source_element_id: str,
    company_gst: str,
    new_legacy_line_id: str,
    width_mm: float | None = None,
    height_mm: float | None = None,
    size_change_rule: str | None = None,
    location_id: str | None = None,
    display_code: str | None = None,
    assembly_name: str | None = None,
    copy_connections: bool = True,
) -> dict[str, Any]:
    """Deep-copy one composite element → new Assembly + Element + topology + assignments.

    Same-size: no size rule required.
    Different-size: size_change_rule must be KEEP_OFFSETS or SCALE (never silent).
    """
    from WEOS.db.engine import db_available, init_db
    from WEOS.factory import cell_assignment as ca
    from WEOS.factory import design_scene as ds
    from WEOS.factory import member_grid as mg

    if not db_available():
        raise RuntimeError("Database unavailable for composite duplicate")
    init_db()

    gst = _norm_gst(company_gst)
    src = ds.get_element(source_element_id, company_gst=gst)
    if src is None:
        raise PermissionError("source element not found for company")
    src_asm = ds.get_assembly(src["assemblyId"], company_gst=gst)
    if src_asm is None:
        raise PermissionError("source assembly not found for company")

    topo = mg.get_element_topology(src["elementId"], company_gst=gst)
    src_w = float(src["widthMm"] or 0)
    src_h = float(src["heightMm"] or 0)
    new_w = float(width_mm) if width_mm is not None else src_w
    new_h = float(height_mm) if height_mm is not None else src_h
    if new_w <= 0 or new_h <= 0:
        raise ValueError("widthMm/heightMm must be positive")

    differ = _dims_differ(src_w, src_h, new_w, new_h)
    rule = _str(size_change_rule).upper() or None
    if differ:
        if not rule:
            raise ValueError(
                "sizeChangeRule required when dimensions differ: KEEP_OFFSETS or SCALE "
                "(never silent guess)"
            )
        if rule not in SIZE_RULES:
            raise ValueError(f"sizeChangeRule must be one of {SIZE_RULES}")
    else:
        rule = None  # same-size — topology copy is exact

    # Create at SOURCE size first so KEEP_OFFSETS/SCALE validation matches Batch E semantics
    new_asm = ds.create_assembly(
        design_document_id=src["designDocumentId"],
        company_gst=gst,
        name=assembly_name or (src_asm.get("name") or "Duplicated"),
        location_id=location_id if location_id is not None else src_asm.get("locationId"),
        legacy_line_id=new_legacy_line_id,
        status="draft",
    )
    new_el = ds.create_element(
        assembly_id=new_asm["assemblyId"],
        company_gst=gst,
        product_type=src["productType"],
        width_mm=src_w,
        height_mm=src_h,
        x_mm=float(src.get("xMm") or 0),
        y_mm=float(src.get("yMm") or 0),
        display_code=display_code,
        product_id=src.get("productId"),
        orientation=src.get("orientation"),
        sill_height_mm=src.get("sillHeightMm"),
        quantity=int(src.get("quantity") or 1),
        geometry_payload={},
        config_payload=copy.deepcopy(src.get("configPayload") or {}),
        legacy_line_id=new_legacy_line_id,
        status="draft",
    )

    cell_map: dict[str, str] = {}
    member_map: dict[str, str] = {}
    if topo.get("gridActivated") and (topo.get("cells") or topo.get("members")):
        remapped, cell_map, member_map = _remap_topology_payload(topo, new_element=new_el)
        _insert_remapped_topology(new_element=new_el, remapped=remapped)
        ca.deep_copy_assignments(
            source_element_id=src["elementId"],
            target_element_id=new_el["elementId"],
            cell_id_map=cell_map,
            company_gst=gst,
        )

    element_id_map = {src["elementId"]: new_el["elementId"]}
    connections: list[dict[str, Any]] = []
    if copy_connections:
        # Only copy connections wholly contained in the remapped element set
        src_cons = ds.list_connections(src["assemblyId"], company_gst=gst)
        for con in src_cons:
            a = _str(con.get("elementAId"))
            b = _str(con.get("elementBId"))
            if a in element_id_map and b in element_id_map:
                connections.append(
                    ds.create_connection(
                        assembly_id=new_asm["assemblyId"],
                        company_gst=gst,
                        element_a_id=element_id_map[a],
                        element_b_id=element_id_map[b],
                        connection_type=_str(con.get("connectionType") or "adjacent_independent"),
                        side_a=con.get("sideA"),
                        side_b=con.get("sideB"),
                        parameters=copy.deepcopy(con.get("parameters"))
                        if isinstance(con.get("parameters"), dict)
                        else con.get("parameters"),
                    )
                )
            elif a == src["elementId"] or b == src["elementId"]:
                # Partial link to sibling not being duplicated — skip (single-element dup)
                pass

    if differ and rule:
        try:
            mg.apply_size_change(
                element_id=new_el["elementId"],
                company_gst=gst,
                width_mm=new_w,
                height_mm=new_h,
                size_change_rule=rule,
            )
        except ValueError:
            # Leave failed duplicate cleaned? Prefer retire on failure so retry is clean.
            retire_element_tree(new_el["elementId"], company_gst=gst, reason="size_change_rejected")
            raise

    # Refresh element after possible size change
    new_el = ds.get_element(new_el["elementId"], company_gst=gst) or new_el
    preview = regenerate_composite_preview(new_el["elementId"], company_gst=gst)
    new_topo = mg.get_element_topology(new_el["elementId"], company_gst=gst)
    assignments = ca.list_assignments_for_element(new_el["elementId"], company_gst=gst)

    # Source isolation check helpers
    src_after = ds.get_element(src["elementId"], company_gst=gst)
    src_topo_after = mg.get_element_topology(src["elementId"], company_gst=gst)

    return {
        "ok": True,
        "batch": BATCH_ID,
        "sourceElementId": src["elementId"],
        "sourceAssemblyId": src["assemblyId"],
        "assembly": new_asm,
        "element": new_el,
        "topology": new_topo,
        "assignments": assignments,
        "cellIdMap": cell_map,
        "memberIdMap": member_map,
        "elementIdMap": element_id_map,
        "connections": connections,
        "sizeChangeRule": rule,
        "preview": preview,
        "compositionSummary": preview.get("compositionSummary")
        or ca.composition_summary(assignments, new_topo.get("cells") or []),
        "sourceUnchanged": {
            "elementId": src["elementId"],
            "widthMm": (src_after or src).get("widthMm"),
            "heightMm": (src_after or src).get("heightMm"),
            "memberCount": src_topo_after.get("memberCount"),
            "cellCount": src_topo_after.get("cellCount"),
            "legacyLineId": (src_after or src).get("legacyLineId"),
        },
    }


def retire_element_tree(
    element_id: str,
    *,
    company_gst: str,
    reason: str = "retired",
) -> dict[str, Any]:
    """Soft-retire element + active members/cells/assignments (ownership-safe)."""
    from sqlalchemy import select

    from WEOS.db.engine import db_available, init_db, session_scope
    from WEOS.db.models import (
        Assembly,
        CellProductAssignment,
        DesignCell,
        DesignElement,
        FrameMember,
    )

    if not db_available():
        raise RuntimeError("Database unavailable")
    init_db()
    gst = _norm_gst(company_gst)
    with session_scope() as s:
        el = s.get(DesignElement, str(element_id).strip())
        if el is None or _norm_gst(el.company_gst) != gst:
            raise PermissionError("element not found for company")
        eid = el.element_id
        for a in s.execute(
            select(CellProductAssignment).where(
                CellProductAssignment.element_id == eid,
                CellProductAssignment.status == "active",
            )
        ).scalars().all():
            a.status = "superseded"
        for m in s.execute(
            select(FrameMember).where(
                FrameMember.element_id == eid,
                FrameMember.status == "active",
            )
        ).scalars().all():
            m.status = "deleted"
        for c in s.execute(
            select(DesignCell).where(
                DesignCell.element_id == eid,
                DesignCell.status == "active",
            )
        ).scalars().all():
            c.status = "superseded"
        el.status = "retired"
        el.legacy_line_id = None
        asm_id = el.assembly_id
        # Retire assembly if no other active elements
        others = s.execute(
            select(DesignElement).where(
                DesignElement.assembly_id == asm_id,
                DesignElement.element_id != eid,
                DesignElement.status != "retired",
            )
        ).scalars().all()
        if not others:
            asm = s.get(Assembly, asm_id)
            if asm is not None:
                asm.status = "retired"
                asm.legacy_line_id = None
        s.flush()
        return {
            "ok": True,
            "batch": BATCH_ID,
            "elementId": eid,
            "assemblyId": asm_id,
            "reason": reason,
            "status": "retired",
        }


def new_idempotency_token() -> str:
    return "IDEM-" + uuid.uuid4().hex[:20].upper()
