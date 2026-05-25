# app/core/orchestrator.py
"""Pipeline orchestrator — coordinates full pipeline execution.

Extracted from pipeline.py. Responsible for:
  - run_pipeline_ir_async  — async execution entry point
  - run_pipeline_ir        — synchronous shim
  - _resolve_capability    — IRNode capability resolution
  - _collect_stream        — streaming output collector
"""
from __future__ import annotations

import asyncio
import hashlib as _hashlib
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any

from app.core.nodes.errors import ResumeError
from app.core.nodes.observers import NodeObserver
from app.core.artifact_store import _infer_artifact_type
from app.core.planner import (
    PipelineConfig,
    PipelineGraph,
    _ir_to_pipeline_config,
)
from app.core.node_executor import NodeExecutor
from app.core.checkpoint import _write_checkpoint, _load_checkpoint_outputs
from app.core.utils import collect_stream as _collect_stream

log = logging.getLogger(__name__)


# ── Capability resolution ──────────────────────────────────────────────────────

def _resolve_capability(ir_node: Any, registry: Any) -> Any:
    """Resolve capability metadata for a node instance.

    Precedence: IRNode.capability_metadata > NodeMetadata capability fields.
    Falls back to IRCapabilityMetadata() defaults for unknown node types.
    """
    from app.core.ir.models import IRCapabilityMetadata

    if ir_node.capability_metadata is not None:
        return ir_node.capability_metadata

    try:
        meta = registry.get_metadata(ir_node.node_type)
        return IRCapabilityMetadata(
            requires_gpu=meta.requires_gpu,
            supports_cpu=meta.supports_cpu,
            supports_edge=meta.supports_edge,
            deterministic=meta.deterministic,
            cacheable=meta.cacheable,
            streaming_support=meta.streaming_support,
            realtime_support=meta.realtime_support,
            memory_requirements=meta.memory_requirements,
            dependency_requirements=meta.dependency_requirements,
            batch_support=meta.batch_support,
        )
    except Exception:
        return IRCapabilityMetadata()


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
    """
    if parallel and event_driven:
        raise ValueError(
            "parallel and event_driven are mutually exclusive execution modes. "
            "Pass only one of parallel=True or event_driven=True."
        )

    from app.core.logger import PipelineLogger
    from app.core.run_journal import RunManager
    from app.core.run_control import register_active_run, deregister_active_run
    from app.core.pipeline_cache import PipelineCache
    from app.core.ir.loader import dump_ir

    if logger is None:
        logger = PipelineLogger()

    if run_manager is None:
        run = RunManager()
    else:
        run = run_manager

    run.save_graph_ir(dump_ir(graph))
    register_active_run(run)

    pipeline_cfg = _ir_to_pipeline_config(graph)
    graph_obj = PipelineGraph(pipeline_cfg, observer=observer)

    # Use the graph hash already computed by save_graph_ir
    graph_hash = run._graph_hash

    run_id = run.run_id
    cache = PipelineCache() if use_cache else None
    start_time = time.time()
    total_nodes = len(pipeline_cfg.nodes)

    # ── Partial execution ──────────────────────────────────────────────────────
    if include_nodes is not None and exclude_nodes is not None:
        raise ValueError("include_nodes and exclude_nodes are mutually exclusive")

    all_node_ids = {n.id for n in graph.nodes}

    for nid in (include_nodes or []) + (exclude_nodes or []):
        if nid not in all_node_ids:
            raise ValueError(f"Unknown node ID '{nid}' in partial execution request")

    if include_nodes is not None:
        active_nodes: set[str] = set(include_nodes)
    elif exclude_nodes is not None:
        active_nodes = all_node_ids - set(exclude_nodes)
    else:
        active_nodes = all_node_ids

    is_partial = active_nodes != all_node_ids

    logger.pipeline_start(
        total_nodes=len(active_nodes),
        partial=is_partial,
        included_nodes=sorted(active_nodes) if is_partial else None,
    )

    # ── Setup executors ────────────────────────────────────────────────────────
    executors: dict[str, NodeExecutor] = {}
    for node_id in graph_obj.execution_order:
        exec_ = NodeExecutor(graph_obj.get_node(node_id), run_id=run_id)
        exec_.setup()
        executors[node_id] = exec_

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
    node_outputs: dict[str, dict[str, Any]] = {}
    node_stats: list[dict] = []
    completed_nodes: set[str] = set()
    skipped_nodes: list[str] = []

    # ── Resume ─────────────────────────────────────────────────────────────────
    if resume_run_id is not None:
        resume_state = run.load_resume_state(resume_run_id)
        # SA-O7 fix: validate graph hash before reusing stale checkpoints.
        # If the graph has changed since the checkpoint was written, resume
        # would silently produce incorrect results.
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
                loaded = _load_checkpoint_outputs(checkpoint_dir)
                if loaded is not None:
                    node_outputs[node_id] = loaded
                    skipped_nodes.append(node_id)
                else:
                    completed_nodes.discard(node_id)

    if checkpoint:
        run.init_resume_state(graph_hash)

    # ── Parallel execution ─────────────────────────────────────────────────────
    if parallel:
        from app.core.executor import ParallelExecutor
        from app.core.nodes import registry as node_registry

        par_exec = ParallelExecutor(max_workers=max_workers)
        node_index_map = {nid: idx for idx, nid in enumerate(graph_obj.execution_order)}
        ir_nodes_map = {ir_node.id: ir_node for ir_node in graph.nodes}

        for wave_idx, wave in enumerate(graph_obj.execution_waves):
            if run.is_cancelled:
                nodes_completed = len(node_stats)
                nodes_remaining = len(active_nodes) - nodes_completed
                logger.pipeline_cancelled(run.run_id, nodes_completed, nodes_remaining)
                for exec_ in executors.values():
                    exec_.teardown()
                run.mark_cancelled()
                run.save_logs(logger.logs)
                deregister_active_run(run.run_id)
                last_completed = node_stats[-1]["node_id"] if node_stats else None
                return node_outputs.get(last_completed, {}) if last_completed else {}

            logger.wave_start(wave_idx, wave)
            wave_start_time = time.time()
            try:
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
                )
            except Exception as exc:
                run.save_logs(logger.logs)
                run.mark_failed(str(exc))
                deregister_active_run(run.run_id)
                raise
            logger.wave_end(wave_idx, wave, time.time() - wave_start_time)

        # Shut down the shared thread pool now that all waves are done
        par_exec.shutdown()

    # ── Sequential execution ───────────────────────────────────────────────────
    elif not event_driven:
        for idx, node_id in enumerate(graph_obj.execution_order):
            if node_id in completed_nodes:
                node = graph_obj.get_node(node_id)
                logger.node_skip(node_id, type(node).__name__, reason="resumed_from_checkpoint")
                continue

            if node_id not in active_nodes:
                node_type = type(graph_obj.get_node(node_id)).__name__
                logger.node_skip(node_id, node_type, reason="excluded_from_partial_execution")
                passthrough: dict[str, Any] = {}
                for src_id, src_port, dst_port in incoming[node_id]:
                    upstream = node_outputs.get(src_id, {})
                    value = upstream.get(src_port)
                    # SA-O4 fix: only set the actual dst_port — do NOT also set
                    # passthrough["output"] unconditionally, which would overwrite
                    # a previously set dst_port for multi-port excluded nodes.
                    passthrough[dst_port] = value
                node_outputs[node_id] = passthrough
                continue

            run.wait_if_paused()
            if run.is_cancelled:
                nodes_completed = len(node_stats)
                nodes_remaining = len(active_nodes) - nodes_completed
                logger.pipeline_cancelled(run.run_id, nodes_completed, nodes_remaining)
                for exec_ in executors.values():
                    exec_.teardown()
                run.mark_cancelled()
                run.save_logs(logger.logs)
                deregister_active_run(run.run_id)
                last_completed = node_stats[-1]["node_id"] if node_stats else None
                return node_outputs.get(last_completed, {}) if last_completed else {}

            node = graph_obj.get_node(node_id)
            exec_ = executors[node_id]
            node_type = type(node).__name__

            logger.node_start(node_type, idx, total_nodes=len(active_nodes))
            node_start_time = time.time()

            # Assemble inputs
            inputs: dict[str, Any] = {}
            for src_id, src_port, dst_port in incoming[node_id]:
                if src_id not in active_nodes:
                    if input_overrides and node_id in input_overrides and dst_port in input_overrides[node_id]:
                        inputs[dst_port] = input_overrides[node_id][dst_port]
                    elif src_id in node_outputs and node_outputs[src_id].get(src_port) is not None:
                        inputs[dst_port] = node_outputs[src_id][src_port]
                    else:
                        checkpoint_outputs = run.find_latest_checkpoint(src_id)
                        inputs[dst_port] = checkpoint_outputs.get(src_port) if checkpoint_outputs else None
                    continue

                condition = edge_conditions.get((src_id, src_port, node_id, dst_port))
                if condition is not None:
                    from app.core.conditions import evaluate_condition, ConditionEvaluationError
                    src_outputs = node_outputs.get(src_id, {})
                    try:
                        passes = evaluate_condition(condition, src_outputs)
                    except ConditionEvaluationError as exc:
                        logger.node_error(node_type, idx, exc)
                        run.save_logs(logger.logs)
                        run.mark_failed(str(exc))
                        deregister_active_run(run.run_id)
                        raise
                    if not passes:
                        inputs[dst_port] = None
                        continue

                upstream_outputs = node_outputs[src_id]
                value = upstream_outputs.get(src_port)
                port = node.input_ports.get(dst_port)
                if port and port.cardinality == "multi":
                    inputs.setdefault(dst_port, [])
                    inputs[dst_port].append(value)
                else:
                    inputs[dst_port] = value

            # Skip node if required port has None from a false condition
            skip_node = False
            for port_name, port in node.input_ports.items():
                if port.required and inputs.get(port_name) is None:
                    false_condition_ports: set[str] = set()
                    for src_id, src_port, dst_port in incoming[node_id]:
                        if dst_port != port_name:
                            continue
                        condition = edge_conditions.get((src_id, src_port, node_id, dst_port))
                        if condition is not None:
                            from app.core.conditions import evaluate_condition
                            src_outputs = node_outputs.get(src_id, {})
                            try:
                                if not evaluate_condition(condition, src_outputs):
                                    false_condition_ports.add(dst_port)
                            except Exception:
                                pass
                    if port_name in false_condition_ports:
                        logger.node_skip(node_id, node_type, reason="condition_false")
                        node_outputs[node_id] = {}
                        skip_node = True
                        break

            if skip_node:
                continue

            if input_overrides and node_id in input_overrides:
                for port_name, override_value in input_overrides[node_id].items():
                    inputs[port_name] = override_value

            for port_name, port in node.input_ports.items():
                if port_name not in inputs and not port.required:
                    inputs[port_name] = None

            # Cache check — call load() directly and treat None as a miss.
            # Do NOT call cache.has() first: has() + load() is a TOCTOU race
            # (the entry can be deleted between the two calls). load() returning
            # None is the authoritative cache-miss signal (ARCH-9 fix).
            cache_hit = False
            cache_key: str | None = None
            if cache is not None:
                node_cfg_dict = next(
                    (spec.config for spec in pipeline_cfg.nodes if spec.node_id == node_id), {}
                )
                # NEW-6 fix: hash each port separately and combine so port
                # identity is preserved. list(inputs.values()) loses port names
                # and causes key collisions for multi-port nodes.
                combined_input_hash = _hashlib.sha256(
                    "".join(cache.input_hash(v) for v in inputs.values()).encode()
                ).hexdigest()
                cache_key = cache.key(node_type, node_cfg_dict, combined_input_hash)
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
                    logger.node_error(node_type, idx, exc)
                    run.save_logs(logger.logs)
                    run.mark_failed(str(exc))
                    deregister_active_run(run.run_id)
                    raise

                node_outputs[node_id] = outputs

                if cache is not None and cache_key is not None:
                    cacheable = True
                    ir_node = next((n for n in graph.nodes if n.id == node_id), None)
                    if ir_node is not None:
                        try:
                            from app.core.registry_runtime import get_registry as _get_reg
                            cap = _resolve_capability(ir_node, _get_reg())
                            cacheable = cap.cacheable
                        except Exception:
                            cacheable = True
                    if cacheable:
                        cache.save(cache_key, outputs)

            if checkpoint:
                _write_checkpoint(run.base_path, node_id, node_outputs[node_id], logger=logger)
                run.update_resume_state(node_id)

            if not cache_hit:
                _prior_artifact_ids: list[str] = []
                for _src_id, _src_port, _dst_port in incoming[node_id]:
                    _prior_artifact_ids.extend(
                        r.artifact_id for r in run._artifacts if r.node_id == _src_id
                    )
                _registered_this_node: set[str] = set()
                for _port_name, _port_value in node_outputs[node_id].items():
                    if _port_value is None:
                        continue
                    _artifact_type = _infer_artifact_type(_port_value)
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
            _output_count = 0
            for _v in node_outputs[node_id].values():
                if isinstance(_v, list):
                    _output_count = len(_v)
                    break
            logger.node_end(node_type, idx, node_duration, output_count=_output_count)
            node_stats.append({
                "node_id": node_id,
                "node_type": node_type,
                "node_index": idx,
                "duration_s": round(node_duration, 4),
            })

    # ── Event-driven execution ─────────────────────────────────────────────────
    if event_driven:
        from app.core.events import EventSource, create_event_source

        trigger_nodes = {
            ir_node.id: ir_node.event_trigger
            for ir_node in graph.nodes
            if ir_node.event_trigger is not None
        }

        if not trigger_nodes:
            log.warning("event_driven=True but no nodes have event_trigger set — running normally")
        else:
            sources: dict[str, EventSource] = {
                node_id: create_event_source(trigger["source_type"], trigger["source_config"])
                for node_id, trigger in trigger_nodes.items()
            }

            trigger_count = 0

            async def _handle_source(node_id: str, source: EventSource) -> None:
                nonlocal trigger_count
                source_type = trigger_nodes[node_id]["source_type"]
                async for payload in source.watch():
                    if run.is_cancelled:
                        break
                    logger.event_received(
                        source_type=source_type,
                        node_id=node_id,
                        payload_keys=list(payload.keys()),
                    )
                    exec_order = list(graph_obj.execution_order)
                    try:
                        trigger_idx = exec_order.index(node_id)
                    except ValueError:
                        trigger_idx = 0

                    for exec_node_id in exec_order[trigger_idx:]:
                        if exec_node_id not in active_nodes:
                            continue
                        exec_node = graph_obj.get_node(exec_node_id)
                        exec_obj = executors[exec_node_id]
                        exec_node_type = type(exec_node).__name__
                        exec_idx = exec_order.index(exec_node_id)

                        exec_inputs: dict[str, Any] = {}
                        if exec_node_id == node_id:
                            exec_inputs = dict(payload)
                        else:
                            for src_id, src_port, dst_port in incoming[exec_node_id]:
                                if src_id in node_outputs:
                                    condition = edge_conditions.get(
                                        (src_id, src_port, exec_node_id, dst_port)
                                    )
                                    if condition:
                                        from app.core.conditions import evaluate_condition
                                        src_outputs = node_outputs.get(src_id, {})
                                        try:
                                            if not evaluate_condition(condition, src_outputs):
                                                continue
                                        except Exception:
                                            continue
                                    exec_inputs[dst_port] = node_outputs[src_id].get(src_port)

                        for port_name, port in exec_node.input_ports.items():
                            if port_name not in exec_inputs and not port.required:
                                exec_inputs[port_name] = None

                        logger.node_start(exec_node_type, exec_idx, total_nodes=len(active_nodes))
                        _node_start_time = time.time()
                        try:
                            exec_outputs = exec_obj.execute(exec_inputs)
                            node_outputs[exec_node_id] = exec_outputs
                        except Exception as exc:
                            logger.node_error(exec_node_type, exec_idx, exc)
                            break
                        _node_duration = time.time() - _node_start_time
                        _output_count = 0
                        for _v in exec_outputs.values():
                            if isinstance(_v, list):
                                _output_count = len(_v)
                                break
                        logger.node_end(exec_node_type, exec_idx, _node_duration,
                                        output_count=_output_count)
                        node_stats.append({
                            "node_id": exec_node_id,
                            "node_type": exec_node_type,
                            "node_index": exec_idx,
                            "duration_s": round(_node_duration, 4),
                        })
                    trigger_count += 1

            async def _cancel_watcher() -> None:
                while not run.is_cancelled:
                    await asyncio.sleep(0.2)
                for src in sources.values():
                    await src.close()

            try:
                tasks = [
                    asyncio.create_task(_handle_source(nid, src))
                    for nid, src in sources.items()
                ]
                cancel_task = asyncio.create_task(_cancel_watcher())
                await asyncio.gather(*tasks, return_exceptions=True)
                cancel_task.cancel()
            except asyncio.CancelledError:
                pass
            finally:
                # SA-O2 fix: always deregister, even if asyncio.gather raises
                # an unexpected exception (not just CancelledError).
                for src in sources.values():
                    await src.close()
                deregister_active_run(run.run_id)

            for exec_ in executors.values():
                exec_.teardown()

            run.save_logs(logger.logs)
            run.save_metadata({
                "num_nodes": len(active_nodes),
                "node_stats": node_stats,
                "duration_s": round(time.time() - start_time, 4),
                "event_driven": True,
                "trigger_count": trigger_count,
            })
            last_id = graph_obj.execution_order[-1]
            return node_outputs.get(last_id, {})

    # ── Teardown and finalize ──────────────────────────────────────────────────
    for exec_ in executors.values():
        exec_.teardown()

    total_duration = time.time() - start_time
    logger.summary()
    run.save_logs(logger.logs)
    run.save_metadata({
        "num_nodes": len(active_nodes),
        "node_stats": node_stats,
        "duration_s": round(total_duration, 4),
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
    deregister_active_run(run.run_id)
    return node_outputs.get(last_id, {})


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
