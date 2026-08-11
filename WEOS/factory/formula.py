"""Safe formula evaluator for Product Library expressions (no eval / exec).

Admins define quantity, length, weight, and pricing formulas as named expressions
over project/line context variables — never arbitrary Python.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any, Mapping

# Canonical material units (every material may use a different unit)
MATERIAL_UNITS = ("PC", "KG", "RFT", "RM", "SQFT", "SQM", "BOX", "PAIR", "SET")

# Default qty formula when admin picks a unit (Materials + Formulas auto-fill)
DEFAULT_QTY_FORMULA_BY_UNIT: dict[str, str] = {
    "PC": "1",
    "KG": "1",
    "RFT": "LengthRft",
    "RM": "LengthRm",
    "SQFT": "AreaSqft",
    "SQM": "AreaSqm",
    "BOX": "1",
    "PAIR": "1",
    "SET": "1",
}

# Admin cheat-sheet (Materials editor + Formula Builder + Agent tip)
FORMULA_VARIABLE_HELP: tuple[dict[str, str], ...] = (
    {"name": "LengthRft", "for": "RFT", "desc": "Railing / line run length in feet (from cart width; L/U = sum of spans)"},
    {"name": "LengthRm", "for": "RM", "desc": "Same run length in metres"},
    {"name": "LengthMm", "for": "mm", "desc": "Same run length in millimetres"},
    {"name": "WidthRft", "for": "RFT", "desc": "Alias of LengthRft — cart Width converted to feet"},
    {"name": "ActualLengthRft", "for": "RFT", "desc": "Alias of LengthRft (commercial railing length)"},
    {"name": "RailingLength", "for": "RFT", "desc": "Alias of LengthRft"},
    {"name": "Length", "for": "RFT", "desc": "Alias of LengthRft — use for continuous bottom/top rail"},
    {"name": "ActualLength", "for": "RFT", "desc": "Alias of LengthRft — accepted for older formulas"},
    {"name": "Width", "for": "mm", "desc": "Cart / opening width in mm (same as width / W)"},
    {"name": "Height", "for": "mm", "desc": "Cart / opening height in mm (same as height / H)"},
    {"name": "Qty", "for": "PC", "desc": "Line quantity (same as qty)"},
    {"name": "AreaSqft", "for": "SQFT", "desc": "Opening area in sq.ft (width × height)"},
    {"name": "AreaSqm", "for": "SQM", "desc": "Opening area in m²"},
    {"name": "runningFeet", "for": "RFT", "desc": "Window frame perimeter in feet (NOT railing run — prefer LengthRft for rails)"},
    {"name": "runningMeters", "for": "RM", "desc": "Window frame perimeter in metres"},
    {"name": "glassArea", "for": "SQM", "desc": "Glass area m² (from shutters when known)"},
    {"name": "glassAreaSqft", "for": "SQFT", "desc": "Glass area sq.ft"},
    {"name": "shutterCount", "for": "PC", "desc": "Number of glass shutters / leaves"},
    {"name": "trackCount", "for": "PC", "desc": "Number of tracks"},
)

# Variables available in Formula Builder previews / validation
FORMULA_VARIABLES = (
    "width",
    "height",
    "qty",
    "W",
    "H",
    "Width",
    "Height",
    "Qty",
    "LengthMm",
    "LengthRft",
    "LengthRm",
    "WidthRft",
    "WidthRm",
    "ActualLengthMm",
    "ActualLengthRft",
    "ActualLengthRm",
    "ActualLength",
    "Length",
    "RailingLength",
    "RailingLengthRft",
    "RailingLengthRm",
    "commercialRailingLengthRFT",
    "commercialRailingLengthRMT",
    "AreaSqft",
    "AreaSqm",
    "trackWidth",
    "frameWidth",
    "interlockWidth",
    "overlap",
    "glassClip",
    "trackCount",
    "shutterCount",
    "meetingGap",
    "shutterInset",
    "leftShutterWidth",
    "rightShutterWidth",
    "leftGlassWidth",
    "rightGlassWidth",
    "glassHeight",
    "glassArea",
    "glassAreaSqft",
    "runningMeters",
    "runningFeet",
    "areaSqm",
    "areaSqft",
    "weightPerMeter",
    "unitRate",
)

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_FUNCS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "ceil": math.ceil,
    "floor": math.floor,
    "sqrt": math.sqrt,
}


def eval_formula(expr: str | int | float, variables: Mapping[str, float]) -> float:
    if isinstance(expr, (int, float)):
        return float(expr)
    text = str(expr).strip()
    if not text:
        return 0.0
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid formula {text!r}: {exc}") from exc
    return float(_eval_node(tree.body, dict(variables)))


def validate_formula(expr: str | int | float, *, variables: Mapping[str, float] | None = None) -> dict[str, Any]:
    """Validate a formula without requiring a full manufacturing context."""
    sample = dict(demo_context())
    if variables:
        sample.update({k: float(v) for k, v in variables.items()})
    try:
        value = eval_formula(expr, sample)
        return {"ok": True, "value": round(value, 6), "expr": str(expr), "variablesUsed": _names_in_expr(expr)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "expr": str(expr), "variablesUsed": _names_in_expr(expr)}


def preview_formula(
    expr: str | int | float,
    *,
    width: float = 1440,
    height: float = 1800,
    qty: float = 1,
    extras: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate a formula against a synthetic line context (Formula Builder preview)."""
    geom = {
        "trackWidth": 29,
        "frameWidth": 35,
        "interlockWidth": 28,
        "overlap": 8,
        "glassClip": 10,
        "trackCount": 2,
        "shutterCount": 2,
        "meetingGap": 0,
    }
    ctx = build_context(width, height, geom, qty=qty, extras=extras)
    result = validate_formula(expr, variables=ctx)
    result["context"] = {
        k: round(v, 4)
        for k, v in sorted(ctx.items())
        if k in FORMULA_VARIABLES or k in (extras or {})
    }
    return result


