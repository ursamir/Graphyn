# app/api/safe_json.py
"""
Bounded Context:  API (HTTP transport)
Responsibility:   Default JSON response class that never 500s on NaN/Inf.
Owns:             SafeJSONResponse
Public Surface:   SafeJSONResponse
Must NOT:         Contain business logic.
Dependencies:     starlette, app.core.utils.json_safe
Reason To Change: Response encoding policy changes.

Installed as ``FastAPI(default_response_class=...)`` so every route (run list,
run detail, metrics, experiments, ...) serialises non-finite floats as
``null`` instead of raising ``ValueError: Out of range float values are not
JSON compliant`` from Starlette's strict encoder.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.responses import JSONResponse

from app.core.utils.json_safe import json_safe


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        try:
            return json.dumps(
                content, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
            ).encode("utf-8")
        except ValueError:
            # Only pay for the recursive walk when a non-finite float is present.
            return json.dumps(
                json_safe(content), ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
            ).encode("utf-8")
