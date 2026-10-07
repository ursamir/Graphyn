# app/core/execution/graph_prepare.py
"""
Bounded Context:  BC1 — Graph Language (execution-entry preparation)
Responsibility:   The single pre-execution pipeline every interface (REST,
                  SDK, CLI, MCP) applies to a GraphIR before
                  get_backend().execute(): workspace path rewire, project /
                  version_tag stamping, inline-secret refusal, and deep
                  validation (VAL-003 refuse on error findings); plus the
                  shared run.start audit record.
Owns:             prepare_graph(), rewire_for_execution(), stamp_graph_project(),
                  check_graph_executable(), GraphPrepareError,
                  PreparedGraph, persist_project_fields(), record_run_start(),
                  persist_run_identity() (meta actor / trigger / declared
                  saved-pipeline ref / declared ``lineage`` model),
                  sanitize_lineage_request(), normalize_trigger(),
                  graph_display_name().
Public Surface:   Same symbols (used by app.api.routers.pipelines, app.core.sdk,
                  app.cli.main via SDK, app.mcp.handlers.execution).
Must NOT:         Execute graphs; import app.api or app.domain; raise HTTP
                  errors (interfaces map GraphPrepareError to their envelope).
Dependencies:     app.core.ir (loader, secret_policy), app.core.paths.workspace_paths,
                  app.core.runs.run_project, app.core.execution.validation,
                  app.core.host.registry_runtime, app.core.trust.audit (all lazy).
Reason To Change: A new pre-execution step must apply to every interface, or
                  the validation / audit contract changes.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_DATASETS_INPUT_MARK = "workspace/datasets/input/"


class GraphPrepareError(ValueError):
    """Graph refused before execution.

    ``code`` is ``validation_failed`` (VAL-003), ``secret_in_ir`` or
    ``load_failed``. ``errors`` / ``warnings`` follow the SRS §14.3 finding
    shape for ``validation_failed``.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        errors: list[dict[str, Any]] | None = None,
        warnings: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.errors = list(errors or [])
        self.warnings = list(warnings or [])

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.code == "validation_failed":
            out["errors"] = self.errors
            out["warnings"] = self.warnings
        return out


@dataclass
class PreparedGraph:
    graph: Any
    project_fields: dict[str, str] = field(default_factory=dict)
    validation: dict[str, Any] | None = None


def graph_display_name(graph: Any) -> str | None:
    try:
        meta = getattr(graph, "metadata", None)
        if isinstance(meta, dict):
            return meta.get("name")
        if meta is not None:
            return getattr(meta, "name", None)
    except Exception:
        return None
    return None


