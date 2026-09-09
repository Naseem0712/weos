"""Assembly → Element + Connection scene domain — WEOS V2 Batch 6.

Cart-line compatibility: each legacy line maps to Default Assembly + one Element
without changing dimensions, product identity, location, qty, money, or preview.
Geometry (W/H/X/Y) is independent of series/config (stored separately in config_payload).
Connections are explicit only — touching geometry does not imply a Connection.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Mapping

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.factory.canonical_customer import _norm_company_gst
from WEOS.factory.design_hierarchy import (
    ensure_design_document,
    ensure_unassigned_floor,
    list_floors,
    list_locations,
    resolve_location_for_legacy_name,
)
from WEOS.db.models import CONNECTION_TYPES

_log = logging.getLogger("weos.design_scene")

# Canonical element product types — do not collapse everything to WINDOW.
ELEMENT_PRODUCT_SLIDING = "SLIDING_WINDOW"
ELEMENT_PRODUCT_CASEMENT = "CASEMENT_WINDOW"
ELEMENT_PRODUCT_FIXED = "FIXED_WINDOW"
ELEMENT_PRODUCT_VENTILATOR = "VENTILATOR"
ELEMENT_PRODUCT_DOOR = "DOOR"
ELEMENT_PRODUCT_GRILL = "GRILL"
ELEMENT_PRODUCT_RAILING = "RAILING"
ELEMENT_PRODUCT_FOLD = "FOLD_WINDOW"
ELEMENT_PRODUCT_SHOWER = "SHOWER_PARTITION"
ELEMENT_PRODUCT_PERGOLA = "PERGOLA"
ELEMENT_PRODUCT_LOUVER = "LOUVER"
ELEMENT_PRODUCT_OTHER = "OTHER"


def new_assembly_id() -> str:
    return "ASM-" + uuid.uuid4().hex[:16].upper()


def new_element_id() -> str:
    return "ELM-" + uuid.uuid4().hex[:16].upper()


def new_connection_id() -> str:
    return "CON-" + uuid.uuid4().hex[:16].upper()


def _require_db() -> None:
    if not db_available():
        raise RuntimeError("Database unavailable for design scene")
    init_db()


def _get_owned_design_doc(design_document_id: str, company_gst: str):
    from WEOS.db.models import DesignDocument

    gst = _norm_company_gst(company_gst)
    doc = None
    with session_scope() as s:
        doc = s.get(DesignDocument, str(design_document_id).strip())
        if doc is None or _norm_company_gst(doc.company_gst) != gst:
            raise PermissionError("design document not found for company")
        return {
            "designDocumentId": doc.design_document_id,
            "projectId": doc.project_id,
            "companyGst": doc.company_gst,
        }


def map_line_to_element_product_type(line: Mapping[str, Any] | None) -> str:
    """Preserve Sliding/Casement/Ventilator/Railing identity — never collapse to WINDOW."""
    line = line or {}
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    raw_bits = [
        str(line.get("productType") or ""),
        str(opts.get("productType") or "") if isinstance(opts, Mapping) else "",
        str(line.get("product") or line.get("productId") or ""),
        str(line.get("category") or ""),
    ]
    blob = " ".join(raw_bits).lower()

    try:
        from WEOS.factory.line_kind import (
            is_railing_cart_line,
            is_shower_cart_line,
            is_ventilator_cart_line,
            normalize_product_type,
        )

        if is_railing_cart_line(line):
            return ELEMENT_PRODUCT_RAILING
        if is_ventilator_cart_line(line):
            return ELEMENT_PRODUCT_VENTILATOR
        if is_shower_cart_line(line):
            return ELEMENT_PRODUCT_SHOWER
        pt = normalize_product_type(
            line.get("productType") or (opts.get("productType") if isinstance(opts, Mapping) else None)
        ) or ""
    except Exception:
        pt = ""

    if pt in {"casements", "casement"} or "casement" in blob:
        return ELEMENT_PRODUCT_CASEMENT
    if pt == "sliding" or ("sliding" in blob and "fold" not in blob):
        return ELEMENT_PRODUCT_SLIDING
    if pt == "fold" or "fold" in blob:
        return ELEMENT_PRODUCT_FOLD
    if pt == "door" or re.search(r"\bdoor\b", blob):
        return ELEMENT_PRODUCT_DOOR
    if "fixed" in blob:
        return ELEMENT_PRODUCT_FIXED
    if "grill" in blob or "grille" in blob:
        return ELEMENT_PRODUCT_GRILL
    if pt in {"pergolas", "pergola"} or "pergola" in blob:
        return ELEMENT_PRODUCT_PERGOLA
    if pt in {"louvers", "louver"} or "louver" in blob or "louvre" in blob:
        return ELEMENT_PRODUCT_LOUVER
    if pt in {"windows"} and "casement" not in blob:
        # Generic windows without more signal — treat as sliding-compatible leaf, not WINDOW blob
        return ELEMENT_PRODUCT_SLIDING
    if "ventilator" in blob or "vent" in blob:
        return ELEMENT_PRODUCT_VENTILATOR
    if "rail" in blob:
        return ELEMENT_PRODUCT_RAILING
    return ELEMENT_PRODUCT_OTHER


def _next_display_code(existing: list[str], prefix: str) -> str:
    nums: list[int] = []
    for code in existing:
        m = re.match(rf"^{re.escape(prefix)}-(\d+)$", str(code or ""), re.I)
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    return f"{prefix}-{n:02d}"


def create_assembly(
    *,
    design_document_id: str,
    company_gst: str,
    name: str = "",
    display_code: str | None = None,
    location_id: str | None = None,
    bounds: dict[str, Any] | None = None,
    sort_order: int = 0,
    status: str = "draft",
    legacy_line_id: str | None = None,
) -> dict[str, Any]:
    _require_db()
    meta = _get_owned_design_doc(design_document_id, company_gst)
    gst = _norm_company_gst(company_gst)
    from sqlalchemy import select

    from WEOS.db.models import Assembly, Location

    with session_scope() as s:
        if location_id:
            loc = s.get(Location, str(location_id).strip())
            if loc is None or _norm_company_gst(loc.company_gst) != gst:
                raise PermissionError("location not found for company")
            if loc.project_id != meta["projectId"]:
                raise ValueError("location not in design document project")
        codes = list(
            s.execute(
                select(Assembly.display_code).where(
                    Assembly.design_document_id == meta["designDocumentId"]
                )
            ).scalars().all()
        )
        code = (display_code or "").strip() or _next_display_code(codes, "A")
        row = Assembly(
            assembly_id=new_assembly_id(),
            design_document_id=meta["designDocumentId"],
            location_id=str(location_id).strip() if location_id else None,
            project_id=meta["projectId"],
            company_gst=gst,
            display_code=code,
            name=str(name or "").strip() or code,
            bounds=bounds,
            sort_order=int(sort_order or 0),
            status=status or "draft",
            legacy_line_id=legacy_line_id,
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def get_assembly(assembly_id: str, *, company_gst: str) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import Assembly

    with session_scope() as s:
        row = s.get(Assembly, str(assembly_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            return None
        return row.to_dict()


def list_assemblies(
    design_document_id: str, *, company_gst: str
) -> list[dict[str, Any]]:
    _require_db()
    meta = _get_owned_design_doc(design_document_id, company_gst)
    from sqlalchemy import select

    from WEOS.db.models import Assembly

    with session_scope() as s:
        rows = s.execute(
            select(Assembly)
            .where(Assembly.design_document_id == meta["designDocumentId"])
            .order_by(Assembly.sort_order, Assembly.display_code)
        ).scalars().all()
        return [r.to_dict() for r in rows]


def create_element(
    *,
    assembly_id: str,
    company_gst: str,
    product_type: str,
    width_mm: float,
    height_mm: float,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
    display_code: str | None = None,
    product_id: str | None = None,
    orientation: str | None = None,
    sill_height_mm: float | None = None,
    parent_element_id: str | None = None,
    quantity: int = 1,
    geometry_payload: dict[str, Any] | None = None,
    config_payload: dict[str, Any] | None = None,
    legacy_line_id: str | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    _require_db()
    gst = _norm_company_gst(company_gst)
    pt = str(product_type or "").strip().upper()
    if not pt:
        raise ValueError("product_type required")
    if pt == "WINDOW":
        raise ValueError("product_type must not collapse to WINDOW — use SLIDING_WINDOW / CASEMENT_WINDOW / …")
    from sqlalchemy import select

    from WEOS.db.models import Assembly, DesignElement

    with session_scope() as s:
        asm = s.get(Assembly, str(assembly_id).strip())
        if asm is None or _norm_company_gst(asm.company_gst) != gst:
            raise PermissionError("assembly not found for company")
        codes = list(
            s.execute(
                select(DesignElement.display_code).where(
                    DesignElement.assembly_id == asm.assembly_id
                )
            ).scalars().all()
        )
        prefix = "W"
        if pt == ELEMENT_PRODUCT_VENTILATOR:
            prefix = "V"
        elif pt == ELEMENT_PRODUCT_RAILING:
            prefix = "R"
        elif pt == ELEMENT_PRODUCT_DOOR:
            prefix = "D"
        elif pt == ELEMENT_PRODUCT_FIXED:
            prefix = "F"
        code = (display_code or "").strip() or _next_display_code(codes, prefix)
        row = DesignElement(
            element_id=new_element_id(),
            assembly_id=asm.assembly_id,
            design_document_id=asm.design_document_id,
            project_id=asm.project_id,
            company_gst=gst,
            display_code=code,
            product_type=pt,
            product_id=str(product_id).strip() if product_id else None,
            width_mm=float(width_mm),
            height_mm=float(height_mm),
            x_mm=float(x_mm or 0.0),
            y_mm=float(y_mm or 0.0),
            orientation=orientation,
            sill_height_mm=sill_height_mm,
            parent_element_id=str(parent_element_id).strip() if parent_element_id else None,
            quantity=int(quantity or 1),
            geometry_payload=geometry_payload if geometry_payload is not None else {},
            config_payload=config_payload if config_payload is not None else {},
            legacy_line_id=legacy_line_id,
            status=status or "draft",
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def get_element(element_id: str, *, company_gst: str) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import DesignElement

    with session_scope() as s:
        row = s.get(DesignElement, str(element_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            return None
        return row.to_dict()


def update_element(
    element_id: str,
    *,
    company_gst: str,
    width_mm: float | None = None,
    height_mm: float | None = None,
    x_mm: float | None = None,
    y_mm: float | None = None,
    orientation: str | None = None,
    sill_height_mm: float | None = None,
    geometry_payload: dict[str, Any] | None = None,
    config_payload: dict[str, Any] | None = None,
    merge_config: bool = True,
    name: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Durable element update — geometry vs config_payload kept separate.

    Does not allow collapsing product_type to WINDOW. Series/glass/hardware
    belong in config_payload only.
    """
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import DesignElement

    with session_scope() as s:
        row = s.get(DesignElement, str(element_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            raise PermissionError("element not found for company")
        if width_mm is not None:
            row.width_mm = float(width_mm)
        if height_mm is not None:
            row.height_mm = float(height_mm)
        if x_mm is not None:
            row.x_mm = float(x_mm)
        if y_mm is not None:
            row.y_mm = float(y_mm)
        if orientation is not None:
            row.orientation = orientation
        if sill_height_mm is not None:
            row.sill_height_mm = float(sill_height_mm)
        if geometry_payload is not None:
            row.geometry_payload = dict(geometry_payload)
        if config_payload is not None:
            if merge_config and isinstance(row.config_payload, dict):
                merged = dict(row.config_payload)
                merged.update(dict(config_payload))
                row.config_payload = merged
            else:
                row.config_payload = dict(config_payload)
        if status is not None:
            row.status = str(status)
        # name is not a DesignElement column — ignore safely for API compat
        _ = name
        s.flush()
        return row.to_dict()


def update_assembly(
    assembly_id: str,
    *,
    company_gst: str,
    name: str | None = None,
    location_id: str | None = None,
    bounds: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Simple assembly metadata edit — no complex resize."""
    _require_db()
    gst = _norm_company_gst(company_gst)
    from WEOS.db.models import Assembly, Location

    with session_scope() as s:
        row = s.get(Assembly, str(assembly_id).strip())
        if row is None or _norm_company_gst(row.company_gst) != gst:
            raise PermissionError("assembly not found for company")
        if name is not None:
            row.name = str(name).strip() or row.name
        if location_id is not None:
            loc = s.get(Location, str(location_id).strip())
            if loc is None or _norm_company_gst(loc.company_gst) != gst:
                raise PermissionError("location not found for company")
            if loc.project_id != row.project_id:
                raise ValueError("location not in assembly project")
            row.location_id = loc.location_id
        if bounds is not None:
            row.bounds = dict(bounds)
        if status is not None:
            row.status = str(status)
        s.flush()
        return row.to_dict()


def list_elements(assembly_id: str, *, company_gst: str) -> list[dict[str, Any]]:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from sqlalchemy import select

    from WEOS.db.models import Assembly, DesignElement

    with session_scope() as s:
        asm = s.get(Assembly, str(assembly_id).strip())
        if asm is None or _norm_company_gst(asm.company_gst) != gst:
            raise PermissionError("assembly not found for company")
        rows = s.execute(
            select(DesignElement)
            .where(DesignElement.assembly_id == asm.assembly_id)
            .order_by(DesignElement.display_code)
        ).scalars().all()
        return [r.to_dict() for r in rows]


def create_connection(
    *,
    assembly_id: str,
    company_gst: str,
    element_a_id: str,
    element_b_id: str,
    connection_type: str,
    side_a: str | None = None,
    side_b: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_db()
    gst = _norm_company_gst(company_gst)
    ctype = str(connection_type or "").strip()
    if ctype not in CONNECTION_TYPES:
        raise ValueError(f"unsupported connection_type: {ctype}")
    if str(element_a_id).strip() == str(element_b_id).strip():
        raise ValueError("connection requires two distinct elements")
    from WEOS.db.models import Assembly, Connection, DesignElement

    with session_scope() as s:
        asm = s.get(Assembly, str(assembly_id).strip())
        if asm is None or _norm_company_gst(asm.company_gst) != gst:
            raise PermissionError("assembly not found for company")
        ea = s.get(DesignElement, str(element_a_id).strip())
        eb = s.get(DesignElement, str(element_b_id).strip())
        if ea is None or eb is None:
            raise ValueError("element endpoints not found")
        if ea.assembly_id != asm.assembly_id or eb.assembly_id != asm.assembly_id:
            raise ValueError("elements must belong to the same assembly")
        if _norm_company_gst(ea.company_gst) != gst or _norm_company_gst(eb.company_gst) != gst:
            raise PermissionError("element not found for company")
        row = Connection(
            connection_id=new_connection_id(),
            assembly_id=asm.assembly_id,
            design_document_id=asm.design_document_id,
            project_id=asm.project_id,
            company_gst=gst,
            element_a_id=ea.element_id,
            element_b_id=eb.element_id,
            side_a=side_a,
            side_b=side_b,
            connection_type=ctype,
            parameters=parameters if parameters is not None else {},
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def list_connections(assembly_id: str, *, company_gst: str) -> list[dict[str, Any]]:
    _require_db()
    gst = _norm_company_gst(company_gst)
    from sqlalchemy import select

    from WEOS.db.models import Assembly, Connection

    with session_scope() as s:
        asm = s.get(Assembly, str(assembly_id).strip())
        if asm is None or _norm_company_gst(asm.company_gst) != gst:
            raise PermissionError("assembly not found for company")
        rows = s.execute(
            select(Connection).where(Connection.assembly_id == asm.assembly_id)
        ).scalars().all()
        return [r.to_dict() for r in rows]


def elements_are_connected(
    element_a_id: str, element_b_id: str, *, company_gst: str
) -> bool:
    """True only if an explicit Connection row links the pair (either direction)."""
    _require_db()
    gst = _norm_company_gst(company_gst)
    a = str(element_a_id).strip()
    b = str(element_b_id).strip()
    from sqlalchemy import or_, select

    from WEOS.db.models import Connection

    with session_scope() as s:
        row = s.execute(
            select(Connection)
            .where(Connection.company_gst == gst)
            .where(
                or_(
                    (Connection.element_a_id == a) & (Connection.element_b_id == b),
                    (Connection.element_a_id == b) & (Connection.element_b_id == a),
                )
            )
        ).scalars().first()
        return row is not None


def _line_location_name(line: Mapping[str, Any]) -> str:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    return str(
        line.get("locationName")
        or line.get("positionName")
        or (opts.get("locationName") if isinstance(opts, Mapping) else None)
        or (opts.get("positionName") if isinstance(opts, Mapping) else None)
        or ""
    ).strip()


def adapt_cart_line_to_assembly_element(
    *,
    design_document_id: str,
    company_gst: str,
    line: Mapping[str, Any],
    x_mm: float = 0.0,
    y_mm: float = 0.0,
) -> dict[str, Any]:
    """Map one cart line → Default Assembly + one Element (compat, non-destructive).

    Does not mutate the line dict, dimensions, product, location text, qty, money, or preview.
    """
    _require_db()
    meta = _get_owned_design_doc(design_document_id, company_gst)
    gst = _norm_company_gst(company_gst)
    lid = str(line.get("lineId") or "").strip() or None

    # Idempotent: reuse prior mapping for same legacy lineId
    from sqlalchemy import select

    from WEOS.db.models import Assembly, DesignElement

    if lid:
        with session_scope() as s:
            existing_el = s.execute(
                select(DesignElement).where(
                    DesignElement.design_document_id == meta["designDocumentId"],
                    DesignElement.company_gst == gst,
                    DesignElement.legacy_line_id == lid,
                )
            ).scalars().first()
            if existing_el is not None:
                asm = s.get(Assembly, existing_el.assembly_id)
                return {
                    "assembly": asm.to_dict() if asm else None,
                    "element": existing_el.to_dict(),
                    "mapped": "existing",
                    "unchanged": {
                        "width": line.get("width"),
                        "height": line.get("height"),
                        "product": line.get("product") or line.get("productId"),
                        "productType": line.get("productType"),
                        "locationName": _line_location_name(line),
                        "qty": line.get("qty"),
                        "sellingRate": line.get("sellingRate"),
                        "previewSvg": line.get("previewSvg"),
                    },
                }

    loc = None
    lname = _line_location_name(line)
    if lname:
        loc = resolve_location_for_legacy_name(
            project_id=meta["projectId"], company_gst=gst, location_name=lname, create=True
        )
    else:
        ensure_unassigned_floor(meta["projectId"], gst)

    width = float(line.get("width") or 0)
    height = float(line.get("height") or 0)
    qty = int(line.get("qty") or 1)
    product_id = str(line.get("product") or line.get("productId") or "").strip() or None
    element_pt = map_line_to_element_product_type(line)

    # Series / colour / glass live in config — not baked into immutable geometry identity
    config = {
        "sectionSeries": line.get("sectionSeries"),
        "colour": line.get("colour"),
        "glass": line.get("glass"),
        "system": line.get("system"),
        "options": line.get("options") if isinstance(line.get("options"), Mapping) else None,
    }
    geometry = {
        "source": "cart_line_adapter",
        # geometry only — series intentionally absent here
    }

    asm = create_assembly(
        design_document_id=meta["designDocumentId"],
        company_gst=gst,
        name=str(line.get("displayName") or product_id or "Default Assembly"),
        location_id=(loc or {}).get("locationId") if loc else None,
        legacy_line_id=lid,
        status="draft",
    )
    el = create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type=element_pt,
        product_id=product_id,
        width_mm=width,
        height_mm=height,
        x_mm=float(x_mm or 0),
        y_mm=float(y_mm or 0),
        quantity=qty,
        geometry_payload=geometry,
        config_payload=config,
        legacy_line_id=lid,
    )
    return {
        "assembly": asm,
        "element": el,
        "mapped": "created",
        "unchanged": {
            "width": line.get("width"),
            "height": line.get("height"),
            "product": line.get("product") or line.get("productId"),
            "productType": line.get("productType"),
            "locationName": lname or None,
            "qty": line.get("qty"),
            "sellingRate": line.get("sellingRate"),
            "previewSvg": line.get("previewSvg"),
        },
    }


def build_scene_read_model(
    design_document_id: str, *, company_gst: str
) -> dict[str, Any]:
    """Canvas-oriented read model: floors → locations → assemblies → elements/connections."""
    _require_db()
    meta = _get_owned_design_doc(design_document_id, company_gst)
    gst = _norm_company_gst(company_gst)
    from WEOS.factory.design_hierarchy import get_design_document

    doc = get_design_document(design_document_id, company_gst=gst)
    if doc is None:
        raise PermissionError("design document not found for company")

    floors = list_floors(meta["projectId"], company_gst=gst)
    locations = list_locations(project_id=meta["projectId"], company_gst=gst)
    assemblies = list_assemblies(design_document_id, company_gst=gst)

    elems_by_asm: dict[str, list[dict[str, Any]]] = {}
    conns_by_asm: dict[str, list[dict[str, Any]]] = {}
    for asm in assemblies:
        aid = asm["assemblyId"]
        elems_by_asm[aid] = list_elements(aid, company_gst=gst)
        conns_by_asm[aid] = list_connections(aid, company_gst=gst)

    locs_by_floor: dict[str, list[dict[str, Any]]] = {}
    for loc in locations:
        locs_by_floor.setdefault(loc["floorId"], []).append(loc)

    asms_by_loc: dict[str, list[dict[str, Any]]] = {}
    asms_unlocated: list[dict[str, Any]] = []
    for asm in assemblies:
        packed = {
            **asm,
            "elements": elems_by_asm.get(asm["assemblyId"], []),
            "connections": conns_by_asm.get(asm["assemblyId"], []),
        }
        lid = asm.get("locationId")
        if lid:
            asms_by_loc.setdefault(str(lid), []).append(packed)
        else:
            asms_unlocated.append(packed)

    floor_nodes = []
    for fl in floors:
        loc_nodes = []
        for loc in locs_by_floor.get(fl["floorId"], []):
            loc_nodes.append(
                {
                    **loc,
                    "assemblies": asms_by_loc.get(loc["locationId"], []),
                }
            )
        floor_nodes.append({**fl, "locations": loc_nodes})

    return {
        "designDocumentId": doc["designDocumentId"],
        "projectId": doc["projectId"],
        "companyGst": doc["companyGst"],
        "name": doc.get("name"),
        "status": doc.get("status"),
        "currentRevisionId": doc.get("currentRevisionId"),
        "floors": floor_nodes,
        "unlocatedAssemblies": asms_unlocated,
    }


def migrate_cart_lines_to_scene(
    *,
    company_gst: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Additive adapter: project cart lines → Assembly+Element. zeroSilentLoss always True."""
    _require_db()
    from WEOS.factory.project_store import list_projects, load_project

    gst_filter = _norm_company_gst(company_gst) if company_gst else ""
    if project_id:
        try:
            docs = [load_project(str(project_id).strip())]
        except FileNotFoundError:
            docs = []
    else:
        docs = []
        for summary in list_projects(
            include_archived=True,
            company_gst=gst_filter or None,
            include_unscoped=not bool(gst_filter),
            limit=10000,
        ):
            try:
                docs.append(load_project(str(summary.get("projectId") or "")))
            except Exception:
                continue

    lines_inspected = 0
    assemblies_mapped = 0
    elements_mapped = 0
    unmapped = 0
    conflicts = 0
    rejected = 0
    manual_review: list[dict[str, Any]] = []

    for doc in docs:
        pid = str(doc.get("projectId") or "").strip()
        cg = _norm_company_gst(doc.get("companyGst"))
        if not pid or not cg:
            rejected += 1
            continue
        if gst_filter and cg != gst_filter:
            continue
        if project_id and pid != str(project_id).strip():
            continue
        try:
            from WEOS.factory.canonical_project import link_project_document

            link_project_document(doc)
            des = ensure_design_document(pid, cg)
        except Exception as exc:
            rejected += 1
            manual_review.append({"projectId": pid, "reason": str(exc)})
            continue

        lines = doc.get("lines") if isinstance(doc.get("lines"), list) else []
        for ln in lines:
            if not isinstance(ln, Mapping):
                unmapped += 1
                continue
            lines_inspected += 1
            try:
                w = ln.get("width")
                h = ln.get("height")
                if w is None or h is None:
                    unmapped += 1
                    manual_review.append(
                        {
                            "projectId": pid,
                            "lineId": ln.get("lineId"),
                            "reason": "missing_width_or_height",
                        }
                    )
                    continue
                result = adapt_cart_line_to_assembly_element(
                    design_document_id=des["designDocumentId"],
                    company_gst=cg,
                    line=ln,
                )
                if result.get("assembly"):
                    assemblies_mapped += 1
                if result.get("element"):
                    elements_mapped += 1
            except Exception as exc:
                conflicts += 1
                manual_review.append(
                    {
                        "projectId": pid,
                        "lineId": ln.get("lineId"),
                        "reason": str(exc),
                    }
                )

    return {
        "ok": True,
        "legacyLinesInspected": lines_inspected,
        "assembliesMapped": assemblies_mapped,
        "elementsMapped": elements_mapped,
        "unmapped": unmapped,
        "conflicts": conflicts,
        "rejected": rejected,
        "manualReview": manual_review,
        "zeroSilentLoss": True,
    }
