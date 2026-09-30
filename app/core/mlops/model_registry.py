# app/core/mlops/model_registry.py
"""
Bounded Context:  BC6 — Observability & Storage / ML lifecycle
Responsibility:   Lightweight model registry on top of artifact aliases
                  (name → staging/prod/latest pointers + source run).
Owns:             register_model, list_models, get_model, request_prod,
                  approve_prod; run eligibility checks (run must exist and
                  have succeeded); the request_prod→approve_prod gate (the
                  prod stage is only written by approve_prod); locked,
                  atomic registry read-modify-write.
Public Surface:   Same helpers for API / UI / MCP; ModelRegistryError,
                  ModelRunNotFound (→404), ModelRunNotSucceeded (→409),
                  ProdRequiresApproval (→403).
Must NOT:         Import app.domain or app.api; must not call remote MLflow.
Dependencies:     json, os, pathlib, datetime, tempfile; config (runs_dir);
                  run_status; workspace_paths.publish_alias;
                  project_pipelines.resource_lock; audit (lazy).
Reason To Change: Registry schema or stage-transition policy changes.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
STAGES = ("staging", "prod", "latest")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ModelRegistryError(ValueError):
    """Base for registry validation errors (ValueError for back-compat)."""


class ModelRunNotFound(ModelRegistryError):
    """The referenced run (or its artifacts) does not exist → HTTP 404."""


class ModelRunNotSucceeded(ModelRegistryError):
    """The referenced run exists but has not succeeded → HTTP 409."""

    def __init__(self, run_id: str, status: str):
        self.run_id = run_id
        self.status = status
        super().__init__(
            f"Run '{run_id}' has status '{status}'; only succeeded runs can be registered"
        )


class ProdRequiresApproval(ModelRegistryError):
    """``stage=prod`` outside approve_prod → HTTP 403."""


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


def _registry_lock(path: Path):
    """Exclusive (threads + processes) lock for registry read-modify-write."""
    from app.core.pipelines.project_pipelines import resource_lock

    return resource_lock(path.with_name(path.name + ".lock"))


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".reg-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        tmp.replace(path)
    except BaseException:
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
    """Register / update a model from a run and point an alias stage.

    ``stage="prod"`` is refused (:class:`ProdRequiresApproval`): prod is only
    reachable through :func:`request_prod` → :func:`approve_prod`.
    """
    stage_s = (stage or "staging").strip().lower()
    if stage_s == "prod":
        raise ProdRequiresApproval(
            "stage 'prod' cannot be set directly; call request-prod then "
            "approve-prod for this model"
        )
    return _register(
        name,
        run_id=run_id,
        slug=slug,
        stage=stage_s,
        description=description,
        actor=actor,
        base_dir=base_dir,
    )


def _runs_root(base_dir: str | Path | None) -> Path:
    if base_dir is not None:
        return Path(base_dir) / "runs"
    from app.core.config import runs_dir

    return runs_dir()


def _require_succeeded_run(run_id: str, base_dir: str | Path | None) -> None:
    """Raise unless ``runs/<run_id>/meta.json`` exists with a succeeded status."""
    if not _SAFE_RUN_ID.match(run_id) or run_id in (".", ".."):
        raise ModelRegistryError(f"Invalid run_id {run_id!r}")
    meta_path = _runs_root(base_dir) / run_id / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelRunNotFound(f"Run '{run_id}' not found") from exc
    except Exception as exc:
        raise ModelRunNotSucceeded(run_id, "unreadable") from exc
    raw_status = str((meta or {}).get("status") or "unknown") if isinstance(meta, dict) else "unknown"
    try:
        from app.core.runs.run_status import normalize_status

        status = normalize_status(raw_status)
    except Exception:
        status = raw_status.strip().lower()
    if status not in ("succeeded", "success"):
        raise ModelRunNotSucceeded(run_id, status)


def _register(
    name: str,
    *,
    run_id: str,
    slug: str,
    stage: str,
    description: str | None,
    actor: str,
    base_dir: str | Path | None,
    clear_pending_prod: bool = False,
) -> dict[str, Any]:
    if not _SAFE_NAME.match(name or ""):
        raise ValueError(f"Invalid model name {name!r}")
    stage_s = (stage or "staging").strip().lower()
    if stage_s not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    run_id = (run_id or "").strip()
    slug = (slug or "").strip()
    if not run_id or not slug:
        raise ValueError("run_id and slug are required")
    _require_succeeded_run(run_id, base_dir)

    from app.core.paths.workspace_paths import publish_alias

    path = registry_path(base_dir)
    # Alias flip + registry write under one lock so the alias and the
    # registry record can never disagree about which run a stage points at.
    with _registry_lock(path):
        try:
            pointer = publish_alias(slug, run_id, stage_s if stage_s != "latest" else "latest")
        except FileNotFoundError as exc:
            raise ModelRunNotFound(
                f"Run '{run_id}' has no artifacts under slug '{slug}'"
            ) from exc
        now = datetime.now(timezone.utc).isoformat()
        return _register_locked(
            path,
            name,
            run_id=run_id,
            slug=slug,
            stage_s=stage_s,
            pointer=pointer,
            now=now,
            description=description,
            actor=actor,
            clear_pending_prod=clear_pending_prod,
        )


def _register_locked(
    path: Path,
    name: str,
    *,
    run_id: str,
    slug: str,
    stage_s: str,
    pointer: str,
    now: str,
    description: str | None,
    actor: str,
    clear_pending_prod: bool,
) -> dict[str, Any]:
    data = _load(path)
    models = data.setdefault("models", {})
    prev = models.get(name) if isinstance(models.get(name), dict) else {}
    stages = dict(prev.get("stages") or {})
    stages[stage_s] = {"run_id": run_id, "slug": slug, "path": pointer, "updated_at": now}
    pending = prev.get("pending_prod")
    if clear_pending_prod:
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
    _audit_register(actor, name, stage_s, run_id, slug)
    return {"name": name, **rec}


def _audit_register(actor: str, name: str, stage_s: str, run_id: str, slug: str) -> None:
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=actor,
            action="model.register",
            resource_type="model",
            resource_id=f"{name}@{stage_s}",
            meta={"run_id": run_id, "slug": slug},
        )
    except Exception:
        pass


def request_prod(
    name: str,
    *,
    run_id: str | None = None,
    actor: str = "api",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Queue prod transition from staging (or explicit run_id)."""
    if not _SAFE_NAME.match(name or ""):
        raise ValueError(f"Invalid model name {name!r}")
    path = registry_path(base_dir)
    with _registry_lock(path):
        cur, rid = _request_prod_locked(path, name, run_id=run_id, actor=actor, base_dir=base_dir)
    try:
        from app.core.trust.audit import record_audit

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


