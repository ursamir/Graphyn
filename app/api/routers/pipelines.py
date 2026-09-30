# app/api/routers/pipelines.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for pipeline validation and execution.
Owns:             POST /pipelines/validate, POST /pipelines/run,
                  POST /pipelines/run-async.
                  Template routes live in pipeline_templates.py.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain pipeline execution logic — delegate to SDK/orchestrator.
Dependencies:     fastapi, app.core.sdk, app.core.ir, app.core.config.
Reason To Change: New pipeline endpoint added, streaming protocol changes,
                  or template storage changes.

Accepts both IR JSON (canonical) and YAML (deprecated) formats.
IR JSON is detected by the presence of a 'schema_version' field in the request body.
All execution delegates to RuntimeBackend.execute() with GraphIR as source of truth.
"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.core.logger import PipelineLogger
from app.core.host.registry_runtime import get_registry
from app.core.execution.validation import validate_pipeline

# Shared pool for /run and /run-async (avoids unbounded daemon threads per request).
_PIPELINE_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="graphyn-pipeline-run")

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


# ── Format detection helper ───────────────────────────────────────────────────


def _stamp_graph_project(graph, payload: dict):
    """Merge optional project / version_tag from payload into GraphIR metadata.

    Thin wrapper over ``app.core.execution.graph_prepare.stamp_graph_project`` (shared
    with SDK / CLI / MCP).
    """
    from app.core.execution.graph_prepare import stamp_graph_project

    return stamp_graph_project(graph, payload)


def _is_ir_payload(payload: dict) -> bool:
    """Detect IR JSON format by presence of schema_version (top-level or under graph)."""
    if not isinstance(payload, dict):
        return False
    if "schema_version" in payload:
        return True
    nested = payload.get("graph")
    return isinstance(nested, dict) and "schema_version" in nested


def _build_graph_from_payload(payload: dict):
    """Build a GraphIR from either IR JSON or YAML payload.

    Returns (graph, deprecation_header) where deprecation_header is None
    for IR JSON and a warning string for YAML payloads.

    Accepts either a bare Graph IR object or ``{"graph": <IR>, "project": …}``.
    Delegates to SDK (V1.md §3.1).
    """
    from app.core.execution.graph_prepare import rewire_for_execution
    from app.core.ir.loader import load_ir
    from app.core.ir.yaml_shim import yaml_config_to_ir

    if _is_ir_payload(payload):
        ir_body = payload
        nested = payload.get("graph")
        if isinstance(nested, dict) and "schema_version" in nested:
            ir_body = nested
        graph = rewire_for_execution(load_ir(ir_body))
        return graph, None
    else:
        # YAML path (Req 4.7.2, 4.7.4)
        yaml_str = payload.get("yaml", "")
        try:
            raw = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=422, detail=f"YAML parse error: {exc}")
        graph = rewire_for_execution(yaml_config_to_ir(raw))
        return graph, "YAML pipeline input is deprecated. Use IR JSON format."


# ── Validate ──────────────────────────────────────────────────────────────────

