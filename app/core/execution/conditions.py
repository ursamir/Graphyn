# app/core/execution/conditions.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Safe evaluation of boolean condition expressions on node
                  output dicts for conditional edge routing.
Owns:             evaluate_condition(), ConditionEvaluationError,
                  _validate_ast() (AST whitelist enforcer).
Public Surface:   evaluate_condition(expression, output) -> bool
                  validate_condition_syntax(expression) -> None
                  ConditionEvaluationError
Must NOT:         Import from app.domain, app.api, or any storage module.
                  Must not execute arbitrary Python — only the whitelisted
                  AST node types are permitted.
Dependencies:     stdlib (ast).
Reason To Change: Condition expression language is extended (new operators,
                  new allowed names), or security policy tightens.

Allowed: comparisons (==, !=, <, >, <=, >=), boolean ops (and, or, not),
         arithmetic ops (+, -, *, /, %), subscript access (output["key"]),
         (``*`` and ``%`` are numeric-only with a result-size guard — no
         ``"a" * 10**9`` string/list repetition or printf-style formatting),
         len() calls, integer/float/string/bool literals.
Disallowed: imports, function calls (except len), attribute access on non-output names,
            assignments, comprehensions, lambdas.
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
    # Python 3.8 wraps subscript slice values in ast.Index (removed in 3.9+).
    # Including it here keeps output["key"] valid on 3.8 without any security
    # impact — Index is a transparent wrapper with no callable behaviour.
    getattr(ast, "Index", type(None)),
} - {type(None)})


def _ast_depth(node: ast.AST) -> int:
    """Return the maximum depth of an AST tree (iterative, avoids recursion limit)."""
    max_depth = 0
    stack = [(node, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            max_depth = depth
        for child in ast.iter_child_nodes(current):
            stack.append((child, depth + 1))
    return max_depth


def _validate_ast(tree: ast.AST) -> None:
    """Walk the AST and raise ConditionEvaluationError for disallowed node types.

    Also enforces a maximum AST depth to prevent DoS via deeply nested
    expressions that pass the whitelist but fail at runtime (SEC-8 fix).

    Req 5.3 — whitelist: comparisons, boolean ops, subscript on 'output', len() only.
    """
    _MAX_AST_DEPTH = 12
    depth = _ast_depth(tree)
    if depth > _MAX_AST_DEPTH:
        raise ConditionEvaluationError(
            f"Condition expression is too deeply nested (depth {depth}, max {_MAX_AST_DEPTH}). "
            "Simplify the expression."
        )

    for node in ast.walk(tree):
        node_type = type(node)
        if node_type not in _ALLOWED_NODE_TYPES:
            raise ConditionEvaluationError(
                f"Disallowed expression element '{node_type.__name__}' in condition. "
                "Only comparisons, boolean operators, subscript access on 'output', "
                "and len() calls are permitted."
            )
        # Only allow len() function calls with exactly one positional argument
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id == "len"):
                func_name = getattr(node.func, "id", repr(node.func))
                raise ConditionEvaluationError(
                    f"Disallowed function call '{func_name}' in condition. "
                    "Only len() is permitted."
                )
            if len(node.args) != 1 or node.keywords:
                raise ConditionEvaluationError(
                    "len() requires exactly one positional argument."
                )
        # Only allow 'output' or 'len' as Name references
        # ('len' appears as the function name in len() calls — it is safe)
        if isinstance(node, ast.Name) and node.id not in ("output", "len"):
            raise ConditionEvaluationError(
                f"Disallowed name '{node.id}' in condition. "
                "Only 'output' is permitted as a variable name."
            )


_MAX_INT_BITS = 4096
_MAX_EXPRESSION_LENGTH = 500


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, complex)


def _safe_mul(a: Any, b: Any) -> Any:
    """Numeric-only multiplication (blocks str/list repetition DoS)."""
    if not (_is_number(a) and _is_number(b)):
        raise ConditionEvaluationError(
            f"'*' is only allowed between numbers (got {type(a).__name__} * {type(b).__name__})"
        )
    if isinstance(a, int) and isinstance(b, int):
        if abs(a).bit_length() + abs(b).bit_length() > _MAX_INT_BITS:
            raise ConditionEvaluationError("'*' result exceeds the maximum integer size")
    return a * b


def _safe_mod(a: Any, b: Any) -> Any:
    """Numeric-only modulo (blocks printf-style string formatting DoS)."""
    if not (_is_number(a) and _is_number(b)):
        raise ConditionEvaluationError(
            f"'%' is only allowed between numbers (got {type(a).__name__} % {type(b).__name__})"
        )
    return a % b


_SAFE_BINOPS = {ast.Mult: "__graphyn_safe_mul", ast.Mod: "__graphyn_safe_mod"}


class _GuardBinOps(ast.NodeTransformer):
    """Rewrite ``a * b`` / ``a % b`` into guarded helper calls (post-validation)."""

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        helper = _SAFE_BINOPS.get(type(node.op))
        if helper is None:
            return node
        call = ast.Call(
            func=ast.Name(id=helper, ctx=ast.Load()),
            args=[node.left, node.right],
            keywords=[],
        )
        return ast.copy_location(call, node)


class _BareNamesToOutput(ast.NodeTransformer):
    """Rewrite bare field names ``score`` into ``output['score']`` (if_switch, F19)."""

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in ("output", "len"):
            return node
        sub = ast.Subscript(
            value=ast.Name(id="output", ctx=ast.Load()),
            slice=ast.Constant(value=node.id),
            ctx=ast.Load(),
        )
        return ast.copy_location(sub, node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        # keep the ``len`` function name itself; rewrite its arguments
        node.args = [self.visit(a) for a in node.args]
        return node


def _parse_and_validate(expression: str, *, bare_names: bool = False) -> ast.Expression:
    if not isinstance(expression, str):
        raise ConditionEvaluationError("Condition expression must be a string")
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
    if bare_names:
        tree = ast.fix_missing_locations(_BareNamesToOutput().visit(tree))
    _validate_ast(tree)
    return tree


def validate_condition_syntax(expression: str, *, bare_names: bool = False) -> None:
    """Static check (length, syntax, AST whitelist) without evaluating.

    Used by graph validation so malformed edge conditions fail before a run.
    Raises ConditionEvaluationError on any problem.
    """
    _parse_and_validate(expression, bare_names=bare_names)


def evaluate_condition(
    expression: str, output: dict[str, Any], *, bare_names: bool = False
) -> bool:
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
    tree = _parse_and_validate(expression, bare_names=bare_names)
    guarded = ast.fix_missing_locations(_GuardBinOps().visit(tree))

    try:
        result = eval(  # noqa: S307
            compile(guarded, "<condition>", "eval"),
            {
                "__builtins__": {"len": len},
                "__graphyn_safe_mul": _safe_mul,
                "__graphyn_safe_mod": _safe_mod,
            },
            {"output": output},
        )
        return bool(result)
    except ConditionEvaluationError:
        raise
    except KeyError as exc:
        raise ConditionEvaluationError(
            f"Condition '{expression}' references key {exc} which is not present "
            f"in the output dict. Available keys: {sorted(output.keys())}"
        ) from exc
    except Exception as exc:
        raise ConditionEvaluationError(
            f"Condition '{expression}' raised an error during evaluation: {exc}"
        ) from exc
