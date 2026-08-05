"""Safe formula evaluator for profile JSON quantity/length expressions."""

from __future__ import annotations

import ast
import operator
import re
from typing import Any, Mapping

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
    raise ValueError(f"Disallowed expression element: {type(node).__name__}")


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def build_context(
    width: float,
    height: float,
    geometry: Mapping[str, Any],
    *,
    extras: Mapping[str, float] | None = None,
) -> dict[str, float]:
    g = {k: float(v) for k, v in geometry.items() if isinstance(v, (int, float))}
    aliases: dict[str, float] = {
        "width": float(width),
        "height": float(height),
        "W": float(width),
        "H": float(height),
        "trackWidth": float(g["trackWidth"]) if "trackWidth" in g else 0.0,
        "frameWidth": float(g["frameWidth"]) if "frameWidth" in g else 0.0,
        "interlockWidth": float(g["interlockWidth"]) if "interlockWidth" in g else 0.0,
        "overlap": float(g["overlap"]) if "overlap" in g else 0.0,
        "glassClip": float(g["glassClip"]) if "glassClip" in g else 0.0,
        "trackCount": float(g["trackCount"]) if "trackCount" in g else 0.0,
        "shutterCount": float(g["shutterCount"]) if "shutterCount" in g else 0.0,
        "meetingGap": float(g["meetingGap"]) if "meetingGap" in g else 0.0,
    }
    aliases["shutterInset"] = aliases["trackWidth"] - aliases["overlap"]
    if extras:
        aliases.update({k: float(v) for k, v in extras.items()})
    for camel, val in list(aliases.items()):
        aliases.setdefault(_camel_to_snake(camel), val)
    return aliases

