"""Unit tests for app/core/conditions.py — Req 19 criteria 1–6."""
from __future__ import annotations

import pytest

from app.core.conditions import ConditionEvaluationError, evaluate_condition


# ── Passing / failing conditions ──────────────────────────────────────────────

def test_len_condition_passes_when_list_longer_than_threshold():
    """Req 19.1 — len(output['output']) > 2 returns True for [1,2,3]."""
    result = evaluate_condition("len(output['output']) > 2", {"output": [1, 2, 3]})
    assert result is True


def test_len_condition_fails_when_list_shorter_than_threshold():
    """Req 19.2 — len(output['output']) > 2 returns False for [1]."""
    result = evaluate_condition("len(output['output']) > 2", {"output": [1]})
    assert result is False


# ── Security / disallowed constructs ─────────────────────────────────────────

def test_import_statement_raises_condition_evaluation_error():
    """Req 19.3 — 'import os' raises ConditionEvaluationError."""
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition("import os", {})


def test_disallowed_function_call_raises_condition_evaluation_error():
    """Req 19.4 — open('x') raises ConditionEvaluationError (disallowed function)."""
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition("open('x')", {})


def test_unknown_name_raises_condition_evaluation_error():
    """Req 19.5 — 'x > 1' raises ConditionEvaluationError (disallowed name)."""
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition("x > 1", {})


def test_syntax_error_raises_condition_evaluation_error():
    """Req 19.6 — '{ bad syntax' raises ConditionEvaluationError (syntax error)."""
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition("{ bad syntax", {})
