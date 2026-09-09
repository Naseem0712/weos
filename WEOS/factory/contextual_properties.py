"""Contextual property panel — WEOS V2 Batch 9.

ONE panel synced to selection by stable IDs (element/assembly/connection).
Geometry (W/H/X/Y) vs ProductConfiguration (series/glass/hardware/colour) stay separate.
Does not rewrite BOM/cost/master/quote/ledger. Presets remain adapter-boundary only.
"""

from __future__ import annotations

from typing import Any, Mapping

from WEOS.factory import product_adapters as pa


SELECTION_KINDS = frozenset({"none", "element", "assembly", "connection"})


def empty_panel_guidance() -> dict[str, Any]:
    return {
        "kind": "none",
        "title": "Engineering Canvas",
        "guidance": "Select an element, assembly, or connection to edit properties.",
        "schema": {"version": 1, "groups": [], "adapterId": None, "productType": None},
        "values": {},
        "selection": {"kind": "none", "elementId": None, "assemblyId": None, "connectionId": None},
    }


def _field_keys(schema: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for g in schema.get("groups") or []:
        if not isinstance(g, Mapping):
            continue
        for f in g.get("fields") or []:
            if isinstance(f, Mapping) and f.get("key"):
                keys.add(str(f["key"]))
    return keys


def schemas_cross_pollute(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """True if active config keys from A appear as railing-only keys in B (smoke helper)."""
    rail_only = {"mountType", "handrail", "bottomRail", "stairSteps", "brackets", "studs", "anchors"}
    window_only = {"sectionSeries", "trackCount", "glassShutters", "handle"}
    a_keys = _field_keys(a)
    b_keys = _field_keys(b)
    # Window schema must not expose railing-only active fields
    if a.get("productType") in pa.WINDOW_FAMILY or a.get("adapterId") == "window_family":
        if a_keys & rail_only:
            return True
    if b.get("productType") in pa.WINDOW_FAMILY or b.get("adapterId") == "window_family":
        if b_keys & rail_only:
            return True
    # Pergola must not leak window / railing controls
    if a.get("productType") == "PERGOLA" or a.get("adapterId") == "pergola":
        if a_keys & (rail_only | window_only):
            return True
    if b.get("productType") == "PERGOLA" or b.get("adapterId") == "pergola":
        if b_keys & (rail_only | window_only):
            return True
    return False


def panel_for_element(element: Mapping[str, Any]) -> dict[str, Any]:
    pt = str(element.get("productType") or "").strip().upper()
    schema = pa.property_schema_for(pt)
    ad = pa.resolve_adapter(pt)
    cfg = ad.load_configuration(element)
    if pt == "PERGOLA" or getattr(ad, "adapter_id", "") == "pergola":
        from WEOS.factory import pergola_model as pm

        values = {
            "elementId": element.get("elementId"),
            "assemblyId": element.get("assemblyId"),
            "productType": pt,
            "orientation": element.get("orientation"),
            **pm.panel_values(element, cfg),
        }
        return {
            "kind": "element",
            "title": f"{element.get('displayCode') or element.get('elementId')} · {pt}",
            "schema": schema,
            "values": values,
            "selection": {
                "kind": "element",
                "elementId": element.get("elementId"),
                "assemblyId": element.get("assemblyId"),
                "connectionId": None,
                "productType": pt,
            },
            "geometryKeys": ["widthMm", "depthMm", "xMm", "yMm"],
            "configDomain": "configPayload",
        }
    values = {
        "elementId": element.get("elementId"),
        "assemblyId": element.get("assemblyId"),
        "productType": pt,
        "widthMm": element.get("widthMm"),
        "heightMm": element.get("heightMm"),
        "xMm": element.get("xMm"),
        "yMm": element.get("yMm"),
        "orientation": element.get("orientation"),
        **{k: v for k, v in cfg.items() if k not in ("widthMm", "heightMm", "xMm", "yMm")},
    }
    return {
        "kind": "element",
        "title": f"{element.get('displayCode') or element.get('elementId')} · {pt}",
        "schema": schema,
        "values": values,
        "selection": {
            "kind": "element",
            "elementId": element.get("elementId"),
            "assemblyId": element.get("assemblyId"),
            "connectionId": None,
            "productType": pt,
        },
        "geometryKeys": ["widthMm", "heightMm", "xMm", "yMm"],
        "configDomain": "configPayload",
    }


def panel_for_assembly(assembly: Mapping[str, Any], *, child_count: int = 0, connection_count: int = 0) -> dict[str, Any]:
    schema = pa.property_schema_for("ASSEMBLY")
    values = {
        "assemblyId": assembly.get("assemblyId"),
        "name": assembly.get("name"),
        "floorId": assembly.get("floorId"),
        "locationId": assembly.get("locationId"),
        "childCount": child_count,
        "connectionCount": connection_count,
        "displayCode": assembly.get("displayCode"),
        "bounds": assembly.get("bounds"),
    }
    return {
        "kind": "assembly",
        "title": f"{assembly.get('displayCode') or assembly.get('assemblyId')} · Assembly",
        "schema": schema,
        "values": values,
        "selection": {
            "kind": "assembly",
            "elementId": None,
            "assemblyId": assembly.get("assemblyId"),
            "connectionId": None,
        },
    }


def panel_for_connection(connection: Mapping[str, Any]) -> dict[str, Any]:
    schema = pa.property_schema_for("CONNECTION")
    values = {
        "connectionId": connection.get("connectionId"),
        "elementAId": connection.get("elementAId"),
        "elementBId": connection.get("elementBId"),
        "sideA": connection.get("sideA"),
        "sideB": connection.get("sideB"),
        "connectionType": connection.get("connectionType"),
        "parameters": connection.get("parameters"),
        "assemblyId": connection.get("assemblyId"),
    }
    return {
        "kind": "connection",
        "title": f"{connection.get('connectionId')} · Connection",
        "schema": schema,
        "values": values,
        "selection": {
            "kind": "connection",
            "elementId": None,
            "assemblyId": connection.get("assemblyId"),
            "connectionId": connection.get("connectionId"),
        },
    }


def split_geometry_and_config(patch: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate geometry fields from ProductConfiguration patch."""
    patch = patch or {}
    geom: dict[str, Any] = {}
    cfg: dict[str, Any] = {}
    geom_keys = {"widthMm", "heightMm", "depthMm", "xMm", "yMm", "orientation", "sillHeightMm"}
    for k, v in patch.items():
        if k in geom_keys:
            geom[k] = v
        elif k in ("elementId", "assemblyId", "connectionId", "productType", "kind"):
            continue
        else:
            cfg[k] = v
    # Pergola plan depth maps to element heightMm (canvas footprint).
    if "depthMm" in geom and "heightMm" not in geom:
        geom["heightMm"] = geom["depthMm"]
    return geom, cfg


def apply_element_property_update(
    element_id: str,
    *,
    company_gst: str,
    patch: Mapping[str, Any],
) -> dict[str, Any]:
    """Panel → geometry/config → SQL save. Raises on failure (caller maps to HTTP)."""
    from WEOS.factory import design_scene as ds

    existing = ds.get_element(element_id, company_gst=company_gst)
    if not existing:
        raise PermissionError("element not found for company")
    geom, cfg = split_geometry_and_config(patch)
    ad = pa.resolve_adapter(existing.get("productType") or "")
    # Keep depthMm inside pergola config as well as footprint heightMm.
    if str(existing.get("productType") or "").upper() == "PERGOLA" and "depthMm" in geom:
        cfg = dict(cfg or {})
        cfg.setdefault("depthMm", geom["depthMm"])
    cfg_out = ad.update_configuration(existing, cfg) if cfg else None
    # Pergola saves a full normalized ProductConfiguration — replace, don't shallow-merge leftovers.
    merge = True
    if str(existing.get("productType") or "").upper() == "PERGOLA" and cfg_out is not None:
        merge = False
    updated = ds.update_element(
        element_id,
        company_gst=company_gst,
        width_mm=geom.get("widthMm"),
        height_mm=geom.get("heightMm"),
        x_mm=geom.get("xMm"),
        y_mm=geom.get("yMm"),
        orientation=geom.get("orientation"),
        sill_height_mm=geom.get("sillHeightMm"),
        config_payload=cfg_out,
        merge_config=merge,
    )
    preview = pa.render_element_preview(updated)
    return {
        "ok": True,
        "persisted": True,
        "element": updated,
        "preview": preview,
        "selection": {
            "kind": "element",
            "elementId": updated.get("elementId"),
            "assemblyId": updated.get("assemblyId"),
            "productType": updated.get("productType"),
        },
    }
