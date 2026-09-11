# app/core/model_registry.py
"""
Bounded Context:  BC6 — Observability & Storage / ML lifecycle
Responsibility:   Lightweight model registry on top of artifact aliases
                  (name → staging/prod/latest pointers + source run).
Owns:             register_model, list_models, get_model, transition_stage.
Public Surface:   Same helpers for API / UI.
Must NOT:         Import app.domain or app.api; must not call remote MLflow.
Dependencies:     json, pathlib, datetime; workspace_paths.publish_alias;
                  audit (lazy).
Reason To Change: Registry schema or stage-transition policy changes.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
STAGES = ("staging", "prod", "latest")


def registry_path(base_dir: str | Path | None = None) -> Path:
    if base_dir is not None:
        root = Path(base_dir)
    else:
        from app.core.config import project_dir

        root = project_dir()
    return root / "artifacts" / "_registry" / "models.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"models": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"models": {}}
    if not isinstance(data, dict):
        return {"models": {}}
    models = data.get("models")
    if not isinstance(models, dict):
        data["models"] = {}
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".reg-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def list_models(base_dir: str | Path | None = None) -> list[dict[str, Any]]:
    data = _load(registry_path(base_dir))
    rows = []
    for name, rec in sorted((data.get("models") or {}).items()):
        if isinstance(rec, dict):
            rows.append({"name": name, **rec})
    return rows


def get_model(name: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    if not _SAFE_NAME.match(name or ""):
        raise ValueError(f"Invalid model name {name!r}")
    data = _load(registry_path(base_dir))
    rec = (data.get("models") or {}).get(name)
    if not isinstance(rec, dict):
        raise FileNotFoundError(f"Model {name!r} not found")
    return {"name": name, **rec}


def register_model(
    name: str,
    *,
    run_id: str,
    slug: str,
    stage: str = "staging",
    description: str | None = None,
    actor: str = "api",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Register / update a model from a run and point an alias stage."""
    if not _SAFE_NAME.match(name or ""):
        raise ValueError(f"Invalid model name {name!r}")
    stage_s = (stage or "staging").strip().lower()
    if stage_s not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    run_id = (run_id or "").strip()
    slug = (slug or "").strip()
    if not run_id or not slug:
        raise ValueError("run_id and slug are required")

    from app.core.workspace_paths import publish_alias

    pointer = publish_alias(slug, run_id, stage_s if stage_s != "latest" else "latest")
    now = datetime.now(timezone.utc).isoformat()
    path = registry_path(base_dir)
    data = _load(path)
    models = data.setdefault("models", {})
    prev = models.get(name) if isinstance(models.get(name), dict) else {}
    stages = dict(prev.get("stages") or {})
    stages[stage_s] = {"run_id": run_id, "slug": slug, "path": pointer, "updated_at": now}
    pending = prev.get("pending_prod")
    if stage_s == "prod":
        pending = None
    rec = {
        "description": (description or prev.get("description") or "").strip()[:500] or None,
        "slug": slug,
        "stages": stages,
        "pending_prod": pending,
        "updated_at": now,
        "updated_by": actor,
        "source_run_id": run_id,
    }
    models[name] = rec
    _save(path, data)
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=actor,
            action="model.register",
            resource_type="model",
            resource_id=f"{name}@{stage_s}",
            meta={"run_id": run_id, "slug": slug},
        )
    except Exception:
        pass
    return {"name": name, **rec}


def request_prod(
    name: str,
    *,
    run_id: str | None = None,
    actor: str = "api",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Queue prod transition from staging (or explicit run_id)."""
    rec = get_model(name, base_dir=base_dir)
    stages = rec.get("stages") or {}
    staging = stages.get("staging") if isinstance(stages.get("staging"), dict) else None
    rid = (run_id or (staging or {}).get("run_id") or "").strip()
    slug = str(rec.get("slug") or (staging or {}).get("slug") or "")
    if not rid or not slug:
        raise ValueError("Need staging stage or run_id to request prod")
    now = datetime.now(timezone.utc).isoformat()
    path = registry_path(base_dir)
    data = _load(path)
    models = data.setdefault("models", {})
    cur = dict(models.get(name) or rec)
    cur["pending_prod"] = {
        "run_id": rid,
        "slug": slug,
        "requested_at": now,
        "requested_by": actor,
    }
    cur["updated_at"] = now
    models[name] = cur
    _save(path, data)
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=actor,
            action="model.promote_request",
            resource_type="model",
            resource_id=f"{name}->prod",
            meta={"run_id": rid},
        )
    except Exception:
        pass
    return {"name": name, **cur, "status": "pending_approval"}


def approve_prod(
    name: str,
    *,
    actor: str = "api",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Approve pending_prod → register at prod stage."""
    rec = get_model(name, base_dir=base_dir)
    pending = rec.get("pending_prod")
    if not isinstance(pending, dict) or not pending.get("run_id"):
        raise ValueError("No pending_prod to approve")
    return register_model(
        name,
        run_id=str(pending["run_id"]),
        slug=str(pending.get("slug") or rec.get("slug") or ""),
        stage="prod",
        description=rec.get("description"),
        actor=actor,
        base_dir=base_dir,
    )
