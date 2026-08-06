"""JSON schemas / empty shells for each Manufacturing Memory type.

Memories are NEVER mixed: each type has its own namespace and shape.
Formulas are versioned objects — never silently overwritten.
"""

from __future__ import annotations

from typing import Any

# Canonical memory type ids (API / folder / search namespace keys)
MEM_ENGINEERING = "engineering"
MEM_COMMERCIAL = "commercial"
MEM_PRODUCT = "product"
MEM_PROFILE = "profile"
MEM_HARDWARE = "hardware"
MEM_GLASS = "glass"
MEM_FORMULA = "formula"
MEM_DRAWING = "drawing"
MEM_QUOTATION = "quotation"
MEM_FACTORY = "factory"
MEM_LEARNING = "learning"

MEMORY_TYPES: tuple[str, ...] = (
    MEM_ENGINEERING,
    MEM_COMMERCIAL,
    MEM_PRODUCT,
    MEM_PROFILE,
    MEM_HARDWARE,
    MEM_GLASS,
    MEM_FORMULA,
    MEM_DRAWING,
    MEM_QUOTATION,
    MEM_FACTORY,
    MEM_LEARNING,
)

# Map memory type → primary library folder (when backed by Learning Engine V2 libraries)
LIBRARY_FOLDER: dict[str, str | None] = {
    MEM_ENGINEERING: None,  # dedicated memories/engineering/
    MEM_COMMERCIAL: None,  # commercial/ + memories/commercial/
    MEM_PRODUCT: "product_series",
    MEM_PROFILE: "profiles",
    MEM_HARDWARE: "hardware",
    MEM_GLASS: "glass",
    MEM_FORMULA: "formulas",
    MEM_DRAWING: None,
    MEM_QUOTATION: "quotation_patterns",
    MEM_FACTORY: None,
    MEM_LEARNING: None,
}

# Human labels for UI
MEMORY_LABELS: dict[str, str] = {
    MEM_ENGINEERING: "Engineering Memory",
    MEM_COMMERCIAL: "Commercial Memory",
    MEM_PRODUCT: "Product Memory",
    MEM_PROFILE: "Profile Memory",
    MEM_HARDWARE: "Hardware Memory",
    MEM_GLASS: "Glass Memory",
    MEM_FORMULA: "Formula Memory",
    MEM_DRAWING: "Drawing Memory",
    MEM_QUOTATION: "Quotation Memory",
    MEM_FACTORY: "Factory Memory",
    MEM_LEARNING: "Learning Memory",
}


def _meta() -> dict[str, Any]:
    return {
        "status": "draft",  # draft | pending_approval | approved | rejected | archived
        "revision": 1,
        "created_at": None,
        "updated_at": None,
        "approved_at": None,
        "approved_by": None,
        "kb_version": None,
        "source": {},  # {kind, ref, quote, page, file} — PDF / quote / user / factory / …
        "sourceKind": "",  # pdf | quote | user | factory | catalogue | learned | manual
        "confidence": None,  # 0..100 — ranking Confidence %
        "priority": 50,  # rule priority 0..100 (higher wins when multiple match)
        "usedInProjects": 0,  # ranking: Used N Projects
        "lastUsed": None,  # ISO timestamp
        "tags": [],
        "relationships": {},  # typed links: seriesIds, profileIds, formulaIds, …
    }


def ranking_fields(item: dict[str, Any] | None) -> dict[str, Any]:
    """UI/API ranking card: Confidence %, Source, Approved Yes/No, Used N, Last Used."""
    it = item or {}
    status = (it.get("status") or "").lower()
    approved = status == "approved"
    src = it.get("source") if isinstance(it.get("source"), dict) else {}
    kind = (
        it.get("sourceKind")
        or src.get("kind")
        or ("pdf" if src.get("file") or src.get("page") else "")
        or ("quote" if src.get("quote") else "")
        or ("user" if it.get("approved_by") else "")
        or "unknown"
    )
    conf = it.get("confidence")
    if conf is None and approved:
        conf = 90
    elif conf is None:
        conf = 40
    try:
        conf_pct = max(0, min(100, float(conf)))
    except (TypeError, ValueError):
        conf_pct = 0.0
    return {
        "confidence": conf_pct,
        "confidenceLabel": f"{conf_pct:.0f}%",
        "source": kind,
        "sourceDetail": src,
        "approved": approved,
        "approvedLabel": "Yes" if approved else "No",
        "usedInProjects": int(it.get("usedInProjects") or 0),
        "lastUsed": it.get("lastUsed"),
        "priority": int(it.get("priority") if it.get("priority") is not None else 50),
        "status": it.get("status") or "draft",
        "id": it.get("id"),
        "memoryType": it.get("memoryType"),
    }


