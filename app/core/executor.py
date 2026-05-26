# app/core/executor.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Execute all nodes in a single parallel wave concurrently.
Owns:             ParallelExecutor — wave-level concurrent execution.
Public Surface:   ParallelExecutor.run_wave(), ParallelExecutor.shutdown()
Must NOT:         Understand audio domain logic, import from app.domain,
                  import from orchestrator (avoids intra-BC5 circular coupling).
Dependencies:     BC2 (nodes.base via executors), BC3 (registry_runtime for
                  capability resolution), BC6 (checkpoint, artifact_store),
                  app.core.utils (collect_stream), app.core.conditions.
Reason To Change: Parallel execution strategy changes (thread pool sizing,
                  wave scheduling, error propagation policy).
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# SA-O5 fix: import the shared stream collector instead of duplicating it here.
from app.core.utils import collect_stream as _collect_stream_parallel


class ParallelExecutor:
    """Executes nodes within a wave concurrently.

    For each wave, all nodes are launched as asyncio tasks:
    - Sync nodes (``node.is_streaming = False``) are offloaded to a
      ``ThreadPoolExecutor`` via ``loop.run_in_executor()`` to avoid blocking
      the event loop.
    - Streaming nodes (``node.is_streaming = True``) are awaited directly via
      ``NodeExecutor.execute_stream()``.

    Results are gathered with ``asyncio.gather(..., return_exceptions=True)``.
    If any task raises an exception, the first exception is re-raised after all
    tasks have been awaited (no cancellation of already-running tasks, since
    ``asyncio.gather`` with ``return_exceptions=True`` waits for all).

    Req 1.2, 1.3, 1.4, 1.8, 1.10
    """

    def __init__(self, max_workers: int | None = None) -> None:
        self._max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        # Single pool shared across ALL waves in a pipeline run (SCALE-3 fix).
        # Created lazily on first use and reused for every subsequent wave,
        # avoiding repeated pool creation/teardown overhead for multi-wave pipelines.
        self._pool: ThreadPoolExecutor | None = None

    def _get_pool(self) -> ThreadPoolExecutor:
        """Return the shared thread pool, creating it on first call."""
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self._max_workers)
        return self._pool

    def shutdown(self) -> None:
        """Shut down the shared thread pool. Call once after all waves complete."""
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None

    async def run_wave(
        self,
        wave: list[str],
        graph_obj: Any,           # PipelineGraph
        executors: dict,          # node_id -> NodeExecutor
        node_outputs: dict,       # node_id -> outputs dict (mutated in place)
        incoming: dict,           # node_id -> [(src_id, src_port, dst_port)]
        pipeline_cfg: Any,        # PipelineConfig
        cache: Any,               # PipelineCache | None
        checkpoint: bool,
        run_base_path: str,
        logger: Any,              # PipelineLogger
        run_id: str,
        total_nodes: int,
        node_stats: list,         # mutated in place
        streaming: bool,
        # node_index_map maps node_id -> its index in execution_order (for logging)
        node_index_map: dict[str, int] | None = None,
        # ir_nodes_map maps node_id -> IRNode (for cacheable check)
        ir_nodes_map: dict[str, Any] | None = None,
        # registry for _resolve_capability
        registry: Any = None,
        # run_manager for artifact registration (Phase 4)
        run_manager: Any = None,
        # edge_conditions for conditional edge evaluation (NEW-4 fix)
        edge_conditions: dict[tuple[str, str, str, str], str | None] | None = None,
        # full graph IR for condition evaluation (NEW-4 fix)
        graph: Any = None,
    ) -> None:
        """Execute all nodes in a wave concurrently.

        A single ``ThreadPoolExecutor`` is created for the entire wave and
        shared across all sync-node tasks, avoiding the overhead of creating
        and destroying a thread pool per node.

        Assembles inputs from ``node_outputs`` (populated by prior waves),
        checks cache, executes, saves to cache (respecting ``cacheable`` flag),
        writes checkpoint, and emits ``node_start`` / ``node_end`` / ``node_error``
        events for each node.

        Req 1.2, 1.3, 1.4, 1.8, 1.10
        """
        loop = asyncio.get_running_loop()

        # Use the run-scoped shared pool (SCALE-3 fix — avoids per-wave pool
        # creation/teardown overhead). The pool is shut down by the orchestrator
        # after all waves complete via ParallelExecutor.shutdown().
        pool = self._get_pool()

        # NEW-5 fix: protect node_stats.append() with a lock so ordering is
        # deterministic and node_stats[-1] returns the correct last node.
        node_stats_lock = threading.Lock()

        tasks = [
            asyncio.create_task(
                self._run_node(
                    node_id=node_id,
                    graph_obj=graph_obj,
                    executors=executors,
                    node_outputs=node_outputs,
                    incoming=incoming,
                    pipeline_cfg=pipeline_cfg,
                    cache=cache,
                    checkpoint=checkpoint,
                    run_base_path=run_base_path,
                    logger=logger,
                    run_id=run_id,
                    total_nodes=total_nodes,
                    node_stats=node_stats,
                    node_stats_lock=node_stats_lock,
                    streaming=streaming,
                    node_index_map=node_index_map or {},
                    ir_nodes_map=ir_nodes_map or {},
                    registry=registry,
                    loop=loop,
                    pool=pool,
                    run_manager=run_manager,
                    edge_conditions=edge_conditions or {},
                )
            )
            for node_id in wave
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Re-raise the first exception found (Req 1.4)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def _run_node(
        self,
        node_id: str,
        graph_obj: Any,
        executors: dict,
        node_outputs: dict,
        incoming: dict,
        pipeline_cfg: Any,
        cache: Any,
        checkpoint: bool,
        run_base_path: str,
        logger: Any,
        run_id: str,
        total_nodes: int,
        node_stats: list,
        node_stats_lock: threading.Lock,
        streaming: bool,
        node_index_map: dict[str, int],
        ir_nodes_map: dict[str, Any],
        registry: Any,
        loop: asyncio.AbstractEventLoop,
        pool: ThreadPoolExecutor,
        run_manager: Any = None,
        edge_conditions: dict[tuple[str, str, str, str], str | None] | None = None,
    ) -> None:
        """Execute a single node: assemble inputs, check cache, execute, save cache/checkpoint.

        ``pool`` is the wave-scoped ThreadPoolExecutor shared by all nodes in
        the same wave — created once in ``run_wave`` rather than per node.
        """
        from app.core.checkpoint import _write_checkpoint
        from app.core.registry_runtime import resolve_capability as _resolve_capability

        node = graph_obj.get_node(node_id)
        exec_ = executors[node_id]
        node_type = type(node).__name__
        # Use -1 sentinel for unknown nodes so they don't appear as "node 0" in logs
        idx = node_index_map.get(node_id, -1)

        logger.node_start(node_type, idx, total_nodes=total_nodes)
        node_start_time = time.time()

        # ── Assemble inputs from upstream outputs ──────────────────────────────
        # NEW-4 fix: evaluate edge_conditions before assembling inputs, mirroring
        # the sequential path in orchestrator.py.
        # SA-O1 note: wave isolation guarantees that nodes in this wave only read
        # from node_outputs keys written by prior waves (fully settled before this
        # wave starts). Plain reads of node_outputs[src_id] are therefore safe
        # without a lock. The only write in this coroutine is
        # node_outputs[node_id] = outputs (a single __setitem__, GIL-safe).
        # The node_outputs_lock is held by run_wave but not needed here.
        _edge_conditions = edge_conditions or {}
        inputs: dict[str, Any] = {}
        for src_id, src_port, dst_port in incoming.get(node_id, []):
            condition = _edge_conditions.get((src_id, src_port, node_id, dst_port))
            if condition is not None:
                from app.core.conditions import evaluate_condition, ConditionEvaluationError
                src_outputs = node_outputs.get(src_id, {})
                try:
                    passes = evaluate_condition(condition, src_outputs)
                except ConditionEvaluationError:
                    passes = False
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

        # Fill unconnected optional ports with None
        for port_name, port in node.input_ports.items():
            if port_name not in inputs and not port.required:
                inputs[port_name] = None

        # ── Cache check — load() directly, treat None as miss (ARCH-9 fix) ──────
        cache_hit = False
        cache_key = None

        if cache is not None:
            node_cfg_dict = {}
            for spec in pipeline_cfg.nodes:
                if spec.node_id == node_id:
                    node_cfg_dict = spec.config
                    break
            # Use the canonical compute_key() on PipelineCache so the hashing
            # strategy is never duplicated between sequential and parallel paths.
            cache_key = cache.compute_key(node_type, node_cfg_dict, inputs)
            cached_result = cache.load(cache_key)
            if cached_result is not None:
                node_outputs[node_id] = cached_result
                cache_hit = True
                logger.info(f"[{idx}] {node_type} — cache hit")

        if not cache_hit:
            try:
                if streaming and node.is_streaming:
                    outputs = await _collect_stream_parallel(exec_, inputs)
                else:
                    # Offload sync node to the wave-scoped thread pool (shared,
                    # not created per-node — see run_wave for pool lifecycle).
                    outputs = await loop.run_in_executor(
                        pool, exec_.execute, inputs
                    )
            except Exception as exc:
                logger.node_error(node_type, idx, exc)
                raise

            node_outputs[node_id] = outputs

            # ── Save to cache (respecting cacheable flag) ──────────────────────
            if cache is not None and cache_key is not None:
                # Check cacheable flag via IRCapabilityMetadata (Req 1.8)
                cacheable = True
                ir_node = ir_nodes_map.get(node_id)
                if ir_node is not None and registry is not None:
                    try:
                        cap_meta = _resolve_capability(ir_node, registry)
                        cacheable = cap_meta.cacheable
                    except Exception:
                        cacheable = True  # default to cacheable on error

                if cacheable:
                    cache.save(cache_key, outputs)

        # ── Checkpoint ────────────────────────────────────────────────────────
        if checkpoint:
            _write_checkpoint(run_base_path, node_id, node_outputs[node_id], logger=logger)

        # ── Artifact registration (Phase 4 provenance) ────────────────────────
        if not cache_hit and run_manager is not None:
            from app.core.artifact_store import _infer_artifact_type
            _prior_artifact_ids: list[str] = []
            for _src_id, _src_port, _dst_port in incoming.get(node_id, []):
                # Use the public artifacts property (thread-safe snapshot)
                _prior_artifact_ids.extend(
                    r.artifact_id for r in run_manager.artifacts
                    if r.node_id == _src_id
                )
            for _port_name, _port_value in node_outputs[node_id].items():
                if _port_value is None:
                    continue
                _artifact_type = _infer_artifact_type(_port_value)
                try:
                    run_manager.register_artifact(
                        node_id=node_id,
                        node_type=node_type,
                        artifact_type=_artifact_type,
                        data=_port_value,
                        metadata={"port": _port_name},
                        input_artifact_ids=_prior_artifact_ids,
                    )
                except Exception as _art_exc:
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "Artifact registration failed for node '%s' port '%s': %s",
                        node_id, _port_name, _art_exc,
                    )

        node_duration = time.time() - node_start_time
        _node_outputs = node_outputs[node_id]
        _output_count = 0
        for _v in _node_outputs.values():
            if isinstance(_v, list):
                _output_count = len(_v)
                break
        logger.node_end(node_type, idx, node_duration, output_count=_output_count)

        # NEW-5 fix: protect node_stats.append() with a lock so ordering is
        # deterministic and node_stats[-1] returns the correct last completed node.
        with node_stats_lock:
            node_stats.append({
                "node_id": node_id,
                "node_type": node_type,
                "node_index": idx,
                "duration_s": round(node_duration, 4),
            })

