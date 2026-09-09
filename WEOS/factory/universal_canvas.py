"""Universal Engineering Canvas Host — WEOS V2 Batch 7.

Owns viewport/coords/zoom/pan/selection orchestration metadata and the
product-adapter registry. Does NOT compute product engineering geometry,
BOM, cost, GST, or PDF. Zoom is display-only and never mutates W/H.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

# Feature flag — default OFF for rollback to #livePreview path.
FLAG_ENV = "WEOS_UNIVERSAL_CANVAS"


def is_universal_canvas_enabled(override: str | bool | None = None) -> bool:
    if override is not None:
        if isinstance(override, bool):
            return override
        return str(override).strip().lower() in ("1", "true", "yes", "on")
    return (os.environ.get(FLAG_ENV) or "0").strip().lower() in ("1", "true", "yes", "on")


# Element drag-to-move is deferred until pose save path is wired in UI safely.
ELEMENT_DRAG_ENABLED = False


def world_to_viewport(
    x_mm: float,
    y_mm: float,
    *,
    pan_x: float,
    pan_y: float,
    zoom: float,
) -> tuple[float, float]:
    """Map world (engineering mm) → viewport CSS pixels. Zoom is display-only."""
    z = float(zoom) if zoom else 1.0
    return (float(x_mm) * z + float(pan_x), float(y_mm) * z + float(pan_y))


def viewport_to_world(
    vx: float,
    vy: float,
    *,
    pan_x: float,
    pan_y: float,
    zoom: float,
) -> tuple[float, float]:
    z = float(zoom) if zoom else 1.0
    if abs(z) < 1e-12:
        z = 1.0
    return ((float(vx) - float(pan_x)) / z, (float(vy) - float(pan_y)) / z)


def clamp_zoom(zoom: float, *, lo: float = 0.25, hi: float = 4.0) -> float:
    return max(lo, min(hi, round(float(zoom) * 100) / 100))


def fit_zoom(
    world_bounds: Mapping[str, float],
    viewport_w: float,
    viewport_h: float,
    *,
    padding: float = 40.0,
) -> float:
    """Compute zoom so world bounds fit in viewport (display-only)."""
    ww = max(1.0, float(world_bounds.get("width", 0) or 0))
    wh = max(1.0, float(world_bounds.get("height", 0) or 0))
    avail_w = max(1.0, float(viewport_w) - 2 * padding)
    avail_h = max(1.0, float(viewport_h) - 2 * padding)
    return clamp_zoom(min(avail_w / ww, avail_h / wh))


def placeholder_render(element: Mapping[str, Any]) -> dict[str, Any]:
    """Fallback box — ID, product type, W×H. No fake engineering SVG."""
    eid = str(element.get("elementId") or element.get("element_id") or "")
    pt = str(element.get("productType") or element.get("product_type") or "OTHER")
    w = float(element.get("widthMm") if element.get("widthMm") is not None else element.get("width_mm") or 0)
    h = float(element.get("heightMm") if element.get("heightMm") is not None else element.get("height_mm") or 0)
    code = str(element.get("displayCode") or element.get("display_code") or eid or "?")
    label = f"{code} | {pt} | {int(w) if w == int(w) else w}×{int(h) if h == int(h) else h}"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {max(w, 1)} {max(h, 1)}" '
        f'data-weos-placeholder="1" data-element-id="{eid}">'
        f'<rect x="0" y="0" width="{max(w, 1)}" height="{max(h, 1)}" '
        f'fill="#e8eef4" stroke="#4a5a6a" stroke-width="8"/>'
        f'<text x="{max(w, 1) / 2}" y="{max(h, 1) / 2}" text-anchor="middle" '
        f'dominant-baseline="middle" font-family="Segoe UI,sans-serif" '
        f'font-size="{max(48, min(w, h) / 8)}" fill="#334455">{code}</text>'
        f"</svg>"
    )
    return {
        "kind": "placeholder",
        "elementId": eid,
        "productType": pt,
        "widthMm": w,
        "heightMm": h,
        "displayCode": code,
        "label": label,
        "svg": svg,
    }


AdapterFn = Callable[[Mapping[str, Any], Mapping[str, Any] | None], dict[str, Any]]


class AdapterRegistry:
    """Product-type → render adapter. Canvas never embeds giant product calc."""

    def __init__(self) -> None:
        self._adapters: dict[str, AdapterFn] = {}
        self._fallback: AdapterFn = lambda el, _ctx=None: placeholder_render(el)

    def register(self, product_type: str, fn: AdapterFn) -> None:
        key = str(product_type or "").strip().upper()
        if not key:
            raise ValueError("product_type required for adapter register")
        self._adapters[key] = fn

    def lookup(self, product_type: str) -> AdapterFn | None:
        key = str(product_type or "").strip().upper()
        return self._adapters.get(key)

    def resolve(self, product_type: str) -> AdapterFn:
        return self.lookup(product_type) or self._fallback

    def render(
        self,
        element: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        pt = str(element.get("productType") or element.get("product_type") or "")
        fn = self.resolve(pt)
        out = fn(element, context)
        if not isinstance(out, dict):
            out = placeholder_render(element)
        out.setdefault("elementId", element.get("elementId") or element.get("element_id"))
        out.setdefault("productType", pt)
        out.setdefault("usedFallback", self.lookup(pt) is None)
        return out

    def registered_types(self) -> list[str]:
        return sorted(self._adapters.keys())


def _preview_svg_adapter(element: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Use existing preview SVG when present — no engine rewrite."""
    ctx = context or {}
    geo = element.get("geometryPayload") if isinstance(element.get("geometryPayload"), Mapping) else {}
    svg = ctx.get("previewSvg") or element.get("previewSvg") or geo.get("previewSvg")
    if not svg and isinstance(ctx.get("previewByElementId"), Mapping):
        svg = ctx["previewByElementId"].get(element.get("elementId") or element.get("element_id"))
    if svg:
        return {
            "kind": "preview_svg",
            "elementId": element.get("elementId") or element.get("element_id"),
            "productType": element.get("productType") or element.get("product_type"),
            "widthMm": element.get("widthMm") if element.get("widthMm") is not None else element.get("width_mm"),
            "heightMm": element.get("heightMm") if element.get("heightMm") is not None else element.get("height_mm"),
            "displayCode": element.get("displayCode") or element.get("display_code"),
            "svg": svg,
            "usedFallback": False,
        }
    return placeholder_render(element)


