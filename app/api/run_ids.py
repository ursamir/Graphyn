# app/api/run_ids.py
"""
Bounded Context:  REST API Layer
Responsibility:   One HTTP mapping for user-supplied run ids (path, query or
                  body): full id or unique prefix >= 8 chars → full id.
Owns:             resolve_run_id_http(), run_dir_http(), run_id_error_detail().
Public Surface:   resolve_run_id_http(raw, *, field, allow_missing, runs_root)
                  -> str; run_dir_http(raw, *, runs_root) -> Path. Errors: 400
                  ``invalid_run_id``, 404 ``run_not_found``, 409
                  ``run_id_ambiguous`` (detail carries ``matches``).
Must NOT:         Contain run persistence logic — delegates to
                  app.core.runs.run_resolve.
Dependencies:     fastapi, app.core.config.runs_dir, app.core.runs.run_resolve.
Reason To Change: Run id prefix policy or the error envelope changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException


def run_id_error_detail(code: str, raw: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "error": code, "run_id": raw, "message": message, **extra}


def resolve_run_id_http(
    raw: Any,
    *,
    field: str = "run_id",
    allow_missing: bool = False,
    runs_root: str | Path | None = None,
) -> str:
    """Return the FULL run id for ``raw`` or raise a typed HTTPException.

    ``allow_missing=True`` returns the stripped input unchanged when no run
    matches or the id is malformed (callers that tolerate unknown ids, e.g.
    compare); an ambiguous prefix still raises 409.
    """
    from app.core.config import runs_dir
    from app.core.runs.run_resolve import MIN_PREFIX, RunIdAmbiguous, RunIdNotFound, resolve_run_id

    rid = str(raw or "").strip()
    try:
        full = resolve_run_id(runs_root if runs_root is not None else runs_dir(), rid)
    except RunIdAmbiguous as exc:
        raise HTTPException(
            status_code=409,
            detail=run_id_error_detail(
                "run_id_ambiguous",
                rid,
                f"Run id prefix '{rid}' matches {len(exc.matches)} runs — "
                "use more characters or the full run id.",
                matches=exc.matches[:20],
                field=field,
            ),
        ) from exc
    except RunIdNotFound as exc:
        if allow_missing:
            return rid
        hint = (
            f" (prefixes need at least {MIN_PREFIX} characters)" if len(rid) < MIN_PREFIX else ""
        )
        raise HTTPException(
            status_code=404,
            detail=run_id_error_detail(
                "run_not_found", rid, f"No run found with id '{rid}'{hint}.", field=field
            ),
        ) from exc
    except ValueError as exc:
        if allow_missing:
            return rid
        raise HTTPException(
            status_code=400,
            detail=run_id_error_detail("invalid_run_id", rid, f"Invalid run id '{rid}'.", field=field),
        ) from exc
    return full


def run_dir_http(raw: Any, *, runs_root: str | Path | None = None) -> Path:
    """Resolved run directory (inside the runs root) for ``raw``."""
    from app.core.config import runs_dir

    root = Path(runs_root if runs_root is not None else runs_dir()).resolve()
    full = resolve_run_id_http(raw, runs_root=root)
    path = (root / full).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(
            status_code=400,
            detail=run_id_error_detail("invalid_run_id", str(raw), f"Invalid run id '{raw}'."),
        )
    return path
