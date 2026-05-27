# unit_test/core/nodes/test_retry.py
"""Tests for app/core/nodes/retry.py — Req 18 criteria 11–14 + Req 2.4 (monotonicity PBT)."""
from __future__ import annotations

import pytest
import pydantic
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.nodes.retry import RetryPolicy


class TestRetryPolicyValidation:
    """Req 18.11–13 — invalid RetryPolicy fields raise pydantic.ValidationError."""

    def test_max_attempts_zero_raises(self):
        """Req 18.11: max_attempts=0 raises ValidationError."""
        with pytest.raises(pydantic.ValidationError):
            RetryPolicy(max_attempts=0)

    def test_max_attempts_negative_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RetryPolicy(max_attempts=-1)

    def test_backoff_seconds_negative_raises(self):
        """Req 18.12: backoff_seconds=-1.0 raises ValidationError."""
        with pytest.raises(pydantic.ValidationError):
            RetryPolicy(backoff_seconds=-1.0)

    def test_backoff_multiplier_below_one_raises(self):
        """Req 18.13: backoff_multiplier=0.5 raises ValidationError."""
        with pytest.raises(pydantic.ValidationError):
            RetryPolicy(backoff_multiplier=0.5)

    def test_backoff_multiplier_zero_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RetryPolicy(backoff_multiplier=0.0)


class TestRetryPolicyWaitBeforeAttempt:
    """Req 18.14 — wait_before_attempt returns correct exponential backoff."""

    def test_wait_before_attempt_2_returns_4(self):
        """Req 18.14: max_attempts=3, backoff_seconds=1.0, backoff_multiplier=2.0,
        wait_before_attempt(2) returns 4.0."""
        policy = RetryPolicy(max_attempts=3, backoff_seconds=1.0, backoff_multiplier=2.0)
        assert policy.wait_before_attempt(2) == pytest.approx(4.0)

    def test_wait_before_attempt_0_returns_backoff_seconds(self):
        """wait_before_attempt(0) = backoff_seconds * multiplier^0 = backoff_seconds."""
        policy = RetryPolicy(max_attempts=3, backoff_seconds=1.0, backoff_multiplier=2.0)
        assert policy.wait_before_attempt(0) == pytest.approx(1.0)

    def test_wait_before_attempt_1_returns_doubled(self):
        """wait_before_attempt(1) = 1.0 * 2.0^1 = 2.0."""
        policy = RetryPolicy(max_attempts=3, backoff_seconds=1.0, backoff_multiplier=2.0)
        assert policy.wait_before_attempt(1) == pytest.approx(2.0)

    def test_zero_backoff_always_returns_zero(self):
        """With backoff_seconds=0, all waits are 0 regardless of multiplier."""
        policy = RetryPolicy(max_attempts=5, backoff_seconds=0.0, backoff_multiplier=3.0)
        for i in range(5):
            assert policy.wait_before_attempt(i) == pytest.approx(0.0)

    def test_multiplier_one_returns_constant_backoff(self):
        """With backoff_multiplier=1.0, all waits equal backoff_seconds."""
        policy = RetryPolicy(max_attempts=5, backoff_seconds=2.0, backoff_multiplier=1.0)
        for i in range(5):
            assert policy.wait_before_attempt(i) == pytest.approx(2.0)


class TestRetryPolicyMonotonicity:
    """Req 2.4 — wait times are non-decreasing (property-based test).

    **Validates: Requirements 2.4**
    """

    @given(
        backoff_s=st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        multiplier=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        attempt=st.integers(min_value=1, max_value=9),
    )
    @settings(max_examples=100)
    def test_wait_monotonic(self, backoff_s, multiplier, attempt):
        """For any valid RetryPolicy, wait times are non-decreasing across attempts."""
        policy = RetryPolicy(
            max_attempts=10,
            backoff_seconds=backoff_s,
            backoff_multiplier=multiplier,
        )
        assert policy.wait_before_attempt(attempt) >= policy.wait_before_attempt(attempt - 1)


class TestRetryPolicyMaxWait:
    """max_wait_seconds caps the computed wait time (LOW finding fix)."""

    def test_max_wait_caps_large_exponent(self):
        """With large attempt index, wait is capped at max_wait_seconds."""
        policy = RetryPolicy(
            max_attempts=50,
            backoff_seconds=1.0,
            backoff_multiplier=2.0,
            max_wait_seconds=30.0,
        )
        assert policy.wait_before_attempt(49) == pytest.approx(30.0)

    def test_max_wait_not_applied_when_below_cap(self):
        """Small exponent: raw value is below cap, so cap has no effect."""
        policy = RetryPolicy(
            max_attempts=3,
            backoff_seconds=1.0,
            backoff_multiplier=2.0,
            max_wait_seconds=60.0,
        )
        assert policy.wait_before_attempt(2) == pytest.approx(4.0)

    def test_max_wait_negative_raises(self):
        """max_wait_seconds < 0 raises ValidationError."""
        with pytest.raises(pydantic.ValidationError):
            RetryPolicy(max_wait_seconds=-1.0)

    def test_default_max_wait_is_60(self):
        """Default max_wait_seconds is 60.0."""
        policy = RetryPolicy()
        assert policy.max_wait_seconds == pytest.approx(60.0)


class TestRetryPolicyIsRetryable:
    """is_retryable() correctly filters non-retryable exceptions (MEDIUM finding fix)."""

    def test_empty_list_always_retryable(self):
        """Default empty non_retryable_exceptions: all exceptions are retryable."""
        policy = RetryPolicy(max_attempts=3)
        assert policy.is_retryable(FileNotFoundError("missing")) is True
        assert policy.is_retryable(ValueError("bad")) is True
        assert policy.is_retryable(RuntimeError("oops")) is True

    def test_exact_class_name_not_retryable(self):
        """Exception whose class name is in the list is not retryable."""
        policy = RetryPolicy(
            max_attempts=3,
            non_retryable_exceptions=["FileNotFoundError"],
        )
        assert policy.is_retryable(FileNotFoundError("missing")) is False

    def test_other_exception_still_retryable(self):
        """Exception not in the list is still retryable."""
        policy = RetryPolicy(
            max_attempts=3,
            non_retryable_exceptions=["FileNotFoundError"],
        )
        assert policy.is_retryable(ConnectionError("timeout")) is True

    def test_base_class_name_blocks_subclass(self):
        """Listing a base class name blocks subclasses via MRO matching."""
        policy = RetryPolicy(
            max_attempts=3,
            non_retryable_exceptions=["OSError"],
        )
        # FileNotFoundError is a subclass of OSError
        assert policy.is_retryable(FileNotFoundError("missing")) is False

    def test_multiple_entries(self):
        """Multiple entries: any match makes the exception non-retryable."""
        policy = RetryPolicy(
            max_attempts=3,
            non_retryable_exceptions=["FileNotFoundError", "ValueError"],
        )
        assert policy.is_retryable(FileNotFoundError("x")) is False
        assert policy.is_retryable(ValueError("x")) is False
        assert policy.is_retryable(RuntimeError("x")) is True