def empty_engineering_memory() -> dict[str, Any]:
    """Profile dims, formulas, overlap, cutting, BOM, nesting, waste, hardware usage."""
    return {
        "id": "",
        "memoryType": MEM_ENGINEERING,
        "title": "",
        "seriesId": "",
        "seriesCode": "",  # e.g. S29
        "profiles": [],  # [{profileId, code, W, H, wall, kg_m, positions, revision}]
        "formulas": [],  # formula memory ids
        "overlapRules": {},
        "cuttingRules": {},
        "bomRules": {},
        "nestingRules": {},
        "optimizationRules": {},
        "wasteRules": {},
        "hardwareUsage": [],
        "brushRailGlass": {},
        "weightRules": {},
        "compatibilityRules": [],  # [{field, allowed, message}]
        "conflictRules": [],  # [{a, b, severity, reason}] — drafts until approved
        "scaleRules": [],  # size-scale suggestions (never auto-apply)
        "notes": "",
        **_meta(),
    }


def empty_commercial_memory() -> dict[str, Any]:
    """Customer / dealer / margins / GST / preferred products — extends Customer Memory."""
    return {
        "id": "",
        "memoryType": MEM_COMMERCIAL,
        "customerName": "",
        "customerType": "",  # customer | architect | dealer | vendor
        "preferredProducts": [],
        "preferredColours": [],
        "preferredGlass": [],
        "preferredHardware": [],
        "margins": {},
        "discountRules": {},
        "paymentTerms": "",
        "gstRules": {},
        "descriptions": {},
        "warranty": "",
        "upsellHints": [],
        "seasonalNotes": [],
        "quotationStyle": {},
        "notes": "",
        **_meta(),
    }


def empty_product_memory() -> dict[str, Any]:
    """Full product: eng + commercial formulas, PDF/DXF/SVG, colours, packing, delivery."""
    return {
        "id": "",
        "memoryType": MEM_PRODUCT,
        "seriesName": "",
        "brand": "",
        "productCategory": "",
        "productDescription": "",
        "aluminiumAlloy": "",
        "temper": "",
        "wallThicknessMm": None,
        "powderCoatingType": "",
        "surfaceFinish": "",
        "colours": [],
        "glassThicknessMm": [],
        "compatibleSeries": [],
        "relatedProducts": [],
        "profileIds": [],
        "hardwareIds": [],
        "glassIds": [],
        "formulaIds": [],
        "drawingIds": [],
        "engineeringFormulas": {},
        "commercialFormulas": {},
        "pdfLayout": {},
        "images": [],
        "dxfRefs": [],
        "svgRefs": [],
        "crossSections": [],
        "machineNotes": "",
        "installNotes": "",
        "factoryNotes": "",
        "packingNotes": "",
        "deliveryNotes": "",
        "quotationRules": {},
        "cuttingRules": {},
        "weightRules": {},
        "pricingRules": {},
        **_meta(),
    }


def empty_profile_memory() -> dict[str, Any]:
    return {
        "id": "",
        "memoryType": MEM_PROFILE,
        "profileName": "",
        "profileCode": "",
        "profileType": "Other",
        "series": [],
        "crossSectionWidthMm": None,
        "crossSectionHeightMm": None,
        "wallThicknessMm": None,
        "weightPerMeterKg": None,
        "materialGrade": "",
        "alloy": "",
        "temper": "",
        "powderCoat": "",
        "usePosition": [],
        "usageRules": {},
        "compatibleProducts": [],
        "compatibleSeries": [],
        "drawingId": None,
        "dxfCrossSection": None,
        "pdfPageNumber": None,
        "profileImage": None,
        "bomRole": None,
        "engineeringNotes": "",
        **_meta(),
    }


def empty_hardware_memory() -> dict[str, Any]:
    return {
        "id": "",
        "memoryType": MEM_HARDWARE,
        "name": "",
        "brand": "",
        "category": "",
        "partNumber": "",
        "stockCode": "",
        "supplier": "",
        "unit": "PC",  # PC | KG | RFT | MTR
        "rate": None,
        "purchaseRate": None,
        "sellingRate": None,
        "weightKg": None,
        "pieceWeightKg": None,
        "compatibleProducts": [],
        "compatibleSeries": [],
        "formulaId": None,
        "installPosition": "",
        "image": None,
        "pdfRef": None,
        "description": "",
        "remarks": "",
        **_meta(),
    }


def empty_glass_memory() -> dict[str, Any]:
    return {
        "id": "",
        "memoryType": MEM_GLASS,
        "name": "",
        "glassType": "",
        "thicknessMm": None,
        "weightKgPerSqm": None,
        "density": None,
        "colour": "",
        "brand": "",
        "coating": "",
        "application": [],
        "applications": [],
        "compatibleProducts": [],
        "rate": None,
        "overlapRules": {},
        "calcFormulaId": None,
        "calcFormula": "",
        **_meta(),
    }


def empty_formula_memory() -> dict[str, Any]:
    """Versioned formula object — history appended; never silent overwrite."""
    return {
        "id": "",
        "memoryType": MEM_FORMULA,
        "name": "",
        "category": "",  # glass | brush | track | hardware | weight | waste | packing | cutting
        "expression": "",
        "variables": [],  # [{name, unit, description, default}]
        "steps": [],  # optional human-readable proof steps template
        "outputName": "",  # e.g. glassWidth
        "unit": "",
        "formulaVersion": 1,
        "description": "",
        "compatibleSeries": [],
        "compatibleProducts": [],
        "approvalDate": None,
        "history": [],  # [{formulaVersion, expression, variables, approved_at, approved_by, reason}]
        "source": "",
        **_meta(),
    }


