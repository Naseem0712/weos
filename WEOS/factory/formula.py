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

# Variables available in Formula Builder previews / validation
FORMULA_VARIABLES = (
    "width",
    "height",
    "qty",
    "W",
    "H",
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
    """Build safe numeric context for formula evaluation from line + geometry."""
    g = {k: float(v) for k, v in geometry.items() if isinstance(v, (int, float))}
    w = float(width)
    h = float(height)
    area_sqm = (w * h) / 1_000_000.0
    area_sqft = area_sqm * 10.7639
    perimeter_mm = 2.0 * (w + h)
    running_m = perimeter_mm / 1000.0
    running_ft = perimeter_mm / 304.8

    aliases: dict[str, float] = {
        "width": w,
        "height": h,
        "qty": float(qty),
        "W": w,
        "H": h,
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
        aliases.update({k: float(v) for k, v in extras.items()})
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