@router.post("/validate", summary="Validate a pipeline YAML or IR JSON")
def validate_pipeline_config(payload: dict = Body(...)):
    """Validate a pipeline config without executing it.

    Accepts both YAML format ({"yaml": "..."}) and IR JSON format.
    Uses yaml_config_to_ir() for YAML (no DeprecationWarning during validation).

    Req 4.8
    """
    if _is_ir_payload(payload):
        # IR JSON validation (Req 4.8.1, 4.8.3, 4.8.4)
        try:
            from app.core.ir.loader import load_ir
            from app.core.ir.secret_policy import assert_no_inline_secrets
            from app.core.paths.workspace_paths import apply_output_rewire
            ir_body = payload
            nested = payload.get("graph")
            if isinstance(nested, dict) and "schema_version" in nested:
                ir_body = nested
            graph = apply_output_rewire(load_ir(ir_body))
            assert_no_inline_secrets(graph)
            from app.core.execution.validation import validate_graph_ir_result

            result = validate_graph_ir_result(graph, get_registry())
            if not result["valid"]:
                return JSONResponse(status_code=422, content=result)
            return result
        except Exception as exc:
            msg = str(exc)
            code = "VAL-SECRET" if "secret" in msg.lower() else "VAL-MIGRATE"
            result = {
                "valid": False,
                "node_count": 0,
                "edge_count": 0,
                "schema_version": None,
                "errors": [{
                    "code": code,
                    "severity": "error",
                    "message": msg,
                    "node_ids": [],
                    "edge_index": None,
                    "field": None,
                }],
                "warnings": [],
            }
            return JSONResponse(status_code=422, content=result)
    else:
        # YAML validation — use yaml_config_to_ir (no DeprecationWarning) (Req 4.8.2, 4.8.5)
        yaml_str = payload.get("yaml", "")
        try:
            config = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            msg = f"YAML parse error: {exc}"
            return JSONResponse(
                status_code=422,
                content={"valid": False, "error": msg, "detail": msg},
            )

        try:
            from app.core.ir.secret_policy import assert_no_inline_secrets
            from app.core.ir.yaml_shim import yaml_config_to_ir

            validate_pipeline(config, get_registry())
            graph = yaml_config_to_ir(config)
            assert_no_inline_secrets(graph)
        except ValueError as exc:
            msg = str(exc)
            return JSONResponse(
                status_code=422,
                content={"valid": False, "error": msg, "detail": msg},
            )
        except Exception as exc:
            msg = str(exc)
            return JSONResponse(
                status_code=422,
                content={"valid": False, "error": msg, "detail": msg},
            )

        headers = {"X-Deprecation-Warning": "YAML pipeline input is deprecated. Use IR JSON format."}
        ncount = len(config.get("pipeline", {}).get("nodes", []))
        ecount = len(config.get("pipeline", {}).get("edges", []) or [])
        return JSONResponse(
            content={
                "valid": True,
                "node_count": ncount,
                "edge_count": ecount,
                "schema_version": None,
                "errors": [],
                "warnings": [],
            },
            headers=headers,
        )


# ── Run (streaming) ───────────────────────────────────────────────────────────

_STREAM_QUEUE_MAX = 512
_TERMINAL_EVENT_TYPES = frozenset({"done", "error"})


class _RunEventChannel:
    """Bounded, never-blocking producer → NDJSON consumer channel.

    ``put_nowait`` (the PipelineLogger queue contract) never blocks and never
    raises: when full it drops the oldest *non-terminal* event, so a slow or
    vanished client cannot wedge a shared ``_PIPELINE_RUN_EXECUTOR`` worker.
    Terminal ``done`` / ``error`` events and the end-of-stream marker are
    always delivered. After the consumer disconnects (:meth:`close`) puts are
    discarded so nothing accumulates.
    """

    def __init__(self, maxsize: int = _STREAM_QUEUE_MAX) -> None:
        from collections import deque

        self._items: "deque[Any]" = deque()
        self._maxsize = max(1, int(maxsize))
        self._lock = threading.Lock()
        self._finished = False
        self._closed = False
        self.dropped = 0
        self.terminal_seen: str | None = None

    @staticmethod
    def _is_terminal(item: Any) -> bool:
        return isinstance(item, dict) and item.get("type") in _TERMINAL_EVENT_TYPES

    def put_nowait(self, item: Any) -> None:
        with self._lock:
            if self._closed or self._finished:
                return
            terminal = self._is_terminal(item)
            if terminal and self.terminal_seen is None:
                self.terminal_seen = str(item.get("type"))
            if len(self._items) >= self._maxsize:
                for idx, queued in enumerate(self._items):
                    if not self._is_terminal(queued):
                        del self._items[idx]
                        self.dropped += 1
                        break
                else:
                    if not terminal:
                        self.dropped += 1
                        return
            self._items.append(item)

    def put(self, item: Any, block: bool = True, timeout: float | None = None) -> None:  # noqa: ARG002
        """Queue-compatible alias — never blocks."""
        self.put_nowait(item)

    def finish(self, terminal: dict[str, Any] | None = None) -> None:
        """Producer done: append ``terminal`` (if any) and mark end-of-stream."""
        with self._lock:
            if self._finished:
                return
            if terminal is not None and not self._closed:
                if self.terminal_seen is None:
                    self.terminal_seen = str(terminal.get("type"))
                self._items.append(terminal)
            self._finished = True

    def close(self) -> None:
        """Consumer gone: discard queued and future events."""
        with self._lock:
            self._closed = True
            self._items.clear()

    def poll(self) -> tuple[bool, Any]:
        """Return ``(True, item)``, ``(True, None)`` at end-of-stream, or ``(False, None)``."""
        with self._lock:
            if self._items:
                return True, self._items.popleft()
            if self._finished:
                return True, None
            return False, None