def demo_context() -> dict[str, float]:
    return build_context(
        1440,
        1800,
        {
            "trackWidth": 29,
            "frameWidth": 35,
            "interlockWidth": 28,
            "overlap": 8,
            "glassClip": 10,
            "trackCount": 2,
            "shutterCount": 2,
            "meetingGap": 0,
        },
        qty=1,
        extras={
            "leftShutterWidth": 720,
            "rightShutterWidth": 720,
            "leftGlassWidth": 650,
            "rightGlassWidth": 650,
            "glassHeight": 1700,
            "weightPerMeter": 0.75,
            "unitRate": 100,
        },
    )


def _names_in_expr(expr: str | int | float) -> list[str]:
    if isinstance(expr, (int, float)):
        return []
    try:
        tree = ast.parse(str(expr).strip() or "0", mode="eval")
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
    return sorted(names)


def _eval_node(node: ast.AST, vars_: dict[str, float]) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in vars_:
            raise KeyError(f"Unknown formula variable '{node.id}'")
        return float(vars_[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return float(_BINOPS[type(node.op)](_eval_node(node.left, vars_), _eval_node(node.right, vars_)))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return float(_UNARY[type(node.op)](_eval_node(node.operand, vars_)))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, vars_)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, vars_)
            fn = _CMPOPS.get(type(op))
            if fn is None:
                raise ValueError(f"Disallowed comparison: {type(op).__name__}")
            if not fn(left, right):
                return 0.0
            left = right
        return 1.0
    if isinstance(node, ast.IfExp):
        return _eval_node(node.body if _eval_node(node.test, vars_) else node.orelse, vars_)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError(f"Disallowed function: {getattr(node.func, 'id', type(node.func).__name__)}")
        if node.keywords:
            raise ValueError("Keyword arguments are not allowed in formulas")
        args = [_eval_node(a, vars_) for a in node.args]
        return float(_FUNCS[node.func.id](*args))
    raise ValueError(f"Disallowed expression element: {type(node).__name__}")


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def build_context(
    width: float,
    height: float,
    geometry: Mapping[str, Any],
    *,
    qty: float = 1.0,
    extras: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Build safe numeric context for formula evaluation from line + geometry.

    For railings, ``width`` is the run length in mm (sum of L/U spans when the
    designer provides commercial length via extras). RFT materials should use
    ``LengthRft`` (aliases: ``Length``, ``ActualLength``, ``WidthRft``).
    """
    g = {k: float(v) for k, v in geometry.items() if isinstance(v, (int, float))}
    w = float(width)
    h = float(height)
    area_sqm = (w * h) / 1_000_000.0
    area_sqft = area_sqm * 10.7639
    perimeter_mm = 2.0 * (w + h)
    running_m = perimeter_mm / 1000.0
    running_ft = perimeter_mm / 304.8

    # Run length: cart width (mm) unless railing quote supplies commercial length.
    ex0 = {k: float(v) for k, v in (extras or {}).items() if isinstance(v, (int, float))}
    length_mm = w
    for key in (
        "commercialLengthMm",
        "railingLengthMm",
        "totalLengthMm",
        "lengthMm",
        "LengthMm",
        "ActualLengthMm",
    ):
        if key in ex0 and ex0[key] > 0:
            length_mm = ex0[key]
            break
    if "commercialRailingLengthRFT" in ex0 and ex0["commercialRailingLengthRFT"] > 0:
        length_rft = ex0["commercialRailingLengthRFT"]
        length_rm = (
            ex0["commercialRailingLengthRMT"]
            if ex0.get("commercialRailingLengthRMT", 0) > 0
            else length_rft / 3.28084
        )
        length_mm = length_rft * 304.8
    elif "commercialRailingLengthRMT" in ex0 and ex0["commercialRailingLengthRMT"] > 0:
        length_rm = ex0["commercialRailingLengthRMT"]
        length_rft = length_rm * 3.28084
        length_mm = length_rm * 1000.0
    else:
        length_rft = length_mm / 304.8
        length_rm = length_mm / 1000.0

    aliases: dict[str, float] = {
        "width": w,
        "height": h,
        "qty": float(qty),
        "W": w,
        "H": h,
        "Width": w,
        "Height": h,
        "Qty": float(qty),
        # Linear run (railing continuous rail / handrail) — prefer these for RFT/RM
        "LengthMm": length_mm,
        "LengthRft": length_rft,
        "LengthRm": length_rm,
        "WidthRft": length_rft,
        "WidthRm": length_rm,
        "ActualLengthMm": length_mm,
        "ActualLengthRft": length_rft,
        "ActualLengthRm": length_rm,
        # Admin-friendly aliases (qty formula returns feet for RFT materials)
        "ActualLength": length_rft,
        "Length": length_rft,
        "RailingLength": length_rft,
        "RailingLengthRft": length_rft,
        "RailingLengthRm": length_rm,
        "commercialRailingLengthRFT": length_rft,
        "commercialRailingLengthRMT": length_rm,
        "AreaSqft": area_sqft,
        "AreaSqm": area_sqm,
        "trackWidth": float(g["trackWidth"]) if "trackWidth" in g else 0.0,
        "frameWidth": float(g["frameWidth"]) if "frameWidth" in g else 0.0,
        "interlockWidth": float(g["interlockWidth"]) if "interlockWidth" in g else 0.0,
        "overlap": float(g["overlap"]) if "overlap" in g else 0.0,
        "glassClip": float(g["glassClip"]) if "glassClip" in g else 0.0,
        "trackCount": float(g["trackCount"]) if "trackCount" in g else 0.0,
        "shutterCount": float(g["shutterCount"]) if "shutterCount" in g else 0.0,
        "meetingGap": float(g["meetingGap"]) if "meetingGap" in g else 0.0,
        "areaSqm": area_sqm,
        "areaSqft": area_sqft,
        "runningMeters": running_m,
        "runningFeet": running_ft,
        "glassArea": area_sqm,
        "glassAreaSqft": area_sqft,
    }
    aliases["shutterInset"] = aliases["trackWidth"] - aliases["overlap"]
    if extras:
        # Extras win for explicit keys, but do not wipe Length* aliases unless provided.
        for k, v in extras.items():
            try:
                aliases[k] = float(v)
            except (TypeError, ValueError):
                continue
        # Re-sync Length aliases if commercial RFT was injected after the first pass
        if "commercialRailingLengthRFT" in aliases and aliases["commercialRailingLengthRFT"] > 0:
            lr = aliases["commercialRailingLengthRFT"]
            lm = (
                aliases["commercialRailingLengthRMT"]
                if aliases.get("commercialRailingLengthRMT", 0) > 0
                else lr / 3.28084
            )
            for name, val in (
                ("LengthRft", lr),
                ("LengthRm", lm),
                ("LengthMm", lr * 304.8),
                ("WidthRft", lr),
                ("WidthRm", lm),
                ("ActualLength", lr),
                ("ActualLengthRft", lr),
                ("ActualLengthRm", lm),
                ("ActualLengthMm", lr * 304.8),
                ("Length", lr),
                ("RailingLength", lr),
                ("RailingLengthRft", lr),
                ("RailingLengthRm", lm),
            ):
                aliases[name] = val
    if "leftGlassWidth" in aliases and "rightGlassWidth" in aliases and "glassHeight" in aliases:
        ga = (
            (aliases["leftGlassWidth"] + aliases["rightGlassWidth"])
            * aliases["glassHeight"]
            / 1_000_000.0
        )
        aliases["glassArea"] = ga
        aliases["glassAreaSqft"] = ga * 10.7639
    for camel, val in list(aliases.items()):
        aliases.setdefault(_camel_to_snake(camel), val)
    return aliases


def normalize_unit(unit: str | None) -> str:
    raw = str(unit or "PC").strip().upper()
    aliases = {
        "PCS": "PC",
        "PIECE": "PC",
        "PIECES": "PC",
        "NOS": "PC",
        "EA": "PC",
        "EACH": "PC",
        "M": "RM",
        "METER": "RM",
        "METRE": "RM",
        "METERS": "RM",
        "METRES": "RM",
        "RMT": "RM",
        "FT": "RFT",
        "FEET": "RFT",
        "FOOT": "RFT",
        "M2": "SQM",
        "M²": "SQM",
        "SQ.M": "SQM",
        "SQ.FT": "SQFT",
        "FT2": "SQFT",
        "SETS": "SET",
        "PAIRS": "PAIR",
        "BOXES": "BOX",
        "KGS": "KG",
    }
    return aliases.get(raw, raw if raw in MATERIAL_UNITS else raw)


def default_qty_formula_for_unit(unit: str | None) -> str:
    """Suggested quantityFormula when admin selects a material unit."""
    return DEFAULT_QTY_FORMULA_BY_UNIT.get(normalize_unit(unit), "1")
