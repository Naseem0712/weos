"""Engineering Master Data — Series / Profiles / Hardware / Glass / Accessories.

SQL-backed canonical masters. Cost-basis fields are foundation only (no Costing Engine).
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Mapping

from sqlalchemy import inspect, text

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.db.models import (
    COST_BASIS_TYPES,
    AccessoryMaster,
    GlassMaster,
    HardwareItem,
    HardwareRule,
    ProductSeries,
    ProfileMaster,
    PROFILE_ROLES,
    SeriesProfileRole,
)
from WEOS.factory.canonical_customer import _norm_company_gst

_log = logging.getLogger("weos.engineering_masters")

BATCH_ID = "ENG-MASTER"
ACCESSORY_KINDS = (
    "MESH",
    "GASKET",
    "EPDM",
    "FASTENER",
    "ANCHOR",
    "FINISH",
    "MATERIAL",
    "ACCESSORY",
)


def new_series_id() -> str:
    return "SER-" + uuid.uuid4().hex[:16].upper()


def new_profile_id() -> str:
    return "PROF-" + uuid.uuid4().hex[:16].upper()


def new_mapping_id() -> str:
    return "SPR-" + uuid.uuid4().hex[:16].upper()


def new_hardware_id() -> str:
    return "HW-" + uuid.uuid4().hex[:16].upper()


def new_hardware_rule_id() -> str:
    return "HWR-" + uuid.uuid4().hex[:16].upper()


def new_glass_id() -> str:
    return "GLS-" + uuid.uuid4().hex[:16].upper()


def new_accessory_id() -> str:
    return "ACC-" + uuid.uuid4().hex[:16].upper()


def _require_db() -> None:
    if not db_available():
        raise RuntimeError("Database unavailable for engineering masters")
    init_db()
    ensure_engineering_schema()


def ensure_engineering_schema() -> None:
    """create_all does not ALTER — add profile_reference if missing on older DBs."""
    from WEOS.db.engine import get_engine

    eng = get_engine()
    if eng is None:
        return
    try:
        insp = inspect(eng)
        if "frame_members" not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns("frame_members")}
        if "profile_reference" not in cols:
            with eng.begin() as conn:
                conn.execute(text("ALTER TABLE frame_members ADD COLUMN profile_reference VARCHAR(80)"))
            _log.info("Added frame_members.profile_reference")
    except Exception as exc:  # pragma: no cover — best-effort migrate
        _log.warning("ensure_engineering_schema: %s", exc)


def _norm_role(role: str | None) -> str:
    r = str(role or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "OUTER": "OUTER_FRAME",
        "FRAME": "OUTER_FRAME",
        "OUTERFRAME": "OUTER_FRAME",
        "OUTER_FRAME_V": "OUTER_FRAME_VERTICAL",
        "OUTER_FRAME_H": "OUTER_FRAME_HORIZONTAL",
        "VERTICAL_FRAME": "OUTER_FRAME_VERTICAL",
        "HORIZONTAL_FRAME": "OUTER_FRAME_HORIZONTAL",
        "MULLION_V": "MULLION",
        "HORIZONTAL_MULLION": "TRANSOM",
        "MEETING_STILE": "INTERLOCK",
        "INTERLOCK_BAR": "INTERLOCK",
        "STILE": "SHUTTER_STILE",
        "RAIL": "SHUTTER_RAIL",
    }
    r = aliases.get(r, r)
    return r


def validate_profile_payload(data: Mapping[str, Any], *, partial: bool = False) -> list[str]:
    """Return validation issues (empty = ok)."""
    issues: list[str] = []
    if not partial:
        if not str(data.get("code") or "").strip():
            issues.append("code is required")
        if not str(data.get("name") or "").strip():
            issues.append("name is required")
    role = data.get("defaultRole") or data.get("default_role")
    if role is not None and str(role).strip():
        nr = _norm_role(str(role))
        if nr not in PROFILE_ROLES and nr != "GENERIC":
            issues.append(f"unknown defaultRole '{role}'")
    wpr = data.get("weightPerRmt", data.get("weight_per_rmt"))
    if wpr is not None and wpr != "":
        try:
            if float(wpr) < 0:
                issues.append("weightPerRmt must be >= 0")
        except (TypeError, ValueError):
            issues.append("weightPerRmt must be numeric")
    stock = data.get("stockLengthMm", data.get("stock_length_mm"))
    if stock is not None and stock != "":
        try:
            if float(stock) <= 0:
                issues.append("stockLengthMm must be > 0")
        except (TypeError, ValueError):
            issues.append("stockLengthMm must be numeric")
    cbt = data.get("costBasisType", data.get("cost_basis_type"))
    if cbt is not None and str(cbt).strip():
        if str(cbt).strip().upper() not in COST_BASIS_TYPES:
            issues.append(f"unknown costBasisType '{cbt}'")
    return issues


def master_revision_token(company_gst: str | None = None) -> str:
    """Fingerprint of active master revisions for stale BOM tracking."""
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        def _sum(model: Any, field: str = "revision") -> int:
            q = s.query(model)
            if gst and hasattr(model, "company_gst"):
                q = q.filter((model.company_gst == gst) | (model.company_gst.is_(None)))
            total = 0
            pk_name = list(model.__table__.primary_key.columns)[0].name
            for row in q.all():
                total += int(getattr(row, field) or 0)
                total += hash(getattr(row, pk_name)) % 97
            return total

        parts = [
            _sum(ProductSeries),
            _sum(ProfileMaster),
            _sum(SeriesProfileRole),
            _sum(HardwareItem),
            _sum(HardwareRule),
            _sum(GlassMaster),
            _sum(AccessoryMaster),
        ]
    return f"MR-{sum(parts) & 0xFFFFFFFF:08X}"


# ── Product Series ───────────────────────────────────────────────────────────


def create_series(
    *,
    code: str,
    name: str,
    family: str = "WINDOW",
    company_gst: str | None = None,
    product_types: list[str] | None = None,
    system_depth_mm: float | None = None,
    track_count: int | None = None,
    legacy_product_id: str | None = None,
    compatibility_aliases: list[str] | None = None,
    description: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_db()
    code_s = str(code or "").strip()
    name_s = str(name or "").strip()
    if not code_s or not name_s:
        raise ValueError("series code and name are required")
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        existing = (
            s.query(ProductSeries)
            .filter(ProductSeries.code == code_s, ProductSeries.company_gst == gst)
            .first()
        )
        if existing:
            raise ValueError(f"series code '{code_s}' already exists")
        row = ProductSeries(
            series_id=new_series_id(),
            company_gst=gst,
            code=code_s,
            name=name_s,
            family=str(family or "WINDOW").strip().upper(),
            product_types=list(product_types or []),
            system_depth_mm=system_depth_mm,
            track_count=track_count,
            legacy_product_id=legacy_product_id,
            compatibility_aliases=list(compatibility_aliases or []),
            description=description,
            meta=meta or {},
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def update_series(series_id: str, *, company_gst: str | None = None, **fields: Any) -> dict[str, Any]:
    _require_db()
    with session_scope() as s:
        row = s.get(ProductSeries, series_id)
        if not row:
            raise PermissionError("series not found")
        if company_gst and row.company_gst and row.company_gst != _norm_company_gst(company_gst):
            raise PermissionError("series not found")
        mapping = {
            "name": "name",
            "code": "code",
            "family": "family",
            "productTypes": "product_types",
            "systemDepthMm": "system_depth_mm",
            "trackCount": "track_count",
            "legacyProductId": "legacy_product_id",
            "compatibilityAliases": "compatibility_aliases",
            "description": "description",
            "status": "status",
            "meta": "meta",
        }
        for k, col in mapping.items():
            if k in fields and fields[k] is not None:
                val = fields[k]
                if col == "family":
                    val = str(val).strip().upper()
                setattr(row, col, val)
        row.revision = int(row.revision or 1) + 1
        s.flush()
        return row.to_dict()


def get_series(series_id: str) -> dict[str, Any] | None:
    _require_db()
    with session_scope() as s:
        row = s.get(ProductSeries, series_id)
        return row.to_dict() if row else None


def list_series(*, company_gst: str | None = None, family: str | None = None) -> list[dict[str, Any]]:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        q = s.query(ProductSeries).filter(ProductSeries.status != "deleted")
        if gst:
            q = q.filter((ProductSeries.company_gst == gst) | (ProductSeries.company_gst.is_(None)))
        if family:
            q = q.filter(ProductSeries.family == str(family).upper())
        return [r.to_dict() for r in q.order_by(ProductSeries.code).all()]


def resolve_series_ref(ref: str | None, *, company_gst: str | None = None) -> dict[str, Any] | None:
    """Resolve series by id, code, legacy product id, or compatibility alias (e.g. 29MM Sliding)."""
    if not ref or not str(ref).strip():
        return None
    _require_db()
    key = str(ref).strip()
    key_norm = re.sub(r"\s+", " ", key).strip().lower()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        row = s.get(ProductSeries, key)
        if row:
            return row.to_dict()
        rows = s.query(ProductSeries).filter(ProductSeries.status != "deleted").all()
        for r in rows:
            if gst and r.company_gst and r.company_gst != gst:
                continue
            if r.code and r.code.lower() == key_norm:
                return r.to_dict()
            if r.legacy_product_id and str(r.legacy_product_id).lower() == key_norm:
                return r.to_dict()
            aliases = r.compatibility_aliases or []
            for a in aliases:
                if re.sub(r"\s+", " ", str(a)).strip().lower() == key_norm:
                    return r.to_dict()
            if r.name and re.sub(r"\s+", " ", r.name).strip().lower() == key_norm:
                return r.to_dict()
    return None


# ── Profiles ─────────────────────────────────────────────────────────────────


def create_profile(*, code: str, name: str, company_gst: str | None = None, **fields: Any) -> dict[str, Any]:
    _require_db()
    payload = {"code": code, "name": name, **fields}
    issues = validate_profile_payload(payload)
    if issues:
        raise ValueError("; ".join(issues))
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        row = ProfileMaster(
            profile_id=new_profile_id(),
            company_gst=gst,
            code=str(code).strip(),
            name=str(name).strip(),
            default_role=_norm_role(fields.get("defaultRole") or fields.get("default_role")) or None,
            roles=list(fields.get("roles") or ([fields.get("defaultRole")] if fields.get("defaultRole") else [])),
            width_mm=_float_or_none(fields.get("widthMm", fields.get("width_mm"))),
            height_mm=_float_or_none(fields.get("heightMm", fields.get("height_mm"))),
            wall_thickness_mm=_float_or_none(fields.get("wallThicknessMm", fields.get("wall_thickness_mm"))),
            weight_per_rmt=_float_or_none(fields.get("weightPerRmt", fields.get("weight_per_rmt"))),
            stock_length_mm=_float_or_none(fields.get("stockLengthMm", fields.get("stock_length_mm"))),
            alloy_or_material=fields.get("alloyOrMaterial") or fields.get("alloy_or_material"),
            finish_ref_id=fields.get("finishRefId") or fields.get("finish_ref_id"),
            cost_basis_type=(str(fields.get("costBasisType") or fields.get("cost_basis_type") or "").upper() or None),
            cost_basis_value=_float_or_none(fields.get("costBasisValue", fields.get("cost_basis_value"))),
            legacy_codes=list(fields.get("legacyCodes") or fields.get("legacy_codes") or []),
            description=fields.get("description"),
            meta=fields.get("meta") or {},
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def update_profile(profile_id: str, *, company_gst: str | None = None, **fields: Any) -> dict[str, Any]:
    _require_db()
    issues = validate_profile_payload(fields, partial=True)
    if issues:
        raise ValueError("; ".join(issues))
    with session_scope() as s:
        row = s.get(ProfileMaster, profile_id)
        if not row:
            raise PermissionError("profile not found")
        if company_gst and row.company_gst and row.company_gst != _norm_company_gst(company_gst):
            raise PermissionError("profile not found")
        colmap = {
            "code": "code",
            "name": "name",
            "defaultRole": "default_role",
            "roles": "roles",
            "widthMm": "width_mm",
            "heightMm": "height_mm",
            "wallThicknessMm": "wall_thickness_mm",
            "weightPerRmt": "weight_per_rmt",
            "stockLengthMm": "stock_length_mm",
            "alloyOrMaterial": "alloy_or_material",
            "finishRefId": "finish_ref_id",
            "costBasisType": "cost_basis_type",
            "costBasisValue": "cost_basis_value",
            "legacyCodes": "legacy_codes",
            "description": "description",
            "status": "status",
            "meta": "meta",
        }
        for k, col in colmap.items():
            if k not in fields or fields[k] is None:
                continue
            val = fields[k]
            if col == "default_role":
                val = _norm_role(val)
            if col == "cost_basis_type":
                val = str(val).upper()
            setattr(row, col, val)
        row.revision = int(row.revision or 1) + 1
        s.flush()
        return row.to_dict()


def get_profile(profile_id: str) -> dict[str, Any] | None:
    _require_db()
    with session_scope() as s:
        row = s.get(ProfileMaster, profile_id)
        return row.to_dict() if row else None


def list_profiles(*, company_gst: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    role_n = _norm_role(role) if role else None
    with session_scope() as s:
        q = s.query(ProfileMaster).filter(ProfileMaster.status != "deleted")
        if gst:
            q = q.filter((ProfileMaster.company_gst == gst) | (ProfileMaster.company_gst.is_(None)))
        rows = q.order_by(ProfileMaster.code).all()
        out = []
        for r in rows:
            d = r.to_dict()
            if role_n:
                roles = [str(x).upper() for x in (d.get("roles") or [])]
                if role_n not in roles and d.get("defaultRole") != role_n:
                    continue
            out.append(d)
        return out


# ── Series ↔ role mapping + resolver ─────────────────────────────────────────


def map_series_profile_role(
    *,
    series_id: str,
    role: str,
    profile_id: str,
    is_required: bool = True,
    notes: str | None = None,
) -> dict[str, Any]:
    _require_db()
    role_n = _norm_role(role)
    if not role_n:
        raise ValueError("role is required")
    with session_scope() as s:
        ser = s.get(ProductSeries, series_id)
        if not ser:
            raise ValueError("series not found")
        prof = s.get(ProfileMaster, profile_id)
        if not prof:
            raise ValueError("profile not found")
        existing = (
            s.query(SeriesProfileRole)
            .filter(SeriesProfileRole.series_id == series_id, SeriesProfileRole.role == role_n)
            .first()
        )
        if existing:
            existing.profile_id = profile_id
            existing.is_required = bool(is_required)
            existing.notes = notes
            existing.status = "active"
            existing.revision = int(existing.revision or 1) + 1
            s.flush()
            return existing.to_dict()
        row = SeriesProfileRole(
            mapping_id=new_mapping_id(),
            series_id=series_id,
            role=role_n,
            profile_id=profile_id,
            is_required=bool(is_required),
            notes=notes,
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def list_series_role_mappings(series_id: str) -> list[dict[str, Any]]:
    _require_db()
    with session_scope() as s:
        rows = (
            s.query(SeriesProfileRole)
            .filter(SeriesProfileRole.series_id == series_id, SeriesProfileRole.status == "active")
            .order_by(SeriesProfileRole.role)
            .all()
        )
        return [r.to_dict() for r in rows]


def resolve_profile_for_role(
    series_id: str | None,
    role: str | None,
    *,
    profile_reference: str | None = None,
) -> dict[str, Any]:
    """Resolve FrameMember profileRole/profileReference via Series+role (or explicit override)."""
    _require_db()
    if profile_reference:
        prof = get_profile(profile_reference)
        if prof:
            return {"ok": True, "profile": prof, "source": "profile_reference", "role": _norm_role(role)}
        return {
            "ok": False,
            "profile": None,
            "source": "profile_reference",
            "issue": f"profile_reference '{profile_reference}' not found",
            "role": _norm_role(role),
        }
    role_n = _norm_role(role)
    if not series_id or not role_n:
        return {
            "ok": False,
            "profile": None,
            "source": "unresolved",
            "issue": "series_id and role required when profile_reference absent",
            "role": role_n,
        }
    # Prefer exact role, then OUTER_FRAME fallback for V/H variants
    candidates = [role_n]
    if role_n in ("OUTER_FRAME_VERTICAL", "OUTER_FRAME_HORIZONTAL"):
        candidates.append("OUTER_FRAME")
    if role_n == "OUTER_FRAME":
        candidates.extend(["OUTER_FRAME_VERTICAL", "OUTER_FRAME_HORIZONTAL"])
    with session_scope() as s:
        for cand in candidates:
            m = (
                s.query(SeriesProfileRole)
                .filter(
                    SeriesProfileRole.series_id == series_id,
                    SeriesProfileRole.role == cand,
                    SeriesProfileRole.status == "active",
                )
                .first()
            )
            if m:
                prof = s.get(ProfileMaster, m.profile_id)
                if prof and prof.status != "deleted":
                    return {
                        "ok": True,
                        "profile": prof.to_dict(),
                        "source": "series_role",
                        "role": cand,
                        "mappingId": m.mapping_id,
                    }
                return {
                    "ok": False,
                    "profile": None,
                    "source": "series_role",
                    "issue": f"mapped profile '{m.profile_id}' missing",
                    "role": cand,
                }
    return {
        "ok": False,
        "profile": None,
        "source": "series_role",
        "issue": f"no profile mapped for series={series_id} role={role_n}",
        "role": role_n,
    }


# ── Hardware / Glass / Accessories ───────────────────────────────────────────


def create_hardware(*, code: str, name: str, company_gst: str | None = None, **fields: Any) -> dict[str, Any]:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        row = HardwareItem(
            hardware_id=new_hardware_id(),
            company_gst=gst,
            code=str(code).strip(),
            name=str(name).strip(),
            category=str(fields.get("category") or "HARDWARE").upper(),
            unit=str(fields.get("unit") or "PC").upper(),
            cost_basis_type=(str(fields.get("costBasisType") or "").upper() or None),
            cost_basis_value=_float_or_none(fields.get("costBasisValue")),
            compatible_families=list(fields.get("compatibleFamilies") or []),
            legacy_codes=list(fields.get("legacyCodes") or []),
            description=fields.get("description"),
            meta=fields.get("meta") or {},
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def create_hardware_rule(
    *,
    hardware_id: str,
    name: str,
    quantity_formula: str = "1",
    series_id: str | None = None,
    product_type: str | None = None,
    condition_formula: str | None = None,
    unit: str = "PC",
    company_gst: str | None = None,
    priority: int = 100,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_db()
    with session_scope() as s:
        if not s.get(HardwareItem, hardware_id):
            raise ValueError("hardware item not found")
        row = HardwareRule(
            rule_id=new_hardware_rule_id(),
            company_gst=_norm_company_gst(company_gst) if company_gst else None,
            series_id=series_id,
            product_type=str(product_type).upper() if product_type else None,
            hardware_id=hardware_id,
            name=str(name).strip(),
            quantity_formula=str(quantity_formula or "1"),
            condition_formula=condition_formula,
            unit=str(unit or "PC").upper(),
            priority=int(priority),
            meta=meta or {},
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def list_hardware(*, company_gst: str | None = None) -> list[dict[str, Any]]:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        q = s.query(HardwareItem).filter(HardwareItem.status != "deleted")
        if gst:
            q = q.filter((HardwareItem.company_gst == gst) | (HardwareItem.company_gst.is_(None)))
        return [r.to_dict() for r in q.order_by(HardwareItem.code).all()]


def list_hardware_rules(*, series_id: str | None = None, product_type: str | None = None) -> list[dict[str, Any]]:
    _require_db()
    with session_scope() as s:
        q = s.query(HardwareRule).filter(HardwareRule.status == "active")
        if series_id:
            q = q.filter((HardwareRule.series_id == series_id) | (HardwareRule.series_id.is_(None)))
        if product_type:
            pt = str(product_type).upper()
            q = q.filter((HardwareRule.product_type == pt) | (HardwareRule.product_type.is_(None)))
        return [r.to_dict() for r in q.order_by(HardwareRule.priority).all()]


def create_glass(*, code: str, name: str, company_gst: str | None = None, **fields: Any) -> dict[str, Any]:
    _require_db()
    with session_scope() as s:
        row = GlassMaster(
            glass_id=new_glass_id(),
            company_gst=_norm_company_gst(company_gst) if company_gst else None,
            code=str(code).strip(),
            name=str(name).strip(),
            makeup=fields.get("makeup"),
            thickness_mm=_float_or_none(fields.get("thicknessMm")),
            density_kg_per_sqm=_float_or_none(fields.get("densityKgPerSqm")),
            cost_basis_type=(str(fields.get("costBasisType") or "").upper() or None),
            cost_basis_value=_float_or_none(fields.get("costBasisValue")),
            legacy_codes=list(fields.get("legacyCodes") or []),
            description=fields.get("description"),
            meta=fields.get("meta") or {},
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def list_glass(*, company_gst: str | None = None) -> list[dict[str, Any]]:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        q = s.query(GlassMaster).filter(GlassMaster.status != "deleted")
        if gst:
            q = q.filter((GlassMaster.company_gst == gst) | (GlassMaster.company_gst.is_(None)))
        return [r.to_dict() for r in q.order_by(GlassMaster.code).all()]


def resolve_glass_ref(ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    _require_db()
    key = str(ref).strip().lower()
    with session_scope() as s:
        row = s.get(GlassMaster, ref)
        if row:
            return row.to_dict()
        for r in s.query(GlassMaster).filter(GlassMaster.status != "deleted").all():
            if r.code.lower() == key or r.name.lower() == key:
                return r.to_dict()
            for lc in r.legacy_codes or []:
                if str(lc).lower() == key:
                    return r.to_dict()
    return None


def create_accessory(
    *,
    kind: str,
    code: str,
    name: str,
    unit: str = "PC",
    company_gst: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    _require_db()
    k = str(kind or "").strip().upper()
    if k not in ACCESSORY_KINDS:
        raise ValueError(f"kind must be one of {', '.join(ACCESSORY_KINDS)}")
    u = str(unit or "PC").strip().upper()
    with session_scope() as s:
        row = AccessoryMaster(
            accessory_id=new_accessory_id(),
            company_gst=_norm_company_gst(company_gst) if company_gst else None,
            kind=k,
            code=str(code).strip(),
            name=str(name).strip(),
            unit=u,
            cost_basis_type=(str(fields.get("costBasisType") or "").upper() or None),
            cost_basis_value=_float_or_none(fields.get("costBasisValue")),
            legacy_codes=list(fields.get("legacyCodes") or []),
            description=fields.get("description"),
            meta=fields.get("meta") or {},
        )
        s.add(row)
        s.flush()
        return row.to_dict()


def list_accessories(*, company_gst: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    _require_db()
    gst = _norm_company_gst(company_gst) if company_gst else None
    with session_scope() as s:
        q = s.query(AccessoryMaster).filter(AccessoryMaster.status != "deleted")
        if gst:
            q = q.filter((AccessoryMaster.company_gst == gst) | (AccessoryMaster.company_gst.is_(None)))
        if kind:
            q = q.filter(AccessoryMaster.kind == str(kind).upper())
        return [r.to_dict() for r in q.order_by(AccessoryMaster.kind, AccessoryMaster.code).all()]


def seed_default_window_masters(*, company_gst: str | None = None) -> dict[str, Any]:
    """Idempotent seed for 29mm/35mm sliding foundation used by BOM smokes & demos."""
    _require_db()
    created: dict[str, Any] = {"series": [], "profiles": [], "mappings": [], "hardware": [], "glass": [], "accessories": []}

    def _ensure_series(code: str, name: str, **kw: Any) -> dict[str, Any]:
        existing = resolve_series_ref(code, company_gst=company_gst)
        if existing:
            return existing
        for alias in kw.get("compatibility_aliases") or []:
            hit = resolve_series_ref(alias, company_gst=company_gst)
            if hit:
                return hit
        row = create_series(code=code, name=name, company_gst=company_gst, **kw)
        created["series"].append(row["seriesId"])
        return row

    s29 = _ensure_series(
        "29mm_sliding",
        "29mm Sliding Window",
        family="WINDOW",
        product_types=["SLIDING", "FIXED", "CASEMENT", "VENTILATOR"],
        system_depth_mm=29,
        track_count=2,
        legacy_product_id="29mm_sliding",
        compatibility_aliases=["29MM Sliding", "29mm Sliding", "29mm_sliding_window", "29MM"],
    )
    s35 = _ensure_series(
        "35mm_sliding",
        "35mm Sliding Window",
        family="WINDOW",
        product_types=["SLIDING", "FIXED"],
        system_depth_mm=35,
        track_count=2,
        legacy_product_id="35mm_sliding",
        compatibility_aliases=["35MM Sliding", "35mm Sliding", "35mm Sliding Window"],
    )

    def _ensure_profile(code: str, name: str, **kw: Any) -> dict[str, Any]:
        for p in list_profiles(company_gst=company_gst):
            if p["code"] == code:
                return p
        row = create_profile(code=code, name=name, company_gst=company_gst, **kw)
        created["profiles"].append(row["profileId"])
        return row

    outer = _ensure_profile(
        "OT-29-65",
        "Outer Track 29x65",
        defaultRole="OUTER_FRAME",
        roles=["OUTER_FRAME", "OUTER_FRAME_VERTICAL", "OUTER_FRAME_HORIZONTAL"],
        widthMm=29,
        heightMm=65,
        wallThicknessMm=1.2,
        weightPerRmt=0.756,
        stockLengthMm=5800,
        costBasisType="PER_KG",
        costBasisValue=220.0,
        legacyCodes=["outer_frame_profile", "Outer frame"],
    )
    mullion = _ensure_profile(
        "MUL-29",
        "Mullion 29",
        defaultRole="MULLION",
        roles=["MULLION", "TRANSOM"],
        widthMm=29,
        heightMm=40,
        weightPerRmt=0.52,
        stockLengthMm=5800,
        costBasisType="PER_RMT",
        costBasisValue=95.0,
    )
    interlock = _ensure_profile(
        "IL-29",
        "Interlock 29",
        defaultRole="INTERLOCK",
        roles=["INTERLOCK", "SHUTTER_STILE"],
        widthMm=29,
        heightMm=35,
        weightPerRmt=0.48,
        stockLengthMm=5800,
        costBasisType="PER_RMT",
        costBasisValue=88.0,
    )
    shutter_rail = _ensure_profile(
        "SR-29",
        "Shutter Rail 29",
        defaultRole="SHUTTER_RAIL",
        roles=["SHUTTER_RAIL", "SASH"],
        widthMm=29,
        heightMm=30,
        weightPerRmt=0.42,
        stockLengthMm=5800,
        costBasisType="PER_RMT",
        costBasisValue=80.0,
    )
    outer35 = _ensure_profile(
        "OT-35-70",
        "Outer Track 35x70",
        defaultRole="OUTER_FRAME",
        roles=["OUTER_FRAME", "OUTER_FRAME_VERTICAL", "OUTER_FRAME_HORIZONTAL"],
        widthMm=35,
        heightMm=70,
        weightPerRmt=0.92,
        stockLengthMm=5800,
        costBasisType="PER_KG",
        costBasisValue=220.0,
    )

    for sid, profiles in (
        (
            s29["seriesId"],
            [
                ("OUTER_FRAME", outer),
                ("OUTER_FRAME_VERTICAL", outer),
                ("OUTER_FRAME_HORIZONTAL", outer),
                ("MULLION", mullion),
                ("TRANSOM", mullion),
                ("INTERLOCK", interlock),
                ("SHUTTER_STILE", interlock),
                ("SHUTTER_RAIL", shutter_rail),
            ],
        ),
        (
            s35["seriesId"],
            [
                ("OUTER_FRAME", outer35),
                ("OUTER_FRAME_VERTICAL", outer35),
                ("OUTER_FRAME_HORIZONTAL", outer35),
                ("MULLION", mullion),
                ("TRANSOM", mullion),
            ],
        ),
    ):
        existing_roles = {m["role"] for m in list_series_role_mappings(sid)}
        for role, prof in profiles:
            if role in existing_roles:
                continue
            m = map_series_profile_role(series_id=sid, role=role, profile_id=prof["profileId"])
            created["mappings"].append(m["mappingId"])

    # Hardware
    hw_codes = {h["code"] for h in list_hardware(company_gst=company_gst)}
    if "HANDLE-STD" not in hw_codes:
        h = create_hardware(
            code="HANDLE-STD",
            name="Standard Handle",
            unit="PC",
            costBasisType="PER_PC",
            costBasisValue=180,
            company_gst=company_gst,
            legacyCodes=["handle"],
        )
        created["hardware"].append(h["hardwareId"])
        create_hardware_rule(
            hardware_id=h["hardwareId"],
            name="One handle per shutter",
            quantity_formula="shutterCount",
            series_id=s29["seriesId"],
            product_type="SLIDING",
            company_gst=company_gst,
        )
    if "ROLLER-STD" not in hw_codes:
        h = create_hardware(
            code="ROLLER-STD",
            name="Wheel / Roller",
            unit="PC",
            costBasisType="PER_PC",
            costBasisValue=55,
            company_gst=company_gst,
            legacyCodes=["wheel_roller"],
        )
        created["hardware"].append(h["hardwareId"])
        create_hardware_rule(
            hardware_id=h["hardwareId"],
            name="Two rollers per shutter",
            quantity_formula="2 * shutterCount",
            series_id=s29["seriesId"],
            product_type="SLIDING",
            company_gst=company_gst,
        )
    if "LOCK-SET" not in hw_codes:
        h = create_hardware(
            code="LOCK-SET",
            name="Lock Set",
            unit="SET",
            costBasisType="PER_SET",
            costBasisValue=120,
            company_gst=company_gst,
        )
        created["hardware"].append(h["hardwareId"])
        create_hardware_rule(
            hardware_id=h["hardwareId"],
            name="One lock set per sliding unit",
            quantity_formula="1",
            series_id=s29["seriesId"],
            product_type="SLIDING",
            company_gst=company_gst,
        )

    glass_codes = {g["code"] for g in list_glass(company_gst=company_gst)}
    if "5MM-CLEAR" not in glass_codes:
        g = create_glass(
            code="5MM-CLEAR",
            name="5mm Clear Float",
            makeup="single",
            thicknessMm=5,
            densityKgPerSqm=12.5,
            costBasisType="PER_SQM",
            costBasisValue=450,
            company_gst=company_gst,
            legacyCodes=["5mm_clear", "glass"],
        )
        created["glass"].append(g["glassId"])

    acc_codes = {a["code"] for a in list_accessories(company_gst=company_gst)}
    for kind, code, name, unit, cbt, cbv in (
        ("MESH", "MESH-SS", "SS Insect Mesh", "SFT", "PER_SFT", 18.0),
        ("GASKET", "EPDM-WOOL", "Woolpile / EPDM gasket", "RMT", "PER_RMT", 12.0),
        ("FASTENER", "SCR-4x25", "Screw 4x25", "NOS", "PER_NOS", 0.5),
        ("ANCHOR", "ANC-M8", "Anchor M8", "PC", "PER_PC", 8.0),
        ("FINISH", "PC-WHITE", "Powder Coat White", "UNIT", "PER_UNIT", 0.0),
        ("MATERIAL", "GEN-AL", "Generic Aluminium", "KG", "PER_KG", 220.0),
    ):
        if code in acc_codes:
            continue
        a = create_accessory(
            kind=kind,
            code=code,
            name=name,
            unit=unit,
            costBasisType=cbt,
            costBasisValue=cbv,
            company_gst=company_gst,
        )
        created["accessories"].append(a["accessoryId"])

    # Railing / Pergola schema capability placeholders (no full BOM yet)
    _ensure_series(
        "railing_generic",
        "Railing System (foundation)",
        family="RAILING",
        product_types=["RAILING"],
        compatibility_aliases=["Railings", "railing"],
        description="Schema foundation — BOM adapter deferred",
        meta={"supportsBom": False, "foundationOnly": True},
    )
    _ensure_series(
        "pergola_generic",
        "Pergola System (foundation)",
        family="PERGOLA",
        product_types=["PERGOLA"],
        compatibility_aliases=["Pergola", "pergola"],
        description="Schema foundation — BOM adapter deferred",
        meta={"supportsBom": False, "foundationOnly": True},
    )

    return {"ok": True, "created": created, "series29": s29, "series35": s35}


def _float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    return float(v)