def stamp_graph_project(graph: Any, payload: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
    """Merge project / version_tag (payload > graph metadata > node configs) into metadata."""
    from app.core.runs.run_project import extract_project_fields_from_payload

    fields = extract_project_fields_from_payload(payload or {}, graph)
    if not fields:
        return graph, fields
    meta = getattr(graph, "metadata", None)
    if meta is None:
        return graph, fields
    updates = {k: v for k, v in fields.items() if v}
    if not updates:
        return graph, fields
    new_meta = meta.model_copy(update=updates)
    return graph.model_copy(update={"metadata": new_meta}), fields


def rewire_for_execution(graph: Any) -> Any:
    """Workspace path rewire (examples/** → workspace/…), seeding sample inputs."""
    from app.core.ir.loader import dump_ir
    from app.core.paths.workspace_paths import apply_output_rewire

    rewired = apply_output_rewire(graph)
    # ``…/latest`` dataset versions → concrete vN before the run, so the
    # snapshot, run record and replay all pin one immutable version.
    from app.core.execution.dataset_refs import resolve_latest_refs

    rewired, _ = resolve_latest_refs(rewired)
    # Sample ingest under examples/**/data now points at
    # workspace/datasets/input/<slug>; REST seeds those at startup/sync, so
    # seed lazily for SDK / CLI / MCP when the rewire introduced one.
    try:
        import json

        before = json.dumps(dump_ir(graph), default=str)
        after = json.dumps(dump_ir(rewired), default=str)
        if _DATASETS_INPUT_MARK in after and after.count(_DATASETS_INPUT_MARK) > before.count(
            _DATASETS_INPUT_MARK
        ):
            from app.core.templates.example_templates import seed_example_input_datasets

            seed_example_input_datasets()
    except Exception:
        log.debug("graph_prepare: example dataset seeding skipped", exc_info=True)
    return rewired


def prepare_graph(
    graph: Any,
    *,
    payload: dict[str, Any] | None = None,
    rewire: bool = True,
    validate: bool = True,
    registry: Any = None,
) -> PreparedGraph:
    """Rewire → stamp project → refuse inline secrets → deep validate.

    ``graph`` may be a GraphIR or an IR dict. Raises :class:`GraphPrepareError`
    (a ``ValueError``) when the graph must not execute.
    """
    if isinstance(graph, dict):
        from app.core.ir.loader import load_ir

        try:
            graph = load_ir(graph)
        except Exception as exc:
            raise GraphPrepareError("load_failed", str(exc)) from exc

    if rewire:
        graph = rewire_for_execution(graph)
    graph, fields = stamp_graph_project(graph, payload)
    result = check_graph_executable(graph, validate=validate, registry=registry)
    return PreparedGraph(graph=graph, project_fields=dict(fields), validation=result)


def check_graph_executable(
    graph: Any, *, validate: bool = True, registry: Any = None
) -> dict[str, Any] | None:
    """Refuse inline secrets, then VAL-003 deep validation. Returns the result."""
    from app.core.ir.secret_policy import assert_no_inline_secrets

    try:
        assert_no_inline_secrets(graph)
    except Exception as exc:
        raise GraphPrepareError("secret_in_ir", str(exc)) from exc
    if not validate:
        return None
    from app.core.execution.validation import validate_graph_ir_result

    if registry is None:
        from app.core.host.registry_runtime import get_registry

        registry = get_registry()
    result = validate_graph_ir_result(graph, registry)
    if not result["valid"]:
        errors = result.get("errors") or []
        message = errors[0]["message"] if errors else "validation failed"
        raise GraphPrepareError(
            "validation_failed",
            message,
            errors=errors,
            warnings=result.get("warnings") or [],
        )
    return result


def persist_project_fields(run_manager: Any, fields: dict[str, str]) -> None:
    """Write project / version_tag into the run's meta (locked atomic writer)."""
    writer = getattr(run_manager, "_write_meta_field", None)
    if not callable(writer):
        return
    for key, value in (fields or {}).items():
        if value:
            try:
                writer(key, value)
            except Exception:
                log.debug("graph_prepare: could not persist %s", key, exc_info=True)


_TRIGGERS = frozenset({"ui", "api", "cli", "sdk", "mcp", "schedule", "replay", "agent", "webhook", "ship"})


def normalize_trigger(value: Any, default: str = "api") -> str:
    text = str(value or "").strip().lower()
    return text if text in _TRIGGERS else default


_LINEAGE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}$")


