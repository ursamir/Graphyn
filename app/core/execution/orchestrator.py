# app/core/execution/orchestrator.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Coordinate execution of validated DAGs across all execution
                  modes (sequential, parallel, event-driven).
Owns:             run_pipeline_ir_async(), run_pipeline_ir() entry points.
Public Surface:   run_pipeline_ir(graph, **kwargs) -> dict
                  run_pipeline_ir_async(graph, **kwargs) -> dict
Must NOT:         Understand audio domain logic, parse API requests,
                  persist artifacts directly, or import from app.domain.
Dependencies:     BC1 (ir.models, ir.loader), BC2 (nodes.base, nodes.observers),
                  BC3 (registry_runtime), BC4 (planner), BC6 (checkpoint,
                  artifact_store, run_journal, run_control, pipeline_cache,
                  logger), app.core.utils, app.core.execution.conditions, app.core.execution.events.
Reason To Change: Runtime execution semantics evolve (new execution mode,
                  cancellation protocol, resume logic, partial execution).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any

from app.core.nodes.errors import ResumeError
from app.core.nodes.observers import NodeObserver
from app.core.artifacts.artifact_store import infer_artifact_type
from app.core.execution.planner import (
    PipelineConfig,
    PipelineGraph,
    ir_to_pipeline_config,
)
from app.core.execution.node_executor import NodeExecutor
from app.core.runs.checkpoint import write_checkpoint, load_checkpoint_outputs
from app.core.utils import collect_stream as _collect_stream
from app.core.host.registry_runtime import resolve_capability as _resolve_capability_impl
from app.core.nodes.metadata import stable_node_type

log = logging.getLogger(__name__)


def _persist_node_stats(run: Any, node_stats: list) -> None:
    try:
        run._write_meta_field("node_stats", node_stats)
    except Exception:
        pass


def _node_stat_record(
    node_id: str,
    node_type: str,
    node_index: int,
    duration_s: float,
    *,
    status: str = "completed",
    cache_hit: bool = False,
) -> dict:
    return {
        "node_id": node_id,
        "node_type": node_type,
        "node_index": node_index,
        "duration_s": round(duration_s, 4),
        "duration_ms": round(duration_s * 1000, 2),
        "status": status,
        "cache_hit": cache_hit,
    }


def _compute_node_cache_key(
    cache: Any,
    node_type: str,
    node_cfg_dict: dict,
    inputs: dict,
    graph_obj: Any,
    node_id: str,
    registry: Any,
) -> str:
    node_inst = graph_obj.get_node(node_id)
    node_seed = getattr(node_inst, "seed", None)
    node_version: str | None = None
    if registry is not None:
        try:
            node_version = registry.get_metadata(node_type).version
        except Exception:
            node_version = None
    return cache.compute_key(
        node_type,
        node_cfg_dict,
        inputs,
        node_seed=node_seed,
        node_version=node_version,
    )


def _graph_display_name(graph: Any) -> str:
    return str(getattr(getattr(graph, "metadata", None), "name", "") or "")


def _scope_graph_to_run(graph: Any, run: Any) -> Any:
    """Rewire output paths into workspace/artifacts/<slug>/runs/<run_id>/."""
    from app.core.paths.workspace_paths import (
        artifact_fs_path,
        artifact_layout,
        artifact_slug,
        scope_outputs_to_run,
    )

    scoped = scope_outputs_to_run(graph, run.run_id)
    name = _graph_display_name(scoped) or _graph_display_name(graph)
    slug = artifact_slug(name or "pipeline")
    layout = artifact_layout(slug, run.run_id)
    try:
        artifact_fs_path(layout["run_dir"]).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    run._write_meta_field("artifacts_dir", layout["run_dir"])
    return scoped


def _finalize_event_driven_run(
    run: Any,
    logger: Any,
    event_terminal: str | None,
    *,
    active_nodes: set[str],
    node_stats: list,
    start_time: float,
    trigger_count: int,
    graph_name: str | None,
    graph: Any,
) -> None:
    """Persist logs and terminal metadata for event-driven execution (P3-13 extract)."""
    run.save_logs(logger.logs)
    if event_terminal == "cancelled":
        run.mark_cancelled()
    elif event_terminal == "failed":
        return
    elif event_terminal is None:
        run.save_metadata({
            "num_nodes": len(active_nodes),
            "node_stats": node_stats,
            "duration_s": round(time.time() - start_time, 4),
            "event_driven": True,
            "trigger_count": trigger_count,
            **({"graph_name": graph_name} if graph_name else {}),
            **_finalize_run_artifacts(run, graph),
        })
        try:
            logger.pipeline_done(run.run_id, time.time() - start_time)
        except Exception:
            log.debug("pipeline_done emit failed (event-driven)", exc_info=True)