def empty_conflict_rule() -> dict[str, Any]:
    """Declarative hard/soft conflict between memory items (admin-gated)."""
    return {
        "id": "",
        "ruleType": "conflict",
        "memoryType": MEM_ENGINEERING,
        "title": "",
        "a": {"memoryType": "", "id": "", "name": ""},
        "b": {"memoryType": "", "id": "", "name": ""},
        "severity": "hard",  # hard = stop generation | soft = warning
        "reason": "",
        "seriesIds": [],
        "status": "draft",
        **{k: v for k, v in _meta().items() if k != "status"},
    }


def empty_compatibility_rule() -> dict[str, Any]:
    """Series/product compatibility constraint (e.g. glass thickness allow-list)."""
    return {
        "id": "",
        "ruleType": "compatibility",
        "memoryType": MEM_ENGINEERING,
        "title": "",
        "seriesId": "",
        "field": "glassThicknessMm",
        "allowed": [],
        "message": "",
        "severity": "warning",
        "status": "draft",
        **{k: v for k, v in _meta().items() if k != "status"},
    }


def empty_drawing_memory() -> dict[str, Any]:
    return {
        "id": "",
        "memoryType": MEM_DRAWING,
        "title": "",
        "drawingType": "",  # dxf | svg | pdf | cross_section | machine
        "seriesId": "",
        "productId": "",
        "profileId": "",
        "revision": 1,
        "fileRef": None,
        "dxfRef": None,
        "svgRef": None,
        "pdfRef": None,
        "dimensionStyle": {},
        "arrowStyle": {},
        "notes": "",
        **_meta(),
    }


def empty_quotation_memory() -> dict[str, Any]:
    return {
        "id": "",
        "memoryType": MEM_QUOTATION,
        "title": "",
        "customerFormat": "",
        "logo": None,
        "terms": "",
        "descriptions": {},
        "notes": "",
        "warranty": "",
        "payment": "",
        "gst": {},
        "footer": "",
        "header": "",
        "signature": "",
        "brandColours": {},
        "templateId": None,
        "pattern": {},
        **_meta(),
    }


def empty_factory_memory() -> dict[str, Any]:
    return {
        "id": "",
        "memoryType": MEM_FACTORY,
        "title": "",
        "seriesId": "",
        "machine": {},
        "cuttingLengthRules": {},
        "optimizationRules": {},
        "wasteRules": {},
        "packingRules": {},
        "bundleRules": {},
        "labelRules": {},
        "qrRules": {},
        "deliveryNotes": "",
        **_meta(),
    }


def empty_learning_memory() -> dict[str, Any]:
    """Observation + frequency suggestion (never auto-applied)."""
    return {
        "id": "",
        "memoryType": MEM_LEARNING,
        "observationType": "",  # glass_default | colour | hardware | formula | profile_usage | …
        "summary": "",
        "evidence": {},  # e.g. {count: 92, total: 100, value: "5mm"}
        "suggestion": "",
        "frequency": None,  # 0..1
        "targetMemoryType": "",
        "targetPayload": {},
        "adminDecision": None,  # None | approved | rejected
        "resultingKbVersion": None,
        "domain": "",  # engineering | commercial
        **_meta(),
    }


_EMPTY_FACTORIES = {
    MEM_ENGINEERING: empty_engineering_memory,
    MEM_COMMERCIAL: empty_commercial_memory,
    MEM_PRODUCT: empty_product_memory,
    MEM_PROFILE: empty_profile_memory,
    MEM_HARDWARE: empty_hardware_memory,
    MEM_GLASS: empty_glass_memory,
    MEM_FORMULA: empty_formula_memory,
    MEM_DRAWING: empty_drawing_memory,
    MEM_QUOTATION: empty_quotation_memory,
    MEM_FACTORY: empty_factory_memory,
    MEM_LEARNING: empty_learning_memory,
}


def empty_memory(memory_type: str) -> dict[str, Any]:
    factory = _EMPTY_FACTORIES.get(memory_type)
    if not factory:
        raise ValueError(f"Unknown memory type: {memory_type}")
    return factory()


def enrich_from_library(memory_type: str, library_item: dict[str, Any]) -> dict[str, Any]:
    """Lift a V2 library item into the richer Memory schema (non-destructive)."""
    base = empty_memory(memory_type)
    merged = {**base, **{k: v for k, v in library_item.items() if v not in (None, "", [], {})}}
    merged["memoryType"] = memory_type
    merged["id"] = library_item.get("id") or base["id"]
    if library_item.get("status") == "approved":
        merged["status"] = "approved"
    # Preserve ranking defaults when library item omitted them
    if merged.get("confidence") is None and merged.get("status") == "approved":
        merged["confidence"] = 90
    if merged.get("priority") is None:
        merged["priority"] = 50
    if not merged.get("sourceKind"):
        merged["sourceKind"] = "catalogue" if library_item.get("linked_from_learning") else "manual"
    return merged
