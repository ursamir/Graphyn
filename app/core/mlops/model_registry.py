# app/core/mlops/model_registry.py
"""
Bounded Context:  BC6 — Observability & Storage / ML lifecycle
Responsibility:   Lightweight model registry on top of artifact aliases
                  (name → staging/prod/latest pointers + source run).
Owns:             register_model, list_models, get_model, request_prod,
                  approve_prod, describe_model(s) (read-time stage →
                  real model file resolution, migrating legacy alias-dir
                  stages), resolve_run_artifact (model_path / node_id /
                  best path → run model row; compiled_untrained guard); run eligibility checks (run must exist and
                  have succeeded); the request_prod→approve_prod gate (the
                  prod stage is only written by approve_prod); locked,
                  atomic registry read-modify-write.
Public Surface:   Same helpers for API / UI / MCP; ModelRegistryError,
                  ModelRunNotFound (→404), ModelRunNotSucceeded (→409),
                  ProdRequiresApproval (→403), ModelUntrained (→422
                  ``compiled_untrained``), ModelArtifactNotFound (→422).
Must NOT:         Import app.domain or app.api; must not call remote MLflow.
Dependencies:     json, os, pathlib, datetime, tempfile; config (runs_dir);
                  run_status; workspace_paths.publish_alias;
                  project_pipelines.resource_lock; audit (lazy);
                  app.core.runs.run_summary (lazy — run model rows).
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


class ModelUntrained(ModelRegistryError):
    """Selected artifact is a compiled-but-untrained model_builder output → 422.

    Pass ``allow_untrained=True`` to register it anyway.
    """

    def __init__(self, artifact: dict[str, Any]):
        self.artifact = artifact
        super().__init__(
            f"Artifact {artifact.get('path')!r} (node {artifact.get('node_id')!r}) is a "
            "compiled_untrained model_builder output — register the trainer's model "
            "instead, or pass allow_untrained=true"
        )


class ModelArtifactNotFound(ModelRegistryError):
    """``model_path`` / ``node_id`` does not match a model file of the run → 422."""


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
    node_id: str | None = None,
    model_path: str | None = None,
    allow_untrained: bool = False,
) -> dict[str, Any]:
    """Register / update a model from a run and point an alias stage.

    ``stage="prod"`` is refused (:class:`ProdRequiresApproval`): prod is only
    reachable through :func:`request_prod` → :func:`approve_prod`.

    The stage records the run's real model file/dir (``artifact_path``,
    also returned as ``path``): ``model_path`` (from GET /runs/{id}/models)
    or ``node_id`` pick it explicitly; otherwise a node id equal to *name*,
    else the best path's trained model. A ``compiled_untrained``
    (model_builder) artifact raises :class:`ModelUntrained` unless
    ``allow_untrained``. ``slug`` may be empty — derived from the artifact.
    """
    stage_s = (stage or "staging").strip().lower()
    if stage_s == "prod":
        raise ProdRequiresApproval(
            "stage 'prod' cannot be set directly; call request-prod then "
            "approve-prod for this model"
        )
    run_id_s = (run_id or "").strip()
    if run_id_s:
        _require_succeeded_run(run_id_s, base_dir)
    artifact = resolve_run_artifact(
        run_id_s,
        base_dir=base_dir,
        name=name,
        node_id=node_id,
        model_path=model_path,
    )
    if artifact is not None and artifact.get("kind") == "compiled_untrained" and not allow_untrained:
        raise ModelUntrained(artifact)
    if not (slug or "").strip() and artifact is not None:
        slug = _slug_from_artifact_path(str(artifact.get("path") or ""), run_id_s) or ""
    return _register(
        name,
        run_id=run_id,
        slug=slug,
        stage=stage_s,
        description=description,
        actor=actor,
        base_dir=base_dir,
        artifact=_artifact_record(artifact),
    )


_ARTIFACT_FIELDS = ("path", "node_id", "path_id", "format", "kind")


def _artifact_record(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(artifact, dict) or not artifact.get("path"):
        return None
    return {
        "artifact_path": artifact.get("path"),
        "node_id": artifact.get("node_id"),
        "path_id": artifact.get("path_id"),
        "format": artifact.get("format"),
        "artifact_kind": artifact.get("kind"),
    }


def _slug_from_artifact_path(path: str, run_id: str) -> str | None:
    """``workspace/artifacts/<slug>/runs/<run_id>/...`` → ``<slug>``."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    try:
        i = parts.index("artifacts")
    except ValueError:
        return None
    rest = parts[i + 1 :]
    if len(rest) >= 3 and rest[1] == "runs" and (not run_id or rest[2] == run_id):
        return rest[0]
    return None