def _finalize_run_artifacts(run: Any, graph: Any) -> dict[str, Any]:
    """Publish latest alias and collect artifacts_dir / metrics for meta.json."""
    from app.core.paths.workspace_paths import (
        artifact_layout,
        artifact_slug,
        publish_latest,
        read_run_metrics,
    )

    extras: dict[str, Any] = {}
    name = _graph_display_name(graph)
    slug = artifact_slug(name or "pipeline")
    layout = artifact_layout(slug, run.run_id)
    extras["artifacts_dir"] = layout["run_dir"]
    metrics = read_run_metrics(slug, run.run_id)
    if metrics:
        extras["metrics"] = metrics
        try:
            run._write_meta_field("metrics", metrics)
        except Exception:
            pass
    try:
        publish_latest(slug, run.run_id)
    except Exception:
        log.warning("Failed to publish latest artifacts for run %s", run.run_id, exc_info=True)
    try:
        run._write_meta_field("artifacts_dir", layout["run_dir"])
    except Exception:
        pass
    return extras



# ── Helpers ───────────────────────────────────────────────────────────────────

def _logical_graph_hash(graph: Any) -> str:
    """SHA-256 of the logical (pre-run-scoping) graph.

    Run scoping rewrites artifact paths to embed the run_id, so a hash of the
    materialized graph differs on every run. Resume validation, checkpoint
    lookup, provenance and node seeds must key off the logical graph instead.
    """
    import hashlib

    from app.core.ir.loader import dump_ir

    return hashlib.sha256(
        json.dumps(dump_ir(graph), sort_keys=True, default=str).encode()
    ).hexdigest()


def _validate_partial_request(
    graph: Any,
    include_nodes: list[str] | None,
    exclude_nodes: list[str] | None,
) -> None:
    if include_nodes is not None and exclude_nodes is not None:
        raise ValueError("include_nodes and exclude_nodes are mutually exclusive")
    all_node_ids = {n.id for n in graph.nodes}
    for nid in (include_nodes or []) + (exclude_nodes or []):
        if nid not in all_node_ids:
            raise ValueError(f"Unknown node ID '{nid}' in partial execution request")


def _safe_find_checkpoint(run: Any, node_id: str) -> dict | None:
    try:
        found = run.find_latest_checkpoint(node_id)
    except Exception:
        log.debug("checkpoint lookup failed for %s", node_id, exc_info=True)
        return None
    return found if isinstance(found, dict) else None


def _excluded_node_outputs(
    node_id: str,
    node: Any,
    incoming: dict[str, list[tuple[str, str, str]]],
    node_outputs: dict[str, dict[str, Any]],
    run: Any,
) -> dict[str, Any]:
    """Outputs to publish for a node excluded from a partial run.

    Keyed by the excluded node's OUTPUT port names (consumers look up
    ``node_outputs[src][src_port]``). Preference: the node's own checkpoint
    for this logical graph; otherwise pass inputs through — a same-named
    input port maps onto an output port, and a single-input/single-output
    node forwards its one input.
    """
    ckpt = _safe_find_checkpoint(run, node_id)
    if ckpt:
        return dict(ckpt)
    in_vals: dict[str, Any] = {}
    for src_id, src_port, dst_port in incoming[node_id]:
        upstream = node_outputs.get(src_id)
        if isinstance(upstream, dict) and src_port in upstream:
            in_vals[dst_port] = upstream[src_port]
    out_names = list(getattr(node, "output_ports", {}) or {})
    result = {name: in_vals[name] for name in out_names if name in in_vals}
    if not result and len(out_names) == 1 and len(in_vals) == 1:
        result[out_names[0]] = next(iter(in_vals.values()))
    if not incoming[node_id] and not result:
        log.warning(
            "Excluded node '%s' has no incoming edges and no checkpoint — downstream "
            "consumers need input_overrides.",
            node_id,
        )
    return result


def _is_cancelled(run: Any) -> bool:
    """Unthrottled cancel check for node boundaries (durable + in-process)."""
    poll = getattr(run, "poll_cancelled", None)
    if callable(poll):
        try:
            return bool(poll())
        except Exception:
            pass
    return bool(run.is_cancelled)


def _cancelled_result(
    run: Any, logger: Any, node_stats: list, node_outputs: dict, active_count: int
) -> dict[str, Any]:
    nodes_completed = len(node_stats)
    try:
        logger.pipeline_cancelled(run.run_id, nodes_completed, max(active_count - nodes_completed, 0))
    except Exception:
        log.debug("pipeline_cancelled emit failed", exc_info=True)
    run.mark_cancelled()
    try:
        run.save_logs(logger.logs)
    except Exception:
        pass
    last_completed = node_stats[-1]["node_id"] if node_stats else None
    return node_outputs.get(last_completed, {}) if last_completed else {}


class _RunResources:
    """Resources the entry-point wrapper must release whatever happens."""

    def __init__(self) -> None:
        self.executors: dict[str, NodeExecutor] = {}

    def teardown(self) -> None:
        for node_id, exec_ in list(self.executors.items()):
            try:
                exec_.teardown()  # idempotent (NodeExecutor tracks teardown)
            except Exception:
                log.warning("teardown failed for node '%s'", node_id, exc_info=True)


# ── Main async execution entry point ──────────────────────────────────────────

