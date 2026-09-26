# app/core/credentials/errors.py
"""Credential-store errors. NeedsCredentialsError is fail-closed at runtime."""
from __future__ import annotations


class CredentialError(ValueError):
    """Invalid credential payload, kind, or store operation."""


class NeedsCredentialsError(RuntimeError):
    """Raised when a step needs a connection/env that is not configured.

    Callers must fail closed — do not silently skip the step.
    """


class CredentialNotFoundError(LookupError):
    """Connection id not found or revoked."""
