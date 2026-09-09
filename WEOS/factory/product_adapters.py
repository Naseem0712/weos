"""Product plugin adapters for Universal Canvas — WEOS V2 Batch 8.

Registry-based dispatch from DesignElement productType → engine plugin.
Does NOT rewrite geometry_engine / pipeline / railing / ventilator / SVG engines.
Does NOT create WindowCanvas / RailingCanvas — ONE Universal Canvas host only.

Geometry (W/H/X/Y) stays on the element; series/glass/hardware/colour live in
config_payload (ProductConfiguration). Unknown types use placeholder fallback.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from WEOS.factory.design_scene import (
    ELEMENT_PRODUCT_CASEMENT,
    ELEMENT_PRODUCT_DOOR,
    ELEMENT_PRODUCT_FIXED,
    ELEMENT_PRODUCT_FOLD,
    ELEMENT_PRODUCT_GRILL,
    ELEMENT_PRODUCT_LOUVER,
    ELEMENT_PRODUCT_OTHER,
    ELEMENT_PRODUCT_PERGOLA,
    ELEMENT_PRODUCT_RAILING,
    ELEMENT_PRODUCT_SHOWER,
    ELEMENT_PRODUCT_SLIDING,
    ELEMENT_PRODUCT_VENTILATOR,
)

# Exact product types — never collapse Sliding/Casement/Fixed/Ventilator to WINDOW.
WINDOW_FAMILY = frozenset(
    {
        ELEMENT_PRODUCT_SLIDING,
        ELEMENT_PRODUCT_FIXED,
        ELEMENT_PRODUCT_CASEMENT,
        ELEMENT_PRODUCT_DOOR,
        ELEMENT_PRODUCT_FOLD,
    }
)

SURFACE_TYPES = frozenset({"SURFACE", "ACP", "HPL", "FLUTED", "PERFORATED"})


def _placeholder_render(element: Mapping[str, Any]) -> dict[str, Any]:
    """Lazy import avoids circular import with universal_canvas registry boot."""
    from WEOS.factory.universal_canvas import placeholder_render

    return placeholder_render(element)


def _pt(element: Mapping[str, Any] | None) -> str:
    el = element or {}
    return str(el.get("productType") or el.get("product_type") or "").strip().upper()


def _w(el: Mapping[str, Any]) -> float:
    v = el.get("widthMm")
    if v is None:
        v = el.get("width_mm")
    return float(v or 0)


def _h(el: Mapping[str, Any]) -> float:
    v = el.get("heightMm")
    if v is None:
        v = el.get("height_mm")
    return float(v or 0)


def _cfg(el: Mapping[str, Any]) -> dict[str, Any]:
    raw = el.get("configPayload") if el.get("configPayload") is not None else el.get("config_payload")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _geo(el: Mapping[str, Any]) -> dict[str, Any]:
    raw = el.get("geometryPayload") if el.get("geometryPayload") is not None else el.get("geometry_payload")
    return dict(raw) if isinstance(raw, Mapping) else {}


@runtime_checkable
class ProductAdapter(Protocol):
    """Adapter contract — relevant product-specific functions only."""

    adapter_id: str

    def supports(self, product_type: str) -> bool: ...

    def load_configuration(self, element: Mapping[str, Any]) -> dict[str, Any]: ...

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def validate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def get_property_schema(self) -> dict[str, Any]: ...

    def update_configuration(
        self, element: Mapping[str, Any], patch: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def calculate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None: ...


def _base_schema_groups(*groups: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "groups": list(groups)}


def _geom_fields() -> dict[str, Any]:
    return {
        "id": "geometry",
        "label": "Geometry",
        "domain": "geometry",
        "fields": [
            {"key": "widthMm", "label": "Width (mm)", "type": "number", "domain": "geometry"},
            {"key": "heightMm", "label": "Height (mm)", "type": "number", "domain": "geometry"},
            {"key": "xMm", "label": "X (mm)", "type": "number", "domain": "geometry"},
            {"key": "yMm", "label": "Y (mm)", "type": "number", "domain": "geometry"},
        ],
    }


class FallbackAdapter:
    """Unknown / incomplete products — placeholder only."""

    adapter_id = "fallback"

    def supports(self, product_type: str) -> bool:
        return True

    def load_configuration(self, element: Mapping[str, Any]) -> dict[str, Any]:
        return _cfg(element)

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        out = _placeholder_render(element)
        out["adapterId"] = self.adapter_id
        out["usedFallback"] = True
        return out

    def validate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"ok": True, "warnings": ["unknown product — placeholder preview"], "errors": []}

    def get_property_schema(self) -> dict[str, Any]:
        return _base_schema_groups(
            _geom_fields(),
            {
                "id": "identity",
                "label": "Product",
                "domain": "config",
                "fields": [
                    {"key": "productType", "label": "Product type", "type": "readonly", "domain": "identity"},
                ],
            },
        )

    def update_configuration(
        self, element: Mapping[str, Any], patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        cfg = _cfg(element)
        for k, v in (patch or {}).items():
            if k in ("widthMm", "heightMm", "xMm", "yMm", "width_mm", "height_mm", "x_mm", "y_mm"):
                continue
            cfg[k] = v
        return cfg

    def calculate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return None


class WindowFamilyAdapter:
    """Sliding / Fixed / Casement / Door / Fold — wraps existing pipeline + SVG."""

    adapter_id = "window_family"

    SYSTEM_BY_TYPE = {
        ELEMENT_PRODUCT_SLIDING: "sliding",
        ELEMENT_PRODUCT_FIXED: "grid",
        ELEMENT_PRODUCT_CASEMENT: "casement",
        ELEMENT_PRODUCT_DOOR: "sliding",
        ELEMENT_PRODUCT_FOLD: "bifold",
    }

    DEFAULT_PRODUCT = {
        ELEMENT_PRODUCT_SLIDING: "29mm_sliding",
        ELEMENT_PRODUCT_FIXED: "29mm_sliding",
        ELEMENT_PRODUCT_CASEMENT: "29mm_sliding",
        ELEMENT_PRODUCT_DOOR: "29mm_sliding",
        ELEMENT_PRODUCT_FOLD: "29mm_sliding",
    }

    def supports(self, product_type: str) -> bool:
        return str(product_type or "").strip().upper() in WINDOW_FAMILY

    def load_configuration(self, element: Mapping[str, Any]) -> dict[str, Any]:
        cfg = _cfg(element)
        pt = _pt(element)
        cfg.setdefault("system", self.SYSTEM_BY_TYPE.get(pt, "sliding"))
        cfg.setdefault("productId", element.get("productId") or self.DEFAULT_PRODUCT.get(pt, "29mm_sliding"))
        cfg.setdefault("productType", pt)
        return cfg

    def _engine_kwargs(self, element: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        pt = _pt(element)
        system = str(config.get("system") or self.SYSTEM_BY_TYPE.get(pt, "sliding"))
        product_id = str(
            config.get("productId")
            or element.get("productId")
            or self.DEFAULT_PRODUCT.get(pt, "29mm_sliding")
        )
        return {
            "width": _w(element),
            "height": _h(element),
            "product_id": product_id,
            "glass": config.get("glass"),
            "colour": config.get("colour") or config.get("color"),
            "handle": config.get("handle"),
            "partitions": config.get("partitions"),
            "mesh": bool(config.get("mesh")),
            "track_count": config.get("trackCount"),
            "section_series": config.get("sectionSeries") or config.get("series"),
            "glass_count": config.get("glassShutters") or config.get("glassCount"),
            "mesh_count": config.get("meshShutters") or config.get("meshCount"),
            "opening": config.get("opening"),
            "opening_side": config.get("openingSide"),
            "opening_explicit": bool(config.get("openingExplicit", False)),
            "fixed_shutters": config.get("fixedShutters"),
            "system": system,
            "fold_left": config.get("foldLeft"),
            "fold_right": config.get("foldRight"),
            "handle_finish": config.get("handleFinish"),
            "handle_level": config.get("handleLevel"),
            "handle_overrides": config.get("handleOverrides"),
            "grid": config.get("grid"),
            "sash_overlap_mm": config.get("sashOverlapMm"),
            "mullion_gap_mm": config.get("mullionGapMm"),
            "frame_material": config.get("frameMaterial"),
        }

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        from WEOS.factory.pipeline import generate_job
        from WEOS.factory.svg_export import render_svg_string

        cfg = dict(config or self.load_configuration(element))
        pt = _pt(element)
        try:
            kw = self._engine_kwargs(element, cfg)
            if kw["width"] <= 0 or kw["height"] <= 0:
                raise ValueError("width/height required")
            job = generate_job(
                kw["width"],
                kw["height"],
                kw["product_id"],
                glass=kw["glass"],
                colour=kw["colour"],
                handle=kw["handle"],
                partitions=kw["partitions"],
                mesh=kw["mesh"],
                track_count=kw["track_count"],
                section_series=kw["section_series"],
                glass_count=kw["glass_count"],
                mesh_count=kw["mesh_count"],
                opening=kw["opening"],
                opening_side=kw["opening_side"],
                opening_explicit=kw["opening_explicit"],
                fixed_shutters=kw["fixed_shutters"],
                system=kw["system"],
                fold_left=kw["fold_left"],
                fold_right=kw["fold_right"],
                handle_finish=kw["handle_finish"],
                handle_level=kw["handle_level"],
                handle_overrides=kw["handle_overrides"],
                grid=kw["grid"],
                sash_overlap_mm=kw["sash_overlap_mm"],
                mullion_gap_mm=kw["mullion_gap_mm"],
                frame_material=kw["frame_material"],
            )
            colour_id = kw["colour"]
            svg = render_svg_string(job.drawing, colour=colour_id) if job.drawing else ""
            if not svg:
                raise ValueError("empty svg")
            return {
                "kind": "engine_svg",
                "adapterId": self.adapter_id,
                "elementId": element.get("elementId") or element.get("element_id"),
                "productType": pt,
                "widthMm": _w(element),
                "heightMm": _h(element),
                "displayCode": element.get("displayCode") or element.get("display_code"),
                "svg": svg,
                "usedFallback": False,
                "system": kw["system"],
            }
        except Exception:
            out = _placeholder_render(element)
            out["adapterId"] = self.adapter_id
            out["usedFallback"] = True
            out["error"] = "window preview failed"
            return out

    def validate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        pt = _pt(element)
        if pt not in WINDOW_FAMILY:
            errors.append(f"unsupported window type {pt}")
        if _w(element) <= 0 or _h(element) <= 0:
            errors.append("widthMm and heightMm must be > 0")
        if pt == "WINDOW":
            errors.append("product type must not collapse to WINDOW")
        return {"ok": not errors, "errors": errors, "warnings": warnings}

    def get_property_schema(self) -> dict[str, Any]:
        return _base_schema_groups(
            _geom_fields(),
            {
                "id": "series",
                "label": "Series / System",
                "domain": "config",
                "fields": [
                    {"key": "sectionSeries", "label": "Series", "type": "string", "domain": "config"},
                    {"key": "system", "label": "System", "type": "string", "domain": "config"},
                    {"key": "trackCount", "label": "Track count", "type": "number", "domain": "config"},
                    {"key": "glassShutters", "label": "Shutter count", "type": "number", "domain": "config"},
                    {"key": "opening", "label": "Opening", "type": "string", "domain": "config"},
                ],
            },
            {
                "id": "glass",
                "label": "Glass",
                "domain": "config",
                "fields": [
                    {"key": "glass", "label": "Glass type", "type": "string", "domain": "config"},
                ],
            },
            {
                "id": "hardware",
                "label": "Hardware",
                "domain": "config",
                "fields": [
                    {"key": "handle", "label": "Handle", "type": "string", "domain": "config"},
                    {"key": "mesh", "label": "Mesh", "type": "boolean", "domain": "config"},
                ],
            },
            {
                "id": "finish",
                "label": "Finish",
                "domain": "config",
                "fields": [
                    {"key": "colour", "label": "Colour", "type": "string", "domain": "config"},
                ],
            },
        )

    def update_configuration(
        self, element: Mapping[str, Any], patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        cfg = self.load_configuration(element)
        geom_keys = {"widthMm", "heightMm", "xMm", "yMm", "width_mm", "height_mm", "x_mm", "y_mm"}
        for k, v in (patch or {}).items():
            if k in geom_keys:
                continue
            cfg[k] = v
        cfg["productType"] = _pt(element)
        return cfg

    def calculate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        from WEOS.factory.pipeline import generate_job

        cfg = dict(config or self.load_configuration(element))
        kw = self._engine_kwargs(element, cfg)
        if kw["width"] <= 0 or kw["height"] <= 0:
            return None
        job = generate_job(
            kw["width"],
            kw["height"],
            kw["product_id"],
            glass=kw["glass"],
            colour=kw["colour"],
            handle=kw["handle"],
            partitions=kw["partitions"],
            mesh=kw["mesh"],
            track_count=kw["track_count"],
            section_series=kw["section_series"],
            glass_count=kw["glass_count"],
            mesh_count=kw["mesh_count"],
            opening=kw["opening"],
            opening_side=kw["opening_side"],
            opening_explicit=kw["opening_explicit"],
            fixed_shutters=kw["fixed_shutters"],
            system=kw["system"],
            fold_left=kw["fold_left"],
            fold_right=kw["fold_right"],
            handle_finish=kw["handle_finish"],
            handle_level=kw["handle_level"],
            handle_overrides=kw["handle_overrides"],
            grid=kw["grid"],
            sash_overlap_mm=kw["sash_overlap_mm"],
            mullion_gap_mm=kw["mullion_gap_mm"],
            frame_material=kw["frame_material"],
        )
        meta = getattr(job, "meta", None) or {}
        area = getattr(job, "area_sqft", None)
        if area is None and isinstance(meta, Mapping):
            area = meta.get("areaSqft")
        return {
            "adapterId": self.adapter_id,
            "productType": _pt(element),
            "system": kw["system"],
            "areaSqft": area,
            "drawing": True,
        }


class VentilatorAdapter:
    adapter_id = "ventilator"

    def supports(self, product_type: str) -> bool:
        return str(product_type or "").strip().upper() == ELEMENT_PRODUCT_VENTILATOR

    def load_configuration(self, element: Mapping[str, Any]) -> dict[str, Any]:
        cfg = _cfg(element)
        vent = cfg.get("ventilator") if isinstance(cfg.get("ventilator"), Mapping) else cfg
        out = dict(vent) if isinstance(vent, Mapping) else {}
        out.setdefault("productType", ELEMENT_PRODUCT_VENTILATOR)
        return out

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        from WEOS.factory.ventilator_engine import compute_ventilator, ensure_ventilator_dims, ventilator_svg

        cfg = ensure_ventilator_dims(
            dict(config or self.load_configuration(element)),
            width=_w(element) or None,
            height=_h(element) or None,
        )
        try:
            q = compute_ventilator(cfg)
            svg = ventilator_svg(cfg, quote=q)
            return {
                "kind": "engine_svg",
                "adapterId": self.adapter_id,
                "elementId": element.get("elementId") or element.get("element_id"),
                "productType": ELEMENT_PRODUCT_VENTILATOR,
                "widthMm": _w(element),
                "heightMm": _h(element),
                "displayCode": element.get("displayCode") or element.get("display_code"),
                "svg": svg,
                "usedFallback": False,
                "quote": q,
            }
        except Exception:
            out = _placeholder_render(element)
            out["adapterId"] = self.adapter_id
            out["usedFallback"] = True
            return out

    def validate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        errors = []
        if _w(element) <= 0 or _h(element) <= 0:
            errors.append("widthMm and heightMm must be > 0")
        return {"ok": not errors, "errors": errors, "warnings": []}

    def get_property_schema(self) -> dict[str, Any]:
        return _base_schema_groups(
            _geom_fields(),
            {
                "id": "ventilator",
                "label": "Ventilator",
                "domain": "config",
                "fields": [
                    {"key": "mode", "label": "Type", "type": "string", "domain": "config"},
                    {"key": "frameProfile", "label": "Frame / profile", "type": "string", "domain": "config"},
                    {"key": "glass", "label": "Glass / louver", "type": "string", "domain": "config"},
                    {"key": "opening", "label": "Opening", "type": "string", "domain": "config"},
                    {"key": "hardware", "label": "Hardware", "type": "string", "domain": "config"},
                    {"key": "colour", "label": "Colour", "type": "string", "domain": "config"},
                ],
            },
        )

    def update_configuration(
        self, element: Mapping[str, Any], patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        cfg = self.load_configuration(element)
        for k, v in (patch or {}).items():
            if k in ("widthMm", "heightMm", "xMm", "yMm"):
                continue
            cfg[k] = v
        return cfg

    def calculate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        from WEOS.factory.ventilator_engine import compute_ventilator, ensure_ventilator_dims

        cfg = ensure_ventilator_dims(
            dict(config or self.load_configuration(element)),
            width=_w(element) or None,
            height=_h(element) or None,
        )
        return compute_ventilator(cfg)


class RailingAdapter:
    """Railing engineering stays in railing_engine; canvas owns placement only."""

    adapter_id = "railing"

    def supports(self, product_type: str) -> bool:
        return str(product_type or "").strip().upper() == ELEMENT_PRODUCT_RAILING

    def load_configuration(self, element: Mapping[str, Any]) -> dict[str, Any]:
        cfg = _cfg(element)
        rail = cfg.get("railing") if isinstance(cfg.get("railing"), Mapping) else cfg
        out = dict(rail) if isinstance(rail, Mapping) else {}
        out.setdefault("productType", ELEMENT_PRODUCT_RAILING)
        out.setdefault("shape", out.get("shape") or "straight")
        return out

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        from WEOS.factory.railing_engine import compute_railing, ensure_railing_dims, railing_svg

        cfg = ensure_railing_dims(
            dict(config or self.load_configuration(element)),
            width=_w(element) or None,
            height=_h(element) or None,
        )
        try:
            q = compute_railing(cfg)
            svg = railing_svg(cfg, quote=q)
            return {
                "kind": "engine_svg",
                "adapterId": self.adapter_id,
                "elementId": element.get("elementId") or element.get("element_id"),
                "productType": ELEMENT_PRODUCT_RAILING,
                "widthMm": _w(element),
                "heightMm": _h(element),
                "displayCode": element.get("displayCode") or element.get("display_code"),
                "svg": svg,
                "usedFallback": False,
                "quote": {
                    "shape": q.get("shape"),
                    "panelCount": q.get("panelCount"),
                    "sellingPerUnit": q.get("sellingPerUnit"),
                },
            }
        except Exception:
            out = _placeholder_render(element)
            out["adapterId"] = self.adapter_id
            out["usedFallback"] = True
            return out

    def validate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        errors = []
        if _w(element) <= 0:
            errors.append("length/widthMm must be > 0")
        return {"ok": not errors, "errors": errors, "warnings": []}

    def get_property_schema(self) -> dict[str, Any]:
        return _base_schema_groups(
            {
                "id": "geometry",
                "label": "Geometry",
                "domain": "geometry",
                "fields": [
                    {"key": "widthMm", "label": "Length (mm)", "type": "number", "domain": "geometry"},
                    {"key": "heightMm", "label": "Height (mm)", "type": "number", "domain": "geometry"},
                    {"key": "xMm", "label": "X (mm)", "type": "number", "domain": "geometry"},
                    {"key": "yMm", "label": "Y (mm)", "type": "number", "domain": "geometry"},
                    {"key": "shape", "label": "Shape", "type": "string", "domain": "config"},
                    {"key": "stairSteps", "label": "Stair steps", "type": "number", "domain": "config"},
                ],
            },
            {
                "id": "system",
                "label": "System",
                "domain": "config",
                "fields": [
                    {"key": "mountType", "label": "Mount type", "type": "string", "domain": "config"},
                    {"key": "handrail", "label": "Handrail", "type": "string", "domain": "config"},
                    {"key": "bottomRail", "label": "Bottom rail", "type": "string", "domain": "config"},
                ],
            },
            {
                "id": "glass",
                "label": "Glass",
                "domain": "config",
                "fields": [
                    {"key": "glassThicknessMm", "label": "Glass thickness", "type": "number", "domain": "config"},
                    {"key": "glassType", "label": "Glass type", "type": "string", "domain": "config"},
                    {"key": "panels", "label": "Divisions / panels", "type": "number", "domain": "config"},
                ],
            },
            {
                "id": "fixing",
                "label": "Fixing",
                "domain": "config",
                "fields": [
                    {"key": "brackets", "label": "Brackets", "type": "string", "domain": "config"},
                    {"key": "connectors", "label": "Connectors", "type": "string", "domain": "config"},
                    {"key": "studs", "label": "Studs", "type": "string", "domain": "config"},
                    {"key": "anchors", "label": "Anchors", "type": "string", "domain": "config"},
                ],
            },
        )

    def update_configuration(
        self, element: Mapping[str, Any], patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        cfg = self.load_configuration(element)
        for k, v in (patch or {}).items():
            if k in ("widthMm", "heightMm", "xMm", "yMm"):
                continue
            cfg[k] = v
        return cfg

    def calculate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        from WEOS.factory.railing_engine import compute_railing, ensure_railing_dims

        cfg = ensure_railing_dims(
            dict(config or self.load_configuration(element)),
            width=_w(element) or None,
            height=_h(element) or None,
        )
        return compute_railing(cfg)


class ShowerAdapter:
    adapter_id = "shower"

    def supports(self, product_type: str) -> bool:
        return str(product_type or "").strip().upper() == ELEMENT_PRODUCT_SHOWER

    def load_configuration(self, element: Mapping[str, Any]) -> dict[str, Any]:
        cfg = _cfg(element)
        sh = cfg.get("shower") if isinstance(cfg.get("shower"), Mapping) else cfg
        out = dict(sh) if isinstance(sh, Mapping) else {}
        out.setdefault("productType", ELEMENT_PRODUCT_SHOWER)
        return out

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        from WEOS.factory.shower_engine import compute_shower, ensure_shower_dims, shower_svg

        cfg = ensure_shower_dims(
            dict(config or self.load_configuration(element)),
            width=_w(element) or None,
            height=_h(element) or None,
        )
        try:
            q = compute_shower(cfg)
            svg = shower_svg(cfg, quote=q)
            return {
                "kind": "engine_svg",
                "adapterId": self.adapter_id,
                "elementId": element.get("elementId") or element.get("element_id"),
                "productType": ELEMENT_PRODUCT_SHOWER,
                "widthMm": _w(element),
                "heightMm": _h(element),
                "displayCode": element.get("displayCode") or element.get("display_code"),
                "svg": svg,
                "usedFallback": False,
            }
        except Exception:
            out = _placeholder_render(element)
            out["adapterId"] = self.adapter_id
            out["usedFallback"] = True
            return out

    def validate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        errors = []
        if _w(element) <= 0 or _h(element) <= 0:
            errors.append("widthMm and heightMm must be > 0")
        return {"ok": not errors, "errors": errors, "warnings": []}

    def get_property_schema(self) -> dict[str, Any]:
        return _base_schema_groups(
            _geom_fields(),
            {
                "id": "shower",
                "label": "Shower",
                "domain": "config",
                "fields": [
                    {"key": "shape", "label": "Shape", "type": "string", "domain": "config"},
                    {"key": "operation", "label": "Operation", "type": "string", "domain": "config"},
                    {"key": "glass", "label": "Glass", "type": "string", "domain": "config"},
                    {"key": "colour", "label": "Colour", "type": "string", "domain": "config"},
                ],
            },
        )

    def update_configuration(
        self, element: Mapping[str, Any], patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        cfg = self.load_configuration(element)
        for k, v in (patch or {}).items():
            if k in ("widthMm", "heightMm", "xMm", "yMm"):
                continue
            cfg[k] = v
        return cfg

    def calculate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        from WEOS.factory.shower_engine import compute_shower, ensure_shower_dims

        cfg = ensure_shower_dims(
            dict(config or self.load_configuration(element)),
            width=_w(element) or None,
            height=_h(element) or None,
        )
        return compute_shower(cfg)


class ThinSchematicAdapter:
    """Louvers / pergola / grill / surface — thin preview via special_schematics."""

    adapter_id = "schematic"

    def __init__(self, product_types: frozenset[str], kind: str) -> None:
        self._types = product_types
        self._kind = kind
        self.adapter_id = f"schematic_{kind}"

    def supports(self, product_type: str) -> bool:
        return str(product_type or "").strip().upper() in self._types

    def load_configuration(self, element: Mapping[str, Any]) -> dict[str, Any]:
        cfg = _cfg(element)
        cfg.setdefault("productType", _pt(element))
        return cfg

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        from WEOS.factory import special_schematics as ss

        cfg = dict(config or self.load_configuration(element))
        cfg["width"] = _w(element)
        cfg["height"] = _h(element)
        pt = _pt(element)
        try:
            if self._kind == "louver":
                svg = ss.louver_svg(cfg)
            elif self._kind == "pergola":
                svg = ss.pergola_svg(cfg)
            elif self._kind == "surface":
                svg = ss.surface_svg(cfg)
            else:
                # Grill / other: schematic-like box via surface with label
                cfg["displayName"] = pt.title()
                svg = ss.surface_svg(cfg)
            return {
                "kind": "schematic_svg",
                "adapterId": self.adapter_id,
                "elementId": element.get("elementId") or element.get("element_id"),
                "productType": pt,
                "widthMm": _w(element),
                "heightMm": _h(element),
                "displayCode": element.get("displayCode") or element.get("display_code"),
                "svg": svg,
                "usedFallback": False,
            }
        except Exception:
            out = _placeholder_render(element)
            out["adapterId"] = self.adapter_id
            out["usedFallback"] = True
            return out

    def validate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        errors = []
        if _w(element) <= 0 or _h(element) <= 0:
            errors.append("widthMm and heightMm must be > 0")
        return {"ok": not errors, "errors": errors, "warnings": []}

    def get_property_schema(self) -> dict[str, Any]:
        return _base_schema_groups(
            _geom_fields(),
            {
                "id": "schematic",
                "label": self._kind.title(),
                "domain": "config",
                "fields": [
                    {"key": "colour", "label": "Colour", "type": "string", "domain": "config"},
                    {"key": "notes", "label": "Notes", "type": "string", "domain": "config"},
                ],
            },
        )

    def update_configuration(
        self, element: Mapping[str, Any], patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        cfg = self.load_configuration(element)
        for k, v in (patch or {}).items():
            if k in ("widthMm", "heightMm", "xMm", "yMm"):
                continue
            cfg[k] = v
        return cfg

    def calculate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return None


class AssemblyPropertyAdapter:
    """Schema-only helper for assembly selection (B9)."""

    adapter_id = "assembly"

    def supports(self, product_type: str) -> bool:
        return str(product_type or "").strip().upper() == "ASSEMBLY"

    def load_configuration(self, element: Mapping[str, Any]) -> dict[str, Any]:
        return dict(element) if isinstance(element, Mapping) else {}

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return _placeholder_render(element)

    def validate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"ok": True, "errors": [], "warnings": []}

    def get_property_schema(self) -> dict[str, Any]:
        return _base_schema_groups(
            {
                "id": "assembly",
                "label": "Assembly",
                "domain": "assembly",
                "fields": [
                    {"key": "assemblyId", "label": "Assembly ID", "type": "readonly", "domain": "identity"},
                    {"key": "name", "label": "Name", "type": "string", "domain": "metadata"},
                    {"key": "floorId", "label": "Floor", "type": "string", "domain": "metadata"},
                    {"key": "locationId", "label": "Location", "type": "string", "domain": "metadata"},
                    {"key": "childCount", "label": "Child elements", "type": "readonly", "domain": "metadata"},
                    {"key": "connectionCount", "label": "Connections", "type": "readonly", "domain": "metadata"},
                ],
            }
        )

    def update_configuration(
        self, element: Mapping[str, Any], patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        return dict(patch or {})

    def calculate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return None


class ConnectionPropertyAdapter:
    adapter_id = "connection"

    def supports(self, product_type: str) -> bool:
        return str(product_type or "").strip().upper() == "CONNECTION"

    def load_configuration(self, element: Mapping[str, Any]) -> dict[str, Any]:
        return dict(element) if isinstance(element, Mapping) else {}

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return _placeholder_render(element)

    def validate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"ok": True, "errors": [], "warnings": []}

    def get_property_schema(self) -> dict[str, Any]:
        return _base_schema_groups(
            {
                "id": "connection",
                "label": "Connection",
                "domain": "connection",
                "fields": [
                    {"key": "connectionId", "label": "Connection ID", "type": "readonly", "domain": "identity"},
                    {"key": "elementAId", "label": "Element A", "type": "readonly", "domain": "identity"},
                    {"key": "elementBId", "label": "Element B", "type": "readonly", "domain": "identity"},
                    {"key": "sideA", "label": "Side A", "type": "string", "domain": "config"},
                    {"key": "sideB", "label": "Side B", "type": "string", "domain": "config"},
                    {"key": "connectionType", "label": "Type", "type": "string", "domain": "config"},
                    {"key": "parameters", "label": "Parameters", "type": "json", "domain": "config"},
                ],
            }
        )

    def update_configuration(
        self, element: Mapping[str, Any], patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        return dict(patch or {})

    def calculate(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return None


class ProductAdapterRegistry:
    """Registry-based dispatch — no giant product switch in the canvas host."""

    def __init__(self) -> None:
        self._adapters: list[Any] = []
        self._fallback = FallbackAdapter()

    def register(self, adapter: Any) -> None:
        self._adapters.append(adapter)

    def resolve(self, product_type: str) -> Any:
        key = str(product_type or "").strip().upper()
        if not key or key == "WINDOW":
            return self._fallback
        for ad in self._adapters:
            if ad.supports(key):
                return ad
        return self._fallback

    def supports(self, product_type: str) -> bool:
        ad = self.resolve(product_type)
        return ad is not self._fallback and ad.supports(product_type)

    def registered_product_types(self) -> list[str]:
        known = [
            ELEMENT_PRODUCT_SLIDING,
            ELEMENT_PRODUCT_FIXED,
            ELEMENT_PRODUCT_CASEMENT,
            ELEMENT_PRODUCT_DOOR,
            ELEMENT_PRODUCT_FOLD,
            ELEMENT_PRODUCT_VENTILATOR,
            ELEMENT_PRODUCT_RAILING,
            ELEMENT_PRODUCT_SHOWER,
            ELEMENT_PRODUCT_LOUVER,
            ELEMENT_PRODUCT_PERGOLA,
            ELEMENT_PRODUCT_GRILL,
            "SURFACE",
            "ASSEMBLY",
            "CONNECTION",
        ]
        return [pt for pt in known if self.resolve(pt) is not self._fallback]

    def render_preview(
        self, element: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        ad = self.resolve(_pt(element))
        cfg = config if config is not None else ad.load_configuration(element)
        out = ad.render_preview(element, cfg)
        out.setdefault("adapterId", getattr(ad, "adapter_id", "unknown"))
        out.setdefault("productType", _pt(element))
        out.setdefault("usedFallback", ad is self._fallback)
        return out

    def get_property_schema(self, product_type: str) -> dict[str, Any]:
        ad = self.resolve(product_type)
        schema = ad.get_property_schema()
        schema = dict(schema)
        schema["adapterId"] = getattr(ad, "adapter_id", "unknown")
        schema["productType"] = str(product_type or "").strip().upper()
        schema["usedFallback"] = ad is self._fallback
        return schema


def build_product_adapter_registry() -> ProductAdapterRegistry:
    reg = ProductAdapterRegistry()
    reg.register(WindowFamilyAdapter())
    reg.register(VentilatorAdapter())
    reg.register(RailingAdapter())
    reg.register(ShowerAdapter())
    reg.register(ThinSchematicAdapter(frozenset({ELEMENT_PRODUCT_LOUVER}), "louver"))
    reg.register(ThinSchematicAdapter(frozenset({ELEMENT_PRODUCT_PERGOLA}), "pergola"))
    reg.register(ThinSchematicAdapter(frozenset({ELEMENT_PRODUCT_GRILL}), "grill"))
    reg.register(ThinSchematicAdapter(SURFACE_TYPES, "surface"))
    reg.register(AssemblyPropertyAdapter())
    reg.register(ConnectionPropertyAdapter())
    return reg


DEFAULT_PRODUCT_REGISTRY = build_product_adapter_registry()


def resolve_adapter(product_type: str) -> Any:
    return DEFAULT_PRODUCT_REGISTRY.resolve(product_type)


def render_element_preview(
    element: Mapping[str, Any], config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return DEFAULT_PRODUCT_REGISTRY.render_preview(element, config)


def property_schema_for(product_type: str) -> dict[str, Any]:
    return DEFAULT_PRODUCT_REGISTRY.get_property_schema(product_type)


def canvas_adapter_fn(element: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Bridge for universal_canvas.AdapterRegistry — engine preview or supplied SVG."""
    ctx = context or {}
    # Prefer already-computed SVG from context when present (UI mirror path).
    geo = element.get("geometryPayload") if isinstance(element.get("geometryPayload"), Mapping) else {}
    svg = ctx.get("previewSvg") or element.get("previewSvg") or (geo or {}).get("previewSvg")
    if not svg and isinstance(ctx.get("previewByElementId"), Mapping):
        svg = ctx["previewByElementId"].get(element.get("elementId") or element.get("element_id"))
    if svg:
        return {
            "kind": "preview_svg",
            "adapterId": resolve_adapter(_pt(element)).adapter_id,
            "elementId": element.get("elementId") or element.get("element_id"),
            "productType": _pt(element),
            "widthMm": _w(element),
            "heightMm": _h(element),
            "displayCode": element.get("displayCode") or element.get("display_code"),
            "svg": svg,
            "usedFallback": False,
        }
    return render_element_preview(element)
