"""Unit tests for app/core/quality_checker.py — Req 23 criteria 1–8."""
from __future__ import annotations

import numpy as np
import pytest

from app.domain.quality_checker import QualityChecker


# ── Req 23.1 — _check_duration_range below minimum returns error finding ──────

def test_check_duration_range_below_min_returns_error_finding():
    """Req 23.1 — duration 100ms < min 200ms returns finding with check_name='duration_range' and severity='error'."""
    results = QualityChecker._check_duration_range(
        "x.wav", 100.0, {"min_duration_ms": 200}
    )

    assert len(results) == 1
    finding = results[0]
    assert finding["check_name"] == "duration_range"
    assert finding["severity"] == "error"
    assert finding["sample_path"] == "x.wav"


# ── Req 23.2 — _check_duration_range within range returns [] ─────────────────

def test_check_duration_range_within_range_returns_empty():
    """Req 23.2 — duration 500ms within [200, 1000] returns [] (no findings)."""
    results = QualityChecker._check_duration_range(
        "x.wav", 500.0, {"min_duration_ms": 200, "max_duration_ms": 1000}
    )

    assert results == []


# ── Req 23.3 — _check_sample_rate mismatch returns finding ───────────────────

def test_check_sample_rate_mismatch_returns_finding():
    """Req 23.3 — sr=8000 vs required=16000 returns finding with check_name='sample_rate'."""
    results = QualityChecker._check_sample_rate(
        "x.wav", 8000, {"required_sample_rate": 16000}
    )

    assert len(results) == 1
    finding = results[0]
    assert finding["check_name"] == "sample_rate"
    assert finding["sample_path"] == "x.wav"


# ── Req 23.4 — _check_clipping with peak >= 1.0 returns finding ──────────────

def test_check_clipping_with_peak_at_one_returns_finding():
    """Req 23.4 — array with value 1.0 returns finding with check_name='clipping'."""
    audio = np.array([0.0, 1.0, 1.0])
    results = QualityChecker._check_clipping("x.wav", audio)

    assert len(results) == 1
    finding = results[0]
    assert finding["check_name"] == "clipping"
    assert finding["sample_path"] == "x.wav"


# ── Req 23.5 — _check_dc_offset with mean > 0.01 returns finding ─────────────

def test_check_dc_offset_with_large_mean_returns_finding():
    """Req 23.5 — np.full(100, 0.05) has mean=0.05 > 0.01, returns finding with check_name='dc_offset'."""
    audio = np.full(100, 0.05)
    results = QualityChecker._check_dc_offset("x.wav", audio)

    assert len(results) == 1
    finding = results[0]
    assert finding["check_name"] == "dc_offset"
    assert finding["sample_path"] == "x.wav"


# ── Req 23.6 — _check_class_imbalance with imbalanced labels returns finding ──

def test_check_class_imbalance_imbalanced_returns_finding_for_minority_label():
    """Req 23.6 — {'a': 100, 'b': 5} returns finding for label 'b' with check_name='class_imbalance'."""
    results = QualityChecker._check_class_imbalance({"a": 100, "b": 5})

    # Should flag 'b' (5 < 20% of mean(52.5) = 10.5)
    assert len(results) >= 1
    check_names = {r["check_name"] for r in results}
    assert "class_imbalance" in check_names

    # The finding for 'b' must be present
    b_findings = [r for r in results if r["sample_path"] == "b"]
    assert len(b_findings) == 1
    assert b_findings[0]["check_name"] == "class_imbalance"


# ── Req 23.7 — _check_class_imbalance with balanced labels returns [] ─────────

def test_check_class_imbalance_balanced_returns_empty():
    """Req 23.7 — {'a': 100, 'b': 90} returns [] (balanced)."""
    results = QualityChecker._check_class_imbalance({"a": 100, "b": 90})

    assert results == []


# ── Req 23.8 — _finding returns dict with all four keys ──────────────────────

def test_finding_returns_dict_with_all_four_keys():
    """Req 23.8 — _finding('x.wav', 'clipping', 'warning', 'detail') returns dict with all four keys."""
    result = QualityChecker._finding("x.wav", "clipping", "warning", "detail")

    assert isinstance(result, dict)
    assert result["sample_path"] == "x.wav"
    assert result["check_name"] == "clipping"
    assert result["severity"] == "warning"
    assert result["detail"] == "detail"
