# app/mcp/handlers/journey.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   P0 J1–J3 MCP tools (pipelines, runs, templates, models,
                  schedules/webhooks, readiness) for journey parity (§21.3).
Owns:             Handler functions + schemas registered via tool_registry.
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA
Must NOT:         Import app.domain except ProjectManager via lazy require;
                  never return secret values.
Dependencies:     core project_pipelines, pipeline_environments, schedules,
                  webhook, model_registry, run helpers, templates paths.
Reason To Change: New J1–J3 MCP tool or schema change.
"""
from __future__ import annotations

from typing import Any


def _err(error_type: str, message: str) -> dict[str, Any]:
    return {"error": True, "error_type": error_type, "message": message}


def _require_project_dir(project: str):
    from app.domain.project_manager import ProjectManager

    name = (project or "").strip()
    if not name:
        raise ValueError("project is required")
    return ProjectManager()._require_project(name), name


def _meta_props() -> dict[str, Any]:
    return {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        }
    }


# ── Pipelines (J1) ────────────────────────────────────────────────────────────

LIST_PIPELINES_DESCRIPTION = (
    "List workspace pipelines for a project, including env pointers when present."
)
LIST_PIPELINES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string", "description": "Workspace/project name."},
        **_meta_props(),
    },
    "required": ["project"],
    "additionalProperties": False,
}

GET_PIPELINE_DESCRIPTION = (
    "Get a project pipeline draft IR, or an env-resolved graph when env is set."
)
GET_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "env": {
            "type": "string",
            "description": "draft (default), staging, or prod",
        },
        **_meta_props(),
    },
    "required": ["project", "pipeline"],
    "additionalProperties": False,
}

SAVE_PIPELINE_DESCRIPTION = (
    "Save draft Graph IR for a project pipeline (secret fail-closed)."
)
SAVE_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "graph": {"type": "object", "description": "Graph IR payload"},
        **_meta_props(),
    },
    "required": ["project", "pipeline", "graph"],
    "additionalProperties": False,
}

PUBLISH_PIPELINE_DESCRIPTION = (
    "Publish draft pipeline to a new version; optional set_env staging|prod."
)
PUBLISH_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "message": {"type": "string"},
        "set_env": {"type": "string"},
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project", "pipeline"],
    "additionalProperties": False,
}

PROMOTE_PIPELINE_DESCRIPTION = (
    "Promote a pipeline version to staging/prod (prod requires approve=true)."
)
PROMOTE_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "to_env": {"type": "string"},
        "version": {"type": "string"},
        "from_env": {"type": "string"},
        "approve": {"type": "boolean"},
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project", "pipeline", "to_env"],
    "additionalProperties": False,
}

ROLLBACK_PIPELINE_DESCRIPTION = (
    "Copy a published pipeline version back onto the draft head."
)
ROLLBACK_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "version": {"type": "string"},
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project", "pipeline", "version"],
    "additionalProperties": False,
}


def list_pipelines_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipeline_environments import enrich_pipeline_summary
    from app.core.project_pipelines import list_pipelines

    args = arguments or {}
    try:
        project_dir, _ = _require_project_dir(str(args.get("project") or ""))
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))
    rows = [enrich_pipeline_summary(project_dir, row) for row in list_pipelines(project_dir)]
    return {"pipelines": rows, "count": len(rows)}


def get_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipeline_environments import get_environment_graph
    from app.core.project_pipelines import get_pipeline

    args = arguments or {}
    pipeline = str(args.get("pipeline") or "").strip()
    env = str(args.get("env") or "draft").strip().lower()
    try:
        project_dir, _ = _require_project_dir(str(args.get("project") or ""))
        if env and env != "draft":
            return get_environment_graph(project_dir, pipeline, env)
        return get_pipeline(project_dir, pipeline)
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def save_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.ir.secret_policy import InlineSecretError
    from app.core.project_pipelines import put_pipeline

    args = arguments or {}
    pipeline = str(args.get("pipeline") or "").strip()
    graph = args.get("graph")
    if not isinstance(graph, dict):
        return _err("validation_failed", "graph object required")
    try:
        project_dir, name = _require_project_dir(str(args.get("project") or ""))
        return put_pipeline(project_dir, pipeline, graph, project_name=name)
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except InlineSecretError as exc:
        return _err("secret_in_ir", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def publish_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipeline_environments import publish_version

    args = arguments or {}
    try:
        project_dir, name = _require_project_dir(str(args.get("project") or ""))
        return publish_version(
            project_dir,
            str(args.get("pipeline") or "").strip(),
            project_name=name,
            message=args.get("message"),
            set_env=args.get("set_env"),
            actor=str(args.get("actor") or "mcp"),
        )
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def promote_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipeline_environments import promote_environment

    args = arguments or {}
    try:
        project_dir, _ = _require_project_dir(str(args.get("project") or ""))
        return promote_environment(
            project_dir,
            str(args.get("pipeline") or "").strip(),
            to_env=str(args.get("to_env") or "").strip(),
            version=args.get("version"),
            from_env=args.get("from_env"),
            approve=bool(args.get("approve")),
            actor=str(args.get("actor") or "mcp"),
        )
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def rollback_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.audit import record_audit
    from app.core.pipeline_environments import rollback_draft_to_version

    args = arguments or {}
    pipeline = str(args.get("pipeline") or "").strip()
    version = str(args.get("version") or "").strip()
    try:
        project_dir, name = _require_project_dir(str(args.get("project") or ""))
        graph = rollback_draft_to_version(
            project_dir, pipeline, version, project_name=name
        )
        record_audit(
            actor=str(args.get("actor") or "mcp"),
            action="pipeline.rollback",
            resource_type="pipeline",
            resource_id=f"{name}/{pipeline}@{version}",
            meta={},
        )
        return {"pipeline": pipeline, "version": version, "graph": graph}
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


# ── Runs (J1/J2/J6) ───────────────────────────────────────────────────────────

LIST_RUNS_DESCRIPTION = "List pipeline runs (newest first), optional project/status filter."
LIST_RUNS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "status": {"type": "string"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        **_meta_props(),
    },
    "additionalProperties": False,
}

GET_RUN_DESCRIPTION = "Get run metadata for a run_id."
GET_RUN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        **_meta_props(),
    },
    "required": ["run_id"],
    "additionalProperties": False,
}

GET_RUN_OUTPUTS_DESCRIPTION = "List downloadable output file descriptors for a run."
GET_RUN_OUTPUTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        **_meta_props(),
    },
    "required": ["run_id"],
    "additionalProperties": False,
}


def list_runs_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json
    from pathlib import Path

    from app.core.config import runs_dir
    from app.core.run_project import normalize_project_name, project_matches
    from app.core.run_status import normalize_status

    args = arguments or {}
    limit = max(1, min(int(args.get("limit") or 50), 500))
    offset = max(0, int(args.get("offset") or 0))
    needle = normalize_project_name(args.get("project"))
    status_filter = str(args.get("status") or "").strip().lower() or None

    root = runs_dir()
    if not root.exists():
        return {"runs": [], "count": 0}
    try:
        entries = sorted(
            (e for e in root.iterdir() if e.is_dir()),
            key=lambda e: e.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return {"runs": [], "count": 0}

    rows: list[dict[str, Any]] = []
    for entry in entries:
        meta_path = entry / "meta.json"
        meta: dict[str, Any] = {"run_id": entry.name}
        if meta_path.is_file():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta.update(loaded)
            except Exception:
                pass
        if needle and not project_matches(meta, needle):
            continue
        if "status" in meta:
            meta["status"] = normalize_status(str(meta.get("status")))
        if status_filter and str(meta.get("status") or "").lower() != status_filter:
            continue
        rows.append(meta)
    page = rows[offset : offset + limit]
    return {"runs": page, "count": len(page), "total_matched": len(rows)}


def get_run_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json

    from app.core.config import runs_dir
    from app.core.run_status import normalize_status

    args = arguments or {}
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return _err("validation_failed", "run_id required")
    path = runs_dir() / run_id / "meta.json"
    if not path.is_file():
        return _err("not_found", f"Run '{run_id}' not found")
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _err("internal_error", f"Failed to read run meta: {exc}")
    if not isinstance(meta, dict):
        return _err("internal_error", "Corrupt run meta")
    if "status" in meta:
        meta["status"] = normalize_status(str(meta.get("status")))
    meta.setdefault("run_id", run_id)
    return meta


def get_run_outputs_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.config import runs_dir
    from app.core.run_outputs import list_run_output_files

    args = arguments or {}
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return _err("validation_failed", "run_id required")
    run_path = runs_dir() / run_id
    if not run_path.is_dir():
        return _err("not_found", f"Run '{run_id}' not found")
    return {"run_id": run_id, "outputs": list_run_output_files(run_id, run_path)}


# ── Templates (J1) ────────────────────────────────────────────────────────────

LIST_TEMPLATES_DESCRIPTION = "List available pipeline templates."
LIST_TEMPLATES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**_meta_props()},
    "additionalProperties": False,
}

GET_TEMPLATE_DESCRIPTION = "Get a pipeline template graph by name (optional version)."
GET_TEMPLATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "version": {"type": "string"},
        **_meta_props(),
    },
    "required": ["name"],
    "additionalProperties": False,
}

INSTANTIATE_TEMPLATE_DESCRIPTION = (
    "Copy a template graph into a workspace pipeline draft (instantiate)."
)
INSTANTIATE_TEMPLATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Template name"},
        "project": {"type": "string"},
        "pipeline": {"type": "string", "description": "Destination pipeline name"},
        "version": {"type": "string"},
        **_meta_props(),
    },
    "required": ["name", "project", "pipeline"],
    "additionalProperties": False,
}


def _templates_dir():
    from app.core.config import project_dir

    return project_dir() / "configs" / "templates"


def _load_template_graph(name: str, version: str | None = None) -> dict[str, Any]:
    import json
    from pathlib import Path

    templates_dir = _templates_dir()
    candidates: list[Path] = []
    if version:
        candidates.append(templates_dir / name / f"{version}.graph.json")
    else:
        tdir = templates_dir / name
        if tdir.is_dir():
            versions = sorted(tdir.glob("*.graph.json"))
            if versions:
                candidates.append(versions[-1])
        candidates.append(templates_dir / f"{name}.graph.json")
    for path in candidates:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            raise ValueError("Template is not a graph object")
    raise FileNotFoundError(f"Template '{name}' not found")


def list_templates_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json

    templates_dir = _templates_dir()
    if not templates_dir.exists():
        return {"templates": [], "count": 0}
    items: list[dict[str, Any]] = []
    for f in sorted(templates_dir.glob("*.graph.json")):
        items.append({"name": f.name[: -len(".graph.json")], "kind": "legacy"})
    for d in sorted(templates_dir.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        meta: dict[str, Any] = {"name": d.name, "kind": "versioned"}
        if meta_path.is_file():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta.update(loaded)
            except Exception:
                pass
        versions = [p.stem for p in sorted(d.glob("*.graph.json"))]
        meta["versions"] = versions
        items.append(meta)
    return {"templates": items, "count": len(items)}


def get_template_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    name = str(args.get("name") or "").strip()
    version = args.get("version")
    version_s = str(version).strip() if isinstance(version, str) and version.strip() else None
    try:
        graph = _load_template_graph(name, version_s)
        return {"name": name, "version": version_s, "graph": graph}
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))
    except Exception as exc:
        return _err("internal_error", str(exc))


def instantiate_template_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.ir.secret_policy import InlineSecretError
    from app.core.project_pipelines import put_pipeline

    args = arguments or {}
    name = str(args.get("name") or "").strip()
    pipeline = str(args.get("pipeline") or "").strip()
    version = args.get("version")
    version_s = str(version).strip() if isinstance(version, str) and version.strip() else None
    try:
        graph = _load_template_graph(name, version_s)
        project_dir, project_name = _require_project_dir(str(args.get("project") or ""))
        saved = put_pipeline(project_dir, pipeline, graph, project_name=project_name)
        return {
            "ok": True,
            "project": project_name,
            "pipeline": pipeline,
            "template": name,
            "version": version_s,
            "saved": saved,
        }
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except InlineSecretError as exc:
        return _err("secret_in_ir", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


# ── Models (J2) ───────────────────────────────────────────────────────────────

LIST_MODELS_DESCRIPTION = "List registered models (stage pointers)."
LIST_MODELS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**_meta_props()},
    "additionalProperties": False,
}

GET_MODEL_DESCRIPTION = "Get one registered model by name."
GET_MODEL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        **_meta_props(),
    },
    "required": ["name"],
    "additionalProperties": False,
}

REGISTER_MODEL_DESCRIPTION = "Register a model stage pointer from a run artifact slug."
REGISTER_MODEL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "run_id": {"type": "string"},
        "slug": {"type": "string"},
        "stage": {"type": "string"},
        "description": {"type": "string"},
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "required": ["name", "run_id", "slug"],
    "additionalProperties": False,
}

REQUEST_MODEL_PROD_DESCRIPTION = "Request prod stage for a model (pending approval)."
REQUEST_MODEL_PROD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "run_id": {"type": "string"},
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "required": ["name"],
    "additionalProperties": False,
}

APPROVE_MODEL_PROD_DESCRIPTION = "Approve pending prod stage for a model."
APPROVE_MODEL_PROD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "required": ["name"],
    "additionalProperties": False,
}

COMPARE_RUNS_DESCRIPTION = "Compare two runs by returning both metas side-by-side."
COMPARE_RUNS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "run_id_a": {"type": "string"},
        "run_id_b": {"type": "string"},
        **_meta_props(),
    },
    "required": ["run_id_a", "run_id_b"],
    "additionalProperties": False,
}


def list_models_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.model_registry import list_models

    models = list_models()
    return {"models": models, "count": len(models)}


def get_model_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.model_registry import get_model

    args = arguments or {}
    name = str(args.get("name") or "").strip()
    try:
        return get_model(name)
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def register_model_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.model_registry import register_model

    args = arguments or {}
    try:
        return register_model(
            str(args.get("name") or "").strip(),
            run_id=str(args.get("run_id") or "").strip(),
            slug=str(args.get("slug") or "").strip(),
            stage=str(args.get("stage") or "staging"),
            description=args.get("description"),
            actor=str(args.get("actor") or "mcp"),
        )
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def request_model_prod_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.model_registry import request_prod

    args = arguments or {}
    try:
        return request_prod(
            str(args.get("name") or "").strip(),
            run_id=args.get("run_id"),
            actor=str(args.get("actor") or "mcp"),
        )
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def approve_model_prod_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.model_registry import approve_prod

    args = arguments or {}
    try:
        return approve_prod(
            str(args.get("name") or "").strip(),
            actor=str(args.get("actor") or "mcp"),
        )
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def compare_runs_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    a = get_run_handler({"run_id": args.get("run_id_a")})
    b = get_run_handler({"run_id": args.get("run_id_b")})
    if a.get("error"):
        return a
    if b.get("error"):
        return b
    return {"run_a": a, "run_b": b}


# ── Schedules / webhooks (J3) ─────────────────────────────────────────────────

LIST_SCHEDULES_DESCRIPTION = "List interval schedules."
LIST_SCHEDULES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**_meta_props()},
    "additionalProperties": False,
}

UPSERT_SCHEDULE_DESCRIPTION = (
    "Create a schedule, or update enabled flag when schedule_id is provided."
)
UPSERT_SCHEDULE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schedule_id": {"type": "string"},
        "name": {"type": "string"},
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "interval_minutes": {"type": "integer"},
        "enabled": {"type": "boolean"},
        "env": {"type": "string"},
        **_meta_props(),
    },
    "additionalProperties": False,
}

ENABLE_SCHEDULE_DESCRIPTION = "Enable or disable a schedule by id."
ENABLE_SCHEDULE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schedule_id": {"type": "string"},
        "enabled": {"type": "boolean"},
        **_meta_props(),
    },
    "required": ["schedule_id"],
    "additionalProperties": False,
}

DELETE_SCHEDULE_DESCRIPTION = "Delete a schedule by id."
DELETE_SCHEDULE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schedule_id": {"type": "string"},
        **_meta_props(),
    },
    "required": ["schedule_id"],
    "additionalProperties": False,
}

RUN_SCHEDULE_NOW_DESCRIPTION = "Trigger a schedule immediately."
RUN_SCHEDULE_NOW_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schedule_id": {"type": "string"},
        **_meta_props(),
    },
    "required": ["schedule_id"],
    "additionalProperties": False,
}

GET_WEBHOOKS_DESCRIPTION = "Get outbound webhook configuration (url + events)."
GET_WEBHOOKS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**_meta_props()},
    "additionalProperties": False,
}

PUT_WEBHOOKS_DESCRIPTION = "Set outbound webhook URL and event list."
PUT_WEBHOOKS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "events": {"type": "array", "items": {"type": "string"}},
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "required": ["url"],
    "additionalProperties": False,
}

TEST_WEBHOOK_DESCRIPTION = "Send a test webhook notification to the configured URL."
TEST_WEBHOOK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "actor": {"type": "string"},
        **_meta_props(),
    },
    "additionalProperties": False,
}


def list_schedules_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.schedules import list_schedules

    items = list_schedules()
    return {"schedules": items, "count": len(items)}


def upsert_schedule_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.schedules import create_schedule, set_schedule_enabled

    args = arguments or {}
    schedule_id = str(args.get("schedule_id") or "").strip()
    if schedule_id:
        enabled = args.get("enabled")
        if enabled is None:
            enabled = True
        try:
            updated = set_schedule_enabled(schedule_id, bool(enabled))
            return {"ok": True, "schedule": updated, "upsert": "update"}
        except KeyError:
            return _err("not_found", f"Schedule '{schedule_id}' not found")
        except ValueError as exc:
            return _err("validation_failed", str(exc))
    try:
        item = create_schedule(
            name=str(args.get("name") or "").strip(),
            project=str(args.get("project") or "").strip(),
            pipeline=str(args.get("pipeline") or "").strip(),
            interval_minutes=int(args.get("interval_minutes") or 60),
            enabled=bool(args.get("enabled") if args.get("enabled") is not None else True),
            env=str(args.get("env") or "prod"),
        )
        return {"ok": True, "schedule": item, "upsert": "create"}
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def enable_schedule_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.schedules import set_schedule_enabled

    args = arguments or {}
    schedule_id = str(args.get("schedule_id") or "").strip()
    enabled = bool(args.get("enabled") if args.get("enabled") is not None else True)
    try:
        return set_schedule_enabled(schedule_id, enabled)
    except KeyError:
        return _err("not_found", f"Schedule '{schedule_id}' not found")
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def delete_schedule_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.schedules import delete_schedule

    args = arguments or {}
    schedule_id = str(args.get("schedule_id") or "").strip()
    try:
        delete_schedule(schedule_id)
        return {"ok": True, "deleted": schedule_id}
    except KeyError:
        return _err("not_found", f"Schedule '{schedule_id}' not found")
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def run_schedule_now_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.schedules import run_schedule_now

    args = arguments or {}
    schedule_id = str(args.get("schedule_id") or "").strip()
    try:
        return run_schedule_now(schedule_id)
    except KeyError:
        return _err("not_found", f"Schedule '{schedule_id}' not found")
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("validation_failed", str(exc))


def get_webhooks_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.webhook import WebhookService

    return WebhookService().load()


def put_webhooks_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.audit import record_audit
    from app.core.webhook import WebhookService

    args = arguments or {}
    url = str(args.get("url") or "").strip()
    events = args.get("events") if isinstance(args.get("events"), list) else []
    try:
        WebhookService().save(url, [str(e) for e in events])
    except ValueError as exc:
        return _err("validation_failed", str(exc))
    record_audit(
        actor=str(args.get("actor") or "mcp"),
        action="webhook.set",
        resource_type="webhook",
        resource_id=url[:64] or "webhook",
        meta={"events": list(events)},
    )
    return {"ok": True, "url": url, "events": events}


def test_webhook_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.audit import record_audit
    from app.core.webhook import WebhookService

    args = arguments or {}
    svc = WebhookService()
    config = svc.load()
    url = config.get("url")
    if not url:
        return {"ok": False, "reason": "No webhook URL configured"}
    svc.notify("test", {"message": "Test notification from Graphyn MCP"})
    record_audit(
        actor=str(args.get("actor") or "mcp"),
        action="webhook.test",
        resource_type="webhook",
        resource_id=str(url)[:64],
        meta={},
    )
    return {"ok": True, "url": url}


# ── Readiness (ops) ───────────────────────────────────────────────────────────

GET_READINESS_DESCRIPTION = (
    "Return backend_mode, worker_count, registry/store readiness checks."
)
GET_READINESS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**_meta_props()},
    "additionalProperties": False,
}


def get_readiness_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import os
    from datetime import datetime, timezone

    from app.core.config import project_dir, runs_dir
    from app.core.nodes import is_registry_ready, registry, registry_init_error

    backend_id = (os.environ.get("GRAPHYN_BACKEND") or "local_python").strip() or "local_python"
    backend_mode = "distributed" if backend_id == "distributed" else "local"
    worker_count = 0
    try:
        from app.core.distributed.registry import get_worker_registry

        worker_count = len(get_worker_registry().list(include_stale=True))
    except Exception:
        worker_count = 0
    reg_ready = is_registry_ready()
    init_err = registry_init_error()
    root = project_dir()
    return {
        "status": "ready" if reg_ready else ("failed" if init_err else "starting"),
        "ready": bool(reg_ready),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": backend_id,
        "backend_mode": backend_mode,
        "worker_count": worker_count,
        "registry_ready": reg_ready,
        "registry_init_error": init_err,
        "node_type_count": len(registry) if reg_ready else 0,
        "checks": {
            "runs_dir_exists": runs_dir().exists(),
            "project_dir_exists": root.exists(),
            "registry_ready": reg_ready,
        },
    }
