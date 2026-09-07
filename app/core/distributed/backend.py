# app/core/distributed/backend.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   DistributedRuntimeBackend — wave scheduler that runs local
                  nodes via NodeExecutor and remote nodes via the job queue
                  with artifact URI refs (no full-graph local rematerialize).
Owns:             DistributedBackend, IR wave helpers, loopback worker helpers.
Public Surface:   DistributedBackend, run_loopback_worker_once,
                  start_loopback_worker_thread, compute_ir_waves.
Must NOT:         Import from app.domain or app.api at module level.
Dependencies:     runtime_backend, distributed.{registry,queue,placement,
                  models,transfer}, ir.models, planner helpers, node_executor,
                  registry_runtime, stdlib.
Reason To Change: Parallel within-wave execution, conditional edges, or
                  cancel/lease reclaim.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from app.core.runtime_backend import LocalPythonBackend, RuntimeBackend

if TYPE_CHECKING:
    from app.core.ir.models import GraphIR
    from app.core.run_journal import RunManager

log = logging.getLogger(__name__)


def compute_ir_waves(graph: "GraphIR") -> list[list[str]]:
    """Compute parallel execution waves from GraphIR edges (no node instantiation).

    Mirrors ``PipelineGraph._compute_waves`` / Kahn topo so distributed
    scheduling can place remote node types that are not registered on the
    control plane.
    """
    from collections import deque

    node_ids = [n.id for n in graph.nodes]
    if not node_ids:
        return []
    id_set = set(node_ids)
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    adjacency: dict[str, list[str]] = defaultdict(list)
    predecessors: dict[str, list[str]] = {nid: [] for nid in node_ids}

    for edge in graph.edges:
        if edge.src_id not in id_set or edge.dst_id not in id_set:
            raise RuntimeError(
                f"Edge {edge.src_id!r}→{edge.dst_id!r} references unknown node"
            )
        adjacency[edge.src_id].append(edge.dst_id)
        predecessors[edge.dst_id].append(edge.src_id)
        in_degree[edge.dst_id] += 1

    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for successor in adjacency[nid]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)

    if len(order) != len(node_ids):
        missing = id_set - set(order)
        raise RuntimeError(
            f"Graph contains a cycle — topological sort failed. "
            f"Nodes not reached: {missing}"
        )

    level: dict[str, int] = {}
    for node_id in order:
        preds = predecessors[node_id]
        level[node_id] = max((level[p] + 1 for p in preds), default=0)

    waves_dict: dict[int, list[str]] = defaultdict(list)
    for nid, lv in level.items():
        waves_dict[lv].append(nid)
    max_level = max(level.values())
    return [waves_dict[i] for i in range(max_level + 1)]


def _assemble_inputs(
    node_id: str,
    *,
    incoming: dict[str, list[tuple[str, str, str]]],
    node_outputs: dict[str, dict[str, Any]],
    input_overrides: dict | None,
) -> dict[str, Any]:
    """Wire upstream outputs → inputs for *node_id* (unconditional edges).

    Conditional edges are ignored for P1 (documented in DISTRIBUTED_EXECUTION.md);
    only ``condition is None`` / absent edges are supported here. Overrides win.
    """
    inputs: dict[str, Any] = {}
    if input_overrides and node_id in input_overrides:
        for port, value in (input_overrides[node_id] or {}).items():
            inputs[port] = value

    for src_id, src_port, dst_port in incoming.get(node_id, []):
        if dst_port in inputs:
            continue
        upstream = node_outputs.get(src_id, {})
        if src_port in upstream:
            inputs[dst_port] = upstream[src_port]
    return inputs


