"""Condition expression evaluator for conditional edges (Phase 3).

Provides a restricted eval() that allows only safe boolean expressions
against a node's output dict.

Allowed: comparisons (==, !=, <, >, <=, >=), boolean ops (and, or, not),
         arithmetic ops (+, -, *, /, %), subscript access (output["key"]),
         len() calls, integer/float/string/bool literals.
Disallowed: imports, function calls (except len), attribute access on non-output names,
            assignments, comprehensions, lambdas.

Req 5.2, 5.3, 5.6
"""
from __future__ import annotations

import ast
from typing import Any


class ConditionEvaluationError(RuntimeError):
    """Raised when a condition expression cannot be evaluated safely."""


_ALLOWED_NODE_TYPES = frozenset({
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not,
    ast.Compare,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.BinOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.Call,          # only len() is allowed — checked separately
    ast.Subscript,     # output["key"] — checked separately
    ast.Name,          # only "output" is allowed — checked separately
    ast.Constant,      # literals: int, float, str, bool, None
    ast.Load,
})


def _validate_ast(tree: ast.AST) -> None:
    """Walk the AST and raise ConditionEvaluationError for disallowed node types.

    Req 5.3 — whitelist: comparisons, boolean ops, subscript on 'output', len() only.
    """
    for node in ast.walk(tree):
        node_type = type(node)
        if node_type not in _ALLOWED_NODE_TYPES:
            raise ConditionEvaluationError(
                f"Disallowed expression element '{node_type.__name__}' in condition. "
                "Only comparisons, boolean operators, subscript access on 'output', "
                "and len() calls are permitted."
            )
        # Only allow len() function calls
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id == "len"):
                func_name = getattr(node.func, "id", repr(node.func))
                raise ConditionEvaluationError(
                    f"Disallowed function call '{func_name}' in condition. "
                    "Only len() is permitted."
                )
        # Only allow 'output' or 'len' as Name references
        # ('len' appears as the function name in len() calls — it is safe)
        if isinstance(node, ast.Name) and node.id not in ("output", "len"):
            raise ConditionEvaluationError(
                f"Disallowed name '{node.id}' in condition. "
                "Only 'output' is permitted as a variable name."
            )


def evaluate_condition(expression: str, output: dict[str, Any]) -> bool:
    """Evaluate a condition expression against a node's output dict.

    The expression has access to ``output`` (the source node's output dict)
    and the built-in ``len()`` function only.

    Args:
        expression: A boolean expression string, e.g. ``"len(output['output']) > 10"``.
        output: The source node's output dict.

    Returns:
        True if the condition passes, False otherwise.

    Raises:
        ConditionEvaluationError: On syntax errors, disallowed constructs, or
                                   runtime evaluation errors.

    Req 5.2, 5.3, 5.4, 5.5
    """
    # Guard against excessively long expressions (DoS protection)
    _MAX_EXPRESSION_LENGTH = 500
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise ConditionEvaluationError(
            f"Condition expression exceeds maximum length of {_MAX_EXPRESSION_LENGTH} characters "
            f"(got {len(expression)})"
        )

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ConditionEvaluationError(
            f"Syntax error in condition '{expression}': {exc}"
        ) from exc

    _validate_ast(tree)

    try:
        result = eval(  # noqa: S307
            compile(tree, "<condition>", "eval"),
            {"__builtins__": {"len": len}},
            {"output": output},
        )
        return bool(result)
    except ConditionEvaluationError:
        raise
    except Exception as exc:
        raise ConditionEvaluationError(
            f"Condition '{expression}' raised an error during evaluation: {exc}"
        ) from exc
