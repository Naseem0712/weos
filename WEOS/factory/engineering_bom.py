"""Engineering BOM domain — derived from saved design + masters (not quote selling rates).

Pipeline: Design Geometry → Product Configuration → Series/Profiles/HW/Glass
         → Engineering BOM → quantities/lengths/weights/areas → (future Costing)
"""

from __future__ import annotations

import hashlib
import logging
import math
import uuid
from copy import deepcopy
from typing import Any, Callable, Mapping, Protocol

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.db.models import DesignElement, DesignDocument, EngineeringBomDocument, EngineeringBomLine
from WEOS.factory import engineering_masters as em
from WEOS.factory.canonical_customer import _norm_company_gst

_log = logging.getLogger("weos.engineering_bom")

GENERATOR_VERSION = "eng-bom-1.0.0"
BATCH_ID = "ENG-BOM"

WINDOW_PRODUCT_TYPES = frozenset(
    {
        "SLIDING_WINDOW",
        "CASEMENT_WINDOW",
        "FIXED_WINDOW",
        "VENTILATOR",
        "DOOR",
        "FOLD_WINDOW",
        "WINDOW_VENT_COMBO",
        "SLIDING",
        "CASEMENT",
        "FIXED",
        "VENT",
    }
)


def new_bom_id() -> str:
    return "EBOM-" + uuid.uuid4().hex[:16].upper()


def new_bom_line_id() -> str:
    return "EBL-" + uuid.uuid4().hex[:16].upper()


def _require_db() -> None:
    if not db_available():
        raise RuntimeError("Database unavailable for engineering BOM")
    init_db()
    em.ensure_engineering_schema()


# ── Line contract helpers ────────────────────────────────────────────────────