def _run_local_node(
    *,
    node_id: str,
    node_type: str,
    config: dict[str, Any],
    seed: int,
    inputs: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Execute one node on the control plane via NodeExecutor."""
    from app.core.node_executor import NodeExecutor
    from app.core.registry_runtime import get_registry
    from app.core.write_paths import ensure_node_write_dirs

    registry = get_registry()
    node_class = registry.get_class(node_type)
    if node_class is None:
        raise RuntimeError(
            f"Local node {node_id!r}: type {node_type!r} is not registered"
        )
    node = node_class(config=dict(config or {}), seed=seed)
    ensure_node_write_dirs(node)
    executor = NodeExecutor(node, run_id=run_id)
    executor.setup()
    try:
        return executor.execute(inputs)
    finally:
        try:
            executor.teardown()
        except Exception:  # noqa: BLE001
            pass


class DistributedBackend(RuntimeBackend):
    """Wave-scheduled distributed backend with all-local short-circuit.

    Behaviour:
    * If every node resolves to ``\"local\"`` (or nothing requires remote),
      delegate entirely to :class:`LocalPythonBackend`.
    * Otherwise run a wave scheduler: local nodes via ``NodeExecutor``,
      remote nodes via job queue + artifact URI refs. Never rematerializes
      the whole graph through LocalPythonBackend after remotes succeed.
    """

    def __init__(self) -> None:
        self._local = LocalPythonBackend()
        self.last_node_workers: dict[str, str] = {}

    @property
    def backend_id(self) -> str:
        return "distributed"

    def execute(
        self,
        graph: "GraphIR",
        *,
        logger: Any = None,
        use_cache: bool = True,
        checkpoint: bool = False,
        streaming: bool = False,
        parallel: bool = False,
        max_workers: int | None = None,
        resume_run_id: str | None = None,
        include_nodes: list[str] | None = None,
        exclude_nodes: list[str] | None = None,
        input_overrides: dict | None = None,
        event_driven: bool = False,
        observer: Any = None,
        run_manager: "RunManager | None" = None,
    ) -> dict[str, Any]:
        from app.core.distributed.placement import placement_needs_remote, resolve_worker
        from app.core.distributed.registry import get_worker_registry
        from app.core.registry_runtime import get_registry, resolve_capability

        registry = get_worker_registry()
        alive = registry.alive_workers()
        import warnings

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                node_registry = get_registry()
        except Exception:
            node_registry = None

        placements: dict[str, str | None] = {}
        needs_remote = False
        for node in graph.nodes:
            cap = getattr(node, "capability_metadata", None)
            if node_registry is not None:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        cap = resolve_capability(node, node_registry)
                except Exception:
                    pass
            target = resolve_worker(
                placement=getattr(node, "placement", None),
                capability=cap,
                workers=alive,
                node_type=node.node_type,
            )
            placements[node.id] = target
            if target not in (None, "local"):
                needs_remote = True
            elif target is None:
                if placement_needs_remote(
                    getattr(node, "placement", None), capability=cap
                ):
                    raise RuntimeError(
                        f"No eligible worker for node {node.id!r} "
                        f"(type={node.node_type!r}, placement={node.placement!r})"
                    )

        if not needs_remote:
            log.debug(
                "DistributedBackend: all nodes local — delegating to LocalPythonBackend"
            )
            return self._local.execute(
                graph,
                logger=logger,
                use_cache=use_cache,
                checkpoint=checkpoint,
                streaming=streaming,
                parallel=parallel,
                max_workers=max_workers,
                resume_run_id=resume_run_id,
                include_nodes=include_nodes,
                exclude_nodes=exclude_nodes,
                input_overrides=input_overrides,
                event_driven=event_driven,
                observer=observer,
                run_manager=run_manager,
            )

        return self._execute_with_jobs(
            graph,
            placements=placements,
            logger=logger,
            input_overrides=input_overrides,
            include_nodes=include_nodes,
            exclude_nodes=exclude_nodes,
            run_manager=run_manager,
        )

    def _execute_with_jobs(
        self,
        graph: "GraphIR",
        *,
        placements: dict[str, str | None],
        logger: Any,
        input_overrides: dict | None,
        include_nodes: list[str] | None,
        exclude_nodes: list[str] | None,
        run_manager: "RunManager | None",
    ) -> dict[str, Any]:
        """Wave scheduler: local NodeExecutor + remote jobs with artifact refs."""
        from app.core.distributed.models import NodeJob
        from app.core.distributed.queue import get_job_queue
        from app.core.distributed.transfer import get_port_value, put_port_value

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

        queue = get_job_queue()
        run_id = getattr(run_manager, "run_id", None) or str(uuid.uuid4())
        seed = int(getattr(getattr(graph, "metadata", None), "seed", 0) or 0)
        nodes_by_id = {n.id: n for n in graph.nodes}

        incoming: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for edge in graph.edges:
            # P1: skip conditional edges (support unconditional wiring only).
            if getattr(edge, "condition", None):
                log.warning(
                    "DistributedBackend P1 ignores conditional edge %s.%s→%s.%s "
                    "(condition=%r)",
                    edge.src_id,
                    edge.src_port,
                    edge.dst_id,
                    edge.dst_port,
                    edge.condition,
                )
                continue
            incoming[edge.dst_id].append((edge.src_id, edge.src_port, edge.dst_port))

        waves = compute_ir_waves(graph)
        node_outputs: dict[str, dict[str, Any]] = {}
        node_workers: dict[str, str] = {}
        timeout_s = float(os.environ.get("GRAPHYN_DISTRIBUTED_JOB_TIMEOUT", "120"))
        deadline = time.monotonic() + timeout_s

        execution_order = [nid for wave in waves for nid in wave]

        for wave_idx, wave in enumerate(waves):
            log.info("DistributedBackend wave %s: %s", wave_idx, wave)
            for node_id in wave:
                if node_id not in active_nodes:
                    # Passthrough wiring for excluded nodes.
                    passthrough: dict[str, Any] = {}
                    for src_id, src_port, dst_port in incoming.get(node_id, []):
                        upstream = node_outputs.get(src_id, {})
                        passthrough[dst_port] = upstream.get(src_port)
                    node_outputs[node_id] = passthrough
                    continue

                ir_node = nodes_by_id[node_id]
                inputs = _assemble_inputs(
                    node_id,
                    incoming=incoming,
                    node_outputs=node_outputs,
                    input_overrides=input_overrides,
                )
                target = placements.get(node_id)

                if target in (None, "local"):
                    outputs = _run_local_node(
                        node_id=node_id,
                        node_type=ir_node.node_type,
                        config=dict(ir_node.config) if ir_node.config else {},
                        seed=seed,
                        inputs=inputs,
                        run_id=run_id,
                    )
                    node_outputs[node_id] = outputs or {}
                    node_workers[node_id] = "local"
                    continue

                # Remote path: serialize inputs → enqueue → wait → hydrate.
                input_refs: dict[str, str] = {}
                for port, value in inputs.items():
                    input_refs[port] = put_port_value(value)

                placement = getattr(ir_node, "placement", None)
                tags = list(placement.tags) if placement and placement.tags else []
                job = NodeJob(
                    job_id=str(uuid.uuid4()),
                    run_id=run_id,
                    node_id=node_id,
                    node_type=ir_node.node_type,
                    config=dict(ir_node.config) if ir_node.config else {},
                    seed=seed,
                    input_refs=input_refs,
                    placement=placement,
                    require_gpu=bool(placement.require_gpu) if placement else False,
                    min_vram_mib=placement.min_vram_mib if placement else None,
                    tags=tags,
                    pool=placement.pool if placement else None,
                )
                stored = queue.enqueue(job)
                log.info(
                    "Enqueued remote job %s for node %s → target %s refs=%s",
                    stored.job_id,
                    node_id,
                    target,
                    list(input_refs),
                )

                remaining = max(0.0, deadline - time.monotonic())
                result = queue.wait_for_result(stored.job_id, timeout_s=remaining)
                if result is None:
                    raise TimeoutError(
                        f"Timed out waiting for distributed job {stored.job_id} "
                        f"(node={node_id})"
                    )
                if result.status != "succeeded":
                    raise RuntimeError(
                        f"Distributed job {stored.job_id} (node={node_id}) "
                        f"ended with status={result.status}: {result.error}"
                    )

                outputs = {}
                if result.output_refs:
                    for port, uri in result.output_refs.items():
                        outputs[port] = get_port_value(uri)
                else:
                    # Soft fallback: embedded debug events (must not be required).
                    for ev in result.events or []:
                        if isinstance(ev, dict) and ev.get("type") == "outputs":
                            data = ev.get("data")
                            if isinstance(data, dict):
                                outputs = data
                                break
                    if not outputs and result.output_refs == {}:
                        outputs = {}

                node_outputs[node_id] = outputs
                if result.worker_id:
                    node_workers[node_id] = result.worker_id
                else:
                    node_workers[node_id] = str(target)

                if run_manager is not None:
                    try:
                        write_field = getattr(run_manager, "_write_meta_field", None)
                        if callable(write_field):
                            write_field(
                                "distributed_node_workers", dict(node_workers)
                            )
                    except Exception:
                        pass

                if logger is not None:
                    try:
                        logger.info(
                            "distributed_node_done",
                            node_id=node_id,
                            worker_id=node_workers[node_id],
                        )
                    except Exception:
                        pass

        self.last_node_workers = dict(node_workers)
        if run_manager is not None:
            try:
                write_field = getattr(run_manager, "_write_meta_field", None)
                if callable(write_field):
                    write_field("distributed_node_workers", dict(node_workers))
                else:
                    meta = getattr(run_manager, "metadata", None)
                    if isinstance(meta, dict):
                        meta["distributed_node_workers"] = dict(node_workers)
            except Exception:
                pass

        if not execution_order:
            return {}
        last_id = execution_order[-1]
        return node_outputs.get(last_id, {})


def run_loopback_worker_once(
    worker_id: str = "loopback",
    *,
    execute_fn: Any | None = None,
) -> bool:
    """Claim at most one job and complete it (in-process test / --in-process).

    Default path hydrates ``input_refs`` via :mod:`transfer`, runs a registered
    node (or ``execute_fn``), uploads outputs as blobs, and completes with
    real ``output_refs``.

    ``execute_fn`` signatures accepted:
    * ``execute_fn(job) -> dict`` (legacy; values uploaded as blobs)
    * ``execute_fn(job, inputs) -> dict``
    """
    from app.core.distributed.models import JobResult
    from app.core.distributed.queue import get_job_queue
    from app.core.distributed.registry import get_worker_registry
    from app.core.distributed.transfer import get_port_value, put_port_value

    registry = get_worker_registry()
    worker = registry.get(worker_id)
    if worker is None:
        raise KeyError(f"loopback worker {worker_id!r} is not registered")

    queue = get_job_queue()
    job = queue.claim(worker)
    if job is None:
        return False

    # Hard refuse missing plugin (claim should already skip; belt-and-suspenders).
    plugins = list(worker.plugins or [])
    if plugins and job.node_type not in plugins:
        queue.complete(
            JobResult(
                job_id=job.job_id,
                status="failed",
                error=(
                    f"Worker {worker_id!r} refuses job: node_type "
                    f"{job.node_type!r} not in advertised plugins {plugins}"
                ),
                worker_id=worker_id,
                duration_s=0.0,
            )
        )
        return True

    if queue.is_cancelled(job.job_id):
        return True

    queue.mark_running(job.job_id)
    started = time.monotonic()
    error = None
    outputs: dict[str, Any] = {}
    status = "succeeded"
    output_refs: dict[str, str] = {}
    try:
        if queue.is_cancelled(job.job_id):
            status = "cancelled"
            error = "cancelled by control plane"
            raise RuntimeError(error)
        inputs: dict[str, Any] = {}
        for port, uri in (job.input_refs or {}).items():
            inputs[port] = get_port_value(uri)

        if execute_fn is not None:
            try:
                outputs = execute_fn(job, inputs) or {}
            except TypeError:
                outputs = execute_fn(job) or {}
        else:
            outputs = _run_local_node(
                node_id=job.node_id,
                node_type=job.node_type,
                config=dict(job.config or {}),
                seed=int(job.seed or 0),
                inputs=inputs,
                run_id=job.run_id,
            )

        for port, value in (outputs or {}).items():
            output_refs[port] = put_port_value(value)
        if queue.is_cancelled(job.job_id):
            status = "cancelled"
            error = "cancelled by control plane"
            output_refs = {}
    except Exception as exc:  # noqa: BLE001 — surface to JobResult
        if queue.is_cancelled(job.job_id) or status == "cancelled":
            status = "cancelled"
            error = "cancelled by control plane"
        else:
            status = "failed"
            error = str(exc)

    # If control cancelled while we ran, prefer cancelled over succeeded/failed.
    if queue.is_cancelled(job.job_id):
        status = "cancelled"
        error = "cancelled by control plane"
        # cancel() already set a result — only complete if not terminal.
        existing = queue.get(job.job_id)
        if existing is not None and existing.status == "cancelled":
            return True

    try:
        queue.complete(
            JobResult(
                job_id=job.job_id,
                status=status,  # type: ignore[arg-type]
                output_refs=output_refs if status == "succeeded" else {},
                events=[],
                error=error,
                worker_id=worker_id,
                duration_s=time.monotonic() - started,
            )
        )
    except ValueError:
        # Already terminal (e.g. cancelled by control) — ok.
        pass
    return True


def start_loopback_worker_thread(
    worker_id: str = "loopback",
    *,
    poll_interval_s: float = 0.05,
    stop_event: threading.Event | None = None,
    execute_fn: Any | None = None,
) -> tuple[threading.Thread, threading.Event]:
    """Background thread that claims/completes jobs until ``stop_event`` is set."""
    stop = stop_event or threading.Event()

    def _run() -> None:
        while not stop.is_set():
            try:
                claimed = run_loopback_worker_once(
                    worker_id, execute_fn=execute_fn
                )
            except KeyError:
                break
            if not claimed:
                stop.wait(poll_interval_s)

    t = threading.Thread(
        target=_run, name=f"graphyn-loopback-{worker_id}", daemon=True
    )
    t.start()
    return t, stop