async def run_pipeline_ir_async(
    graph: Any,
    logger: Any = None,
    use_cache: bool = True,
    checkpoint: bool = False,
    streaming: bool = False,
    parallel: bool = False,
    observer: NodeObserver | None = None,
    run_manager: Any = None,
    max_workers: int | None = None,
    resume_run_id: str | None = None,
    include_nodes: list[str] | None = None,
    exclude_nodes: list[str] | None = None,
    input_overrides: dict | None = None,
    event_driven: bool = False,
    # SA-O3: event_loop parameter removed — it was accepted but never used.
    # Callers that passed event_loop= will get a TypeError; update call sites.
) -> dict[str, Any]:
    """Execute a pipeline from a GraphIR object (async-native entry point).

    run_pipeline_ir() is the synchronous shim that calls asyncio.run() on this.

    Lifecycle guarantee: once the RunManager exists, every exit path leaves
    the run in a terminal durable status (succeeded / failed / cancelled),
    tears down every executor that was set up, and deregisters the run.
    """
    if parallel and event_driven:
        raise ValueError(
            "parallel and event_driven are mutually exclusive execution modes. "
            "Pass only one of parallel=True or event_driven=True."
        )
    # P1-4: parallel path does not yet honour filters / overrides / resume —
    # refuse rather than silently producing wrong results.
    if parallel and (
        include_nodes is not None
        or exclude_nodes is not None
        or input_overrides
        or resume_run_id is not None
    ):
        raise ValueError(
            "parallel=True cannot be combined with include_nodes, exclude_nodes, "
            "input_overrides, or resume_run_id until those are wired into ParallelExecutor. "
            "Run without --parallel, or omit those options."
        )

    from app.core.logger import PipelineLogger
    from app.core.runs.run_journal import RunManager
    from app.core.runs.run_control import register_active_run, deregister_active_run

    if logger is None:
        logger = PipelineLogger()
    run = RunManager() if run_manager is None else run_manager

    resources = _RunResources()
    registered = False
    try:
        # Validate the partial-execution request before the run is registered
        # or marked running (a bad id must not leave a 'running' ghost).
        _validate_partial_request(graph, include_nodes, exclude_nodes)
        register_active_run(run)
        registered = True
        return await _run_pipeline_body(
            graph,
            run=run,
            logger=logger,
            resources=resources,
            use_cache=use_cache,
            checkpoint=checkpoint,
            streaming=streaming,
            parallel=parallel,
            observer=observer,
            max_workers=max_workers,
            resume_run_id=resume_run_id,
            include_nodes=include_nodes,
            exclude_nodes=exclude_nodes,
            input_overrides=input_overrides,
            event_driven=event_driven,
        )
    except BaseException as exc:
        cancelled = isinstance(exc, asyncio.CancelledError)
        try:
            cancelled = cancelled or _is_cancelled(run)
        except Exception:
            pass
        try:
            if cancelled:
                run.mark_cancelled()
            else:
                run.mark_failed(str(exc) or type(exc).__name__)
        except Exception:
            log.warning("failed to record terminal status for run %s",
                        getattr(run, "run_id", "?"), exc_info=True)
        try:
            run.save_logs(logger.logs)
        except Exception:
            pass
        raise
    finally:
        resources.teardown()
        if registered:
            deregister_active_run(run.run_id)


