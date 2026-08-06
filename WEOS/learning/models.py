"""Learning Engine V2 — shared schemas, constants, and empty shells.

Engineering rules live in structured JSON (pending → approved KB), not hardcoded Python.
"""

from __future__ import annotations

from typing import Any

# Unified pending proposal kinds
KIND_PRODUCT_SERIES = "product_series"
KIND_PROFILE = "profile"
KIND_HARDWARE = "hardware"
KIND_GLASS = "glass"
KIND_ACCESSORY = "accessory"
KIND_PACKAGING = "packaging"
KIND_FORMULA = "formula"
KIND_QUOTATION_PATTERN = "quotation_pattern"
KIND_TEMPLATE = "template"
KIND_MATERIAL_BATCH = "material_batch"
KIND_CATALOGUE_BUNDLE = "catalogue_bundle"  # series + profiles + hardware from one PDF
KIND_ENGINEERING_RULES = "engineering_rules"  # legacy DXF/JSON path (ingest.py)

ALL_KINDS = (
    KIND_PRODUCT_SERIES,
    KIND_PROFILE,
    KIND_HARDWARE,
    KIND_GLASS,
    KIND_ACCESSORY,
    KIND_PACKAGING,
    KIND_FORMULA,
    KIND_QUOTATION_PATTERN,
    KIND_TEMPLATE,
    KIND_MATERIAL_BATCH,
    KIND_CATALOGUE_BUNDLE,
    KIND_ENGINEERING_RULES,
)

STATUS_PENDING = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EDITED = "edited_pending"

# Profile type taxonomy (catalogue drawings)
PROFILE_TYPES = (
    "Outer Track",
    "Shutter Frame",
    "Interlock",
    "Mullion",
    "Transom",
    "Beading",
    "Sash",
    "Handle Section",
    "Adapter",
    "Corner Profile",
    "Extension Profile",
    "Drain Cover",
    "Meeting Rail",
    "Glass Beading",
    "Other",
)

# Tree groups for Product Library UI
TREE_GROUPS = (
    ("outer_track", "Outer Track", ("Outer Track",)),
    ("shutter_frame", "Shutter Frame", ("Shutter Frame", "Sash")),
    ("interlock", "Interlock", ("Interlock", "Meeting Rail")),
    ("glass_beading", "Glass Beading", ("Beading", "Glass Beading")),
    ("hardware", "Roller / Lock / Handle / Brush", ()),  # hardware library
    ("accessories", "Accessories", ("Adapter", "Corner Profile", "Extension Profile", "Drain Cover", "Mullion", "Transom", "Handle Section", "Other")),
)

# Default usage rules that can drive BOM once approved
DEFAULT_USAGE_RULES: dict[str, dict[str, Any]] = {
    "Outer Track": {
        "positions": ["Top", "Bottom", "Left", "Right"],
        "bomRole": "outer_frame",
        "orientation": ["horizontal", "vertical"],
        "notes": "Perimeter outer track / frame",
    },
    "Shutter Frame": {
        "positions": ["Vertical", "Horizontal"],
        "bomRole": "shutter_frame",
        "orientation": ["vertical", "horizontal"],
        "notes": "Shutter / sash perimeter",
    },
    "Interlock": {
        "positions": ["Meeting Side"],
        "bomRole": "interlock",
        "orientation": ["vertical"],
        "notes": "Meeting stile between shutters",
    },
    "Beading": {
        "positions": ["Glass perimeter"],
        "bomRole": "beading",
        "orientation": ["perimeter"],
        "notes": "Glass retainer bead",
    },
    "Glass Beading": {
        "positions": ["Glass perimeter"],
        "bomRole": "beading",
        "orientation": ["perimeter"],
        "notes": "Glass retainer bead",
    },
    "Sash": {
        "positions": ["Vertical", "Horizontal"],
        "bomRole": "sash",
        "orientation": ["vertical", "horizontal"],
        "notes": "Sash section",
    },
    "Mullion": {
        "positions": ["Vertical divider"],
        "bomRole": "mullion",
        "orientation": ["vertical"],
        "notes": "Vertical divider",
    },
    "Transom": {
        "positions": ["Horizontal divider"],
        "bomRole": "transom",
        "orientation": ["horizontal"],
        "notes": "Horizontal divider",
    },
}