def build_default_registry() -> AdapterRegistry:
    """B8: registry dispatches to product engine adapters (still ONE canvas host)."""

    def _engine_or_preview(
        element: Mapping[str, Any], context: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        # Lazy import — product_adapters imports placeholder_render from this module.
        from WEOS.factory.product_adapters import canvas_adapter_fn

        return canvas_adapter_fn(element, context)

    reg = AdapterRegistry()
    for pt in (
        "SLIDING_WINDOW",
        "CASEMENT_WINDOW",
        "FIXED_WINDOW",
        "FOLD_WINDOW",
        "DOOR",
        "VENTILATOR",
        "SHOWER_PARTITION",
        "RAILING",
        "GRILL",
        "PERGOLA",
        "LOUVER",
        "SURFACE",
    ):
        reg.register(pt, _engine_or_preview)
    return reg


DEFAULT_REGISTRY = build_default_registry()


def flatten_scene_elements(scene: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Floor→Location→Assembly→Elements (+ unlocated) into a flat canvas list."""
    out: list[dict[str, Any]] = []

    def _pack(el: Mapping[str, Any], *, floor: Mapping[str, Any] | None, location: Mapping[str, Any] | None, assembly: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "elementId": el.get("elementId"),
            "displayCode": el.get("displayCode"),
            "productType": el.get("productType"),
            "productId": el.get("productId"),
            "widthMm": float(el.get("widthMm") or 0),
            "heightMm": float(el.get("heightMm") or 0),
            "xMm": float(el.get("xMm") or 0),
            "yMm": float(el.get("yMm") or 0),
            "orientation": el.get("orientation"),
            "assemblyId": assembly.get("assemblyId"),
            "assemblyDisplayCode": assembly.get("displayCode"),
            "floorId": (floor or {}).get("floorId"),
            "floorCode": (floor or {}).get("code"),
            "floorName": (floor or {}).get("name"),
            "locationId": (location or {}).get("locationId") or assembly.get("locationId"),
            "locationCode": (location or {}).get("code"),
            "locationName": (location or {}).get("name"),
            "designDocumentId": el.get("designDocumentId") or scene.get("designDocumentId"),
            "projectId": el.get("projectId") or scene.get("projectId"),
            "geometryPayload": el.get("geometryPayload"),
            "configPayload": el.get("configPayload"),
            "status": el.get("status"),
        }

    for fl in scene.get("floors") or []:
        if not isinstance(fl, Mapping):
            continue
        for loc in fl.get("locations") or []:
            if not isinstance(loc, Mapping):
                continue
            for asm in loc.get("assemblies") or []:
                if not isinstance(asm, Mapping):
                    continue
                for el in asm.get("elements") or []:
                    if isinstance(el, Mapping):
                        out.append(_pack(el, floor=fl, location=loc, assembly=asm))

    for asm in scene.get("unlocatedAssemblies") or []:
        if not isinstance(asm, Mapping):
            continue
        for el in asm.get("elements") or []:
            if isinstance(el, Mapping):
                out.append(_pack(el, floor=None, location=None, assembly=asm))

    return out


def flatten_scene_connections(scene: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Explicit connections only — never infer from touching geometry."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _take(asm: Mapping[str, Any]) -> None:
        for c in asm.get("connections") or []:
            if not isinstance(c, Mapping):
                continue
            cid = str(c.get("connectionId") or "")
            if cid and cid in seen:
                continue
            if cid:
                seen.add(cid)
            out.append(
                {
                    "connectionId": c.get("connectionId"),
                    "assemblyId": c.get("assemblyId") or asm.get("assemblyId"),
                    "elementAId": c.get("elementAId"),
                    "elementBId": c.get("elementBId"),
                    "connectionType": c.get("connectionType"),
                    "sideA": c.get("sideA"),
                    "sideB": c.get("sideB"),
                    "parameters": c.get("parameters"),
                }
            )

    for fl in scene.get("floors") or []:
        if not isinstance(fl, Mapping):
            continue
        for loc in fl.get("locations") or []:
            if not isinstance(loc, Mapping):
                continue
            for asm in loc.get("assemblies") or []:
                if isinstance(asm, Mapping):
                    _take(asm)
    for asm in scene.get("unlocatedAssemblies") or []:
        if isinstance(asm, Mapping):
            _take(asm)
    return out


def world_bounds_for_elements(elements: list[Mapping[str, Any]]) -> dict[str, float]:
    if not elements:
        return {"minX": 0.0, "minY": 0.0, "maxX": 1000.0, "maxY": 1000.0, "width": 1000.0, "height": 1000.0}
    min_x = min(float(e.get("xMm") or 0) for e in elements)
    min_y = min(float(e.get("yMm") or 0) for e in elements)
    max_x = max(float(e.get("xMm") or 0) + float(e.get("widthMm") or 0) for e in elements)
    max_y = max(float(e.get("yMm") or 0) + float(e.get("heightMm") or 0) for e in elements)
    return {
        "minX": min_x,
        "minY": min_y,
        "maxX": max_x,
        "maxY": max_y,
        "width": max(1.0, max_x - min_x),
        "height": max(1.0, max_y - min_y),
    }


def build_canvas_view_model(
    scene: Mapping[str, Any],
    *,
    registry: AdapterRegistry | None = None,
    preview_by_element_id: Mapping[str, str] | None = None,
    selected_element_ids: list[str] | None = None,
    floor_id: str | None = None,
    location_id: str | None = None,
) -> dict[str, Any]:
    """Orchestration read model for the Universal Canvas Host."""
    reg = registry or DEFAULT_REGISTRY
    elements = flatten_scene_elements(scene)
    connections = flatten_scene_connections(scene)

    if floor_id:
        elements = [e for e in elements if e.get("floorId") == floor_id]
    if location_id:
        elements = [e for e in elements if e.get("locationId") == location_id]

    ctx = {"previewByElementId": dict(preview_by_element_id or {})}
    rendered = []
    for el in elements:
        r = reg.render(el, ctx)
        rendered.append(
            {
                **el,
                "render": r,
                "label": el.get("displayCode") or el.get("elementId"),
            }
        )

    sel = [str(x) for x in (selected_element_ids or []) if x]
    primary = sel[0] if sel else None
    primary_el = next((e for e in rendered if e.get("elementId") == primary), None)

    floors = []
    for fl in scene.get("floors") or []:
        if not isinstance(fl, Mapping):
            continue
        locs = []
        for loc in fl.get("locations") or []:
            if isinstance(loc, Mapping):
                locs.append(
                    {
                        "locationId": loc.get("locationId"),
                        "code": loc.get("code"),
                        "name": loc.get("name"),
                    }
                )
        floors.append(
            {
                "floorId": fl.get("floorId"),
                "code": fl.get("code"),
                "name": fl.get("name"),
                "levelIndex": fl.get("levelIndex"),
                "locations": locs,
            }
        )

    return {
        "host": "UniversalCanvas",
        "flag": FLAG_ENV,
        "enabled": is_universal_canvas_enabled(),
        "elementDragEnabled": ELEMENT_DRAG_ENABLED,
        "designDocumentId": scene.get("designDocumentId"),
        "projectId": scene.get("projectId"),
        "companyGst": scene.get("companyGst"),
        "floors": floors,
        "filterFloorId": floor_id,
        "filterLocationId": location_id,
        "elements": rendered,
        "connections": connections,
        "bounds": world_bounds_for_elements(rendered),
        "selection": {
            "mode": "single",
            "selectedElementIds": sel,
            "primaryElementId": primary,
            "multiSelectReady": True,
        },
        "selected": (
            {
                "elementId": primary_el.get("elementId"),
                "productType": primary_el.get("productType"),
                "widthMm": primary_el.get("widthMm"),
                "heightMm": primary_el.get("heightMm"),
                "displayCode": primary_el.get("displayCode"),
                "assemblyId": primary_el.get("assemblyId"),
                "floorId": primary_el.get("floorId"),
                "locationId": primary_el.get("locationId"),
            }
            if primary_el
            else None
        ),
        "adapters": reg.registered_types(),
    }


def update_element_pose(
    element_id: str,
    *,
    company_gst: str,
    x_mm: float | None = None,
    y_mm: float | None = None,
) -> dict[str, Any]:
    """Durable pose update via SQL DesignElement — never localStorage SoT.

    Width/height are intentionally untouched (engineering dims stay engine-owned).
    """
    from WEOS.db.engine import db_available, init_db, session_scope
    from WEOS.db.models import DesignElement
    from WEOS.factory.canonical_customer import _norm_company_gst

    if not db_available():
        raise RuntimeError("Database unavailable for canvas pose update")
    init_db()
    gst = _norm_company_gst(company_gst)
    eid = str(element_id).strip()
    with session_scope() as s:
        row = s.get(DesignElement, eid)
        if row is None or _norm_company_gst(row.company_gst) != gst:
            raise PermissionError("element not found for company")
        if x_mm is not None:
            row.x_mm = float(x_mm)
        if y_mm is not None:
            row.y_mm = float(y_mm)
        s.flush()
        return row.to_dict()
