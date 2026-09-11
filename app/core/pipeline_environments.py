# app/core/pipeline_environments.py
"""
Bounded Context:  BC6 — Observability & Storage / project assets
Responsibility:   Version history + draft/staging/prod environment pointers
                  for project-owned pipelines.
Owns:             publish_version, promote_environment, list_versions,
                  get_environment_graph, environments helpers.
Public Surface:   Same helpers; used by projects API and schedules.
Must NOT:         Import app.domain or app.api.
Dependencies:     json, re, pathlib, tempfile, datetime; project_pipelines;
                  ir.loader; secret_policy; audit (lazy).
Reason To Change: Pipeline versioning / environment promotion policy changes.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.ir.loader import dump_ir, load_ir
from app.core.ir.secret_policy import assert_no_inline_secrets
from app.core.project_pipelines import (
    SAFE_PIPELINE_NAME_RE,
    get_pipeline,
    pipelines_dir,
    put_pipeline,
)

log = logging.getLogger(__name__)

ENV_NAMES = ("draft", "staging", "prod")
_SAFE_VERSION = re.compile(r"^v\d+$")


def _pipeline_bundle_dir(project_dir: Path, name: str) -> Path:
    if not SAFE_PIPELINE_NAME_RE.match(name or ""):
        raise ValueError(f"Invalid pipeline name {name!r}")
    return pipelines_dir(project_dir) / name


def versions_dir(project_dir: Path, name: str) -> Path:
    return _pipeline_bundle_dir(project_dir, name) / "versions"


def environments_path(project_dir: Path, name: str) -> Path:
    return _pipeline_bundle_dir(project_dir, name) / "environments.json"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".env-", suffix=".tmp")
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


def _load_envs(project_dir: Path, name: str) -> dict[str, Any]:
    path = environments_path(project_dir, name)
    if not path.is_file():
        return {"staging": None, "prod": None, "updated_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"staging": None, "prod": None, "updated_at": None}
    if not isinstance(data, dict):
        return {"staging": None, "prod": None, "updated_at": None}
    return {
        "staging": data.get("staging"),
        "prod": data.get("prod"),
        "updated_at": data.get("updated_at"),
        "pending_prod": data.get("pending_prod"),
    }


def get_environments(project_dir: Path, name: str) -> dict[str, Any]:
    """Return env pointers plus draft marker (draft = working head file)."""
    envs = _load_envs(project_dir, name)
    draft_exists = (pipelines_dir(project_dir) / f"{name}.graph.json").is_file()
    return {
        "pipeline": name,
        "draft": "head" if draft_exists else None,
        "staging": envs.get("staging"),
        "prod": envs.get("prod"),
        "pending_prod": envs.get("pending_prod"),
        "updated_at": envs.get("updated_at"),
    }


def list_versions(project_dir: Path, name: str) -> list[dict[str, Any]]:
    root = versions_dir(project_dir, name)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("v*.graph.json"), reverse=True):
        vid = path.name[: -len(".graph.json")]
        if not _SAFE_VERSION.match(vid):
            continue
        meta: dict[str, Any] = {"version": vid, "path": str(path.name)}
        try:
            meta["updated_at"] = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            pass
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                nodes = data.get("nodes")
                meta["node_count"] = len(nodes) if isinstance(nodes, list) else 0
                md = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
                meta["graph_name"] = md.get("name")
                meta["message"] = (data.get("_publish") or {}).get("message") if isinstance(data.get("_publish"), dict) else None
                meta["published_at"] = (data.get("_publish") or {}).get("published_at") if isinstance(data.get("_publish"), dict) else None
        except Exception:
            log.debug("skip version %s", path, exc_info=True)
        items.append(meta)
    return items


def get_version(project_dir: Path, name: str, version: str) -> dict[str, Any]:
    if not _SAFE_VERSION.match(version or ""):
        raise ValueError(f"Invalid version {version!r}")
    path = versions_dir(project_dir, name) / f"{version}.graph.json"
    if not path.is_file():
        raise FileNotFoundError(f"Version {version} not found for pipeline {name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid version payload")
    # Strip internal publish meta for IR consumers
    clean = {k: v for k, v in data.items() if k != "_publish"}
    load_ir(clean)
    return clean


def _next_version_id(project_dir: Path, name: str) -> str:
    root = versions_dir(project_dir, name)
    root.mkdir(parents=True, exist_ok=True)
    nums = []
    for path in root.glob("v*.graph.json"):
        m = re.match(r"^v(\d+)\.graph\.json$", path.name)
        if m:
            nums.append(int(m.group(1)))
    return f"v{(max(nums) + 1) if nums else 1}"


def publish_version(
    project_dir: Path,
    name: str,
    *,
    project_name: str,
    message: str | None = None,
    set_env: str | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    """Snapshot draft head into versions/vN and optionally point staging.

    ``set_env`` may be ``staging`` (immediate) or ``prod`` (creates pending
    approval — use promote_environment to confirm).
    """
    draft = get_pipeline(project_dir, name)
    graph = load_ir(draft)
    assert_no_inline_secrets(graph)
    out = dump_ir(graph)
    vid = _next_version_id(project_dir, name)
    now = datetime.now(timezone.utc).isoformat()
    out["_publish"] = {
        "version": vid,
        "published_at": now,
        "message": (message or "").strip()[:500] or None,
        "actor": actor,
        "project": project_name,
    }
    vpath = versions_dir(project_dir, name) / f"{vid}.graph.json"
    vpath.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(vpath.parent), prefix=f".{vid}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        tmp.replace(vpath)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    envs = _load_envs(project_dir, name)
    env_target = (set_env or "").strip().lower() or None
    if env_target == "staging":
        envs["staging"] = vid
        envs["updated_at"] = now
        _atomic_write_json(environments_path(project_dir, name), envs)
    elif env_target == "prod":
        # Require explicit approve via promote
        envs["pending_prod"] = {
            "version": vid,
            "requested_at": now,
            "requested_by": actor,
            "message": (message or "").strip()[:500] or None,
        }
        envs["updated_at"] = now
        _atomic_write_json(environments_path(project_dir, name), envs)
    elif env_target is not None:
        raise ValueError("set_env must be 'staging', 'prod', or omitted")

    try:
        from app.core.audit import record_audit

        record_audit(
            actor=actor,
            action="pipeline.publish",
            resource_type="pipeline",
            resource_id=f"{project_name}/{name}@{vid}",
            meta={"env": env_target, "message": message},
        )
    except Exception:
        pass

    return {
        "pipeline": name,
        "version": vid,
        "environments": get_environments(project_dir, name),
        "message": (message or "").strip()[:500] or None,
    }


def promote_environment(
    project_dir: Path,
    name: str,
    *,
    to_env: str,
    version: str | None = None,
    from_env: str | None = None,
    approve: bool = False,
    actor: str = "api",
) -> dict[str, Any]:
    """Point staging/prod at a version. Prod requires approve=True."""
    to_env = (to_env or "").strip().lower()
    if to_env not in ("staging", "prod"):
        raise ValueError("to_env must be staging or prod")
    envs = _load_envs(project_dir, name)

    vid = (version or "").strip() or None
    if not vid and from_env:
        fe = from_env.strip().lower()
        if fe == "staging":
            vid = envs.get("staging")
        elif fe == "draft":
            # publish first then promote
            raise ValueError("Promote from draft: publish first, then promote the version")
        elif fe == "prod":
            vid = envs.get("prod")
    if not vid and to_env == "prod" and isinstance(envs.get("pending_prod"), dict):
        vid = envs["pending_prod"].get("version")
    if not vid:
        raise ValueError("Provide version= or from_env=staging (or approve pending_prod)")
    if not _SAFE_VERSION.match(vid):
        raise ValueError(f"Invalid version {vid!r}")
    # Ensure version exists
    get_version(project_dir, name, vid)

    if to_env == "prod" and not approve:
        envs["pending_prod"] = {
            "version": vid,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "requested_by": actor,
        }
        envs["updated_at"] = envs["pending_prod"]["requested_at"]
        _atomic_write_json(environments_path(project_dir, name), envs)
        try:
            from app.core.audit import record_audit

            record_audit(
                actor=actor,
                action="pipeline.promote_request",
                resource_type="pipeline",
                resource_id=f"{name}@{vid}->prod",
                meta={"approve_required": True},
            )
        except Exception:
            pass
        return {
            "pipeline": name,
            "pending_prod": envs["pending_prod"],
            "environments": get_environments(project_dir, name),
            "status": "pending_approval",
        }

    now = datetime.now(timezone.utc).isoformat()
    envs[to_env] = vid
    if to_env == "prod":
        envs["pending_prod"] = None
    envs["updated_at"] = now
    _atomic_write_json(environments_path(project_dir, name), envs)

    try:
        from app.core.audit import record_audit

        record_audit(
            actor=actor,
            action="pipeline.promote",
            resource_type="pipeline",
            resource_id=f"{name}@{vid}->{to_env}",
            meta={"approve": approve},
        )
    except Exception:
        pass

    return {
        "pipeline": name,
        "version": vid,
        "env": to_env,
        "environments": get_environments(project_dir, name),
        "status": "promoted",
    }


def get_environment_graph(
    project_dir: Path,
    name: str,
    env: str = "draft",
) -> dict[str, Any]:
    """Resolve Graph IR for draft|staging|prod."""
    env = (env or "draft").strip().lower()
    if env == "draft":
        return get_pipeline(project_dir, name)
    envs = _load_envs(project_dir, name)
    vid = envs.get(env)
    if not vid:
        raise FileNotFoundError(f"No version pointed by environment {env!r}")
    return get_version(project_dir, name, str(vid))


def enrich_pipeline_summary(project_dir: Path, item: dict[str, Any]) -> dict[str, Any]:
    """Attach environments + version count to a list_pipelines row."""
    name = str(item.get("name") or "")
    if not name:
        return item
    try:
        envs = get_environments(project_dir, name)
        versions = list_versions(project_dir, name)
    except Exception:
        return item
    out = dict(item)
    out["environments"] = {
        "draft": envs.get("draft"),
        "staging": envs.get("staging"),
        "prod": envs.get("prod"),
        "pending_prod": envs.get("pending_prod"),
    }
    out["version_count"] = len(versions)
    out["latest_version"] = versions[0]["version"] if versions else None
    return out


def rollback_draft_to_version(
    project_dir: Path,
    name: str,
    version: str,
    *,
    project_name: str,
) -> dict[str, Any]:
    """Copy a published version back onto the draft head."""
    data = get_version(project_dir, name, version)
    return put_pipeline(project_dir, name, data, project_name=project_name)