HARDWARE_KEYWORDS = (
    ("Handle", ("handle", "lever", "knob")),
    ("Roller", ("roller", "wheel", "pulley")),
    ("Lock", ("lock", "latch", "deadbolt")),
    ("Keeper", ("keeper", "striker", "strike")),
    ("Corner Connector", ("corner connector", "corner cleat", "corner joint")),
    ("Interlock Connector", ("interlock connector", "interlock cleat")),
    ("Cap", ("end cap", "cap", "cover cap")),
    ("Brush", ("brush", "pile", "wool pile", "weather strip")),
    ("Track Rail", ("track rail", "ss rail", "stainless rail")),
    ("EPDM", ("epdm",)),
    ("Rubber", ("rubber", "gasket", "seal")),
    ("Screws", ("screw", "self tap", "fastener")),
    ("Anchor", ("anchor", "rawl", "fix plug")),
    ("End Caps", ("end cap", "endcover")),
)

GLASS_KEYWORDS = ("glass", "toughened", "tempered", "laminated", "reflective", "low-e", "low e", "clear glass")

# Continuous learn pipeline source hooks (scaffolding — always gated by review)
PIPELINE_SOURCES = (
    {"id": "dxf", "label": "DXF drawings", "status": "active"},
    {"id": "json", "label": "JSON catalogues / rules", "status": "active"},
    {"id": "pdf_catalogue", "label": "Product catalogue PDFs", "status": "active"},
    {"id": "images", "label": "Product / cross-section images", "status": "partial"},
    {"id": "old_quotes", "label": "Previous quotations", "status": "active"},
    {"id": "calculate_cart", "label": "Calculate / Window Cart engineering", "status": "active"},
    {"id": "material_formulas", "label": "Material weight / waste formulas", "status": "active"},
    {"id": "commercial_quotes", "label": "Commercial quote intelligence", "status": "active"},
    {"id": "customer_memory", "label": "Customer Memory (prefs)", "status": "active"},
    {"id": "factory_feedback", "label": "Factory feedback", "status": "scaffolded"},
    {"id": "customer_feedback", "label": "Customer feedback", "status": "scaffolded"},
    {"id": "updated_catalogues", "label": "Updated catalogues", "status": "active"},
    {"id": "supplier_catalogues", "label": "Supplier catalogues", "status": "scaffolded"},
)


def empty_product_series() -> dict[str, Any]:
    return {
        "id": "",
        "seriesName": "",
        "brand": "",
        "productCategory": "",
        "productDescription": "",
        "aluminiumAlloy": "",
        "temper": "",
        "wallThicknessMm": None,
        "powderCoatingType": "",
        "surfaceFinish": "",
        "glassThicknessMm": [],
        "hardwareCompatibility": [],
        "productImages": [],
        "crossSectionImages": [],
        "dimensionTables": [],
        "profiles": [],
        "hardware": [],
        "glass": [],
        "formulas": [],
        "quotationRules": {},
        "pdfLayout": {},
        "cuttingRules": {},
        "weightRules": {},
        "pricingRules": {},
    }


def empty_profile() -> dict[str, Any]:
    return {
        "id": "",
        "profileName": "",
        "profileCode": "",
        "profileType": "Other",
        "crossSectionWidthMm": None,
        "crossSectionHeightMm": None,
        "wallThicknessMm": None,
        "weightPerMeterKg": None,
        "materialGrade": "",
        "usePosition": [],
        "usageRules": {},
        "compatibleSeries": [],
        "profileImage": None,
        "dxfCrossSection": None,
        "pdfPageNumber": None,
        "engineeringNotes": "",
        "bomRole": None,
    }


def empty_hardware() -> dict[str, Any]:
    return {
        "id": "",
        "name": "",
        "brand": "",
        "partNumber": "",
        "hardwareType": "",
        "compatibleSeries": [],
        "unit": "PC",
        "pieceWeightKg": None,
        "purchaseRate": None,
        "sellingRate": None,
        "image": None,
        "description": "",
        "remarks": "",
    }


def empty_glass() -> dict[str, Any]:
    return {
        "id": "",
        "name": "",
        "glassType": "",
        "thicknessMm": None,
        "colour": "",
        "coating": "",
        "weightKgPerSqm": None,
        "density": None,
        "applications": [],
        "compatibleProducts": [],
    }


def empty_formula() -> dict[str, Any]:
    return {
        "id": "",
        "name": "",
        "category": "",  # glass | brush | track | hardware | weight | waste | packing
        "expression": "",
        "variables": [],
        "description": "",
        "compatibleSeries": [],
        "source": "",
    }