def _run_models(run_id: str, base_dir: str | Path | None) -> list[dict[str, Any]]:
    if not run_id or not _SAFE_RUN_ID.match(run_id):
        return []
    run_path = _runs_root(base_dir) / run_id
    if not run_path.is_dir():
        return []
    try:
        from app.core.runs.run_summary import run_models

        return run_models(run_id, run_path)
    except Exception:
        log.debug("run_models failed for %s", run_id, exc_info=True)
        return []


def _best_path_id(run_id: str, base_dir: str | Path | None) -> str | None:
    try:
        from app.core.runs.run_summary import run_insights

        ins = run_insights(run_id, _runs_root(base_dir) / run_id)
        return ((ins.get("summary") or {}).get("best_path_id")) or None
    except Exception:
        return None


def resolve_run_artifact(
    run_id: str,
    *,
    base_dir: str | Path | None = None,
    name: str | None = None,
    node_id: str | None = None,
    model_path: str | None = None,
    prefer_kind: tuple[str, ...] = ("trained", "optimized", "compiled_untrained"),
) -> dict[str, Any] | None:
    """Pick the run model row (GET /runs/{id}/models) a registration refers to.

    Returns None when the run produced no recognizable model files (legacy
    runs) — the registration then keeps the alias-dir pointer only.
    Raises :class:`ModelArtifactNotFound` for an explicit ``model_path`` /
    ``node_id`` that matches nothing.
    """
    rows = _run_models(run_id, base_dir)
    if model_path:
        from app.core.runs.run_summary import resolve_workspace_path

        target = resolve_workspace_path(model_path)
        for row in rows:
            rp = resolve_workspace_path(row.get("path"))
            if target is not None and rp is not None and os.path.abspath(rp) == os.path.abspath(target):
                return row
        raise ModelArtifactNotFound(
            f"model_path {model_path!r} is not a model file produced by run {run_id!r}"
        )
    if not rows:
        if node_id:
            raise ModelArtifactNotFound(f"Run {run_id!r} has no model files for node {node_id!r}")
        return None

    def _rank(row: dict[str, Any]) -> int:
        kind = str(row.get("kind") or "")
        return prefer_kind.index(kind) if kind in prefer_kind else len(prefer_kind)

    if node_id:
        hits = [r for r in rows if r.get("node_id") == node_id]
        if not hits:
            raise ModelArtifactNotFound(f"Run {run_id!r} has no model files for node {node_id!r}")
        return sorted(hits, key=_rank)[0]
    if name:
        hits = [r for r in rows if r.get("node_id") == name]
        if hits:
            return sorted(hits, key=_rank)[0]
    best = _best_path_id(run_id, base_dir)
    pool = [r for r in rows if best and r.get("path_id") == best] or rows
    return sorted(pool, key=_rank)[0]


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
    artifact: dict[str, Any] | None = None,
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
            artifact=artifact,
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
    artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = _load(path)
    models = data.setdefault("models", {})
    prev = models.get(name) if isinstance(models.get(name), dict) else {}
    stages = dict(prev.get("stages") or {})
    stage_rec: dict[str, Any] = {"run_id": run_id, "slug": slug, "path": pointer, "updated_at": now}
    if isinstance(artifact, dict) and artifact.get("artifact_path"):
        # ``path`` is the real model file/dir (what Ship / edge_optimizer
        # load); the stage alias dir stays available as ``alias_path``.
        stage_rec.update({k: v for k, v in artifact.items() if v is not None})
        stage_rec["alias_path"] = pointer
        stage_rec["path"] = artifact["artifact_path"]
    stages[stage_s] = stage_rec
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
    if staging and staging.get("run_id") == rid and staging.get("artifact_path"):
        for key in ("artifact_path", "node_id", "path_id", "format", "artifact_kind"):
            if staging.get(key) is not None:
                cur["pending_prod"][key] = staging[key]
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
            artifact=_pending_artifact(pending, rec, base_dir),
        )


