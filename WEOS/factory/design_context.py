"""Active Design Context — WEOS V2 Canvas D0.

ONE product context owner for Universal Canvas:
  selectedProductType → registry → schema → renderer → toolset

Never collapse unknown / WINDOW to Window tools. Element-scoped config;
atomic product switch clears prior adapter/schema/toolset/renderer revision.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from WEOS.factory import product_adapters as pa
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

# Product-specific toolsets — never a generic "windowTools" catch-all.
TOOLSET_SLIDING = "sliding"
TOOLSET_CASEMENT = "casement"
TOOLSET_FIXED = "fixed"
TOOLSET_FOLD = "fold"
TOOLSET_DOOR = "door"
TOOLSET_VENTILATOR = "ventilator"
TOOLSET_SHOWER = "shower"
TOOLSET_LOUVER = "louver"
TOOLSET_ACP = "acp"
TOOLSET_SURFACE = "surface"
TOOLSET_RAILING = "railing"
TOOLSET_PERGOLA = "pergola"
TOOLSET_GRILL = "grill"
TOOLSET_UNSUPPORTED = "unsupported"

UNSUPPORTED_MESSAGE = (
    "This product type is not supported on Universal Canvas yet. "
    "Window tools are not shown for unsupported products."
)

TOOLSET_BY_PRODUCT: dict[str, str] = {
    ELEMENT_PRODUCT_SLIDING: TOOLSET_SLIDING,
    ELEMENT_PRODUCT_CASEMENT: TOOLSET_CASEMENT,
    ELEMENT_PRODUCT_FIXED: TOOLSET_FIXED,
    ELEMENT_PRODUCT_FOLD: TOOLSET_FOLD,
    ELEMENT_PRODUCT_DOOR: TOOLSET_DOOR,
    ELEMENT_PRODUCT_VENTILATOR: TOOLSET_VENTILATOR,
    ELEMENT_PRODUCT_SHOWER: TOOLSET_SHOWER,
    ELEMENT_PRODUCT_LOUVER: TOOLSET_LOUVER,
    ELEMENT_PRODUCT_RAILING: TOOLSET_RAILING,
    ELEMENT_PRODUCT_PERGOLA: TOOLSET_PERGOLA,
    "GRILL": TOOLSET_GRILL,
    "SURFACE": TOOLSET_SURFACE,
    "ACP": TOOLSET_ACP,
    "HPL": TOOLSET_SURFACE,
    "FLUTED": TOOLSET_SURFACE,
    "PERFORATED": TOOLSET_SURFACE,
}

# Catalogue / legacy world labels → canonical element product types (when unambiguous).
WORLD_TO_PRODUCT: dict[str, str] = {
    "sliding": ELEMENT_PRODUCT_SLIDING,
    "casement": ELEMENT_PRODUCT_CASEMENT,
    "fixed": ELEMENT_PRODUCT_FIXED,
    "fold": ELEMENT_PRODUCT_FOLD,
    "bifold": ELEMENT_PRODUCT_FOLD,
    "door": ELEMENT_PRODUCT_DOOR,
    "ventilator": ELEMENT_PRODUCT_VENTILATOR,
    "shower": ELEMENT_PRODUCT_SHOWER,
    "louver": ELEMENT_PRODUCT_LOUVER,
    "railing": ELEMENT_PRODUCT_RAILING,
    "staircase_railing": ELEMENT_PRODUCT_RAILING,
    "pergola": ELEMENT_PRODUCT_PERGOLA,
    "surface": "SURFACE",
    "acp": "ACP",
}


def normalize_product_type(raw: Any) -> str:
    """Uppercase exact type. Empty / WINDOW stay empty — never rewritten to SLIDING_WINDOW."""
    key = str(raw or "").strip().upper()
    if not key or key == "WINDOW":
        return ""
    return key


def adapter_id_for_context(adapter: Any) -> str:
    """Public adapter id for ActiveDesignContext — schematic_louver → louver."""
    aid = str(getattr(adapter, "adapter_id", "fallback") or "fallback")
    if aid.startswith("schematic_"):
        return aid[len("schematic_") :]
    return aid


def toolset_for(product_type: str) -> str:
    pt = normalize_product_type(product_type)
    if not pt:
        return TOOLSET_UNSUPPORTED
    return TOOLSET_BY_PRODUCT.get(pt, TOOLSET_UNSUPPORTED)


def is_supported(product_type: str) -> bool:
    pt = normalize_product_type(product_type)
    if not pt:
        return False
    ad = pa.resolve_adapter(pt)
    return getattr(ad, "adapter_id", "") != "fallback"


def empty_context(*, reason: str | None = None) -> dict[str, Any]:
    return {
        "selectedProductType": None,
        "elementId": None,
        "assemblyId": None,
        "adapterId": "fallback",
        "propertySchema": {
            "version": 1,
            "groups": [],
            "adapterId": "fallback",
            "productType": None,
            "usedFallback": True,
            "toolset": TOOLSET_UNSUPPORTED,
            "guidance": reason or UNSUPPORTED_MESSAGE,
        },
        "toolset": TOOLSET_UNSUPPORTED,
        "renderer": "placeholder",
        "renderRevision": 0,
        "supported": False,
        "guidance": reason or UNSUPPORTED_MESSAGE,
        "configScope": "none",
        "source": "none",
        "supportsFrameGrid": False,
        "supportsCellSubdivision": False,
        "structureCapabilities": {
            "supportsFrameGrid": False,
            "supportsCellSubdivision": False,
        },
    }


def _specialize_window_schema(schema: dict[str, Any], product_type: str) -> dict[str, Any]:
    """Exact window-family fields per product — Casement ≠ Sliding tool surface."""
    out = deepcopy(schema)
    pt = normalize_product_type(product_type)
    groups = out.get("groups") or []
    for g in groups:
        if not isinstance(g, dict) or g.get("id") != "series":
            continue
        fields = list(g.get("fields") or [])
        by_key = {str(f.get("key")): f for f in fields if isinstance(f, dict)}
        if pt == ELEMENT_PRODUCT_CASEMENT:
            # Casement: no track/opening-side sliding controls; add sash fields.
            fields = [f for f in fields if str(f.get("key")) not in ("trackCount", "opening")]
            if "casementPanels" not in by_key:
                fields.append(
                    {
                        "key": "casementPanels",
                        "label": "Casement panels",
                        "type": "json",
                        "domain": "config",
                    }
                )
            if "sashOverlapMm" not in by_key:
                fields.append(
                    {
                        "key": "sashOverlapMm",
                        "label": "Sash overlap (mm)",
                        "type": "number",
                        "domain": "config",
                    }
                )
            if "mullionGapMm" not in by_key:
                fields.append(
                    {
                        "key": "mullionGapMm",
                        "label": "Mullion gap (mm)",
                        "type": "number",
                        "domain": "config",
                    }
                )
        elif pt == ELEMENT_PRODUCT_SLIDING:
            # Sliding keeps track / opening / shutter count — strip casement-only if present.
            fields = [
                f
                for f in fields
                if str(f.get("key")) not in ("casementPanels", "sashOverlapMm", "mullionGapMm")
            ]
        elif pt == ELEMENT_PRODUCT_FIXED:
            fields = [
                f
                for f in fields
                if str(f.get("key"))
                not in ("trackCount", "opening", "casementPanels", "sashOverlapMm", "mullionGapMm")
            ]
            if "grid" not in by_key:
                fields.append({"key": "grid", "label": "Grid", "type": "json", "domain": "config"})
        elif pt == ELEMENT_PRODUCT_FOLD:
            fields = [f for f in fields if str(f.get("key")) not in ("trackCount", "casementPanels")]
            if "foldLeft" not in by_key:
                fields.append(
                    {"key": "foldLeft", "label": "Fold left", "type": "number", "domain": "config"}
                )
            if "foldRight" not in by_key:
                fields.append(
                    {"key": "foldRight", "label": "Fold right", "type": "number", "domain": "config"}
                )
        g["fields"] = fields
    out["toolset"] = toolset_for(pt)
    out["productType"] = pt
    return out


def property_schema_for_context(product_type: str) -> dict[str, Any]:
    pt = normalize_product_type(product_type)
    if not pt:
        ad = pa.FallbackAdapter()
        schema = dict(ad.get_property_schema())
        schema["adapterId"] = "fallback"
        schema["productType"] = None
        schema["usedFallback"] = True
        schema["toolset"] = TOOLSET_UNSUPPORTED
        schema["guidance"] = UNSUPPORTED_MESSAGE
        from WEOS.factory.canvas_preview import enrich_schema

        return enrich_schema(schema)
    ad = pa.resolve_adapter(pt)
    adapter_id = adapter_id_for_context(ad)
    schema = dict(ad.get_property_schema())
    schema["adapterId"] = adapter_id
    schema["productType"] = pt
    schema["usedFallback"] = adapter_id == "fallback"
    schema["toolset"] = toolset_for(pt)
    if adapter_id == "fallback":
        schema["guidance"] = UNSUPPORTED_MESSAGE
        # Ensure fallback does not expose window-only keys as active tool chrome.
        rail_or_window = {"sectionSeries", "trackCount", "glassShutters", "handle", "mountType"}
        for g in schema.get("groups") or []:
            if not isinstance(g, dict):
                continue
            g["fields"] = [
                f
                for f in (g.get("fields") or [])
                if not (isinstance(f, dict) and str(f.get("key")) in rail_or_window)
            ]
    elif adapter_id == "window_family":
        schema = _specialize_window_schema(schema, pt)
    from WEOS.factory.canvas_preview import enrich_schema

    return enrich_schema(schema)


def property_schema_for(product_type: str) -> dict[str, Any]:
    """Public schema entry used by panel/API — D0-aware specialization."""
    return property_schema_for_context(product_type)


def resolve_active_design_context(
    *,
    product_type: str | None = None,
    element_id: str | None = None,
    assembly_id: str | None = None,
    config_payload: Mapping[str, Any] | None = None,
    source: str = "element",
    render_revision: int = 0,
) -> dict[str, Any]:
    """Build one ActiveDesignContext snapshot. Never defaults unsupported → Window."""
    pt = normalize_product_type(product_type)
    if not pt:
        ctx = empty_context(reason=UNSUPPORTED_MESSAGE)
        ctx["elementId"] = element_id
        ctx["assemblyId"] = assembly_id
        ctx["renderRevision"] = int(render_revision or 0)
        ctx["source"] = source
        return ctx

    ad = pa.resolve_adapter(pt)
    adapter_id = adapter_id_for_context(ad)
    supported = adapter_id != "fallback"
    schema = property_schema_for_context(pt)
    toolset = toolset_for(pt) if supported else TOOLSET_UNSUPPORTED
    renderer = "engine" if supported else "placeholder"
    if adapter_id in ("louver", "grill", "surface", "pergola"):
        renderer = "schematic"
    guidance = None if supported else UNSUPPORTED_MESSAGE

    # Element-scoped config — never a shared global currentWindowConfig.
    config_scope = f"element:{element_id}" if element_id else f"draft:{pt}"
    scoped_config = dict(config_payload) if isinstance(config_payload, Mapping) else {}

    from WEOS.factory import member_grid as mg

    caps = mg.product_capabilities(pt, declared=scoped_config.get("capabilities") if isinstance(scoped_config, dict) else None)

    return {
        "selectedProductType": pt,
        "elementId": element_id,
        "assemblyId": assembly_id,
        "adapterId": adapter_id,
        "propertySchema": schema,
        "toolset": toolset,
        "renderer": renderer,
        "renderRevision": int(render_revision or 0),
        "supported": supported,
        "guidance": guidance,
        "configScope": config_scope,
        "configPayload": scoped_config,
        "source": source,
        "supportsFrameGrid": caps["supportsFrameGrid"],
        "supportsCellSubdivision": caps["supportsCellSubdivision"],
        "structureCapabilities": caps,
    }


def switch_product_context(
    previous: Mapping[str, Any] | None,
    *,
    product_type: str | None,
    element_id: str | None = None,
    assembly_id: str | None = None,
    config_payload: Mapping[str, Any] | None = None,
    source: str = "switch",
) -> dict[str, Any]:
    """Atomic product switch: bump revision, discard prior toolset/schema/config scope."""
    prev_rev = int((previous or {}).get("renderRevision") or 0)
    # Do not inherit previous config when product type changes.
    prev_pt = normalize_product_type((previous or {}).get("selectedProductType"))
    next_pt = normalize_product_type(product_type)
    cfg = config_payload
    if prev_pt and next_pt and prev_pt != next_pt:
        cfg = None if source in ("catalogue", "switch", "product-change") else config_payload
        if element_id and (previous or {}).get("elementId") and element_id != (previous or {}).get(
            "elementId"
        ):
            cfg = config_payload
        elif not element_id:
            cfg = None
    ctx = resolve_active_design_context(
        product_type=next_pt or None,
        element_id=element_id,
        assembly_id=assembly_id,
        config_payload=cfg,
        source=source,
        render_revision=prev_rev + 1,
    )
    ctx["previousProductType"] = prev_pt or None
    ctx["clearedPriorContext"] = True
    return ctx


def context_from_element(element: Mapping[str, Any], *, render_revision: int = 0) -> dict[str, Any]:
    el = element or {}
    pt = el.get("productType") or el.get("product_type")
    cfg = el.get("configPayload") if el.get("configPayload") is not None else el.get("config_payload")
    return resolve_active_design_context(
        product_type=str(pt) if pt else None,
        element_id=el.get("elementId") or el.get("element_id"),
        assembly_id=el.get("assemblyId") or el.get("assembly_id"),
        config_payload=cfg if isinstance(cfg, Mapping) else None,
        source="element",
        render_revision=render_revision,
    )


def catalogue_product_type(meta: Mapping[str, Any] | None, world: str | None = None) -> str:
    """Map catalogue / world selection to canonical type — no silent WINDOW."""
    if meta:
        raw = (
            meta.get("elementProductType")
            or meta.get("canvasProductType")
            or meta.get("productType")
            or meta.get("type")
        )
        pt = normalize_product_type(raw)
        if pt and pt in TOOLSET_BY_PRODUCT:
            return pt
        # Heuristic from catalogue bits (same vocabulary as UI worlds).
        blob = " ".join(
            str(x or "")
            for x in (
                meta.get("productType"),
                meta.get("id"),
                meta.get("category"),
                meta.get("displayName"),
                meta.get("system"),
            )
        ).lower()
        if "pergola" in blob:
            return ELEMENT_PRODUCT_PERGOLA
        if "ventilat" in blob:
            return ELEMENT_PRODUCT_VENTILATOR
        if "shower" in blob:
            return ELEMENT_PRODUCT_SHOWER
        if "louver" in blob or "louvre" in blob:
            return ELEMENT_PRODUCT_LOUVER
        if "rail" in blob:
            return ELEMENT_PRODUCT_RAILING
        if "casement" in blob or "openable" in blob:
            return ELEMENT_PRODUCT_CASEMENT
        if "fold" in blob or "bifold" in blob:
            return ELEMENT_PRODUCT_FOLD
        if blob == "acp" or blob.startswith("acp ") or " acp" in f" {blob} " or "/acp" in blob:
            return "ACP"
        if any(x in blob for x in ("hpl", "fluted", "perforated", "cladding", "facade")):
            return "SURFACE"
        if "fixed" in blob or "grid" in blob:
            return ELEMENT_PRODUCT_FIXED
        if "door" in blob and "window" not in blob:
            return ELEMENT_PRODUCT_DOOR
        if any(x in blob for x in ("slid", "tele", "sync", "window")):
            return ELEMENT_PRODUCT_SLIDING
    w = str(world or "").strip().lower()
    if w in WORLD_TO_PRODUCT:
        return WORLD_TO_PRODUCT[w]
    return ""


def contexts_leak(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """True if toolset/schema from A wrongly appears active on B after a switch."""
    if not a or not b:
        return False
    if a.get("selectedProductType") == b.get("selectedProductType"):
        return False
    if a.get("toolset") and a.get("toolset") == b.get("toolset") and a.get("toolset") != TOOLSET_UNSUPPORTED:
        # Distinct products must not share the same product-specific toolset
        # except surface family aliases (ACP vs SURFACE both surface-like).
        surfacey = {TOOLSET_ACP, TOOLSET_SURFACE}
        if {a.get("toolset"), b.get("toolset")} <= surfacey:
            return False
        if a.get("adapterId") != b.get("adapterId"):
            return True
    # Window schema keys must not remain as B's toolset when B is non-window.
    if a.get("adapterId") == "window_family" and b.get("adapterId") != "window_family":
        if b.get("toolset") in (TOOLSET_SLIDING, TOOLSET_CASEMENT, TOOLSET_FIXED, TOOLSET_FOLD, TOOLSET_DOOR):
            return True
    return False


def assert_no_window_fallthrough(product_type: str) -> dict[str, Any]:
    """Guard used by smokes — WINDOW / empty never resolve to window_family."""
    ctx = resolve_active_design_context(product_type=product_type, source="assert")
    if normalize_product_type(product_type) in ("", "WINDOW") or not product_type:
        if ctx.get("adapterId") == "window_family" or ctx.get("toolset") in (
            TOOLSET_SLIDING,
            TOOLSET_CASEMENT,
        ):
            raise AssertionError("WINDOW fallthrough to window tools")
        if ctx.get("toolset") != TOOLSET_UNSUPPORTED:
            raise AssertionError("empty/WINDOW must use unsupported toolset")
    return ctx