async def _run_pipeline_body(
    graph: Any,
    *,
    run: Any,
    logger: Any,
    resources: _RunResources,
    use_cache: bool,
    checkpoint: bool,
    streaming: bool,
    parallel: bool,
    observer: NodeObserver | None,
    max_workers: int | None,
    resume_run_id: str | None,
    include_nodes: list[str] | None,
    exclude_nodes: list[str] | None,
    input_overrides: dict | None,
    event_driven: bool,
) -> dict[str, Any]:
    """Execution body; the caller owns terminal status, teardown and deregistration."""
    from app.core.execution.pipeline_cache import PipelineCache
    from app.core.ir.loader import dump_ir
    from app.core.execution.planner import plain_jsonable

    # ── Logical vs materialized graph ──────────────────────────────────────────
    # Hash + seeds + cache keys come from the logical graph; execution uses the
    # run-scoped (materialized) configs.
    logical_hash = _logical_graph_hash(graph)
    logical_configs = {n.id: plain_jsonable(n.config) for n in graph.nodes}
    graph = _scope_graph_to_run(graph, run)
    try:
        run.save_graph_ir(dump_ir(graph), logical_hash=logical_hash)
    except TypeError:
        # Custom run managers without the logical_hash keyword.
        run.save_graph_ir(dump_ir(graph))
    graph_name = _graph_display_name(graph)
    if graph_name:
        run._write_meta_field("graph_name", graph_name)
    try:
        from app.core.runs.run_project import extract_project_fields_from_graph

        for key, value in extract_project_fields_from_graph(graph).items():
            run._write_meta_field(key, value)
    except Exception:
        log.warning("Failed to stamp project fields on run %s", run.run_id, exc_info=True)

    graph_hash = getattr(run, "_graph_hash", "") or logical_hash
    run_id = run.run_id
    all_node_ids = {n.id for n in graph.nodes}
    if include_nodes is not None:
        active_nodes: set[str] = set(include_nodes)
    elif exclude_nodes is not None:
        active_nodes = all_node_ids - set(exclude_nodes)
    else:
        active_nodes = all_node_ids
    is_partial = active_nodes != all_node_ids

    node_outputs: dict[str, dict[str, Any]] = {}
    node_stats: list[dict] = []

    # Queued-run cancel (API offline cancel / other process): refuse to start.
    if _is_cancelled(run):
        log.info("run %s was cancelled before it started — not executing", run_id)
        return _cancelled_result(run, logger, node_stats, node_outputs, len(active_nodes))
    # SRS §13.2: pending → running when executor starts work (compare-and-set).
    try:
        run.mark_running()
    except Exception:
        log.debug("mark_running failed for %s", run_id, exc_info=True)
    if _is_cancelled(run):
        return _cancelled_result(run, logger, node_stats, node_outputs, len(active_nodes))

    pipeline_cfg = ir_to_pipeline_config(graph)
    graph_obj = PipelineGraph(pipeline_cfg, observer=observer, seed_configs=logical_configs)

    cache = PipelineCache() if use_cache else None
    start_time = time.time()
    total_nodes = len(pipeline_cfg.nodes)

    logger.pipeline_start(
        total_nodes=len(active_nodes),
        partial=is_partial,
        included_nodes=sorted(active_nodes) if is_partial else None,
        run_id=run_id,
    )
    run._write_meta_field("num_nodes", len(active_nodes))

    from app.core.nodes import registry as node_registry

    # ── Setup executors ────────────────────────────────────────────────────────
    # Registered in ``resources`` as they are set up so the entry wrapper tears
    # down exactly the executors that exist, on any failure.
    def _cancel_check() -> bool:
        return bool(run.is_cancelled)

    for node_id in graph_obj.execution_order:
        exec_ = NodeExecutor(graph_obj.get_node(node_id), run_id=run_id)
        # Mode A cancel: kill isolated subprocesses / interrupt retry back-off.
        exec_.set_cancel_check(_cancel_check)
        exec_.setup()
        resources.executors[node_id] = exec_
    executors = resources.executors

    # ── Edge lookups ───────────────────────────────────────────────────────────
    incoming: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for edge in pipeline_cfg.edges:
        incoming[edge.dst_id].append((edge.src_id, edge.src_port, edge.dst_port))

    edge_conditions: dict[tuple[str, str, str, str], str | None] = {}
    for ir_edge in graph.edges:
        edge_conditions[
            (ir_edge.src_id, ir_edge.src_port, ir_edge.dst_id, ir_edge.dst_port)
        ] = ir_edge.condition

    # ── State ──────────────────────────────────────────────────────────────────
    completed_nodes: set[str] = set()
    skipped_nodes: list[str] = []
    # Nodes skipped because a required branch/condition input was unproduced (P1-1).
    branch_skipped: set[str] = set()

    # ── Resume ─────────────────────────────────────────────────────────────────
    if resume_run_id is not None:
        resume_state = run.load_resume_state(resume_run_id)
        # SA-O7: validate the LOGICAL graph hash before reusing checkpoints.
        saved_hash = resume_state.get("graph_hash", "")
        if saved_hash and saved_hash != graph_hash:
            raise ResumeError(
                f"Cannot resume: graph has changed since the checkpoint was written "
                f"(saved={saved_hash[:16]}…, current={graph_hash[:16]}…). "
                "Start a new run or use the original graph."
            )
        completed_nodes = set(resume_state.get("completed_nodes", []))
        from app.core.config import runs_dir as _runs_dir
        prior_run_path = os.path.join(str(_runs_dir()), resume_run_id)
        for node_id in list(completed_nodes):
            checkpoint_dir = os.path.join(prior_run_path, "checkpoints", f"node_{node_id}")
            manifest_path = os.path.join(checkpoint_dir, "manifest.json")
            if not os.path.exists(manifest_path):
                log.warning(
                    "Checkpoint missing for node '%s' in run '%s' — will re-execute",
                    node_id, resume_run_id,
                )
                completed_nodes.discard(node_id)
            else:
                loaded = load_checkpoint_outputs(checkpoint_dir)
                if loaded is not None:
                    node_outputs[node_id] = loaded
                    skipped_nodes.append(node_id)
                else:
                    completed_nodes.discard(node_id)

    if checkpoint:
        run.init_resume_state(graph_hash)
        # Carry resumed nodes forward so this run can itself be resumed.
        for node_id in skipped_nodes:
            try:
                run.update_resume_state(node_id)
            except Exception:
                pass

    # ── Parallel execution ─────────────────────────────────────────────────────
    if parallel:
        from app.core.execution.executor import ParallelExecutor

        par_exec = ParallelExecutor(max_workers=max_workers)
        node_index_map = {nid: idx for idx, nid in enumerate(graph_obj.execution_order)}
        ir_nodes_map = {ir_node.id: ir_node for ir_node in graph.nodes}

        try:
            for wave_idx, wave in enumerate(graph_obj.execution_waves):
                run.wait_if_paused()
                if _is_cancelled(run):
                    return _cancelled_result(
                        run, logger, node_stats, node_outputs, len(active_nodes)
                    )

                logger.wave_start(wave_idx, wave)
                wave_start_time = time.time()
                await par_exec.run_wave(
                    wave=wave,
                    graph_obj=graph_obj,
                    executors=executors,
                    node_outputs=node_outputs,
                    incoming=incoming,
                    pipeline_cfg=pipeline_cfg,
                    cache=cache,
                    checkpoint=checkpoint,
                    run_base_path=run.base_path,
                    logger=logger,
                    run_id=run_id,
                    total_nodes=total_nodes,
                    node_stats=node_stats,
                    streaming=streaming,
                    node_index_map=node_index_map,
                    ir_nodes_map=ir_nodes_map,
                    registry=node_registry,
                    run_manager=run,
                    edge_conditions=edge_conditions,
                    graph=graph,
                    cache_configs=logical_configs,
                )
                logger.wave_end(wave_idx, wave, time.time() - wave_start_time)
        finally:
            par_exec.shutdown()

    # ── Sequential execution ───────────────────────────────────────────────────
    elif not event_driven:
        for idx, node_id in enumerate(graph_obj.execution_order):
            if node_id in completed_nodes:
                node = graph_obj.get_node(node_id)
                logger.node_skip(node_id, stable_node_type(node), reason="resumed_from_checkpoint")
                continue

            if node_id not in active_nodes:
                excluded = graph_obj.get_node(node_id)
                logger.node_skip(
                    node_id, stable_node_type(excluded), reason="excluded_from_partial_execution"
                )
                node_outputs[node_id] = _excluded_node_outputs(
                    node_id, excluded, incoming, node_outputs, run
                )
                continue

            run.wait_if_paused()
            if _is_cancelled(run):
                return _cancelled_result(run, logger, node_stats, node_outputs, len(active_nodes))

            node = graph_obj.get_node(node_id)
            exec_ = executors[node_id]
            node_type = stable_node_type(node)

            logger.node_start(
                node_type, idx, total_nodes=len(active_nodes), node_id=node_id
            )
            node_start_time = time.time()

            node_overrides: dict[str, Any] = (
                dict(input_overrides.get(node_id) or {}) if input_overrides else {}
            )
            # Ports whose value is already provided (override, or an inactive
            # source's value from passthrough/checkpoint) — their edges must
            # not make the skip check treat the port as unproduced.
            provided_ports: set[str] = set(node_overrides)

            # Assemble inputs — cache condition results to avoid double-evaluation
            # in the skip-node check below (SA-O-COND fix).
            inputs: dict[str, Any] = {}
            _condition_results: dict[tuple[str, str, str], bool] = {}
            for src_id, src_port, dst_port in incoming[node_id]:
                if dst_port in node_overrides:
                    continue
                port = node.input_ports.get(dst_port)
                multi = bool(port and port.cardinality == "multi")
                if src_id not in active_nodes:
                    upstream = node_outputs.get(src_id)
                    value = upstream.get(src_port) if isinstance(upstream, dict) else None
                    if value is None:
                        ckpt = _safe_find_checkpoint(run, src_id)
                        value = ckpt.get(src_port) if ckpt else None
                    if value is not None:
                        provided_ports.add(dst_port)
                        if multi:
                            inputs.setdefault(dst_port, []).append(value)
                        else:
                            inputs[dst_port] = value
                    continue

                condition = edge_conditions.get((src_id, src_port, node_id, dst_port))
                if condition is not None:
                    from app.core.execution.conditions import evaluate_condition, ConditionEvaluationError
                    src_outputs = node_outputs.get(src_id, {})
                    try:
                        passes = evaluate_condition(condition, src_outputs)
                    except ConditionEvaluationError as exc:
                        logger.node_error(node_type, idx, exc)
                        run.save_logs(logger.logs)
                        run.mark_failed(str(exc), node_stats=node_stats)
                        raise
                    _condition_results[(src_id, src_port, dst_port)] = passes
                    if not passes:
                        # Unproduced — do not inject None (P1-1 / T1).
                        continue

                if src_id in branch_skipped:
                    continue

                upstream_outputs = node_outputs.get(src_id, {})
                if not isinstance(upstream_outputs, dict) or src_port not in upstream_outputs:
                    # Inactive if_switch branch or empty skip outputs.
                    continue
                value = upstream_outputs.get(src_port)
                if multi:
                    inputs.setdefault(dst_port, []).append(value)
                else:
                    inputs[dst_port] = value

            # Overrides apply BEFORE the skip check so an override can feed a
            # node whose upstream is excluded / unproduced.
            inputs.update(node_overrides)

            # Skip when a required port is unproduced (condition / branch / upstream skip).
            from app.core.execution.skip_logic import should_skip_for_unproduced

            skip_view = {
                node_id: [e for e in incoming[node_id] if e[2] not in provided_ports]
            }
            skip_node, skip_reason = should_skip_for_unproduced(
                node_id=node_id,
                node=node,
                incoming=skip_view,
                node_outputs=node_outputs,
                skipped=branch_skipped,
                edge_conditions=edge_conditions,
                condition_results=_condition_results,
            )
            if skip_node:
                logger.node_skip(node_id, node_type, reason=skip_reason or "condition_false")
                node_outputs[node_id] = {}
                branch_skipped.add(node_id)
                continue

            for port_name, port in node.input_ports.items():
                if port_name not in inputs and not port.required:
                    inputs[port_name] = None

            # Cache check — load() directly; None is a miss (ARCH-9: no has()).
            cache_hit = False
            cache_key: str | None = None
            if cache is not None:
                node_cfg_dict = logical_configs.get(node_id)
                if node_cfg_dict is None:
                    node_cfg_dict = next(
                        (spec.config for spec in pipeline_cfg.nodes if spec.node_id == node_id), {}
                    )
                _node_version: str | None = None
                try:
                    from app.core.host.registry_runtime import get_registry as _get_reg_cache

                    _node_version = _get_reg_cache().get_metadata(node_type).version
                except Exception:
                    _node_version = None
                cache_key = cache.compute_key(
                    node_type,
                    node_cfg_dict,
                    inputs,
                    node_seed=getattr(node, "seed", None),
                    node_version=_node_version,
                )
                cached_result = cache.load(cache_key)
                if cached_result is not None:
                    node_outputs[node_id] = cached_result
                    cache_hit = True
                    logger.info(f"[{idx}] {node_type} — cache hit")

            if not cache_hit:
                try:
                    if streaming and node.is_streaming:
                        outputs = await _collect_stream(exec_, inputs)
                    else:
                        outputs = exec_.execute(inputs)
                except Exception as exc:
                    logger.node_error(node_type, idx, exc, node_id=node_id)
                    run.save_logs(logger.logs)
                    if not _is_cancelled(run):
                        run.mark_failed(
                            str(exc),
                            node_stats=node_stats,
                            failed_node_id=node_id,
                            failed_node_type=node_type,
                        )
                    raise

                node_outputs[node_id] = outputs

                if cache is not None and cache_key is not None:
                    cacheable = True
                    ir_node = next((n for n in graph.nodes if n.id == node_id), None)
                    if ir_node is not None:
                        try:
                            from app.core.host.registry_runtime import get_registry as _get_reg
                            cap = _resolve_capability_impl(ir_node, _get_reg())
                            cacheable = cap.cacheable
                        except Exception:
                            cacheable = True
                    if cacheable:
                        cache.save(cache_key, outputs)

            if checkpoint:
                write_checkpoint(
                    run.base_path,
                    node_id,
                    node_outputs[node_id],
                    logger=logger,
                    graph_hash=graph_hash,
                )
                run.update_resume_state(node_id)

            _prior_artifact_ids: list[str] = []
            for _src_id, _src_port, _dst_port in incoming[node_id]:
                _prior_artifact_ids.extend(
                    r.artifact_id for r in run._artifacts if r.node_id == _src_id
                )
            _registered_this_node: set[str] = set()
            for _port_name, _port_value in node_outputs[node_id].items():
                if _port_value is None:
                    continue
                _artifact_type = infer_artifact_type(_port_value)
                try:
                    _rec = run.register_artifact(
                        node_id=node_id,
                        node_type=node_type,
                        artifact_type=_artifact_type,
                        data=_port_value,
                        metadata={"port": _port_name},
                        input_artifact_ids=[
                            aid for aid in _prior_artifact_ids
                            if aid not in _registered_this_node
                        ],
                    )
                    _registered_this_node.add(_rec.artifact_id)
                except Exception as _art_exc:
                    log.warning(
                        "Artifact registration failed for node '%s' port '%s': %s",
                        node_id, _port_name, _art_exc,
                    )

            node_duration = time.time() - node_start_time
            # SA-O-CNT: list length for list ports, 1 per non-None scalar port.
            _output_count = sum(
                len(v) if isinstance(v, list) else (0 if v is None else 1)
                for v in node_outputs[node_id].values()
            )
            logger.node_end(
                node_type,
                idx,
                node_duration,
                output_count=_output_count,
                node_id=node_id,
            )
            node_stats.append(
                _node_stat_record(
                    node_id, node_type, idx, node_duration, cache_hit=cache_hit
                )
            )
            _persist_node_stats(run, node_stats)

    # ── Event-driven execution ─────────────────────────────────────────────────
    if event_driven:
        handled = await _run_event_driven(
            graph=graph,
            graph_obj=graph_obj,
            run=run,
            logger=logger,
            executors=executors,
            active_nodes=active_nodes,
            incoming=incoming,
            edge_conditions=edge_conditions,
            node_outputs=node_outputs,
            node_stats=node_stats,
            start_time=start_time,
            graph_name=graph_name,
        )
        if handled:
            last_id = graph_obj.execution_order[-1]
            return node_outputs.get(last_id, {})

    # ── Finalize ───────────────────────────────────────────────────────────────
    # A cancel that landed during the last node must end as cancelled, never
    # be overwritten by succeeded.
    if _is_cancelled(run):
        return _cancelled_result(run, logger, node_stats, node_outputs, len(active_nodes))

    total_duration = time.time() - start_time
    logger.summary()
    try:
        logger.pipeline_done(run.run_id, total_duration)
    except Exception:
        log.debug("pipeline_done emit failed", exc_info=True)
    run.save_logs(logger.logs)
    run.save_metadata({
        "num_nodes": len(active_nodes),
        "node_stats": node_stats,
        "duration_s": round(total_duration, 4),
        **({"graph_name": graph_name} if graph_name else {}),
        **_finalize_run_artifacts(run, graph),
        **(
            {"partial_execution": True, "included_nodes": sorted(active_nodes)}
            if is_partial and include_nodes is not None else {}
        ),
        **(
            {"partial_execution": True, "excluded_nodes": sorted(set(exclude_nodes or []))}
            if is_partial and exclude_nodes is not None else {}
        ),
        **(
            {
                "resumed_from": resume_run_id,
                "skipped_nodes": skipped_nodes,
                "executed_nodes": [s["node_id"] for s in node_stats],
            }
            if resume_run_id is not None else {}
        ),
    })

    last_id = graph_obj.execution_order[-1]
    # SA-O-LAST: distinguish "empty output" from "last node skipped/excluded".
    if last_id not in node_outputs:
        log.warning(
            "Last node '%s' produced no outputs (skipped or excluded). "
            "Returning empty dict.",
            last_id,
        )
    return node_outputs.get(last_id, {})


