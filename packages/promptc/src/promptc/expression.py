"""Minimal safe expression evaluator for promptc {% when %} conditions.

Parity enforced by CI job promptc-evaluator-parity. If you change this
evaluator or dag_executor's simpleeval usage, update
packages/promptc/tests/fixtures/expression_parity.json and verify both
sides produce identical results.

This module is the single-source-of-truth for which operators/functions
promptc recognizes. It MUST NOT import from dag_executor to keep promptc
portable (the whole point of PRP-PLAT-011 is that promptc is a library
consumable outside the dag-executor runtime).
"""
from __future__ import annotations

import ast
import operator
import re
from typing import Any, Callable, Mapping


class ExpressionError(Exception):
    """Raised for parse failures, disallowed constructs, or evaluation errors."""


def evaluate(expr: str, names: Mapping[str, Any]) -> Any:
    """Evaluate `expr` with `names` bound as local variables.

    Returns the expression value (bool, int, str, etc.). Does NOT coerce
    to bool — the caller does that (gate vs interrupt may differ).

    Raises ExpressionError for:
      - ast.parse failures (syntax)
      - unsupported AST node types (lambda, comprehension, subscript,
        attribute access, method call, assignment, starred args, f-strings, ...)
      - calls to functions not in the whitelist
      - unknown variable names
    """
    # Inject JSON-style aliases without overriding caller values.
    bound: dict[str, Any] = dict(names)
    bound.setdefault("true", True)
    bound.setdefault("false", False)
    bound.setdefault("null", None)

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"parse error: {e}") from e

    return _walk(tree.body, bound)


# Whitelisted callable map — every call target must be a bare Name whose id is a key here.
_FUNCS: dict[str, Callable[..., Any]] = {
    "len": len,
    "contains": lambda hay, needle: needle in hay,
    "startswith": lambda s, prefix: s.startswith(prefix),
    "matches": lambda s, pattern: bool(re.fullmatch(pattern, s)),
}

# Comparison operators
_COMPARE_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

# Boolean operators
_BOOL_OPS: dict[type, Callable[[Any], Any]] = {
    ast.And: lambda values: all(values),
    ast.Or: lambda values: any(values),
}

# Binary operators
_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}

# Unary operators
_UNARY_OPS: dict[type, Callable[[Any], Any]] = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


# Dispatched explicitly via isinstance, NOT via ast.NodeVisitor. NodeVisitor's
# default generic_visit silently recurses into unhandled node types, which
# would defeat the "reject unknown constructs" guarantee. Any node type not
# explicitly handled below falls through to the final `raise ExpressionError`.
def _walk(node: ast.AST, names: Mapping[str, Any]) -> Any:
    """Walk an AST node and evaluate it."""
    # Constant literals (str, int, float, bool, None, etc.)
    if isinstance(node, ast.Constant):
        return node.value

    # Variable lookup
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise ExpressionError(f"unknown variable: {node.id}")
        return names[node.id]

    # Comparison operators (==, !=, <, <=, >, >=, in, not in)
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ExpressionError("chained comparisons are not supported")
        left = _walk(node.left, names)
        right = _walk(node.comparators[0], names)
        cmp_op_type = type(node.ops[0])
        if cmp_op_type not in _COMPARE_OPS:
            raise ExpressionError(f"unsupported comparison operator: {cmp_op_type.__name__}")
        return _COMPARE_OPS[cmp_op_type](left, right)

    # Boolean operators (and, or)
    if isinstance(node, ast.BoolOp):
        bool_op_type = type(node.op)
        if bool_op_type not in _BOOL_OPS:
            raise ExpressionError(f"unsupported boolean operator: {bool_op_type.__name__}")
        values = [_walk(val, names) for val in node.values]
        return _BOOL_OPS[bool_op_type](values)

    # Unary operators (not, -, +)
    if isinstance(node, ast.UnaryOp):
        unary_op_type = type(node.op)
        if unary_op_type not in _UNARY_OPS:
            raise ExpressionError(f"unsupported unary operator: {unary_op_type.__name__}")
        operand = _walk(node.operand, names)
        return _UNARY_OPS[unary_op_type](operand)

    # Binary operators (+, -, *, /, %)
    if isinstance(node, ast.BinOp):
        bin_op_type = type(node.op)
        if bin_op_type not in _BIN_OPS:
            raise ExpressionError(f"unsupported binary operator: {bin_op_type.__name__}")
        left = _walk(node.left, names)
        right = _walk(node.right, names)
        return _BIN_OPS[bin_op_type](left, right)

    # Function calls (whitelist only)
    if isinstance(node, ast.Call):
        # Reject non-bare-Name targets (rules out attribute/method calls, lambdas)
        if not isinstance(node.func, ast.Name):
            raise ExpressionError(
                f"unsupported call target: {type(node.func).__name__}"
            )
        fname = node.func.id
        if fname not in _FUNCS:
            raise ExpressionError(f"call to non-whitelisted function: {fname}")
        if node.keywords:
            raise ExpressionError("keyword arguments are not supported")
        args = [_walk(a, names) for a in node.args]
        try:
            return _FUNCS[fname](*args)
        except ExpressionError:
            raise
        except Exception as e:
            raise ExpressionError(f"{fname}(...) failed: {e}") from e

    # List literals
    if isinstance(node, ast.List):
        return [_walk(elt, names) for elt in node.elts]

    # Tuple literals
    if isinstance(node, ast.Tuple):
        return tuple(_walk(elt, names) for elt in node.elts)

    # Everything else is rejected
    raise ExpressionError(f"unsupported construct: {type(node).__name__}")