def sanitize_lineage_request(raw: Any) -> dict[str, Any] | None:
    """Validate the optional run payload ``lineage`` declaration.

    Shape: ``{"model": {"name": str, "version"?: str, "stage"?: str},
    "source_run_id"?: str}`` — e.g. the Ship wizard declaring which
    registered model a package run ships. Unknown keys are dropped; invalid
    tokens make the whole field ``None`` (never raises).
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    model = raw.get("model")
    if isinstance(model, str):
        model = {"name": model}
    if isinstance(model, dict):
        m: dict[str, str] = {}
        for key in ("name", "version", "stage"):
            val = model.get(key)
            if val is None or val == "":
                continue
            text = str(val).strip()
            if not _LINEAGE_TOKEN.match(text):
                return None
            m[key] = text
        if m.get("name"):
            out["model"] = m
    src = raw.get("source_run_id")
    if isinstance(src, str) and _LINEAGE_TOKEN.match(src.strip()):
        out["source_run_id"] = src.strip()
    return out or None


def persist_run_identity(
    run_manager: Any,
    *,
    actor: str,
    trigger: str,
    payload: dict[str, Any] | None = None,
    actor_verified: bool | None = None,
    claimed_actor: str | None = None,
) -> None:
    """Write ``actor`` / ``trigger`` (+ declared saved-pipeline ref) into run meta.

    ``actor_verified`` / ``claimed_actor`` default from the current API
    request identity (app.core.trust.identity.bind_actor): verified only when
    the bearer token maps to the actor name. Non-HTTP callers (MCP, CLI, SDK)
    record ``actor_verified: false``.

    The same actor string goes into meta.json, the sealed audit record and
    every run.* platform audit event. Optional payload keys ``pipeline``,
    ``pipeline_env`` and ``pipeline_version`` declare which saved pipeline the
    graph came from (otherwise the audit record infers it by content hash).
    Optional ``lineage: {model: {name, version|stage}}`` declares the
    registered model a run ships (meta ``lineage_request`` → the sealed
    record's ``lineage.models``).
    """
    writer = getattr(run_manager, "_write_meta_field", None)
    if not callable(writer):
        return
    try:
        from app.core.trust.identity import bind_actor

        act, verified, claimed, _origin = bind_actor(actor, actor_verified, claimed_actor)
    except Exception:
        act, verified, claimed = (actor or "unknown").strip()[:128] or "unknown", bool(actor_verified), claimed_actor
    fields: dict[str, Any] = {
        "actor": act or "unknown",
        "actor_verified": bool(verified),
        "trigger": normalize_trigger(trigger),
    }
    if claimed:
        fields["claimed_actor"] = str(claimed)[:128]
    try:
        from app.core.trust.identity import principal_snapshot

        principal = principal_snapshot()
    except Exception:
        principal = None
    if principal:
        fields["principal"] = principal
    body = payload if isinstance(payload, dict) else {}
    name = body.get("pipeline") or body.get("pipeline_name")
    if isinstance(name, str) and name.strip():
        fields["pipeline_name"] = name.strip()[:128]
    env = body.get("pipeline_env")
    if isinstance(env, str) and env.strip().lower() in ("draft", "staging", "prod"):
        fields["pipeline_env"] = env.strip().lower()
    ver = body.get("pipeline_version")
    if isinstance(ver, str) and ver.strip():
        fields["pipeline_version_id"] = ver.strip()[:32]
    lineage = sanitize_lineage_request(body.get("lineage"))
    if lineage:
        fields["lineage_request"] = lineage
    for key, value in fields.items():
        try:
            writer(key, value)
        except Exception:
            log.debug("graph_prepare: could not persist %s", key, exc_info=True)


def record_run_start(
    run_id: str,
    graph: Any,
    *,
    actor: str,
    mode: str,
    run_manager: Any = None,
    trigger: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append the run.start audit event (never raises).

    When ``run_manager`` is given the actor / trigger are also persisted into
    the run meta (see :func:`persist_run_identity`).
    """
    if run_manager is not None:
        try:
            persist_run_identity(run_manager, actor=actor, trigger=trigger or mode, payload=payload)
        except Exception:
            log.debug("graph_prepare: persist_run_identity failed", exc_info=True)
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=(actor or "unknown").strip() or "unknown",
            action="run.start",
            resource_type="run",
            resource_id=str(run_id),
            meta={"graph_name": graph_display_name(graph), "mode": mode,
                  "trigger": normalize_trigger(trigger or mode),
                  "project": getattr(getattr(graph, "metadata", None), "project", None)},
        )
    except Exception:
        log.debug("graph_prepare: run.start audit failed", exc_info=True)
