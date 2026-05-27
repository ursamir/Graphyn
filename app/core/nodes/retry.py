# app/core/nodes/retry.py
"""
Bounded Context:  BC2 — Node Contract
Responsibility:   Exponential back-off retry configuration for nodes.
                  Defines the wait schedule between execution attempts.
Owns:             RetryPolicy Pydantic model, wait_before_attempt(), is_retryable().
Public Surface:   RetryPolicy — declare as ``retry_policy: ClassVar[RetryPolicy]``
                  on a Node subclass to override the default (max_attempts=1,
                  no retry).
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not contain execution logic — only configuration.
Dependencies:     pydantic.
Reason To Change: Retry strategy changes (e.g. jitter, new back-off algorithms),
                  or new exception-filtering semantics are required.
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class RetryPolicy(BaseModel):
    """Exponential back-off retry configuration for a node.

    The wait before retry attempt ``i`` (0-indexed, where ``i=0`` is the
    first retry after the initial failure) is::

        wait_i = min(backoff_seconds * (backoff_multiplier ** i), max_wait_seconds)

    Examples with ``backoff_seconds=1.0``, ``backoff_multiplier=2.0``,
    ``max_wait_seconds=60.0``:

    - Before 2nd attempt (i=0): ``min(1.0 * 2.0^0, 60) = 1.0 s``
    - Before 3rd attempt (i=1): ``min(1.0 * 2.0^1, 60) = 2.0 s``
    - Before 4th attempt (i=2): ``min(1.0 * 2.0^2, 60) = 4.0 s``

    Exception filtering
    -------------------
    ``non_retryable_exceptions`` is an optional list of fully-qualified or
    simple exception class names (e.g. ``["FileNotFoundError",
    "ValueError"]``).  When non-empty, ``is_retryable(exc)`` returns
    ``False`` for any exception whose class name or any base-class name
    matches an entry in the list, causing the executor to surface the error
    immediately without consuming remaining attempts.

    Note: ``BaseException`` subclasses that are *not* ``Exception`` subclasses
    (``KeyboardInterrupt``, ``SystemExit``, ``MemoryError``) already bypass
    the executor's ``except Exception`` clause and are never retried regardless
    of this field.

    Attributes:
        max_attempts: Total number of attempts including the first (minimum 1).
        backoff_seconds: Base wait time in seconds (minimum 0).
        backoff_multiplier: Multiplier applied per retry (minimum 1.0).
        max_wait_seconds: Upper bound on computed wait time (minimum 0).
            Prevents astronomically large waits with high max_attempts +
            exponential backoff. Default 60.0 s.
        non_retryable_exceptions: Simple or qualified exception class names
            that should NOT be retried. Empty list (default) = retry all
            ``Exception`` subclasses.
    """

    max_attempts: int = 1
    backoff_seconds: float = 0.0
    backoff_multiplier: float = 1.0
    max_wait_seconds: float = 60.0
    non_retryable_exceptions: list[str] = []

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

    @field_validator("max_wait_seconds")
    @classmethod
    def _non_negative_max_wait(cls, v: float) -> float:
        if v < 0:
            raise ValueError("max_wait_seconds must be >= 0")
        return v

    def wait_before_attempt(self, attempt_index: int) -> float:
        """Return the wait time in seconds before retry ``attempt_index`` (0-indexed).

        ``attempt_index=0`` → wait before the 2nd overall attempt (first retry).
        ``attempt_index=1`` → wait before the 3rd overall attempt (second retry).

        The result is capped at ``max_wait_seconds`` to prevent astronomically
        large waits when ``max_attempts`` is large and backoff is exponential.
        """
        raw = self.backoff_seconds * (self.backoff_multiplier ** attempt_index)
        return min(raw, self.max_wait_seconds)

    def is_retryable(self, exc: BaseException) -> bool:
        """Return ``False`` if ``exc`` matches any entry in ``non_retryable_exceptions``.

        Matching is done against the simple class name and all base-class names
        in the MRO, so ``"Exception"`` would block everything — use with care.
        An empty ``non_retryable_exceptions`` list (the default) always returns
        ``True`` (retry everything that reaches the executor's except clause).
        """
        if not self.non_retryable_exceptions:
            return True
        mro_names = {cls.__name__ for cls in type(exc).__mro__}
        return not bool(mro_names & set(self.non_retryable_exceptions))