def make_bom_line(
    *,
    category: str,
    description: str,
    unit: str = "PC",
    quantity: float = 1.0,
    master_id: str | None = None,
    master_kind: str | None = None,
    code: str | None = None,
    profile_role: str | None = None,
    length_mm: float | None = None,
    required_length_mm: float | None = None,
    stock_consumption_mm: float | None = None,
    width_mm: float | None = None,
    height_mm: float | None = None,
    area_sqm: float | None = None,
    weight_kg: float | None = None,
    weight_per_rmt: float | None = None,
    cell_id: str | None = None,
    member_id: str | None = None,
    element_id: str | None = None,
    assembly_id: str | None = None,
    scope_level: str = "PIECE",
    deduction_mode: str | None = None,
    cost_basis_type: str | None = None,
    cost_basis_value: float | None = None,
    rollup_key: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """EngineeringBOMLine contract — never uses quote selling rate."""
    req = required_length_mm if required_length_mm is not None else length_mm
    length_m = (float(req) / 1000.0) if req is not None else None
    wpr = float(weight_per_rmt) if weight_per_rmt is not None else None
    wt = weight_kg
    if wt is None and length_m is not None and wpr is not None:
        wt = round(length_m * wpr * float(quantity or 1), 6)
    area = area_sqm
    if area is None and width_mm is not None and height_mm is not None:
        area = round((float(width_mm) * float(height_mm) * float(quantity or 1)) / 1_000_000.0, 6)
    return {
        "lineId": new_bom_line_id(),
        "category": str(category).upper(),
        "masterId": master_id,
        "masterKind": master_kind,
        "code": code,
        "description": description,
        "profileRole": profile_role,
        "unit": str(unit).upper(),
        "quantity": float(quantity),
        "lengthMm": length_mm,
        "lengthM": length_m,
        "requiredLengthMm": req,
        "stockConsumptionMm": stock_consumption_mm,
        "widthMm": width_mm,
        "heightMm": height_mm,
        "areaSqm": area,
        "weightKg": wt,
        "weightPerRmt": wpr,
        "cellId": cell_id,
        "memberId": member_id,
        "elementId": element_id,
        "assemblyId": assembly_id,
        "scopeLevel": scope_level,
        "deductionMode": deduction_mode,
        "costBasisType": cost_basis_type,
        "costBasisValue": cost_basis_value,
        "rollupKey": rollup_key
        or f"{str(category).upper()}|{code or description}|{profile_role or ''}",
        "meta": meta or {},
        "usesQuoteSellingRate": False,
    }


def stock_consume(required_mm: float, stock_length_mm: float | None) -> float:
    """Stock bars needed × stock length (mm). Distinguishes Required Length vs Stock Consumption."""
    req = max(0.0, float(required_mm))
    if not stock_length_mm or stock_length_mm <= 0:
        return req
    bars = int(math.ceil(req / float(stock_length_mm) - 1e-9))
    return bars * float(stock_length_mm)


# ── ProductBOMAdapter protocol ───────────────────────────────────────────────


class ProductBOMAdapter(Protocol):
    product_family: str

    def supports(self, product_type: str | None) -> bool: ...

    def generate(
        self,
        *,
        element: Mapping[str, Any],
        topology: Mapping[str, Any] | None,
        assignments: list[Mapping[str, Any]],
        series: Mapping[str, Any] | None,
        company_gst: str,
    ) -> dict[str, Any]:
        """Return {lines, issues, status}."""
        ...


_ADAPTERS: list[ProductBOMAdapter] = []


def register_bom_adapter(adapter: ProductBOMAdapter) -> None:
    _ADAPTERS.append(adapter)


def get_bom_adapter(product_type: str | None) -> ProductBOMAdapter | None:
    for a in _ADAPTERS:
        if a.supports(product_type):
            return a
    return None


def _eval_simple(expr: str, ctx: Mapping[str, float]) -> float:
    """Safe-ish arithmetic for hardware qty formulas (identifiers from ctx only)."""
    from WEOS.factory.formula import eval_formula

    try:
        return float(eval_formula(expr, ctx))
    except Exception:
        # Fallback: very small subset
        safe = {k: float(v) for k, v in ctx.items()}
        return float(eval(expr, {"__builtins__": {}}, safe))  # noqa: S307 — constrained ctx


# ── Window BOM adapter ───────────────────────────────────────────────────────


class WindowBOMAdapter:
    """Sliding / Fixed / Casement / Ventilator including composite cell products."""

    product_family = "WINDOW"

    def supports(self, product_type: str | None) -> bool:
        pt = str(product_type or "").strip().upper()
        if not pt:
            return False
        if pt in WINDOW_PRODUCT_TYPES:
            return True
        return "WINDOW" in pt or pt in ("DOOR", "VENTILATOR", "FOLD")

    def generate(
        self,
        *,
        element: Mapping[str, Any],
        topology: Mapping[str, Any] | None,
        assignments: list[Mapping[str, Any]],
        series: Mapping[str, Any] | None,
        company_gst: str,
    ) -> dict[str, Any]:
        lines: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        eid = element.get("elementId")
        aid = element.get("assemblyId")
        w = float(element.get("widthMm") or 0)
        h = float(element.get("heightMm") or 0)
        series_id = (series or {}).get("seriesId") if series else None

        # 1) Outer frame piece-level (ONCE at element — no double-count with members)
        for role, length, label in (
            ("OUTER_FRAME_VERTICAL", h, "Outer frame vertical"),
            ("OUTER_FRAME_HORIZONTAL", w, "Outer frame horizontal"),
        ):
            resolved = em.resolve_profile_for_role(series_id, role)
            if not resolved.get("ok"):
                issues.append(
                    {
                        "code": "MISSING_PROFILE_MAPPING",
                        "severity": "error",
                        "message": resolved.get("issue") or f"missing {role}",
                        "role": role,
                    }
                )
                continue
            prof = resolved["profile"]
            for _ in range(2):
                req = float(length)
                stock = stock_consume(req, prof.get("stockLengthMm"))
                lines.append(
                    make_bom_line(
                        category="PROFILE",
                        description=f"{label} — {prof.get('name')}",
                        master_id=prof.get("profileId"),
                        master_kind="PROFILE",
                        code=prof.get("code"),
                        profile_role=role,
                        unit="PC",
                        quantity=1,
                        length_mm=req,
                        required_length_mm=req,
                        stock_consumption_mm=stock,
                        weight_per_rmt=prof.get("weightPerRmt"),
                        element_id=eid,
                        assembly_id=aid,
                        scope_level="PIECE",
                        cost_basis_type=prof.get("costBasisType"),
                        cost_basis_value=prof.get("costBasisValue"),
                        meta={"outerFrame": True, "noDoubleCount": True},
                    )
                )

        topo = topology or {}
        members = list(topo.get("members") or [])
        cells = list(topo.get("cells") or [])

        # 2) FrameMember → profile BOM (mullions/transoms only — skip outer-frame roles)
        for m in members:
            if str(m.get("status") or "active") != "active":
                continue
            role = em._norm_role(m.get("profileRole") or _default_member_role(m))
            if role in ("OUTER_FRAME", "OUTER_FRAME_VERTICAL", "OUTER_FRAME_HORIZONTAL"):
                # Outer frame already emitted from element dims
                continue
            length = _member_length_mm(m)
            resolved = em.resolve_profile_for_role(
                series_id, role, profile_reference=m.get("profileReference")
            )
            if not resolved.get("ok"):
                issues.append(
                    {
                        "code": "MISSING_MEMBER_PROFILE",
                        "severity": "error",
                        "message": resolved.get("issue"),
                        "memberId": m.get("memberId"),
                        "role": role,
                    }
                )
                continue
            prof = resolved["profile"]
            req = float(length)
            lines.append(
                make_bom_line(
                    category="PROFILE",
                    description=f"{role} — {prof.get('name')}",
                    master_id=prof.get("profileId"),
                    master_kind="PROFILE",
                    code=prof.get("code"),
                    profile_role=role,
                    unit="PC",
                    quantity=1,
                    length_mm=req,
                    required_length_mm=req,
                    stock_consumption_mm=stock_consume(req, prof.get("stockLengthMm")),
                    weight_per_rmt=prof.get("weightPerRmt"),
                    member_id=m.get("memberId"),
                    element_id=eid,
                    assembly_id=aid,
                    scope_level="PIECE",
                    cost_basis_type=prof.get("costBasisType"),
                    cost_basis_value=prof.get("costBasisValue"),
                )
            )

        # 3) Cell product BOM (no outer frame again)
        leaf_cells = [c for c in cells if c.get("isLeaf")]
        if not leaf_cells and not assignments:
            # Single-product element without grid — treat whole opening as one cell
            leaf_cells = [
                {
                    "cellId": None,
                    "widthMm": w,
                    "heightMm": h,
                    "isLeaf": True,
                }
            ]
            if not assignments:
                assignments = [
                    {
                        "productType": _assignment_type_from_element(element.get("productType")),
                        "seriesId": series_id,
                        "configuration": (element.get("configPayload") or {}),
                        "status": "active",
                    }
                ]

        assign_by_cell = {
            a.get("cellId"): a
            for a in assignments
            if str(a.get("status") or "active") == "active"
        }

        for cell in leaf_cells:
            cid = cell.get("cellId")
            asg = assign_by_cell.get(cid) if cid else (assignments[0] if assignments else None)
            if not asg and len(assignments) == 1 and not cid:
                asg = assignments[0]
            if not asg:
                continue
            cell_lines, cell_issues = _cell_product_bom(
                cell=cell,
                assignment=asg,
                series_id=asg.get("seriesId") or series_id,
                element_id=eid,
                assembly_id=aid,
                company_gst=company_gst,
            )
            lines.extend(cell_lines)
            issues.extend(cell_issues)

        status = _status_from_issues(lines, issues)
        return {"lines": lines, "issues": issues, "status": status}


def _default_member_role(member: Mapping[str, Any]) -> str:
    mt = str(member.get("memberType") or "").upper()
    ori = str(member.get("orientation") or "").upper()
    if mt == "TRANSOM" or (mt in ("", "MULLION") and ori == "H"):
        return "TRANSOM"
    return "MULLION"


def _member_length_mm(member: Mapping[str, Any]) -> float:
    try:
        x1, y1 = float(member.get("x1Mm") or 0), float(member.get("y1Mm") or 0)
        x2, y2 = float(member.get("x2Mm") or 0), float(member.get("y2Mm") or 0)
        return math.hypot(x2 - x1, y2 - y1)
    except (TypeError, ValueError):
        return 0.0


def _assignment_type_from_element(product_type: str | None) -> str:
    pt = str(product_type or "").upper()
    if "CASEMENT" in pt:
        return "CASEMENT"
    if "FIXED" in pt:
        return "FIXED"
    if "VENT" in pt:
        return "VENTILATOR"
    if "DOOR" in pt:
        return "DOOR"
    return "SLIDING"


def _cell_product_bom(
    *,
    cell: Mapping[str, Any],
    assignment: Mapping[str, Any],
    series_id: str | None,
    element_id: str | None,
    assembly_id: str | None,
    company_gst: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    pt = str(assignment.get("productType") or "").upper()
    if pt in ("OPEN",):
        return lines, issues
    cfg = assignment.get("configuration") if isinstance(assignment.get("configuration"), dict) else {}
    cw = float(cell.get("widthMm") or 0)
    ch = float(cell.get("heightMm") or 0)
    cid = cell.get("cellId")
    shutter_count = int(cfg.get("shutterCount") or cfg.get("sashCount") or (2 if pt == "SLIDING" else 1))
    mesh_on = bool(cfg.get("mesh"))

    # Glass — NOMINAL deductions when exact bead offsets unknown
    glass_cfg = cfg.get("glass") if isinstance(cfg.get("glass"), dict) else {}
    glass_ref = (
        glass_cfg.get("glassId")
        or glass_cfg.get("code")
        or glass_cfg.get("makeup")
        or assignment.get("glass")
        or "5MM-CLEAR"
    )
    glass = em.resolve_glass_ref(str(glass_ref)) or em.resolve_glass_ref("5MM-CLEAR")
    # Nominal inset for frame/sash rebate
    inset = 40.0 if pt == "SLIDING" else 30.0
    if pt == "FIXED":
        inset = 25.0
    gw = max(0.0, cw - 2 * inset)
    gh = max(0.0, ch - 2 * inset)
    glass_qty = max(1, shutter_count) if pt in ("SLIDING", "CASEMENT") else 1
    if pt == "SLIDING":
        gw = max(0.0, (cw / max(shutter_count, 1)) - inset)
    if glass:
        dens = float(glass.get("densityKgPerSqm") or 0)
        area = (gw * gh * glass_qty) / 1_000_000.0
        lines.append(
            make_bom_line(
                category="GLASS",
                description=f"Glass {glass.get('name')} {gw:.0f}×{gh:.0f}",
                master_id=glass.get("glassId"),
                master_kind="GLASS",
                code=glass.get("code"),
                unit="PC",
                quantity=glass_qty,
                width_mm=gw,
                height_mm=gh,
                area_sqm=round(area, 6),
                weight_kg=round(area * dens, 6) if dens else None,
                cell_id=cid,
                element_id=element_id,
                assembly_id=assembly_id,
                scope_level="CELL",
                deduction_mode="NOMINAL",
                cost_basis_type=glass.get("costBasisType"),
                cost_basis_value=glass.get("costBasisValue"),
                meta={"cellId": cid, "type": glass.get("makeup"), "nominalInsetMm": inset},
            )
        )
    else:
        issues.append(
            {
                "code": "MISSING_GLASS_MASTER",
                "severity": "error",
                "message": f"glass '{glass_ref}' not in masters",
                "cellId": cid,
            }
        )

    # Cell shutter profiles (not outer frame)
    if pt in ("SLIDING", "CASEMENT") and series_id:
        stile_len = max(0.0, ch - 20.0)
        rail_len = max(0.0, (cw / max(shutter_count, 1)) - 20.0)
        for role, length, qty in (
            ("SHUTTER_STILE", stile_len, shutter_count * 2),
            ("SHUTTER_RAIL", rail_len, shutter_count * 2),
        ):
            if pt == "CASEMENT" and role == "SHUTTER_STILE":
                role = "SASH"
            resolved = em.resolve_profile_for_role(series_id, role)
            if not resolved.get("ok"):
                # try INTERLOCK as stile fallback
                if role in ("SHUTTER_STILE", "SASH"):
                    resolved = em.resolve_profile_for_role(series_id, "INTERLOCK")
            if not resolved.get("ok"):
                issues.append(
                    {
                        "code": "MISSING_CELL_PROFILE",
                        "severity": "warning",
                        "message": resolved.get("issue"),
                        "role": role,
                        "cellId": cid,
                    }
                )
                continue
            prof = resolved["profile"]
            for _i in range(int(qty)):
                lines.append(
                    make_bom_line(
                        category="PROFILE",
                        description=f"{role} — {prof.get('name')}",
                        master_id=prof.get("profileId"),
                        master_kind="PROFILE",
                        code=prof.get("code"),
                        profile_role=role,
                        unit="PC",
                        quantity=1,
                        length_mm=length,
                        required_length_mm=length,
                        stock_consumption_mm=stock_consume(length, prof.get("stockLengthMm")),
                        weight_per_rmt=prof.get("weightPerRmt"),
                        cell_id=cid,
                        element_id=element_id,
                        assembly_id=assembly_id,
                        scope_level="CELL",
                        cost_basis_type=prof.get("costBasisType"),
                        cost_basis_value=prof.get("costBasisValue"),
                    )
                )
        if pt == "SLIDING":
            resolved = em.resolve_profile_for_role(series_id, "INTERLOCK")
            if resolved.get("ok"):
                prof = resolved["profile"]
                length = stile_len
                lines.append(
                    make_bom_line(
                        category="PROFILE",
                        description=f"INTERLOCK — {prof.get('name')}",
                        master_id=prof.get("profileId"),
                        master_kind="PROFILE",
                        code=prof.get("code"),
                        profile_role="INTERLOCK",
                        unit="PC",
                        quantity=max(0, shutter_count - 1),
                        length_mm=length,
                        required_length_mm=length,
                        stock_consumption_mm=stock_consume(length, prof.get("stockLengthMm")),
                        weight_per_rmt=prof.get("weightPerRmt"),
                        cell_id=cid,
                        element_id=element_id,
                        assembly_id=assembly_id,
                        scope_level="CELL",
                        cost_basis_type=prof.get("costBasisType"),
                        cost_basis_value=prof.get("costBasisValue"),
                    )
                )

    # Hardware rules
    ctx = {
        "shutterCount": float(shutter_count),
        "sashCount": float(shutter_count),
        "width": cw,
        "height": ch,
        "mesh": 1.0 if mesh_on else 0.0,
    }
    rules = em.list_hardware_rules(series_id=series_id, product_type=pt)
    hw_by_id = {h["hardwareId"]: h for h in em.list_hardware(company_gst=company_gst)}
    for rule in rules:
        if rule.get("seriesId") and series_id and rule["seriesId"] != series_id:
            continue
        if rule.get("productType") and rule["productType"] != pt:
            continue
        cond = rule.get("conditionFormula")
        if cond:
            try:
                if float(_eval_simple(cond, ctx)) <= 0:
                    continue
            except Exception:
                issues.append(
                    {
                        "code": "HARDWARE_RULE_CONDITION_ERROR",
                        "severity": "warning",
                        "message": f"condition failed: {cond}",
                        "ruleId": rule.get("ruleId"),
                    }
                )
                continue
        try:
            qty = float(_eval_simple(rule.get("quantityFormula") or "1", ctx))
        except Exception as exc:
            issues.append(
                {
                    "code": "HARDWARE_RULE_QTY_ERROR",
                    "severity": "error",
                    "message": str(exc),
                    "ruleId": rule.get("ruleId"),
                }
            )
            continue
        if qty <= 0:
            continue
        hw = hw_by_id.get(rule["hardwareId"])
        if not hw:
            issues.append(
                {
                    "code": "MISSING_HARDWARE_MASTER",
                    "severity": "error",
                    "message": f"hardware {rule['hardwareId']} missing",
                }
            )
            continue
        lines.append(
            make_bom_line(
                category="HARDWARE",
                description=hw.get("name") or rule.get("name"),
                master_id=hw.get("hardwareId"),
                master_kind="HARDWARE",
                code=hw.get("code"),
                unit=rule.get("unit") or hw.get("unit") or "PC",
                quantity=qty,
                cell_id=cid,
                element_id=element_id,
                assembly_id=assembly_id,
                scope_level="CELL",
                cost_basis_type=hw.get("costBasisType"),
                cost_basis_value=hw.get("costBasisValue"),
                meta={"ruleId": rule.get("ruleId")},
            )
        )

    # Mesh / gasket accessories foundation
    if mesh_on:
        mesh_list = em.list_accessories(company_gst=company_gst, kind="MESH")
        if mesh_list:
            mesh = mesh_list[0]
            area_sft = (cw * ch) / 92903.04  # mm² → sft
            lines.append(
                make_bom_line(
                    category="MESH",
                    description=mesh.get("name"),
                    master_id=mesh.get("accessoryId"),
                    master_kind="MESH",
                    code=mesh.get("code"),
                    unit=mesh.get("unit") or "SFT",
                    quantity=round(area_sft, 4),
                    width_mm=cw,
                    height_mm=ch,
                    cell_id=cid,
                    element_id=element_id,
                    assembly_id=assembly_id,
                    scope_level="CELL",
                    deduction_mode="NOMINAL",
                    cost_basis_type=mesh.get("costBasisType"),
                    cost_basis_value=mesh.get("costBasisValue"),
                )
            )
        else:
            issues.append(
                {
                    "code": "MISSING_MESH_MASTER",
                    "severity": "warning",
                    "message": "mesh requested but no MESH accessory master",
                    "cellId": cid,
                }
            )

    gasket_list = em.list_accessories(company_gst=company_gst, kind="GASKET")
    if gasket_list and pt != "OPEN":
        gsk = gasket_list[0]
        peri_m = 2 * (cw + ch) / 1000.0
        lines.append(
            make_bom_line(
                category="GASKET",
                description=gsk.get("name"),
                master_id=gsk.get("accessoryId"),
                master_kind="GASKET",
                code=gsk.get("code"),
                unit=gsk.get("unit") or "RMT",
                quantity=round(peri_m, 4),
                length_mm=peri_m * 1000,
                required_length_mm=peri_m * 1000,
                cell_id=cid,
                element_id=element_id,
                assembly_id=assembly_id,
                scope_level="CELL",
                cost_basis_type=gsk.get("costBasisType"),
                cost_basis_value=gsk.get("costBasisValue"),
            )
        )

    return lines, issues


def _status_from_issues(lines: list[dict[str, Any]], issues: list[dict[str, Any]]) -> str:
    if not lines and any(i.get("severity") == "error" for i in issues):
        return "ERROR"
    if not lines:
        return "EMPTY"
    errs = [i for i in issues if i.get("severity") == "error"]
    if errs:
        return "PARTIAL"
    warns = [i for i in issues if i.get("severity") == "warning"]
    if warns:
        return "PARTIAL"
    return "READY"


# Register default adapter
register_bom_adapter(WindowBOMAdapter())


class RailingBomFoundationAdapter:
    """Schema capability only — no full railing BOM yet."""

    product_family = "RAILING"

    def supports(self, product_type: str | None) -> bool:
        return "RAILING" in str(product_type or "").upper()

    def generate(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "lines": [],
            "issues": [
                {
                    "code": "ADAPTER_DEFERRED",
                    "severity": "warning",
                    "message": "Railing BOM adapter foundation only — full BOM deferred",
                }
            ],
            "status": "PARTIAL",
        }


class PergolaBomFoundationAdapter:
    product_family = "PERGOLA"

    def supports(self, product_type: str | None) -> bool:
        return "PERGOLA" in str(product_type or "").upper()

    def generate(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "lines": [],
            "issues": [
                {
                    "code": "ADAPTER_DEFERRED",
                    "severity": "warning",
                    "message": "Pergola BOM adapter foundation only — full BOM deferred",
                }
            ],
            "status": "PARTIAL",
        }


register_bom_adapter(RailingBomFoundationAdapter())
register_bom_adapter(PergolaBomFoundationAdapter())


# ── Generation / persistence / stale ─────────────────────────────────────────


def _fingerprint(parts: Mapping[str, Any]) -> str:
    blob = repr(sorted(parts.items())).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:24]


def _summarize(lines: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat: dict[str, int] = {}
    total_wt = 0.0
    total_area = 0.0
    for ln in lines:
        cat = ln.get("category") or "OTHER"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        if ln.get("weightKg"):
            total_wt += float(ln["weightKg"])
        if ln.get("areaSqm"):
            total_area += float(ln["areaSqm"])
    return {
        "lineCount": len(lines),
        "byCategory": by_cat,
        "totalWeightKg": round(total_wt, 4),
        "totalGlassAreaSqm": round(total_area, 4),
    }


def generate_element_bom(
    element_id: str,
    *,
    company_gst: str,
    persist: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Generate deterministic engineering BOM for one DesignElement (window/composite)."""
    _require_db()
    from WEOS.factory import cell_assignment as ca
    from WEOS.factory import member_grid as mg

    gst = _norm_company_gst(company_gst)
    with session_scope() as s:
        el = s.get(DesignElement, element_id)
        if not el or el.company_gst != gst:
            raise PermissionError("element not found")
        element = el.to_dict()
        des = s.get(DesignDocument, el.design_document_id)
        design_rev = des.current_revision_id if des else None
        project_id = el.project_id
        assembly_id = el.assembly_id
        design_document_id = el.design_document_id

    topo = None
    try:
        if mg.supports_frame_grid(element.get("productType")):
            topo = mg.get_element_topology(element_id, company_gst=gst)
    except Exception as exc:
        _log.info("topology optional: %s", exc)

    try:
        assignments = ca.list_assignments_for_element(element_id, company_gst=gst)
    except Exception:
        assignments = []

    series = _resolve_element_series(element, assignments, company_gst=gst)
    master_token = em.master_revision_token(gst)
    fp = _fingerprint(
        {
            "elementId": element_id,
            "w": element.get("widthMm"),
            "h": element.get("heightMm"),
            "rev": design_rev,
            "master": master_token,
            "gen": GENERATOR_VERSION,
            "topo": (topo or {}).get("memberCount"),
            "asg": len(assignments),
            "series": (series or {}).get("seriesId"),
        }
    )

    if not force and persist:
        existing = get_current_bom(element_id=element_id, company_gst=gst)
        if existing and existing.get("sourceFingerprint") == fp and existing.get("status") != "STALE":
            return existing

    adapter = get_bom_adapter(element.get("productType"))
    if not adapter:
        result = {
            "lines": [],
            "issues": [
                {
                    "code": "NO_ADAPTER",
                    "severity": "error",
                    "message": f"No ProductBOMAdapter for {element.get('productType')}",
                }
            ],
            "status": "ERROR",
        }
    else:
        result = adapter.generate(
            element=element,
            topology=topo,
            assignments=assignments,
            series=series,
            company_gst=gst,
        )

    lines = result.get("lines") or []
    issues = result.get("issues") or []
    status = result.get("status") or _status_from_issues(lines, issues)
    rolled = rollup_lines(lines, scope_level="ELEMENT")
    payload = {
        "companyGst": gst,
        "projectId": project_id,
        "designDocumentId": design_document_id,
        "assemblyId": assembly_id,
        "elementId": element_id,
        "scopeLevel": "ELEMENT",
        "status": status,
        "generatorVersion": GENERATOR_VERSION,
        "designRevisionId": design_rev,
        "masterRevisionToken": master_token,
        "sourceFingerprint": fp,
        "issues": issues,
        "summary": _summarize(lines),
        "lines": lines,
        "rollup": rolled,
        "series": series,
        "editableSource": False,
        "usesQuoteSellingRate": False,
    }
    if persist:
        return _persist_bom(payload, supersede_element_id=element_id)
    payload["bomId"] = new_bom_id()
    payload["isCurrent"] = True
    return payload


def _resolve_element_series(
    element: Mapping[str, Any],
    assignments: list[Mapping[str, Any]],
    *,
    company_gst: str,
) -> dict[str, Any] | None:
    cfg = element.get("configPayload") if isinstance(element.get("configPayload"), dict) else {}
    candidates = [
        cfg.get("seriesId"),
        cfg.get("seriesCode"),
        cfg.get("series"),
        element.get("productId"),
    ]
    for a in assignments:
        candidates.extend([a.get("seriesId"), a.get("seriesCode")])
        acfg = a.get("configuration") if isinstance(a.get("configuration"), dict) else {}
        candidates.extend([acfg.get("seriesId"), acfg.get("seriesCode")])
    for c in candidates:
        hit = em.resolve_series_ref(c, company_gst=company_gst) if c else None
        if hit:
            return hit
    # Default window series
    return em.resolve_series_ref("29mm_sliding", company_gst=company_gst)


def _persist_bom(payload: dict[str, Any], *, supersede_element_id: str | None = None) -> dict[str, Any]:
    _require_db()
    bom_id = new_bom_id()
    with session_scope() as s:
        if supersede_element_id:
            olds = (
                s.query(EngineeringBomDocument)
                .filter(
                    EngineeringBomDocument.element_id == supersede_element_id,
                    EngineeringBomDocument.is_current.is_(True),
                )
                .all()
            )
            for old in olds:
                old.is_current = False
                old.superseded_by = bom_id
                if old.status != "STALE":
                    # keep historical status but mark superseded
                    pass
        doc = EngineeringBomDocument(
            bom_id=bom_id,
            company_gst=payload["companyGst"],
            project_id=payload["projectId"],
            design_document_id=payload.get("designDocumentId"),
            assembly_id=payload.get("assemblyId"),
            element_id=payload.get("elementId"),
            scope_level=payload.get("scopeLevel") or "ELEMENT",
            status=payload.get("status") or "EMPTY",
            generator_version=payload.get("generatorVersion") or GENERATOR_VERSION,
            design_revision_id=payload.get("designRevisionId"),
            design_content_hash=payload.get("designContentHash"),
            master_revision_token=payload.get("masterRevisionToken"),
            source_fingerprint=payload.get("sourceFingerprint"),
            issues=payload.get("issues") or [],
            summary=payload.get("summary") or {},
            lines_payload=payload.get("lines") or [],
            is_current=True,
            meta={
                "rollup": payload.get("rollup"),
                "series": payload.get("series"),
                "batch": BATCH_ID,
            },
        )
        s.add(doc)
        for i, ln in enumerate(payload.get("lines") or []):
            s.add(
                EngineeringBomLine(
                    line_id=ln.get("lineId") or new_bom_line_id(),
                    bom_id=bom_id,
                    company_gst=payload["companyGst"],
                    category=ln.get("category") or "OTHER",
                    master_id=ln.get("masterId"),
                    master_kind=ln.get("masterKind"),
                    code=ln.get("code"),
                    description=ln.get("description") or "",
                    profile_role=ln.get("profileRole"),
                    unit=ln.get("unit") or "PC",
                    quantity=float(ln.get("quantity") or 0),
                    length_mm=ln.get("lengthMm"),
                    length_m=ln.get("lengthM"),
                    required_length_mm=ln.get("requiredLengthMm"),
                    stock_consumption_mm=ln.get("stockConsumptionMm"),
                    width_mm=ln.get("widthMm"),
                    height_mm=ln.get("heightMm"),
                    area_sqm=ln.get("areaSqm"),
                    weight_kg=ln.get("weightKg"),
                    weight_per_rmt=ln.get("weightPerRmt"),
                    cell_id=ln.get("cellId"),
                    member_id=ln.get("memberId"),
                    element_id=ln.get("elementId") or payload.get("elementId"),
                    assembly_id=ln.get("assemblyId") or payload.get("assemblyId"),
                    scope_level=ln.get("scopeLevel") or "PIECE",
                    rollup_key=ln.get("rollupKey"),
                    deduction_mode=ln.get("deductionMode"),
                    cost_basis_type=ln.get("costBasisType"),
                    cost_basis_value=ln.get("costBasisValue"),
                    sort_order=i,
                    meta=ln.get("meta"),
                )
            )
        s.flush()
        out = doc.to_dict()
        out["rollup"] = payload.get("rollup")
        out["series"] = payload.get("series")
        return out


def get_current_bom(
    *,
    element_id: str | None = None,
    bom_id: str | None = None,
    company_gst: str | None = None,
) -> dict[str, Any] | None:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        if bom_id:
            doc = s.get(EngineeringBomDocument, bom_id)
            if not doc:
                return None
            if gst and doc.company_gst != gst:
                return None
            return _bom_with_freshness(doc)
        if not element_id:
            return None
        q = s.query(EngineeringBomDocument).filter(
            EngineeringBomDocument.element_id == element_id,
            EngineeringBomDocument.is_current.is_(True),
        )
        if gst:
            q = q.filter(EngineeringBomDocument.company_gst == gst)
        doc = q.order_by(EngineeringBomDocument.updated_at.desc()).first()
        if not doc:
            return None
        return _bom_with_freshness(doc)


def _bom_with_freshness(doc: EngineeringBomDocument) -> dict[str, Any]:
    out = doc.to_dict()
    out["rollup"] = (doc.meta or {}).get("rollup") if isinstance(doc.meta, dict) else None
    out["series"] = (doc.meta or {}).get("series") if isinstance(doc.meta, dict) else None
    # Stale if master revision moved
    try:
        current_master = em.master_revision_token(doc.company_gst)
        if doc.master_revision_token and doc.master_revision_token != current_master:
            out["status"] = "STALE"
            out["freshness"] = "STALE"
            out["staleReason"] = "master_revision_changed"
            return out
    except Exception:
        pass
    out["freshness"] = "CURRENT" if doc.is_current and out.get("status") != "STALE" else out.get("status")
    return out


def mark_stale_for_element(element_id: str, *, company_gst: str, reason: str = "design_changed") -> int:
    _require_db()
    gst = _norm_company_gst(company_gst)
    n = 0
    with session_scope() as s:
        rows = (
            s.query(EngineeringBomDocument)
            .filter(
                EngineeringBomDocument.element_id == element_id,
                EngineeringBomDocument.company_gst == gst,
                EngineeringBomDocument.is_current.is_(True),
            )
            .all()
        )
        for r in rows:
            r.status = "STALE"
            meta = dict(r.meta or {})
            meta["staleReason"] = reason
            r.meta = meta
            n += 1
    # BOM STALE → Cost STALE (costing domain listens; does not redesign BOM)
    try:
        from WEOS.factory import engineering_costing as ec

        ec.mark_stale_for_element(element_id, company_gst=gst, reason=f"bom_{reason}")
    except Exception as exc:
        _log.info("costing stale hook skipped: %s", exc)
    return n


def regenerate_bom(element_id: str, *, company_gst: str) -> dict[str, Any]:
    """Safe regenerate — supersedes previous current BOM, does not mutate historical rows."""
    return generate_element_bom(element_id, company_gst=company_gst, persist=True, force=True)


# ── Rollup ───────────────────────────────────────────────────────────────────


def rollup_lines(lines: list[dict[str, Any]], *, scope_level: str = "ELEMENT") -> list[dict[str, Any]]:
    """Piece-level → rolled-up by rollupKey (qty/length/weight/area summed)."""
    buckets: dict[str, dict[str, Any]] = {}
    for ln in lines:
        key = ln.get("rollupKey") or f"{ln.get('category')}|{ln.get('code')}|{ln.get('description')}"
        if key not in buckets:
            buckets[key] = deepcopy(ln)
            buckets[key]["scopeLevel"] = scope_level
            buckets[key]["lineId"] = new_bom_line_id()
            buckets[key]["meta"] = dict(ln.get("meta") or {})
            buckets[key]["meta"]["pieceCount"] = 1
            continue
        b = buckets[key]
        b["quantity"] = float(b.get("quantity") or 0) + float(ln.get("quantity") or 0)
        for fld in ("requiredLengthMm", "stockConsumptionMm", "lengthMm", "weightKg", "areaSqm", "lengthM"):
            if ln.get(fld) is not None:
                b[fld] = float(b.get(fld) or 0) + float(ln[fld])
        b["meta"]["pieceCount"] = int(b["meta"].get("pieceCount") or 0) + 1
    return list(buckets.values())


def rollup_hierarchy(
    *,
    project_id: str,
    company_gst: str,
    element_boms: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Cell → Assembly → Design → Location → Floor → Project rollup structure."""
    _require_db()
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds

    gst = _norm_company_gst(company_gst)
    if element_boms is None:
        # Collect current BOMs for project elements
        with session_scope() as s:
            docs = (
                s.query(EngineeringBomDocument)
                .filter(
                    EngineeringBomDocument.project_id == project_id,
                    EngineeringBomDocument.company_gst == gst,
                    EngineeringBomDocument.is_current.is_(True),
                    EngineeringBomDocument.scope_level == "ELEMENT",
                )
                .all()
            )
            element_boms = [d.to_dict() for d in docs]

    assemblies: dict[str, list[dict[str, Any]]] = {}
    for bom in element_boms:
        aid = bom.get("assemblyId") or "_none"
        assemblies.setdefault(aid, []).append(dict(bom))

    assembly_nodes = []
    all_lines: list[dict[str, Any]] = []
    for aid, boms in assemblies.items():
        lines: list[dict[str, Any]] = []
        for b in boms:
            lines.extend(b.get("lines") or [])
        all_lines.extend(lines)
        assembly_nodes.append(
            {
                "scopeLevel": "ASSEMBLY",
                "assemblyId": aid,
                "summary": _summarize(lines),
                "rollup": rollup_lines(lines, scope_level="ASSEMBLY"),
                "elements": [{"elementId": b.get("elementId"), "bomId": b.get("bomId"), "status": b.get("status")} for b in boms],
            }
        )

    # Attach design / location / floor when available
    design_nodes = []
    try:
        des_list = dh.list_design_documents(project_id, company_gst=gst)
    except Exception:
        des_list = []
    for des in des_list:
        did = des.get("designDocumentId")
        related = [a for a in assembly_nodes if True]  # assemblies may share design
        # Filter by assembly design via scene
        design_lines: list[dict[str, Any]] = []
        try:
            asms = ds.list_assemblies(did, company_gst=gst)
            asm_ids = {a["assemblyId"] for a in asms}
            for a in assembly_nodes:
                if a.get("assemblyId") in asm_ids:
                    for el in a.get("elements") or []:
                        pass
                    design_lines.extend(a.get("rollup") or [])
        except Exception:
            design_lines = list(all_lines)
        design_nodes.append(
            {
                "scopeLevel": "DESIGN",
                "designDocumentId": did,
                "summary": _summarize(design_lines if design_lines else all_lines),
                "rollup": rollup_lines(
                    [ln for a in assembly_nodes for ln in (a.get("rollup") or [])]
                    if design_lines
                    else all_lines,
                    scope_level="DESIGN",
                ),
            }
        )

    project_rollup = rollup_lines(all_lines, scope_level="PROJECT")
    return {
        "scopeLevel": "PROJECT",
        "projectId": project_id,
        "summary": _summarize(all_lines),
        "rollup": project_rollup,
        "assemblies": assembly_nodes,
        "designs": design_nodes,
        "hierarchy": ["CELL", "ELEMENT", "ASSEMBLY", "DESIGN", "LOCATION", "FLOOR", "PROJECT"],
        "usesQuoteSellingRate": False,
    }


def generate_composite_fixture_bom(*, company_gst: str, element_id: str) -> dict[str, Any]:
    """Helper used by smoke — same path as generate_element_bom."""
    return generate_element_bom(element_id, company_gst=company_gst, persist=True, force=True)
