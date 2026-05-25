# app/core/nodes/retry.py
"""
Bounded Context:  BC2 — Node Contract
Responsibility:   Exponential back-off retry configuration for nodes.
                  Defines the wait schedule between execution attempts.
Owns:             RetryPolicy Pydantic model and wait_before_attempt().
Public Surface:   RetryPolicy — declare as ``retry_policy: ClassVar[RetryPolicy]``
                  on a Node subclass to override the default (max_attempts=1,
                  no retry).
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not contain execution logic — only configuration.
Dependencies:     pydantic.
Reason To Change: Retry strategy changes (e.g. jitter, max_wait_seconds added),
                  or new back-off algorithms are supported.
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class RetryPolicy(BaseModel):
    """Exponential back-off retry configuration for a node.

    The wait before retry attempt ``i`` (0-indexed, where ``i=0`` is the
    first retry after the initial failure) is::

        wait_i = backoff_seconds * (backoff_multiplier ** i)

    Examples with ``backoff_seconds=1.0``, ``backoff_multiplier=2.0``:

    - Before 2nd attempt (i=0): ``1.0 * 2.0^0 = 1.0 s``
    - Before 3rd attempt (i=1): ``1.0 * 2.0^1 = 2.0 s``
    - Before 4th attempt (i=2): ``1.0 * 2.0^2 = 4.0 s``

    Attributes:
        max_attempts: Total number of attempts including the first (minimum 1).
        backoff_seconds: Base wait time in seconds (minimum 0).
        backoff_multiplier: Multiplier applied per retry (minimum 1.0).
    """

    max_attempts: int = 1
    backoff_seconds: float = 0.0
    backoff_multiplier: float = 1.0

    @field_validator("max_attempts")
    @classmethod
    def _min_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_attempts must be >= 1")
        return v

    @field_validator("backoff_seconds")
    @classmethod
    def _non_negative_backoff(cls, v: float) -> float:
        if v < 0:
            raise ValueError("backoff_seconds must be >= 0")
        return v

    @field_validator("backoff_multiplier")
    @classmethod
    def _min_multiplier(cls, v: float) -> float:
        if v < 1.0:
            raise ValueError("backoff_multiplier must be >= 1.0")
        return v

    def wait_before_attempt(self, attempt_index: int) -> float:
        """Return the wait time in seconds before retry ``attempt_index`` (0-indexed).

        ``attempt_index=0`` → wait before the 2nd overall attempt (first retry).
        ``attempt_index=1`` → wait before the 3rd overall attempt (second retry).
        """
        return self.backoff_seconds * (self.backoff_multiplier ** attempt_index)
