# app/core/utils/json_safe.py
"""
Bounded Context:  Shared kernel (utilities)
Responsibility:   Make arbitrary payloads strict-JSON safe by replacing
                  non-finite floats (NaN, +/-Infinity) with ``None``.
Owns:             json_safe, has_non_finite
Public Surface:   json_safe, has_non_finite
Must NOT:         Import from app.api or app.domain.
Dependencies:     stdlib
Reason To Change: Policy for non-finite numbers changes.

Policy (F19): a metric that is undefined (e.g. ROC AUC on an eval split that
lacks a class) is reported as ``null`` — never ``NaN``, which strict JSON
(RFC 8259) cannot carry and which made ``GET /runs`` return 500.
"""

from __future__ import annotations

import math
from typing import Any


def json_safe(obj: Any) -> Any:
    """Return *obj* with every non-finite float replaced by ``None``.

    dicts / lists / tuples are rebuilt only when they contain such a value;
    everything else (including numpy floats, which subclass ``float``) is
    handled by the same rule and other objects are returned unchanged.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def has_non_finite(obj: Any) -> bool:
    if isinstance(obj, float):
        return not math.isfinite(obj)
    if isinstance(obj, dict):
        return any(has_non_finite(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(has_non_finite(v) for v in obj)
    return False