@router.post("/run", summary="Run a pipeline and stream log events")
def run_pipeline_stream(request: Request, payload: dict = Body(...)):
    """Execute a pipeline and stream NDJSON log events as they occur.

    Delegates to get_backend().execute(graph) (V1.md §3.1).
    Accepts both IR JSON and YAML formats (Req 4.7).

    Stream contract: first line ``run_started``; the last line is always a
    terminal ``done`` or ``error`` event. Under back-pressure the oldest
    non-terminal events are dropped (never the terminal one) and the
    producer thread never blocks, even after the client disconnects.
    """
    from app.core.host.shutdown import is_draining

    if is_draining():
        raise HTTPException(
            status_code=503,
            detail={"code": "draining", "message": "Control plane is shutting down; refusing new runs"},
        )
    try:
        graph, deprecation_header = _build_graph_from_payload(payload)
        graph, project_fields = _stamp_graph_project(graph, payload)
        _refuse_invalid_graph(graph)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    from app.core.execution.graph_prepare import persist_project_fields, record_run_start
    from app.core.runs.run_journal import RunManager

    # Same contract as /run-async: run_id known before the first NDJSON event
    run_mgr = RunManager()
    run_id = run_mgr.run_id
    persist_project_fields(run_mgr, project_fields)
    if not _is_ir_payload(payload):
        run_mgr.save_config(payload.get("yaml", ""))

    channel = _RunEventChannel()
    logger = PipelineLogger(queue=channel)

    def _run():
        from app.core.execution.runtime_backend import get_backend  # noqa: PLC0415

        terminal: dict[str, Any] | None = None
        try:
            get_backend().execute(graph, logger=logger, run_manager=run_mgr)
            # Success terminal normally comes from logger.pipeline_done
            # (type=done + run_id); synthesize one if the backend did not.
            if channel.terminal_seen is None:
                terminal = {
                    "type": "done",
                    "run_id": run_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except BaseException as exc:  # noqa: BLE001 — terminal event must always be sent
            try:
                run_mgr.mark_failed(str(exc) or type(exc).__name__)
            except Exception:
                pass
            if channel.terminal_seen != "error":
                terminal = {
                    "type": "error",
                    "run_id": run_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            if not isinstance(exc, Exception):
                raise
        finally:
            channel.finish(terminal)

    try:
        _PIPELINE_RUN_EXECUTOR.submit(_run)
    except RuntimeError as exc:  # executor shut down
        try:
            run_mgr.mark_failed(str(exc))
        except Exception:
            pass
        channel.finish({
            "type": "error",
            "run_id": run_id,
            "error_type": type(exc).__name__,
            "message": str(exc),
        })

    async def stream():
        import asyncio

        # Emit run_id immediately so Observe deep-links work before first node
        yield json.dumps({"type": "run_started", "run_id": run_id}) + "\n"
        idle = 0.0
        try:
            while True:
                has_item, item = channel.poll()
                if not has_item:
                    # Non-blocking poll: no threadpool thread is parked on a
                    # queue; client disconnect cancels this coroutine here or
                    # is detected via request.is_disconnected() while idle.
                    step = 0.02 if idle < 1.0 else 0.1
                    await asyncio.sleep(step)
                    idle += step
                    if idle >= 1.0 and await request.is_disconnected():
                        return
                    continue
                idle = 0.0
                if item is None:
                    return
                try:
                    if isinstance(item, dict) and "run_id" not in item:
                        item = {**item, "run_id": run_id}
                    line = json.dumps(item) + "\n"
                except (TypeError, ValueError) as exc:
                    line = json.dumps({
                        "type": "log",
                        "run_id": run_id,
                        "level": "WARNING",
                        "message": f"Serialization error (event dropped): {exc}",
                    }) + "\n"
                yield line
        finally:
            channel.close()

    headers = {"X-Run-Id": run_id}
    if deprecation_header:
        headers["X-Deprecation-Warning"] = deprecation_header

    from app.api.actor import resolve_actor

    record_run_start(run_id, graph, actor=resolve_actor(request), mode="stream")

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers=headers)


# ── Run async ─────────────────────────────────────────────────────────────────

def _refuse_invalid_graph(graph) -> None:
    """VAL-003: refuse execute when validation has error-severity findings.

    Delegates to ``app.core.execution.graph_prepare.check_graph_executable`` (same
    checks SDK / CLI / MCP apply) and maps GraphPrepareError to HTTP 422.
    """
    from app.core.execution.graph_prepare import GraphPrepareError, check_graph_executable

    try:
        check_graph_executable(graph)
    except GraphPrepareError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc


@router.post("/run-async", summary="Start a pipeline run asynchronously")
def run_pipeline_async(request: Request, payload: dict = Body(...)):
    """Start a pipeline run in a background thread and return the run_id immediately.

    Delegates to get_backend().execute(graph) (V1.md §3.1).
    Accepts both IR JSON and YAML formats (Req 4.7).
    Honors Idempotency-Key (API-CONV-004). Durable status starts as ``pending``
    (PERS-001) before the ack body is returned.
    """
    from app.core.host.shutdown import is_draining

    if is_draining():
        raise HTTPException(
            status_code=503,
            detail={"code": "draining", "message": "Control plane is shutting down; refusing new runs"},
        )
    from app.api.idempotency import begin_idempotent, complete_idempotent, idempotency_guard

    cached = begin_idempotent(
        request, body=payload, route="POST /api/v1/pipelines/run-async"
    )
    if cached is not None:
        return cached

    with idempotency_guard(request):
        try:
            graph, deprecation_header = _build_graph_from_payload(payload)
            graph, project_fields = _stamp_graph_project(graph, payload)
            _refuse_invalid_graph(graph)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        from app.core.runs.run_journal import RunManager

        # Create ONE RunManager before the thread starts so run_id is known immediately.
        # Constructor writes durable status=pending (PERS-001) before we ack.
        run_mgr = RunManager()
        run_id = run_mgr.run_id

        # Persist project scoping immediately so GET /runs?project= can filter mid-flight
        from app.core.execution.graph_prepare import persist_project_fields, record_run_start

        persist_project_fields(run_mgr, project_fields)

        # Save YAML config for backward compat if YAML was submitted
        if not _is_ir_payload(payload):
            run_mgr.save_config(payload.get("yaml", ""))

        def _run():
            try:
                from app.core.execution.runtime_backend import get_backend  # noqa: PLC0415
                get_backend().execute(graph, run_manager=run_mgr)
            except Exception as exc:
                run_mgr.mark_failed(str(exc))

        _PIPELINE_RUN_EXECUTOR.submit(_run)

        headers = {}
        if deprecation_header:
            headers["X-Deprecation-Warning"] = deprecation_header

        from app.api.actor import resolve_actor

        record_run_start(run_id, graph, actor=resolve_actor(request), mode="async")

        body = {"run_id": run_id, "status": "pending"}
        complete_idempotent(request, status_code=200, body=body, headers=headers)
    return JSONResponse(content=body, headers=headers)

# Template and marketplace routes. This module does not import pipeline_templates
# until the router exists, and pipeline_templates does not import this module.
from app.api.routers.pipeline_templates import router as template_router

router.include_router(template_router)