def _pending_artifact(
    pending: dict[str, Any], rec: dict[str, Any], base_dir: str | Path | None
) -> dict[str, Any] | None:
    """Artifact for approve_prod: carried by the request, else resolved now."""
    if pending.get("artifact_path"):
        return {k: pending.get(k) for k in ("artifact_path", "node_id", "path_id", "format", "artifact_kind")}
    try:
        row = resolve_run_artifact(
            str(pending.get("run_id") or ""), base_dir=base_dir, name=str(rec.get("name") or "")
        )
    except ModelRegistryError:
        row = None
    return _artifact_record(row)


# ── read-time enrichment (GET /models, /models/{name}) ────────────────────────


def _stage_artifact(
    name: str, stage: dict[str, Any], base_dir: str | Path | None
) -> dict[str, Any] | None:
    """Resolve a stage to its model row; migrates legacy alias-dir stages."""
    run_id = str(stage.get("run_id") or "")
    rows = _run_models(run_id, base_dir)
    if not rows:
        return None
    want = stage.get("artifact_path")
    if want:
        from app.core.runs.run_summary import resolve_workspace_path

        target = resolve_workspace_path(str(want))
        for row in rows:
            rp = resolve_workspace_path(row.get("path"))
            if target is not None and rp is not None and os.path.abspath(rp) == os.path.abspath(target):
                return row
    try:
        return resolve_run_artifact(
            run_id,
            base_dir=base_dir,
            name=name,
            node_id=stage.get("node_id") or None,
        )
    except ModelRegistryError:
        return None


def _enrich_stage(name: str, stage_name: str, stage: dict[str, Any], base_dir: str | Path | None) -> dict[str, Any]:
    out = dict(stage)
    out["kind"] = "model_stage"
    out["stage"] = stage_name
    out.setdefault("alias_path", stage.get("path"))
    row = _stage_artifact(name, stage, base_dir)
    if row is None:
        out.setdefault("artifact_path", None)
        out["exists"] = bool(stage.get("artifact_path")) and _artifact_exists(str(stage.get("artifact_path")))
        return out
    out.update(
        {
            "artifact_path": row.get("path"),
            "path": row.get("path"),
            "format": row.get("format"),
            "artifact_kind": row.get("kind"),
            "node_id": row.get("node_id"),
            "path_id": row.get("path_id"),
            "path_label": row.get("path_label"),
            "size_bytes": row.get("size_bytes"),
            "created_at": row.get("created_at"),
            "metrics": row.get("metrics") or {},
            "labels": row.get("labels") or [],
            "exists": _artifact_exists(str(row.get("path") or "")),
            "source_run_id": stage.get("run_id"),
        }
    )
    try:
        from app.core.runs.run_summary import run_insights

        ins = run_insights(str(stage.get("run_id")), _runs_root(base_dir) / str(stage.get("run_id")))
        out["source_run_display_name"] = ins.get("display_name")
    except Exception:
        pass
    return out


def _artifact_exists(raw: str) -> bool:
    try:
        from app.core.runs.run_summary import resolve_workspace_path

        p = resolve_workspace_path(raw)
        return bool(p is not None and p.exists())
    except OSError:
        return False


def describe_model(name: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    """:func:`get_model` + per-stage resolved artifact (path/format/size/metrics/labels)."""
    rec = get_model(name, base_dir=base_dir)
    stages = rec.get("stages") if isinstance(rec.get("stages"), dict) else {}
    out = dict(rec)
    out["stages"] = {
        sname: _enrich_stage(name, sname, srec, base_dir)
        for sname, srec in stages.items()
        if isinstance(srec, dict)
    }
    pending = rec.get("pending_prod")
    if isinstance(pending, dict):
        out["pending_prod"] = {**pending, "kind": "model_stage", "stage": "pending_prod"}
    return out


def describe_models(base_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """:func:`list_models` rows with enriched stages (see :func:`describe_model`)."""
    out = []
    for row in list_models(base_dir=base_dir):
        try:
            out.append(describe_model(str(row.get("name")), base_dir=base_dir))
        except Exception:
            out.append(row)
    return out