def _request_prod_locked(
    path: Path,
    name: str,
    *,
    run_id: str | None,
    actor: str,
    base_dir: str | Path | None,
) -> tuple[dict[str, Any], str]:
    rec = get_model(name, base_dir=base_dir)
    stages = rec.get("stages") or {}
    staging = stages.get("staging") if isinstance(stages.get("staging"), dict) else None
    rid = (run_id or (staging or {}).get("run_id") or "").strip()
    slug = str(rec.get("slug") or (staging or {}).get("slug") or "")
    if not rid or not slug:
        raise ValueError("Need staging stage or run_id to request prod")
    prod = stages.get("prod") if isinstance(stages.get("prod"), dict) else None
    if prod and prod.get("run_id") == rid:
        raise ValueError(f"Run '{rid}' is already in prod for '{name}'")
    pending = rec.get("pending_prod")
    if isinstance(pending, dict) and pending.get("run_id") == rid:
        raise ValueError(f"Run '{rid}' already has a pending prod request for '{name}'")
    # Fail at request time rather than at approval for a bogus/failed run.
    _require_succeeded_run(rid, base_dir)
    now = datetime.now(timezone.utc).isoformat()
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
    return cur, rid


def approve_prod(
    name: str,
    *,
    actor: str = "api",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Approve pending_prod → register at prod stage (the only prod path).

    The whole approve (read pending → publish alias → write) holds the
    registry lock, so two approvers cannot both consume one request. The
    lock is reentrant, so the nested :func:`_register` does not deadlock.
    """
    if not _SAFE_NAME.match(name or ""):
        raise ValueError(f"Invalid model name {name!r}")
    path = registry_path(base_dir)
    with _registry_lock(path):
        rec = get_model(name, base_dir=base_dir)
        pending = rec.get("pending_prod")
        if not isinstance(pending, dict) or not pending.get("run_id"):
            raise ValueError("No pending_prod to approve")
        return _register(
            name,
            run_id=str(pending["run_id"]),
            slug=str(pending.get("slug") or rec.get("slug") or ""),
            stage="prod",
            description=rec.get("description"),
            actor=actor,
            base_dir=base_dir,
            clear_pending_prod=True,
        )