def _reachable_from(start: str, edges: Any) -> set[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        adjacency[e.src_id].add(e.dst_id)
    seen: set[str] = set()
    stack = [start]
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(adjacency.get(nid, ()))
    return seen


async def _run_event_driven(
    *,
    graph: Any,
    graph_obj: Any,
    run: Any,
    logger: Any,
    executors: dict[str, NodeExecutor],
    active_nodes: set[str],
    incoming: dict[str, list[tuple[str, str, str]]],
    edge_conditions: dict[tuple[str, str, str, str], str | None],
    node_outputs: dict[str, dict[str, Any]],
    node_stats: list,
    start_time: float,
    graph_name: str | None,
) -> bool:
    """Event-driven loop. Returns False when the graph has no trigger nodes.

    - Each event runs only the trigger node and nodes reachable from it (not
      every later node in topo order — other triggers stay idle).
    - Chains are serialized with a lock (node executors are not re-entrant).
    - The first failure or cancel stops ALL sources: the watcher closes every
      source and cancels idle handler tasks, so an idle source cannot hang
      the run. The failure status is never overwritten by a later cancel.
    """
    from app.core.execution.events import EventSource, create_event_source

    trigger_nodes = {
        ir_node.id: ir_node.event_trigger
        for ir_node in graph.nodes
        if ir_node.event_trigger is not None
    }
    if not trigger_nodes:
        log.warning("event_driven=True but no nodes have event_trigger set — running normally")
        return False

    exec_order = list(graph_obj.execution_order)
    chains: dict[str, list[str]] = {}
    for trig_id in trigger_nodes:
        reach = _reachable_from(trig_id, graph.edges)
        chains[trig_id] = [nid for nid in exec_order if nid in reach]

    sources: dict[str, EventSource] = {}
    closed: set[str] = set()
    try:
        for node_id, trigger in trigger_nodes.items():
            sources[node_id] = create_event_source(trigger["source_type"], trigger["source_config"])
    except Exception:
        for src in sources.values():
            try:
                await src.close()
            except Exception:
                pass
        raise

    async def _close_sources() -> None:
        for nid, src in sources.items():
            if nid in closed:
                continue
            closed.add(nid)
            try:
                await src.close()
            except Exception:
                log.warning("event source close failed for %s", nid, exc_info=True)

    state: dict[str, Any] = {"terminal": None, "trigger_count": 0}
    exec_lock = asyncio.Lock()

    async def _wait_if_paused() -> None:
        while run.is_paused and not run.is_cancelled:
            await asyncio.sleep(0.1)

    async def _run_chain(trigger_id: str, payload: dict) -> bool:
        for exec_node_id in chains[trigger_id]:
            await _wait_if_paused()
            if state["terminal"] is not None:
                return False
            if _is_cancelled(run):
                state["terminal"] = "cancelled"
                return False
            if exec_node_id not in active_nodes:
                continue
            exec_node = graph_obj.get_node(exec_node_id)
            exec_obj = executors[exec_node_id]
            exec_node_type = stable_node_type(exec_node)
            exec_idx = exec_order.index(exec_node_id)

            exec_inputs: dict[str, Any] = {}
            if exec_node_id == trigger_id:
                exec_inputs = dict(payload)
            else:
                for src_id, src_port, dst_port in incoming[exec_node_id]:
                    if src_id not in node_outputs:
                        continue
                    condition = edge_conditions.get((src_id, src_port, exec_node_id, dst_port))
                    if condition:
                        from app.core.execution.conditions import evaluate_condition
                        try:
                            if not evaluate_condition(condition, node_outputs.get(src_id, {})):
                                continue
                        except Exception:
                            continue
                    exec_inputs[dst_port] = node_outputs[src_id].get(src_port)

            for port_name, port in exec_node.input_ports.items():
                if port_name not in exec_inputs and not port.required:
                    exec_inputs[port_name] = None

            logger.node_start(
                exec_node_type, exec_idx, total_nodes=len(active_nodes), node_id=exec_node_id
            )
            _node_start_time = time.time()
            try:
                exec_outputs = await asyncio.to_thread(exec_obj.execute, exec_inputs)
            except Exception as exc:
                logger.node_error(exec_node_type, exec_idx, exc, node_id=exec_node_id)
                if _is_cancelled(run):
                    state["terminal"] = "cancelled"
                else:
                    run.mark_failed(
                        str(exc),
                        node_stats=node_stats,
                        failed_node_id=exec_node_id,
                        failed_node_type=exec_node_type,
                    )
                    state["terminal"] = "failed"
                return False
            node_outputs[exec_node_id] = exec_outputs
            _node_duration = time.time() - _node_start_time
            _output_count = sum(
                len(v) if isinstance(v, list) else (0 if v is None else 1)
                for v in exec_outputs.values()
            )
            logger.node_end(
                exec_node_type, exec_idx, _node_duration,
                output_count=_output_count, node_id=exec_node_id,
            )
            node_stats.append(
                _node_stat_record(exec_node_id, exec_node_type, exec_idx, _node_duration)
            )
            _persist_node_stats(run, node_stats)
        return True

    async def _handle_source(node_id: str, source: EventSource) -> None:
        source_type = trigger_nodes[node_id]["source_type"]
        async for payload in source.watch():
            await _wait_if_paused()
            if state["terminal"] is not None:
                break
            if _is_cancelled(run):
                state["terminal"] = "cancelled"
                break
            logger.event_received(
                source_type=source_type,
                node_id=node_id,
                payload_keys=list(payload.keys()),
            )
            async with exec_lock:
                ok = await _run_chain(node_id, payload)
            if not ok:
                break
            state["trigger_count"] += 1

    tasks = [
        asyncio.create_task(_handle_source(nid, src)) for nid, src in sources.items()
    ]

    async def _watcher() -> None:
        while state["terminal"] is None and not run.is_cancelled:
            if all(t.done() for t in tasks):
                return
            await asyncio.sleep(0.2)
        if state["terminal"] is None:
            state["terminal"] = "cancelled"
        await _close_sources()
        # Wait for any in-flight chain to reach a node boundary, then cancel
        # handlers still blocked on an idle source.
        async with exec_lock:
            for t in tasks:
                if not t.done():
                    t.cancel()

    watcher = asyncio.create_task(_watcher())
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        await _close_sources()

    source_error: BaseException | None = None
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            continue
        if isinstance(result, BaseException) and source_error is None:
            source_error = result
    if source_error is not None and state["terminal"] != "failed":
        state["terminal"] = "failed"
        run.mark_failed(str(source_error) or type(source_error).__name__, node_stats=node_stats)
        raise source_error
    if state["terminal"] is None and _is_cancelled(run):
        state["terminal"] = "cancelled"

    _finalize_event_driven_run(
        run,
        logger,
        state["terminal"],
        active_nodes=active_nodes,
        node_stats=node_stats,
        start_time=start_time,
        trigger_count=state["trigger_count"],
        graph_name=graph_name,
        graph=graph,
    )
    return True


# ── Synchronous shim ───────────────────────────────────────────────────────────

def run_pipeline_ir(
    graph: Any,
    logger: Any = None,
    use_cache: bool = True,
    checkpoint: bool = False,
    streaming: bool = False,
    parallel: bool = False,
    observer: NodeObserver | None = None,
    run_manager: Any = None,
    max_workers: int | None = None,
    resume_run_id: str | None = None,
    include_nodes: list[str] | None = None,
    exclude_nodes: list[str] | None = None,
    input_overrides: dict | None = None,
    event_driven: bool = False,
    # SA-O3: event_loop parameter removed — it was accepted but never used.
) -> dict[str, Any]:
    """Execute a pipeline from a GraphIR object (synchronous entry point).

    Delegates to run_pipeline_ir_async() via asyncio.run().
    Cannot be called from an async context — use run_pipeline_ir_async() directly.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        raise RuntimeError(
            "run_pipeline_ir() cannot be called from an async context "
            "(a running event loop was detected). "
            "Use 'await run_pipeline_ir_async(...)' instead."
        )

    return asyncio.run(run_pipeline_ir_async(
        graph=graph,
        logger=logger,
        use_cache=use_cache,
        checkpoint=checkpoint,
        streaming=streaming,
        parallel=parallel,
        observer=observer,
        run_manager=run_manager,
        max_workers=max_workers,
        resume_run_id=resume_run_id,
        include_nodes=include_nodes,
        exclude_nodes=exclude_nodes,
        input_overrides=input_overrides,
        event_driven=event_driven,
    ))

# Public names. A leading underscore stays private to this module.
logical_graph_hash = _logical_graph_hash
scope_graph_to_run = _scope_graph_to_run
